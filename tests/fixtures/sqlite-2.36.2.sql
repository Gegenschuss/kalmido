-- Kalmido 2.36.2 SQLite schema (the last version before Postgres), for tests/mk_sqlite_fixture.py. Generated from a fresh 2.36.2 install.
PRAGMA user_version=2;
CREATE TABLE lists (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '',
  folder TEXT NOT NULL DEFAULT '', sort REAL NOT NULL DEFAULT 0,
  view TEXT NOT NULL DEFAULT 'list', is_inbox INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, owner_id INTEGER, rate REAL, status TEXT NOT NULL DEFAULT '', status_note TEXT NOT NULL DEFAULT '', status_by INTEGER, status_at TEXT, checklist INTEGER NOT NULL DEFAULT 0, dep_shift INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'list', archived_at TEXT, agent_tidy TEXT NOT NULL DEFAULT 'off', icon TEXT, tickets INTEGER NOT NULL DEFAULT 0, ticket_tpl TEXT NOT NULL DEFAULT '', tidy_agent INTEGER, nag TEXT NOT NULL DEFAULT '', day_hours REAL, description TEXT NOT NULL DEFAULT '', agent_listen TEXT, col_cfg TEXT, ptype TEXT NOT NULL DEFAULT '', family TEXT NOT NULL DEFAULT '', life TEXT NOT NULL DEFAULT '', trip TEXT NOT NULL DEFAULT '', client_id INTEGER, agent_members INTEGER NOT NULL DEFAULT 0, agent_peers INTEGER NOT NULL DEFAULT 0, sort_mode TEXT NOT NULL DEFAULT '', org_id INTEGER REFERENCES orgs(id) ON DELETE SET NULL, folder_own TEXT NOT NULL DEFAULT '[]', page_layout TEXT NOT NULL DEFAULT '', git_folder_off INTEGER NOT NULL DEFAULT 0, stale_days INTEGER, agent_followup INTEGER NOT NULL DEFAULT 0, done_in_section INTEGER);
