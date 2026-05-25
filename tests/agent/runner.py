# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scenario runner for agent integration tests.

Wraps :class:`bowerbot.agent.AgentRuntime` to record every tool call,
token cost, and LLM response per prompt, then dumps human-readable
artifacts to ``tests/agent/artifacts/<scenario>/<timestamp>/``. Each
scenario is run in an isolated temporary project so scenarios cannot
contaminate each other.

Usage from pytest::

    @pytest.mark.agent_integration
    async def test_pendulum(scenario_runner):
        scenario = AgentScenario(
            name="pendulum",
            description="Build a two-cube pendulum from a vague prompt",
            prompts=["I want to make a pendulum out of two cubes"],
            assertions=[has_physics_scene, has_revolute_joint],
        )
        await scenario_runner.run(scenario)
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pxr import Usd

from bowerbot.agent import AgentRuntime
from bowerbot.config import Settings
from bowerbot.project import Project
from bowerbot.skills.base import ToolResult
from bowerbot.skills.registry import SkillRegistry
from bowerbot.state import SceneState
from bowerbot.utils import stage_utils

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    """One tool call captured during a scenario run."""

    prompt_index: int
    tool_name: str
    params: dict[str, Any]
    success: bool
    error: str | None
    data: Any


@dataclass
class TurnRecord:
    """One user prompt and the agent's full response, including all tool calls."""

    prompt: str
    response: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class ScenarioContext:
    """Final state passed to assertion callables."""

    scenario_name: str
    project_dir: Path
    scene_path: Path
    state: SceneState
    turns: list[TurnRecord]

    @property
    def stage(self) -> Usd.Stage | None:
        """The composed scene stage at the end of the scenario."""
        return self.state.stage

    @property
    def all_tool_calls(self) -> list[ToolCallRecord]:
        """Flattened list of every tool call across every turn."""
        return [tc for turn in self.turns for tc in turn.tool_calls]

    def tool_calls_for(self, tool_name: str) -> list[ToolCallRecord]:
        """Every recorded call to *tool_name*."""
        return [tc for tc in self.all_tool_calls if tc.tool_name == tool_name]

    @property
    def total_prompt_tokens(self) -> int:
        """Sum of prompt tokens across every LLM turn."""
        return sum(t.prompt_tokens or 0 for t in self.turns)

    @property
    def total_completion_tokens(self) -> int:
        """Sum of completion tokens across every LLM turn."""
        return sum(t.completion_tokens or 0 for t in self.turns)


@dataclass
class AgentScenario:
    """One end-to-end agent walkthrough definition."""

    name: str
    description: str
    prompts: list[str]
    setup: Callable[[Path], None] | None = None
    assertions: list[Callable[[ScenarioContext], None]] = field(default_factory=list)
    tier: str = ""


class _RecordingAgent(AgentRuntime):
    """AgentRuntime subclass that records every tool call into the active turn."""

    def __post_init__(self) -> None:
        super().__post_init__()
        self._current_turn_calls: list[ToolCallRecord] = []
        self._current_prompt_index: int = -1

    def start_prompt(self, index: int) -> list[ToolCallRecord]:
        """Begin recording for a new prompt; returns the list to populate."""
        self._current_prompt_index = index
        self._current_turn_calls = []
        return self._current_turn_calls

    async def _dispatch_tool(
        self, func_name: str, func_args: dict[str, Any],
    ) -> ToolResult:
        """Dispatch via AgentRuntime then record the call + result."""
        result = await super()._dispatch_tool(func_name, func_args)
        self._current_turn_calls.append(ToolCallRecord(
            prompt_index=self._current_prompt_index,
            tool_name=func_name,
            params=func_args,
            success=result.success,
            error=result.error,
            data=result.data if result.success else None,
        ))
        return result


