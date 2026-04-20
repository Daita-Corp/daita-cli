"""
Daita MCP Server — tools for coding agents (Claude Code, Codex, etc.).

Start with:
    daita mcp-server

Configure in .mcp.json:
    {
      "mcpServers": {
        "daita": {
          "command": "daita",
          "args": ["mcp-server"],
          "env": {"DAITA_API_KEY": "sk-..."}
        }
      }
    }

Design:
- Tools register via the @tool decorator so schema + handler live together.
- Errors propagate as exceptions; the MCP SDK wraps them as isError results.
- run_agent streams progress notifications while polling with backoff.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from daita_cli.api_client import DaitaAPIClient
from daita_cli.output import OutputFormatter

app = Server("daita-platform")

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

Handler = Callable[..., Awaitable[Any]]


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict
    handler: Handler
    needs_client: bool = True
    needs_framework: bool = False


_REGISTRY: dict[str, ToolDef] = {}


def tool(
    name: str,
    description: str,
    input_schema: dict,
    *,
    needs_client: bool = True,
    needs_framework: bool = False,
) -> Callable[[Handler], Handler]:
    """Register an MCP tool. Schema + handler colocated.

    needs_client:    wraps the handler with a DaitaAPIClient (default True).
    needs_framework: requires daita-agents to be importable. Raises a clear
                     error at call time if it isn't.
    """

    def decorator(fn: Handler) -> Handler:
        if name in _REGISTRY:
            raise RuntimeError(f"Duplicate MCP tool registration: {name}")
        _REGISTRY[name] = ToolDef(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=fn,
            needs_client=needs_client,
            needs_framework=needs_framework,
        )
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _framework_available() -> bool:
    try:
        import daita.agents  # noqa: F401
    except ImportError:
        return False
    return True


def _progress_token() -> str | int | None:
    """Return the caller's progress token, if they requested progress updates."""
    try:
        ctx = app.request_context
    except LookupError:
        return None
    if ctx.meta is None:
        return None
    return getattr(ctx.meta, "progressToken", None)


