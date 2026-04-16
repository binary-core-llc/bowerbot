# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot services — pure-function business logic.

Services are stateless modules. They take primitive types
(``Usd.Stage``, ``Path``, pydantic schemas) and return primitive
values. All ``pxr`` usage is contained within this package.

Tool handlers in ``bowerbot.tools`` pull state out of ``SceneState``
and thread it into service calls.
"""
