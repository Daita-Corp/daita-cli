"""
DaitaAPIClient — async httpx client shared by CLI commands and MCP server.
"""

import os
import httpx
from typing import Any

from daita_cli import __version__

_DEFAULT_BASE_URL = "https://api.daita-tech.io"


class APIError(Exception):
    def __init__(self, status_code: int, detail: str, raw: Any = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.raw = raw


class AuthError(APIError): ...


class NotFoundError(APIError): ...


class ValidationError(APIError): ...


class RateLimitError(APIError): ...


class ServerError(APIError): ...


def _raise_for(status: int, detail: str, raw: Any) -> None:
    if status in (401, 403):
        raise AuthError(status, detail, raw)
    if status == 404:
        raise NotFoundError(status, detail, raw)
    if status in (400, 422):
        raise ValidationError(status, detail, raw)
    if status == 429:
        raise RateLimitError(status, detail, raw)
    if status >= 500:
        raise ServerError(status, detail, raw)
    raise APIError(status, detail, raw)


class DaitaAPIClient:
    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or os.getenv("DAITA_API_KEY")
        self.base_url = (
            base_url or os.getenv("DAITA_API_ENDPOINT") or _DEFAULT_BASE_URL
        ).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict:
        if not self.api_key:
            raise AuthError(
                401, "DAITA_API_KEY is not set. Export it or pass --api-key."
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"Daita-CLI/{__version__}",
            "Content-Type": "application/json",
        }

    async def __aenter__(self) -> "DaitaAPIClient":
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _check_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "DaitaAPIClient must be used as an async context manager"
            )
        return self._client

    async def _handle(self, resp: httpx.Response) -> Any:
        if resp.is_success:
            try:
                return resp.json()
            except Exception:
                return resp.text
        try:
            body = resp.json()
            detail = body.get("detail") or body.get("message") or str(body)
        except Exception:
            detail = resp.text or f"HTTP {resp.status_code}"
        _raise_for(resp.status_code, detail, resp)

    async def get(self, path: str, params: dict = None) -> Any:
        resp = await self._check_client().get(
            path, headers=self._headers(), params=params
        )
        return await self._handle(resp)

    async def post(self, path: str, json: dict = None) -> Any:
        resp = await self._check_client().post(path, headers=self._headers(), json=json)
        return await self._handle(resp)

    async def put(self, path: str, json: dict = None) -> Any:
        resp = await self._check_client().put(path, headers=self._headers(), json=json)
        return await self._handle(resp)

    async def patch(self, path: str, json: dict = None) -> Any:
        resp = await self._check_client().patch(
            path, headers=self._headers(), json=json
        )
        return await self._handle(resp)

    async def delete(self, path: str, params: dict = None) -> Any:
        resp = await self._check_client().delete(
            path, headers=self._headers(), params=params
        )
        return await self._handle(resp)
