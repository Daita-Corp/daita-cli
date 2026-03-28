"""
@api_command decorator — wraps async Click commands with client injection,
OutputFormatter injection, and standardised error/exit-code handling.

Usage:
    @cli.command()
    @click.argument("name")
    @api_command
    async def my_cmd(client, formatter, name): ...
"""

import asyncio
import functools
import sys

import click

from daita_cli.api_client import AuthError, NotFoundError, APIError, DaitaAPIClient
from daita_cli.output import OutputFormatter


def api_command(f):
    """
    Decorator that:
    1. Runs the coroutine via asyncio.run()
    2. Injects `client` (DaitaAPIClient) and `formatter` (OutputFormatter) as first two args
    3. Maps exceptions to exit codes: 0=ok, 1=error, 2=auth, 130=interrupt
    """
    @functools.wraps(f)
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        obj = ctx.obj or {}
        formatter: OutputFormatter = obj.get("formatter", OutputFormatter())

        async def _run():
            async with DaitaAPIClient() as client:
                return await f(client, formatter, *args, **kwargs)

        try:
            asyncio.run(_run())
        except AuthError as e:
            formatter.error("AUTH_ERROR", str(e))
            sys.exit(2)
        except NotFoundError as e:
            formatter.error("NOT_FOUND", str(e))
            sys.exit(1)
        except APIError as e:
            formatter.error("API_ERROR", str(e), {"status_code": e.status_code})
            sys.exit(1)
        except KeyboardInterrupt:
            sys.exit(130)
        except click.ClickException:
            raise
        except Exception as e:
            formatter.error("ERROR", str(e))
            sys.exit(1)

    return wrapper
