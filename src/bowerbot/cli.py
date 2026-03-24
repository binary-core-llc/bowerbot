# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot CLI — natural language 3D scene assembly."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import click
import litellm
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

from bowerbot import __version__
from bowerbot.config import load_settings

if TYPE_CHECKING:
    from bowerbot.config import Settings
    from bowerbot.project import Project
    from bowerbot.skills.registry import SkillRegistry

theme = Theme({
    "sf": "bold green",
    "user": "bold cyan",
    "info": "dim",
})
console = Console(theme=theme)


def _build_registry(settings: Settings, project: Project | None = None) -> SkillRegistry:
    """Build a SkillRegistry and optionally bind it to a project."""
    from bowerbot.skills.registry import SkillRegistry

    registry = SkillRegistry()
    registry.load_from_settings(settings)

    if project:
        # Find the assembly skill and bind it to the project
        assembly = registry._skills.get("assembly")
        if assembly:
            assembly.set_project(project)

    return registry


@click.group()
@click.version_option()
def main() -> None:
    """BowerBot — AI-powered 3D scene assembly using OpenUSD."""


# ── Project commands ──────────────────────────────────────────


@main.command()
@click.argument("name")
def new(name: str) -> None:
    """Create a new BowerBot project."""
    from bowerbot.project import Project

    settings = load_settings()
    projects_dir = Path(settings.projects_dir)
    projects_dir.mkdir(parents=True, exist_ok=True)

    try:
        project = Project.create(projects_dir, name)
        console.print(f"[sf]✅ Created project:[/] {project.name}")
        console.print(f"   Path: {project.path}")
        console.print(f"\n[info]Start working:[/]")
        console.print(f"   cd {project.path}")
        console.print(f"   bowerbot chat")
    except FileExistsError:
        console.print(f"[red]Project already exists:[/] {name}")


@main.command(name="list")
def list_projects() -> None:
    """List all BowerBot projects."""
    from bowerbot.project import Project

    settings = load_settings()
    projects = Project.list_projects(Path(settings.projects_dir))

    if not projects:
        console.print("[info]No projects yet. Create one with:[/]")
        console.print("  bowerbot new my_project")
        return

    table = Table(title="BowerBot Projects")
    table.add_column("Name", style="bold green")
    table.add_column("Objects", justify="right")
    table.add_column("Updated", style="dim")
    table.add_column("Path", style="dim")

    for p in projects:
        table.add_row(
            p.name,
            str(p.meta.object_count),
            p.meta.updated_at[:10],
            str(p.path),
        )

    console.print(table)


@main.command()
@click.argument("name")
def open(name: str) -> None:
    """Open a project and start an interactive session."""
    from bowerbot.project import Project

    settings = load_settings()
    projects_dir = Path(settings.projects_dir)

    # Find project by name
    project_path = projects_dir / name.lower().replace(" ", "_")
    if not project_path.exists():
        console.print(f"[red]Project not found:[/] {name}")
        console.print("[info]Available projects:[/]")
        for p in Project.list_projects(projects_dir):
            console.print(f"  • {p.meta.name} ({p.path.name})")
        return

    project = Project.load(project_path)
    _start_chat(settings, project)


# ── Chat command ──────────────────────────────────────────────


@main.command()
def chat() -> None:
    """Interactive scene building session.

    If run inside a project directory, auto-loads that project.
    Otherwise starts without a project (use 'new' to create one).
    """
    from bowerbot.project import Project

    settings = load_settings()

    # Try to detect a project in the current directory
    project = Project.detect(Path.cwd())

    if project:
        console.print(f"[sf]Detected project:[/] {project.name}")

    _start_chat(settings, project)


