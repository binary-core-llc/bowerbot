# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Running USD's own validators (the ValidationFramework) on a file and reporting what they find."""

from __future__ import annotations

import functools
import logging
from pathlib import Path

from pxr import Usd
from pxr import UsdValidation

from bowerbot import schemas

logger = logging.getLogger(__name__)

# ── Running USD's validators ──


def run_usd_compliance_checker(file_path: str | Path) -> list[schemas.ValidationIssue]:
    """Run USD's modern ValidationFramework against *file_path*."""
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
    return _issues(errors)


def run_validators_on_stage(stage: Usd.Stage, keyword: str) -> list[schemas.ValidationIssue]:
    """What USD's validators tagged *keyword* report on an open stage, unsaved edits included."""
    try:
        return _issues(_keyword_context(keyword).Validate(stage))
    except Exception as exc:
        logger.warning("USD validation (%s) failed: %s", keyword, exc)
        return []


# ── Helpers ──


def _issues(errors: list[UsdValidation.ValidationError]) -> list[schemas.ValidationIssue]:
    """USD's validation errors as issues, in an order that does not change between runs."""
    issues: list[schemas.ValidationIssue] = []
    for err in errors:
        severity = (
            schemas.Severity.ERROR
            if err.GetType() == UsdValidation.ValidationErrorType.Error
            else schemas.Severity.WARNING
        )
        sites = err.GetSites()
        prim_path = (
            str(sites[0].GetPrim().GetPath())
            if sites and sites[0].GetPrim() else None
        )
        issues.append(schemas.ValidationIssue(
            severity=severity,
            message=f"{err.GetName()}: {err.GetMessage()}",
            prim_path=prim_path,
        ))
    # USD runs its validators in parallel, so the order it reports in changes from run to run.
    issues.sort(key=lambda issue: (issue.prim_path or "", issue.message))
    return issues


@functools.cache
def _keyword_context(keyword: str) -> UsdValidation.ValidationContext:
    """A ValidationContext with the validators tagged *keyword*, built once."""
    registry = UsdValidation.ValidationRegistry()
    names = [metadata.name for metadata in registry.GetValidatorMetadataForKeyword(keyword)]
    return UsdValidation.ValidationContext(registry.GetOrLoadValidatorsByName(names))


@functools.cache
def _validation_context() -> UsdValidation.ValidationContext:
    """Build a ValidationContext with all registered validators, once.

    A failed build raises and is not cached, so the next call tries again.
    """
    registry = UsdValidation.ValidationRegistry()
    validators = registry.GetOrLoadAllValidators()
    return UsdValidation.ValidationContext(validators)


def _get_validation_context() -> UsdValidation.ValidationContext | None:
    """The shared ValidationContext, or ``None`` when it cannot be built."""
    try:
        return _validation_context()
    except Exception as exc:
        logger.warning("Failed to build USD validation context: %s", exc)
        return None
