"""
Daita MCP Server — ~30 tools for coding agents (Claude Code, Codex, etc.).

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
"""

import asyncio
import json
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from daita_cli.api_client import DaitaAPIClient, APIError, AuthError
from daita_cli.output import OutputFormatter

app = Server("daita-platform")

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_TOOLS: list[Tool] = [
    # Agents
    Tool(
        name="list_agents",
        description="List agents. Filters: agent_type (agent|workflow), status_filter (active|inactive), page, per_page.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_type": {"type": "string", "enum": ["agent", "workflow"]},
                "status_filter": {"type": "string", "enum": ["active", "inactive"]},
                "page": {"type": "integer", "default": 1},
                "per_page": {"type": "integer", "default": 20},
            },
        },
    ),
    Tool(
        name="get_agent",
        description="Get details for a specific agent by ID.",
        inputSchema={
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        },
    ),
    Tool(
        name="list_deployed_agents",
        description="List deployed agents with their configuration.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # Deployments
    Tool(
        name="list_deployments",
        description="List deployments for the current API key.",
        inputSchema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        },
    ),
    Tool(
        name="get_deployment_history",
        description="Get deployment history for a specific project.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["project"],
        },
    ),
    Tool(
        name="rollback_deployment",
        description="Rollback to a previous deployment by deployment ID.",
        inputSchema={
            "type": "object",
            "properties": {"deployment_id": {"type": "string"}},
            "required": ["deployment_id"],
        },
    ),
    Tool(
        name="delete_deployment",
        description="Delete a deployment by ID.",
        inputSchema={
            "type": "object",
            "properties": {"deployment_id": {"type": "string"}},
            "required": ["deployment_id"],
        },
    ),
    # Executions
    Tool(
        name="run_agent",
        description=(
            "Execute an agent or workflow and poll until complete. "
            "Returns the final result. Use timeout_seconds to control max wait."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Agent or workflow name"},
                "target_type": {"type": "string", "enum": ["agent", "workflow"], "default": "agent"},
                "data": {"type": "object", "description": "Input data"},
                "task": {"type": "string", "default": "process"},
                "timeout_seconds": {"type": "integer", "default": 300},
            },
            "required": ["target_name"],
        },
    ),
    Tool(
        name="list_executions",
        description="List recent executions with optional filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
                "status": {"type": "string", "enum": ["queued", "running", "completed", "failed", "cancelled"]},
                "target_type": {"type": "string", "enum": ["agent", "workflow"]},
            },
        },
    ),
    Tool(
        name="get_execution",
        description="Get details and result for a specific execution.",
        inputSchema={
            "type": "object",
            "properties": {"execution_id": {"type": "string"}},
            "required": ["execution_id"],
        },
    ),
    Tool(
        name="cancel_execution",
        description="Cancel a running execution.",
        inputSchema={
            "type": "object",
            "properties": {"execution_id": {"type": "string"}},
            "required": ["execution_id"],
        },
    ),
    Tool(
        name="get_execution_stats",
        description="Get execution statistics.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # Traces
    Tool(
        name="list_traces",
        description="List traces with optional filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "per_page": {"type": "integer", "default": 10},
                "status": {"type": "string"},
                "agent_id": {"type": "string"},
            },
        },
    ),
    Tool(
        name="get_trace",
        description="Get trace details.",
        inputSchema={
            "type": "object",
            "properties": {"trace_id": {"type": "string"}},
            "required": ["trace_id"],
        },
    ),
    Tool(
        name="get_trace_spans",
        description="Get span hierarchy for a trace.",
        inputSchema={
            "type": "object",
            "properties": {"trace_id": {"type": "string"}},
            "required": ["trace_id"],
        },
    ),
    Tool(
        name="get_trace_decisions",
        description="Get AI decision events for a trace.",
        inputSchema={
            "type": "object",
            "properties": {"trace_id": {"type": "string"}},
            "required": ["trace_id"],
        },
    ),
    Tool(
        name="get_trace_stats",
        description="Get trace statistics.",
        inputSchema={
            "type": "object",
            "properties": {"period": {"type": "string", "enum": ["24h", "7d", "30d"], "default": "24h"}},
        },
    ),
    # Schedules
    Tool(
        name="list_schedules",
        description="List agent schedules.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_schedule",
        description="Get schedule details.",
        inputSchema={
            "type": "object",
            "properties": {"schedule_id": {"type": "string"}},
            "required": ["schedule_id"],
        },
    ),
    Tool(
        name="pause_schedule",
        description="Pause a schedule.",
        inputSchema={
            "type": "object",
            "properties": {"schedule_id": {"type": "string"}},
            "required": ["schedule_id"],
        },
    ),
    Tool(
        name="resume_schedule",
        description="Resume a paused schedule.",
        inputSchema={
            "type": "object",
            "properties": {"schedule_id": {"type": "string"}},
            "required": ["schedule_id"],
        },
    ),
    # Memory
    Tool(
        name="get_memory_status",
        description="Get memory system status. project is required.",
        inputSchema={
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": ["project"],
        },
    ),
    Tool(
        name="get_workspace_memory",
        description="Get memory contents for a workspace. project is required.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "project": {"type": "string"},
            },
            "required": ["workspace", "project"],
        },
    ),
    # Secrets
    Tool(
        name="list_secrets",
        description="List stored secret key names (values are never returned).",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="set_secret",
        description="Store or update an encrypted secret.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    ),
    Tool(
        name="delete_secret",
        description="Delete a stored secret by key name.",
        inputSchema={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    ),
    # Webhooks
    Tool(
        name="list_webhooks",
        description="List webhook URLs for the organization.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # Conversations
    Tool(
        name="list_conversations",
        description="List conversations. user_id scopes conversations (default: 'cli').",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "user_id": {"type": "string", "default": "cli"},
            },
        },
    ),
    Tool(
        name="get_conversation",
        description="Get conversation details.",
        inputSchema={
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "user_id": {"type": "string", "default": "cli"},
            },
            "required": ["conversation_id"],
        },
    ),
    Tool(
        name="create_conversation",
        description="Create a new conversation.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "title": {"type": "string"},
                "user_id": {"type": "string", "default": "cli"},
            },
            "required": ["agent_name"],
        },
    ),
    Tool(
        name="delete_conversation",
        description="Delete a conversation.",
        inputSchema={
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "user_id": {"type": "string", "default": "cli"},
            },
            "required": ["conversation_id"],
        },
    ),
    # Local dev (require daita-agents)
    Tool(
        name="init_project",
        description=(
            "Scaffold a new Daita project in the current directory. "
            "Requires daita-agents to be installed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "project_type": {"type": "string", "enum": ["basic", "analysis", "pipeline"], "default": "basic"},
            },
        },
    ),
    Tool(
        name="create_agent",
        description=(
            "Add a new agent to the current project from template. "
            "Requires daita-agents to be installed."
        ),
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    Tool(
        name="create_workflow",
        description=(
            "Add a new workflow to the current project from template. "
            "Requires daita-agents to be installed."
        ),
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    Tool(
        name="test_agent",
        description=(
            "Run an agent or workflow locally and return results including cost, duration, output. "
            "Requires daita-agents to be installed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Agent/workflow name (optional)"},
            },
        },
    ),
]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _ok(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _err(message: str, status_code: int = None) -> list[TextContent]:
    payload = {"error": True, "detail": message}
    if status_code is not None:
        payload["status_code"] = status_code
    return [TextContent(type="text", text=json.dumps(payload))]


def _require_framework_mcp():
    try:
        import daita.agents  # noqa
    except ImportError:
        return False
    return True


@app.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # Local dev tools (no API key needed, but need daita-agents)
    if name in ("init_project", "create_agent", "create_workflow", "test_agent"):
        return await _handle_local(name, arguments)

    try:
        async with DaitaAPIClient() as client:
            return await _dispatch(client, name, arguments)
    except AuthError as e:
        return _err(str(e), 401)
    except APIError as e:
        return _err(str(e), e.status_code)
    except Exception as e:
        return _err(str(e))


async def _handle_local(name: str, arguments: dict) -> list[TextContent]:
    fmt = OutputFormatter(mode="json")
    try:
        if name == "init_project":
            from daita_cli.commands.init import _init
            await _init(
                project_name=arguments.get("project_name"),
                project_type=arguments.get("project_type", "basic"),
                force=False,
                formatter=fmt,
            )
            return _ok({"status": "ok", "message": f"Project '{arguments.get('project_name', 'daita_project')}' initialized."})

        if name == "create_agent":
            from daita_cli.commands.create import _create_component
            _create_component(template="agent", name=arguments["name"], formatter=fmt)
            return _ok({"status": "ok", "message": f"Agent '{arguments['name']}' created."})

        if name == "create_workflow":
            from daita_cli.commands.create import _create_component
            _create_component(template="workflow", name=arguments["name"], formatter=fmt)
            return _ok({"status": "ok", "message": f"Workflow '{arguments['name']}' created."})

        if name == "test_agent":
            if not _require_framework_mcp():
                return _err("test_agent requires daita-agents. Install it with: pip install daita-agents")
            from daita_cli.commands.test import _run_tests
            await _run_tests(
                target=arguments.get("target"),
                data_file=None,
                watch=False,
                formatter=fmt,
            )
            return _ok({"status": "ok", "message": "Test run completed."})

    except Exception as e:
        return _err(str(e))

    return _err(f"Unknown local tool: {name}")


async def _dispatch(client: DaitaAPIClient, name: str, args: dict) -> list[TextContent]:
    # Agents
    if name == "list_agents":
        params = {k: args[k] for k in ("agent_type", "status_filter", "page", "per_page") if k in args}
        return _ok(await client.get("/api/v1/agents/agents", params=params or None))

    if name == "get_agent":
        return _ok(await client.get(f"/api/v1/agents/agents/{args['agent_id']}"))

    if name == "list_deployed_agents":
        return _ok(await client.get("/api/v1/agents/agents/deployed"))

    # Deployments
    if name == "list_deployments":
        return _ok(await client.get("/api/v1/deployments/api-key", params={"per_page": args.get("limit", 10)}))

    if name == "get_deployment_history":
        return _ok(await client.get(
            f"/api/v1/deployments/history/{args['project']}",
            params={"per_page": args.get("limit", 10)},
        ))

    if name == "rollback_deployment":
        return _ok(await client.post(f"/api/v1/deployments/rollback/{args['deployment_id']}"))

    if name == "delete_deployment":
        return _ok(await client.delete(f"/api/v1/deployments/{args['deployment_id']}"))

    # Executions — run_agent polls until complete
    if name == "run_agent":
        timeout = args.get("timeout_seconds", 300)
        request = {
            "data": args.get("data", {}),
            "timeout_seconds": timeout,
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

        # Poll until done
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(1)
            status_data = await client.get(f"/api/v1/executions/{execution_id}")
            status = status_data.get("status", "")
            if status in ("completed", "success", "failed", "error", "cancelled"):
                return _ok(status_data)
        return _err(f"Execution timed out after {timeout}s. execution_id={execution_id}")

    if name == "list_executions":
        params = {k: args[k] for k in ("limit", "status", "target_type") if k in args}
        return _ok(await client.get("/api/v1/autonomous/executions", params=params or None))

    if name == "get_execution":
        return _ok(await client.get(f"/api/v1/autonomous/executions/{args['execution_id']}"))

    if name == "cancel_execution":
        return _ok(await client.delete(f"/api/v1/autonomous/executions/{args['execution_id']}"))

    if name == "get_execution_stats":
        return _ok(await client.get("/api/v1/autonomous/stats"))

    # Traces
    if name == "list_traces":
        params = {k: args[k] for k in ("per_page", "status", "agent_id") if k in args}
        return _ok(await client.get("/api/v1/traces/traces", params=params or None))

    if name == "get_trace":
        return _ok(await client.get(f"/api/v1/traces/traces/{args['trace_id']}"))

    if name == "get_trace_spans":
        return _ok(await client.get(f"/api/v1/traces/traces/{args['trace_id']}/spans"))

    if name == "get_trace_decisions":
        return _ok(await client.get(f"/api/v1/traces/traces/{args['trace_id']}/decisions"))

    if name == "get_trace_stats":
        return _ok(await client.get("/api/v1/traces/traces/stats", params={"period": args.get("period", "24h")}))

    # Schedules
    if name == "list_schedules":
        return _ok(await client.get("/api/v1/schedules/"))

    if name == "get_schedule":
        return _ok(await client.get(f"/api/v1/schedules/{args['schedule_id']}"))

    if name == "pause_schedule":
        return _ok(await client.patch(f"/api/v1/schedules/{args['schedule_id']}", json={"enabled": False}))

    if name == "resume_schedule":
        return _ok(await client.patch(f"/api/v1/schedules/{args['schedule_id']}", json={"enabled": True}))

    # Memory
    if name == "get_memory_status":
        return _ok(await client.get("/api/v1/memory/status", params={"project": args["project"]}))

    if name == "get_workspace_memory":
        params = {"limit": args.get("limit", 50), "project": args["project"]}
        return _ok(await client.get(f"/api/v1/memory/workspaces/{args['workspace']}", params=params))

    # Secrets
    if name == "list_secrets":
        return _ok(await client.get("/api/v1/secrets"))

    if name == "set_secret":
        return _ok(await client.post("/api/v1/secrets", json={"key": args["key"], "value": args["value"]}))

    if name == "delete_secret":
        return _ok(await client.delete(f"/api/v1/secrets/{args['key']}"))

    # Webhooks
    if name == "list_webhooks":
        return _ok(await client.get("/api/v1/webhooks/webhooks/list"))

    # Conversations
    if name == "list_conversations":
        params = {"limit": args.get("limit", 20), "user_id": args.get("user_id", "cli")}
        if "agent_name" in args:
            params["agent_name"] = args["agent_name"]
        return _ok(await client.get("/api/v1/conversations", params=params))

    if name == "get_conversation":
        return _ok(await client.get(
            f"/api/v1/conversations/{args['conversation_id']}",
            params={"user_id": args.get("user_id", "cli")},
        ))

    if name == "create_conversation":
        payload = {"agent_name": args["agent_name"], "user_id": args.get("user_id", "cli")}
        if "title" in args:
            payload["title"] = args["title"]
        return _ok(await client.post("/api/v1/conversations", json=payload))

    if name == "delete_conversation":
        return _ok(await client.delete(
            f"/api/v1/conversations/{args['conversation_id']}",
            params={"user_id": args.get("user_id", "cli")},
        ))

    return _err(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

async def run_server():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
