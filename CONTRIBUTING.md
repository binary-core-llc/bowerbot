# Contributing to BowerBot

Thanks for your interest in contributing to BowerBot!

## Getting Started

```bash
git clone https://github.com/binary-core-llc/bowerbot.git
cd bowerbot
uv sync
uv run pytest
```

## How to Submit Changes

### 1. Create a branch

Branch names must follow `type/short-description`. This is enforced by CI.

```
feat/polyhaven-skill
fix/bounding-box-scale
docs/update-readme
refactor/move-imports
test/token-manager
chore/ci-setup
```

### 2. Make your changes

Commit however you like on your branch; commit messages on feature branches don't matter. Only the PR title matters (see next step).

### 3. Open a PR

The **PR title** must use conventional format. This is what becomes the commit on `main` and what Release Please uses for versioning and changelogs.

**PR title format:** `type: short description`

**PR title examples:**

```
feat: add PolyHaven asset skill
fix: correct bounding box calculation for scaled references
docs: update configuration section in README
refactor: move lazy imports to top-level
```

### 4. Merge

All PRs are **squash merged**. The PR title becomes the single commit message on `main`. Release Please reads it and handles versioning automatically.

```
feat/my-feature → PR titled "feat: ..." → squash merge → main → Release Please
```

### PR checklist

- [ ] Branch name follows `type/description` convention
- [ ] PR title follows `type: description` format
- [ ] Tests pass (`uv run pytest`)
- [ ] One feature or fix per PR
- [ ] New functionality includes tests

## Conventional Commit Types

| Type | When to use | Version bump |
|------|-------------|--------------|
| `feat` | New feature or tool | Minor (1.0.0 → 1.1.0) |
| `fix` | Bug fix | Patch (1.0.0 → 1.0.1) |
| `docs` | Documentation only | None |
| `refactor` | Code change that doesn't add a feature or fix a bug | None |
| `test` | Adding or updating tests | None |
| `chore` | Build, CI, or tooling changes | None |

Add `!` after the type for breaking changes (e.g., `feat!: redesign skill interface`). This triggers a major bump (1.0.0 → 2.0.0).

## Project Structure

BowerBot is organized FastAPI-style. Adding a feature is a three-file change (schema, service, tool):

- **`schemas/`**: pydantic models and enums.
- **`utils/`**: pure-function primitives. The only place `pxr` is imported.
- **`services/`**: orchestrators with signature `(state, params)`. One per tool. Call utils and other services, mutate state, raise on errors.
- **`tools/`**: thin adapters. Guard preconditions, call ONE service, wrap in `ToolResult`.
- **`state.py`**: `SceneState`, threaded through every tool handler.
- **`dispatcher.py`**: tool registry and router.
- **`skills/`**: the skill SDK (the `Skill` contract and the `SkillRegistry`). Skills themselves ship as separate pip packages and are discovered at runtime via entry points; they do not live in this directory.
- **`prompts/`**: LLM instructions as `.md` files.

## Writing a Skill

The best way to contribute is writing a new **skill** for an asset provider, DCC, or simulation runtime: Sketchfab, PolyHaven, CGTrader, a company DAM, Isaac Sim, MuJoCo, anything that produces or consumes 3D content.

### Skill layout (required)

Every skill follows the same FastAPI shape as the core. Even small skills mirror this layout for consistency, predictability, and growth headroom.

```
my_provider/
  __init__.py        # Re-exports the Skill class
  skill.py           # Skill subclass. Tool registration + execute() dispatch only.
  SKILL.md           # Natural language instructions for the LLM
  schemas/           # Pydantic models / enums for this skill's data
  services/          # Orchestrators. One module per tool. Take params (and ctx).
  tools/             # Tool definitions list returned by get_tools()
  utils/             # Pure-function primitives the services compose
```

See `skills/sketchfab/` for a complete reference.

### The Skill contract

A skill subclasses `bowerbot.skills.Skill` and implements three methods:

- `get_tools() -> list[Tool]` — declares what the LLM sees.
- `execute(tool_name, params, ctx) -> ToolResult` — routes to a service.
- `validate_config() -> None` — verifies the skill is properly configured. Raises `SkillConfigError` with an actionable message when something is missing or invalid.

The `skill.py` file should be **a dispatcher**, not a place for logic. It maps a tool name to a service function and wraps the result. All real work lives in `services/` and `utils/`.

