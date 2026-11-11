#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.937.0 part B (#5244, stage 7c of the shared core, one-way): knowledge pages -- a person share is only the share of the
page's / folder's node (fs_shares) with its card in wiki_share_cards, wiki_shares holds public links only. Own container.
Invented names only. Both people are without an organisation (freelancer-matrix: wiki).
 - the dialog lists a page share and a folder share (+ its pair on the page of the folder's name) with the id p<share>;
   "Shared with me" shows the pages of both and their text opens
 - the folder renamed: the share follows (the folder's pages and the page of its name stay open)
 - revoke and Undo: the share comes back under the same id with its card (the switch "show pictures", the typed address)
 - a public link keeps working
 - the start (wiki/wkshare.py wsh_retire): an older database with core_id / core_id2, TEXT times and a BIGINT is_folder and a
   person row not moved yet -- the start check holds while the row finds no room on its node (nothing dropped, the row opens
   nothing, the log names it); the next start copies it forward, keeps its card (pictures), drops the person rows (also the
   one of a page in the trash, which gave nothing), the two columns, moves the types and raises the back limit
usage: p2937_b_kern_wiki_test.py <datadir>      (a fresh container; P2937B_NOSTART=1 = the server already runs)"""
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
from kt import B, DATA, check, sess, until  # noqa: E402

FEAT = "wiki,files,collab,comments"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
kt.fresh(prefix="P2937B", env={"KALMIDO_API_RATE": "100000"})
kt.docker_logs_on_first_fail()


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


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def _health():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


def restart():
    """The next start of the server (core/db.py init_db runs wiki/wkshare.py wsh_retire)."""
    subprocess.run(["docker", "restart", CT], capture_output=True)
    check(until(lambda: _health(), timeout=90), "the server is up again after the restart")


def in_app(code, *args):
    r = subprocess.run(["docker", "exec", "-i", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", code, *map(str, args)],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (r.stdout + r.stderr)[-600:]}


def page(s, path, text):
    r = s.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def shared(s):
    return {x["path"]: x["id"] for x in s.get(B + "/api/wiki/shared").json().get("pages", [])}


def text_of(s, pid):
    r = s.get(B + f"/api/wiki/shared/pages/{pid}")
    return r.json().get("body", "") if r.ok else None


def dialog(s):
    r = s.get(B + "/api/wiki/shares", params={"space": "private"})
    return r.json().get("shares", []) if r.ok else []


def cols():
    return {r[0]: r[1] for r in sql("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='wiki_shares'")}


A = kt.setup()
FID, Fr = freelancer(B, A, "frida", features=FEAT)
FIO, Fi = freelancer(B, A, "fiona", features=FEAT)

# ================================================================== the dialog on the core, "Shared with me"
WD = page(Fr, "Docs", "the index of the docs")
WI = page(Fr, "Docs/Intro", "the intro text")
WN = page(Fr, "Note", "a note for fiona")
r = Fr.post(B + "/api/wiki/shares", json={"space": "private", "folder": "Docs", "kind": "person", "email": "fiona@example.com", "images": True})
check(r.ok and r.json().get("by_email") is True, f"frida shares the folder Docs by address, pictures on {r.status_code} {r.text[:160]}")
r = Fr.post(B + "/api/wiki/shares", json={"page_id": WN, "kind": "person", "email": "fiona@example.com"})
check(r.ok, f"frida shares the page Note by address {r.status_code}")
sh = dialog(Fr)
fold = next((x for x in sh if x["folder"]), {})
note = next((x for x in sh if not x["folder"] and x["kind"] == "person"), {})
check(len(sh) == 2 and str(fold.get("id", "")).startswith("p") and str(note.get("id", "")).startswith("p"),
      f"the dialog lists both person shares with the id p<share> {sh}")
check(fold.get("path") == "Docs" and fold.get("images") is True and fold.get("user", {}).get("name") == "fiona@example.com"
      and note.get("path") == "Note" and note.get("images") is False, f"... path, pictures and the typed address from the card {fold} {note}")
check(not sql("SELECT 1 FROM wiki_shares WHERE kind<>'link'"), "wiki_shares holds no person row")
FOLD = int(str(fold.get("id", "p0"))[1:])
pair = sql("SELECT pair_id FROM wiki_share_cards WHERE fs_share_id=?", (FOLD,))
check(bool(pair and pair[0][0]) and sql("SELECT n.ref_id FROM fs_shares f JOIN fs_nodes n ON n.id=f.node_id WHERE f.id=?", (pair[0][0],)) == [(WD,)],
      f"the folder share's pair lies on the page of the folder's name {pair}")
got = shared(Fi)
check({WD, WI, WN} <= set(got.values()),
      f"Shared with me: the folder's pages and the page {sorted(got)}")
check(text_of(Fi, WI) == "the intro text" and text_of(Fi, WD) == "the index of the docs" and text_of(Fi, WN) == "a note for fiona",
      "... and their text opens")
check(any(f.get("name") == "Docs" for f in Fi.get(B + "/api/wiki/shared").json().get("folders", [])), "... the shared folder is listed")

# ================================================================== the folder renamed: the share follows (was core_id2)
r = Fr.post(B + "/api/wiki/move", json={"space": "private", "from": "Docs", "to": "Handbook"})
check(r.ok, f"frida renames the folder Docs to Handbook {r.text[:160]}")
check(text_of(Fi, WI) == "the intro text" and text_of(Fi, WD) == "the index of the docs",
      "the renamed folder's page and the page of its name stay open for fiona")
check(next((x["path"] for x in dialog(Fr) if x["id"] == fold.get("id")), None) == "Handbook", "the dialog shows the new name")

# ================================================================== revoke and Undo under the same id
r = Fr.delete(B + f"/api/wiki/shares/{fold.get('id')}")
check(r.ok and r.json().get("revoked") is True and text_of(Fi, WI) is None and text_of(Fi, WD) is None,
      f"revoked: fiona reads nothing of the folder at once {r.status_code}")
check(not sql("SELECT 1 FROM fs_shares WHERE id IN (?, ?)", (FOLD, pair[0][0] if pair else 0)), "... both core shares are gone (obj_revoked)")
r = Fr.post(B + f"/api/wiki/shares/{fold.get('id')}/restore")
check(r.ok and r.json().get("id") == fold.get("id") and r.json().get("images") is True and r.json().get("user", {}).get("name") == "fiona@example.com",
      f"Undo: back under the same id with its card {r.text[:200]}")
check(text_of(Fi, WI) == "the intro text" and text_of(Fi, WD) == "the index of the docs", "... fiona reads again (the pair too)")
check(Fr.delete(B + f"/api/wiki/shares/{fold.get('id')}").ok and Fr.post(B + f"/api/wiki/shares/{fold.get('id')}/restore").ok,
      "Redo and Undo again work on the same id")
check(Fr.patch(B + f"/api/wiki/shares/{note.get('id')}", json={"images": True}).ok
      and next((x["images"] for x in dialog(Fr) if x["id"] == note.get("id")), None) is True, "the switch of the page share goes on")
check(Fi.delete(B + f"/api/wiki/shares/{note.get('id')}").status_code == 404, "fiona cannot end frida's share")

# ================================================================== a public link keeps working
r = Fr.post(B + "/api/wiki/shares", json={"page_id": WN, "kind": "link"})
check(r.status_code == 201 and "/s/w/" in r.json().get("url", ""), f"frida makes a public link {r.text[:120]}")
LINK = "/s/w/" + r.json().get("url", "/s/w/x").split("/s/w/", 1)[1]
check(requests.get(B + LINK).ok and "a note for fiona" in requests.get(B + LINK).text, "the public link opens")

# ================================================================== Fable F2: the pair outlives its folder share's node
# 2.937.0 (#5244, Fable F2): the folder's node goes to the trash, the pair on the page of the folder's name still opens
# that page -- the knowledge dialog lists it (as a page share) and ends it
WP = page(Fr, "Proj", "the project index")
page(Fr, "Proj/Plan", "the plan")
r = Fr.post(B + "/api/wiki/shares", json={"space": "private", "folder": "Proj", "kind": "person", "email": "fiona@example.com"})
check(r.ok, f"F2 setup: frida shares the folder Proj {r.status_code}")
pj = next((x for x in dialog(Fr) if x["folder"] and x["path"] == "Proj"), {})
PJ = int(str(pj.get("id", "p0"))[1:])
pp = sql("SELECT pair_id FROM wiki_share_cards WHERE fs_share_id=?", (PJ,))
PP = pp[0][0] if pp and pp[0][0] else 0
sql("UPDATE fs_nodes SET deleted_at=now() WHERE id=(SELECT node_id FROM fs_shares WHERE id=?)", (PJ,), write=True)
check(PP and text_of(Fi, WP) == "the project index", "F2 setup: the folder's node in the trash, its pair still opens the page Proj")
lone = next((x for x in dialog(Fr) if x["id"] == f"p{PP}"), {})
check(lone.get("path") == "Proj" and lone.get("folder") is False and lone.get("kind") == "person",
      f"F2: the knowledge dialog lists the pair as a share of the page Proj {lone} {dialog(Fr)}")
check(Fr.delete(B + f"/api/wiki/shares/p{PP}").ok and text_of(Fi, WP) is None, "F2: ended in the knowledge dialog, fiona reads the page no more")
check(Fr.post(B + f"/api/wiki/shares/p{PP}/restore").ok and text_of(Fi, WP) == "the project index", "F2: its Undo brings it back")

# Fable F3 setup: greta shares a page with fiona (core share + card); below, her old row carries the card and she is disabled
GID, Gr = freelancer(B, A, "greta", features=FEAT)
WGR = page(Gr, "Greta note", "greta's note")
check(Gr.post(B + "/api/wiki/shares", json={"page_id": WGR, "kind": "person", "email": "fiona@example.com", "images": True}).ok,
      "F3 setup: greta shares a page with fiona (pictures on)")
GS = next((int(str(x["id"])[1:]) for x in dialog(Gr) if x["kind"] == "person"), 0)
# Fable F5 setup: frida's page Kept is shared with fiona, its core share has role edit and an expiry by now
WK = page(Fr, "Kept", "a kept page")
check(Fr.post(B + "/api/wiki/shares", json={"page_id": WK, "kind": "person", "email": "fiona@example.com"}).ok, "F5 setup: Kept shared with fiona")
KS = next((int(str(x["id"])[1:]) for x in dialog(Fr) if x["kind"] == "person" and x["path"] == "Kept"), 0)
sql("UPDATE fs_shares SET role='edit', expires_at='2030-01-01T00:00:00+00:00' WHERE id=?", (KS,), write=True)

# ================================================================== the start: an older database
check("core_id" not in cols() and cols().get("is_folder") == "boolean" and cols().get("created_at") == "timestamp with time zone",
      f"a new database: no core_id, real types {cols()}")
ISO = "to_char({0} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"')"
sql("ALTER TABLE wiki_shares ADD COLUMN core_id BIGINT, ADD COLUMN core_id2 BIGINT, "
    "ALTER COLUMN is_folder DROP DEFAULT, ALTER COLUMN is_folder TYPE BIGINT USING (CASE WHEN is_folder THEN 1 ELSE 0 END), "
    "ALTER COLUMN is_folder SET DEFAULT 0, "
    + ", ".join(f"ALTER COLUMN {x} TYPE TEXT USING {ISO.format(x)}" for x in ("created_at", "expires_at", "last_used_at", "revoked_at")),
    write=True)
check("core_id" in cols() and cols().get("is_folder") == "bigint", "setup: wiki_shares as before 2.937")
WL = page(Fr, "Legacy", "an old shared page")
WG = page(Fr, "Gone", "a page in the trash")
Fr.get(B + "/api/wiki", params={"space": "private"})  # the index: the tree has the nodes
check(Fr.delete(B + f"/api/wiki/pages/{WG}").ok, "setup: the page Gone in the trash")
TS = "2026-11-05T10:00:00+00:00"
for pid, path in ((WL, "Legacy"), (WG, "Gone")):
    sql("INSERT INTO wiki_shares(org_id,owner_id,path,is_folder,kind,user_id,token,created_by,created_at,page_id,images) "
        "VALUES(NULL,?,?,0,'person',?,'',?,?,?,1)", (FID, path, FIO, FID, TS, pid), write=True)
# Fable F3: greta's share as an older version kept it (the row with core_id, no card) and her account disabled at the start
sql("DELETE FROM wiki_share_cards WHERE fs_share_id=?", (GS,), write=True)
sql("INSERT INTO wiki_shares(org_id,owner_id,path,is_folder,kind,user_id,token,created_by,created_at,page_id,images,core_id) "
    "VALUES(NULL,?,'Greta note',0,'person',?,'',?,?,?,1,?)", (GID, FIO, GID, TS, WGR, GS), write=True)
sql("UPDATE users SET disabled=1 WHERE id=?", (GID,), write=True)
# Fable F5: an old row of Kept not moved yet (no core_id, no expiry) beside the core share fiona holds there
sql("INSERT INTO wiki_shares(org_id,owner_id,path,is_folder,kind,user_id,token,created_by,created_at,page_id,images) "
    "VALUES(NULL,?,'Kept',0,'person',?,'',?,?,?,0)", (FID, FIO, FID, TS, WK), write=True)
NL = sql("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (WL,))
NL = NL[0][0] if NL else 0
# the node is full (200 shares): the forward copy finds no room, the row counts as left
sql("INSERT INTO fs_shares(node_id,user_id,role,created_by,created_at) SELECT ?, ?, 'view', ?, ? FROM generate_series(1, 200)",
    (NL, FID, FID, TS), write=True)
restart()
Fr, Fi = sess("frida"), sess("fiona")
check("core_id" in cols() and sql("SELECT COUNT(*) FROM wiki_shares WHERE kind='person'")[0][0] == 4,  # + greta's row (Fable F3), Kept (F5)
      "start check: a row without room on its node -> nothing dropped, the person rows and the columns stay")
check("knowledge shares, stage 7c (#5244): 1 old row(s) of wiki_shares have no share in the shared core" in logs(), "start check: the log names it")
check(text_of(Fi, WL) is None, "start check: the old row opens nothing (no fallback reader)")
check(KS and sql("SELECT role, expires_at IS NOT NULL FROM fs_shares WHERE id=?", (KS,)) == [("edit", True)]
      and sql("SELECT COUNT(*) FROM fs_shares WHERE node_id=(SELECT node_id FROM fs_shares WHERE id=?) AND user_id=?", (KS, FIO))[0][0] == 1,
      "F5: the forward copy kept fiona's core share on Kept as it was (role edit, its expiry), no second one")
check(text_of(Fi, WI) == "the intro text", "start check: the shares on the core keep working")

sql("DELETE FROM fs_shares WHERE node_id=? AND user_id=?", (NL, FID), write=True)
restart()
Fr, Fi = sess("frida"), sess("fiona")
c = cols()
check("core_id" not in c and "core_id2" not in c, f"retire: core_id / core_id2 dropped {sorted(c)}")
check(c.get("is_folder") == "boolean" and all(c.get(x) == "timestamp with time zone" for x in ("created_at", "expires_at", "last_used_at", "revoked_at")),
      f"retire: real types (#5305) {c}")
check(not sql("SELECT 1 FROM wiki_shares WHERE kind<>'link'"), "retire: no person row left (the one of the page in the trash went too)")
check(text_of(Fi, WL) == "an old shared page", "retire: the old row was copied forward first, fiona reads the page")
leg = next((x for x in dialog(Fr) if x["path"] == "Legacy"), {})
check(leg.get("images") is True and str(leg.get("id", "")).startswith("p"), f"retire: its card kept the switch 'show pictures' {leg}")
check(text_of(Fi, WG) is None, "retire: the page in the trash is not shared")
check(GS and sql("SELECT images FROM wiki_share_cards WHERE fs_share_id=?", (GS,)) == [(True,)],
      "F3: the share of an owner disabled at the start kept its card (pictures on) while her old row went")
check(text_of(Fi, WI) == "the intro text" and text_of(Fi, WN) == "a note for fiona", "retire: the shares made on the core stay")
check(requests.get(B + LINK).ok, "retire: the public link still opens")
fl = dict(sql("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')"))
mine = in_app("import json; from kalmido.core.config import APP_VERSION; print(json.dumps(APP_VERSION))")
check(isinstance(mine, str) and fl.get("back_floor") == ".".join(mine.split(".")[:2] + ["0"]), f"retire: back_floor is the minor of this image {fl} {mine}")
check("knowledge shares, stage 7c (#5244): every old row of wiki_shares has its share in the shared core" in logs(), "retire: the log says so")
restart()
check("core_id" not in cols() and text_of(sess("fiona"), WL) == "an old shared page", "the next start is a no-op")

# ================================================================== Fable F1: a database from before core_id came (before 2.565)
# 2.937.0 (#5244, Fable F1): "done" is the target types, not the missing core_id / core_id2 -- the hook adds them back and runs
Fr = sess("frida")
WB = page(Fr, "Before", "a page from before the core")
Fr.get(B + "/api/wiki", params={"space": "private"})  # the index: the tree has the nodes
sql("ALTER TABLE wiki_shares ALTER COLUMN is_folder DROP DEFAULT, ALTER COLUMN is_folder TYPE BIGINT USING (CASE WHEN is_folder THEN 1 ELSE 0 END), "
    "ALTER COLUMN is_folder SET DEFAULT 0, "
    + ", ".join(f"ALTER COLUMN {x} TYPE TEXT USING {ISO.format(x)}" for x in ("created_at", "expires_at", "last_used_at", "revoked_at")),
    write=True)
sql("INSERT INTO wiki_shares(org_id,owner_id,path,is_folder,kind,user_id,token,created_by,created_at,page_id,images) "
    "VALUES(NULL,?,'Before',0,'person',?,'',?,?,?,0)", (FID, FIO, FID, TS, WB), write=True)
check("core_id" not in cols() and cols().get("created_at") == "text" and text_of(sess("fiona"), WB) is None,
      "F1 setup: wiki_shares as before 2.565 (no core_id / core_id2, TEXT times), a person row that gives nothing yet")
restart()
c = cols()
check("core_id" not in c and "core_id2" not in c and c.get("is_folder") == "boolean" and c.get("created_at") == "timestamp with time zone",
      f"F1: the start ran the whole stage on the old database (columns added back and dropped again, real types) {c}")
check(not sql("SELECT 1 FROM wiki_shares WHERE kind<>'link'") and text_of(sess("fiona"), WB) == "a page from before the core",
      "F1: the old row was copied forward first (fiona reads the page), no person row left")
check(requests.get(B + LINK).ok, "F1: the public link still opens")
check("wiki_shares: a database from before the shared core's columns core_id, core_id2 -- added back" in logs(), "F1: the log names the old database")

sys.exit(kt.done("p2937_b_kern_wiki"))
