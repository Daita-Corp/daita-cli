"""Tests for DaitaAPIClient."""

import pytest
import respx
import httpx

from daita_cli.api_client import (
    DaitaAPIClient,
    AuthError,
    NotFoundError,
    ValidationError,
    ServerError,
)


@pytest.fixture
def client():
    return DaitaAPIClient(api_key="test-key", base_url="https://api.daita-tech.io")


@pytest.mark.asyncio
async def test_get_success(client):
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/agents/agents").mock(
            return_value=httpx.Response(200, json={"agents": []})
        )
        async with client:
            result = await client.get("/api/v1/agents/agents")
    assert result == {"agents": []}


@pytest.mark.asyncio
async def test_get_401_raises_auth_error(client):
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/agents/agents").mock(
            return_value=httpx.Response(401, json={"detail": "Unauthorized"})
        )
        with pytest.raises(AuthError):
            async with client:
                await client.get("/api/v1/agents/agents")


@pytest.mark.asyncio
async def test_get_404_raises_not_found(client):
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/agents/agents/missing").mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
        )
        with pytest.raises(NotFoundError):
            async with client:
                await client.get("/api/v1/agents/agents/missing")


@pytest.mark.asyncio
async def test_get_500_raises_server_error(client):
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/agents/agents").mock(
            return_value=httpx.Response(500, json={"detail": "Internal error"})
        )
        with pytest.raises(ServerError):
            async with client:
                await client.get("/api/v1/agents/agents")


@pytest.mark.asyncio
async def test_missing_api_key_raises_auth_error():
    client = DaitaAPIClient(api_key="", base_url="https://api.daita-tech.io")
    with pytest.raises(AuthError):
        async with client:
            await client.get("/api/v1/agents/agents")


@pytest.mark.asyncio
async def test_post_sends_json(client):
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        route = mock.post("/api/v1/secrets").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        async with client:
            result = await client.post(
                "/api/v1/secrets", json={"key": "K", "value": "V"}
            )
    assert result == {"status": "ok"}
    assert route.called
