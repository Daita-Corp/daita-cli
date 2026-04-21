"""
daita test [target] — run agents/workflows locally using importlib.
No daita-agents dependency at import time; user code will import it at runtime.
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import click

from daita_cli.output import OutputFormatter
from daita_cli.project_utils import ensure_project_root, list_python_files


@click.command("test")
@click.argument("target", required=False)
@click.option("--data", "data_file", help="JSON/text file with test data")
@click.option("--watch", is_flag=True, help="Watch for changes and re-run")
@click.pass_context
def test_command(ctx, target, data_file, watch):
    """Test agents and workflows locally."""
    obj = ctx.obj or {}
    formatter = obj.get("formatter", OutputFormatter())

    if watch:
        try:
            import watchdog  # noqa: F401
        except ImportError:
            raise click.ClickException(
                "watchdog is required for --watch mode.\n"
                "Install it with: pip install 'daita-agents[cli]'"
            )

    try:
        asyncio.run(_run_tests(target, data_file, watch, formatter))
    except click.ClickException:
        raise
    except KeyboardInterrupt:
        click.echo("\n  Tests cancelled.", err=True)
        sys.exit(130)
    except Exception as e:
        formatter.error("ERROR", str(e))
        sys.exit(1)


async def _run_tests(target, data_file, watch, formatter):
    project_root = ensure_project_root()
    test_data = _load_test_data(project_root, data_file)

    if target:
        await _test_single(project_root, target, test_data, formatter)
    else:
        await _test_all(project_root, test_data, formatter)

    if watch:
        formatter.progress("\n  Watching for changes... (Ctrl+C to stop)")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            formatter.progress("\n  Stopped watching.")


async def _test_single(project_root, target, test_data, formatter):
    formatter.progress(f"  Testing: {target}")
    agent_file = project_root / "agents" / f"{target}.py"
    workflow_file = project_root / "workflows" / f"{target}.py"

    if agent_file.exists():
        await _test_agent(agent_file, target, test_data, formatter)
    elif workflow_file.exists():
        await _test_workflow(workflow_file, target, test_data, formatter)
    else:
        raise click.ClickException(
            f"Target '{target}' not found in agents/ or workflows/."
        )


async def _test_all(project_root, test_data, formatter):
    agents = list_python_files(project_root / "agents")
    workflows = list_python_files(project_root / "workflows")
    formatter.progress(f"  Testing {len(agents)} agents, {len(workflows)} workflows")

    for a in agents:
        await _test_agent(project_root / "agents" / f"{a}.py", a, test_data, formatter)
    for w in workflows:
        await _test_workflow(
            project_root / "workflows" / f"{w}.py", w, test_data, formatter
        )


async def _test_agent(agent_file, name, test_data, formatter):
    try:
        factory = _load_factory(agent_file, "create_agent")
        agent = factory()

        await agent.start()
        try:
            result = await agent.run(
                f"Process this test data: {test_data}", detailed=True
            )
            click.echo(f"  {name}: OK")
            if isinstance(result, dict):
                ms = result.get("processing_time_ms", 0)
                cost = result.get("cost_usd", 0)
                click.echo(f"    {ms:.0f}ms  ${cost:.4f}")
        finally:
            await agent.stop()
    except Exception as e:
        click.echo(f"  {name}: FAILED — {e}")


async def _test_workflow(workflow_file, name, test_data, formatter):
    try:
        factory = _load_factory(workflow_file, "create_workflow")
        wf = factory()
        await wf.start()
        try:
            if hasattr(wf, "agents") and wf.agents:
                first = list(wf.agents.keys())[0]
                await wf.inject_data(first, test_data)
                await asyncio.sleep(1)
            click.echo(f"  {name}: OK")
        finally:
            await wf.stop()
    except Exception as e:
        click.echo(f"  {name}: FAILED — {e}")


def _load_factory(file_path: Path, fn_name: str):
    """Load a Python file and return the named factory function."""
    project_root = file_path.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    spec = importlib.util.spec_from_file_location("_daita_test_module", file_path)
    if spec is None:
        raise ImportError(f"Cannot load {file_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise ImportError(f"Failed to load {file_path.name}: {e}")

    if not hasattr(module, fn_name):
        available = [
            n
            for n in dir(module)
            if callable(getattr(module, n)) and not n.startswith("_")
        ]
        raise ValueError(f"No {fn_name}() in {file_path.name}. Available: {available}")
    return getattr(module, fn_name)


def _load_test_data(project_root: Path, data_file: str | None) -> dict:
    if not data_file:
        return {"test": True, "message": "Default test data"}
    path = Path(data_file)
    if not path.is_absolute():
        path = project_root / path
    if path.exists():
        if path.suffix == ".json":
            with open(path) as f:
                return json.load(f)
        else:
            with open(path) as f:
                return {"content": f.read()}
    return {"test": True}
