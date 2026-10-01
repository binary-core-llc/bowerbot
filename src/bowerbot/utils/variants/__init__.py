# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The variant tools: adding variants to an asset or the scene, masking checks, suspect sets.

The universal variant-set operations live in ``usd.variant_sets``, and an
asset's variants.usda (the layer, reading it, default selections, removal) in
``authoring.asset_variants``. Services layer the category orchestrators on top.
"""

from bowerbot.utils.variants import asset
from bowerbot.utils.variants import bodies
from bowerbot.utils.variants import geometry
from bowerbot.utils.variants import masking
from bowerbot.utils.variants import scene
from bowerbot.utils.variants import suspect_sets

__all__ = [
    "asset",
    "bodies",
    "geometry",
    "masking",
    "scene",
    "suspect_sets",
]
