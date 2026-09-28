# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot's USD primitives: pure functions, one module per domain.

Services call them through the package, never by importing a function::

    from bowerbot import utils

    utils.stage.open_stage(path)
    utils.lights.create_light(stage, prim_path, light)
"""

from bowerbot.utils import asset_folder
from bowerbot.utils import cameras
from bowerbot.utils import dependencies
from bowerbot.utils import geometry
from bowerbot.utils import inspection
from bowerbot.utils import intake
from bowerbot.utils import integrity
from bowerbot.utils import layout
from bowerbot.utils import library
from bowerbot.utils import lights
from bowerbot.utils import materials
from bowerbot.utils import naming
from bowerbot.utils import physics
from bowerbot.utils import physics_typing
from bowerbot.utils import scatter
from bowerbot.utils import stage
from bowerbot.utils import surface
from bowerbot.utils import textures
from bowerbot.utils import usd_schema
from bowerbot.utils import validation
from bowerbot.utils import variants

__all__ = [
    "asset_folder",
    "cameras",
    "dependencies",
    "geometry",
    "inspection",
    "intake",
    "integrity",
    "layout",
    "library",
    "lights",
    "materials",
    "naming",
    "physics",
    "physics_typing",
    "scatter",
    "stage",
    "surface",
    "textures",
    "usd_schema",
    "validation",
    "variants",
]
