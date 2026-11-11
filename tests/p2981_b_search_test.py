#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.981.0 (#5278, stage Q6a of the cross-cutting core): the shared search index obj_search (core/objsearch.py). Own container.
Invented names only.
 - the table is there; task_fts, cmt_fts, the trigram indexes and contacts.search are gone; a database of before (the old side
   tables, an old trigger writing into them, contacts.search, a trigram index made again by hand) loses them at the next start,
   the back limit becomes the minor of this image, and a task / contact is written as before
 - umlauts (question 13): "Müller" finds "Mueller" and back, in tasks, notes, contacts and messages
 - word start everywhere, part of a word only in names and numbers (question 14): "ank" finds no task "Bankverbindung", but a
   contact "Bankmann" and the end of a phone number; a part of the ticket key finds its task
 - rights: another organisation and a person without one find nothing of Alpha; a guest finds only the shared project; the
   private project of alice is not in bob's hits; an agent finds only the tasks / comments of the project shared with it
 - comments: a task's comment is a hit of the task; a comment of a kind without a registered rights check (video) gives no
   hit at all, although it is in the index
 - knowledge pages (question 15): a guest with a share of the core on a folder finds its pages by name (also a part of the
   name), not a page outside it; alice finds every page of the space
 - the index follows: a renamed title, a changed phone number, a task deleted for good; a lost index row and a new index
   version are built again at the start
freelancer-matrix: search (a person without an organisation finds her own task, note and contact, umlauts and name parts)
usage: p2981_b_search_test.py <datadir>"""
import os
import subprocess
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

V = B + "/api/v1"


def box(code):
    """Python inside the app container (as the system); "import app" starts the app (init_db: the move, the fragments)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\n"
                          "from kalmido.core.pg import system_ctx\nc = connect()\nwith system_ctx(c):\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "c.commit()\nc.close()"],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"the run in the container works {out.stderr[-800:]}")
    return out.stdout.strip()


def there(sql, args=()):
    return bool(dbx(sql, args))


def table_there(t):
    return there("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (t,))


def tasks_found(s, q):
    """ids of the tasks of the main search (core/state.py search_tasks)."""
    r = s.get(B + "/api/tasks", params={"scope": "search", "q": q, "limit": 200})
    return {t["id"] for t in r.json().get("tasks", [])} if r.ok else {("error", r.status_code)}


def fts(s, q):
    """(task id, where) of the full-text search /api/search, and its answer."""
    r = s.get(B + "/api/search", params={"q": q, "limit": 50})
    j = r.json() if r.ok else {}
    return {(h["task"]["id"], h["where"]) for h in j.get("hits", [])}, j


def notes_found(s, q):
    r = s.get(B + "/api/notes", params={"q": q})
    return {n["id"] for n in r.json().get("notes", [])} if r.ok else {("error", r.status_code)}


def contacts_found(s, q):
    r = s.get(B + "/api/contacts", params={"q": q})
    return {x["id"] for x in r.json().get("items", [])} if r.ok else {("error", r.status_code)}


def msgs(s, q):
    r = s.get(B + "/api/search/messages", params={"q": q})
    return {(h["art"], h["id"]) for h in r.json().get("hits", [])} if r.ok else {("error", r.status_code)}


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def contact(s, **kw):
    r = s.post(B + "/api/contacts", json=kw)
    assert r.status_code in (200, 201), r.text
    return r.json()


kt.fresh(prefix="P2981B")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ALICE = kt.me_id(A)
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, role in (("bob", "member"), ("gina", "guest"), ("carl", "member")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    org_join(B, u, ORG)
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carl"]})
check(r.ok, "setup: organisation Beta for carl " + r.text[:100])
check(A.delete(B + f"/api/orgs/{ORG}/members/{uid['carl']}").ok, "setup: carl leaves Alpha")
FID, Fr = freelancer(B, A)
Bo, Gi, Ca = kt.sess("bob"), kt.sess("gina"), kt.sess("carl")
for s in (Bo, Gi, Ca, Fr):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BETA = r.json().get("id")

# an agent of Alpha, member of the shared project only
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "robo", "display_name": "Robo"})
check(r.ok, "setup: an agent " + r.text[:100])
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG}).ok, "setup: the agent belongs to Alpha")
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, AG))

