# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Every golden scenario still produces, step by step, exactly what was recorded.

Each scenario and convention has one recording,
``tests/golden/expected/<area>/<scenario>.<convention>.txt``, holding every
step in order. A failure names the first step whose snapshot differs and shows
the difference. When the difference is intended, review it and re-record with
``BOWERBOT_UPDATE_GOLDEN=1 pytest tests/test_golden_output.py``.

Each scenario is also recorded with every folder listed in reverse order and
must give the same recording: the disk's listing order differs between
machines, so BowerBot's output must not depend on it.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import pytest

from tests.golden import model
from tests.golden import recorder
from tests.golden import scenarios

EXPECTED = Path(__file__).parent / "golden" / "expected"
UPDATE = os.environ.get("BOWERBOT_UPDATE_GOLDEN") == "1"
STEP_MARK = "=== step "

CASES = [
    pytest.param(scenario, convention, id=f"{scenario.name}[{convention.key}]")
    for scenario in scenarios.SCENARIOS
    for convention in scenario.conventions
]


def _recording_path(scenario: model.Scenario, convention: model.Convention) -> Path:
    return EXPECTED / f"{scenario.name}.{convention.key}.txt"


def _header(scenario: model.Scenario, convention: model.Convention) -> str:
    return (
        f"##### scenario: {scenario.name}\n"
        f"##### convention: {convention.up_axis}-up, {convention.meters_per_unit} meters per unit\n"
        f"##### {scenario.description}\n"
    )


def _join(
    scenario: model.Scenario, convention: model.Convention, steps: list[recorder.StepRecord],
) -> str:
    return "\n\n".join([_header(scenario, convention), *(step.text for step in steps)])


def _split_steps(text: str) -> list[str]:
    """The recording's steps, each starting at its ``=== step`` line."""
    parts, current = [], []
    for line in text.splitlines(keepends=True):
        if line.startswith(STEP_MARK) and current:
            parts.append("".join(current))
            current = []
        current.append(line)
    parts.append("".join(current))
    return [part.strip("\n") for part in parts if part.startswith(STEP_MARK)]


def _compare(
    scenario: model.Scenario, convention: model.Convention, now: str, when: str = "",
) -> None:
    """Fail with the first step where *now* differs from the recording."""
    path = _recording_path(scenario, convention)
    assert path.is_file(), f"no recording for {scenario.name} [{convention.key}]; record it first"
    recorded = path.read_text(encoding="utf-8")
    if recorded == now:
        return
    case = f"{scenario.name} [{convention.key}]{when}"
    before, after = _split_steps(recorded), _split_steps(now)
    for index in range(max(len(before), len(after))):
        old = before[index] if index < len(before) else "(no such step recorded)"
        new = after[index] if index < len(after) else "(the scenario no longer has this step)"
        if old != new:
            title = (after[index] if index < len(after) else old).splitlines()[0]
            diff = "\n".join(difflib.unified_diff(
                old.splitlines(), new.splitlines(),
                fromfile="recorded", tofile="now", lineterm="",
            ))
            pytest.fail(f"{case} differs at {title}:\n{diff}")
    pytest.fail(f"{case}: the header or layout changed; re-record it")


@pytest.mark.parametrize(("scenario", "convention"), CASES)
def test_golden_output(
    scenario: model.Scenario, convention: model.Convention, tmp_path: Path,
) -> None:
    now = _join(scenario, convention, recorder.record(scenario, convention, tmp_path))
    if UPDATE:
        path = _recording_path(scenario, convention)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(now, encoding="utf-8")
        return
    _compare(scenario, convention, now)


@pytest.mark.parametrize(("scenario", "convention"), CASES)
def test_golden_output_ignores_listing_order(
    scenario: model.Scenario, convention: model.Convention, tmp_path: Path,
) -> None:
    """The same recording with every folder listed in reverse order.

    Failing here while test_golden_output passes means BowerBot's output
    depends on the order the disk lists files in, which differs between machines.
    """
    if UPDATE:
        pytest.skip("re-recording")
    steps = recorder.record(scenario, convention, tmp_path, reverse_listings=True)
    now = _join(scenario, convention, steps)
    _compare(scenario, convention, now, " with folders listed in reverse order")
