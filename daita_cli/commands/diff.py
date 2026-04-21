"""
daita diff <exec_a> <exec_b> — compare two executions.

Designed as a summarizer first, enumerator second. Default output shows
headline deltas; `--focus` drills into one dimension (output, spans,
decisions, cost).
"""

from __future__ import annotations

import asyncio
import difflib
import json
import sys
from typing import Any

import click

from daita_cli.api_client import DaitaAPIClient
from daita_cli.command_helpers import api_command, pick

_FOCUS_CHOICES = ("all", "output", "spans", "decisions", "cost")


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


async def _fetch_bundle(client: DaitaAPIClient, execution_id: str) -> dict:
    """Fetch execution + its spans + decisions in parallel. Missing pieces
    are tolerated — a failed execution may not have spans yet."""

    async def _safe(coro):
        try:
            return await coro
        except Exception:
            return None

    exec_data = await client.get(f"/api/v1/executions/{execution_id}")
    # In this backend, trace_id and execution_id are the same underlying
    # operation_id — fall back if no explicit linkage field is present.
    trace_id = pick(exec_data, "trace_id", "traceId", default=None) or execution_id

    # The trace record carries fields the execution record doesn't (cost,
    # token counts). Fetch it alongside spans/decisions so we can look up
    # metrics from whichever payload actually has them.
    trace_data, spans, decisions = await asyncio.gather(
        _safe(client.get(f"/api/v1/traces/traces/{trace_id}")),
        _safe(client.get(f"/api/v1/traces/traces/{trace_id}/spans")),
        _safe(client.get(f"/api/v1/traces/traces/{trace_id}/decisions")),
    )

    return {
        "execution": exec_data,
        "trace": trace_data or {},
        "spans": _as_list(spans, "spans"),
        "decisions": _as_list(decisions, "decisions"),
    }


def _as_list(raw: Any, key: str) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get(key) or raw.get("items") or []
    return []


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------


def _to_number(v) -> float | None:
    """Coerce to float or return None. Tolerates numeric strings like '81339'."""
    if v is None:
        return None
    if isinstance(v, bool):  # bool is a subclass of int — don't want it
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _delta(a, b) -> dict | None:
    an, bn = _to_number(a), _to_number(b)
    if an is None or bn is None:
        return None
    if an == 0 and bn == 0:
        return {"a": 0, "b": 0, "delta": 0, "pct": 0}
    change = bn - an
    pct = (change / an * 100) if an else float("inf")
    return {"a": an, "b": bn, "delta": change, "pct": round(pct, 1)}


def _stringify_output(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, sort_keys=True, default=str)


def _span_index(spans: list[dict]) -> dict[str, dict]:
    """Index spans by name for quick lookup. Collisions keep the longest one
    (typical pattern: one span name per logical step)."""
    by_name: dict[str, dict] = {}
    for s in spans:
        name = s.get("operationName") or s.get("name") or s.get("operation_name") or ""
        if not name:
            continue
        existing = by_name.get(name)
        s_dur = s.get("duration_ms") or s.get("duration") or 0
        e_dur = (
            (existing.get("duration_ms") or existing.get("duration") or 0)
            if existing
            else 0
        )
        if existing is None or s_dur > e_dur:
            by_name[name] = s
    return by_name


def _span_duration(s: dict) -> float | None:
    """Tolerate duration_ms / duration naming."""
    for k in ("duration_ms", "duration"):
        v = s.get(k)
        if v is not None:
            return float(v)
    return None


def _diff_spans(a: list[dict], b: list[dict]) -> list[dict]:
    """Return per-span timing deltas for spans that appear in both runs."""
    ia, ib = _span_index(a), _span_index(b)
    out: list[dict] = []
    for name in sorted(set(ia) | set(ib)):
        da = _span_duration(ia.get(name, {})) if name in ia else None
        db = _span_duration(ib.get(name, {})) if name in ib else None
        if da is None and db is None:
            continue
        out.append(
            {
                "name": name,
                "a_ms": da,
                "b_ms": db,
                "delta_ms": (db - da) if (da is not None and db is not None) else None,
                "only_in": "a" if db is None else ("b" if da is None else None),
            }
        )
    # Sort by absolute delta descending so the biggest movers surface first
    out.sort(
        key=lambda r: abs(r["delta_ms"]) if r["delta_ms"] is not None else 0,
        reverse=True,
    )
    return out


def _decision_key(d: dict) -> str:
    """Best-effort identity for a DecisionEvent.

    The backend `DecisionEvent` model has no top-level id — fall back through
    nested span_id, then composite (timestamp + decisionPoint)."""
    return (
        d.get("decision_id")
        or d.get("decisionId")
        or d.get("id")
        or (d.get("data") or {}).get("span_id")
        or f"{d.get('timestamp', '')}:{d.get('decisionPoint') or d.get('decision_point', '')}"
    )


