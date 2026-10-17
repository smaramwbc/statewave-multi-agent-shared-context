"""
Reviewer agent.

Validates the Coder's output. In the naive pipeline it reads both outputs
sequentially and can only detect the conflict after both agents have finished —
too late to prevent wasted compute. In the Statewave pipeline it reads the
full shared timeline and validates against the authoritative source of truth.
"""

import time
from core.display import agent_log, info, collision_box
from core.llm import LLMClient
from statewave_agents import Agent, ContextBundle


SYSTEM_PROMPT_NAIVE = """You are a senior code reviewer (Reviewer agent).
You are reviewing the implementation plan produced by a Coder agent.

Planner's decisions (passed to you after the fact):
{planner_output}

Coder's implementation plan:
{coder_output}

Check for conflicts:
- Did the Coder implement anything the Planner explicitly deprecated?
- Are there any contradictions between the two plans?

Respond with:
  STATUS: CONFLICT or STATUS: CLEAN
  FINDINGS:
  <bullet list of issues, or "No issues found">"""


SYSTEM_PROMPT_WITH_CONTEXT = """You are a senior code reviewer (Reviewer agent).
You have access to the full shared architectural context, including decisions
from both the Planner and the Coder:

{context_block}

Review the overall plan for:
- Deprecated modules that were implemented anyway
- Contradictions or conflicts in the shared decisions
- Missing alignment between planning and implementation

Respond with:
  STATUS: CONFLICT or STATUS: CLEAN
  FINDINGS:
  <bullet list of issues, or "No issues found">"""


class ReviewerAgent(Agent):
    name = "Reviewer"
    NAME = "Reviewer"  # kept for callers that still read the old constant
    caller_type = "reviewer"

    def __init__(self, llm_client: LLMClient, model: str = "groq/llama-3.3-70b-versatile"):
        self._llm = llm_client
        self._model = model

    # ------------------------------------------------------------------
    # statewave_agents.Agent interface — generic reusable path
    # ------------------------------------------------------------------

    def act(self, task: str, context: ContextBundle) -> dict:
        agent_log(self.name, "Reading shared context for review...")
        info(f"Retrieved {len(context.memories)} memory item(s) from shared context for review.")

        raw = self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_WITH_CONTEXT.format(
                        context_block=context.assembled_context or "No shared context available."
                    ),
                },
                {"role": "user", "content": f"Task: {task}"},
            ],
        ).choices[0].message.content

        status, findings = self._parse_review(raw)

        return {
            "status": status,
            "findings": findings,
            "raw": raw,
            "timestamp": time.time(),
            "used_shared_context": context.has_context(),
            "context_memories": context.memories,
        }

    def publish_decisions(self, result: dict) -> None:
        self.context.note(
            self.name,
            f"Review result: {result['status']}. Findings: "
            f"{'; '.join(result['findings']) if result['findings'] else 'None'}",
            episode_type="review_finding",
            metadata={"status": result["status"], "findings": result["findings"]},
        )

    # ------------------------------------------------------------------
    # Naive mode — detects conflict only AFTER both agents have finished
    # ------------------------------------------------------------------

    def review_naive(
        self,
        task: str,
        planner_result: dict,
        coder_result: dict,
    ) -> dict:
        agent_log(self.NAME, "Starting review (no shared context — conflict detection is post-hoc)...")
        info("Receiving Planner and Coder outputs sequentially — both have already finished.")

        planner_out = planner_result.get("raw", "")
        coder_out = coder_result.get("raw", "")

        raw = self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_NAIVE.format(
                        planner_output=planner_out,
                        coder_output=coder_out,
                    ),
                },
                {"role": "user", "content": f"Task: {task}"},
            ],
        ).choices[0].message.content

        status, findings = self._parse_review(raw)

        if status == "CONFLICT":
            collision_box(
                "Conflict detected — but both agents have already completed their work.\n"
                "Wasted compute cannot be recovered. This is the message-passing failure mode.\n\n"
                + "\n".join(f"  • {f}" for f in findings)
            )
        else:
            agent_log(self.NAME, "No conflicts found.", style="green")

        return {
            "status": status,
            "findings": findings,
            "raw": raw,
            "timestamp": time.time(),
            "used_shared_context": False,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse_review(self, raw: str) -> tuple[str, list[str]]:
        status = "CLEAN"
        findings = []
        in_findings = False

        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("STATUS:"):
                val = stripped.split(":", 1)[1].strip().upper()
                if "CONFLICT" in val:
                    status = "CONFLICT"
            elif stripped.upper().startswith("FINDINGS:"):
                in_findings = True
            elif in_findings and stripped.startswith(("-", "•", "*")):
                entry = stripped.lstrip("-•* ").strip()
                if entry and entry.lower() != "no issues found":
                    findings.append(entry)

        return status, findings
