# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Validation result schemas."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    """Validation issue severity."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    """A single validation finding."""

    severity: Severity
    message: str
    prim_path: str | None = None


class ValidationResult(BaseModel):
    """Result of running the validator on a stage."""

    is_valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        """Number of issues with ERROR severity."""
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)
