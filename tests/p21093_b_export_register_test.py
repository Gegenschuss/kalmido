#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1093.0 (#5289, stage Q11): the export register of the core (kalmido/core/objexport.py). The tables of the core (obj_*) say
where their rows go; the hand lists of admin/ hold only the old tables. Invented names only (example.com).
 - before / after: the files, where clauses, reasons and import parts the register gives are exactly the hand entries the
   lists had before (frozen below as they stood in 2.1092), none of them by hand any more, nothing twice
 - the organisation boundary: two organisations with a comment, a reaction, a watcher and a contact's task link each; the
   export of one carries its rows in the old files and columns, never a row of the other; its manifest names the core's
   tables that stay out with their reasons
 - freelancer-matrix: a person without an organisation: the account export carries the own comment (data/comments.json), its
   manifest and the export page name the core's tables that stay out (the register's reasons, "history of knowledge pages")
Starts its OWN container (workspaces mode, no server key: the organisation export is a plain ZIP; P21093B_NOSTART=1 = it runs).
usage: p21093_b_export_register_test.py <datadir>"""
# freelancer-matrix: tasks
import io
import json
import subprocess
import sys
import zipfile

import kt
from freelancer_fixture import FEATURES, freelancer
from kt import B, check, dbx, sess, su_get

kt.fresh(prefix="P21093B", env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_API_RATE": "100000"})
kt.docker_logs_on_first_fail()
TS = "2026-11-10T10:00:00+00:00"


def ok(r, what):
    check(r.status_code in (200, 201, 202, 204), f"{what} {r.status_code} {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {}


def in_app(code):
    r = subprocess.run(["docker", "exec", kt.CT, "python", "-c", code], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-600:]


# ================================================================== before / after (in the app, no data)
# the hand entries of the core's tables as they stood before the register (2.1092: admin/orgexport.py OX_AREAS / OX_LEFT,
# admin/retexport.py RX_TABLES + RX_WHERE, admin/exportleft.py UMZ_LEFT_TABLES / UMZ_LATER_NAMES, admin/acctimport.py
# UMZ_READ / UMZ_ORG_MAP), with the constants they used
SNAP = r'''
import json
import app  # noqa: F401 (every module registered)
from kalmido.admin.orgexport import LSQ, TSQ, RSQ, OX_LETTER_LINKS, OX_AREAS, OX_LEFT, ox_areas, ox_left
from kalmido.admin.retexport import RX_TABLES, RX_WHERE, rx_tables
from kalmido.admin.exportleft import UMZ_LEFT_TABLES, UMZ_LATER_NAMES, umz_left_tables, umz_later_names
from kalmido.admin.acctimport import UMZ_READ, UMZ_READ_OWN, UMZ_ORG_MAP, UMZ_ORG_MAP_OWN
from kalmido.core.access import live_sql
from kalmido.core.objexport import OEX
OLD_ORG = {
    ("lists/tags.json", "obj_tags", f"scope_kind='list' AND scope_id IN (SELECT CAST(x.id AS TEXT) FROM ({LSQ}) x)"),
    ("org/labels.json", "obj_tags", "scope_kind='org' AND org_id=?"),
    ("lists/playbooks.json", "obj_versions", f"kind='playbook' AND ref_id IN (SELECT id FROM playbooks WHERE list_id IN ({LSQ}))"),
    ("tasks/tags.json", "obj_tag_links", f"""kind='task' AND obj_id IN ({TSQ}) AND tag_id IN (SELECT id FROM obj_tags WHERE (scope_kind='list'
     AND scope_id IN (SELECT CAST(x.id AS TEXT) FROM ({LSQ}) x)) OR (scope_kind='org' AND org_id=?))"""),
    ("tasks/watchers.json", "obj_follow", f"kind='task' AND mode='watch' AND ref_id IN ({TSQ})"),
    ("comments.json", "obj_comments", f"kind='task' AND ref_id IN ({TSQ})"),
    ("comments/reactions.json", "obj_reactions",
     f"target_kind='comment' AND target_id IN (SELECT id FROM obj_comments WHERE kind='task' AND ref_id IN ({TSQ}) AND {live_sql()})"),
    ("chat/reactions.json", "obj_reactions",
     f"target_kind='tchat' AND target_id IN (SELECT id FROM tchat_msgs WHERE room_id IN ({RSQ}) AND {live_sql()})"),
    ("books/contact_tasks.json", "obj_links", f"src_kind='contact' AND dst_kind='task' AND rel='contact' AND src_id IN (SELECT id FROM contacts WHERE book_id IN (SELECT id FROM books WHERE org_id=?)) AND dst_id IN ({TSQ})"),
    ("office/procdocs.json", "obj_versions", "kind='procdoc' AND org_id=?"),
    ("office/letter_links.json", "obj_links", f"org_id=? AND {OX_LETTER_LINKS}"),
    ("wiki/versions.json", "obj_versions", "kind='wiki' AND org_id=? AND ref_id NOT IN (SELECT id FROM wiki_pages WHERE deleted_at IS NOT NULL)"),
    ("videos/comments.json", "obj_comments", f"kind='video' AND org_id=? AND {live_sql()} AND ref_id NOT IN (SELECT id FROM video_reviews WHERE deleted_at IS NOT NULL)"),
    ("documents/notes.json", "obj_comments", f"kind='doc_note' AND org_id=? AND {live_sql()}"),
    ("hub/mail_links.json", "obj_links", "org_id=? AND src_kind='hub_mail' AND rel='made' AND src_id NOT IN (SELECT id FROM hub_mails WHERE deleted_at IS NOT NULL)"),
}
OLD_RX = {("books/procedure-documentation.csv", "obj_versions", "kind='procdoc' AND org_id=?"),
          ("letters/letter-links.csv", "obj_links", f"org_id=? AND {OX_LETTER_LINKS} AND src_id IN (SELECT id FROM office_letters WHERE org_id=? AND status<>'draft')")}
OLD_OX_LEFT = {"obj_addr_shares": "invitations (not_included)", "obj_history": "derived or working data, rebuilt on the target",
               "obj_undo": "undo steps of 30 days", "obj_revoked": "shares removed (not_included)"}
DER, SHR, VIEW = "derived or working data, rebuilt on the target", "who shares what with whom (a share is made anew on the target)", "what a person has seen or hidden, the order of their rows"
OLD_UMZ_LEFT = {"obj_history": DER, "obj_undo": DER, "obj_revoked": SHR, "obj_addr_shares": SHR, "obj_comment_trash": DER,
                "obj_versions": "not yet in the account export", "obj_search_words": DER, "obj_seen": VIEW, "obj_search": DER}
OLD_LATER = {"obj_versions": "history of knowledge pages"}
OLD_MAP = {"lists/tags.json": "list_tags", "tasks/tags.json": "task_list_tags", "org/labels.json": "org_tags", "comments.json": "comments"}
OLD_READ = {"list_tags", "task_tags", "task_list_tags", "comments", "org_tags", "video_comments", "task_bell", "task_watchers"}
core = lambda d: {k: v for k, v in d.items() if k.startswith("obj_")}
out = {
    "org": {x for x in ox_areas() if x[1].startswith("obj_")} == OLD_ORG,
    "org_hand": not [x for x in OX_AREAS if x[1].startswith("obj_")] and not core(OX_LEFT),
    "org_twice": len(ox_areas()) == len({x[0] for x in ox_areas()}),
    "org_left": core(ox_left()) == OLD_OX_LEFT,
    "rx": {x for x in rx_tables() if x[1].startswith("obj_")} == OLD_RX,
    "rx_hand": not [x for x in RX_TABLES if x[1].startswith("obj_")] and not core(RX_WHERE),
    "umz_left": core(umz_left_tables()) == OLD_UMZ_LEFT and not core(UMZ_LEFT_TABLES),
    "later": core(umz_later_names()) == OLD_LATER and not core(UMZ_LATER_NAMES),
    "map": {k: v for k, v in UMZ_ORG_MAP.items() if k in OLD_MAP} == OLD_MAP and not set(OLD_MAP) & set(UMZ_ORG_MAP_OWN),
    "read": OLD_READ <= UMZ_READ and not OLD_READ & UMZ_READ_OWN,
    "all_core": sorted(t for t in OEX if not t.startswith("obj_")),
}
# 2.1093.0 (#5289, review): a table registered after the account import read the register would silently not be imported
from kalmido.core.objexport import obj_export
try:
    obj_export("obj_zz_late", read=("zz_late",), by="kind zz")
    out["late"] = "accepted"
except ValueError as e:
    out["late"] = "refused" if "after the account import" in str(e) else str(e)
print(json.dumps(out, sort_keys=True))
'''
r = in_app(SNAP)
try:
    snap = json.loads(r)
except ValueError:
    snap = {}
check(snap.get("org") is True, f"before / after: the organisation export's files of the core's tables are the old ones, where clauses unchanged {r[:300]}")
check(snap.get("org_hand") is True, "no hand entry of a core table in OX_AREAS / OX_LEFT")
check(snap.get("org_twice") is True, "no file of the organisation export twice")
check(snap.get("org_left") is True, "the reasons of the organisation export are the old ones")
check(snap.get("rx") is True and snap.get("rx_hand") is True, "the retention export: the same CSV files and rows, none by hand")
check(snap.get("umz_left") is True and snap.get("later") is True, "the account export: the same reasons and names, none by hand")
check(snap.get("map") is True and snap.get("read") is True, "the imports: the same files and parts, none by hand")
check(snap.get("late") == "refused", f"a part registered after the import read the register is refused, not lost {snap.get('late')}")
check(snap.get("all_core") == [], f"only the core's tables in the register {snap.get('all_core')}")

# ================================================================== the organisation boundary (two organisations)
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
BOB = ok(A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Mitglied", "password": "password123",
                                         "email": "bob@example.com"}), "setup: bob").get("id")
kt.proved()
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORGS = {}
for name in ("Alpha Quelle", "Beta Fremd"):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE})
    check(r.status_code == 201, f"setup: organisation {name} {r.text[:120]}")
    ORGS[name] = r.json().get("id")
    ok(A.put(B + f"/api/orgs/{ORGS[name]}/members", json={"email": "bob@example.com", "role": "member"}), f"setup: bob in {name}")
    sess("bob").post(B + f"/api/orgs/{ORGS[name]}/join")  # an invitation is accepted (an instance admin's add is direct)
ORG, ORGB = ORGS["Alpha Quelle"], ORGS["Beta Fremd"]
DATA = {}
for org, tag in ((ORG, "alpha"), (ORGB, "beta")):
    A.patch(B + "/api/settings", json={"workspace": f"org:{org}"})
    lid = ok(A.post(B + "/api/lists", json={"name": f"Projekt {tag}", "org_id": org}), f"setup: list of {tag}").get("id")
    ok(A.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"}), f"setup: bob on the list of {tag}")
    tid = ok(A.post(B + "/api/tasks", json={"title": f"Aufgabe {tag}", "list_id": lid}), f"setup: task of {tag}").get("id")
    cid = ok(A.post(B + f"/api/tasks/{tid}/comments", json={"body": f"Kommentar {tag}"}), f"setup: comment of {tag}").get("id")
    ok(Bo.post(B + f"/api/comments/{cid}/reactions", json={"emoji": "heart"}), f"setup: bob's reaction in {tag}")
    # the core's rows directly where this suite does not check the area's route: a watcher, a contact's task link
    dbx("INSERT INTO obj_follow(kind, ref_id, user_id, mode, created_at) VALUES('task',?,?,'watch',?)", (tid, BOB, TS))
    bk = ok(A.post(B + "/api/books", json={"name": f"Kontakte {tag}", "org_id": org}), f"setup: address book of {tag}").get("id")
    if not dbx("SELECT org_id FROM books WHERE id=? AND org_id=?", (bk, org)):
        dbx("UPDATE books SET org_id=?, owner_org_id=? WHERE id=?", (org, org, bk))
    co = ok(A.post(B + "/api/contacts", json={"book_id": bk, "fn": f"Kim {tag}"}), f"setup: contact of {tag}").get("id")
    dbx("INSERT INTO obj_links(src_kind, src_id, dst_kind, dst_id, rel, extra, created_by, created_at) VALUES('contact',?,'task',?,'contact',"
        "CAST(? AS JSONB),?,?)", (co, tid, '{"kind": "waiting"}', ALICE, TS))
    DATA[tag] = {"list": lid, "task": tid, "comment": cid, "contact": co}
check(all(DATA.get(t, {}).get("comment") for t in ("alpha", "beta")), f"setup: both organisations have their rows {DATA}")

A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
ok(A.post(B + f"/api/orgs/{ORG}/export"), "the export of alpha starts")
st = kt.until(lambda: A.get(B + f"/api/orgs/{ORG}/export").json().get("state") in ("done", "failed"), timeout=240)
check(st and A.get(B + f"/api/orgs/{ORG}/export").json().get("state") == "done", "the export of alpha is done")
OX = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
try:
    z = zipfile.ZipFile(io.BytesIO(OX))
except zipfile.BadZipFile:
    z = None
check(z is not None, f"a plain ZIP without the server key {OX[:16]!r}")
names = set(z.namelist()) if z else set()


def rows(name):
    if name not in names:
        return []
    raw = z.read(name).decode()
    try:
        v = json.loads(raw)
    except ValueError:
        v = [json.loads(x) for x in raw.splitlines() if x.strip()]
    return v if isinstance(v, list) else []


a, b = DATA.get("alpha", {}), DATA.get("beta", {})
cm = rows("comments.json")
check(any(r.get("body") == "Kommentar alpha" and r.get("task_id") == a.get("task") for r in cm)
      and all(r.get("task_id") == a.get("task") for r in cm), f"comments.json: alpha's comment in the old columns (task_id), only alpha's task {cm}")
rx_ = rows("comments/reactions.json")
check(rx_ and {r.get("comment_id") for r in rx_} == {a.get("comment")}, f"comments/reactions.json: bob's reaction on alpha's comment only {rx_}")
wa = rows("tasks/watchers.json")
check((a.get("task"), BOB) in {(r.get("task_id"), r.get("user_id")) for r in wa} and {r.get("task_id") for r in wa} == {a.get("task")},
      f"tasks/watchers.json: bob watching alpha's task, nothing of beta {wa}")
ct = rows("books/contact_tasks.json")
check({(r.get("contact_id"), r.get("task_id")) for r in ct} == {(a.get("contact"), a.get("task"))}, f"books/contact_tasks.json: alpha's link only {ct}")
blob = b"".join(z.read(n) for n in names if n.endswith(".json")) if z else b""
check(b"Kommentar beta" not in blob and b"Kim beta" not in blob, "nothing of beta anywhere in alpha's archive")
man = json.loads(z.read("manifest.json")) if z and "manifest.json" in names else {}
ni = " | ".join(man.get("not_included") or [])
check("undo steps of 30 days: " in ni and "obj_undo" in ni and "obj_history" in ni, f"the manifest names the core's tables that stay out (register) {ni[:400]}")

# ================================================================== freelancer-matrix: the account export of a person without organisation
FID, Fr = freelancer(B, A)
FL = ok(Fr.post(B + "/api/lists", json={"name": "Frei Projekt"}), "freelancer: own list").get("id")
FT = ok(Fr.post(B + "/api/tasks", json={"title": "Frei Aufgabe", "list_id": FL}), "freelancer: own task").get("id")
ok(Fr.post(B + f"/api/tasks/{FT}/comments", json={"body": "Frei Kommentar"}), "freelancer: own comment")
j = Fr.get(B + "/api/account/export").json()
later = next((x for x in j.get("not_included") or [] if x.startswith("not yet in the file: ")), "")
check("history of knowledge pages" in later, f"freelancer: the export page names the register's area not yet in the file {later[:200]}")
ok(Fr.post(B + "/api/account/export", json={}), "freelancer: account export starts")
kt.until(lambda: Fr.get(B + "/api/account/export").json().get("state") != "running", timeout=240)
check(Fr.get(B + "/api/account/export").json().get("state") == "done", "freelancer: account export done")
raw = su_get(Fr, B + "/api/account/export/file").content
try:
    fz = zipfile.ZipFile(io.BytesIO(raw))
except zipfile.BadZipFile:
    fz = None
check(fz is not None, "freelancer: the account export is a ZIP")
fn = set(fz.namelist()) if fz else set()
fc = fz.read("data/comments.json").decode() if "data/comments.json" in fn else ""
check("Frei Kommentar" in fc and "Kommentar alpha" not in fc, f"freelancer: data/comments.json has the own comment only {fc[:200]}")
fman = json.loads(fz.read("manifest.json")) if fz and "manifest.json" in fn else {}
fni = " | ".join(fman.get("not_included") or [])
check("obj_seen" in fni and "obj_search" in fni and "obj_history" in fni, f"freelancer: the manifest names the core's tables that stay out {fni[:400]}")

sys.exit(kt.done("p21093_b_export_register"))
