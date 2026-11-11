#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.981.0 (#5287, stage Q9b of the cross-cutting core): the bell of a project is a row of obj_follow (kind 'list'), the owner's
notification templates of projects and folders are rows of obj_notif_cap. Own container. Invented names only.
 - the old tables list_bell, list_notif and folder_notif are gone; the start moves rows of them made again by hand (what a
   version before 2.981 leaves after a rollback) into the core and drops them; a broken value becomes the safe one
 - the bell: custom (own choice kept while another mode is set), all, default (the row stays for the choice); "all" brings
   the News of every comment, "mute" holds back comments but not mentions (News and the push decision), the core's follow
   step answers "mute"
 - a person outside the project with a bell row by hand gets nothing (no right to read)
 - the ceiling: the project's template for everyone and one person, the folder's template and its rename, the push decision
   (notif_ok) follows it; the account export keeps the parts list_notif / folder_notif with their old columns
 - a member removed from the project: their bell there ends; a workspace move takes the bell along; a project deleted for
   good takes its bells and templates along
 - a person without an organisation (freelancer fixture) mutes her own project and sets its template
freelancer-matrix: lists
usage: p2981_c_follow_test.py <datadir>"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402


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


def bell_rows(lid):
    """[(user, mode)] of the project's bell rows in obj_follow."""
    return sorted((r[0], r[1]) for r in dbx("SELECT user_id, mode FROM obj_follow WHERE kind='list' AND ref_id=?", (lid,)))


def caps(kind, rid):
    return sorted((r[0], r[1], r[2]) for r in dbx("SELECT path, user_id, tpl FROM obj_notif_cap WHERE kind=? AND ref_id=?", (kind, rid)))


def put_bell(s, lid, mode, **kw):
    return s.put(B + f"/api/lists/{lid}/bell", json={"mode": mode, **kw})


def state_list(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


def news(s, tid, kind):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x.get("task_id") == tid and x.get("kind") == kind]


def comment(s, tid, text):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": text})
    check(r.ok, f"comment written {r.status_code} {r.text[:200]}")


def push_ok(uid, row, lid):
    """The push decision of collab/news.py notif_ok (matrix, the owner's ceiling, the bell) for uid about project lid."""
    out = box(f"""from kalmido.collab.news import notif_ok
from kalmido.collab.comments import collab_user
print("PUSH", notif_ok(c, {uid}, collab_user(c, {uid}), "{row}", "push", {lid}))""")
    return next((ln.split()[1] == "True" for ln in out.splitlines() if ln.startswith("PUSH")), None)


def tpl_url(lid):
    return B + f"/api/lists/{lid}/notify-template"


