# Git integration

Connect tasks to GitHub, GitLab, Gitea / Forgejo or Bitbucket Cloud, and hand a ticket to a coding agent.

## Git integration

A **project** can be connected to one or more repositories (*Edit project > Repository*, up to five; the area shows
for projects of the type *Software / AI dev* and for projects that already have a repository): **GitHub** (github.com or a
GitHub Enterprise server), **GitLab** (gitlab.com or your own server, also nested groups like `group/sub/repo`),
**Gitea / Forgejo** (the server's address) and **Bitbucket Cloud** (2.18.0; Bitbucket Server / Data Center is not
supported). Pasting a github.com, gitlab.com or bitbucket.org address picks the provider. Only the project owner and project
admins connect, change or remove them; everyone in the project sees the results.

**A repository on a folder** (2.33.0, #934): *Folder settings > Repository* connects a repository once for every
project in the folder and its subfolders, also projects added later; `#id` and `fixes #id` work across all of them
with one poll per repository. A project can switch it off (*Edit project > Repository*) or connect its own instead. Only the
folder's owner connects it; the token stays sealed.

- **Token:** a fine-grained token with *read-only* access to the repository (contents, pull requests, commit statuses /
  checks) is enough (GitLab: `read_api`; Bitbucket: a read-only repository or workspace access token, or
  `user:app-password`); a public repository works without one (with GitHub's much lower limit for anonymous requests).
  It is write-only (the page only says *Token set*) and encrypted with `KALMIDO_SECRET_KEY`;
  without the key no token can be stored. Kalmido never gets write access: it only reads.
- **Polling, not webhooks:** the server asks the Git server itself, every 3 minutes per repository
  (`KALMIDO_GIT_POLL`), with ETags (unchanged answers cost GitHub no rate limit), pauses when the rate limit runs low
  and backs off while a repository fails (up to an hour). So it works on a server that GitHub cannot reach (behind a
  VPN, in the office LAN). A background thread does it, a few repositories at a time: requests never wait on it.
  Internal Git servers need the host on the admin allow-list (*Settings > Server > Server > Advanced*, or
  `KALMIDO_CALENDAR_ALLOW_HOSTS`), the same SSRF guard as calendar subscriptions.
- **Matching** (tasks of the connected project only): `#123` (the task number, in the address `#t/123`) in a commit
  message, a pull request title or description, or a branch named `kalmido-123` (also `kalmido-123-…`), `task-123-…` or `123-…`.
- **Task panel > Code** (after the fields, before the comments): the linked pull requests (open / merged / closed,
  author, CI ✓ ✗ ⏲ from the combined status and the check runs) and the latest commits, a button that copies a branch
  name for the task, and *… is working on it* while an assigned agent works on it. Rows show a chip with the pull request
  and its CI. The history notes when a linked pull request is opened, merged or closed.
- **Keywords:** `fixes #123`, `closes #123`, `resolves #123` (also fix / fixed, close / closed, resolve / resolved, and
  German `erledigt #123`) in a **merged** pull request or a commit on the default branch complete the task, once, and
  only for changes after the repository was connected. The history names the pull request or commit and has *Undo*.
- **Optional webhook** (off by default, for a Gitea / Forgejo next door or a public server): *Turn the webhook on* shows
  the payload URL `/api/hooks/git/<id>` and a secret once; a push, pull request or status event with a valid signature
  (`X-Hub-Signature-256`, `X-Gitea-Signature`, `X-Forgejo-Signature`, GitLab's *Secret token* `X-Gitlab-Token`,
  Bitbucket's *Secret* `X-Hub-Signature`) triggers the next check at once. The body is
  never trusted, polling stays the source of truth.
- **Build state** (2.151.0): every linked commit and merged pull request knows the **first version tag** that holds it
  (a new tag is compared once with the version before it; tags are versions like `v2.151.0`, sorted by number), and
  branches named after a task are compared with the default branch. *Code* starts with one line: *In version 2.151.0*,
  *In main, not released yet* or *Built, not in main yet* with the branch and how many commits it is ahead. The project's
  **version field** (a text field named *Package*, *Version*, *Release* or *Target version*, or the one picked in the
  repository dialog; *Off* turns it off) is checked against the tags: a task that is still open although a tag with
  exactly its version exists gets a hint at the task and a small mark in its row. Values like `2.46c` are not checked.
  Agents read it as `build` (`get_task`, `GET /api/v1/tasks/{id}`) and per project with `list_build_status`
  (`GET /api/v1/lists/{id}/build-status`).
- **Releases** (2.18.0): a new tag like `v2.18.0` completes the open milestone "2.18.0" or "Release 2.18.0" of the project
  once, with *Undo*; tags that existed before the connection never do.
- **Release pass** (2.392.0): a project can switch on that the poll also completes its open tasks that are still open
  although their version field or their code is released (the *stale* tasks of the build state), once per task and
  version, with *Undo*. It is off for every project until someone switches it on. A task marked as done only in part
  (finished up to a later version) waits for that version; a parked task is never completed. Webhooks and agents get
  `task.completed` with `via: "release"` and no actor. It only reads what the poll stored and never writes to Git.
- **Error reports** (2.18.0): *Error reports > Turn on* gives the project a secret URL (shown once; *New URL*, *Turn off*).
  Point a Sentry webhook (an internal integration with issue / alert webhooks) or any service that sends JSON
  `{title, body, url, fingerprint, level}` at it: a new error becomes a bug ticket with the details and the link, the same
  error again only counts up at its open ticket. A new error sends one News item and push (*Settings > Notifications >
  New error reports*); repeats stay quiet. At most `KALMIDO_ERROR_REPORTS_PER_HOUR` (default 30) new tickets per
  project and hour. Tasks by e-mail (see [Tasks by e-mail](IMPORT.md#tasks-by-e-mail)) are another way in.
- **Code in Markdown** (2.18.0): code blocks are highlighted by language and have *Copy*; `src/app.py:42` (or
  `app.js:10-20`) in notes and comments links to that file and line at the default branch.
- **API / MCP:** `GET /api/v1/lists/{id}/repos` (never a token), `get_task` includes `code` and `repo`;
  `GET` / `PATCH /api/v1/lists/{id}/error-hook` for people.

### Hand a ticket to a coding agent

Assign a task in a connected project to an agent (for example Claude Code with the MCP server on a dev machine). Its
`assigned` event and `get_task` carry `repo`: provider, web address, owner / name, default branch, a suggested branch
`kalmido-<id>` and the linked pull requests with CI. The agent works in its own checkout, pushes the branch with its
own credentials, opens a pull request and asks for approval (`request_merge_approval`): a *Ready to merge* comment with
the pull request, its CI and *Approve* / *Reject* for the project owner, project admins, the assignee and admins. 👍 / 👎 sends
the agent a `reaction` event with `approval` and `merge_request`; only then does it merge. A sample `CLAUDE.md` for such
a project agent: [docs/AGENTS.md](AGENTS.md#coding-agent-workflow).
