"""
statewave_agents — reusable shared-context coordination for multi-agent LLM systems.

    from statewave_agents import Agent, SharedContext
    from core.llm import LLMClient

    ctx = SharedContext(subject_id="run-123")
    llm = LLMClient()

    class MyAgent(Agent):
        def act(self, task, context):
            ...

    agent = MyAgent(llm, ctx)
"""

from statewave_agents.context import SharedContext, Decision, ContextBundle
from statewave_agents.agent import Agent

__all__ = ["Agent", "SharedContext", "Decision", "ContextBundle"]
