# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset-folder intake schemas."""

from pydantic import BaseModel
from pydantic import Field


class IntakeReport(BaseModel):
    """Outcome of copying a source folder into the project."""

    scene_ref_path: str
    asset_folder_name: str

    root_original_name: str
    root_canonical_name: str
    was_renamed: bool

    files_copied: int

    warnings: list[str] = Field(default_factory=list)
