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


def _to_class_name(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_") if w)


def _clean_name(name: str) -> str:
    return name.replace("-", "_").lower()


def _create_component(template: str, name: str, formatter: OutputFormatter):
    project_root = ensure_project_root()
    clean_name = _clean_name(name)
    class_name = _to_class_name(clean_name)

    if template == "agent":
        dest_dir = project_root / "agents"
        dest_file = dest_dir / f"{clean_name}.py"
        if dest_file.exists():
            raise click.ClickException(f"Agent '{clean_name}' already exists.")
        dest_dir.mkdir(exist_ok=True)
        dest_file.write_text(_agent_template(clean_name, class_name))
    elif template == "workflow":
        dest_dir = project_root / "workflows"
        dest_file = dest_dir / f"{clean_name}.py"
        if dest_file.exists():
            raise click.ClickException(f"Workflow '{clean_name}' already exists.")
        dest_dir.mkdir(exist_ok=True)
        dest_file.write_text(_workflow_template(clean_name, class_name))
    else:
        raise click.ClickException(f"Unknown template: {template}")

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


def _update_config(project_root: Path, component_key: str, name: str, display_name: str):
    cfg_file = project_root / "daita-project.yaml"
    if cfg_file.exists():
        with open(cfg_file) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    config.setdefault(component_key, [])
    if not any(c["name"] == name for c in config[component_key]):
        config[component_key].append({
            "name": name,
            "display_name": display_name,
            "type": "standard" if component_key == "agents" else "basic",
            "created_at": datetime.now().isoformat(),
        })
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
