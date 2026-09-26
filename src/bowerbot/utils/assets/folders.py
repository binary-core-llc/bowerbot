# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset folders — intaking a whole library folder as a self-contained ASWF asset."""

from __future__ import annotations

import logging
from pathlib import Path

from bowerbot.schemas import DetectionOutcome, IntakeReport
from bowerbot.utils.assets.aswf import normalize_root_metadata
from bowerbot.utils.assets.localize import localize
from bowerbot.utils.core.asset_folder import detect_folder_root

logger = logging.getLogger(__name__)


def intake_folder(source_folder: Path, project_assets_dir: Path) -> IntakeReport:
    """Copy *source_folder* into *project_assets_dir* as a self-contained asset.

    The root is written as ``<folder>.usda`` (converted to text if it was a
    binary file) and every file it depends on is copied and re-pathed, so
    the copy composes exactly like the source. The root's own arcs are
    kept as authored.
    """
    detection = detect_folder_root(source_folder)
    if detection.outcome is DetectionOutcome.AMBIGUOUS:
        names = ", ".join(Path(c).name for c in detection.candidates)
        msg = (
            f"Folder {source_folder.name} has multiple independent USD files "
            f"with no cross-references ({names}). ASWF expects a single root. "
            f"Rename one to '{source_folder.name}.usda' or place the files "
            f"individually."
        )
        raise ValueError(msg)
    if detection.root is None:
        msg = f"No USD files found in {source_folder}"
        raise ValueError(msg)

    source_root = Path(detection.root)
    target_folder = project_assets_dir.resolve() / source_folder.name
    if target_folder.exists():
        return _reuse_existing_target(target_folder, source_root)

    canonical_root = target_folder / f"{target_folder.name}.usda"
    copy = localize(source_root, source_folder, canonical_root)
    normalize_root_metadata(canonical_root, target_folder.name)

    logger.info(
        "Intaked %s -> %s (%d file(s), %d localized)",
        source_folder.name, target_folder.name,
        copy.files_copied, len(copy.localized_layers) + len(copy.localized_assets),
    )
    return IntakeReport(
        scene_ref_path=f"assets/{target_folder.name}/{canonical_root.name}",
        asset_folder_name=target_folder.name,
        root_original_name=source_root.name,
        root_canonical_name=canonical_root.name,
        was_renamed=source_root.name != canonical_root.name,
        files_copied=copy.files_copied,
        localized_layers=copy.localized_layers,
        localized_assets=copy.localized_assets,
    )


def _reuse_existing_target(target_folder: Path, source_root: Path) -> IntakeReport:
    """Build an IntakeReport for a target folder that already exists."""
    canonical = target_folder / f"{target_folder.name}.usda"
    if not canonical.exists():
        msg = (
            f"Target folder {target_folder} exists but has no canonical "
            f"root '{canonical.name}'. Delete it and retry."
        )
        raise RuntimeError(msg)
    normalize_root_metadata(canonical, target_folder.name)
    return IntakeReport(
        scene_ref_path=f"assets/{target_folder.name}/{canonical.name}",
        asset_folder_name=target_folder.name,
        root_original_name=source_root.name,
        root_canonical_name=canonical.name,
        was_renamed=source_root.name != canonical.name,
        files_copied=0,
        warnings=["target folder already existed; source was not re-copied"],
    )
