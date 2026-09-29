# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Features: the logic behind each tool family, one module per family.

A module here uses ``usd`` and ``authoring`` (plus ``constants`` and
``schemas``), never another feature: when a job needs two features, the
service calls both. Callers write ``from bowerbot.utils import features``,
then ``features.cameras.create_camera(...)``.
"""

from bowerbot.utils.features import cameras
from bowerbot.utils.features import lights
from bowerbot.utils.features import materials

__all__ = [
    "cameras",
    "lights",
    "materials",
]
