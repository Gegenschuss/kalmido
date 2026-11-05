#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.567.0 A API tests (#4707): deleting no longer deletes for good at once -- budget entries (with their receipts), budget
categories and recurring entries, templates, key links of a project, sections and planned sprints go into a trash, come
back through their restore route (the app's Undo, the trash view GET /api/trash/parts: also from another device) and go for
good only after the trash period (files/trashpurge.py). Own container (kt.fresh). Invented people and figures only.
freelancer-matrix: personal, lists, tasks
tenant-matrix: budget, list, template, aggregate
 - budget (the person without an organisation): an entry deleted -> not in the month, its sums and its receipt download; the
   receipt file stays on disk; restore -> back with its receipt and the sums; a booked entry deleted frees the month, booked
   again meanwhile it comes back as a plain entry; a category deleted -> its entries / templates without one, restored -> hung
   back; a template deleted -> its booked entry loses the link, restored -> linked again; the trash run deletes the old ones
   for good (the receipt file too), a young one stays
 - templates, key links, sections (with their limit and tasks), planned sprints (with their tasks): delete -> gone from the
   lists, restore -> back with the same id
 - another person: 404 on every restore and nothing in their trash view; a read-only member of the budget: 403
Regression: before 2.567 every one of these deletes removed the row at once (the restore routes did not exist).
usage: p2567_a_trash_test.py <datadir>"""
import os
import subprocess
from datetime import datetime, timedelta, timezone

import kt
from kt import B, CT, DATA, check
from freelancer_fixture import freelancer

kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces"})
A = kt.setup()
FID, Fr = freelancer(B, A)
SID, St = freelancer(B, A, "sven")  # the stranger (another person without an organisation)
OLD = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(timespec="seconds").replace("+00:00", "Z")


def tick():
    """The trash period run with the switch on (tp_tick, forced) -> its output."""
    out = subprocess.run(["docker", "exec", "-e", "KALMIDO_RETENTION_PURGE=1", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.files.trashpurge import tp_tick\n"
                          "c = connect()\nprint('counts', tp_tick(c, True))\nc.close()"], capture_output=True, text=True)
    check("counts" in out.stdout and "Traceback" not in out.stderr, "the trash run ran " + (out.stdout + out.stderr)[-600:])
    return out.stdout


def parts(s):
    r = s.get(B + "/api/trash/parts")
    check(r.ok, f"the trash view answers {r.status_code} {r.text[:200]}")
    return {(x["kind"], x["id"]) for x in r.json().get("items", [])} if r.ok else set()


def alive(table, rid):
    return bool(kt.dbx(f"SELECT 1 FROM {table} WHERE id=?", (rid,)))


# ================================================================== budget (freelancer: the personal area)
L = Fr.post(B + "/api/budget/lists", json={"name": "Household"}).json()["list_id"]
M = Fr.get(B + "/api/budget").json()["month"]


def month():
    return Fr.get(B + f"/api/budget/{L}", params={"month": M}).json()


KIDS = Fr.post(B + f"/api/budget/{L}/cats", json={"name": "Kids", "kind": "out"}).json()["id"]
R = Fr.post(B + f"/api/budget/{L}/recurring", json={"title": "Rent", "amount": 1000, "kind": "out", "per": "month", "start": M,
                                                    "cat_id": KIDS}).json()["id"]
E1 = Fr.post(B + f"/api/budget/{L}/entries", json={"day": f"{M}-02", "amount": 60, "kind": "out", "title": "Shoes", "cat_id": KIDS}).json()["id"]
F1 = Fr.post(B + f"/api/budget/entries/{E1}/files", files=[("file", ("r.txt", b"receipt", "text/plain"))]).json()["files"][0]["id"]
P1 = os.path.join(DATA, "attachments", kt.dbx("SELECT path FROM budget_files WHERE id=?", (F1,))[0][0])
E2 = Fr.post(B + f"/api/budget/recurring/{R}/book", json={"month": M}).json()["id"]
before = month()["totals"]["ist_out"]
check(before == 1060.0, f"setup: the month spends 1060 ({before})")

r = Fr.delete(B + f"/api/budget/entries/{E1}")
check(r.ok and r.json().get("trash") is True and r.json()["entry"]["title"] == "Shoes", f"an entry deleted: into the trash {r.text[:200]}")
j = month()
check(E1 not in [e["id"] for e in j["entries"]] and j["totals"]["ist_out"] == 1000.0, f"… not in the month, not in its sums ({j['totals']})")
check(alive("budget_entries", E1) and os.path.exists(P1), "… the row and the receipt file stay (regression: before 2.567 both were gone)")
check(Fr.get(B + f"/api/budget/files/{F1}").status_code == 404, "… its receipt does not download while it is in the trash")
check(("budget_entry", E1) in parts(Fr), "… the trash view names it")
check(("budget_entry", E1) not in parts(St), "… not in another person's trash view")
check(St.post(B + f"/api/budget/entries/{E1}/restore").status_code == 404, "another person cannot restore it (404)")
r = Fr.post(B + f"/api/budget/entries/{E1}/restore")
check(r.ok and r.json()["id"] == E1 and len(r.json()["files"]) == 1, f"restored with its receipt {r.text[:200]}")
check(month()["totals"]["ist_out"] == 1060.0 and Fr.get(B + f"/api/budget/files/{F1}").content == b"receipt", "… back in the sums, the receipt downloads")
check(Fr.post(B + f"/api/budget/entries/{E1}/restore").status_code == 404, "a second restore: 404 (it is not in the trash)")

# a booked entry: its month is free while it is in the trash
check(Fr.delete(B + f"/api/budget/entries/{E2}").ok, "the booked rent deleted")
check(any(o["recurring"]["id"] == R for o in month()["open_recurring"]), "… the template is open in the month again")
E3 = Fr.post(B + f"/api/budget/recurring/{R}/book", json={"month": M})
check(E3.status_code == 201, f"… and can be booked again {E3.text[:200]}")
E3 = E3.json()["id"]
r = Fr.post(B + f"/api/budget/entries/{E2}/restore")
check(r.ok and r.json()["recurring_id"] is None, f"restored while the month is booked again: back as a plain entry {r.text[:200]}")
check(Fr.delete(B + f"/api/budget/entries/{E2}").ok, "(the plain copy deleted again)")

# a category: its rows lose it while it is in the trash, get it back on restore
r = Fr.delete(B + f"/api/budget/cats/{KIDS}")
check(r.ok and r.json().get("trash") is True and E1 in r.json()["entry_ids"], f"a category deleted into the trash {r.text[:200]}")
j = month()
check(KIDS not in [x["id"] for x in j["cats"]] and next(e for e in j["entries"] if e["id"] == E1)["cat_id"] is None,
      "… gone from the month, its entry without a category")
check(Fr.post(B + f"/api/budget/{L}/entries", json={"day": f"{M}-03", "amount": 1, "kind": "out", "title": "x", "cat_id": KIDS}).status_code == 400,
      "… a category in the trash takes no new entry")
check(St.post(B + f"/api/budget/cats/{KIDS}/restore").status_code == 404, "another person cannot restore it (404)")
r = Fr.post(B + f"/api/budget/cats/{KIDS}/restore")
check(r.ok and r.json()["id"] == KIDS, f"the category restored {r.text[:200]}")
j = month()
check(next(e for e in j["entries"] if e["id"] == E1)["cat_id"] == KIDS, "… its entry hangs on it again")
check(next(x for x in Fr.get(B + f"/api/budget/{L}/recurring").json()["items"] if x["id"] == R)["cat_id"] == KIDS, "… and its template")

# a template: its booked entry loses the link while it is in the trash
r = Fr.delete(B + f"/api/budget/recurring/{R}")
check(r.ok and r.json().get("trash") is True, f"a template deleted into the trash {r.text[:200]}")
check(R not in [x["id"] for x in Fr.get(B + f"/api/budget/{L}/recurring").json()["items"]], "… gone from the templates")
check(next(e for e in month()["entries"] if e["id"] == E3)["recurring_id"] is None, "… its booked entry without the link")
check(St.post(B + f"/api/budget/recurring/{R}/restore").status_code == 404, "another person cannot restore it (404)")
r = Fr.post(B + f"/api/budget/recurring/{R}/restore")
check(r.ok and r.json()["id"] == R and next(e for e in month()["entries"] if e["id"] == E3)["recurring_id"] == R,
      f"restored: the booked entry is linked again {r.text[:200]}")
# review 2.567: an entry of the template restored while the template is in the trash, the month booked again meanwhile -> the
# template's restore linked both to the same month (unique index budget_entries_booked: 500, the template stayed in the trash)
check(Fr.delete(B + f"/api/budget/entries/{E3}").ok, "the booked rent deleted again")
E4 = Fr.post(B + f"/api/budget/recurring/{R}/book", json={"month": M})
check(E4.status_code == 201, f"… the month booked anew {E4.text[:200]}")
E4 = E4.json()["id"]
check(Fr.delete(B + f"/api/budget/recurring/{R}").ok, "… the template deleted")
check(Fr.post(B + f"/api/budget/entries/{E3}/restore").ok, "… the older entry restored while its template is in the trash")
r = Fr.post(B + f"/api/budget/recurring/{R}/restore")
ents = {e["id"]: e for e in month()["entries"]}
check(r.ok and ents[E4]["recurring_id"] == R and ents[E3]["recurring_id"] is None,
      f"the template restored: the newest entry of the month linked, the older one plain {r.status_code} {r.text[:200]}")
check(Fr.delete(B + f"/api/budget/entries/{E3}").ok, "(the plain copy deleted again)")

# a read-only member restores nothing
check(Fr.put(B + f"/api/lists/{L}/members", json={"user_id": SID, "role": "view"}).ok, "setup: the budget shared read-only with sven")
check(Fr.delete(B + f"/api/budget/entries/{E1}").ok, "(the entry with the receipt deleted again)")
check(St.post(B + f"/api/budget/entries/{E1}/restore").status_code == 403, "a read-only member cannot restore (403)")
check(("budget_entry", E1) not in parts(St), "… and does not see it in the trash view")
Fr.delete(B + f"/api/lists/{L}/members/{SID}")

# the trash period: the old one goes for good with its receipt file, a young one stays
E4 = Fr.post(B + f"/api/budget/{L}/entries", json={"day": f"{M}-04", "amount": 5, "kind": "out", "title": "Young"}).json()["id"]
Fr.delete(B + f"/api/budget/entries/{E4}")
kt.dbx("UPDATE budget_entries SET deleted_at=? WHERE id=?", (OLD, E1))
out = tick()
check(not alive("budget_entries", E1) and not alive("budget_files", F1) and not os.path.exists(P1),
      f"the trash run deleted the old entry, its receipt row and file {out[-300:]}")
check(alive("budget_entries", E4), "… the young one stays in the trash")

# ================================================================== templates (freelancer)
INBOX = next(x["id"] for x in Fr.get(B + "/api/state").json()["lists"] if x.get("is_inbox"))
TK = Fr.post(B + "/api/tasks", json={"title": "Weekly review", "list_id": INBOX}).json()["id"]
T = Fr.post(B + "/api/templates", json={"task_id": TK, "name": "Review"}).json()["id"]
r = Fr.delete(B + f"/api/templates/{T}")
check(r.ok and r.json().get("trash") is True and alive("templates", T), f"a template deleted into the trash {r.text[:200]}")
check(T not in [x["id"] for x in Fr.get(B + "/api/templates").json()["templates"]], "… gone from the templates")
check(T not in [x["id"] for x in Fr.get(B + "/api/state").json().get("templates", [])], "… and from the state")
check(Fr.post(B + f"/api/templates/{T}/apply", json={}).status_code == 404, "… it cannot be used")
check(("template", T) in parts(Fr) and ("template", T) not in parts(St), "… the trash view names it (only its person's)")
check(St.post(B + f"/api/templates/{T}/restore").status_code == 404, "another person cannot restore it (404)")
ex = Fr.get(B + "/api/export.json")
check(ex.ok and T not in [x["id"] for x in ex.json().get("templates", [])]
      and E4 not in [e["id"] for x in ex.json().get("budget", []) for e in x["entries"]],
      f"the person's export leaves out what is in the trash {ex.status_code} {ex.text[:200]}")
r = Fr.post(B + f"/api/templates/{T}/restore")
check(r.ok and r.json()["id"] == T and T in [x["id"] for x in Fr.get(B + "/api/templates").json()["templates"]], f"restored {r.text[:200]}")

# ================================================================== key links, sections, sprints (a freelancer's project)
P = Fr.post(B + "/api/lists", json={"name": "Product", "kind": "project"}).json()["id"]
LK = Fr.post(B + f"/api/lists/{P}/links", json={"url": "https://example.com/spec", "title": "Spec"}).json()["id"]
r = Fr.delete(B + f"/api/lists/{P}/links/{LK}")
check(r.ok and alive("list_links", LK), f"a key link deleted into the trash {r.text[:200]}")
check(LK not in [x["id"] for x in Fr.get(B + f"/api/lists/{P}/overview").json().get("links", [])], "… gone from the overview")
check(("link", LK) in parts(Fr), "… the trash view names it")
check(St.post(B + f"/api/lists/{P}/links/{LK}/restore").status_code == 404, "another person cannot restore it (404)")
r = Fr.post(B + f"/api/lists/{P}/links/{LK}/restore")
check(r.ok and LK in [x["id"] for x in Fr.get(B + f"/api/lists/{P}/overview").json().get("links", [])], f"restored {r.text[:200]}")

SEC = Fr.post(B + "/api/sections", json={"list_id": P, "name": "Doing", "wip_limit": 3}).json()["id"]
TS = Fr.post(B + "/api/tasks", json={"title": "Build", "list_id": P, "section_id": SEC}).json()["id"]
r = Fr.delete(B + f"/api/sections/{SEC}")
check(r.ok and r.json().get("trash") is True and r.json()["tasks"] == [TS], f"a section deleted into the trash {r.text[:200]}")
st = Fr.get(B + "/api/state").json()
check(SEC not in [x["id"] for x in st["sections"]] and next(t for t in st["tasks"] if t["id"] == TS)["section_id"] is None,
      "… gone, its task without a section (as before)")
check(("section", SEC) in parts(Fr) and ("section", SEC) not in parts(St), "… the trash view names it (not to another person)")
check(St.post(B + f"/api/sections/{SEC}/restore").status_code == 404, "another person cannot restore it (404)")
r = Fr.post(B + f"/api/sections/{SEC}/restore")
check(r.ok and r.json()["id"] == SEC and r.json()["wip_limit"] == 3 and r.json()["moved"] == [TS], f"restored: same id, limit, task {r.text[:200]}")
st = Fr.get(B + "/api/state").json()
check(SEC in [x["id"] for x in st["sections"]] and next(t for t in st["tasks"] if t["id"] == TS)["section_id"] == SEC, "… in the state again")
check(Fr.post(B + f"/api/sections/{SEC}/restore").status_code == 404, "a second restore: 404")

check(Fr.put(B + f"/api/lists/{P}/sprint-settings", json={"on": True}).ok, "setup: sprints on")
SP = Fr.post(B + f"/api/lists/{P}/sprints", json={"goal": "Later"}).json()
SP = SP.get("id") or (SP.get("sprint") or {}).get("id")
check(Fr.patch(B + f"/api/tasks/{TS}", json={"sprint_id": SP}).ok, "setup: the task planned into the sprint")
r = Fr.delete(B + f"/api/sprints/{SP}")
check(r.ok and r.json().get("trash") is True and r.json()["tasks"] == [TS], f"a planned sprint deleted into the trash {r.text[:200]}")
check(Fr.get(B + f"/api/sprints/{SP}").status_code == 404 and kt.dbx("SELECT sprint_id FROM tasks WHERE id=?", (TS,))[0][0] is None,
      "… gone, its task back in the backlog (as before)")
check(St.post(B + f"/api/sprints/{SP}/restore").status_code == 404, "another person cannot restore it (404)")
r = Fr.post(B + f"/api/sprints/{SP}/restore")
check(r.ok and r.json()["sprint"]["id"] == SP and r.json()["moved"] == [TS], f"restored: same id, its task {r.text[:200]}")
check(kt.dbx("SELECT sprint_id FROM tasks WHERE id=?", (TS,))[0][0] == SP, "… the task is in the sprint again")

# the trash period for links, list parts and templates
Fr.delete(B + f"/api/lists/{P}/links/{LK}")
Fr.delete(B + f"/api/sections/{SEC}")
Fr.delete(B + f"/api/templates/{T}")
kt.dbx("UPDATE list_links SET deleted_at=? WHERE id=?", (OLD, LK))
kt.dbx("UPDATE list_part_trash SET deleted_at=? WHERE kind='section' AND ref_id=?", (OLD, SEC))
kt.dbx("UPDATE templates SET deleted_at=? WHERE id=?", (OLD, T))
out = tick()
check(not alive("list_links", LK) and not alive("templates", T)
      and not kt.dbx("SELECT 1 FROM list_part_trash WHERE kind='section' AND ref_id=?", (SEC,)),
      f"the trash run deleted the old link, template and section copy {out[-300:]}")
check(Fr.post(B + f"/api/sections/{SEC}/restore").status_code == 404, "… the section cannot come back after that")
check("_err" not in out, f"no area of the run failed {out[-300:]}")

raise SystemExit(kt.done("p2567_a_trash"))
