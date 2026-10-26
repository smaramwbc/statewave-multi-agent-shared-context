"""
Timeline inspector — python timeline_inspector.py --run <run_id>

Prints the full chronological shared context for a Statewave run:
  - Who wrote what, and when
  - What each agent retrieved when it called GET /v1/context
  - The final compiled memory state

This is the audit artifact that does not exist in any message-passing setup.
"""

import argparse
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from core.statewave_client import StatewaveClient
from core.display import header, divider, info, error
from statewave_agents.context import reads_subject_id

console = Console()


def _ts(epoch: float | None) -> str:
    if not epoch:
        return "—"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3] + "Z"


def _relative(base: float, t: float) -> str:
    delta = t - base
    return f"T+{delta:.1f}s"


def _agent_style(caller: str) -> str:
    return {
        "Planner": "bold magenta",
        "Coder": "bold blue",
        "Reviewer": "bold yellow",
    }.get(caller, "white")


def print_timeline(run_id: str, sw_client: StatewaveClient) -> None:
    header(
        f"Shared Timeline — Run {run_id}",
        "Chronological audit trail of every agent decision and context retrieval.",
    )

    try:
        data = sw_client.get_timeline(run_id)
        reads = sw_client.get_timeline(reads_subject_id(run_id))
    except Exception as exc:
        error(f"Failed to fetch timeline for run '{run_id}': {exc}")
        sys.exit(1)

    events = data.get("events", []) + reads.get("events", [])
    memories = data.get("memories", [])

    if not events:
        info("No events found for this run ID. Check that the run completed successfully.")
        return

    # Find the earliest timestamp to compute relative times
    timestamps = [e.get("timestamp") for e in events if e.get("timestamp")]
    base_ts = min(timestamps) if timestamps else 0.0

    # ------------------------------------------------------------------
    # Section 1: Chronological event log
    # ------------------------------------------------------------------
    divider("CHRONOLOGICAL EVENT LOG")

    table = Table(
        show_header=True,
        header_style="bold white",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
        expand=True,
    )
    table.add_column("Time (UTC)", style="dim", width=14)
    table.add_column("Relative", style="dim", width=8)
    table.add_column("Agent", width=10)
    table.add_column("Event Type", width=22)
    table.add_column("Content", ratio=1)

    for event in sorted(events, key=lambda e: e.get("timestamp", 0)):
        caller = event.get("caller_id", "unknown")
        ts = event.get("timestamp")
        evt_type = event.get("type", "event")
        content = event.get("content", "")

        table.add_row(
            _ts(ts),
            _relative(base_ts, ts) if ts else "—",
            Text(caller, style=_agent_style(caller)),
            Text(evt_type, style="cyan"),
            content[:200] + ("…" if len(content) > 200 else ""),
        )

    console.print(table)

    # ------------------------------------------------------------------
    # Section 2: What each agent knew when it called GET /v1/context
    # ------------------------------------------------------------------
    context_retrievals = [e for e in events if e.get("type") == "context_retrieval"]
    if context_retrievals:
        divider("AGENT CONTEXT RETRIEVALS")
        for cr in sorted(context_retrievals, key=lambda e: e.get("timestamp", 0)):
            caller = cr.get("caller_id", "unknown")
            ts = cr.get("timestamp")
            retrieved = cr.get("retrieved_memories", [])
            rel = _relative(base_ts, ts) if ts else "—"

            console.print(
                Panel(
                    "\n".join(
                        f"  [{m.get('type', '?')}] (confidence {m.get('confidence', 0):.2f})  {m.get('content', '')[:160]}"
                        for m in retrieved
                    )
                    or "  (no memories retrieved)",
                    title=f"[{_agent_style(caller)}]{caller}[/{_agent_style(caller)}] retrieved context at {_ts(ts)} ({rel})",
                    border_style="dim",
                )
            )

    # ------------------------------------------------------------------
    # Section 3: Final compiled memory state
    # ------------------------------------------------------------------
    if memories:
        divider("FINAL COMPILED MEMORY STATE")

        mem_table = Table(
            show_header=True,
            header_style="bold white",
            box=box.SIMPLE_HEAVY,
            show_lines=True,
            expand=True,
        )
        mem_table.add_column("Memory Type", width=22)
        mem_table.add_column("Written By", width=12)
        mem_table.add_column("Confidence", width=12)
        mem_table.add_column("Status", width=12)
        mem_table.add_column("Content", ratio=1)

        for mem in memories:
            status = mem.get("status", "active")
            status_style = "dim" if status == "superseded" else "green"
            mem_table.add_row(
                Text(mem.get("type", "memory"), style="cyan"),
                Text(mem.get("caller_id", "—"), style=_agent_style(mem.get("caller_id", ""))),
                f"{mem.get('confidence', 0):.2f}",
                Text(status, style=status_style),
                mem.get("content", "")[:200],
            )

        console.print(mem_table)

    # ------------------------------------------------------------------
    # Section 4: Summary
    # ------------------------------------------------------------------
    divider("SUMMARY")
    agents_seen = sorted({e.get("caller_id") for e in events if e.get("caller_id")})
    writes = [e for e in events if e.get("type") in ("architectural_decision", "implementation_note", "review_finding")]
    reads = context_retrievals

    info(f"Run ID          : {run_id}")
    info(f"Agents active   : {', '.join(agents_seen)}")
    info(f"Episodes written: {len(writes)}")
    info(f"Context reads   : {len(reads)}")
    info(f"Memories stored : {len(memories)}")
    info(f"Superseded      : {sum(1 for m in memories if m.get('status') == 'superseded')}")

    console.print()
    console.print(
        "[dim]Every agent's decision traced to its source. "
        "This audit trail does not exist in any message-passing setup.[/dim]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect the shared timeline for a Statewave multi-agent run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python timeline_inspector.py --run sw-abc12345
  python timeline_inspector.py --run sw-abc12345 --api-key sw-your-key
        """,
    )
    parser.add_argument("--run", required=True, metavar="RUN_ID", help="Statewave subject / run ID to inspect")
    parser.add_argument("--api-key", default=None, help="Statewave API key (overrides STATEWAVE_API_KEY env var)")
    parser.add_argument("--base-url", default=None, help="Statewave base URL (overrides STATEWAVE_BASE_URL env var)")

    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    sw_client = StatewaveClient(api_key=args.api_key, base_url=args.base_url)

    print_timeline(args.run, sw_client)


if __name__ == "__main__":
    main()
