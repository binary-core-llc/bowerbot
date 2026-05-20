# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot — AI-powered 3D scene assembly using OpenUSD."""

import logging
from importlib.metadata import version

logging.getLogger("LiteLLM").setLevel(logging.ERROR)

__version__ = version("bowerbot")
