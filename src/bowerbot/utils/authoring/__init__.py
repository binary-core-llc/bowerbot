# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot's authoring model: how BowerBot lays out a project.

Asset folders, ``scene.usda`` and its ``/Scene`` placements, the library and
the project's textures. A module here uses ``usd`` and other modules in this
group (plus ``constants`` and ``schemas``), never a feature. Callers write
``from bowerbot.utils import authoring``, then
``authoring.naming.safe_project_name(...)``.
"""

from bowerbot.utils.authoring import naming
from bowerbot.utils.authoring import stage

__all__ = [
    "naming",
    "stage",
]
