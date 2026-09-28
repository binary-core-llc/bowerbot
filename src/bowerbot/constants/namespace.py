# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Values for renaming, moving and removing prims."""


class NamespaceRules:
    """What makes a prim spec count as empty."""

    # Prim spec fields that are not authored content: an over with only these is empty.
    INTRINSIC_PRIM_INFO_KEYS = frozenset({"specifier", "typeName"})
