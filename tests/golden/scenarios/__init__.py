# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Every golden scenario, gathered from the area modules."""

from __future__ import annotations

from tests.golden import model
from tests.golden.scenarios import editing
from tests.golden.scenarios import lights_cameras
from tests.golden.scenarios import materials
from tests.golden.scenarios import options
from tests.golden.scenarios import physics
from tests.golden.scenarios import placement
from tests.golden.scenarios import project_library_validation
from tests.golden.scenarios import scatter
from tests.golden.scenarios import state
from tests.golden.scenarios import variants

SCENARIOS: tuple[model.Scenario, ...] = (
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
