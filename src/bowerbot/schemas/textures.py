# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Texture and HDRI file-format schemas."""

from enum import StrEnum


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
