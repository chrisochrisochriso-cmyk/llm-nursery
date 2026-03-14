"""
paperknight AI - Coordinator Service

FastAPI service that bridges the pk CLI with LFM2-24B inference.

- Queries ChromaDB RAG BEFORE every inference request
- Injects relevant context into system prompt
- Selects system prompt based on user profile (chriso vs johno)
- Routes to Ollama node1 (primary) or node2 (failover)
- Streams responses back to CLI
- Internal API only - never exposed outside home LAN

No secrets required. No external API calls. Zero cloud.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import base64

import chromadb
import httpx
import numpy as np
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pk-coordinator")

# ---------------------------------------------------------------------------
# Config (all via environment variables)
# ---------------------------------------------------------------------------
OLLAMA_URL      = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL_NAME      = os.environ.get("MODEL_NAME", "llama3.1:8b")
CHROMADB_URL    = os.environ.get("CHROMADB_URL", "http://localhost:8000")
RAG_TOP_K       = int(os.environ.get("RAG_TOP_K", "5"))
HISTORY_PATH    = Path(os.environ.get("HISTORY_PATH", "/storage/history"))
INFERENCE_MODE  = os.environ.get("INFERENCE_MODE", "ollama")  # ollama | pipeline

SHARD_URLS = {
    0: os.environ.get("SHARD_0_URL", "http://shard-0:8080"),
    1: os.environ.get("SHARD_1_URL", "http://shard-1:8080"),
    2: os.environ.get("SHARD_2_URL", "http://shard-2:8080"),
    3: os.environ.get("SHARD_3_URL", "http://shard-3:8080"),
}

# Qwen2.5 EOS token IDs
_LLAMA_EOS_IDS = {151645, 151643}  # <|im_end|> and <|endoftext|>

# Embedding model - loaded once at startup, stays in memory (~200MB)
_embedder: Optional[SentenceTransformer] = None
CHROMA_COLLECTION = "paperknight"
_chroma_collection = None

NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# ---------------------------------------------------------------------------
# System prompts per user profile
# ---------------------------------------------------------------------------
SYSTEM_PROMPTS = {
    "chriso": (
        "You are a senior security engineer and coding assistant for paperknight Threat Labs. "
        "Stack: C++, Python, Go, Kubernetes, BGP security, MITM proxies, vulnerability scanners, "
        "DaemonSet architectures. "
        "Always lead with security implications. Be direct, skip filler. "
        "Flag CRITICAL security issues immediately with severity. "
        "All code and context shared with you is sensitive security research."
    ),
    "health": (
        "You are a friendly health companion assistant. "
        "Your two jobs are: (1) help the user log and track their symptoms clearly and kindly, "
        "and (2) translate medical documents, doctor's notes, and clinical jargon into plain, "
        "easy-to-understand English that anyone can follow. "
        "Always be warm, clear, and reassuring. Never diagnose or prescribe — if something sounds "
        "serious, gently encourage them to speak with their doctor. "
        "When logging symptoms, ask follow-up questions to get useful detail: when did it start, "
        "how severe, any changes, what makes it better or worse. "
        "When translating medical text, explain every term in plain language and summarise what "
        "the document is telling the patient in simple bullet points."
    ),
    "default": (
        "You are paperknight AI, a private AI assistant. "
        "Be helpful, clear, and direct."
    ),
}

REVIEW_SUFFIX = (
    "\n\nReview this code. Lead with security vulnerabilities (CRITICAL/HIGH/MEDIUM/LOW). "
    "Then flag bugs, logic errors, and performance issues. Be specific - include line references."
)

SCAN_SUFFIX = (
    "\n\nSecurity scan this. Rate each finding: CRITICAL / HIGH / MEDIUM / LOW. "
    "For each: what it is, why it matters, how to fix it. Be direct."
)

# ---------------------------------------------------------------------------
# RAG: query ChromaDB for relevant context
# ---------------------------------------------------------------------------

async def shard_embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts using shard-0 hidden states (Qwen2.5-3B quality).
    Mean-pools hidden states [1, seq_len, 2048] -> [2048] float32 vector.
    Falls back to local all-MiniLM if shard-0 is unavailable.
    """
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for text in texts:
            try:
                r = await client.post(
                    f"{SHARD_URLS[0]}/embed",
                    json={"text": text, "temperature": 0.0},
                )
                r.raise_for_status()
                hs = r.json()["hidden_states"]
                raw = base64.b64decode(hs["b64"])
                arr = np.frombuffer(raw, dtype=np.float16).reshape(hs["shape"])
                # Mean pool across sequence dimension → [hidden_size]
                vec = arr[0].mean(axis=0).astype(np.float32)
                results.append(vec.tolist())
            except Exception as e:
                logger.warning("Shard embed failed, falling back to local: %s", e)
                fallback = await asyncio.to_thread(embed, [text])
                results.append(fallback[0])
    return results


