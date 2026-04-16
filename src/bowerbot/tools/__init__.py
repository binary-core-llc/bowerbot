# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot tool layer — tool definitions and thin handler wrappers.

Each domain module declares:

* A list of :class:`~bowerbot.skills.base.Tool` definitions (the LLM
  function schemas).
* One handler per tool. Handlers take ``(state, params)``, orchestrate
  service calls, and return a :class:`~bowerbot.skills.base.ToolResult`.

The dispatcher (``bowerbot.dispatcher``) stitches every module's tools
into one registry for the agent.
"""