# ================================================================== the table, the old structures gone
check(table_there("obj_search"), "the shared search index obj_search exists")
for t in ("task_fts", "cmt_fts"):
    check(not table_there(t), f"the old side table {t} is gone")
check(not there("SELECT 1 FROM information_schema.columns WHERE table_name='contacts' AND column_name='search'"), "contacts.search is gone")
ix = [x[0] for x in dbx("SELECT indexname FROM pg_indexes WHERE indexname LIKE 'msg_trgm_%' OR indexname LIKE 'tasks_trgm_%'")]
check(ix == [], f"no trigram index of the searches any more {ix}")
check(there("SELECT 1 FROM pg_indexes WHERE indexname='ix5278_obj_search_tsv'"), "the GIN index of obj_search")
check(not there("SELECT 1 FROM information_schema.columns WHERE table_name='obj_search' AND column_name='org_id'"),
      "obj_search has no org_id (row-level security would stop its index; the readers join the source rows)")

# ================================================================== data
W = A.post(B + "/api/lists", json={"name": "Werkstatt", "org_id": ORG}).json()["id"]
for who, role in ((uid["bob"], "edit"), (uid["gina"], "view"), (AG, "edit")):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": role}).ok, f"setup: {who} in Werkstatt")
P = A.post(B + "/api/lists", json={"name": "Privat", "org_id": ORG}).json()["id"]
TM1 = task(A, W, "Angebot Müller GmbH")
TM2 = task(A, W, "Rechnung", content="an Herrn Mueller schicken")
TBANK = task(A, W, "Bankverbindung prüfen")
TLINK = task(A, W, "Website", url="https://example.com/zauberwald")
TP = task(A, P, "Müller privat")
CMT = A.post(B + f"/api/tasks/{TBANK}/comments", json={"body": "Zebrastreifen vor dem Büro besprechen"}).json()["id"]
CMTP = A.post(B + f"/api/tasks/{TP}/comments", json={"body": "Zebrastreifen privat"}).json()["id"]
LB = Ca.post(B + "/api/lists", json={"name": "Beta", "org_id": BETA}).json().get("id")
TB = task(Ca, LB, "Müller in Beta")
FL = Fr.post(B + "/api/lists", json={"name": "Haushalt"}).json()["id"]
TF = task(Fr, FL, "Müllabfuhr anrufen", content="Ärger mit der Tonne")
N1 = A.post(B + f"/api/lists/{W}/notes", json={"title": "Quartalsplanung", "body": "Die Übersicht für Herrn Müller", "tags": "kunde"}).json()["id"]
NF = Fr.post(B + f"/api/lists/{FL}/notes", json={"title": "Notiz Mueller", "body": "privat"}).json()["id"]
C1 = contact(A, given="Anna", family="Bankmann", org="Mueller Bau", phones=[{"value": "+49 171 5551234"}],
             emails=[{"value": "anna@beispiel.example"}], addresses=[{"street": "Hauptweg 1", "city": "Berlin"}])["id"]
CF = contact(Fr, fn="Jürgen Fröhlich", phones=[{"value": "030 777 8899"}])["id"]

# ================================================================== umlauts (question 13)
for q in ("Müller", "Mueller", "muller", "MÜLLER"):
    got = tasks_found(A, q)
    check({TM1, TM2, TP} <= got and TB not in got, f"tasks: {q!r} finds Müller and Mueller (alice, not Beta's) {sorted(got, key=str)}")
