"""
Naive pipeline — the BEFORE.

Three agents run sequentially (simulating parallel work by withholding
context between them). The Planner deprecates a module; the Coder never
sees that decision and rebuilds it from scratch; the Reviewer catches the
conflict only after both agents have already finished.

This is the failure mode that Statewave prevents.
"""

import time
import uuid

from agents.planner import PlannerAgent
from agents.coder import CoderAgent
from agents.reviewer import ReviewerAgent
from core.display import header, divider, info, warning, agent_log
from core.llm import LLMClient


def run(task: str, llm_client: LLMClient, model: str = "groq/llama-3.3-70b-versatile") -> dict:
    run_id = f"naive-{uuid.uuid4().hex[:8]}"

    header(
        "BEFORE: Naive Message-Passing Pipeline",
        "Agents work from individual prompt contexts. No shared source of truth.",
    )
    info(f"Run ID  : {run_id}")
    info(f"Task    : {task}")
    divider()

    planner = PlannerAgent(llm_client, model=model)
    coder = CoderAgent(llm_client, model=model)
    reviewer = ReviewerAgent(llm_client, model=model)

    # ------------------------------------------------------------------
    # Step 1: Planner makes architectural decisions
    # In a real parallel system the Coder would already be starting here.
    # We model this by NOT passing planner_result to the Coder.
    # ------------------------------------------------------------------
    divider("STEP 1 — Planner")
    t0 = time.time()
    planner_result = planner.plan_naive(task)
    t_plan = time.time() - t0
    info(f"Planner finished in {t_plan:.1f}s")

    warning(
        "In a parallel run the Coder is already running. "
        "Even in sequential simulation, the Planner's decisions are NOT forwarded."
    )

    # ------------------------------------------------------------------
    # Step 2: Coder implements — no awareness of Planner's decisions
    # ------------------------------------------------------------------
    divider("STEP 2 — Coder")
    t1 = time.time()
    coder_result = coder.implement_naive(task, planner_context=None)
    t_code = time.time() - t1
    info(f"Coder finished in {t_code:.1f}s")

    # Check overlap: did the Coder build something the Planner deprecated?
    deprecated = {d.split("—")[0].strip().lower() for d in planner_result["decisions"]["deprecate"]}
    built = {m.lower() for m in coder_result["implementing"]}
    collision_candidates = deprecated & built

    if collision_candidates:
        warning(
            f"Coder built modules that Planner deprecated: {', '.join(collision_candidates)}\n"
            "  This work is now wasted — but the Coder had no way to know."
        )

    # ------------------------------------------------------------------
    # Step 3: Reviewer detects the conflict — after the fact
    # ------------------------------------------------------------------
    divider("STEP 3 — Reviewer")
    t2 = time.time()
    reviewer_result = reviewer.review_naive(task, planner_result, coder_result)
    t_review = time.time() - t2
    info(f"Reviewer finished in {t_review:.1f}s")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    divider("RUN SUMMARY")
    total = t_plan + t_code + t_review
    info(f"Total compute time  : {total:.1f}s")
    info(f"Conflict detected   : {'YES — after the fact' if reviewer_result['status'] == 'CONFLICT' else 'NO'}")
    info(f"Wasted compute      : ~{t_code:.1f}s (Coder rebuilt deprecated module)")
    info(f"Audit trail         : None — no shared timeline exists")

    return {
        "run_id": run_id,
        "mode": "naive",
        "task": task,
        "planner": planner_result,
        "coder": coder_result,
        "reviewer": reviewer_result,
        "deprecated_rebuilt": len(collision_candidates),
        "timing": {"plan": t_plan, "code": t_code, "review": t_review, "total": total},
    }
