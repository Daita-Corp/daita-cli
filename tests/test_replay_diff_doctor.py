"""Tests for replay, diff, doctor, and ASCII timeline."""

import asyncio
import json
import pytest
import respx
import httpx

from daita_cli.api_client import DaitaAPIClient
from daita_cli.commands._timeline import (
    build_tree,
    compute_bottlenecks,
    render_timeline,
    trace_duration,
)
from daita_cli.commands.diff import build_summary, compute_diff, render_diff_text
from daita_cli.commands.doctor import (
    Level,
    check_api_key,
    check_python_version,
    run_doctor,
)
from daita_cli.commands.replay import _build_replay_request


# ---------------------------------------------------------------------------
# _timeline
# ---------------------------------------------------------------------------


def _span(id_, name, parent=None, start=0, duration=100):
    return {
        "span_id": id_,
        "name": name,
        "parent_span_id": parent,
        "start_ms": start,
        "duration_ms": duration,
    }


def test_build_tree_nests_children_under_parents():
    spans = [
        _span("1", "root", None, 0, 1000),
        _span("2", "child_a", "1", 100, 200),
        _span("3", "grandchild", "2", 150, 100),
        _span("4", "child_b", "1", 400, 500),
    ]
    roots = build_tree(spans)
    assert len(roots) == 1
    assert roots[0].name == "root"
    assert len(roots[0].children) == 2
    assert roots[0].children[0].name == "child_a"
    assert roots[0].children[0].children[0].name == "grandchild"


def test_build_tree_handles_camelcase_api_shape():
    """Regression: the real API uses spanId / parentSpanId / operationName /
    startTime / duration (camelCase). Earlier code only looked for snake_case
    and silently dropped every span."""
    spans = [
        {
            "spanId": "root_span_id",
            "parentSpanId": None,
            "operationName": "agent_run",
            "startTime": "2026-04-18T16:00:24.533274+00:00",
            "duration": 5945,
            "status": "success",
        },
        {
            "spanId": "child_span_id",
            "parentSpanId": "root_span_id",
            "operationName": "llm_call",
            "startTime": "2026-04-18T16:00:25.000000+00:00",
            "duration": 2000,
            "status": "success",
        },
    ]
    roots = build_tree(spans)
    assert len(roots) == 1
    assert roots[0].name == "agent_run"
    assert roots[0].duration_ms == 5945
    assert len(roots[0].children) == 1
    assert roots[0].children[0].name == "llm_call"


def test_render_timeline_camelcase_api_shape_renders_non_empty():
    """If build_tree recognizes the camelCase schema, render_timeline should
    produce populated output (not 'No spans to display')."""
    spans = [
        {"spanId": "1", "parentSpanId": None, "operationName": "pipeline",
         "startTime": "2026-01-01T00:00:00+00:00", "duration": 1000},
        {"spanId": "2", "parentSpanId": "1", "operationName": "step_a",
         "startTime": "2026-01-01T00:00:00+00:00", "duration": 300},
    ]
    out = render_timeline(spans, width=80, ascii_only=True)
    assert "No spans" not in out
    assert "pipeline" in out
    assert "step_a" in out


def test_build_tree_handles_orphan_spans():
    """Spans whose parent_span_id is missing should become roots."""
    spans = [
        _span("1", "orphan_a", None, 0, 100),
        _span("2", "orphan_b", "nonexistent", 200, 100),
    ]
    roots = build_tree(spans)
    assert len(roots) == 2


def test_trace_duration_computes_total_span():
    spans = [
        _span("1", "a", None, 0, 500),
        _span("2", "b", None, 300, 400),  # ends at 700
    ]
    roots = build_tree(spans)
    assert trace_duration(roots) == 700


def test_compute_bottlenecks_flags_dominant_spans():
    # transform consumes 70% of total → should be flagged slow
    spans = [
        _span("1", "pipeline", None, 0, 1000),
        _span("2", "extract", "1", 0, 100),
        _span("3", "transform", "1", 100, 700),
        _span("4", "load", "1", 800, 200),
    ]
    bottlenecks = compute_bottlenecks(spans)
    names = {b["name"] for b in bottlenecks}
    # pipeline itself is 100% and transform is 70%; both exceed 30%
    assert "transform" in names
    assert "pipeline" in names


