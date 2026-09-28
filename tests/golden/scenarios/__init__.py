# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Every golden scenario, gathered from the area modules."""

from __future__ import annotations

from tests.golden.model import Scenario
from tests.golden.scenarios import (
    editing,
    lights_cameras,
    materials,
    options,
    physics,
    placement,
    project_library_validation,
    scatter,
    state,
    variants,
)

SCENARIOS: tuple[Scenario, ...] = (
    *placement.SCENARIOS,
    *editing.SCENARIOS,
    *materials.SCENARIOS,
    *lights_cameras.SCENARIOS,
    *variants.SCENARIOS,
    *physics.SCENARIOS,
    *scatter.SCENARIOS,
    *project_library_validation.SCENARIOS,
    *state.SCENARIOS,
    *options.SCENARIOS,
)
