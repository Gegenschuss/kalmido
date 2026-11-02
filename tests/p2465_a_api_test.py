#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.465.0 (#2361, #2477), for a person without an organisation (freelancer-matrix: sheets, freelancer-matrix: pim).
 - #2361 an agent hears sheet_shared at a new share and sheet_unshared at its end (no event for a changed role, the event
   of the end names no title); a share that comes back is new again; moving the table to another workspace ends it
 - #2477 POST /api/v1/address-books/{id}/import takes several .vcf files or a ZIP (multipart) like the app, the {vcf} text
   stays; no right to the book = 404 before anything is unpacked; a ZIP without vCards is refused
Invented names only."""
import io
import os
import sys
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, done  # noqa: E402

V = B + "/api/v1"
kt.fresh()
A = kt.setup(lang="en")
FID, Fr = freelancer(B, A, "frida")
_, Fe = freelancer(B, A, "fenna")

# ---- #2361 the freelancer's own agent
r = A.post(B + "/api/admin/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "contacts"]})
assert r.status_code == 201, r.text
FAG, AH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
for q, a in (("DELETE FROM org_members WHERE user_id=?", (FAG,)), ("UPDATE agents SET org_id=NULL, owner_id=? WHERE user_id=?", (FID, FAG))):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    c.execute(q, a)
    c.commit()
    c.close()


def events():
    return [e for e in requests.get(V + "/agent/events?since=0&limit=200", headers=AH).json()["data"] if e["event"].startswith("sheet_")]


r = Fr.post(B + "/api/sheets", json={"title": "Fotos 2027", "space": "private"})
assert r.status_code == 201, r.text
SID = r.json()["id"]
r = Fr.post(B + f"/api/sheets/{SID}/shares", json={"user_id": FAG, "role": "read"})
check(r.status_code == 201, "#2361: the freelancer shares the table with the own agent " + r.text[:200])
SH = r.json()["id"]
ev = events()
check(len(ev) == 1 and ev[0]["event"] == "sheet_shared" and ev[0]["data"] == {"sheet": {"id": SID, "title": "Fotos 2027"}, "role": "read"},
      f"#2361: the agent hears sheet_shared with table and role {ev}")
check(Fr.post(B + f"/api/sheets/{SID}/shares", json={"user_id": FAG, "role": "write"}).status_code == 201
      and Fr.patch(B + f"/api/sheets/{SID}/shares/{SH}", json={"role": "read"}).ok and len(events()) == 1,
      "#2361: a changed role is no new share (no event), by POST or PATCH")
check(Fr.delete(B + f"/api/sheets/{SID}/shares/{SH}").ok, "#2361: the share ends")
ev = events()
check(len(ev) == 2 and ev[1]["event"] == "sheet_unshared" and ev[1]["data"] == {"sheet": {"id": SID}},
      f"#2361: sheet_unshared with the id only, no title {ev[1:]}")
check(Fr.post(B + f"/api/sheets/{SID}/shares", json={"user_id": FAG, "role": "read"}).status_code == 201
      and [e["event"] for e in events()][2:] == ["sheet_shared"], "#2361: a share that comes back is new again")
FE = Fe.get(B + "/api/state").json()["me"]["id"]
check(Fr.post(B + f"/api/sheets/{SID}/shares", json={"user_id": FE, "role": "read"}).status_code in (201, 409) and len(events()) == 3,
      "#2361: a share with a person is no agent's event")

# ---- #2477
VC = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{u}\r\nFN:{n}\r\nEND:VCARD\r\n"


def tok(s):
    r = s.post(B + "/api/me/tokens", json={"name": "import", "scopes": ["contacts"]})
    assert r.ok, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


FH, EH = tok(Fr), tok(Fe)
BK = requests.post(V + "/address-books", headers=FH, json={"name": "Kunden"}).json()["id"]


def names():
    return sorted(c["name"] if "name" in c else c.get("fn", "") for c in requests.get(V + "/contacts", headers=FH, params={"book_id": BK}).json()["data"])


def vcf(u, n):
    return VC.format(u=u, n=n).encode()


r = requests.post(V + f"/address-books/{BK}/import", headers=FH, json={"vcf": VC.format(u="t1", n="Text Eins")})
check(r.ok and r.json()["created"] == 1 and "files" not in r.json(), "#2477: the vCard text stays " + r.text[:200])
r = requests.post(V + f"/address-books/{BK}/import", headers=FH, files=[("files", ("a.vcf", vcf("m1", "Mehr Eins"))), ("files", ("b.vcf", vcf("m2", "Mehr Zwei")))])
check(r.ok and r.json()["created"] == 2 and r.json()["files"]["files"] == 2, "#2477: several .vcf files " + r.text[:200])
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("x/c.vcf", vcf("z1", "Zip Eins"))
    z.writestr("d.vcard", vcf("z2", "Zip Zwei"))
    z.writestr("hallo.txt", "kein Kontakt")
ZIP = buf.getvalue()
check(requests.post(V + f"/address-books/{BK}/import", headers=EH, files={"file": ("k.zip", ZIP)}).status_code == 404, "#2477: a foreign book answers 404")
r = requests.post(V + f"/address-books/{BK}/import", headers=FH, files={"file": ("k.zip", ZIP)})
check(r.ok and r.json()["created"] == 2 and r.json()["files"]["skipped"] == ["hallo.txt"], "#2477: a ZIP of vCards, other files skipped " + r.text[:300])
r = requests.post(V + f"/address-books/{BK}/import", headers=FH, files={"file": ("one.vcf", vcf("o1", "Einzel Datei"))})
check(r.ok and r.json()["created"] == 1, "#2477: one plain .vcf as a file " + r.text[:200])
check(requests.post(V + f"/address-books/{BK}/import", headers=FH, files={"file": ("a.csv", b"name;mail\nA;b@example.com\n")}).status_code == 400, "#2477: CSV stays the app's")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("hallo.txt", "nichts")
check(requests.post(V + f"/address-books/{BK}/import", headers=FH, files={"file": ("n.zip", buf.getvalue())}).status_code == 400, "#2477: a ZIP without vCards is refused")
got = names()
check(len(got) == 6, f"#2477: all cards are in the book {got}")
r = requests.post(V + f"/address-books/{BK}/import", headers=AH, files={"file": ("a.vcf", vcf("g1", "Agent Karte"))})
check(r.status_code in (403, 404), f"#2477: an agent without a share of the book is refused {r.status_code}")
sys.exit(done("p2465_a_api"))
