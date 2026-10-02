# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""ASWF asset folder values: layer file names and how the root composes them."""


class ASWFLayerNames:
    """ASWF USD Working Group standard layer file names."""

    GEO = "geo.usda"
    MTL = "mtl.usda"
    LGT = "lgt.usda"
    PHY = "phy.usda"            # Physics APIs (RigidBody/Mass/Collision)
    CONTENTS = "contents.usda"  # References to the assets added to this asset
    VARIANTS = "variants.usda"  # Variant set declarations + opinions
    MAPS = "maps"
    TEXTURES = "textures"


class AssetFolderNamespace:
    """Prim names BowerBot authors under an asset's root prim."""

    # Scope that holds the assets added to this asset (authored in contents.usda).
    CONTENTS_SCOPE = "contents"
    # Scope that holds the asset's lights (authored in lgt.usda).
    LIGHTS_SCOPE = "lgt"
    # Scope that holds the asset's materials (authored in mtl.usda).
    MATERIALS_SCOPE = "mtl"


class AssetFolderRules:
    """What counts as a USD layer in an asset folder, and how the root references them."""

    # File extensions of a USD layer inside an asset folder.
    USD_LAYER_EXTENSIONS: frozenset[str] = frozenset({".usd", ".usda", ".usdc"})
    # The extension that is always text, where an asset path is written between @ signs.
    TEXT_LAYER_EXTENSION = ".usda"
    # Side layers a library asset folder may ship, besides its root and geometry files.
    LIBRARY_SIDE_LAYERS: frozenset[str] = frozenset({
        ASWFLayerNames.MTL,
        ASWFLayerNames.LGT,
        ASWFLayerNames.PHY,
        ASWFLayerNames.VARIANTS,
    })
    # Order the asset root references its side layers in (strongest first).
    CANONICAL_REFERENCE_ORDER: tuple[str, ...] = (
        ASWFLayerNames.VARIANTS,
        ASWFLayerNames.CONTENTS,
        ASWFLayerNames.LGT,
        ASWFLayerNames.MTL,
        ASWFLayerNames.PHY,
    )
