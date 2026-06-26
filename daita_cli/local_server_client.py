"""Client helpers for the local Daita Agent Server."""

from __future__ import annotations

from typing import Any

import httpx


DEFAULT_LOCAL_SERVER_URL = "http://127.0.0.1:8123"


class LocalAgentServerClient:
    def __init__(self, server_url: str = DEFAULT_LOCAL_SERVER_URL, timeout: float = 30):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "LocalAgentServerClient":
        self._client = httpx.AsyncClient(base_url=self.server_url, timeout=self.timeout)
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _check_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "LocalAgentServerClient must be used as an async context manager"
            )
        return self._client

    async def _handle(self, response: httpx.Response) -> Any:
        response.raise_for_status()
        return response.json()

    async def health(self) -> Any:
        return await self._handle(await self._check_client().get("/health"))

    async def list_agents(self) -> Any:
        return await self._handle(await self._check_client().get("/agents"))

    async def get_agent(self, agent_name: str) -> Any:
        return await self._handle(
            await self._check_client().get(f"/agents/{agent_name}")
        )

    async def run_agent(
        self,
        agent_name: str,
        *,
        prompt: str,
        session_id: str | None = None,
        include_evidence: bool = True,
        include_tasks: bool = True,
        include_telemetry: bool = True,
    ) -> Any:
        payload = {
            "prompt": prompt,
            "session_id": session_id,
            "include_evidence": include_evidence,
            "include_tasks": include_tasks,
            "include_telemetry": include_telemetry,
        }
        return await self._handle(
            await self._check_client().post(f"/agents/{agent_name}/runs", json=payload)
        )

    async def list_operations(self) -> Any:
        return await self._handle(
            await self._check_client().get("/runtime/operations")
        )

    async def get_operation(self, operation_id: str) -> Any:
        return await self._handle(
            await self._check_client().get(f"/runtime/operations/{operation_id}")
        )

    async def get_operation_tasks(self, operation_id: str) -> Any:
        return await self._handle(
            await self._check_client().get(
                f"/runtime/operations/{operation_id}/tasks"
            )
        )

    async def get_operation_evidence(self, operation_id: str) -> Any:
        return await self._handle(
            await self._check_client().get(
                f"/runtime/operations/{operation_id}/evidence"
            )
        )


async def get_local_agent_server_status(
    server_url: str = DEFAULT_LOCAL_SERVER_URL,
) -> Any:
    async with LocalAgentServerClient(server_url) as client:
        return await client.health()


async def list_local_server_agents(server_url: str = DEFAULT_LOCAL_SERVER_URL) -> Any:
    async with LocalAgentServerClient(server_url) as client:
        return await client.list_agents()


async def get_local_server_agent(
    agent_name: str,
    server_url: str = DEFAULT_LOCAL_SERVER_URL,
) -> Any:
    async with LocalAgentServerClient(server_url) as client:
        return await client.get_agent(agent_name)


async def call_local_agent(
    agent_name: str,
    prompt: str,
    *,
    server_url: str = DEFAULT_LOCAL_SERVER_URL,
    session_id: str | None = None,
    include_evidence: bool = True,
    include_tasks: bool = True,
    include_telemetry: bool = True,
) -> Any:
    async with LocalAgentServerClient(server_url) as client:
        return await client.run_agent(
            agent_name,
            prompt=prompt,
            session_id=session_id,
            include_evidence=include_evidence,
            include_tasks=include_tasks,
            include_telemetry=include_telemetry,
        )


async def get_local_server_runtime_operation(
    operation_id: str,
    server_url: str = DEFAULT_LOCAL_SERVER_URL,
) -> Any:
    async with LocalAgentServerClient(server_url) as client:
        return await client.get_operation(operation_id)


async def get_local_server_operation_tasks(
    operation_id: str,
    server_url: str = DEFAULT_LOCAL_SERVER_URL,
) -> Any:
    async with LocalAgentServerClient(server_url) as client:
        return await client.get_operation_tasks(operation_id)


async def get_local_server_operation_evidence(
    operation_id: str,
    server_url: str = DEFAULT_LOCAL_SERVER_URL,
) -> Any:
    async with LocalAgentServerClient(server_url) as client:
        return await client.get_operation_evidence(operation_id)
