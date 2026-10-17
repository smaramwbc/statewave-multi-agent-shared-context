"""
Agent — base class for any LLM agent that coordinates through a SharedContext.

Subclass this for a project-specific role (planner, coder, reviewer, or
anything else). The base class handles the two coordination primitives —
reading shared context before acting, and publishing decisions after — so
subclasses only implement the domain logic: how to prompt the LLM and how to
parse its output.
"""

from __future__ import annotations

from core.llm import LLMClient
from statewave_agents.context import ContextBundle, SharedContext


class Agent:
    """
    Base class for a shared-context-aware agent.

    Subclasses implement `act(task, context)`, which receives the
    ContextBundle retrieved from the shared subject (empty if none exists
    yet) and returns a result dict. The base class takes care of retrieval
    and, via `publish_decisions`, writing results back.
    """

    name: str = "Agent"
    caller_type: str = "agent"

    def __init__(self, llm: LLMClient, context: SharedContext, model: str = "groq/llama-3.3-70b-versatile"):
        self.llm = llm
        self.context = context
        self.model = model

    def run(self, task: str, top_k: int = 5) -> dict:
        """Read shared context, then act. This is the entrypoint most callers use."""
        bundle = self.context.before_acting(
            self.name, task, top_k=top_k, caller_type=self.caller_type
        )
        result = self.act(task, bundle)
        self.publish_decisions(result)
        return result

    def act(self, task: str, context: ContextBundle) -> dict:
        """Override in subclasses: call the LLM, parse the response, return a result dict."""
        raise NotImplementedError

    def publish_decisions(self, result: dict) -> None:
        """
        Override in subclasses to write decisions/notes back to the shared
        context based on `result`. No-op by default so read-only agents
        (e.g. a pure reviewer) don't have to implement it.
        """
        return None
