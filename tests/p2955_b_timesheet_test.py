#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.955.0 (#5648): the timesheet of an invoice for the client (office/delivery.py ls_sheet_report / ls_sheet_model).
Own container with a mail stub (tests/stub_mail.py). Invented companies, people and figures only.
 - default: non-billable entries are left out, the total counts only what is printed
 - the switch "Show non-billable entries" (GET .../timesheet.pdf?nonbillable=1, POST .../send nonbillable: true): they are in,
   marked "not billable", the total shows the billable hours apart
 - an entry billed on ANOTHER invoice carries "billed with <number>"; on a document of an office where the sending person
   has no role only "already billed"; entries of the sheet's own invoice carry no mark
 - nothing left after the selection: the same 400 as without entries; with the switch the sheet is made
 - the mail attachment follows the same switch
 - a person without an organisation (freelancer-matrix: office): the same selection
usage: p2955_b_timesheet_test.py <datadir>      (P2955B_NOSTART=1: a running server with the mail stub on KALMIDO_TEST_PORT)"""
import email
import io
import json
import os
import re
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, docker_logs_on_first_fail, done, nostart, sess, setup, until  # noqa: E402

FEAT = "cal,comments,collab,office,clients,time"
D = "/api/office/docs"
MAILENV = ["-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none",
           "-e", "KALMIDO_MAIL_FROM=kalmido@example.test", "-e", "KALMIDO_INSTANCE_MODE=workspaces"]
if not nostart("P2955B"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
docker_logs_on_first_fail()
OUT = os.path.join(DATA, "mail", "out.jsonl")


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def pdf_text(data):
    from pypdf import PdfReader
    return " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages).replace("\n", " ")


def item(title, qty, rate, unit="hour"):
    return {"kind": "service", "title": title, "qty": qty, "unit": unit, "rate": rate, "tax": "standard", "raw_fee": 0, "producing": 0,
            "intext": "intern", "cost": 0, "discountable": 1}


def entry(user_id, list_id, day, hours, note, billable=1, billed=None):
    start, end = f"{day}T08:00:00Z", f"{day}T{8 + int(hours):02d}:{int(round(hours % 1 * 60)):02d}:00Z"
    sql("INSERT INTO time_entries(user_id, list_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at, billable,"
        " billed_doc_id, billed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, list_id, "Schnitt", start, end, int(hours * 3600), note, "manual", end, end, billable, billed, end if billed else None), write=True)


def office(s, name):
    r = s.put(B + "/api/office/settings", json={"lang": "en", "currency": "EUR", "company_fields": {
        "name": name, "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "hallo@studio.example",
        "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}})
    assert r.ok, r.text


def client(s, name):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt", "country": "DE"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def invoice(s, cl, frm, to, final=True):
    r = s.post(B + D, json={"kind": "invoice", "lang": "en", "client_id": cl, "service_from": frm, "service_to": to, "items": [item("Beratung", 1, 100)]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        assert r.ok, r.text
    return did, s.get(B + f"{D}/{did}").json()


def hours(t, n):
    """Whether text t holds "<n> h" as a whole number of hours (not the end of "1.25 h")."""
    return re.search(rf"(?<![\d.,]){n} h\b", t) is not None


def sheet(s, did, nb=False):
    r = s.get(B + f"{D}/{did}/timesheet.pdf" + ("?nonbillable=1" if nb else ""))
    return r, (pdf_text(r.content) if r.status_code == 200 else "")


def sheet_mails(to):
    """The texts of the timesheet attachments of the mails the stub got for address to (oldest first)."""
    out = []
    try:
        lines = open(OUT, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return out
    for ln in lines:
        j = json.loads(ln)
        if not any(to in x for x in j["to"]):
            continue
        for part in email.message_from_string(j["raw"]).walk():
            if (part.get_filename() or "").startswith("timesheet-"):
                out.append(pdf_text(part.get_payload(decode=True)))
    return out


# ---------------------------------------------------------------- setup: Alpha (alice admin), Beta (carol admin, alice no role)
A = setup()
assert A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"}).ok
Ca = sess("carol")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
office(A, "Studio Nordlicht GmbH")
office(Ca, "Beta Werkstatt GmbH")
CL = client(A, "Kunde Xaver GmbH")
CLB = client(Ca, "Kunde bei Beta")

INV, inv = invoice(A, CL, "2026-05-01", "2026-05-31")
OTHER, other = invoice(A, CL, "2026-04-01", "2026-04-30")  # an earlier invoice of the same office
BETA, beta = invoice(Ca, CLB, "2026-05-01", "2026-05-31")  # a document of an office alice has no role in
check(other["number"] and beta["number"] and other["number"] != inv["number"], f"numbers {inv['number']} / {other['number']} / {beta['number']}")
LID = A.post(B + "/api/lists", json={"name": "Projekt Film"}).json()["id"]
sql("UPDATE lists SET client_id=?, org_id=?, time_tracking=1 WHERE id=?", (CL, ORG, LID), write=True)
entry(ALICE, LID, "2026-05-04", 2.5, "Rohschnitt Akt eins")
entry(ALICE, LID, "2026-05-05", 1, "Interne Teamrunde", billable=0)
entry(ALICE, LID, "2026-05-06", 0.5, "Vorabversion Trailer", billed=OTHER)
entry(ALICE, LID, "2026-05-07", 0.75, "Tonmischung Sprecher", billed=BETA)
entry(ALICE, LID, "2026-05-08", 1.25, "Abnahme beim Kunden", billed=INV)

# ================================================================ default: without the non-billable entries
r, t = sheet(A, INV)
check(r.status_code == 200 and r.content[:5] == b"%PDF-", "the timesheet PDF " + (r.text[:160] if r.status_code != 200 else "ok"))
check("Rohschnitt" in t and "Abnahme" in t and "Vorabversion" in t and "Tonmischung" in t, "billable and billed entries are printed: " + t[:400])
check("Interne Teamrunde" not in t and "not billable" not in t, "default: no non-billable entry")
check("Total hours" in t and "Billable hours" not in t, "default: one total, no separate billable line")
check(hours(t, 5), "default total = 2.5 + 0.5 + 0.75 + 1.25 h = 5 h: " + t[-300:])
# billed elsewhere: the number of the own office's other invoice; another office's document: only "already billed"
check(f"billed with {other['number']}" in t, f"an entry billed on another invoice names it ({other['number']})")
# (both offices count from the same scheme: Beta's number may equal this invoice's own number in the sheet's head)
check(t.count("billed with") == 1 and "already billed" in t, "a document of an office without a role: only 'already billed'")
check(t.count("billed with") == 1 and inv["number"] and f"billed with {inv['number']}" not in t, "an entry of this invoice carries no mark")
# review 2.955.0: a role in the other office does not put its number onto this office's sheet (it goes to an outside client)
sql("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, 'member') ON CONFLICT DO NOTHING", (ORG2, ALICE), write=True)
_, tm = sheet(A, INV)
check(tm.count("billed with") == 1 and "already billed" in tm, "a role in the other office: still only 'already billed' for its document")
sql("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG2, ALICE), write=True)

# ================================================================ the switch: non-billable entries shown and marked
r, t2 = sheet(A, INV, nb=True)
check(r.status_code == 200, "with the switch 200 " + r.text[:160])
check("Interne Teamrunde" in t2 and "not billable" in t2, "with the switch: the non-billable entry, marked")
check("Total hours" in t2 and "Billable hours" in t2, "with the switch: billable hours apart in the total")
check(hours(t2, 6) and hours(t2, 5), "totals 6 h / billable 5 h: " + t2[-300:])
check("Interne Teamrunde" not in pdf_text(A.get(B + f"{D}/{INV}/timesheet.pdf?nonbillable=0").content), "nonbillable=0 = the default")

# ================================================================ empty after the selection: the same 400 as without entries
INVE, _ = invoice(A, CL, "2026-06-01", "2026-06-30", final=False)
entry(ALICE, LID, "2026-06-03", 1, "Nur intern", billable=0)
r, _t = sheet(A, INVE)
check(r.status_code == 400 and "no time entries" in r.json().get("error", ""), "only non-billable entries: the 400 without entries " + r.text[:160])
r, t3 = sheet(A, INVE, nb=True)
check(r.status_code == 200 and "Nur intern" in t3, "... with the switch the sheet is made")
check(A.get(B + f"{D}/{INVE}").json()["timesheet_ok"] is True, "timesheet_ok stays the invoice's check (client and period)")

# ================================================================ the mail attachment follows the switch
r = A.post(B + f"{D}/{INV}/send", json={"to": "kunde1@example.com", "timesheet": True})
check(r.ok, "send with the timesheet " + r.text[:200])
got = until(lambda: sheet_mails("kunde1@example.com"), 20) or [""]
check("Rohschnitt" in got[-1] and "Interne Teamrunde" not in got[-1], "attachment default: without the non-billable entry")
r = A.post(B + f"{D}/{INV}/send", json={"to": "kunde2@example.com", "timesheet": True, "nonbillable": True})
check(r.ok, "send with the switch " + r.text[:200])
got = until(lambda: sheet_mails("kunde2@example.com"), 20) or [""]
check("Interne Teamrunde" in got[-1] and "not billable" in got[-1], "attachment with the switch: the non-billable entry, marked")

# ================================================================ a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A, features=FEAT)
office(Fr, "Frida Freiberuflich")
FC = client(Fr, "Privatkunde")
FLID = Fr.post(B + "/api/lists", json={"name": "Privatprojekt"}).json()["id"]
Fr.patch(B + f"/api/lists/{FLID}", json={"client_id": FC})
entry(FID, FLID, "2026-05-04", 1.5, "Konzept Webseite")
entry(FID, FLID, "2026-05-05", 1, "Eigene Fortbildung", billable=0)
FI, _ = invoice(Fr, FC, "2026-05-01", "2026-05-31", final=False)
r, ft = sheet(Fr, FI)
check(r.status_code == 200 and "Konzept Webseite" in ft and "Eigene Fortbildung" not in ft, "freelancer: default without the non-billable entry " + r.text[:160])
r, ft2 = sheet(Fr, FI, nb=True)
check(r.status_code == 200 and "Eigene Fortbildung" in ft2 and "Billable hours" in ft2, "freelancer: with the switch")
check(Fr.get(B + f"{D}/{INV}/timesheet.pdf?nonbillable=1").status_code == 404, "freelancer: an organisation's invoice 404")

sys.exit(done("p2955_b_timesheet"))
