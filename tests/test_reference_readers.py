# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The one reader of a prim spec's references and payloads."""

from __future__ import annotations

from pxr import Sdf

from bowerbot.utils import usd


def test_reference_and_payload_readers_see_every_way_of_adding(tmp_path):
    """A prepended, appended, added or explicit arc counts; a deleted or reordered one does not."""
    layer = Sdf.Layer.CreateNew(str(tmp_path / "arcs.usda"))
    layer.ImportFromString("""#usda 1.0
def "mixed" (
    prepend references = @./pre.usda@
    append references = @./app.usda@
    add references = @./add.usda@
    delete references = @./gone.usda@
    reorder references = [@./app.usda@, @./only_ordered.usda@]
    prepend payload = @./load.usda@
) {}
def "explicit" (references = [@./one.usda@, @./two.usda@]) {}
def "none" (payload = None) {}
""")
    mixed = layer.GetPrimAtPath("/mixed")
    assert sorted(usd.references.reference_paths(mixed)) == [
        "./add.usda", "./app.usda", "./pre.usda",
    ]
    assert usd.references.payload_paths(mixed) == ["./load.usda"]
    assert usd.references.reference_paths(layer.GetPrimAtPath("/explicit")) == [
        "./one.usda", "./two.usda",
    ]
    assert usd.references.payload_paths(layer.GetPrimAtPath("/none")) == []
    targets = {path.name for path in usd.references.layer_file_targets(layer)}
    assert targets == {"pre.usda", "app.usda", "add.usda", "load.usda", "one.usda", "two.usda"}
