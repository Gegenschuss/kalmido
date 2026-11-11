#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.955.0 (#5276, stage Q5b of the cross-cutting core): the personal tags are rows of the core (obj_tags scope user,
obj_tag_links kind task; core/objtags.py). Own container. Invented names only.
 - task_tags is gone; made again by hand with rows (what a version before 2.955 leaves after a rollback) the next start moves
   them: one person's names equal under lower() become ONE tag (decided 08.11.2026, question 8: Kunde / kunde), the spelling on
   most tasks wins, a leading '#' and spaces go, a row of an account that is gone stays out, a row of the single-user era
   (user_id 0) goes to the first administrator
 - writing through the app: tags ["Neu", "neu"] are one tag, a later "NEU" finds it; ?tag= of API v1 and the tag count find it
   in any case; deleting the tag and the undo (restore)
 - nobody else sees a person's tags (bob's tag on a shared task is not in alice's state nor in her API v1 tag list)
 - CalDAV CATEGORIES read the core (calendars/caldav.py dav_ctx)
 - promote = a scope change: the links move to the project tag (their time stays), the personal tag goes
 - an agent keeps its own private tags (scope user of the agent, src agent; question 12)
 - the account export still has the file task_tags (task_id, user_id, tag); an account deleted for good takes its tags along
 - a person without an organisation: personal tags work in her own project
freelancer-matrix: tasks
usage: p2955_c_tags_user_test.py <datadir>"""
import os
import subprocess
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, H, check, dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402


def box(code):
    """Python inside the app container (as the system); "import app" starts the app (init_db: the move, the fragments)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\n"
                          "from kalmido.core.pg import system_ctx\nc = connect()\nwith system_ctx(c):\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "c.commit()\nc.close()"],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"the run in the container works {out.stderr[-800:]}")
    return out.stdout.strip()


