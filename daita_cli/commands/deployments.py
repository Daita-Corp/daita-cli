import click
from daita_cli.command_helpers import api_command


@click.group()
def deployments():
    """Manage deployments."""
    pass


@deployments.command("list")
@click.option("--limit", default=10, show_default=True)
@api_command
async def list_deployments(client, formatter, limit):
    """List deployments."""
    data = await client.get("/api/v1/deployments/api-key", params={"per_page": limit})
    items = data if isinstance(data, list) else data.get("deployments", data.get("items", []))
    formatter.list_items(
        items,
        columns=["deployment_id", "project_name", "environment", "status", "version", "deployed_at"],
        title="Deployments",
    )


@deployments.command("show")
@click.argument("deployment_id")
@api_command
async def show_deployment(client, formatter, deployment_id):
    """Show deployment details."""
    data = await client.get(f"/api/v1/deployments/{deployment_id}")
    formatter.item(data)


@deployments.command("delete")
@click.argument("deployment_id")
@click.option("--force", is_flag=True, help="Skip confirmation")
@api_command
async def delete_deployment(client, formatter, deployment_id, force):
    """Delete a deployment."""
    if not force:
        click.confirm(f"Delete deployment {deployment_id}?", abort=True)
    data = await client.delete(f"/api/v1/deployments/{deployment_id}")
    formatter.success(data, message=f"Deployment {deployment_id} deleted.")


@deployments.command("history")
@click.argument("project_name")
@click.option("--limit", default=10, show_default=True)
@api_command
async def deployment_history(client, formatter, project_name, limit):
    """Show deployment history for a project."""
    data = await client.get(
        f"/api/v1/deployments/history/{project_name}",
        params={"per_page": limit},
    )
    items = data if isinstance(data, list) else data.get("deployments", data.get("items", []))
    formatter.list_items(
        items,
        columns=["deployment_id", "environment", "status", "version", "deployed_at"],
        title=f"Deployment History: {project_name}",
    )


@deployments.command("rollback")
@click.argument("deployment_id")
@click.option("--force", is_flag=True, help="Skip confirmation")
@api_command
async def rollback_deployment(client, formatter, deployment_id, force):
    """Rollback to a previous deployment."""
    if not force:
        click.confirm(f"Rollback to deployment {deployment_id}?", abort=True)
    data = await client.post(f"/api/v1/deployments/rollback/{deployment_id}")
    formatter.success(data, message=f"Rolled back to deployment {deployment_id}.")