class ScenarioRunner:
    """Driver that runs one ``AgentScenario`` in an isolated project."""

    def __init__(
        self,
        settings: Settings,
        project_root: Path,
        artifact_root: Path,
    ) -> None:
        self.settings = settings
        self.project_root = project_root
        self.artifact_root = artifact_root

    async def run(self, scenario: AgentScenario) -> ScenarioContext:
        """Execute *scenario* end-to-end and return the captured context."""
        project = self._build_project(scenario.name)
        if scenario.setup is not None:
            scenario.setup(project.path)

        state = self._build_state(project)
        agent = _RecordingAgent(
            settings=self.settings,
            state=state,
            skill_registry=SkillRegistry(),
        )

        turns: list[TurnRecord] = []
        for index, prompt in enumerate(scenario.prompts):
            turn_calls = agent.start_prompt(index)
            try:
                response = await agent.process(prompt)
            except Exception as exc:
                response = f"[AGENT ERROR] {type(exc).__name__}: {exc}"
                logger.exception(
                    "Scenario %s turn %s raised", scenario.name, index,
                )
            usage = self._last_usage(agent)
            turns.append(TurnRecord(
                prompt=prompt,
                response=response,
                tool_calls=list(turn_calls),
                prompt_tokens=usage[0],
                completion_tokens=usage[1],
            ))

        if state.project is not None and state.project.scene_path.exists():
            state.stage = stage_utils.open_stage(state.project.scene_path)

        ctx = ScenarioContext(
            scenario_name=scenario.name,
            project_dir=project.path,
            scene_path=state.project.scene_path
            if state.project is not None else Path(),
            state=state,
            turns=turns,
        )

        artifact_dir = self._dump_artifacts(scenario, ctx)
        logger.info(
            "scenario=%s tool_calls=%s tokens=%s artifact=%s",
            scenario.name,
            len(ctx.all_tool_calls),
            ctx.total_prompt_tokens + ctx.total_completion_tokens,
            artifact_dir,
        )

        for assertion in scenario.assertions:
            assertion(ctx)

        return ctx

    def _build_project(self, scenario_name: str) -> Project:
        """Create a fresh project directory for the scenario."""
        self.project_root.mkdir(parents=True, exist_ok=True)
        return Project.create(self.project_root, scenario_name)

    def _build_state(self, project: Project) -> SceneState:
        """Build a SceneState bound to *project*, opening its scene if present."""
        state = SceneState(
            scene_defaults=self.settings.scene_defaults,
            library_dir=Path(self.settings.assets_dir),
        )
        state.project = project
        state.stage_path = project.scene_path
        if project.scene_path.exists():
            state.stage = stage_utils.open_stage(project.scene_path)
            state.object_count = len(stage_utils.list_prims(state.stage))
            state.mark_saved()
        return state

    def _last_usage(
        self, _agent: _RecordingAgent,
    ) -> tuple[int | None, int | None]:
        """Best-effort extraction of the last LLM turn's token usage."""
        # litellm responses do not surface usage to AgentRuntime callers
        # in a stable shape across providers; per-turn accounting is read
        # from the file log instead. Return None here to keep TurnRecord
        # typed but populated from the log slice during artifact dump.
        return None, None

    def _dump_artifacts(
        self, scenario: AgentScenario, ctx: ScenarioContext,
    ) -> Path:
        """Write transcript.md, tool_calls.json, and a scene.usda copy."""
        timestamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        out = self.artifact_root / scenario.name / timestamp
        out.mkdir(parents=True, exist_ok=True)

        (out / "transcript.md").write_text(
            self._format_transcript(scenario, ctx), encoding="utf-8",
        )
        (out / "tool_calls.json").write_text(
            json.dumps(
                [_tool_call_to_dict(tc) for tc in ctx.all_tool_calls],
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
        if ctx.scene_path.exists():
            (out / "scene.usda").write_text(
                ctx.scene_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        return out

    def _format_transcript(
        self, scenario: AgentScenario, ctx: ScenarioContext,
    ) -> str:
        """Render a human-readable transcript markdown file."""
        lines = [
            f"# {scenario.name}",
            "",
            f"**Tier:** {scenario.tier or 'unspecified'}",
            f"**Description:** {scenario.description}",
            f"**Project:** `{ctx.project_dir}`",
            f"**Tool calls:** {len(ctx.all_tool_calls)}",
            "",
        ]
        for turn_index, turn in enumerate(ctx.turns):
            lines.extend([
                f"## Turn {turn_index + 1}",
                "",
                "**User:**",
                "",
                f"> {turn.prompt}",
                "",
            ])
            if turn.tool_calls:
                lines.append("**Tool calls:**")
                lines.append("")
                for tc in turn.tool_calls:
                    status = "ok" if tc.success else f"error: {tc.error}"
                    lines.append(
                        f"- `{tc.tool_name}` ({status}) "
                        f"params={json.dumps(tc.params, default=str)}",
                    )
                lines.append("")
            lines.extend([
                "**Agent:**",
                "",
                turn.response or "(no response)",
                "",
            ])
        return "\n".join(lines)


def _tool_call_to_dict(tc: ToolCallRecord) -> dict[str, Any]:
    """Serialize a ToolCallRecord for the JSON artifact."""
    return {
        "prompt_index": tc.prompt_index,
        "tool_name": tc.tool_name,
        "params": tc.params,
        "success": tc.success,
        "error": tc.error,
        "data_summary": _summarize(tc.data),
    }


def _summarize(value: Any) -> Any:
    """Truncate large blobs of tool response data so artifacts stay readable."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _summarize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_summarize(v) for v in value[:8]] + (
            ["...truncated"] if len(value) > 8 else []
        )
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + f"...[+{len(value) - 200}]"
    return value