async def query_rag(query: str) -> Optional[str]:
    """Query ChromaDB for relevant documents. Returns injected context string or None."""
    try:
        embeddings = await shard_embed_texts([query])
        collection = await asyncio.to_thread(get_chroma_collection)
        result = await asyncio.to_thread(
            collection.query,
            query_embeddings=embeddings,
            n_results=RAG_TOP_K,
            include=["documents", "metadatas", "distances"],
        )

        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        if not documents:
            return None

        relevant = [
            (doc, meta, dist)
            for doc, meta, dist in zip(documents, metadatas, distances)
            if dist < 1.5
        ]

        if not relevant:
            return None

        context_parts = ["[CONTEXT FROM KNOWLEDGE BASE]"]
        for doc, meta, _ in relevant:
            source = meta.get("source", "unknown") if meta else "unknown"
            context_parts.append(f"Source: {source}\n{doc}")

        return "\n\n".join(context_parts) + "\n[END CONTEXT]"

    except Exception as e:
        logger.warning("RAG query failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Ollama: route to available node
# ---------------------------------------------------------------------------

async def get_available_ollama() -> str:
    """Return Ollama URL if healthy, raise 503 otherwise."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                return OLLAMA_URL
    except Exception:
        pass
    raise HTTPException(status_code=503, detail="Ollama is not available")


async def stream_ollama(
    ollama_url: str,
    system_prompt: str,
    user_message: str,
    num_predict: int = 512,
) -> AsyncIterator[str]:
    """Stream response from Ollama, yielding chunks as they arrive."""
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": True,
        "options": {
            "temperature": 0.7,
            "num_predict": num_predict,
            "num_ctx": 4096,
        },
    }

    async with httpx.AsyncClient(timeout=600.0) as client:
        async with client.stream("POST", f"{ollama_url}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue


def _llama_chat_prompt(system_prompt: str, user_message: str) -> str:
    """Build Qwen2.5 ChatML format prompt string."""
    return (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{user_message}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


async def _check_shards() -> bool:
    """Return True if all 4 shards are healthy."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for url in SHARD_URLS.values():
                r = await client.get(f"{url}/health")
                if r.status_code != 200:
                    return False
        return True
    except Exception:
        return False


async def stream_pipeline(
    system_prompt: str,
    user_message: str,
    max_new_tokens: int = 64,
) -> AsyncIterator[str]:
    """Stream tokens through the 4-shard pipeline."""
    prompt = _llama_chat_prompt(system_prompt, user_message)
    generated_ids: list[int] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for _ in range(max_new_tokens):
            # Reconstruct full text for this step
            current_text = prompt
            if generated_ids:
                dec = await client.post(
                    f"{SHARD_URLS[0]}/decode", json={"token_ids": generated_ids}
                )
                dec.raise_for_status()
                current_text += dec.json()["text"]

            # Shard 0: tokenise + embed
            r = await client.post(
                f"{SHARD_URLS[0]}/embed",
                json={"text": current_text, "temperature": 0.7},
            )
            r.raise_for_status()
            data = r.json()

            # Shards 1-2: hidden state passthrough
            for sid in (1, 2):
                r = await client.post(
                    f"{SHARD_URLS[sid]}/forward",
                    json={
                        "hidden_states": data["hidden_states"],
                        "seq_len": data["seq_len"],
                        "temperature": 0.7,
                    },
                )
                r.raise_for_status()
                data = r.json()

            # Shard 3: project to vocab → next token
            r = await client.post(
                f"{SHARD_URLS[3]}/forward",
                json={
                    "hidden_states": data["hidden_states"],
                    "seq_len": data["seq_len"],
                    "temperature": 0.7,
                },
            )
            r.raise_for_status()
            next_token_id = r.json()["next_token_id"]

            if next_token_id in _LLAMA_EOS_IDS:
                break

            generated_ids.append(next_token_id)

            # Decode just the new token and yield it
            dec = await client.post(
                f"{SHARD_URLS[0]}/decode", json={"token_ids": [next_token_id]}
            )
            dec.raise_for_status()
            yield dec.json()["text"]


async def generate(
    system_prompt: str,
    user_message: str,
    stream: bool = True,
    num_predict: int = 512,
) -> str | AsyncIterator[str]:
    """Generate a response, routing to pipeline shards or Ollama."""
    use_pipeline = INFERENCE_MODE == "pipeline" and await _check_shards()

    if use_pipeline:
        logger.info("Routing to pipeline shards")
        if stream:
            return stream_pipeline(system_prompt, user_message)
        full = []
        async for chunk in stream_pipeline(system_prompt, user_message):
            full.append(chunk)
        return "".join(full)

    # Ollama fallback
    logger.info("Routing to Ollama (%s)", MODEL_NAME)
    ollama_url = await get_available_ollama()
    if stream:
        return stream_ollama(ollama_url, system_prompt, user_message, num_predict=num_predict)
    full = []
    async for chunk in stream_ollama(ollama_url, system_prompt, user_message, num_predict=num_predict):
        full.append(chunk)
    return "".join(full)


# ---------------------------------------------------------------------------
# History logging
# ---------------------------------------------------------------------------

def log_history(profile: str, command: str, query: str, response_preview: str) -> None:
    """Append query to history file. Non-blocking best-effort."""
    try:
        HISTORY_PATH.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        entry = {
            "ts": datetime.now().isoformat(),
            "profile": profile,
            "command": command,
            "query": query[:500],
            "response_preview": response_preview[:200],
        }
        with open(HISTORY_PATH / f"{today}.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning("History write failed: %s", e)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        logger.info("Loading embedding model (all-MiniLM-L6-v2)...")
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Embedding model ready")
    return _embedder


def embed(texts: list[str]) -> list[list[float]]:
    return get_embedder().encode(texts, show_progress_bar=False).tolist()


def get_chroma_collection():
    """Get or create the ChromaDB collection using the Python client."""
    global _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    host = CHROMADB_URL.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(CHROMADB_URL.split(":")[-1]) if ":" in CHROMADB_URL else 8000
    client = chromadb.HttpClient(host=host, port=port)
    _chroma_collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("ChromaDB collection ready: %s", CHROMA_COLLECTION)
    return _chroma_collection


async def add_to_chroma(
    documents: list[str],
    metadatas: list[dict],
    ids: list[str],
) -> int:
    """Embed and store documents in ChromaDB. Returns number added."""
    embeddings = await shard_embed_texts(documents)
    try:
        collection = await asyncio.to_thread(get_chroma_collection)
        await asyncio.to_thread(
            collection.add,
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ChromaDB add failed: {e}")
    return len(documents)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks for better RAG recall."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return [c for c in chunks if len(c.strip()) > 50]


async def warmup_model():
    """Ping Ollama on startup to load the model into RAM."""
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            logger.info("Warming up model %s (this may take a minute)...", MODEL_NAME)
            await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": MODEL_NAME, "prompt": "hi", "stream": False},
            )
            logger.info("Model warm and ready")
    except Exception as e:
        logger.warning("Warmup failed (will retry on first request): %s", e)


async def keepalive_loop():
    """Ping Ollama every 10 minutes so the model stays loaded in RAM."""
    while True:
        await asyncio.sleep(600)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={"model": MODEL_NAME, "prompt": "", "stream": False, "keep_alive": "1h"},
                )
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    HISTORY_PATH.mkdir(parents=True, exist_ok=True)
    # Pre-load embedding model so first add doesn't pause inference
    await asyncio.to_thread(get_embedder)
    await asyncio.to_thread(get_chroma_collection)
    # Warm up the LLM so first request is instant
    asyncio.create_task(warmup_model())
    # Keep model hot in RAM between requests
    asyncio.create_task(keepalive_loop())
    logger.info("pk-coordinator started (model=%s)", MODEL_NAME)
    yield


app = FastAPI(title="paperknight AI Coordinator", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

WEB_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PaperKnight Health Companion</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f0f4f8;
    height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .container {
    width: 100%;
    max-width: 720px;
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: #fff;
    box-shadow: 0 2px 24px rgba(0,0,0,0.08);
  }
  .header {
    padding: 18px 24px;
    background: #1a6fa8;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .header h1 { font-size: 1.2rem; font-weight: 600; }
  .header .sub { font-size: 0.8rem; opacity: 0.8; margin-top: 2px; }
  .status-dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: #4ade80; flex-shrink: 0;
  }
  .status-dot.offline { background: #f87171; }
  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .bubble {
    max-width: 85%;
    padding: 12px 16px;
    border-radius: 16px;
    line-height: 1.55;
    font-size: 0.95rem;
    white-space: pre-wrap;
    word-wrap: break-word;
  }
  .bubble.user {
    align-self: flex-end;
    background: #1a6fa8;
    color: #fff;
    border-bottom-right-radius: 4px;
  }
  .bubble.assistant {
    align-self: flex-start;
    background: #f0f4f8;
    color: #1a202c;
    border-bottom-left-radius: 4px;
  }
  .bubble.thinking {
    align-self: flex-start;
    background: #f0f4f8;
    color: #718096;
    font-style: italic;
    font-size: 0.88rem;
  }
  .input-bar {
    padding: 16px 24px;
    border-top: 1px solid #e2e8f0;
    display: flex;
    gap: 10px;
    align-items: flex-end;
  }
  textarea {
    flex: 1;
    border: 1.5px solid #cbd5e0;
    border-radius: 12px;
    padding: 10px 14px;
    font-size: 0.95rem;
    font-family: inherit;
    resize: none;
    min-height: 44px;
    max-height: 120px;
    outline: none;
    transition: border-color 0.2s;
  }
  textarea:focus { border-color: #1a6fa8; }
  button {
    border: none;
    border-radius: 12px;
    padding: 10px 16px;
    cursor: pointer;
    font-size: 1.1rem;
    transition: background 0.2s, transform 0.1s;
  }
  button:active { transform: scale(0.95); }
  #sendBtn {
    background: #1a6fa8;
    color: #fff;
    min-width: 48px;
  }
  #sendBtn:hover { background: #155d8f; }
  #sendBtn:disabled { background: #a0aec0; cursor: not-allowed; }
  #voiceBtn {
    background: #f0f4f8;
    color: #4a5568;
    min-width: 48px;
  }
  #voiceBtn:hover { background: #e2e8f0; }
  #voiceBtn.recording { background: #fed7d7; color: #c53030; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
  .speak-btn {
    background: none;
    border: none;
    font-size: 0.8rem;
    color: #a0aec0;
    cursor: pointer;
    padding: 2px 6px;
    margin-top: 4px;
  }
  .speak-btn:hover { color: #1a6fa8; }
  .no-voice { font-size: 0.75rem; color: #a0aec0; text-align: center; padding: 4px 0; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="status-dot" id="statusDot"></div>
    <div>
      <h1>PaperKnight Health Companion</h1>
      <div class="sub">Private AI &bull; Your information stays on your device</div>
    </div>
  </div>

  <div class="messages" id="messages">
    <div class="bubble assistant">
      Hello! I'm your health companion. I can help you log and track your symptoms, or translate medical documents and doctor's notes into plain English.<br><br>
      What would you like to do today?
    </div>
  </div>

  <div class="input-bar">
    <textarea id="input" placeholder="Type your message, or use the mic..." rows="1"
      onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
    <button id="voiceBtn" title="Hold to speak" onclick="toggleVoice()">🎤</button>
    <button id="sendBtn" onclick="send()">➤</button>
  </div>
</div>

<script>
const messagesEl = document.getElementById('messages');
const inputEl    = document.getElementById('input');
const sendBtn    = document.getElementById('sendBtn');
const voiceBtn   = document.getElementById('voiceBtn');
const statusDot  = document.getElementById('statusDot');

let speaking = false;
let recognition = null;
let synth = window.speechSynthesis;

// Check status on load
fetch('/health').then(r => {
  statusDot.classList.toggle('offline', !r.ok);
}).catch(() => statusDot.classList.add('offline'));

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
}

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addBubble(role, text) {
  const div = document.createElement('div');
  div.className = 'bubble ' + role;
  div.textContent = text;
  messagesEl.appendChild(div);
  scrollBottom();
  return div;
}

function speak(text) {
  if (!synth) return;
  synth.cancel();
  const utt = new SpeechSynthesisUtterance(text);
  utt.rate = 0.95;
  utt.pitch = 1;
  synth.speak(utt);
}

async function send() {
  const text = inputEl.value.trim();
  if (!text) return;

  addBubble('user', text);
  inputEl.value = '';
  inputEl.style.height = 'auto';
  sendBtn.disabled = true;

  const thinking = addBubble('thinking', 'Thinking...');

  try {
    const resp = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, profile: 'health', stream: true }),
    });

    thinking.remove();

    if (!resp.ok) { addBubble('assistant', 'Sorry, something went wrong. Please try again.'); return; }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    const bubble = addBubble('assistant', '');
    let fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      fullText += chunk;
      bubble.textContent = fullText;
      scrollBottom();
    }

    // Speak the response
    speak(fullText);

    // Add small speak-again button
    const speakBtn = document.createElement('button');
    speakBtn.className = 'speak-btn';
    speakBtn.textContent = '🔊 Read aloud';
    speakBtn.onclick = () => speak(fullText);
    bubble.appendChild(speakBtn);

  } catch (e) {
    thinking.remove();
    addBubble('assistant', 'Connection error. Is PaperKnight running?');
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

// Voice input
function toggleVoice() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    alert('Voice input is not supported in this browser. Try Chrome or Edge.');
    return;
  }

  if (speaking) {
    recognition && recognition.stop();
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.lang = 'en-GB';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    speaking = true;
    voiceBtn.classList.add('recording');
    voiceBtn.textContent = '⏹';
  };
  recognition.onresult = (e) => {
    inputEl.value = e.results[0][0].transcript;
    autoResize(inputEl);
    send();
  };
  recognition.onerror = () => {};
  recognition.onend = () => {
    speaking = false;
    voiceBtn.classList.remove('recording');
    voiceBtn.textContent = '🎤';
  };

  recognition.start();
}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def web_ui():
    """Serve the health companion web UI."""
    return WEB_UI_HTML


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class InferRequest(BaseModel):
    message: str
    profile: str = "default"   # chriso | johno | default
    stream: bool = True


