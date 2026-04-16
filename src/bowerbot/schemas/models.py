# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Data schemas used across BowerBot."""

from enum import StrEnum

from pydantic import BaseModel, Field


class AssetFormat(StrEnum):
    """Supported 3D asset formats."""

    USD = ".usd"
    USDA = ".usda"
    USDC = ".usdc"
    USDZ = ".usdz"


class AssetCategory(StrEnum):
    """Classification of a USD asset following ASWF conventions."""

    GEO = "geo"          # geometry layer
    MTL = "mtl"          # materials + bindings layer
    LGT = "lgt"          # lighting layer
    PACKAGE = "package"  # ASWF-compliant asset folder


class ASWFLayerNames:
    """ASWF USD Working Group standard layer file names.

    Centralized here so no hardcoded strings are scattered
    across the codebase. Used by AssetAssembler and LocalSkill.

    Reference: https://github.com/usd-wg/assets/blob/main/docs/asset-structure-guidelines.md
    """

    GEO = "geo.usda"
    MTL = "mtl.usda"
    LGT = "lgt.usda"
    CONTENTS = "contents.usda"  # Nested asset references placed inside this asset
    MAPS = "maps"
    TEXTURES = "textures"




class MaterialXShaders:
    """MaterialX shader identifiers and naming conventions."""

    STANDARD_SURFACE = "ND_standard_surface_surfaceshader"
    STANDARD_SURFACE_PRIM = "standard_surface"
    OUTPUT_QUALIFIER = "mtlx"


class ProceduralMaterialParams(BaseModel):
    """Parameters for creating a procedural MaterialX material."""

    material_name: str
    base_color: tuple[float, float, float] = (0.8, 0.8, 0.8)
    metalness: float = 0.0
    roughness: float = 0.5
    opacity: float = 1.0


class HDRIFormat(StrEnum):
    """HDRI / environment map formats."""

    HDR = ".hdr"
    HDRI = ".hdri"
    EXR = ".exr"


class ImageFormat(StrEnum):
    """Material texture image formats."""

    PNG = ".png"
    JPG = ".jpg"
    JPEG = ".jpeg"
    TIF = ".tif"
    TIFF = ".tiff"
    TGA = ".tga"
    BMP = ".bmp"


class TextureCategory(StrEnum):
    """Texture search categories."""

    HDRI = "hdri"
    MATERIAL = "material"
    ALL = "all"

    def extensions(self) -> set[str]:
        """Return the file extensions for this category."""
        hdri = {f.value for f in HDRIFormat}
        image = {f.value for f in ImageFormat}
        match self:
            case TextureCategory.HDRI:
                return hdri
            case TextureCategory.MATERIAL:
                return image
            case _:
                return hdri | image


class AssetMetadata(BaseModel):
    """Metadata for a 3D asset sourced from any skill."""

    name: str
    source_skill: str  # e.g. "sketchfab", "local", "cgtrader"
    source_id: str  # Skill-specific identifier (URL, SKU, file path)
    file_path: str | None = None  # Local path after download


class TransformParams(BaseModel):
    """A prim transform (translate + rotate + scale).

    Reusable across any operation that places a prim — nested assets,
    cameras, or other scene/asset objects.
    """

    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)




class PositionMode(StrEnum):
    """Coordinate system used when placing a prim inside an asset.

    * ``absolute`` — translate values are asset-local coordinates in the
      asset's native units. Use when you know the exact position, e.g.
      from a `list_prim_children` bounds reading or a precise layout.
    * ``bounds_offset`` — translate values are offsets from the asset's
      bounding box surfaces (center for X/Z, top/bottom for Y). Use
      for "above/below/next to" placements like a bulb above a lamp.
    """

    ABSOLUTE = "absolute"
    BOUNDS_OFFSET = "bounds_offset"


class PlacementCategory(StrEnum):
    """Where an object category gets placed by default."""

    FLOOR = "floor"  # Y = 0 (tables, chairs, shelves)
    SURFACE = "surface"  # Y = furniture_height (products, displays)
    CEILING = "ceiling"  # Y = room_height (pendant lights)
    WALL = "wall"  # Against wall boundary


class SceneObject(BaseModel):
    """An object placed in the scene graph."""

    prim_path: str  # e.g. "/Scene/Furniture/Table_01"
    asset: AssetMetadata
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    category: PlacementCategory = PlacementCategory.FLOOR




class LightType(StrEnum):
    """Supported USD light types."""

    DISTANT = "DistantLight"
    DOME = "DomeLight"
    SPHERE = "SphereLight"
    RECT = "RectLight"
    DISK = "DiskLight"
    CYLINDER = "CylinderLight"


class LightParams(BaseModel):
    """Parameters describing a USD light.

    Contains only the light's own attributes. Placement context
    (scene prim path or asset folder + light name) is passed
    separately to the engine methods.
    """

    light_type: LightType
    intensity: float = 1000.0
    exposure: float = 0.0  # Power of 2 multiplier on intensity (camera stops)
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # Type-specific (only relevant ones used per light type)
    angle: float | None = None  # DistantLight
    texture: str | None = None  # DomeLight HDRI path
    radius: float | None = None  # SphereLight, DiskLight, CylinderLight
    width: float | None = None  # RectLight
    height: float | None = None  # RectLight
    length: float | None = None  # CylinderLight




class Severity(StrEnum):
    """Validation issue severity."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    """A single validation finding."""

    severity: Severity
    message: str
    prim_path: str | None = None


class ValidationResult(BaseModel):
    """Result of running the validator on a stage."""

    is_valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)
