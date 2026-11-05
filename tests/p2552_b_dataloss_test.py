#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.552.0 B (#4561, rest of #4318, audit #2425): the last small data loss spots of the office, the fields and the knowledge
base. Own container (start.sh through kt.fresh, mode workspaces). Invented names only (example.com); the person without an
organisation (tests/freelancer_fixture.py) does every step that exists for her.
freelancer-matrix: office, wiki, tasks
 - B21: a deleted credit card position goes into the office trash first (label without the sealed merchant / amount); the
   undo route and the office trash bring it back with its id; another office 404; a confirmed statement takes none back (409)
 - B19: a draft in the office trash whose client was deleted for good since comes back without the client, the answer says so
 - B12: a task moved to another project keeps its value at the old field: the field's delete count (moved) and the project's
   purge-info (moved_values) name it, both delete dialogs say it
 - B28: renaming a knowledge folder (POST /api/wiki/move and the tree's rename) takes its pages in the trash along; a page
   whose name was taken meanwhile comes back as "Name (2)" (renamed in the answer), not skipped
usage: p2552_b_dataloss_test.py <datadir>      (KMT_NOSTART=1: a running server)"""
import os
import sys
from datetime import date

import dbx as dbxm
import kt
from kt import B, DATA, check, done
from freelancer_fixture import freelancer

O = "/api/office"
K = O + "/cards"
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def kt_src(rel):
    with open(os.path.join(SRC, rel), encoding="utf-8") as f:
        return f.read()


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # noqa: BLE001 - an UPDATE without rows to read
            return []
    finally:
        c.close()


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2552B")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, Fr = freelancer(B, A)
D = date.today().isoformat()

# ================================================================== B21 credit card positions: into the office trash first
card = Fr.post(B + K, json={"holder_id": FID, "last4": "4321"})
check(card.ok, f"B21: freelancer card {card.status_code} {card.text[:160]}")
st = Fr.post(B + f"{K}/{card.json()['id']}/statements", files={"file": ("stmt.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}, data={"month": D[:7]})
check(st.ok, f"B21: a statement {st.status_code} {st.text[:160]}")
SID = st.json()["statement"]["id"]
keep = Fr.post(B + f"{K}/statements/{SID}/lines", json={"day": D, "merchant": "Objektivverleih Beispiel", "amount": "10.00"}).json()["line"]
LID = Fr.post(B + f"{K}/statements/{SID}/lines", json={"day": D, "merchant": "Tippfehler Beispiel", "amount": "2.50"}).json()["line"]["id"]


def del_line():
    r = Fr.delete(B + f"{K}/lines/{LID}")
    check(r.ok, f"B21: the position goes {r.status_code} {r.text[:160]}")
    return r.json().get("trash_id")


TID = del_line()
check(bool(TID), "B21: the answer of the delete names the office trash copy (trash_id)")
row = sql("SELECT kind, label FROM office_trash WHERE id=?", (TID or 0,))
check(row and row[0][0] == "cc_line", f"B21: the copy is in the office trash as kind cc_line: {row}")
check(row and "Tippfehler" not in row[0][1] and "2.50" not in row[0][1], f"B21: the label carries no sealed merchant / amount: {row}")
check(A.post(B + f"{K}/trash/{TID}/restore").status_code == 404, "B21: another office cannot restore the copy (404)")
r = Fr.post(B + f"{K}/trash/{TID}/restore")
check(r.ok and r.json()["line"]["id"] == LID and r.json()["line"]["merchant"] == "Tippfehler Beispiel" and r.json()["line"]["amount"] == "2.50",
      f"B21: the undo brings the position back with its id and values {r.status_code} {r.text[:200]}")
check(not sql("SELECT 1 FROM office_trash WHERE id=?", (TID,)), "B21: the copy left the trash")
lines = Fr.get(B + f"{K}/statements/{SID}").json()["lines"]
check(sorted(x["id"] for x in lines) == sorted([keep["id"], LID]), f"B21: the statement shows both positions again: {[x['id'] for x in lines]}")

TID = del_line()
items = Fr.get(B + O + "/trash").json()["items"]
check(any(x["id"] == TID and x["kind"] == "cc_line" for x in items), "B21: the office trash lists the position")
r = Fr.post(B + O + f"/trash/{TID}/restore")
check(r.ok and r.json().get("kind") == "cc_line" and sql("SELECT 1 FROM office_cc_lines WHERE id=?", (LID,)), f"B21: the office trash restores it {r.status_code} {r.text[:160]}")

TID = del_line()
check(Fr.patch(B + f"{K}/statements/{SID}", json={"total": "10.00"}).ok and Fr.post(B + f"{K}/statements/{SID}/confirm", json={}).ok, "B21: statement confirmed")
r = Fr.post(B + f"{K}/trash/{TID}/restore")
check(r.status_code == 409 and not sql("SELECT 1 FROM office_cc_lines WHERE id=?", (LID,)), f"B21: a confirmed statement takes no position back (409) {r.status_code}")
check(Fr.post(B + O + f"/trash/{TID}/restore").status_code == 409, "B21: the office trash refuses it as well (409)")
check(sql("SELECT 1 FROM office_trash WHERE id=?", (TID,)), "B21: the copy stays in the trash after the refusal")

# ================================================================== B19 a draft whose client is gone for good comes back without it
CID = Fr.post(B + "/api/clients", json={"name": "Weggangskunde GmbH", "email": "weg@example.com"}).json()["id"]
r = Fr.post(B + O + "/docs", json={"project_title": "Fruehling Beispiel", "client_id": CID})
check(r.status_code == 201, f"B19: a draft with a client {r.status_code} {r.text[:160]}")
DID = r.json()["id"]
check(sql("SELECT client_id FROM office_docs WHERE id=?", (DID,))[0][0] == CID, "B19: the draft names the client")
r = Fr.delete(B + O + f"/docs/{DID}")
TID = r.json().get("trash_id") if r.ok else None
check(bool(TID), f"B19: the draft is in the office trash {r.status_code} {r.text[:160]}")
check(Fr.delete(B + f"/api/clients/{CID}").ok, "B19: the client goes to the trash")
r = Fr.delete(B + f"/api/clients/{CID}/purge")
check(r.ok and not sql("SELECT 1 FROM clients WHERE id=?", (CID,)), f"B19: the client is deleted for good {r.status_code} {r.text[:160]}")
r = Fr.post(B + O + f"/trash/{TID}/restore")
j = r.json() if r.ok else {}
check(r.ok and j.get("id") == DID, f"B19: the draft comes back (was 409) {r.status_code} {r.text[:200]}")
check("client_id" in (j.get("gone") or []) and "without a client" in (j.get("note") or ""), f"B19: the answer says it came back without the client: {j}")
row = sql("SELECT client_id, project_title FROM office_docs WHERE id=?", (DID,))
check(row and row[0][0] is None, f"B19: the draft has no client now: {row}")
check(Fr.get(B + O + f"/docs/{DID}").ok, "B19: the draft opens")
check(not sql("SELECT 1 FROM office_trash WHERE id=?", (TID,)), "B19: the copy left the trash")

# ================================================================== B12 values of moved tasks: the delete dialogs name them
Fr.patch(B + "/api/settings", json={"set_delta": {"features": {"add": ["fields"]}}})
L1 = Fr.post(B + "/api/lists", json={"name": "Altprojekt Beispiel", "kind": "project"}).json()["id"]
L2 = Fr.post(B + "/api/lists", json={"name": "Neuprojekt Beispiel", "kind": "project"}).json()["id"]
r = Fr.post(B + f"/api/lists/{L1}/fields", json={"name": "Budget", "type": "number"})
check(r.ok, f"B12: a field {r.status_code} {r.text[:160]}")
FD = r.json()["id"]
T1 = Fr.post(B + "/api/tasks", json={"title": "Bleibt hier", "list_id": L1}).json()["id"]
T2 = Fr.post(B + "/api/tasks", json={"title": "Zieht um", "list_id": L1}).json()["id"]
for t in (T1, T2):
    check(Fr.patch(B + f"/api/tasks/{t}", json={"fields": {str(FD): 120}}).ok, "B12: a value")
j = Fr.get(B + f"/api/fields/{FD}/count").json()
check(j.get("tasks") == 2 and j.get("moved") == 0, f"B12: nothing moved yet {j}")
check(Fr.patch(B + f"/api/tasks/{T2}", json={"list_id": L2}).ok, "B12: one task moves to the other project")
check(sql("SELECT COUNT(*) FROM task_field_values WHERE task_id=? AND field_id=?", (T2, FD))[0][0] == 1, "B12: its value stays at the old field")
j = Fr.get(B + f"/api/fields/{FD}/count").json()
check(j.get("tasks") == 2 and j.get("moved") == 1, f"B12: the field's delete count names the moved task {j}")
check(Fr.patch(B + f"/api/lists/{L1}", json={"archived": True}).ok and Fr.delete(B + f"/api/lists/{L1}").ok, "B12: the old project into the projects' trash")
pi = Fr.get(B + f"/api/trash/purge-info?list={L1}").json()
check(pi.get("moved_values") == 1 and pi.get("tasks") == 1, f"B12: purge-info of the project names the moved task {pi}")
for rel in ("static/js/projects.js", "static/js/tablecells.js"):
    check("fdMovedWarn(fc)" in kt_src(rel), f"B12: the field delete dialog of {rel} names the moved tasks")
check("j.moved_values" in kt_src("static/js/trashui.js"), "B12: the project's delete dialog names them")

# ================================================================== B28 knowledge: folder rename takes trash pages along, restore " (2)"
def wpage(path, text="Beispieltext"):
    r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": text})
    check(r.status_code == 201, f"B28: page {path} {r.status_code} {r.text[:160]}")
    return r.json()["id"]


def wpath(pid):
    return sql("SELECT path FROM wiki_pages WHERE id=?", (pid,))[0][0]


def wtrashed(pid):
    return sql("SELECT deleted_at FROM wiki_pages WHERE id=?", (pid,))[0][0] is not None


W1, W2 = wpage("Projekte/Laufend"), wpage("Projekte/Abgelegt")
check(Fr.delete(B + f"/api/wiki/pages/{W2}").ok, "B28: one page of the folder in the trash")
r = Fr.post(B + "/api/wiki/move", json={"space": "private", "from": "Projekte", "to": "Archiv"})
check(r.ok and wpath(W1) == "Archiv/Laufend", f"B28: the folder is renamed {r.status_code} {r.text[:160]}")
check(wpath(W2) == "Archiv/Abgelegt" and wtrashed(W2), f"B28: the page in the trash followed and stays in the trash: {wpath(W2)}")
r = Fr.post(B + "/api/wiki/restore", json={"ids": [W2]})
check(r.ok and r.json().get("ids") == [W2] and wpath(W2) == "Archiv/Abgelegt" and not wtrashed(W2), f"B28: restored into the renamed folder {r.text[:200]}")

# the tree's rename (PATCH of the folder node)
W3, W4 = wpage("Kunden/Offen"), wpage("Kunden/Erledigt")
Fr.get(B + "/api/wiki", params={"space": "private"})  # the tree is synced
node = sql("SELECT parent_id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (W3,))
check(bool(node), "B28: the page has its node in the tree")
check(Fr.delete(B + f"/api/wiki/pages/{W4}").ok, "B28: another page in the trash")
r = Fr.patch(B + f"/api/files/nodes/{node[0][0]}", json={"name": "Kundschaft"}) if node else None
check(r is not None and r.ok and wpath(W3) == "Kundschaft/Offen", f"B28: the folder node renamed {r.status_code if r is not None else '-'}")
check(wpath(W4) == "Kundschaft/Erledigt" and wtrashed(W4), f"B28: the page in the trash followed the tree's rename: {wpath(W4)}")

# a name taken meanwhile: back as "Name (2)"
W5 = wpage("Notiz", "alter Text")
check(Fr.delete(B + f"/api/wiki/pages/{W5}").ok, "B28: a page in the trash")
W6 = wpage("Notiz", "neuer Text")
r = Fr.post(B + "/api/wiki/restore", json={"ids": [W5]})
j = r.json() if r.ok else {}
check(r.ok and j.get("ids") == [W5] and not j.get("skipped"), f"B28: the page comes back instead of being skipped {r.text[:200]}")
check(wpath(W5) == "Notiz (2)" and not wtrashed(W5) and wpath(W6) == "Notiz", f"B28: as 'Notiz (2)', the new page keeps its name: {wpath(W5)}")
check([x.get("path") for x in j.get("renamed") or []] == ["Notiz (2)"], f"B28: the answer names the new name {j}")
check("r.renamed" in kt_src("static/js/wiki.js"), "B28: the knowledge trash says the new name")

sys.exit(done("p2552_b_dataloss"))