def _start_chat(settings: Settings, project: Project | None = None) -> None:
    """Start an interactive chat session, optionally inside a project."""
    registry = _build_registry(settings, project=project)

    # Build status lines
    status = f"[sf]BowerBot[/] v{__version__} — Interactive Scene Builder\n"
    status += f"[info]Model:[/]  {settings.llm.model}\n"
    status += f"[info]Skills:[/] {', '.join(registry.enabled_skills)}\n"

    if project:
        status += f"[info]Project:[/] {project.name}\n"
        status += f"[info]Path:[/]    {project.path}\n"
        if project.scene_path.exists():
            assembly = registry._skills.get("assembly")
            count = assembly._object_count if assembly else 0
            status += f"[info]Scene:[/]   {project.meta.scene_file} ({count} object(s))\n"
    else:
        status += f"[info]Project:[/] none (use 'bowerbot new' to create one)\n"

    status += f"\n[info]Commands: 'quit' to exit, 'reset' to start a new session[/]"

    console.print(Panel(status, title="[sf]BowerBot[/]", border_style="green"))

    from bowerbot.agent import AgentRuntime

    agent = AgentRuntime(settings=settings, skill_registry=registry)

    # If resuming a project with an existing scene, tell the agent
    if project and project.scene_path.exists():
        assembly = registry._skills.get("assembly")
        if assembly and assembly._object_count > 0:
            objects = assembly.writer.list_prims()
            object_summary = "\n".join(
                f"  - {o['prim_path']} (asset: {o['asset']}, position: {o['position']})"
                for o in objects
            )
            context = (
                f"You are resuming project '{project.name}'. "
                f"The scene is already open at {project.scene_path} with "
                f"{len(objects)} object(s):\n{object_summary}\n"
                f"The stage is loaded and ready — you do NOT need to call create_stage."
            )
            agent.conversation_history.append({"role": "system", "content": context})

    asyncio.run(_chat_loop(agent, console))


async def _chat_loop(agent, console: Console) -> None:
    """Run the interactive chat loop."""
    while True:
        console.print()
        try:
            user_input = console.input("[user]You:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[info]Goodbye![/]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[info]Goodbye![/]")
            break

        if user_input.lower() == "reset":
            agent.reset()
            console.print("[info]Session reset — starting fresh.[/]")
            continue

        try:
            with console.status("[sf]BowerBot is thinking...[/]", spinner="dots"):
                response = await agent.process(user_input)
            console.print(f"\n[sf]BowerBot:[/] {response}")
        except KeyboardInterrupt:
            console.print("\n[info]Interrupted. Type 'quit' to exit.[/]")
        except litellm.AuthenticationError:
            console.print(
                "\n[red]Authentication failed.[/] "
                "Check your API key with 'bowerbot info'."
            )
        except litellm.RateLimitError:
            console.print(
                "\n[yellow]Rate limited.[/] "
                "Retries exhausted — wait a moment and try again."
            )
        except litellm.APIConnectionError:
            console.print(
                "\n[red]Cannot reach API.[/] "
                "Check your network connection."
            )
        except litellm.Timeout:
            console.print(
                "\n[yellow]Request timed out.[/] "
                "Try again or increase request_timeout in config."
            )
        except Exception as e:
            console.print(f"\n[red]Error:[/] {e}")
            console.print("[info]You can keep going or type 'reset' to start over.[/]")


# ── Utility commands ──────────────────────────────────────────


@main.command()
@click.argument("prompt")
def build(prompt: str) -> None:
    """Build a USD scene from a single prompt (auto-creates a project)."""
    from bowerbot.project import Project

    settings = load_settings()

    # Auto-create a project from the prompt
    # Take first few words as project name
    words = prompt.split()[:4]
    project_name = " ".join(words)

    projects_dir = Path(settings.projects_dir)
    projects_dir.mkdir(parents=True, exist_ok=True)

    try:
        project = Project.create(projects_dir, project_name)
    except FileExistsError:
        # Load existing project
        safe_name = project_name.lower().replace(" ", "_")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c in "_-")
        project = Project.load(projects_dir / safe_name)

    console.print(f"[sf]BowerBot[/] Building scene...")
    console.print(f"  Prompt:   {prompt}")
    console.print(f"  Model:    {settings.llm.model}")
    console.print(f"  Project:  {project.name}")
    console.print(f"  Path:     {project.path}")

    registry = _build_registry(settings, project=project)
    console.print(f"  Skills:   {registry.enabled_skills}")

    from bowerbot.agent import AgentRuntime

    agent = AgentRuntime(settings=settings, skill_registry=registry)

    try:
        response = asyncio.run(agent.process(prompt))
        console.print(f"\n{response}")
    except litellm.AuthenticationError:
        console.print(
            "\n[red]Authentication failed.[/] "
            "Check your API key with 'bowerbot info'."
        )
    except litellm.RateLimitError:
        console.print(
            "\n[yellow]Rate limited.[/] "
            "Retries exhausted — wait a moment and try again."
        )
    except litellm.APIConnectionError:
        console.print(
            "\n[red]Cannot reach API.[/] "
            "Check your network connection."
        )
    except litellm.Timeout:
        console.print(
            "\n[yellow]Request timed out.[/] "
            "Try again or increase request_timeout in config."
        )
    except Exception as e:
        console.print(f"\n[red]Error:[/] {e}")


