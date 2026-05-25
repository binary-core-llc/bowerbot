# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Pytest harness wiring agent scenarios into parameterised test functions.

These tests cost real money (LLM calls). They are excluded by default
from ``pytest`` runs via the ``agent_integration`` marker. Run them
locally with::

    pytest -m agent_integration tests/agent/

Or one tier::

    pytest -m agent_integration tests/agent/ -k discovery
"""

from __future__ import annotations

import pytest

from tests.agent.runner import AgentScenario, ScenarioRunner
from tests.agent.scenarios import (
    conceptual,
    discovery,
    iteration,
    physics_goals,
    recovery,
    refusals,
    tool_coverage,
    vague_intent,
)

_ALL_SCENARIOS: list[AgentScenario] = (
    discovery.ALL
    + vague_intent.ALL
    + physics_goals.ALL
    + iteration.ALL
    + conceptual.ALL
    + recovery.ALL
    + refusals.ALL
    + tool_coverage.ALL
)


@pytest.mark.agent_integration
@pytest.mark.parametrize(
    "scenario", _ALL_SCENARIOS, ids=lambda s: s.name,
)
async def test_agent_scenario(
    scenario: AgentScenario,
    scenario_runner: ScenarioRunner,
) -> None:
    """Run one agent scenario end-to-end and apply its assertions."""
    await scenario_runner.run(scenario)
