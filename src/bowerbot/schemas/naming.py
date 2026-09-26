# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Naming schemas — the rules prim and variant names follow."""


class NamingRules:
    """What makes a USD prim name or a variant name valid."""

    PRIM_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"
    VARIANT_NAME_FORBIDDEN = frozenset(" \t\n\r/\\")
