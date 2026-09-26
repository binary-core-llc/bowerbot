# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for name cleaning: prim names, prim paths, groups and variant names."""

import pytest

from bowerbot.utils.core.naming import (
    clean_group,
    clean_prim_name,
    clean_prim_path,
    clean_variant_name,
)


@pytest.mark.parametrize(("raw", "expected"), [
    ("Chair", "Chair"),
    ("_private", "_private"),
    ("Key Light", "Key_Light"),
    ("3D Table", "_3D_Table"),
    ("front--left  wheel", "front_left_wheel"),
    ("Lámpara Café", "Lampara_Cafe"),
    (" Sofa! ", "Sofa"),
])
def test_clean_prim_name(raw, expected):
    assert clean_prim_name(raw, "Asset") == expected


@pytest.mark.parametrize("raw", ["", "!!!", "桌子"])
def test_clean_prim_name_refuses_a_name_with_nothing_usable(raw):
    with pytest.raises(ValueError, match="Light name"):
        clean_prim_name(raw, "Light")


def test_clean_prim_name_fallback_for_derived_names():
    assert clean_prim_name("椅子", "Prototype", fallback="Prototype") == "Prototype"
    assert clean_prim_name("Silla 2", "Prototype", fallback="Prototype") == "Silla_2"


def test_clean_prim_path_cleans_every_segment():
    assert clean_prim_path("/Scene/Living Room/2nd Table", "New path") == (
        "/Scene/Living_Room/_2nd_Table"
    )
    with pytest.raises(ValueError, match="absolute"):
        clean_prim_path("Scene/Table", "New path")


def test_clean_group_keeps_nesting():
    assert clean_group("2nd Floor//Wet Area") == "_2nd_Floor/Wet_Area"
    with pytest.raises(ValueError, match="names no scope"):
        clean_group(" / ")


@pytest.mark.parametrize(("raw", "expected"), [
    ("oak", "oak"),
    ("2k", "2k"),
    ("LOD-0", "LOD-0"),
    ("a|b", "a|b"),
    ("light oak", "light_oak"),
    ("v/1.2", "v_1_2"),
])
def test_clean_variant_name(raw, expected):
    assert clean_variant_name(raw) == expected
