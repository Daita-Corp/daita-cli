"""
daita init — scaffold a new Daita project.
No daita-agents dependency required.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import click
import yaml

from daita_cli.output import OutputFormatter


@click.command("init")
@click.argument("project_name", required=False)
@click.option(
    "--type", "project_type",
    default="basic",
    type=click.Choice(["basic", "analysis", "pipeline"]),
    help="Project type",
)
@click.option("--force", is_flag=True, help="Overwrite existing project")
@click.pass_context
def init_command(ctx, project_name, project_type, force):
    """Initialize a new Daita project."""
    obj = ctx.obj or {}
    formatter = obj.get("formatter", OutputFormatter())

    try:
        asyncio.run(_init(project_name, project_type, force, formatter))
    except click.ClickException:
        raise
    except KeyboardInterrupt:
        click.echo("\n  Operation cancelled.", err=True)
        sys.exit(130)
    except Exception as e:
        formatter.error("ERROR", str(e))
        sys.exit(1)


async def _init(project_name, project_type, force, formatter):
    if not project_name:
        project_name = click.prompt("Project name", default=Path.cwd().name)

    project_dir = Path.cwd() / project_name

    if project_dir.exists() and not force:
        if any(project_dir.iterdir()):
            click.confirm(
                f"Directory '{project_name}' exists and is not empty. Continue?",
                abort=True,
            )

    project_dir.mkdir(exist_ok=True)
    formatter.progress(f"  Creating Daita project: {project_name}")
    formatter.progress(f"  Location: {project_dir}")

    _create_structure(project_dir)
    _create_config(project_dir, project_name)
    _create_starter_files(project_dir, project_name)
    _create_support_files(project_dir, project_name)

    if not formatter.is_json:
        click.echo(f"\nProject '{project_name}' created successfully!\n")
        click.echo(f"Next steps:")
        click.echo(f"   1. cd {project_name}")
        click.echo(f"   2. export OPENAI_API_KEY=your_key_here")
        click.echo(f"   3. pip install -r requirements.txt")
        click.echo(f"   4. daita test              # Test locally (free)")
        click.echo(f"   5. daita push              # Deploy to cloud (requires API key)")
    else:
        formatter.success({"project": project_name, "location": str(project_dir)})


def _create_structure(project_dir: Path):
    for d in [".daita", "agents", "workflows", "data", "tests"]:
        (project_dir / d).mkdir(exist_ok=True)
    for d in ["agents", "workflows", "tests"]:
        init = project_dir / d / "__init__.py"
        init.write_text('"""Daita project components."""\n')
    (project_dir / "data" / ".gitkeep").write_text("")


def _create_config(project_dir: Path, project_name: str):
    try:
        import importlib.metadata
        version = importlib.metadata.version("daita-agents")
    except Exception:
        version = "0.12.1"

    config = {
        "name": project_name,
        "version": "1.0.0",
        "description": f"A Daita AI agent project",
        "created_at": datetime.utcnow().isoformat(),
        "agents": [],
        "workflows": [],
    }
    with open(project_dir / "daita-project.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def _create_starter_files(project_dir: Path, project_name: str):
    agent_code = '''\
"""
My Agent - Data Processing Example
"""
from daita import Agent
from daita.core.tools import tool


@tool
async def calculate_stats(data: list) -> dict:
    """Calculate basic statistics for a list of numbers."""
    if not data:
        return {"error": "No data provided"}
    return {
        "count": len(data),
        "sum": sum(data),
        "avg": sum(data) / len(data),
        "min": min(data),
        "max": max(data),
    }


def create_agent():
    return Agent(
        name="Data Processor",
        model="gpt-4o-mini",
        prompt="You are a data analyst. Help users analyze and process data.",
        tools=[calculate_stats],
    )


if __name__ == "__main__":
    import asyncio

    async def main():
        agent = create_agent()
        await agent.start()
        try:
            answer = await agent.run("Analyze these sales numbers: [100, 250, 175, 300, 225]")
            print(f"Analysis: {answer}")
        finally:
            await agent.stop()

    asyncio.run(main())
'''

    workflow_code = '''\
"""
My Workflow - Data Pipeline
"""
from daita import Agent, Workflow


def create_workflow():
    workflow = Workflow("Data Pipeline")
    validator = Agent(name="Data Validator", model="gpt-4o-mini",
                      prompt="You validate data quality.")
    analyzer = Agent(name="Data Analyzer", model="gpt-4o-mini",
                     prompt="You analyze data and extract insights.")
    workflow.add_agent("validator", validator)
    workflow.add_agent("analyzer", analyzer)
    workflow.connect("validator", "validated_data", "analyzer")
    return workflow


if __name__ == "__main__":
    import asyncio

    async def main():
        wf = create_workflow()
        await wf.start()
        await wf.stop()

    asyncio.run(main())
'''

    (project_dir / "agents" / "my_agent.py").write_text(agent_code)
    (project_dir / "workflows" / "my_workflow.py").write_text(workflow_code)


def _create_support_files(project_dir: Path, project_name: str):
    try:
        import importlib.metadata
        framework_version = importlib.metadata.version("daita-agents")
    except Exception:
        framework_version = "0.12.1"

    (project_dir / "requirements.txt").write_text(
        f"# Daita Agents Framework\ndaita-agents=={framework_version}\n\n"
        "# LLM provider\nopenai>=1.0.0\n\n"
        "# Development\npytest>=7.0.0\npytest-asyncio>=0.21.0\n"
    )

    (project_dir / ".gitignore").write_text(
        "__pycache__/\n*.py[cod]\n.env\n.venv\nvenv/\n.vscode/\n.idea/\n.DS_Store\n.daita/memory/\n"
    )

    (project_dir / "tests" / "test_basic.py").write_text(
        '"""Basic tests."""\nimport pytest\n\n\ndef test_placeholder():\n    assert True\n'
    )
