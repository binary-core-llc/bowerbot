A BowerBot project is one folder holding one scene, its assets, and its
packaged output. Exactly one project is "focused" at a time; every
authoring tool (place_asset, create_light, apply_physics_api, ...)
operates on the focused project.

### Focusing a project

- `create_project(name)` — start a fresh project and focus it. Use when
  the user wants a new scene ("make me a coffee shop").
- `open_project(name)` — focus an existing project. Use to resume or
  switch ("keep working on my kitchen"). Call `list_projects` first if
  you are unsure of the exact name.
- Both calls rebind the focus: from that point on, all authoring lands
  in that project until you open another.

### Knowing where you are

- `list_projects` — show every project, with the focused one flagged.
- `get_current_project` — report the focused project, its path, and its
  object count. Returns "no project open" when nothing is focused.

### When nothing is focused

If the user asks to author something (place an asset, add a light) and
no project is open, the authoring tool will refuse with "No stage open"
or "No project open". Resolve it by calling `open_project` (to resume an
existing one) or `create_project` (to start fresh) FIRST, then retry the
authoring call. Ask the user which they want if it is ambiguous.
