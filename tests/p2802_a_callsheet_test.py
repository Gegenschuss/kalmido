#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.855.0 A (#1956): the call sheet of a shoot day (Film-Tagesdispo, hub/callsheet.py). Invented people, firms and numbers only.
 - without Film & Video: GET /api/team/dispo/callsheet/<job> and its PDF 404 (as if there was nothing)
 - with it: the day, the title, the project, the production (office master data) and the crew of the job come from the app;
   a contact booked brings its mobile number / e-mail, a member booked the ones of the address book entry with her e-mail
 - PUT saves the day details (unknown keys go, texts are cut, a table with too many lines 400) and the directions sketch
   (PNG only, a text file 400); GET shows them again, the sketch is served as image/png; a stale save 409 with the current
   state (expect_updated_at), nothing overwritten
 - the PDF: application/pdf, page 1 with location, call times, shoot start, wrap, strike, important, set phone, the link
   "Open in maps" as a URI action, the crew list with the contact's phone, the cast, the transport ("Own arrangement"),
   the shots of the chosen shot list day, the sketch as an image of its own page, the footer "As of" + "Page n of N"
 - 2.855.0 review: a sketch over 12 megapixels 400; phone / mail never from a shared book outside the area (F2)
 - 2.986.0 (#5649): client and agency chosen from the contacts (only the area's readable ones; a shared / foreign book's id 400 and,
   smuggled into the stored details, shown nowhere, PDF included), the agency remembered at the project and offered on its next
   call sheet, the free text kept as the fallback
 - rights: another person's job 404 (with and without ?org=), an agent 403, the module Disposition off 409, Film & Video
   switched off again 404
