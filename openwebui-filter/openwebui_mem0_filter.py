"""
title: Mem0 Memory
description: Long-term memory via a self-hosted Mem0 server. Recalls relevant memories before each reply and learns from each exchange.
version: 1.0.0
requirements: aiohttp
"""

import asyncio
from typing import Optional

import aiohttp
from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        mem0_url: str = Field(default="http://mem0:8000", description="Mem0 server URL (compose service name)")
        mem0_api_key: str = Field(default="", description="MEM0_API_KEY (the mem0 REST API bearer)")
        user_id_field: str = Field(default="email", description="Which Open WebUI user field keys memories: email or id")
        top_k: int = Field(default=8, description="Max memories injected per message")
        threshold: float = Field(default=0.35, description="Min similarity score (0-1) for a memory to be injected")
        search_timeout: int = Field(default=60, description="Seconds to wait for the memory search before giving up. Bursts serialize behind local embed loads (shared GPU squeezes nomic-embed to CPU during vision-model windows); 15s timed out there.")
        learn: bool = Field(default=True, description="Extract new memories from each exchange")
        show_status: bool = Field(default=True, description="Show 'recalled N memories' status in chat")
        priority: int = Field(default=0)

    class UserValves(BaseModel):
        enabled: bool = Field(default=True, description="Use long-term memory in my chats")

    def __init__(self):
        self.valves = self.Valves()
        self._tasks: set = set()

    # ---- helpers -------------------------------------------------------

    def _uid(self, user: Optional[dict]) -> Optional[str]:
        if not user:
            return None
        return user.get(self.valves.user_id_field) or user.get("id")

    def _enabled(self, user: Optional[dict]) -> bool:
        uv = (user or {}).get("valves")
        return getattr(uv, "enabled", True) if uv is not None else True

    @staticmethod
    def _text(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # multimodal: [{"type": "text", "text": ...}, {"type": "image_url", ...}]
            return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        return ""

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.valves.mem0_api_key:
            h["Authorization"] = f"Bearer {self.valves.mem0_api_key}"
        return h

    async def _post(self, path: str, payload: dict, timeout: float) -> dict:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.post(self.valves.mem0_url.rstrip("/") + path, json=payload, headers=self._headers()) as r:
                r.raise_for_status()
                return await r.json()

    async def _status(self, emitter, text: str):
        if emitter and self.valves.show_status:
            await emitter({"type": "status", "data": {"description": text, "done": True}})

    # ---- filter hooks --------------------------------------------------

    async def inlet(self, body: dict, __user__: Optional[dict] = None, __metadata__: Optional[dict] = None,
                    __event_emitter__=None) -> dict:
        if (__metadata__ or {}).get("task") or not self._enabled(__user__):
            return body  # skip title/tag/follow-up generation tasks
        uid = self._uid(__user__)
        messages = body.get("messages") or []
        query = next((self._text(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
        if not uid or not query.strip():
            return body

        try:
            res = await self._post("/search", {"query": query[:2000], "user_id": uid,
                                               "top_k": self.valves.top_k, "threshold": self.valves.threshold}, self.valves.search_timeout)
        except Exception as e:
            print(f"[mem0] search failed: {e}")
            return body

        memories = [r["memory"] for r in res.get("results", []) if r.get("memory")]
        if not memories:
            return body

        block = ("Long-term memory about the user (from earlier conversations; use when relevant, "
                 "don't mention it unless asked):\n" + "\n".join(f"- {m}" for m in memories))
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = f"{self._text(messages[0]['content'])}\n\n{block}"
        else:
            messages.insert(0, {"role": "system", "content": block})
        body["messages"] = messages
        await self._status(__event_emitter__, f"Recalled {len(memories)} memor{'y' if len(memories) == 1 else 'ies'}")
        return body

    async def outlet(self, body: dict, __user__: Optional[dict] = None, __metadata__: Optional[dict] = None) -> dict:
        if not self.valves.learn or (__metadata__ or {}).get("task") or not self._enabled(__user__):
            return body
        uid = self._uid(__user__)
        msgs = [m for m in (body.get("messages") or []) if m.get("role") in ("user", "assistant")]
        if not uid or len(msgs) < 2:
            return body

        exchange = [{"role": m["role"], "content": self._text(m.get("content"))[:4000]} for m in msgs[-2:]]
        payload = {"messages": exchange, "user_id": uid, "infer": True,
                   "metadata": {"source": "openwebui", "chat_id": body.get("chat_id") or (__metadata__ or {}).get("chat_id")}}

        async def learn():
            try:
                await self._post("/memories", payload, 180)
            except Exception as e:
                print(f"[mem0] add failed: {e}")

        # fire-and-forget so the reply isn't delayed by extraction
        t = asyncio.create_task(learn())
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return body
