#!/usr/bin/env python3
"""2.116.0 API tests, part C (#2064 #2068): a list as a CSV file, code snippets through the app's task route. Own container (start.sh).
Invented names only, addresses @example.com.
 - GET /api/lists/<id>/export.csv: UTF-8 BOM, the columns, a custom field per column (select / person / checkbox as text), tags,
   assignee, section, parent task, done=0 leaves the completed out, a title starting with = + - @ is defused with a quote,
   ';' with decimal-comma languages, the file name = list name + date
 - another person's list 404, a participant gets only the tasks assigned to them (no context parents, no notes of others),
   a viewer reads, an agent token is refused (403), a list with the lock is 409
 - a person without an organisation (freelancer-matrix: lists): exports the own private list
 - snippets (the app's PATCH /api/tasks/<id>): add, change (author + time of the unchanged one stay), remove; a viewer is refused (403)
usage: p2116_c_api_test.py <datadir>      (a fresh container; P2116C_NOSTART=1 = the server already runs)"""
import csv
import io
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def rows(r):
    t = r.content.decode("utf-8")
    assert t.startswith("﻿"), "BOM"
    first = t[1:].split("\r\n", 1)[0]
    d = ";" if first.count(";") > first.count(",") else ","
    return list(csv.reader(io.StringIO(t[1:]), delimiter=d))


