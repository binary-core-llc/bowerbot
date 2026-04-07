# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SceneGraphBuilder — converts semantic layout decisions into
exact spatial coordinates.
"""

import math
from dataclasses import dataclass

from bowerbot.schemas import PlacementCategory

# Default vertical offset (meters) above an asset's top surface
# when placing a light with no explicit Y position.
DEFAULT_LIGHT_Y_OFFSET = 0.5


@dataclass
class Placement:
    """A computed placement position."""

    translate: tuple[float, float, float]
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)


class SceneGraphBuilder:
    """Computes spatial positions and transforms for objects in a scene."""

    def __init__(
        self,
        room_bounds: tuple[float, float, float] = (10.0, 3.0, 8.0),
    ) -> None:
        self.room_width, self.room_height, self.room_depth = room_bounds

    def compute_placement(
        self,
        category: PlacementCategory,
        surface_height: float = 0.0,
    ) -> float:
        """Compute the Y position based on placement category."""
        match category:
            case PlacementCategory.FLOOR:
                return 0.0
            case PlacementCategory.SURFACE:
                return surface_height
            case PlacementCategory.CEILING:
                return self.room_height
            case PlacementCategory.WALL:
                return 0.0
            case _:
                return 0.0

    def suggest_grid_layout(
        self,
        count: int,
        spacing: float = 2.0,
        center: tuple[float, float] | None = None,
    ) -> list[Placement]:
        """Compute positions for N objects in a grid layout.

        Automatically determines rows/columns to fit the count,
        centered in the room or at the specified center point.
        """
        if count <= 0:
            return []

        cols = math.ceil(math.sqrt(count))
        rows = math.ceil(count / cols)

        cx = center[0] if center else self.room_width / 2
        cz = center[1] if center else self.room_depth / 2

        x_offset = cx - (cols - 1) * spacing / 2
        z_offset = cz - (rows - 1) * spacing / 2

        placements = []
        for i in range(count):
            row = i // cols
            col = i % cols
            x = x_offset + col * spacing
            z = z_offset + row * spacing
            placements.append(Placement(translate=(x, 0.0, z)))

        return placements

    def suggest_wall_layout(
        self,
        count: int,
        wall: str = "back",
        spacing: float = 2.0,
        wall_offset: float = 0.05,
    ) -> list[Placement]:
        """Place objects along a wall."""
        placements = []
        total_span = (count - 1) * spacing

        for i in range(count):
            offset_along = -total_span / 2 + i * spacing

            match wall:
                case "back":
                    x = self.room_width / 2 + offset_along
                    z = wall_offset
                    ry = 0.0
                case "front":
                    x = self.room_width / 2 + offset_along
                    z = self.room_depth - wall_offset
                    ry = 180.0
                case "left":
                    x = wall_offset
                    z = self.room_depth / 2 + offset_along
                    ry = 90.0
                case "right":
                    x = self.room_width - wall_offset
                    z = self.room_depth / 2 + offset_along
                    ry = -90.0
                case _:
                    x, z, ry = 0.0, 0.0, 0.0

            placements.append(Placement(translate=(x, 0.0, z), rotate=(0.0, ry, 0.0)))

        return placements

    @staticmethod
    def apply_bounds_offsets(
        bounds: dict[str, dict[str, float]],
        tx: float,
        ty: float,
        tz: float,
        has_explicit_y: bool,
    ) -> tuple[float, float, float]:
        """Convert offset-from-bounds values to absolute positions.

        For asset-level lights, translate values are offsets from the
        geometry's bounding box surfaces. This computes the final
        position from those offsets and the asset bounds.

        Args:
            bounds: Geometry bounds dict with ``min``, ``max``,
                ``center`` keys, each containing ``x``, ``y``, ``z``.
            tx: X offset from center.
            ty: Y offset from top (positive) or bottom (negative)
                surface. Ignored when *has_explicit_y* is ``False``
                — defaults to 0.5m above the top surface.
            tz: Z offset from center.
            has_explicit_y: Whether the caller provided an explicit
                Y value. When ``False``, defaults to 0.5m above top.

        Returns:
            Absolute ``(x, y, z)`` position tuple.
        """
        tx = bounds["center"]["x"] + tx
        tz = bounds["center"]["z"] + tz

        if has_explicit_y:
            if ty >= 0:
                ty = bounds["max"]["y"] + ty
            else:
                ty = bounds["min"]["y"] + ty
        else:
            ty = bounds["max"]["y"] + DEFAULT_LIGHT_Y_OFFSET

        return tx, ty, tz

    def check_collision(
        self,
        pos_a: tuple[float, float, float],
        size_a: tuple[float, float, float],
        pos_b: tuple[float, float, float],
        size_b: tuple[float, float, float],
    ) -> bool:
        """Check if two axis-aligned bounding boxes overlap."""
        for i in range(3):
            half_a = size_a[i] / 2
            half_b = size_b[i] / 2
            if abs(pos_a[i] - pos_b[i]) >= (half_a + half_b):
                return False
        return True
