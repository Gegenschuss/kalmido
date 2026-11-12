#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1005.0 (#5415, stage 4d of the core's trash, part E): the copies an older version put into office_trash go back into
their tables as rows of the core's trash (office/okern.py ofk_copies_back, every start; one way), and the readers of the
travel costs never offer a draft of the trash. Invented names and figures only.
 - old copies made by hand as office/otrash.py otb_put did before 2.1005 (the row as a copy, the row deleted): a draft with
   two positions and a number, a trip with its receipt, a service (master data) -> written back: each a row with deleted_at /
   deleted_by of the copy, the copy gone from office_trash, listed in the office trash as the core's kind (odoc, otrip,
   omd_services), restored through the core: the draft with its positions and its number, the trip with its receipt, the
   service live; another organisation 404
 - a copy whose row is there again (a conflict) is left in office_trash and counted, never listed; a copy of a kind not on
   the core's trash (the start balance of the cash flow) stays a copy and is still listed and restored
 - a written-back draft whose copy is older than the trash period: the core's retention run deletes it for good
 - the copies' routes of the other kinds are gone: POST /api/office/trash/<id>/restore of a draft's copy 404
 - travel costs (#5415 D, d_leser.md): a draft of the trash is never offered for billing (bill-docs), billing onto it 404, a
   receipt billed on it counts as open again, its project title is no project of the trip form
 - 2.1055.0 (#5791, fable 2.1005 F5): that receipt billed on another invoice meanwhile -> the draft's restore takes its position
   out (taken, note), the other invoice keeps it; a receipt billed nowhere else comes back bound to the draft's position
 - 2.1055.0 (#5791, F6): the copies' run reads only ids first, loads each copy on its own (never the start balance's), and asks
   the catalog for a table's columns once per run
freelancer-matrix: office (a person without an organisation: every step in her personal office)
tenant-matrix: office (another organisation: 404 on the restore of a written-back draft)
usage: p21005_e_copies_back_test.py <datadir>"""
import json
import os
import sys
from datetime import timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P21005E")
OFC = B + "/api/office"
T = OFC + "/trips"
TODAY = testclock.today()
PM = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=10)
PM1 = PM.isoformat()
NEW = ("deleted_at", "deleted_by", "rev", "updated_by", "trash_refs")  # the columns the core added (a copy before 2.1005 has none)

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "office", "clients"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
OLGA = r.json().get("id")
check(A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": OLGA}).ok, "setup: another organisation")
Ol = sess("olga")
Ol.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ORG2 = dbx("SELECT id FROM orgs WHERE name='Other Example'")[0][0]
Ol.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
AID = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
FID, Fr = freelancer(B, A)
Fr.get(OFC + "/settings")  # the personal office comes with the first office call
PERS = dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]


def row_json(table, rid):
    return json.loads(dbx(f"SELECT CAST(row_to_json(x) AS TEXT) FROM {table} x WHERE id=?", (rid,))[0][0])


def old_copy(oid, uid, kind, table, rid, label, children=(), sub="", when="2026-11-09T10:00:00.000Z", delete=True):
    """Row rid of table (+ children: [(table, column)] of rows pointing at it) as a copy in office_trash, the row deleted, as
    office/otrash.py otb_put did before 2.1005 -> the copy's id."""
    rows = [[table, [{k: v for k, v in row_json(table, rid).items() if k not in NEW}]]]
    for t, col in children:
        rows.append([t, [{k: v for k, v in json.loads(x[0]).items() if k not in NEW}
                         for x in dbx(f"SELECT CAST(row_to_json(x) AS TEXT) FROM {t} x WHERE {col}=? ORDER BY id", (rid,))]])
    tid = dbx("INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
              (oid, kind, sub, rid, label, json.dumps({"rows": rows, "nulls": []}), uid, when))[0][0]
    if delete:
        dbx(f"DELETE FROM {table} WHERE id=?", (rid,))
    return tid


def copies_back():
    """What every start does (kalmido/startup.py after init_db): here by hand, inside the server's container."""
    out = in_app("from kalmido.office.okern import ofk_copies_back\nprint('BACK', ofk_copies_back(c))\nc.commit()")
    check("BACK" in out, f"the copies' run {out[-300:]}")
    return out


def trash(s, core=None):
    r = s.get(OFC + "/trash")
    items = r.json().get("items", []) if r.ok else []
    return [x for x in items if core is None or x.get("core") == core]


def deleted(table, rid):
    r = dbx(f"SELECT deleted_at, deleted_by FROM {table} WHERE id=?", (rid,))
    return r[0] if r else None


def scenario(S, who, oid, uid):
    # ------------------------------------------------------------ old copies of the kinds on the core's trash
    r = S.post(OFC + "/docs", json={"kind": "offer", "lang": "en", "project_title": f"Example Spot {who}",
                                  "items": [{"title": "Concept", "qty": 1, "rate": 800}, {"title": "Shoot", "qty": 2, "rate": 900}]})
    check(r.status_code == 201, f"{who}: setup a draft {r.text[:200]}")
    did = r.json()["id"]
    num = f"EX-{who}-7"
    dbx("UPDATE office_docs SET number=? WHERE id=?", (num, did))
    its = sorted(x[0] for x in dbx("SELECT id FROM office_doc_items WHERE doc_id=?", (did,)))
    td = old_copy(oid, uid, "doc", "office_docs", did, f"Example Spot {who}", children=[("office_doc_items", "doc_id")], sub="offer")
    r = S.post(T, json={"date_from": PM1, "date_to": PM1, "dest": f"Example Harbour {who}",
                        "items": [{"date": PM1, "category": "train", "amount": "59.90", "currency": "EUR"}]})
    check(r.status_code == 201, f"{who}: setup a trip {r.text[:200]}")
    trip, item = r.json()["id"], r.json()["items"][0]["id"]
    tt = old_copy(oid, uid, "trip", "office_trips", trip, f"Example Harbour {who}", children=[("office_trip_items", "trip_id")])
    svc = S.post(OFC + "/services", json={"name_de": f"Example Grading {who}"}).json()["id"]
    ts = old_copy(oid, uid, "services", "office_services", svc, f"Example Grading {who}")
    # a conflict: its row is there again (restored meanwhile by hand) - the copy is left and never listed
    svc2 = S.post(OFC + "/services", json={"name_de": f"Example Colour {who}"}).json()["id"]
    tc = old_copy(oid, uid, "services", "office_services", svc2, f"Example Colour {who}", delete=False)
    # a kind not on the core's trash: the start balance stays a copy
    check(S.put(OFC + "/cashflow/start", json={"amount": "700.00", "day": PM1}).ok, f"{who}: setup start balance")
    r = S.delete(OFC + "/cashflow/start")
    tcs = r.json().get("trash_id") if r.ok else None
    check(tcs, f"{who}: the start balance goes with a copy {r.text[:200]}")
    check(S.post(OFC + f"/trash/{td}/restore").status_code == 404, f"{who}: the copies' restore of a draft is gone (404)")

    out = copies_back()
    check(not dbx("SELECT 1 FROM office_trash WHERE id IN (?, ?, ?)", (td, tt, ts)), f"{who}: the three copies left office_trash {out[-200:]}")
    for table, rid in (("office_docs", did), ("office_trips", trip), ("office_services", svc)):
        d = deleted(table, rid)
        check(d and d[0] and d[1] == uid, f"{who}: {table} {rid} is a row of the core's trash (deleted_at, deleted_by of the copy) {d}")
    d, t0 = deleted("office_trip_items", item), deleted("office_trips", trip)
    check(d and d[0] == t0[0] and d[1] is None, f"{who}: its receipt in the trash with it (a child: the trip's time only, core/writes.py _kids_trash) {d}")
    check(sorted(x[0] for x in dbx("SELECT id FROM office_doc_items WHERE doc_id=? AND deleted_at IS NULL", (did,))) == its,
          f"{who}: the draft's positions are back with it (live, the draft hides them)")
    check(dbx("SELECT number FROM office_docs WHERE id=?", (did,))[0][0] == "", f"{who}: the number is free while it lies in the trash")
    check(dbx("SELECT 1 FROM office_trash WHERE id=?", (tc,)) and not [x for x in trash(S) if x["id"] == tc and not x.get("core")],
          f"{who}: the conflict copy is left, not listed")
    check(dbx("SELECT 1 FROM office_trash WHERE id=?", (tcs,)) and [x for x in trash(S) if x["id"] == tcs and x["kind"] == "cf_start"],
          f"{who}: the start balance stays a copy and is listed")
    check(S.get(OFC + f"/docs/{did}").status_code == 404 and trip not in [t["id"] for t in S.get(T, params={"year": PM1[:4]}).json().get("trips", [])],
          f"{who}: the draft and the trip are not in the office")
    lst = trash(S)
    check([x for x in lst if x.get("core") == "odoc" and x["id"] == did and x["sub"] == "offer"], f"{who}: the draft is listed (odoc)")
    check([x for x in lst if x.get("core") == "otrip" and x["id"] == trip], f"{who}: the trip is listed (otrip)")
    check(not [x for x in lst if x.get("core") == "otripitem" and x["id"] == item], f"{who}: its receipt is no entry of its own")
    check([x for x in lst if x.get("core") == "omd_services" and x["id"] == svc], f"{who}: the service is listed (omd_services)")
    check(Ol.post(OFC + f"/trash/core/odoc/{did}/restore").status_code in (403, 404), f"{who}: another organisation: 404")  # tenant
    # ------------------------------------------------------------ restored through the core
    r = S.post(OFC + f"/trash/core/odoc/{did}/restore")
    d = S.get(OFC + f"/docs/{did}").json() if r.ok else {}
    check(r.ok and d.get("number") == num and [x["title"] for x in d.get("items") or []] == ["Concept", "Shoot"],
          f"{who}: the draft comes back with its number and positions {r.text[:200]} {d.get('number')}")
    r = S.post(OFC + f"/trash/core/otrip/{trip}/restore")
    t = next((x for x in S.get(T, params={"year": PM1[:4]}).json().get("trips", []) if x["id"] == trip), None)
    check(r.ok and t and [x["id"] for x in t.get("items") or []] == [item], f"{who}: the trip comes back with its receipt {r.text[:200]}")
    r = S.post(OFC + f"/trash/core/omd_services/{svc}/restore")
    check(r.ok and deleted("office_services", svc) == (None, None), f"{who}: the service comes back live {r.text[:200]}")
    r = S.post(OFC + f"/trash/{tcs}/restore")
    st = S.get(OFC + "/cashflow/start").json().get("start") or {}
    check(r.ok and st.get("amount") == "700.00", f"{who}: the start balance's copy comes back {r.text[:200]} {st}")
    # ------------------------------------------------------------ an old copy past the trash period: the core's retention run
    r = S.post(OFC + "/docs", json={"kind": "invoice", "lang": "en", "project_title": f"Example Old {who}"})
    old = r.json()["id"]
    old_copy(oid, uid, "doc", "office_docs", old, f"Example Old {who}", sub="invoice", when="2020-01-02T03:04:05.000Z")
    copies_back()
    out = in_app("from kalmido.core.writes import obj_trash_prune\nprint('PURGED', obj_trash_prune(c, 'odoc', purge=True))\nc.commit()")
    check(not dbx("SELECT 1 FROM office_docs WHERE id=?", (old,)), f"{who}: the old draft is deleted for good by the core's run {out[-200:]}")

    # ------------------------------------------------------------ travel costs never offer a draft of the trash
    r = S.post(OFC + "/docs", json={"kind": "invoice", "lang": "en", "project_title": f"Example Travel Bill {who}"})
    inv = r.json()["id"]
    r = S.post(T, json={"date_from": PM1, "date_to": PM1, "dest": f"Example Dock {who}",
                        "items": [{"date": PM1, "category": "taxi", "amount": "19.00", "currency": "EUR"}]})
    trip2, rc = r.json()["id"], r.json()["items"][0]["id"]
    check(inv in [x["id"] for x in S.get(T + "/bill-docs").json().get("docs", [])], f"{who}: setup: the draft is offered for billing")
    r = S.post(T + "/bill", json={"doc_id": inv, "item_ids": [rc]})
    check(r.ok, f"{who}: setup: the receipt billed on the draft {r.text[:200]}")
    r = S.delete(OFC + f"/docs/{inv}")
    check(r.ok and (r.json().get("trash") or {}).get("id") == inv, f"{who}: the draft into the core's trash {r.text[:200]}")
    check(inv not in [x["id"] for x in S.get(T + "/bill-docs").json().get("docs", [])], f"{who}: a draft of the trash is not offered for billing")
    check(S.post(T + "/bill", json={"doc_id": inv, "item_ids": [rc]}).status_code == 404, f"{who}: billing onto a draft of the trash 404")
    j = S.get(T, params={"year": PM1[:4]}).json()
    t = next((x for x in j.get("trips", []) if x["id"] == trip2), {})
    check([x.get("billed") for x in t.get("items") or []] == [None], f"{who}: its receipt counts as open (not billed on the trash) {t.get('items')}")
    check(f"Example Travel Bill {who}" not in (j.get("projects") or []), f"{who}: its project title is no project of the trip form {j.get('projects')}")
    # ------------------------------------------------------------ 2.1055.0 (#5791, fable 2.1005 F5): never billed twice
    # the open receipt goes onto another invoice meanwhile; the draft's restore takes its position out and says so
    r = S.post(OFC + "/docs", json={"kind": "invoice", "lang": "en", "project_title": f"Example Second Bill {who}"})
    inv2 = r.json()["id"]
    r = S.post(T + "/bill", json={"doc_id": inv2, "item_ids": [rc]})
    check(r.ok, f"{who}: (5791) the open receipt billed on another invoice {r.text[:200]}")
    r = S.post(OFC + f"/trash/core/odoc/{inv}/restore")
    j = r.json() if r.ok else {}
    d = S.get(OFC + f"/docs/{inv}").json() if r.ok else {}
    check(r.ok and j.get("taken") == 1 and "billed on another document" in (j.get("note") or ""),
          f"{who}: (5791) the restore names the position taken out {r.text[:300]}")
    check(r.ok and not [x for x in d.get("items") or [] if "Taxi" in (x.get("title") or "")] and float((d.get("totals") or {}).get("net") or 0) == 0,
          f"{who}: (5791) the restored draft no longer carries the receipt's position (sums recalculated) {d.get('items')} {d.get('totals')}")
    d2 = S.get(OFC + f"/docs/{inv2}").json()
    check([x for x in d2.get("items") or [] if "Taxi" in (x.get("title") or "")], f"{who}: (5791) the other invoice keeps its position {d2.get('items')}")
    check(dbx("SELECT billed_doc_id FROM office_trip_items WHERE id=?", (rc,))[0][0] == inv2, f"{who}: (5791) the receipt stays billed on the other invoice")
    # a receipt still billed on the draft only: its position comes back with it, the receipt bound to it as before
    r = S.post(T, json={"date_from": PM1, "date_to": PM1, "dest": f"Example Pier {who}",
                        "items": [{"date": PM1, "category": "taxi", "amount": "23.00", "currency": "EUR"}]})
    rc3 = r.json()["items"][0]["id"]
    pos3 = (S.post(T + "/bill", json={"doc_id": inv, "item_ids": [rc3]}).json().get("positions") or [None])[0]
    check(S.delete(OFC + f"/docs/{inv}").ok, f"{who}: (5791) the draft into the trash again")
    r = S.post(OFC + f"/trash/core/odoc/{inv}/restore")
    d = S.get(OFC + f"/docs/{inv}").json() if r.ok else {}
    check(r.ok and not r.json().get("taken") and pos3 in [x["id"] for x in d.get("items") or []],
          f"{who}: (5791) a position whose receipt is billed nowhere else comes back {r.text[:200]}")
    check(dbx("SELECT billed_doc_id, billed_item_id FROM office_trip_items WHERE id=?", (rc3,))[0] == (inv, pos3),
          f"{who}: (5791) its receipt is billed on the draft as before")
    # review: the other invoice lies in the trash itself by the restore (it bills nothing): the position stays, the receipt bound back
    r = S.post(T, json={"date_from": PM1, "date_to": PM1, "dest": f"Example Quay {who}",
                        "items": [{"date": PM1, "category": "taxi", "amount": "31.00", "currency": "EUR"}]})
    rc4 = r.json()["items"][0]["id"]
    pos4 = (S.post(T + "/bill", json={"doc_id": inv, "item_ids": [rc4]}).json().get("positions") or [None])[0]
    check(S.delete(OFC + f"/docs/{inv}").ok, f"{who}: (5791) setup: the draft into the trash once more")
    inv3 = S.post(OFC + "/docs", json={"kind": "invoice", "lang": "en", "project_title": f"Example Third Bill {who}"}).json()["id"]
    check(S.post(T + "/bill", json={"doc_id": inv3, "item_ids": [rc4]}).ok and S.delete(OFC + f"/docs/{inv3}").ok,
          f"{who}: (5791) setup: billed on a third invoice, that one into the trash too")
    r = S.post(OFC + f"/trash/core/odoc/{inv}/restore")
    d = S.get(OFC + f"/docs/{inv}").json() if r.ok else {}
    check(r.ok and not r.json().get("taken") and pos4 in [x["id"] for x in d.get("items") or []]
          and dbx("SELECT billed_doc_id, billed_item_id FROM office_trip_items WHERE id=?", (rc4,))[0] == (inv, pos4),
          f"{who}: (5791) an invoice of the trash bills nothing: the position stays, the receipt bound to the draft {r.text[:200]}")
    # review: time entries billed as ONE position; one of them billed elsewhere meanwhile -> the position goes, the other is open
    r = S.post(OFC + "/docs", json={"kind": "invoice", "lang": "en", "project_title": f"Example Hours {who}",
                                  "items": [{"title": "Hours", "qty": 2, "unit": "hour", "rate": 90}]})
    dh = r.json()["id"]
    ph = dbx("SELECT id FROM office_doc_items WHERE doc_id=?", (dh,))[0][0]
    other = S.post(OFC + "/docs", json={"kind": "invoice", "lang": "en", "project_title": f"Example Other Hours {who}",
                                        "items": [{"title": "Hours", "qty": 1, "unit": "hour", "rate": 90}]}).json()["id"]
    po = dbx("SELECT id FROM office_doc_items WHERE doc_id=?", (other,))[0][0]
    es = [dbx("INSERT INTO time_entries(user_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at, billed_doc_id, billed_item_id, billed_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id", (uid, "Example Edit", f"{PM1}T0{h}:00:00Z", f"{PM1}T0{h + 1}:00:00Z", 3600, "", "manual",
                                                               f"{PM1}T10:00:00Z", f"{PM1}T10:00:00Z", dh, ph, f"{PM1}T10:00:00Z"))[0][0] for h in (1, 3)]
    check(S.delete(OFC + f"/docs/{dh}").ok, f"{who}: (5791) setup: the hours draft into the trash")
    check(dbx("SELECT COUNT(*) FROM time_entries WHERE id IN (?, ?) AND billed_doc_id IS NULL", tuple(es))[0][0] == 2, f"{who}: (5791) setup: its times are open")
    dbx("UPDATE time_entries SET billed_doc_id=?, billed_item_id=?, billed_at=? WHERE id=?", (other, po, f"{PM1}T11:00:00Z", es[0]))  # as from-time did
    r = S.post(OFC + f"/trash/core/odoc/{dh}/restore")
    d = S.get(OFC + f"/docs/{dh}").json() if r.ok else {}
    check(r.ok and r.json().get("taken") == 1 and ph not in [x["id"] for x in d.get("items") or []],
          f"{who}: (5791) the hours position goes: one of its times is billed elsewhere {r.text[:200]}")
    check(dbx("SELECT billed_doc_id, billed_item_id FROM time_entries WHERE id=?", (es[1],))[0] == (None, None)
          and dbx("SELECT billed_doc_id FROM time_entries WHERE id=?", (es[0],))[0][0] == other,
          f"{who}: (5791) its other time is open again (never billed without a position), the first stays on the other invoice")


scenario(A, "alice", ORG, AID)
scenario(Fr, "frida", PERS, FID)

# ------------------------------------------------------------ review 2.1005.0 (F1, F2): hardening of the copies' step
# a copy the step cannot read (valid JSON, but no object / no rows) stays a copy and never stops the run (nor the start)
bad = [dbx("INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
           (ORG, "doc", "offer", 0, "broken", snap, AID, "2026-11-09T10:00:00.000Z"))[0][0] for snap in ("null", "[]", '{"rows": [["office_docs"]]}')]
# a copy filed under another organisation than its row's: never written back into either area
r = A.post(OFC + "/services", json={"name_de": "Example Foreign Grading"})
fsvc = r.json()["id"]
tf = old_copy(ORG2, OLGA, "services", "office_services", fsvc, "Example Foreign Grading")
out = copies_back()
check("Traceback" not in out and "BACK" in out, f"(F1) unreadable copies do not stop the run {out[-300:]}")
check(len(dbx("SELECT id FROM office_trash WHERE id IN (?,?,?)", tuple(bad))) == 3, "(F1) the unreadable copies stay copies")
check(not dbx("SELECT 1 FROM office_services WHERE id=?", (fsvc,)) and dbx("SELECT 1 FROM office_trash WHERE id=?", (tf,)),
      f"(F2) a copy filed under another organisation is not written back (stays a copy) {out[-200:]}")
check(not [x for x in trash(Ol) if x.get("id") == fsvc], "(F2) the other organisation's office trash does not list it")

# ------------------------------------------------------------ 2.1055.0 (#5791, fable 2.1005 F6): the run on every start reads only
# the ids of the copies first (never every snapshot of the table at once, never the start balance's copies kept here) and asks
# the catalog for a table's columns once per run
check(A.put(OFC + "/cashflow/start", json={"amount": "400.00", "day": PM1}).ok and A.delete(OFC + "/cashflow/start").ok,
      "(F6) setup: a start balance's copy kept in office_trash")
cs = dbx("SELECT id FROM office_trash WHERE kind='cf_start' ORDER BY id DESC LIMIT 1")[0][0]
out = in_app("""from kalmido.office.okern import ofk_copies_back
q = []
class W:
    def __init__(s, c):
        s.c = c
    def execute(s, sql, *a):
        q.append((sql, a))
        return s.c.execute(sql, *a)
    def __getattr__(s, n):
        return getattr(s.c, n)
print('BACK', ofk_copies_back(W(c)))
print('ALLSNAPS', any('FROM office_trash' in x and 'SELECT *' in x and 'WHERE id=' not in x for x, _a in q))
print('LOADED', sorted(a[0][0] for x, a in q if x.startswith('SELECT * FROM office_trash WHERE id=') and a))
cat = [a[0][0] for x, a in q if 'information_schema.columns' in x and a]
print('CATALOG', len(cat) == len(set(cat)))
c.rollback()""")
check("ALLSNAPS False" in out, f"(F6) never every snapshot of office_trash at once {out[-300:]}")
ld = next((json.loads(x[7:]) for x in out.splitlines() if x.startswith("LOADED ")), None)
check(ld is not None and cs not in ld and tf in ld, f"(F6) the start balance's copy is never loaded, a copy of another kind is {out[-300:]}")
check("CATALOG True" in out, f"(F6) a table's columns asked once per run {out[-300:]}")

# ------------------------------------------------------------ 2.1005.0 (#5415, merge with #5494): an old sign-off record's copy
# (office/signoff.py sig_gone_delete before 2.1004 put an orphaned video review's record into office_trash, kind signoff): it
# comes back as a row of the core's trash (kind osignoff) - an organisation's into its area, a private one (org_id NULL) into its
# creator's personal office, as the copy named it (okern._copy_back: ofk_office_of, not org_id alone)


def old_sig(org, by, title, filed):
    tok = os.urandom(8).hex()
    sid = dbx("""INSERT INTO office_signoffs(org_id, kind, title, token_hash, token, state, created_by, created_at)
                 VALUES(?,'video',?,?,?,'open',?,?) RETURNING id""", (org, title, tok, tok, by, "2026-11-01T10:00:00+00:00"))[0][0]
    return sid, old_copy(filed, by, "signoff", "office_signoffs", sid, title)


s_org, t_org = old_sig(ORG, AID, "Example Rough Cut", ORG)
s_own, t_own = old_sig(None, FID, "Example Private Cut", PERS)
out = copies_back()
check(not dbx("SELECT 1 FROM office_trash WHERE id IN (?, ?)", (t_org, t_own)), f"(5494) both sign-off copies left office_trash {out[-200:]}")
d = deleted("office_signoffs", s_own)
check(d and d[0] and d[1] == FID and dbx("SELECT org_id FROM office_signoffs WHERE id=?", (s_own,))[0][0] is None,
      f"(5494) the private record is a row of the core's trash, still without an organisation {d}")
check([x for x in trash(Fr, "osignoff") if x["id"] == s_own] and not [x for x in trash(A, "osignoff") if x["id"] == s_own],
      "(5494) listed in its creator's personal office trash only")
check([x for x in trash(A, "osignoff") if x["id"] == s_org], "(5494) the organisation's record is listed in its office trash")
r = Fr.post(OFC + f"/trash/core/osignoff/{s_own}/restore")
check(r.ok and deleted("office_signoffs", s_own) == (None, None), f"(5494) its creator restores it {r.text[:200]}")
sys.exit(done("p21005_e_copies_back"))
