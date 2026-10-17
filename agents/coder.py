"""
Coder agent.

Implements the features decided by the Planner. In the naive pipeline it
receives no shared context and can unknowingly rebuild a deprecated module.
In the Statewave pipeline it reads the shared context before starting and
respects any deprecation decisions it finds there.
"""

import time
from core.display import agent_log, info, warning
from core.llm import LLMClient
from statewave_agents import Agent, ContextBundle


SYSTEM_PROMPT_NAIVE = """You are a senior software engineer (Coder agent).
You have been asked to implement a feature. You have no information about
prior architectural decisions — act on the task description alone.

List every module / class you will implement as bullet points under:
  IMPLEMENTING:
  <list>

Be direct and specific."""


SYSTEM_PROMPT_WITH_CONTEXT = """You are a senior software engineer (Coder agent).
You have access to the shared architectural context below, including any
DEPRECATION DECISIONS made by the Planner.

{context_block}

Based on this context, list every module / class you will implement.
If a module appears in the DEPRECATE decisions, explicitly SKIP it and say why.

  IMPLEMENTING:
  <modules you will build>

  SKIPPING:
  <modules you are skipping and the reason from context>"""


class CoderAgent(Agent):
    name = "Coder"
    NAME = "Coder"  # kept for callers that still read the old constant
    caller_type = "coder"

    def __init__(self, llm_client: LLMClient, model: str = "groq/llama-3.3-70b-versatile"):
        self._llm = llm_client
        self._model = model

    # ------------------------------------------------------------------
    # statewave_agents.Agent interface — generic reusable path
    # ------------------------------------------------------------------

    def act(self, task: str, context: ContextBundle) -> dict:
        agent_log(self.name, "Reading shared context before starting implementation...")
        if context.has_context():
            info(f"Retrieved {len(context.memories)} memory item(s) from shared context:")
            for mem in context.memories:
                agent_log(
                    self.name,
                    f"  [{mem.get('type', 'memory')}] (confidence {mem.get('confidence', 0):.2f}) "
                    f"{mem.get('content', '')[:120]}",
                    style="dim cyan",
                )
        else:
            info("No compiled memories found in shared context yet.")

        context_block = context.assembled_context or "No prior context available."
        system_prompt = SYSTEM_PROMPT_WITH_CONTEXT.format(context_block=context_block)

        raw = self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Task: {task}"},
            ],
        ).choices[0].message.content

        implementing = self._parse_section(raw, "IMPLEMENTING")
        skipping = self._parse_section(raw, "SKIPPING")

        for m in implementing:
            agent_log(self.name, f"  Building → {m}", style="blue")
        for s in skipping:
            agent_log(self.name, f"  Skipping → {s}", style="dim yellow")

        return {
            "implementing": implementing,
            "skipping": skipping,
            "raw": raw,
            "timestamp": time.time(),
            "used_shared_context": context.has_context(),
            "context_memories": context.memories,
        }

    def publish_decisions(self, result: dict) -> None:
        if result["implementing"]:
            self.context.note(
                self.name,
                f"Implementation plan: {', '.join(result['implementing'])}",
                episode_type="implementation_note",
                metadata={"modules": result["implementing"], "skipped": result["skipping"]},
            )

    # ------------------------------------------------------------------
    # Naive mode — no shared context, collision is possible
    # ------------------------------------------------------------------

    def implement_naive(self, task: str, planner_context: dict | None = None) -> dict:
        """
        Implement without reading shared context.
        planner_context is deliberately NOT used here to model the real failure:
        even if it were passed as a param, in a truly parallel run it may not
        have arrived yet.
        """
        agent_log(self.NAME, "Starting implementation (no shared context)...")
        info("No shared context available — working from task description only.")

        raw = self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_NAIVE},
                {"role": "user", "content": f"Task: {task}"},
            ],
        ).choices[0].message.content

        implementing = self._parse_section(raw, "IMPLEMENTING")
        agent_log(self.NAME, f"Will implement {len(implementing)} module(s):")
        for m in implementing:
            agent_log(self.NAME, f"  → {m}", style="blue")

        return {
            "implementing": implementing,
            "skipping": [],
            "raw": raw,
            "timestamp": time.time(),
            "used_shared_context": False,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse_section(self, raw: str, section: str) -> list[str]:
        items = []
        in_section = False
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith(f"{section}:"):
                in_section = True
                continue
            if in_section:
                if stripped.upper().endswith(":") and stripped.upper() != f"{section}:":
                    break
                if stripped.startswith(("-", "•", "*")):
                    entry = stripped.lstrip("-•* ").strip()
                    if entry:
                        items.append(entry)
        return items