async def _emit_progress(
    progress_token: str | int | None,
    progress: float,
    total: float,
    message: str,
) -> None:
    if progress_token is None:
        return
    try:
        session = app.request_context.session
    except LookupError:
        return
    try:
        await session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
        )
    except Exception:
        # Progress notifications are best-effort; never fail the tool over one.
        pass


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@tool(
    name="list_agents",
    description="List agents. Filters: agent_type (agent|workflow), status_filter (active|inactive), page, per_page.",
    input_schema={
        "type": "object",
        "properties": {
            "agent_type": {"type": "string", "enum": ["agent", "workflow"]},
            "status_filter": {"type": "string", "enum": ["active", "inactive"]},
            "page": {"type": "integer", "default": 1},
            "per_page": {"type": "integer", "default": 20},
        },
    },
)
async def list_agents(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    params = {
        k: args[k]
        for k in ("agent_type", "status_filter", "page", "per_page")
        if k in args
    }
    return _ok(await client.get("/api/v1/agents/agents", params=params or None))


@tool(
    name="get_agent",
    description="Get details for a specific agent by ID.",
    input_schema={
        "type": "object",
        "properties": {"agent_id": {"type": "string"}},
        "required": ["agent_id"],
    },
)
async def get_agent(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get(f"/api/v1/agents/agents/{args['agent_id']}"))


@tool(
    name="list_deployed_agents",
    description="List deployed agents from the most recent deployments.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "Max agents to return",
            },
        },
    },
)
async def list_deployed_agents(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(
        await client.get(
            "/api/v1/agents/agents/deployed", params={"limit": args.get("limit", 20)}
        )
    )


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------


@tool(
    name="list_deployments",
    description="List deployments for the current API key.",
    input_schema={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 10}},
    },
)
async def list_deployments(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(
        await client.get(
            "/api/v1/deployments/api-key", params={"per_page": args.get("limit", 10)}
        )
    )


@tool(
    name="get_deployment_history",
    description="Get deployment history for a specific project.",
    input_schema={
        "type": "object",
        "properties": {
            "project": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["project"],
    },
)
async def get_deployment_history(
    client: DaitaAPIClient, args: dict
) -> list[TextContent]:
    return _ok(
        await client.get(
            f"/api/v1/deployments/history/{args['project']}",
            params={"per_page": args.get("limit", 10)},
        )
    )


@tool(
    name="delete_deployment",
    description="Delete a deployment by ID.",
    input_schema={
        "type": "object",
        "properties": {"deployment_id": {"type": "string"}},
        "required": ["deployment_id"],
    },
)
async def delete_deployment(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.delete(f"/api/v1/deployments/{args['deployment_id']}"))


# ---------------------------------------------------------------------------
# Executions
# ---------------------------------------------------------------------------


@tool(
    name="run_agent",
    description=(
        "Execute an agent or workflow and poll until complete. "
        "Returns the final result. Use timeout_seconds to control max wait. "
        "Emits MCP progress notifications while polling if the caller passes a progressToken."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_name": {"type": "string", "description": "Agent or workflow name"},
            "target_type": {
                "type": "string",
                "enum": ["agent", "workflow"],
                "default": "agent",
            },
            "data": {"type": "object", "description": "Input data"},
            "task": {"type": "string", "default": "process"},
            "timeout_seconds": {"type": "integer", "default": 300},
        },
        "required": ["target_name"],
    },
)
async def run_agent(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    from daita_cli.commands._polling import poll_until_terminal

    timeout = float(args.get("timeout_seconds", 300))
    request = {
        "data": args.get("data", {}),
        "timeout_seconds": int(timeout),
        "execution_source": "mcp",
    }
    target_type = args.get("target_type", "agent")
    if target_type == "agent":
        request["agent_name"] = args["target_name"]
        request["task"] = args.get("task", "process")
    else:
        request["workflow_name"] = args["target_name"]

    result = await client.post("/api/v1/executions/execute", json=request)
    execution_id = result["execution_id"]

    progress_token = _progress_token()
    await _emit_progress(progress_token, 0.0, timeout, f"queued: {execution_id}")

    async def _on_poll(data: dict, elapsed: float):
        await _emit_progress(
            progress_token,
            min(elapsed, timeout),
            timeout,
            f"{data.get('status') or 'polling'}: {execution_id}",
        )

    try:
        status_data = await poll_until_terminal(
            client,
            f"/api/v1/executions/{execution_id}",
            timeout=timeout,
            on_poll=_on_poll,
        )
    except TimeoutError:
        raise TimeoutError(
            f"Execution did not complete within {timeout:.0f}s. "
            f"execution_id={execution_id} — inspect with get_execution."
        )
    return _ok(status_data)


@tool(
    name="list_executions",
    description="List recent executions with optional filters.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 10},
            "status": {
                "type": "string",
                "enum": ["queued", "running", "completed", "failed", "cancelled"],
            },
            "target_type": {"type": "string", "enum": ["agent", "workflow"]},
        },
    },
)
async def list_executions(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    # Backend query param is `status_filter` (not `status`).
    params: dict = {"limit": args.get("limit", 10), "offset": 0}
    if "status" in args:
        params["status_filter"] = args["status"]
    if "target_type" in args:
        params["target_type"] = args["target_type"]
    return _ok(await client.get("/api/v1/executions/", params=params))


@tool(
    name="get_execution",
    description="Get details and result for a specific execution.",
    input_schema={
        "type": "object",
        "properties": {"execution_id": {"type": "string"}},
        "required": ["execution_id"],
    },
)
async def get_execution(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get(f"/api/v1/executions/{args['execution_id']}"))


@tool(
    name="cancel_execution",
    description="Cancel a running execution.",
    input_schema={
        "type": "object",
        "properties": {"execution_id": {"type": "string"}},
        "required": ["execution_id"],
    },
)
async def cancel_execution(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.delete(f"/api/v1/executions/{args['execution_id']}"))


@tool(
    name="get_execution_stats",
    description="Get execution statistics.",
    input_schema={"type": "object", "properties": {}},
)
async def get_execution_stats(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get("/api/v1/autonomous/stats"))


@tool(
    name="replay_execution",
    description=(
        "Re-run an execution with identical inputs (inherits agent/workflow, data, task). "
        "Never mutates the original; returns a new execution with its terminal status. "
        'Use overrides to patch fields (e.g. {"task": "validate"}). '
        "Pair with diff_executions to compare outcomes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "execution_id": {"type": "string"},
            "deployment_id": {
                "type": "string",
                "description": "Replay against a specific deployment version",
            },
            "overrides": {
                "type": "object",
                "description": "Shallow patch merged onto the replay request",
            },
            "timeout_seconds": {"type": "integer", "default": 300},
        },
        "required": ["execution_id"],
    },
)
async def replay_execution_tool(
    client: DaitaAPIClient, args: dict
) -> list[TextContent]:
    from daita_cli.commands.replay import replay_execution

    progress_token = _progress_token()
    timeout = float(args.get("timeout_seconds", 300))

    async def _hook(data: dict, elapsed: float):
        await _emit_progress(
            progress_token,
            min(elapsed, timeout),
            timeout,
            f"{data.get('status', 'polling')}: {data.get('execution_id')}",
        )

    overrides = args.get("overrides")
    overrides_json = json.dumps(overrides) if overrides else None

    final = await replay_execution(
        client,
        args["execution_id"],
        overrides=overrides_json,
        deployment_id=args.get("deployment_id"),
        timeout=int(timeout),
        on_poll=_hook,
    )
    return _ok(final)


