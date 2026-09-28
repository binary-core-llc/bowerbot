# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD building blocks: generic OpenUSD operations that any USD tool could use.

A module here knows nothing about BowerBot's asset folders, ``/Scene`` layout
or tools. It uses only other modules in this group (plus ``constants`` and
``schemas``). Callers write ``from bowerbot.utils import usd``, then
``usd.naming.safe_prim_name(...)``.
"""

from bowerbot.utils.usd import bounds
from bowerbot.utils.usd import metrics
from bowerbot.utils.usd import namespace
from bowerbot.utils.usd import naming
from bowerbot.utils.usd import transforms
from bowerbot.utils.usd import values

__all__ = [
    "bounds",
    "metrics",
    "namespace",
    "naming",
    "transforms",
    "values",
]
