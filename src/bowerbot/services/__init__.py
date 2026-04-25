# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot services — state-aware orchestrators.

Each service module mirrors a tools module 1:1. Every public function
takes ``(state: SceneState, params: dict)``, calls into ``utils/`` (and
other services) to do the work, mutates state when needed, and raises
on errors. Tools wrap them in ``ToolResult``; ``pxr`` lives in ``utils/``.
"""