### Layering inside a skill

The same rules that govern the BowerBot core apply inside every skill:

- `schemas/` holds pydantic models and enums. Data only.
- `utils/` holds pure-function primitives. The only place `pxr` (or any heavy SDK) should be imported.
- `services/` holds orchestrators called from `Skill.execute()`. Take `(params, ctx)`, call utils, raise on errors.
- `tools/` holds the `Tool` definitions returned by `get_tools()`. Pure data, no logic.
- `skill.py` holds the `Skill` subclass. Tool registration plus `execute()` dispatch only.

### SkillContext

Every `execute()` call receives a `SkillContext`. This is the only way a skill sees outside state:

```python
@dataclass(frozen=True)
class SkillContext:
    library_dir: Path           # User's curated library
    cache_dir: Path | None      # This skill's download dir (library_dir / cache_subdir)
    project_dir: Path | None    # Currently open project root, or None
    scene_path: Path | None     # Currently open scene file, or None
```

Skills that need stage access call `Usd.Stage.Open(ctx.scene_path)` themselves. The context never exposes a live shared stage.

### Key rules

- **Skills are hyper-isolated**: a skill depends only on `bowerbot.skills` (the public contract), the standard library, and external packages it ships with. It does **not** import from `bowerbot.utils`, `bowerbot.services`, `bowerbot.state`, or any other core module. If a skill needs a primitive, it carries its own copy in its `utils/`.
- **Entry-point name must match `Skill.name`**: the registry compares them and skips with an error if they differ. Pick one identifier and use it both in `pyproject.toml` and on the class.
- **One SKILL.md per skill**: injected into the system prompt when the skill is active.
- **Return ToolResult**: always return `ToolResult(success=True/False, ...)` from `execute()`.
- **Raise `SkillConfigError`** from `validate_config()` when a required setting is missing or invalid. The registry logs the message and skips the skill so BowerBot keeps running. Do not return `True` / `False`; the contract is exception-based.
- **Use `ctx.cache_dir` for downloads**: declare `cache_subdir` on the class (e.g. `"cache/polyhaven"`); the registry creates the dir and exposes it via `ctx.cache_dir`.
- **Use `ctx.project_dir` and `ctx.scene_path` for scene-aware skills**: these are `None` when no project is open. Always handle that case.
- **No hardcoded paths**: every path comes through `SkillContext` or tool params.

### Public API and stability

Skill authors import from `bowerbot.skills`:

```python
from bowerbot.skills import (
    Skill,
    SkillCategory,
    SkillConfigError,
    SkillContext,
    Tool,
    ToolResult,
)
```

These six names are the public contract. They follow semver: breaking changes are reserved for major version bumps. External skill packages should pin a compatible bowerbot range in their own `pyproject.toml`:

```toml
dependencies = ["bowerbot>=1.5,<2"]
```

Anything under `bowerbot.skills.base` is an implementation detail. Import from `bowerbot.skills` instead.

### Distributing a skill as a separate package

Skills ship one of two ways:

1. **In-tree** (built-in): live under `src/bowerbot/skills/<name>/` and register via the main `pyproject.toml` entry points. Used for first-party skills like `sketchfab`.
2. **Separate pip package**: their own repo, their own `pyproject.toml`, distributed on PyPI. Used for community and third-party skills. Layout:

```
bowerbot-skill-polyhaven/
  pyproject.toml
  src/bowerbot_skill_polyhaven/
    __init__.py
    skill.py
    SKILL.md
    schemas/
    services/
    tools/
    utils/
  tests/
```

The package's `pyproject.toml` declares the entry point exactly like in-tree skills do:

```toml
[project]
name = "bowerbot-skill-polyhaven"
dependencies = ["bowerbot>=1.5,<2", "httpx"]

[project.entry-points."bowerbot.skills"]
polyhaven = "bowerbot_skill_polyhaven.skill:PolyhavenSkill"
```

After `pip install bowerbot-skill-polyhaven`, BowerBot's `SkillRegistry` discovers it automatically. No core code changes required.

## Code Style

- Python 3.12+
- Type hints on all public methods
- No `.env` files; all config goes through `~/.bowerbot/config.json`
- Keep imports at the top of the file, not inside methods

## Running Tests

```bash
uv run pytest
```