if not os.environ.get("P2116C_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments", "fields"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": 1}
for u in ("bob", "pete", "vic", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "carol" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Pe, Vi, Ca = sess("bob"), sess("pete"), sess("vic"), sess("carol")
for s in (A, Bo, Pe, Vi, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "comments,fields"}).ok

# ================================================================ the list
L = A.post(B + "/api/lists", json={"name": "Kitchen: plan/2031", "kind": "project", "org_id": ORG}).json()["id"]
for u, ro in (("bob", "edit"), ("pete", "participant"), ("vic", "view")):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": uid[u], "role": ro}).ok
sec = A.post(B + "/api/sections", json={"list_id": L, "name": "Phase one"}).json()["id"]
fsel = A.post(B + f"/api/lists/{L}/fields", json={"name": "Stage", "type": "select",
                                                   "options": {"options": [{"id": "s1", "name": "Draft", "color": "blue"}]}}).json()["id"]
fper = A.post(B + f"/api/lists/{L}/fields", json={"name": "Owner", "type": "person"}).json()["id"]
fchk = A.post(B + f"/api/lists/{L}/fields", json={"name": "Approved", "type": "checkbox"}).json()["id"]
ftxt = A.post(B + f"/api/lists/{L}/fields", json={"name": "Ref", "type": "text"}).json()["id"]


def mk(s, **kw):
    r = s.post(B + "/api/tasks", json=kw)
    assert r.ok, (kw, r.text)
    return r.json()["id"]


T1 = mk(A, title="Order tiles", list_id=L, section_id=sec, due="2031-05-04", priority=5, tags=["urgent"], content="Notes;with,separators",
        assignee_id=uid["pete"])
T1a = mk(A, title="Measure floor", parent_id=T1, assignee_id=uid["pete"])
T2 = mk(A, title="=SUM(A1:A9)", list_id=L, content="@secret-notes")
T3 = mk(A, title="Done thing", list_id=L)
A.post(B + f"/api/tasks/{T3}/complete", json={})
T4 = mk(A, title="Not for pete", list_id=L, content="PRIVATE-NOTES")
r = A.patch(B + f"/api/tasks/{T1}", json={"fields": {str(fsel): "s1", str(fper): str(uid["bob"]), str(fchk): "1", str(ftxt): "+49 12"}})
assert r.ok, r.text

# ================================================================ the CSV
r = A.get(B + f"/api/lists/{L}/export.csv")
check(r.status_code == 200 and r.headers["Content-Type"].startswith("text/csv"), f"csv 200 {r.status_code}")
check("filename=" in r.headers.get("Content-Disposition", "") and "Kitchen__plan_2031-" in r.headers["Content-Disposition"]
      and r.headers["Content-Disposition"].endswith('.csv"'), "file name = list name + date " + r.headers.get("Content-Disposition", ""))
R = rows(r)
head = R[0]
check(head[:11] == ["Title", "Status", "Due", "Priority", "Tags", "Assignee", "Section", "Parent task", "Notes", "Completed", "Created"]
      and head[11:] == ["Stage", "Owner", "Approved", "Ref"], f"columns {head}")
by = {x[0]: x for x in R[1:]}
t1 = by["Order tiles"]
check(t1[1] == "Open" and t1[2] == "2031-05-04" and t1[3] == "High" and t1[4] == "urgent" and t1[5] == "Pete" and t1[6] == "Phase one"
      and t1[8] == "Notes;with,separators", f"row 1 {t1}")
check(t1[11:] == ["Draft", "Bob", "Yes", "'+49 12"], f"field columns {t1[11:]}")
check(by["Measure floor"][7] == "Order tiles", "parent task column")
check("'=SUM(A1:A9)" in by and by["'=SUM(A1:A9)"][8] == "'@secret-notes", f"formula defused {list(by)}")
check(by["Done thing"][1] == "Done" and by["Done thing"][9], "done: status + completed on")
R0 = rows(A.get(B + f"/api/lists/{L}/export.csv?done=0"))
check("Done thing" not in {x[0] for x in R0} and "Order tiles" in {x[0] for x in R0}, "done=0 leaves the completed out")
# decimal-comma language: ';'
A.patch(B + "/api/settings", json={"lang": "de"})
rd = A.get(B + f"/api/lists/{L}/export.csv")
check(rd.content.decode("utf-8").split("\r\n")[0].count(";") >= 10 and rd.content.startswith(b"\xef\xbb\xbf"), "German: ';' and BOM")
A.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================ who may
check(Ca.get(B + f"/api/lists/{L}/export.csv").status_code == 404, "another person's list: 404")
check(A.get(B + "/api/lists/999999/export.csv").status_code == 404, "unknown list: 404")
check(requests.get(B + f"/api/lists/{L}/export.csv", headers=H).status_code in (401, 403), "no session: refused")
Rp = rows(Pe.get(B + f"/api/lists/{L}/export.csv"))
titles = {x[0] for x in Rp[1:]}
check(titles == {"Order tiles", "Measure floor"}, f"participant: only their own tasks {titles}")
check("PRIVATE-NOTES" not in Pe.get(B + f"/api/lists/{L}/export.csv").text, "participant: no notes of others")
check(Vi.get(B + f"/api/lists/{L}/export.csv").status_code == 200 and len(rows(Vi.get(B + f"/api/lists/{L}/export.csv"))) == 6,
      "viewer reads the whole list")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
check(requests.get(B + f"/api/lists/{L}/export.csv", headers=AGH).status_code in (401, 403), "agent token refused")

# ================================================================ snippets through the app's route
r = Bo.patch(B + f"/api/tasks/{T1}", json={"snippets": [{"lang": "py", "path": "a/b.py", "line": 3, "code": "print(1)\n"}]})
check(r.ok and len(r.json().get("snippets") or []) == 1, "snippet added " + r.text[:200])
sn = r.json()["snippets"]
r = A.patch(B + f"/api/tasks/{T1}", json={"snippets": [sn[0], {"lang": "sh", "code": "ls -l"}]})
sn2 = r.json().get("snippets") or []
check(r.ok and len(sn2) == 2 and sn2[0]["by"] == sn[0]["by"] and sn2[0]["updated_at"] == sn[0]["updated_at"], "second added, the first keeps author + time")
r = A.patch(B + f"/api/tasks/{T1}", json={"snippets": [{**sn2[0], "code": "print(2)"}, sn2[1]]})
check(r.ok and r.json()["snippets"][0]["code"] == "print(2)", "snippet changed")
check(Vi.patch(B + f"/api/tasks/{T1}", json={"snippets": []}).status_code == 403, "viewer cannot change snippets")
r = A.patch(B + f"/api/tasks/{T1}", json={"snippets": [sn2[1]]})
check(r.ok and [s["id"] for s in r.json()["snippets"]] == [sn2[1]["id"]], "snippet removed")
check(A.patch(B + f"/api/tasks/{T1}", json={"snippets": [{"lang": "py", "code": "x" * 20001}]}).status_code == 400, "too long: 400")

# ================================================================ a person without an organisation (freelancer-matrix: lists)
FID, Fl = freelancer(B, A)
PL = Fl.post(B + "/api/lists", json={"name": "Private plans", "org_id": None}).json()["id"]
mk(Fl, title="Own task", list_id=PL)
Rf = rows(Fl.get(B + f"/api/lists/{PL}/export.csv"))
check(len(Rf) == 2 and Rf[1][0] == "Own task", f"freelancer: own list exported {Rf}")
check(Fl.get(B + f"/api/lists/{L}/export.csv").status_code == 404, "freelancer: an organisation's list: 404")
T9 = mk(Fl, title="Snip", list_id=PL)
check(Fl.patch(B + f"/api/tasks/{T9}", json={"snippets": [{"lang": "js", "code": "let a = 1"}]}).ok, "freelancer: snippet added")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