class ReviewRequest(BaseModel):
    content: str               # file content to review
    filename: str = ""
    profile: str = "default"
    stream: bool = True


class ScanRequest(BaseModel):
    content: str               # content to scan
    filename: str = ""
    profile: str = "default"
    stream: bool = True


class StatusResponse(BaseModel):
    status: str
    model: str
    ollama: str
    rag: str
    history_entries: int


class AddDocRequest(BaseModel):
    content: str
    source: str                # filename, URL, or CVE ID
    doc_type: str = "text"     # text | code | cve | url


class AddUrlRequest(BaseModel):
    url: str


class AddCveRequest(BaseModel):
    cve_id: str                # e.g. CVE-2024-1234


class SearchRequest(BaseModel):
    query: str
    n_results: int = 5


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "rag": CHROMADB_URL,
    }


@app.get("/status")
async def status() -> dict:
    """Full cluster health - used by `pk status` dashboard."""
    results = {"model": MODEL_NAME, "status": "ok"}

    # Check Ollama
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                tags = r.json().get("models", [])
                model_short = MODEL_NAME.split(":")[0]
                has_model = any(model_short in m.get("name", "") for m in tags)
                results["ollama"] = "ready" if has_model else "no-model"
            else:
                results["ollama"] = "degraded"
    except Exception:
        results["ollama"] = "offline"

    # Check ChromaDB
    try:
        collection = await asyncio.to_thread(get_chroma_collection)
        count = await asyncio.to_thread(collection.count)
        results["rag"] = "ok"
        results["rag_documents"] = count
    except Exception:
        results["rag"] = "offline"
        results["rag_documents"] = 0

    # Count history entries today
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        hfile = HISTORY_PATH / f"{today}.jsonl"
        results["history_today"] = sum(1 for _ in open(hfile)) if hfile.exists() else 0
    except Exception:
        results["history_today"] = 0

    return results


