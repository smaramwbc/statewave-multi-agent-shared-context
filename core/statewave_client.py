"""
Thin adapter over the official `statewave` Python SDK.

Keeps this project's original call surface (write_episode / compile /
get_context / get_timeline) so agents/*.py and timeline_inspector.py don't
need to change, while all actual HTTP, retry, and pagination logic is
delegated to the SDK instead of a hand-rolled httpx client.
"""

import os
from typing import Any

from statewave import StatewaveClient as _SDKStatewaveClient


class StatewaveClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        api_key = api_key or os.getenv("STATEWAVE_API_KEY") or None
        base_url = base_url or os.getenv("STATEWAVE_BASE_URL", "http://localhost:8100")
        self._sdk = _SDKStatewaveClient(base_url=base_url, api_key=api_key)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def write_episode(
        self,
        subject_id: str,
        caller_id: str,
        content: str,
        episode_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write a single episode (decision, observation, note) to Statewave."""
        episode = self._sdk.create_episode(
            subject_id=subject_id,
            source=caller_id,
            type=episode_type,
            payload={"content": content},
            metadata=metadata or {},
        )
        return episode.model_dump(mode="json")

    def compile(self, subject_id: str) -> dict[str, Any]:
        """Trigger memory compilation so new episodes become retrievable immediately."""
        result = self._sdk.compile_memories_wait(subject_id)
        return result.model_dump(mode="json")

    def get_context(
        self,
        subject_id: str,
        caller_id: str,
        task: str,
        top_k: int = 5,
        caller_type: str = "agent",
    ) -> dict[str, Any]:
        """Retrieve ranked memories relevant to a task for a given caller.

        Sends the caller identity (caller_id and caller_type) so the service
        can apply per-role policy. A tenant that sets require_caller_identity
        rejects a request with no identity.
        """
        bundle = self._sdk.get_context(
            subject_id=subject_id,
            task=task,
            caller_id=caller_id,
            caller_type=caller_type,
        )
        return bundle.model_dump(mode="json")

    def get_timeline(self, subject_id: str) -> dict[str, Any]:
        """Return the full chronological event log for a subject."""
        timeline = self._sdk.get_timeline(subject_id)

        events = []
        for ep in timeline.episodes:
            events.append(
                {
                    "caller_id": ep.source,
                    "timestamp": ep.created_at.timestamp(),
                    "type": ep.type,
                    "content": ep.payload.get("content", ""),
                    "retrieved_memories": ep.metadata.get("retrieved_memories", []),
                }
            )

        memories = [
            {
                "type": mem.kind,
                "caller_id": mem.metadata.get("caller_id", ""),
                "confidence": mem.confidence,
                "status": mem.status,
                "content": mem.content,
            }
            for mem in timeline.memories
        ]

        return {"events": events, "memories": memories}
