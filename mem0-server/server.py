"""Minimal self-hosted Mem0 REST API backed by Ollama + Qdrant.

Endpoints (all require `Authorization: Bearer $MEM0_API_KEY` when that is set):
  GET    /health
  POST   /memories            {messages, user_id, metadata?, infer?}
  POST   /search              {query, user_id, top_k?, threshold?}
  GET    /memories?user_id=   list a user's memories
  DELETE /memories/{id}
  DELETE /memories?user_id=   wipe a user's memories
"""

import os
from typing import Any, Optional, Union

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from mem0 import Memory
from pydantic import BaseModel

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
API_KEY = os.environ.get("MEM0_API_KEY", "")

OLLAMA_CLOUD_KEY = os.environ.get("OLLAMA_API_KEY", "")

# Fact extraction LLM: Ollama Cloud (via its OpenAI-compatible API) when a key is set,
# otherwise the local Ollama container. mem0's native ollama provider sends no auth header.
if OLLAMA_CLOUD_KEY:
    LLM = {
        "provider": "openai",
        "config": {
            "model": os.environ.get("MEM0_LLM_MODEL", "gemma4:31b"),
            "openai_base_url": os.environ.get("OLLAMA_CLOUD_URL", "https://ollama.com/v1"),
            "api_key": OLLAMA_CLOUD_KEY,
            "temperature": 0.1,
            "max_tokens": 2000,
        },
    }
else:
    LLM = {
        "provider": "ollama",
        "config": {
            "model": os.environ.get("MEM0_LOCAL_LLM_MODEL", "qwen3:4b-instruct"),
            "ollama_base_url": OLLAMA_URL,
            "temperature": 0.1,
            "max_tokens": 2000,
        },
    }

CONFIG = {
    "version": "v1.1",
    "llm": LLM,
    "embedder": {
        "provider": "ollama",
        "config": {
            "model": os.environ.get("MEM0_EMBED_MODEL", "nomic-embed-text"),
            "ollama_base_url": OLLAMA_URL,
            "embedding_dims": int(os.environ.get("MEM0_EMBED_DIMS", "768")),
        },
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "host": os.environ.get("QDRANT_HOST", "qdrant"),
            "port": int(os.environ.get("QDRANT_PORT", "6333")),
            "collection_name": os.environ.get("MEM0_COLLECTION", "openwebui_memories"),
            "embedding_model_dims": int(os.environ.get("MEM0_EMBED_DIMS", "768")),
        },
    },
    "history_db_path": os.environ.get("MEM0_HISTORY_DB", "/data/history.db"),
}

memory = Memory.from_config(CONFIG)
app = FastAPI(title="mem0-local")


def auth(authorization: Optional[str] = Header(None)):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="invalid api key")


class AddRequest(BaseModel):
    messages: Union[str, list[dict[str, Any]]]
    user_id: str
    metadata: Optional[dict[str, Any]] = None
    infer: bool = True


class SearchRequest(BaseModel):
    query: str
    user_id: str
    top_k: int = 8
    threshold: float = 0.3


@app.get("/health")
def health():
    return {"ok": True, "llm": CONFIG["llm"]["config"]["model"], "embedder": CONFIG["embedder"]["config"]["model"]}


@app.post("/memories", dependencies=[Depends(auth)])
async def add(req: AddRequest):
    return await run_in_threadpool(
        memory.add, req.messages, user_id=req.user_id, metadata=req.metadata, infer=req.infer
    )


@app.post("/search", dependencies=[Depends(auth)])
async def search(req: SearchRequest):
    return await run_in_threadpool(
        memory.search, req.query, filters={"user_id": req.user_id}, top_k=req.top_k, threshold=req.threshold
    )


@app.get("/memories", dependencies=[Depends(auth)])
async def list_memories(user_id: str, limit: int = 1000):
    return await run_in_threadpool(memory.get_all, filters={"user_id": user_id}, top_k=limit)


@app.delete("/memories/{memory_id}", dependencies=[Depends(auth)])
async def delete(memory_id: str):
    await run_in_threadpool(memory.delete, memory_id)
    return {"deleted": memory_id}


@app.delete("/memories", dependencies=[Depends(auth)])
async def delete_all(user_id: str):
    await run_in_threadpool(memory.delete_all, user_id=user_id)
    return {"deleted_all_for": user_id}
