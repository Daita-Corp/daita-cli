"""
daita logs — show deployment history from the cloud API.
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import click

from daita_cli.api_client import DaitaAPIClient, AuthError, APIError
from daita_cli.output import OutputFormatter


@click.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Poll for new deployments")
@click.option("--lines", "-n", default=10, show_default=True, help="Number of deployments to show")
@click.pass_context
def logs_command(ctx, follow, lines):
    """View deployment logs."""
    obj = ctx.obj or {}
    formatter = obj.get("formatter", OutputFormatter())

    async def _run():
        api_key = os.getenv("DAITA_API_KEY")
        if not api_key:
            formatter.error("AUTH_ERROR", "DAITA_API_KEY not set")
            sys.exit(2)

        project_name = _local_project_name()

        async with DaitaAPIClient() as client:
            deployments = await _fetch(client, project_name, lines)

        if formatter.is_json:
            import json
            print(json.dumps({"deployments": deployments, "count": len(deployments)}, default=str))
            return

        scope = f" ({project_name})" if project_name else " (Organization)"
        click.echo(f"\n  Deployment History{scope}\n")

        _print_deployments(deployments)

        if follow:
            click.echo("\n  Following... (Ctrl+C to stop)")
            try:
                while True:
                    await asyncio.sleep(5)
                    async with DaitaAPIClient() as client:
                        fresh = await _fetch(client, project_name, lines)
                    if len(fresh) > len(deployments):
                        click.echo("\n  New deployment:")
                        _print_deployments(fresh[:1])
                        deployments = fresh
            except KeyboardInterrupt:
                click.echo("\n  Stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(130)


async def _fetch(client, project_name, limit):
    params = {"per_page": limit}
    if project_name:
        params["project_name"] = project_name
    try:
        data = await client.get("/api/v1/deployments/api-key", params=params)
        return data if isinstance(data, list) else data.get("deployments", [])
    except APIError:
        return []


def _print_deployments(deployments):
    for d in deployments:
        env = d.get("environment", "?")
        version = d.get("version", "?")
        project = d.get("project_name", "")
        status = d.get("status", "?")
        ts = d.get("deployed_at", "")
        if ts and "T" in ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                ts = ts[:19].replace("T", " ")
        icon = "●" if status == "active" else "○"
        label = f"{project} " if project else ""
        click.echo(f"  {icon} {env}: {label}v{version}")
        click.echo(f"      {ts}  [{status}]")
        click.echo("")


def _local_project_name() -> str | None:
    try:
        import yaml
        current = Path.cwd()
        for p in [current] + list(current.parents):
            cfg = p / "daita-project.yaml"
            if cfg.exists():
                with open(cfg) as f:
                    config = yaml.safe_load(f)
                return config.get("name") if config else None
    except Exception:
        pass
    return None
