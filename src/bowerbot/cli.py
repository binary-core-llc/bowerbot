# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot CLI: natural language 3D scene assembly."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path

import click
import litellm
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.theme import Theme

from bowerbot import __version__, dispatcher, mcp_server
from bowerbot.agent import AgentRuntime
from bowerbot.config import (
    BOWERBOT_HOME,
    GLOBAL_CONFIG_PATH,
    LinearUnit,
    LLMSettings,
    McpSettings,
    Mode,
    Settings,
    Transport,
    UpAxis,
    ensure_home,
    load_settings,
    save_settings,
)
from bowerbot.logging_setup import configure_logging
from bowerbot.project import Project
from bowerbot.skills.registry import SkillRegistry
from bowerbot.state import SceneState
from bowerbot.utils import inspection_utils
from bowerbot.utils.naming_utils import safe_project_name

theme = Theme({
    "sf": "bold green",
    "user": "bold cyan",
    "info": "dim",
})
console = Console(theme=theme)


def _build_state(
    settings: Settings, project: Project | None = None,
) -> SceneState:
    """Build a SceneState, optionally focusing it on *project*."""
    state = SceneState.from_settings(settings)
    if project is not None:
        state.bind_project(project)
    return state


def _build_registry(settings: Settings) -> SkillRegistry:
    """Build a SkillRegistry with extension skills only."""
    registry = SkillRegistry()
    registry.load_from_settings(settings)
    return registry


def _choose[EnumT: StrEnum](
    prompt: str, options: dict[EnumT, str], default: EnumT,
) -> EnumT:
    """Prompt for one StrEnum value, listing a description per option."""
    enum_cls = type(default)
    console.print(f"\n[sf]{prompt}[/]")
    for value, description in options.items():
        console.print(f"  [sf]{value.value}[/]: {description}")
    chosen = Prompt.ask(
        "  Choose",
        choices=[value.value for value in options],
        default=default.value,
    )
    return enum_cls(chosen)


@click.group(invoke_without_command=True)
@click.version_option()
@click.pass_context
def main(ctx: click.Context) -> None:
    """BowerBot: AI-powered 3D scene assembly using OpenUSD."""
    settings = load_settings()
    configure_logging(settings)
    if ctx.invoked_subcommand is not None:
        return
    if settings.mode is Mode.MCP:
        mcp_server.serve(settings)
    else:
        click.echo(ctx.get_help())


@main.command()
@click.argument("name")
def new(name: str) -> None:
    """Create a new BowerBot project."""
    settings = load_settings()
    projects_dir = Path(settings.projects_dir)
    projects_dir.mkdir(parents=True, exist_ok=True)

    up_axis = _choose(
        "World up-axis for this scene?",
        {
            UpAxis.Y: "Y-up (most DCCs, Maya, web).",
            UpAxis.Z: "Z-up (Omniverse, Isaac Sim, CAD).",
        },
        UpAxis.Y,
    )
    unit = _choose(
        "Scene units?",
        {
            LinearUnit.METERS: "meters (metersPerUnit 1.0).",
            LinearUnit.CENTIMETERS: "centimeters (0.01).",
            LinearUnit.MILLIMETERS: "millimeters (0.001).",
        },
        LinearUnit.METERS,
    )

    try:
        project = Project.create(
            projects_dir, name,
            up_axis=up_axis, meters_per_unit=unit.meters_per_unit,
        )
        console.print(
            f"[sf]Created project:[/] {project.name} "
            f"({up_axis.value}-up, {unit.value})",
        )
        console.print(f"   Path: {project.path}")
        console.print("\n[info]Start working:[/]")
        console.print(f"   cd {project.path}")
        console.print("   bowerbot chat")
    except FileExistsError:
        console.print(f"[red]Project already exists:[/] {name}")


@main.command(name="list")
def list_projects() -> None:
    """List all BowerBot projects."""
    settings = load_settings()
    projects = Project.list_projects(Path(settings.projects_dir))

    if not projects:
        console.print("[info]No projects yet. Create one with:[/]")
        console.print("  bowerbot new my_project")
        return

    table = Table(title="BowerBot Projects")
    table.add_column("Name", style="bold green")
    table.add_column("Updated", style="dim")
    table.add_column("Path", style="dim")

    for p in projects:
        table.add_row(p.name, p.meta.updated_at[:10], str(p.path))

    console.print(table)


@main.command()
@click.argument("name")
def open(name: str) -> None:
    """Open a project and start an interactive session."""
    settings = load_settings()
    projects_dir = Path(settings.projects_dir)

    project_path = projects_dir / name.lower().replace(" ", "_")
    if not project_path.exists():
        console.print(f"[red]Project not found:[/] {name}")
        console.print("[info]Available projects:[/]")
        for p in Project.list_projects(projects_dir):
            console.print(f"  - {p.meta.name} ({p.path.name})")
        return

    project = Project.load(project_path)
    _start_chat(settings, project)


