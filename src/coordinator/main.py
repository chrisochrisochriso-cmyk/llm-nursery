"""
Coordinator service for paperknight Threat Labs inference system.

Polls Telegram Bot API for new messages, routes them through either:
  - Ollama (default, INFERENCE_MODE=ollama): single Ollama chat call
  - Pipeline (INFERENCE_MODE=pipeline): chains through 4 distributed shards

Access control: set ALLOWED_CHAT_ID to your Telegram user/chat ID to
restrict the bot to your account only. Find your ID by messaging the bot
and checking /whoami, or reading the first update log line at startup.

All config via environment variables - no secrets in source.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("coordinator")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
ALLOWED_CHAT_ID = os.environ.get("ALLOWED_CHAT_ID", "")  # empty = allow all

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama-service:11434")
INFERENCE_MODE = os.environ.get("INFERENCE_MODE", "ollama")
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen2.5-coder:1.5b-instruct-q4_0")

SHARD_URLS = {
    0: os.environ.get("SHARD_0_URL", "http://pipeline-shard-0-service:8080"),
    1: os.environ.get("SHARD_1_URL", "http://pipeline-shard-1-service:8080"),
    2: os.environ.get("SHARD_2_URL", "http://pipeline-shard-2-service:8080"),
    3: os.environ.get("SHARD_3_URL", "http://pipeline-shard-3-service:8080"),
}

_QWEN_EOS_IDS = {151645, 151643}

SYSTEM_PROMPT = """\
You are a security-focused coding assistant for paperknight Threat Labs.

You assist with: C++, Python, Kubernetes security, MITM proxy development, \
BGP research, ClawSec tooling, TIDS (Threat Intelligence Detection System), \
and k8sec-IR (Kubernetes Security Incident Response) tooling.

All code and context shared with you is sensitive security research. \
Be direct and technical. Identify security vulnerabilities explicitly when \
reviewing code. Do not add disclaimers about security research contexts.\
"""

# ---------------------------------------------------------------------------
# Inference: Ollama
# ---------------------------------------------------------------------------

async def generate_ollama(message: str) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 512},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Inference: Pipeline (4-shard)
# ---------------------------------------------------------------------------

def _qwen_chat_prompt(message: str) -> str:
    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{message}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


async def generate_pipeline(message: str, max_new_tokens: int = 512) -> str:
    current_text = _qwen_chat_prompt(message)
    generated_ids: list[int] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for _ in range(max_new_tokens):
            r = await client.post(
                f"{SHARD_URLS[0]}/embed",
                json={"text": current_text, "temperature": 0.7},
            )
            r.raise_for_status()
            data = r.json()

            for shard_id in (1, 2):
                r = await client.post(
                    f"{SHARD_URLS[shard_id]}/forward",
                    json={"hidden_states": data["hidden_states"], "seq_len": data["seq_len"], "temperature": 0.7},
                )
                r.raise_for_status()
                data = r.json()

            r = await client.post(
                f"{SHARD_URLS[3]}/forward",
                json={"hidden_states": data["hidden_states"], "seq_len": data["seq_len"], "temperature": 0.7},
            )
            r.raise_for_status()
            next_token_id = r.json()["next_token_id"]

            if next_token_id in _QWEN_EOS_IDS:
                break

            generated_ids.append(next_token_id)

            if generated_ids:
                dec = await client.post(
                    f"{SHARD_URLS[0]}/decode", json={"token_ids": generated_ids}
                )
                dec.raise_for_status()
                current_text = _qwen_chat_prompt(message) + dec.json()["text"]

    if not generated_ids:
        return ""

    async with httpx.AsyncClient(timeout=10.0) as client:
        dec = await client.post(f"{SHARD_URLS[0]}/decode", json={"token_ids": generated_ids})
        dec.raise_for_status()
        return dec.json()["text"].strip()


# ---------------------------------------------------------------------------
# Telegram integration
# ---------------------------------------------------------------------------

async def send_telegram_reply(chat_id: int, reply_to: int, text: str) -> None:
    """Send a message in-thread via Telegram Bot API."""
    # Telegram has a 4096 char message limit - split if needed
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=15.0) as client:
        for chunk in chunks:
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "reply_to_message_id": reply_to,
                "parse_mode": "Markdown",
            }
            resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
            if resp.status_code != 200:
                # Retry without Markdown if parse failed
                payload["parse_mode"] = None
                payload.pop("parse_mode")
                await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)


async def send_typing(chat_id: int) -> None:
    """Show typing indicator while inference runs."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(
            f"{TELEGRAM_API}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
        )


