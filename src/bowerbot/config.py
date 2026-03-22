# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot configuration management.

All settings live in ~/.bowerbot/config.json — one file, one place.
No .env files needed.

Load order:
1. ~/.bowerbot/config.json
2. Built-in defaults
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings

# Global config directory
BOWERBOT_HOME = Path.home() / ".bowerbot"
GLOBAL_CONFIG_PATH = BOWERBOT_HOME / "config.json"


class LLMSettings(BaseSettings):
    """LLM provider configuration."""

    model: str = "gpt-4o"
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 4096

    # Token management
    context_window: int | None = None  # None = auto-detect from litellm
    summarization_threshold: float = 0.75  # fraction of budget before summarizing
    tool_result_age_threshold: int = 2  # user turns before compressing tool results
    min_keep_recent: int = 6  # minimum recent messages kept verbatim
    summary_max_tokens: int = 512  # max tokens for the summarization call

    # Error recovery
    num_retries: int = 3  # retries for rate limits and transient errors
    request_timeout: float = 120.0  # seconds before a request times out


class SkillConfig(BaseSettings):
    """Configuration for a single skill."""

    enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class SceneDefaults(BaseSettings):
    """Default scene parameters baked into every USD stage."""

    meters_per_unit: float = 1.0
    up_axis: str = "Y"
    default_room_bounds: tuple[float, float, float] = (10.0, 3.0, 8.0)


class Settings(BaseSettings):
    """Top-level BowerBot settings."""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    scene_defaults: SceneDefaults = Field(default_factory=SceneDefaults)
    skills: dict[str, SkillConfig] = Field(default_factory=dict)
    assets_dir: Path = Path("./assets")
    projects_dir: Path = Path("./scenes")

    model_config = {"env_prefix": "BOWERBOT_", "env_nested_delimiter": "__"}

    def get_api_key(self) -> str:
        """Resolve the API key from settings."""
        if self.llm.api_key:
            return self.llm.api_key
        return ""


def ensure_home() -> Path:
    """Create ~/.bowerbot/ if it doesn't exist. Returns the path."""
    BOWERBOT_HOME.mkdir(parents=True, exist_ok=True)
    return BOWERBOT_HOME


def load_settings() -> Settings:
    """Load settings from ~/.bowerbot/config.json."""
    raw: dict[str, Any] = {}
    if GLOBAL_CONFIG_PATH.exists():
        raw = json.loads(GLOBAL_CONFIG_PATH.read_text(encoding="utf-8"))

    return Settings(**raw) if raw else Settings()


def save_settings(settings: Settings) -> None:
    """Save settings to ~/.bowerbot/config.json."""
    ensure_home()

    data = settings.model_dump(mode="json")
    data["assets_dir"] = str(data["assets_dir"])
    data["projects_dir"] = str(data["projects_dir"])

    GLOBAL_CONFIG_PATH.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )
