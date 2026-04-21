"""
Shared execution-polling primitive.

Used by `daita run`, `daita replay`, and the `run_agent` / `replay_execution`
MCP tools. Adaptive backoff keeps fast runs snappy and long runs cheap.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from daita_cli.api_client import DaitaAPIClient

TERMINAL_OK = {"completed", "success"}
TERMINAL_FAIL = {"failed", "error"}
TERMINAL_CANCELLED = {"cancelled"}
TERMINAL_STATUSES = TERMINAL_OK | TERMINAL_FAIL | TERMINAL_CANCELLED

StatusHook = Callable[[dict, float], Awaitable[None]] | None


async def poll_until_terminal(
    client: DaitaAPIClient,
    status_url: str,
    *,
    timeout: float = 300,
    on_poll: StatusHook = None,
    initial_delay: float = 1.0,
    max_delay: float = 5.0,
    backoff: float = 1.5,
) -> dict[str, Any]:
    """Poll `status_url` with adaptive backoff until terminal status or timeout.

    Args:
        client: active DaitaAPIClient (must already be open).
        status_url: path the client will GET each tick.
        timeout: seconds before raising TimeoutError.
        on_poll: optional async hook called with (status_data, elapsed) each tick.
        initial_delay / max_delay / backoff: backoff schedule.

    Returns:
        Final status dict (status is one of TERMINAL_STATUSES).

    Raises:
        TimeoutError: if no terminal status within `timeout`.
    """
    loop = asyncio.get_event_loop()
    start = loop.time()
    elapsed = 0.0
    delay = initial_delay

    while elapsed < timeout:
        await asyncio.sleep(min(delay, timeout - elapsed))
        elapsed = loop.time() - start
        data = await client.get(status_url)

        if on_poll is not None:
            await on_poll(data, elapsed)

        if data.get("status", "") in TERMINAL_STATUSES:
            return data

        delay = min(delay * backoff, max_delay)

    raise TimeoutError(
        f"Execution did not reach terminal state within {timeout:.0f}s (polled {status_url})"
    )
