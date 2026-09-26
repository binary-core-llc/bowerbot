# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Config schemas — where BowerBot keeps its own files."""

from pathlib import Path


class ConfigPaths:
    """BowerBot's home folder and the config file inside it."""

    HOME = Path.home() / ".bowerbot"
    CONFIG_FILE = HOME / "config.json"
