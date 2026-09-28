# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Golden-output tests: every tool, step by step, recorded against a known-good baseline.

Each scenario runs tool calls through the dispatcher, as the MCP server and
the agent do. After every step the recorder writes a readable snapshot: the
call and its answer, the project's file tree, what changed in each file,
what the composed scene changed, the world placement of every prim, and the
validator's findings. ``tests/test_golden_output.py`` replays every scenario
and compares each step with the recorded file under ``tests/golden/expected``.

Re-record on purpose, after reviewing a change, with
``BOWERBOT_UPDATE_GOLDEN=1 pytest tests/test_golden_output.py``.
"""
