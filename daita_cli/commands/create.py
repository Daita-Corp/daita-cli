"""
daita create agent|workflow <name> — add a component to the current project.
No daita-agents dependency required.
"""

import sys
from datetime import datetime
from pathlib import Path

import click
import yaml

from daita_cli.output import OutputFormatter
from daita_cli.project_utils import ensure_project_root


@click.group("create")
def create_group():
    """Create agents, workflows, and other components."""
    pass


@create_group.command("agent")
@click.argument("name")
@click.pass_context
def create_agent(ctx, name):
    """Create a new agent."""
    obj = ctx.obj or {}
    formatter = obj.get("formatter", OutputFormatter())
    try:
        _create_component("agent", name, formatter)
    except click.ClickException:
        raise
    except Exception as e:
        formatter.error("ERROR", str(e))
        sys.exit(1)


@create_group.command("workflow")
@click.argument("name")
@click.pass_context
def create_workflow(ctx, name):
    """Create a new workflow."""
    obj = ctx.obj or {}
    formatter = obj.get("formatter", OutputFormatter())
    try:
        _create_component("workflow", name, formatter)
    except click.ClickException:
        raise
    except Exception as e:
        formatter.error("ERROR", str(e))
        sys.exit(1)


@create_group.command("skill")
@click.argument("name")
@click.pass_context
def create_skill(ctx, name):
    """Create a new skill."""
    obj = ctx.obj or {}
    formatter = obj.get("formatter", OutputFormatter())
    try:
        _create_component("skill", name, formatter)
    except click.ClickException:
        raise
    except Exception as e:
        formatter.error("ERROR", str(e))
        sys.exit(1)


def _to_class_name(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_") if w)


def _clean_name(name: str) -> str:
    return name.replace("-", "_").lower()


_TEMPLATE_CONFIG = {
    "agent": {"dir": "agents", "builder": "_agent_template"},
    "workflow": {"dir": "workflows", "builder": "_workflow_template"},
    "skill": {"dir": "skills", "builder": "_skill_template"},
}


def _create_component(template: str, name: str, formatter: OutputFormatter):
    project_root = ensure_project_root()
    clean_name = _clean_name(name)
    class_name = _to_class_name(clean_name)

    cfg = _TEMPLATE_CONFIG.get(template)
    if cfg is None:
        raise click.ClickException(f"Unknown template: {template}")

    dest_dir = project_root / cfg["dir"]
    dest_file = dest_dir / f"{clean_name}.py"
    if dest_file.exists():
        raise click.ClickException(
            f"{template.capitalize()} '{clean_name}' already exists."
        )
    dest_dir.mkdir(exist_ok=True)
    builder = globals()[cfg["builder"]]
    dest_file.write_text(builder(clean_name, class_name))

    # Prompt for display name (non-interactive: use default)
    default_display = clean_name.replace("_", " ").title()
    if sys.stdin.isatty():
        display_name = click.prompt(
            f"  Display name for deployment",
            default=default_display,
        )
    else:
        display_name = default_display

    _update_config(project_root, template + "s", clean_name, display_name)

    formatter.success(
        {"name": clean_name, "display_name": display_name, "file": str(dest_file)},
        message=f"  Created {template}: {clean_name}  (display: '{display_name}')",
    )


def _update_config(
    project_root: Path, component_key: str, name: str, display_name: str
):
    cfg_file = project_root / "daita-project.yaml"
    if cfg_file.exists():
        with open(cfg_file) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    config.setdefault(component_key, [])
    if not any(c["name"] == name for c in config[component_key]):
        config[component_key].append(
            {
                "name": name,
                "display_name": display_name,
                "type": "standard" if component_key == "agents" else "basic",
                "created_at": datetime.now().isoformat(),
            }
        )
        with open(cfg_file, "w") as f:
            yaml.dump(config, f, default_flow_style=False)


def _agent_template(name: str, class_name: str) -> str:
    return f'''\
"""
{class_name} Agent
"""
from daita import Agent


def create_agent():
    """Create the agent instance."""
    return Agent(
        name="{class_name}",
        model="gpt-4o-mini",
        prompt="You are a helpful AI assistant.",
    )


if __name__ == "__main__":
    import asyncio

    async def main():
        agent = create_agent()
        await agent.start()
        try:
            answer = await agent.run("Hello!")
            print(answer)
        finally:
            await agent.stop()

    asyncio.run(main())
'''


def _workflow_template(name: str, class_name: str) -> str:
    return f'''\
"""
{class_name} Workflow
"""
from daita import Agent, Workflow


def create_workflow():
    """Create the workflow instance."""
    workflow = Workflow("{class_name}")
    agent = Agent(name="Agent", model="gpt-4o-mini", prompt="You are helpful.")
    workflow.add_agent("agent", agent)
    return workflow


if __name__ == "__main__":
    import asyncio

    async def main():
        wf = create_workflow()
        await wf.start()
        await wf.stop()
        print("Done")

    asyncio.run(main())
'''


def _skill_template(name: str, class_name: str) -> str:
    return f'''\
"""
{class_name} Skill

Skills bundle domain-specific instructions with related tools. Attach to any
agent via `agent.add_skill({name}_skill)` to layer in behavior without
mutating the base prompt.
"""
from daita.skills import Skill
from daita.core.tools import tool


@tool
async def example_tool(payload: dict) -> dict:
    """Replace with a real tool relevant to this skill."""
    return {{"ok": True, "received": payload}}


{name}_skill = Skill(
    name="{name}",
    description="Describe what this skill teaches the agent to do.",
    instructions=(
        "Describe the behavioral guidance this skill provides. "
        "Agents that add this skill will receive these instructions at runtime."
    ),
    tools=[example_tool],
)


if __name__ == "__main__":
    # Attach to an agent:
    #
    #     from skills.{name} import {name}_skill
    #     agent.add_skill({name}_skill)
    print(f"Skill: {{{name}_skill.name}} — {{{name}_skill.description}}")
'''
