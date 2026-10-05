"""
main.py — CLI entrypoint for the statewave-multi-agent-shared-context demo.

Usage:
  python main.py                          # run both pipelines with default task
  python main.py --mode naive             # run only the naive (before) pipeline
  python main.py --mode statewave         # run only the Statewave (after) pipeline
  python main.py --mode both              # run both and compare (default)
  python main.py --task "your task here"  # custom task description
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from rich.console import Console

from core.display import divider, info, error
from core.llm import LLMClient
from core.statewave_client import StatewaveClient

console = Console()

DEFAULT_TASK = (
    "Build a user authentication service. "
    "The legacy session-token module must be deprecated in favour of JWT. "
    "Implement login, logout, token refresh, and role-based access control."
)

load_dotenv()

# LLM calls go through LiteLLM (https://docs.litellm.ai) — provider-agnostic.
# Set LLM_API_KEY and (optionally) LLM_MODEL as "<provider>/<model>" in .env.
# Default is Groq's free tier. Get a key at https://console.groq.com/keys
_LLM_MODEL = os.getenv("LLM_MODEL", "groq/llama-3.3-70b-versatile")


def _build_llm_client() -> LLMClient:
    if not os.environ.get("LLM_API_KEY"):
        error("No LLM API key found. Set LLM_API_KEY in .env")
        sys.exit(1)
    return LLMClient()


def _build_sw_client() -> StatewaveClient:
    return StatewaveClient()


def run_naive(task: str) -> dict:
    from pipeline_naive import run
    return run(task, llm_client=_build_llm_client(), model=_LLM_MODEL)


def run_statewave(task: str) -> dict:
    from pipeline_statewave import run
    return run(
        task,
        llm_client=_build_llm_client(),
        sw_client=_build_sw_client(),
        model=_LLM_MODEL,
    )


def compare(naive_result: dict, sw_result: dict) -> None:
    divider("BEFORE vs AFTER COMPARISON")

    naive_timing = naive_result["timing"]["total"]
    sw_timing = sw_result["timing"]["total"]
    naive_conflict = naive_result["reviewer"]["status"] == "CONFLICT"
    sw_conflict = sw_result["reviewer"]["status"] == "CONFLICT"
    naive_skipped = len(naive_result["coder"]["skipping"])
    sw_skipped = len(sw_result["coder"].get("skipping", []))

    rows = [
        ("Conflict detected",    "YES (after the fact)" if naive_conflict else "NO",   "NO — prevented before it happened" if not sw_conflict else "YES"),
        ("Deprecated modules rebuilt", str(len(naive_result["coder"]["implementing"])), str(len(sw_result["coder"]["implementing"]) - sw_skipped if sw_skipped else "0")),
        ("Modules skipped (saved)",    str(naive_skipped),                             str(sw_skipped)),
        ("Total compute time",  f"{naive_timing:.1f}s",                                f"{sw_timing:.1f}s"),
        ("Audit trail",         "None",                                                 f"python timeline_inspector.py --run {sw_result['run_id']}"),
        ("Shared context",      "No",                                                   "Yes — Statewave subject"),
    ]

    console.print()
    console.print(f"  {'Metric':<30}  {'BEFORE (naive)':<35}  {'AFTER (Statewave)'}")
    console.print(f"  {'─' * 30}  {'─' * 35}  {'─' * 35}")
    for label, before, after in rows:
        console.print(f"  [dim]{label:<30}[/dim]  {before:<35}  [green]{after}[/green]")
    console.print()


def main() -> None:

    parser = argparse.ArgumentParser(
        description="statewave-multi-agent-shared-context demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  naive      The BEFORE: agents work from individual prompt contexts.
             Planner deprecates a module; Coder unknowingly rebuilds it;
             Reviewer catches the conflict only after both agents finish.

  statewave  The AFTER: every agent reads from and writes to the same
             Statewave subject. Coder reads the deprecation before acting.
             The conflict never happens.

  both       Run both pipelines on the same task and print a side-by-side
             comparison (default).

Examples:
  python main.py
  python main.py --mode naive
  python main.py --mode statewave
  python main.py --task "Build a payment processing service. Deprecate the legacy Stripe v1 module."
  python timeline_inspector.py --run sw-abc12345
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["naive", "statewave", "both"],
        default="both",
        help="Which pipeline to run (default: both)",
    )
    parser.add_argument(
        "--task",
        default=DEFAULT_TASK,
        help="Task description for all agents",
    )

    args = parser.parse_args()

    if args.mode == "naive":
        run_naive(args.task)

    elif args.mode == "statewave":
        run_statewave(args.task)

    else:  # both
        info("Running BEFORE pipeline first...")
        divider()
        naive_result = run_naive(args.task)

        console.print()
        info("Running AFTER pipeline second...")
        divider()
        sw_result = run_statewave(args.task)

        compare(naive_result, sw_result)


if __name__ == "__main__":
    main()
