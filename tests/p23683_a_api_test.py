#!/usr/bin/env python3
# kalmido-suite:
"""2.368.3 (#2988) API tests: table formulas read in the person's language, own container (start.sh). Invented names only.
freelancer-matrix: sheets
 - English names (SUM, IF, here., project., task. with English fields) are equal to the German ones
 - stored is one form (SUM, TRUE, hier.<key>, {p:N}.<key>), each person reads their own language, also an older stored German cell
 - the completion offers the person's names and finds the other language's too
 - "Project" and "Client" stay free as names of cells; all as a person without organisation
usage: p23683_a_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, done, sess, B, H, DATA  # noqa: E402,F401
import dbx as dbxm  # noqa: E402


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args)
        rows = r.fetchall() if sql.lstrip().upper().startswith("SELECT") else None
        c.commit()
        return rows
    finally:
        c.close()


if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, F = freelancer(B, A)


def put(sid, addr, raw):
    return F.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"cell": addr, "raw": raw}]})


def shown(sid, addr):
    return next((x for x in F.get(B + f"/api/sheets/{sid}").json()["cells"] if x["addr"] == addr), {})


def stored(sid, addr):
    x = shown(sid, addr)
    return dbx("SELECT raw FROM sheet_cells WHERE id=?", (x["id"],))[0][0]


def language(lg):
    assert F.patch(B + "/api/settings", json={"lang": lg}).ok


P = F.post(B + "/api/lists", json={"name": "Shoot Berlin", "org_id": None, "kind": "project"}).json()["id"]
T = F.post(B + "/api/tasks", json={"title": "Grade", "list_id": P}).json()["id"]
SID = F.post(B + "/api/sheets", json={"title": "Budget", "space": "private"}).json()["id"]
LS = F.post(B + "/api/sheets", json={"title": "On the project", "space": "private", "list_id": P}).json()["id"]
check(put(SID, "A1", "10").ok and put(SID, "A2", "20").ok, "setup: values")

# ---- English and German are equal; stored is one form
check(put(SID, "B1", "=SUMME(A1:A2)").ok and shown(SID, "B1")["value"] == 30, "SUMME in an English account")
check(shown(SID, "B1")["raw"] == "=SUM(A1:A2)", "German input reads English here " + shown(SID, "B1")["raw"])
check(stored(SID, "B1").startswith("=SUM("), "stored language-neutral " + stored(SID, "B1"))
check(put(SID, "B2", '=if(A1>5;WAHR;false)').ok and shown(SID, "B2")["raw"] == "=IF(A1>5;TRUE;FALSE)", "IF and the truth values " + shown(SID, "B2")["raw"])
check(stored(SID, "B2").startswith("=IF(") and "WAHR" not in stored(SID, "B2"), "stored in one form " + stored(SID, "B2"))
check(put(SID, "B3", "=project.shoot_berlin.tasks").ok and shown(SID, "B3")["value"] == 1, "project.<name>.tasks " + str(shown(SID, "B3")))
check(stored(SID, "B3") == "={p:%d}.aufgaben" % P, "stored by id and key " + stored(SID, "B3"))
check(put(SID, "B4", "=projekt.shoot_berlin.offen").ok and shown(SID, "B4")["raw"] == "=project.shoot_berlin.open", "German variable reads English")
check(put(SID, "B5", f"=task.{T}.title").ok and shown(SID, "B5")["value"] == "Grade", "task.<id>.title " + str(shown(SID, "B5")))
check(put(LS, "A1", "=here.open").ok and shown(LS, "A1")["value"] == 1, "here.open " + str(shown(LS, "A1")))
check(stored(LS, "A1") == "=hier.offen" and shown(LS, "A1")["raw"] == "=here.open", "here keeps its stored key " + stored(LS, "A1"))
check(put(SID, "B6", "=project.shoot_berlin.nonsense").status_code == 400, "an unknown field: 400")
check(put(SID, "B7", "=NOSUCH(1)").status_code == 400, "an unknown function: 400")

# ---- each person reads their own language; an older cell stored in German too
c = shown(SID, "B1")
dbx("UPDATE sheet_cells SET raw=? WHERE id=?", ("=SUMME({c:%d}:{c:%d})" % (shown(SID, "A1")["id"], shown(SID, "A2")["id"]), c["id"]))
check(shown(SID, "B1")["raw"] == "=SUM(A1:A2)", "an older German cell reads English")
language("de")
check(shown(SID, "B1")["raw"] == "=SUMME(A1:A2)", "... and German for a German account")
check(shown(SID, "B2")["raw"] == "=WENN(A1>5;WAHR;FALSCH)", "IF reads WENN " + shown(SID, "B2")["raw"])
check(shown(SID, "B4")["raw"] == "=projekt.shoot_berlin.offen", "the variable reads German")
check(shown(SID, "B5")["raw"] == f"=aufgabe.{T}.titel", "the task value reads German")
check(shown(LS, "A1")["raw"] == "=hier.offen", "hier reads German")
vs = F.get(B + f"/api/sheets/{SID}/vars", params={"q": "vlook"}).json()["vars"]
check(any(v["token"] == "SVERWEIS" for v in vs), "German: the English name finds SVERWEIS " + str(vs[:2]))
language("fr")
check(shown(SID, "B1")["raw"] == "=SUM(A1:A2)", "other languages read English")
language("en")
vs = F.get(B + f"/api/sheets/{SID}/vars", params={"q": "sver"}).json()["vars"]
check(any(v["token"] == "VLOOKUP" and v["help"] for v in vs), "English: the German name finds VLOOKUP " + str(vs[:2]))
vs = F.get(B + f"/api/sheets/{SID}/vars", params={"q": "sum"}).json()["vars"]
check(any(v["token"] == "SUM" for v in vs) and not any(v["token"] == "SUMME" for v in vs), "English: no German name offered")
vs = F.get(B + f"/api/sheets/{SID}/vars", params={"q": "shoot"}).json()["vars"]
check(any(v["token"] == "project.shoot_berlin.total_time" for v in vs), "English: the Kalmido value in English " + str(vs[:2]))
vs = F.get(B + f"/api/sheets/{LS}/vars", params={"q": "here"}).json()["vars"]
check(any(v["token"] == "here.open" for v in vs), "English: here. in the completion " + str(vs[:2]))

# ---- no new reserved words
x = shown(SID, "A1")
check(F.post(B + f"/api/sheets/{SID}/cells/{x['id']}/name", json={"name": "project"}).ok, "a cell may be called project")
check(put(SID, "C1", "=project*2").ok and shown(SID, "C1")["value"] == 20, "... and read " + str(shown(SID, "C1")))
sys.exit(done("p23683_a_api"))
