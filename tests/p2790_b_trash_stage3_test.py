#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.809.0 (#5365): stage 3 of the core's trash -- file-store nodes (files/fskern.py, kind fs_entry), knowledge pages with
their files (wiki/wkkern.py, wiki_page, children wiki_files) and tables (sheets/shkern.py, sheet_table) go into the ONE trash
of the core (core/writes.py obj_trash / obj_restore / obj_purge, the retention run obj_trash_tick). Own container (kt.fresh).
Invented names and texts only.
 - per area: delete -> in the core's trash (deleted_at + deleted_by, the core's history 'trash') and in the area's trash view
   -> restore through the area's route (the content is there again) -> delete again -> deleted for good by hand (the
   area's purge route) -> another one dated back past the period: the core's run counts it (switch off) and deletes it with
   its stored file (switch on), one deleted today stays
 - a knowledge page's files go into the trash with it (the same time) and come back with it; a file deleted on its own before
   stays in the trash
 - a receipt kept by law (doc_meta.kept_until): deleting it for good 409, the core's run leaves it in the trash and counts it
   (fs_entry_locked)
 - rights as before: someone else gets 404 on restoring / deleting for good the person's page, table or file
 - 2.1093.0 (#5472): a folder of the knowledge tree / of the tables into the file store's trash puts its page (with its files)
   / table into the core's trash (deleted_by, the core's 'trash') and its restore brings them back ('restore'); the undo of
   an agent's new table lands in the core's trash; files deleted on their own (wiki_file, sheet_file) go with the core's run
freelancer-matrix: files, wiki, sheets (the flows run as a person without an organisation)
tenant-matrix: files, wiki, sheets (a person of an organisation cannot restore / purge the freelancer's objects)
usage: p2790_b_trash_stage3_test.py <datadir>"""
import json
import os
import subprocess
from datetime import timedelta, timezone

import kt
from kt import B, CT, DATA, check, sess
import testclock
from freelancer_fixture import FEATURES, freelancer

kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2790B")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})  # the areas on: a refusal is the rights, not a switch
FID, Fr = freelancer(B, A)
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def sql(q, args=()):
    return kt.dbx(q, args)


def one(q, args=()):
    r = sql(q, args)
    return r[0][0] if r else None


def old_iso():
    return (testclock.now() - timedelta(days=40)).astimezone(timezone.utc).isoformat(timespec="milliseconds")


def tick(on):
    """The core's retention run (forced), switch on / off -> its counts."""
    env = ["-e", "KALMIDO_RETENTION_PURGE=1"] if on else []
    out = subprocess.run(["docker", "exec", *env, CT, "python", "-c",
                          "import json, app\nfrom kalmido.core.db import connect\nfrom kalmido.core.writes import obj_trash_tick\n"
                          "c = connect()\nprint(json.dumps(obj_trash_tick(c, True)))\nc.close()"], capture_output=True, text=True)
    check(out.returncode == 0 and "Traceback" not in out.stderr, "the core's run ran " + (out.stdout + out.stderr)[-600:])
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def stored(rel):
    return bool(rel) and os.path.isfile(os.path.join(DATA, "attachments", rel))


def trashed(table, rid):
    """(deleted_at set, deleted_by) of the row, None when it is gone."""
    r = sql(f"SELECT deleted_at, deleted_by FROM {table} WHERE id=?", (rid,))
    return (bool(r[0][0]), r[0][1]) if r else None


def core_note(kind, rid, action):
    return bool(sql("SELECT 1 FROM obj_history WHERE kind=? AND ref_id=? AND action=?", (kind, rid, action)))


# ================================================================== the file store
def upload(name, body=b"invented text\n" * 20):
    r = Fr.post(B + "/api/files/upload", data={"space": "private"}, files={"file": (name, body, "text/plain")})
    check(r.status_code == 201, f"setup: upload {name} {r.text[:160]}")
    return one("SELECT id FROM fs_nodes WHERE owner_id=? AND name=? ORDER BY id DESC LIMIT 1", (FID, name))


F1 = upload("plan-a.txt", b"Invented plan A\n")
P1 = one("SELECT path FROM fs_versions WHERE node_id=?", (F1,))
check(Fr.delete(B + f"/api/files/nodes/{F1}").ok, "files: into the trash")
check(trashed("fs_nodes", F1) == (True, FID) and core_note("fs_entry", F1, "trash"), f"files: in the core's trash {trashed('fs_nodes', F1)}")
j = Fr.get(B + "/api/files", params={"space": "trash"}).json()
check(F1 in [x["id"] for x in j.get("items") or []], "files: the trash view lists it")
check(A.post(B + f"/api/files/nodes/{F1}/restore").status_code == 404, "files: someone else cannot restore it (404)")
check(A.delete(B + f"/api/files/nodes/{F1}", params={"purge": "1"}).status_code == 404, "files: someone else cannot delete it for good (404)")
check(Fr.post(B + f"/api/files/nodes/{F1}/restore").ok and trashed("fs_nodes", F1) == (False, None), "files: restored")
r = Fr.get(B + f"/api/files/nodes/{F1}/content")
check(r.ok and b"Invented plan A" in r.content, f"files: the content is there again {r.status_code}")
check(Fr.delete(B + f"/api/files/nodes/{F1}").ok, "files: into the trash again")
check(Fr.delete(B + f"/api/files/nodes/{F1}", params={"purge": "1"}).ok and trashed("fs_nodes", F1) is None and not stored(P1),
      "files: deleted for good by hand, the stored file gone from the disk")
# the period: an old one goes (switch on), a young one stays
F2, F3 = upload("old-b.txt"), upload("young-c.txt")
P2 = one("SELECT path FROM fs_versions WHERE node_id=?", (F2,))
check(Fr.post(B + "/api/files/trash", json={"ids": [F2, F3]}).ok, "files: two into the trash at once")
check(trashed("fs_nodes", F2) == (True, FID) and trashed("fs_nodes", F3) == (True, FID), "files: both in the core's trash")
sql("UPDATE fs_nodes SET deleted_at=? WHERE id=?", (old_iso(), F2))

# a receipt kept by law
r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("beleg.pdf", PDF, "application/pdf")})
check(r.status_code == 201, f"setup: a document {r.text[:160]}")
R1 = (r.json().get("ids") or [0])[0] if r.ok else 0
kt.until(lambda: sql("SELECT 1 FROM doc_meta WHERE node_id=?", (R1,)) and not sql("SELECT 1 FROM doc_meta WHERE node_id=? AND state='run'", (R1,)), 30)
sql("UPDATE doc_meta SET kept_until=? WHERE node_id=?", ((testclock.today() + timedelta(days=3000)).isoformat(), R1))
check(Fr.delete(B + f"/api/files/nodes/{R1}").ok, "receipt: into the trash (allowed)")
sql("UPDATE fs_nodes SET deleted_at=? WHERE id=?", (old_iso(), R1))
r = Fr.delete(B + f"/api/files/nodes/{R1}", params={"purge": "1"})
check(r.status_code == 409 and "Kept by law until" in r.text and trashed("fs_nodes", R1), f"receipt: deleting it for good 409 {r.status_code} {r.text[:160]}")

# ================================================================== knowledge pages
def page(path, text):
    r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": text})
    check(r.status_code == 201, f"setup: page {path} {r.text[:160]}")
    return r.json()["id"]


def wfile(pid, name):
    r = Fr.post(B + f"/api/wiki/pages/{pid}/files", files={"file": (name, PDF, "application/pdf")})
    check(r.status_code == 201, f"setup: a file of the page {r.text[:160]}")
    fid = r.json()["files"][0]["id"]
    return fid, one("SELECT path FROM wiki_files WHERE id=?", (fid,))


