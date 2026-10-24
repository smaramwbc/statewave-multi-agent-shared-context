"""Regression tests for mapping SDK context bundles into SharedContext."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from agents.coder import CoderAgent
from agents.reviewer import ReviewerAgent
from statewave_agents.context import SharedContext


class FakeContextClient:
    def __init__(self, response: dict):
        self.response = response

    def get_context(self, **kwargs) -> dict:
        return self.response


class FakeLLMClient:
    def __init__(self, content: str):
        message = SimpleNamespace(content=content)
        completion = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: completion)
        )


class SharedContextTests(TestCase):
    def setUp(self):
        self.fact = {
            "kind": "architectural_decision",
            "confidence": 0.92,
            "content": "Use JWT authentication.",
        }
        self.procedure = {
            "kind": "deployment_procedure",
            "confidence": 0.81,
            "content": "Deploy after running migrations.",
        }
        self.response = {
            "assembled_context": "Use JWT authentication.",
            "facts": [self.fact],
            "procedures": [self.procedure],
            "episodes": [{"type": "decision", "payload": {"content": "raw"}}],
        }
        self.context = SharedContext(
            subject_id="test-run",
            client=FakeContextClient(self.response),
        )

    def test_before_acting_maps_memories_and_filters_by_kind(self):
        bundle = self.context.before_acting("Coder", "Implement authentication")

        self.assertEqual(bundle.assembled_context, self.response["assembled_context"])
        self.assertEqual(bundle.memories, [self.fact, self.procedure])
        self.assertTrue(bundle.has_context())
        self.assertEqual(bundle.memories_of_kind("architectural_decision"), [self.fact])
        self.assertEqual(bundle.memories_of_kind("missing_kind"), [])

    def test_before_acting_excludes_episodes_and_defaults_missing_memory_lists(self):
        context = SharedContext(
            subject_id="test-run",
            client=FakeContextClient(
                {
                    "assembled_context": "Raw episode context.",
                    "episodes": [{"type": "note", "payload": {"content": "raw"}}],
                }
            ),
        )

        bundle = context.before_acting("Coder", "Check context")

        self.assertEqual(bundle.memories, [])
        self.assertFalse(bundle.has_context())

    def test_coder_and_reviewer_report_mapped_memories(self):
        bundle = self.context.before_acting("Coder", "Implement authentication")
        coder = CoderAgent(
            FakeLLMClient("IMPLEMENTING:\n- jwt-auth\n\nSKIPPING:\n- legacy-auth")
        )
        reviewer = ReviewerAgent(FakeLLMClient("STATUS: CLEAN\nFINDINGS:\n- No issues found"))

        with (
            patch("agents.coder.agent_log") as coder_log,
            patch("agents.coder.info"),
            patch("agents.reviewer.agent_log"),
            patch("agents.reviewer.info") as reviewer_info,
        ):
            coder_result = coder.act("Implement authentication", bundle)
            reviewer_result = reviewer.act("Review authentication", bundle)

        coder_log.assert_any_call(
            "Coder",
            "  [architectural_decision] (confidence 0.92) Use JWT authentication.",
            style="dim cyan",
        )
        reviewer_info.assert_any_call(
            "Retrieved 2 memory item(s) from shared context for review."
        )
        self.assertTrue(coder_result["used_shared_context"])
        self.assertTrue(reviewer_result["used_shared_context"])
        self.assertEqual(coder_result["context_memories"], [self.fact, self.procedure])
        self.assertEqual(reviewer_result["context_memories"], [self.fact, self.procedure])
