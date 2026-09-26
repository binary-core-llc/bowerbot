# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD compliance — running USD's ValidationFramework and surfacing its issues."""

from __future__ import annotations

import functools
import logging
from pathlib import Path

from pxr import Sdr, Usd, UsdShade, UsdValidation

from bowerbot.schemas import MaterialXShaders, Severity, UsdValidatorNames, ValidationIssue

logger = logging.getLogger(__name__)


def run_usd_compliance_checker(file_path: str | Path) -> list[ValidationIssue]:
    """Run USD's ValidationFramework against *file_path*; issues come back in a stable order.

    Without MaterialX in this USD build the shader registry cannot resolve
    MaterialX ids (``ND_*``), so those shaders skip that one check and are
    reported once as INFO instead of one false error each.
    """
    contexts = _get_validation_contexts()
    if contexts is None:
        return []
    stage_context, shader_context = contexts

    stage = Usd.Stage.Open(str(file_path))
    if stage is None:
        return []

    unchecked: list[Usd.Prim] = []
    try:
        errors = list(stage_context.Validate(stage))
        if shader_context is not None:
            shaders = [prim for prim in stage.Traverse() if prim.IsA(UsdShade.Shader)]
            unchecked = [prim for prim in shaders if _is_materialx_shader(prim)]
            checked = [prim for prim in shaders if not _is_materialx_shader(prim)]
            if checked:
                errors += shader_context.Validate(checked)
    except Exception as exc:
        logger.warning("USD validation failed on %s: %s", file_path, exc)
        return []

    issues = [_to_issue(err) for err in errors]
    if unchecked:
        issues.append(ValidationIssue(
            severity=Severity.INFO,
            message=(
                f"MaterialX shaders not checked against the shader registry: this USD "
                f"build has no MaterialX support ({len(unchecked)} shader(s) with "
                f"{MaterialXShaders.NODE_DEF_PREFIX}* ids)."
            ),
        ))
    return sorted(issues, key=_issue_order)


def _to_issue(err: UsdValidation.ValidationError) -> ValidationIssue:
    """One USD validation error as a ValidationIssue."""
    severity = (
        Severity.ERROR
        if err.GetType() == UsdValidation.ValidationErrorType.Error
        else Severity.WARNING
    )
    sites = err.GetSites()
    prim_path = (
        str(sites[0].GetPrim().GetPath())
        if sites and sites[0].GetPrim() else None
    )
    return ValidationIssue(
        severity=severity,
        message=f"{err.GetName()}: {err.GetMessage()}",
        prim_path=prim_path,
    )


def _issue_order(issue: ValidationIssue) -> tuple[int, str, str]:
    """Errors, then warnings, then notes; by prim path and message within each."""
    return list(Severity).index(issue.severity), issue.prim_path or "", issue.message


def _is_materialx_shader(prim: Usd.Prim) -> bool:
    """Whether *prim* is a shader whose id is a MaterialX node definition."""
    shader_id = UsdShade.Shader(prim).GetIdAttr().Get()
    return isinstance(shader_id, str) and shader_id.startswith(MaterialXShaders.NODE_DEF_PREFIX)


def _get_validation_contexts() -> tuple[
    UsdValidation.ValidationContext, UsdValidation.ValidationContext | None,
] | None:
    """The shared validation contexts, or ``None`` if they cannot be built."""
    try:
        return _validation_contexts()
    except Exception as exc:
        logger.warning("Failed to build USD validation context: %s", exc)
        return None


@functools.cache
def _validation_contexts() -> tuple[
    UsdValidation.ValidationContext, UsdValidation.ValidationContext | None,
]:
    """Build the contexts once: the whole stage, plus the shader-registry check on its own.

    The second context exists only when this USD build lacks MaterialX; it then
    runs on the non-MaterialX shaders while the first runs everything else.
    """
    validators = UsdValidation.ValidationRegistry().GetOrLoadAllValidators()
    if MaterialXShaders.SDR_SOURCE_TYPE in Sdr.Registry().GetAllShaderNodeSourceTypes():
        return UsdValidation.ValidationContext(validators), None
    shader_check = UsdValidatorNames.SHADER_SDR_COMPLIANCE
    stage_validators = [v for v in validators if v.GetMetadata().name != shader_check]
    shader_validators = [v for v in validators if v.GetMetadata().name == shader_check]
    return (
        UsdValidation.ValidationContext(stage_validators),
        UsdValidation.ValidationContext(shader_validators),
    )
