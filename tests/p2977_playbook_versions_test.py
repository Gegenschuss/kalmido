#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.977.0 (#5282, stage Q7b of the cross-cutting core): the playbooks and the procedure documentation keep only their head,
their versions are rows of the core's obj_versions (kind "playbook" / "procdoc"). Own container (a server key: sealed texts).
Invented names only. freelancer-matrix: lists  freelancer-matrix: office
 - a new database: playbooks = id, list_id, owner_id, folder; office_procdocs = id, org_id; obj_versions has source
 - a list's Playbook: saves are numbered versions of the core on ONE head (source edit / restore), the routes answer as before
   (versions newest first, one version, restore = a new version, a stale base 409); a person without an organisation the same
 - a folder merged into another by a rename: the moved versions follow the target's (the moved text is current), one head left,
   the ids grow with the numbers
 - the procedure documentation of an organisation: versions of the core, sealed at rest, an old version reads as it was; the
   personal office of a person without an organisation the same
 - the move at the start (lists/playbook.py pb_retire, office/procdoc.py pd_retire) on old columns as 2.39 - 2.976 made them:
   the playbook rows move (numbers kept, the owner for an author NULL, NULL for an account that is gone, source kept), the old
   rows besides the head go, the columns go, the unique indexes come back; the procedure documentation of an area whose text
   cannot be opened stays with its columns (start check, log line) while the others moved (a sealed text sealed again for the
   new context and readable); the back limit names #5282; once that row is gone the next start drops the columns
usage: p2977_playbook_versions_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, FAILS, OKS, check, sess, until  # noqa: E402,F401

FEAT = "cal,comments,collab,office,clients,docs"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
PD = B + "/api/office/procdoc"

kt.fresh(env={"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": base64.b64encode(os.urandom(32)).decode()}, prefix="P2977")


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def cols(t):
    return {r[0] for r in sql("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?", (t,))}


def indexes(t):
    return {r[0]: r[1] for r in sql("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname=current_schema() AND tablename=?", (t,))}


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def _health():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


def restart():
    """The next start of the server (core/db.py init_db runs the START hooks: pb_retire, pd_retire)."""
    subprocess.run(["docker", "restart", CT], capture_output=True)
    up = until(lambda: _health(), timeout=90)
    check(up, "the server is up again after the restart")
    if not up:  # the reason in the suite's output (the start's traceback)
        print(logs()[-6000:])
        sys.exit(1)


