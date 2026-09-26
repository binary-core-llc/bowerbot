# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Override schemas — scene opinions that can mask what an asset layer authors."""

from typing import Literal

type OpinionKind = Literal["attribute", "relationship", "active"]

# (scene prim path, kind, attribute or relationship name — "active" for kind "active")
type MaskingOpinion = tuple[str, OpinionKind, str]


class OverrideRules:
    """What counts as an empty override."""

    # Prim-spec info every spec carries; not authored content.
    INTRINSIC_INFO_KEYS = frozenset({"specifier", "typeName"})
