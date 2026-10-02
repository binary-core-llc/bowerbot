# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD's own physics rules: what its validators report, and refusing an edit that adds to it.

A physics tool makes its edit, asks USD's validators whether the scene now has
an error it did not have before, and only then saves. The rules are USD's, so
what BowerBot accepts and what ``validate_scene`` reports cannot disagree.

Physics is set with the physics tools only: a variant may not change it.
"""

from __future__ import annotations

from typing import Any

from pxr import Usd

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import usd


def errors(stage: Usd.Stage) -> set[str]:
    """Every physics error USD's validators report on *stage*, unsaved edits included."""
    return {
        issue.message
        for issue in usd.compliance.run_validators_on_stage(
            stage, constants.PhysicsRules.VALIDATOR_KEYWORD,
        )
        if issue.severity == schemas.Severity.ERROR
    }


def refuse_in_variant(overrides: dict[str, dict[str, Any]]) -> None:
    """Refuse variant overrides of physics attributes: BowerBot has no physics variants."""
    namespace = constants.PhysicsRules.ATTRIBUTE_NAMESPACE
    found = sorted(
        f"{prim_path}.{name}" for prim_path, attributes in overrides.items()
        for name in attributes if namespace in name.split(":")[:-1]
    )
    if found:
        raise ValueError(
            f"A variant cannot change physics attributes ({', '.join(found)}): "
            "BowerBot has no physics variants. Set physics with apply_physics_api or "
            "create_joint, where every change is checked against USD's physics rules.",
        )


def refuse_new_errors(stage: Usd.Stage, known: set[str], doing: str) -> None:
    """Refuse an edit, not saved yet, that gave *stage* a physics error *known* does not have."""
    new = sorted(errors(stage) - known)
    if new:
        found = "; ".join(message.rstrip(".") for message in new)
        raise ValueError(
            f"{doing} is refused: USD's physics rules would then report "
            f"{len(new)} error(s): {found}. Nothing was changed.",
        )
