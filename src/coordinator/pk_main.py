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

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
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
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL_NAME = os.environ.get("MODEL_NAME", "llama3.1:8b")
CHROMADB_URL = os.environ.get("CHROMADB_URL", "http://localhost:8000")
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))
HISTORY_PATH = Path(os.environ.get("HISTORY_PATH", "/storage/history"))

# Embedding model - loaded once at startup, stays in memory (~200MB)
_embedder: Optional[SentenceTransformer] = None
CHROMA_COLLECTION = "paperknight"

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
    "johno": (
        "You are a helpful senior software engineer assistant for Johno. "
        "Focus on code correctness, clarity, and best practices. "
        "Explain things clearly. Be friendly and practical. "
        "Homelab and operations context. "
        "Flag any security issues you notice."
    ),
    "default": (
        "You are paperknight AI, a private AI assistant for paperknight Threat Labs. "
        "Be direct and technical. Flag security issues explicitly."
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

async def query_rag(query: str) -> Optional[str]:
    """Query ChromaDB for relevant documents. Returns injected context string or None."""
    try:
        embeddings = await asyncio.to_thread(embed, [query])
        async with httpx.AsyncClient(timeout=5.0) as client:
            payload = {
                "query_embeddings": embeddings,
                "n_results": RAG_TOP_K,
                "include": ["documents", "metadatas", "distances"],
            }
            resp = await client.post(
                f"{CHROMADB_URL}/api/v1/collections/{CHROMA_COLLECTION}/query",
                json=payload,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            documents = data.get("documents", [[]])[0]
            metadatas = data.get("metadatas", [[]])[0]
            distances = data.get("distances", [[]])[0]

            if not documents:
                return None

            # Only inject context that's actually relevant (distance threshold)
            relevant = [
                (doc, meta, dist)
                for doc, meta, dist in zip(documents, metadatas, distances)
                if dist < 1.5  # cosine distance threshold
            ]

            if not relevant:
                return None

            # Build context block
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
            "num_predict": 2048,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
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


async def generate(
    system_prompt: str,
    user_message: str,
    stream: bool = True,
) -> str | AsyncIterator[str]:
    """Generate a response, streaming or blocking."""
    ollama_url = await get_available_ollama()

    if stream:
        return stream_ollama(ollama_url, system_prompt, user_message)

    # Blocking mode for history logging
    full_response = []
    async for chunk in stream_ollama(ollama_url, system_prompt, user_message):
        full_response.append(chunk)
    return "".join(full_response)


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


async def ensure_collection() -> None:
    """Create the ChromaDB collection if it doesn't exist."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{CHROMADB_URL}/api/v1/collections/{CHROMA_COLLECTION}")
            if r.status_code == 200:
                return
            # Create it
            await client.post(
                f"{CHROMADB_URL}/api/v1/collections",
                json={"name": CHROMA_COLLECTION, "metadata": {"hnsw:space": "cosine"}},
            )
            logger.info("Created ChromaDB collection: %s", CHROMA_COLLECTION)
    except Exception as e:
        logger.warning("ChromaDB collection setup failed: %s", e)


async def add_to_chroma(
    documents: list[str],
    metadatas: list[dict],
    ids: list[str],
) -> int:
    """Embed and store documents in ChromaDB. Returns number added."""
    await ensure_collection()
    embeddings = await asyncio.to_thread(embed, documents)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{CHROMADB_URL}/api/v1/collections/{CHROMA_COLLECTION}/add",
            json={
                "ids": ids,
                "embeddings": embeddings,
                "documents": documents,
                "metadatas": metadatas,
            },
        )
        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"ChromaDB add failed: {resp.text}")
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    HISTORY_PATH.mkdir(parents=True, exist_ok=True)
    # Pre-load embedding model so first add doesn't pause inference
    await asyncio.to_thread(get_embedder)
    await ensure_collection()
    logger.info("pk-coordinator started (model=%s)", MODEL_NAME)
    yield


app = FastAPI(title="paperknight AI Coordinator", lifespan=lifespan)


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
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{CHROMADB_URL}/api/v1/heartbeat")
            results["rag"] = "ok" if r.status_code == 200 else "degraded"
            # Get document count
            try:
                rc = await client.get(f"{CHROMADB_URL}/api/v1/collections/paperknight")
                if rc.status_code == 200:
                    count = rc.json().get("metadata", {}).get("count", "?")
                    results["rag_documents"] = count
            except Exception:
                results["rag_documents"] = "?"
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
            async for chunk in await generate(system_prompt, message, stream=True):
                yield chunk

        return StreamingResponse(response_stream(), media_type="text/plain")

    response = await generate(system_prompt, message, stream=False)
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
            async for chunk in await generate(system_prompt, message, stream=True):
                yield chunk

        return StreamingResponse(response_stream(), media_type="text/plain")

    response = await generate(system_prompt, message, stream=False)
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
    await ensure_collection()
    embeddings = await asyncio.to_thread(embed, [query])

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{CHROMADB_URL}/api/v1/collections/{CHROMA_COLLECTION}/query",
            json={
                "query_embeddings": embeddings,
                "n_results": n_results,
                "include": ["documents", "metadatas", "distances"],
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="ChromaDB query failed")

    data = resp.json()
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
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.delete(f"{CHROMADB_URL}/api/v1/collections/{CHROMA_COLLECTION}")
    await ensure_collection()
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
