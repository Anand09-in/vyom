"""Conversation history — Redis-backed, unbounded, no TTL.

Distinct from query_log (Postgres, in repo.py): query_log is permanent
observability metadata with no answer text and is never read back. This
store holds the actual {question, answer} turns so a follow-up question
can be resolved against what was actually said.

Storage is a plain append-only list per session — every turn is kept
forever until a client explicitly deletes it (see DELETE /query/history
in api/routers/query.py). Nothing is ever evicted or summarized here;
"only the last N turns go to the LLM" is enforced by callers slicing via
get_recent(), not by anything this store does to the data itself.

Two more structures track the sidebar's "recent conversations" list,
separate from the turn data itself so listing never has to load full
conversation bodies:
  vyom:conversations        ZSET  member=session_id, score=last-activity ts
  vyom:conversation_titles  HASH  field=session_id,  value=title (first message, fixed)
Both are unbounded too — "last 10" (list_recent) is a query-time limit,
not a storage cap, so nothing is lost by the sidebar only showing 10.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import redis.asyncio as redis

from vyom.config import Settings

_CONVERSATIONS_KEY = "vyom:conversations"
_TITLES_KEY = "vyom:conversation_titles"
_TITLE_MAX_LEN = 60


@dataclass
class Turn:
    question: str
    answer: str


@dataclass
class ConversationSummary:
    session_id: str
    title: str


class HistoryStore:
    def __init__(self, settings: Settings) -> None:
        self._client = redis.from_url(settings.redis_url, decode_responses=True)

    @staticmethod
    def _key(session_id: str) -> str:
        return f"vyom:history:{session_id}"

    async def get_all(self, session_id: str) -> list[Turn]:
        """Every turn ever stored for this session, oldest first."""
        raw = await self._client.lrange(self._key(session_id), 0, -1)
        return [Turn(**json.loads(r)) for r in raw]

    async def get_recent(self, session_id: str, n: int) -> list[Turn]:
        """Last n turns only — what actually gets sent to the LLM."""
        raw = await self._client.lrange(self._key(session_id), -n, -1)
        return [Turn(**json.loads(r)) for r in raw]

    async def append(self, session_id: str, question: str, answer: str) -> None:
        payload = json.dumps({"question": question, "answer": answer})
        await self._client.rpush(self._key(session_id), payload)
        # Title is fixed at the first message — HSETNX is a no-op if it's
        # already set. Recency score updates on every message so actively
        # used conversations bubble to the top of the sidebar.
        await self._client.hsetnx(_TITLES_KEY, session_id, question[:_TITLE_MAX_LEN])
        await self._client.zadd(_CONVERSATIONS_KEY, {session_id: time.time()})

    async def list_recent(self, n: int) -> list[ConversationSummary]:
        """The n most-recently-active conversations, newest first."""
        session_ids = await self._client.zrevrange(_CONVERSATIONS_KEY, 0, n - 1)
        if not session_ids:
            return []
        titles = await self._client.hmget(_TITLES_KEY, session_ids)
        return [
            ConversationSummary(session_id=sid, title=title or "")
            for sid, title in zip(session_ids, titles)
        ]

    async def delete(self, session_id: str) -> None:
        await self._client.delete(self._key(session_id))
        await self._client.zrem(_CONVERSATIONS_KEY, session_id)
        await self._client.hdel(_TITLES_KEY, session_id)

    async def close(self) -> None:
        await self._client.aclose()
