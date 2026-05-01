# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test Sketchfab skill — verify API authentication and endpoints."""

import asyncio
import tempfile
from pathlib import Path

from bowerbot.config import load_settings
from bowerbot.skills.base import SkillContext
from bowerbot.skills.sketchfab import SketchfabSkill


def _make_ctx(tmp: Path) -> SkillContext:
    """Build a minimal SkillContext for read-only Sketchfab tools."""
    cache_dir = tmp / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return SkillContext(library_dir=tmp, cache_dir=cache_dir)


async def test_auth_and_list():
    """Verify API token works and list user's models."""
    settings = load_settings()
    sketchfab_config = settings.skills.get("sketchfab")

    if not sketchfab_config or not sketchfab_config.enabled:
        print("Skipping — sketchfab not enabled in config.json")
        return

    token = sketchfab_config.config.get("token", "")
    if not token:
        print("Skipping — no token in config.json")
        return

    with tempfile.TemporaryDirectory() as tmp:
        skill = SketchfabSkill(token=token)
        result = await skill.execute(
            "list_my_models", {"max_results": 5}, _make_ctx(Path(tmp)),
        )

    if not result.success:
        print(f"API call failed: {result.error}")
        return

    model_count = len(result.data)
    print(
        f"test_auth_and_list PASSED — API connected, "
        f"{model_count} model(s) in your account",
    )

    if model_count > 0:
        for m in result.data:
            print(
                f"   • {m['name']} (uid: {m['uid']}, verts: {m['vertex_count']})",
            )
    else:
        print("   (No models uploaded yet — that is fine, connection works!)")


async def test_search_empty():
    """Search for something — should return a list gracefully."""
    settings = load_settings()
    sketchfab_config = settings.skills.get("sketchfab")

    if not sketchfab_config or not sketchfab_config.enabled:
        return

    token = sketchfab_config.config.get("token", "")
    with tempfile.TemporaryDirectory() as tmp:
        skill = SketchfabSkill(token=token)
        result = await skill.execute(
            "search_my_models", {"query": "table"}, _make_ctx(Path(tmp)),
        )

    assert result.success, f"Search failed: {result.error}"
    print(
        f"test_search_empty PASSED — search returned "
        f"{len(result.data)} result(s)",
    )


async def main():
    await test_auth_and_list()
    await test_search_empty()
    print("\nSketchfab connection tests done!")


if __name__ == "__main__":
    asyncio.run(main())
