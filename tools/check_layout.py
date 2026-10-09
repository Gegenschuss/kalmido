#!/usr/bin/env python3
"""Checks that the module lists agree (2.20.0, #646; see docs/ARCHITECTURE.md):

  * web client: every static/js/*.js is loaded by a <script> tag in static/index.html, main.js last, and the service
    worker (static/sw.js, SHELL) precaches exactly these files in the same order
  * server: kalmido/__init__.py ORDER names every module of the package exactly once (and nothing else)
  * schema (2.30.0, #1036): every table with a reference to a person (a column REFERENCES users(id) or named user_id,
    owner_id, created_by, ...) carries org_id or list_id -- the workspace boundary can be checked on it -- or stands in
    TENANT_EXEMPT below with the reason why it does not need one (bound through its parent, the person's own rows, ...)

usage: python3 tools/check_layout.py      exit code 1 on a mismatch
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERR = []


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "static", "js", "*.js")))
tags = re.findall(r'<script src="/static/js/([\w-]+\.js)"></script>', read("static", "index.html"))
shell = re.findall(r"'/static/js/([\w-]+\.js)'", read("static", "sw.js"))
if sorted(tags) != files:
    ERR.append(f"index.html script tags vs static/js/: missing {sorted(set(files) - set(tags))}, unknown {sorted(set(tags) - set(files))}")
if len(set(tags)) != len(tags):
    ERR.append("index.html loads a module twice")
if tags and tags[-1] != "main.js":
    ERR.append("index.html: main.js (the start-up) must be the last script")
if shell != tags:
    ERR.append("sw.js SHELL: the static/js/ files differ from index.html (same files, same order)")

init = read("kalmido", "__init__.py")
m = re.search(r"ORDER = \((.*?)\n\)", init, re.S)
order = re.findall(r'"([\w.]+)"', m.group(1)) if m else []
mods = sorted(os.path.relpath(p, os.path.join(ROOT, "kalmido"))[:-3].replace(os.sep, ".")
              for p in glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True)
              if not p.endswith("__init__.py"))
if sorted(order) != mods or len(set(order)) != len(order):
    ERR.append(f"kalmido/__init__.py ORDER vs the package: missing {sorted(set(mods) - set(order))}, unknown {sorted(set(order) - set(mods))}")
for p in glob.glob(os.path.join(ROOT, "kalmido", "*", "__init__.py")):
    body = re.sub(r'^""".*?"""\s*', "", read(p), flags=re.S).strip()
    if body:
        ERR.append(f"{os.path.relpath(p, ROOT)} must stay empty (only a docstring): the load order is kalmido/__init__.py's job")

# ---- 2.30.0 (#1036): the schema rule. A new table with a person in it must say how the boundary between organisations and
# private applies to it: an org_id / list_id column, or an entry here with the reason.
PERSON_COLS = ("user_id", "owner_id", "created_by", "actor_id", "kid_id", "agent_id", "assignee_id", "by_id")
_TASK = "per task (task_id -> its list's workspace and rights)"
_OWN = "the person's own rows (read and written only as user_id = me), never shared"
_CAL = "per calendar (cal_id / event_id -> ev_cals.org_id, the members' workspace rule)"
_BOOK = "per address book (book_id -> books.org_id, the members' workspace rule)"
_CHAT = "a team chat room (room_id -> tchat_rooms: a list's room or a direct chat between people who may see each other)"
_AGENT = "the agent's own rows (agent_id -> agents.org_id; its lists through list_members)"
_FAM = "the household of a family (Family module): private by definition, never an organisation's"
TENANT_EXEMPT = {
    "task_tags": _TASK, "attachments": _TASK, "comments": _TASK, "activity": _TASK, "task_seen": _TASK, "task_push": _TASK,
    "task_deps": _TASK, "pomos": _TASK, "tidy_pending": _TASK, "task_people": _TASK, "comment_reactions": "per comment -> its task",
    "habits": _OWN, "pl_conns": _OWN + " (a person's own Paperless connection; shared ones by the admin, B4)",
    "pl_conn_users": "who may use a shared Paperless connection (instance configuration, B4)", "pl_tokens": _OWN,
    "filters": _OWN, "user_settings": _OWN, "sessions": _OWN, "push_subs": _OWN, "templates": _OWN, "cal_subs": _OWN,
    "recovery_codes": _OWN, "webauthn_creds": _OWN, "api_tokens": _OWN, "webhooks": _OWN + " (deliveries only for visible tasks)",
    "imports": _OWN, "sample_items": _OWN, "app_passwords": _OWN, "dav_sync2": _OWN, "journal": _OWN, "contact_care": _OWN,
    "user_invites": "an invitation / password link of one account (admins only)", "folder_props": _OWN + " (the defaults of a folder; each list keeps its org_id)",
    "folder_people": "the owner's folder shared with people: every list share goes through the workspace rule (_folder_member_add)",
    "ev_cal_members": _CAL, "events": _CAL, "ev_reminded": _CAL, "event_attendees": _CAL + "; invited people must be visible",
    "book_members": _BOOK, "contacts": _BOOK,
    "groups": "instance-wide groups of the operator: visible only through members one may see (B1); shares go through the rule",
    "group_members": "members of a group (see groups); materialized into list_members under the workspace rule",
    "tchat_msgs": _CHAT, "tchat_reads": _CHAT, "tchat_rx": _CHAT,
    "agent_chat": "a person's chat with an agent (agent_id + user_id; the agent's workspace decides what it sees)",
    "chat_reactions": "per agent chat message",
    "agent_steps": "2.32.0 (#1081): an agent's steps for ONE person (its chat answer / its job for that person); only that person reads them",
    "agent_events": _AGENT + " (events are made only for lists it is in)",
    "agent_bridges": _AGENT + " (an owner's approval between two lists)",
    "kid_parents": _FAM, "kid_stars": _FAM, "kid_rewards": _FAM,
}
schema_src = re.sub(r"--[^\n]*", "", read("kalmido", "core", "schema.py"))
tables = {m.group(1): m.group(2) for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);", schema_src, re.S)}
for m in re.finditer(r'ALTER TABLE (\w+) ADD COLUMN (\w+) ([^"]*)"', schema_src):
    tables[m.group(1)] = tables.get(m.group(1), "") + f", {m.group(2)} {m.group(3)}"


def _cols(body):
    out, depth, cur = [], 0, ""
    for ch in body:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [x for x in out + [cur.strip()] if x and not x.upper().startswith(("PRIMARY", "UNIQUE", "FOREIGN", "CHECK"))]


n_people = 0
for t, body in sorted(tables.items()):
    cols = _cols(body)
    names = {x.split()[0] for x in cols}
    person = any("REFERENCES users" in x for x in cols) or bool(names & set(PERSON_COLS))
    if not person:
        continue
    n_people += 1
    if names & {"org_id", "list_id"}:
        if t in TENANT_EXEMPT:
            ERR.append(f"schema: {t} has org_id / list_id now: take it off TENANT_EXEMPT (tools/check_layout.py)")
    elif not TENANT_EXEMPT.get(t):
        ERR.append(f"schema: table {t} refers to a person but has neither org_id nor list_id: add one, or put it on TENANT_EXEMPT "
                   "in tools/check_layout.py with the reason why the workspace boundary needs none (#1036)")
for t in sorted(set(TENANT_EXEMPT) - set(tables)):
    ERR.append(f"schema: TENANT_EXEMPT names {t}, which is no table (any more)")

for e in ERR:
    print("ERROR:", e)
print(f"check_layout: {len(tags)} client modules, {len(order)} server modules, {n_people} tables with people, {len(ERR)} error(s)")
sys.exit(1 if ERR else 0)
