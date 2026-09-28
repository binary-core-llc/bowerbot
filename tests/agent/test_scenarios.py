# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Pytest harness for agent scenarios; tiers come from each scenario's ``suites``."""

from __future__ import annotations

import pytest

from tests.agent import runner
from tests.agent.scenarios import conceptual
from tests.agent.scenarios import discovery
from tests.agent.scenarios import exploratory
from tests.agent.scenarios import iteration
from tests.agent.scenarios import physics_goals
from tests.agent.scenarios import recovery
from tests.agent.scenarios import refusals
from tests.agent.scenarios import tool_categories
from tests.agent.scenarios import tool_coverage
from tests.agent.scenarios import vague_intent

_ALL_SCENARIOS: list[runner.AgentScenario] = (
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
    scenario: runner.AgentScenario,
    scenario_runner: runner.ScenarioRunner,
) -> None:
    """Run one agent scenario end-to-end and apply its assertions."""
    await scenario_runner.run(scenario)
