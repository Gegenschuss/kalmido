#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1155.0 (#5652): the call sheet by e-mail (hub/callsheet.py cs_mail_get / cs_mail_post). Own container (start.sh with the
SMTP stub of tests/stub_mail.py). Invented people, firms and addresses only.
 - GET .../mail: the distribution with addresses -- crew (a contact booked with an e-mail), agency and client (the contacts
   chosen) in that order, each address once; the crew without an address under "without"; the default subject / text; the
   PDF's file name; the way out (the server's address)
 - POST preview: the recipients chosen, the subject, the text with the signature ("-- "), the PDF's name and size --
   and no mail goes out, nothing is counted
 - POST send: one mail per recipient (To: only that one, no Cc), the PDF attached (%PDF-), the own subject; a recipient left
   out gets nothing; the office log has one "send" entry per mail (target callsheet)
 - an address that is not in the distribution: 400 and nothing sent (the call sheet is no way to mail anybody); no recipient 400
 - rights: greta (another person) 404 for the form and the send; in an organisation a read-only member gets 403 for the
   send (the form says can_send false), the admin may
freelancer-matrix: hub (frida has no organisation: her own area, her own office, her own address book)
tenant-matrix: hub (greta, another person: frida's call sheet mail 404)
usage: p21155_a_csmail_test.py <datadir>"""
import email
import email.policy
import json
import os
import shutil
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, CT, DATA, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

MAILENV = {"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
           "KALMIDO_MAIL_FROM": "kalmido@example.test"}
if kt.fresh(MAILENV):
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
    until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1025), 1)"],
                                 capture_output=True).returncode == 0, 20)

A = kt.setup()
FID, Fr = freelancer(B, A, "frida")
GID, Gr = freelancer(B, A, "greta")
FEAT = "cal,collab,comments,kanban,fields,files,contacts,office,clients,dispo,workload"
for s in (Fr, Gr):
    check(s.patch(B + "/api/settings", json={"features": FEAT}).ok, "the modules incl. Disposition")
DAY = "2027-04-05"


def mails():
    p = os.path.join(DATA, "mail", "out.jsonl")
    out = []
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            if ln.strip():
                out.append(email.message_from_string(json.loads(ln)["raw"], policy=email.policy.default))
    return out


# ------------------------------------------------------------ frida: Film & Video, her office, contacts, a shoot day
check(Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "city": "Musterstadt", "country": "DE",
                                                                  "email": "buero@beispielfilm.example"},
                                              "lang": "en", "currency": "EUR"}).ok, "frida's office master data")
check(Fr.put(B + "/api/industry", json={"industry": "film"}).ok, "frida chooses Film & Video")
PERS = kt.dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
BK = Fr.post(B + "/api/books", json={"name": "Crew und Kunden", "org_id": None}).json()["id"]
KIM = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Kim Kamera", "emails": [{"value": "kim@example.com"}]}).json()["id"]
TOM = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Tom Ton"}).json()["id"]
AGY = Fr.post(B + "/api/contacts", json={"book_id": BK, "kind": "org", "fn": "Werbe Beispiel GmbH",
                                         "emails": [{"value": "agentur@example.com"}]}).json()["id"]
KND = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Karla Kunde", "org": "Kundenfirma Beispiel KG",
                                         "emails": [{"value": "karla@example.com"}]}).json()["id"]
r = Fr.post(B + "/api/team/dispo/bookings", json={"title": "Imagefilm", "start": DAY + "T07:00", "end": DAY + "T19:00", "status": "firm",
                                                  "org": PERS, "resources": [{"kind": "contact", "id": KIM}, {"kind": "contact", "id": TOM},
                                                                             {"kind": "contact", "id": KND}]})
check(r.status_code == 201, "the shoot day booked " + r.text[:160])
JOB = r.json()["bookings"][0]["job"]
CS = B + f"/api/team/dispo/callsheet/{JOB}"
Q = f"?org={PERS}"
cs = Fr.get(CS + Q).json()["callsheet"]
r = Fr.put(CS + Q, json={"data": {"agency_contact": AGY, "client_contact": KND, "loc_name": "Studio Nord"}, "expect_updated_at": cs["updated_at"] or None})
check(r.ok, "agency and client chosen " + r.text[:160])

# ------------------------------------------------------------ the form
r = Fr.get(CS + "/mail" + Q)
check(r.ok, "GET .../mail " + r.text[:160])
m = r.json()
got = [(x["group"], x["email"]) for x in m["recipients"]]
# karla is booked in the crew AND chosen as the client: her address once (the crew's place first)
check(got == [("crew", "kim@example.com"), ("crew", "karla@example.com"), ("agency", "agentur@example.com")],
      f"the distribution: crew, then the agency; karla's address once {got}")
check(any(x["name"] == "Tom Ton" and x["group"] == "crew" for x in m["without"]), f"Tom (no address) under without {m['without']}")
check("Imagefilm" in m["subject"] and m["text"].startswith("Hello,"), f"the default subject / text {m['subject']!r} {m['text'][:60]!r}")
check(m["filename"].startswith("callsheet-") and m["filename"].endswith(".pdf"), f"the PDF's name {m['filename']}")
check(m["sender"]["way"] == "server" and m["can_send"] is True and m["max"] == 60, f"the way out, can_send {m['sender']} {m['can_send']}")

# karla only as the client (not booked): a second shoot day without her
r = Fr.post(B + "/api/team/dispo/bookings", json={"title": "Imagefilm Tag 2", "start": "2027-04-06T07:00", "end": "2027-04-06T19:00", "status": "firm",
                                                  "org": PERS, "resources": [{"kind": "contact", "id": KIM}]})
JOB2 = r.json()["bookings"][0]["job"]
CS2 = B + f"/api/team/dispo/callsheet/{JOB2}"
check(Fr.put(CS2 + Q, json={"data": {"agency_contact": AGY, "client_contact": KND}}).ok, "day 2: agency and client chosen")
m2 = Fr.get(CS2 + "/mail" + Q).json()
got = [(x["group"], x["email"], x["name"]) for x in m2["recipients"]]
check(got == [("crew", "kim@example.com", "Kim Kamera"), ("agency", "agentur@example.com", "Werbe Beispiel GmbH"),
              ("client", "karla@example.com", "Karla Kunde")], f"crew, agency, client in that order {got}")

# ------------------------------------------------------------ the preview: nothing goes out
n0 = len(mails())
r = Fr.post(CS2 + "/mail" + Q, json={"to": ["kim@example.com", "KARLA@example.com"], "preview": True})
check(r.ok, "the preview " + r.text[:160])
p = r.json()
check([x["email"] for x in p["recipients"]] == ["kim@example.com", "karla@example.com"], f"the preview's recipients {p['recipients']}")
check(p["text"].startswith("Hello,") and "\n-- \n" in p["text"], f"the text with the signature {p['text']!r}")
check(p["file"]["name"] == m2["filename"] and p["file"]["size"] > 1000, f"the PDF attached {p['file']}")
check(len(mails()) == n0, "the preview sent nothing")
check(kt.dbx("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND target='callsheet'", (PERS,))[0][0] == 0, "... and logged nothing")

# ------------------------------------------------------------ only the distribution
r = Fr.post(CS2 + "/mail" + Q, json={"to": ["kim@example.com", "fremd@example.com"]})
check(r.status_code == 400, f"an address outside the distribution: 400 ({r.status_code})")
check(Fr.post(CS2 + "/mail" + Q, json={"to": []}).status_code == 400, "no recipient: 400")
check(Fr.post(CS2 + "/mail" + Q, json={"to": "kim@example.com"}).status_code == 400, "not a list: 400")
check(len(mails()) == n0, "... nothing sent")

# ------------------------------------------------------------ the send: one mail each, the PDF attached
r = Fr.post(B + f"/api/team/dispo/callsheet/{JOB2}/mail?org={PERS}", json={"to": ["kim@example.com", "karla@example.com"], "subject": "Dispo Imagefilm Tag 2",
                                     "text": "Hallo zusammen,\n\nanbei die Dispo."})
check(r.ok and r.json() == {"sent": ["kim@example.com", "karla@example.com"], "failed": []}, "the send " + r.text[:200])
new = mails()[n0:]
check(len(new) == 2, f"two mails ({len(new)})")
check(sorted(str(x["To"]) for x in new) == ["karla@example.com", "kim@example.com"] and not any(x["Cc"] for x in new),
      f"each recipient a mail of their own, no copy {[str(x['To']) for x in new]}")
for x in new:
    check(str(x["Subject"]) == "Dispo Imagefilm Tag 2", f"the own subject {x['Subject']}")
    body = x.get_body(("plain",)).get_content()
    check(body.startswith("Hallo zusammen,") and "anbei die Dispo." in body, f"the own text {body[:80]!r}")
    att = [a for a in x.iter_attachments() if a.get_content_type() == "application/pdf"]
    check(len(att) == 1 and att[0].get_filename() == m2["filename"] and att[0].get_content()[:5] == b"%PDF-", "the PDF attached")
    check(str(x["Reply-To"] or "") == "buero@beispielfilm.example", f"answers go to the office's address {x['Reply-To']}")
check(not any("agentur@example.com" in str(x["To"]) for x in new), "the agency left out: no mail for it")
check(kt.dbx("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND target='callsheet' AND action='send'", (PERS,))[0][0] == 2,
      "the office log: one send entry per mail")

# ------------------------------------------------------------ rights: another person
check(Gr.put(B + "/api/industry", json={"industry": "film"}).ok, "greta chooses Film & Video too")
check(Gr.get(B + f"/api/team/dispo/callsheet/{JOB2}/mail?org={PERS}").status_code == 404, "greta: frida's mail form 404")
n1 = len(mails())
check(Gr.post(B + f"/api/team/dispo/callsheet/{JOB2}/mail?org={PERS}", json={"to": ["kim@example.com"]}).status_code == 404, "greta: the send 404")
check(len(mails()) == n1, "... nothing sent")

# ------------------------------------------------------------ an organisation: a read-only member may not send (403)
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
check(A.put(B + f"/api/books/{OB}/members", json={"user_id": RITA, "role": "edit"}).ok, "the book shared with rita")
OK = A.post(B + "/api/contacts", json={"book_id": OB, "fn": "Olaf Kunde", "emails": [{"value": "olaf@example.com"}]}).json()["id"]
LO = A.post(B + "/api/lists", json={"name": "Kinospot", "kind": "project", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{LO}/members", json={"user_id": RITA, "role": "view"}).ok, "the project shared with rita")
r = A.post(B + "/api/team/dispo/callsheets", json={"list_id": LO, "date": "2027-06-01"})
check(r.status_code == 201, "a call sheet of the organisation " + r.text[:160])
OCS = B + f"/api/team/dispo/callsheet/{r.json()['callsheet']['job']}"
OQ = f"?org={ORG}"
cs = A.get(OCS + OQ).json()["callsheet"]
check(A.put(OCS + OQ, json={"data": {**cs["data"], "client_contact": OK}, "expect_updated_at": cs["updated_at"]}).ok, "the client chosen")
r = Ri.get(OCS + "/mail" + OQ)
check(r.ok and r.json()["can_send"] is False and [x["email"] for x in r.json()["recipients"]] == ["olaf@example.com"],
      "rita reads the form, may not send " + r.text[:200])
n2 = len(mails())
r = Ri.post(OCS + "/mail" + OQ, json={"to": ["olaf@example.com"]})
check(r.status_code == 403, f"rita: the send 403 ({r.status_code})")
check(len(mails()) == n2, "... nothing sent")
r = A.post(OCS + "/mail" + OQ, json={"to": ["olaf@example.com"]})
check(r.ok and r.json()["sent"] == ["olaf@example.com"] and len(mails()) == n2 + 1, "alice (admin) sends " + r.text[:160])

raise SystemExit(kt.done("p21155_a_csmail"))
