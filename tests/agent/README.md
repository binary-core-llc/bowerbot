# Agent integration tests

End-to-end scenarios that drive the live LLM against the real tool
surface, organised by how a user actually thinks (discovery, vague
intent, goal-oriented, iteration, conceptual, recovery, refusal,
tool coverage, tool categories, exploratory) rather than by tool
family.

## Running

These tests cost real LLM API calls. `pyproject.toml` leaves them
out of default `pytest` runs (its `addopts` deselects the
`agent_integration` and `integration` markers; a `-m` on the command
line replaces that filter). The runner uses the model and API key in
`~/.bowerbot/config.json` (it skips the suite cleanly if no key is
present, so they will simply not run without setup).

```
# Full suite (all 33 scenarios; cost depends on the model in your config.json)
pytest -m agent_integration tests/agent/

# One tier (-k matches scenario names, which start with the tier's prefix:
# discovery_, vague_, goal_, iteration_, conceptual_, recovery_, refusal_,
# coverage_, category_, explore_)
pytest -m agent_integration tests/agent/ -k discovery
pytest -m agent_integration tests/agent/ -k recovery

# Smoke subset (12 highest-signal scenarios), or every scenario
pytest -m "agent_integration and agent_smoke" tests/agent/
pytest -m "agent_integration and agent_full" tests/agent/

# One scenario by name
pytest -m agent_integration tests/agent/ -k goal_pendulum_from_scratch

# With live stdout (useful for watching LLM responses scroll by)
pytest -m agent_integration tests/agent/ -s
```

`pytest` without `-m` runs zero agent tests (the `addopts` filter), so
day-to-day development is unaffected.

## What an artifact looks like

Every run dumps a folder under `tests/agent/artifacts/` (gitignored):

```
tests/agent/artifacts/<scenario_name>/<timestamp>/
  transcript.md     # human-readable: every prompt, every tool call, every response
  tool_calls.json   # structured: name, params, success/error, truncated data
  scene.usda        # final state of the scene file the agent built
```

The `transcript.md` is the most useful artifact for spotting UX
issues — the assertions only catch state, the transcript catches
*how* the agent got there (did it ask a clarifying question? did
it explain its choice? did it call introspection first?).

## What's tested where

| Tier | What it tests | Tool families covered |
|---|---|---|
| `discovery` | Inspection-only prompts; agent should not author | `list_scene`, `list_prim_attributes`, `list_prim_children`, `get_physics_summary`, library browsers |
| `vague_intent` | Underspecified asks; agent should inspect before authoring or ask | lighting, asset placement, physics setup |
| `physics_goals` | Goal-oriented physics prompts | `setup_physics_scene`, `apply_physics_api`, `create_joint` |
| `iteration` | Multi-turn refinement; agent must use prior context | mass updates, kinematic toggle, sibling generalisation |
| `conceptual` | Q&A; agent should explain, not author | none (refusal of authoring is the assertion) |
| `recovery` | Change of mind; agent must undo / change course | `remove_physics_api`, retargeting |
| `refusals` | Spec-invalid asks; tool layer should refuse and the agent should explain | physics prim-type guards, destructive operations |
| `tool_coverage` | Catches tool categories not naturally hit by the other tiers | `validate_scene`, `save_scene_snapshot`, collision groups, articulation root |
| `tool_categories` | One tool family end to end per scenario | snapshots (save, list, delete), `create_material` / `bind_material`, dimming and removing a light, a falling stack (rigid bodies + collision) |
| `exploratory` | Everyday conversational edits | xform ops (random tilt, scale up), deleting a collision-group member, UsdLux attributes, one change applied to many prims |

## Adding a scenario

1. Decide which tier fits. If none fits, propose a new tier
   here first.
2. Add to `tests/agent/scenarios/<tier>.py` an `AgentScenario`
   instance. Append it to that file's `ALL` list.
3. If your scenario needs a pre-populated scene, write a
   `setup_*` helper in `tests/agent/scenarios/_fixtures.py` and
   reference it as the scenario's `setup` callable.
4. Add assertions that check **final state** (composed stage)
   rather than the order of tool calls. The transcript artifact
   handles "did the agent ask the right question" qualitatively.

## Cost guidelines

- Cost depends on the model in your `config.json`. On `gpt-4.1`, a
  single-prompt scenario cost about $0.03-$0.08 and a multi-prompt
  iteration scenario $0.15-$0.30.
- The suite has 33 scenarios; the `agent_smoke` subset (12) is the
  cheap pre-PR run.

Token usage per turn is recorded in the file log
(`~/.bowerbot/logs/bowerbot.log`) and in the artifact transcripts.
