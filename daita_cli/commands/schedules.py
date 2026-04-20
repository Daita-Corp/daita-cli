import click
from daita_cli.command_helpers import api_command


@click.group()
def schedules():
    """Manage agent schedules."""
    pass


@schedules.command("list")
@api_command
async def list_schedules(client, formatter):
    """List schedules."""
    data = await client.get("/api/v1/schedules/")
    items = (
        data if isinstance(data, list) else data.get("schedules", data.get("items", []))
    )
    formatter.list_items(
        items,
        columns=["id", "name", "cron", "agent_name", "status", "next_run"],
        title="Schedules",
    )


@schedules.command("show")
@click.argument("schedule_id")
@api_command
async def show_schedule(client, formatter, schedule_id):
    """Show schedule details."""
    data = await client.get(f"/api/v1/schedules/{schedule_id}")
    formatter.item(data)


@schedules.command("pause")
@click.argument("schedule_id")
@api_command
async def pause_schedule(client, formatter, schedule_id):
    """Pause a schedule."""
    data = await client.patch(
        f"/api/v1/schedules/{schedule_id}", json={"enabled": False}
    )
    formatter.success(data, message=f"Schedule {schedule_id} paused.")


@schedules.command("resume")
@click.argument("schedule_id")
@api_command
async def resume_schedule(client, formatter, schedule_id):
    """Resume a paused schedule."""
    data = await client.patch(
        f"/api/v1/schedules/{schedule_id}", json={"enabled": True}
    )
    formatter.success(data, message=f"Schedule {schedule_id} resumed.")