@main.command()
def chat() -> None:
    """Interactive scene building session.

    If run inside a project directory, auto-loads that project.
    Otherwise starts without a project (use 'new' to create one).
    """
    settings = load_settings()
    project = Project.detect(Path.cwd())
    if project:
        console.print(f"[sf]Detected project:[/] {project.name}")
    _start_chat(settings, project)


def _format_object_summary(obj: dict) -> str:
    """Format a scene object for the resume context message."""
    path = obj["prim_path"]
    pos = obj.get("position")
    label = obj.get("asset") or obj.get("light_type") or obj.get("type", "unknown")
    return f"  - {path} ({label}, position: {pos})"


def _start_chat(settings: Settings, project: Project | None = None) -> None:
    """Start an interactive chat session, optionally inside a project."""
    state = _build_state(settings, project=project)
    registry = _build_registry(settings)

    status = f"[sf]BowerBot[/] v{__version__}: Interactive Scene Builder\n"
    status += f"[info]Model:[/]  {settings.llm.model}\n"
    status += f"[info]Skills:[/] {', '.join(registry.enabled_skills)}\n"

    if project:
        status += f"[info]Project:[/] {project.name}\n"
        status += f"[info]Path:[/]    {project.path}\n"
        if project.scene_path.exists():
            status += (
                f"[info]Scene:[/]   {project.meta.scene_file} "
                f"({state.object_count} object(s))\n"
            )
    else:
        status += "[info]Project:[/] none (use 'bowerbot new' to create one)\n"

    status += "\n[info]Commands: 'quit' to exit, 'reset' to start a new session[/]"
    console.print(Panel(status, title="[sf]BowerBot[/]", border_style="green"))

    agent = AgentRuntime(
        settings=settings, state=state, skill_registry=registry,
    )

    if project and project.scene_path.exists() and state.object_count > 0:
        objects = inspection_utils.list_prims(state.stage)
        object_summary = "\n".join(
            _format_object_summary(o) for o in objects
        )
        context = (
            f"You are resuming project '{project.name}'. The scene is "
            f"already open at {project.scene_path} with "
            f"{len(objects)} object(s):\n{object_summary}\n"
            f"The stage is loaded and ready, you do NOT need to call "
            f"create_stage."
        )
        agent.conversation_history.append(
            {"role": "system", "content": context},
        )

    asyncio.run(_chat_loop(agent, console))


def _focused_project_name(agent: AgentRuntime) -> str | None:
    """Name of the project the agent's state is currently focused on."""
    return agent.state.project.name if agent.state.project else None


async def _chat_loop(agent: AgentRuntime, console: Console) -> None:
    """Run the interactive chat loop."""
    focused = _focused_project_name(agent)
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
            console.print("[info]Session reset, starting fresh.[/]")
            continue

        try:
            with console.status("[sf]BowerBot is thinking...[/]", spinner="dots"):
                response = await agent.process(user_input)
            console.print(f"\n[sf]BowerBot:[/] {response}")
            now_focused = _focused_project_name(agent)
            if now_focused != focused:
                focused = now_focused
                if now_focused is not None:
                    console.print(
                        f"\n[info]→ Now working on: {now_focused}  "
                        f"({agent.state.object_count} object(s))[/]",
                    )
        except KeyboardInterrupt:
            console.print("\n[info]Interrupted. Type 'quit' to exit.[/]")
        except litellm.AuthenticationError:
            console.print(
                "\n[red]Authentication failed.[/] "
                "Check your API key with 'bowerbot info'.",
            )
        except litellm.RateLimitError:
            console.print(
                "\n[yellow]Rate limited.[/] "
                "Retries exhausted. Wait a moment and try again.",
            )
        except litellm.APIConnectionError:
            console.print(
                "\n[red]Cannot reach API.[/] Check your network connection.",
            )
        except litellm.Timeout:
            console.print(
                "\n[yellow]Request timed out.[/] "
                "Try again or increase request_timeout in config.",
            )
        except Exception as e:
            console.print(f"\n[red]Error:[/] {e}")
            console.print(
                "[info]You can keep going or type 'reset' to start over.[/]",
            )


@main.command()
@click.argument("prompt")
def build(prompt: str) -> None:
    """Build a USD scene from a single prompt (auto-creates a project)."""
    settings = load_settings()

    words = prompt.split()[:4]
    project_name = " ".join(words)
    projects_dir = Path(settings.projects_dir)
    projects_dir.mkdir(parents=True, exist_ok=True)

    try:
        project = Project.create(projects_dir, project_name)
    except FileExistsError:
        safe_name = safe_project_name(project_name)
        project = Project.load(projects_dir / safe_name)

    console.print("[sf]BowerBot[/] Building scene...")
    console.print(f"  Prompt:   {prompt}")
    console.print(f"  Model:    {settings.llm.model}")
    console.print(f"  Project:  {project.name}")
    console.print(f"  Path:     {project.path}")

    state = _build_state(settings, project=project)
    registry = _build_registry(settings)
    console.print(f"  Skills:   {registry.enabled_skills}")

    agent = AgentRuntime(
        settings=settings, state=state, skill_registry=registry,
    )

    try:
        response = asyncio.run(agent.process(prompt))
        console.print(f"\n{response}")
    except litellm.AuthenticationError:
        console.print(
            "\n[red]Authentication failed.[/] "
            "Check your API key with 'bowerbot info'.",
        )
    except litellm.RateLimitError:
        console.print(
            "\n[yellow]Rate limited.[/] "
            "Retries exhausted. Wait a moment and try again.",
        )
    except litellm.APIConnectionError:
        console.print(
            "\n[red]Cannot reach API.[/] Check your network connection.",
        )
    except litellm.Timeout:
        console.print(
            "\n[yellow]Request timed out.[/] "
            "Try again or increase request_timeout in config.",
        )
    except Exception as e:
        console.print(f"\n[red]Error:[/] {e}")