h, _ = fts(A, "mueller")
check({(TM1, "title"), (TM2, "notes"), (TP, "title")} <= h, f"/api/search: title and notes hits for 'mueller' {h}")
check(notes_found(A, "mueller") == {N1} and notes_found(A, "übersicht") == {N1} and notes_found(A, "uebersicht") == {N1},
      "notes: umlauts both ways (title / text)")
check(contacts_found(A, "müller") == {C1}, "contacts: 'müller' finds the company Mueller Bau")

# ================================================================== word start vs. part of a word (question 14)
check(TBANK in tasks_found(A, "bank") and TBANK not in tasks_found(A, "ank"), "tasks: a word start finds, a part in the word not")
check(TBANK in tasks_found(A, "prufen") and TBANK in tasks_found(A, "pruefen"), "tasks: 'prüfen' as prufen / pruefen")
check(TLINK in tasks_found(A, "zauberwald"), "tasks: a word of the link (after its slash) is a word start")
check(N1 not in notes_found(A, "planung") and N1 in notes_found(A, "quartal"), "notes: word start only (no part in a word)")
check(contacts_found(A, "ankm") == {C1}, "contacts: a part of the family name")
check(contacts_found(A, "5551234") == {C1} and contacts_found(A, "1715551") == {C1}, "contacts: a part of the phone number")
check(contacts_found(A, "erlin") == set() and contacts_found(A, "berl") == {C1}, "contacts: the address only by word start")
check(contacts_found(A, "beispiel") == {C1}, "contacts: a word of the e-mail address")
r = A.patch(B + f"/api/lists/{W}", json={"ticket_key": "WKS"})
check(r.ok, f"setup: the project's ticket key {r.status_code} {r.text[:200]}")
TK = task(A, W, "Regal aufbauen")
no = dbx("SELECT ticket_no FROM tasks WHERE id=?", (TK,))[0][0]
check(no is not None and TK in tasks_found(A, f"KS-{no}"), f"tasks: a part of the ticket key WKS-{no}")

# ================================================================== rights
check(not tasks_found(Ca, "müller") & {TM1, TM2, TP} and TB in tasks_found(Ca, "müller"), "another organisation: only its own")
check(not tasks_found(Fr, "müller") & {TM1, TM2, TP, TB}, "a person without an organisation: nothing of Alpha / Beta")
gb = tasks_found(Bo, "müller")
check({TM1, TM2} <= gb and TP not in gb, f"bob: the shared project, not alice's private one {gb}")
gg = tasks_found(Gi, "müller")
check({TM1, TM2} <= gg and TP not in gg, f"the guest: the shared project only {gg}")
h, _ = fts(Gi, "mueller")
check({x[0] for x in h} <= {TM1, TM2}, f"the guest's /api/search: the shared project only {h}")
check(notes_found(Ca, "mueller") == set() and contacts_found(Ca, "bankmann") == set() and contacts_found(Bo, "bankmann") == set(),
      "notes and contacts of other people: never")
r = requests.get(V + "/tasks", headers=AGH, params={"q": "müller"})
got = {t["id"] for t in r.json().get("data", [])} if r.ok else {("error", r.status_code)}
check({TM1, TM2} <= got and TP not in got and TB not in got, f"the agent (v1 q): only the shared project {got}")
r = requests.get(V + "/search", headers=AGH, params={"scope": "messages", "q": "zebrastreifen"})
got = {h["id"] for h in r.json().get("data", [])} if r.ok else {("error", r.status_code)}
check(CMT in got and CMTP not in got, f"the agent (messages): the comment of the shared project only {got}")