def _diff_decisions(a: list[dict], b: list[dict]) -> dict:
    a_ids = {_decision_key(d) for d in a}
    b_ids = {_decision_key(d) for d in b}
    return {
        "count_a": len(a),
        "count_b": len(b),
        "only_in_a": len(a_ids - b_ids),
        "only_in_b": len(b_ids - a_ids),
        "shared": len(a_ids & b_ids),
    }


def _output_diff(a: Any, b: Any) -> dict:
    sa, sb = _stringify_output(a), _stringify_output(b)
    if sa == sb:
        return {"changed": False, "chars_a": len(sa), "chars_b": len(sb)}
    return {
        "changed": True,
        "chars_a": len(sa),
        "chars_b": len(sb),
        "size_delta": len(sb) - len(sa),
    }


def _unified_output_diff(a: Any, b: Any) -> str:
    sa = _stringify_output(a).splitlines(keepends=False)
    sb = _stringify_output(b).splitlines(keepends=False)
    return "\n".join(
        difflib.unified_diff(sa, sb, fromfile="a", tofile="b", lineterm="")
    )


# Field-name aliases for the metrics diff extracts. First present, non-empty wins.
_DURATION_KEYS = ("duration_ms", "duration", "latency_ms")
_COST_KEYS = ("cost_usd", "cost", "total_cost")
_TOKENS_IN_KEYS = ("tokens_in", "input_tokens", "inputTokens", "tokensIn")
_TOKENS_OUT_KEYS = ("tokens_out", "output_tokens", "outputTokens", "tokensOut")
_EXEC_ID_KEYS = ("execution_id", "id", "executionId")
_RESULT_KEYS = ("result", "output", "output_preview", "outputPreview")


def _metric(bundle: dict, keys: tuple[str, ...]):
    """Pull a numeric metric from the execution payload first, then fall back
    to the trace payload. Cost and token counts live on the trace record in
    this backend; duration lives on both."""
    return pick(bundle.get("execution") or {}, *keys, default=None) or pick(
        bundle.get("trace") or {}, *keys, default=None
    )


def build_summary(bundle_a: dict, bundle_b: dict) -> dict:
    """Compute a structured diff summary. Stable shape — safe for JSON/MCP."""
    ea, eb = bundle_a["execution"], bundle_b["execution"]
    return {
        "a": pick(ea, *_EXEC_ID_KEYS),
        "b": pick(eb, *_EXEC_ID_KEYS),
        "status": {"a": ea.get("status"), "b": eb.get("status")},
        "duration_ms": _delta(
            _metric(bundle_a, _DURATION_KEYS), _metric(bundle_b, _DURATION_KEYS)
        ),
        "cost_usd": _delta(
            _metric(bundle_a, _COST_KEYS), _metric(bundle_b, _COST_KEYS)
        ),
        "tokens_in": _delta(
            _metric(bundle_a, _TOKENS_IN_KEYS), _metric(bundle_b, _TOKENS_IN_KEYS)
        ),
        "tokens_out": _delta(
            _metric(bundle_a, _TOKENS_OUT_KEYS), _metric(bundle_b, _TOKENS_OUT_KEYS)
        ),
        "output": _output_diff(
            pick(ea, *_RESULT_KEYS, default=None), pick(eb, *_RESULT_KEYS, default=None)
        ),
        "spans": _diff_spans(bundle_a["spans"], bundle_b["spans"]),
        "decisions": _diff_decisions(bundle_a["decisions"], bundle_b["decisions"]),
    }


async def compute_diff(client: DaitaAPIClient, exec_a: str, exec_b: str) -> dict:
    """Fetch both bundles and return the summary. Shared with MCP."""
    a, b = await asyncio.gather(
        _fetch_bundle(client, exec_a),
        _fetch_bundle(client, exec_b),
    )
    return build_summary(a, b)


# ---------------------------------------------------------------------------
# Human-readable rendering
# ---------------------------------------------------------------------------


def _fmt_delta(d: dict | None, unit: str = "") -> str:
    if d is None:
        return "—"
    sign = "+" if d["delta"] > 0 else ""
    pct_str = f" ({sign}{d['pct']:.0f}%)" if d["pct"] != float("inf") else ""
    return f"{d['a']}{unit} → {d['b']}{unit}  {sign}{d['delta']}{unit}{pct_str}"


