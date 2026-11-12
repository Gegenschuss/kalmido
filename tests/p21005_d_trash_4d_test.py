#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1005.0 (#5415, stage 4d of the core's trash, part D): trips, their travel receipts, the trips of a per diem import taken
back and the positions of a credit card statement are deleted into the ONE trash of the core (office/okern.py ofk_register ->
core/writes.py obj_trash) instead of a copy in office_trash and the row deleted. Invented names and figures only.
 - a trip with two receipts: delete -> the row stays with deleted_at (its receipts with it), gone from the list, the per diem
   report and its CSV, the evaluation and the EUeR -> in the office trash (core otrip, the destination as label; its receipts
   are no entries of their own) -> the undo (POST .../trips/<id>/restore) brings it back with the same ids, everything as
   before; another organisation 404, a member 403 / 404; no step in the person's undo list (the checks of the routes)
 - a single receipt: in the trash, listed (core otripitem); its trip into the trash meanwhile: the receipt's restore 409;
   the trip back without it, then the receipt back
 - the core's retention run deletes a trip of the trash with its receipts for good after the period
 - a per diem import taken back (POST .../trips/delete): each trip in the trash, listed one by one; the office trash's
   restore brings it back unchanged and the run counts as not undone again; a second take-back takes it again
 - a credit card position: delete -> gone from its statement, listed with day and merchant (read at listing) -> the undo
   (POST .../cards/lines/<id>/restore) and the office trash bring it back; the statement confirmed since: 409 on both ways
 - a month locked since: the undo and the office trash's restore of a trip 409, it stays in the trash
 - 2.1005.0 (part E): the old undo routes of the copies are gone (p21005_e_copies_back_test.py)
