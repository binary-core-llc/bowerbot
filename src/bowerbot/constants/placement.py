# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Placement values."""


class PlacementRules:
    """Limits on what a placement call accepts."""

    # Placements one place_layout call may create.
    MAX_LAYOUT_PLACEMENTS = 100_000


class PlacementDefaults:
    """Fallbacks when a placement call leaves a value out."""

    # Distance above an asset's top, along its up axis, for a bounds-offset
    # position that gives no up value, in meters (converted to the asset's units).
    ABOVE_OFFSET_METERS = 0.5
    # Distance between grid positions, in meters (converted to project units).
    GRID_SPACING_METERS = 2.0
    # Floor size of the room a grid is centered in, in meters (converted to project units).
    GRID_ROOM_METERS = (10.0, 8.0)
