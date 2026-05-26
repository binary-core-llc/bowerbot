# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Diagnostic finding schemas; subsystem checks emit these into a unified report."""

from enum import StrEnum

from pydantic import BaseModel, Field

from bowerbot.schemas.validation import Severity


class FindingStatus(StrEnum):
    """Per-check outcome."""

    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"


class Finding(BaseModel):
    """One diagnostic check result."""

    check_id: str
    subsystem: str
    status: FindingStatus
    severity: Severity = Severity.INFO
    message: str
    prim_path: str | None = None
    evidence: dict = Field(default_factory=dict)
    fix_hint: str | None = None


class DiagnosticReport(BaseModel):
    """Aggregate of every check run for one diagnose invocation."""

    focus: str | None = None
    findings: list[Finding] = Field(default_factory=list)

    @property
    def fail_count(self) -> int:
        """Number of findings with FAIL status."""
        return sum(1 for f in self.findings if f.status == FindingStatus.FAIL)

    @property
    def is_healthy(self) -> bool:
        """Whether every check passed (no FAILs)."""
        return self.fail_count == 0
