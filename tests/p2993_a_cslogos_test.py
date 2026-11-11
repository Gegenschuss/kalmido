#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.993.0 (#5650): the logos of the call sheet (hub/callsheet.py). Invented people, firms and numbers only.
 - no logo at all: production.logo false, GET .../logo 404, the PDF has no logo row (no image CsL*)
 - only one (the office logo of the area): GET .../logo image/png, the PDF has the production's logo on the left only
 - all three: agency and client = the photo of the contact chosen; PUT .../photo/<contact> saves the picture at the contact
   (the contacts' own way: the contact's photo afterwards, a data URI), GET .../photo/<contact> serves it; the PDF: production
   left, agency centre, client right
 - a missing one keeps the others in place: the office logo removed again, the agency and the client stay where they were
 - the upload: a text file 400, a contact of another book 404, nothing changed; the choice of the dialog says photo / can_photo
 - rights: greta (another person) 404 for the logo, the photo and the upload; in an organisation a read-only member reads the
   logos but the upload is 403 (can_photo false), the contact's photo unchanged
freelancer-matrix: hub (frida has no organisation: her own area, her own office, her own address book)
tenant-matrix: hub (greta, another person: frida's logos and contact photos 404, the upload 404)
usage: p2993_a_cslogos_test.py <datadir>"""
import base64
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


def png(w=60, h=20, rgb=(20, 120, 200)):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def uri(data):
    return "data:image/png;base64," + base64.b64encode(data).decode()


def pdf_ops(data):
    out = b""
    for m in re.finditer(rb"stream\r?\n(.*?)\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out.decode("latin-1")


def logos(sess, job, org):
    """{n: (x, w)} of the logo images CsL<n> on the PDF's first page (0 production, 1 agency, 2 client)."""
    r = sess.get(B + f"/api/team/dispo/callsheet/{job}/pdf?org={org}")
    check(r.ok and r.content[:5] == b"%PDF-", f"the PDF ({r.status_code})")
    return {int(m.group(5)): (float(m.group(3)), float(m.group(1)))
            for m in re.finditer(r"([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm /CsL(\d) Do", pdf_ops(r.content))}


# ------------------------------------------------------------ frida: Film & Video, her office, a shoot day
check(Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "city": "Musterstadt", "country": "DE"},
                                              "lang": "en", "currency": "EUR"}).ok, "frida's office master data")
check(Fr.put(B + "/api/industry", json={"industry": "film"}).ok, "frida chooses Film & Video")
PERS = kt.dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
BK = Fr.post(B + "/api/books", json={"name": "Kunden", "org_id": None}).json()["id"]
AGY = Fr.post(B + "/api/contacts", json={"book_id": BK, "kind": "org", "fn": "Werbe Beispiel GmbH"}).json()["id"]
KND = Fr.post(B + "/api/contacts", json={"book_id": BK, "kind": "org", "fn": "Kundenfirma Beispiel KG"}).json()["id"]
r = Fr.post(B + "/api/team/dispo/bookings", json={"title": "Imagefilm", "start": DAY + "T07:00", "end": DAY + "T19:00", "status": "firm",
                                                  "org": PERS, "resources": [{"kind": "user", "id": FID}]})
check(r.status_code == 201, "the shoot day booked " + r.text[:160])
JOB = r.json()["bookings"][0]["job"]
CS = B + f"/api/team/dispo/callsheet/{JOB}"
Q = f"?org={PERS}"

# ------------------------------------------------------------ no logo
cs = Fr.get(CS + Q).json()["callsheet"]
check(cs["auto"]["production"].get("logo") is False, f"no office logo yet {cs['auto']['production']}")
ch = {x["id"]: x for x in cs["auto"].get("contacts", [])}
check(ch.get(AGY, {}).get("photo") is False and ch[AGY].get("can_photo") is True, f"the choice: no photo, frida may give one {ch.get(AGY)}")
check(Fr.get(CS + "/logo" + Q).status_code == 404, "no office logo: GET .../logo 404")
check(Fr.get(CS + f"/photo/{AGY}" + Q).status_code == 404, "no contact photo: GET .../photo 404")
check(logos(Fr, JOB, PERS) == {}, "no logo: the PDF has no logo row")

