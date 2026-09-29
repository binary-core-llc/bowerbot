# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot's USD primitives: pure functions, one module per job.

The modules are grouped into folders:

- ``usd/``: USD building blocks, generic OpenUSD operations;
- ``authoring/``: BowerBot's authoring model (asset folders, ``/Scene`` placements);
- one folder per tool family (``physics/``, ...), split by category. A tool
  family uses ``usd`` and ``authoring``, never another family.

Code imports the group it needs and calls a module through it::

    from bowerbot.utils import usd

    usd.naming.safe_prim_name(name)
"""

from bowerbot.utils import authoring
from bowerbot.utils import cameras
from bowerbot.utils import inspection
from bowerbot.utils import layout
from bowerbot.utils import lights
from bowerbot.utils import materials
from bowerbot.utils import physics
from bowerbot.utils import scatter
from bowerbot.utils import usd
from bowerbot.utils import validation
from bowerbot.utils import variants

__all__ = [
    "authoring",
    "cameras",
    "inspection",
    "layout",
    "lights",
    "materials",
    "physics",
    "scatter",
    "usd",
    "validation",
    "variants",
]
