# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Naming values: which prim, variant, joint and group names are valid."""

import re


class NamingRules:
    """Characters and patterns a name must follow."""

    # A legal USD prim name.
    PRIM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
    # Characters refused in variant, variant set, joint and collision group names.
    FORBIDDEN_CHARS = frozenset(" \t\n\r/\\")
