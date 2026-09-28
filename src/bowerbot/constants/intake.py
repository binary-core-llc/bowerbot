# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset intake values."""


class IntakeRules:
    """How intake recognizes an asset folder's root file."""

    # File names that mark a folder's root when several USD files could be it.
    ROOT_NAME_HINTS: tuple[str, ...] = ("root", "main", "asset")
