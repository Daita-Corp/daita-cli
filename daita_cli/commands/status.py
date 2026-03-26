"""
daita status — show project and deployment status.

Works without a Daita project (cloud-only mode). Shows local project info
if daita-project.yaml is found; always shows cloud deployments if API key present.
"""

import asyncio
import os
import sys
from pathlib import Path

import click

from daita_cli.api_client import DaitaAPIClient, AuthError, APIError
from daita_cli.output import OutputFormatter


@click.command("status")
@click.pass_context
def status_command(ctx):
    """Show project and deployment status."""
    obj = ctx.obj or {}
    formatter = obj.get("formatter", OutputFormatter())

    async def _run():
        # Local project info (optional — no error if not in a project)
        project_name = _local_project_name()
        if project_name and not formatter.is_json:
            click.echo(f"  Project: {project_name}")
            click.echo(f"  Location: {Path.cwd()}")
            click.echo("")

        api_key = os.getenv("DAITA_API_KEY")
        if not api_key:
            if formatter.is_json:
                formatter.error("AUTH_ERROR", "DAITA_API_KEY not set")
            else:
                click.echo("  Cloud Deployments: Not configured")
                click.echo("  Set DAITA_API_KEY to see deployment status.")
            return

        async with DaitaAPIClient() as client:
            params = {}
            if project_name:
                params["project_name"] = project_name
            try:
                data = await client.get("/api/v1/deployments/api-key", params=params or None)
            except APIError as e:
                formatter.error("API_ERROR", str(e))
                return

            deployments = data if isinstance(data, list) else data.get("deployments", [])

            if formatter.is_json:
                import json
                print(json.dumps({"project": project_name, "deployments": deployments}, default=str))
                return

            if not deployments:
                click.echo("  Cloud Deployments: None")
                click.echo("  Run 'daita push' to deploy.")
                return

            scope = f" ({project_name})" if project_name else " (Organization)"
            click.echo(f"  Cloud Deployments{scope} ({len(deployments)}):")
            for d in deployments[:5]:
                env = d.get("environment", "?")
                version = d.get("version", "?")
                status = d.get("status", "?")
                deployed_at = d.get("deployed_at", "")[:16].replace("T", " ")
                icon = "●" if status == "active" else "○"
                click.echo(f"    {icon} {env}: v{version}  {deployed_at}  [{status}]")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(130)


def _local_project_name() -> str | None:
    """Walk upward from cwd looking for daita-project.yaml."""
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
