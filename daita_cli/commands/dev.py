"""daita dev - run a local Agent Server for a DbAgent-compatible factory."""

from __future__ import annotations

import sys

import click

from daita_cli.local_agent_server import serve_dev_server


def _runtime_store_callback(ctx, param, value):
    if value != "sqlite":
        raise click.BadParameter("Phase 0 supports only sqlite runtime stores.")
    return value


@click.command("dev")
@click.option("--agent", "agent_path", required=True, help="Python agent file path.")
@click.option("--factory", default="create_agent", show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8123, show_default=True, type=int)
@click.option(
    "--runtime-store",
    default="sqlite",
    show_default=True,
    callback=_runtime_store_callback,
)
@click.option(
    "--runtime-store-path",
    default=".daita/runtime.sqlite",
    show_default=True,
)
@click.option("--env-file", help="Optional dotenv-style file to load before import.")
@click.pass_context
def dev_command(
    ctx,
    agent_path,
    factory,
    host,
    port,
    runtime_store,
    runtime_store_path,
    env_file,
):
    """Start a local production-shaped Agent Server."""
    runtime_override_keys = set()
    store_source = ctx.get_parameter_source("runtime_store")
    path_source = ctx.get_parameter_source("runtime_store_path")
    if store_source is not None and store_source.name == "COMMANDLINE":
        runtime_override_keys.update({"runtime_store", "store"})
    if path_source is not None and path_source.name == "COMMANDLINE":
        runtime_override_keys.update({"runtime_store_path", "store_path"})
    try:
        serve_dev_server(
            agent_path=agent_path,
            factory_name=factory,
            host=host,
            port=port,
            runtime_store=runtime_store,
            runtime_store_path=runtime_store_path,
            env_file=env_file,
            runtime_override_keys=runtime_override_keys,
        )
    except KeyboardInterrupt:
        click.echo("\n  Server stopped.", err=True)
        sys.exit(130)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
