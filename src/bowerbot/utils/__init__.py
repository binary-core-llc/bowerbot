# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot's USD primitives: pure functions, one module per job.

The modules are grouped into folders:

- ``usd/``: USD building blocks, generic OpenUSD operations;
- ``authoring/``: BowerBot's authoring model (asset folders, ``/Scene`` placements);
- one folder per tool family (``physics/``, ...), split by category. A tool
  family uses ``usd`` and ``authoring``, never another family.
  (``features/`` still holds the families not moved into their own folder yet.)

Code imports the group it needs and calls a module through it::

    from bowerbot.utils import usd

    usd.naming.safe_prim_name(name)

Modules not moved into a group yet are called as ``utils.<module>.<function>``.
"""

from bowerbot.utils import authoring
from bowerbot.utils import cameras
from bowerbot.utils import features
from bowerbot.utils import geometry
from bowerbot.utils import inspection
from bowerbot.utils import layout
from bowerbot.utils import physics
from bowerbot.utils import scatter
from bowerbot.utils import usd
from bowerbot.utils import validation
from bowerbot.utils import variants

__all__ = [
    "authoring",
    "cameras",
    "features",
    "geometry",
    "inspection",
    "layout",
    "physics",
    "scatter",
    "usd",
    "validation",
    "variants",
]
