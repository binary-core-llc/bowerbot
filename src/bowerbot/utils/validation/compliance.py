# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD compliance — running USD's ValidationFramework and surfacing its issues."""

from __future__ import annotations

import functools
import logging
from pathlib import Path

from pxr import Usd, UsdValidation

from bowerbot.schemas import Severity, ValidationIssue

logger = logging.getLogger(__name__)


def run_usd_compliance_checker(file_path: str | Path) -> list[ValidationIssue]:
    """Run USD's ValidationFramework against *file_path* and surface its issues."""
    ctx = _get_validation_context()
    if ctx is None:
        return []

    stage = Usd.Stage.Open(str(file_path))
    if stage is None:
        return []

    try:
        errors = ctx.Validate(stage)
    except Exception as exc:
        logger.warning("USD validation failed on %s: %s", file_path, exc)
        return []

    issues: list[ValidationIssue] = []
    for err in errors:
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
        issues.append(ValidationIssue(
            severity=severity,
            message=f"{err.GetName()}: {err.GetMessage()}",
            prim_path=prim_path,
        ))
    return issues


def _get_validation_context() -> UsdValidation.ValidationContext | None:
    """The shared ValidationContext, or ``None`` if it cannot be built."""
    try:
        return _validation_context()
    except Exception as exc:
        logger.warning("Failed to build USD validation context: %s", exc)
        return None


@functools.cache
def _validation_context() -> UsdValidation.ValidationContext:
    """Build a ValidationContext with every registered validator, once."""
    registry = UsdValidation.ValidationRegistry()
    return UsdValidation.ValidationContext(registry.GetOrLoadAllValidators())