@app.post("/ask")
async def ask(req: InferRequest):
    """General question - streams response."""
    system_prompt = SYSTEM_PROMPTS.get(req.profile, SYSTEM_PROMPTS["default"])

    # RAG: inject relevant context before inference
    rag_context = await query_rag(req.message)
    if rag_context:
        system_prompt = f"{system_prompt}\n\n{rag_context}"
        logger.info("RAG context injected (%d chars)", len(rag_context))

    if req.stream:
        async def response_stream():
            chunks = []
            async for chunk in await generate(system_prompt, req.message, stream=True):
                chunks.append(chunk)
                yield chunk
            # Log after streaming completes
            asyncio.create_task(
                asyncio.to_thread(
                    log_history, req.profile, "ask", req.message, "".join(chunks)
                )
            )

        return StreamingResponse(response_stream(), media_type="text/plain")

    response = await generate(system_prompt, req.message, stream=False)
    log_history(req.profile, "ask", req.message, response)
    return {"response": response}


@app.post("/review")
async def review(req: ReviewRequest):
    """Security-focused code review - streams response."""
    system_prompt = SYSTEM_PROMPTS.get(req.profile, SYSTEM_PROMPTS["default"])

    # Build review message with file context
    file_label = f"File: {req.filename}\n\n" if req.filename else ""
    message = f"{file_label}{req.content}{REVIEW_SUFFIX}"

    # RAG: look for relevant security patterns or past findings
    rag_context = await query_rag(f"security review {req.filename} {req.content[:200]}")
    if rag_context:
        system_prompt = f"{system_prompt}\n\n{rag_context}"

    if req.stream:
        async def response_stream():
            async for chunk in await generate(system_prompt, message, stream=True, num_predict=1024):
                yield chunk

        return StreamingResponse(response_stream(), media_type="text/plain")

    response = await generate(system_prompt, message, stream=False, num_predict=1024)
    return {"response": response}