def test_render_timeline_produces_multiline_output():
    spans = [
        _span("1", "pipeline", None, 0, 1000),
        _span("2", "extract", "1", 0, 300),
        _span("3", "transform", "1", 300, 700),
    ]
    out = render_timeline(spans, width=80, ascii_only=True)
    assert "pipeline" in out
    assert "extract" in out
    assert "transform" in out
    # ASCII fallback should use = not unicode
    assert "=" in out
    assert "█" not in out


def test_render_timeline_empty_is_safe():
    assert "No spans" in render_timeline([])


# ---------------------------------------------------------------------------
# replay — request building
# ---------------------------------------------------------------------------


def test_build_replay_request_inherits_agent_and_data():
    original = {
        "execution_id": "exec_old",
        "agent_name": "my_agent",
        "task": "analyze",
        "data": {"foo": "bar"},
    }
    req = _build_replay_request(original, overrides=None, timeout=120)
    assert req["agent_name"] == "my_agent"
    assert req["task"] == "analyze"
    assert req["data"] == {"foo": "bar"}
    assert req["execution_source"] == "replay"
    assert req["source_metadata"]["replay_of"] == "exec_old"
    assert req["timeout_seconds"] == 120


def test_build_replay_request_inherits_workflow():
    original = {
        "execution_id": "exec_old",
        "workflow_name": "my_workflow",
        "data": {"x": 1},
    }
    req = _build_replay_request(original, overrides=None, timeout=60)
    assert req["workflow_name"] == "my_workflow"
    assert "agent_name" not in req


def test_build_replay_request_applies_overrides():
    original = {
        "execution_id": "exec_old",
        "agent_name": "orig_agent",
        "data": {"a": 1},
    }
    req = _build_replay_request(original, overrides='{"task": "validate"}', timeout=60)
    assert req["task"] == "validate"
    assert req["agent_name"] == "orig_agent"  # non-overridden fields preserved


def test_build_replay_request_rejects_malformed_override():
    original = {"execution_id": "e", "agent_name": "a", "data": {}}
    with pytest.raises(Exception):
        _build_replay_request(original, overrides="not json", timeout=60)


# ---------------------------------------------------------------------------
# diff — summary computation
# ---------------------------------------------------------------------------


def _bundle(execution_id, status="completed", duration=1000, cost=0.01, result="hello",
            spans=None, decisions=None):
    return {
        "execution": {
            "execution_id": execution_id,
            "status": status,
            "duration_ms": duration,
            "cost_usd": cost,
            "result": result,
        },
        "spans": spans or [],
        "decisions": decisions or [],
    }


def test_delta_tolerates_numeric_strings():
    """Regression: diff crashed with 'unsupported operand for -: str and str'
    when the API returned numeric fields as strings."""
    from daita_cli.commands.diff import _delta

    d = _delta("1000", "500")
    assert d is not None
    assert d["delta"] == -500
    assert d["pct"] == -50.0


def test_delta_returns_none_for_non_numeric():
    from daita_cli.commands.diff import _delta

    assert _delta("not a number", "5") is None
    assert _delta(None, 5) is None
    assert _delta(True, False) is None  # bools should not masquerade as ints


def test_diff_decisions_uses_span_id_fallback_for_missing_top_level_id():
    """DecisionEvent has no `id` field — match on data.span_id instead."""
    from daita_cli.commands.diff import _diff_decisions

    a = [{"eventType": "decision_completed", "data": {"span_id": "sp1"}},
         {"eventType": "decision_completed", "data": {"span_id": "sp2"}}]
    b = [{"eventType": "decision_completed", "data": {"span_id": "sp1"}},
         {"eventType": "decision_completed", "data": {"span_id": "sp3"}}]
    result = _diff_decisions(a, b)
    assert result["shared"] == 1
    assert result["only_in_a"] == 1
    assert result["only_in_b"] == 1


def test_diff_decisions_composite_key_when_no_ids():
    """When decisions have no IDs at all, fall back to (timestamp, decisionPoint)."""
    from daita_cli.commands.diff import _diff_decisions

    a = [{"timestamp": "2026-01-01T00:00:00", "decisionPoint": "route"}]
    b = [{"timestamp": "2026-01-01T00:00:00", "decisionPoint": "route"}]
    result = _diff_decisions(a, b)
    assert result["shared"] == 1
    assert result["only_in_a"] == 0


def test_render_diff_text_distinguishes_empty_from_identical_decisions():
    """Regression: users couldn't tell '0 differed' from 'no decisions'."""
    from daita_cli.commands.diff import render_diff_text

    empty = build_summary(_bundle("a"), _bundle("b"))
    empty_out = render_diff_text(empty)
    assert "none recorded" in empty_out.lower()


