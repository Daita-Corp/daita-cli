# daita-cli

Official CLI and MCP server for the [Daita](https://daita-tech.io) platform — deploy, run, and observe your hosted AI agents from the terminal or any coding agent.

---

## Installation

```bash
pip install daita-cli
```

Requires Python 3.11+.

---

## Authentication

Export your API key before running any command:

```bash
export DAITA_API_KEY=sk-...
```

Get your key from the [Daita dashboard](https://daita-tech.io).

---

## Quick Start

```bash
# Initialize a new project
daita init my-project

# Test locally before deploying
daita test

# Deploy to the cloud
daita push

# Run an agent remotely
daita run my-agent --data-json '{"input": "hello"}'

# Follow execution in real-time
daita run my-agent --follow
```

---

## Commands

### Local Development

| Command | Description |
|---------|-------------|
| `daita init [name]` | Scaffold a new Daita project |
| `daita create agent <name>` | Add a new agent from template |
| `daita create workflow <name>` | Add a new workflow from template |
| `daita test [target]` | Run agents/workflows locally |
| `daita push` | Deploy the current project to the cloud |
| `daita status` | Show project and deployment status |

### Agents & Executions

| Command | Description |
|---------|-------------|
| `daita agents list` | List all agents |
| `daita agents show <id>` | Show agent details |
| `daita agents deployed` | List deployed agents |
| `daita run <target>` | Execute an agent or workflow remotely |
| `daita executions list` | List recent executions |
| `daita executions show <id>` | Show execution details and result |
| `daita executions cancel <id>` | Cancel a running execution |

### Observability

| Command | Description |
|---------|-------------|
| `daita traces list` | List execution traces |
| `daita traces show <id>` | Show trace details |
| `daita traces spans <id>` | Show span hierarchy |
| `daita traces decisions <id>` | Show AI decision events |
| `daita traces stats` | Trace statistics (24h/7d/30d) |
| `daita logs` | View deployment logs |
| `daita operations list` | List platform operations |
| `daita operations stats` | Operation statistics |
| `daita memory status` | Show memory system status |
| `daita memory show <workspace>` | Show workspace memory contents |
| `daita conversations list` | List conversations |
| `daita conversations show <id>` | Show conversation details |

### Infrastructure

| Command | Description |
|---------|-------------|
| `daita deployments list` | List deployments |
| `daita deployments history <project>` | Deployment history |
| `daita deployments rollback <id>` | Rollback to a previous deployment |
| `daita schedules list` | List agent schedules |
| `daita schedules pause <id>` | Pause a schedule |
| `daita schedules resume <id>` | Resume a schedule |
| `daita secrets list` | List secret key names |
| `daita secrets set <key> <value>` | Store an encrypted secret |
| `daita secrets remove <key>` | Delete a secret |
| `daita webhooks list` | List webhook URLs |

---

## Output Formats

All commands support `--output` / `-o`:

```bash
daita agents list -o json     # JSON (default when piped)
daita agents list -o table    # ASCII table
daita agents list -o text     # Human-readable text
```

Output defaults to JSON automatically when stdout is not a TTY (e.g. in scripts or CI).

---

## MCP Server

`daita-cli` ships a full [Model Context Protocol](https://modelcontextprotocol.io) server with ~30 tools, letting coding agents (Claude Code, Codex, Cursor, etc.) interact with your Daita platform directly.

### Start the server

```bash
daita mcp-server
```

### Configure in Claude Code

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "daita": {
      "command": "daita",
      "args": ["mcp-server"],
      "env": {
        "DAITA_API_KEY": "sk-..."
      }
    }
  }
}
```

### Available MCP tools

| Category | Tools |
|----------|-------|
| Agents | `list_agents`, `get_agent`, `list_deployed_agents` |
| Executions | `run_agent`, `list_executions`, `get_execution`, `cancel_execution`, `get_execution_stats` |
| Traces | `list_traces`, `get_trace`, `get_trace_spans`, `get_trace_decisions`, `get_trace_stats` |
| Deployments | `list_deployments`, `get_deployment_history`, `rollback_deployment`, `delete_deployment` |
| Schedules | `list_schedules`, `get_schedule`, `pause_schedule`, `resume_schedule` |
| Memory | `get_memory_status`, `get_workspace_memory` |
| Secrets | `list_secrets`, `set_secret`, `delete_secret` |
| Webhooks | `list_webhooks` |
| Conversations | `list_conversations`, `get_conversation`, `create_conversation`, `delete_conversation` |
| Local dev | `init_project`, `create_agent`, `create_workflow`, `test_agent` |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DAITA_API_KEY` | API key (required) |
| `DAITA_API_ENDPOINT` | Override the API base URL (default: `https://api.daita-tech.io`) |
| `DAITA_OUTPUT` | Default output format: `json`, `text`, or `table` |

---

## Development

```bash
git clone https://github.com/daita-tech/daita-cli
cd daita-cli
pip install -e ".[dev]"
pytest
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
