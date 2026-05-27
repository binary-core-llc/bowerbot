# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Pytest harness for agent scenarios; tiers come from each scenario's ``suites``."""

from __future__ import annotations

import pytest

from tests.agent.runner import AgentScenario, ScenarioRunner
from tests.agent.scenarios import (
    conceptual,
    discovery,
    exploratory,
    iteration,
    physics_goals,
    recovery,
    refusals,
    tool_categories,
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
    + tool_categories.ALL
    + exploratory.ALL
)


def _params() -> list:
    return [
        pytest.param(
            s,
            id=s.name,
            marks=[getattr(pytest.mark, f"agent_{suite}") for suite in s.suites],
        )
        for s in _ALL_SCENARIOS
    ]


@pytest.mark.agent_integration
@pytest.mark.parametrize("scenario", _params())
async def test_agent_scenario(
    scenario: AgentScenario,
    scenario_runner: ScenarioRunner,
) -> None:
    """Run one agent scenario end-to-end and apply its assertions."""
    await scenario_runner.run(scenario)