# ------------------------------------------------------------ only one: the office logo of the area
r = Fr.post(B + "/api/office/logo", files={"file": ("logo.png", png(200, 60), "image/png")})
check(r.ok, "frida's office logo " + r.text[:120])
check(Fr.get(CS + Q).json()["callsheet"]["auto"]["production"].get("logo") is True, "the production has a logo")
r = Fr.get(CS + "/logo" + Q)
check(r.ok and r.headers.get("Content-Type", "").startswith("image/png") and r.content[:8] == b"\x89PNG\r\n\x1a\n", f"GET .../logo image/png ({r.status_code})")
lg = logos(Fr, JOB, PERS)
check(set(lg) == {0}, f"only the production's logo in the PDF {lg}")
X0 = lg[0][0]

# ------------------------------------------------------------ the upload of a client / agency logo (= the contact's photo)
r = Fr.put(CS + f"/photo/{AGY}" + Q, json={"photo": "data:image/png;base64," + base64.b64encode(b"just text").decode()})
check(r.status_code == 400, f"a text file: 400 ({r.status_code})")
check(kt.dbx("SELECT photo FROM contacts WHERE id=?", (AGY,))[0][0] == "", "... and the contact unchanged")
OTHER = Gr.post(B + "/api/contacts", json={"book_id": Gr.post(B + "/api/books", json={"name": "Gretas", "org_id": None}).json()["id"],
                                           "kind": "org", "fn": "Fremd GmbH"}).json()["id"]
check(Fr.put(CS + f"/photo/{OTHER}" + Q, json={"photo": uri(png())}).status_code == 404, "a contact of another person's book: 404")
r = Fr.put(CS + f"/photo/{AGY}" + Q, json={"photo": uri(png(300, 100, (200, 40, 40)))})
check(r.ok and r.json().get("contact", {}).get("photo") is True, "the agency's logo saved " + r.text[:160])
ph = Fr.get(B + f"/api/contacts/{AGY}").json().get("photo") or ""
check(ph.startswith("data:image/"), f"... as the contact's photo (the contacts' own way) {ph[:30]}")
r = Fr.get(CS + f"/photo/{AGY}" + Q)
check(r.ok and r.headers.get("Content-Type", "").startswith("image/") and len(r.content) > 50, f"GET .../photo serves it ({r.status_code})")
check(Fr.put(CS + f"/photo/{KND}" + Q, json={"photo": uri(png(120, 120, (40, 160, 40)))}).ok, "the client's logo saved")
cs = Fr.get(CS + Q).json()["callsheet"]
r = Fr.put(CS + Q, json={"data": {"agency_contact": AGY, "client_contact": KND}, "expect_updated_at": cs["updated_at"] or None})
check(r.ok, "agency and client chosen " + r.text[:160])
a = r.json()["callsheet"]["auto"]
check(a["agency_contact"].get("photo") is True and a["client_contact"].get("photo") is True, "both chosen contacts have a photo")

# ------------------------------------------------------------ all three
lg = logos(Fr, JOB, PERS)
check(set(lg) == {0, 1, 2}, f"all three logos in the PDF {lg}")
check(lg[0][0] == X0 and lg[0][0] < lg[1][0] < lg[2][0], f"production left, agency centre, client right {lg}")
right = lg[2][0] + lg[2][1]
mid = lg[1][0] + lg[1][1] / 2
check(abs((X0 + right) / 2 - mid) < 1, f"the agency in the middle of the row {lg}")

# ------------------------------------------------------------ one missing: the others keep their place
check(Fr.delete(B + "/api/office/logo").ok, "the office logo removed")
lg2 = logos(Fr, JOB, PERS)
check(set(lg2) == {1, 2} and lg2[1] == lg[1] and lg2[2] == lg[2], f"no production logo: agency and client where they were {lg2}")

