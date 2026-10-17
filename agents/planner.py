"""
Planner agent.

Decides the high-level architecture for the current task. In the naive
pipeline its decisions live only in its own context dict. In the Statewave
pipeline it writes every decision as an episode and compiles immediately.
"""

import time
from core.display import agent_log, info
from core.llm import LLMClient
from statewave_agents import Agent, ContextBundle


SYSTEM_PROMPT = """You are a senior software architect (Planner agent).
Your job is to analyse the task description and produce:
1. A list of modules / components to build.
2. A list of explicit DEPRECATION DECISIONS — modules that must NOT be built
   because they are outdated, replaced, or otherwise deprecated.

Respond in plain text with two clearly labelled sections:
  BUILD:
  <bullet list of things to implement>

  DEPRECATE:
  <bullet list of modules/patterns to skip and WHY>

Be specific and concise. This output will be read by a Coder agent."""


class PlannerAgent(Agent):
    name = "Planner"
    NAME = "Planner"  # kept for callers that still read the old constant
    caller_type = "planner"

    def __init__(self, llm_client: LLMClient, model: str = "groq/llama-3.3-70b-versatile"):
        self._llm = llm_client
        self._model = model

    # ------------------------------------------------------------------
    # statewave_agents.Agent interface — generic reusable path
    # ------------------------------------------------------------------

    def act(self, task: str, context: ContextBundle) -> dict:
        agent_log(self.name, "Starting planning (Statewave shared context)...")
        raw = self._call_llm(task)
        decisions = self._parse_decisions(raw)
        agent_log(
            self.name,
            f"Architectural decisions: {len(decisions['build'])} build, {len(decisions['deprecate'])} deprecate",
        )
        return {"raw": raw, "decisions": decisions, "timestamp": time.time()}

    def publish_decisions(self, result: dict) -> None:
        decisions = result["decisions"]
        for item in decisions["build"]:
            self.context.decide(self.name, f"Build decision: {item}", kind="build")
        for dep in decisions["deprecate"]:
            agent_log(self.name, f"  DEPRECATING → {dep}", style="bold red")
            self.context.decide(self.name, f"Deprecation decision: {dep}", kind="deprecate")
        info("Compiling episodes → making decisions available to all agents now...")

    # ------------------------------------------------------------------
    # Naive mode — decisions stay inside this object only
    # ------------------------------------------------------------------

    def plan_naive(self, task: str) -> dict:
        """
        Run planning with no shared context layer.
        Returns a local context dict that is NOT shared with other agents.
        """
        agent_log(self.NAME, "Starting planning (no shared context)...")
        raw = self._call_llm(task)
        decisions = self._parse_decisions(raw)

        agent_log(self.NAME, f"Architectural decisions: {len(decisions['build'])} build, {len(decisions['deprecate'])} deprecate")
        for dep in decisions["deprecate"]:
            agent_log(self.NAME, f"  DEPRECATING → {dep}", style="dim red")

        info("Planner decisions written to local context only — other agents cannot see this.")
        return {"raw": raw, "decisions": decisions, "timestamp": time.time()}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _call_llm(self, task: str) -> str:
        response = self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Task: {task}"},
            ],
        )
        return response.choices[0].message.content

    def _parse_decisions(self, raw: str) -> dict:
        build, deprecate = [], []
        current_section = None
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("BUILD:"):
                current_section = "build"
            elif stripped.upper().startswith("DEPRECATE:"):
                current_section = "deprecate"
            elif stripped.startswith(("-", "•", "*")) and current_section:
                entry = stripped.lstrip("-•* ").strip()
                if entry:
                    (build if current_section == "build" else deprecate).append(entry)
        return {"build": build, "deprecate": deprecate}