def render_diff_text(summary: dict, focus: str = "all") -> str:
    """Render a human-readable summary. Terse by default."""
    lines = [f"Diff: {summary['a']}  →  {summary['b']}", "─" * 60]

    st = summary["status"]
    if focus in ("all", "cost"):
        lines.append(f"Status       {st['a']:<15} {st['b']:<15}")

    # Duration and cost metrics are both relevant to a cost-focused view.
    if focus in ("all", "cost") and summary["duration_ms"]:
        lines.append(f"Duration     {_fmt_delta(summary['duration_ms'], 'ms')}")
    if focus in ("all", "cost") and summary["cost_usd"]:
        lines.append(f"Cost         {_fmt_delta(summary['cost_usd'], '$')}")
    if focus in ("all", "cost") and summary["tokens_in"]:
        lines.append(f"Tokens in    {_fmt_delta(summary['tokens_in'])}")
    if focus in ("all", "cost") and summary["tokens_out"]:
        lines.append(f"Tokens out   {_fmt_delta(summary['tokens_out'])}")

    # If the caller asked for cost but the backend didn't return cost/tokens,
    # make that explicit instead of leaving an empty block.
    if focus == "cost" and not any(
        summary[k] for k in ("cost_usd", "tokens_in", "tokens_out")
    ):
        lines.append("Cost/tokens  (not reported by the execution or trace record)")

    if focus in ("all", "output"):
        o = summary["output"]
        if o["changed"]:
            lines.append(
                f"Output       {o['chars_a']} → {o['chars_b']} chars  (use --focus output --unified for diff)"
            )
        else:
            lines.append("Output       identical")

    if focus in ("all", "spans"):
        spans = summary["spans"]
        if not spans:
            lines.append("Spans        (no span data)")
        elif focus == "spans":
            lines.append("Spans (top movers)")
            for s in spans[:10]:
                if s["delta_ms"] is None:
                    tag = "only in a" if s["only_in"] == "a" else "only in b"
                    lines.append(f"  {s['name']:<30} {tag}")
                else:
                    arrow = "▲" if s["delta_ms"] > 0 else "▼"
                    lines.append(
                        f"  {s['name']:<30} {s['a_ms']}ms → {s['b_ms']}ms  "
                        f"{arrow}{abs(s['delta_ms'])}ms"
                    )
        else:
            changed = [
                s for s in spans if s["delta_ms"] not in (None, 0) or s["only_in"]
            ]
            lines.append(f"Spans        {len(changed)} differed (use --focus spans)")

    if focus in ("all", "decisions"):
        d = summary["decisions"]
        diff_count = d["only_in_a"] + d["only_in_b"]
        if focus == "decisions":
            if d["count_a"] == 0 and d["count_b"] == 0:
                lines.append("Decisions    (none recorded for either run)")
            else:
                lines.append(f"Decisions    {d['count_a']} vs {d['count_b']}")
                lines.append(f"  shared    : {d['shared']}")
                lines.append(f"  only in a : {d['only_in_a']}")
                lines.append(f"  only in b : {d['only_in_b']}")
        else:
            if d["count_a"] == 0 and d["count_b"] == 0:
                lines.append("Decisions    (none recorded)")
            elif diff_count == 0:
                lines.append(f"Decisions    {d['count_a']} identical")
            else:
                lines.append(
                    f"Decisions    {d['count_a']} vs {d['count_b']}, {diff_count} differed"
                )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("diff")
@click.argument("execution_a")
@click.argument("execution_b")
@click.option(
    "--focus",
    type=click.Choice(_FOCUS_CHOICES),
    default="all",
    show_default=True,
    help="Drill into one dimension.",
)
@click.option(
    "--unified",
    is_flag=True,
    help="With --focus output, print a git-style unified diff of the final outputs.",
)
@api_command
async def diff_command(
    client: DaitaAPIClient,
    formatter,
    execution_a: str,
    execution_b: str,
    focus: str,
    unified: bool,
):
    """Compare two executions. Headline deltas by default; drill in with --focus."""
    from daita_cli.commands._spinner import spinner

    async with spinner(f"Diffing {execution_a} vs {execution_b}…", formatter=formatter):
        summary = await compute_diff(client, execution_a, execution_b)

    async def _refetch_for_unified():
        async with spinner("Computing unified diff…", formatter=formatter):
            return await asyncio.gather(
                _fetch_bundle(client, execution_a),
                _fetch_bundle(client, execution_b),
            )

    if formatter.is_json:
        if unified and focus == "output":
            a, b = await _refetch_for_unified()
            summary["output_unified"] = _unified_output_diff(
                a["execution"].get("result"), b["execution"].get("result")
            )
        print(json.dumps(summary, indent=2, default=str))
        return

    click.echo(render_diff_text(summary, focus=focus))

    if unified and focus == "output" and summary["output"]["changed"]:
        a, b = await _refetch_for_unified()
        click.echo("\n--- unified output diff ---")
        click.echo(
            _unified_output_diff(
                a["execution"].get("result"), b["execution"].get("result")
            )
        )

    # Non-zero exit when executions diverged on status — useful for CI.
    if summary["status"]["a"] != summary["status"]["b"]:
        sys.exit(1)