# ------------------------------------------------------------ rights: another person
check(Gr.put(B + "/api/industry", json={"industry": "film"}).ok, "greta chooses Film & Video too")
check(Gr.get(B + f"/api/team/dispo/callsheet/{JOB}/logo?org={PERS}").status_code == 404, "greta: frida's logo 404")
check(Gr.get(B + f"/api/team/dispo/callsheet/{JOB}/photo/{AGY}?org={PERS}").status_code == 404, "greta: frida's contact photo 404")
check(Gr.put(B + f"/api/team/dispo/callsheet/{JOB}/photo/{AGY}?org={PERS}", json={"photo": uri(png())}).status_code == 404, "greta: the upload 404")
check(Fr.get(B + f"/api/contacts/{AGY}").json().get("photo") == ph, "... and the photo unchanged")

# ------------------------------------------------------------ an organisation: a read-only member may not upload (403)
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beispiel Studio", "admin_id": ALICE})
check(r.ok, "an organisation, alice its admin " + r.text[:160])
ORG = r.json()["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "readonly"}], "username": "rita", "display_name": "Rita",
                                   "password": kt.PASSWORD, "email": "rita@example.com"})
check(r.ok, "rita, read-only " + r.text[:120])
RITA = r.json()["id"]
Ri = kt.sess("rita")
for s in (A, Ri):
    check(s.patch(B + "/api/settings", json={"features": FEAT, "workspace": f"org:{ORG}"}).ok, "modules + the organisation's workspace")
check(A.put(B + "/api/industry", json={"industries": ["film"]}).ok, "the organisation: Film & Video")
OB = A.post(B + "/api/books", json={"name": "Studio Kunden", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/books/{OB}/members", json={"user_id": RITA, "role": "edit"}).ok, "the book shared with rita (her read-only role decides)")
OK = A.post(B + "/api/contacts", json={"book_id": OB, "kind": "org", "fn": "Studio Kunde AG"}).json()["id"]
LO = A.post(B + "/api/lists", json={"name": "Kinospot", "kind": "project", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{LO}/members", json={"user_id": RITA, "role": "view"}).ok, "the project shared with rita")
r = A.post(B + "/api/team/dispo/callsheets", json={"list_id": LO, "date": "2027-06-01"})
check(r.status_code == 201, "a call sheet of the organisation " + r.text[:160])
OJ = r.json()["callsheet"]["job"]
OCS = B + f"/api/team/dispo/callsheet/{OJ}"
cs = A.get(OCS + f"?org={ORG}").json()["callsheet"]
check(A.put(OCS + f"?org={ORG}", json={"data": {**cs["data"], "client_contact": OK}, "expect_updated_at": cs["updated_at"]}).ok, "the client chosen")
cs = Ri.get(OCS + f"?org={ORG}")
check(cs.ok, "rita reads the call sheet " + cs.text[:120])
cc = cs.json()["callsheet"]["auto"].get("client_contact") or {}
check(cc.get("id") == OK and cc.get("can_photo") is False, f"rita: the client shown, no upload offered {cc}")
r = Ri.put(OCS + f"/photo/{OK}?org={ORG}", json={"photo": uri(png())})
check(r.status_code == 403, f"rita: the upload 403 ({r.status_code})")
check(kt.dbx("SELECT photo FROM contacts WHERE id=?", (OK,))[0][0] == "", "... and the contact's photo unchanged")
cc = A.get(OCS + f"?org={ORG}").json()["callsheet"]["auto"].get("client_contact") or {}
check(cc.get("can_photo") is True, f"alice (admin): the upload offered {cc}")
check(A.put(OCS + f"/photo/{OK}?org={ORG}", json={"photo": uri(png())}).ok, "alice saves the client's logo")
check(Ri.get(OCS + f"/photo/{OK}?org={ORG}").ok, "rita sees it")

raise SystemExit(kt.done("p2993_a_cslogos"))