W1 = page("Stage3/Plan", "Invented plan text")
WF1, WP1 = wfile(W1, "plan.pdf")
WF2, _ = wfile(W1, "draft.pdf")
check(Fr.delete(B + f"/api/wiki/files/{WF2}").ok, "wiki: (setup) one file deleted on its own")
sql("UPDATE wiki_files SET deleted_at='2026-01-01T00:00:00.000+00:00' WHERE id=?", (WF2,))
check(Fr.delete(B + f"/api/wiki/pages/{W1}").ok, "wiki: the page into the trash")
t = sql("SELECT p.deleted_at, f.deleted_at, p.deleted_by FROM wiki_pages p JOIN wiki_files f ON f.page_id=p.id WHERE p.id=? AND f.id=?", (W1, WF1))
check(t and t[0][0] and t[0][0] == t[0][1] and t[0][2] == FID and core_note("wiki_page", W1, "trash"),
      f"wiki: page and its file in the core's trash with the same time {t}")
tl = Fr.get(B + "/api/wiki/trash", params={"space": "private"}).json()
check(W1 in [p["id"] for p in tl.get("pages") or []], "wiki: the trash view lists the page")
check(A.post(B + "/api/wiki/restore", json={"ids": [W1]}).json().get("skipped") == [W1], "wiki: someone else cannot restore it")
r = A.post(B + "/api/wiki/purge", json={"space": "private", "ids": [W1]})
check(trashed("wiki_pages", W1) is not None, f"wiki: someone else cannot delete it for good {r.status_code}")
r = Fr.post(B + "/api/wiki/restore", json={"ids": [W1]})
check(r.ok and r.json().get("ids") == [W1] and trashed("wiki_pages", W1) == (False, None), f"wiki: restored {r.text[:160]}")
check(one("SELECT deleted_at FROM wiki_files WHERE id=?", (WF1,)) is None, "wiki: its file came back with it")
check(one("SELECT deleted_at FROM wiki_files WHERE id=?", (WF2,)) is not None, "wiki: the file deleted on its own before stays in the trash")
r = Fr.get(B + f"/api/wiki/pages/{W1}")
check(r.ok and "Invented plan text" in r.text, f"wiki: the text is there again {r.status_code}")
# review 2.809.0 (#5365): a page trashed before 2.809 by an import's undo - its files carry a time a moment AFTER the page's
# (the old wiki_bulk); the old rule brought them back (">="), so the core's restore does too
W4 = page("Stage3/Before", "Invented import text")
WF4, _ = wfile(W4, "import.pdf")
check(Fr.delete(B + f"/api/wiki/pages/{W4}").ok, "wiki (old trash): the page into the trash")
sql("UPDATE wiki_pages SET deleted_at='2026-11-05T10:00:00.000+00:00' WHERE id=?", (W4,))
sql("UPDATE wiki_files SET deleted_at='2026-11-05T10:00:00.004+00:00' WHERE id=?", (WF4,))
r = Fr.post(B + "/api/wiki/restore", json={"ids": [W4]})
check(r.ok and trashed("wiki_pages", W4) == (False, None), f"wiki (old trash): restored {r.text[:160]}")
check(one("SELECT deleted_at FROM wiki_files WHERE id=?", (WF4,)) is None, "wiki (old trash): its file stamped a moment later came back with it")
check(Fr.delete(B + f"/api/wiki/pages/{W1}").ok, "wiki: into the trash again")
r = Fr.post(B + "/api/wiki/purge", json={"space": "private", "ids": [W1]})
check(r.ok and r.json().get("ids") == [W1] and trashed("wiki_pages", W1) is None and not stored(WP1)
      and not sql("SELECT 1 FROM wiki_files WHERE page_id=?", (W1,)), f"wiki: deleted for good by hand with its files {r.text[:160]}")
W2 = page("Stage3/Old", "Old text")
_, WP2 = wfile(W2, "old.pdf")
W3 = page("Stage3/Young", "Young text")
for w in (W2, W3):
    check(Fr.delete(B + f"/api/wiki/pages/{w}").ok, f"wiki: page {w} into the trash")
sql("UPDATE wiki_pages SET deleted_at=? WHERE id=?", (old_iso(), W2))

# ================================================================== tables
def table(title, text):
    r = Fr.post(B + "/api/sheets", json={"title": title, "space": "private"})
    check(r.status_code == 201, f"setup: table {title} {r.text[:160]}")
    sid = r.json()["id"]
    check(Fr.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"cell": "A1", "raw": text}]}).ok, "setup: a cell")
    return sid


