import json
import os
import shutil
import sys

import click

from daita_cli.command_helpers import api_command, normalize_rows
from daita_cli.commands._timeline import compute_bottlenecks, render_timeline

# Display schema for `traces list`. Keys = display columns; values = API field
# candidates (first present wins). Tolerates snake_case ↔ camelCase drift.
_TRACE_ROW_SCHEMA = {
    "trace_id": ("id", "trace_id"),
    "name": ("name",),
    "status": ("status",),
    "started_at": ("startTime", "started_at", "start_time", "created_at"),
    "duration_ms": ("duration", "duration_ms", "latency_ms"),
    "cost": ("cost", "total_cost", "cost_usd"),
}

_SPAN_ROW_SCHEMA = {
    "span_id": ("span_id", "id", "spanId"),
    "name": ("name", "operation_name", "operationName"),
    "status": ("status",),
    "started_at": ("startTime", "started_at", "start_time"),
    "duration_ms": ("duration", "duration_ms"),
}

_DECISION_ROW_SCHEMA = {
    "decision_id": ("decision_id", "id", "decisionId"),
    "type": ("type", "decision_type", "decisionType"),
    "timestamp": ("timestamp", "startTime", "created_at"),
    "summary": ("summary", "description", "reason"),
}


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
    items = (
        data if isinstance(data, list) else data.get("traces", data.get("items", []))
    )
    rows = normalize_rows(items, _TRACE_ROW_SCHEMA)
    formatter.list_items(
        rows,
        columns=list(_TRACE_ROW_SCHEMA.keys()),
        title="Traces",
    )


@traces.command("show")
@click.argument("trace_id")
@api_command
async def show_trace(client, formatter, trace_id):
    """Show trace details."""
    data = await client.get(f"/api/v1/traces/traces/{trace_id}")
    formatter.item(data)


def _term_width(explicit: int | None) -> int:
    if explicit:
        return explicit
    try:
        return shutil.get_terminal_size((100, 20)).columns
    except OSError:
        return 100


def _ascii_fallback_needed() -> bool:
    """True if the terminal likely can't render unicode block chars."""
    lang = (os.environ.get("LANG") or "").lower()
    return "utf" not in lang and "utf8" not in lang


@traces.command("spans")
@click.argument("trace_id")
@click.option(
    "--mode",
    type=click.Choice(["timeline", "tree", "flat"]),
    default=None,
    help="Rendering mode. Default: timeline on TTY, flat on pipe.",
)
@click.option("--ascii", "ascii_only", is_flag=True, help="Force ASCII-only rendering.")
@click.option("--width", type=int, help="Override terminal width.")
@click.option(
    "--min-duration",
    type=float,
    default=0,
    help="Hide spans shorter than N ms (timeline mode only).",
)
@api_command
async def trace_spans(
    client, formatter, trace_id, mode, ascii_only, width, min_duration
):
    """Show span hierarchy for a trace.

    On a TTY, renders an ASCII timeline by default. When piped / non-TTY,
    outputs structured JSON with pre-computed bottlenecks so LLM callers
    can reason over the data without parsing terminal output.
    """
    data = await client.get(f"/api/v1/traces/traces/{trace_id}/spans")
    spans = data if isinstance(data, list) else data.get("spans", data.get("items", []))

    # JSON mode: structured payload with computed signals
    if formatter.is_json:
        print(
            json.dumps(
                {
                    "trace_id": trace_id,
                    "spans": spans,
                    "bottlenecks": compute_bottlenecks(spans),
                    "count": len(spans),
                },
                default=str,
            )
        )
        return

    effective_mode = mode or ("timeline" if sys.stdout.isatty() else "flat")

    if effective_mode == "flat":
        rows = normalize_rows(spans, _SPAN_ROW_SCHEMA)
        formatter.list_items(
            rows, columns=list(_SPAN_ROW_SCHEMA.keys()), title=f"Spans: {trace_id}"
        )
        return

    # Timeline or tree — both go through the renderer (tree = width-0 trick
    # would be awkward; instead we render timeline and drop the bar column
    # for --mode tree by reusing a tiny renderer).
    if effective_mode == "tree":
        _render_tree(spans)
        return

    use_ascii = ascii_only or _ascii_fallback_needed()
    term_width = _term_width(width)

    click.echo(f"\nTrace: {trace_id}")
    click.echo(
        render_timeline(
            spans,
            width=term_width,
            ascii_only=use_ascii,
            min_duration_ms=min_duration,
        )
    )


def _render_tree(spans: list[dict]) -> None:
    """Minimal tree rendering without the timeline bars. No width math."""
    from daita_cli.commands._timeline import build_tree

    roots = build_tree(spans)
    if not roots:
        click.echo("No spans to display.")
        return

    def _emit(node, prefix: str = "", is_last: bool = True):
        connector = "└─ " if node.depth else ""
        click.echo(f"{prefix}{connector}{node.name}  ({node.duration_ms:.0f}ms)")
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, c in enumerate(node.children):
            _emit(
                c,
                prefix=child_prefix if node.depth else "  ",
                is_last=(i == len(node.children) - 1),
            )

    for i, r in enumerate(roots):
        _emit(r, is_last=(i == len(roots) - 1))


@traces.command("decisions")
@click.argument("trace_id")
@api_command
async def trace_decisions(client, formatter, trace_id):
    """Show AI decision events for a trace."""
    data = await client.get(f"/api/v1/traces/traces/{trace_id}/decisions")
    items = (
        data if isinstance(data, list) else data.get("decisions", data.get("items", []))
    )
    rows = normalize_rows(items, _DECISION_ROW_SCHEMA)
    formatter.list_items(
        rows, columns=list(_DECISION_ROW_SCHEMA.keys()), title=f"Decisions: {trace_id}"
    )


@traces.command("stats")
@click.option(
    "--period",
    type=click.Choice(["24h", "7d", "30d"]),
    default="24h",
    show_default=True,
)
@api_command
async def trace_stats(client, formatter, period):
    """Show trace statistics."""
    data = await client.get("/api/v1/traces/traces/stats", params={"period": period})
    formatter.item(data)
