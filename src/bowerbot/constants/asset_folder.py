# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""ASWF asset folder values: layer file names and how the root composes them."""


class ASWFLayerNames:
    """ASWF USD Working Group standard layer file names.

    Centralized so no hardcoded strings are scattered across the
    codebase.

    Reference: https://github.com/usd-wg/assets/blob/main/docs/asset-structure-guidelines.md
    """

    GEO = "geo.usda"
    MTL = "mtl.usda"
    LGT = "lgt.usda"
    PHY = "phy.usda"            # Physics APIs (RigidBody/Mass/Collision)
    CONTENTS = "contents.usda"  # References to the assets added to this asset
    VARIANTS = "variants.usda"  # Variant set declarations + opinions
    MAPS = "maps"
    TEXTURES = "textures"


class AssetFolderRules:
    """What counts as a USD layer in an asset folder, and how the root references them."""

    # File extensions of a USD layer inside an asset folder.
    USD_LAYER_EXTENSIONS: frozenset[str] = frozenset({".usd", ".usda", ".usdc"})
    # Order the asset root references its side layers in (strongest first).
    CANONICAL_REFERENCE_ORDER: tuple[str, ...] = (
        ASWFLayerNames.VARIANTS,
        ASWFLayerNames.CONTENTS,
        ASWFLayerNames.LGT,
        ASWFLayerNames.MTL,
        ASWFLayerNames.PHY,
    )
