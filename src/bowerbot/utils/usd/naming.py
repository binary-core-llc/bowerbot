# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Valid and safe USD names: prims (assets, lights, cameras, joints, groups) and variants."""

from bowerbot import constants

# ── Prim names ──


def is_valid_prim_name(name: str) -> bool:
    """Whether *name* is a legal USD prim identifier."""
    return constants.NamingRules.PRIM_NAME.match(name) is not None


def safe_prim_name(name: str) -> str:
    """Sanitize a string into a USD prim name: letters, digits and underscores only."""
    return "".join(
        c for c in name if c.isalnum() or c == "_"
    ).strip()


def clean_prim_name(raw: str, what: str = "name") -> str:
    """*raw* without the characters USD refuses; refused when no prim name is left."""
    cleaned = safe_prim_name(raw)
    if not is_valid_prim_name(cleaned):
        raise ValueError(
            f"{what} {raw!r} is not a valid USD prim name: use letters, digits and "
            "underscores, and do not start with a digit.",
        )
    return cleaned


def require_prim_name(name: str, what: str = "name") -> None:
    """Refuse *name* unless it is a prim name exactly as given (nothing is cleaned)."""
    if not is_valid_prim_name(name):
        raise ValueError(
            f"{what} {name!r} is not a valid USD prim name: use letters, digits and "
            "underscores, and do not start with a digit.",
        )


# ── Variant names ──


def is_valid_variant_set_name(name: str) -> bool:
    """Whether *name* can name a variant set: the same rule as a prim name."""
    return is_valid_prim_name(name)


def is_valid_variant_name(name: str) -> bool:
    """Whether *name* can name a variant: letters, digits, ``_``, ``-``, ``|``, a leading dot."""
    return constants.NamingRules.VARIANT_NAME.match(name) is not None


def validate_variant_set_name(name: str) -> None:
    """Raise ``ValueError`` if *name* cannot name a variant set."""
    if not is_valid_variant_set_name(name):
        raise ValueError(
            f"Invalid variant set name: {name!r} (use letters, digits and underscores, "
            "and do not start with a digit).",
        )


def validate_variant_name(name: str) -> None:
    """Raise ``ValueError`` if *name* cannot name a variant."""
    if not is_valid_variant_name(name):
        raise ValueError(
            f"Invalid variant name: {name!r} (use letters, digits, underscores and hyphens).",
        )


def safe_variant_name(raw: str) -> str:
    """*raw* with every character a variant name cannot hold replaced by ``_``."""
    return "".join(
        c if c.isascii() and (c.isalnum() or c in "_|-") else "_" for c in raw
    )
