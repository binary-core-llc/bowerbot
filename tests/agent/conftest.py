# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Pytest fixtures for agent integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from bowerbot import config
from bowerbot import logging_setup
from tests.agent import runner

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_ROOT = _REPO_ROOT / "tests" / "agent" / "artifacts"


@pytest.fixture(scope="session")
def agent_settings() -> config.Settings:
    """Load the real ~/.bowerbot/config.json so we use the user's API key."""
    settings = config.load_settings()
    if not settings.get_api_key():
        pytest.skip(
            "No OpenAI API key in ~/.bowerbot/config.json; agent "
            "integration tests require one. Run `bowerbot onboard` "
            "to set it.",
        )
    logging_setup.configure_logging(settings)
    return settings


@pytest.fixture()
def scenario_runner(agent_settings, tmp_path) -> runner.ScenarioRunner:
    """Build a runner that isolates each scenario in its own tmp project dir."""
    return runner.ScenarioRunner(
        settings=agent_settings,
        project_root=tmp_path / "projects",
        artifact_root=_ARTIFACT_ROOT,
    )
