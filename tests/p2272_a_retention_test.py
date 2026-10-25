#!/usr/bin/env python3
"""2.272.0 API tests, part A (#3026): one rule for the trash runs, own container (start.sh). Invented names only.
 - the floor: KALMIDO_TRASH_DAYS=0 never means "everything now" (ret_trash_days 1; a comment deleted just now stays)
 - the list trash (lists/listtrash.py otr_prune): switch off = nothing goes, the counts are reported (run "lists");
   switch on = the old list goes with its task and the attachment file on disk; a young one stays
 - the task trash (tasks/tasktrash.py ttp_tick): tasks of a project kept by law (lists.retain_until in the future) stay,
   also as the subtask of a due task in another list (detached), and are counted as tasks_kept
 - wiki: restoring a page brings its files back from the trash; the page run (wiki_trash_tick) and the files run (wka_tick)
   only count while the switch is off and delete the stored file with the switch on
 - GET /api/admin/retention lists the new runs
 - a person without an organisation (freelancer fixture): a private list in the trash follows the same rule
usage: p2272_a_retention_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402
OLD = "2020-01-01T00:00:00+00:00"
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")

if os.environ.get("P2272A_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
FEAT = "collab,comments,wiki"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
c = dbx.connect(DATA)


def box(code, on=False, env=()):
    """Python in the app container (a watchdog run called directly, force=True); on = KALMIDO_PURGE_TRASH=1. -> last line."""
    e = [x for k in ((["KALMIDO_PURGE_TRASH=1"] if on else []) + list(env)) for x in ("-e", k)]
    out = subprocess.run(["docker", "exec", *e, CT, "python", "-c", "import json, app\nc = app.connect()\ntry:\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "finally:\n    c.close()"],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"the run works {out.stdout[-200:]} {out.stderr[-800:]}")
    lines = out.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def exists(table, i):
    return bool(c.execute(f"SELECT 1 FROM {table} WHERE id=?", (i,)).fetchone())


def list_to_trash(s, lid):
    s.patch(B + f"/api/lists/{lid}", json={"archived": True})
    check(s.delete(B + f"/api/lists/{lid}").ok, f"setup: list {lid} into the trash")


def attach(s, tid):
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("note.txt", b"invented content", "text/plain")})
    check(r.ok, "setup: an attachment " + r.text[:120])
    p = (c.execute("SELECT path FROM attachments WHERE task_id=?", (tid,)).fetchone() or [""])[0]
    return os.path.join(DATA, "attachments", p) if p else ""


def runs(kind="trash"):
    r = A.get(B + "/api/admin/retention")
    return ((r.json().get("kinds") or {}).get(kind) or {}).get("runs") or {} if r.ok else {}


# ---------------------------------------------------------------- the floor of the trash period
check(box("from kalmido.core.retention import ret_trash_days\nprint(ret_trash_days())", env=("KALMIDO_TRASH_DAYS=0",)) == "1",
      "#3026: a trash period of 0 is 1 day")
T0 = task(A, None, "Comment holder")
check(A.post(B + f"/api/tasks/{T0}/comments", json={"body": "gone soon"}).ok, "setup: a comment")
CM = c.execute("SELECT id FROM comments WHERE task_id=?", (T0,)).fetchone()[0]
check(A.delete(B + f"/api/comments/{CM}").ok, "setup: the comment deleted (emptied row in the trash)")
box("from kalmido.files.trashpurge import tp_tick\nprint(tp_tick(c, True))", on=True, env=("KALMIDO_TRASH_DAYS=0",))
check(exists("comments", CM), "#3026: period 0 + switch on: the comment deleted just now stays (tp_tick)")

# ---------------------------------------------------------------- the list trash: switch off counts, on deletes
LO = A.post(B + "/api/lists", json={"name": "Old project", "org_id": None}).json()["id"]
TO = task(A, LO, "Task of the old project")
FO = attach(A, TO)
LY = A.post(B + "/api/lists", json={"name": "Young project", "org_id": None}).json()["id"]
list_to_trash(A, LO)
list_to_trash(A, LY)
c.execute("UPDATE lists SET deleted_at=? WHERE id=?", (OLD, LO))
c.execute("UPDATE tasks SET deleted_at=? WHERE list_id=? AND deleted_at IS NOT NULL", (OLD, LO))
box("from kalmido.lists.listtrash import otr_prune\nprint(otr_prune(c, True))")
check(exists("lists", LO) and exists("tasks", TO) and FO and os.path.isfile(FO), "#3026: switch off: the old list, its task and file stay")
last = runs().get("lists") or {}
check(last.get("purged") is False and (last.get("counts") or {}).get("lists") == 1 and (last.get("counts") or {}).get("tasks") == 1,
      f"#3026: switch off: the list run reports what it would delete {last}")
out = box("from kalmido.lists.listtrash import otr_prune\nprint(otr_prune(c, True))", on=True)
check(out == "1" and not exists("lists", LO) and not exists("tasks", TO), f"#3026: switch on: the old list goes with its task ({out})")
check(not os.path.exists(FO), "#3026: switch on: the attachment file is gone from disk")
check(exists("lists", LY), "#3026: the young list stays in the trash")
check((runs().get("lists") or {}).get("purged") is True, "#3026: the list run reports the purge")

# ---------------------------------------------------------------- tasks of a project kept by law
LK = A.post(B + "/api/lists", json={"name": "Kept project", "org_id": None}).json()["id"]
TK = task(A, LK, "Kept task")
FK = attach(A, TK)
LN = A.post(B + "/api/lists", json={"name": "Normal list", "org_id": None}).json()["id"]
PN = task(A, LN, "Parent in a normal list")
SK = task(A, LN, "Its subtask, moved into the kept project", parent_id=PN)
c.execute("UPDATE tasks SET list_id=? WHERE id=?", (LK, SK))
list_to_trash(A, LK)
check(A.delete(B + f"/api/tasks/{PN}").ok, "setup: the parent into the trash")
c.execute("UPDATE tasks SET deleted_at=? WHERE id IN (?, ?, ?)", (OLD, TK, SK, PN))
c.execute("UPDATE lists SET deleted_at=?, retain_until='2099-12-31' WHERE id=?", (OLD, LK))
n = json.loads(box("from kalmido.tasks.tasktrash import ttp_tick\nprint(json.dumps(ttp_tick(c, force=True)))") or "{}")
check(n.get("tasks_kept") == 2 and n.get("tasks") == 1, f"#3026: dry run: the kept tasks are counted apart {n}")
n = json.loads(box("from kalmido.tasks.tasktrash import ttp_tick\nprint(json.dumps(ttp_tick(c, force=True)))", on=True) or "{}")
check(not exists("tasks", PN), f"#3026: the due parent in the normal list goes {n}")
check(exists("tasks", TK) and FK and os.path.isfile(FK), "#3026: the task of the kept project stays with its file")
r = c.execute("SELECT parent_id, list_id FROM tasks WHERE id=?", (SK,)).fetchone()
check(r is not None and r["parent_id"] is None and r["list_id"] == LK, f"#3026: the kept subtask stays, detached {dict(r) if r else None}")
box("from kalmido.lists.listtrash import otr_prune\nprint(otr_prune(c, True))", on=True)
check(exists("lists", LK) and exists("tasks", TK), "#3026: the kept project waits for its end (list run)")
c.execute("UPDATE lists SET retain_until='2020-12-31' WHERE id=?", (LK,))
n = json.loads(box("from kalmido.tasks.tasktrash import ttp_tick\nprint(json.dumps(ttp_tick(c, force=True)))", on=True) or "{}")
check(not exists("tasks", TK) and not os.path.exists(FK), f"#3026: after its end the kept task goes with its file {n}")

# ---------------------------------------------------------------- wiki: restore brings the files back; the runs
def page(path):
    r = A.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": "Text of " + path})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def wfile(pid):
    r = A.post(B + f"/api/wiki/pages/{pid}/files", files={"file": ("plan.pdf", PDF, "application/pdf")})
    assert r.status_code == 201, r.text
    fid = r.json()["files"][0]["id"]
    return fid, os.path.join(DATA, "attachments", c.execute("SELECT path FROM wiki_files WHERE id=?", (fid,)).fetchone()[0])


WP = page("Restore/Plan")
WF, WFP = wfile(WP)
WF2, _ = wfile(WP)
check(A.delete(B + f"/api/wiki/files/{WF2}").ok, "setup: one file deleted on its own")
c.execute("UPDATE wiki_files SET deleted_at='2026-01-01T00:00:00.000+00:00' WHERE id=?", (WF2,))  # before the page
check(A.post(B + "/api/wiki/trash", json={"ids": [WP], "files": [WF]}).ok, "setup: page and file into the trash (like an import undo)")
check(A.post(B + "/api/wiki/restore", json={"ids": [WP]}).ok, "wiki: the page restored (only its id, like the trash view)")
check(c.execute("SELECT deleted_at FROM wiki_files WHERE id=?", (WF,)).fetchone()[0] is None, "#3026: its file is back too")
check(c.execute("SELECT deleted_at FROM wiki_files WHERE id=?", (WF2,)).fetchone()[0] is not None,
      "#3026: a file deleted on its own before stays in the trash")
# the files run: the lone trashed file (older than the period)
c.execute("UPDATE wiki_files SET deleted_at=? WHERE id=?", ("2020-01-01T00:00:00.000+00:00", WF2))
box("from kalmido.wiki.wikiatt import wka_tick\nwka_tick(c, force=True)\nprint('ok')")
check(exists("wiki_files", WF2) and ((runs().get("wiki_files") or {}).get("counts") or {}).get("files") == 1,
      f"#3026: switch off: the wiki file stays, counted {runs().get('wiki_files')}")
box("from kalmido.wiki.wikiatt import wka_tick\nwka_tick(c, force=True)\nprint('ok')", on=True)
check(not exists("wiki_files", WF2), "#3026: switch on: the wiki file goes")
# the page run
check(A.delete(B + f"/api/wiki/pages/{WP}").ok, "setup: the page into the trash again")
c.execute("UPDATE wiki_pages SET deleted_at='2020-01-01T00:00:00.000+00:00' WHERE id=?", (WP,))
n = json.loads(box("from kalmido.wiki.pages import wiki_trash_tick\nprint(json.dumps(wiki_trash_tick(c, True)))") or "{}")
check(n.get("pages") == 1 and exists("wiki_pages", WP) and os.path.isfile(WFP), f"#3026: switch off: the page stays, counted {n}")
check((runs().get("wiki") or {}).get("purged") is False, "#3026: the wiki run reports the dry run")
n = json.loads(box("from kalmido.wiki.pages import wiki_trash_tick\nprint(json.dumps(wiki_trash_tick(c, True)))", on=True) or "{}")
check(not exists("wiki_pages", WP) and not os.path.exists(WFP), f"#3026: switch on: the page goes with its stored file {n}")

# ---------------------------------------------------------------- the other runs report too (dry run)
box("from kalmido.sheets.shkinds import shk_tick\nshk_tick(c, force=True)\nfrom kalmido.office.contractfiles import dma_purge_tick\n"
    "dma_purge_tick(c)\nfrom kalmido.office.meals import bw_purge_tick\nbw_purge_tick(c)\nfrom kalmido.videos.review import vdr_trash_prune\n"
    "vdr_trash_prune(c)\nprint('ok')")
check({"lists", "tasks", "wiki", "wiki_files"} <= set(runs()), f"#3026: GET /api/admin/retention lists the runs {sorted(runs())}")

# ---------------------------------------------------------------- freelancer: a private list in the trash
FIDF, Fr = freelancer(B, A, features=FEAT)
FL = Fr.post(B + "/api/lists", json={"name": "Own project", "org_id": None}).json()["id"]
FT = task(Fr, FL, "Own task")
list_to_trash(Fr, FL)
c.execute("UPDATE lists SET deleted_at=? WHERE id=?", (OLD, FL))
c.execute("UPDATE tasks SET deleted_at=? WHERE list_id=? AND deleted_at IS NOT NULL", (OLD, FL))
box("from kalmido.lists.listtrash import otr_prune\nprint(otr_prune(c, True))")
check(exists("lists", FL) and exists("tasks", FT), "freelancer: switch off: the private list stays")
box("from kalmido.lists.listtrash import otr_prune\nprint(otr_prune(c, True))", on=True)
check(not exists("lists", FL) and not exists("tasks", FT), "freelancer: switch on: the private list goes")

# ---------------------------------------------------------------- 2.272.0 F (#3026, review M4): the runs inside a request
FL2 = Fr.post(B + "/api/lists", json={"name": "Hooks", "org_id": None}).json()["id"]
HK = c.execute("INSERT INTO hook_in(list_id, token_hash, created_at, deleted_at) VALUES(?,?,?,?) RETURNING id", (FL2, "p2272a-hook", OLD, OLD)).fetchone()[0]
ORGA = c.execute("SELECT id FROM orgs WHERE personal_of IS NULL ORDER BY id LIMIT 1").fetchone()[0]
SUP = c.execute("INSERT INTO office_suppliers(org_id, name, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?) RETURNING id",
                (ORGA, "Example Supplier", OLD, OLD, OLD)).fetchone()[0]
c.commit()
M4 = (f"from kalmido.core.pg import system_ctx\nfrom kalmido.integrations.hookin import whi_purge\nfrom kalmido.office.datevimp import _purge\n"
      f"with system_ctx(c):\n    whi_purge(c, {FL2})\n    _purge(c, {ORGA})\nc.commit()\nprint('ok')")
box(M4)
check(exists("hook_in", HK) and exists("office_suppliers", SUP), "#3026 M4: switch off: an old deleted webhook / supplier stays")
box(M4, on=True)
check(not exists("hook_in", HK) and not exists("office_suppliers", SUP), "#3026 M4: switch on: they go after the trash period")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
