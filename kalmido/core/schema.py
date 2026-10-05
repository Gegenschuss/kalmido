"""Database schema, migrations, indexes and the default settings (user + instance)."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS lists (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '',
  folder TEXT NOT NULL DEFAULT '', sort REAL NOT NULL DEFAULT 0,
  view TEXT NOT NULL DEFAULT 'list', is_inbox INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sections (
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, sort REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  section_id INTEGER REFERENCES sections(id) ON DELETE SET NULL,
  parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
  priority INTEGER NOT NULL DEFAULT 0,          -- 0 none, 1 low, 3 medium, 5 high
  status INTEGER NOT NULL DEFAULT 0,            -- 0 open, 2 done, -1 won't do
  due TEXT, due_time TEXT,
  reminders TEXT NOT NULL DEFAULT '',           -- csv of minutes before due ("0,15")
  reminded TEXT NOT NULL DEFAULT '',            -- json list of fired keys
  repeat TEXT NOT NULL DEFAULT '',              -- RRULE body (FREQ=...)
  repeat_from TEXT NOT NULL DEFAULT 'due',      -- 'due' | 'done'
  sort REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  completed_at TEXT, deleted_at TEXT, tt_id TEXT);
CREATE INDEX IF NOT EXISTS tasks_list ON tasks(list_id);
CREATE INDEX IF NOT EXISTS tasks_parent ON tasks(parent_id);
CREATE INDEX IF NOT EXISTS tasks_open ON tasks(status) WHERE deleted_at IS NULL;
CREATE TABLE IF NOT EXISTS task_tags (                -- tags are per user (user_id)
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL DEFAULT 0,
  tag TEXT NOT NULL, PRIMARY KEY (task_id, user_id, tag));
CREATE TABLE IF NOT EXISTS habits (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '',
  goal INTEGER NOT NULL DEFAULT 1, days TEXT NOT NULL DEFAULT '1234567',
  remind_at TEXT NOT NULL DEFAULT '', reminded_on TEXT NOT NULL DEFAULT '',
  sort REAL NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS habit_logs (
  habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
  day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (habit_id, day));
CREATE TABLE IF NOT EXISTS pomos (
  id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  kind TEXT NOT NULL DEFAULT 'focus', minutes INTEGER NOT NULL,
  start TEXT NOT NULL, paused_at TEXT, paused_s INTEGER NOT NULL DEFAULT 0,
  end TEXT, done INTEGER NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- global (server-internal)
CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  name TEXT NOT NULL, mime TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
  path TEXT NOT NULL,                           -- relative to ATT_DIR
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS attachments_task ON attachments(task_id);
CREATE TABLE IF NOT EXISTS paperless_links (
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  doc_id INTEGER,                               -- NULL while an upload is still being consumed
  title TEXT NOT NULL DEFAULT '', correspondent TEXT NOT NULL DEFAULT '', created TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ok',            -- ok | pending | error
  message TEXT NOT NULL DEFAULT '', ptask TEXT, att_id INTEGER, added_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS paperless_links_task ON paperless_links(task_id);
-- 2.1.0 (#180): Paperless connections. kind server = set up by an admin (name + URL, NO shared token: every user who
-- may use it enters their own token); personal = a user's own (name + URL + token, only the owner ever sees or uses it).
-- The legacy connection from the environment (PAPERLESS_TOKEN) is not stored here (id 0 in paperless_links.conn_id).
CREATE TABLE IF NOT EXISTS pl_conns (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL,   -- server | personal
  owner_id INTEGER,                             -- personal: the owner (server: NULL)
  name TEXT NOT NULL, url TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pl_conn_users (      -- server connections: who may use them (the admin decides)
  conn_id INTEGER NOT NULL REFERENCES pl_conns(id) ON DELETE CASCADE, user_id INTEGER NOT NULL,
  PRIMARY KEY(conn_id, user_id));
CREATE TABLE IF NOT EXISTS pl_tokens (          -- the users' Paperless API tokens, AES-GCM with KALMIDO_SECRET_KEY (never in the DB)
  conn_id INTEGER NOT NULL REFERENCES pl_conns(id) ON DELETE CASCADE, user_id INTEGER NOT NULL,
  token TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(conn_id, user_id));
-- 2.1.0 (#317): the per-list bell of a user: all | mute (no row = default = the notification matrix)
CREATE TABLE IF NOT EXISTS list_bell (
  user_id INTEGER NOT NULL, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  mode TEXT NOT NULL, PRIMARY KEY(user_id, list_id));
CREATE TABLE IF NOT EXISTS filters (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  rules TEXT NOT NULL DEFAULT '{}',            -- json: {op, lists, dates, prios, tags}
  sort REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL DEFAULT '',
  password_hash TEXT,                           -- NULL = no built-in login (proxy only)
  proxy_login TEXT UNIQUE,                      -- value of AUTH_PROXY_HEADER that maps to this user
  is_admin INTEGER NOT NULL DEFAULT 0, drop_token TEXT, created_at TEXT NOT NULL,
  disabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS list_members (             -- shared lists: role admin|edit|participant|view (1.10.0); folder/sort/view = the member's own
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'edit', folder TEXT NOT NULL DEFAULT '', sort REAL NOT NULL DEFAULT 0,
  view TEXT, added_at TEXT NOT NULL, PRIMARY KEY (list_id, user_id));
CREATE INDEX IF NOT EXISTS list_members_user ON list_members(user_id);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comments (                 -- task comments; soft delete (deleted_at, body wiped)
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  body TEXT NOT NULL DEFAULT '',                -- mentions as <@user_id> tokens
  mentions TEXT NOT NULL DEFAULT '',            -- csv of mentioned user ids
  created_at TEXT NOT NULL, edited_at TEXT, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS activity (                 -- task history, structured (rendered by the client)
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INTEGER, kind TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS task_seen (                -- unread comments: highest comment id a user has seen
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  seen_id INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, task_id));
CREATE TABLE IF NOT EXISTS push_subs (                -- Web Push: one row per subscribed browser / device
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint TEXT NOT NULL UNIQUE,                -- push service URL (allow-listed hosts only, see WEBPUSH_HOSTS)
  p256dh TEXT NOT NULL, auth TEXT NOT NULL,     -- the browser's encryption keys (base64url)
  label TEXT NOT NULL DEFAULT '',               -- "Chrome on Android"
  created_at TEXT NOT NULL, last_ok TEXT,
  fails INTEGER NOT NULL DEFAULT 0,             -- consecutive rejections (400/401/403); 5 = removed
  backoff_until REAL NOT NULL DEFAULT 0);       -- 429: no sends before this unix time
CREATE TABLE IF NOT EXISTS push_tags (                -- 2.0.5: task notifications shown on a device (per tag "t-<id>"), so they
  sub_id INTEGER NOT NULL REFERENCES push_subs(id) ON DELETE CASCADE,  -- can be closed there once handled elsewhere
  tag TEXT NOT NULL,
  sent_at REAL NOT NULL,                        -- unix time of the last push with this tag to this device
  handled_at REAL,                              -- handled on another device: to be closed here (dismiss push / next push)
  PRIMARY KEY (sub_id, tag));
CREATE TABLE IF NOT EXISTS task_push (                -- burst rule for collaboration pushes (per recipient + task)
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  sent_at REAL NOT NULL DEFAULT 0,              -- unix time of the last push
  pending INTEGER NOT NULL DEFAULT 0,           -- comments / changes counted since then (summary)
  events INTEGER NOT NULL DEFAULT 0, mentioned INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, task_id));
CREATE TABLE IF NOT EXISTS notifications (            -- "News" feed per user (structured, rendered by the client)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                           -- mention|comment|assign|unassign|complete|share|role|unshare
  task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL,
  actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  comment_id INTEGER,                           -- comment kinds: the (live) comment, excerpt read at display time
  data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, read_at TEXT);
CREATE TABLE IF NOT EXISTS templates (                -- private per user: a task (+ subtasks) or a whole list
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'task',            -- task | list
  name TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',   -- json, see tpl_* below
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS time_entries (             -- time tracking (module "time"), see the section below
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,   -- NULL: list-level entry, or the task was purged
  list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL,   -- the task's list (kept in sync by a trigger)
  task_title TEXT NOT NULL DEFAULT '',          -- snapshot (trigger), shown once the task is purged
  start TEXT NOT NULL, end TEXT,                -- UTC ISO; end NULL = the running timer
  seconds INTEGER NOT NULL DEFAULT 0,           -- duration (focus: without pauses); 0 while running
  note TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'manual',        -- timer | manual | focus
  pomo_id INTEGER,                              -- focus: the session it came from (imported once)
  client_id TEXT,                               -- timer: id chosen by the device (offline start -> matching stop)
  reminded INTEGER NOT NULL DEFAULT 0, auto_stopped INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS time_user_start ON time_entries(user_id, start);
CREATE INDEX IF NOT EXISTS time_task ON time_entries(task_id);
CREATE INDEX IF NOT EXISTS time_list ON time_entries(list_id, start);
CREATE UNIQUE INDEX IF NOT EXISTS time_running ON time_entries(user_id) WHERE end IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS time_pomo ON time_entries(pomo_id) WHERE pomo_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS time_client ON time_entries(user_id, client_id) WHERE client_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS task_deps (                -- dependencies: task_id waits on ("is blocked by") blocker_id
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  blocker_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  created_by INTEGER, created_at TEXT NOT NULL, PRIMARY KEY (task_id, blocker_id));
CREATE INDEX IF NOT EXISTS task_deps_blocker ON task_deps(blocker_id);
CREATE TABLE IF NOT EXISTS list_fields (              -- custom fields of a list (defined by the owner)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, type TEXT NOT NULL,       -- text | number | select | date | checkbox | person | url
  options TEXT NOT NULL DEFAULT '{}',           -- json: number {unit}, select {options: [{id, name, color}]}
  pinned INTEGER NOT NULL DEFAULT 0,            -- 1 = shown as a chip on the task rows (at most 2 per list)
  sort REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS list_fields_list ON list_fields(list_id);
CREATE TABLE IF NOT EXISTS task_field_values (        -- one value per task and field, shared by all list members
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  field_id INTEGER NOT NULL REFERENCES list_fields(id) ON DELETE CASCADE,
  value TEXT NOT NULL, PRIMARY KEY (task_id, field_id));
CREATE INDEX IF NOT EXISTS task_field_values_field ON task_field_values(field_id);
CREATE TABLE IF NOT EXISTS list_status (              -- project status updates of a list (history; current one on lists)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS list_status_list ON list_status(list_id, id);
CREATE TABLE IF NOT EXISTS admin_alerts (             -- admin alerts (ntfy, admins only): the last AA_KEEP
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL,   -- update | webpush | watchdog | integration | security | storage | test
  key TEXT NOT NULL,                            -- identical kind + key = one alert per cooldown
  message TEXT NOT NULL,                        -- English text (the settings list renders tmpl in the viewer's language)
  tmpl TEXT NOT NULL DEFAULT '[]',              -- json [one, other, n, args, click]
  created_at TEXT NOT NULL, sent_at TEXT,
  delivered INTEGER NOT NULL DEFAULT 0,         -- 1 = at least one ntfy topic accepted it
  state TEXT NOT NULL DEFAULT 'sent',           -- sent | failed | queued (daily summary) | summarized | capped (hourly limit)
  repeats INTEGER NOT NULL DEFAULT 0);          -- identical alerts swallowed by the cooldown since
CREATE INDEX IF NOT EXISTS admin_alerts_key ON admin_alerts(kind, key, created_at);
CREATE TABLE IF NOT EXISTS cal_subs (             -- external calendar subscriptions (read-only, private per user)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                           -- ics | caldav
  name TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '', visible INTEGER NOT NULL DEFAULT 1,
  interval INTEGER NOT NULL DEFAULT 15,         -- minutes between syncs (15 | 60)
  url TEXT NOT NULL,                            -- encrypted (cal_seal): the ICS link / the CalDAV calendar collection
  url_hint TEXT NOT NULL DEFAULT '',            -- scheme://host/... shown in the settings
  username TEXT NOT NULL DEFAULT '', password TEXT NOT NULL DEFAULT '',  -- CalDAV; password encrypted
  etag TEXT NOT NULL DEFAULT '', last_modified TEXT NOT NULL DEFAULT '', ctag TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',       -- pending | ok | error
  error TEXT NOT NULL DEFAULT '',               -- error code (CAL_ERR key[:detail]), never content
  fails INTEGER NOT NULL DEFAULT 0, events INTEGER NOT NULL DEFAULT 0, truncated INTEGER NOT NULL DEFAULT 0,
  digest TEXT NOT NULL DEFAULT '', tried_at TEXT, synced_at TEXT, fetched_at TEXT, changed_at TEXT,
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS cal_subs_user ON cal_subs(user_id);
CREATE TABLE IF NOT EXISTS cal_events (           -- expanded occurrences of a subscription (replaced on every change)
  id INTEGER PRIMARY KEY, sub_id INTEGER NOT NULL REFERENCES cal_subs(id) ON DELETE CASCADE,
  uid TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',         -- plain text
  all_day INTEGER NOT NULL DEFAULT 0,
  start TEXT NOT NULL, end TEXT NOT NULL,       -- all-day: local dates (end exclusive); timed: UTC 'YYYY-MM-DDTHH:MM:SSZ'
  d0 TEXT NOT NULL, d1 TEXT NOT NULL);          -- first / last local day (server time zone), for range queries
CREATE INDEX IF NOT EXISTS cal_events_sub ON cal_events(sub_id, d0);
CREATE TRIGGER IF NOT EXISTS time_task_list AFTER UPDATE OF list_id ON tasks WHEN NEW.list_id IS NOT OLD.list_id
BEGIN UPDATE time_entries SET list_id=NEW.list_id WHERE task_id=NEW.id; END;
CREATE TABLE IF NOT EXISTS recovery_codes (       -- two-factor: one-time recovery codes (SHA-256 of the code, never the code)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL, created_at TEXT NOT NULL, used_at TEXT);
CREATE INDEX IF NOT EXISTS recovery_codes_user ON recovery_codes(user_id);
CREATE TABLE IF NOT EXISTS webauthn_creds (       -- passkeys (WebAuthn): second factor and optional passwordless login
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  cred_id TEXT NOT NULL UNIQUE,                 -- credential id, base64url
  public_key BLOB NOT NULL,                     -- COSE public key
  sign_count INTEGER NOT NULL DEFAULT 0, transports TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '',
  rp_id TEXT NOT NULL DEFAULT '', aaguid TEXT NOT NULL DEFAULT '', backed_up INTEGER NOT NULL DEFAULT 0,
  discoverable INTEGER,                         -- 1 / 0 = the browser said (credProps), NULL = unknown
  created_at TEXT NOT NULL, last_used_at TEXT);
CREATE INDEX IF NOT EXISTS webauthn_creds_user ON webauthn_creds(user_id);
CREATE TABLE IF NOT EXISTS api_tokens (           -- personal access tokens for /api/v1 (package B): SHA-256 of the token, never the token
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL DEFAULT '',              -- first characters, shown in the settings to tell tokens apart
  scopes TEXT NOT NULL DEFAULT 'read',          -- csv: read | write | admin-read
  expires_at TEXT, created_at TEXT NOT NULL, last_used_at TEXT);
CREATE INDEX IF NOT EXISTS api_tokens_user ON api_tokens(user_id);
CREATE TABLE IF NOT EXISTS webhooks (             -- outgoing webhooks per user (package B)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '', url TEXT NOT NULL,
  events TEXT NOT NULL DEFAULT '',              -- csv of WH_EVENTS
  secret TEXT NOT NULL,                         -- sealed (server key): signs the deliveries, shown to the user once
  enabled INTEGER NOT NULL DEFAULT 1,
  disabled_reason TEXT NOT NULL DEFAULT '',     -- '' | failures (turned off after the last retry failed)
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS webhooks_user ON webhooks(user_id);
CREATE TABLE IF NOT EXISTS webhook_queue (        -- pending deliveries (survive a restart); retried with backoff
  id INTEGER PRIMARY KEY, webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
  delivery TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS webhook_queue_next ON webhook_queue(next_at);
CREATE TABLE IF NOT EXISTS webhook_log (          -- delivery log (last WH_LOG_KEEP per webhook): status, code, duration; never bodies
  id INTEGER PRIMARY KEY, webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
  delivery TEXT NOT NULL, event TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1,
  ok INTEGER NOT NULL DEFAULT 0, status INTEGER, error TEXT NOT NULL DEFAULT '', ms INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS webhook_log_hook ON webhook_log(webhook_id, id);
CREATE TABLE IF NOT EXISTS imports (          -- package C: one row per import (report + undo), the last IMPORT_KEEP per user
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source TEXT NOT NULL, file_name TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL DEFAULT '{}',           -- json {lists, sections, tasks}: the ids this import created (undo)
  report TEXT NOT NULL DEFAULT '{}',            -- json counts
  created_at TEXT NOT NULL, undone_at TEXT);
CREATE INDEX IF NOT EXISTS imports_user ON imports(user_id, id);
CREATE TABLE IF NOT EXISTS sample_items (         -- 1.8.0: what the sample project created (list, section, task, field, time)
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, item_id INTEGER NOT NULL, PRIMARY KEY (kind, item_id));
CREATE INDEX IF NOT EXISTS sample_items_user ON sample_items(user_id, kind);
CREATE TABLE IF NOT EXISTS agents (               -- 2.0.0: settings of users of kind 'agent' (see "agents")
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  enabled INTEGER NOT NULL DEFAULT 1,           -- kill switch: 0 = tokens refused, no events, webhook off
  note TEXT NOT NULL DEFAULT '',                -- what the agent is for (admins)
  status TEXT NOT NULL DEFAULT 'idle',          -- idle | working | waiting | error (reported by the agent)
  status_text TEXT NOT NULL DEFAULT '', status_at TEXT,
  webhook_id INTEGER,                           -- its webhook (webhooks.agent = 1), NULL = polling only
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_events (         -- 2.0.0: event queue per agent (polling / long-polling); id = seq
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  uuid TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS agent_events_agent ON agent_events(agent_id, id);
CREATE TABLE IF NOT EXISTS agent_jobs (           -- 2.0.0: jobs an agent reports (Agents tab)
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- the person it is for (optional)
  title TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'running',   -- running | waiting | done | failed | stopped
  log TEXT NOT NULL DEFAULT '', action TEXT, action_by INTEGER, action_at TEXT,   -- last Approve / Reject / Stop
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS agent_jobs_agent ON agent_jobs(agent_id, state);
CREATE INDEX IF NOT EXISTS agent_jobs_task ON agent_jobs(task_id);
CREATE TABLE IF NOT EXISTS agent_chat (           -- 2.0.0: one conversation per person and agent
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sender TEXT NOT NULL,                         -- user | agent
  body TEXT NOT NULL, task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, created_at TEXT NOT NULL, read_at TEXT);
CREATE INDEX IF NOT EXISTS agent_chat_pair ON agent_chat(agent_id, user_id, id);
CREATE TABLE IF NOT EXISTS chat_files (           -- 2.13.1 (#465): images / files of a chat message (either side)
  id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES agent_chat(id) ON DELETE CASCADE,
  name TEXT NOT NULL, mime TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
  path TEXT NOT NULL,                           -- relative to ATT_DIR: chat/<agent id>-<user id>/<random>-<name>
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chat_files_msg ON chat_files(message_id);
CREATE TABLE IF NOT EXISTS chat_reactions (       -- 2.7.2 (#421): heart | up | down (or one emoji) per person and chat message
  message_id INTEGER NOT NULL REFERENCES agent_chat(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  emoji TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (message_id, user_id, emoji));
CREATE TABLE IF NOT EXISTS agent_usage (          -- 2.1.1 (#326): model usage an agent reports (numbers + ids, never prompts)
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  model TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL,                                -- NULL = not reported
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL,
  job_id INTEGER REFERENCES agent_jobs(id) ON DELETE SET NULL,
  note TEXT NOT NULL DEFAULT '',                -- optional, at most USAGE_NOTE_MAX characters
  day TEXT NOT NULL,                            -- local day (server time zone): periods, charts
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS agent_usage_agent ON agent_usage(agent_id, day);
CREATE INDEX IF NOT EXISTS agent_usage_task ON agent_usage(task_id) WHERE task_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS agent_audit (          -- 2.2.1 (#358): every API request made with an agent's token (never bodies)
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL,   -- no foreign key: the log outlives a deleted agent (retention removes it)
  at TEXT NOT NULL,                             -- UTC, milliseconds
  day TEXT NOT NULL,                            -- local day (server time zone): filter, retention
  method TEXT NOT NULL, route TEXT NOT NULL,    -- the route template, e.g. /api/v1/tasks/{tid} (never query values)
  status INTEGER NOT NULL, task_id INTEGER, list_id INTEGER,   -- ids from the path or the body, when there
  ms INTEGER NOT NULL DEFAULT 0);               -- duration
CREATE INDEX IF NOT EXISTS agent_audit_agent ON agent_audit(agent_id, id);
CREATE INDEX IF NOT EXISTS agent_audit_day ON agent_audit(day);
CREATE TABLE IF NOT EXISTS comment_reactions (    -- 2.0.0: heart | up | down per person and comment
  comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  emoji TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (comment_id, user_id, emoji));
CREATE TABLE IF NOT EXISTS list_tags (            -- 2.0.0: tags of a list, shared by its members (colour per list)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', sort REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS list_tags_name ON list_tags(list_id, name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS task_list_tags (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES list_tags(id) ON DELETE CASCADE, PRIMARY KEY (task_id, tag_id));
CREATE INDEX IF NOT EXISTS task_list_tags_tag ON task_list_tags(tag_id);
CREATE TABLE IF NOT EXISTS public_links (         -- public read-only link of a list (package B), one per list
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL UNIQUE REFERENCES lists(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,              -- SHA-256 of the token in the URL (lookup)
  token TEXT NOT NULL,                          -- the token, sealed (server key): the owner can copy the link again
  mode TEXT NOT NULL DEFAULT 'view',            -- view | tick (view + tick off)
  notes INTEGER NOT NULL DEFAULT 0,             -- 1 = task notes shown as plain text
  password_hash TEXT, pw_rev INTEGER NOT NULL DEFAULT 0,   -- optional password; pw_rev invalidates unlock cookies
  expires_at TEXT, created_by INTEGER, created_at TEXT NOT NULL, last_used_at TEXT,
  views INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS list_activity (        -- 2.1.2 (#349): history of a list as a whole (kind owner = ownership transferred)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  user_id INTEGER, kind TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS list_activity_list ON list_activity(list_id);
CREATE TABLE IF NOT EXISTS git_conns (            -- 2.2.0 (#271): repositories connected to a project list
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,                       -- github | gitea (also Forgejo)
  base_url TEXT NOT NULL DEFAULT '',            -- web address of the server; '' = github.com
  owner TEXT NOT NULL, repo TEXT NOT NULL,
  token TEXT NOT NULL DEFAULT '',               -- access token, AES-GCM with KALMIDO_SECRET_KEY ('' = none: public repository)
  hook_secret TEXT NOT NULL DEFAULT '',         -- inbound webhook secret, sealed the same way ('' = webhook off)
  default_branch TEXT NOT NULL DEFAULT '', etags TEXT NOT NULL DEFAULT '{}',
  polled_at TEXT, next_at REAL NOT NULL DEFAULT 0, fails INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
  created_by INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS git_conns_list ON git_conns(list_id);
CREATE TABLE IF NOT EXISTS git_prs (              -- pull requests that are linked to a task
  conn_id INTEGER NOT NULL REFERENCES git_conns(id) ON DELETE CASCADE, number INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'open',   -- open | merged | closed
  author TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', head_ref TEXT NOT NULL DEFAULT '', head_sha TEXT NOT NULL DEFAULT '',
  ci TEXT NOT NULL DEFAULT '', ci_sha TEXT NOT NULL DEFAULT '',          -- success | failure | pending | '' (none)
  updated_at TEXT, merged_at TEXT, PRIMARY KEY (conn_id, number));
CREATE TABLE IF NOT EXISTS git_commits (          -- commits that are linked to a task (first line of the message)
  conn_id INTEGER NOT NULL REFERENCES git_conns(id) ON DELETE CASCADE, sha TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', branch TEXT NOT NULL DEFAULT '',
  at TEXT, PRIMARY KEY (conn_id, sha));
CREATE TABLE IF NOT EXISTS git_links (            -- task <-> pull request (kind pr, ref = number) / commit (kind commit, ref = sha)
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  conn_id INTEGER NOT NULL REFERENCES git_conns(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, ref TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (task_id, conn_id, kind, ref));
CREATE INDEX IF NOT EXISTS git_links_conn ON git_links(conn_id, kind, ref);
CREATE TABLE IF NOT EXISTS git_closes (           -- completions by "fixes #id": once per task; undo = what do_complete filled
  task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, conn_id INTEGER NOT NULL, kind TEXT NOT NULL,
  ref TEXT NOT NULL, undo TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, undone_at TEXT);
CREATE TABLE IF NOT EXISTS git_tags (             -- 2.18.0 (#408): tag names a connection has seen (a NEW one can reach a milestone)
  conn_id INTEGER NOT NULL REFERENCES git_conns(id) ON DELETE CASCADE, name TEXT NOT NULL, seen_at TEXT NOT NULL,
  PRIMARY KEY (conn_id, name));
CREATE TABLE IF NOT EXISTS issue_hooks (          -- 2.18.0 (#408): inbound error-report webhook of a list (one per list)
  list_id INTEGER PRIMARY KEY REFERENCES lists(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,                     -- SHA-256 of the secret in the URL (never stored plain)
  created_by INTEGER, created_at TEXT NOT NULL, last_at TEXT, received INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS issue_reports (        -- fingerprints of error reports: one open ticket per error, repeats counted
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, fp TEXT NOT NULL,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,   -- NULL = only counted (rate limit), no ticket yet
  count INTEGER NOT NULL DEFAULT 1, first_at TEXT NOT NULL, last_at TEXT NOT NULL, PRIMARY KEY (list_id, fp));
CREATE INDEX IF NOT EXISTS issue_reports_task ON issue_reports(task_id);
CREATE TABLE IF NOT EXISTS list_links (           -- 2.7.1 (#410): key links of a project list (overview), ordered
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  title TEXT NOT NULL, url TEXT NOT NULL, sort REAL NOT NULL DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS list_links_list ON list_links(list_id, sort);
CREATE TABLE IF NOT EXISTS list_milestones (      -- 2.7.1 (#410): milestones of a project list (local day; timeline markers)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, day TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS list_milestones_list ON list_milestones(list_id, day);
CREATE TABLE IF NOT EXISTS list_files (           -- 2.7.1 (#410): project files uploaded on the list itself (ATT_DIR/lists/<id>/)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, mime TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
  path TEXT NOT NULL, user_id INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS list_files_list ON list_files(list_id);
CREATE TABLE IF NOT EXISTS list_paperless (       -- 2.7.1 (#410): Paperless documents linked to a project list
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  conn_id INTEGER, doc_id INTEGER, title TEXT NOT NULL DEFAULT '', correspondent TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL DEFAULT '', added_by INTEGER, added_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS list_paperless_list ON list_paperless(list_id);
-- 2.9.0 (#435): CalDAV. App passwords (only the KDF hash; caps = which of CATEGORIES / RELATED-TO the client writes)
CREATE TABLE IF NOT EXISTS app_passwords (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, pw_hash TEXT NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT, last_client TEXT,
  caps TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS app_passwords_user ON app_passwords(user_id);
-- a task as a CalDAV resource: the client's UID and resource name (NULL = made up: kalmido-<id>-<instance>), a parent
-- UID that has not arrived yet, the properties Kalmido has no field for (raw content lines, sent back as they came)
CREATE TABLE IF NOT EXISTS dav_meta (
  task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
  uid TEXT, href TEXT, parent_uid TEXT, extra TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS dav_meta_uid ON dav_meta(uid);
CREATE INDEX IF NOT EXISTS dav_meta_href ON dav_meta(href);
CREATE INDEX IF NOT EXISTS dav_meta_parent ON dav_meta(parent_uid) WHERE parent_uid IS NOT NULL;
-- 2.10.0 (#441): groups of people (admin), their members (oidc_group: synced from that OIDC group claim at every login)
CREATE TABLE IF NOT EXISTS groups (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, oidc_group TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, created_by INTEGER);
CREATE TABLE IF NOT EXISTS group_members (
  group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  added_at TEXT NOT NULL, PRIMARY KEY (group_id, user_id));
CREATE INDEX IF NOT EXISTS group_members_user ON group_members(user_id);
-- a list (list_id) or a folder of its owner (owner_id + folder, subfolders included) shared with a group, with a role
CREATE TABLE IF NOT EXISTS group_shares (
  id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  list_id INTEGER REFERENCES lists(id) ON DELETE CASCADE, owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  folder TEXT, role TEXT NOT NULL DEFAULT 'edit', added_by INTEGER, added_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS group_shares_list ON group_shares(list_id);
CREATE INDEX IF NOT EXISTS group_shares_owner ON group_shares(owner_id);
-- sync-collection: the (href -> ETag) set a sync-token stood for (zlib json), the last ones per person and list
CREATE TABLE IF NOT EXISTS dav_sync (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  token TEXT NOT NULL, state BLOB NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (user_id, list_id, token));
-- 2.17.0 (#442): notes of a list / project (Markdown), tags comma separated
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '', pinned INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER, updated_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS notes_list ON notes(list_id, updated_at);
-- 2.17.0 (#419): team chat: direct messages (a < b, user ids) and one channel per shared list
CREATE TABLE IF NOT EXISTS tchat_rooms (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, list_id INTEGER REFERENCES lists(id) ON DELETE CASCADE,
  a INTEGER REFERENCES users(id) ON DELETE CASCADE, b INTEGER REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, last_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS tchat_dm ON tchat_rooms(a, b) WHERE kind='dm';
CREATE UNIQUE INDEX IF NOT EXISTS tchat_list ON tchat_rooms(list_id) WHERE kind='list';
CREATE TABLE IF NOT EXISTS tchat_msgs (
  id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL REFERENCES tchat_rooms(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, body TEXT NOT NULL,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, created_at TEXT NOT NULL, edited_at TEXT, deleted_at TEXT);
CREATE INDEX IF NOT EXISTS tchat_msgs_room ON tchat_msgs(room_id, id);
CREATE TABLE IF NOT EXISTS tchat_reads (
  room_id INTEGER NOT NULL REFERENCES tchat_rooms(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  last_id INTEGER NOT NULL DEFAULT 0, muted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (room_id, user_id));
CREATE TABLE IF NOT EXISTS tchat_rx (
  message_id INTEGER NOT NULL REFERENCES tchat_msgs(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  emoji TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (message_id, user_id, emoji));
-- 2.17.0 (#443): secret tokens of the e-mail addresses for new tasks (list_id NULL = the person's inbox)
CREATE TABLE IF NOT EXISTS mail_tokens (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  list_id INTEGER REFERENCES lists(id) ON DELETE CASCADE, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS mail_tokens_user ON mail_tokens(user_id);
-- 2.19.0 (#653): the module "Family" (see its section): who comes along to a task, the parents of a kid account, a kid's
-- stars (ledger: + task / bonus, - reward) and rewards, the shop area an item had last time, address books (CardDAV)
CREATE TABLE IF NOT EXISTS task_people (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, user_id));
CREATE INDEX IF NOT EXISTS task_people_user ON task_people(user_id);
CREATE TABLE IF NOT EXISTS kid_parents (
  kid_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, parent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (kid_id, parent_id));
CREATE TABLE IF NOT EXISTS kid_stars (
  id INTEGER PRIMARY KEY, kid_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  delta INTEGER NOT NULL, kind TEXT NOT NULL,   -- task | bonus | reward
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, reward_id INTEGER, title TEXT NOT NULL DEFAULT '',
  by_id INTEGER, at TEXT NOT NULL,              -- task: the completion's completed_at (undo takes exactly that one back)
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS kid_stars_kid ON kid_stars(kid_id, id);
CREATE TABLE IF NOT EXISTS kid_rewards (
  id INTEGER PRIMARY KEY, kid_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '', cost INTEGER NOT NULL, once INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'open',           -- open | requested | redeemed (once)
  requested_at TEXT, decided_by INTEGER, decided_at TEXT, created_by INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS kid_rewards_kid ON kid_rewards(kid_id);
CREATE TABLE IF NOT EXISTS shop_memory (
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, item TEXT NOT NULL,
  section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE, at TEXT NOT NULL, PRIMARY KEY (list_id, item));
CREATE TABLE IF NOT EXISTS contact_srcs (         -- private per user, like cal_subs: url + password sealed (cal_seal)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '', url TEXT NOT NULL, url_hint TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '', password TEXT NOT NULL DEFAULT '',
  list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL, lead INTEGER NOT NULL DEFAULT 7,
  status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '', fails INTEGER NOT NULL DEFAULT 0,
  count INTEGER NOT NULL DEFAULT 0, tried_at TEXT, synced_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contact_links (        -- a contact's birthday / anniversary -> its task (digest = what it was made from)
  src_id INTEGER NOT NULL REFERENCES contact_srcs(id) ON DELETE CASCADE, uid TEXT NOT NULL, kind TEXT NOT NULL,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, digest TEXT NOT NULL DEFAULT '',
  book TEXT NOT NULL DEFAULT '',                  -- the address book's URL (sealed like the source's), for a later contacts module
  PRIMARY KEY (src_id, uid, kind));
-- 2.21.0 (#659): events. Own calendars (shared like lists: view | edit), events in local wall time of their zone (all day:
-- dates, end exclusive), repeat rule + left-out occurrences + changed occurrences (overrides: json, as clients sent them),
-- attendees (a person of this server, a contact or an address), the reminders already sent
CREATE TABLE IF NOT EXISTS ev_cals (
  id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', sort INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, changed_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ev_cals_owner ON ev_cals(owner_id);
CREATE TABLE IF NOT EXISTS ev_cal_members (
  cal_id INTEGER NOT NULL REFERENCES ev_cals(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'view', hidden INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL, PRIMARY KEY (cal_id, user_id));
CREATE INDEX IF NOT EXISTS ev_cal_members_user ON ev_cal_members(user_id);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, cal_id INTEGER NOT NULL REFERENCES ev_cals(id) ON DELETE CASCADE,
  uid TEXT NOT NULL, href TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
  all_day INTEGER NOT NULL DEFAULT 0, start TEXT NOT NULL, end TEXT NOT NULL, tz TEXT NOT NULL DEFAULT '',
  rrule TEXT NOT NULL DEFAULT '', exdates TEXT NOT NULL DEFAULT '', overrides TEXT NOT NULL DEFAULT '',
  reminders TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'confirmed', busy INTEGER NOT NULL DEFAULT 1,
  url TEXT, task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, extra TEXT NOT NULL DEFAULT '',
  seq INTEGER NOT NULL DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
  first_day TEXT NOT NULL DEFAULT '', last_day TEXT NOT NULL DEFAULT '');  -- local days the series spans ('' last = open end)
CREATE INDEX IF NOT EXISTS events_cal ON events(cal_id, deleted_at);
CREATE INDEX IF NOT EXISTS events_uid ON events(uid);
CREATE INDEX IF NOT EXISTS events_task ON events(task_id) WHERE task_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS event_attendees (
  id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
  email TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', partstat TEXT NOT NULL DEFAULT 'needs-action',
  role TEXT NOT NULL DEFAULT 'req');
CREATE INDEX IF NOT EXISTS event_attendees_event ON event_attendees(event_id);
CREATE INDEX IF NOT EXISTS event_attendees_user ON event_attendees(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS event_attendees_contact ON event_attendees(contact_id) WHERE contact_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS ev_reminded (
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE, user_id INTEGER NOT NULL, k TEXT NOT NULL,
  at TEXT NOT NULL, PRIMARY KEY (event_id, user_id, k));
-- 2.21.0 (#658): contacts. Address books (shared like lists: view | edit), one row per vCard (the mapped fields + the
-- properties Kalmido has no field for, sent back as they came), links to tasks (waiting on / responsible outside / about)
CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', src_id INTEGER REFERENCES contact_srcs(id) ON DELETE SET NULL,
  occ_list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL,   -- birthdays + anniversaries become tasks of this list
  created_at TEXT NOT NULL, changed_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS books_owner ON books(owner_id);
CREATE TABLE IF NOT EXISTS book_members (
  book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'view', added_at TEXT NOT NULL, PRIMARY KEY (book_id, user_id));
CREATE INDEX IF NOT EXISTS book_members_user ON book_members(user_id);
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  uid TEXT NOT NULL, href TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'individual',  -- individual | org | group
  fn TEXT NOT NULL DEFAULT '', given TEXT NOT NULL DEFAULT '', family TEXT NOT NULL DEFAULT '', middle TEXT NOT NULL DEFAULT '',
  prefix TEXT NOT NULL DEFAULT '', suffix TEXT NOT NULL DEFAULT '', nickname TEXT NOT NULL DEFAULT '',
  org TEXT NOT NULL DEFAULT '', dept TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
  emails TEXT NOT NULL DEFAULT '[]', phones TEXT NOT NULL DEFAULT '[]', addresses TEXT NOT NULL DEFAULT '[]', urls TEXT NOT NULL DEFAULT '[]',
  bday TEXT NOT NULL DEFAULT '', anniversary TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
  groups TEXT NOT NULL DEFAULT '[]', photo TEXT NOT NULL DEFAULT '', version TEXT NOT NULL DEFAULT '3.0',
  extra TEXT NOT NULL DEFAULT '', src_digest TEXT NOT NULL DEFAULT '', search TEXT NOT NULL DEFAULT '',
  created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS contacts_book ON contacts(book_id);
CREATE INDEX IF NOT EXISTS contacts_uid ON contacts(uid);
CREATE TABLE IF NOT EXISTS contact_tasks (
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'about',   -- waiting | responsible | about
  added_by INTEGER, added_at TEXT NOT NULL, PRIMARY KEY (contact_id, task_id));
CREATE INDEX IF NOT EXISTS contact_tasks_task ON contact_tasks(task_id);
CREATE TABLE IF NOT EXISTS contact_occ (   -- a contact's birthday / anniversary -> its task (like contact_links for own contacts)
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE, kind TEXT NOT NULL,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, digest TEXT NOT NULL DEFAULT '', PRIMARY KEY (contact_id, kind));
-- sync-collection of event calendars + address books (coll: e<id> | inv | b<id>), like dav_sync
CREATE TABLE IF NOT EXISTS dav_sync2 (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, coll TEXT NOT NULL,
  token TEXT NOT NULL, state BLOB NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (user_id, coll, token));
-- 2.22.0 (#663): "Home & life". journal: one private entry per person and day (module "review");
-- contact_care: "stay in touch" per person and contact (module "care": every N days, the last time, a note);
-- kk_conns: the read-later connection of a person to Karakeep (module "reading"; the API key sealed like a Paperless token)
CREATE TABLE IF NOT EXISTS journal (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, day TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
  mood INTEGER, updated_at TEXT NOT NULL, PRIMARY KEY (user_id, day));
CREATE TABLE IF NOT EXISTS contact_care (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  every_days INTEGER NOT NULL DEFAULT 0, last TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, contact_id));
-- 2.22.0 (#697): a one-time link to set one's own password (an invitation of a new person, or a reset by an admin):
-- only the SHA-256 of the token is stored, 7 days, used once; one per person (a new one replaces it)
CREATE TABLE IF NOT EXISTS user_invites (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, token_hash TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'invite',
  created_by INTEGER, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, sent_at TEXT, used_at TEXT);
-- 2.22.0 (#740): "Share folder": the owner's folder is shared with a person: its lists now and every list that comes into it later
CREATE TABLE IF NOT EXISTS folder_people (
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, folder TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL DEFAULT 'edit', created_at TEXT NOT NULL,
  PRIMARY KEY (owner_id, folder, user_id));
-- 2.22.0 (#752): organisations. People belong to 1..n of them; the instance setting people_visibility decides whom a
-- person sees at all: all | org (only people of their organisations) | contacts (only people they are connected with)
CREATE TABLE IF NOT EXISTS orgs (id INTEGER PRIMARY KEY, name TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS org_members (
  org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (org_id, user_id));
CREATE INDEX IF NOT EXISTS org_members_user ON org_members(user_id);
CREATE TABLE IF NOT EXISTS kk_conns (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, url TEXT NOT NULL, token TEXT NOT NULL DEFAULT '',
  list_id INTEGER, source TEXT NOT NULL DEFAULT '', archive INTEGER NOT NULL DEFAULT 1, synced_at TEXT, error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
-- 2.23.0 (#463): clients (customers) of an organisation: lists belong to one (lists.client_id); hours, budget and the
-- timesheet per client. Only the people of the client's organisation see it (org_id NULL: its creator and the admins)
CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY, org_id INTEGER REFERENCES orgs(id) ON DELETE SET NULL, name TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '',
  color TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', rate REAL, budget_h REAL, budget_amount REAL,
  archived INTEGER NOT NULL DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS clients_org ON clients(org_id);
-- 2.23.0 (#463): forms -> tasks: a link (/f/<token>, the token sealed, looked up by its SHA-256) that creates a task in the
-- list; access 'org' = signed-in people of the list owner's organisations, 'public' = anyone with the link
CREATE TABLE IF NOT EXISTS forms (
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, token TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL, intro TEXT NOT NULL DEFAULT '', access TEXT NOT NULL DEFAULT 'org', section_id INTEGER,
  ask_email INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1, count INTEGER NOT NULL DEFAULT 0, last_at TEXT,
  created_by INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS forms_list ON forms(list_id);
"""
# Bumped when the database layout changes (stored in PRAGMA user_version). A backup can be restored when its
# schema version is not newer than this one (older ones are migrated by init_db).
SCHEMA_VERSION = 2  # package B only added tables + a column: older versions can still restore its backups
# triggers / views a restored database may contain (anything else is refused: it would run inside this app)
SCHEMA_TRIGGERS = {"time_task_list", "time_task_title"}
# time_entries.task_title follows a rename only for entries of users who still see the task (a former
# member keeps the old snapshot and never learns new titles). Re-created on every start (init_db).
TIME_TITLE_TRIGGER = """CREATE TRIGGER time_task_title AFTER UPDATE OF title ON tasks WHEN NEW.title IS NOT OLD.title
BEGIN UPDATE time_entries SET task_title=NEW.title WHERE task_id=NEW.id AND user_id IN
  (SELECT owner_id FROM lists WHERE id=NEW.list_id UNION SELECT user_id FROM list_members WHERE list_id=NEW.list_id
   AND (role!='participant' OR user_id IS NEW.assignee_id)); END"""  # 1.10.0: participants only while it is theirs