def table_there(t):
    return bool(dbx("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (t,)))


def st(s):
    return s.get(B + "/api/state").json()


def tags_of(s, tid):
    return next((t.get("tags") for t in st(s)["tasks"] if t["id"] == tid), None)


def mklist(s, name):
    r = s.post(B + "/api/lists", json={"name": name, "kind": "project"})
    assert r.ok, r.text
    return r.json()["id"]


def task(s, lid, title):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


def utags(uid):
    """(name, task ids) of person uid's personal tags in the core, by name."""
    return dbx("""SELECT ot.name, array_agg(k.obj_id ORDER BY k.obj_id) FROM obj_tags ot LEFT JOIN obj_tag_links k ON k.tag_id=ot.id
                  WHERE ot.scope_kind='user' AND ot.scope_id=? GROUP BY ot.id, ot.name ORDER BY ot.name""", (str(uid),))


kt.fresh(prefix="P2955C")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": kt.PASSWORD})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
uid = {}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [], "username": u, "display_name": u.title(), "password": kt.PASSWORD,
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca = kt.sess("bob"), kt.sess("carl")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB, CARL = uid["bob"], uid["carl"]
L = mklist(A, "Kundenprojekt")
A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
T1, T2, T3, T4 = (task(A, L, x) for x in ("Angebot", "Rechnung", "Anruf", "Termin"))

# ================================================================== the old table is gone, the move of a rolled-back database
check(not table_there("task_tags"), "task_tags is gone (fragment 5276_a)")
dbx("""CREATE TABLE task_tags (task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, user_id BIGINT NOT NULL DEFAULT 0,
       tag TEXT NOT NULL, PRIMARY KEY (task_id, user_id, tag))""")
for tid, u, tag in ((T1, ALICE, "Kunde"), (T2, ALICE, "kunde"), (T3, ALICE, " #Kunde"), (T4, ALICE, "Kunde"), (T1, ALICE, "kunde"),
                    (T1, BOB, "kunde"), (T2, 0, "Altlast"), (T3, 999999, "Waise"), (T4, ALICE, "  "), (T2, ALICE, "Intern")):
    dbx("INSERT INTO task_tags(task_id, user_id, tag) VALUES(?,?,?)", (tid, u, tag))
box("pass")  # the next start of the app
check(not table_there("task_tags"), "the start dropped task_tags made again")
got = utags(ALICE)
check(got == [("Altlast", [T2]), ("Intern", [T2]), ("Kunde", [T1, T2, T3, T4])],
      f"the move: Kunde / kunde / ' #Kunde' are ONE tag (the spelling on most tasks), the single-user era's tag goes to the first admin, an empty name stays out {got}")
check(utags(BOB) == [("kunde", [T1])], f"bob's own tag stays his own, with his spelling {utags(BOB)}")
check(not dbx("SELECT 1 FROM obj_tags WHERE scope_kind='user' AND (scope_id='999999' OR scope_id='0' OR name='Waise')"),
      "a row of an account that is gone stays out; nothing waits under scope_id 0 after the start")
check(dbx("SELECT DISTINCT src FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id WHERE ot.scope_kind='user'") == [("person",)],
      "the moved links are a person's")
check(tags_of(A, T1) == ["Kunde"] and tags_of(Bo, T1) == ["kunde"], f"the state: each sees their own tag {tags_of(A, T1)} {tags_of(Bo, T1)}")

# ================================================================== writing through the app
r = A.patch(B + f"/api/tasks/{T3}", json={"tags": ["Neu", "neu", "#neu "]})
check(r.ok and tags_of(A, T3) == ["Neu"], f"tags Neu / neu / #neu on one task: one tag {r.status_code} {tags_of(A, T3)}")
r = A.patch(B + f"/api/tasks/{T4}", json={"tags": ["Kunde", "NEU"]})
check(r.ok and "Neu" in (tags_of(A, T4) or []) and len(dbx("SELECT 1 FROM obj_tags WHERE scope_kind='user' AND scope_id=? AND lower(name)='neu'", (str(ALICE),))) == 1,
      f"a later NEU finds the tag Neu (no second row) {tags_of(A, T4)}")
check(A.get(B + "/api/tags/count", params={"tag": "NEU"}).json() == {"tasks": 2, "open": 2}, "the tag count finds it in any case")
HA = {"Authorization": "Bearer " + A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "tasks:write"]}).json()["token"], **H}
got = sorted(x["id"] for x in requests.get(B + "/api/v1/tasks", params={"tag": "neu"}, headers=HA).json().get("data", []))
check(got == [T3, T4], f"API v1 ?tag=neu finds both tasks {got}")
r = A.patch(B + f"/api/tasks/{T3}", json={"tags": []})
check(r.ok and tags_of(A, T3) == [] and utags(ALICE)[-1] == ("Neu", [T4]), f"taken off one task, the tag stays on the other {utags(ALICE)}")
j = A.post(B + "/api/tags/delete", json={"tag": "neu"}).json()
check(j.get("ids") == [T4] and j.get("count") == 1 and not any(x[0] == "Neu" for x in utags(ALICE)),
      f"deleting the tag (any case): its tasks for the undo, the tag row goes {j}")
j = A.post(B + "/api/tags/restore", json={"tag": "Neu", "ids": [T4]}).json()
check(j.get("count") == 1 and tags_of(A, T4) == ["Kunde", "Neu"], f"the undo puts it back {j} {tags_of(A, T4)}")

# ================================================================== nobody else sees a person's tags
r = Bo.patch(B + f"/api/tasks/{T2}", json={"tags": ["Geheim"]})
check(r.ok and tags_of(Bo, T2) == ["Geheim"], f"bob tags a shared task {r.status_code}")
check("Geheim" not in (tags_of(A, T2) or []), "alice does not see bob's tag in her state")
names = [x["name"] for x in requests.get(B + "/api/v1/tags", headers=HA).json().get("data", []) if x["kind"] == "personal"]
check("Geheim" not in names and "Kunde" in names, f"... nor in her API v1 tag list {names}")
check(A.get(B + "/api/tags/count", params={"tag": "Geheim"}).json()["tasks"] == 0, "... nor in her tag count")
check(tags_of(Bo, T1) == ["kunde"] and "Intern" in tags_of(A, T2), "bob's tags and alice's stay apart on the same task")

