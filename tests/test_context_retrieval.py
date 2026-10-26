"""Tests for recording context retrievals and showing them in the timeline (#485)."""

import io
from unittest import TestCase
from unittest.mock import patch

from rich.console import Console

import timeline_inspector
from statewave_agents.context import SharedContext, reads_subject_id


class FakeClient:
    def __init__(self, context: dict | None = None, timelines: dict | None = None):
        self.context = context or {}
        self.timelines = timelines or {}
        self.episodes: list[dict] = []
        self.compiled: list[str] = []

    def get_context(self, **kwargs) -> dict:
        return self.context

    def write_episode(self, **kwargs) -> dict:
        self.episodes.append(kwargs)
        return {}

    def compile(self, subject_id: str) -> dict:
        self.compiled.append(subject_id)
        return {}

    def get_timeline(self, subject_id: str) -> dict:
        return self.timelines.get(subject_id, {"events": [], "memories": []})


class BeforeActingTests(TestCase):
    def test_records_retrieval_in_reads_subject_without_compiling(self):
        client = FakeClient(
            context={
                "assembled_context": "Deprecation: legacy-session-token",
                "memories": [
                    {
                        "kind": "episode_summary",
                        "confidence": 0.8,
                        "content": "Deprecation: legacy-session-token",
                    }
                ],
            }
        )
        ctx = SharedContext(subject_id="sw-test", client=client)

        bundle = ctx.before_acting("Coder", "Build auth")

        self.assertEqual(len(bundle.memories), 1)
        self.assertEqual(len(client.episodes), 1)
        episode = client.episodes[0]
        self.assertEqual(episode["subject_id"], reads_subject_id("sw-test"))
        self.assertEqual(episode["caller_id"], "Coder")
        self.assertEqual(episode["episode_type"], "context_retrieval")
        self.assertEqual(episode["content"], "Retrieved 1 memories (incl. deprecation)")
        self.assertEqual(
            episode["metadata"]["retrieved_memories"],
            [
                {
                    "type": "episode_summary",
                    "confidence": 0.8,
                    "content": "Deprecation: legacy-session-token",
                }
            ],
        )
        self.assertEqual(client.compiled, [])

    def test_summary_omits_deprecation_note_when_none_retrieved(self):
        client = FakeClient(
            context={
                "memories": [
                    {"kind": "episode_summary", "confidence": 0.8, "content": "Built: jwt-auth"},
                    {"kind": "episode_summary", "confidence": 0.8, "content": "STATUS: CLEAN"},
                ],
            }
        )
        ctx = SharedContext(subject_id="sw-test", client=client)

        ctx.before_acting("Reviewer", "Review the build")

        self.assertEqual(client.episodes[0]["content"], "Retrieved 2 memories")


    def test_each_read_records_its_own_episode(self):
        client = FakeClient(context={"memories": []})
        ctx = SharedContext(subject_id="sw-test", client=client)

        ctx.before_acting("Coder", "Build auth")
        ctx.before_acting("Reviewer", "Review the build")
        ctx.before_acting("Coder", "Build auth, take two")

        self.assertEqual(len(client.episodes), 3)
        self.assertEqual(
            [e["caller_id"] for e in client.episodes], ["Coder", "Reviewer", "Coder"]
        )
        self.assertEqual(
            {e["subject_id"] for e in client.episodes}, {reads_subject_id("sw-test")}
        )


class TimelineInspectorTests(TestCase):
    def test_shows_retrievals_from_reads_subject(self):
        retrieval = {
            "type": "context_retrieval",
            "content": "Retrieved 1 memories (incl. deprecation)",
            "retrieved_memories": [
                {"type": "episode_summary", "confidence": 0.8, "content": "Deprecation"}
            ],
        }
        client = FakeClient(
            timelines={
                "sw-test": {
                    "events": [
                        {
                            "caller_id": "Planner",
                            "timestamp": 1.0,
                            "type": "architectural_decision",
                            "content": "Deprecation",
                        }
                    ],
                    "memories": [],
                },
                reads_subject_id("sw-test"): {
                    "events": [
                        {**retrieval, "caller_id": "Coder", "timestamp": 2.0},
                        {**retrieval, "caller_id": "Reviewer", "timestamp": 3.0},
                    ],
                    "memories": [],
                },
            }
        )
        console = Console(file=io.StringIO(), record=True, width=200)

        with (
            patch.object(timeline_inspector, "console", console),
            patch("core.display.console", console),
        ):
            timeline_inspector.print_timeline("sw-test", client)

        output = console.export_text()
        self.assertIn("AGENT CONTEXT RETRIEVALS", output)
        self.assertIn("Coder retrieved context", output)
        self.assertIn("Reviewer retrieved context", output)
        self.assertIn("Context reads   : 2", output)
