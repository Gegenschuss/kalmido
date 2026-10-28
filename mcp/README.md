# Kalmido MCP server

`kalmido_mcp.py` lets an AI agent use Kalmido as a tool through the [Model Context Protocol](https://modelcontextprotocol.io).
It needs only Python 3 (standard library, no packages) and talks to the Kalmido REST API with the **agent's** API token.

Kalmido never starts AI processes itself. You run this server (and your agent) on your own machine. For the agent concept, events and approvals, see [docs/AGENTS.md](../docs/AGENTS.md).

## Before you start

1. An admin creates the agent in **Settings > Agents > Status > Add agent**, or (2.7.2, when an admin allows it) you create your own personal agent in **Settings > Agents > Set up > Create agent**. Copy its API token (it is shown once). Step-by-step guides for Linux, macOS and Windows: **Settings > Agents > Set up** and [docs/AGENTS.md](../docs/AGENTS.md#set-up-an-agent).
2. Share the projects that the agent should work in with the agent (role Member, Participant or Read-only).

## Claude Code

```sh
claude mcp add kalmido -e KALMIDO_URL=https://tasks.example.com -e KALMIDO_TOKEN=abk_... -- python3 /path/to/kalmido/mcp/kalmido_mcp.py
```

## Claude Desktop (and other clients with a JSON config)

```json
{
  "mcpServers": {
    "kalmido": {
      "command": "python3",
      "args": ["/path/to/kalmido/mcp/kalmido_mcp.py"],
      "env": { "KALMIDO_URL": "https://tasks.example.com", "KALMIDO_TOKEN": "abk_..." }
    }
  }
}
```

## HTTP mode

For clients that connect over HTTP, the server supports a subset of Streamable HTTP: `POST /mcp` with JSON responses (no SSE stream and no sessions).

```sh
KALMIDO_URL=https://tasks.example.com KALMIDO_TOKEN=abk_... MCP_HTTP_TOKEN=$(openssl rand -hex 24) \
  python3 mcp/kalmido_mcp.py --http --port 8765
# client: url http://127.0.0.1:8765/mcp, header "Authorization: Bearer <MCP_HTTP_TOKEN>"
```

By default the server binds to `127.0.0.1`. It rejects requests with an `Origin` that is not localhost (DNS rebinding) and requests without the bearer token. Since 2.126.0 `MCP_HTTP_TOKEN` (at least 16 characters) is required: without it `--http` does not start. If you bind to another address, put TLS in front.

## Tools

Projects are called lists in the API (`list_id`, `/api/v1/lists`, `kind=list|project`); `kind=project` is the switch "Progress and status".

The server offers about 320 tools, one or more for nearly every REST route of the agent API. This page is only an overview;
the complete, tested lists are elsewhere:

- [`CLAUDE.template.md`](CLAUDE.template.md): every tool with its parameters, written for the agent (the file an agent reads).
- [docs/AGENTS.md](../docs/AGENTS.md): events, approvals, proposals and the rules of the agent channel.
- [docs/API.md](../docs/API.md): the REST calls behind the tools and the permission (scope) of each.
- `tools/list` of a running server: only the tools the token may use (from `GET /api/v1/me`, refreshed every 5 minutes).

| Area | Tools (examples) | Scope |
|---|---|---|
| Projects and tasks | `list_lists`, `list_tasks`, `search_tasks`, `get_task`, `list_subtasks`, `get_dependencies`, `get_project_overview` | `read` |
| Change tasks | `create_task`, `update_task`, `complete_task`, `move_task`, `batch_tasks`, `set_waiting`, `check_in_habit` | `tasks:write` |
| Comments and chat | `add_comment`, `react` (`remove: true` takes a reaction back), `send_chat`, `react_to_chat` (`emoji`, `remove`), `list_chats`, `request_chat_approval` | `comments`, `read` |
| Files of tasks and projects | `list_attachments`, `get_attachment` (`source`: `task`, `chat`, `team` or `project`), `read_attachment`, `upload_attachment` | `attachments:read`, `attachments:write` |
| File store | the folders and files shared with the agent | `files:read`, `files:write` |
| Structure | projects, sections, fields, project tags, templates, saved filters, folders | `structure` |
| Deleting | `delete_task`, `restore_task`, `empty_trash`, `delete_list` and the other `delete_*` | `delete` |
| Time | `start_timer`, `stop_timer`, `add_time_entry`, `get_time_gaps` | `time`, `read` |
| Calendar and contacts | events, event calendars, address books, contacts | `calendar`, `contacts` |
| Agent channel | `get_agent`, `set_status`, `list_events`, `wait_for_events`, `list_jobs`, `create_job`, `submit_proposal`, `propose_*`, `report_usage` | none (the agent's own channel; a read-only token may not post) |
| Office drafts | quotation, invoice and letter drafts a person checks and sends | `office` |
| Further areas | pin board notepads, view arrangements, proposals for old data, tables, knowledge pages | `pinboard`, `layouts`, `import`, `sheets:read` / `sheets:write`, `wiki:read` / `wiki:write` |
| Export | `export_data` | `export` |

A new agent starts with `read`, `tasks:write`, `comments`, `files:read` and `files:write`; the other scopes (including
`office`, `pinboard`, `layouts`, `import`, `sheets:*`, `wiki:*`) an admin ticks on purpose. Never for an agent: `account`,
`admin-read`, `private` and `docs:upload`. A few tools check a scope that depends on the request body (a batch with deletions,
`export_data`, linking a contact), and answer a plain `403` without `required_scope` when it is missing.

An agent's dangerous requests (deleting a project or a field, emptying the trash, batches of 10+ tasks, moving projects,
folders, sharing) answer `approval_required` with a waiting job: a person approves it in Kalmido and the agent gets the
result as a `job` event. `tests/parity_test.py` fails when a REST route has no tool (or no documented reason).

API errors come back as tool results with `isError: true` and the API's message, for example `HTTP 403: No permission (view only)`.

## Runtime launcher (2.4.1)

[`agent_launcher.sh`](agent_launcher.sh) starts Claude Code with the runtime settings an admin chose in Kalmido (model,
auto-compact, nightly fresh restart, *Reset now*), always in a fresh session, and restarts it when they change:

```sh
./agent_launcher.sh -e /path/to/kalmido-agent.env -- claude -p "Work through your Kalmido events" --mcp-config ~/.kalmido-mcp.json
```

The env file holds `KALMIDO_URL` and `KALMIDO_TOKEN`. Details and a systemd unit: [docs/AGENTS.md](../docs/AGENTS.md#runtime-settings).

**macOS (2.44.0, #962):** `agent_launcher.sh` runs on a Mac as it is (`/bin/bash` 3.2, `python3`; no GNU `date`, no
`setsid`, no PowerShell).

**Windows (2.7.2):** [`agent_launcher.ps1`](agent_launcher.ps1) is the same launcher in PowerShell (Windows
PowerShell 5.1 or PowerShell 7; on macOS / Linux an alternative with PowerShell 7):

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File agent_launcher.ps1 -e $HOME\.config\kalmido\agent.env --once   # dry run
pwsh -NoProfile -ExecutionPolicy Bypass -File agent_launcher.ps1 -e $HOME\.config\kalmido\agent.env -- claude -p "Work through your Kalmido events"
```

A scheduled task (Windows) and a launchd plist (macOS): [docs/AGENTS.md](../docs/AGENTS.md#set-up-an-agent).

**Set up with one command (2.44.0, #1517):** *Settings > Agents > (agent) > Set up on a computer* shows one command with a
one-time code. The setup script of your Kalmido (`/agent-setup.sh` for macOS / Linux, `/agent-setup.ps1` for Windows)
trades the code for the agent's token (kept in a private file), fetches the files in [`starter_files.txt`](starter_files.txt)
(a new starter module must be listed there) and sets up the autostart (launchd / systemd --user / Task Scheduler). Both
scripts mark the same steps (`# kalmido-setup-step: <id>`, checked by `tests/launcher_parity_test.py`). Details:
[docs/AGENTS.md](../docs/AGENTS.md#set-up-on-a-computer-with-one-command-2440).

**Event mode (2.35.0):** with `--events` both launchers start [`agent_run.py`](agent_run.py) in front of the command: it
waits for the agent's events and runs the command once per event, headless with stream-json, and sends steps, model,
permission mode, typing / status, the plan usage ring, the reply reference and approval cards like a hosted chat service;
the final text of a chat run is posted as the answer. The command then has no `-p`. 2.40.0: a chat answer that asks to
decide or makes a proposal without a final ` ```approval ` block goes back to the agent once (same session, the complete
answer with the block); still none -> it is posted with a note that nothing happens without an explicit yes
(`KALMIDO_APPROVAL_CHECK=0` switches this off). A final ` ```suggest ` block (up to three next steps) becomes answer
buttons; a typed number picks one. Long answers go in numbered parts with code blocks closed and reopened at the cut.

```sh
./agent_launcher.sh -e /path/to/kalmido-agent.env --events -- claude --mcp-config ~/.kalmido-mcp.json
```

What a launcher has to do is listed in [`launcher_capabilities.json`](launcher_capabilities.json); a test fails when the
`.sh` or the `.ps1` lacks one.

## Claude Code usage hook

[`claude_usage_hook.py`](claude_usage_hook.py) (2.1.1) reports a Claude Code session's token usage to Kalmido after every turn,
as a **Stop hook**, and (2.11.0) for subagents as a **SubagentStop hook** with the same command: it reads the session
(or subagent) transcript, sums the new assistant messages per model and calls
`POST /api/v1/agent/usage` with the agent's token (numbers only, never text). Wire it in `.claude/settings.json`:

```json
{"hooks": {
  "Stop": [{"hooks": [{"type": "command",
    "command": "python3 /path/to/kalmido/mcp/claude_usage_hook.py /path/to/kalmido-agent.env", "timeout": 30}]}],
  "SubagentStop": [{"hooks": [{"type": "command",
    "command": "python3 /path/to/kalmido/mcp/claude_usage_hook.py /path/to/kalmido-agent.env", "timeout": 30}]}]}}
```

The env file holds `KALMIDO_URL` and `KALMIDO_TOKEN` (optional `KALMIDO_USAGE_PRICES`, `KALMIDO_USAGE_TASK`,
`KALMIDO_USAGE_STATE_DIR`). Details, the price table and `--dry-run`: [docs/AGENTS.md](../docs/AGENTS.md#claude-code-report-usage-automatically).

## Security

- The token has exactly the agent's permissions: only the projects shared with it, only its scopes (2.15.0), never admin rights. An admin can pause the agent at any time. A paused agent's token stops working at once.
- Keep the token out of shared config files. The server never prints or logs it.
- A person can chat with the agent even if they cannot see every project the agent sees. The agent must not quote content from projects that this person cannot see.

## Tests

```sh
python3 tests/mcp_test.py   # stub API server, stdio + HTTP; no Docker needed
python3 tests/parity_test.py   # app routes -> API routes -> MCP tools (no Docker)
python3 tests/usage_hook_test.py   # the usage hook against a stub API with a sample transcript
python3 tests/launcher_ps1_test.py # agent_launcher.ps1 against a stub API (needs pwsh; skipped without it)
python3 tests/launcher_parity_test.py   # both launchers carry every capability; agent_run.py without a server
python3 tests/agent_docs_coverage_test.py   # every agent event, agent endpoint and MCP tool is documented
```
