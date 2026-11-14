#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1158.0 A API tests (#4566 A): the packing list of a shoot day -- the devices of a quotation's equipment set as
pencilled-in bookings of the disposition and the packing list of the call sheet. Own container (kt.fresh). Invented people,
firms and figures only.
freelancer-matrix: hub
tenant-matrix: hub
 - GET /api/office/docs/<id>/tasks: a shoot day carries its devices (gear: name, category, quantity rounded up to whole pieces,
   busy = already booked in the period), the rows whose device is no longer in the master data (loose, text only)
 - POST .../tasks {dispo}: one booking per device (kind equipment, status option, qty, the shoot day's job); the answer counts
   the devices and the double booked ones; the disposition shows the quantity and the double booking warning
 - the call sheet (auto.pack): devices with category and quantity, the text line; ticking off (data.pack) is saved and comes
   back, an unknown key is 400; the PDF has the packing list with the ticked line
 - a new version: a pencilled-in device follows its quantity, a device no longer in the quotation goes, a firm one stays and
   is marked; afterwards nothing left to do
 - a person without an organisation (her own area): the same flow; another area's call sheet 404
usage: p21158_a_packliste_test.py <datadir>"""
import re
import zlib

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0"})
FEAT = "cal,comments,collab,office,clients,docs,files,fields,time,dispo,workload"
O = "/api/office"
D = O + "/docs"
CS = "/api/team/dispo/callsheet/"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
CLIENT = {"name": "Beispiel Kunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Musterstadt", "country": "DE"}


def sql(q, args=()):
    return kt.dbx(q, args)


def pdf_text(data):
    out = b""
    for m in re.finditer(rb"stream\r?\n(.*?)\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out.decode("latin-1")


def has(txt, s):
    return s.encode("cp1252").hex() in txt


def settings(S, packs):
    check(S.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "de", "currency": "EUR", "industry_packs": packs}).ok, f"office settings {packs}")


def gear_rows(oid, root):
    """{offer_pos: (status, kind, rid, label, qty, mark, job, start, end)} of the chain's living device bookings."""
    return {r[0]: r[1:] for r in sql("SELECT offer_pos, status, resource_kind, resource_id, res_label, qty, offer_mark, job, start, \"end\" "
                                     "FROM hub_bookings WHERE org_id=? AND offer_root=? AND deleted_at IS NULL AND resource_kind='equipment'",
                                     (oid, root))}


def scenario(S, who, oid, cam):
    cl = S.post(B + "/api/clients", json=CLIENT).json().get("id")
    eq = {}
    for name, cat in (("Kamera Alpha", "Kamera"), ("Stativ Beta", "Grip"), ("Altes Licht", "Licht")):
        r = S.post(B + O + "/equipment", json={"name": name, "category": cat, "daily_rate": 50})
        check(r.status_code in (200, 201), f"{who}: the device {name} {r.text[:160]}")
        eq[name] = r.json()["id"]
    KA, ST, AL = eq["Kamera Alpha"], eq["Stativ Beta"], eq["Altes Licht"]
    # the camera is already booked on the first shoot day by hand: the double booking warning
    r = S.post(B + "/api/team/dispo/bookings", json={"title": "Fremddreh", "start": "2027-03-01", "status": "firm", "org": oid,
                                                     "resources": [{"kind": "equipment", "id": KA}]})
    check(r.status_code == 201, f"{who}: the camera booked by hand {r.text[:160]}")
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "project_title": f"Werbefilm {who}", "client_id": cl, "service_from": "2027-03-01",
                            "service_to": "2027-03-10", "items": []})
    check(r.status_code == 201, f"{who}: the quotation {r.text[:200]}")
    Q = r.json()["id"]
    r = S.post(B + f"{D}/{Q}/parts", json={"kind": "shoot", "title": "Dreh Studio"})
    check(r.status_code in (200, 201), f"{who}: the shoot part {r.text[:200]}")
    pid = r.json()["part"]["id"]
    r = S.patch(B + f"{D}/{Q}/parts/{pid}", json={"sheet": {"head": {"shoot_days": 2}, "staff": [{"role_id": cam, "qty": 1, "uid": "g"}],
                                                             "set": {"name": "Studio", "items": [{"equipment_id": KA, "qty": 1}, {"equipment_id": ST, "qty": 2.5},
                                                                                                 {"equipment_id": AL, "qty": 1}]}}})
    check(r.ok, f"{who}: the sheet with its equipment set {r.text[:200]}")
    stf = (((r.json().get("part") or {}).get("sheet") or {}).get("staff") or [{}])[0]
    check(stf.get("uid") and stf["uid"] != "g", f"{who}: review F3: a crew row never keeps the uid g (the device key) {stf}")
    check(S.patch(B + f"{O}/equipment/{AL}", json={"archived": 1}).ok, f"{who}: the old light archived (no device of the master data any more)")
    # ------------------------------------------------------------ the preview
    dp = S.get(B + f"{D}/{Q}/tasks").json().get("dispo") or {}
    days = dp.get("days") or []
    check(dp.get("on") is True and len(days) == 1, f"{who}: one shoot day {dp}")
    d1 = days[0] if days else {}
    g = {x["name"]: x for x in d1.get("gear") or []}
    check(set(g) == {"Kamera Alpha", "Stativ Beta"} and g["Stativ Beta"]["qty"] == 3 and g["Kamera Alpha"]["qty"] == 1
          and g["Kamera Alpha"]["category"] == "Kamera", f"{who}: the devices with category and whole pieces {d1.get('gear')}")
    check(g.get("Kamera Alpha", {}).get("busy") == 1 and not g.get("Stativ Beta", {}).get("busy"), f"{who}: the camera already booked then {d1.get('gear')}")
    check(d1.get("loose") == [{"name": "Altes Licht", "qty": 1}] and d1.get("gear_off") == 0, f"{who}: the archived light as text only {d1.get('loose')}")
    # ------------------------------------------------------------ apply
    r = S.post(B + f"{D}/{Q}/tasks", json={"pick": [], "dispo": {"pick": [d1["key"]]}, "create": {"name": f"Werbefilm {who}"}})
    res = r.json().get("dispo", {}) if r.ok else {}
    check(r.status_code == 201 and res.get("booked") == 3 and res.get("gear") == 2 and res.get("warnings") == 1,
          f"{who}: one place + two devices, one double booked {r.text[:200]}")
    gr = gear_rows(oid, Q)
    kk, sk = f"{d1['key']}:g:{KA}", f"{d1['key']}:g:{ST}"
    check(set(gr) == {kk, sk} and all(x[0] == "option" and x[1] == "equipment" for x in gr.values()), f"{who}: pencilled-in device bookings {gr}")
    check(gr.get(sk, ())[3:5] == ("Stativ Beta", 3) and gr.get(kk, ())[3:5] == ("Kamera Alpha", 1), f"{who}: name and quantity {gr}")
    check((gr.get(sk) or (0,) * 9)[7:9] == ("2027-03-01", "2027-03-02"), f"{who}: the period of the shoot day {gr.get(sk)}")
    JOB = gr.get(sk, (None,) * 9)[6]
    slot_job = sql("SELECT job FROM hub_bookings WHERE org_id=? AND offer_root=? AND resource_kind='slot' AND deleted_at IS NULL", (oid, Q))
    check(slot_job == [(JOB,)] and gr.get(kk, (None,) * 9)[6] == JOB, f"{who}: devices and the place are one shoot day {slot_job} {JOB}")
    j = S.get(B + "/api/team/dispo", params={"start": "2027-03-01", "days": 3}).json()
    mine = {b["rid"]: b for b in j.get("bookings", []) if b.get("job") == JOB and b["kind"] == "equipment"}
    check(mine.get(ST, {}).get("qty") == 3 and mine.get(KA, {}).get("conflicts"), f"{who}: the disposition shows quantity and double booking {mine}")
    check([x["state"] for x in S.get(B + f"{D}/{Q}/tasks").json()["dispo"]["days"]] == ["same"], f"{who}: nothing left to do")
    # ------------------------------------------------------------ the call sheet's packing list
    r = S.get(B + CS + JOB, params={"org": oid})
    check(r.ok, f"{who}: the call sheet {r.status_code} {r.text[:160]}")
    pack = (r.json().get("callsheet") or {}).get("auto", {}).get("pack") or []
    by = {x["name"]: x for x in pack}
    check(by.get("Kamera Alpha", {}).get("key") == f"e:{KA}" and by.get("Stativ Beta", {}).get("qty") == 3 and by["Stativ Beta"]["category"] == "Grip",
          f"{who}: devices with key, category and quantity {pack}")
    check(by.get("Altes Licht", {}).get("text") is True and re.fullmatch(r"t:[0-9a-f]{10}", by.get("Altes Licht", {}).get("key", "")),
          f"{who}: the archived light as a text line {pack}")
    check([x["name"] for x in pack] == ["Stativ Beta", "Kamera Alpha", "Altes Licht"], f"{who}: by category, the text lines last {[x['name'] for x in pack]}")
    tick = [f"e:{ST}", by["Altes Licht"]["key"]]
    r = S.put(B + CS + JOB, params={"org": oid}, json={"data": {"loc_name": "Studio 3", "pack": tick}})
    check(r.ok and sorted(r.json()["callsheet"]["data"].get("pack") or []) == sorted(tick), f"{who}: ticked lines saved {r.text[:200]}")
    cs = S.get(B + CS + JOB, params={"org": oid}).json()["callsheet"]
    check(sorted(cs["data"].get("pack") or []) == sorted(tick) and cs["data"].get("loc_name") == "Studio 3", f"{who}: read again, the ticks stay {cs['data']}")
    r = S.put(B + CS + JOB, params={"org": oid}, json={"data": {"pack": ["x:1"]}, "expect_updated_at": cs["updated_at"]})
    check(r.status_code == 400, f"{who}: an unknown key 400 {r.status_code}")
    r = S.put(B + CS + JOB, params={"org": oid}, json={"data": {"pack": [f"e:{ST}\n"]}, "expect_updated_at": cs["updated_at"]})
    check(r.status_code == 400, f"{who}: review F5: a key with a line break 400 {r.status_code}")
    hist = S.get(B + CS + JOB + "/history", params={"org": oid}).json().get("history") or []
    check(any("pack" in h["fields"] for h in hist), f"{who}: the history of the call sheet (obj_write) names the packing list {hist}")
    r = S.get(B + CS + JOB + "/pdf", params={"org": oid})
    txt = pdf_text(r.content) if r.ok else ""
    check(r.ok and has(txt, "Packliste") and has(txt, "Stativ Beta") and has(txt, "Altes Licht") and has(txt, "[x]") and has(txt, "Grip"),
          f"{who}: the PDF has the packing list with the ticked line ({r.status_code})")
    # ------------------------------------------------------------ a new version: the stand 1 piece, the camera gone (made firm before)
    kid = sql("SELECT id FROM hub_bookings WHERE org_id=? AND offer_pos=? AND deleted_at IS NULL", (oid, kk))[0][0]
    check(S.patch(B + f"/api/team/dispo/bookings/{kid}", json={"status": "firm"}).ok, f"{who}: the camera made firm")
    r = S.post(B + f"{D}/{Q}/duplicate")
    check(r.status_code == 201, f"{who}: a new version {r.text[:160]}")
    Q2 = r.json()["id"]
    part = next(p for p in S.get(B + f"{D}/{Q2}").json()["parts"] if p["title"] == "Dreh Studio")
    r = S.patch(B + f"{D}/{Q2}/parts/{part['id']}", json={"sheet": {"set": {"items": [{"equipment_id": ST, "qty": 1}]}}})
    check(r.ok, f"{who}: the set of the new version {r.text[:160]}")
    dd = S.get(B + f"{D}/{Q2}/tasks").json()["dispo"]["days"]
    check([(x["state"], x["firm"]) for x in dd] == [("changed", 1)], f"{who}: changed, the firm camera only marked {[(x['state'], x['firm']) for x in dd]}")
    r = S.post(B + f"{D}/{Q2}/tasks", json={"pick": [], "dispo": {"pick": [dd[0]["key"]]}})
    res = r.json().get("dispo", {}) if r.ok else {}
    check(r.ok and res.get("booked") == 0 and res.get("adapted") == 1 and res.get("marked") == 1, f"{who}: the stand adapted, the camera marked {r.text[:200]}")
    gr = gear_rows(oid, Q)
    check(gr.get(sk, ())[4] == 1 and gr.get(sk, ())[5] == "" and gr.get(kk, ())[0] == "firm" and gr.get(kk, ())[5] == "gone",
          f"{who}: the stand 1 piece, the firm camera stays marked {gr}")
    check([x["state"] for x in S.get(B + f"{D}/{Q2}/tasks").json()["dispo"]["days"]] == ["same"], f"{who}: afterwards nothing left to do")
    # the camera taken off the shoot day by hand: the packing list follows the bookings
    check(S.delete(B + f"/api/team/dispo/bookings/{kid}").ok, f"{who}: the camera removed in the disposition")
    pack = S.get(B + CS + JOB, params={"org": oid}).json()["callsheet"]["auto"]["pack"]
    # (the old light is no longer in the new version's set: its text line went with it)
    check([(x["name"], x["qty"]) for x in pack] == [("Stativ Beta", 1)], f"{who}: the packing list follows the bookings and the version {pack}")
    return JOB


s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "de", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
settings(A, ["film"])
CAM = A.post(B + O + "/crew", json={"name_de": "Kamera", "name_en": "Camera", "rate_day": 650, "intext": "intern"}).json()["id"]
JA = scenario(A, "alice", ORG, CAM)

# ------------------------------------------------------------ a person without an organisation (freelancer-matrix: hub)
FID, Fr = freelancer(B, A, "frida")
Fr.patch(B + "/api/settings", json={"lang": "de", "features": FEAT, "tour": "done"})
settings(Fr, ["film"])
PERS = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
FCAM = Fr.post(B + O + "/crew", json={"name_de": "Kamera", "name_en": "Camera", "rate_day": 600, "intext": "intern"}).json()["id"]
JF = scenario(Fr, "frida", PERS, FCAM)
# tenant-matrix: hub -- another area's call sheet (and its packing list): 404 both ways
check(A.get(B + CS + JF, params={"org": PERS}).status_code == 404, "Alice: Frida's call sheet 404")
check(Fr.get(B + CS + JA, params={"org": ORG}).status_code == 404, "Frida: Alpha's call sheet 404")

raise SystemExit(kt.done("p21158_a_packliste"))
