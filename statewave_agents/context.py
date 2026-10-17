"""
SharedContext — the coordination primitive on top of the raw Statewave SDK.

Where core.statewave_client.StatewaveClient exposes the transport-level API
(write_episode / compile / get_context / get_timeline), SharedContext exposes
what an agent developer actually wants: "publish a decision", "what do I need
to know before I act", "what has anyone decided so far".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.statewave_client import StatewaveClient


@dataclass
class Decision:
    """A single decision published to the shared subject."""

    caller_id: str
    kind: str  # e.g. "build", "deprecate", or any project-specific label
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: 0.0)


@dataclass
class ContextBundle:
    """Everything an agent retrieves before acting."""

    assembled_context: str
    memories: list[dict[str, Any]]

    def has_context(self) -> bool:
        return bool(self.memories)

    def memories_of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.memories if m.get("type") == kind]


class SharedContext:
    """
    A shared subject that any number of agents can read from and write to.

    One SharedContext per run/task. Agents call `.decide(...)` to publish and
    `.before_acting(...)` to retrieve what's relevant before doing work.
    """

    def __init__(
        self,
        subject_id: str,
        client: StatewaveClient | None = None,
        auto_compile: bool = True,
    ):
        self.subject_id = subject_id
        self._client = client or StatewaveClient()
        self._auto_compile = auto_compile

    def decide(
        self,
        caller_id: str,
        content: str,
        kind: str = "decision",
        metadata: dict[str, Any] | None = None,
        episode_type: str = "architectural_decision",
    ) -> Decision:
        """Publish a decision to the shared subject, visible to every agent."""
        meta = dict(metadata or {})
        meta["decision_kind"] = kind
        self._client.write_episode(
            subject_id=self.subject_id,
            caller_id=caller_id,
            content=content,
            episode_type=episode_type,
            metadata=meta,
        )
        if self._auto_compile:
            self._client.compile(self.subject_id)
        return Decision(caller_id=caller_id, kind=kind, content=content, metadata=meta)

    def note(
        self,
        caller_id: str,
        content: str,
        episode_type: str = "note",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write a non-decision episode (implementation note, review finding, etc)."""
        self._client.write_episode(
            subject_id=self.subject_id,
            caller_id=caller_id,
            content=content,
            episode_type=episode_type,
            metadata=metadata or {},
        )
        if self._auto_compile:
            self._client.compile(self.subject_id)

    def before_acting(
        self,
        caller_id: str,
        task: str,
        top_k: int = 5,
        caller_type: str = "agent",
    ) -> ContextBundle:
        """Retrieve everything relevant to `task` that other agents have already decided."""
        response = self._client.get_context(
            subject_id=self.subject_id,
            caller_id=caller_id,
            task=task,
            top_k=top_k,
            caller_type=caller_type,
        )
        return ContextBundle(
            assembled_context=response.get("assembled_context", ""),
            memories=response.get("memories", []),
        )

    def timeline(self) -> dict[str, Any]:
        """The full chronological audit trail for this subject."""
        return self._client.get_timeline(self.subject_id)
