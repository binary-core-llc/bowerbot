# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Data schemas used across BowerBot."""

from enum import Enum

from pydantic import BaseModel, Field


# ── Asset Schemas ──────────────────────────────────────────────


class AssetFormat(str, Enum):
    """Supported 3D asset formats."""

    USD = ".usd"
    USDA = ".usda"
    USDC = ".usdc"
    USDZ = ".usdz"


# ── Texture Schemas ───────────────────────────────────────────


class HDRIFormat(str, Enum):
    """HDRI / environment map formats."""

    HDR = ".hdr"
    HDRI = ".hdri"
    EXR = ".exr"


class ImageFormat(str, Enum):
    """Material texture image formats."""

    PNG = ".png"
    JPG = ".jpg"
    JPEG = ".jpeg"
    TIF = ".tif"
    TIFF = ".tiff"
    TGA = ".tga"
    BMP = ".bmp"


class TextureCategory(str, Enum):
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
    format: AssetFormat = AssetFormat.USDZ
    bbox_min: tuple[float, float, float] | None = None
    bbox_max: tuple[float, float, float] | None = None
    tags: list[str] = Field(default_factory=list)
    license: str | None = None


# ── Scene Graph Schemas ────────────────────────────────────────


class PlacementCategory(str, Enum):
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


# ── Light Schemas ─────────────────────────────────────────────


class LightType(str, Enum):
    """Supported USD light types."""

    DISTANT = "DistantLight"
    DOME = "DomeLight"
    SPHERE = "SphereLight"
    RECT = "RectLight"
    DISK = "DiskLight"
    CYLINDER = "CylinderLight"


class LightParams(BaseModel):
    """Parameters for creating a USD light."""

    prim_path: str
    light_type: LightType
    intensity: float = 1000.0
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


# ── Material Schemas ──────────────────────────────────────────


class MaterialBinding(BaseModel):
    """A material and the prims bound to it."""

    material_prim_path: str  # e.g. "/mtl/wood_varnished"
    material_name: str  # e.g. "wood_varnished"
    bound_prims: list[str] = Field(default_factory=list)


# ── Validation Schemas ─────────────────────────────────────────


class Severity(str, Enum):
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
