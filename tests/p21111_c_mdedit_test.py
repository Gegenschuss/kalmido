#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1111.0 (#5830): agents send only the change of a long text - append (at the end or under a heading) and replace one
section - for knowledge pages, a task's notes and a project's description; one shared building block (core/mdedit.py).
Invented names only.
 - a task's notes: POST /api/v1/tasks/{id}/notes/append (end: exactly one empty line before; under a heading: the end of
   its section) and .../notes/replace-section (the text below one heading up to the next of the same or a higher level)
 - replace-section needs the version (400 version_required without, 409 + the current task when outdated); append does not
 - the heading not there = 404 heading_not_found, there twice = 409 heading_ambiguous, both with the headings, nothing
   written; headings in a code fence do not count
 - the same save as the whole write: the task's history has the change, a locked task is marked locked_bypass (as PATCH)
 - a project's description: .../overview/append and .../overview/replace-section, the text before in its history
 - a knowledge page: .../wiki/pages/{id}/replace-section (version required, ambiguous heading 409)
 - the rights of the whole write: a token without the scope 403 (OpenAPI names tasks:write / structure / wiki:write), a
   view share 403, another person's agent 404
 - an approval card of such a step shows only the lines it changes (GET /api/approvals/diff: append / section)
 - tenant-matrix: task, list, wiki_v1 (another person's agent: 404 on her task, her project and her page)
 - freelancer-matrix: tasks, lists, wiki (a person without an organisation: her own agent and her own token change her
   task's notes, her project's description and her page)
usage: p21111_c_mdedit_test.py <datadir>"""
import os
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, setup

V = B + "/api/v1"
os.environ["KALMIDO_AGENT_CONTROL_NEW"] = "approve_all"  # the real default; the agent is set to free below, then back for the cards
fresh(prefix="P21082")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, OTTO = freelancer(B, A, "otto")
SCOPES = ["read", "tasks:write", "structure", "wiki:read", "wiki:write"]


def err(r):
    try:
        e = r.json()["error"]
        return e if isinstance(e, dict) else {}
    except (ValueError, KeyError, TypeError):
        return {}


def agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": SCOPES})
    check(r.status_code in (200, 201), f"personal agent {name} {r.status_code} {r.text[:150]}")
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


def level(aid, lv, s=F):
    check(s.patch(B + f"/api/agents/{aid}/control", json={"level": lv}).ok, f"setup: agent level {lv}")


FA, FH = agent(F, "fridabot")
OA, OH = agent(OTTO, "ottobot")
level(FA, "free")
level(OA, "free", OTTO)


def api(method, path, h=None, **kw):
    return requests.request(method, V + path, headers=h or FH, **kw)


def notes(tid):
    return dbx("SELECT content FROM tasks WHERE id=?", (tid,))[0][0]


def task(title, text, lid):
    r = F.post(B + "/api/tasks", json={"title": title, "list_id": lid, "notes": text})
    check(r.ok, f"setup: task {title} {r.status_code} {r.text[:150]}")
    return r.json()["id"]


FL = F.post(B + "/api/lists", json={"name": "Frida launch", "kind": "project"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "setup: the project is shared with her agent to edit")
SPEC = "# Spec\nintro\n\n## Plan\n- step 1\n\n## Risks\n- none\n```\n## not a heading\n```\n"
T = task("Spec", SPEC, FL)

# ================================================================ scopes and OpenAPI
spec = requests.get(V + "/openapi.json").json()["paths"]
for p, sc in (("/tasks/{id}/notes/append", "tasks:write"), ("/tasks/{id}/notes/replace-section", "tasks:write"),
              ("/lists/{id}/overview/append", "structure"), ("/lists/{id}/overview/replace-section", "structure"),
              ("/wiki/pages/{id}/replace-section", "wiki:write")):
    check(spec.get(p, {}).get("post", {}).get("x-kalmido-scope") == sc, f"OpenAPI: POST {p} needs {sc}")
RO = F.post(B + "/api/me/tokens", json={"name": "ro", "scopes": ["read"]}).json().get("token")
r = api("POST", f"/tasks/{T}/notes/append", h={"Authorization": "Bearer " + RO}, json={"text": "x"})
check(r.status_code == 403 and err(r).get("required_scope") == "tasks:write", f"a read token: 403 tasks:write ({r.status_code} {r.text[:150]})")

# ================================================================ a task's notes: append
a0 = dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND user_id=?", (T, FA))[0][0]
r = api("POST", f"/tasks/{T}/notes/append", json={"text": "Found: the cache"})
check(r.ok and notes(T) == SPEC.rstrip("\n") + "\n\nFound: the cache\n", f"append at the end: one empty line before {r.status_code} {notes(T)!r}")
check(r.ok and r.json().get("notes") == notes(T), "the answer is the task with its notes")
check(dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND user_id=?", (T, FA))[0][0] > a0, "the task's history has the agent's change")
r = api("POST", f"/tasks/{T}/notes/append", json={"text": "- step 2", "under": "plan"})
check(r.ok and "## Plan\n- step 1\n\n- step 2\n\n## Risks" in notes(T), f"under Plan: the end of that section {notes(T)!r}")
before = notes(T)
r = api("POST", f"/tasks/{T}/notes/append", json={"text": "x", "under": "not a heading"})
check(r.status_code == 404 and err(r).get("code") == "heading_not_found" and err(r).get("headings") == ["Spec", "Plan", "Risks"],
      f"an unknown heading: 404 with the headings, the fenced line is none ({r.status_code} {r.text[:200]})")
check(api("POST", f"/tasks/{T}/notes/append", json={"text": "  "}).status_code == 400, "an empty text: 400")
check(api("POST", f"/tasks/{T}/notes/append", json={"text": "x", "notes": "whole"}).status_code == 400, "an unknown field: 400")
check(notes(T) == before, "the refused calls wrote nothing")

# ================================================================ a task's notes: replace a section
r = api("POST", f"/tasks/{T}/notes/replace-section", json={"heading": "Risks", "text": "- the cache"})
check(r.status_code == 400 and err(r).get("code") == "version_required", f"replace without a version: 400 version_required ({r.status_code})")
r = api("POST", f"/tasks/{T}/notes/replace-section", json={"heading": "Risks", "text": "- the cache", "expect_updated_at": "2000-01-01T00:00:00Z"})
check(r.status_code == 409 and (r.json().get("current") or {}).get("notes") == before, f"an outdated version: 409 with the current task ({r.status_code})")
cur = api("GET", f"/tasks/{T}").json()
r = api("POST", f"/tasks/{T}/notes/replace-section", json={"heading": "## Risks", "text": "- the cache\n- the date", "expect_updated_at": cur["updated_at"]})
want = "# Spec\nintro\n\n## Plan\n- step 1\n\n- step 2\n\n## Risks\n\n- the cache\n- the date\n"
check(r.ok and notes(T) == want, f"replace the Risks section (to the end, the fence went with it) {r.status_code} {notes(T)!r}")
cur = api("GET", f"/tasks/{T}").json()
r = api("POST", f"/tasks/{T}/notes/replace-section", json={"heading": "Plan", "text": "- one step", "expect_updated_at": cur["updated_at"]})
check(r.ok and notes(T) == "# Spec\nintro\n\n## Plan\n\n- one step\n\n## Risks\n\n- the cache\n- the date\n", f"a middle section: the next heading stays {notes(T)!r}")
T3 = task("Long", "# " + "a" * 2000 + "\nbody\n## Real\nx\n", FL)
r = api("POST", f"/tasks/{T3}/notes/append", json={"text": "y", "under": "zzz"})
check(r.status_code == 404 and err(r).get("headings") == ["Real"], f"review F1: a line over 1000 characters is no heading {r.text[:120]}")
T2 = task("Twice", "## Plan\na\n## Plan\nb\n", FL)
cur = api("GET", f"/tasks/{T2}").json()
r = api("POST", f"/tasks/{T2}/notes/replace-section", json={"heading": "Plan", "text": "c", "expect_updated_at": cur["updated_at"]})
check(r.status_code == 409 and err(r).get("code") == "heading_ambiguous" and err(r).get("headings") == ["Plan", "Plan"]
      and notes(T2) == "## Plan\na\n## Plan\nb\n", f"a heading twice: 409 heading_ambiguous, nothing written ({r.status_code} {r.text[:200]})")
r = api("POST", f"/tasks/{T2}/notes/replace-section", json={"heading": "Gone", "text": "c", "expect_updated_at": cur["updated_at"]})
check(r.status_code == 404 and err(r).get("code") == "heading_not_found", "replace: an unknown heading 404")

# ================================================================ a locked task: like the whole write (the agent's change is marked)
check(F.patch(B + f"/api/tasks/{T2}", json={"locked": True}).ok, "setup: Frida locks the task")
r = api("POST", f"/tasks/{T2}/notes/append", json={"text": "late note"})
check(r.ok and notes(T2).endswith("\n\nlate note\n"), f"a locked task: appended like PATCH notes ({r.status_code} {r.text[:150]})")
check(dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND kind='locked_bypass'", (T2,))[0][0] >= 1, "the history marks the change of a locked task")

# ================================================================ her own token (a person without an organisation)
TOK = F.post(B + "/api/me/tokens", json={"name": "own", "scopes": ["read", "write"]}).json().get("token")
r = api("POST", f"/tasks/{T}/notes/append", h={"Authorization": "Bearer " + TOK}, json={"text": "by Frida", "under": "Risks"})
check(r.ok and notes(T).endswith("- the date\n\nby Frida\n"), f"her own token appends under Risks {r.status_code} {notes(T)!r}")
r = api("POST", f"/tasks/{T}/notes/append", h={"Authorization": "Bearer " + TOK}, json={"text": "x", "under": "Spec"})
check(r.ok and notes(T).endswith("by Frida\n\nx\n"), "a level-1 heading: its section runs over the level-2 ones to the end")

# ================================================================ the share decides; another person's agent never
FV = F.post(B + "/api/lists", json={"name": "Frida read", "kind": "project"}).json()["id"]
check(F.put(B + f"/api/lists/{FV}/members", json={"user_id": FA, "role": "view"}).ok, "setup: a project shared to view")
TV = task("Read only", "x", FV)
r = api("POST", f"/tasks/{TV}/notes/append", json={"text": "y"})
check(r.status_code in (403, 404) and notes(TV) == "x", f"a view share: refused, nothing written ({r.status_code})")
# tenant: POST /api/v1/tasks/{}/notes/append
# tenant: POST /api/v1/tasks/{}/notes/replace-section
check(api("POST", f"/tasks/{T}/notes/append", h=OH, json={"text": "intruder"}).status_code == 404 and "intruder" not in notes(T),
      "another person's agent: 404 on her task")
check(api("POST", f"/tasks/{T}/notes/replace-section", h=OH, json={"heading": "Plan", "text": "i", "expect_updated_at": "x"}).status_code == 404,
      "another person's agent: replace 404")

# ================================================================ a project's description
OV = B + f"/api/lists/{FL}/overview"
check(F.patch(OV, json={"description": "## Goal\nship it\n\n## Status\nred"}).ok, "setup: Frida writes the description")
r = api("POST", f"/lists/{FL}/overview/append", json={"text": "- by Friday", "under": "Goal"})
check(r.ok and r.json().get("description") == "## Goal\nship it\n\n- by Friday\n\n## Status\nred", f"description: append under Goal {r.status_code} {r.text[:200]}")
r = api("POST", f"/lists/{FL}/overview/replace-section", json={"heading": "Status", "text": "green"})
check(r.status_code == 400 and err(r).get("code") == "version_required", "description: replace without a version 400")
at = api("GET", f"/lists/{FL}/overview").json()["description_at"]
r = api("POST", f"/lists/{FL}/overview/replace-section", json={"heading": "Status", "text": "green", "expect_updated_at": "2000-01-01T00:00:00Z"})
check(r.status_code == 409 and (err(r).get("current") or {}).get("description", "").endswith("red"), f"description: outdated 409 + current ({r.status_code})")
r = api("POST", f"/lists/{FL}/overview/replace-section", json={"heading": "Status", "text": "green", "expect_updated_at": at})
check(r.ok and r.json().get("description") == "## Goal\nship it\n\n- by Friday\n\n## Status\n\ngreen", f"description: Status replaced {r.status_code} {r.text[:200]}")
h = F.get(OV + "/history").json().get("history", [])
check(any("red" in x["text"] for x in h), f"the text before is in the project's history {h}")
r = api("POST", f"/lists/{FL}/overview/append", json={"text": "x", "under": "Nope"})
check(r.status_code == 404 and err(r).get("headings") == ["Goal", "Status"], "description: an unknown heading 404 with the headings")
# tenant: POST /api/v1/lists/{}/overview/append
# tenant: POST /api/v1/lists/{}/overview/replace-section
check(api("POST", f"/lists/{FL}/overview/append", h=OH, json={"text": "intruder"}).status_code == 404, "another person's agent: 404 on her project")
check(api("POST", f"/lists/{FL}/overview/replace-section", h=OH, json={"heading": "Goal", "text": "i", "expect_updated_at": at}).status_code == 404,
      "another person's agent: replace 404 on her project")
check("intruder" not in F.get(OV).json()["description"], "her description stays hers")

# ================================================================ a knowledge page: replace a section
# her own token with the knowledge scopes: an agent's write to a page is never placed in a project, so even a "free"
# personal agent asks first (agents/control.py ctl_lists: unknown) -- the card is checked below with the task steps
WT = F.post(B + "/api/me/tokens", json={"name": "wiki", "scopes": ["read", "wiki:read", "wiki:write"]}).json().get("token")
WH = {"Authorization": "Bearer " + WT}
OWT = OTTO.post(B + "/api/me/tokens", json={"name": "wiki", "scopes": ["read", "wiki:read", "wiki:write"]}).json().get("token")
OWH = {"Authorization": "Bearer " + OWT}
w = F.post(B + "/api/wiki/pages", json={"space": "private", "path": "Kit/Guide", "body": "# Guide\n\n## Setup\nold\n\n## Use\nrun\n"})
check(w.status_code in (200, 201), f"setup: a private knowledge page {w.status_code}")
PID = w.json().get("id")
FOL = {f["path"]: f["id"] for f in F.get(B + "/api/wiki", params={"space": "private"}).json().get("folders", [])}
check(F.post(B + f"/api/files/nodes/{FOL.get('Kit')}/shares", json={"agent_id": FA, "role": "edit"}).status_code == 201, "setup: folder shared")
r = api("POST", f"/wiki/pages/{PID}/replace-section", h=WH, json={"heading": "Setup", "text": "new"})
check(r.status_code == 400 and err(r).get("code") == "version_required", "page: replace without a version 400")
# review F3: a version that is no string, or an empty If-Match, is no version
check(api("POST", f"/wiki/pages/{PID}/replace-section", h=WH, json={"heading": "Setup", "text": "new", "expect_updated_at": False}).status_code == 400,
      "page: expect_updated_at false: 400")
r = api("POST", f"/wiki/pages/{PID}/replace-section", h={**WH, "If-Match": "W/"}, json={"heading": "Setup", "text": "new"})
check(r.status_code == 400 and err(r).get("code") == "version_required", f"page: an empty If-Match is no version ({r.status_code})")
r = api("POST", f"/lists/{FL}/overview/replace-section", h={**FH, "If-Match": '""'}, json={"heading": "Status", "text": "x"})
check(r.status_code == 400 and err(r).get("code") == "version_required", f"description: an empty If-Match is no version ({r.status_code})")
cur = api("GET", f"/wiki/pages/{PID}", h=WH).json()
r = api("POST", f"/wiki/pages/{PID}/replace-section", h=WH, json={"heading": "Setup", "text": "pip install\nthen go", "expect_updated_at": cur["updated_at"]})
check(r.ok and r.json().get("body") == "# Guide\n\n## Setup\n\npip install\nthen go\n\n## Use\nrun\n", f"page: Setup replaced {r.status_code} {r.text[:200]}")
cur = api("GET", f"/wiki/pages/{PID}", h=WH).json()
r = api("POST", f"/wiki/pages/{PID}/replace-section", h=WH, json={"heading": "Setup", "text": "x", "expect_updated_at": "2000-01-01T00:00:00.000Z"})
check(r.status_code == 409, "page: an outdated version 409")
r = api("POST", f"/wiki/pages/{PID}/replace-section", h=WH, json={"heading": "Install", "text": "x", "expect_updated_at": cur["updated_at"]})
check(r.status_code == 404 and err(r).get("headings") == ["Guide", "Setup", "Use"], "page: an unknown heading 404 with the headings")
r = api("POST", f"/wiki/pages/{PID}/replace-section", h=WH, json={"heading": "Guide", "text": "", "expect_updated_at": cur["updated_at"]})
check(r.ok and r.json().get("body") == "# Guide\n", f"page: an empty text empties the level-1 section (to the end) {r.text[:200]}")
# tenant: POST /api/v1/wiki/pages/{}/replace-section
check(api("POST", f"/wiki/pages/{PID}/replace-section", h=OWH, json={"heading": "Guide", "text": "i", "expect_updated_at": "x"}).status_code == 404,
      "another person's token: 404 on her page")

# ================================================================ the approval card shows only the change
level(FA, "approve_all")


def card_of(r, what):
    check(r.status_code == 409 and err(r).get("code") == "approval_required", f"{what}: a card first {r.status_code} {r.text[:200]}")
    ap = err(r).get("approval") or {}
    step = {k: ap[k] for k in ("method", "path", "body", "if_match") if k in ap}
    c = requests.post(V + f"/agent/chats/{FID}", headers=FH, json={"approval": {"title": "May I?", "step": step}})
    check(c.status_code == 201, f"{what}: the card {c.status_code} {c.text[:200]}")
    return c.json().get("id")


M1 = card_of(api("POST", f"/tasks/{T}/notes/append", json={"text": "- a new risk", "under": "Risks"}), "notes append")
d = F.get(B + "/api/approvals/diff", params={"chat": M1}).json().get("diff") or {}
check(d.get("kind") == "task" and d.get("append") is True and d.get("added") == 1 and d.get("removed") == 0 and ["+", "- a new risk"] in d.get("rows", []),
      f"the card of an append: only the new line {d}")
cur = api("GET", f"/tasks/{T}").json()
M2 = card_of(api("POST", f"/tasks/{T}/notes/replace-section", json={"heading": "Plan", "text": "- two steps", "expect_updated_at": cur["updated_at"]}), "notes replace")
d = F.get(B + "/api/approvals/diff", params={"chat": M2}).json().get("diff") or {}
check(d.get("kind") == "task" and d.get("section") is True and d.get("added") == 1 and d.get("removed") == 1
      and ["-", "- one step"] in d.get("rows", []) and ["+", "- two steps"] in d.get("rows", []), f"the card of a section: the one line out, the one in {d}")
M3 = card_of(api("POST", f"/lists/{FL}/overview/append", json={"text": "done soon"}), "description append")
d = F.get(B + "/api/approvals/diff", params={"chat": M3}).json().get("diff") or {}
check(d.get("kind") == "project" and d.get("added") == 1 and d.get("removed") == 0, f"the card of a description append {d}")
cur = api("GET", f"/wiki/pages/{PID}").json()
M4 = card_of(api("POST", f"/wiki/pages/{PID}/replace-section", json={"heading": "Guide", "text": "intro", "expect_updated_at": cur["updated_at"]}), "page replace")
d = F.get(B + "/api/approvals/diff", params={"chat": M4}).json().get("diff") or {}
check(d.get("kind") == "wiki" and d.get("section") is True and d.get("added") == 1 and d.get("removed") == 0, f"the card of a page section {d}")
check("- a new risk" not in notes(T), "nothing ran before the Yes")

sys.exit(done("p21111_c_mdedit"))