def in_app(code, *args):
    r = subprocess.run(["docker", "exec", "-i", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", code, *map(str, args)],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (r.stdout + r.stderr)[-600:]}


def pbv(where, args=()):
    """(no, body, created_by, source, id) of the Playbook versions of the heads matching where (newest first)."""
    return sql("SELECT v.no, v.body, v.created_by, v.source, v.id FROM playbooks p JOIN obj_versions v ON v.kind='playbook' AND v.ref_id=p.id "
               f"WHERE {where} ORDER BY v.no DESC", args)


def field(d, key):
    return next(f for s in d["sections"] for f in s["fields"] if f["key"] == key)


A = kt.setup()
ALICE = A.get(B + "/api/me").json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FE, Fe = freelancer(B, A, "fred", features=FEAT)  # freelancer-matrix: lists, office (no organisation, the personal office)
r = A.post(B + "/api/users", json={"username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
assert r.ok, r.text
Ol = sess("olga")
Ol.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})

# ================================================================== a new database
check(cols("playbooks") == {"id", "list_id", "owner_id", "folder"}, f"playbooks holds only the head {cols('playbooks')}")
check(cols("office_procdocs") == {"id", "org_id"}, f"office_procdocs holds only the head {cols('office_procdocs')}")
check("source" in cols("obj_versions"), "obj_versions has the column source")
check("UNIQUE" in indexes("playbooks").get("playbooks_list_v", "") and "UNIQUE" in indexes("office_procdocs").get("office_procdocs_org", ""),
      f"one head per Playbook / area (unique) {indexes('playbooks')} {indexes('office_procdocs')}")

# ================================================================== a list's Playbook
L = A.post(B + "/api/lists", json={"name": "Kundenprojekt"}).json()["id"]
PBU = B + f"/api/lists/{L}/playbook"
check(A.put(PBU, json={"text": "Regel eins."}).ok and A.put(PBU, json={"text": "Regel eins.\nRegel zwei.", "base_version": 1}).ok,
      "two saves of the Playbook")
check(A.put(PBU, json={"text": "veraltet", "base_version": 1}).status_code == 409, "a stale base_version: 409")
d = A.get(PBU).json()
check(d.get("version") == 2 and d.get("text") == "Regel eins.\nRegel zwei." and (d.get("updated_by") or {}).get("id") == ALICE,
      f"the current Playbook as before {d}")
vs = A.get(PBU + "/versions").json().get("versions") or []
check([v["version"] for v in vs] == [2, 1] and [v["source"] for v in vs] == ["edit", "edit"] and vs[0]["chars"] == len("Regel eins.\nRegel zwei."),
      f"the versions newest first {vs}")
v1 = A.get(PBU + "/versions/1").json()
check(v1.get("text") == "Regel eins." and v1.get("version") == 1, f"one version with its text {v1}")
r = A.post(PBU.replace("/playbook", "/playbook/restore"), json={"version": 1})
check(r.ok and r.json().get("version") == 3, f"restore = version 3 {r.text[:200]}")
rows = pbv("p.list_id=?", (L,))
check([x[0] for x in rows] == [3, 2, 1] and rows[0][1] == "Regel eins." and rows[0][3] == "restore" and rows[0][2] == ALICE,
      f"the versions are rows of the core (kind playbook), the restore says so {rows}")
check(len(sql("SELECT 1 FROM playbooks WHERE list_id=?", (L,))) == 1, "one head for the list")
check([x[4] for x in rows] == sorted((x[4] for x in rows), reverse=True), "the ids grow with the numbers")
check(Ol.get(PBU).status_code in (403, 404) and Ol.get(PBU + "/versions/1").status_code in (403, 404), "another person reads none of it")
# a person without an organisation
FL = Fe.post(B + "/api/lists", json={"name": "Freies Projekt"}).json()["id"]
check(Fe.put(B + f"/api/lists/{FL}/playbook", json={"text": "Freie Regel."}).ok, "freelancer: saves the Playbook")
fv = Fe.get(B + f"/api/lists/{FL}/playbook/versions").json().get("versions") or []
check([v["version"] for v in fv] == [1] and pbv("p.list_id=?", (FL,))[0][1] == "Freie Regel.", f"freelancer: version 1 in the core {fv}")

# ================================================================== a folder merged into another by a rename
for name, folder in (("In A", "Alpha"), ("In B", "Beta")):
    check(A.post(B + "/api/lists", json={"name": name, "folder": folder}).ok, f"setup: a list in {folder}")
F = B + "/api/folders/playbook"
check(A.put(F, json={"folder": "Beta", "text": "Beta-Regel."}).ok and A.put(F, json={"folder": "Alpha", "text": "Alpha-Regel."}).ok,
      "setup: the Playbooks of both folders")
r = A.post(B + "/api/folders/rename", json={"old": "Alpha", "new": "Beta"})
check(r.ok, f"rename Alpha -> Beta (merge) {r.status_code} {r.text[:160]}")
d = A.get(F, params={"folder": "Beta"}).json()
check(d.get("text") == "Alpha-Regel." and d.get("version") == 2, f"the moved text is the current one {d}")
heads = sql("SELECT folder FROM playbooks WHERE list_id IS NULL AND owner_id=? ORDER BY folder", (ALICE,))
check(heads == [("Beta",)], f"one head left {heads}")
fr = pbv("p.list_id IS NULL AND p.owner_id=? AND p.folder='Beta'", (ALICE,))
check([(x[0], x[1]) for x in fr] == [(2, "Alpha-Regel."), (1, "Beta-Regel.")] and fr[0][4] > fr[1][4],
      f"the versions follow the target's, the ids grow with the numbers {fr}")
check(A.get(F, params={"folder": "Alpha"}).json().get("text") == "", "nothing left under the old name")

# ================================================================== the procedure documentation
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.put(PD, json={"own": {"company": "Erster Stand"}, "base": 0}).ok and A.put(PD, json={"own": {"company": "Zweiter Stand"}, "base": 1}).ok,
      "two saves of the procedure documentation")
pr = sql("SELECT v.no, v.body, v.created_by FROM office_procdocs p JOIN obj_versions v ON v.kind='procdoc' AND v.ref_id=p.id "
         "WHERE p.org_id=? ORDER BY v.no", (ORG,))
check([x[0] for x in pr] == [1, 2] and all(str(x[1]).startswith("kenc1:") for x in pr) and pr[0][2] == ALICE,
      f"two versions of the core, sealed at rest {[(x[0], str(x[1])[:10]) for x in pr]}")
check(len(sql("SELECT 1 FROM office_procdocs WHERE org_id=?", (ORG,))) == 1, "one head for the area")
d = A.get(PD, params={"version": "1"}).json()
check(d.get("viewing") == 1 and field(d, "company")["own"] == "Erster Stand" and d.get("version") == 2, f"version 1 reads as it was {str(d)[:200]}")
vs = A.get(PD + "/versions").json().get("items") or []
check([v["version"] for v in vs] == [2, 1], f"the versions newest first {vs}")
check(Ol.get(PD + "/versions").json().get("items", []) == [], "another person's office sees none of it")
check(Fe.put(PD, json={"own": {"company": "Freiberuflich"}}).ok and Fe.get(PD).json().get("version") == 1
      and field(Fe.get(PD, params={"version": "1"}).json(), "company")["own"] == "Freiberuflich",
      "freelancer: the personal office's procedure documentation works the same")

# ================================================================== the move at the start: old columns as 2.39 - 2.976 made them
ORG3 = A.post(B + "/api/admin/orgs", json={"name": "Gamma Film", "admin_id": ALICE}).json()["id"]
ORG4 = A.post(B + "/api/admin/orgs", json={"name": "Delta Ton", "admin_id": ALICE}).json()["id"]
SEAL = in_app("import app, json, sys\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\n"
              "from kalmido.core.orgcrypt import oc_key, oc_enc_k\n"
              "c = connect()\nwith system_ctx(c):\n    o = int(sys.argv[1])\n    k = oc_key(c, o)\n"
              "    print(json.dumps(oc_enc_k(k, o, 'office_procdocs.data', sys.argv[2]) if k else None))\nc.commit()\nc.close()",
              ORG3, json.dumps({"own": {"company": "Alter versiegelter Stand"}, "auto": {}, "lang": "de", "app_version": "2.900.0"}))
check(isinstance(SEAL, str) and SEAL.startswith("kenc1:"), f"setup: a text sealed with the old context {str(SEAL)[:80]}")
L2 = A.post(B + "/api/lists", json={"name": "Altprojekt"}).json()["id"]
T0, T1 = "2026-03-01T10:00:00+00:00", "2026-03-02T10:00:00+00:00"
# the indexes under their names in the old form (schema.py of 2.39 - 2.976): a start finds them by name and leaves them
for q in ("DROP INDEX IF EXISTS playbooks_list_v", "DROP INDEX IF EXISTS playbooks_folder_v", "DROP INDEX IF EXISTS office_procdocs_org",
          "ALTER TABLE playbooks ADD COLUMN version BIGINT, ADD COLUMN body TEXT NOT NULL DEFAULT '', "
          "ADD COLUMN source TEXT NOT NULL DEFAULT 'edit', ADD COLUMN author_id BIGINT, ADD COLUMN created_at TEXT",
          "ALTER TABLE office_procdocs ADD COLUMN version BIGINT, ADD COLUMN data TEXT NOT NULL DEFAULT '{}', ADD COLUMN created_by BIGINT, "
          "ADD COLUMN created_at TEXT",
          "CREATE UNIQUE INDEX playbooks_list_v ON playbooks(list_id, version) WHERE list_id IS NOT NULL",
          "CREATE UNIQUE INDEX playbooks_folder_v ON playbooks(owner_id, folder, version) WHERE list_id IS NULL",
          "CREATE INDEX office_procdocs_org ON office_procdocs(org_id, version)"):
    sql(q, write=True)
for lid, owner, folder, v, body, src, author, at in (
        (L2, None, None, 3, "Alt drei", "edit", None, T0), (L2, None, None, 4, "Alt vier", "proposal", 999999, T1),
        (None, ALICE, "Archiv", 1, "Archiv-Regel", "import", ALICE, T0)):
    sql("INSERT INTO playbooks(list_id, owner_id, folder, version, body, source, author_id, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (lid, owner, folder, v, body, src, author, at), write=True)
for oid, v, data in ((ORG3, 1, json.dumps({"own": {"company": "Alter Klartext"}, "auto": {}, "lang": "de"})), (ORG3, 2, SEAL),
                     (ORG4, 1, "kenc1:" + "A" * 48)):  # ORG4: cannot be opened (no key, no valid tag)
    sql("INSERT INTO office_procdocs(org_id, version, data, created_by, created_at) VALUES(?,?,?,?,?)", (oid, v, data, ALICE, T0), write=True)
restart()
A, Fe = sess("alice"), sess("fred")
check(cols("playbooks") == {"id", "list_id", "owner_id", "folder"}, f"the playbook columns went {cols('playbooks')}")
check("UNIQUE" in indexes("playbooks").get("playbooks_list_v", "") and "UNIQUE" in indexes("playbooks").get("playbooks_folder_v", ""),
      f"the unique indexes of the heads are back {indexes('playbooks')}")
mv = pbv("p.list_id=?", (L2,))
check([(x[0], x[1], x[3]) for x in mv] == [(4, "Alt vier", "proposal"), (3, "Alt drei", "edit")] and len(sql("SELECT 1 FROM playbooks WHERE list_id=?", (L2,))) == 1,
      f"the old rows moved with their numbers and sources onto one head {mv}")
check(mv[1][2] == ALICE and mv[0][2] is None, f"author NULL -> the owner (#1978), a gone account -> NULL (foreign, B-M7) {mv}")
# Fable review F1: the account export names a gone author 0 (NULL there means the owner's own text, an import would follow it)
ex = [p for p in A.get(B + "/api/export.json").json().get("playbooks", []) if p.get("list_id") == L2]
check(sorted((p["version"], p["author_id"]) for p in ex) == [(3, ALICE), (4, 0)], f"F1: the export marks the gone author with 0 {ex}")
d = A.get(B + f"/api/lists/{L2}/playbook").json()
check(d.get("version") == 4 and d.get("text") == "Alt vier", f"the moved Playbook reads as before {d}")
check([(x[0], x[1]) for x in pbv("p.list_id IS NULL AND p.owner_id=? AND p.folder='Archiv'", (ALICE,))] == [(1, "Archiv-Regel")],
      "a folder's old version moved")
check(A.put(B + f"/api/lists/{L2}/playbook", json={"text": "Neu nach dem Umzug"}).json().get("version") == 5, "a save after the move: version 5")
fl = dict(sql("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')"))
check("#5282" in (fl.get("back_floor_how") or ""), f"the back limit names #5282 {fl}")
# the procedure documentation: the area that cannot be opened keeps the columns, the other one moved
check("version" in cols("office_procdocs") and "data" in cols("office_procdocs"), "start check: a text that cannot be opened keeps the columns")
check("procedure documentation, stage Q7b (#5282): the 1 old version(s) of office area" in logs(), "start check: the log names it")
check(sql("SELECT version FROM office_procdocs WHERE org_id=? AND version IS NOT NULL", (ORG4,)) == [(1,)], "its row stays as it was")
p3 = sql("SELECT v.no, v.body FROM office_procdocs p JOIN obj_versions v ON v.kind='procdoc' AND v.ref_id=p.id WHERE p.org_id=? ORDER BY v.no", (ORG3,))
check([x[0] for x in p3] == [1, 2] and str(p3[1][1]).startswith("kenc1:") and p3[1][1] != SEAL,
      f"the other area moved, the sealed text sealed again for obj_versions {[(x[0], str(x[1])[:12]) for x in p3]}")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG3}"})
d2 = A.get(PD, params={"version": "2"}).json()
check(d2.get("viewing") == 2 and field(d2, "company")["own"] == "Alter versiegelter Stand", f"and reads as before {str(d2)[:200]}")
check(field(A.get(PD, params={"version": "1"}).json(), "company")["own"] == "Alter Klartext", "the plain old version too")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG4}"})
r = A.put(PD, json={"own": {"company": "zu frueh"}})
check(r.status_code == 409, f"F4: the area whose old versions wait saves nothing new (409) {r.status_code} {r.text[:160]}")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.get(PD).json().get("version") == 2, "an area saved by the new code meanwhile is untouched")
# the row that cannot be opened goes (the way out): the next start drops the columns
sql("DELETE FROM office_procdocs WHERE org_id=?", (ORG4,), write=True)
restart()
check(cols("office_procdocs") == {"id", "org_id"}, f"the next start drops the columns {cols('office_procdocs')}")
check("UNIQUE" in indexes("office_procdocs").get("office_procdocs_org", ""), "one head per area (unique index)")
check(len(sql("SELECT 1 FROM office_procdocs WHERE org_id=?", (ORG3,))) == 1, "one head left for the moved area")
A = sess("alice")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG3}"})
r = A.put(PD, json={"own": {"company": "Nach dem Umzug"}, "base": 2})
check(r.ok and r.json().get("version") == 3, f"a save after the move: version 3 {r.text[:200]}")

print(f"p2977_playbook_versions: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
