#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1068.0 (#5831): an approval card whose step changes a text shows the change itself (GET /api/approvals/diff,
agents/apvdiff.py), reckoned by the server from the card's bound body against the target NOW, with the rights of the
person who looks. Invented names only.
 - a knowledge page PATCH: exactly the one new line (+), two lines of context, a gap before; nothing removed
 - the target changed since the card: changed true, the diff against the text now
 - appending (POST .../append): only the appended line counts, the page's rest is context
 - a task's notes: kind task with the task's number and title
 - a step on a task the person cannot see: hidden no_access, no word of its text
 - decided: the state at the answer stays (later edits do not change it); it is never in choices (the agent's), so the
   agent's own read of its chat carries no line of it
 - a comment card on a task: the people who see the task; a stranger 404
 - only the card's person asks a chat card (another person, the instance admin: 404); a bad query 400
 - tenant-matrix: agent (another person's agent card and comment card: 404)
 - freelancer-matrix: agents (the personal agent of a person without an organisation)
usage: p21068_apvdiff_test.py <datadir>"""
import json
import os

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

V = B + "/api/v1"
D = B + "/api/approvals/diff"

os.environ["KALMIDO_AGENT_CONTROL_NEW"] = "approve_all"  # the real default: every change needs a card
fresh(prefix="P21068")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, OTTO = freelancer(B, A, "otto")
SCOPES = ["read", "tasks:write", "comments", "wiki:read", "wiki:write"]


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


FA, FH = agent(F, "fridabot")
FL = F.post(B + "/api/lists", json={"name": "Frida work"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "setup: the project is shared with the agent")


def api(method, path, **kw):
    return requests.request(method, V + path, headers=FH, **kw)


def card(step, want=201):
    r = requests.post(V + f"/agent/chats/{FID}", headers=FH, json={"approval": {"title": "May I?", "step": step}})
    check(r.status_code == want, f"approval card {step.get('method')} {step.get('path')} -> {r.status_code} {r.text[:200]}")
    return r.json().get("id") if r.ok else 0


def step_of(r):
    ap = err(r).get("approval") or {}
    return {k: ap[k] for k in ("method", "path", "body", "if_match") if k in ap}


def refused_card(r, what):
    check(r.status_code == 409 and err(r).get("code") == "approval_required", f"{what}: refused first {r.status_code} {r.text[:200]}")
    return card(step_of(r))


def diff(s, **q):
    r = s.get(D, params=q)
    return r, (r.json().get("diff") if r.ok else None)


def page_body(pid):
    return F.get(B + f"/api/wiki/pages/{pid}").json().get("body")


# ================================================================== setup: a page shared with the agent
w = F.post(B + "/api/wiki/pages", json={"space": "private", "path": "Kit/Overview", "body": "Line A\nLine B\nLine C\nLine E"})
check(w.status_code in (200, 201), f"setup: a private knowledge page {w.status_code} {w.text[:200]}")
PID = w.json().get("id")
FOL = {f["path"]: f["id"] for f in F.get(B + "/api/wiki", params={"space": "private"}).json().get("folders", [])}
check(F.post(B + f"/api/files/nodes/{FOL.get('Kit')}/shares", json={"agent_id": FA, "role": "edit"}).status_code == 201, "setup: folder shared")

# ================================================================== a page PATCH: exactly the one new line
cur = api("GET", f"/wiki/pages/{PID}").json()
M1 = refused_card(api("PATCH", f"/wiki/pages/{PID}", json={"body": "Line A\nLine B\nLine C\nLine D\nLine E", "expect_updated_at": cur["updated_at"]}), "page PATCH")
r, d = diff(F, chat=M1)
check(r.ok and d and d["kind"] == "wiki" and d["ref"] == "Kit/Overview" and d["added"] == 1 and d["removed"] == 0, f"the page card: one line added, nothing removed {r.status_code} {d}")
rows = (d or {}).get("rows") or []
check(["+", "Line D"] in rows and not any(x[0] == "-" for x in rows), f"the new line is a + row, no - row {rows}")
check(rows[:3] == [["…", ""], [" ", "Line B"], [" ", "Line C"]] and rows[-1] == [" ", "Line E"], f"two lines of context, a gap before {rows}")
check(d and d["changed"] is False and not d.get("decided"), "not changed since the card")

# only the card's person
check(diff(OTTO, chat=M1)[0].status_code == 404, "another person: 404")
check(diff(A, chat=M1)[0].status_code == 404, "the instance admin (not the chat's person): 404")
check(F.get(D).status_code == 400 and F.get(D, params={"chat": M1, "comment": 1}).status_code == 400 and F.get(D, params={"chat": "x"}).status_code == 400,
      "no / both / a bad id: 400")

# ================================================================== changed since the card
check(F.patch(B + f"/api/wiki/pages/{PID}", json={"body": "Line A changed\nLine B\nLine C\nLine E"}).ok, "setup: Frida edits the page")
r, d = diff(F, chat=M1)
check(d and d["changed"] is True and d["added"] == 2 and d["removed"] == 1 and ["-", "Line A changed"] in d["rows"] and ["+", "Line A"] in d["rows"],
      f"changed since: the diff against the text now {d}")

# ================================================================== appending: only the appended line
cur = api("GET", f"/wiki/pages/{PID}").json()
M2 = refused_card(api("POST", f"/wiki/pages/{PID}/append", json={"text": "- [Lights](lights)"}), "append")
r, d = diff(F, chat=M2)
check(d and d["kind"] == "wiki" and d.get("append") is True and d["added"] == 1 and d["removed"] == 0 and d["rows"][-1] == ["+", "- [Lights](lights)"],
      f"append: one line added (the empty line before is not counted) {d}")

# ================================================================== a task's notes
T = F.post(B + "/api/tasks", json={"title": "Plan the shoot", "list_id": FL, "notes": "Buy film\nCharge batteries"}).json()["id"]
tv = api("GET", f"/tasks/{T}").json()
M3 = refused_card(api("PATCH", f"/tasks/{T}", json={"notes": "Buy film\nCharge batteries\nBook the van", "expect_updated_at": tv.get("updated_at")}), "task notes")
r, d = diff(F, chat=M3)
check(d and d["kind"] == "task" and d["ref"] == f"#{T}" and d["name"] == "Plan the shoot" and d["added"] == 1 and ["+", "Book the van"] in d["rows"],
      f"task notes: kind task, number and title, the new line {d}")

# ================================================================== a target the person cannot read
OL = OTTO.post(B + "/api/lists", json={"name": "Otto private"}).json()["id"]
OT = OTTO.post(B + "/api/tasks", json={"title": "Otto secret", "list_id": OL, "notes": "the hidden plan"}).json()["id"]
M4 = card({"method": "PATCH", "path": f"/tasks/{OT}", "body": {"notes": "x"}})
r, d = diff(F, chat=M4)
check(r.ok and d and d.get("hidden") == "no_access" and d["rows"] == [] and "hidden plan" not in r.text and "Otto secret" not in r.text,
      f"a task Frida cannot see: no_access, none of its text {r.text[:300]}")

# ================================================================== decided: the state at the answer
before = diff(F, chat=M1)[1]
check(F.post(B + f"/api/agents/{FA}/chat/{M1}/choice", json={"choice_ids": ["yes"]}).ok, "Frida says Yes to the page card")
check(F.patch(B + f"/api/wiki/pages/{PID}", json={"body": "Totally new text"}).ok, "setup: the page changes after the Yes")
r, d = diff(F, chat=M1)
check(d and d.get("decided") is True and d.get("at") and d["rows"] == before["rows"][:60] and d["added"] == before["added"],
      f"decided: the rows of the answer, not of the text now {d}")
row = kt.dbx("SELECT apv_diff IS NOT NULL, choices->'approval'->'diff' IS NOT NULL FROM agent_chat WHERE id=?", (M1,))
check(row and row[0][0] and not row[0][1], f"the record is in apv_diff, never in choices {row}")
mine = requests.get(V + f"/agent/chats/{FID}", headers=FH)
check(mine.ok and "Line A changed" not in mine.text, "the agent's read of its chat carries no line of the record")
check(F.post(B + f"/api/agents/{FA}/chat/{M4}/choice", json={"choice_ids": ["no"]}).ok, "Frida says No to the foreign card")
r, d = diff(F, chat=M4)
check(r.ok and (d is None or (d.get("hidden") and d["rows"] == [])) and "hidden plan" not in r.text, f"a decided no_access card stays without text {r.text[:200]}")

# ================================================================== a comment card on a task
check(F.patch(B + f"/api/agents/{FA}/control", json={"level": "routine"}).ok, "setup: routine steps free (a comment)")
cur = api("GET", f"/wiki/pages/{PID}").json()
r = api("POST", f"/tasks/{T}/comments", json={"body": "May I change the page?", "approval": {"title": "Change the page",
        "step": {"method": "PATCH", "path": f"/wiki/pages/{PID}", "body": {"body": "Totally new text\nOne more", "expect_updated_at": cur["updated_at"]}}}})
check(r.status_code == 201, f"the agent's comment card {r.status_code} {r.text[:200]}")
CID = r.json().get("id")
r, d = diff(F, comment=CID)
check(d and d["kind"] == "wiki" and d["added"] == 1 and ["+", "One more"] in d["rows"], f"a comment card: the diff for a person who sees the task {d}")
# tenant: GET /api/approvals/diff
check(diff(OTTO, comment=CID)[0].status_code == 404 and diff(OTTO, chat=M2)[0].status_code == 404, "the other person: 404 for both kinds")
check(F.post(B + f"/api/comments/{CID}/choice", json={"choice_ids": ["yes"]}).ok, "Frida says Yes to the comment card")
row = kt.dbx("SELECT extra->'apvdiff' IS NOT NULL, extra->'choices'->'approval'->'diff' IS NOT NULL FROM obj_comments WHERE id=?", (CID,))
check(row and row[0][0] and not row[0][1], f"the comment's record sits beside choices {row}")
r, d = diff(F, comment=CID)
check(d and d.get("decided") is True and ["+", "One more"] in d["rows"], f"the decided comment card keeps its record {d}")
print(json.dumps({"page": PID, "cards": [M1, M2, M3, M4], "comment": CID}))
done()
