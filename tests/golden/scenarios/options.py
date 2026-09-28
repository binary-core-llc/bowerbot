# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Every remaining option of every tool: physics, scatter, placement, layout, lights,
cameras, materials, listings, and refusals of the tools that take no input."""

from __future__ import annotations

from tests.golden import model

CRATE = {"asset": "$lib/crate.usda"}


def _place(
    asset: str,
    name: str,
    group: str = "Props",
    x: float = 0.0,
    up: float = 0.0,
    save: str | None = None,
) -> model.Step:
    return model.Step(
        "place_asset",
        {"asset_file_path": f"$lib/{asset}", "asset_name": name, "group": group, **model.at(x, up)},
        save=save,
        note=f"place {asset} as {name}",
    )


def _ground() -> model.Step:
    return _place("ground.usda", "Ground", "Architecture", save="ground")


SCENARIOS = (
    model.Scenario(
        "physics/every_api_and_joint",
        "Every physics API and joint type, relationships, and both scopes.",
        (
            _ground(),
            _place("crate.usda", "Crate", x=-1.0, save="a"),
            _place("crate.usda", "Crate", x=1.0, save="b"),
            model.Step("setup_physics_scene", {"name": "World"}, note="a named physics scene"),
            model.Step(
                "apply_physics_api",
                {
                    "prim_path": "$ground/asset/Plane",
                    "api_name": "PhysicsCollisionAPI",
                    "scope": "asset",
                    "relationships": {"physics:simulationOwner": ["/Scene/Physics/World"]},
                },
                note="a collider on the ground mesh, owned by the World scene",
            ),
            model.Step(
                "apply_physics_api",
                {
                    "prim_path": "$ground/asset/Plane",
                    "api_name": "PhysicsMeshCollisionAPI",
                    "scope": "asset",
                    "attributes": {"physics:approximation": "none"},
                },
                note="exact mesh collision on the ground",
            ),
            model.Step(
                "apply_physics_api",
                {"prim_path": "$a/asset", "api_name": "PhysicsRigidBodyAPI", "scope": "asset"},
            ),
            model.Step(
                "apply_physics_api",
                {
                    "prim_path": "$a/asset",
                    "api_name": "PhysicsArticulationRootAPI",
                    "scope": "asset",
                },
                note="an articulation root on the crate",
            ),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsPrismaticJoint",
                    "name": "Slide",
                    "body0": "$a/asset",
                    "body1": "$b/asset",
                    "scope": "scene",
                    "attributes": {"physics:axis": "X"},
                },
            ),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsSphericalJoint",
                    "name": "Ball",
                    "body0": "$a/asset",
                    "body1": "$b/asset",
                    "scope": "scene",
                },
            ),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsDistanceJoint",
                    "name": "Rope",
                    "body0": "$a/asset",
                    "body1": "$b/asset",
                    "scope": "scene",
                    "attributes": {"physics:maxDistance": 2.0},
                },
            ),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsRevoluteJoint",
                    "name": "Door",
                    "body0": "$a/asset",
                    "body1": "$b/asset",
                    "scope": "scene",
                },
            ),
            model.Step(
                "list_physics_api_properties",
                {"api_name": "PhysicsDriveAPI", "instance_name": "angular"},
            ),
            model.Step(
                "apply_physics_api",
                {
                    "prim_path": "/Scene/Physics/Door",
                    "api_name": "PhysicsDriveAPI",
                    "instance_name": "angular",
                    "attributes": {"drive:angular:physics:stiffness": 100.0},
                },
                note="a drive on the revolute joint",
            ),
            model.Step(
                "apply_physics_api",
                {
                    "prim_path": "/Scene/Physics/Door",
                    "api_name": "PhysicsLimitAPI",
                    "instance_name": "angular",
                },
                note="a limit on the revolute joint",
            ),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsFixedJoint",
                    "name": "Glue",
                    "body0": "$a/asset/Box",
                    "body1": "$a/asset",
                    "scope": "asset",
                    "asset_anchor_prim_path": "$a",
                },
                note="an asset joint anchored on the first crate",
            ),
            model.Step("list_joints", {"under_prim_path": "/Scene/Physics"}),
            model.Step(
                "remove_physics_api",
                {
                    "prim_path": "/Scene/Physics/Door",
                    "api_name": "PhysicsDriveAPI",
                    "instance_name": "angular",
                },
            ),
            model.Step(
                "remove_physics_api",
                {
                    "prim_path": "/Scene/Physics/Door",
                    "api_name": "PhysicsLimitAPI",
                    "instance_name": "angular",
                },
            ),
            model.Step(
                "remove_physics_api",
                {
                    "prim_path": "$a/asset",
                    "api_name": "PhysicsArticulationRootAPI",
                    "scope": "asset",
                },
            ),
            model.Step(
                "remove_physics_api",
                {
                    "prim_path": "$ground/asset/Plane",
                    "api_name": "PhysicsMeshCollisionAPI",
                    "scope": "asset",
                },
            ),
            model.Step(
                "setup_physics_scene",
                {"gravity_direction": [0, 0, 0]},
                note="a gravity direction of zero length",
            ),
        ),
    ),
    model.Scenario(
        "physics/masking_and_groups",
        "A scene value masking the asset's physics, the masking flags, and group options.",
        (
            _place("crate.usda", "Crate", x=-1.0, save="a"),
            _place("crate.usda", "Crate", x=1.0, save="b"),
            model.Step(
                "apply_physics_api",
                {
                    "prim_path": "$b/asset",
                    "api_name": "PhysicsMassAPI",
                    "scope": "scene",
                    "attributes": {"physics:mass": 40.0},
                },
                note="crate b gets its own mass",
            ),
            model.Step(
                "apply_physics_api",
                {
                    "prim_path": "$a/asset",
                    "api_name": "PhysicsMassAPI",
                    "scope": "asset",
                    "attributes": {"physics:mass": 5.0},
                },
                note="the asset's mass: masked on crate b",
            ),
            model.Step(
                "apply_physics_api",
                {
                    "prim_path": "$a/asset",
                    "api_name": "PhysicsMassAPI",
                    "scope": "asset",
                    "attributes": {"physics:mass": 5.0},
                    "confirm_masked": True,
                },
                note="author it anyway",
            ),
            model.Step(
                "apply_physics_api",
                {
                    "prim_path": "$a/asset",
                    "api_name": "PhysicsMassAPI",
                    "scope": "asset",
                    "attributes": {"physics:mass": 6.0},
                    "clear_masking_overrides": True,
                },
                note="clear crate b's own mass first",
            ),
            model.Step(
                "remove_physics_api",
                {
                    "prim_path": "$a/asset",
                    "api_name": "PhysicsMassAPI",
                    "scope": "asset",
                    "confirm_masked": True,
                },
            ),
            model.Step(
                "remove_physics_api",
                {
                    "prim_path": "$a/asset",
                    "api_name": "PhysicsMassAPI",
                    "scope": "asset",
                    "clear_masking_overrides": True,
                },
            ),
            model.Step(
                "create_or_update_collision_group",
                {"name": "Crates", "includes": ["$a", "$b"], "invert_filter": True},
                note="a group that collides only with what it filters",
            ),
            model.Step(
                "create_or_update_collision_group",
                {"name": "Stack", "includes": ["$a"], "merge_group": "Merged"},
                note="a group merged with others under one name",
            ),
            model.Step("list_collision_groups"),
        ),
    ),
    model.Scenario(
        "scatter/every_surface_option",
        "scatter_on_surface with every option: alignment, variation, avoidance, regions.",
        (
            _ground(),
            _place("table.usda", "Table", "Furniture", save="table"),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Tuned",
                    "group": "Props",
                    "assets": [
                        {"asset": "$lib/crate.usda", "weight": 2},
                        {"asset": "$lib/unfrozen.usda", "fix_root_transforms": True},
                        {"asset": "$lib/rooted_mesh.usda", "fix_root_prim": True},
                    ],
                    "surfaces": ["$ground"],
                    "arrangement": "random",
                    "count": 6,
                    "seed": 7,
                    "min_spacing": model.Meters(0.8),
                    "avoid": ["$table"],
                    "avoid_margin": model.Meters(0.5),
                    "align": "surface",
                    "random_yaw": False,
                    "tilt_jitter_degrees": 5.0,
                    "scale_range": [0.8, 1.2],
                    "embed": model.Meters(0.02),
                    "max_slope_degrees": 30.0,
                    "variation": 0.5,
                    "variation_scale": 2.0,
                    "output": "instancer",
                },
                note="random, every tuning option, avoiding the table",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Upright",
                    "assets": [CRATE],
                    "surfaces": ["$ground"],
                    "count": 3,
                    "seed": 8,
                    "align": "up",
                    "region": {
                        "center_prim": "$table",
                        "radius": model.Meters(3.0),
                        "falloff": "linear",
                    },
                },
                note="around the table, fading out linearly",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Soft",
                    "assets": [CRATE],
                    "surfaces": ["$ground"],
                    "count": 3,
                    "seed": 9,
                    "region": {
                        "center": model.Point(-3.0, 0.0, -3.0),
                        "radius": model.Meters(1.5),
                        "falloff": "smooth",
                    },
                },
                note="a smooth falloff",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Hard",
                    "assets": [CRATE],
                    "surfaces": ["$ground"],
                    "count": 3,
                    "seed": 10,
                    "region": {
                        "center": model.Point(3.0, 0.0, -3.0),
                        "radius": model.Meters(1.5),
                        "falloff": "none",
                    },
                },
                note="no falloff",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Grid",
                    "assets": [CRATE],
                    "surfaces": ["$ground"],
                    "arrangement": "rows",
                    "spacing": model.Meters(1.0),
                    "row_spacing": model.Meters(1.0),
                    "row_direction_degrees": 45.0,
                    "jitter": model.Meters(0.1),
                    "seed": 11,
                    "region": {"center": model.Point(3.0, 0.0, 3.0), "radius": model.Meters(1.5)},
                },
                note="rows turned 45 degrees with jitter",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Heap",
                    "assets": [CRATE],
                    "surfaces": ["$ground"],
                    "arrangement": "pile",
                    "count": 5,
                    "seed": 12,
                    "repose_degrees": 25.0,
                    "region": {"center": model.Point(-3.0, 0.0, 3.0), "radius": model.Meters(1.0)},
                },
                note="a pile with a 25-degree angle of repose",
            ),
        ),
    ),
    model.Scenario(
        "scatter/every_path_option",
        "scatter_along_path with every option: circles, curves, sides, facing, order, output.",
        (
            _ground(),
            _place("path_curve.usda", "Path", "Architecture", save="path"),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Circle",
                    "assets": [CRATE],
                    "circle": {
                        "center": model.Point(0.0, 0.0, 0.0),
                        "radius": model.Meters(3.0),
                        "start_angle_degrees": 90.0,
                    },
                    "count": 6,
                    "facing": "center",
                    "output": "instancer",
                },
                note="six crates on a circle, facing its center",
            ),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Halo",
                    "assets": [CRATE],
                    "circle": {"center_prim": "$ground", "radius": model.Meters(4.0)},
                    "count": 4,
                    "facing": "outward",
                    "output": "placements",
                },
                note="around the ground's center, facing out",
            ),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Curve",
                    "group": "Props",
                    "assets": [
                        {"asset": "$lib/crate.usda", "weight": 1},
                        {"asset": "$lib/unfrozen.usda", "fix_root_transforms": True},
                        {"asset": "$lib/rooted_mesh.usda", "fix_root_prim": True},
                    ],
                    "curve_prim": "$path/asset/Curve",
                    "spacing": model.Meters(1.0),
                    "start_offset": model.Meters(0.5),
                    "gap": model.Meters(0.2),
                    "sides": "left",
                    "offset": model.Meters(0.5),
                    "facing": "tangent",
                    "yaw_offset_degrees": 90.0,
                    "asset_order": "cycle",
                    "scale_range": [0.9, 1.1],
                    "seed": 3,
                },
                note="along the curve, on its left, cycling three assets",
            ),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Right",
                    "assets": [CRATE],
                    "points": [model.Point(-4.0, 0.0, 4.0), model.Point(4.0, 0.0, 4.0)],
                    "count": 3,
                    "sides": "right",
                    "offset": model.Meters(0.5),
                    "facing": "fixed",
                    "direction_degrees": 30.0,
                    "asset_order": "random",
                    "seed": 4,
                },
            ),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Middle",
                    "assets": [CRATE],
                    "points": [model.Point(-4.0, 0.0, -4.0), model.Point(4.0, 0.0, -4.0)],
                    "count": 3,
                    "sides": "center",
                    "facing": "random",
                    "seed": 5,
                    "surfaces": ["$ground"],
                    "snap": True,
                    "follow_slope": True,
                    "align": "surface",
                    "embed": model.Meters(0.01),
                },
                note="snapped onto the ground and following its slope",
            ),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Upright",
                    "assets": [CRATE],
                    "points": [model.Point(-2.0, 0.0, 0.0), model.Point(2.0, 0.0, 0.0)],
                    "count": 2,
                    "align": "up",
                    "validate_only": True,
                },
                note="validate only",
            ),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Right",
                    "assets": [CRATE],
                    "points": [model.Point(-4.0, 0.0, 4.0), model.Point(4.0, 0.0, 4.0)],
                    "count": 5,
                    "replace": True,
                    "seed": 6,
                },
                note="replace the right-side row",
            ),
            model.Step(
                "drop_to_surface",
                {
                    "prim_paths": ["/Scene/Scatter/Halo"],
                    "surfaces": ["$ground"],
                    "align": "surface",
                },
                note="drop the halo, aligning to the surface",
            ),
            model.Step(
                "drop_to_surface",
                {"prim_paths": ["/Scene/Scatter/Halo"], "surfaces": ["$ground"], "align": "keep"},
                note="drop again, keeping orientation",
            ),
        ),
    ),
    model.Scenario(
        "placement/every_option",
        "The remaining placement and layout options.",
        (
            _place("chair.usda", "Lamp", "Lighting", save="lamp"),
            _place("table.usda", "Table", "Furniture", x=3.0, save="table"),
            model.Step(
                "place_asset_inside",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "A",
                    "container_prim_path": "$table",
                    "group": "Architecture",
                    **model.at(0.0),
                    "rotate_y": 30.0,
                    "position_mode": "bounds_offset",
                },
                note="bounds_offset mode, turned 30 degrees",
            ),
            model.Step(
                "place_asset_inside",
                {
                    "asset_file_path": "$lib/unfrozen.usda",
                    "asset_name": "B",
                    "container_prim_path": "$table",
                    "group": "Furniture",
                    **model.at(0.2),
                    "fix_root_transforms": True,
                    "confirm_shared_modification": True,
                },
            ),
            model.Step(
                "place_asset_inside",
                {
                    "asset_file_path": "$lib/rooted_mesh.usda",
                    "asset_name": "C",
                    "container_prim_path": "$table",
                    "group": "Lighting",
                    **model.at(-0.2),
                    "fix_root_prim": True,
                },
            ),
            model.Step(
                "place_asset_inside",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "D",
                    "container_prim_path": "$table",
                    "group": "Products",
                    **model.at(0.0),
                },
            ),
            model.Step(
                "place_layout",
                {
                    "placements": [
                        {
                            "asset": "$lib/crate.usda",
                            "group": "Props",
                            "rotate": [0, 45, 0],
                            "scale": 2.0,
                            "transforms": [
                                {"translate": model.Point(6.0, 0.0, 0.0)},
                                {"translate": model.Point(7.0, 0.0, 0.0), "scale": [1, 2, 1]},
                            ],
                        },
                        {
                            "asset": "$lib/unfrozen.usda",
                            "group": "Props",
                            "fix_root_transforms": True,
                            "transforms": [{"translate": model.Point(8.0, 0.0, 0.0)}],
                        },
                        {
                            "asset": "$lib/rooted_mesh.usda",
                            "group": "Props",
                            "fix_root_prim": True,
                            "transforms": [{"translate": model.Point(9.0, 0.0, 0.0)}],
                        },
                    ]
                },
                note="default rotate and scale, a per-placement scale, repairs",
            ),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "lights/every_option",
        "The remaining light and camera options.",
        (
            _place("lamp/lamp.usda", "Lamp", save="lamp"),
            model.Step(
                "create_light",
                {
                    "light_type": "DiskLight",
                    "light_name": "Disk",
                    **model.at(0.0, 3.0, 0.0),
                    "rotate_x": 10.0,
                    "rotate_y": 20.0,
                    "rotate_z": 30.0,
                },
                save="disk",
                note="turned on all three axes",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Glow",
                    "asset_prim_path": "$lamp",
                    "position_mode": "bounds_offset",
                    **model.at(0.0, 0.1, 0.0),
                },
                save="glow",
                note="an asset light placed by bounds offset",
            ),
            model.Step("update_light", {"prim_path": "$disk", "rotate_y": 90.0, "rotate_z": 0.0}),
            model.Step(
                "update_light",
                {"prim_path": "$glow", "position_mode": "absolute", **model.at(0.0, 0.8, 0.0)},
            ),
            model.Step(
                "update_light",
                {
                    "prim_path": "$glow",
                    "position_mode": "bounds_offset",
                    **model.at(0.0, 0.05, 0.0),
                },
            ),
            model.Step(
                "create_camera",
                {
                    "camera_name": "Tilted",
                    **model.at(0.0, 2.0, 4.0),
                    "rotate_x": -10.0,
                    "rotate_y": 15.0,
                    "rotate_z": 5.0,
                },
                save="cam",
            ),
            model.Step("update_camera", {"prim_path": "$cam", "rotate_x": -20.0, "rotate_y": 0.0}),
        ),
    ),
    model.Scenario(
        "materials/every_option",
        "The remaining material options: shared binding and cleanup scoped to one asset.",
        (
            _place("table.usda", "Table", "Furniture", save="table"),
            _place("table.usda", "Table", "Furniture", x=2.0, save="table_2"),
            model.Step(
                "bind_material",
                {
                    "prim_path": "$table/asset/Top",
                    "material_file": "$lib/materials/oak.usda",
                    "confirm_shared_modification": True,
                },
                note="bind to a shared asset, confirmed",
            ),
            model.Step(
                "create_material",
                {
                    "prim_path": "$table/asset/Top",
                    "material_name": "walnut",
                    "confirm_shared_modification": True,
                },
            ),
            model.Step(
                "cleanup_unused_materials",
                {"asset_prim_path": "$table"},
                note="clean up only this asset",
            ),
            model.Step("cleanup_unused_contents", {"asset_prim_path": "$table"}),
            model.Step("cleanup_unused_materials", {"asset_prim_path": "/Scene/Nope"}),
        ),
    ),
    model.Scenario(
        "library/every_option",
        "Library and texture listings with every category and limit, and refusals of the tools "
        "that take no input.",
        (
            model.Step("list_assets", {"category": "all", "limit": 3}),
            model.Step("list_textures", {"category": "all"}),
            model.Step("list_textures", {"category": "material"}),
            model.Step("search_textures", {"query": "o", "category": "all"}),
            model.Step("search_textures", {"query": "studio", "category": "hdri"}),
            model.Step("compute_grid_layout", {"count": -2}, note="a negative count"),
            model.Step(
                "compute_grid_layout", {"count": 4, "spacing": -1.0}, note="a negative spacing"
            ),
            model.Step(
                "get_current_project", {"nope": 1}, note="a parameter the tool does not take"
            ),
            model.Step("list_projects", {"nope": 1}),
            model.Step("list_camera_properties", {"nope": 1}),
            model.Step(
                "list_light_type_properties",
                {"light_type": "LaserLight"},
                note="a light type that does not exist",
            ),
        ),
    ),
)
