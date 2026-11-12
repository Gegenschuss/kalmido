#!/usr/bin/env python3
"""2.363.2 (#3104): every office import is an import run, and the task import of TickTick takes the shared way.
 - fixed costs, trips and leads: a run in the import runs, undone there (what changed since stays), twice = 409, an old run 409;
   the undo of the toast marks the run as undone
 - leads without an e-mail: the same file again = duplicates, also inside one file; the commit checks again
 - TickTick: preview stores nothing, the import can be undone, the same file again skips, a task of the former import
   (bare taskId) is found, a broken date is a warning (no raw error), not a TickTick file = a clear message, cp1252 is read,
   the rate limit holds
 - newsletter consent import: an entry of the recent imports, undo restores the earlier status, a changed consent stays
freelancer-matrix: office, tasks (every part runs as a person without an organisation)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, FAILS, OKS, check  # noqa: E402,F401
from freelancer_fixture import freelancer  # noqa: E402

DATA = os.environ.get("KALMIDO_TEST_DATA") or (sys.argv[1] if len(sys.argv) > 1 else "")
O = B + "/api/office"
R = O + "/legacy/runs"

kt.fresh()
A = kt.setup(lang="en")
FID, Fr = freelancer(B, A)


def sql(q, args=()):
    return dbxm.connect(DATA).execute(q, args).fetchall()


def runs(kind):
    return [x for x in Fr.get(R).json()["runs"] if x["kind"] == kind]


def undo(rid):
    return Fr.post(R + f"/{rid}/undo", json={})


# ---- fixed costs
rows = [{"label": n, "amount": "100", "repeat": "monthly", "start": "2026-01-01"} for n in ("Miete", "Strom")]
r = Fr.post(O + "/fixed-costs/import", json={"items": rows})
check(r.status_code == 201 and r.json()["created"] == 2, "fixed costs imported " + r.text[:200])
ids = r.json()["ids"]
run = runs("fixed_costs")
check(len(run) == 1 and run[0]["total"] == 2 and not run[0]["undone_at"], f"#3104: a run for the fixed costs {run}")
check(Fr.post(O + "/fixed-costs/import", json={"items": rows}).json()["created"] == 0 and len(runs("fixed_costs")) == 1, "#3104: nothing new = no run")
dbxm.connect(DATA).execute("UPDATE office_fixed_costs SET updated_at='2030-01-01T00:00:00Z' WHERE id=?", (ids[0],))
r = undo(run[0]["id"])
check(r.ok and r.json()["removed"]["fixed_costs"] == 1 and r.json()["kept"]["entries"] == 1, "#3104: the undo keeps the changed row " + r.text[:200])
check([x[0] for x in sql("SELECT id FROM office_fixed_costs WHERE id IN (?,?) AND deleted_at IS NULL", tuple(ids))] == [ids[0]], "#3104: only the unchanged one went")  # 2.905.0 (#5414): into the trash
check(runs("fixed_costs")[0]["undone_at"], "#3104: the run shows as undone")
check(undo(run[0]["id"]).status_code == 409, "#3104: undone twice = 409")
# the toast's undo settles the run
r = Fr.post(O + "/fixed-costs/import", json={"items": [{"label": "Netz", "amount": "20", "repeat": "monthly", "start": "2026-01-01"}]})
Fr.post(O + "/fixed-costs/delete", json={"ids": r.json()["ids"]})
check(all(x["undone_at"] for x in runs("fixed_costs")), "#3104: the toast's undo marks the run as undone")
# too late
r = Fr.post(O + "/fixed-costs/import", json={"items": [{"label": "Alt", "amount": "30", "repeat": "monthly", "start": "2026-01-01"}]})
old = runs("fixed_costs")[0]["id"]
dbxm.connect(DATA).execute("UPDATE office_import_runs SET created_at='2020-01-01T00:00:00Z' WHERE id=?", (old,))
r = undo(old)
check(r.status_code == 409 and "24 hours" in r.text, "#3104: after 24 hours the undo refuses with a reason " + r.text[:200])

# ---- trips
trips = [{"date_from": "2026-03-02", "date_to": "2026-03-02", "dest": "Koeln", "people": [{"name": "Rita Reise"}], "purpose": "job", "project": "Dreh"}]
r = Fr.post(O + "/trips/import", json={"trips": trips})
check(r.status_code == 201 and r.json()["created"] == 1, "trip imported " + r.text[:200])
tid = r.json()["ids"][0]
run = runs("trips")
check(len(run) == 1, f"#3104: a run for the trips {run}")
r = undo(run[0]["id"])
check(r.ok and r.json()["removed"]["trips"] == 1 and not sql("SELECT id FROM office_trips WHERE id=? AND deleted_at IS NULL", (tid,)), "#3104: the trip went " + r.text[:200])  # 2.1005.0 (#5415): into the trash

# ---- leads
CSV = "Name;Firma\nOhne Mail;Beispiel GmbH\nOHNE  mail;beispiel gmbh\nNoch einer;\n"
L = O + "/leads/import"
j = Fr.post(L, json={"text": CSV}).json()
check(j["count"] == 2 and j["dup_count"] == 1, f"#3104: a twin inside the file without an e-mail is found {j}")
r = Fr.post(L, json={"text": CSV, "commit": True})
check(r.status_code == 201 and len(r.json()["ids"]) == 2, "leads imported " + r.text[:200])
j = Fr.post(L, json={"text": CSV}).json()
check(j["count"] == 0 and j["dup_count"] == 3, f"#3104: the same file again = duplicates {j}")
check(Fr.post(L, json={"text": CSV, "commit": True}).status_code == 400, "#3104: the commit checks again")
run = runs("leads")
check(len(run) == 1 and run[0]["total"] == 2, f"#3104: a run for the leads {run}")
r = undo(run[0]["id"])
check(r.ok and r.json()["removed"]["leads"] == 2, "#3104: the leads went to the bin " + r.text[:200])
check(Fr.post(L, json={"text": CSV}).json()["count"] == 2, "#3104: after the undo the file imports again")

# ---- TickTick
HEAD = '"Folder Name","List Name","Title","Tags","Content","Start Date","Due Date","Reminder","Priority","Status","Order","Is All Day","Column Name","Column Order","taskId","parentId"\n'
TT = ('"Date: 2026-10-01"\n\n' + HEAD
      + '"Ordner","TT Projekt","Eltern","a,b","Text","","2026-10-14T22:00:00+0000","-PT15M","5","0","1","false","Offen","2","p1",""\n'
      + '"Ordner","TT Projekt","Kind","","","","kein Datum","","0","0","2","false","Neu","1","k1","p1"\n')
I = B + "/api/import/ticktick"


def post(body, dry, name="tt.csv"):
    return Fr.post(I, data={"dry_run": "1"} if dry else {}, files={"file": (name, body, "text/csv")})


r = post(TT.encode(), True)
check(r.ok and r.json()["dry_run"] and r.json()["created"]["tasks"] == 2, "#3104: TickTick has a preview " + r.text[:300])
check(any("date" in w["text"].lower() for w in r.json()["warnings"]), f"#3104: a broken date is a warning {r.json()['warnings']}")
check(not sql("SELECT id FROM tasks WHERE title='Eltern'"), "#3104: the preview stores nothing")
r = post(TT.encode(), False)
j = r.json()
check(r.ok and j["import_id"] and j["created"]["tasks"] == 2 and j["created"]["subtasks"] == 1, "#3104: TickTick imported, with an undo " + r.text[:300])
p = sql("SELECT priority, due, reminders FROM tasks WHERE title='Eltern'")[0]
check(p[0] == 5 and p[1] == "2026-10-15" and p[2] == "15", f"priority, date and reminder are kept {p}")
sec = [x[0] for x in sql("SELECT name FROM sections WHERE name IN ('Neu','Offen') ORDER BY sort")]
check(sec == ["Neu", "Offen"], f"the sections in TickTick's order {sec}")
check(post(TT.encode(), False).json()["skipped"] == 2, "#3104: the same file again skips")
check(Fr.post(B + f"/api/imports/{j['import_id']}/undo").json()["tasks"] == 2, "#3104: the undo takes both back")
# a task of the former import (bare taskId)
dbxm.connect(DATA).execute("UPDATE tasks SET tt_id='alt1' WHERE id=(SELECT id FROM tasks WHERE created_by=? ORDER BY id LIMIT 1)", (FID,))
ALT = HEAD + '"","Alt","Schon da","","","","","","0","0","1","","","","alt1",""\n'
check(post(ALT.encode(), True).json()["skipped"] == 1, "#3104: a task of the former import is found")
r = post(b"a,b\n1,2\n", True)
check(r.status_code == 400 and "TickTick" in r.text, "#3104: another file = a clear message " + r.text[:200])
r = post((HEAD + '"","Bürö","Grüße","","","","","","x","0","y","","","","c1",""\n').encode("cp1252"), True)
check(r.ok and r.json()["lists"][0]["name"] == "Bürö", "#3104: Windows-1252, a broken number: no raw error " + r.text[:200])

# ---- newsletter consent import
bk = Fr.post(B + "/api/books", json={"name": "Kunden", "org_id": None}).json()["id"]
cid = Fr.post(B + "/api/contacts", json={"book_id": bk, "fn": "Anna Probe", "emails": [{"value": "anna@example.com"}]})
cid = cid.json().get("id") if cid.ok else None
if cid:
    IM = B + "/api/newsletter/consent/import"
    d = {"ws": "private", "csv": "anna@example.com;2025-03-05;Messe\n", "filename": "c.csv", "apply": True}
    r = Fr.post(IM, json=d)
    check(r.ok and r.json()["applied"] == 1 and r.json()["import_id"], "#3104: the consent import is an import entry " + r.text[:200])
    iid = r.json()["import_id"]
    st = lambda: sql("SELECT nl_status FROM contacts WHERE id=?", (cid,))[0][0]  # noqa: E731
    check(st() == "yes", "consent stored")
    e = [x for x in Fr.get(B + "/api/imports").json()["imports"] if x["id"] == iid]
    check(e and e[0]["can_undo"] and e[0]["source_name"] == "Newsletter", f"#3104: it shows in the recent imports {e}")
    r = Fr.post(B + f"/api/imports/{iid}/undo")
    check(r.ok and r.json()["contacts"] == 1 and (st() or "") == "", "#3104: the undo restores the earlier status " + r.text[:200])
    iid = Fr.post(IM, json=d).json()["import_id"]
    dbxm.connect(DATA).execute("UPDATE contacts SET nl_at='2026-01-01T00:00:00Z' WHERE id=?", (cid,))
    r = Fr.post(B + f"/api/imports/{iid}/undo")
    check(r.ok and r.json()["kept_contacts"] == 1 and st() == "yes", "#3104: a consent changed since stays " + r.text[:200])
else:
    check(False, "contact created")

# ---- the rate limit (last: it blocks further imports)
r = None
for _ in range(40):
    r = post(ALT.encode(), True)
    if r.status_code == 429:
        break
check(r.status_code == 429, f"#3104: TickTick has the rate limit {r.status_code}")
raise SystemExit(kt.done("p2363_2_runs"))