@app.post("/scan")
async def scan(req: ScanRequest):
    """Security scan with severity ratings - streams response."""
    system_prompt = SYSTEM_PROMPTS.get(req.profile, SYSTEM_PROMPTS["default"])

    file_label = f"File: {req.filename}\n\n" if req.filename else ""
    message = f"{file_label}{req.content}{SCAN_SUFFIX}"

    rag_context = await query_rag(f"CVE vulnerability scan {req.content[:200]}")
    if rag_context:
        system_prompt = f"{system_prompt}\n\n{rag_context}"

    if req.stream:
        async def response_stream():
            async for chunk in await generate(system_prompt, message, stream=True, num_predict=1024):
                yield chunk

        return StreamingResponse(response_stream(), media_type="text/plain")

    response = await generate(system_prompt, message, stream=False, num_predict=1024)
    return {"response": response}


# ---------------------------------------------------------------------------
# RAG ingestion endpoints
# ---------------------------------------------------------------------------

@app.post("/rag/add")
async def rag_add(req: AddDocRequest) -> dict:
    """Add a document (file content) to the RAG knowledge base."""
    chunks = chunk_text(req.content)
    if not chunks:
        raise HTTPException(status_code=400, detail="Document is empty or too short")

    base_id = hashlib.sha256(f"{req.source}:{req.content[:200]}".encode()).hexdigest()[:16]
    ids = [f"{base_id}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": req.source, "type": req.doc_type, "chunk": i} for i in range(len(chunks))]

    count = await add_to_chroma(chunks, metadatas, ids)
    logger.info("RAG add: %s (%d chunks)", req.source, count)
    return {"added": count, "source": req.source, "chunks": len(chunks)}


