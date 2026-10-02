# Kalmido MCP server

`kalmido_mcp.py` lets an AI agent use Kalmido as a tool through the [Model Context Protocol](https://modelcontextprotocol.io).
It needs only Python 3 (standard library, no packages) and talks to the Kalmido REST API with the **agent's** API token.

Kalmido never starts AI processes itself. You run this server (and your agent) on your own machine. For the agent concept, events and approvals, see [docs/AGENTS.md](../docs/AGENTS.md).

## Before you start

1. An admin creates the agent in **Settings > Agents > Status > Add agent**, or (2.7.2, when an admin allows it) you create your own personal agent in **Settings > Agents > Set up > Create agent**. Copy its API token (it is shown once). Step-by-step guides for Linux, macOS and Windows: **Settings > Agents > Set up** and [docs/AGENTS.md](../docs/AGENTS.md#set-up-an-agent).
2. Share the lists that the agent should work in with the agent (role Member, Participant or Viewer).

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

By default the server binds to `127.0.0.1`. It rejects requests with an `Origin` that is not localhost (DNS rebinding) and, when `MCP_HTTP_TOKEN` is set, requests without that bearer token. If you bind to another address, always set `MCP_HTTP_TOKEN` and put TLS in front.

## Tools

| Tool | What it does | REST call |
|---|---|---|
| `get_agent` | agent user, enabled state, status, job counts, latest event cursor, runtime settings (2.4.1) | `GET /api/v1/agent` |
| `list_lists` | visible lists, including their sections `[{id, name}]`, list tags and agent tidy mode | `GET /api/v1/lists` |
| `list_list_tags` | shared tags of a list | `GET /api/v1/lists/{id}/tags` |
| `list_tasks` | tasks filtered by list, status, tag, list tag or assignee; `compact: true` = only the fields to scan a list with (id, title, list_id, section_id, parent_id, status, due, due_time, priority, tags, list_tags, assignee_id), `false` = full tasks, not given = full up to 25 tasks per page, compact above (`"compact": true` in the result) | `GET /api/v1/tasks` (`?fields=compact`) |
| `search_tasks` | full-text search | `GET /api/v1/search?q=` |
| `get_task` | a task plus its comments (reactions, suggestions); 2.2.0: `code` (linked pull requests + CI, commits) and `repo` (the list's repository, a suggested branch) | `GET /api/v1/tasks/{id}` + `/comments` |
| `create_task` / `update_task` / `complete_task` | change tasks | `POST /api/v1/tasks`, `PATCH /api/v1/tasks/{id}`, `POST .../complete` |
| `add_comment` | comment, optionally with a structured tidy suggestion | `POST /api/v1/tasks/{id}/comments` |
| `react` | 👍 / 👎 / ❤️ on a comment (or take one back) | `POST /api/v1/comments/{id}/reactions`, `DELETE .../reactions/{emoji}` |
| `set_status` | idle / working / waiting / error, a short text and optionally the task it works on ("Claude is writing …" there) | `PUT /api/v1/agent/status` |
| `list_events` | events after a cursor | `GET /api/v1/agent/events?since=` |
| `wait_for_events` | long-poll for events (up to 60 s) | `GET /api/v1/agent/events?since=&wait=` |
| `list_jobs` / `create_job` / `update_job` | jobs shown in the Agents tab | `/api/v1/agent/jobs` |
| `get_job` / `submit_proposal` | 2.3.0: one job (a proposal job with its input) / answer a `job_request` with a structured proposal ([Proposals](../docs/AGENTS.md#proposals)) | `/api/v1/agent/jobs/{id}`, `.../proposal` |
| `list_chats` / `send_chat` | chat with people | `GET /api/v1/agent/chats`, `POST /api/v1/agent/chats/{user_id}` |
| `chat_typing` | typing dots in one person's chat for 10 s (2.4.1) | `POST /api/v1/agent/typing` |
| `react_to_chat` | 2.7.2: 👍 / 👎 / ❤️ on a chat message (`user_id`, `message_id`, `emoji`, `on`, default true); a person's 👍 on your message arrives as a `reaction` event with `approval: "approved"` | `POST /api/v1/agent/chats/{user_id}/messages/{id}/reactions` |
| `tidy_task` | tidy a task (lists in tidy mode "auto") | `POST /api/v1/tasks/{id}/tidy` |
| `set_waiting` / `clear_waiting` | 2.1.0: mark a task as waiting on external (`note`, follow-up day `until`) or end it | `PUT` / `DELETE /api/v1/tasks/{id}/waiting` |
| `list_waiting` | 2.1.0: open tasks waiting on external (`list_tasks` also takes `waiting: true / false`) | `GET /api/v1/tasks?waiting=true` |
| `list_groups` | 2.10.0: groups of people with their members (`mine` = yours) | `GET /api/v1/groups` |
| `list_list_groups` | 2.10.0: the groups a list is shared with (role, directly or via a folder) | `GET /api/v1/lists/{id}/groups` |
| `get_day_plan` | 2.10.0: the built-in day plan of your user (preview; `mode` day or fill) | `GET /api/v1/dayplan` |
| `get_day_review` | 2.10.0: the daily review (done, open, moved, next working day) | `GET /api/v1/dayplan/review` |
| `report_usage` | 2.1.1: report the agent's model usage (model, tokens, optional cost, task / list / job, short note; numbers only) | `POST /api/v1/agent/usage` |
| `list_repos` | 2.2.0: repositories connected to a list (never a token) | `GET /api/v1/lists/{id}/repos` |
| `get_project_overview` | 2.7.1: the overview of a project list (description, key links, milestones, files, members, status, time), read-only | `GET /api/v1/lists/{id}/overview` |
| `request_merge_approval` | 2.2.0: a *Ready to merge* comment for your pull request (`task_id`, `pr_url`, `summary`); wait for the `reaction` event with `approval: "approved"` before merging | `POST /api/v1/tasks/{id}/comments` with `suggestion.kind = merge_request` |
| `get_usage` | 2.1.1: the agent's own usage by day, task, list or model, with its limit | `GET /api/v1/agent/usage` |

API errors come back as tool results with `isError: true` and the API's message, for example `HTTP 403: No permission (view only)`.

## Runtime launcher (2.4.1)

[`agent_launcher.sh`](agent_launcher.sh) starts Claude Code with the runtime settings an admin chose in Kalmido (model,
auto-compact, nightly fresh restart, *Reset now*), always in a fresh session, and restarts it when they change:

```sh
./agent_launcher.sh -e /path/to/kalmido-agent.env -- claude -p "Work through your Kalmido events" --mcp-config ~/.kalmido-mcp.json
```

The env file holds `KALMIDO_URL` and `KALMIDO_TOKEN`. Details and a systemd unit: [docs/AGENTS.md](../docs/AGENTS.md#runtime-settings).

**Windows and macOS (2.7.2):** [`agent_launcher.ps1`](agent_launcher.ps1) is the same launcher in PowerShell (Windows
PowerShell 5.1 or PowerShell 7; on macOS PowerShell 7, since `agent_launcher.sh` needs GNU `date` and `setsid`):

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File agent_launcher.ps1 -e $HOME\.config\kalmido\agent.env --once   # dry run
pwsh -NoProfile -ExecutionPolicy Bypass -File agent_launcher.ps1 -e $HOME\.config\kalmido\agent.env -- claude -p "Work through your Kalmido events"
```

A scheduled task (Windows) and a launchd plist (macOS): [docs/AGENTS.md](../docs/AGENTS.md#set-up-an-agent).

## Claude Code usage hook

[`claude_usage_hook.py`](claude_usage_hook.py) (2.1.1) reports a Claude Code session's token usage to Kalmido after every turn,
as a **Stop hook**: it reads the session transcript, sums the new assistant messages per model and calls
`POST /api/v1/agent/usage` with the agent's token (numbers only, never text). Wire it in `.claude/settings.json`:

```json
{"hooks": {"Stop": [{"hooks": [{"type": "command",
  "command": "python3 /path/to/kalmido/mcp/claude_usage_hook.py /path/to/kalmido-agent.env", "timeout": 30}]}]}}
```

The env file holds `KALMIDO_URL` and `KALMIDO_TOKEN` (optional `KALMIDO_USAGE_PRICES`, `KALMIDO_USAGE_TASK`,
`KALMIDO_USAGE_STATE_DIR`). Details, the price table and `--dry-run`: [docs/AGENTS.md](../docs/AGENTS.md#claude-code-report-usage-automatically).

## Security

- The token has exactly the agent's permissions: only the lists shared with it, never admin rights, no Paperless access. An admin can pause the agent at any time. A paused agent's token stops working at once.
- Keep the token out of shared config files. The server never prints or logs it.
- A person can chat with the agent even if they cannot see every list the agent sees. The agent must not quote content from lists that this person cannot see.

## Tests

```sh
python3 tests/mcp_test.py   # stub API server, stdio + HTTP; no Docker needed
python3 tests/usage_hook_test.py   # the usage hook against a stub API with a sample transcript
python3 tests/launcher_ps1_test.py # agent_launcher.ps1 against a stub API (needs pwsh; skipped without it)
```