def test_build_summary_pulls_cost_from_trace_when_missing_on_execution():
    """Regression: cost/tokens live on the trace record in this backend. diff
    must fall through from execution → trace rather than leaving metrics blank."""
    # Execution payload has no cost/tokens (matches real ExecutionResponse shape).
    # Trace payload does (matches real trace payload shown by user).
    bundle_a = {
        "execution": {"id": "exec_a", "status": "success", "duration_ms": 5000},
        "trace": {
            "id": "exec_a",
            "cost": 0.05,
            "inputTokens": 1000,
            "outputTokens": 200,
            "totalTokens": 1200,
        },
        "spans": [],
        "decisions": [],
    }
    bundle_b = {
        "execution": {"id": "exec_b", "status": "success", "duration_ms": 3000},
        "trace": {
            "id": "exec_b",
            "cost": 0.03,
            "inputTokens": 800,
            "outputTokens": 150,
        },
        "spans": [],
        "decisions": [],
    }
    s = build_summary(bundle_a, bundle_b)
    assert s["cost_usd"] is not None and round(s["cost_usd"]["delta"], 4) == -0.02
    assert s["tokens_in"]["delta"] == -200
    assert s["tokens_out"]["delta"] == -50
    assert s["duration_ms"]["delta"] == -2000  # from execution, which takes precedence


def test_render_diff_text_cost_focus_shows_duration():
    """Regression: duration was only rendered on --focus all."""
    from daita_cli.commands.diff import render_diff_text

    bundle_a = {
        "execution": {"id": "a", "status": "success", "duration_ms": 1000},
        "trace": {"cost": 0.02},
        "spans": [], "decisions": [],
    }
    bundle_b = {
        "execution": {"id": "b", "status": "success", "duration_ms": 500},
        "trace": {"cost": 0.01},
        "spans": [], "decisions": [],
    }
    s = build_summary(bundle_a, bundle_b)
    out = render_diff_text(s, focus="cost")
    assert "Duration" in out
    assert "Cost" in out


def test_render_diff_text_cost_focus_explains_missing_metrics():
    """When cost/tokens are absent, say so instead of printing nothing."""
    from daita_cli.commands.diff import render_diff_text

    bundle_a = {"execution": {"id": "a", "status": "success"}, "trace": {}, "spans": [], "decisions": []}
    bundle_b = {"execution": {"id": "b", "status": "success"}, "trace": {}, "spans": [], "decisions": []}
    s = build_summary(bundle_a, bundle_b)
    out = render_diff_text(s, focus="cost")
    assert "not reported" in out.lower()


def test_build_summary_handles_camelcase_execution_payload():
    """Regression: execution payloads use camelCase (inputTokens, totalTokens,
    cost, duration). Earlier code looked for snake_case and silently returned
    None for every metric."""
    bundle_a = {
        "execution": {
            "id": "exec_a",
            "status": "completed",
            "duration": 5000,       # not duration_ms
            "cost": 0.05,           # not cost_usd
            "inputTokens": 1000,
            "outputTokens": 200,
            "result": "hello",
        },
        "spans": [],
        "decisions": [],
    }
    bundle_b = {
        "execution": {
            "id": "exec_b",
            "status": "completed",
            "duration": 3000,
            "cost": 0.03,
            "inputTokens": 800,
            "outputTokens": 150,
            "result": "hi",
        },
        "spans": [],
        "decisions": [],
    }
    summary = build_summary(bundle_a, bundle_b)
    assert summary["a"] == "exec_a"
    assert summary["b"] == "exec_b"
    assert summary["duration_ms"]["delta"] == -2000
    assert round(summary["cost_usd"]["delta"], 4) == -0.02
    assert summary["tokens_in"]["delta"] == -200
    assert summary["tokens_out"]["delta"] == -50
    assert summary["output"]["changed"] is True


def test_build_summary_detects_duration_delta():
    a = _bundle("a", duration=1000)
    b = _bundle("b", duration=500)
    s = build_summary(a, b)
    assert s["duration_ms"]["delta"] == -500
    assert s["duration_ms"]["pct"] == -50.0


def test_build_summary_detects_identical_output():
    a = _bundle("a", result="same")
    b = _bundle("b", result="same")
    assert build_summary(a, b)["output"]["changed"] is False