CREATE TABLE sections (
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, sort REAL NOT NULL DEFAULT 0);
CREATE TABLE tasks (
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
  completed_at TEXT, deleted_at TEXT, tt_id TEXT, pinned INTEGER NOT NULL DEFAULT 0, start TEXT, duration INTEGER, created_by INTEGER, assignee_id INTEGER, url TEXT, assigned_by INTEGER, completed_by INTEGER, waiting_at TEXT, wait_note TEXT NOT NULL DEFAULT '', wait_until TEXT, wait_by INTEGER, wait_fired TEXT NOT NULL DEFAULT '', ttype TEXT NOT NULL DEFAULT '', deadline INTEGER NOT NULL DEFAULT 0, nag TEXT NOT NULL DEFAULT '', nag_at TEXT NOT NULL DEFAULT '', assignee_group_id INTEGER, plan_start TEXT, ms INTEGER NOT NULL DEFAULT 0, milestone_id INTEGER, fam TEXT NOT NULL DEFAULT '', rotation TEXT NOT NULL DEFAULT '', stars INTEGER, approval TEXT NOT NULL DEFAULT '', approver_id INTEGER, snippets TEXT NOT NULL DEFAULT '', locked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE task_tags (                -- tags are per user (user_id)
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL DEFAULT 0,
  tag TEXT NOT NULL, PRIMARY KEY (task_id, user_id, tag));
CREATE TABLE habits (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '',
  goal INTEGER NOT NULL DEFAULT 1, days TEXT NOT NULL DEFAULT '1234567',
  remind_at TEXT NOT NULL DEFAULT '', reminded_on TEXT NOT NULL DEFAULT '',
  sort REAL NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, per_week INTEGER NOT NULL DEFAULT 0, user_id INTEGER);
CREATE TABLE habit_logs (
  habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
  day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', PRIMARY KEY (habit_id, day));
CREATE TABLE pomos (
  id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  kind TEXT NOT NULL DEFAULT 'focus', minutes INTEGER NOT NULL,
  start TEXT NOT NULL, paused_at TEXT, paused_s INTEGER NOT NULL DEFAULT 0,
  end TEXT, done INTEGER NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0, user_id INTEGER);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE attachments (
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  name TEXT NOT NULL, mime TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
  path TEXT NOT NULL,                           -- relative to ATT_DIR
  created_at TEXT NOT NULL, comment_id INTEGER, user_id INTEGER);
CREATE TABLE paperless_links (
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  doc_id INTEGER,                               -- NULL while an upload is still being consumed
  title TEXT NOT NULL DEFAULT '', correspondent TEXT NOT NULL DEFAULT '', created TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ok',            -- ok | pending | error
  message TEXT NOT NULL DEFAULT '', ptask TEXT, att_id INTEGER, added_at TEXT NOT NULL, conn_id INTEGER, added_by INTEGER);
CREATE TABLE pl_conns (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL,   -- server | personal
  owner_id INTEGER,                             -- personal: the owner (server: NULL)
  name TEXT NOT NULL, url TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE pl_conn_users (      -- server connections: who may use them (the admin decides)
  conn_id INTEGER NOT NULL REFERENCES pl_conns(id) ON DELETE CASCADE, user_id INTEGER NOT NULL,
  PRIMARY KEY(conn_id, user_id));
CREATE TABLE pl_tokens (          -- the users' Paperless API tokens, AES-GCM with KALMIDO_SECRET_KEY (never in the DB)
  conn_id INTEGER NOT NULL REFERENCES pl_conns(id) ON DELETE CASCADE, user_id INTEGER NOT NULL,
  token TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(conn_id, user_id));
CREATE TABLE list_bell (
  user_id INTEGER NOT NULL, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  mode TEXT NOT NULL, custom TEXT, PRIMARY KEY(user_id, list_id));
CREATE TABLE filters (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  rules TEXT NOT NULL DEFAULT '{}',            -- json: {op, lists, dates, prios, tags}
  sort REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, user_id INTEGER);
CREATE TABLE users (
  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL DEFAULT '',
  password_hash TEXT,                           -- NULL = no built-in login (proxy only)
  proxy_login TEXT UNIQUE,                      -- value of AUTH_PROXY_HEADER that maps to this user
  is_admin INTEGER NOT NULL DEFAULT 0, drop_token TEXT, created_at TEXT NOT NULL,
  disabled INTEGER NOT NULL DEFAULT 0, ical_token TEXT, paperless_access INTEGER NOT NULL DEFAULT 0, totp_secret TEXT, totp_step INTEGER NOT NULL DEFAULT 0, webauthn_handle TEXT, oidc_subject TEXT, email TEXT, avatar TEXT, kind TEXT NOT NULL DEFAULT 'user', kid INTEGER NOT NULL DEFAULT 0, signup TEXT NOT NULL DEFAULT '', storage_quota_mb INTEGER);
CREATE TABLE user_settings (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (user_id, key));
CREATE TABLE list_members (             -- shared lists: role admin|edit|participant|view (1.10.0); folder/sort/view = the member's own
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'edit', folder TEXT NOT NULL DEFAULT '', sort REAL NOT NULL DEFAULT 0,
  view TEXT, added_at TEXT NOT NULL, own_role TEXT, grole TEXT, PRIMARY KEY (list_id, user_id));
CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, via TEXT NOT NULL DEFAULT 'password');
CREATE TABLE comments (                 -- task comments; soft delete (deleted_at, body wiped)
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  body TEXT NOT NULL DEFAULT '',                -- mentions as <@user_id> tokens
  mentions TEXT NOT NULL DEFAULT '',            -- csv of mentioned user ids
  created_at TEXT NOT NULL, edited_at TEXT, deleted_at TEXT, suggestion TEXT, reply_to INTEGER);
CREATE TABLE activity (                 -- task history, structured (rendered by the client)
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INTEGER, kind TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE task_seen (                -- unread comments: highest comment id a user has seen
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  seen_id INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, task_id));
CREATE TABLE push_subs (                -- Web Push: one row per subscribed browser / device
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint TEXT NOT NULL UNIQUE,                -- push service URL (allow-listed hosts only, see WEBPUSH_HOSTS)
  p256dh TEXT NOT NULL, auth TEXT NOT NULL,     -- the browser's encryption keys (base64url)
  label TEXT NOT NULL DEFAULT '',               -- "Chrome on Android"
  created_at TEXT NOT NULL, last_ok TEXT,
  fails INTEGER NOT NULL DEFAULT 0,             -- consecutive rejections (400/401/403); 5 = removed
  backoff_until REAL NOT NULL DEFAULT 0, dismiss_at REAL NOT NULL DEFAULT 0, dismiss_day TEXT NOT NULL DEFAULT '', dismiss_n INTEGER NOT NULL DEFAULT 0);
CREATE TABLE push_tags (                -- 2.0.5: task notifications shown on a device (per tag "t-<id>"), so they
  sub_id INTEGER NOT NULL REFERENCES push_subs(id) ON DELETE CASCADE,  -- can be closed there once handled elsewhere
  tag TEXT NOT NULL,
  sent_at REAL NOT NULL,                        -- unix time of the last push with this tag to this device
  handled_at REAL,                              -- handled on another device: to be closed here (dismiss push / next push)
  PRIMARY KEY (sub_id, tag));
CREATE TABLE task_push (                -- burst rule for collaboration pushes (per recipient + task)
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  sent_at REAL NOT NULL DEFAULT 0,              -- unix time of the last push
  pending INTEGER NOT NULL DEFAULT 0,           -- comments / changes counted since then (summary)
  events INTEGER NOT NULL DEFAULT 0, mentioned INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, task_id));
CREATE TABLE notifications (            -- "News" feed per user (structured, rendered by the client)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                           -- mention|comment|assign|unassign|complete|share|role|unshare
  task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL,
  actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  comment_id INTEGER,                           -- comment kinds: the (live) comment, excerpt read at display time
  data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, read_at TEXT);
CREATE TABLE templates (                -- private per user: a task (+ subtasks) or a whole list
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'task',            -- task | list
  name TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',   -- json, see tpl_* below
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE time_entries (             -- time tracking (module "time"), see the section below
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
CREATE TABLE task_deps (                -- dependencies: task_id waits on ("is blocked by") blocker_id
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  blocker_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  created_by INTEGER, created_at TEXT NOT NULL, PRIMARY KEY (task_id, blocker_id));
CREATE TABLE list_fields (              -- custom fields of a list (defined by the owner)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, type TEXT NOT NULL,       -- text | number | select | date | checkbox | person | url
  options TEXT NOT NULL DEFAULT '{}',           -- json: number {unit}, select {options: [{id, name, color}]}
  pinned INTEGER NOT NULL DEFAULT 0,            -- 1 = shown as a chip on the task rows (at most 2 per list)
  sort REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE task_field_values (        -- one value per task and field, shared by all list members
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  field_id INTEGER NOT NULL REFERENCES list_fields(id) ON DELETE CASCADE,
  value TEXT NOT NULL, PRIMARY KEY (task_id, field_id));
CREATE TABLE list_status (              -- project status updates of a list (history; current one on lists)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE admin_alerts (             -- admin alerts (ntfy, admins only): the last AA_KEEP
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL,   -- update | webpush | watchdog | integration | security | storage | test
  key TEXT NOT NULL,                            -- identical kind + key = one alert per cooldown
  message TEXT NOT NULL,                        -- English text (the settings list renders tmpl in the viewer's language)
  tmpl TEXT NOT NULL DEFAULT '[]',              -- json [one, other, n, args, click]
  created_at TEXT NOT NULL, sent_at TEXT,
  delivered INTEGER NOT NULL DEFAULT 0,         -- 1 = at least one ntfy topic accepted it
  state TEXT NOT NULL DEFAULT 'sent',           -- sent | failed | queued (daily summary) | summarized | capped (hourly limit)
  repeats INTEGER NOT NULL DEFAULT 0);
CREATE TABLE sev_known (            -- admins, org admins, agents and agent tokens already seen by the watch
  kind TEXT NOT NULL,                           -- admin | org_admin | agent | agent_token
  ref TEXT NOT NULL,                            -- user id | "org:user" | token hash (32 chars); '*' = the baseline of this kind is taken
  at TEXT NOT NULL, PRIMARY KEY (kind, ref));
CREATE TABLE admin_login_ips (      -- the last SEV_IPS sign-in addresses of each admin, hashed (never the address)
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ip_hash TEXT NOT NULL, first_at TEXT NOT NULL, last_at TEXT NOT NULL, PRIMARY KEY (user_id, ip_hash));
CREATE TABLE cal_subs (             -- external calendar subscriptions (read-only, private per user)
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
CREATE TABLE cal_events (           -- expanded occurrences of a subscription (replaced on every change)
  id INTEGER PRIMARY KEY, sub_id INTEGER NOT NULL REFERENCES cal_subs(id) ON DELETE CASCADE,
  uid TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',         -- plain text
  all_day INTEGER NOT NULL DEFAULT 0,
  start TEXT NOT NULL, end TEXT NOT NULL,       -- all-day: local dates (end exclusive); timed: UTC 'YYYY-MM-DDTHH:MM:SSZ'
  d0 TEXT NOT NULL, d1 TEXT NOT NULL);
CREATE TABLE recovery_codes (       -- two-factor: one-time recovery codes (SHA-256 of the code, never the code)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL, created_at TEXT NOT NULL, used_at TEXT);
CREATE TABLE webauthn_creds (       -- passkeys (WebAuthn): second factor and optional passwordless login
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  cred_id TEXT NOT NULL UNIQUE,                 -- credential id, base64url
  public_key BLOB NOT NULL,                     -- COSE public key
  sign_count INTEGER NOT NULL DEFAULT 0, transports TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '',
  rp_id TEXT NOT NULL DEFAULT '', aaguid TEXT NOT NULL DEFAULT '', backed_up INTEGER NOT NULL DEFAULT 0,
  discoverable INTEGER,                         -- 1 / 0 = the browser said (credProps), NULL = unknown
  created_at TEXT NOT NULL, last_used_at TEXT);
CREATE TABLE api_tokens (           -- personal access tokens for /api/v1 (package B): SHA-256 of the token, never the token
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL DEFAULT '',              -- first characters, shown in the settings to tell tokens apart
  scopes TEXT NOT NULL DEFAULT 'read',          -- csv: read | write | admin-read
  expires_at TEXT, created_at TEXT NOT NULL, last_used_at TEXT, allowed_ips TEXT NOT NULL DEFAULT '', list_ids TEXT NOT NULL DEFAULT '');
CREATE TABLE webhooks (             -- outgoing webhooks per user (package B)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '', url TEXT NOT NULL,
  events TEXT NOT NULL DEFAULT '',              -- csv of WH_EVENTS
  secret TEXT NOT NULL,                         -- sealed (server key): signs the deliveries, shown to the user once
  enabled INTEGER NOT NULL DEFAULT 1,
  disabled_reason TEXT NOT NULL DEFAULT '',     -- '' | failures (turned off after the last retry failed)
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, agent INTEGER NOT NULL DEFAULT 0);
CREATE TABLE webhook_queue (        -- pending deliveries (survive a restart); retried with backoff
  id INTEGER PRIMARY KEY, webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
  delivery TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE webhook_log (          -- delivery log (last WH_LOG_KEEP per webhook): status, code, duration; never bodies
  id INTEGER PRIMARY KEY, webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
  delivery TEXT NOT NULL, event TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1,
  ok INTEGER NOT NULL DEFAULT 0, status INTEGER, error TEXT NOT NULL DEFAULT '', ms INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL);
CREATE TABLE imports (          -- package C: one row per import (report + undo), the last IMPORT_KEEP per user
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source TEXT NOT NULL, file_name TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL DEFAULT '{}',           -- json {lists, sections, tasks}: the ids this import created (undo)
  report TEXT NOT NULL DEFAULT '{}',            -- json counts
  created_at TEXT NOT NULL, undone_at TEXT);
CREATE TABLE sample_items (         -- 1.8.0: what the sample project created (list, section, task, field, time)
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, item_id INTEGER NOT NULL, PRIMARY KEY (kind, item_id));
CREATE TABLE agents (               -- 2.0.0: settings of users of kind 'agent' (see "agents")
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  enabled INTEGER NOT NULL DEFAULT 1,           -- kill switch: 0 = tokens refused, no events, webhook off
  note TEXT NOT NULL DEFAULT '',                -- what the agent is for (admins)
  status TEXT NOT NULL DEFAULT 'idle',          -- idle | working | waiting | error (reported by the agent)
  status_text TEXT NOT NULL DEFAULT '', status_at TEXT,
  webhook_id INTEGER,                           -- its webhook (webhooks.agent = 1), NULL = polling only
  created_at TEXT NOT NULL, status_task INTEGER, usage_limits TEXT NOT NULL DEFAULT '', usage_alerted TEXT NOT NULL DEFAULT '', proposals TEXT NOT NULL DEFAULT 'shared', runtime TEXT NOT NULL DEFAULT '', reset_seq INTEGER NOT NULL DEFAULT 0, last_poll_at TEXT, typing_user INTEGER, typing_until REAL NOT NULL DEFAULT 0, owner_id INTEGER, admin_paused INTEGER NOT NULL DEFAULT 0, scopes TEXT NOT NULL DEFAULT '', allowed_ips TEXT NOT NULL DEFAULT '', provider TEXT NOT NULL DEFAULT '', org_id INTEGER REFERENCES orgs(id) ON DELETE SET NULL, list_ids TEXT NOT NULL DEFAULT '', host_info TEXT NOT NULL DEFAULT '', quota TEXT NOT NULL DEFAULT '', stale_sent TEXT NOT NULL DEFAULT '');
CREATE TABLE agent_events (         -- 2.0.0: event queue per agent (polling / long-polling); id = seq
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  uuid TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE tidy_pending (          -- 2.27.0 (#999): a new task waits for its 'tidy' event until people let it be
  task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, actor_id INTEGER, created_at TEXT NOT NULL,
  sent_at TEXT);
CREATE TABLE agent_jobs (           -- 2.0.0: jobs an agent reports (Agents tab)
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- the person it is for (optional)
  title TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'running',   -- running | waiting | done | failed | stopped
  log TEXT NOT NULL DEFAULT '', action TEXT, action_by INTEGER, action_at TEXT,   -- last Approve / Reject / Stop
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, kind TEXT, input TEXT, proposal TEXT, prop_state TEXT NOT NULL DEFAULT '', applied TEXT, list_id INTEGER, approval TEXT);
CREATE TABLE agent_chat (           -- 2.0.0: one conversation per person and agent
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sender TEXT NOT NULL,                         -- user | agent
  body TEXT NOT NULL, task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, created_at TEXT NOT NULL, read_at TEXT, delivered_at TEXT, choices TEXT, choice TEXT, job_id INTEGER REFERENCES agent_jobs(id) ON DELETE SET NULL, reply_to INTEGER);
CREATE TABLE chat_files (           -- 2.13.1 (#465): images / files of a chat message (either side)
  id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES agent_chat(id) ON DELETE CASCADE,
  name TEXT NOT NULL, mime TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
  path TEXT NOT NULL,                           -- relative to ATT_DIR: chat/<agent id>-<user id>/<random>-<name>
  created_at TEXT NOT NULL);
CREATE TABLE chat_reactions (       -- 2.7.2 (#421): heart | up | down (or one emoji) per person and chat message
  message_id INTEGER NOT NULL REFERENCES agent_chat(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  emoji TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (message_id, user_id, emoji));
CREATE TABLE agent_steps (          -- 2.32.0 (#1081): an agent's words between its tool calls (prose, filtered)
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- the ONLY person who sees them
  job_id INTEGER REFERENCES agent_jobs(id) ON DELETE CASCADE,        -- a job's history (NULL = a chat run)
  message_id INTEGER REFERENCES agent_chat(id) ON DELETE CASCADE,    -- the chat answer they belong to (NULL = live / none)
  state TEXT NOT NULL DEFAULT 'live',           -- live (chat run in progress) | done | log (a job's progress line)
  text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE agent_schedules (      -- 2.34.0 (#272): planned jobs of a person for an agent (event scheduled_job)
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- who planned it (the agent answers in their chat)
  title TEXT NOT NULL, prompt TEXT NOT NULL,
  freq TEXT NOT NULL DEFAULT 'daily',           -- daily | weekdays | weekly | monthly
  days TEXT NOT NULL DEFAULT '',                -- weekly: ISO weekdays "1,3"; monthly: the day of the month
  at_time TEXT NOT NULL DEFAULT '09:00', tz TEXT NOT NULL DEFAULT '',   -- HH:MM in the person's IANA time zone
  list_id INTEGER REFERENCES lists(id) ON DELETE CASCADE,            -- optional: the list it is about (shared with the agent)
  enabled INTEGER NOT NULL DEFAULT 1, next_at TEXT,                  -- next due time (UTC), NULL = off
  last_at TEXT, last_state TEXT NOT NULL DEFAULT '', last_seq INTEGER,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE agent_usage (          -- 2.1.1 (#326): model usage an agent reports (numbers + ids, never prompts)
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  model TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL,                                -- NULL = not reported
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL,
  job_id INTEGER REFERENCES agent_jobs(id) ON DELETE SET NULL,
  note TEXT NOT NULL DEFAULT '',                -- optional, at most USAGE_NOTE_MAX characters
  day TEXT NOT NULL,                            -- local day (server time zone): periods, charts
  created_at TEXT NOT NULL);
CREATE TABLE agent_audit (          -- 2.2.1 (#358): every API request made with an agent's token (never bodies)
  id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL,   -- no foreign key: the log outlives a deleted agent (retention removes it)
  at TEXT NOT NULL,                             -- UTC, milliseconds
  day TEXT NOT NULL,                            -- local day (server time zone): filter, retention
  method TEXT NOT NULL, route TEXT NOT NULL,    -- the route template, e.g. /api/v1/tasks/{tid} (never query values)
  status INTEGER NOT NULL, task_id INTEGER, list_id INTEGER,   -- ids from the path or the body, when there
  ms INTEGER NOT NULL DEFAULT 0, scope TEXT NOT NULL DEFAULT '');
CREATE TABLE comment_reactions (    -- 2.0.0: heart | up | down per person and comment
  comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  emoji TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (comment_id, user_id, emoji));
CREATE TABLE list_tags (            -- 2.0.0: tags of a list, shared by its members (colour per list)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', sort REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE task_list_tags (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES list_tags(id) ON DELETE CASCADE, PRIMARY KEY (task_id, tag_id));
CREATE TABLE public_links (         -- public read-only link of a list (package B), one per list
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL UNIQUE REFERENCES lists(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,              -- SHA-256 of the token in the URL (lookup)
  token TEXT NOT NULL,                          -- the token, sealed (server key): the owner can copy the link again
  mode TEXT NOT NULL DEFAULT 'view',            -- view | tick (view + tick off)
  notes INTEGER NOT NULL DEFAULT 0,             -- 1 = task notes shown as plain text
  password_hash TEXT, pw_rev INTEGER NOT NULL DEFAULT 0,   -- optional password; pw_rev invalidates unlock cookies
  expires_at TEXT, created_by INTEGER, created_at TEXT NOT NULL, last_used_at TEXT,
  views INTEGER NOT NULL DEFAULT 0);
CREATE TABLE list_activity (        -- 2.1.2 (#349): history of a list as a whole (kind owner = ownership transferred)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  user_id INTEGER, kind TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE git_conns (            -- 2.2.0 (#271): repositories connected to a project list
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,                       -- github | gitea (also Forgejo)
  base_url TEXT NOT NULL DEFAULT '',            -- web address of the server; '' = github.com
  owner TEXT NOT NULL, repo TEXT NOT NULL,
  token TEXT NOT NULL DEFAULT '',               -- access token, AES-GCM with KALMIDO_SECRET_KEY ('' = none: public repository)
  hook_secret TEXT NOT NULL DEFAULT '',         -- inbound webhook secret, sealed the same way ('' = webhook off)
  default_branch TEXT NOT NULL DEFAULT '', etags TEXT NOT NULL DEFAULT '{}',
  polled_at TEXT, next_at REAL NOT NULL DEFAULT 0, fails INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
  created_by INTEGER, created_at TEXT NOT NULL, tags_at TEXT);
CREATE TABLE git_prs (              -- pull requests that are linked to a task
  conn_id INTEGER NOT NULL REFERENCES git_conns(id) ON DELETE CASCADE, number INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'open',   -- open | merged | closed
  author TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', head_ref TEXT NOT NULL DEFAULT '', head_sha TEXT NOT NULL DEFAULT '',
  ci TEXT NOT NULL DEFAULT '', ci_sha TEXT NOT NULL DEFAULT '',          -- success | failure | pending | '' (none)
  updated_at TEXT, merged_at TEXT, PRIMARY KEY (conn_id, number));
CREATE TABLE git_commits (          -- commits that are linked to a task (first line of the message)
  conn_id INTEGER NOT NULL REFERENCES git_conns(id) ON DELETE CASCADE, sha TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', branch TEXT NOT NULL DEFAULT '',
  at TEXT, PRIMARY KEY (conn_id, sha));
CREATE TABLE git_links (            -- task <-> pull request (kind pr, ref = number) / commit (kind commit, ref = sha)
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  conn_id INTEGER NOT NULL REFERENCES git_conns(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, ref TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (task_id, conn_id, kind, ref));
CREATE TABLE git_closes (           -- completions by "fixes #id": once per task; undo = what do_complete filled
  task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, conn_id INTEGER NOT NULL, kind TEXT NOT NULL,
  ref TEXT NOT NULL, undo TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, undone_at TEXT);
CREATE TABLE git_folders (          -- 2.33.0 (#934): a repository connected to a folder (git_conns row on one of its lists)
  conn_id INTEGER PRIMARY KEY REFERENCES git_conns(id) ON DELETE CASCADE,
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, folder TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE git_tags (             -- 2.18.0 (#408): tag names a connection has seen (a NEW one can reach a milestone)
  conn_id INTEGER NOT NULL REFERENCES git_conns(id) ON DELETE CASCADE, name TEXT NOT NULL, seen_at TEXT NOT NULL,
  PRIMARY KEY (conn_id, name));
CREATE TABLE issue_hooks (          -- 2.18.0 (#408): inbound error-report webhook of a list (one per list)
  list_id INTEGER PRIMARY KEY REFERENCES lists(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,                     -- SHA-256 of the secret in the URL (never stored plain)
  created_by INTEGER, created_at TEXT NOT NULL, last_at TEXT, received INTEGER NOT NULL DEFAULT 0);
CREATE TABLE issue_reports (        -- fingerprints of error reports: one open ticket per error, repeats counted
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, fp TEXT NOT NULL,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,   -- NULL = only counted (rate limit), no ticket yet
  count INTEGER NOT NULL DEFAULT 1, first_at TEXT NOT NULL, last_at TEXT NOT NULL, PRIMARY KEY (list_id, fp));
CREATE TABLE list_links (           -- 2.7.1 (#410): key links of a project list (overview), ordered
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  title TEXT NOT NULL, url TEXT NOT NULL, sort REAL NOT NULL DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL);
CREATE TABLE list_milestones (      -- 2.7.1 (#410): milestones of a project list (local day; timeline markers)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, day TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL);
CREATE TABLE mail_counts (         -- 2.24.0 (#899): mails per sender / receiving address and day (admin/hosting.py)
  k TEXT PRIMARY KEY, day TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0);
CREATE TABLE list_files (           -- 2.7.1 (#410): project files uploaded on the list itself (ATT_DIR/lists/<id>/)
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, mime TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
  path TEXT NOT NULL, user_id INTEGER, created_at TEXT NOT NULL);
CREATE TABLE list_paperless (       -- 2.7.1 (#410): Paperless documents linked to a project list
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  conn_id INTEGER, doc_id INTEGER, title TEXT NOT NULL DEFAULT '', correspondent TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL DEFAULT '', added_by INTEGER, added_at TEXT NOT NULL);
CREATE TABLE app_passwords (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, pw_hash TEXT NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT, last_client TEXT,
  caps TEXT NOT NULL DEFAULT '');
CREATE TABLE dav_meta (
  task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
  uid TEXT, href TEXT, parent_uid TEXT, extra TEXT NOT NULL DEFAULT '');
CREATE TABLE groups (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, oidc_group TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, created_by INTEGER);
CREATE TABLE group_members (
  group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  added_at TEXT NOT NULL, PRIMARY KEY (group_id, user_id));
CREATE TABLE group_shares (
  id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  list_id INTEGER REFERENCES lists(id) ON DELETE CASCADE, owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  folder TEXT, role TEXT NOT NULL DEFAULT 'edit', added_by INTEGER, added_at TEXT NOT NULL);
CREATE TABLE dav_sync (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  token TEXT NOT NULL, state BLOB NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (user_id, list_id, token));
CREATE TABLE notes (
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '', pinned INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER, updated_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE tchat_rooms (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, list_id INTEGER REFERENCES lists(id) ON DELETE CASCADE,
  a INTEGER REFERENCES users(id) ON DELETE CASCADE, b INTEGER REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, last_at TEXT);
CREATE TABLE tchat_msgs (
  id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL REFERENCES tchat_rooms(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, body TEXT NOT NULL,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, created_at TEXT NOT NULL, edited_at TEXT, deleted_at TEXT, reply_to INTEGER);
CREATE TABLE tchat_reads (
  room_id INTEGER NOT NULL REFERENCES tchat_rooms(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  last_id INTEGER NOT NULL DEFAULT 0, muted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (room_id, user_id));
CREATE TABLE tchat_rx (
  message_id INTEGER NOT NULL REFERENCES tchat_msgs(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  emoji TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (message_id, user_id, emoji));
CREATE TABLE mail_tokens (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  list_id INTEGER REFERENCES lists(id) ON DELETE CASCADE, created_at TEXT NOT NULL);
CREATE TABLE task_people (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, user_id));
CREATE TABLE kid_parents (
  kid_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, parent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (kid_id, parent_id));
CREATE TABLE kid_stars (
  id INTEGER PRIMARY KEY, kid_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  delta INTEGER NOT NULL, kind TEXT NOT NULL,   -- task | bonus | reward
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, reward_id INTEGER, title TEXT NOT NULL DEFAULT '',
  by_id INTEGER, at TEXT NOT NULL,              -- task: the completion's completed_at (undo takes exactly that one back)
  created_at TEXT NOT NULL);
CREATE TABLE kid_rewards (
  id INTEGER PRIMARY KEY, kid_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '', cost INTEGER NOT NULL, once INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'open',           -- open | requested | redeemed (once)
  requested_at TEXT, decided_by INTEGER, decided_at TEXT, created_by INTEGER, created_at TEXT NOT NULL);
CREATE TABLE shop_memory (
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, item TEXT NOT NULL,
  section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE, at TEXT NOT NULL, PRIMARY KEY (list_id, item));
CREATE TABLE contact_srcs (         -- private per user, like cal_subs: url + password sealed (cal_seal)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '', url TEXT NOT NULL, url_hint TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '', password TEXT NOT NULL DEFAULT '',
  list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL, lead INTEGER NOT NULL DEFAULT 7,
  status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '', fails INTEGER NOT NULL DEFAULT 0,
  count INTEGER NOT NULL DEFAULT 0, tried_at TEXT, synced_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE contact_links (        -- a contact's birthday / anniversary -> its task (digest = what it was made from)
  src_id INTEGER NOT NULL REFERENCES contact_srcs(id) ON DELETE CASCADE, uid TEXT NOT NULL, kind TEXT NOT NULL,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, digest TEXT NOT NULL DEFAULT '',
  book TEXT NOT NULL DEFAULT '',                  -- the address book's URL (sealed like the source's), for a later contacts module
  PRIMARY KEY (src_id, uid, kind));
CREATE TABLE ev_cals (
  id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', sort INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, changed_at TEXT NOT NULL, org_id INTEGER REFERENCES orgs(id) ON DELETE SET NULL);
CREATE TABLE ev_cal_members (
  cal_id INTEGER NOT NULL REFERENCES ev_cals(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'view', hidden INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL, PRIMARY KEY (cal_id, user_id));
CREATE TABLE events (
  id INTEGER PRIMARY KEY, cal_id INTEGER NOT NULL REFERENCES ev_cals(id) ON DELETE CASCADE,
  uid TEXT NOT NULL, href TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
  all_day INTEGER NOT NULL DEFAULT 0, start TEXT NOT NULL, end TEXT NOT NULL, tz TEXT NOT NULL DEFAULT '',
  rrule TEXT NOT NULL DEFAULT '', exdates TEXT NOT NULL DEFAULT '', overrides TEXT NOT NULL DEFAULT '',
  reminders TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'confirmed', busy INTEGER NOT NULL DEFAULT 1,
  url TEXT, task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, extra TEXT NOT NULL DEFAULT '',
  seq INTEGER NOT NULL DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
  first_day TEXT NOT NULL DEFAULT '', last_day TEXT NOT NULL DEFAULT '');
CREATE TABLE event_attendees (
  id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
  email TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', partstat TEXT NOT NULL DEFAULT 'needs-action',
  role TEXT NOT NULL DEFAULT 'req');
CREATE TABLE ev_reminded (
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE, user_id INTEGER NOT NULL, k TEXT NOT NULL,
  at TEXT NOT NULL, PRIMARY KEY (event_id, user_id, k));
CREATE TABLE books (
  id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', src_id INTEGER REFERENCES contact_srcs(id) ON DELETE SET NULL,
  occ_list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL,   -- birthdays + anniversaries become tasks of this list
  created_at TEXT NOT NULL, changed_at TEXT NOT NULL, org_id INTEGER REFERENCES orgs(id) ON DELETE SET NULL);
CREATE TABLE book_members (
  book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'view', added_at TEXT NOT NULL, PRIMARY KEY (book_id, user_id));
CREATE TABLE contacts (
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
CREATE TABLE contact_tasks (
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'about',   -- waiting | responsible | about
  added_by INTEGER, added_at TEXT NOT NULL, PRIMARY KEY (contact_id, task_id));
CREATE TABLE contact_occ (   -- a contact's birthday / anniversary -> its task (like contact_links for own contacts)
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE, kind TEXT NOT NULL,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL, digest TEXT NOT NULL DEFAULT '', PRIMARY KEY (contact_id, kind));
CREATE TABLE dav_sync2 (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, coll TEXT NOT NULL,
  token TEXT NOT NULL, state BLOB NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (user_id, coll, token));
CREATE TABLE journal (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, day TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
  mood INTEGER, updated_at TEXT NOT NULL, PRIMARY KEY (user_id, day));
CREATE TABLE contact_care (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  every_days INTEGER NOT NULL DEFAULT 0, last TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, contact_id));
CREATE TABLE user_invites (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, token_hash TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'invite',
  created_by INTEGER, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, sent_at TEXT, used_at TEXT);
CREATE TABLE folder_props (
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, folder TEXT NOT NULL, props TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL, PRIMARY KEY (owner_id, folder));
CREATE TABLE agent_bridges (
  agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, list_a INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  list_b INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, by_id INTEGER, at TEXT NOT NULL, PRIMARY KEY (agent_id, list_a, list_b));
CREATE TABLE agent_list_access (
  agent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  day TEXT NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (list_id, day, agent_id, kind));
CREATE TABLE folder_people (
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, folder TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL DEFAULT 'edit', created_at TEXT NOT NULL,
  PRIMARY KEY (owner_id, folder, user_id));
CREATE TABLE orgs (id INTEGER PRIMARY KEY, name TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, domains TEXT NOT NULL DEFAULT '');
CREATE TABLE org_members (
  org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL DEFAULT 'member',
  PRIMARY KEY (org_id, user_id));
CREATE TABLE org_list_log (
  id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  list_id INTEGER, list_name TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,                         -- archive | restore | delete | owner
  by_id INTEGER, owner_id INTEGER, to_id INTEGER, created_at TEXT NOT NULL);
CREATE TABLE kk_conns (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, url TEXT NOT NULL, token TEXT NOT NULL DEFAULT '',
  list_id INTEGER, source TEXT NOT NULL DEFAULT '', archive INTEGER NOT NULL DEFAULT 1, synced_at TEXT, error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
CREATE TABLE clients (
  id INTEGER PRIMARY KEY, org_id INTEGER REFERENCES orgs(id) ON DELETE SET NULL, name TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '',
  color TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', rate REAL, budget_h REAL, budget_amount REAL,
  archived INTEGER NOT NULL DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, street TEXT NOT NULL DEFAULT '', zip TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '', vat_id TEXT NOT NULL DEFAULT '', customer_no TEXT NOT NULL DEFAULT '', buyer_reference TEXT NOT NULL DEFAULT '', email_invoice TEXT NOT NULL DEFAULT '', payment_terms_days INTEGER);
CREATE TABLE forms (
  id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, token TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL, intro TEXT NOT NULL DEFAULT '', access TEXT NOT NULL DEFAULT 'org', section_id INTEGER,
  ask_email INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1, count INTEGER NOT NULL DEFAULT 0, last_at TEXT,
  created_by INTEGER, created_at TEXT NOT NULL);
CREATE TABLE list_layouts (
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  layout TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (list_id, user_id));
CREATE TABLE list_notif (
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, user_id INTEGER NOT NULL DEFAULT 0,
  tpl TEXT NOT NULL, custom TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (list_id, user_id));
CREATE TABLE folder_notif (
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, folder TEXT NOT NULL, user_id INTEGER NOT NULL DEFAULT 0,
  tpl TEXT NOT NULL, custom TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (owner_id, folder, user_id));
CREATE TABLE login_ips (
  ip TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, at TEXT NOT NULL, PRIMARY KEY (ip, user_id));
CREATE TABLE office_settings (
  org_id INTEGER PRIMARY KEY REFERENCES orgs(id) ON DELETE CASCADE, data TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL);
CREATE TABLE office_services (
  id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, name_de TEXT NOT NULL, name_en TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '', sort REAL NOT NULL DEFAULT 0, unit TEXT NOT NULL DEFAULT 'day', daily_rate REAL, hourly_rate REAL,
  raw_fee INTEGER NOT NULL DEFAULT 0, producing INTEGER NOT NULL DEFAULT 0, intext TEXT NOT NULL DEFAULT 'extern', role TEXT NOT NULL DEFAULT '',
  tax TEXT NOT NULL DEFAULT 'standard', archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE office_equipment (
  id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
  daily_rate REAL, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE office_sets (
  id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, name TEXT NOT NULL, discount_pct REAL,
  items TEXT NOT NULL DEFAULT '[]', archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE office_texts (
  id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, kind TEXT NOT NULL, key TEXT NOT NULL DEFAULT '',
  text_de TEXT NOT NULL DEFAULT '', text_en TEXT NOT NULL DEFAULT '', sort REAL NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE office_contracts (
  id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, name TEXT NOT NULL,
  client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL, date TEXT NOT NULL DEFAULT '', raw_included INTEGER NOT NULL DEFAULT 0,
  rights_time_id INTEGER REFERENCES office_texts(id) ON DELETE SET NULL, rights_territory_id INTEGER REFERENCES office_texts(id) ON DELETE SET NULL,
  rights_media_id INTEGER REFERENCES office_texts(id) ON DELETE SET NULL, rights_note_de TEXT NOT NULL DEFAULT '', rights_note_en TEXT NOT NULL DEFAULT '',
  closing_de TEXT NOT NULL DEFAULT '', closing_en TEXT NOT NULL DEFAULT '', rates TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT '',
  archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE office_numbers (
  org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, kind TEXT NOT NULL, period TEXT NOT NULL DEFAULT '',
  last INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (org_id, kind, period));
CREATE TABLE office_docs (
  id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, kind TEXT NOT NULL DEFAULT 'offer',
  number TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft', lang TEXT NOT NULL DEFAULT 'de', currency TEXT NOT NULL DEFAULT 'EUR',
  fx_rate REAL, vat_mode TEXT NOT NULL DEFAULT 'vat', client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
  recipient TEXT NOT NULL DEFAULT '{}', project_title TEXT NOT NULL DEFAULT '', project_ref TEXT NOT NULL DEFAULT '',
  date TEXT NOT NULL DEFAULT '', valid_until TEXT NOT NULL DEFAULT '', contract_id INTEGER REFERENCES office_contracts(id) ON DELETE SET NULL,
  raw_mode TEXT NOT NULL DEFAULT 'optional', raw_factor REAL, prod_quotient REAL, producing_rate REAL, discount_pct REAL,
  intro TEXT NOT NULL DEFAULT '', closing TEXT NOT NULL DEFAULT '', rights TEXT NOT NULL DEFAULT '{}', fields TEXT NOT NULL DEFAULT '[]',
  totals TEXT NOT NULL DEFAULT '{}', created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, sent_at TEXT, locked_at TEXT, locked_by INTEGER, sender TEXT, recipient_snapshot TEXT, tax_snapshot TEXT, pack_version TEXT, service_from TEXT, service_to TEXT);
CREATE TABLE office_doc_items (
  id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES office_docs(id) ON DELETE CASCADE, sort REAL NOT NULL DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'service', service_id INTEGER REFERENCES office_services(id) ON DELETE SET NULL,
  title TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '', qty REAL NOT NULL DEFAULT 1, unit TEXT NOT NULL DEFAULT 'day',
  rate REAL NOT NULL DEFAULT 0, tax TEXT NOT NULL DEFAULT 'standard', raw_fee INTEGER NOT NULL DEFAULT 0, producing INTEGER NOT NULL DEFAULT 0,
  intext TEXT NOT NULL DEFAULT 'intern', cost REAL NOT NULL DEFAULT 0, discountable INTEGER NOT NULL DEFAULT 1, org_id INTEGER REFERENCES orgs(id) ON DELETE CASCADE, tax_pct TEXT, net TEXT, tax_amount TEXT);
CREATE TABLE office_company (
  org_id INTEGER PRIMARY KEY REFERENCES orgs(id) ON DELETE CASCADE, name TEXT NOT NULL DEFAULT '', street TEXT NOT NULL DEFAULT '',
  zip TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '', tax_number TEXT NOT NULL DEFAULT '', vat_id TEXT NOT NULL DEFAULT '', iban TEXT NOT NULL DEFAULT '',
  bic TEXT NOT NULL DEFAULT '', bank_name TEXT NOT NULL DEFAULT '', register_court TEXT NOT NULL DEFAULT '', register_no TEXT NOT NULL DEFAULT '',
  managing_directors TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
CREATE TABLE office_doc_log (
  id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, doc_id INTEGER,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, at TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL DEFAULT 'doc',
  detail TEXT NOT NULL DEFAULT '{}');
CREATE VIRTUAL TABLE msg_fts USING fts5(body, tokenize='unicode61 remove_diacritics 2');
CREATE INDEX tasks_list ON tasks(list_id);
CREATE INDEX tasks_parent ON tasks(parent_id);
CREATE INDEX tasks_open ON tasks(status) WHERE deleted_at IS NULL;
CREATE INDEX attachments_task ON attachments(task_id);
CREATE INDEX paperless_links_task ON paperless_links(task_id);
CREATE INDEX list_members_user ON list_members(user_id);
CREATE INDEX time_user_start ON time_entries(user_id, start);
CREATE INDEX time_task ON time_entries(task_id);
CREATE INDEX time_list ON time_entries(list_id, start);
CREATE UNIQUE INDEX time_running ON time_entries(user_id) WHERE end IS NULL;
CREATE UNIQUE INDEX time_pomo ON time_entries(pomo_id) WHERE pomo_id IS NOT NULL;
CREATE UNIQUE INDEX time_client ON time_entries(user_id, client_id) WHERE client_id IS NOT NULL;
CREATE INDEX task_deps_blocker ON task_deps(blocker_id);
CREATE INDEX list_fields_list ON list_fields(list_id);
CREATE INDEX task_field_values_field ON task_field_values(field_id);
CREATE INDEX list_status_list ON list_status(list_id, id);
CREATE INDEX admin_alerts_key ON admin_alerts(kind, key, created_at);
CREATE INDEX cal_subs_user ON cal_subs(user_id);
CREATE INDEX cal_events_sub ON cal_events(sub_id, d0);
CREATE INDEX recovery_codes_user ON recovery_codes(user_id);
CREATE INDEX webauthn_creds_user ON webauthn_creds(user_id);
CREATE INDEX api_tokens_user ON api_tokens(user_id);
CREATE INDEX webhooks_user ON webhooks(user_id);
CREATE INDEX webhook_queue_next ON webhook_queue(next_at);
CREATE INDEX webhook_log_hook ON webhook_log(webhook_id, id);
CREATE INDEX imports_user ON imports(user_id, id);
CREATE INDEX sample_items_user ON sample_items(user_id, kind);
CREATE INDEX agent_events_agent ON agent_events(agent_id, id);
CREATE INDEX agent_jobs_agent ON agent_jobs(agent_id, state);
CREATE INDEX agent_jobs_task ON agent_jobs(task_id);
CREATE INDEX agent_chat_pair ON agent_chat(agent_id, user_id, id);
CREATE INDEX chat_files_msg ON chat_files(message_id);
CREATE INDEX agent_steps_pair ON agent_steps(agent_id, user_id, id);
CREATE INDEX agent_steps_job ON agent_steps(job_id) WHERE job_id IS NOT NULL;
CREATE INDEX agent_steps_user ON agent_steps(user_id, id);
CREATE INDEX agent_steps_msg ON agent_steps(message_id) WHERE message_id IS NOT NULL;
CREATE INDEX agent_schedules_due ON agent_schedules(next_at) WHERE enabled=1;
CREATE INDEX agent_schedules_pair ON agent_schedules(agent_id, user_id);
CREATE INDEX agent_schedules_list ON agent_schedules(list_id) WHERE list_id IS NOT NULL;
CREATE INDEX agent_usage_agent ON agent_usage(agent_id, day);
CREATE INDEX agent_usage_task ON agent_usage(task_id) WHERE task_id IS NOT NULL;
CREATE INDEX agent_audit_agent ON agent_audit(agent_id, id);
CREATE INDEX agent_audit_day ON agent_audit(day);
CREATE UNIQUE INDEX list_tags_name ON list_tags(list_id, name COLLATE NOCASE);
CREATE INDEX task_list_tags_tag ON task_list_tags(tag_id);
CREATE INDEX list_activity_list ON list_activity(list_id);
CREATE INDEX git_conns_list ON git_conns(list_id);
CREATE INDEX git_links_conn ON git_links(conn_id, kind, ref);
CREATE INDEX git_folders_owner ON git_folders(owner_id, folder);
CREATE INDEX issue_reports_task ON issue_reports(task_id);
CREATE INDEX list_links_list ON list_links(list_id, sort);
CREATE INDEX list_milestones_list ON list_milestones(list_id, day);
CREATE INDEX list_files_list ON list_files(list_id);
CREATE INDEX list_paperless_list ON list_paperless(list_id);
CREATE INDEX app_passwords_user ON app_passwords(user_id);
CREATE INDEX dav_meta_uid ON dav_meta(uid);
CREATE INDEX dav_meta_href ON dav_meta(href);
CREATE INDEX dav_meta_parent ON dav_meta(parent_uid) WHERE parent_uid IS NOT NULL;
CREATE INDEX group_members_user ON group_members(user_id);
CREATE INDEX group_shares_list ON group_shares(list_id);
CREATE INDEX group_shares_owner ON group_shares(owner_id);
CREATE INDEX notes_list ON notes(list_id, updated_at);
CREATE UNIQUE INDEX tchat_dm ON tchat_rooms(a, b) WHERE kind='dm';
CREATE UNIQUE INDEX tchat_list ON tchat_rooms(list_id) WHERE kind='list';
CREATE INDEX tchat_msgs_room ON tchat_msgs(room_id, id);
CREATE INDEX mail_tokens_user ON mail_tokens(user_id);
CREATE INDEX task_people_user ON task_people(user_id);
CREATE INDEX kid_stars_kid ON kid_stars(kid_id, id);
CREATE INDEX kid_rewards_kid ON kid_rewards(kid_id);
CREATE INDEX ev_cals_owner ON ev_cals(owner_id);
CREATE INDEX ev_cal_members_user ON ev_cal_members(user_id);
CREATE INDEX events_cal ON events(cal_id, deleted_at);
CREATE INDEX events_uid ON events(uid);
CREATE INDEX events_task ON events(task_id) WHERE task_id IS NOT NULL;
CREATE INDEX event_attendees_event ON event_attendees(event_id);
CREATE INDEX event_attendees_user ON event_attendees(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX event_attendees_contact ON event_attendees(contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX books_owner ON books(owner_id);
CREATE INDEX book_members_user ON book_members(user_id);
CREATE INDEX contacts_book ON contacts(book_id);
CREATE INDEX contacts_uid ON contacts(uid);
CREATE INDEX contact_tasks_task ON contact_tasks(task_id);
CREATE INDEX org_members_user ON org_members(user_id);
CREATE INDEX org_list_log_org ON org_list_log(org_id, id);
CREATE INDEX clients_org ON clients(org_id);
CREATE INDEX forms_list ON forms(list_id);
CREATE INDEX office_services_org ON office_services(org_id);
CREATE INDEX office_equipment_org ON office_equipment(org_id);
CREATE INDEX office_sets_org ON office_sets(org_id);
CREATE INDEX office_texts_org ON office_texts(org_id);
CREATE INDEX office_contracts_org ON office_contracts(org_id);
CREATE INDEX office_docs_org ON office_docs(org_id, kind);
CREATE UNIQUE INDEX office_docs_number ON office_docs(org_id, number) WHERE number != '';
CREATE INDEX office_doc_items_doc ON office_doc_items(doc_id);
CREATE INDEX office_doc_log_org ON office_doc_log(org_id, id);
CREATE INDEX office_doc_log_doc ON office_doc_log(doc_id);
CREATE INDEX tasks_agroup ON tasks(assignee_group_id) WHERE assignee_group_id IS NOT NULL;
CREATE INDEX lists_owner ON lists(owner_id);
CREATE INDEX tasks_assignee ON tasks(assignee_id);
CREATE INDEX habits_user ON habits(user_id);
CREATE INDEX pomos_user ON pomos(user_id);
CREATE INDEX filters_user ON filters(user_id);
CREATE INDEX task_tags_user ON task_tags(user_id, tag);
CREATE UNIQUE INDEX tasks_tt_user ON tasks(created_by, tt_id) WHERE tt_id IS NOT NULL;
CREATE INDEX comments_task ON comments(task_id);
CREATE INDEX activity_task ON activity(task_id, id);
CREATE INDEX attachments_comment ON attachments(comment_id) WHERE comment_id IS NOT NULL;
CREATE INDEX notifications_user ON notifications(user_id, id);
CREATE INDEX notifications_task ON notifications(task_id);
CREATE INDEX tasks_completed_by ON tasks(completed_by, completed_at) WHERE completed_by IS NOT NULL;
CREATE INDEX templates_user ON templates(user_id);
CREATE INDEX push_subs_user ON push_subs(user_id);
CREATE UNIQUE INDEX users_oidc ON users(oidc_subject) WHERE oidc_subject IS NOT NULL;
CREATE INDEX sessions_user ON sessions(user_id);
CREATE INDEX lists_org ON lists(org_id) WHERE org_id IS NOT NULL;
CREATE INDEX activity_created ON activity(created_at);
CREATE INDEX activity_user ON activity(user_id, created_at);
CREATE INDEX comments_user ON comments(user_id, created_at);
CREATE INDEX comments_created ON comments(created_at);
CREATE INDEX office_doc_items_org ON office_doc_items(org_id, doc_id);
CREATE INDEX tasks_msid ON tasks(milestone_id) WHERE milestone_id IS NOT NULL;
CREATE TRIGGER time_task_list AFTER UPDATE OF list_id ON tasks WHEN NEW.list_id IS NOT OLD.list_id
BEGIN UPDATE time_entries SET list_id=NEW.list_id WHERE task_id=NEW.id; END;
CREATE TRIGGER time_task_title AFTER UPDATE OF title ON tasks WHEN NEW.title IS NOT OLD.title
BEGIN UPDATE time_entries SET task_title=NEW.title WHERE task_id=NEW.id AND user_id IN
  (SELECT owner_id FROM lists WHERE id=NEW.list_id UNION SELECT user_id FROM list_members WHERE list_id=NEW.list_id
   AND (role!='participant' OR user_id IS NEW.assignee_id)); END;
CREATE TRIGGER msg_fts_comments_ai AFTER INSERT ON comments WHEN new.deleted_at IS NULL AND new.body!='' BEGIN DELETE FROM msg_fts WHERE rowid=new.id*4+1; INSERT INTO msg_fts(rowid, body) VALUES (new.id*4+1, CASE WHEN replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss')=new.body THEN new.body ELSE new.body||char(10)||replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss') END); END;
CREATE TRIGGER msg_fts_comments_au AFTER UPDATE OF body, deleted_at ON comments BEGIN DELETE FROM msg_fts WHERE rowid=old.id*4+1; INSERT INTO msg_fts(rowid, body) SELECT new.id*4+1, CASE WHEN replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss')=new.body THEN new.body ELSE new.body||char(10)||replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss') END WHERE new.deleted_at IS NULL AND new.body!=''; END;
CREATE TRIGGER msg_fts_comments_ad AFTER DELETE ON comments BEGIN DELETE FROM msg_fts WHERE rowid=old.id*4+1; END;
CREATE TRIGGER msg_fts_tchat_msgs_ai AFTER INSERT ON tchat_msgs WHEN new.deleted_at IS NULL AND new.body!='' BEGIN DELETE FROM msg_fts WHERE rowid=new.id*4+2; INSERT INTO msg_fts(rowid, body) VALUES (new.id*4+2, CASE WHEN replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss')=new.body THEN new.body ELSE new.body||char(10)||replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss') END); END;
CREATE TRIGGER msg_fts_tchat_msgs_au AFTER UPDATE OF body, deleted_at ON tchat_msgs BEGIN DELETE FROM msg_fts WHERE rowid=old.id*4+2; INSERT INTO msg_fts(rowid, body) SELECT new.id*4+2, CASE WHEN replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss')=new.body THEN new.body ELSE new.body||char(10)||replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss') END WHERE new.deleted_at IS NULL AND new.body!=''; END;
CREATE TRIGGER msg_fts_tchat_msgs_ad AFTER DELETE ON tchat_msgs BEGIN DELETE FROM msg_fts WHERE rowid=old.id*4+2; END;
CREATE TRIGGER msg_fts_agent_chat_ai AFTER INSERT ON agent_chat WHEN new.body!='' BEGIN DELETE FROM msg_fts WHERE rowid=new.id*4+3; INSERT INTO msg_fts(rowid, body) VALUES (new.id*4+3, CASE WHEN replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss')=new.body THEN new.body ELSE new.body||char(10)||replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss') END); END;
CREATE TRIGGER msg_fts_agent_chat_au AFTER UPDATE OF body ON agent_chat BEGIN DELETE FROM msg_fts WHERE rowid=old.id*4+3; INSERT INTO msg_fts(rowid, body) SELECT new.id*4+3, CASE WHEN replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss')=new.body THEN new.body ELSE new.body||char(10)||replace(replace(replace(replace(replace(replace(replace(new.body,'ä','ae'),'ö','oe'),'ü','ue'),'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ß','ss') END WHERE new.body!=''; END;
CREATE TRIGGER msg_fts_agent_chat_ad AFTER DELETE ON agent_chat BEGIN DELETE FROM msg_fts WHERE rowid=old.id*4+3; END;
-- the settings of a fresh 2.36.2 install (without its secrets: 2.37 creates new ones)
INSERT INTO settings(key,value) VALUES('version','1');
INSERT INTO settings(key,value) VALUES('collab_all','1');
INSERT INTO settings(key,value) VALUES('time_all','1');
INSERT INTO settings(key,value) VALUES('update_check','1');
INSERT INTO settings(key,value) VALUES('ntfy_inbox_since','');
INSERT INTO settings(key,value) VALUES('aa_on','1');
INSERT INTO settings(key,value) VALUES('aa_topic','');
INSERT INTO settings(key,value) VALUES('aa_prio','4');
INSERT INTO settings(key,value) VALUES('aa_kinds','update,webpush,watchdog,integration,security,storage');
INSERT INTO settings(key,value) VALUES('aa_mode','instant');
INSERT INTO settings(key,value) VALUES('aa_digest_time','08:00');
INSERT INTO settings(key,value) VALUES('aa_cooldown_h','6');
INSERT INTO settings(key,value) VALUES('aa_max_hour','10');
INSERT INTO settings(key,value) VALUES('aa_disk_pct','5');
INSERT INTO settings(key,value) VALUES('aa_disk_mb','1024');
INSERT INTO settings(key,value) VALUES('aa_integ_min','15');
INSERT INTO settings(key,value) VALUES('aa_update_notified','');
INSERT INTO settings(key,value) VALUES('aa_digest_sent','');
INSERT INTO settings(key,value) VALUES('cal_allow_hosts','');
INSERT INTO settings(key,value) VALUES('twofa_required','0');
INSERT INTO settings(key,value) VALUES('passkey_login','1');
INSERT INTO settings(key,value) VALUES('storage_quota_mb','');
INSERT INTO settings(key,value) VALUES('storage_pool','user');
INSERT INTO settings(key,value) VALUES('support_email','');
INSERT INTO settings(key,value) VALUES('mail_day_limit','');
INSERT INTO settings(key,value) VALUES('announce','');
INSERT INTO settings(key,value) VALUES('signup_mode','off');
INSERT INTO settings(key,value) VALUES('signup_domains','');
INSERT INTO settings(key,value) VALUES('oidc_autocreate','0');
INSERT INTO settings(key,value) VALUES('bk_on','0');
INSERT INTO settings(key,value) VALUES('bk_time','03:30');
INSERT INTO settings(key,value) VALUES('bk_keep_daily','14');
INSERT INTO settings(key,value) VALUES('bk_keep_weekly','8');
INSERT INTO settings(key,value) VALUES('bk_encrypt','0');
INSERT INTO settings(key,value) VALUES('bk_pass','');
INSERT INTO settings(key,value) VALUES('bk_last_day','');
INSERT INTO settings(key,value) VALUES('bk_last_ok','');
INSERT INTO settings(key,value) VALUES('bk_last_name','');
INSERT INTO settings(key,value) VALUES('bk_last_error','');
INSERT INTO settings(key,value) VALUES('bk_last_error_at','');
INSERT INTO settings(key,value) VALUES('bk_enabled_at','');
INSERT INTO settings(key,value) VALUES('public_links','1');
INSERT INTO settings(key,value) VALUES('migr_att_user','1');
INSERT INTO settings(key,value) VALUES('migr_kind','1');
INSERT INTO settings(key,value) VALUES('migr_kind272','1');
INSERT INTO settings(key,value) VALUES('migr_feat8','1');
INSERT INTO settings(key,value) VALUES('migr_feat9','1');
INSERT INTO settings(key,value) VALUES('migr_feat10','1');
INSERT INTO settings(key,value) VALUES('people_visibility','org');
INSERT INTO settings(key,value) VALUES('migr_orgs2220','1');
INSERT INTO settings(key,value) VALUES('migr_ws2280','1');
INSERT INTO settings(key,value) VALUES('migr_ws2300','1');
INSERT INTO settings(key,value) VALUES('migr_listen2300','1');
INSERT INTO settings(key,value) VALUES('migr_folders2220','1');
INSERT INTO settings(key,value) VALUES('migr_folder931','1');
INSERT INTO settings(key,value) VALUES('migr_order988','1');
INSERT INTO settings(key,value) VALUES('migr_notiftpl2330','1');
INSERT INTO settings(key,value) VALUES('migr_scopes215','1');
INSERT INTO settings(key,value) VALUES('migr_completed_by','1');
INSERT INTO settings(key,value) VALUES('migr_folder_path','1');
INSERT INTO settings(key,value) VALUES('migr_tidy_agent','1');
INSERT INTO settings(key,value) VALUES('migr_auditfix','1');
INSERT INTO settings(key,value) VALUES('msg_fts_v','1');
INSERT INTO settings(key,value) VALUES('migr_ev221','1');
