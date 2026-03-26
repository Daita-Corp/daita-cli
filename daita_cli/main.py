"""
Daita CLI — entry point.

Usage:
    daita agents list
    daita deployments list
    daita executions list
    daita traces list
    daita schedules list
    daita operations list
    daita memory status
    daita secrets list
    daita webhooks list
    daita conversations list
    daita run <agent>
    daita status
    daita logs
    daita push               # requires daita-agents
    daita init [name]        # requires daita-agents
    daita create agent|workflow <name>  # requires daita-agents
    daita test [target]      # requires daita-agents
    daita mcp-server
"""

import click

from daita_cli import __version__
from daita_cli.output import OutputFormatter

from daita_cli.commands.agents import agents
from daita_cli.commands.deployments import deployments
from daita_cli.commands.executions import executions
from daita_cli.commands.traces import traces
from daita_cli.commands.schedules import schedules
from daita_cli.commands.operations import operations
from daita_cli.commands.memory import memory
from daita_cli.commands.secrets import secrets
from daita_cli.commands.webhooks import webhooks
from daita_cli.commands.conversations import conversations
from daita_cli.commands.run import run_command
from daita_cli.commands.status import status_command
from daita_cli.commands.logs import logs_command
from daita_cli.commands.push import push_command
from daita_cli.commands.init import init_command
from daita_cli.commands.create import create_group
from daita_cli.commands.test import test_command


@click.group()
@click.version_option(version=__version__, prog_name="daita")
@click.option("--output", "-o", type=click.Choice(["json", "text", "table"]), help="Output format")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-error output")
@click.pass_context
def cli(ctx, output, verbose, quiet):
    """Daita CLI — manage and observe your hosted AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["formatter"] = OutputFormatter(mode=output)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet


# Cloud commands (no daita-agents needed)
cli.add_command(agents)
cli.add_command(deployments)
cli.add_command(executions)
cli.add_command(traces)
cli.add_command(schedules)
cli.add_command(operations)
cli.add_command(memory)
cli.add_command(secrets)
cli.add_command(webhooks)
cli.add_command(conversations)
cli.add_command(run_command)
cli.add_command(status_command)
cli.add_command(logs_command)

# Commands that delegate to daita-agents (shows clear error if not installed)
cli.add_command(push_command)
cli.add_command(init_command)
cli.add_command(create_group)
cli.add_command(test_command)

# Backward compat hidden alias: `daita execution-logs <id>` → `daita executions logs <id>`
@cli.command("execution-logs", hidden=True)
@click.argument("execution_id")
@click.option("--follow", "-f", is_flag=True)
@click.pass_context
def _execution_logs_alias(ctx, execution_id, follow):
    """Deprecated: use `daita executions logs <id>`."""
    from daita_cli.commands.executions import execution_logs
    ctx.invoke(execution_logs, execution_id=execution_id, follow=follow)


@cli.command("mcp-server")
def mcp_server_command():
    """Start the MCP server for coding agent integrations."""
    import asyncio
    from daita_cli.mcp_server import run_server
    asyncio.run(run_server())


def main():
    cli()


if __name__ == "__main__":
    main()
