# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Values — JSON ↔ USD conversion, and number and 3-float parsing."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from pxr import Gf, Sdf

from bowerbot.schemas.transforms import Vec3


def usd_to_json(value: object) -> object:
    """Render a USD-typed value as a JSON-friendly Python value."""
    if value is None:
        return None
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Sdf.AssetPath):
        return value.path or str(value)
    if isinstance(value, Gf.Quatd | Gf.Quatf | Gf.Quath):
        # Real part first, as USD writes quaternions: [w, x, y, z].
        return [value.GetReal(), *value.GetImaginary()]
    # Gf vectors and matrices have no __iter__; iter() walks them by index.
    if (
        hasattr(value, "__len__")
        and hasattr(value, "__getitem__")
        and not isinstance(value, bytes)
    ):
        items = list(iter(value))
        if items and isinstance(usd_to_json(items[0]), list):
            return [usd_to_json(v) for v in items]
        try:
            return [float(c) for c in items]
        except (TypeError, ValueError):
            return [str(c) for c in items]
    return str(value)


def from_float32(value: float) -> float:
    """A float32 read from USD as the shortest decimal that is the same float32.

    USD hands float attributes back widened to double (9.81 reads as
    9.8100004196167); this gives back the 9.81 that was authored.
    """
    return float(str(np.float32(value)))


def json_to_usd(value: object, type_name: Sdf.ValueTypeName) -> object:
    """Cast a JSON-shaped value to match a USD attribute's declared type."""
    if type_name.isArray:
        items = _decode_json_string(value, type_name)
        if not isinstance(items, list | tuple):
            msg = f"value {value!r} does not match {type_name}; pass a list, one entry per element."
            raise ValueError(msg)
        elements = []
        for index, item in enumerate(items):
            try:
                elements.append(json_to_usd(item, type_name.scalarType))
            except ValueError as exc:
                raise ValueError(f"element {index} of {type_name}: {exc}") from None
        return elements

    raw = str(type_name).lower()

    if raw in ("token", "string"):
        return str(value)
    if raw == "asset":
        return Sdf.AssetPath(str(value))

    value = _decode_json_string(value, type_name)
    if raw in ("float", "half", "double"):
        return _number(value, type_name)
    if raw in ("int", "uchar", "uint", "int64", "uint64"):
        return int(_number(value, type_name))
    if raw == "bool":
        return _boolean(value, type_name)
    return _gf_value(value, type_name)


def infer_sdf_type(value: object) -> Sdf.ValueTypeName:
    """Guess an Sdf type from a JSON-shaped value."""
    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Float
    if isinstance(value, str):
        return Sdf.ValueTypeNames.Token
    if isinstance(value, list | tuple):
        if value and isinstance(value[0], list | tuple):
            return infer_sdf_type(value[0]).arrayType
        n = len(value)
        if n == 2:
            return Sdf.ValueTypeNames.Float2
        if n == 3:
            return Sdf.ValueTypeNames.Color3f
        if n == 4:
            return Sdf.ValueTypeNames.Color4f
    return Sdf.ValueTypeNames.Float


def coerce_number(value: object, what: object) -> float:
    """Coerce a scalar (or its JSON-encoded string) to float with a curated error."""
    return _number(_decode_json_string(value, what), what)


def to_vec3(value: object, name: str = "vector") -> Vec3:
    """Exactly 3 numbers (or their JSON strings) as a float triple."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(
            f"{name!r} must be a list of 3 numbers; got {value!r}",
        )
    x, y, z = (coerce_number(v, name) for v in value)
    return x, y, z


def parse_vec3(value: object, name: str = "vector") -> Vec3 | None:
    """Like ``to_vec3``, but ``None`` stays ``None``."""
    if value is None:
        return None
    return to_vec3(value, name)


def unpack_vec3(
    params: dict[str, Any],
    kx: str,
    ky: str,
    kz: str,
) -> Vec3 | None:
    """Read a triple of optional keys; return ``None`` if all are missing."""
    if all(params.get(k) is None for k in (kx, ky, kz)):
        return None
    return (
        float(params.get(kx, 0.0)),
        float(params.get(ky, 0.0)),
        float(params.get(kz, 0.0)),
    )


def _gf_value(value: object, type_name: Sdf.ValueTypeName) -> object:
    """Build the Gf quaternion, matrix or vector *type_name* holds; other values pass through."""
    default = type_name.defaultValue
    if isinstance(default, Gf.Quatd | Gf.Quatf | Gf.Quath):
        w, x, y, z = _number_seq(value, 4, type_name)
        return type(default)(w, x, y, z)
    if isinstance(default, Gf.Matrix2d | Gf.Matrix3d | Gf.Matrix4d):
        size = len(default)
        if not isinstance(value, list | tuple) or len(value) != size:
            msg = f"value {value!r} does not match {type_name}; pass {size} rows of {size} numbers."
            raise ValueError(msg)
        return type(default)(*(n for row in value for n in _number_seq(row, size, type_name)))
    if hasattr(default, "__len__") and hasattr(default, "__getitem__"):
        numbers = _number_seq(value, len(default), type_name)
        if isinstance(default[0], int):
            return type(default)(*(int(n) for n in numbers))
        return type(default)(*numbers)
    return value


def _decode_json_string(value: object, what: object) -> object:
    """Decode a JSON-encoded string sent for a non-string value."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        msg = (
            f"value {value!r} is not valid for {what}; pass JSON matching "
            f"the type (e.g. a list of numbers for vectors, true/false "
            f"for bools)."
        )
        raise ValueError(msg) from None


def _number(value: object, what: object) -> float:
    """Coerce a scalar to float with a curated error."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"value {value!r} is not a number; {what} needs one."
        raise ValueError(msg)
    return float(value)


def _boolean(value: object, what: object) -> bool:
    """Coerce a bool (or 0/1) with a curated error."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    msg = f"value {value!r} is not a bool; {what} needs true or false."
    raise ValueError(msg)


def _number_seq(value: object, arity: int, what: object) -> list[float]:
    """Coerce a sequence of *arity* numbers with a curated error."""
    if not isinstance(value, (list, tuple)) or len(value) != arity:
        msg = (
            f"value {value!r} does not match {what}; "
            f"pass a list of {arity} numbers."
        )
        raise ValueError(msg)
    return [_number(item, what) for item in value]
