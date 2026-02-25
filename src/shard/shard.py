"""
Pipeline shard service for distributed Qwen2.5-Coder inference.

Each shard loads a specific range of transformer layers from the PVC,
keeping only ~1/4 of model parameters in memory at steady state.

Layer assignment for Qwen2.5-Coder-1.5B-Instruct (28 transformer layers):
  Shard 0:  embed_tokens + layers 0..6   (text -> hidden states)
  Shard 1:  layers 7..13                 (hidden states passthrough)
  Shard 2:  layers 14..20               (hidden states passthrough)
  Shard 3:  layers 21..27 + norm + lm_head  (hidden states -> next token ID)

Tensor serialization: base64-encoded float16 numpy arrays passed as JSON.
No KV cache across shard boundaries - each generation step is a full pass.

Memory note: startup briefly loads the full ~3GB model to extract layers,
then frees unused portions. Peak memory ~3GB per shard during init,
~400MB at steady state. Start shards sequentially on 8GB machines.
"""

import base64
import gc
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("shard")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SHARD_ID = int(os.environ.get("SHARD_ID", "0"))
MODEL_PATH = os.environ.get("MODEL_PATH", "/storage/models/qwen2.5-coder")

# Layer ranges for Qwen2.5-Coder-1.5B-Instruct (28 layers, 0-indexed)
_LAYER_CFG = {
    0: {"start": 0,  "end": 7,  "has_embed": True,  "has_head": False},
    1: {"start": 7,  "end": 14, "has_embed": False, "has_head": False},
    2: {"start": 14, "end": 21, "has_embed": False, "has_head": False},
    3: {"start": 21, "end": 28, "has_embed": False, "has_head": True},
}

# ---------------------------------------------------------------------------
# Globals (populated at startup)
# ---------------------------------------------------------------------------
_modules: dict = {}
_tokenizer = None


# ---------------------------------------------------------------------------
# Tensor helpers
# ---------------------------------------------------------------------------

def _t2b64(t: torch.Tensor) -> dict:
    """Serialize a tensor to a JSON-safe dict."""
    arr = t.detach().cpu().to(torch.float16).numpy()
    return {
        "b64": base64.b64encode(arr.tobytes()).decode(),
        "shape": list(arr.shape),
    }


def _b642t(d: dict) -> torch.Tensor:
    """Deserialize a tensor from a dict produced by _t2b64."""
    raw = base64.b64decode(d["b64"])
    arr = np.frombuffer(raw, dtype=np.float16).reshape(d["shape"]).copy()
    return torch.from_numpy(arr)


def _causal_mask(seq_len: int, dtype: torch.dtype) -> torch.Tensor:
    """4D upper-triangular causal mask: 0 for attend, -inf for mask."""
    mask = torch.zeros(1, 1, seq_len, seq_len, dtype=dtype)
    mask = mask + torch.triu(
        torch.full((seq_len, seq_len), float("-inf"), dtype=dtype),
        diagonal=1,
    )
    return mask


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def _load_shard() -> None:
    global _modules, _tokenizer

    cfg = _LAYER_CFG[SHARD_ID]
    logger.info(
        "Shard %d: loading layers %d..%d from %s",
        SHARD_ID, cfg["start"], cfg["end"] - 1, MODEL_PATH,
    )

    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch.nn as nn

    if cfg["has_embed"]:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        logger.info("Tokenizer loaded")

    # Load full model with low_cpu_mem_usage to reduce peak RAM during init.
    # Layers outside our range are extracted and then freed.
    logger.info("Loading full model (will free unused layers after extraction)...")
    full = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.float16,
        device_map="cpu",
        low_cpu_mem_usage=True,
    )

    mods: dict = {}

    if cfg["has_embed"]:
        mods["embed_tokens"] = full.model.embed_tokens

    layer_slice = nn.ModuleList(
        [full.model.layers[i] for i in range(cfg["start"], cfg["end"])]
    )
    mods["layers"] = layer_slice

    if cfg["has_head"]:
        mods["norm"] = full.model.norm
        mods["lm_head"] = full.lm_head

    # Free the rest of the model
    del full
    gc.collect()

    _modules = mods
    logger.info(
        "Shard %d ready: %d layers, embed=%s, head=%s",
        SHARD_ID, len(layer_slice), cfg["has_embed"], cfg["has_head"],
    )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_shard()
    yield


