#!/usr/bin/env python3
"""1.5 (UX1) API tests (fresh DB on the TEST container :3048): lists are archived first, deleted for good only from the
archive. PATCH archived (with _prev for undo / redo and the conflict rule), DELETE refuses a list that is not archived
(409, nothing changes), the inbox never; the owner only; DELETE of an archived list removes the list, its sections,
sharing, custom fields and public link, and moves every task (open and done) to the trash of the owner's inbox, where
it can be restored; members of a shared list lose access. Plus the settings the app now saves one by one (every key
alone, the undo value back)."""
import os, sqlite3, sys
import requests

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1]
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what)


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok
    return s


def db():
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def q(sql, *a):
    with db() as c:
        return c.execute(sql, a).fetchall()


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bb = sess("bob")
A.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields"})
st = A.get(B + "/api/state").json()
INBOX = next(x["id"] for x in st["lists"] if x["is_inbox"])
L = A.post(B + "/api/lists", json={"name": "Office", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
FLD = A.post(B + f"/api/lists/{L}/fields", json={"name": "Budget", "type": "text"}).json()["id"]
SEC = A.post(B + "/api/sections", json={"list_id": L, "name": "Later"}).json()
SEC = SEC.get("id") or SEC.get("section", {}).get("id")
t_open = A.post(B + "/api/tasks", json={"title": "Open one", "list_id": L, "section_id": SEC}).json()["id"]
t_done = A.post(B + "/api/tasks", json={"title": "Done one", "list_id": L}).json()["id"]
A.patch(B + f"/api/tasks/{t_open}", json={"fields": {str(FLD): "100"}})
A.post(B + f"/api/tasks/{t_done}/complete")
if not q("SELECT 1 FROM tasks WHERE id=? AND status=2", t_done):
    A.post(B + "/api/tasks/batch", json={"ids": [t_done], "action": "complete", "data": {}})
pl = A.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"})
check(pl.ok and q("SELECT 1 FROM public_links WHERE list_id=?", L), f"setup: public link ({pl.status_code})")
check(q("SELECT status FROM tasks WHERE id=?", t_done)[0]["status"] == 2, "setup: a done task in the list")

# ================= not archived: DELETE refuses, nothing changes
r = A.delete(B + f"/api/lists/{L}")
check(r.status_code == 409 and "rchive" in r.json().get("error", ""), f"DELETE of a list that is not archived -> 409 ({r.status_code})")
check(q("SELECT 1 FROM lists WHERE id=?", L) and q("SELECT list_id FROM tasks WHERE id=?", t_open)[0]["list_id"] == L, "409: list and tasks unchanged")
check(A.delete(B + f"/api/lists/{INBOX}").status_code == 400, "the inbox can never be deleted")
check(Bb.delete(B + f"/api/lists/{L}").status_code in (403, 404), "a member cannot delete the list")

# ================= archive with _prev (undo / redo path) and the conflict rule
r = A.patch(B + f"/api/lists/{L}", json={"archived": 1, "_prev": {"archived": 0}}).json()
check(r.get("ok") and r.get("conflicts") == [] and q("SELECT archived FROM lists WHERE id=?", L)[0]["archived"] == 1, "archive with _prev")
check(Bb.patch(B + f"/api/lists/{L}", json={"archived": 0}).status_code == 403, "a member cannot archive / restore")
r = A.patch(B + f"/api/lists/{L}", json={"archived": 0, "_prev": {"archived": 1}}).json()
check(r.get("conflicts") == [] and q("SELECT archived FROM lists WHERE id=?", L)[0]["archived"] == 0, "undo of the archive: back (with _prev)")
A.patch(B + f"/api/lists/{L}", json={"archived": 1})
r = A.patch(B + f"/api/lists/{L}", json={"archived": 0, "_prev": {"archived": 0}}).json()
check([c["field"] for c in r.get("conflicts", [])] == ["archived"] and q("SELECT archived FROM lists WHERE id=?", L)[0]["archived"] == 1,
      "archived elsewhere meanwhile (_prev says 0): the undo of a restore is reported as a conflict, the list stays archived")
A.patch(B + f"/api/lists/{L}", json={"archived": 1})
st = A.get(B + "/api/state").json()
lj = next(x for x in st["lists"] if x["id"] == L)
check(lj["archived"] and any(t["id"] == t_open for t in st["tasks"]), "archived: list and tasks still in the state (restorable)")
check(any(x["id"] == L and x["archived"] for x in Bb.get(B + "/api/state").json()["lists"]), "member still sees the archived list")

# ================= delete for good from the archive
r = A.delete(B + f"/api/lists/{L}")
check(r.status_code == 200 and r.json().get("ok"), f"DELETE of an archived list -> ok ({r.status_code})")
check(not q("SELECT 1 FROM lists WHERE id=?", L), "list gone")
check(not q("SELECT 1 FROM sections WHERE list_id=?", L), "sections gone")
check(not q("SELECT 1 FROM list_members WHERE list_id=?", L), "sharing gone")
check(not q("SELECT 1 FROM list_fields WHERE list_id=?", L), "custom fields gone")
check(not q("SELECT 1 FROM public_links WHERE list_id=?", L), "public link gone")
rows = {x["id"]: dict(x) for x in q("SELECT id, list_id, deleted_at, section_id, status FROM tasks WHERE id IN (?, ?)", t_open, t_done)}
check(all(x["list_id"] == INBOX and x["deleted_at"] and x["section_id"] is None for x in rows.values()) and rows[t_done]["status"] == 2,
      "open and done tasks in the trash of the owner's inbox")
check(not any(x["id"] == L for x in Bb.get(B + "/api/state").json()["lists"]), "the member lost the list")
check(A.post(B + f"/api/tasks/{t_open}/restore").ok and q("SELECT deleted_at FROM tasks WHERE id=?", t_open)[0]["deleted_at"] is None, "a task restored from the trash")
check(A.delete(B + f"/api/lists/{L}").status_code == 404, "deleting again -> 404")

# ================= settings one by one (autosave) and back (undo)
for k, v in (("allday_time", "07:15"), ("digest_time", ""), ("push_priority", "5"), ("pomo_focus", "30"), ("time_target", "7.5"), ("hide_blocked_today", "1"), ("features", "cal,habits")):
    before = A.get(B + "/api/state").json()["settings"].get(k)
    ok1 = A.patch(B + "/api/settings", json={k: v}).ok and A.get(B + "/api/state").json()["settings"].get(k) == v
    ok2 = A.patch(B + "/api/settings", json={k: before}).ok and A.get(B + "/api/state").json()["settings"].get(k) == before
    check(ok1 and ok2, f"setting {k}: alone, and back")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