@app.post("/rag/add-url")
async def rag_add_url(req: AddUrlRequest) -> dict:
    """Fetch a URL and add its text content to RAG."""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        try:
            resp = await client.get(req.url, headers={"User-Agent": "paperknight-AI/1.0"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=400, detail=f"Fetch failed: {e}")

    content_type = resp.headers.get("content-type", "")
    if "html" in content_type:
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove scripts, styles, nav cruft
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
    else:
        text = resp.text

    if len(text) < 100:
        raise HTTPException(status_code=400, detail="Page content too short to be useful")

    chunks = chunk_text(text)
    base_id = hashlib.sha256(req.url.encode()).hexdigest()[:16]
    ids = [f"{base_id}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": req.url, "type": "url", "chunk": i} for i in range(len(chunks))]

    count = await add_to_chroma(chunks, metadatas, ids)
    logger.info("RAG add-url: %s (%d chunks)", req.url, count)
    return {"added": count, "source": req.url, "chunks": len(chunks)}


@app.post("/rag/add-cve")
async def rag_add_cve(req: AddCveRequest) -> dict:
    """Fetch a CVE from NVD and add it to RAG knowledge base."""
    cve_id = req.cve_id.upper().strip()
    if not re.match(r"^CVE-\d{4}-\d+$", cve_id):
        raise HTTPException(status_code=400, detail=f"Invalid CVE ID format: {cve_id}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(NVD_API, params={"cveId": cve_id})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"NVD API failed: {e}")

    data = resp.json()
    vulns = data.get("vulnerabilities", [])
    if not vulns:
        raise HTTPException(status_code=404, detail=f"{cve_id} not found in NVD")

    cve_data = vulns[0].get("cve", {})
    descriptions = cve_data.get("descriptions", [])
    desc = next((d["value"] for d in descriptions if d["lang"] == "en"), "No description")

    # Pull CVSS scores
    metrics = cve_data.get("metrics", {})
    cvss_v3 = metrics.get("cvssMetricV31", [{}])[0].get("cvssData", {})
    cvss_v2 = metrics.get("cvssMetricV2", [{}])[0].get("cvssData", {})
    score = cvss_v3.get("baseScore") or cvss_v2.get("baseScore", "N/A")
    severity = cvss_v3.get("baseSeverity") or cvss_v2.get("baseSeverity", "N/A")

    # Pull affected products
    configs = cve_data.get("configurations", [])
    affected = []
    for cfg in configs:
        for node in cfg.get("nodes", []):
            for cpe in node.get("cpeMatch", []):
                if cpe.get("vulnerable"):
                    affected.append(cpe.get("criteria", ""))

    # Build structured text for RAG
    doc = (
        f"CVE ID: {cve_id}\n"
        f"CVSS Score: {score} ({severity})\n"
        f"Description: {desc}\n"
        f"Affected: {', '.join(affected[:10]) if affected else 'See NVD'}\n"
        f"Published: {cve_data.get('published', 'N/A')}\n"
        f"Last Modified: {cve_data.get('lastModified', 'N/A')}"
    )

    doc_id = hashlib.sha256(cve_id.encode()).hexdigest()[:16]
    await add_to_chroma([doc], [{"source": cve_id, "type": "cve", "score": str(score)}], [doc_id])
    logger.info("RAG add-cve: %s (score=%s %s)", cve_id, score, severity)
    return {"added": 1, "source": cve_id, "score": score, "severity": severity}


@app.get("/rag/search")
async def rag_search(query: str, n_results: int = 5) -> dict:
    """Search RAG knowledge base without generating a response."""
    embeddings = await asyncio.to_thread(embed, [query])
    try:
        collection = await asyncio.to_thread(get_chroma_collection)
        data = await asyncio.to_thread(
            collection.query,
            query_embeddings=embeddings,
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ChromaDB query failed: {e}")

    results = []
    docs = data.get("documents", [[]])[0]
    metas = data.get("metadatas", [[]])[0]
    dists = data.get("distances", [[]])[0]

    for doc, meta, dist in zip(docs, metas, dists):
        results.append({
            "source": meta.get("source", "unknown") if meta else "unknown",
            "type": meta.get("type", "unknown") if meta else "unknown",
            "distance": round(dist, 4),
            "excerpt": doc[:300] + ("..." if len(doc) > 300 else ""),
        })

    return {"query": query, "results": results}


@app.delete("/rag/reset")
async def rag_reset() -> dict:
    """Delete and recreate the RAG collection. Use with care."""
    global _chroma_collection
    host = CHROMADB_URL.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(CHROMADB_URL.split(":")[-1]) if ":" in CHROMADB_URL else 8000
    client = chromadb.HttpClient(host=host, port=port)
    await asyncio.to_thread(client.delete_collection, CHROMA_COLLECTION)
    _chroma_collection = None
    await asyncio.to_thread(get_chroma_collection)
    logger.warning("RAG collection reset")
    return {"status": "reset", "collection": CHROMA_COLLECTION}


@app.get("/history")
async def history(limit: int = 20) -> dict:
    """Recent query history."""
    entries = []
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        hfile = HISTORY_PATH / f"{today}.jsonl"
        if hfile.exists():
            lines = hfile.read_text().strip().split("\n")
            for line in reversed(lines[-limit:]):
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        logger.warning("History read failed: %s", e)
    return {"entries": entries}
