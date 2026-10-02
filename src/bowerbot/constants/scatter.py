# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter values: canonical names, limits, defaults and algorithm knobs."""


class ScatterNamespace:
    """Canonical names BowerBot uses when authoring a scatter."""

    DEFAULT_GROUP = "Scatter"
    PROTOTYPES = "Prototypes"


class ScatterRules:
    """Limits on what a scatter call accepts."""

    MAX_INSTANCES = 1_000_000
    MAX_PLACEMENTS = 10_000
    # Pieces one pile may hold.
    MAX_PILE_PIECES = 20_000
    # Refusal when a surface scatter gives neither a count nor a density.
    COUNT_OR_DENSITY = "a surface scatter needs a count or a density."


class ScatterDefaults:
    """Fallbacks when a scatter call leaves a value out."""

    # Default pile tilt off the flattest side, degrees.
    PILE_TILT_DEGREES = 10.0


class ScatterTuning:
    """Internal knobs of the scatter algorithms."""

    # Points a circle path is drawn with.
    PATH_SEGMENTS = 256
    # How far a scatter's stored box may be from the measured one, relative to its size.
    EXTENT_TOLERANCE = 1e-4
    # Sampling rounds tried to reach an exact count.
    MAX_SAMPLE_ROUNDS = 24
    # Most points drawn in one sampling round.
    MAX_SAMPLE_BATCH = 2_000_000
    # Candidates drawn per wanted instance when a minimum spacing thins them.
    SPACING_OVERSAMPLE = 6
    # Most candidates drawn for minimum-spacing thinning.
    MAX_SPACING_CANDIDATES = 400_000
    # Instance count above which a scatter warns about scene.usda size.
    LARGE_SCATTER = 100_000
    # Samples used to measure the area a region or avoid list leaves.
    AREA_PROBE = 20_000
    # Share of a model's height treated as its base.
    BASE_SLICE = 0.05
    # Samples per side of a piece's base footprint.
    BASE_GRID = 3
    # Steepest face whose ground is plane-fitted from above.
    FIT_MAX_SLOPE_DEGREES = 60.0
    # Most stranded pieces a drop's answer lists.
    STRANDED_REPORT = 20
    # Most cells per side of a pile's heightfield.
    PILE_GRID = 400
    # Pile drops tried per piece, and base growth when none fits the cone.
    PILE_TRIES = 16
    PILE_GROWTH = 1.05
    PILE_GROWTH_STEPS = 4
    # Share of a piece's box it fills; sizes the pile heightfield.
    PILE_SOLIDITY = 0.5
    # Vertices sampled per prototype.
    SHAPE_POINTS = 1500
    # Footprint samples per side when dropping a placement onto a surface.
    DROP_FOOTPRINT = 3
    # Bytes one instance adds to an ASCII .usda layer.
    ASCII_BYTES_PER_INSTANCE = 116
