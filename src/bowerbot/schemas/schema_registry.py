# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Schema-registry schemas — a property a USD prim or API schema declares."""

from typing import Any

from pydantic import BaseModel


class SchemaPropertySpec(BaseModel):
    """One property a USD schema declares, read from the schema registry."""

    name: str
    kind: str  # "attribute" or "relationship"
    type_name: str | None = None
    default: Any = None
    allowed_tokens: list[str] = []
    documentation: str = ""
