# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Pytest fixtures for agent integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from bowerbot.config import Settings, load_settings
from bowerbot.logging_setup import configure_logging
from tests.agent.runner import ScenarioRunner

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_ROOT = _REPO_ROOT / "tests" / "agent" / "artifacts"


@pytest.fixture(scope="session")
def agent_settings() -> Settings:
    """Load the real ~/.bowerbot/config.json so we use the user's API key."""
    settings = load_settings()
    if not settings.get_api_key():
        pytest.skip(
            "No OpenAI API key in ~/.bowerbot/config.json; agent "
            "integration tests require one. Run `bowerbot onboard` "
            "to set it.",
        )
    configure_logging(settings)
    return settings


@pytest.fixture()
def scenario_runner(agent_settings, tmp_path) -> ScenarioRunner:
    """Build a runner that isolates each scenario in its own tmp project dir."""
    return ScenarioRunner(
        settings=agent_settings,
        project_root=tmp_path / "projects",
        artifact_root=_ARTIFACT_ROOT,
    )