def test_build_summary_flags_status_divergence():
    a = _bundle("a", status="completed")
    b = _bundle("b", status="failed")
    s = build_summary(a, b)
    assert s["status"]["a"] != s["status"]["b"]


def test_build_summary_sorts_spans_by_delta():
    a = _bundle("a", spans=[
        _span("1", "fast", None, 0, 100),
        _span("2", "slow", None, 100, 1000),
    ])
    b = _bundle("b", spans=[
        _span("3", "fast", None, 0, 110),
        _span("4", "slow", None, 110, 500),  # big delta
    ])
    s = build_summary(a, b)
    # Biggest mover first
    assert s["spans"][0]["name"] == "slow"
    assert s["spans"][0]["delta_ms"] == -500


def test_render_diff_text_includes_headline_fields():
    s = build_summary(_bundle("a", duration=1000), _bundle("b", duration=500))
    out = render_diff_text(s)
    assert "a" in out and "b" in out
    assert "Duration" in out


# ---------------------------------------------------------------------------
# diff — integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_diff_fetches_both_bundles(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/executions/exec_a").mock(
            return_value=httpx.Response(200, json={
                "execution_id": "exec_a", "status": "completed",
                "duration_ms": 1000, "cost_usd": 0.02, "result": "A",
                "trace_id": "tr_a",
            })
        )
        mock.get("/api/v1/executions/exec_b").mock(
            return_value=httpx.Response(200, json={
                "execution_id": "exec_b", "status": "completed",
                "duration_ms": 500, "cost_usd": 0.01, "result": "B",
                "trace_id": "tr_b",
            })
        )
        # Trace endpoints succeed with empty data
        mock.get("/api/v1/traces/traces/tr_a/spans").mock(
            return_value=httpx.Response(200, json={"spans": []})
        )
        mock.get("/api/v1/traces/traces/tr_a/decisions").mock(
            return_value=httpx.Response(200, json={"decisions": []})
        )
        mock.get("/api/v1/traces/traces/tr_b/spans").mock(
            return_value=httpx.Response(200, json={"spans": []})
        )
        mock.get("/api/v1/traces/traces/tr_b/decisions").mock(
            return_value=httpx.Response(200, json={"decisions": []})
        )

        async with DaitaAPIClient() as client:
            summary = await compute_diff(client, "exec_a", "exec_b")

    assert summary["a"] == "exec_a"
    assert summary["b"] == "exec_b"
    assert summary["duration_ms"]["delta"] == -500
    assert summary["output"]["changed"] is True


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_python_version_passes():
    result = await check_python_version()
    assert result.level == Level.OK
    assert result.category == "env"


@pytest.mark.asyncio
async def test_check_api_key_reports_missing(monkeypatch):
    monkeypatch.delenv("DAITA_API_KEY", raising=False)
    result = await check_api_key()
    assert result.level == Level.ERROR
    assert result.fix is not None
    assert "sk" in result.fix.lower() or "daita" in result.fix.lower() or "DAITA_API_KEY" in result.fix


@pytest.mark.asyncio
async def test_check_api_key_warns_on_malformed(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "weird")
    result = await check_api_key()
    assert result.level == Level.WARN


@pytest.mark.asyncio
async def test_check_api_key_ok_on_sk_prefix(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "sk-" + "x" * 40)
    result = await check_api_key()
    assert result.level == Level.OK


@pytest.mark.asyncio
async def test_run_doctor_env_only_returns_env_checks(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "sk-" + "x" * 40)
    results = await run_doctor(env=True, platform=False)
    categories = {r.category for r in results}
    assert categories == {"env"}
    assert len(results) >= 3  # python, cli, api_key, (framework maybe)


def test_check_result_serializes_level_as_string():
    from daita_cli.commands.doctor import CheckResult

    r = CheckResult(id="x", category="env", label="l", level=Level.OK, message="ok")
    d = r.as_dict()
    assert d["level"] == "ok"  # string, not enum
    assert isinstance(json.dumps(d), str)


# ---------------------------------------------------------------------------
# MCP tool exposure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_mcp_tools_registered():
    from daita_cli.mcp_server import _REGISTRY

    for name in ("replay_execution", "diff_executions", "doctor", "get_trace_timeline"):
        assert name in _REGISTRY, f"{name} missing from MCP registry"


def test_pick_returns_first_present_key():
    from daita_cli.command_helpers import pick

    item = {"id": "abc", "name": "x"}
    assert pick(item, "trace_id", "id") == "abc"
    assert pick(item, "missing", "name") == "x"