# ================================================================== comments
h, j = fts(A, "zebra")
check((TBANK, "comment") in h and (TP, "comment") in h, f"a comment is a hit of its task {h}")
check(any(x.get("comment_id") == CMT for x in j.get("hits", [])), "... with the comment's id")
h, _ = fts(Bo, "zebra")
check((TBANK, "comment") in h and TP not in {x[0] for x in h}, f"bob: not the comment of the private project {h}")
check(("c", CMT) in msgs(Bo, "zebrastreifen") and ("c", CMTP) not in msgs(Bo, "zebrastreifen"), "the message search the same")
check(msgs(Ca, "zebrastreifen") == set(), "another organisation: no comment")
# a comment of a kind without a registered rights check: in the index, never a hit
dbx("INSERT INTO obj_comments(kind, ref_id, user_id, body) VALUES('video', 1, ?, 'Zebrastreifen im Video')", (ALICE,))
VC = dbx("SELECT id FROM obj_comments WHERE kind='video'")[0][0]
check(there("SELECT 1 FROM obj_search WHERE kind='comment' AND ref_id=? AND pkind='video'", (VC,)), "the video comment is in the index")
h, j = fts(A, "zebrastreifen")
check("comments" not in j and ("c", VC) not in msgs(A, "zebrastreifen"), f"... and no hit (no rights check registered) {j.get('comments')}")

# ================================================================== team chat
RDM = A.post(B + "/api/team/dm", json={"user_id": uid["bob"]}).json().get("id")
r = A.post(B + f"/api/team/rooms/{RDM}/messages", json={"body": "Treffen in der Müllerstraße"})
TM = r.json().get("id") if r.ok else None
check(TM is not None, f"setup: a direct message {r.status_code}")
check(("t", TM) in msgs(Bo, "muellerstrasse") and ("t", TM) in msgs(A, "müllerstraße"), "team chat: umlauts and ß both ways")
check(("t", TM) not in msgs(Gi, "muellerstrasse"), "team chat: not for a third person")

# ================================================================== knowledge pages (question 15)
SP = f"org:{ORG}"


