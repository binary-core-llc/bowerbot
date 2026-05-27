# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared UsdSchemaRegistry introspection helpers."""

from __future__ import annotations

from typing import Any

from pxr import Sdf, Usd


def property_doc(
    prim_def: Usd.PrimDefinition, prop_name: str, spec: Sdf.PropertySpec,
) -> str:
    """Best-effort documentation lookup across USD versions."""
    getter = getattr(prim_def, "GetPropertyDocumentation", None)
    if callable(getter):
        return getter(prop_name) or ""
    return spec.GetInfo("documentation") or ""


def to_jsonable(value: Any) -> Any:
    """Convert pxr values to JSON-friendly Python for summaries."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if hasattr(value, "__iter__") and not isinstance(value, str):
        try:
            return [float(c) for c in value]
        except (TypeError, ValueError):
            return str(value)
    return str(value)
