# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Valid and safe USD names: prims, variants, joints, collision groups."""

from bowerbot import constants

# ── Checking names ──


def is_valid_prim_name(name: str) -> bool:
    """Whether *name* is a legal USD prim identifier."""
    return constants.NamingRules.PRIM_NAME.match(name) is not None


def is_valid_variant_set_name(name: str) -> bool:
    """Reject empty names or names with whitespace / path separators."""
    return bool(name) and not any(c in constants.NamingRules.FORBIDDEN_CHARS for c in name)


def validate_variant_name(name: str, label: str = "variant") -> None:
    """Raise ``ValueError`` if ``name`` is not a valid variant identifier."""
    if not is_valid_variant_set_name(name):
        raise ValueError(f"Invalid {label} name: {name!r}")


def validate_joint_name(name: str) -> None:
    """Refuse an empty joint name, or one with whitespace or path separators."""
    if not name:
        raise ValueError("Joint name cannot be empty.")
    bad = [c for c in name if c in constants.NamingRules.FORBIDDEN_CHARS]
    if bad:
        raise ValueError(
            f"Joint name {name!r} has invalid characters "
            f"{sorted(set(bad))}; use letters, digits, and underscores.",
        )


def validate_group_name(name: str) -> None:
    """Refuse an empty collision group name, or one with whitespace or path separators."""
    if not name:
        raise ValueError("Collision group name cannot be empty.")
    bad = [c for c in name if c in constants.NamingRules.FORBIDDEN_CHARS]
    if bad:
        raise ValueError(
            f"Collision group name {name!r} has invalid characters "
            f"{sorted(set(bad))}; use letters, digits, and underscores.",
        )


# ── Making names safe ──


def safe_prim_name(name: str) -> str:
    """Sanitize a string for use as a USD prim name.

    USD prim names only allow alphanumeric characters and
    underscores — no hyphens, spaces, or special characters.
    """
    return "".join(
        c for c in name if c.isalnum() or c == "_"
    ).strip()
