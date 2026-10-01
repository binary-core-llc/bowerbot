# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""What a variant holds: the opinions each kind of variant authors inside its body."""

from __future__ import annotations

from typing import Any

from pxr import Sdf
from pxr import Usd
from pxr import UsdShade

from bowerbot.utils import usd


def author_bindings(stage: Usd.Stage, bindings: dict[str, str]) -> None:
    """Bind each mesh path to its material path."""
    for mesh_path, material_path in bindings.items():
        mesh_over = stage.OverridePrim(mesh_path)
        binding_api = UsdShade.MaterialBindingAPI.Apply(mesh_over)
        binding_api.GetDirectBindingRel().SetTargets([Sdf.Path(material_path)])


def author_payloads(stage: Usd.Stage, payloads: dict[str, str]) -> None:
    """Replace each prim's payloads with one payload file."""
    for target_path, payload_asset in payloads.items():
        target = stage.OverridePrim(target_path)
        target.GetPayloads().ClearPayloads()
        target.GetPayloads().AddPayload(payload_asset)


def author_overrides(
    stage: Usd.Stage,
    overrides: dict[str, dict[str, Any]],
    resolved_types: dict[str, dict[str, Sdf.ValueTypeName | None]],
) -> None:
    """Set each prim's attributes to the override values, with their declared types."""
    for path, attrs in overrides.items():
        stage.OverridePrim(path)
        types = resolved_types[path]
        for attr_name, value in attrs.items():
            usd.attributes.set_prim_attribute(
                stage, path, attr_name, value,
                expected_type=types[attr_name],
            )


def author_activations(stage: Usd.Stage, activations: dict[str, bool]) -> None:
    """Switch each prim on or off."""
    for prim_path, active in activations.items():
        stage.OverridePrim(prim_path).SetActive(active)


def author_references(stage: Usd.Stage, prim_path: str, refs: list[str]) -> None:
    """Replace the prim's references with *refs*."""
    ov = stage.OverridePrim(prim_path)
    ov.GetReferences().ClearReferences()
    for r in refs:
        ov.GetReferences().AddReference(r)
