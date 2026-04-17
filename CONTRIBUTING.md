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

Understanding where things live helps you contribute effectively. BowerBot is organized FastAPI-style, so adding a feature is almost always a three-file change (schema + service + tool):

- **`schemas/`**: pydantic models and enums, grouped by domain.
- **`services/`**: pure-function business logic. All `pxr` calls live here.
- **`tools/`**: LLM-facing tool definitions and thin handlers that call services.
- **`state.py`**: `SceneState` dataclass threaded through every tool handler.
- **`dispatcher.py`**: tool registry and router.
- **`skills/`**: extension skills (asset providers, integrations).
- **`prompts/`**: LLM instructions as `.md` files. Edit these to change agent behavior without touching Python.
- **`utils/`**: shared utilities (USD introspection, file operations, naming).

## Writing a Skill

The best way to contribute is writing a new **skill** for an asset provider you use: Sketchfab, PolyHaven, CGTrader, a company DAM, or any platform that serves 3D assets or textures.

Each skill is a folder in `src/bowerbot/skills/` with:

```
my_provider/
  __init__.py
  my_provider.py      # Implements the Skill interface
  SKILL.md            # Natural language instructions for the LLM
```

See `skills/sketchfab/` for a provider skill example and `skills/textures/` for a local search skill example.

### Key rules

- **Skills never touch USD**: all `pxr` calls live in `services/`
- **One SKILL.md per skill**: it's injected into the system prompt when active
- **Return ToolResult**: always return `ToolResult(success=True/False, ...)` from `execute()`
- **Use `self.assets_dir`**: all skills receive a centralized asset directory from the registry. Provider skills declare a `cache_subdir` for downloads (e.g., `cache/polyhaven`). Search skills scan the full tree.
- **No hardcoded paths**: paths come from the system, not from skill config

## Code Style

- Python 3.12+
- Type hints on all public methods
- No `.env` files; all config goes through `~/.bowerbot/config.json`
- Keep imports at the top of the file, not inside methods

## Running Tests

```bash
uv run pytest
```
