# Contributing to BowerBot

Thanks for your interest in contributing to BowerBot!

## Getting Started

```bash
git clone https://github.com/binary-core-llc/bowerbot.git
cd bowerbot
uv sync
```

## Commit Convention

This project uses [Conventional Commits](https://www.conventionalcommits.org/) and [Release Please](https://github.com/googleapis/release-please) for automated versioning and changelogs.

**Format:** `type: short description`

| Type | When to use |
|------|-------------|
| `feat` | New feature or tool |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that doesn't add a feature or fix a bug |
| `test` | Adding or updating tests |
| `chore` | Build, CI, or tooling changes |

**Examples:**

```
feat: add PolyHaven asset skill
fix: correct bounding box calculation for scaled references
docs: update configuration section in README
refactor: move lazy imports to top-level
```

A `feat` commit creates a minor version bump. A `fix` creates a patch bump. Add `!` after the type for breaking changes (e.g., `feat!: redesign skill interface`).

## Writing a Skill

The best way to contribute is writing a new **skill** for an asset provider. Each skill is a folder in `src/bowerbot/skills/` with:

```
my_provider/
  __init__.py
  my_provider.py      # Implements the Skill interface
  SKILL.md            # Natural language instructions for the LLM
```

See `skills/sketchfab/` for a complete example.

### Key rules

- **Skills never touch USD** — all `pxr` calls live in `engine/`
- **One SKILL.md per skill** — it's injected into the system prompt when active
- **Return ToolResult** — always return `ToolResult(success=True/False, ...)` from `execute()`

## Code Style

- Python 3.12+
- Type hints on all public methods
- No `.env` files — all config goes through `~/.bowerbot/config.json`
- Keep imports at the top of the file, not inside methods

## Running Tests

```bash
uv run pytest
```

## Branch Naming

Branch names must follow the pattern `type/short-description`:

```
feat/polyhaven-skill
fix/bounding-box-scale
docs/update-readme
refactor/move-imports
test/token-manager
chore/ci-setup
```

The type prefix must match one of the conventional commit types (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`). This is enforced by CI.

## Pull Request Workflow

1. Create a branch from `main` using the naming convention above
2. Make your changes — commit however you like on your branch
3. Open a PR to `main` — **the PR title must use conventional format** (e.g., `feat: add PolyHaven skill`)
4. All PRs are squash merged. The PR title becomes the commit message on `main`
5. Release Please reads that commit and handles versioning automatically

```
feat/my-feature → PR titled "feat: ..." → squash merge → main → Release Please
```

### PR checklist

- [ ] Branch name follows `type/description` convention
- [ ] Tests pass (`uv run pytest`)
- [ ] One feature or fix per PR
- [ ] New functionality includes tests
