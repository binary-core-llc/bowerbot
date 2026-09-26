# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Logging schemas — the logger tree and what logged payloads hide or shorten."""


class LoggingRules:
    """Fixed logging behavior; verbosity and rotation are settings instead."""

    # Root of BowerBot's logger tree: every module logs under it.
    LOGGER_ROOT = "bowerbot"
    # Keys whose values are redacted from logged payloads (matched ignoring case).
    SECRET_KEY_PATTERN = r"(api[_-]?key|token|password|secret|auth(?:oriz)?)"
    # String values longer than this are truncated in logged payloads.
    MAX_STRING_LENGTH = 200
