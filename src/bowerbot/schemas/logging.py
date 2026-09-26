# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Logging schemas — the logger tree and what logged payloads hide or shorten."""


class LoggingRules:
    """Fixed logging behavior; verbosity and rotation are settings instead."""

    # Root of BowerBot's logger tree: every module logs under it.
    LOGGER_ROOT = "bowerbot"
    # A key naming one of these words (split on _ - and camelCase, ignoring
    # case; "api key" counts as "apikey") has its value redacted in logs.
    SECRET_KEY_WORDS = frozenset({
        "apikey", "token", "password", "passwd", "secret", "auth", "authorization",
        "credential", "credentials",
    })
    # Splits a key into words: runs of lower case/digits, or capitals.
    KEY_WORD_PATTERN = r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])"
    # String values longer than this are truncated in logged payloads.
    MAX_STRING_LENGTH = 200