S1 = table("Stage3 budget", "Invented cell text")
check(Fr.delete(B + f"/api/sheets/{S1}").ok, "tables: into the trash")
check(trashed("sheets", S1) == (True, FID) and core_note("sheet_table", S1, "trash"), f"tables: in the core's trash {trashed('sheets', S1)}")
tl = Fr.get(B + "/api/sheets/trash", params={"space": "private"}).json()
check(S1 in [x["id"] for x in tl.get("sheets") or []], "tables: the trash view lists it")
r = A.post(B + f"/api/sheets/{S1}/restore")
check(r.status_code in (403, 404) and trashed("sheets", S1) == (True, FID), f"tables: someone else cannot restore it {r.status_code} {r.text[:160]}")
A.post(B + "/api/sheets/purge", json={"space": "private", "ids": [S1]})
check(trashed("sheets", S1) is not None, "tables: someone else cannot delete it for good")
check(Fr.post(B + f"/api/sheets/{S1}/restore").ok and trashed("sheets", S1) == (False, None), "tables: restored")
r = Fr.get(B + f"/api/sheets/{S1}")
check(r.ok and "Invented cell text" in r.text, f"tables: the cell is there again {r.status_code}")
check(Fr.delete(B + f"/api/sheets/{S1}").ok, "tables: into the trash again")
r = Fr.post(B + "/api/sheets/purge", json={"space": "private", "ids": [S1]})
check(r.ok and r.json().get("ids") == [S1] and trashed("sheets", S1) is None, f"tables: deleted for good by hand {r.text[:160]}")
# 2.809.0 (#5365, review): a further sheet's own trash / restore writes core rows (kind sheet_table, ref = the sheet); the
# table's delete for good takes them along, not only the rows of its first sheet
S4 = table("Stage3 tabs", "z")
r = Fr.post(B + f"/api/sheets/{S4}/tabs", json={"name": "Second"})
check(r.status_code == 201, f"tables: a further sheet {r.text[:160]}")
T4 = r.json()["tab"]["id"]
check(Fr.delete(B + f"/api/sheets/{S4}/tabs/{T4}").ok and Fr.post(B + f"/api/sheets/{S4}/tabs/{T4}/restore").ok,
      "tables: the further sheet into the trash and back")
check(one("SELECT count(*) FROM obj_history WHERE kind='sheet_table' AND ref_id=?", (T4,)), "setup: the further sheet has core history")
check(Fr.delete(B + f"/api/sheets/{S4}").ok, "tables: the table with its further sheet into the trash")
r = Fr.post(B + "/api/sheets/purge", json={"space": "private", "ids": [S4]})
check(r.ok and trashed("sheets", S4) is None, f"tables: the table with a further sheet deleted for good {r.text[:160]}")
left = [one(f"SELECT count(*) FROM {t} WHERE kind='sheet_table' AND ref_id=?", (T4,)) for t in ("obj_history", "obj_undo")]
check(left == [0, 0], f"tables: no core rows of the further sheet stay behind {left}")
S2, S3 = table("Stage3 old", "x"), table("Stage3 young", "y")
for s in (S2, S3):
    check(Fr.delete(B + f"/api/sheets/{s}").ok, f"tables: {s} into the trash")
sql("UPDATE sheets SET deleted_at=? WHERE id=?", (old_iso(), S2))

