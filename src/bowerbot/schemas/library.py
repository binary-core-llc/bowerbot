# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library schemas — what an asset library scan looks at and returns."""

from bowerbot.schemas.assets import AssetCategory


class LibraryRules:
    """What an asset library scan looks at and returns."""

    # The only categories scan_library assigns: package roots, loose materials,
    # loose geometry. 'lgt' is an ASWF layer kind, never a library result.
    CATEGORIES = (AssetCategory.PACKAGE, AssetCategory.MTL, AssetCategory.GEO)
    # Category filter that matches every category.
    ALL = "all"
    # Folders that hold an asset's support files, not assets.
    NON_ASSET_DIRS = frozenset({"cache", "maps", "materials"})


class LibraryDefaults:
    """Values a library search uses when the request leaves them out."""

    SEARCH_LIMIT = 25
