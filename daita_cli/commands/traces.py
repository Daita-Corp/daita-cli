import click
from daita_cli.command_helpers import api_command


@click.group()
def traces():
    """View execution traces."""
    pass


@traces.command("list")
@click.option("--limit", default=10, show_default=True)
@click.option("--status")
@click.option("--agent-id")
@api_command
async def list_traces(client, formatter, limit, status, agent_id):
    """List traces."""
    params = {"per_page": limit}
    if status:
        params["status"] = status
    if agent_id:
        params["agent_id"] = agent_id
    data = await client.get("/api/v1/traces/traces", params=params)
    items = data if isinstance(data, list) else data.get("traces", data.get("items", []))
    formatter.list_items(
        items,
        columns=["trace_id", "agent_id", "status", "started_at", "duration_ms"],
        title="Traces",
    )


@traces.command("show")
@click.argument("trace_id")
@api_command
async def show_trace(client, formatter, trace_id):
    """Show trace details."""
    data = await client.get(f"/api/v1/traces/traces/{trace_id}")
    formatter.item(data)


@traces.command("spans")
@click.argument("trace_id")
@api_command
async def trace_spans(client, formatter, trace_id):
    """Show span hierarchy for a trace."""
    data = await client.get(f"/api/v1/traces/traces/{trace_id}/spans")
    items = data if isinstance(data, list) else data.get("spans", data.get("items", []))
    formatter.list_items(
        items,
        columns=["span_id", "name", "status", "started_at", "duration_ms"],
        title=f"Spans: {trace_id}",
    )


@traces.command("decisions")
@click.argument("trace_id")
@api_command
async def trace_decisions(client, formatter, trace_id):
    """Show AI decision events for a trace."""
    data = await client.get(f"/api/v1/traces/traces/{trace_id}/decisions")
    items = data if isinstance(data, list) else data.get("decisions", data.get("items", []))
    formatter.list_items(
        items,
        columns=["decision_id", "type", "timestamp", "summary"],
        title=f"Decisions: {trace_id}",
    )


@traces.command("stats")
@click.option("--period", type=click.Choice(["24h", "7d", "30d"]), default="24h", show_default=True)
@api_command
async def trace_stats(client, formatter, period):
    """Show trace statistics."""
    data = await client.get("/api/v1/traces/traces/stats", params={"period": period})
    formatter.item(data)
