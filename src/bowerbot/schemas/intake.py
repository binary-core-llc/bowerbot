# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset-folder intake schemas."""

from enum import StrEnum

from pydantic import BaseModel, Field


class DetectionOutcome(StrEnum):
    """Classification for ``detect_folder_root``."""

    UNAMBIGUOUS = "unambiguous"  # a single root file was identified
    AMBIGUOUS = "ambiguous"      # multiple independent USD files, no clear root
    EMPTY = "empty"              # folder has no USD files


class FolderDetection(BaseModel):
    """Outcome of inspecting a source folder for a canonical root."""

    outcome: DetectionOutcome
    folder: str
    root: str | None = None
    candidates: list[str] = Field(default_factory=list)
    reason: str = ""


class IntakeReport(BaseModel):
    """Outcome of copying a source folder into the project."""

    scene_ref_path: str
    asset_folder_name: str

    root_original_name: str
    root_canonical_name: str
    was_renamed: bool

    files_copied: int
    localized_layers: list[str] = Field(default_factory=list)
    localized_assets: list[str] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)