# additive migrations: (table, column, ddl)
MIGRATIONS = [
    ("tasks", "pinned", "ALTER TABLE tasks ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"),
    ("tasks", "start", "ALTER TABLE tasks ADD COLUMN start TEXT"),          # timeline: first day (local date)
    ("tasks", "duration", "ALTER TABLE tasks ADD COLUMN duration INTEGER"),  # minutes, week/day calendar blocks
    ("habits", "per_week", "ALTER TABLE habits ADD COLUMN per_week INTEGER NOT NULL DEFAULT 0"),  # 0 = fixed weekdays
    ("habit_logs", "note", "ALTER TABLE habit_logs ADD COLUMN note TEXT NOT NULL DEFAULT ''"),
    # multi-user (2026-09-26)
    ("lists", "owner_id", "ALTER TABLE lists ADD COLUMN owner_id INTEGER"),
    ("tasks", "created_by", "ALTER TABLE tasks ADD COLUMN created_by INTEGER"),
    ("tasks", "assignee_id", "ALTER TABLE tasks ADD COLUMN assignee_id INTEGER"),
    ("habits", "user_id", "ALTER TABLE habits ADD COLUMN user_id INTEGER"),
    ("pomos", "user_id", "ALTER TABLE pomos ADD COLUMN user_id INTEGER"),
    ("filters", "user_id", "ALTER TABLE filters ADD COLUMN user_id INTEGER"),
    # comments, activity, link (2026-09-26)
    ("tasks", "url", "ALTER TABLE tasks ADD COLUMN url TEXT"),                         # website link (http/https)
    ("attachments", "comment_id", "ALTER TABLE attachments ADD COLUMN comment_id INTEGER"),  # file of a comment
    ("tasks", "assigned_by", "ALTER TABLE tasks ADD COLUMN assigned_by INTEGER"),       # who set the assignee (pushes)
    # package 1 (2026-09-26): statistics count completions for the person who completed; calendar feed
    ("tasks", "completed_by", "ALTER TABLE tasks ADD COLUMN completed_by INTEGER"),
    ("users", "ical_token", "ALTER TABLE users ADD COLUMN ical_token TEXT"),           # secret of GET /ical/<uid>.<token>.ics
    # time tracking (2026-09-27): hourly rate of a list (reports / CSV amount), set by the owner
    ("lists", "rate", "ALTER TABLE lists ADD COLUMN rate REAL"),
    # package 3 (2026-09-27): project status of a list ('' = none; history in list_status)
    ("lists", "status", "ALTER TABLE lists ADD COLUMN status TEXT NOT NULL DEFAULT ''"),
    ("lists", "status_note", "ALTER TABLE lists ADD COLUMN status_note TEXT NOT NULL DEFAULT ''"),
    ("lists", "status_by", "ALTER TABLE lists ADD COLUMN status_by INTEGER"),
    ("lists", "status_at", "ALTER TABLE lists ADD COLUMN status_at TEXT"),
    # security audit (2026-09-28): Paperless only for users an admin allows (migration: existing admins)
    ("users", "paperless_access", "ALTER TABLE users ADD COLUMN paperless_access INTEGER NOT NULL DEFAULT 0"),
    # package A (2026-09-29): two-factor (TOTP secret encrypted, last used time step = no replay), passkeys (random
    # user handle), OIDC (linked subject "issuer|sub", optional e-mail for linking), how a session logged in
    ("users", "totp_secret", "ALTER TABLE users ADD COLUMN totp_secret TEXT"),
    ("users", "totp_step", "ALTER TABLE users ADD COLUMN totp_step INTEGER NOT NULL DEFAULT 0"),
    ("users", "webauthn_handle", "ALTER TABLE users ADD COLUMN webauthn_handle TEXT"),
    ("users", "oidc_subject", "ALTER TABLE users ADD COLUMN oidc_subject TEXT"),
    ("users", "email", "ALTER TABLE users ADD COLUMN email TEXT"),
    ("sessions", "via", "ALTER TABLE sessions ADD COLUMN via TEXT NOT NULL DEFAULT 'password'"),
    # package B (2026-09-29): checklist mode of a list (done items stay in a "Done" section, reusable)
    ("lists", "checklist", "ALTER TABLE lists ADD COLUMN checklist INTEGER NOT NULL DEFAULT 0"),
    # package D2 (2026-09-29): "Move dependent tasks along" (Gantt auto-shift) per list, set by the owner
    ("lists", "dep_shift", "ALTER TABLE lists ADD COLUMN dep_shift INTEGER NOT NULL DEFAULT 0"),
    # package D2: list type list | checklist | project (checklist stays as a column, kept in step: kind='checklist'
    # <=> checklist=1). Only project lists get time tracking, dependencies, custom fields and progress / status.
    ("lists", "kind", "ALTER TABLE lists ADD COLUMN kind TEXT NOT NULL DEFAULT 'list'"),
    # 1.6.1: when a list was archived (UTC, shown in the "Archived" view; NULL = not archived / archived before 1.6.1)
    ("lists", "archived_at", "ALTER TABLE lists ADD COLUMN archived_at TEXT"),
    # 1.9.0: profile picture: "p:<preset>" (static/avatars/<preset>.svg) or "u:<token>" (ATT_DIR/avatars/u<id>-<token>.jpg)
    ("users", "avatar", "ALTER TABLE users ADD COLUMN avatar TEXT"),
    # 2.0.0: agents (users.kind 'agent', see "agents"), tidy suggestions, "Agent may tidy up entries" per list, agent webhooks
    ("users", "kind", "ALTER TABLE users ADD COLUMN kind TEXT NOT NULL DEFAULT 'user'"),
    ("comments", "suggestion", "ALTER TABLE comments ADD COLUMN suggestion TEXT"),
    ("lists", "agent_tidy", "ALTER TABLE lists ADD COLUMN agent_tidy TEXT NOT NULL DEFAULT 'off'"),
    ("webhooks", "agent", "ALTER TABLE webhooks ADD COLUMN agent INTEGER NOT NULL DEFAULT 0"),
    # 2.0.2: own list icon: "p:<preset>" (static/avatars/<preset>.svg, or the app icon) or "u:<token>"
    # (ATT_DIR/listicons/l<id>-<token>.png); NULL = emoji in the name / colour dot as before
    ("lists", "icon", "ALTER TABLE lists ADD COLUMN icon TEXT"),
    # 2.0.2: the task an agent says it works on (PUT /api/v1/agent/status {task_id}) -> "Claude is writing ..." there
    ("agents", "status_task", "ALTER TABLE agents ADD COLUMN status_task INTEGER"),
    # 2.0.5: rate limit of the "dismiss" pushes (close notifications handled on another device) per device
    ("push_subs", "dismiss_at", "ALTER TABLE push_subs ADD COLUMN dismiss_at REAL NOT NULL DEFAULT 0"),
    ("push_subs", "dismiss_day", "ALTER TABLE push_subs ADD COLUMN dismiss_day TEXT NOT NULL DEFAULT ''"),
    ("push_subs", "dismiss_n", "ALTER TABLE push_subs ADD COLUMN dismiss_n INTEGER NOT NULL DEFAULT 0"),
    # 2.1.0 (#180): which Paperless connection a link belongs to (NULL / 0 = the legacy one from the environment) and who
    # added it (a pending upload is resolved with that person's token)
    ("paperless_links", "conn_id", "ALTER TABLE paperless_links ADD COLUMN conn_id INTEGER"),
    ("paperless_links", "added_by", "ALTER TABLE paperless_links ADD COLUMN added_by INTEGER"),
    # 2.1.0 (#335): "Waiting on external": since when (NULL = not waiting), who / what (note), follow-up date (local day),
    # who set it, the follow-up day that already fired (reminder + News + agent event followup_due, once per date)
    ("tasks", "waiting_at", "ALTER TABLE tasks ADD COLUMN waiting_at TEXT"),
    ("tasks", "wait_note", "ALTER TABLE tasks ADD COLUMN wait_note TEXT NOT NULL DEFAULT ''"),
    ("tasks", "wait_until", "ALTER TABLE tasks ADD COLUMN wait_until TEXT"),
    ("tasks", "wait_by", "ALTER TABLE tasks ADD COLUMN wait_by INTEGER"),
    ("tasks", "wait_fired", "ALTER TABLE tasks ADD COLUMN wait_fired TEXT NOT NULL DEFAULT ''"),
    # 2.1.1 (#326): usage limits of an agent (json {period, metric, soft, hard}; '' = none) and the alerts already sent in
    # the current period (json {period: key, levels: [...]})
    ("agents", "usage_limits", "ALTER TABLE agents ADD COLUMN usage_limits TEXT NOT NULL DEFAULT ''"),
    ("agents", "usage_alerted", "ALTER TABLE agents ADD COLUMN usage_alerted TEXT NOT NULL DEFAULT ''"),
    # 2.3.0 (#260-#263): agent proposals. Who may ask the agent (off | shared | all); a proposal job's kind, input (what the
    # person sent), the validated proposal, its state (requested | ready | applied | discarded), the undo record, its list
    ("agents", "proposals", "ALTER TABLE agents ADD COLUMN proposals TEXT NOT NULL DEFAULT 'shared'"),
    ("agent_jobs", "kind", "ALTER TABLE agent_jobs ADD COLUMN kind TEXT"),
    ("agent_jobs", "input", "ALTER TABLE agent_jobs ADD COLUMN input TEXT"),
    ("agent_jobs", "proposal", "ALTER TABLE agent_jobs ADD COLUMN proposal TEXT"),
    ("agent_jobs", "prop_state", "ALTER TABLE agent_jobs ADD COLUMN prop_state TEXT NOT NULL DEFAULT ''"),
    ("agent_jobs", "applied", "ALTER TABLE agent_jobs ADD COLUMN applied TEXT"),
    ("agent_jobs", "list_id", "ALTER TABLE agent_jobs ADD COLUMN list_id INTEGER"),
    # 2.4.0 (#340): ticket types. A task's type ('' | bug | feature | task); per list: ticket types on (0 / 1) and the
    # note templates of new bug / feature tickets (json {bug, feature}; a missing / empty one = the built-in text)
    ("tasks", "ttype", "ALTER TABLE tasks ADD COLUMN ttype TEXT NOT NULL DEFAULT ''"),
    ("lists", "tickets", "ALTER TABLE lists ADD COLUMN tickets INTEGER NOT NULL DEFAULT 0"),
    ("lists", "ticket_tpl", "ALTER TABLE lists ADD COLUMN ticket_tpl TEXT NOT NULL DEFAULT ''"),
    # 2.4.1 (#377): runtime preferences of an agent (json {model, autocompact, autocompact_pct, nightly_reset}; '' = the
    # agent's defaults) and the "Reset now" counter; Kalmido only stores them, the agent host applies them
    ("agents", "runtime", "ALTER TABLE agents ADD COLUMN runtime TEXT NOT NULL DEFAULT ''"),
    ("agents", "reset_seq", "ALTER TABLE agents ADD COLUMN reset_seq INTEGER NOT NULL DEFAULT 0"),
    # 2.4.1 (#375): the agent's last event poll (UTC ISO, "offline" after AGENT_OFFLINE_S) and its "typing" signal to
    # one person in the chat (user id + until, epoch seconds)
    ("agents", "last_poll_at", "ALTER TABLE agents ADD COLUMN last_poll_at TEXT"),
    ("agents", "typing_user", "ALTER TABLE agents ADD COLUMN typing_user INTEGER"),
    ("agents", "typing_until", "ALTER TABLE agents ADD COLUMN typing_until REAL NOT NULL DEFAULT 0"),
    # 2.4.1 (#379): the one agent that tidies up a list (NULL = the first agent with edit rights, see tidy_agent_of)
    ("lists", "tidy_agent", "ALTER TABLE lists ADD COLUMN tidy_agent INTEGER"),
    # 2.6.1 (#404): the bell "custom": my own choice of events for this list, json {event: {news: 0|1, push: 0|1}}
    ("list_bell", "custom", "ALTER TABLE list_bell ADD COLUMN custom TEXT"),
    # 2.7.0 (#412): the due date is a deadline (0 no, 1 yes, 2 yes + on Today from the first reminder on)
    ("tasks", "deadline", "ALTER TABLE tasks ADD COLUMN deadline INTEGER NOT NULL DEFAULT 0"),
    # 2.7.0 (#413): nags = the reminder repeats until the task is done. tasks.nag: '' = the list's default, 'off', or an
    # interval (NAG_VALUES); tasks.nag_at = "<due> <time>|<last nag>" (dedupe, a new date starts over); lists.nag = the default
    ("tasks", "nag", "ALTER TABLE tasks ADD COLUMN nag TEXT NOT NULL DEFAULT ''"),
    ("tasks", "nag_at", "ALTER TABLE tasks ADD COLUMN nag_at TEXT NOT NULL DEFAULT ''"),
    ("lists", "nag", "ALTER TABLE lists ADD COLUMN nag TEXT NOT NULL DEFAULT ''"),
    # 2.7.0 (#407): hours of a working day / shift for this list (NULL = the instance's value, admin setting time_day_h)
    ("lists", "day_hours", "ALTER TABLE lists ADD COLUMN day_hours REAL"),
    # 2.7.1 (#410): the description of a project list (Markdown, its overview)
    ("lists", "description", "ALTER TABLE lists ADD COLUMN description TEXT NOT NULL DEFAULT ''"),
    # 2.7.2 (#422): when the agent fetched a person's chat message (event poll, MCP, webhook delivered, chat read)
    ("agent_chat", "delivered_at", "ALTER TABLE agent_chat ADD COLUMN delivered_at TEXT"),
    # 2.7.2 (#420): a personal agent belongs to the person who created it (NULL = a team agent of the admins)
    ("agents", "owner_id", "ALTER TABLE agents ADD COLUMN owner_id INTEGER"),
    ("agents", "admin_paused", "ALTER TABLE agents ADD COLUMN admin_paused INTEGER NOT NULL DEFAULT 0"),  # its owner cannot resume it
    # 2.10.0 (#441): a member row keeps the personal role (own_role, NULL = only via groups) and the best role via groups
    # (grole); role = the higher of both (see grp_sync). Tasks can be assigned to a group (whoever has time takes it).
    ("list_members", "own_role", "ALTER TABLE list_members ADD COLUMN own_role TEXT"),
    ("list_members", "grole", "ALTER TABLE list_members ADD COLUMN grole TEXT"),
    ("tasks", "assignee_group_id", "ALTER TABLE tasks ADD COLUMN assignee_group_id INTEGER"),
    # 2.11.0 (#440 follow-up): the day plan's slot "YYYY-MM-DDTHH:MM" (local); planning never touches due / deadline
    ("tasks", "plan_start", "ALTER TABLE tasks ADD COLUMN plan_start TEXT"),
    # 2.13.1 (#471): "Agent reads every comment": the agents that get a 'comment' event for every comment of a person in
    # this list (comma separated user ids; '' = none; NULL = the default: the list's tidy agent while tidying is on)
    ("lists", "agent_listen", "ALTER TABLE lists ADD COLUMN agent_listen TEXT"),
    # 2.14.0 (#425): the list's columns (JSON array of column keys in order, the same for every member; NULL = the default)
    ("lists", "col_cfg", "ALTER TABLE lists ADD COLUMN col_cfg TEXT"),
    # 2.15.0 (#479): an agent's scopes + address restriction (copied onto its tokens), a token's address restriction,
    # an agent's request waiting for approval (JSON: method, path, query, body), the scope an audited request needed
    ("agents", "scopes", "ALTER TABLE agents ADD COLUMN scopes TEXT NOT NULL DEFAULT ''"),
    ("agents", "allowed_ips", "ALTER TABLE agents ADD COLUMN allowed_ips TEXT NOT NULL DEFAULT ''"),
    ("api_tokens", "allowed_ips", "ALTER TABLE api_tokens ADD COLUMN allowed_ips TEXT NOT NULL DEFAULT ''"),
    ("agent_jobs", "approval", "ALTER TABLE agent_jobs ADD COLUMN approval TEXT"),
    ("agent_audit", "scope", "ALTER TABLE agent_audit ADD COLUMN scope TEXT NOT NULL DEFAULT ''"),
    # 2.18.0 (#430): a task can be a MILESTONE (ms = 1: a diamond with a date, checkable, no assignee needed; shown in the
    # list, Kanban, calendar and timeline). The milestones of the project overview (list_milestones, 2.7.1) are migrated
    # into such tasks once. milestone_id: the milestone (a task of the same list with ms = 1) a task belongs to, e.g.
    # the release / version it ships in ("Software 2": progress, burndown, release notes per milestone).
    ("tasks", "ms", "ALTER TABLE tasks ADD COLUMN ms INTEGER NOT NULL DEFAULT 0"),
    ("tasks", "milestone_id", "ALTER TABLE tasks ADD COLUMN milestone_id INTEGER"),
    # 2.18.0 (#408): the project type of a list ('' = none / a plain project, else a key of PTYPES: agency | software |
    # private), stored when a project is created from a type and changeable later in the list dialog
    ("lists", "ptype", "ALTER TABLE lists ADD COLUMN ptype TEXT NOT NULL DEFAULT ''"),
    # 2.18.0 (#408): when a repository connection took its tag baseline (NULL = not yet: the next poll only records the
    # existing tags; only tags seen after that can complete a milestone)
    ("git_conns", "tags_at", "ALTER TABLE git_conns ADD COLUMN tags_at TEXT"),
    # 2.19.0 (#653): the module "Family". tasks.fam: json of a birthday / anniversary / household deadline ('' = none);
    # tasks.rotation: json {who, mode, i, wk} of a household rotation ('' = none); tasks.stars: what a kid gets for it
    # (NULL = 1); lists.family: '' | shopping | meals | birthdays | household | packing; users.kid: a kid account
    ("tasks", "fam", "ALTER TABLE tasks ADD COLUMN fam TEXT NOT NULL DEFAULT ''"),
    ("tasks", "rotation", "ALTER TABLE tasks ADD COLUMN rotation TEXT NOT NULL DEFAULT ''"),
    ("tasks", "stars", "ALTER TABLE tasks ADD COLUMN stars INTEGER"),
    ("lists", "family", "ALTER TABLE lists ADD COLUMN family TEXT NOT NULL DEFAULT ''"),
    ("contact_links", "book", "ALTER TABLE contact_links ADD COLUMN book TEXT NOT NULL DEFAULT ''"),
    ("users", "kid", "ALTER TABLE users ADD COLUMN kid INTEGER NOT NULL DEFAULT 0"),
    # 2.22.0 (#663): "Home & life". lists.life: '' | contracts | home | health | travel | reading (what the list is for);
    # lists.trip: json {from, to, where} of a trip list; tasks.fam also holds the kinds contract / device / upkeep / health /
    # bookmark (see kalmido/life/model.py)
    ("lists", "life", "ALTER TABLE lists ADD COLUMN life TEXT NOT NULL DEFAULT ''"),
    ("lists", "trip", "ALTER TABLE lists ADD COLUMN trip TEXT NOT NULL DEFAULT ''"),
    # 2.23.0 (#463): package "Team, family, clients". lists.client_id: the client a list belongs to; tasks.approval: ''
    # (no approval) | pending | approved | changes | rejected, tasks.approver_id: who decides; orgs.domains: e-mail domains
    # of an organisation (self-registration, #711); users.signup: '' | confirm (e-mail not confirmed yet) | pending (waits
    # for an admin)
    ("lists", "client_id", "ALTER TABLE lists ADD COLUMN client_id INTEGER"),
    ("tasks", "approval", "ALTER TABLE tasks ADD COLUMN approval TEXT NOT NULL DEFAULT ''"),
    ("tasks", "approver_id", "ALTER TABLE tasks ADD COLUMN approver_id INTEGER"),
    ("orgs", "domains", "ALTER TABLE orgs ADD COLUMN domains TEXT NOT NULL DEFAULT ''"),
    ("users", "signup", "ALTER TABLE users ADD COLUMN signup TEXT NOT NULL DEFAULT ''"),
]
INDEXES = """
CREATE INDEX IF NOT EXISTS lists_owner ON lists(owner_id);
CREATE INDEX IF NOT EXISTS tasks_assignee ON tasks(assignee_id);
CREATE INDEX IF NOT EXISTS habits_user ON habits(user_id);
CREATE INDEX IF NOT EXISTS pomos_user ON pomos(user_id);
CREATE INDEX IF NOT EXISTS filters_user ON filters(user_id);
CREATE INDEX IF NOT EXISTS task_tags_user ON task_tags(user_id, tag);
CREATE UNIQUE INDEX IF NOT EXISTS tasks_tt_user ON tasks(created_by, tt_id) WHERE tt_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS comments_task ON comments(task_id);
CREATE INDEX IF NOT EXISTS activity_task ON activity(task_id, id);
CREATE INDEX IF NOT EXISTS attachments_comment ON attachments(comment_id) WHERE comment_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id, id);
CREATE INDEX IF NOT EXISTS notifications_task ON notifications(task_id);
CREATE INDEX IF NOT EXISTS tasks_completed_by ON tasks(completed_by, completed_at) WHERE completed_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS templates_user ON templates(user_id);
CREATE INDEX IF NOT EXISTS push_subs_user ON push_subs(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS users_oidc ON users(oidc_subject) WHERE oidc_subject IS NOT NULL;
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
"""
MAX_DEPTH = 3  # task > subtask > sub-subtask
# per user (table user_settings)
USER_DEFAULTS = {
    "allday_time": "09:00",     # reminder base time for all-day tasks
    "default_reminder": "0",    # reminder preset for new timed tasks ('' = none)
    "digest_time": "",          # daily "due today" push (HH:MM, '' = off)
    "digest_sent": "",
    "digest_mail": "0",         # 2.17.0 (#443): the daily summary also by e-mail (at digest_time; needs SMTP + an address)
    "digest_mail_sent": "",
    "mail_from_me": "0",        # 2.17.0 (#443): mails from my own address to the plain task address land in my inbox
    # 2.17.0 (#475): the dashboard behind the logo, json {"order": [widget keys], "hidden": [widget keys]} ('' = default)
    "dashboard": "",
    "work_start": "09:00", "work_end": "17:00",  # 2.10.0 (#440): working hours of the day planner
    "review_time": "",          # 2.10.0 (#440): evening review push (HH:MM, '' = off)
    "review_sent": "",
    "care_sent": "",            # 2.22.0 (#663): the day of the last "Time to get in touch" push
    "today_inbox": "0",         # 2.22.0 (#681): Today also shows the inbox (own section, counted in Today's number)
    "pomo_focus": "25", "pomo_short": "5", "pomo_long": "15", "pomo_long_every": "4",
    "ntfy_topic": "",           # set by an admin (a user could otherwise push into someone else's topic)
    "push_priority": "4",       # priority of every push to this user: 3 normal, 4 high, 5 urgent (ntfy + Web Push)
    # ntfy | webpush | both. Web Push (default, also for existing users since 1.1.3): while the user has no
    # subscribed device (or no device accepted the push), it goes to the ntfy topic instead.
    "push_channel": "webpush",
    # 1.5.1: "Show completed" per view (route key like "today", "l:12", "f:3", "tag:x"; "cal" = the calendar) -> 0/1,
    # json object. 1.8.1: the global switch show_completed is gone, a view without an entry shows its completed tasks
    "show_done_views": "{}",
    # modules that can be switched off in the settings (hidden from nav, data stays)
    # collab = activity, mentions, News feed, sharing / assigning UI (2.0.6: comments are a module of their own)
    # comments = comments on tasks (2.0.6, #315): personal timestamped notes; with collab in shared lists also
    #            @mentions, pushes and News
    # progress = progress bar in the list header + the "Where is it stuck?" overview
    # deps = dependencies ("waiting on", timeline arrows + linking, unblock notifications); fields = custom fields
    "features": "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,events,contacts",
    "nav_order": "tasks,cal,matrix,habits,pomo",   # order of the mobile tab bar / desktop rail
    "folders": "[]",            # json list: folder order in the sidebar (also keeps empty folders); 2.4.0: paths "A/b"
    "folders_closed": "[]",     # 2.4.0 (#361): json list of the folder paths folded in the sidebar (all devices)
    "comment_order": "old",     # 2.4.2 (#386): comments in the task panel: old = oldest first (box below), new = newest first (box above)
    # 2.4.2 (#391): sharing with agents, per agent id (string): {"auto": [agent ids that get my new lists],
    # "skip": {"<agent id>": [list ids I stopped sharing with it]}}; written only by /api/agents/<aid>/share-all + /autoshare
    # and the member routes (server-only)
    "agent_share": "{}",
    "features_rev": "10",       # one-shot migrations of the features list
    "paperless_keep": "0",      # 1 = keep the local attachment after it was consumed by Paperless
    "lang": "en",               # UI + push language: en or a static/i18n/<code>.json
    "ical_scope": "all",        # calendar feed: all = every visible open task with a date, mine = mine / assigned to me
    "ical_alarms": "1",         # calendar feed: reminders as VALARM
    # time tracking
    "time_rounding": "0",       # minutes: every entry is rounded UP in reports / CSV / timesheet (0 = off)
    "time_remind_h": "4",       # push "timer still running" after N hours (0 = off)
    "time_autostop_h": "12",    # stop a forgotten timer after N hours, end = start + N h (0 = off)
    "time_focus": "1",          # finished focus / stopwatch sessions on a task become time entries
    "time_currency": "€",       # amounts (hourly rate of a list)
    "time_target": "0",         # daily target in hours (0 = none)
    "capacity_h": "",           # 2.23.0 (#463): working hours per week for the workload view ('' = 5 x the hours per day)
    # package 3
    "hide_blocked_today": "0",  # 1 = tasks waiting on an open blocker are left out of "Today"
    "progress_subtasks": "0",   # 1 = the list progress counts subtasks too (else only main tasks)
    "hide_progress": "",        # D2: comma list of list ids whose progress bar this user hid (the "x" on the bar)
    # 2.6.1 (#401): 1 = date, time, repeat and reminder changes wait for OK (default: they apply at once, with Undo)
    "date_confirm": "0",
    # 2.7.0 (#413): quiet hours of nags (HH:MM each, '' = none): no nag push in between, it comes when they end
    "quiet_from": "22:00", "quiet_to": "07:00",
    # 2.6.1 (#402): comma list of agent ids whose status dot this user hid in the header ('' = every agent shown)
    "agents_hidden": "",
    # D3: the roadmap ("All" as a timeline), json: {v: list|timeline, z: week|month|quarter, po: projects only (null = auto),
    # hd: hide done, who: assignee filter, ls: list ids (empty = all), def: auto|c|e (collapse default), t: {group: 0|1},
    # nd (2.0.6): "No date" rows in open lists (default on)}
    "roadmap": "",
    # v1.1
    "evcals_hidden": "[]",      # 2.21.0 (#659): json list of the event calendars I hid from my views (server-only)
    "purpose": "",              # 2.19.0 (#653): what the person uses Kalmido for (me | family | team | software; server-only)
    "celebrate": "1",           # the heron celebrates an emptied Today / a completed list or project
    "cal_today": "1",           # "Events today" block on Today (external calendar subscriptions)
    "tour": "done",             # welcome tour: pending (new users) | done; existing users never see it
    "onboard": "done",          # "Getting started" list: pending (new users, created on first start) | done
    "sample_ask": "1",          # 1.8.0: the welcome tour offers the sample project (0 = decided in the setup / created once)
    # 1.9.0: which events create a News item (groups, see NEWS_GROUPS). Default: everything but "completed by others"
    "news_kinds": "mention,assign,comment,unblock,share,status",
    # 2.1.0 (#317): the rest of the notification matrix, json {event: {news?, push?}} (see NOTIF_ROWS; '' = defaults)
    "notify": "",
}
# global, server-internal (table settings); the legacy single-user rows stay there untouched
GLOBAL_DEFAULTS = {
    "version": "1",             # bumped on every change; clients poll it
    "collab_all": "1",          # admin: collaboration for everyone (0 = no sharing / mentions / News / pushes; data stays;
                                #        2.0.6: comments stay as personal notes)
    "time_all": "1",            # admin: time tracking for everyone (0 = module off for all; entries stay)
    "update_check": "1",        # admin: daily check for a new release (see UPDATE_URL)
    "update_info": "",          # json cache of the last check: {checked_at, latest, url, error}
    "ntfy_inbox_since": "",     # last imported ntfy message id (or unix time on first start)
    # admin alerts via ntfy (see "admin alerts"; KALMIDO_ADMIN_ALERTS=0 / KALMIDO_ADMIN_TOPIC override)
    "aa_on": "1",               # admin: operational alerts to the admins
    "aa_topic": "",             # '' = every admin's own ntfy topic, else one shared admin topic
    "aa_prio": "4",             # ntfy priority 3 / 4 / 5
    "aa_kinds": "update,webpush,watchdog,integration,security,storage",
    "aa_mode": "instant",       # instant | digest (one summary a day at aa_digest_time)
    "aa_digest_time": "08:00",
    "aa_cooldown_h": "6",       # identical alert (kind + key) at most once per N hours
    "aa_max_hour": "10",        # at most N alerts per hour (the rest is only listed)
    "aa_disk_pct": "5",         # low disk: free space below N % ...
    "aa_disk_mb": "1024",       # ... or below N MB (0 = that check off)
    "aa_integ_min": "15",       # Paperless / ntfy inbox failing for N minutes
    "aa_update_notified": "",   # last version an update alert went out for
    "aa_digest_sent": "",       # day of the last daily summary
    "cal_allow_hosts": "",      # admin: internal hosts calendar subscriptions may reach ("host, host:port")
    # sign-in (package A): 2FA policy for built-in logins, passwordless passkey login, OIDC auto-create
    "twofa_required": "0",      # admin: users with a password must use a second factor (enrol at the next login)
    "passkey_login": "1",       # admin: passkeys may log in without the password (user verification required)
    "signup_mode": "off",       # 2.23.0 (#711): self-registration on the login page: off | domain | approval | open
    "signup_domains": "",       # ... the e-mail domains allowed in the mode "domain" (comma separated)
    "oidc_autocreate": "0",     # admin: first OIDC login without a matching user creates one (off: admin creates users)
    # automatic backups (see "backups"; KALMIDO_BACKUPS=0 turns the feature off)
    "bk_on": "0", "bk_time": "03:30", "bk_keep_daily": "14", "bk_keep_weekly": "8",
    "bk_encrypt": "0", "bk_pass": "",            # passphrase sealed with the server key; never sent to a client
    "bk_last_day": "", "bk_last_ok": "", "bk_last_name": "", "bk_last_error": "", "bk_last_error_at": "",
    "bk_enabled_at": "",
    "public_links": "1",        # admin: public read-only links of lists (KALMIDO_PUBLIC_LINKS=0 turns them off for good)
}
PRIO = {0: "", 1: "niedrig", 3: "mittel", 5: "hoch"}
