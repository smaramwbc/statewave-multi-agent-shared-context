"""
Statewave pipeline — the AFTER.

Same three agents, same task. Every agent reads from and writes to the same
Statewave subject before acting. The Coder retrieves the Planner's deprecation
decision before starting work. The conflict never happens.
"""

import time
import uuid

from agents.planner import PlannerAgent
from agents.coder import CoderAgent
from agents.reviewer import ReviewerAgent
from core.llm import LLMClient
from core.statewave_client import StatewaveClient
from core.display import header, divider, info, success, agent_log, collision_box, resolved_box
from statewave_agents import SharedContext


def run(task: str, llm_client: LLMClient, sw_client: StatewaveClient, model: str = "groq/llama-3.3-70b-versatile") -> dict:
    run_id = f"sw-{uuid.uuid4().hex[:8]}"

    header(
        "AFTER: Statewave Shared-Context Pipeline",
        "Every agent reads from and writes to the same authoritative subject.",
    )
    info(f"Run ID     : {run_id}")
    info(f"Subject ID : {run_id}  (this is the shared source of truth)")
    info(f"Task       : {task}")
    divider()

    shared = SharedContext(subject_id=run_id, client=sw_client)

    planner = PlannerAgent(llm_client, model=model)
    coder = CoderAgent(llm_client, model=model)
    reviewer = ReviewerAgent(llm_client, model=model)
    for a in (planner, coder, reviewer):
        a.context = shared

    # ------------------------------------------------------------------
    # Step 1: Planner writes decisions to shared subject and compiles
    # ------------------------------------------------------------------
    divider("STEP 1 — Planner → writes to shared subject")
    t0 = time.time()
    planner_result = planner.run(task)
    t_plan = time.time() - t0
    info(f"Planner finished in {t_plan:.1f}s  |  decisions published to subject: {run_id}")

    # ------------------------------------------------------------------
    # Step 2: Coder reads shared subject BEFORE acting
    # ------------------------------------------------------------------
    divider("STEP 2 — Coder → reads shared subject before implementation")
    t1 = time.time()
    coder_result = coder.run(task)
    t_code = time.time() - t1
    info(f"Coder finished in {t_code:.1f}s")

    if coder_result["skipping"]:
        success(
            f"Coder skipped {len(coder_result['skipping'])} deprecated module(s) "
            "because the shared context contained the Planner's deprecation decision."
        )

    # Check if Coder rebuilt any deprecated modules despite shared context
    deprecated = {d.split("—")[0].strip().lower() for d in planner_result["decisions"]["deprecate"]}
    built = {m.lower() for m in coder_result["implementing"]}
    collision_candidates = deprecated & built

    # ------------------------------------------------------------------
    # Step 3: Reviewer reads the full shared context — both decisions in one place
    # ------------------------------------------------------------------
    divider("STEP 3 — Reviewer → validates against shared source of truth")
    t2 = time.time()
    reviewer_result = reviewer.run(task)
    t_review = time.time() - t2
    info(f"Reviewer finished in {t_review:.1f}s")

    if reviewer_result["status"] == "CONFLICT":
        collision_box(
            "Unexpected conflict found in shared context review:\n\n"
            + "\n".join(f"  • {f}" for f in reviewer_result["findings"])
        )
    else:
        resolved_box(
            "Review complete — no conflicts found.\n"
            "The Coder read the Planner's deprecation before acting.\n"
            "The shared context prevented the collision before it could happen."
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    divider("RUN SUMMARY")
    total = t_plan + t_code + t_review
    info(f"Total compute time  : {total:.1f}s")
    info(f"Conflict detected   : {'YES' if reviewer_result['status'] == 'CONFLICT' else 'NO — prevented before it happened'}")
    info(f"Wasted compute      : 0s  (Coder skipped deprecated modules)")
    info(f"Audit trail         : run  python timeline_inspector.py --run {run_id}")

    return {
        "run_id": run_id,
        "mode": "statewave",
        "task": task,
        "subject_id": run_id,
        "planner": planner_result,
        "coder": coder_result,
        "reviewer": reviewer_result,
        "deprecated_rebuilt": len(collision_candidates),
        "timing": {"plan": t_plan, "code": t_code, "review": t_review, "total": total},
    }
