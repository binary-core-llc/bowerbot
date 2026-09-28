# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot's USD primitives: pure functions, one module per job.

The modules are being grouped into three folders, one per layer:

- ``usd/``: USD building blocks, generic OpenUSD operations;
- ``authoring/``: BowerBot's authoring model (asset folders, ``/Scene`` placements);
- ``features/``: the logic behind each tool family.

Code imports the group it needs and calls a module through it::

    from bowerbot.utils import usd

    usd.naming.safe_prim_name(name)

Modules not moved into a group yet are called as ``utils.<module>.<function>``.
"""

from bowerbot.utils import asset_folder
from bowerbot.utils import authoring
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
from bowerbot.utils import physics
from bowerbot.utils import physics_typing
from bowerbot.utils import scatter
from bowerbot.utils import stage
from bowerbot.utils import surface
from bowerbot.utils import textures
from bowerbot.utils import usd
from bowerbot.utils import usd_schema
from bowerbot.utils import validation
from bowerbot.utils import variants

__all__ = [
    "asset_folder",
    "authoring",
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
    "physics",
    "physics_typing",
    "scatter",
    "stage",
    "surface",
    "textures",
    "usd",
    "usd_schema",
    "validation",
    "variants",
]
