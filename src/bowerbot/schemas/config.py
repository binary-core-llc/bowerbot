# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Config schemas — where BowerBot keeps its own files."""

from pathlib import Path


class ConfigPaths:
    """BowerBot's home folder and the files it keeps there."""

    HOME = Path.home() / ".bowerbot"
    CONFIG_FILE = HOME / "config.json"
    # What each loose library file was classified as, so it is read only once.
    LIBRARY_INDEX = HOME / "library_index.json"