@main.command()
def skills() -> None:
    """List available and enabled skills."""
    settings = load_settings()

    registry = _build_registry(settings)

    if registry.skill_count == 0:
        console.print("[yellow]No skills enabled. Check config.json[/]")
        return

    console.print("[sf]Enabled skills:[/]")
    for name in registry.enabled_skills:
        tools = [
            t["function"]["name"]
            for t in registry.get_all_tools()
            if t["function"]["name"].startswith(name)
        ]
        console.print(f"  • {name} ({len(tools)} tools)")
        for tool_name in tools:
            console.print(f"      - {tool_name}")


@main.command()
def info() -> None:
    """Show current configuration."""
    settings = load_settings()

    console.print("[sf]BowerBot Configuration[/]")
    console.print(f"  Model:           {settings.llm.model}")
    console.print(f"  Temperature:     {settings.llm.temperature}")
    console.print(f"  Max tokens:      {settings.llm.max_tokens}")
    console.print(f"  API key:         {'✅ set' if settings.get_api_key() else '❌ missing'}")
    console.print(f"  Projects dir:    {settings.projects_dir}")
    console.print(f"  Meters per unit: {settings.scene_defaults.meters_per_unit}")
    console.print(f"  Up axis:         {settings.scene_defaults.up_axis}")
    console.print(f"  Room bounds:     {settings.scene_defaults.default_room_bounds}")

    skills_enabled = [k for k, v in settings.skills.items() if v.enabled]
    console.print(f"  Skills enabled:  {skills_enabled or 'none'}")


@main.command()
def onboard() -> None:
    """Set up BowerBot for first use."""
    from bowerbot.config import GLOBAL_CONFIG_PATH, BOWERBOT_HOME, ensure_home, save_settings

    console.print(Panel(
        "[sf]BowerBot[/] — First Time Setup\n\n"
        "This will create your global configuration at:\n"
        f"  [info]{BOWERBOT_HOME}[/]",
        title="[sf]Setup[/]",
        border_style="green",
    ))

    if GLOBAL_CONFIG_PATH.exists():
        console.print(f"\n[info]Config already exists at {GLOBAL_CONFIG_PATH}[/]")
        overwrite = console.input("Overwrite? (y/N): ").strip().lower()
        if overwrite != "y":
            console.print("[info]Keeping existing config.[/]")
            return

    ensure_home()

    console.print("\n[sf]LLM Configuration[/]")
    model = console.input("  Model [gpt-4o]: ").strip() or "gpt-4o"
    api_key = console.input("  API key: ").strip()

    if not api_key:
        console.print(
            "[yellow]Warning:[/] No API key provided. "
            "BowerBot won't work without one.\n"
            "You can add it later in "
            "~/.bowerbot/config.json"
        )

    console.print("\n[sf]Sketchfab Integration[/]")
    sketchfab_token = console.input(
        "  Sketchfab API token (optional): ",
    ).strip()

    console.print("\n[sf]Asset Directory[/]")
    assets_dir = (
        console.input("  Asset directory [./assets]: ").strip()
        or "./assets"
    )

    from bowerbot.config import (
        LLMSettings, SceneDefaults, Settings, SkillConfig,
    )

    settings = Settings(
        llm=LLMSettings(
            model=model,
            api_key=api_key,
            temperature=0.1,
            max_tokens=4096,
        ),
        scene_defaults=SceneDefaults(),
        skills={
            "local": SkillConfig(enabled=True),
            "textures": SkillConfig(enabled=True),
            "sketchfab": SkillConfig(
                enabled=bool(sketchfab_token),
                config={"token": sketchfab_token} if sketchfab_token else {},
            ),
        },
        assets_dir=assets_dir,
    )

    save_settings(settings)

    console.print(f"\n[sf]✅ Config saved to {GLOBAL_CONFIG_PATH}[/]")
    console.print("\n[info]You're ready to go! Try:[/]")
    console.print("  [sf]bowerbot new my_first_scene[/]")
    console.print("  [sf]bowerbot chat[/]")


if __name__ == "__main__":
    main()
