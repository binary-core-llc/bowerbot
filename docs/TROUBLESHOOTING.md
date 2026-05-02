# Troubleshooting

Common issues and how to resolve them.

## Working with BowerBot and a DCC at the same time

BowerBot detects when you save changes to `scene.usda` from any external USD-aware tool (Omniverse, usdview, Isaac Sim, your DCC of choice, etc.) and reloads its in-memory copy automatically before the next tool call. You can switch back and forth between BowerBot and your DCC without losing edits, as long as you save and finish in one tool before switching to the other.

### What works

- Edit in BowerBot, save (automatic), switch to your DCC, load `scene.usda`, edit, save, switch back to BowerBot, ask for another change. BowerBot detects the external edits and reloads before its next tool call.
- Both directions, repeated as often as you want.

### What does not work yet

- **Concurrent saves.** If BowerBot and your DCC save at the exact same moment, the last writer wins and the other edit is lost. Always save in one tool before switching to the other.
- **Edits to referenced layers.** BowerBot watches `scene.usda`, not the assets it references. If you edit `assets/table/mtl.usda` directly in your DCC and save, BowerBot may not detect the change until you also touch `scene.usda`. Full layer-graph watching is on the roadmap.
- **Network filesystem lag.** Some shared drives (NFS, SMB, cloud-sync folders) can serve stale file metadata for a few seconds. If you save in your DCC and BowerBot does not detect it, wait a moment and retry the BowerBot command.

### Best practice: clean handoffs

For mission-critical work, treat BowerBot and your DCC as serial editors:

1. Block out the scene in BowerBot.
2. Save and end the BowerBot session.
3. Open `scene.usda` in your DCC, refine.
4. Save in your DCC, close.
5. Re-open in BowerBot for additional changes.

This guarantees no race conditions. BowerBot's auto-reload makes the casual back-and-forth workflow safe for the vast majority of cases, but the clean-handoff pattern is bulletproof.

## CLI rendering issues

### "BowerBot info" or other commands crash with `UnicodeEncodeError`

Fixed in 1.5.2 (the CLI no longer emits non-ASCII characters). If you see this on an older version, upgrade:

```bash
uv tool install bowerbot --reinstall
# or
pip install --upgrade bowerbot
```

### Long paths render as `?` in `bowerbot list` on Windows

Cosmetic only. Rich renders truncated paths with a Unicode ellipsis that the default Windows console (cp1252) cannot render. The full path is intact in `project.json`. To see it without truncation, set `PYTHONIOENCODING=utf-8` before running:

```powershell
$env:PYTHONIOENCODING = "utf-8"
bowerbot list
```

## Skill installation

### "Skill 'X' is enabled in config but not installed"

The skill's config block exists in `~/.bowerbot/config.json` but the Python package is not in BowerBot's environment. Install it in the same environment as BowerBot:

```bash
# If you used 'uv tool install bowerbot':
uv tool install bowerbot --with bowerbot-skill-X --reinstall

# If you used 'pip install bowerbot':
pip install bowerbot-skill-X
```

### "bowerbot skills" does not show a skill that is pip-installed

Two common causes:

1. **Wrong environment.** The skill was installed in a different Python environment than BowerBot. Verify with `pip show bowerbot-skill-X`. If the location differs from BowerBot's environment, reinstall there.
2. **Entry point missing or broken.** The skill's `pyproject.toml` is missing `[project.entry-points."bowerbot.skills"]`. Check with:

   ```bash
   python -c "from importlib.metadata import entry_points; print('\n'.join(f'{ep.name} -> {ep.value}' for ep in entry_points(group='bowerbot.skills')))"
   ```

   If your skill is missing from the output despite being pip-installed, file an issue on the skill's repo.

### Sketchfab "401 Unauthorized" errors

Your Sketchfab API token is missing, expired, or invalid. Get a fresh one at https://sketchfab.com/settings/password and update the `token` field under `skills.sketchfab.config` in `~/.bowerbot/config.json`.

## LLM and tool-calling issues

### "Reached maximum tool-calling rounds"

The LLM exceeded the per-request tool-call budget. Increase `max_tool_rounds` in the `llm` section of `~/.bowerbot/config.json` (default is 25). For large material-binding workflows on dozens of mesh parts, 50 is reasonable.

### Models that do not work well

`gpt-4o` skips tool calls and ignores SKILL.md. Use `gpt-4.1` (default), `gpt-4.1-mini`, or `anthropic/claude-sonnet-4-6`. See the Tested Models table in [README.md](../README.md#tested-models).

## Where to get help

- GitHub Discussions: https://github.com/binary-core-llc/bowerbot/discussions
- File a bug: https://github.com/binary-core-llc/bowerbot/issues
- Tutorial videos: https://www.youtube.com/playlist?list=PLhNtBS4KXazZk_LSZfMHlzmNQPqHc4CMb
- Demo videos: https://www.youtube.com/playlist?list=PLhNtBS4KXaza-3Sn4ggJLH-6ujRZ3Iapd
