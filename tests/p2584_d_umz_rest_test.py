#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.584.0 (#3965): the account import takes over absences, timesheets, household budgets and the playbooks of folders into
the private space, and the undo takes them away again. Invented names only (example.com). A crafted account export (old
account id 1000) into a person without an organisation (freelancer_fixture, "gina"); a second one ("otto") is the stranger:
 - the preview no longer names "Household budget", "Absences" or "Timesheets" as staying behind, nor a folder's playbook;
   it names the timesheet month gina has here already
 - absences land in gina's personal office (kind and note sealed, readable through /api/team/absences), a waiting request
   as an entered absence, one whose end lies before its start not at all; a row whose person column names somebody else
   (otto's id) is still gina's -- never otto's
 - timesheets: the month gina has here already keeps hers, the other month arrives (no decider, private space)
 - the budget of the file's budget list arrives on the new budget list (category with limit, template, two entries: the
   booked template month points at the new template), sealed; a budget that names a project that is no budget list, or
   otto's budget list (an id of this server), brings nothing there
 - a folder's playbook arrives with both versions (the author only when it was me), a folder gina has a playbook for keeps hers
 - the undo takes every one of them away again; gina's own month and playbook, and everything of otto, stay; an entry changed
   since the import stays
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2584D_NOSTART=1 = the server already runs like that).
freelancer-matrix: own
usage: p2584_d_umz_rest_test.py <datadir>"""
import base64
import hashlib
import io
import json
import os
import sys
import zipfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
TS = "2026-10-20T06:00:00Z"
ME = 1000


def sha(b):
    return hashlib.sha256(b).hexdigest()


def mkzip(tables):
    entries = {f"data/{t}.json": json.dumps(rows).encode() for t, rows in tables.items()}
    flist = [{"path": p, "size": len(b), "sha256": sha(b)} for p, b in entries.items()]
    m = {"format": "kalmido-account", "v": 1, "kalmido_version": "test", "created_at": TS,
         "source": {"url": "https://example.com", "hosted": True}, "user": {"id": ME, "name": "Test Person", "email": "test@example.com"},
         "tables": {}, "files": flist, "client_encrypted": {}, "export_id": os.urandom(16).hex()}
    mb = json.dumps(m).encode()
    cs = f"{sha(mb)}  manifest.json\n" + "".join(f"{f['sha256']}  {f['path']}\n" for f in flist)
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", cs.encode())
        for p, b in entries.items():
            z.writestr(p, b)
    return bio.getvalue()


def state_of(s, iid):
    j = s.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid, until(lambda: state_of(s, iid), 180) or {}


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2584D")
A = kt.setup()
GID, Gi = freelancer(B, A, "gina")  # the target account, without an organisation
OID, Ot = freelancer(B, A, "otto")  # the stranger
r = Ot.post(B + "/api/budget/lists", json={"name": "Otto Haushalt"})
check(r.ok, f"otto's budget list {r.status_code} {r.text[:160]}")
OLIST = r.json().get("list_id") if r.ok else 0
check(OLIST and one("SELECT COUNT(*) FROM budget_cats WHERE list_id=?", (OLIST,)) > 0, f"guard: otto's list has its default categories {OLIST}")
OTTO_BUD = {t: one(f"SELECT COUNT(*) FROM {t} WHERE list_id=?", (OLIST,)) for t in ("budget_cats", "budget_recurring", "budget_entries")}
kt.dbx("INSERT INTO time_sheets(user_id, month, state, note, created_at, updated_at) VALUES(?, '2026-08', 'open', '', ?, ?)", (GID, TS, TS))
kt.dbx("INSERT INTO playbooks(list_id, owner_id, folder, version, body, source, created_at) VALUES(NULL, ?, 'Bestand', 1, 'Gina eigen', 'edit', ?)",
       (GID, TS))

FILE = mkzip({
    "lists": [{"id": 1, "name": "Umzug Projekt", "created_at": TS},
              {"id": 5, "name": "Haushalt Umzug", "life": "budget", "created_at": TS}],
    "budgets": [{"list_id": 5, "name": "Haushalt Umzug",
                 "categories": [{"id": 51, "list_id": 5, "name": "Essen", "kind": "out", "limit": 300, "sort": 0}],
                 "recurring": [{"id": 52, "list_id": 5, "title": "Miete", "amount": 800, "kind": "out", "cat_id": 51, "per": "month",
                                "start": "2026-01", "until": None}],
                 "entries": [{"id": 53, "list_id": 5, "day": "2026-10-03", "amount": 45.5, "kind": "out", "title": "Einkauf", "note": "Markt",
                              "counterpart": "Laden", "cat_id": 51, "recurring_id": None, "source": "manual"},
                             {"id": 54, "list_id": 5, "day": "2026-10-01", "amount": 800, "kind": "out", "title": "Miete", "note": "",
                              "counterpart": "", "cat_id": 51, "recurring_id": 52, "source": "recurring"},
                             {"id": 55, "list_id": 5, "day": "kein Tag", "amount": 1, "kind": "out", "title": "Kaputt"}]},
                # a budget on a project that is no budget list, and one naming otto's list (an id of this server)
                {"list_id": 1, "name": "Kein Budget", "entries": [{"id": 56, "day": "2026-10-04", "amount": 5, "kind": "out", "title": "Falsch"}]},
                {"list_id": OLIST, "name": "Fremd", "categories": [{"id": 57, "name": "Fremdkat", "kind": "out"}],
                 "entries": [{"id": 58, "day": "2026-10-05", "amount": 7, "kind": "out", "title": "Fremd"}]}],
    "absences": [{"id": 61, "org_id": 77, "kind": "vacation", "start_date": "2026-11-16", "end_date": "2026-11-20", "half_day": "",
                  "note": "Urlaub Umzug", "status": "approved", "created_at": TS},
                 {"id": 62, "kind": "sick", "start_date": "2026-11-02", "end_date": "2026-11-03", "note": "krank", "status": "pending",
                  "user_id": OID, "created_by": OID, "created_at": TS},
                 {"id": 63, "kind": "vacation", "start_date": "2026-11-10", "end_date": "2026-11-01", "note": "rueckwaerts", "created_at": TS}],
    "timesheets": [{"id": 71, "org_id": 77, "month": "2026-08", "state": "closed", "note": "alt", "created_at": TS, "updated_at": TS},
                   {"id": 72, "org_id": 77, "month": "2026-09", "state": "approved", "note": "Umzug Monat", "decided_at": TS,
                    "user_id": OID, "decided_by": OID, "created_at": TS, "updated_at": TS}],
    "playbooks": [{"id": 81, "list_id": None, "owner_id": ME, "folder": "Kunden", "version": 1, "body": "Ordner v1", "author_id": ME,
                   "source": "edit", "created_at": TS},
                  {"id": 82, "list_id": None, "owner_id": ME, "folder": "Kunden", "version": 2, "body": "Ordner v2", "author_id": 2000,
                   "source": "proposal", "created_at": TS},
                  {"id": 83, "list_id": None, "owner_id": ME, "folder": "Bestand", "version": 1, "body": "Fremd Bestand", "created_at": TS}],
})

iid, j = upload(Gi, FILE)
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
nt = {x.get("what"): x.get("count") for x in (j.get("preview") or {}).get("not_taken") or []}
gone = {"Household budget", "Absences", "Timesheets", "Playbooks"} & set(nt)
check(not gone, f"#3965 the preview no longer names them as staying behind {gone} {nt}")
check(nt.get("Timesheets of months you have here already") == 1, f"#3965 ... but the month gina has here already {nt}")
r = Gi.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}})
check(r.status_code == 202, f"the run starts {r.status_code} {r.text[:200]}")
j = until(lambda: state_of(Gi, iid), 180) or {}
check(j.get("state") == "done", f"the import is done {j.get('state')} {j.get('error')}")
RES = j.get("result") or {}
IMP = RES.get("import_id")
WARN = json.dumps(RES.get("warnings"), ensure_ascii=False)
check("Timesheets of months you have here already were not taken over" in WARN and "2026-08" in WARN,
      f"#3965 the result names the month that stays {WARN[:400]}")
check("Folders that have a playbook here already keep it" in WARN and "Bestand" in WARN, f"#3965 ... and the folder that keeps its playbook {WARN[:400]}")
LEFT = json.dumps(RES, ensure_ascii=False)
check("Household budget (" not in LEFT and "Absences (" not in LEFT and "Timesheets (" not in LEFT,
      f"#3965 the result's 'stays on the old server' no longer names them {LEFT[:400]}")

# absences: in gina's personal office, sealed, readable for her
PB = one("SELECT id FROM orgs WHERE personal_of=?", (GID,))
ab = kt.dbx("SELECT user_id, org_id, kind, note, status, start_date, created_by, decided_by FROM hub_absences WHERE deleted_at IS NULL ORDER BY start_date")
check(PB and len(ab) == 2 and all(a[0] == GID and a[1] == PB and a[6] == GID and a[7] is None for a in ab),
      f"#3965 two absences arrive in gina's personal office, both hers (the one naming otto too), no decider {ab} {PB}")
check(all(a[2] not in ("sick", "vacation") and a[3] not in ("krank", "Urlaub Umzug") for a in ab), f"#3965 ... kind and note sealed {ab}")
check(all(a[4] == "approved" for a in ab), f"#3965 ... the waiting request is an entered absence {[a[4] for a in ab]}")
check(one("SELECT COUNT(*) FROM hub_absences WHERE user_id=?", (OID,)) == 0, "#3965 nothing lands with otto")
r = Gi.get(B + "/api/team/absences", params={"start": "2026-11-01", "end": "2026-11-30"})
items = r.json().get("items") or [] if r.ok else []
check(sorted((x.get("kind"), x.get("note")) for x in items) == [("sick", "krank"), ("vacation", "Urlaub Umzug")],
      f"#3965 gina reads them in her absences {r.status_code} {[(x.get('kind'), x.get('note')) for x in items]}")

# timesheets
ts = kt.dbx("SELECT month, state, org_id, decided_by, note FROM time_sheets WHERE user_id=? ORDER BY month", (GID,))
check([(t[0], t[1]) for t in ts] == [("2026-08", "open"), ("2026-09", "approved")] and ts[1][2] is None and ts[1][3] is None,
      f"#3965 the month gina had stays hers, the other one arrives (private, no decider) {ts}")
check(one("SELECT COUNT(*) FROM time_sheets WHERE user_id=?", (OID,)) == 0, "#3965 no timesheet lands with otto")

# budgets
BL = one("SELECT id FROM lists WHERE owner_id=? AND name='Haushalt Umzug' AND life='budget' AND deleted_at IS NULL", (GID,))
PL = one("SELECT id FROM lists WHERE owner_id=? AND name='Umzug Projekt' AND deleted_at IS NULL", (GID,))
check(BL and PL, f"the budget list and the project arrive {BL} {PL} {WARN[:300]}")
r = Gi.get(B + f"/api/budget/{BL or 0}", params={"month": "2026-10"})
v = r.json() if r.ok else {}
cats = {x.get("name"): x for x in v.get("cats") or []}
ents = sorted((e.get("title"), e.get("amount"), e.get("note"), e.get("cat_id") == (cats.get("Essen") or {}).get("id")) for e in v.get("entries") or [])
check(r.ok and set(cats) == {"Essen"} and cats["Essen"].get("limit") == 300,
      f"#3965 the category arrives with its limit {r.status_code} {list(cats)} {json.dumps(cats)[:200]}")
check(ents == [("Einkauf", 45.5, "Markt", True), ("Miete", 800.0, "", True)], f"#3965 the two entries arrive on the new category {ents}")
rec = (Gi.get(B + f"/api/budget/{BL or 0}/recurring").json() or {}).get("items") or []
RID = rec[0].get("id") if rec else None
check(len(rec) == 1 and rec[0].get("title") == "Miete" and rec[0].get("amount") == 800, f"#3965 the template arrives {rec}")
check(one("SELECT recurring_id FROM budget_entries WHERE list_id=? AND rmonth='2026-10'", (BL or 0,)) == RID and RID,
      "#3965 the booked month points at the new template")
sids = kt.dbx("SELECT sid, title FROM budget_entries WHERE list_id=?", (BL or 0,))
check(all(x[0] in (0, -GID) and (x[0] == 0 or x[1] not in ("Einkauf", "Miete")) for x in sids),
      f"#3965 the entries are sealed like one made by hand (the owner's account key while private encryption is on) {sids}")
check(one("SELECT COUNT(*) FROM budget_entries WHERE list_id=?", (PL or 0,)) == 0, "#3965 a budget on a project that is no budget list brings nothing")
now = {t: one(f"SELECT COUNT(*) FROM {t} WHERE list_id=?", (OLIST,)) for t in OTTO_BUD}
check(now == OTTO_BUD, f"#3965 otto's budget list gets nothing from gina's file {now} {OTTO_BUD}")

# folder playbooks
pbs = kt.dbx("SELECT folder, version, body, author_id, source FROM playbooks WHERE list_id IS NULL AND owner_id=? ORDER BY folder, version", (GID,))
check([(p[0], p[1], p[2]) for p in pbs] == [("Bestand", 1, "Gina eigen"), ("Kunden", 1, "Ordner v1"), ("Kunden", 2, "Ordner v2")],
      f"#3965 the folder's playbook arrives with both versions, the folder gina has keeps hers {pbs}")
check(pbs[1][3] == GID and pbs[2][3] is None and pbs[2][4] == "proposal", f"#3965 ... the author only when it was me {pbs}")
r = Gi.get(B + "/api/folders/playbook", params={"folder": "Kunden"})
check(r.ok and r.json().get("text") == "Ordner v2", f"#3965 gina reads the folder's current playbook {r.status_code} {r.text[:160]}")
check(one("SELECT COUNT(*) FROM playbooks WHERE owner_id=?", (OID,)) == 0, "#3965 no playbook lands with otto")

# the undo: an entry changed since stays
KEEP = one("SELECT id FROM budget_entries WHERE list_id=? AND rmonth=''", (BL or 0,))
kt.dbx("UPDATE budget_entries SET updated_at='2099-01-01T00:00:00Z' WHERE id=?", (KEEP or 0,))
check(IMP and Gi.post(B + f"/api/imports/{IMP}/undo", json={}).ok, "the undo")
check(one("SELECT COUNT(*) FROM hub_absences WHERE deleted_at IS NULL") == 0, "#3965 the undo takes the absences away again")
check([(t[0], t[1]) for t in kt.dbx("SELECT month, state FROM time_sheets WHERE user_id=? ORDER BY month", (GID,))] == [("2026-08", "open")],
      "#3965 ... the timesheet too, gina's own month stays")
left = {t: one(f"SELECT COUNT(*) FROM {t} WHERE list_id=?", (BL or 0,)) for t in ("budget_cats", "budget_recurring", "budget_entries")}
check(left == {"budget_cats": 0, "budget_recurring": 0, "budget_entries": 1} and one("SELECT id FROM budget_entries WHERE list_id=?", (BL or 0,)) == KEEP,
      f"#3965 ... the budget rows too, the entry changed since stays {left}")
check([(p[0], p[2]) for p in kt.dbx("SELECT folder, version, body FROM playbooks WHERE list_id IS NULL AND owner_id=?", (GID,))] == [("Bestand", "Gina eigen")],
      "#3965 ... the folder's playbook too, gina's own stays")
now = {t: one(f"SELECT COUNT(*) FROM {t} WHERE list_id=?", (OLIST,)) for t in OTTO_BUD}
check(now == OTTO_BUD and one("SELECT COUNT(*) FROM lists WHERE id=? AND deleted_at IS NULL", (OLIST,)) == 1, f"#3965 otto's list is untouched {now}")

sys.exit(kt.done("p2584_d_umz_rest"))