def test_pick_skips_none_and_empty():
    from daita_cli.command_helpers import pick

    item = {"a": None, "b": "", "c": "hit"}
    assert pick(item, "a", "b", "c") == "hit"
    assert pick(item, "missing", default="fallback") == "fallback"


def test_normalize_rows_projects_camelcase_api_payload():
    """Regression: `daita traces list` rendered empty columns because the API
    returns camelCase keys. normalize_rows must project them onto the display schema."""
    from daita_cli.command_helpers import normalize_rows

    # Shape mirrors the real API response reported by the user
    api_items = [{
        "id": "652941ec-d1f0-4ca6-b510-1c3352885362",
        "name": "memory_tester",
        "status": "completed",
        "startTime": "2026-04-18T16:14:20+00:00",
        "duration": 81339,
        "cost": 0.239166,
    }]
    schema = {
        "trace_id": ("id", "trace_id"),
        "name": ("name",),
        "status": ("status",),
        "started_at": ("startTime", "started_at"),
        "duration_ms": ("duration", "duration_ms"),
        "cost": ("cost",),
    }
    rows = normalize_rows(api_items, schema)
    assert rows[0]["trace_id"] == "652941ec-d1f0-4ca6-b510-1c3352885362"
    assert rows[0]["name"] == "memory_tester"
    assert rows[0]["started_at"] == "2026-04-18T16:14:20+00:00"
    assert rows[0]["duration_ms"] == 81339


def test_sort_newest_first_orders_by_start_time_descending():
    from daita_cli.commands.executions import _sort_newest_first

    items = [
        {"id": "old", "startTime": "2025-01-01T00:00:00Z"},
        {"id": "new", "startTime": "2026-04-18T00:00:00Z"},
        {"id": "mid", "startTime": "2026-01-15T00:00:00Z"},
    ]
    ordered = _sort_newest_first(items)
    assert [it["id"] for it in ordered] == ["new", "mid", "old"]


def test_sort_newest_first_missing_timestamps_fall_to_bottom():
    from daita_cli.commands.executions import _sort_newest_first

    items = [
        {"id": "no_ts"},
        {"id": "has_ts", "startTime": "2026-01-01T00:00:00Z"},
    ]
    ordered = _sort_newest_first(items)
    assert ordered[0]["id"] == "has_ts"


def test_normalize_rows_handles_snake_case_fallback():
    """Same schema should also work when the API emits snake_case."""
    from daita_cli.command_helpers import normalize_rows

    api_items = [{"trace_id": "t1", "started_at": "2026-01-01"}]
    schema = {
        "trace_id": ("id", "trace_id"),
        "started_at": ("startTime", "started_at"),
    }
    rows = normalize_rows(api_items, schema)
    assert rows[0]["trace_id"] == "t1"
    assert rows[0]["started_at"] == "2026-01-01"


@pytest.mark.asyncio
async def test_spinner_is_noop_in_non_tty():
    """Critical: spinner must not emit anything when stderr isn't a TTY (tests, CI, pipes)."""
    import io
    import sys as _sys
    from daita_cli.commands._spinner import spinner

    captured = io.StringIO()
    old_stderr = _sys.stderr
    _sys.stderr = captured
    try:
        async with spinner("should not appear"):
            await asyncio.sleep(0.15)
    finally:
        _sys.stderr = old_stderr
    assert captured.getvalue() == ""


@pytest.mark.asyncio
async def test_spinner_disabled_by_env(monkeypatch):
    monkeypatch.setenv("DAITA_NO_SPINNER", "1")
    from daita_cli.commands._spinner import _enabled
    assert _enabled() is False


@pytest.mark.asyncio
async def test_spinner_disabled_in_json_formatter():
    from daita_cli.commands._spinner import _enabled
    from daita_cli.output import OutputFormatter

    fmt = OutputFormatter(mode="json")
    assert _enabled(fmt) is False


@pytest.mark.asyncio
async def test_doctor_mcp_tool_runs_without_client(monkeypatch):
    """The doctor MCP tool is marked needs_client=False and should run without an API key."""
    from daita_cli.mcp_server import call_tool

    monkeypatch.delenv("DAITA_API_KEY", raising=False)
    # Platform checks will fail (no key), but env checks should still run.
    result = await call_tool("doctor", {"platform": False})
    data = json.loads(result[0].text)
    assert "results" in data
    assert "counts" in data
    assert any(r["category"] == "env" for r in data["results"])
