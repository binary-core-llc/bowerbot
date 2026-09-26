# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""CLI commands: project names checked up front, skills reported as installed."""

from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from click.testing import CliRunner

from bowerbot import cli
from bowerbot.config import LLMSettings, Settings, SkillConfig
from bowerbot.project import Project
from bowerbot.skills import registry as registry_mod


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    """Settings on a temporary projects dir; the user's config and logs are never touched."""
    configured = Settings(
        assets_dir=tmp_path / "library", projects_dir=tmp_path / "projects",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: configured)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    return configured


def _install(monkeypatch, *entry_points: EntryPoint) -> None:
    monkeypatch.setattr(
        registry_mod, "entry_points",
        lambda *, group: entry_points if group == "bowerbot.skills" else (),
    )


def test_new_refuses_a_taken_name_before_asking_axis_and_units(settings):
    Project.create(settings.projects_dir, "Coffee Shop")

    result = CliRunner().invoke(cli.main, ["new", "Coffee Shop"])

    assert result.exit_code == 0, result.output
    assert "Project already exists" in result.output
    assert "up-axis" not in result.output


def test_new_refuses_an_unusable_name_before_asking_axis_and_units(settings):
    result = CliRunner().invoke(cli.main, ["new", "!!!"])

    assert result.exit_code == 0, result.output
    assert "has no letters or digits" in result.output
    assert "up-axis" not in result.output
    assert not settings.projects_dir.exists() or not any(settings.projects_dir.iterdir())


def test_new_asks_axis_and_units_for_a_free_name(settings):
    result = CliRunner().invoke(cli.main, ["new", "Coffee Shop"], input="Z\ncentimeters\n")

    assert result.exit_code == 0, result.output
    project = Project.load(settings.projects_dir / "coffee_shop")
    assert project.meta.up_axis.value == "Z"
    assert project.meta.meters_per_unit == 0.01


def test_open_finds_a_project_by_the_name_it_was_created_with(settings, monkeypatch):
    Project.create(settings.projects_dir, "My Shop!")
    opened: list[Project | None] = []
    monkeypatch.setattr(cli, "_start_chat", lambda _settings, project=None: opened.append(project))

    result = CliRunner().invoke(cli.main, ["open", "My Shop!"])

    assert result.exit_code == 0, result.output
    assert "Project not found" not in result.output
    assert [p.name for p in opened if p] == ["My Shop!"]


def test_skills_lists_an_installed_skill_that_is_not_configured(settings, monkeypatch):
    _install(monkeypatch, EntryPoint(
        name="broken", value="tests.test_skills:_MisconfiguredSkill", group="bowerbot.skills",
    ))

    result = CliRunner().invoke(cli.main, ["skills"])

    assert result.exit_code == 0, result.output
    assert "Installed but not configured" in result.output
    assert "broken: missing token" in result.output


def test_skills_lists_a_skill_config_turns_off(settings, monkeypatch):
    settings.skills["external_provider"] = SkillConfig(enabled=False)
    _install(monkeypatch, EntryPoint(
        name="external_provider", value="tests.test_skills:_ExternalSkill",
        group="bowerbot.skills",
    ))

    result = CliRunner().invoke(cli.main, ["skills"])

    assert result.exit_code == 0, result.output
    assert "Disabled in config" in result.output
    assert "external_provider__ping" not in result.output


def test_info_reports_the_skills_that_loaded(settings, monkeypatch):
    _install(monkeypatch, EntryPoint(
        name="external_provider", value="tests.test_skills:_ExternalSkill",
        group="bowerbot.skills",
    ))

    result = CliRunner().invoke(cli.main, ["info"])

    assert result.exit_code == 0, result.output
    assert "external_provider" in result.output


def test_onboarding_offers_the_configured_default_model():
    assert LLMSettings().model == "anthropic/claude-opus-5-5"


def test_cli_output_stays_ascii():
    """Windows consoles on cp1252 raise UnicodeEncodeError on anything else."""
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert source.isascii(), [c for c in source if not c.isascii()]


def test_config_paths_expand_the_home_folder():
    configured = Settings(assets_dir="~/usd_library", projects_dir="~/scenes")
    assert configured.assets_dir == Path.home() / "usd_library"
    assert configured.projects_dir == Path.home() / "scenes"
