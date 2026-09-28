# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Validation values."""


class AppleUSDZConstraints:
    """Apple consumer USDZ subset (AR Quick Look on iOS Files/Safari/iMessage).

    Targets the broadest Apple consumer path. visionOS and iOS 18+
    RealityKit are permissive supersets (MaterialX, subdivision) but
    the strict subset works everywhere.
    """

    TEXTURE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