# ================================================================== 2.1093.0 (#5472): the rest of stage 3
# a folder of the knowledge tree into the file store's trash: its page goes into the core's trash with its files (children,
# the same time), noted by the core ('trash'); the folder's restore brings both back ('restore')
W6 = page("Stage3Dir/Inside", "Invented folder page")
WF6, _ = wfile(W6, "inside.pdf")
WD = one("SELECT parent_id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (W6,))
check(WD and Fr.delete(B + f"/api/files/nodes/{WD}").ok, "folder (wiki): into the file store's trash")
t = sql("SELECT p.deleted_at, f.deleted_at, p.deleted_by FROM wiki_pages p JOIN wiki_files f ON f.page_id=p.id WHERE p.id=? AND f.id=?", (W6, WF6))
check(t and t[0][0] and t[0][0] == t[0][1] and t[0][2] == FID and core_note("wiki_page", W6, "trash"),
      f"folder (wiki): the page in the core's trash with its file, the same time, who deleted it {t}")
check(Fr.post(B + f"/api/files/nodes/{WD}/restore").ok, "folder (wiki): restored")
check(trashed("wiki_pages", W6) == (False, None) and one("SELECT deleted_at FROM wiki_files WHERE id=?", (WF6,)) is None
      and core_note("wiki_page", W6, "restore"), f"folder (wiki): the page and its file came back {trashed('wiki_pages', W6)}")
r = Fr.get(B + f"/api/wiki/pages/{W6}")
check(r.ok and "Invented folder page" in r.text, f"folder (wiki): the page reads again {r.status_code}")
# the same for a table filed in a folder of the tables
r = Fr.post(B + "/api/sheets/folders", json={"name": "Stage3 folder", "space": "private"})
check(r.ok, f"setup: a folder of the tables {r.text[:160]}")
SD = r.json()["folder"]["id"]
r = Fr.post(B + "/api/sheets", json={"title": "Stage3 filed", "space": "private", "folder_id": SD})
check(r.status_code == 201, f"setup: a table in the folder {r.text[:160]}")
S6 = r.json()["id"]
check(Fr.delete(B + f"/api/files/nodes/{SD}").ok, "folder (tables): into the file store's trash")
check(trashed("sheets", S6) == (True, FID) and core_note("sheet_table", S6, "trash"),
      f"folder (tables): the table in the core's trash, who deleted it, noted {trashed('sheets', S6)}")
check(Fr.post(B + f"/api/files/nodes/{SD}/restore").ok and trashed("sheets", S6) == (False, None)
      and core_note("sheet_table", S6, "restore"), f"folder (tables): the table came back {trashed('sheets', S6)}")
# an agent's new table taken back (the batch's undo): into the core's trash (deleted_by, the core's 'trash'), not by hand
r = Fr.post(B + "/api/sheets", json={"title": "Stage3 agent made", "space": "private"})
S7 = r.json()["id"] if r.status_code == 201 else 0
sql("INSERT INTO sheet_changes(sheet_id, batch, agent_id, kind, created_at) VALUES(?, 'agt5472', NULL, 'create', ?)",
    (S7, testclock.now().astimezone(timezone.utc).isoformat(timespec="milliseconds")))
r = Fr.post(B + f"/api/sheets/{S7}/batches/agt5472/undo")
check(r.ok and r.json().get("undone") == 1, f"undo of a new table: taken back {r.status_code} {r.text[:160]}")
check(trashed("sheets", S7) == (True, FID) and core_note("sheet_table", S7, "trash"),
      f"undo of a new table: in the core's trash with the core's note {trashed('sheets', S7)}")
tl = Fr.get(B + "/api/sheets/trash", params={"space": "private"}).json()
check(S7 in [x["id"] for x in tl.get("sheets") or []], "undo of a new table: the tables' trash lists it")
check(Fr.post(B + f"/api/sheets/{S7}/restore").ok and trashed("sheets", S7) == (False, None), "undo of a new table: restorable")
# the files deleted on their own (the runs wka_tick / shk_tick went): the core's run takes them (part kinds wiki_file /
# sheet_file), a file of a live page / table past the period; one of today stays
WF7, WP7 = wfile(W6, "lone-old.pdf")
WF8, WP8 = wfile(W6, "lone-young.pdf")
for f in (WF7, WF8):
    check(Fr.delete(B + f"/api/wiki/files/{f}").ok, f"wiki file {f}: deleted on its own")
sql("UPDATE wiki_files SET deleted_at=? WHERE id=?", (old_iso(), WF7))
S8 = table("Stage3 files", "f")
sh = Fr.get(B + f"/api/sheets/{S8}").json()
rows8 = [x["id"] for x in sh.get("rows") or []]
r = Fr.post(B + f"/api/sheets/{S8}/columns", json={"title": "Doc", "kind": "file"})
check(r.status_code == 201 and rows8, f"setup: a file column {r.text[:160]}")
col8 = r.json()["column"]["id"]
r = Fr.post(B + f"/api/sheets/{S8}/files", data={"row_id": str(rows8[0]), "col_id": str(col8)},
            files={"file": ("cell.pdf", PDF, "application/pdf")})
check(r.status_code == 201, f"setup: a file in a cell {r.text[:160]}")
SF8 = r.json()["file"]["id"]
SP8 = one("SELECT path FROM sheet_files WHERE id=?", (SF8,))
check(Fr.put(B + f"/api/sheets/{S8}/cells", json={"cells": [{"row_id": rows8[0], "col_id": col8, "raw": ""}]}).ok,
      "table file: the cell emptied (its file into the trash)")
check(one("SELECT deleted_at FROM sheet_files WHERE id=?", (SF8,)) is not None, "table file: in the trash")
sql("UPDATE sheet_files SET deleted_at=? WHERE id=?", (old_iso(), SF8))

# ================================================================== the core's retention run over the three areas
n = tick(False)
check(n.get("fs_entry") == 2 and n.get("wiki_page") == 1 and n.get("sheet_table") == 1,
      f"switch off: counted (the old file + the receipt, the old page, the old table) {n}")
check(n.get("wiki_file") == 1 and n.get("sheet_file") == 1 and stored(WP7) and stored(SP8),
      f"switch off (#5472): the old wiki file and table file counted, not deleted {n}")
check(trashed("fs_nodes", F2) and trashed("wiki_pages", W2) and trashed("sheets", S2) and stored(P2) and stored(WP2), "switch off: nothing deleted")
n = tick(True)
check(n.get("fs_entry_locked") == 1, f"switch on: the receipt kept by law is counted as locked {n}")
check(n.get("fs_entry") == 1, f"switch on: only the old file counts as deleted, not the locked receipt (review) {n}")
check(trashed("fs_nodes", F2) is None and not stored(P2), "switch on: the old file and its stored file gone")
check(trashed("fs_nodes", R1) == (True, FID), "switch on: the receipt kept by law stays in the trash")
check(trashed("wiki_pages", W2) is None and not stored(WP2), "switch on: the old page and its stored file gone")
check(trashed("sheets", S2) is None, "switch on: the old table gone")
check(trashed("fs_nodes", F3) and trashed("wiki_pages", W3) and trashed("sheets", S3), "switch on: the ones deleted today stay")
check(n.get("wiki_file") == 1 and n.get("sheet_file") == 1, f"switch on (#5472): the old wiki file and table file counted {n}")
check(not sql("SELECT 1 FROM wiki_files WHERE id=?", (WF7,)) and not stored(WP7), "switch on (#5472): the old wiki file gone with its stored file")
check(not sql("SELECT 1 FROM sheet_files WHERE id=?", (SF8,)) and not stored(SP8), "switch on (#5472): the old table file gone with its stored file")
check(sql("SELECT 1 FROM wiki_files WHERE id=?", (WF8,)) and stored(WP8), "switch on (#5472): the wiki file deleted today stays")
# 2.809.0 (#5365, review): one batch per kind and run (one advisory lock each), the rest in the next run
# 2.1112.2 (#5992): the cut is a point in time - deleted_at is TIMESTAMPTZ since #5306, the text '9999' is none (the app passes ret_trash_cut)
out = subprocess.run(["docker", "exec", CT, "python", "-c",
                      "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core import writes\n"
                      "c = connect()\nprint(writes.OBJ_PRUNE_BATCH, len(writes.obj_trash_due(c, 'fs_entry', '9999-12-31T00:00:00Z', limit=1)))\nc.close()"],
                     capture_output=True, text=True)
check(out.stdout.split()[:2] == ["500", "1"], f"the run takes a batch, not everything at once {(out.stdout + out.stderr)[-300:]}")
last = sql("SELECT value FROM settings WHERE key='ret_last_trash.obj_trash'")
check(last and json.loads(last[0][0]).get("purged") is True, f"the run reports for the retention page {last}")

raise SystemExit(kt.done("p2790_b_trash_stage3"))
