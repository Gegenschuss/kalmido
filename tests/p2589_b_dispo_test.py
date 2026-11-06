#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.589.0 B API tests (#4571): shoot days of a quotation as pencilled-in bookings of the disposition. Own container
(kt.fresh). Invented people, firms and figures only.
freelancer-matrix: hub
tenant-matrix: hub
 - GET /api/office/docs/<id>/tasks: the field dispo -- one day per shoot part (its shoot days, from the quotation's period of
   service, the next part right after), one open place per person of each crew function; all new and ticked
 - POST .../tasks {pick: [], dispo: {pick}}: only shoot days (no task), a new project; status option, kind slot, the project
   linked, one job per day; the disposition shows them, a filled place (POST /api/team/dispo/bookings/<id>/fill) keeps its
   function, a firm one shows in the person's calendar
 - a new version: the pencilled-in day follows (longer period, an empty place of a function no longer there goes, a removed
   part's empty places go), a firm booking and a filled place stay and are only marked; a change by hand takes the mark off
 - no date in the quotation: the preview asks (not ticked), applying without a date 400 and nothing made, with a date booked
 - the module Disposition off / the industry not Film & Video: a hint, nothing booked (the tasks still work); 409 when sent
 - rights: filling another organisation's place 404, a member filling an admin's place 403, without the module 409
 - a person without an organisation (her own area): the same flow
usage: p2589_b_dispo_test.py <datadir>"""
import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0"})
FEAT = "cal,comments,collab,office,clients,docs,files,fields,time,dispo,workload"
O = "/api/office"
D = O + "/docs"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
CLIENT = {"name": "Beispiel Kunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Musterstadt", "country": "DE"}


def sql(q, args=()):
    return kt.dbx(q, args)


def bookings(oid, root):
    """[(offer_pos, status, kind, rid, label, start, end, mark, slot, list_id, job)] of a chain, living ones."""
    return sql("SELECT offer_pos, status, resource_kind, resource_id, res_label, start, \"end\", offer_mark, slot_name, list_id, job FROM hub_bookings "
               "WHERE org_id=? AND offer_root=? AND deleted_at IS NULL ORDER BY offer_pos", (oid, root))


def shoot(S, who, q, title, days, staff):
    r = S.post(B + f"{D}/{q}/parts", json={"kind": "shoot", "title": title})
    check(r.status_code in (200, 201), f"{who}: the shoot part {title} {r.text[:200]}")
    pid = r.json()["part"]["id"]
    r = S.patch(B + f"{D}/{q}/parts/{pid}", json={"sheet": {"head": {"shoot_days": days, "travel_days": 1, "travel_share": 0.5}, "staff": staff}})
    check(r.ok, f"{who}: the sheet of {title} {r.text[:200]}")
    return pid


def settings(S, packs):
    check(S.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "de", "currency": "EUR", "industry_packs": packs}).ok, f"office settings {packs}")


def scenario(S, who, oid, cam, lig, other=None, other_s=None):
    cl = S.post(B + "/api/clients", json=CLIENT).json().get("id")
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "project_title": f"Imagefilm {who}", "client_id": cl, "service_from": "2027-03-01",
                            "service_to": "2027-03-10", "items": [{"kind": "service", "title": "Konzept", "qty": 1, "unit": "day", "rate": 800}]})
    check(r.status_code == 201, f"{who}: the quotation {r.text[:200]}")
    Q = r.json()["id"]
    shoot(S, who, Q, "Dreh Berlin", 2, [{"role_id": cam, "qty": 2}, {"role_id": lig, "qty": 2}])
    shoot(S, who, Q, "Dreh Hamburg", 1, [{"role_id": cam, "qty": 1}])
    # ------------------------------------------------------------ the preview: two shoot days with their places
    pv = S.get(B + f"{D}/{Q}/tasks").json()
    dp = pv.get("dispo") or {}
    days = dp.get("days") or []
    check(dp.get("on") is True and not dp.get("hint") and len(days) == 2, f"{who}: two shoot days in the preview {dp}")
    d1, d2 = days if len(days) == 2 else ({}, {})
    check(d1.get("start") == "2027-03-01" and d1.get("days") == 2 and d2.get("start") == "2027-03-03" and d2.get("days") == 1,
          f"{who}: the dates from the period of service, the second day after the first {[(x.get('start'), x.get('days')) for x in days]}")
    check([p["name"] for p in d1.get("places", [])] == ["Kamera", "Kamera", "Beleuchter", "Beleuchter"] and [p["name"] for p in d2.get("places", [])] == ["Kamera"],
          f"{who}: one open place per person of a crew function {d1.get('places')} {d2.get('places')}")
    check(all(x["state"] == "new" and x["pick"] and not x["need_date"] for x in days) and "Dreh Berlin" in d1.get("title", ""), f"{who}: new and ticked {days}")
    # ------------------------------------------------------------ apply: only the shoot days, a new project
    r = S.post(B + f"{D}/{Q}/tasks", json={"pick": [], "dispo": {"pick": [d1["key"], d2["key"]]}, "create": {"name": f"Imagefilm {who}"}})
    check(r.status_code == 201 and r.json().get("dispo", {}).get("booked") == 5 and r.json().get("created") == 0 and r.json().get("made_project"),
          f"{who}: five open places booked, no task {r.text[:200]}")
    L = r.json().get("list_id")
    bs = bookings(oid, Q)
    check(len(bs) == 5 and all(b[1] == "option" and b[2] == "slot" and b[3] == 0 and b[9] == L for b in bs), f"{who}: pencilled in, open, the project linked {bs}")
    check(len({b[10] for b in bs}) == 2 and {(b[5], b[6]) for b in bs} == {("2027-03-01", "2027-03-02"), ("2027-03-03", "2027-03-03")},
          f"{who}: one job per shoot day, whole days {bs}")
    check(sql("SELECT COUNT(*) FROM tasks WHERE list_id=? AND deleted_at IS NULL", (L,))[0][0] == 0, f"{who}: no task made")
    pv = S.get(B + f"{D}/{Q}/tasks").json()
    check([x["state"] for x in pv["dispo"]["days"]] == ["same", "same"], f"{who}: the preview again: nothing to do {pv['dispo']['days']}")
    j = S.get(B + "/api/team/dispo", params={"start": "2027-03-01", "days": 7}).json()
    mine = [b for b in j.get("bookings", []) if b.get("offer")]
    check(len(mine) == 5 and all(b["kind"] == "slot" and b["slot"] in ("Kamera", "Beleuchter") and b["status"] == "option" for b in mine),
          f"{who}: the disposition shows the open places {mine}")
    # ------------------------------------------------------------ fill a place, make one firm
    ids, label = {}, {}
    for i, k, lb in sql("SELECT id, offer_pos, slot_name FROM hub_bookings WHERE org_id=? AND offer_root=? AND deleted_at IS NULL", (oid, Q)):
        ids[k], label[k] = i, lb
    kam1 = next(k for k in ids if k.startswith(d1["key"] + ":") and k.endswith(":1") and label[k] == "Kamera")
    lig1 = next(k for k in ids if k.startswith(d1["key"] + ":") and k.endswith(":1") and label[k] == "Beleuchter")
    me_id = S.get(B + "/api/state").json()["me"]["id"]
    who_lig = other or me_id
    r = S.post(B + f"/api/team/dispo/bookings/{ids[lig1]}/fill", json={"kind": "user", "id": who_lig})
    check(r.ok and r.json()["booking"]["kind"] == "user" and r.json()["booking"]["slot"] == "Beleuchter", f"{who}: a place filled, its function kept {r.text[:200]}")
    r = S.post(B + f"/api/team/dispo/bookings/{ids[kam1]}/fill", json={"kind": "user", "id": me_id})
    check(r.ok and S.patch(B + f"/api/team/dispo/bookings/{ids[kam1]}", json={"status": "firm"}).ok, f"{who}: the camera place filled and firm {r.text[:200]}")
    ev = [e for e in S.get(B + "/api/calendars/events", params={"from": "2027-03-01", "to": "2027-03-07"}).json().get("events", []) if e.get("booking") == ids[kam1]]
    check(len(ev) == 1 and ev[0]["all_day"] and ev[0]["end"] == "2027-03-03", f"{who}: the firm shoot day in the calendar like other bookings {ev}")
    # Undo of a fill: the place is open again with its function
    r = S.post(B + f"/api/team/dispo/bookings/{ids[lig1]}/fill", json={"kind": "slot"})
    check(r.ok and r.json()["booking"]["kind"] == "slot" and r.json()["booking"]["label"] == "Beleuchter", f"{who}: opened again {r.text[:200]}")
    check(S.post(B + f"/api/team/dispo/bookings/{ids[lig1]}/fill", json={"kind": "user", "id": who_lig}).ok, f"{who}: filled again")
    if other_s is not None:  # a member fills a place the admin made: 403
        check(other_s.post(B + f"/api/team/dispo/bookings/{ids[kam1]}/fill", json={"kind": "slot"}).status_code == 403, f"{who}: a member on the admin's place 403")
    # ------------------------------------------------------------ a new version: Berlin 3 days, without Beleuchter; Hamburg removed
    r = S.post(B + f"{D}/{Q}/duplicate")
    check(r.status_code == 201 and r.json().get("version_of") == Q, f"{who}: a new version {r.text[:200]}")
    Q2 = r.json()["id"]
    d = S.get(B + f"{D}/{Q2}").json()
    parts = {p["title"]: p["id"] for p in d.get("parts") or []}
    berlin = next(p for p in d["parts"] if p["title"] == "Dreh Berlin")
    cam_row = [{"uid": x["uid"], "qty": 2} for x in berlin["sheet"]["staff"] if x.get("role_id") == cam]  # the same row (its uid), as the editor sends it
    check(len(cam_row) == 1, f"{who}: the camera row of the copy {berlin['sheet'].get('staff')}")
    r = S.patch(B + f"{D}/{Q2}/parts/{parts['Dreh Berlin']}", json={"sheet": {"head": {"shoot_days": 3}, "staff": cam_row}})
    check(r.ok, f"{who}: Berlin changed {r.text[:200]}")
    keep = ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "ref_part_id")
    items = [{k: it.get(k) for k in keep} for it in d["items"] if not (it.get("kind") == "part" and it.get("ref_part_id") == parts["Dreh Hamburg"])]
    check(S.put(B + f"{D}/{Q2}/items", json={"items": items, "parts_known": list(parts.values())}).ok, f"{who}: Hamburg off the title page")
    pv = S.get(B + f"{D}/{Q2}/tasks").json()
    st = {x["key"]: x for x in pv["dispo"]["days"]}
    b1, b2 = st.get(d1["key"], {}), st.get(d2["key"], {})
    check(b1.get("state") == "changed" and b1.get("pick") and b1.get("firm") == 2 and b1.get("start") == "2027-03-01" and b1.get("days") == 3,
          f"{who}: Berlin changed, two bookings only marked (firm / filled) {b1}")
    check(b2.get("state") == "gone" and b2.get("pick"), f"{who}: Hamburg no longer in the quotation {b2}")
    r = S.post(B + f"{D}/{Q2}/tasks", json={"pick": [], "dispo": {"pick": [d1["key"], d2["key"]]}})
    res = r.json().get("dispo", {}) if r.ok else {}
    check(r.ok and res == {"booked": 0, "adapted": 3, "marked": 2}, f"{who}: adapted 1 + 2 gone, 2 marked {r.text[:200]}")
    after = {b[0]: b for b in bookings(oid, Q)}
    kam2 = kam1[:-2] + ":2"
    check(set(after) == {kam1, kam2, lig1}, f"{who}: the empty Beleuchter place and Hamburg's place went {sorted(after)}")
    check(after[kam1][1] == "firm" and (after[kam1][5], after[kam1][6]) == ("2027-03-01", "2027-03-02") and after[kam1][7] == "changed",
          f"{who}: the firm booking untouched, marked {after[kam1]}")
    check(after[kam2][1] == "option" and (after[kam2][5], after[kam2][6]) == ("2027-03-01", "2027-03-03") and after[kam2][7] == "",
          f"{who}: the pencilled-in place follows (3 days) {after[kam2]}")
    check(after[lig1][2] == "user" and after[lig1][7] == "gone", f"{who}: the filled place of a function no longer there: kept, marked {after[lig1]}")
    j = S.get(B + "/api/team/dispo", params={"start": "2027-03-01", "days": 7}).json()
    mk = {b["id"]: b.get("offer_mark") for b in j["bookings"] if b.get("offer")}
    check(mk.get(ids[kam1]) == "changed" and mk.get(ids[lig1]) == "gone", f"{who}: the disposition shows the marks {mk}")
    check(S.patch(B + f"/api/team/dispo/bookings/{ids[kam1]}", json={"end": "2027-03-03"}).ok
          and sql("SELECT offer_mark FROM hub_bookings WHERE id=?", (ids[kam1],)) == [("",)], f"{who}: a change by hand takes the mark off")
    pv = S.get(B + f"{D}/{Q2}/tasks").json()
    check([x["state"] for x in pv["dispo"]["days"]] == ["same"], f"{who}: afterwards nothing left to do {pv['dispo']['days']}")
    # ------------------------------------------------------------ no date in the quotation: the preview asks
    Q3 = S.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl, "items": []}).json()["id"]
    shoot(S, who, Q3, "Dreh ohne Datum", 1, [{"role_id": cam, "qty": 1}])
    check(S.post(B + f"{D}/{Q3}/project", json={"list_id": L}).ok, f"{who}: the dateless quotation in the project")
    dd = S.get(B + f"{D}/{Q3}/tasks").json()["dispo"]["days"]
    check(len(dd) == 1 and dd[0]["need_date"] and dd[0]["start"] is None and not dd[0]["pick"], f"{who}: the preview asks for the date {dd}")
    r = S.post(B + f"{D}/{Q3}/tasks", json={"pick": [], "dispo": {"pick": [dd[0]["key"]]}})
    check(r.status_code == 400 and not bookings(oid, Q3), f"{who}: without a date 400, nothing booked {r.text[:200]}")
    r = S.post(B + f"{D}/{Q3}/tasks", json={"pick": [], "dispo": {"pick": [dd[0]["key"]], "dates": {dd[0]["key"]: "2027-04-07"}}})
    b3 = bookings(oid, Q3)
    check(r.status_code == 201 and len(b3) == 1 and (b3[0][5], b3[0][6]) == ("2027-04-07", "2027-04-07"), f"{who}: with the date booked {r.text[:200]} {b3}")
    # ------------------------------------------------------------ the module off / not Film & Video: a hint, nothing booked
    Q4 = S.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl, "service_from": "2027-05-03", "items": [{"kind": "service", "title": "Schnitt", "qty": 2, "unit": "hour", "rate": 90}]}).json()["id"]
    shoot(S, who, Q4, "Dreh Modul", 1, [{"role_id": cam, "qty": 1}])
    check(S.post(B + f"{D}/{Q4}/project", json={"list_id": L}).ok, f"{who}: Q4 in the project")
    key4 = S.get(B + f"{D}/{Q4}/tasks").json()["dispo"]["days"][0]["key"]
    feats = S.get(B + "/api/state").json()["me"].get("settings", {}).get("features") or FEAT
    check(S.patch(B + "/api/settings", json={"features": ",".join(x for x in feats.split(",") if x != "dispo")}).ok, f"{who}: the module off")
    pv = S.get(B + f"{D}/{Q4}/tasks").json()
    check(pv["dispo"]["on"] is False and pv["dispo"]["hint"] and not pv["dispo"]["days"], f"{who}: module off: a hint {pv['dispo']}")
    r = S.post(B + f"{D}/{Q4}/tasks", json={"pick": [], "dispo": {"pick": [key4]}})
    check(r.status_code == 409 and not bookings(oid, Q4), f"{who}: module off: 409, nothing booked {r.status_code}")
    r = S.post(B + f"{D}/{Q4}/tasks", json={"pick": [x["key"] for x in pv["rows"] if x["title"] == "Schnitt"]})
    check(r.status_code == 201 and r.json()["created"] == 1 and r.json()["dispo"]["booked"] == 0 and not bookings(oid, Q4), f"{who}: the tasks still work {r.text[:200]}")
    check(S.patch(B + "/api/settings", json={"features": feats}).ok, f"{who}: the module on again")
    settings(S, [])
    pv = S.get(B + f"{D}/{Q4}/tasks").json()
    check(pv["dispo"]["on"] is False and "Film" in (pv["dispo"]["hint"] or ""), f"{who}: not Film & Video: a hint {pv['dispo']}")
    check(S.post(B + f"{D}/{Q4}/tasks", json={"pick": [], "dispo": {"pick": [key4]}}).status_code == 409 and not bookings(oid, Q4), f"{who}: not film: nothing booked")
    settings(S, ["film"])
    return Q, ids


s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Ca.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab", "tour": "done"})  # no office, no disposition
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for u in ("bob", "carol"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
settings(A, ["film"])
CAM = A.post(B + O + "/crew", json={"name_de": "Kamera", "name_en": "Camera", "rate_day": 650, "intext": "intern"}).json()["id"]
LIG = A.post(B + O + "/crew", json={"name_de": "Beleuchter", "name_en": "Lighting", "rate_day": 350, "intext": "extern"}).json()["id"]

QA, IDA = scenario(A, "alice", ORG, CAM, LIG, other=ids["bob"], other_s=Bo)
anyid = next(iter(IDA.values()))
check(Ca.post(B + f"/api/team/dispo/bookings/{anyid}/fill", json={"kind": "slot"}).status_code == 409, "Carol without the module: 409")

# ------------------------------------------------------------ a person without an organisation (freelancer-matrix: hub)
FID, Fr = freelancer(B, A, "frida")
settings(Fr, ["film"])
PERS = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
FCAM = Fr.post(B + O + "/crew", json={"name_de": "Kamera", "name_en": "Camera", "rate_day": 600, "intext": "intern"}).json()["id"]
FLIG = Fr.post(B + O + "/crew", json={"name_de": "Beleuchter", "name_en": "Lighting", "rate_day": 300, "intext": "extern"}).json()["id"]
FQ, FIDS = scenario(Fr, "frida", PERS, FCAM, FLIG)
check(sql("SELECT COUNT(*) FROM hub_bookings WHERE org_id=? AND offer_root IS NOT NULL", (PERS,))[0][0] > 0, "frida: the bookings in her own area")
# tenant-matrix: hub -- another area's open place by id: 404 both ways, nothing changed
fid = next(iter(FIDS.values()))
check(A.post(B + f"/api/team/dispo/bookings/{fid}/fill", json={"kind": "slot"}).status_code == 404, "Alice: Frida's place 404")
check(Fr.post(B + f"/api/team/dispo/bookings/{anyid}/fill", json={"kind": "slot"}).status_code == 404, "Frida: Alpha's place 404")
check(A.get(B + f"{D}/{FQ}/tasks").status_code == 404, "Alice: Frida's quotation 404")

raise SystemExit(kt.done("p2589_b_dispo"))