def page(path):
    r = A.post(B + "/api/wiki/pages", json={"space": SP, "path": path, "body": "Text"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


WP1 = page("Kunden/Müller Bau/Ablauf")
WP2 = page("Intern/Geheimplan")
j = A.get(B + "/api/wiki", params={"space": SP}).json()
FK = next((f["id"] for f in j.get("folders", []) if f["path"] == "Kunden/Müller Bau"), None)
r = A.post(B + f"/api/files/nodes/{FK}/shares", json={"user_id": uid["gina"], "role": "view"})
check(r.status_code == 201, f"setup: the folder shared with the guest {r.status_code} {r.text[:200]}")
_, j = fts(Gi, "ablauf")
check([p["id"] for p in j.get("wiki", [])] == [WP1], f"the guest finds the shared page by its name {j.get('wiki')}")
_, j = fts(Gi, "geheim")
check(not j.get("wiki"), f"... not a page outside the share {j.get('wiki')}")
_, j = fts(A, "heimpl")
check([p["id"] for p in j.get("wiki", [])] == [WP2], f"a part of a page's name (alice, the space) {j.get('wiki')}")
_, j = fts(Ca, "ablauf")
check(not j.get("wiki"), "another organisation: no page")

# ================================================================== freelancer-matrix: search
check(TF in tasks_found(Fr, "mull") and TF in tasks_found(Fr, "arger") and TF not in tasks_found(A, "mull"),
      "freelancer: her task by word start and umlaut (nobody else's)")
h, _ = fts(Fr, "aerger")
check((TF, "notes") in h, f"freelancer: /api/search in the notes {h}")
check(notes_found(Fr, "müller") == {NF}, "freelancer: her note (Mueller as Müller)")
check(contacts_found(Fr, "frohlich") == {CF} and contacts_found(Fr, "rgen") == {CF} and contacts_found(Fr, "7778899") == {CF},
      "freelancer: her contact by umlaut, a part of the name, a part of the number")
check(contacts_found(A, "frohlich") == set(), "... nobody else's")

# ================================================================== the index follows
check(A.patch(B + f"/api/tasks/{TM1}", json={"title": "Angebot Schmidt GmbH"}).ok, "setup: rename")
check(TM1 not in tasks_found(A, "müller") and TM1 in tasks_found(A, "schmidt"), "a renamed title: the new word, not the old")
check(A.patch(B + f"/api/contacts/{C1}", json={"phones": [{"value": "+49 160 4443322"}]}).ok, "setup: a new phone number")
check(contacts_found(A, "4443322") == {C1} and contacts_found(A, "5551234") == set(), "a changed phone number follows")
GONE = task(A, W, "Wombat vorübergehend")
dbx("DELETE FROM tasks WHERE id=?", (GONE,))
check(not there("SELECT 1 FROM obj_search WHERE kind='task' AND ref_id=?", (GONE,)), "a task deleted for good: its index row goes")

# ================================================================== the start: lost rows, a new version, the old structures
dbx("DELETE FROM obj_search WHERE kind='note' AND ref_id=?", (N1,))
dbx("DELETE FROM kalmido_meta WHERE key IN ('back_floor', 'back_floor_how')")
dbx("CREATE TABLE task_fts (task_id BIGINT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, vec tsvector NOT NULL)")
dbx("CREATE TABLE cmt_fts (comment_id BIGINT PRIMARY KEY, vec tsvector NOT NULL)")
dbx("""CREATE FUNCTION kalmido_fts_task() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN INSERT INTO task_fts(task_id, vec) VALUES (NEW.id, to_tsvector('simple', NEW.title)) ON CONFLICT DO NOTHING; RETURN NULL; END $fn$""")
dbx("CREATE TRIGGER kalmido_fts_task_ins AFTER INSERT ON tasks FOR EACH ROW EXECUTE FUNCTION kalmido_fts_task()")
dbx("ALTER TABLE contacts ADD COLUMN search TEXT NOT NULL DEFAULT ''")
dbx("CREATE INDEX tasks_trgm_title ON tasks USING gin (title gin_trgm_ops)")
dbx("CREATE INDEX msg_trgm_tchat_msgs ON tchat_msgs USING gin (kalmido_fold(body) gin_trgm_ops)")
box("pass")  # the next start of the app
check(not table_there("task_fts") and not table_there("cmt_fts"), "the start dropped the side tables made again")
check(not there("SELECT 1 FROM information_schema.columns WHERE table_name='contacts' AND column_name='search'"), "... and contacts.search")
check(not there("SELECT 1 FROM pg_trigger WHERE tgname='kalmido_fts_task_ins'") and not there("SELECT 1 FROM pg_proc WHERE proname='kalmido_fts_task'"),
      "... and the old trigger with its function")
check(not dbx("SELECT indexname FROM pg_indexes WHERE indexname IN ('tasks_trgm_title', 'msg_trgm_tchat_msgs')"), "... and the trigram indexes")
mine = box("from kalmido.core.config import APP_VERSION\nprint(APP_VERSION)")
fl = dict(dbx("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')"))
check(fl.get("back_floor") == ".".join(mine.split(".")[:2] + ["0"]) and "#5278" in (fl.get("back_floor_how") or ""),
      f"the move raised back_floor to the minor of this image {fl} {mine}")
check(there("SELECT 1 FROM obj_search WHERE kind='note' AND ref_id=?", (N1,)), "a lost index row is filled at the start")
kt.fresh(prefix="P2981B", keep=True)
A = kt.sess("alice")
T2 = task(A, W, "Nach dem Umzug Müller")
check(T2 in tasks_found(A, "mueller"), "after the move a new task is written and found")
C2 = contact(A, fn="Neu Kontakt", phones=[{"value": "0151 2223334"}])["id"]
check(contacts_found(A, "2223334") == {C2}, "... and a new contact")
dbx("UPDATE settings SET value='0' WHERE key='osr_v'")
dbx("UPDATE obj_search SET tsv=''::tsvector WHERE kind='task' AND ref_id=?", (TM2,))
kt.fresh(prefix="P2981B", keep=True)
A = kt.sess("alice")
check(TM2 in tasks_found(A, "mueller"), "a new index version builds the index again at the start")

sys.exit(kt.done("p2981_b_search"))
