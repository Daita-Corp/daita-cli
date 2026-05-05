"""Shared cloud eval helpers for CLI and MCP callers."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from daita_cli import __version__
from daita_cli.api_client import DaitaAPIClient
from daita_cli.commands._polling import poll_until_terminal

PRODUCTION_ENVIRONMENT = "production"

PollHook = Callable[[dict, float], Awaitable[None]]


def build_eval_execute_request(
    *,
    timeout_seconds: int,
    trigger_source: str,
    source_metadata: dict[str, Any] | None = None,
    eval_suite_id: str | None = None,
    suite_name: str | None = None,
    project_name: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "environment": PRODUCTION_ENVIRONMENT,
        "timeout_seconds": timeout_seconds,
        "trigger_source": trigger_source,
        "source_metadata": source_metadata or {},
    }
    optional = {
        "eval_suite_id": eval_suite_id,
        "suite_name": suite_name,
        "project_name": project_name,
        "config_path": config_path,
    }
    request.update({key: value for key, value in optional.items() if value})
    return request


def cli_source_metadata(command: str) -> dict[str, str]:
    return {"cli_version": __version__, "command": command}


async def submit_eval_suite(
    client: DaitaAPIClient,
    request: dict[str, Any],
) -> dict[str, Any]:
    return await client.post("/api/v1/evals/runs/execute", json=request)


async def wait_for_eval_report(
    client: DaitaAPIClient,
    submitted: dict[str, Any],
    *,
    timeout_seconds: float,
    on_poll: PollHook | None = None,
) -> dict[str, Any]:
    execution_id = submitted["execution_id"]
    final_status = await poll_until_terminal(
        client,
        f"/api/v1/executions/{execution_id}",
        timeout=timeout_seconds,
        on_poll=on_poll,
    )
    if final_status.get("status") in {"failed", "error", "cancelled"}:
        detail = final_status.get("error") or f"Cloud eval {final_status.get('status')}"
        raise RuntimeError(detail)
    return await latest_eval_report(client, submitted)


async def latest_eval_report(
    client: DaitaAPIClient,
    submitted: dict[str, Any],
) -> dict[str, Any]:
    runs = await client.get(
        "/api/v1/evals/runs",
        params={
            "eval_suite_id": submitted["eval_suite_id"],
            "project_name": submitted.get("project_name"),
            "environment": PRODUCTION_ENVIRONMENT,
            "per_page": 1,
        },
    )
    items = runs.get("runs") or []
    if not items:
        raise LookupError("Cloud eval completed but no eval run was found.")
    return await client.get(f"/api/v1/evals/runs/{items[0]['eval_run_id']}/report")
