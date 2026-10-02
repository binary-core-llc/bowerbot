# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Naming values: which prim and variant names are valid."""

import re


class NamingRules:
    """Characters and patterns a name must follow."""

    # A legal USD prim name.
    PRIM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
    # A legal USD variant name (a variant SET name follows PRIM_NAME).
    VARIANT_NAME = re.compile(r"\.?[A-Za-z0-9_|\-]+\Z")