@main.command()
def skills() -> None:
    """List available and enabled skills."""
    settings = load_settings()

    scene_tools = dispatcher.get_tool_names()
    console.print(f"[sf]Scene builder:[/] {len(scene_tools)} tools")
    for name in sorted(scene_tools):
        console.print(f"    - {name}")

    registry = _build_registry(settings)

    if registry.skill_count == 0:
        console.print("\n[info]No extension skills enabled.[/]")
        return

    console.print("\n[sf]Extension skills:[/]")
    for name in registry.enabled_skills:
        tools = [
            t["function"]["name"]
            for t in registry.get_all_tools()
            if t["function"]["name"].startswith(name)
        ]
        console.print(f"  - {name} ({len(tools)} tools)")
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
    console.print(
        f"  API key:         "
        f"{'[green]set[/]' if settings.get_api_key() else '[red]missing[/]'}",
    )
    console.print(f"  Projects dir:    {settings.projects_dir}")

    skills_enabled = [k for k, v in settings.skills.items() if v.enabled]
    console.print(f"  Skills enabled:  {skills_enabled or 'none'}")


@main.command()
def onboard() -> None:
    """Set up BowerBot for first use."""
    console.print(Panel(
        "[sf]BowerBot[/]: First Time Setup\n\n"
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

    mode = _choose(
        "How will you run BowerBot?",
        {
            Mode.AGENT: "BowerBot uses its own AI. Needs an LLM API key.",
            Mode.MCP: "an MCP client (Claude Desktop, etc.) drives BowerBot. "
            "No API key.",
        },
        Mode.AGENT,
    )

    llm = LLMSettings()
    mcp = McpSettings()
    if mode is Mode.AGENT:
        console.print("\n[sf]LLM Configuration[/]")
        model = console.input("  Model [gpt-4.1]: ").strip() or "gpt-4.1"
        api_key = console.input("  API key: ").strip()
        if not api_key:
            console.print(
                "[yellow]Warning:[/] No API key provided. Agent mode won't "
                "work without one. Add it later in ~/.bowerbot/config.json",
            )
        llm = LLMSettings(model=model, api_key=api_key)
    else:
        console.print(
            "\n[info]MCP mode selected. No API key needed; "
            "the connecting MCP client provides the AI.[/]",
        )
        transport = _choose(
            "How will your MCP client connect?",
            {
                Transport.STDIO: "the client launches BowerBot itself "
                "(e.g. Claude Desktop).",
                Transport.HTTP: "BowerBot runs as a local server the client "
                "connects to by URL (e.g. Cursor, VS Code, Claude Code).",
            },
            Transport.STDIO,
        )
        mcp = McpSettings(transport=transport)

    console.print("\n[sf]Directories[/]")
    assets_dir = (
        console.input("  Asset directory [./assets]: ").strip() or "./assets"
    )
    projects_dir = (
        console.input("  Projects directory [./scenes]: ").strip() or "./scenes"
    )

    settings = Settings(
        mode=mode,
        llm=llm,
        mcp=mcp,
        skills={},
        assets_dir=assets_dir,
        projects_dir=projects_dir,
    )

    save_settings(settings)

    console.print(f"\n[sf]Config saved to {GLOBAL_CONFIG_PATH}[/]")
    console.print(
        "\n[info]Skills are extension packages you install separately. "
        "After installing one (e.g. [sf]pip install bowerbot-skill-sketchfab[/]), "
        "add its config to your config.json under the [sf]skills[/] block.[/]",
    )
    if mode is Mode.AGENT:
        console.print("\n[info]You're ready to go! Try:[/]")
        console.print("  [sf]bowerbot new my_first_scene[/]")
        console.print("  [sf]bowerbot chat[/]")
    elif mcp.transport is Transport.STDIO:
        console.print(
            "\n[info]MCP mode ready. Point your MCP client at the "
            "[sf]bowerbot[/] command; it launches the server for you "
            "(see 'MCP mode' in the README).[/]",
        )
    else:
        console.print("\n[info]MCP mode ready. Start the server with:[/]")
        console.print("  [sf]bowerbot[/]")
        console.print(
            f"[info]then connect your MCP client to "
            f"[sf]http://{mcp.host}:{mcp.port}{mcp.path}[/] "
            f"(see 'MCP mode' in the README).[/]",
        )


if __name__ == "__main__":
    main()
