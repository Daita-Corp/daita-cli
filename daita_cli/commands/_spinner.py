"""
Async spinner for long-running CLI operations.

Silently no-ops when:
- stderr is not a TTY (piped, redirected, CI),
- the caller's OutputFormatter is in JSON mode,
- the user sets DAITA_NO_SPINNER=1.

All output goes to stderr so piped stdout stays clean for JSON consumers.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager

_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_ASCII_FRAMES = ("|", "/", "-", "\\")
_TICK_INTERVAL = 0.08


def _supports_unicode() -> bool:
    lang = (os.environ.get("LANG") or "").lower()
    return "utf" in lang


def _enabled(formatter=None) -> bool:
    if os.environ.get("DAITA_NO_SPINNER"):
        return False
    if formatter is not None and getattr(formatter, "is_json", False):
        return False
    return sys.stderr.isatty()


@asynccontextmanager
async def spinner(message: str, *, formatter=None):
    """Show an animated spinner on stderr while the block runs.

    Example:
        async with spinner("Fetching…", formatter=formatter):
            data = await slow_op()
    """
    if not _enabled(formatter):
        yield
        return

    frames = _FRAMES if _supports_unicode() else _ASCII_FRAMES
    stop = asyncio.Event()

    async def _tick():
        idx = 0
        try:
            while not stop.is_set():
                sys.stderr.write(f"\r\033[K  {frames[idx % len(frames)]}  {message}")
                sys.stderr.flush()
                idx += 1
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_TICK_INTERVAL)
                except asyncio.TimeoutError:
                    pass
        finally:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

    task = asyncio.create_task(_tick())
    try:
        yield
    finally:
        stop.set()
        await asyncio.gather(task, return_exceptions=True)
