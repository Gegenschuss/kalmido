#!/usr/bin/env python3
"""Checks that the module lists agree (2.20.0, #646; see docs/ARCHITECTURE.md):

  * web client: every static/js/*.js is loaded by a <script> tag in static/index.html, main.js last, and the service
    worker (static/sw.js, SHELL) precaches exactly these files in the same order; 2.53.0 (#1410): or it is loaded on
    demand -- then it stands in LAZY (sw.js) and in LD_MODS (static/js/lazyload.js), in the same order, and has no tag
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

from check_migrations import schema_src as all_schema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERR = []


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "static", "js", "*.js")))
tags = re.findall(r'<script src="/static/js/([\w-]+\.js)"(?: defer)?></script>', read("static", "index.html"))  # 2.191.0 B (#2505): defer
sw = read("static", "sw.js")
_list = lambda name: re.findall(r"'/static/js/([\w-]+\.js)'", (re.search(name + r" = \[(.*?)\];", sw, re.S) or [None, ""])[1])
shell = _list("SHELL")
# 2.53.0 (#1410): the modules loaded on demand: LAZY in sw.js = the files of LD_MODS in lazyload.js (same order), no script tag
lazy = _list("LAZY")
_ld = re.search(r"const LD_MODS = \{(.*?)\n\};", read("static", "js", "lazyload.js"), re.S)
ld_files = [f + ".js" for f in re.findall(r"'([\w-]+)'", re.sub(r"^\s*\w+:", "", _ld.group(1), flags=re.M))] if _ld else []
if lazy != ld_files:
    ERR.append(f"sw.js LAZY differs from LD_MODS in static/js/lazyload.js (same files, same order): {lazy} vs {ld_files}")
if set(lazy) & set(tags):
    ERR.append(f"index.html loads modules that are loaded on demand (LAZY): {sorted(set(lazy) & set(tags))}")
if len(set(lazy)) != len(lazy):
    ERR.append("sw.js LAZY names a module twice")
if sorted(tags + lazy) != files:
    ERR.append(f"index.html script tags + LAZY vs static/js/: missing {sorted(set(files) - set(tags) - set(lazy))}, unknown {sorted(set(tags + lazy) - set(files))}")
# 2.65.0 (#1824): the stylesheets loaded with a module: LAZY_CSS in sw.js = the files of LD_CSS in lazyload.js (same order) =
# static/css/*.css, each once
lazy_css = re.findall(r"'/static/css/([\w-]+\.css)'", (re.search(r"LAZY_CSS = \[(.*?)\];", sw, re.S) or [None, ""])[1])
_lc = re.search(r"const LD_CSS = \{(.*?)\};", read("static", "js", "lazyload.js"), re.S)
ld_css = [f + ".css" for f in re.findall(r"'([\w-]+)'", re.sub(r"^\s*\w+:", "", _lc.group(1), flags=re.M))] if _lc else []
# 2.476.0 (#3487): static/css/start-*.css are no module stylesheets: the server sends them behind app.css (tools/check_appcss.py)
css_files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "static", "css", "*.css"))
                   if not os.path.basename(p).startswith("start-"))
if lazy_css != ld_css:
    ERR.append(f"sw.js LAZY_CSS differs from LD_CSS in static/js/lazyload.js (same files, same order): {lazy_css} vs {ld_css}")
if sorted(lazy_css) != css_files or len(set(lazy_css)) != len(lazy_css):
    ERR.append(f"sw.js LAZY_CSS vs static/css/: missing {sorted(set(css_files) - set(lazy_css))}, unknown {sorted(set(lazy_css) - set(css_files))}")
if len(set(tags)) != len(tags):
    ERR.append("index.html loads a module twice")
if tags and tags[-1] != "main.js":
    ERR.append("index.html: main.js (the start-up) must be the last script")
# 2.476.0 (#3487): new start scripts no longer pile up right before main.js (the most frequent conflict in index.html after
# app.css): they go into the part below the mark, sorted by name, so two packages land on different lines. The scripts above
# the mark keep their order (defer runs them in it; some depend on it) and their number only goes down.
LAYOUT_TOP_MAX = 138  # 01.11.2026: 136 start scripts above the mark when the rule came in, +2 margin for packages landing during its check; lower it when one moves or goes
_ih = read("static", "index.html")
_mk = re.search(r"<!-- [^\n]*new start scripts go below this line[^\n]*-->\n", _ih)
if not _mk:
    ERR.append("index.html: the mark of the sorted start scripts (before main.js) is missing")
else:
    _top = re.findall(r'<script src="/static/js/([\w-]+\.js)"', _ih[:_mk.start()])
    _low = _ih[_mk.end():_ih.find('<script src="/static/js/main.js"')]
    _new = re.findall(r'<script src="/static/js/([\w-]+\.js)" defer></script>\n', _low)
    if "".join(f'<script src="/static/js/{n}" defer></script>\n' for n in _new) != _low:
        ERR.append("index.html: between the mark and main.js only start scripts, one per line (<script src=\"/static/js/x.js\" defer></script>)")
    if _new != sorted(_new):
        ERR.append(f"index.html: the start scripts below the mark are sorted by name: {_new} -> {sorted(_new)}")
    if len(_top) > LAYOUT_TOP_MAX:
        ERR.append(f"index.html: {len(_top)} start scripts above the mark (limit {LAYOUT_TOP_MAX}): a new start script goes below "
                   "the mark, sorted by name -- better still, load it on demand (LD_MODS in static/js/lazyload.js)")
# 2.312.0 (#3285): render() (render.js) draws only once main.js declared bootDone(); renamed or moved = a blank app
if not re.search(r"^function bootDone\(", read("static", "js", "main.js"), re.M):
    ERR.append("static/js/main.js: function bootDone() must stay declared there (render.js waits for it)")
if shell != tags:
    ERR.append("sw.js SHELL: the static/js/ files differ from index.html (same files, same order)")
# 2.126.0 D (#1992 O7): every file the service worker precaches exists (addAll fails on a single 404: the new version would
# never install), and the cache name is counted up with every version -- its line names the version it belongs to
for name in ("SHELL", "LAZY", "LAZY_CSS"):
    for u in re.findall(r"'/(static/[^']+)'", (re.search(name + r" = \[(.*?)\];", sw, re.S) or [None, ""])[1]):
        # 2.191.0 A (#2518): the core texts of a language (<code>.core.json) are split from <code>.json by the server
        if not os.path.isfile(os.path.join(ROOT, re.sub(r"^(static/i18n/[\w-]+)\.core\.json$", r"\1.json", u))):
            ERR.append(f"sw.js {name}: /{u} does not exist")
# 2.742.0 (#5217): the web manifest (kalmido/core/codemanifest.py, tools/web_manifest.py) names every file under static/: each file
# the app page loads and the service worker precaches must be one of them, else the release's list misses code the browser runs
sys.path.insert(0, os.path.join(ROOT, "kalmido", "core"))
import codemanifest  # noqa: E402
_cm_rels = set(codemanifest.cm_static_rels(os.path.join(ROOT, "static")))
for _u in [m.group(2) for m in codemanifest.CM_ASSET_RE.finditer(read("static", "index.html"))] + \
        [u[8:] for v in codemanifest.cm_sw_lists(sw).values() for u in v if not re.fullmatch(r"/static/i18n/[\w-]+\.core\.json", u)]:
    if _u not in _cm_rels:
        ERR.append(f"web manifest: /static/{_u} (index.html / sw.js) is no file under static/ (kalmido/core/codemanifest.py cm_static_rels)")
_cache = re.search(r"const CACHE = 'tasks-shell-v\d+';\s*// app (\S+)", sw)
_ver = read("VERSION").strip()
if not _cache or _cache.group(1) != _ver:
    ERR.append(f"static/sw.js: count CACHE up for version {_ver} and name it in the comment of that line (// app {_ver})")
# 2.579.0 (#4283): the service worker and the page open the same IndexedDB databases (the offline queue "kalmido-outbox"):
# the same name, the same version and the same stores - a version counted up on one side only makes the other side's open()
# fail (VersionError) or run an upgrade without its stores, and the queue falls back to localStorage without a word
_IDB_RE = re.compile(r"indexedDB\.open\('([\w-]+)',\s*(\d+)\);[^\n]*\n([^\n]*)")
_idb_store = lambda line: sorted(set(re.findall(r"createObjectStore\('([\w-]+)'(?:,\s*(\{[^}]*\}))?", line)))
_idb_page = {}
for p in sorted(glob.glob(os.path.join(ROOT, "static", "js", "*.js"))):
    for m in _IDB_RE.finditer(read("static", "js", os.path.basename(p))):
        _idb_page.setdefault(m.group(1), set()).add((int(m.group(2)), tuple(_idb_store(m.group(3))), os.path.basename(p)))
_idb_sw = [(m.group(1), int(m.group(2)), tuple(_idb_store(m.group(3)))) for m in _IDB_RE.finditer(sw)]
if "indexedDB" in sw and not _idb_sw:
    ERR.append("static/sw.js uses IndexedDB, but tools/check_layout.py finds no indexedDB.open('<name>', <version>) there (keep that form)")
for _n, _v, _st in _idb_sw:
    _pg = _idb_page.get(_n, set())
    if not _pg:
        ERR.append(f"static/sw.js opens the IndexedDB database {_n!r}, no file of static/js does: the worker and the page must share it")
    for _pv, _pst, _pf in sorted(_pg):
        if (_pv, _pst) != (_v, _st):
            ERR.append(f"IndexedDB {_n!r}: static/sw.js opens version {_v} with the stores {list(_st)}, static/js/{_pf} version {_pv} with {list(_pst)} (count both up together)")

init = read("kalmido", "__init__.py")
m = re.search(r"ORDER = \((.*?)\n\)", init, re.S)
order = re.findall(r'"([\w.]+)"', m.group(1)) if m else []
mods = sorted(os.path.relpath(p, os.path.join(ROOT, "kalmido"))[:-3].replace(os.sep, ".")
              for p in glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True)
              if not p.endswith("__init__.py") and "migrations.d" not in p)  # 2.485.0 (#3939): fragments are data, not modules
if sorted(order) != mods or len(set(order)) != len(order):
    ERR.append(f"kalmido/__init__.py ORDER vs the package: missing {sorted(set(mods) - set(order))}, unknown {sorted(set(order) - set(mods))}")
# 2.624.0 (#3941): new modules no longer land all over ORDER (the most frequent conflict in kalmido/__init__.py): one without
# an order need goes into the sorted block at its end (one per line, sorted by name, like the start scripts of index.html);
# after the block only core.idem and startup, which must stay last. The modules above the block keep their order.
ORDER_TAIL = ["core.idem", "startup"]
_om = re.search(r"\n    # -- sorted block [^\n]*\n(.*?)    # -- end of the sorted block[^\n]*\n(.*)", m.group(1) + "\n" if m else "", re.S)
if not _om:
    ERR.append("kalmido/__init__.py ORDER: the marks of the sorted block (# -- sorted block ... / # -- end of the sorted block) are missing")
else:
    _blk = [ln for ln in _om.group(1).splitlines() if not re.match(r"\s*#", ln)]
    _sorted = [re.match(r'    "([\w.]+)",(  #.*)?$', ln) for ln in _blk]
    if not all(_sorted):
        ERR.append(f"kalmido/__init__.py ORDER: in the sorted block one module per line (    \"pkg.mod\",  # comment): {[ln for ln, x in zip(_blk, _sorted) if not x]}")
    _names = [x.group(1) for x in _sorted if x]
    if _names != sorted(_names):
        ERR.append(f"kalmido/__init__.py ORDER: the sorted block is sorted by name: {_names} -> {sorted(_names)}")
    if re.findall(r'"([\w.]+)"', _om.group(2)) != ORDER_TAIL:
        ERR.append(f"kalmido/__init__.py ORDER: after the sorted block only {ORDER_TAIL}: a new module goes into the block, sorted by name")
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
    "hub_mailbox_rules": "2.581.0 (#4804): the document rules of one workspace mailbox (box_id -> hub_mailboxes, which carries org_id; created_by only records who wrote it; the app checks the manage right of the mailbox's workspace)",
    "module_card_people": "2.575.0 (#3778): who has a module card of an organisation (the card row carries org_id; the app checks the card and that the person is a member)",
    "appt_pages": "2.94.0 B (#1929): a person's own public booking page (like ev_cals: owned by the person, no workspace; the lead goes to office_org_id, checked by the app)",
    "appt_types": "2.94.0 B (#1929): the appointment types of a person's own booking page (user_id = the owner)",
    "appt_bookings": "2.94.0 B (#1929): bookings on a person's own booking page (user_id = the owner; event / contact / lead are checked rows of their own areas)",
    "orgs": "2.47.3 (#1360): personal_of = the owner of a personal office (a hidden orgs row; its own policy: only the owner's app.org_ids reach it)",
    "agent_setup_codes": "2.44.0 (#1517): a one-time setup code of one agent, issued by its owner / an instance admin and redeemed without an account (the agent row carries the workspace)",
    "oauth_codes": "2.488.0 (#3363): a one-time authorization code of the hosted MCP access: the person who agreed and the agent they may manage (agents/mcpremote.py mcpr_may; the agent row carries the workspace)",
    "oauth_grants": "2.488.0 (#3363): an access of an MCP client to one agent, given by a person who may manage it (like agent_setup_codes; the agent row carries the workspace, its token goes through /api/v1)",
    "agent_server": "2.557.0 B (#4670): the settings of one server agent (agent_id = the agent; its row in agents carries the workspace), managed by who may edit the agent; its key is sealed and never served",
    "agent_runs": "2.557.0 B (#4670): the runs of one server agent (numbers and states only; the agent row carries the workspace, its tool calls go through /api/v1)",
    "attachments": _TASK, "activity": _TASK, "task_push": _TASK,
    "task_decisions": _TASK, "task_deps": _TASK, "task_relations": _TASK, "pomos": _TASK, "tidy_pending": _TASK, "task_people": _TASK,
    "habits": _OWN, "pl_conns": _OWN + " (Paperless connection, unused since 2.36.0, kept)",
    "pl_conn_users": "who could use a shared Paperless connection (unused since 2.36.0, kept)", "pl_tokens": _OWN,
    "user_task_order": _OWN + " (2.40.0 #1344: the own order of My tasks; rows only for tasks the person sees)",
    "user_mine_sections": _OWN + " (2.569.0 #4395: the own sections of My tasks; only names, no task data)",
    "user_mine_rules": _OWN + " (2.823.0 #4773: the own rules of My tasks; they only move tasks in the own order)",
    "user_mine_rule_runs": _OWN + " (2.823.0 #4773: once per rule, task and occasion; ids and a key, no task data)",
    "user_keys": _OWN + " (2.64.0 #1864: the wrapped account key; read and written only by core/orgcrypt.py as system, never served)",
    "wait_hidden": _OWN + " (2.41.0 #1205: Waiting-on texts the person took out of their own suggestions)",
    "view_layouts": _OWN + " (2.55.0 #1069: saved arrangements of a view; layout json only, no content)",
    "e2e_keys": _OWN + " (2.42.0 #828: the person's public key + wrapped key bundle; others only get the public key of a DM partner)",
    "task_enc_notes": "2.42.0 (#828): one person's encrypted note of a task, bound through the task (need_task) and readable only by its author",
    "task_note_locks": "2.48.0 (#1642): the locked note of a task, bound through the task (need_task), readable only by the person who locked it",
    # 2.48.0 (#1207): the file store's rows below a node, bound through fs_nodes (org_id + row-level security, files/store.py fs_role)
    "fs_versions": "2.48.0 (#1207): the versions of a file store node, bound through the node (need_node)",
    "fs_shares": "2.48.0 (#1207): shares of a file store node, bound through the node; share targets are checked against its workspace (tenancy CHECKS)",
    "fs_log": "2.48.0 (#1207): the access history of a file store node, bound through the node (shown to its owners and editors)",
    "filters": _OWN, "user_settings": _OWN, "sessions": _OWN, "push_subs": _OWN, "templates": "2.905.0 (#5288): a kind of the shared core (owner_id; an organisation's read by its members, lists/templates.py)", "template_files": _OWN, "cal_subs": _OWN,
    "recovery_codes": _OWN, "webauthn_creds": _OWN, "api_tokens": _OWN,
    "imports": _OWN, "sample_items": _OWN, "app_passwords": _OWN, "dav_sync2": _OWN, "journal": _OWN, "contact_care": _OWN,
    "life_device_links": _OWN + " (2.140.0 B #2136: the link of a private device with office equipment; each side is checked on reading)",
    "user_invites": "an invitation / password link of one account (admins only)", "folder_props": _OWN + " (the defaults of a folder; each list keeps its org_id)",
    "folder_heads": _OWN + " (2.83.0 #1427: the header strip style of an owner's folder; no content)",
    "rss_feeds": _OWN + " (2.85.0 #1162: a person's feeds, never shared, never an agent's; 2.172.0 B #2677: org_id added by MIGRATIONS = an organisation's feed)", "rss_items": _OWN + " (2.85.0 #1162: the articles of the own feeds)",
    "rss_reads": "2.172.0 B (#2677): a person's own read mark of an article (bound through item_id -> rss_items -> rss_feeds.org_id)",
    # 2.89.0 (#1916): parts of a table (sheets carries org_id; every route checks the sheet first: sheets/core.py sh_need)
    "sheet_cells": "2.89.0 (#1916): a cell of a table (bound through sheet_id -> sheets.org_id)",
    "sheet_changes": "2.89.0 (#1916): the trail of an agent call on a table (bound through sheet_id -> sheets.org_id)",
    "sheet_lastvals": "2.89.0 (#1916): the last value of a cell one person saw (their own rows, bound through the cell's sheet)",
    "sheet_hist": "2.124.0 B (#2112): the change history of a table's cells (bound through sheet_id -> sheets.org_id, read only with the sheet)",
    "space_moves": "2.96.0 (#1941): a page / table moved between workspaces (both sides; read only through the object's visibility: wiki/wkmove.py, sheets/shmove.py)",
    "doc_office_moves": "2.547.0 (#4434): the undo of one person's receipts move into the office (read and written only for user_id = the signed-in person, docs/areamove.py; the documents carry the workspace)",
    "deleted_accounts": "2.152.0 B (#2172): the instance's journal of deleted accounts (hashes only), read by the restore alone, never by a person",
    "folder_agents": "2.41.0 (#1420): the agents of an owner's folder; every list share goes through the workspace rule (folder_apply / list_agent_set)",
    "obj_notif_cap": _OWN + " (2.33.0 #927: the owner's notification template of a list / folder; it only limits pushes of people already in its lists; 2.981.0 #5287: was list_notif / folder_notif)",
    "git_folders": _OWN + " (2.33.0 #934: the owner's folder repository; it serves only the owner's lists in that folder)",
    "login_ips": "2.33.0 (#834): private sign-in addresses for the proxy check, admins only (instance diagnostics)",
    "admin_login_ips": "2.36.2 (#1133): hashed sign-in addresses of admins for the security alerts (instance diagnostics)",
    "events": _CAL, "ev_reminded": _CAL, "event_attendees": _CAL + "; invited people must be visible",
    "contacts": _BOOK,
    "groups": "instance-wide groups of the operator: visible only through members one may see (B1); shares go through the rule",
    "group_members": "members of a group (see groups); materialized into list_members under the workspace rule",
    "tchat_msgs": _CHAT, "tchat_reads": _CHAT,
    "tchat_thread_reads": "2.139.0 A (#2127): a person's read mark in a thread of a team chat room: bound through its room (like tchat_reads)",
    "agent_chat": "a person's chat with an agent (agent_id + user_id; the agent's workspace decides what it sees)",
    "agent_chat_prefs": "2.233.0 A (#2848): a person's own settings for one agent chat (agent_id + user_id, like agent_chat)",
    "agent_push_held": "2.236.0 B (#2905): a count of pushes an agent held back for one person in its quiet window (no content; like agent_chat)",
    "quiet_push_held": "2.367 (#2966): a count of a person's pushes held back in their own quiet hours (no content; only that person)",
    "push_gate": "2.367 (#2967): counts of a person's bundled pushes (no content; only that person, the summary checks access again)",
    "agent_rules": _AGENT + " (2.235.0 C #2903: its standing rules; the source is checked against what the agent sees)",
    # 2.763.0 (#5269): replaces comment_reactions, tchat_rx and chat_reactions
    # 2.905.0 (#5284): replaces task_seen
    "obj_seen": "a person's own read mark of the shared core on an object (kind + ref_id -> a task); read and written only for that person, the area checks the object before it writes one",
    # 2.947.0 (#5275): replaces task_list_tags (list_tags / org_tags: obj_tags, bound through its scope; a label has org_id)
    "obj_tag_links": "a tag of the shared core on an object (kind + obj_id -> a task's project); created_by only names who set it, the area checks the object before its tags are read or written",
    "obj_reactions": "a reaction of the shared core on its target (target_kind + target_id -> a comment's task, a team chat message's room, an agent chat message's conversation); the area checks the target before a reaction is read or written",
    "agent_steps": "2.32.0 (#1081): an agent's steps for ONE person (its chat answer / its job for that person); only that person reads them",
    "agent_events": _AGENT + " (events are made only for lists it is in)",
    "job_watch": _AGENT + " (2.392.2 #3366: the watchdog's findings; the owner reads them only for tasks they still see, agents/waiting.py)",
    "agent_bridges": _AGENT + " (an owner's approval between two lists)",
    "chat_saves": _OWN + " (2.37.0 #1159: which chat message a person saved as a task; the task itself keeps its list)",
    "kid_parents": _FAM, "kid_stars": _FAM, "kid_rewards": _FAM,
    "kid_pins": _FAM, "kid_pin_open": _OWN + " (2.49.0 #1551: the session of a kid)",
    "view_layout_offers": "2.55.0 (#1068): an arrangement template from one person to another (no workspace, no content); only the two see it",
    # 2.49.0 (#1106): finding people by e-mail is person to person, outside every workspace (accounts/discover.py)
    "disc_profiles": _OWN, "disc_tokens": _OWN, "disc_quota": _OWN, "conn_blocks": _OWN,
    "conn_requests": "2.49.0 (#1106): a request between two people (no workspace); only the two see it",
    "conn_links": "2.49.0 (#1106): an accepted connection between two people, like a private shared list (no workspace)",
    "wiki_keys": "2.64.3 (#1817): a wrapped key of a knowledge space -> its wiki_spaces row (org_id or owner_id); only the person it is wrapped for reads it",
    "fs_lock_keys": "2.353.0 A (#2758): a wrapped key of a locked folder -> its fs_locks row (org_id or the folder's owner); only the person it is wrapped for reads it",
    "wiki_key_pending": "2.64.3 (#1817): an organisation member waiting for the key of a knowledge space -> its wiki_spaces row (org_id)",
    "msv_links": "2.73.0 A (#661): the accounts of one person on other Kalmido servers (accounts/servers.py); only the person sees them",
    "ev_cal_feeds": _CAL + " (2.111.0 B #2056: a person's subscription link; every fetch checks that the person still sees the calendar)",
    "ev_invite_day": _OWN + " (2.111.0 B #2056: the person's count of invitation mails per day)",
    "notify_mail_queue": _OWN + " (2.142.0 A #2146: the person's events waiting for their bundled mail; ids only, each task is checked with task_visible when sending)",
    "abs_cal_feeds": _OWN + " (2.155.0 B #2076: the person's subscription link of their own absences + holidays; never data of others)",
    "idem_keys": _OWN + " (2.270.0 C #3022: the person's idempotency keys and the stored answer of their own write request; read only for the same person, method and path)",
}
schema_src = re.sub(r"--[^\n]*", "", all_schema(ROOT))  # 2.475.0 (#3478): + migrations.d
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

# 2.33.0: the client modules share one global scope -- a second top-level function of the same name silently replaces
# the first (the message search's msToggle broke the milestone switch)
_seen = {}
for f in sorted(glob.glob(os.path.join(ROOT, "static", "js", "*.js"))):
    for m in re.finditer(r"^(?:async )?function ([A-Za-z_$][\w$]*)", open(f, encoding="utf-8").read(), re.M):
        n = m.group(1)
        if n in _seen and _seen[n] != os.path.basename(f):
            ERR.append(f"client: function {n} is defined in {_seen[n]} and {os.path.basename(f)} (one replaces the other)")
        _seen.setdefault(n, os.path.basename(f))

# 2.48.0: the stylesheet's braces balance -- a lost "}" after a merge nests every later rule into the block before it
# (the end of an @media print block made the rules of three parts apply only when printing)
# 2.476.0 (#3487): the same per start style file, and app.css does not grow (tools/check_appcss.py)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_appcss  # noqa: E402
ERR += check_appcss.braces("app.css", read("static", "app.css")) + check_appcss.errors(ROOT)

# 2.192.0 C (#2514): new Python suites import check/sess/until from tests/kt.py (tools/check_kt.py, list tools/kt_legacy.txt)
import check_kt  # noqa: E402
_kt_err, _kt_warn = check_kt.errors()
ERR += [e.removeprefix("ERROR: ") for e in _kt_err]
for _w in _kt_warn:
    print(_w)

# 2.623.0 (#4950): a test file must end with sys.exit(done(...)), not a bare done(...) (tools/check_done_exit.py)
import check_done_exit  # noqa: E402
ERR += check_done_exit.errors()

# 2.638.0 (#4294): every public_links_on(c, KIND) names a kind of PUB_KINDS (tools/check_pubkinds.py)
import check_pubkinds  # noqa: E402
ERR += check_pubkinds.errors()

# 2.653.0 (#5087): finger operation hangs on isTouchUi(), the width (isMobile()) only on layout (tools/check_touch_switch.py,
# list tools/touch_switch_legacy.txt); runs here so the CI lint and the Mac lint both have it
import check_touch_switch  # noqa: E402
_ts_err, _ts_warn = check_touch_switch.errors()
ERR += _ts_err
for _w in _ts_warn:
    print(_w)

# 2.726.0 (#5164): a menu entry that opens a further menu / sheet / picker shows the arrow ({next: 1} or {more}),
# tools/check_menu_next.py; runs here so the CI lint and the Mac lint both have it
import check_menu_next  # noqa: E402
ERR += check_menu_next.errors()

for e in ERR:
    print("ERROR:", e)
print(f"check_layout: {len(tags)} client modules, {len(order)} server modules, {n_people} tables with people, {len(ERR)} error(s)")
sys.exit(1 if ERR else 0)
