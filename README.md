# statewave-multi-agent-shared-context

**Multiple agents, one source of truth.**

![Multi-agent shared context banner](docs/images/multi%20agent%20shared.png)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](#requirements)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green)](#license)

> **Part of [Statewave](https://github.com/smaramwbc/statewave)** — the open-source memory runtime for AI agents.
>
> 📦 [Core runtime](https://github.com/smaramwbc/statewave) · 🐍 [Python SDK](https://github.com/smaramwbc/statewave-py) · 🟦 [TypeScript SDK](https://github.com/smaramwbc/statewave-ts) · 🔌 [Connectors](https://github.com/smaramwbc/statewave-connectors) · 📘 [Docs](https://github.com/smaramwbc/statewave-docs) · 💡 [Examples](https://github.com/smaramwbc/statewave-examples) · 🖥️ [Admin](https://github.com/smaramwbc/statewave-admin) · 🌐 [statewave.ai](https://statewave.ai)
>
> 📋 **Issues & feature requests:** [statewave/issues](https://github.com/smaramwbc/statewave/issues) (centralized tracker)

Parallel agents that read from and write to the same authoritative context layer stop contradicting each other before the conflict happens.

## Table of Contents

- [statewave-multi-agent-shared-context](#statewave-multi-agent-shared-context)
  - [Table of Contents](#table-of-contents)
  - [The Problem](#the-problem)
  - [The Fix](#the-fix)
  - [How It Works](#how-it-works)
  - [What This Repo Builds](#what-this-repo-builds)
  - [The Three Demo Moments](#the-three-demo-moments)
    - [1. The Collision (Before)](#1-the-collision-before)
    - [2. No Collision (After)](#2-no-collision-after)
    - [3. The Shared Timeline](#3-the-shared-timeline)
  - [Screenshots](#screenshots)
  - [Requirements](#requirements)
  - [Stack](#stack)
  - [Quickstart](#quickstart)
    - [1. Start Statewave locally](#1-start-statewave-locally)
    - [2. Clone and install this demo](#2-clone-and-install-this-demo)
    - [3. Configure credentials](#3-configure-credentials)
    - [4. Run the demo](#4-run-the-demo)
  - [Project Structure](#project-structure)
  - [How Statewave Integrates](#how-statewave-integrates)
  - [Troubleshooting](#troubleshooting)
  - [Why Not AutoGen / LangGraph?](#why-not-autogen--langgraph)
  - [License](#license)

---

## The Problem

In a naive parallel agent system, the Planner makes an architectural decision (e.g. *deprecate the legacy session-token module*) and writes it into its own context. The Coder starts work simultaneously and never sees that decision. The Coder rebuilds the deprecated module from scratch. The Reviewer catches the conflict only after both agents have finished  too late to prevent the wasted compute.

This is a documented real failure mode in production parallel agent systems. It happens because agents pass context through messages, not through a shared persistent layer.

## The Fix

[Statewave](https://statewave.ai) gives every agent in the fleet a shared **subject** (the run ID). Decisions are written as **episodes** and compiled into **typed memories** that every agent reads before acting.

- The Coder reads the Planner's deprecation before starting work.
- The conflict never happens.
- The full decision chain is reconstructable from `GET /v1/timeline`.

---

## How It Works

Statewave is a shared memory store that sits between agents instead of agents passing messages to each other directly. Every agent in a run reads from and writes to the same **subject** (identified by the run ID), so "did someone already decide this?" is a lookup, not a guess.

![Architecture diagram  Planner, Coder, and Reviewer all reading from and writing to the same Statewave subject, contrasted with the naive before/after outcome](docs/images/architecture.svg)

The data model is three layers:

1. **Episode**  a raw fact an agent records, e.g. *"Planner decided to deprecate legacy-session-token."* Written with `sw_client.write_episode(...)` → SDK `create_episode()`. Cheap, append-only, no interpretation yet.
2. **Compile**  turns freshly written episodes into retrievable memories. Called with `sw_client.compile(...)` → SDK `compile_memories_wait()`. This step exists because a raw episode isn't searchable/rankable until it's compiled  skipping it is what causes stale reads.
3. **Memory**  a typed, confidence-scored, queryable fact derived from one or more episodes (e.g. `architectural_decision`, confidence `0.92`). Other agents pull relevant memories with `sw_client.get_context(...)` → SDK `get_context()`, which returns the memories ranked for their specific task.

Concretely, in this repo's `--mode statewave` pipeline ([pipeline_statewave.py](pipeline_statewave.py)):

```
Planner
  → decides to deprecate legacy-session-token
  → write_episode(type="architectural_decision", content="Deprecation: legacy-session-token")
  → compile(subject_id)                      # decision is now readable by anyone

Coder
  → get_context(subject_id, task="implement feature: ...")   # BEFORE writing any code
  → sees the deprecation memory in the returned context
  → skips legacy-session-token, builds jwt-auth instead
  → write_episode(type="implementation_note", ...)
  → compile(subject_id)

Reviewer
  → get_context(subject_id, task="review implementation: ...")
  → cross-checks Planner's decisions against Coder's output
  → finds no conflict, because the Coder already had the decision
```

This is why the collision is *prevented* rather than *detected*: the Coder's context read happens before it decides what to build, not after. In the naive pipeline ([pipeline_naive.py](pipeline_naive.py)), there is no equivalent read  the Coder only ever sees the original task string, so it has no way to know the Planner already made a decision that invalidates part of its plan.

The full episode → compile → memory chain for a run is auditable end-to-end with `python timeline_inspector.py --run <id>`  see [The Shared Timeline](#3-the-shared-timeline) below.

---

## What This Repo Builds

A three-agent Python CLI running a simulated software development task:

| Agent    | Role                                      |
|----------|-------------------------------------------|
| Planner  | Makes architectural decisions, including deprecations |
| Coder    | Implements features                        |
| Reviewer | Validates output against the source of truth |

The demo runs **two pipelines** on the same task:

1. **BEFORE** (`--mode naive`)  agents use message-passing only. Collision happens.
2. **AFTER** (`--mode statewave`)  agents share a Statewave subject. Collision is prevented.

A third command, `python timeline_inspector.py --run <id>`, prints the full chronological audit trail for the Statewave run  what each agent knew when it acted, what it wrote, and the final memory state.

---

## The Three Demo Moments

### 1. The Collision (Before)

```
[Planner]  DEPRECATING → legacy-session-token module  replaced by JWT
[Coder]    No shared context available  working from task description only.
[Coder]    → legacy-session-token module
[Coder]    → jwt-auth module
[Reviewer] ╔══ COLLISION DETECTED ═══════════════════════════════════════╗
           ║ Conflict detected  but both agents have already completed  ║
           ║ their work. Wasted compute cannot be recovered.             ║
           ╚════════════════════════════════════════════════════════════╝
```

### 2. No Collision (After)

```
[Planner]  DEPRECATING → legacy-session-token module  replaced by JWT
[Planner]  Compiling episodes → making decisions available to all agents now...
[Coder]    Reading shared context before starting implementation...
[Coder]    [architectural_decision] (confidence 0.92) Deprecation: legacy-session-token
[Coder]    Skipping → legacy-session-token module (deprecated by Planner: use JWT)
[Reviewer] ╔══ CONFLICT AVOIDED ═════════════════════════════════════════╗
           ║ Review complete  no conflicts found.                       ║
           ║ The Coder read the Planner's deprecation before acting.     ║
           ╚════════════════════════════════════════════════════════════╝
```

### 3. The Shared Timeline

```
$ python timeline_inspector.py --run sw-abc12345

  Time (UTC)    Relative  Agent     Event Type               Content
  ──────────────────────────────────────────────────────────────────────
  14:01:00Z     T+0.0s    Planner   architectural_decision   Deprecation: legacy-session-token...
  14:01:12Z     T+12.1s   Planner   compile                  Memory compilation triggered
  14:01:15Z     T+15.3s   Coder     context_retrieval        Retrieved 2 memories (incl. deprecation)
  14:05:00Z     T+4m0s    Coder     implementation_note      Built: jwt-auth, rbac, login, logout
  14:05:30Z     T+4m30s   Reviewer  context_retrieval        Retrieved 4 memories
  14:05:45Z     T+4m45s   Reviewer  review_finding           STATUS: CLEAN
```

---

## Screenshots

The architecture diagram in [How It Works](#how-it-works) ([docs/images/architecture.svg](docs/images/architecture.svg)) is the canonical visual for this repo  it's an SVG built in Statewave's own dark indigo/violet theme (matching the banner above), so it stays crisp at any size and is easy to edit as a text file if the pipeline changes.

Additional demo screenshots and recordings live in [docs/images/](docs/images/). To add one:

1. Drop the image file into `docs/images/` (e.g. `docs/images/collision-detected.png`).
2. Reference it from this README with `![alt text](docs/images/your-file.png)`  see the banner image at the top of this file for the exact syntax (spaces in filenames must be URL-encoded as `%20`).
3. For terminal output specifically, prefer pasting the raw text in a fenced code block (as in [The Three Demo Moments](#the-three-demo-moments)) over a screenshot  it stays copy-pasteable and diffable, and doesn't go stale if `core/display.py` styling changes.

---

## Requirements

- **Python 3.11+**
- **Node.js** (for `npx @statewavedev/statewave`) or Docker, if self-hosting Statewave
- An **LLM provider API key**  the demo calls the model through [LiteLLM](https://docs.litellm.ai), so any supported provider works. The default is **Groq** (generous free tier)  get a key at [console.groq.com/keys](https://console.groq.com/keys)

## Stack

- **[LiteLLM](https://docs.litellm.ai)**  provider-agnostic LLM calls. Default model: `groq/llama-3.3-70b-versatile`. Point it at any provider by setting `LLM_MODEL` to `<provider>/<model>` (e.g. `openai/gpt-4o-mini`, `anthropic/claude-3-5-haiku-20241022`, `ollama/llama3`). Wrapped in [core/llm.py](core/llm.py).
- **Statewave** (official [`statewave`](https://pypi.org/project/statewave/) Python SDK)  shared context layer (episodes, compiled memories, timeline). See [core/statewave_client.py](core/statewave_client.py).
- **Rich**  terminal output

---

## Quickstart

### 1. Start Statewave locally

Statewave is self-hosted. Boot it with one command  it starts the API + Postgres via Docker:

```bash
# macOS / Linux
npx @statewavedev/statewave

# Windows (PowerShell)
irm https://www.statewave.ai/install.ps1 | iex
```

The API will be available at `http://localhost:8100`. No account or API key required.

### 2. Clone and install this demo

```bash
git clone https://github.com/smaramwbc/statewave-multi-agent-shared-context
cd statewave-multi-agent-shared-context
pip install -r requirements.txt
```

### 3. Configure credentials

```bash
cp .env.example .env
# Edit .env  add your LLM_API_KEY (free Groq key: https://console.groq.com/keys)
# STATEWAVE_BASE_URL defaults to http://localhost:8100  no changes needed
```

### 4. Run the demo

```bash
# Full before/after comparison (default)
python main.py

# Only the naive pipeline
python main.py --mode naive

# Only the Statewave pipeline
python main.py --mode statewave

# Custom task
python main.py --task "Build a payment service. Deprecate legacy Stripe v1 module."

# Inspect the shared timeline of a completed run
python timeline_inspector.py --run sw-abc12345
```

---

## Project Structure

```
statewave-multi-agent-shared-context/
├── main.py                    # CLI entrypoint  orchestrates both pipelines
├── timeline_inspector.py      # Timeline inspector command
├── pipeline_naive.py          # BEFORE: agents use message-passing only
├── pipeline_statewave.py      # AFTER: agents share a Statewave subject
├── agents/
│   ├── planner.py             # Planner agent (naive + Statewave modes)
│   ├── coder.py               # Coder agent (naive + Statewave modes)
│   └── reviewer.py            # Reviewer agent (naive + Statewave modes)
├── core/
│   ├── statewave_client.py    # Adapter over the official statewave SDK
│   ├── llm.py                 # LiteLLM-backed client (OpenAI-style call surface)
│   └── display.py             # Rich-based terminal helpers
├── statewave_agents/          # Reusable SharedContext primitive (framework-agnostic)
│   ├── context.py             # SharedContext: before_acting() / decide()
│   └── agent.py               # Base Agent class
├── requirements.txt
└── .env.example
```

---

## How Statewave Integrates

All Statewave calls go through the official [`statewave`](https://pypi.org/project/statewave/) Python SDK, wrapped by [core/statewave_client.py](core/statewave_client.py)  no hand-rolled HTTP.

| Operation | SDK method | When |
|-----------|------------|------|
| Write decision | `create_episode()` | After every Planner decision |
| Compile | `compile_memories_wait()` | Immediately after writing  makes memories available (handles multi-batch draining) |
| Read context | `get_context()` | Before any agent acts |
| Inspect timeline | `get_timeline()` | Audit / `timeline_inspector.py` |

Every call includes a `caller_id` so the full decision chain is attributable per agent.

---

## Troubleshooting

**`litellm.AuthenticationError`**
Your `LLM_API_KEY` is missing or doesn't match the provider in `LLM_MODEL`. The key must belong to the provider prefix  a Groq key for `groq/...`, an OpenAI key for `openai/...`, and so on.

**`litellm.BadRequestError` / "LLM Provider NOT provided" / model not found**
`LLM_MODEL` must be a fully-qualified `<provider>/<model>` string (e.g. `groq/llama-3.3-70b-versatile`), not a bare model name. See [LiteLLM's provider list](https://docs.litellm.ai/docs/providers).

**`UnicodeEncodeError` on Windows (`'charmap' codec can't encode character '→'`)**
The default Windows console encoding (cp1252) can't render the Unicode arrows used in `core/display.py`. Run with UTF-8 forced:
```powershell
$env:PYTHONIOENCODING = "utf-8"; python main.py
```

**Connection refused on `localhost:8100`**
The Statewave server isn't running. See [Quickstart step 1](#1-start-statewave-locally).

---

## Why Not AutoGen / LangGraph?

AutoGen group chat and LangGraph hierarchical agent tutorials both route context through **messages**. Messages pass state forward sequentially. They do not give every agent access to the same authoritative source at all times.

- In a sequential pipeline, message-passing works because agents take turns.
- In a parallel pipeline, there is no turn order. By the time a message could be sent, the receiving agent has already started  or finished.

Statewave replaces the coordination layer with a shared read/write surface. No wiring. No quadratic message overhead. Every agent reads the same truth.

Statewave is self-hosted  there is no managed cloud API. See [Quickstart step 1](#1-start-statewave-locally) to run it locally. Docs at `http://localhost:8100/docs` once running. Source: [github.com/smaramwbc/statewave](https://github.com/smaramwbc/statewave).

---

## Integrating With Other Agent Frameworks

The coordination primitive in this repo isn't tied to `agents/*.py`  it's [`SharedContext`](statewave_agents/context.py), which only needs two calls around whatever an agent already does:

- `context.before_acting(caller_id, task)`  call before the agent decides anything, to see what other agents have already decided.
- `context.decide(caller_id, content, kind=...)`  call after the agent produces a decision, to publish it for everyone else.

Any framework's agent loop can wrap around those two calls. `caller_id` and `subject_id` (the run/session id) are the only two ideas you need to carry over.

### CrewAI

Expose the same primitive as a CrewAI `Tool` so any Crew agent can read/write the shared subject as part of its normal tool-calling loop:

```python
from crewai import Agent, Crew, Task
from crewai.tools import tool
from statewave_agents.context import SharedContext

shared = SharedContext(subject_id="crew-run-001")

@tool("check_shared_decisions")
def check_shared_decisions(task_description: str) -> str:
    """Look up what other agents in this crew have already decided before you act."""
    bundle = shared.before_acting(caller_id="crew-agent", task=task_description)
    return bundle.assembled_context or "No prior decisions yet."

@tool("publish_decision")
def publish_decision(decision: str, kind: str = "decision") -> str:
    """Publish a decision so every other agent in this crew can see it."""
    shared.decide(caller_id="crew-agent", content=decision, kind=kind)
    return "Published."

planner = Agent(role="Planner", goal="...", tools=[check_shared_decisions, publish_decision])
coder = Agent(role="Coder", goal="...", tools=[check_shared_decisions, publish_decision])

Crew(agents=[planner, coder], tasks=[...]).kickoff()
```

Give every agent in the crew both tools and the same `subject_id`  CrewAI still owns task sequencing, Statewave owns "does anyone already know this."

### Claude Agent SDK

Register the same two operations as SDK tools so any Claude agent can call them mid-turn:

```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient
from statewave_agents.context import SharedContext

shared = SharedContext(subject_id="claude-run-001")

@tool("check_shared_decisions", "Look up what other agents have already decided", {"task": str})
async def check_shared_decisions(args):
    bundle = shared.before_acting(caller_id="claude-agent", task=args["task"])
    return {"content": [{"type": "text", "text": bundle.assembled_context or "No prior decisions yet."}]}

@tool("publish_decision", "Publish a decision for other agents to see", {"decision": str, "kind": str})
async def publish_decision(args):
    shared.decide(caller_id="claude-agent", content=args["decision"], kind=args.get("kind", "decision"))
    return {"content": [{"type": "text", "text": "Published."}]}

server = create_sdk_mcp_server(name="shared-context", tools=[check_shared_decisions, publish_decision])
options = ClaudeAgentOptions(mcp_servers={"shared-context": server})

async with ClaudeSDKClient(options=options) as client:
    await client.query("Implement the login endpoint.")
```

Run one Claude agent per role, all pointed at the same MCP server instance (same `subject_id`) so they read/write the same subject.

### Any other framework or custom harness (LangGraph, AutoGen, a hand-rolled loop, etc.)

There's no SDK-specific step required  every framework's agent has *some* point where it's about to act and some point where it produces output. Hook `SharedContext` in at exactly those two points:

```python
from statewave_agents.context import SharedContext

shared = SharedContext(subject_id=run_id)

def run_my_agent(caller_id: str, task: str):
    bundle = shared.before_acting(caller_id, task)          # 1. read before acting
    result = my_framework_agent.run(task, extra_context=bundle.assembled_context)
    shared.decide(caller_id, result.decision, kind=result.kind)  # 2. write after acting
    return result
```

The only requirement: every agent in a run must share the same `subject_id`, and every write must happen before the next agent's read for the read to matter  the ordering guarantee, not the framework, is what prevents the collision.

---

## License

Apache 2.0  see [LICENSE](LICENSE).