# ================================================================== CalDAV CATEGORIES read the core
out = box(f"""from kalmido.calendars.caldav import dav_ctx
u = c.execute("SELECT * FROM users WHERE id=?", ({ALICE},)).fetchone()
print('DAV' + repr(dav_ctx(c, u, [{T1}, {T2}])['tags']))""")
check(f"DAV{{{T1}: ['Kunde'], {T2}: ['Altlast', 'Intern', 'Kunde']}}" in out, f"CalDAV CATEGORIES: alice's tags of the core, not bob's {out[-300:]}")

# ================================================================== promote = a scope change
at = dbx("""SELECT k.created_at FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id WHERE ot.scope_kind='user' AND ot.scope_id=?
            AND ot.name='Intern' AND k.obj_id=?""", (str(ALICE), T2))
r = A.post(B + f"/api/lists/{L}/tags/promote", json={"tag": "Intern"})
check(r.ok and r.json().get("ids") == [T2], f"promote {r.status_code} {r.text[:200]}")
lt = dbx("""SELECT ot.scope_kind, k.created_at FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id WHERE k.obj_id=? AND ot.name='Intern'""", (T2,))
check(lt == [("list", at[0][0])] if at else False, f"the link moved to the project's tag, its time stays {lt} {at}")
check(not any(x[0] == "Intern" for x in utags(ALICE)), "the personal tag is gone")

# ================================================================== an agent keeps its own tags
r = A.post(B + "/api/my/agents", json={"username": "taggerbot", "display_name": "Taggerbot", "scopes": ["read", "tasks:write"], "org_id": None})
check(r.status_code == 201, f"an agent {r.status_code} {r.text[:200]}")
AG, HG = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"})
r = requests.patch(B + f"/api/v1/tasks/{T1}", headers=HG, json={"tags": ["Bot-Privat", "bot-privat"]})
check(r.ok and r.json().get("tags") == ["Bot-Privat"], f"the agent sets its own tag {r.status_code} {r.text[:200]}")
check(utags(AG) == [("Bot-Privat", [T1])] and dbx("SELECT k.src FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id WHERE ot.scope_id=?",
                                                    (str(AG),)) == [("agent",)], f"scope user of the agent, src agent {utags(AG)}")
check(tags_of(A, T1) == ["Kunde"], "alice does not see the agent's tag")
check(requests.get(B + f"/api/v1/tasks/{T1}", headers=HG).json().get("tags") == ["Bot-Privat"], "the agent reads only its own tag")

# ================================================================== account export, account deleted
out = box(f"""from kalmido.accounts.settings import umz_export_queries
sql, args = umz_export_queries({ALICE})['task_tags']
print('EXP' + repr(sorted(tuple(r) for r in c.execute(sql, args).fetchall())))""")
check(f"({T1}, {ALICE}, 'Kunde')" in out and "Geheim" not in out, f"the account export: the file task_tags with my tags only {out[-300:]}")
Ca.post(B + "/api/lists", json={"name": "Carl privat"})
CL = next(x["id"] for x in st(Ca)["lists"] if x["name"] == "Carl privat")
CT1 = task(Ca, CL, "Carls Aufgabe")
Ca.patch(B + f"/api/tasks/{CT1}", json={"tags": ["Carls"]})
check(utags(CARL) == [("Carls", [CT1])], "carl has a tag")
check(A.delete(B + f"/api/users/{CARL}").ok, "carl deleted")
check(utags(CARL) == [], "an account deleted takes its personal tags along")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes"}).json()["id"]
FT = task(Fr, FL, "Angebot schreiben")
r = Fr.patch(B + f"/api/tasks/{FT}", json={"tags": ["Privat", "privat"]})
check(r.ok and tags_of(Fr, FT) == ["Privat"], f"freelancer: one personal tag {r.status_code} {tags_of(Fr, FT)}")
check(Fr.get(B + "/api/tags/count", params={"tag": "PRIVAT"}).json()["tasks"] == 1, "freelancer: the count in any case")
check(Fr.post(B + "/api/tags/delete", json={"tag": "privat"}).json().get("ids") == [FT] and tags_of(Fr, FT) == [], "freelancer: deleted")

sys.exit(kt.done("p2955_c_tags_user"))