kt.fresh(prefix="P2981C")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
for u in ("bob", "gina"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    org_join(B, u, ORG)
r = A.post(B + "/api/users", json={"orgs": [], "username": "dave", "display_name": "Dave", "password": "password123", "email": "dave@example.com"})
assert r.ok, r.text
Bo, Gi, Da = kt.sess("bob"), kt.sess("gina"), kt.sess("dave")
for s in (Bo, Gi, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB, GINA, DAVE = kt.me_id(Bo), kt.me_id(Gi), kt.me_id(Da)

# ================================================================== the old tables are gone, the core's tables are there
check(table_there("obj_follow") and table_there("obj_notif_cap"), "the core's tables obj_follow and obj_notif_cap exist")
for t in ("list_bell", "list_notif", "folder_notif"):
    check(not table_there(t), f"the old table {t} is gone")

LID = A.post(B + "/api/lists", json={"name": "Werkstatt", "kind": "project", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{LID}/members", json={"user_id": BOB, "role": "edit"})
A.put(B + f"/api/lists/{LID}/members", json={"user_id": GINA, "role": "edit"})

# ================================================================== the bell of a project
r = put_bell(Bo, LID, "custom", custom={"comment": {"news": 0, "push": 1}})
check(r.ok and r.json()["mode"] == "custom" and r.json()["custom"] == {"comment": {"news": 0, "push": 1}}, f"bob: own choice {r.status_code} {r.text[:200]}")
row = dbx("SELECT mode, custom->'comment'->>'news', org_id FROM obj_follow WHERE kind='list' AND ref_id=? AND user_id=?", (LID, BOB))
check(row and tuple(row[0]) == ("custom", "0", ORG), f"a row of obj_follow kind list with the choice as JSON and the project's workspace {row}")
check(put_bell(Bo, LID, "all").ok and bell_rows(LID) == [(BOB, "all")], f"bob: everything {bell_rows(LID)}")
check(dbx("SELECT custom IS NOT NULL FROM obj_follow WHERE kind='list' AND ref_id=? AND user_id=?", (LID, BOB))[0][0], "the own choice stays while 'all' is set")
check(put_bell(Bo, LID, "default").ok and bell_rows(LID) == [(BOB, "default")], f"back to default: the row stays for the choice {bell_rows(LID)}")
sl = state_list(Bo, LID)
check(sl and sl["bell"] == "default" and sl["bell_custom"] == {"comment": {"news": 0, "push": 1}}, f"the app shows the bell and the kept choice {sl and (sl['bell'], sl['bell_custom'])}")
check(put_bell(Bo, LID, "custom").ok and state_list(Bo, LID)["bell"] == "custom", "switching back to custom brings the choice back")

# "all": every comment of the project
TA = A.post(B + "/api/tasks", json={"title": "Regal bauen", "list_id": LID}).json()["id"]
check(put_bell(Bo, LID, "all").ok, "bob: everything")
comment(A, TA, "Holz ist da")
check(kt.until(lambda: news(Bo, TA, "comment"), timeout=10), "the bell 'all': bob gets the News of a comment on a task he never touched")
check(not news(Gi, TA, "comment"), "gina (default bell) does not")

# "mute": nothing but mentions
TB = Bo.post(B + "/api/tasks", json={"title": "Schrauben zaehlen", "list_id": LID}).json()["id"]
check(put_bell(Bo, LID, "mute").ok, "bob mutes the project")
comment(A, TB, "kurze Frage")
comment(A, TB, f"<@{BOB}> bitte ansehen")
check(kt.until(lambda: news(Bo, TB, "mention"), timeout=10), "muted: a mention still reaches bob")
check(not news(Bo, TB, "comment"), "muted: the plain comment on his own task does not")
check(push_ok(BOB, "comment", LID) is False and push_ok(BOB, "mention", LID) is True, "the push decision: muted holds the comment, not the mention")
out = box(f"""from kalmido.core.objfollow import ofl_quiet
print("Q", ofl_quiet(c, {BOB}, "list", {LID}, {{}}, only_mute=True), ofl_quiet(c, {GINA}, "list", {LID}, {{}}, only_mute=True))""")
check("Q True False" in out, f"the core's follow step: bob's project is muted, gina's not {out[-200:]}")

# ================================================================== who gets something: the right first
dbx("INSERT INTO obj_follow(user_id,kind,ref_id,org_id,mode) VALUES(?,'list',?,?,'all')", (DAVE, LID, ORG))  # by hand: no right
check(Da.get(B + f"/api/lists/{LID}/notify-template").status_code == 404, "dave does not see the project")
comment(A, TA, "noch eine Frage")
check(kt.until(lambda: len(news(Bo, TA, "comment")) >= 1, timeout=10), "the comment went out")
check(not dbx("SELECT 1 FROM notifications WHERE user_id=? AND task_id=?", (DAVE, TA)), "dave (a bell 'all' without the right) gets nothing")
dbx("DELETE FROM obj_follow WHERE user_id=? AND kind='list'", (DAVE,))

# ================================================================== the owner's ceiling
check(put_bell(Bo, LID, "default").ok, "bob: bell back to default")
# the default template of a share comes from KALMIDO_NOTIF_TEMPLATE (the test server's may differ): set 'read' explicitly
r = A.put(tpl_url(LID), json={"tpl": "read"})
check(r.ok and caps("list", LID) == [("", 0, "read")], f"alice: the project's template 'read' {r.status_code} {caps('list', LID)}")
check(push_ok(BOB, "comment", LID) is False and push_ok(BOB, "mention", LID) is True, "'read': no push for a comment, one for a mention")
r = A.put(tpl_url(LID), json={"tpl": "work"})
check(r.ok and r.json()["own"]["tpl"] == "work", f"alice: the project's template 'work' {r.status_code} {r.text[:200]}")
check(caps("list", LID) == [("", 0, "work")], f"a row of obj_notif_cap kind list for everyone {caps('list', LID)}")
check(Bo.get(tpl_url(LID)).json()["effective"]["tpl"] == "work" and push_ok(BOB, "comment", LID) is True, "bob: 'work' lets the comment push through")
check(push_ok(BOB, "complete", LID) is False, "... but not a completion")
r = A.put(tpl_url(LID), json={"tpl": "custom", "custom": {"complete": 1}, "user_id": BOB})
check(r.ok and caps("list", LID) == [("", 0, "work"), ("", BOB, "custom")], f"alice: bob's own template {caps('list', LID)}")
cj = dbx("SELECT custom->>'complete' FROM obj_notif_cap WHERE kind='list' AND ref_id=? AND user_id=?", (LID, BOB))
check(cj and cj[0][0] == "1", f"the choice is JSONB {cj}")
check(push_ok(BOB, "complete", LID) is True and push_ok(BOB, "comment", LID) is False and push_ok(GINA, "comment", LID) is True,
      "bob's own template counts for bob, the project's for gina")
check(A.put(tpl_url(LID), json={"tpl": None, "user_id": BOB}).ok and A.put(tpl_url(LID), json={"tpl": None}).ok and caps("list", LID) == [],
      f"alice takes both back {caps('list', LID)}")

# the folder's template
check(A.patch(B + f"/api/lists/{LID}", json={"folder": "Kunden"}).ok, "the project goes into the folder Kunden")
r = A.put(B + "/api/folders/notify-template", json={"folder": "Kunden", "tpl": "all"})
check(r.ok and caps("folder", ALICE) == [("Kunden", 0, "all")], f"alice: the folder's template (kind folder, ref the owner, path the folder) {r.status_code} {caps('folder', ALICE)}")
check(Bo.get(tpl_url(LID)).json()["effective"]["tpl"] == "all" and push_ok(BOB, "complete", LID) is True, "bob: the folder's 'all' counts")
check(A.post(B + "/api/folders/rename", json={"old": "Kunden", "new": "Klienten"}).ok, "alice renames the folder")
check(caps("folder", ALICE) == [("Klienten", 0, "all")] and Bo.get(tpl_url(LID)).json()["effective"]["tpl"] == "all",
      f"the template goes along with the folder {caps('folder', ALICE)}")

# the account export keeps its parts
check(A.put(tpl_url(LID), json={"tpl": "read", "user_id": BOB}).ok, "alice: bob's template again (for the export)")
out = box(f"""import json
from kalmido.accounts.settings import umz_export_queries
q = umz_export_queries({ALICE})
for k in ("list_notif", "folder_notif"):
    sql, a = q[k]
    print("EX" + k + " " + json.dumps([dict(r) for r in c.execute(sql, a).fetchall()], default=str))""")
ex = {ln.split(" ", 1)[0][2:]: json.loads(ln.split(" ", 1)[1]) for ln in out.splitlines() if ln.startswith("EX")}
ln_, fn_ = ex.get("list_notif") or [], ex.get("folder_notif") or []
check([(x["list_id"], x["user_id"], x["tpl"]) for x in ln_] == [(LID, BOB, "read")] and set(ln_[0]) == {"list_id", "user_id", "tpl", "custom", "updated_at"},
      f"the account export: the part list_notif with its old columns {ln_}")
check([(x["owner_id"], x["folder"], x["user_id"], x["tpl"]) for x in fn_] == [(ALICE, "Klienten", 0, "all")], f"... and folder_notif {fn_}")

# ================================================================== the end of a share, the workspace, the project
check(put_bell(Gi, LID, "mute").ok and (GINA, "mute") in bell_rows(LID), "gina mutes the project")
check(A.delete(B + f"/api/lists/{LID}/members/{GINA}").ok, "alice removes gina from the project")
check(not [x for x in bell_rows(LID) if x[0] == GINA], f"her bell there ends {bell_rows(LID)}")
check(put_bell(Bo, LID, "all").ok, "bob: everything")
out = box(f"""from kalmido.collab.news import list_bell
c.execute("UPDATE obj_follow SET org_id=NULL WHERE kind='list' AND ref_id=?", ({LID},))
print("OTHER", list_bell(c, {BOB}, {LID})[0])
c.execute("UPDATE obj_follow SET org_id=? WHERE kind='list' AND ref_id=?", ({ORG}, {LID}))
print("BACK", list_bell(c, {BOB}, {LID})[0])""")
check("OTHER default" in out and "BACK all" in out, f"a bell row of another workspace does not count, of its own it does {out[-200:]}")
L2 = A.post(B + "/api/lists", json={"name": "Lager", "kind": "project", "org_id": ORG}).json()["id"]
check(put_bell(A, L2, "mute").ok and A.put(tpl_url(L2), json={"tpl": "work"}).ok, "alice: bell and template of a second project")
out = box(f"""from kalmido.accounts.orgs import list_space_follow
c.execute("UPDATE lists SET org_id=NULL WHERE id=?", ({L2},))
list_space_follow(c, {L2}, {ORG}, False)""")
o = dbx("SELECT org_id FROM obj_follow WHERE kind='list' AND ref_id=? AND user_id=?", (L2, ALICE))
check(o and o[0][0] is None, f"the project moves into another workspace: its bell goes along {o}")
dbx("DELETE FROM lists WHERE id=?", (L2,))
check(bell_rows(L2) == [] and caps("list", L2) == [], "a project deleted for good takes its bells and templates along")

# ================================================================== the move of the old tables (a version before 2.981 ran)
L3 = A.post(B + "/api/lists", json={"name": "Archiv", "kind": "project", "org_id": ORG}).json()["id"]
dbx("""CREATE TABLE list_bell (user_id BIGINT NOT NULL, list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
       mode TEXT NOT NULL, custom TEXT, PRIMARY KEY(user_id, list_id))""")
dbx("""CREATE TABLE list_notif (list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE, user_id BIGINT NOT NULL DEFAULT 0,
       tpl TEXT NOT NULL, custom TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (list_id, user_id))""")
dbx("""CREATE TABLE folder_notif (owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, folder TEXT NOT NULL,
       user_id BIGINT NOT NULL DEFAULT 0, tpl TEXT NOT NULL, custom TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (owner_id, folder, user_id))""")
dbx("INSERT INTO list_bell(user_id,list_id,mode,custom) VALUES(?,?,'custom',?)", (ALICE, L3, json.dumps({"newtask": {"push": 1}})))
dbx("INSERT INTO list_bell(user_id,list_id,mode,custom) VALUES(?,?,'loud','{not json}')", (BOB, L3))
dbx("INSERT INTO list_notif(list_id,user_id,tpl,custom,updated_at) VALUES(?,0,'custom',?,'2026-11-01T08:30:00+00:00')", (L3, json.dumps({"comment": 1})))
dbx("INSERT INTO list_notif(list_id,user_id,tpl,custom,updated_at) VALUES(?,?,'bogus',NULL,'not a time')", (L3, BOB))
dbx("INSERT INTO folder_notif(owner_id,folder,user_id,tpl,custom,updated_at) VALUES(?,'Alt',0,'read',NULL,'2026-11-01T08:30:00+00:00')", (ALICE,))
box("pass")  # the next start of the app
check(not any(table_there(t) for t in ("list_bell", "list_notif", "folder_notif")), "the start dropped the old tables made again")
mine = box("from kalmido.core.config import APP_VERSION\nprint(APP_VERSION)")
fl = dict(dbx("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')"))
check(fl.get("back_floor") == ".".join(mine.split(".")[:2] + ["0"]) and "#5287" in (fl.get("back_floor_how") or ""),
      f"the move raised back_floor to the minor of this image {fl} {mine}")
check(bell_rows(L3) == [(ALICE, "custom"), (BOB, "default")], f"the bells moved; an unknown mode became default {bell_rows(L3)}")
m = dbx("SELECT user_id, custom->'newtask'->>'push', custom IS NULL, org_id FROM obj_follow WHERE kind='list' AND ref_id=? ORDER BY user_id", (L3,))
check([tuple(x) for x in m] == [(ALICE, "1", False, ORG), (BOB, None, True, ORG)], f"the choice came along, a broken one became NULL, the workspace was set {m}")
check(caps("list", L3) == [("", 0, "custom"), ("", BOB, "read")], f"the templates moved; an unknown one became read {caps('list', L3)}")
t = dbx("SELECT custom->>'comment', updated_at::text FROM obj_notif_cap WHERE kind='list' AND ref_id=? AND user_id=0", (L3,))
check(t and t[0][0] == "1" and t[0][1].startswith("2026-11-01"), f"... with their choice and time {t}")
check(("Alt", 0, "read") in caps("folder", ALICE), f"the folder's template moved {caps('folder', ALICE)}")
check(state_list(A, L3)["bell"] == "custom", "the app reads the moved bell")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes"}).json()["id"]
r = put_bell(Fr, FL, "mute")
check(r.ok and state_list(Fr, FL)["bell"] == "mute", f"freelancer: mutes her project {r.status_code} {r.text[:200]}")
f = dbx("SELECT mode, org_id FROM obj_follow WHERE kind='list' AND ref_id=? AND user_id=?", (FL, FID))
check([tuple(x) for x in f] == [("mute", None)], f"freelancer: a private row {f}")
r = Fr.put(tpl_url(FL), json={"tpl": "read"})
check(r.ok and r.json()["own"]["tpl"] == "read" and caps("list", FL) == [("", 0, "read")], f"freelancer: the template of her project {r.text[:200]}")
check(put_bell(Fr, FL, "default").ok and bell_rows(FL) == [], "freelancer: back to default without an own choice: no row")

sys.exit(kt.done("p2981_c_follow"))
