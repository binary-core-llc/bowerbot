# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot's fixed values, grouped by domain.

Each domain file groups its values in classes named for what they hold:
``<Domain>Rules`` (what BowerBot accepts), ``<Domain>Defaults`` (fallbacks
when a call leaves a value out), ``<Domain>Tuning`` (internal algorithm
knobs), ``<Domain>Namespace`` (prim and file names BowerBot authors) and
``<Domain>Usd`` (the pxr classes and values behind a name). Import from
``bowerbot.constants``; this package re-exports every class.
"""

from bowerbot.constants.asset_folder import AssetFolderRules, ASWFLayerNames
from bowerbot.constants.cameras import CameraDefaults, CameraTuning
from bowerbot.constants.intake import IntakeRules
from bowerbot.constants.library import LibraryDefaults, LibraryRules
from bowerbot.constants.lights import LightDefaults, LightRules, LightUsd
from bowerbot.constants.materials import MaterialRules, MaterialXShaders, PreviewSurfaceShader
from bowerbot.constants.metrics import MetricsUsd
from bowerbot.constants.namespace import NamespaceRules
from bowerbot.constants.naming import NamingRules
from bowerbot.constants.physics import PhysicsNamespace, PhysicsRules, PhysicsUsd
from bowerbot.constants.placement import PlacementRules
from bowerbot.constants.scatter import (
    ScatterDefaults,
    ScatterNamespace,
    ScatterRules,
    ScatterTuning,
)
from bowerbot.constants.scene import SceneNamespace
from bowerbot.constants.surface import SurfaceTuning
from bowerbot.constants.transforms import TransformUsd
from bowerbot.constants.validation import AppleUSDZConstraints

__all__ = [
    "AppleUSDZConstraints",
    "ASWFLayerNames",
    "AssetFolderRules",
    "CameraDefaults",
    "CameraTuning",
    "IntakeRules",
    "LibraryDefaults",
    "LibraryRules",
    "LightDefaults",
    "LightRules",
    "LightUsd",
    "MaterialRules",
    "MaterialXShaders",
    "MetricsUsd",
    "NamespaceRules",
    "NamingRules",
    "PhysicsNamespace",
    "PhysicsRules",
    "PhysicsUsd",
    "PlacementRules",
    "PreviewSurfaceShader",
    "ScatterDefaults",
    "ScatterNamespace",
    "ScatterRules",
    "ScatterTuning",
    "SceneNamespace",
    "SurfaceTuning",
    "TransformUsd",
]