@tool(
    name="diff_executions",
    description=(
        "Compare two executions. Returns structured deltas across status, duration, cost, "
        "tokens, output size, span timings, and decision counts. "
        "Use focus to narrow scope: all | output | spans | decisions | cost."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "execution_a": {"type": "string"},
            "execution_b": {"type": "string"},
            "focus": {
                "type": "string",
                "enum": ["all", "output", "spans", "decisions", "cost"],
                "default": "all",
            },
        },
        "required": ["execution_a", "execution_b"],
    },
)
async def diff_executions_tool(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    from daita_cli.commands.diff import compute_diff

    summary = await compute_diff(client, args["execution_a"], args["execution_b"])
    focus = args.get("focus", "all")
    if focus != "all":
        # Trim the summary down to the requested focus for cheaper LLM consumption
        keep = {"a", "b", "status"}
        if focus == "output":
            keep |= {"output"}
        elif focus == "spans":
            keep |= {"spans"}
        elif focus == "decisions":
            keep |= {"decisions"}
        elif focus == "cost":
            keep |= {"duration_ms", "cost_usd", "tokens_in", "tokens_out"}
        summary = {k: v for k, v in summary.items() if k in keep}
    return _ok(summary)


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------


@tool(
    name="list_traces",
    description="List traces with optional filters.",
    input_schema={
        "type": "object",
        "properties": {
            "per_page": {"type": "integer", "default": 10},
            "status": {"type": "string"},
            "agent_id": {"type": "string"},
        },
    },
)
async def list_traces(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    params = {k: args[k] for k in ("status", "agent_id") if k in args}
    params["per_page"] = args.get("per_page", 10)
    return _ok(await client.get("/api/v1/traces/traces", params=params))


@tool(
    name="get_trace",
    description="Get trace details.",
    input_schema={
        "type": "object",
        "properties": {"trace_id": {"type": "string"}},
        "required": ["trace_id"],
    },
)
async def get_trace(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get(f"/api/v1/traces/traces/{args['trace_id']}"))


@tool(
    name="get_trace_spans",
    description="Get span hierarchy for a trace.",
    input_schema={
        "type": "object",
        "properties": {"trace_id": {"type": "string"}},
        "required": ["trace_id"],
    },
)
async def get_trace_spans(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get(f"/api/v1/traces/traces/{args['trace_id']}/spans"))


@tool(
    name="get_trace_decisions",
    description="Get AI decision events for a trace.",
    input_schema={
        "type": "object",
        "properties": {"trace_id": {"type": "string"}},
        "required": ["trace_id"],
    },
)
async def get_trace_decisions(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get(f"/api/v1/traces/traces/{args['trace_id']}/decisions"))


@tool(
    name="get_trace_stats",
    description="Get trace statistics.",
    input_schema={
        "type": "object",
        "properties": {
            "period": {"type": "string", "enum": ["24h", "7d", "30d"], "default": "24h"}
        },
    },
)
async def get_trace_stats(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(
        await client.get(
            "/api/v1/traces/traces/stats", params={"period": args.get("period", "24h")}
        )
    )


@tool(
    name="get_trace_timeline",
    description=(
        "Return a structured span timeline for a trace, including computed bottlenecks "
        "(spans that consumed >30%% of total duration). Preferred over get_trace_spans "
        "when debugging performance — returns pre-computed signals an LLM can act on."
    ),
    input_schema={
        "type": "object",
        "properties": {"trace_id": {"type": "string"}},
        "required": ["trace_id"],
    },
)
async def get_trace_timeline(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    from daita_cli.commands._timeline import compute_bottlenecks

    raw = await client.get(f"/api/v1/traces/traces/{args['trace_id']}/spans")
    spans = raw if isinstance(raw, list) else raw.get("spans", raw.get("items", []))
    return _ok(
        {
            "trace_id": args["trace_id"],
            "spans": spans,
            "bottlenecks": compute_bottlenecks(spans),
            "count": len(spans),
        }
    )


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


@tool(
    name="list_schedules",
    description="List agent schedules.",
    input_schema={"type": "object", "properties": {}},
)
async def list_schedules(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get("/api/v1/schedules/"))


@tool(
    name="get_schedule",
    description="Get schedule details.",
    input_schema={
        "type": "object",
        "properties": {"schedule_id": {"type": "string"}},
        "required": ["schedule_id"],
    },
)
async def get_schedule(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get(f"/api/v1/schedules/{args['schedule_id']}"))


@tool(
    name="pause_schedule",
    description="Pause a schedule.",
    input_schema={
        "type": "object",
        "properties": {"schedule_id": {"type": "string"}},
        "required": ["schedule_id"],
    },
)
async def pause_schedule(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(
        await client.patch(
            f"/api/v1/schedules/{args['schedule_id']}", json={"enabled": False}
        )
    )


@tool(
    name="resume_schedule",
    description="Resume a paused schedule.",
    input_schema={
        "type": "object",
        "properties": {"schedule_id": {"type": "string"}},
        "required": ["schedule_id"],
    },
)
async def resume_schedule(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(
        await client.patch(
            f"/api/v1/schedules/{args['schedule_id']}", json={"enabled": True}
        )
    )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


@tool(
    name="get_memory_status",
    description="Get memory system status. project is required.",
    input_schema={
        "type": "object",
        "properties": {"project": {"type": "string"}},
        "required": ["project"],
    },
)
async def get_memory_status(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(
        await client.get("/api/v1/memory/status", params={"project": args["project"]})
    )


@tool(
    name="get_workspace_memory",
    description="Get memory contents for a workspace. project is required.",
    input_schema={
        "type": "object",
        "properties": {
            "workspace": {"type": "string"},
            "limit": {"type": "integer", "default": 50},
            "project": {"type": "string"},
        },
        "required": ["workspace", "project"],
    },
)
async def get_workspace_memory(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    params = {"limit": args.get("limit", 50), "project": args["project"]}
    return _ok(
        await client.get(
            f"/api/v1/memory/workspaces/{args['workspace']}", params=params
        )
    )


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


@tool(
    name="list_secrets",
    description="List stored secret key names (values are never returned).",
    input_schema={"type": "object", "properties": {}},
)
async def list_secrets(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get("/api/v1/secrets"))


@tool(
    name="set_secret",
    description="Store or update an encrypted secret.",
    input_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["key", "value"],
    },
)
async def set_secret(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(
        await client.post(
            "/api/v1/secrets", json={"key": args["key"], "value": args["value"]}
        )
    )


@tool(
    name="delete_secret",
    description="Delete a stored secret by key name.",
    input_schema={
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    },
)
async def delete_secret(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.delete(f"/api/v1/secrets/{args['key']}"))


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


@tool(
    name="list_webhooks",
    description="List webhook URLs for the organization.",
    input_schema={"type": "object", "properties": {}},
)
async def list_webhooks(client: DaitaAPIClient, args: dict) -> list[TextContent]:
    return _ok(await client.get("/api/v1/webhooks/list"))


# ---------------------------------------------------------------------------
# Local dev tools (no API key required)
# ---------------------------------------------------------------------------


@tool(
    name="init_project",
    description="Scaffold a new Daita project in the current directory.",
    input_schema={
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "project_type": {
                "type": "string",
                "enum": ["basic", "analysis", "pipeline"],
                "default": "basic",
            },
        },
    },
    needs_client=False,
)
async def init_project(args: dict) -> list[TextContent]:
    from daita_cli.commands.init import _init

    fmt = OutputFormatter(mode="json")
    await _init(
        project_name=args.get("project_name"),
        project_type=args.get("project_type", "basic"),
        force=False,
        formatter=fmt,
    )
    return _ok(
        {
            "status": "ok",
            "message": f"Project '{args.get('project_name', 'daita_project')}' initialized.",
        }
    )


@tool(
    name="create_agent",
    description="Add a new agent to the current project from template.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    needs_client=False,
)
async def create_agent(args: dict) -> list[TextContent]:
    from daita_cli.commands.create import _create_component

    fmt = OutputFormatter(mode="json")
    _create_component(template="agent", name=args["name"], formatter=fmt)
    return _ok({"status": "ok", "message": f"Agent '{args['name']}' created."})


@tool(
    name="create_workflow",
    description="Add a new workflow to the current project from template.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    needs_client=False,
)
async def create_workflow(args: dict) -> list[TextContent]:
    from daita_cli.commands.create import _create_component

    fmt = OutputFormatter(mode="json")
    _create_component(template="workflow", name=args["name"], formatter=fmt)
    return _ok({"status": "ok", "message": f"Workflow '{args['name']}' created."})


@tool(
    name="create_skill",
    description=(
        "Add a new skill to the current project from template. Skills bundle "
        "instructions + tools that attach to any agent via agent.add_skill()."
    ),
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    needs_client=False,
)
async def create_skill(args: dict) -> list[TextContent]:
    from daita_cli.commands.create import _create_component

    fmt = OutputFormatter(mode="json")
    _create_component(template="skill", name=args["name"], formatter=fmt)
    return _ok({"status": "ok", "message": f"Skill '{args['name']}' created."})


@tool(
    name="doctor",
    description=(
        "Run daita-cli health checks (environment + platform connectivity). "
        "Returns structured results with per-check IDs and copy-pasteable fixes. "
        "Always the right first step when something isn't working."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "env": {
                "type": "boolean",
                "default": True,
                "description": "Run environment checks",
            },
            "platform": {
                "type": "boolean",
                "default": True,
                "description": "Run platform/API checks",
            },
            "timeout": {
                "type": "number",
                "default": 5.0,
                "description": "Per-check timeout in seconds",
            },
        },
    },
    needs_client=False,
)
async def doctor_tool(args: dict) -> list[TextContent]:
    from daita_cli.commands.doctor import run_doctor, _count, Level

    results = await run_doctor(
        env=args.get("env", True),
        platform=args.get("platform", True),
        per_check_timeout=float(args.get("timeout", 5.0)),
    )
    counts = {lvl.value: n for lvl, n in _count(results).items()}
    return _ok(
        {
            "results": [r.as_dict() for r in results],
            "counts": counts,
            "has_errors": counts.get(Level.ERROR.value, 0) > 0,
        }
    )


@tool(
    name="test_agent",
    description=(
        "Run an agent or workflow locally and return results including cost, duration, output. "
        "Requires daita-agents to be installed (the loaded user code imports it)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Agent/workflow name (optional)",
            },
        },
    },
    needs_client=False,
    needs_framework=True,
)
async def test_agent(args: dict) -> list[TextContent]:
    from daita_cli.commands.test import _run_tests

    fmt = OutputFormatter(mode="json")
    await _run_tests(
        target=args.get("target"),
        data_file=None,
        watch=False,
        formatter=fmt,
    )
    return _ok({"status": "ok", "message": "Test run completed."})


# ---------------------------------------------------------------------------
# MCP dispatch
# ---------------------------------------------------------------------------


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name=t.name, description=t.description, inputSchema=t.input_schema)
        for t in _REGISTRY.values()
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch a tool call. Errors raise — the MCP SDK wraps them as isError results."""
    tool_def = _REGISTRY.get(name)
    if tool_def is None:
        raise ValueError(f"Unknown tool: {name}")

    if tool_def.needs_framework and not _framework_available():
        raise RuntimeError(
            f"{name} requires daita-agents. Install it with: pip install daita-agents"
        )

    if tool_def.needs_client:
        async with DaitaAPIClient() as client:
            return await tool_def.handler(client, arguments)
    return await tool_def.handler(arguments)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


async def run_server():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