async def handle_update(update: dict) -> None:
    """Process one Telegram update."""
    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id: int = message["chat"]["id"]
        message_id: int = message["message_id"]
        text: str = message.get("text", "").strip()

        if not text:
            return

        # Access control
        if ALLOWED_CHAT_ID and str(chat_id) != ALLOWED_CHAT_ID:
            logger.warning("Blocked message from chat_id=%s", chat_id)
            return

        logger.info("Message from chat_id=%s: %.80s", chat_id, text)

        # Show typing while we work
        await send_typing(chat_id)

        if INFERENCE_MODE == "pipeline":
            response = await generate_pipeline(text)
        else:
            response = await generate_ollama(text)

        logger.info("Response (%.80s...)", response)
        await send_telegram_reply(chat_id, message_id, response)

    except Exception:
        logger.exception("handle_update failed")


async def poll_loop() -> None:
    """Long-poll Telegram getUpdates. Handles reconnects automatically."""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set - polling disabled")
        return

    offset = 0
    logger.info("Starting Telegram long-poll (mode=%s, model=%s)", INFERENCE_MODE, MODEL_NAME)

    async with httpx.AsyncClient(timeout=40.0) as client:
        while True:
            try:
                resp = await client.get(
                    f"{TELEGRAM_API}/getUpdates",
                    params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                )
                if resp.status_code == 200:
                    updates = resp.json().get("result", [])
                    for update in updates:
                        update_id = update["update_id"]
                        if update_id >= offset:
                            offset = update_id + 1
                        # Log chat_id on first message so user can set ALLOWED_CHAT_ID
                        if msg := (update.get("message") or update.get("edited_message")):
                            logger.info(
                                "Received update from chat_id=%s user=%s",
                                msg["chat"]["id"],
                                msg.get("from", {}).get("username", "unknown"),
                            )
                        asyncio.create_task(handle_update(update))
                else:
                    logger.warning("getUpdates returned %s", resp.status_code)
                    await asyncio.sleep(5)
            except httpx.TimeoutException:
                pass  # Normal for long-poll, just loop again
            except httpx.RequestError as e:
                logger.warning("Telegram poll error: %s", e)
                await asyncio.sleep(5)
            except Exception:
                logger.exception("Unexpected poll error")
                await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

_poll_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poll_task
    _poll_task = asyncio.create_task(poll_loop())
    logger.info("Coordinator started (mode=%s)", INFERENCE_MODE)
    yield
    if _poll_task:
        _poll_task.cancel()


app = FastAPI(title="paperknight Coordinator", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "inference_mode": INFERENCE_MODE,
        "model": MODEL_NAME,
        "telegram": "configured" if TELEGRAM_TOKEN else "missing token",
        "allowed_chat_id": ALLOWED_CHAT_ID or "all (set ALLOWED_CHAT_ID to restrict)",
    }


class InferRequest(BaseModel):
    message: str
    mode: Optional[str] = None


@app.post("/infer")
async def infer(req: InferRequest) -> dict:
    """Direct inference endpoint for testing without Telegram."""
    mode = req.mode or INFERENCE_MODE
    try:
        if mode == "pipeline":
            text = await generate_pipeline(req.message)
        else:
            text = await generate_ollama(req.message)
        return {"response": text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/pipeline/health")
async def pipeline_health() -> dict:
    results = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for shard_id, url in SHARD_URLS.items():
            try:
                r = await client.get(f"{url}/health")
                results[f"shard_{shard_id}"] = r.json() if r.status_code == 200 else "degraded"
            except Exception as e:
                results[f"shard_{shard_id}"] = f"offline: {e}"
    return results
