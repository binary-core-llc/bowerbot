# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset library values."""

from bowerbot.schemas import AssetCategory, AssetFormat


class LibraryRules:
    """What the library scan lists, and the category filters it accepts."""

    # File extensions the library scan lists as assets.
    USD_EXTENSIONS: frozenset[str] = frozenset(f.value for f in AssetFormat)
    # Top-level library folders that never hold a package.
    NON_ASSET_DIRS: frozenset[str] = frozenset({"cache", "maps", "materials"})
    # The category filter that lists every category.
    ANY_CATEGORY: str = "all"
    # The only categories scan_library assigns: package roots, loose materials,
    # loose geometry. Source of truth for the listable-category filter; 'lgt' is
    # an ASWF layer kind, never a library result.
    CATEGORIES: tuple[AssetCategory, ...] = (
        AssetCategory.PACKAGE,
        AssetCategory.MTL,
        AssetCategory.GEO,
    )


class LibraryDefaults:
    """Fallbacks for library searches."""

    # Results returned when a search or listing gives no limit.
    SEARCH_LIMIT: int = 25
