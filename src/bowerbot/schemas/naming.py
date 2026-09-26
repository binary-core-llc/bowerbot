# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Naming schemas — the rules prim and variant names follow."""


class NamingRules:
    """What makes a USD prim name or a variant name valid (ASCII, for portability)."""

    # Prim and variant-set names: an identifier.
    PRIM_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"
    # Variant names may also use '-' and '|' and start with a digit.
    VARIANT_NAME_PATTERN = r"[A-Za-z0-9_|\-]+"
    # Runs of characters a cleaned prim or variant name replaces with '_'.
    PRIM_NAME_INVALID = r"[^A-Za-z0-9_]+"
    VARIANT_NAME_INVALID = r"[^A-Za-z0-9_|\-]+"