freelancer-matrix: office (a person without an organisation: every step in her personal office)
tenant-matrix: office (another organisation: 404 on a foreign trip / position of the core's trash)
usage: p21005_d_trash_4d_test.py <datadir>"""
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

fresh(prefix="P21005D")
OFC = B + "/api/office"
T = OFC + "/trips"
K = OFC + "/cards"
TODAY = testclock.today()
PM = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=10)  # the 10th of the previous month (it can be locked)
PM1, PM2 = PM.isoformat(), (PM + timedelta(days=1)).isoformat()
D0 = TODAY.isoformat()

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "office", "clients"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
uid = {}
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
uid["bob"] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
check(A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]}).ok, "setup: another organisation")
Bo, Ol = sess("bob"), sess("olga")
for s in (Bo, Ol):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ORG2 = dbx("SELECT id FROM orgs WHERE name='Other Example'")[0][0]
Ol.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
AID = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
FID, Fr = freelancer(B, A)


def live(table, rid):
    return bool(dbx(f"SELECT 1 FROM {table} WHERE id=? AND deleted_at IS NULL", (rid,)))


def there(table, rid):
    return bool(dbx(f"SELECT 1 FROM {table} WHERE id=?", (rid,)))


def trash(s, core=None):
    r = s.get(OFC + "/trash")
    items = r.json().get("items", []) if r.ok else []
    return [x for x in items if core is None or x.get("core") == core]


def trip_ids(s, year):
    r = s.get(T, params={"year": year})
    return [t["id"] for t in r.json().get("trips", [])] if r.ok else None


def scenario(S, who, me, member=None):
    y = PM1[:4]
    # ------------------------------------------------------------ a trip with two receipts (with a per diem)
    dest = f"Example Harbour {who}"
    r = S.post(T, json={"date_from": PM1, "date_to": PM2, "dest": dest, "overnight": True, "people": [{"id": me}],
                        "items": [{"date": PM1, "category": "train", "amount": "59.90", "currency": "EUR"},
                                  {"date": PM2, "category": "hotel", "amount": "120.00", "currency": "EUR"}]})
    check(r.status_code == 201 and len(r.json().get("items") or []) == 2, f"{who}: setup a trip with two receipts {r.text[:200]}")
    trip = r.json()["id"]
    items = sorted(x["id"] for x in r.json()["items"])
    vma0 = S.get(T + "/vma", params={"year": y}).json()
    in_vma = lambda j: any(t["id"] == trip for p in j.get("people", []) for t in p.get("trips", []))  # noqa: E731
    check(in_vma(vma0), f"{who}: the per diem report has the trip {json.dumps(vma0)[:200]}")
    csv0 = S.get(T + "/vma.csv", params={"year": y})
    check(csv0.ok and dest in csv0.text, f"{who}: the per diem CSV names the trip {csv0.status_code}")
    rep0 = S.get(T + "/report", params={"by": "month"}).json()
    euer0 = S.get(OFC + "/books/euer", params={"year": y})
    check(rep0.get("count") == 2 and euer0.ok, f"{who}: the evaluation counts both receipts {rep0} {euer0.status_code}")

    if member is not None:  # the admin's trip: a member (level "own") cannot delete it
        check(member.delete(T + f"/{trip}").status_code in (403, 404) and live("office_trips", trip), f"{who}: a member cannot delete it")
    check(Ol.delete(T + f"/{trip}").status_code in (403, 404) and live("office_trips", trip), f"{who}: another organisation cannot delete it")
    r = S.delete(T + f"/{trip}")
    check(r.ok and r.json().get("trash") == {"kind": "otrip", "id": trip} and r.json().get("trip", {}).get("dest") == dest,
          f"{who}: the trip goes into the core's trash {r.text[:200]}")
    check(there("office_trips", trip) and not live("office_trips", trip) and not any(live("office_trip_items", i) for i in items)
          and all(there("office_trip_items", i) for i in items), f"{who}: the rows stay with deleted_at, the receipts with it")
    check(not dbx("SELECT 1 FROM office_trash WHERE kind='trip' AND ref_id=?", (trip,)), f"{who}: no copy in office_trash any more")
    lst = trip_ids(S, y)
    check(lst is not None and trip not in lst, f"{who}: gone from the list {lst}")
    check(S.get(T + f"/{trip}/history").status_code == 404 and S.patch(T + f"/{trip}", json={"dest": "X"}).status_code == 404,
          f"{who}: its address 404 (history, save)")
    check(S.post(T + f"/{trip}/items", json={"date": PM1, "category": "taxi", "amount": "9.00"}).status_code == 404, f"{who}: no receipt into a trip of the trash")
    check(not in_vma(S.get(T + "/vma", params={"year": y}).json()), f"{who}: gone from the per diem report")
    csv1 = S.get(T + "/vma.csv", params={"year": y})
    check(csv1.ok and dest not in csv1.text, f"{who}: gone from the per diem CSV")
    rep1 = S.get(T + "/report", params={"by": "month"}).json()
    check(rep1.get("count") == 0, f"{who}: gone from the evaluation {rep1}")
    euer1 = S.get(OFC + "/books/euer", params={"year": y})
    check(euer1.ok and euer1.json() != euer0.json(), f"{who}: the EUeR no longer counts its receipts")
    t = [x for x in trash(S, "otrip") if x["id"] == trip]
    check(len(t) == 1 and t[0]["kind"] == "trip" and dest in t[0]["label"] and PM1 in t[0]["label"], f"{who}: in the office trash with destination and days {t}")
    check(not [x for x in trash(S, "otripitem") if x["id"] in items], f"{who}: its receipts are no entries of their own")
    check(not dbx("SELECT 1 FROM obj_undo WHERE kind='otrip' AND ref_id=? AND mode IN ('trash', 'restore')", (trip,)),
          f"{who}: no step in the person's undo list (the route's checks)")
    check(Ol.post(T + f"/{trip}/restore").status_code in (403, 404) and not live("office_trips", trip), f"{who}: another organisation: the undo 404")  # tenant: POST /api/office/trips/{}/restore
    check(Ol.post(OFC + f"/trash/core/otrip/{trip}/restore").status_code in (403, 404) and not live("office_trips", trip),
          f"{who}: another organisation: the office trash's restore 404")
    if member is not None:
        check(member.post(T + f"/{trip}/restore").status_code in (403, 404) and not live("office_trips", trip), f"{who}: a member: the undo 403 / 404")
    r = S.post(T + f"/{trip}/restore")
    check(r.ok and r.json().get("id") == trip and sorted(x["id"] for x in r.json().get("items") or []) == items,
          f"{who}: the undo brings the trip back with its receipts (same ids) {r.text[:200]}")
    check(trip in (trip_ids(S, y) or []) and in_vma(S.get(T + "/vma", params={"year": y}).json())
          and S.get(T + "/report", params={"by": "month"}).json().get("count") == 2 and S.get(OFC + "/books/euer", params={"year": y}).json() == euer0.json(),
          f"{who}: back in the list, the per diem, the evaluation and the EUeR as before")
    check(not [x for x in trash(S, "otrip") if x["id"] == trip], f"{who}: out of the office trash")

    # ------------------------------------------------------------ a single receipt; its trip into the trash meanwhile
    r = S.delete(T + f"/{trip}/items/{items[0]}")
    check(r.ok and r.json().get("trash") == {"kind": "otripitem", "id": items[0]} and len(r.json()["trip"]["items"]) == 1,
          f"{who}: a receipt into the trash {r.text[:200]}")
    t = [x for x in trash(S, "otripitem") if x["id"] == items[0]]
    check(len(t) == 1 and t[0]["kind"] == "trip_item" and PM1 in t[0]["label"], f"{who}: the receipt in the office trash with its day {t}")
    check(S.get(T + "/report", params={"by": "month"}).json().get("count") == 1, f"{who}: the evaluation counts one receipt")
    check(S.delete(T + f"/{trip}").ok, f"{who}: the trip into the trash too")
    r = S.post(OFC + f"/trash/core/otripitem/{items[0]}/restore")
    check(r.status_code == 409 and "trash" in r.text and not live("office_trip_items", items[0]), f"{who}: the receipt of a trip in the trash: 409 {r.status_code} {r.text[:200]}")
    check(S.post(T + f"/{trip}/items/{items[0]}/restore").status_code == 404, f"{who}: the receipt's undo: its trip is not there (404)")
    check(Ol.post(T + f"/{trip}/items/{items[0]}/restore").status_code in (403, 404), f"{who}: another organisation: the receipt's undo 404")  # tenant: POST /api/office/trips/{}/items/{}/restore
    r = S.post(OFC + f"/trash/core/otrip/{trip}/restore")
    check(r.ok and r.json().get("kind") == "trip" and live("office_trips", trip) and live("office_trip_items", items[1]) and not live("office_trip_items", items[0]),
          f"{who}: the office trash brings the trip back with the receipt that went with it, not the one deleted before {r.text[:200]}")
    r = S.post(T + f"/{trip}/items/{items[0]}/restore")
    check(r.ok and sorted(x["id"] for x in r.json().get("items") or []) == items, f"{who}: then the receipt's undo brings it back {r.text[:200]}")

    # ------------------------------------------------------------ a per diem import taken back
    r = S.post(T + "/import", json={"trips": [{"date_from": D0, "dest": f"Example Import A {who}", "purpose": "job", "people": [{"id": me}]},
                                              {"date_from": D0, "dest": f"Example Import B {who}", "purpose": "job", "people": [{"id": me}]}]})
    check(r.status_code == 201 and r.json()["created"] == 2, f"{who}: setup a trips import {r.text[:200]}")
    tids = sorted(r.json()["ids"])
    r = S.post(T + "/delete", json={"ids": tids})
    check(r.ok and r.json().get("deleted") == 2 and r.json().get("trash") == {"kind": "otrip", "ids": tids} and not any(live("office_trips", i) for i in tids),
          f"{who}: the import taken back: both trips in the trash {r.text[:200]}")
    run = dbx("SELECT r.id, r.undone_at FROM office_import_runs r JOIN office_trips t ON t.import_run_id=r.id WHERE t.id=?", (tids[0],))
    check(run and run[0][1], f"{who}: the run counts as undone {run}")
    check(sorted(x["id"] for x in trash(S, "otrip") if x["id"] in tids) == tids, f"{who}: the office trash lists both trips")
    r = S.post(OFC + f"/trash/core/otrip/{tids[0]}/restore")
    run = dbx("SELECT undone_at FROM office_import_runs WHERE id=?", (run[0][0],)) if run else None
    tr0 = dbx("SELECT created_at, updated_at FROM office_trips WHERE id=?", (tids[0],))
    check(r.ok and live("office_trips", tids[0]) and run and run[0][0] is None and tr0 and tr0[0][0] == tr0[0][1],
          f"{who}: one restored unchanged, its run not undone again {r.text[:200]} {run} {tr0}")
    r = S.post(T + "/delete", json={"ids": tids})
    check(r.ok and r.json().get("deleted") == 1 and not live("office_trips", tids[0]), f"{who}: a second take-back takes the restored trip again {r.text[:200]}")

    # ------------------------------------------------------------ a credit card position
    card = S.post(K, json={"holder_id": me, "last4": "4321"})
    check(card.ok, f"{who}: setup a card {card.status_code} {card.text[:160]}")
    st = S.post(K + f"/{card.json()['id']}/statements", files={"file": ("stmt.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}, data={"month": D0[:7]})
    check(st.ok, f"{who}: setup a statement {st.status_code} {st.text[:160]}")
    sid = st.json()["statement"]["id"]
    keep = S.post(K + f"/statements/{sid}/lines", json={"day": D0, "merchant": "Example Lens Rental", "amount": "10.00"}).json()["line"]["id"]
    lid = S.post(K + f"/statements/{sid}/lines", json={"day": D0, "merchant": "Example Typo Shop", "amount": "2.50"}).json()["line"]["id"]
    lines = lambda: [x["id"] for x in S.get(K + f"/statements/{sid}").json()["lines"]]  # noqa: E731
    check(Ol.delete(K + f"/lines/{lid}").status_code in (403, 404) and live("office_cc_lines", lid), f"{who}: another organisation cannot delete the position")
    r = S.delete(K + f"/lines/{lid}")
    check(r.ok and r.json().get("trash") == {"kind": "occline", "id": lid} and r.json()["line"]["merchant"] == "Example Typo Shop",
          f"{who}: the position into the trash {r.text[:200]}")
    check(there("office_cc_lines", lid) and not live("office_cc_lines", lid) and lines() == [keep], f"{who}: the row stays in the trash, gone from its statement")
    check(S.patch(K + f"/lines/{lid}", json={"merchant": "X"}).status_code == 404, f"{who}: a position of the trash is not saved (404)")
    t = [x for x in trash(S, "occline") if x["id"] == lid]
    check(len(t) == 1 and t[0]["kind"] == "cc_line" and "Example Typo Shop" in t[0]["label"] and D0 in t[0]["label"], f"{who}: in the office trash with day and merchant {t}")
    check(Ol.post(K + f"/lines/{lid}/restore").status_code in (403, 404) and Ol.post(OFC + f"/trash/core/occline/{lid}/restore").status_code in (403, 404)
          and not live("office_cc_lines", lid), f"{who}: another organisation: no restore")  # tenant: POST /api/office/cards/lines/{}/restore
    r = S.post(K + f"/lines/{lid}/restore")
    check(r.ok and r.json()["line"]["id"] == lid and r.json()["line"]["amount"] == "2.50" and sorted(lines()) == sorted([keep, lid]),
          f"{who}: the undo brings the position back with its id and values {r.text[:200]}")
    check(S.delete(K + f"/lines/{lid}").ok, f"{who}: the position into the trash again")
    r = S.post(OFC + f"/trash/core/occline/{lid}/restore")
    check(r.ok and r.json().get("kind") == "cc_line" and live("office_cc_lines", lid), f"{who}: the office trash restores it {r.text[:200]}")
    check(S.delete(K + f"/lines/{lid}").ok, f"{who}: and into the trash once more")
    check(S.patch(K + f"/statements/{sid}", json={"total": "10.00"}).ok and S.post(K + f"/statements/{sid}/confirm", json={}).ok,
          f"{who}: the statement confirmed (without the position of the trash)")
    check(S.post(K + f"/lines/{lid}/restore").status_code == 409 and S.post(OFC + f"/trash/core/occline/{lid}/restore").status_code == 409
          and not live("office_cc_lines", lid), f"{who}: a confirmed statement takes no position back (409 on both ways)")
    check(lines() == [keep], f"{who}: the confirmed statement does not show it")

    # 2.1005.0 (#5415, part E): the old undo routes of the copies (/trips/trash/<id>/restore, /cards/trash/<id>/restore) went
    # with the copies (written back as rows of the core's trash at the start, p21005_e_copies_back_test.py); their checks left

    # ------------------------------------------------------------ a month locked since (last: it locks the month)
    check(S.delete(T + f"/{trip}").ok, f"{who}: the trip into the trash again")
    m = PM1[:7]
    lock = S.post(OFC + "/periods/lock", json={"through": m, "confirm": f"{m[5:7]}/{m[:4]}"})
    check(lock.ok, f"{who}: setup the month of the trip locked {lock.text[:200]}")
    r = S.post(T + f"/{trip}/restore")
    check(r.status_code == 409 and not live("office_trips", trip) and there("office_trips", trip), f"{who}: a month locked since: the undo 409, it stays in the trash {r.text[:200]}")
    r = S.post(OFC + f"/trash/core/otrip/{trip}/restore")
    check(r.status_code == 409 and not live("office_trips", trip), f"{who}: the office trash 409 as well {r.text[:200]}")


scenario(A, "org", AID, member=Bo)
scenario(Fr, "freelancer", FID)

# ---------------------------------------------------------------- the core's retention run (TIMESTAMPTZ columns)
r = A.post(T, json={"date_from": D0, "date_to": D0, "dest": "Example Old Trip", "items": [{"date": D0, "category": "taxi", "amount": "12.00"}]})
OLDT, OLDI = r.json()["id"], r.json()["items"][0]["id"]
YNG = A.post(T, json={"date_from": D0, "date_to": D0, "dest": "Example Young Trip"}).json()["id"]
check(A.delete(T + f"/{OLDT}").ok and A.delete(T + f"/{YNG}").ok, "retention: two trips into the trash")
dbx("UPDATE office_trips SET deleted_at=? WHERE id=?", ("2020-01-02T03:04:05+00:00", OLDT))
dbx("UPDATE office_trip_items SET deleted_at=? WHERE trip_id=?", ("2020-01-02T03:04:05+00:00", OLDT))
out = in_app("""from kalmido.core.writes import obj_trash_prune
print("PURGED", obj_trash_prune(c, "otrip", purge=True))
c.commit()""")
check("PURGED 1" in out and not there("office_trips", OLDT) and not there("office_trip_items", OLDI) and there("office_trips", YNG),
      f"retention: the old trip gone for good with its receipt, the young one stays {out[-300:]}")

sys.exit(done("p21005_d_trash_4d"))