app = FastAPI(title=f"Pipeline Shard {SHARD_ID}", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class EmbedRequest(BaseModel):
    text: str
    temperature: float = 0.7


class ForwardRequest(BaseModel):
    hidden_states: dict       # {b64, shape}
    seq_len: int
    temperature: float = 0.7


class DecodeRequest(BaseModel):
    token_ids: list[int]


class ShardResponse(BaseModel):
    hidden_states: Optional[dict] = None   # shards 0-2
    seq_len: Optional[int] = None
    next_token_id: Optional[int] = None    # shard 3 only
    text: Optional[str] = None             # /decode only


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    cfg = _LAYER_CFG[SHARD_ID]
    return {
        "shard": SHARD_ID,
        "status": "ready",
        "layers": f"{cfg['start']}..{cfg['end'] - 1}",
    }


@app.post("/embed", response_model=ShardResponse)
def embed(req: EmbedRequest) -> ShardResponse:
    """
    Shard 0 only.
    Tokenize raw text, run through embedding + first layer block,
    return hidden states for shard 1 to continue.
    """
    if SHARD_ID != 0:
        raise HTTPException(400, "Only shard 0 handles /embed")

    enc = _tokenizer(req.text, return_tensors="pt")
    input_ids: torch.Tensor = enc["input_ids"]
    seq_len = input_ids.shape[1]
    pos_ids = torch.arange(seq_len).unsqueeze(0)

    with torch.no_grad():
        hidden = _modules["embed_tokens"](input_ids)
        causal = _causal_mask(seq_len, hidden.dtype)
        for layer in _modules["layers"]:
            out = layer(
                hidden,
                attention_mask=causal,
                position_ids=pos_ids,
                use_cache=False,
            )
            hidden = out[0]

    return ShardResponse(hidden_states=_t2b64(hidden), seq_len=seq_len)


@app.post("/forward", response_model=ShardResponse)
def forward(req: ForwardRequest) -> ShardResponse:
    """
    Shards 1-3.
    Run hidden states through this shard's layer block.
    Shard 3 additionally applies norm + lm_head and returns the next token ID.
    """
    hidden = _b642t(req.hidden_states)
    seq_len = req.seq_len
    pos_ids = torch.arange(seq_len).unsqueeze(0)

    with torch.no_grad():
        causal = _causal_mask(seq_len, hidden.dtype)
        for layer in _modules["layers"]:
            out = layer(
                hidden,
                attention_mask=causal,
                position_ids=pos_ids,
                use_cache=False,
            )
            hidden = out[0]

        if "norm" not in _modules:
            # Middle shard: pass hidden states to next shard
            return ShardResponse(hidden_states=_t2b64(hidden), seq_len=seq_len)

        # Final shard: project to vocab and sample next token
        hidden = _modules["norm"](hidden)
        logits = _modules["lm_head"](hidden[:, -1, :])  # last position

        if req.temperature > 0.0:
            probs = torch.softmax(logits / req.temperature, dim=-1)
            next_token = int(torch.multinomial(probs, num_samples=1).item())
        else:
            next_token = int(logits.argmax(dim=-1).item())

    return ShardResponse(next_token_id=next_token, seq_len=seq_len)


@app.post("/decode", response_model=ShardResponse)
def decode(req: DecodeRequest) -> ShardResponse:
    """
    Shard 0 only.
    Decode a list of token IDs back to text. Used by the coordinator
    to reconstruct partial output during pipeline generation.
    """
    if SHARD_ID != 0:
        raise HTTPException(400, "Only shard 0 handles /decode")
    text = _tokenizer.decode(req.token_ids, skip_special_tokens=True)
    return ShardResponse(text=text)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