freelancer-matrix: hub (frida has no organisation: her own area, her own office, her own industry)
tenant-matrix: hub (greta, another person's area: frida's call sheet 404 for reading, the PDF and saving)
usage: p2802_a_callsheet_test.py <datadir>"""
import base64
import json
import re
import struct
import zlib

import kt
from kt import B, check
from freelancer_fixture import freelancer

A = kt.setup()
FID, Fr = freelancer(B, A, "frida")
GID, Gr = freelancer(B, A, "greta")
FEAT = "cal,collab,comments,kanban,fields,files,contacts,office,clients,dispo,workload"
for s in (Fr, Gr):
    check(s.patch(B + "/api/settings", json={"features": FEAT}).ok, "the modules incl. Disposition")
DAY = "2027-04-05"
CS = "/api/team/dispo/callsheet/"


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


def png(w=40, h=24, rgb=(20, 120, 200)):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


# ------------------------------------------------------------ frida's area: master data, address book, a shoot, a booking
r = Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345",
                                                                "city": "Musterstadt", "country": "DE", "phone": "030 1111111"},
                                               "lang": "en", "currency": "EUR"})
check(r.ok, "frida's office master data " + r.text[:120])
PERS = kt.dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
BK = Fr.post(B + "/api/books", json={"name": "Crew", "org_id": None}).json()["id"]
r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Carla Kamera", "emails": [{"value": "carla@example.com"}],
                                       "phones": [{"value": "030 2222222", "type": ["work"]}, {"value": "0170 3333333", "type": ["cell"]}]})
check(r.status_code == 201, "a crew contact " + r.text[:120])
CARLA = r.json()["id"]
check(Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Frida Selbst", "emails": [{"value": "frida@example.com"}],
                                         "phones": [{"value": "0170 4444444", "type": ["cell"]}]}).status_code == 201, "her own address book entry")
r = Fr.post(B + "/api/team/dispo/bookings", json={"title": "Imagefilm Kueche", "start": DAY + "T07:00", "end": DAY + "T19:00", "status": "firm",
                                                  "org": PERS, "resources": [{"kind": "contact", "id": CARLA}, {"kind": "user", "id": FID}]})
check(r.status_code == 201, "the shoot day booked " + r.text[:160])
JOB = r.json()["bookings"][0]["job"]
Q = f"?org={PERS}"

# ------------------------------------------------------------ without Film & Video: nothing
check(Fr.get(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}").status_code == 404, "no Film & Video: the call sheet 404")
check(Fr.get(B + f"/api/team/dispo/callsheet/{JOB}/pdf?org={PERS}").status_code == 404, "no Film & Video: its PDF 404")

# ------------------------------------------------------------ Film & Video: what comes from the app
check(Fr.put(B + "/api/industry", json={"industry": "film"}).ok, "frida chooses Film & Video")
r = Fr.post(B + "/api/lists", json={"name": "Imagefilm Kueche", "ptype": "shoot", "sections": True})
check(r.ok, "a shoot project " + r.text[:120])
L = r.json()["id"]
st = Fr.get(B + "/api/state").json()
day1 = next(s for s in st["sections"] if s["list_id"] == L)
check(Fr.post(B + "/api/tasks", json={"title": "Totale Kueche", "list_id": L, "section_id": day1["id"]}).ok, "a shot on day 1")
r = Fr.post(B + "/api/team/dispo/bookings", json={"title": "Dreh Tag 1", "start": DAY, "end": DAY, "status": "option", "org": PERS,
                                                  "list_id": L, "resources": [{"kind": "contact", "id": CARLA}]})
check(r.status_code == 201, "a second shoot day with the project " + r.text[:160])
JOB2 = r.json()["bookings"][0]["job"]

r = Fr.get(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}")
check(r.ok, "the call sheet " + r.text[:160])
cs = r.json().get("callsheet") or {}
a = cs.get("auto") or {}
check(a.get("date") == DAY and a.get("start") == "07:00" and a.get("end") == "19:00" and a.get("title") == "Imagefilm Kueche",
      f"the day and times of the job {a.get('date')} {a.get('start')} {a.get('end')}")
check((a.get("production") or {}).get("name") == "Beispiel Film GmbH" and "030 1111111" in (a.get("production") or {}).get("lines", []),
      f"the production from the office master data {a.get('production')}")
crew = {p["name"]: p for p in a.get("crew", [])}
check(crew.get("Carla Kamera", {}).get("phone") == "0170 3333333" and crew["Carla Kamera"].get("mail") == "carla@example.com",
      f"the contact booked: her mobile number first, her e-mail {crew.get('Carla Kamera')}")
check(crew.get("Frida", {}).get("phone") == "0170 4444444", f"the member booked: the number of her address book entry {crew}")
check(cs.get("data") == {} and cs.get("updated_at") == "" and cs.get("can_edit") is True and cs.get("sketch") is False, f"nothing stored yet {cs.get('data')}")
r2 = Fr.get(B + f"/api/team/dispo/callsheet/{JOB2}?org={PERS}").json().get("callsheet", {}).get("auto", {})
check(r2.get("project") == "Imagefilm Kueche" and r2.get("shot_days", [])[:1] == [day1["name"]] and r2.get("start") == "",
      f"the job with the project: its name and the shot list days {r2.get('project')} {r2.get('shot_days')}")
# review 2.802 F1: the project's client follows the client file's rules - frida's own client shows, a private client of greta
# (org NULL, created by her) hung on frida's project never does (row security alone lets org NULL through)
r = Fr.post(B + "/api/clients", json={"name": "Kunde Beispiel AG", "contact": "Anna Auftrag", "phone": "030 8888888"})
check(r.ok, "frida's client " + r.text[:120])
kt.dbx("UPDATE lists SET client_id=? WHERE id=?", (r.json()["id"], L))
cl = Fr.get(B + f"/api/team/dispo/callsheet/{JOB2}?org={PERS}").json().get("callsheet", {}).get("auto", {}).get("client") or {}
check(cl.get("name") == "Kunde Beispiel AG" and cl.get("phone") == "030 8888888", f"frida's own client on her call sheet {cl}")
r = Gr.post(B + "/api/clients", json={"name": "Geheim GmbH", "contact": "Gerd Geheim", "phone": "030 9999999"})
check(r.ok, "greta's private client " + r.text[:120])
kt.dbx("UPDATE lists SET client_id=? WHERE id=?", (r.json()["id"], L))
cl = Fr.get(B + f"/api/team/dispo/callsheet/{JOB2}?org={PERS}").json().get("callsheet", {}).get("auto", {}).get("client") or {}
check("Geheim" not in str(cl) and "9999999" not in str(cl), f"greta's private client never on frida's call sheet {cl}")
kt.dbx("UPDATE lists SET client_id=NULL WHERE id=?", (L,))

# ------------------------------------------------------------ saving the day details + the sketch
DATA = {"subtitle": "Kampagne Fruehjahr", "day_no": "2", "set_name": "Aufnahmeleitung", "set_phone": "0170 5555555",
        "loc_name": "Studio Nord", "loc_address": "Musterweg 7, 12345 Musterstadt", "parking": "Parken im Hof hinten",
        "transit": "Bus 100 bis Musterplatz", "calls": [{"dept": "Kamera", "time": "06:30"}, {"dept": "Licht", "time": "06:45"}],
        "shoot_start": "08:00", "lunch_from": "13:00", "lunch_to": "14:00", "wrap": "18:00", "strike": "19:30",
        "weather": "Sonnenaufgang 06:52, 14 Grad", "important": "Bitte leise am Set", "attachments": "Moodboard",
        "cast": [{"role": "Koch", "name": "Max Beispiel", "phone": "0170 6666666", "arrival": "07:00", "ready": "08:00"}],
        "transport": [{"vehicle": "Bus 1 / Carla", "from": "Lager", "to": "Set", "riders": "Max", "cargo": "Licht", "call": ""}],
        "unknown": "goes", "contacts": [{"role": "Regie", "name": "Rita Regie", "phone": "0170 7777777"}]}
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}", json={"data": {**DATA, "cast": [{"name": "x"}] * 61}})
check(r.status_code == 400, f"a table with too many lines: 400 ({r.status_code})")
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}", json={"data": DATA, "sketch": "data:image/png;base64," + base64.b64encode(b"just text").decode()})
check(r.status_code == 400, f"a sketch that is no PNG / JPEG: 400 ({r.status_code})")
check(kt.dbx("SELECT COUNT(*) FROM hub_callsheets")[0][0] == 0, "... and nothing stored")
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}", json={"data": DATA, "sketch": "data:image/png;base64," + base64.b64encode(png()).decode()})
check(r.ok, "saved with a sketch " + r.text[:200])
cs = r.json().get("callsheet") or {}
V1 = cs.get("updated_at")
check(V1 and cs.get("sketch") is True and "unknown" not in cs["data"] and cs["data"]["loc_name"] == "Studio Nord"
      and cs["data"]["calls"][0] == {"dept": "Kamera", "time": "06:30"}, f"the details back, unknown keys gone {cs.get('data')}")
cs = Fr.get(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}").json()["callsheet"]
check(cs["data"].get("important") == "Bitte leise am Set" and cs["data"].get("cast", [{}])[0].get("name") == "Max Beispiel"
      and cs.get("updated_at") == V1, "opened again: the same details and version")
r = Fr.get(B + cs["sketch_url"])
check(r.ok and r.headers.get("Content-Type", "").startswith("image/png") and r.content[:8] == b"\x89PNG\r\n\x1a\n", f"the sketch as image/png ({r.status_code})")
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}", json={"data": {**DATA, "important": "zweite Fassung"}, "expect_updated_at": V1})
check(r.ok, "a save with the version read " + r.text[:120])
V2 = r.json()["callsheet"]["updated_at"]
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}", json={"data": {**DATA, "important": "veraltet"}, "expect_updated_at": V1})
check(r.status_code == 409 and (r.json().get("callsheet") or {}).get("data", {}).get("important") == "zweite Fassung",
      f"a stale save: 409 with the current state ({r.status_code})")
check(Fr.get(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}").json()["callsheet"]["updated_at"] == V2, "... and nothing overwritten")

# ------------------------------------------------------------ the PDF
check(Fr.put(B + f"/api/team/dispo/callsheet/{JOB2}?org={PERS}", json={"data": {"loc_name": "Kueche Ost", "shot_day": day1["name"]}}).ok, "day 2: a shot list day chosen")
r = Fr.get(B + f"/api/team/dispo/callsheet/{JOB}/pdf?org={PERS}")
check(r.ok and r.headers.get("Content-Type", "").startswith("application/pdf") and r.content[:5] == b"%PDF-", f"the PDF ({r.status_code})")
raw, txt = r.content, pdf_text(r.content)
for s in ("Imagefilm Kueche", "Kampagne Fruehjahr", "Studio Nord", "Musterweg 7, 12345 Musterstadt", "Open in maps", "Parken im Hof hinten",
          "06:30", "08:00", "18:00", "19:30", "zweite Fassung", "Sonnenaufgang 06:52, 14 Grad", "Beispiel Film GmbH",
          "Carla Kamera", "0170 3333333", "carla@example.com", "Max Beispiel", "0170 6666666", "Bus 1 / Carla", "Own arrangement",
          "Rita Regie", "Set phone: Aufnahmeleitung – 0170 5555555", "Shoot day 2", "Moodboard", "Directions sketch",
          "As of: ", "Page 1 of ", "Crew list", "Cast", "Transport"):
    check(has(txt, s), f"the PDF says {s!r}")
check(b"/S /URI /URI (https://www.google.com/maps/search/?api=1&query=Musterweg%207%2C%2012345%20Musterstadt)" in raw,
      "the address is a link that opens the maps app (a URI action, nothing fetched)")
check(b"/Subtype /Image" in raw and raw.count(b"/Type /Page ") >= 3, "the sketch as an image on a page of its own (3 pages or more)")
check(not has(txt, "Totale Kueche"), "no shot list day chosen: no shots")
r = Fr.get(B + f"/api/team/dispo/callsheet/{JOB2}/pdf?org={PERS}")
txt2 = pdf_text(r.content)
check(r.ok and has(txt2, "Totale Kueche") and has(txt2, "Shots of the day") and has(txt2, "Kueche Ost"), "day 2: the shots of the chosen shot list day")
check(not has(txt2, "Directions sketch") and not has(txt2, "Own arrangement"), "day 2: no sketch, no transport (only what is there)")

# ------------------------------------------------------------ 2.855.0 review F5: a sketch of more than 12 megapixels is refused
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB2}?org={PERS}", json={"data": {"loc_name": "Kueche Ost"}, "sketch": "data:image/png;base64," + base64.b64encode(png(4000, 3001)).decode()})
check(r.status_code == 400 and "megapixel" in r.text.lower(), f"a sketch of 12.004 megapixels: 400 ({r.status_code} {r.text[:120]})")

# ------------------------------------------------------------ 2.855.0 review F2: phone / mail only from the area's books
# greta shares her private address book with frida; an entry there with frida's e-mail never brings its number onto the
# call sheet of frida's area (the person may read it, but it is not a book of that area)
GB = Gr.post(B + "/api/books", json={"name": "Gretas Buch", "org_id": None}).json()["id"]
check(Gr.post(B + "/api/contacts", json={"book_id": GB, "fn": "Frida privat", "emails": [{"value": "frida@example.com"}],
                                         "phones": [{"value": "0170 9990000", "type": ["cell"]}]}).status_code == 201, "an entry in greta's book")
check(Gr.put(B + f"/api/books/{GB}/members", json={"user_id": FID, "role": "view"}).ok, "greta shares her book with frida")
check(any(b.get("id") == GB for b in (Fr.get(B + "/api/books").json().get("items") or [])), "frida reads greta's book")
kt.dbx("UPDATE contacts SET emails='[]' WHERE fn='Frida Selbst'")
crew = {p["name"]: p for p in Fr.get(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}").json()["callsheet"]["auto"].get("crew", [])}
check("0170 9990000" not in str(crew), f"the number of greta's shared book is not on frida's call sheet {crew.get('Frida')}")
kt.dbx("UPDATE contacts SET emails=? WHERE fn='Frida Selbst'", ('[{"value": "frida@example.com"}]',))

# ------------------------------------------------------------ 2.986.0 (#5649): client and agency from the contacts
r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Anja Agentur", "org": "Werbe Beispiel GmbH", "emails": [{"value": "anja@example.com"}],
                                       "phones": [{"value": "0170 1212121", "type": ["cell"]}]})
check(r.status_code == 201, "an agency person " + r.text[:120])
ANJA = r.json()["id"]
r = Fr.post(B + "/api/contacts", json={"book_id": BK, "kind": "org", "fn": "Kundenfirma Beispiel KG", "emails": [{"value": "info@example.com"}],
                                       "phones": [{"value": "030 3434343", "type": ["work"]}]})
check(r.status_code == 201, "a client company " + r.text[:120])
KUNDE = r.json()["id"]
FOREIGN = kt.dbx("SELECT id FROM contacts WHERE fn='Frida privat'")[0][0]  # greta's book, shared with frida, not a book of the area
GB2 = Gr.post(B + "/api/books", json={"name": "Gretas zweites Buch", "org_id": None}).json()["id"]
r = Gr.post(B + "/api/contacts", json={"book_id": GB2, "fn": "Gerd Geheim", "phones": [{"value": "0170 8080808", "type": ["cell"]}]})
check(r.status_code == 201, "a contact only greta reads (her book, not shared) " + r.text[:120])
SECRET = r.json()["id"]
a = Fr.get(B + f"/api/team/dispo/callsheet/{JOB2}?org={PERS}").json()["callsheet"]["auto"]
ids = {x["id"]: x for x in a.get("contacts") or []}
check(ANJA in ids and KUNDE in ids and ids[ANJA]["company"] == "Werbe Beispiel GmbH" and ids[ANJA]["person"] == "Anja Agentur"
      and ids[KUNDE]["company"] == "Kundenfirma Beispiel KG" and ids[KUNDE]["person"] == "", f"the choice: the area's people and companies {ids.get(ANJA)}")
check(FOREIGN not in ids and SECRET not in ids and "Frida privat" not in str(a) and "Gerd Geheim" not in str(a),
      "the choice never holds a contact of another book (shared or not)")
check(a.get("agency_default") is None and a.get("agency_contact") is None, "nothing remembered at the project yet")
for k, x in (("agency_contact", FOREIGN), ("agency_contact", SECRET), ("client_contact", SECRET), ("agency_contact", "abc"), ("agency_contact", True)):
    r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB2}?org={PERS}", json={"data": {"loc_name": "Kueche Ost", k: x}})
    check(r.status_code == 400, f"{k}={x!r} (not a readable contact of the area): 400 ({r.status_code})")
check(kt.dbx("SELECT cs_agency_id FROM lists WHERE id=?", (L,))[0][0] is None, "... and nothing remembered")
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB2}?org={PERS}", json={"data": {"loc_name": "Kueche Ost", "shot_day": day1["name"], "client": "Alter Kundentext",
                                                                         "client_contact": KUNDE, "agency_contact": str(ANJA)}})
check(r.ok, "client and agency chosen from the contacts " + r.text[:160])
cs = r.json()["callsheet"]
check(cs["data"].get("agency_contact") == ANJA and cs["data"].get("client_contact") == KUNDE and cs["data"].get("client") == "Alter Kundentext",
      f"the ids stored as numbers, the free text kept as the fallback {cs['data']}")
ag = cs["auto"].get("agency_contact") or {}
check(ag.get("company") == "Werbe Beispiel GmbH" and ag.get("person") == "Anja Agentur" and ag.get("phone") == "0170 1212121"
      and ag.get("email") == "anja@example.com", f"the agency: company, person, phone, e-mail of the contact {ag}")
check((cs["auto"].get("client_contact") or {}).get("company") == "Kundenfirma Beispiel KG", "the client: the company chosen")
check(kt.dbx("SELECT cs_agency_id FROM lists WHERE id=?", (L,))[0][0] == ANJA, "the agency is remembered at the project")
txt = pdf_text(Fr.get(B + f"/api/team/dispo/callsheet/{JOB2}/pdf?org={PERS}").content)
for x in ("Werbe Beispiel GmbH", "Anja Agentur", "anja@example.com", "0170 1212121", "Kundenfirma Beispiel KG", "030 3434343", "info@example.com", "Agency"):
    check(has(txt, x), f"the PDF names the chosen contact: {x!r}")
check(not has(txt, "Alter Kundentext"), "the PDF: the contact chosen comes before the free text")
check(has(txt, "Distribution: Carla Kamera, Anja Agentur"), "the agency's person is on the distribution line")
# a new call sheet of the same project starts with the remembered agency; one with only a free text keeps it
r = Fr.post(B + "/api/team/dispo/bookings", json={"title": "Dreh Tag 2", "start": "2027-04-06", "end": "2027-04-06", "status": "option", "org": PERS,
                                                  "list_id": L, "resources": [{"kind": "contact", "id": CARLA}]})
check(r.status_code == 201, "a third shoot day of the project " + r.text[:160])
JOB3 = r.json()["bookings"][0]["job"]
cs = Fr.get(B + f"/api/team/dispo/callsheet/{JOB3}?org={PERS}").json()["callsheet"]
check(cs["data"] == {} and (cs["auto"].get("agency_default") or {}).get("id") == ANJA, f"the new call sheet: the agency of the project offered {cs['auto'].get('agency_default')}")
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB3}?org={PERS}", json={"data": {"agency": "Freitext Agentur Alt\nZweite Zeile"}})
check(r.ok and r.json()["callsheet"]["auto"].get("agency_contact") is None, "an agency as free text only")
txt = pdf_text(Fr.get(B + f"/api/team/dispo/callsheet/{JOB3}/pdf?org={PERS}").content)
check(has(txt, "Freitext Agentur Alt") and not has(txt, "Werbe Beispiel GmbH"), "the free text stays the agency of that call sheet (fallback)")
# an id smuggled into the stored details (not through the API) is shown nowhere
raw = kt.dbx("SELECT data FROM hub_callsheets WHERE org_id=? AND job=?", (PERS, JOB3))[0][0]
check(raw.startswith("{"), "frida's personal area keeps the details in plain JSON (the test can write into them)")
kt.dbx("UPDATE hub_callsheets SET data=? WHERE org_id=? AND job=?", ('{"agency_contact": %d, "client_contact": %d}' % (SECRET, FOREIGN), PERS, JOB3))
a = Fr.get(B + f"/api/team/dispo/callsheet/{JOB3}?org={PERS}").json()["callsheet"]["auto"]
check(a.get("agency_contact") is None and a.get("client_contact") is None and "Gerd" not in str(a) and "Frida privat" not in str(a),
      f"a smuggled id: no contact in the dialog {a.get('agency_contact')} {a.get('client_contact')}")
txt = pdf_text(Fr.get(B + f"/api/team/dispo/callsheet/{JOB3}/pdf?org={PERS}").content)
check(not has(txt, "Gerd Geheim") and not has(txt, "0170 8080808") and not has(txt, "Frida privat") and not has(txt, "0170 9990000"),
      "a smuggled id: nothing of the contact in the PDF (neither the columns, the crew list nor the distribution line)")
# review F1/F3 (2.986.0, #5649): a contact this person cannot read is not handed out in data, and a save of the dialog (which
# then sends no id) keeps it instead of dropping it silently; the same id sent back passes, another unreadable one is 400
d_ = Fr.get(B + f"/api/team/dispo/callsheet/{JOB3}?org={PERS}").json()["callsheet"]["data"]
check("agency_contact" not in d_ and "client_contact" not in d_, f"an unreadable contact id is not handed out {d_}")
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB3}?org={PERS}", json={"data": {"loc_name": "Neuer Ort"}})
check(r.ok, "a save without the unreadable ids " + r.text[:160])
raw = json.loads(kt.dbx("SELECT data FROM hub_callsheets WHERE org_id=? AND job=?", (PERS, JOB3))[0][0])
check(raw.get("agency_contact") == SECRET and raw.get("client_contact") == FOREIGN and raw.get("loc_name") == "Neuer Ort",
      f"... keeps the contacts somebody else chose {raw}")
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB3}?org={PERS}", json={"data": {"agency_contact": SECRET, "client_contact": FOREIGN}})
check(r.ok, "the same unreadable ids sent back: no 400 " + r.text[:160])
r = Fr.put(B + f"/api/team/dispo/callsheet/{JOB3}?org={PERS}", json={"data": {"agency_contact": FOREIGN}})
check(r.status_code == 400, f"another unreadable id instead: 400 ({r.status_code})")
check(kt.dbx("SELECT cs_agency_id FROM lists WHERE id=?", (L,))[0][0] == ANJA, "a kept unreadable agency is not remembered at the project")
# a contact gone to the trash is not shown any more either
check(Fr.delete(B + f"/api/contacts/{ANJA}").ok, "the agency contact into the trash")
a = Fr.get(B + f"/api/team/dispo/callsheet/{JOB2}?org={PERS}").json()["callsheet"]["auto"]
check(a.get("agency_contact") is None and a.get("agency_default") is None, "a contact in the trash: no agency shown")
check(Fr.post(B + f"/api/contacts/{ANJA}/restore").ok, "... and back")

# ------------------------------------------------------------ rights
check(Gr.put(B + "/api/industry", json={"industry": "film"}).ok, "greta chooses Film & Video too")
check(Gr.get(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}").status_code == 404, "greta: frida's area by ?org= 404")
check(Gr.get(B + f"/api/team/dispo/callsheet/{JOB}").status_code == 404, "greta: frida's job in her own area 404")
check(Gr.get(B + f"/api/team/dispo/callsheet/{JOB}/pdf?org={PERS}").status_code == 404, "greta: frida's PDF 404")
check(Gr.get(B + f"/api/team/dispo/callsheet/{JOB}/sketch?org={PERS}").status_code == 404, "greta: frida's sketch 404")
check(Gr.put(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}", json={"data": {"important": "fremd"}}).status_code == 404, "greta: saving frida's call sheet 404")
check(Gr.get(B + f"/api/team/dispo/callsheet/x%20y?org={PERS}").status_code == 404, "a strange job name 404")
r = A.post(B + "/api/admin/agents", json={"username": "dispobot", "display_name": "Dispobot", "scopes": ["calendar"]})
check(r.status_code == 201, "an agent " + r.text[:120])
AG = kt.sess(soft=True)
AG.headers.update({"Authorization": "Bearer " + (r.json().get("token") or "")})
check(AG.get(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}").status_code in (401, 403), "an agent: the call sheet is refused")
check(Fr.patch(B + "/api/settings", json={"features": FEAT.replace(",dispo", "")}).ok, "frida switches the Disposition off")
check(Fr.get(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}").status_code == 409, "the module off: 409 like the disposition")
check(Fr.patch(B + "/api/settings", json={"features": FEAT}).ok and Fr.put(B + "/api/industry", json={"industry": ""}).ok, "the module on, Film & Video off")
check(Fr.get(B + f"/api/team/dispo/callsheet/{JOB}?org={PERS}").status_code == 404, "Film & Video off again: 404")
# 2.986.0 (#5649): three now (the third shoot day of the contact block)
check(kt.dbx("SELECT COUNT(*) FROM hub_callsheets WHERE org_id=?", (PERS,))[0][0] == 3, "the stored call sheets stay (only hidden)")

raise SystemExit(kt.done("p2802_a_callsheet"))
