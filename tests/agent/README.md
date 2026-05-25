# Agent integration tests

End-to-end scenarios that drive the live LLM against the real tool
surface, organised by how a user actually thinks (discovery, vague
intent, goal-oriented, iteration, conceptual, recovery, refusal,
tool coverage) rather than by tool family.

## Running

These tests cost real LLM API calls. They are excluded by default
from `pytest` runs via the `agent_integration` marker. The runner
reads your API key from `~/.bowerbot/config.json` (it skips the
suite cleanly if no key is present, so they will simply not run
without setup).

```
# Full suite (every scenario across every tier; ~$1.50-$2.50 with gpt-4.1)
pytest -m agent_integration tests/agent/

# One tier
pytest -m agent_integration tests/agent/ -k discovery
pytest -m agent_integration tests/agent/ -k physics_goals

# One scenario by name
pytest -m agent_integration tests/agent/ -k goal_pendulum_from_scratch

# With live stdout (useful for watching LLM responses scroll by)
pytest -m agent_integration tests/agent/ -s
```

`pytest` without the marker runs zero agent tests, so day-to-day
development is unaffected.

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
| `tool_coverage` | Catches tool categories not naturally hit by the other tiers | `validate_scene`, `save_snapshot`, collision groups, articulation root |

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

- A single-prompt scenario typically costs $0.03-$0.08 on `gpt-4.1`.
- A multi-prompt iteration scenario can run $0.15-$0.30.
- The full ~20-scenario suite runs about $1.50-$2.50 per pass.

Token usage per turn is recorded in the file log
(`~/.bowerbot/logs/bowerbot.log`) and in the artifact transcripts.
