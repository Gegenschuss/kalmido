#!/usr/bin/env python3
"""2.91.0 API tests, part A (#1923): invoice series, own container (start.sh, mode workspaces) with the SMTP stub
(stub_mail.py). Invented companies, people and figures only. tenant-matrix: office  freelancer-matrix: office
 - a series from a template invoice (monthly / quarterly / yearly, the 31st = the month's last day, an end): "make now"
   makes a NEW draft per call (series_id + series_period, date today, period of service = the period, no number before
   finalising), the placeholders {period} {month} {quarter} {year} filled (unknown braces stay, the template keeps them)
 - never twice: the same period again is 409 (unique index), a copy (duplicate) is no invoice of the series
 - the end: after the last period the series is off, "make now" 409; a cancelled template is refused
 - auto_send: finalised (number, e-invoice XML) and mailed to the client's invoice address; without an address the
   invoice stays a draft (no number) and the answer names the reason
 - the cash flow: the coming periods as planned income (kind series, the template's gross / net), a draft of the series
   instead of its period (never twice), a finalised one as an open invoice; paused series count not
 - the bin: delete, the list without it, ?bin=1, restore; PATCH (title, every -> next_date, active)
 - the watchdog: a series with periods in the past makes one period per run (a task in the creator's inbox with the link,
   no amount), more than 3 missed periods only the newest (the task names the rest); a deleted template pauses the series
 - rights: a member 403, another organisation 404 (its template, its series), an agent 403; a person without an
   organisation (personal office) does all of it in their own area and nobody else sees it
usage: p291_a_api_test.py <datadir>"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date, timedelta

import requests

import dbx as dbxm
import testclock

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
O = "/api/office"
D = O + "/docs"
S = O + "/series"
FEAT = "cal,comments,collab,office,clients"
SMTP = (" -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test"
        " -e KALMIDO_INSTANCE_MODE=workspaces")
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "hallo@beispiel.example",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def dbx(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8")]
    except OSError:
        return []


def first_of(d, n=0):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


if not os.environ.get("P291A_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + SMTP)
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(1)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Freelancer")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
DAVE = Da.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
TODAY = testclock.today()
assert A.put(B + O + "/settings", json={"lang": "de", "company_fields": COMPANY}).ok
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                      "email_invoice": "rechnung@kunde-eins.example"}).json()["id"]
CLN = A.post(B + "/api/clients", json={"name": "Kunde Ohne Mail AG", "street": "Hafenweg 2", "zip": "20457", "city": "Hamburg", "country": "DE"}).json()["id"]


def invoice(s, cl, title="Retainer {month}", rate=500, **kw):
    r = s.post(B + D, json={"kind": "invoice", "lang": "de", "client_id": cl, "project_title": title, "intro": "Leistungen im Zeitraum {period}.",
                            "closing": "Danke für {year}.", "service_from": "2026-01-01", "service_to": "2026-01-31",
                            "items": [{"title": "Betreuung {quarter}", "detail": "Jahr {year} {unbekannt}", "qty": 1, "rate": rate}], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def doc(s, did):
    return s.get(B + f"{D}/{did}").json()


def items_of(s):
    return {x["id"]: x for x in s.get(B + S).json()["items"]}


# ================================================================== a series, made by hand
TPL = invoice(A, CL)
r = A.post(B + S, json={"template_id": TPL["id"], "every": "monthly", "start": "2027-01-31", "title": "Retainer Kunde Eins"})
check(r.status_code == 201, "a new series " + r.text[:200])
S1 = r.json()
check(S1.get("next_date") == "2027-01-31" and S1.get("active") == 1 and S1.get("auto_send") == 0 and S1.get("next_periods") == ["2027-01-31", "2027-02-28", "2027-03-31"]
      and float(S1.get("template", {}).get("gross") or 0) == 595, f"the series: next date = start, the 31st becomes the month's last day {S1.get('next_periods')} {S1.get('template')}")
r = A.post(B + f"{S}/{S1['id']}/run")
check(r.ok and r.json().get("doc_id") and r.json().get("sent") is False, "make now: a draft " + r.text[:200])
D1 = doc(A, r.json()["doc_id"])
check(D1["kind"] == "invoice" and D1["status"] == "draft" and not D1["number"] and D1["series_id"] == S1["id"] and D1["series_period"] == "2027-01-31"
      and D1["date"] == TODAY.isoformat() and D1["service_from"] == "2027-01-31" and D1["service_to"] == "2027-02-27" and D1["client_id"] == CL,
      f"the draft: series, period, date today, period of service, no number yet {[D1.get(k) for k in ('status', 'number', 'series_period', 'date', 'service_from', 'service_to')]}")
check(D1["project_title"] == "Retainer Januar 2027" and D1["intro"] == "Leistungen im Zeitraum 31.01.2027 - 27.02.2027." and D1["closing"] == "Danke für 2027."
      and D1["items"][0]["title"] == "Betreuung Q1 2027" and D1["items"][0]["detail"] == "Jahr 2027 {unbekannt}" and float(D1["totals"]["gross"]) == 595,
      f"the placeholders filled, unknown braces stay {D1.get('project_title')} | {D1.get('intro')} | {D1['items'][0].get('title')} | {D1['items'][0].get('detail')}")
T1 = doc(A, TPL["id"])
check(T1["project_title"] == "Retainer {month}" and T1["items"][0]["title"] == "Betreuung {quarter}" and not T1.get("series_id"), "the template keeps its placeholders")
r = A.post(B + f"{S}/{S1['id']}/run")
D2 = doc(A, r.json()["doc_id"]) if r.ok else {}
check(D2.get("series_period") == "2027-02-28" and D2.get("service_to") == "2027-03-30" and D2.get("project_title") == "Retainer Februar 2027" and D2.get("id") != D1["id"],
      f"make now again: the next period, a new invoice {D2.get('series_period')} {D2.get('service_to')}")
it = items_of(A)[S1["id"]]
check(it["next_date"] == "2027-03-31" and [m["period"] for m in it["made"]] == ["2027-02-28", "2027-01-31"] and it["made_count"] == 2
      and str(D1["id"]) in A.get(B + S).json()["docs"], f"the list: next date, the invoices made (newest first), doc -> series {it.get('next_date')} {it.get('made')}")
# never twice
check(A.patch(B + f"{S}/{S1['id']}", json={"next_date": "2027-01-31"}).ok, "PATCH next_date (the undo of make now)")
r = A.post(B + f"{S}/{S1['id']}/run")
check(r.status_code == 409, "the same period again: 409 " + r.text[:120])
check(dbx("SELECT COUNT(*) FROM office_docs WHERE series_id=? AND series_period='2027-01-31'", (S1["id"],))[0][0] == 1, "one invoice per period")
check(A.patch(B + f"{S}/{S1['id']}", json={"next_date": "2027-02-15"}).status_code == 400, "next_date must be a period start")
check(A.patch(B + f"{S}/{S1['id']}", json={"next_date": "2027-03-31"}).ok, "back to the next free period")
r = A.post(B + f"{D}/{D1['id']}/duplicate")
check(r.status_code == 201 and not r.json().get("series_id") and not r.json().get("series_period"), "a copy of a series invoice is no invoice of the series " + r.text[:120])
DUP = r.json().get("id")
# quarterly, yearly, end, validation
TQ = invoice(A, CL, title="Wartung {quarter}")
r = A.post(B + S, json={"template_id": TQ["id"], "every": "quarterly", "start": "2027-11-30"})
check(r.status_code == 201 and r.json()["next_periods"] == ["2027-11-30", "2028-02-29", "2028-05-30"], "quarterly: every 3 months, the day kept " + r.text[:200])
SQ = r.json()
r = A.post(B + S, json={"template_id": TQ["id"], "every": "yearly", "start": "2028-02-29"})
check(r.status_code == 201 and r.json()["next_periods"] == ["2028-02-29", "2029-02-28", "2030-02-28"], "yearly: 29 February -> 28 February " + r.text[:200])
SY = r.json()
r = A.post(B + f"{S}/{SY['id']}/run")
DY = doc(A, r.json()["doc_id"]) if r.ok else {}
check(DY.get("service_to") == "2029-02-27" and DY.get("project_title") == "Wartung Q1 2028", f"yearly: a year of service {DY.get('service_to')} {DY.get('project_title')}")
for bad in ({"template_id": TQ["id"], "every": "weekly", "start": "2027-01-01"}, {"template_id": TQ["id"], "every": "monthly"},
            {"template_id": TQ["id"], "every": "monthly", "start": "2027-02-30"}, {"template_id": TQ["id"], "every": "monthly", "start": "2027-03-01", "until": "2027-02-01"}):
    check(A.post(B + S, json=bad).status_code == 400, f"validation: {bad}")
OFFER = A.post(B + D, json={"project_title": "Angebot", "client_id": CL}).json()["id"]
check(A.post(B + S, json={"template_id": OFFER, "every": "monthly", "start": "2027-01-01"}).status_code == 404, "a quotation is no template (404)")
TE = invoice(A, CL, title="Kurz")
r = A.post(B + S, json={"template_id": TE["id"], "every": "monthly", "start": "2027-06-01", "until": "2027-07-01"})
SE = r.json()
check(A.post(B + f"{S}/{SE['id']}/run").ok and items_of(A)[SE["id"]]["active"] == 1, "end: the first period, still on")
check(A.post(B + f"{S}/{SE['id']}/run").ok, "end: the last period")
it = items_of(A)[SE["id"]]
check(it["active"] == 0 and it["next_periods"] == [], f"end: after the last period the series is off {it.get('active')}")
check(A.post(B + f"{S}/{SE['id']}/run").status_code == 409, "end: make now refuses")
check(A.patch(B + f"{S}/{SE['id']}", json={"active": 1}).status_code == 409, "end: switching on needs a later end")
r = A.patch(B + f"{S}/{SE['id']}", json={"until": "2027-09-01", "active": 1})
check(r.ok and r.json()["active"] == 1 and r.json()["next_date"] == "2027-08-01", "a later end: on again, next date after the last invoice " + r.text[:160])
# PATCH: every -> next date after the last invoice made
r = A.patch(B + f"{S}/{SQ['id']}", json={"every": "monthly", "title": "Wartung monatlich"})
check(r.ok and r.json()["every"] == "monthly" and r.json()["title"] == "Wartung monatlich" and r.json()["next_date"] == "2027-11-30", "PATCH: interval and name " + r.text[:160])

# ================================================================== auto_send
mails0 = len(mails())
TS = invoice(A, CL, title="Abo {month}", rate=100)
r = A.post(B + S, json={"template_id": TS["id"], "every": "monthly", "start": "2027-05-01", "auto_send": 1})
SS = r.json()
check(r.status_code == 201 and SS["auto_send"] == 1, "auto_send: the series " + r.text[:120])
r = A.post(B + f"{S}/{SS['id']}/run")
check(r.ok and r.json().get("sent") is True and not r.json().get("error"), "auto_send: sent at once " + r.text[:300])
DS = doc(A, r.json()["doc_id"]) if r.ok else {}
check(DS.get("status") == "sent" and (DS.get("number") or "").startswith("RE-") and DS.get("locked"), f"auto_send: finalised with its number, status sent {DS.get('status')} {DS.get('number')}")
m = until(lambda: [x for x in mails()[mails0:] if "rechnung@kunde-eins.example" in json.dumps(x)], 10)
check(bool(m), "auto_send: the mail to the client's invoice address")
x = A.get(B + f"{D}/{DS.get('id')}/xml")
check(x.ok and b"CrossIndustryInvoice" in x.content, f"auto_send: the e-invoice like any invoice {x.status_code}")
TN = invoice(A, CLN, title="Ohne Mail")
SN = A.post(B + S, json={"template_id": TN["id"], "every": "monthly", "start": "2027-05-01", "auto_send": 1}).json()
r = A.post(B + f"{S}/{SN['id']}/run")
DN = doc(A, r.json()["doc_id"]) if r.ok else {}
check(r.ok and r.json().get("sent") is False and "e-mail" in (r.json().get("error") or "") and DN.get("status") == "draft" and not DN.get("number"),
      "auto_send without a mail address: a draft without number, the reason " + r.text[:300])

# ================================================================== the cash flow
M0 = TODAY.isoformat()[:7]
M1 = first_of(TODAY, 1)
T2 = invoice(A, CL, title="Monatlich")
S2 = A.post(B + S, json={"template_id": T2["id"], "every": "monthly", "start": M1.isoformat()}).json()


def cf(basis="gross"):
    return A.get(B + O + f"/cashflow?from={M0}&months=3&basis={basis}").json()["entries"]


es = [e for e in cf() if e.get("series_id") == S2["id"]]
check(len(es) == 2 and all(e["kind"] == "series" and e["dir"] == "in" and e["state"] == "plan" and e["amount"] == "595.00" for e in es)
      and es[0]["date"] == (M1 + timedelta(days=14)).isoformat(), f"cash flow: the coming periods as planned income (period + payment days) {es}")
check([e["amount"] for e in cf("net") if e.get("series_id") == S2["id"]] == ["500.00", "500.00"], "cash flow: net basis")
check(any(e.get("series_id") == S1["id"] and e.get("doc_id") == D2["id"] for e in cf()), "cash flow: a draft of a series counts with its document")
r = A.post(B + f"{S}/{S2['id']}/run")
DC = r.json().get("doc_id")
es = [e for e in cf() if e.get("series_id") == S2["id"]]
check(len(es) == 2 and sum(1 for e in es if e.get("doc_id") == DC) == 1 and not any(e.get("period") == M1.isoformat() and not e.get("doc_id") for e in es),
      f"cash flow: the made period counts once (its draft) {es}")
check(A.post(B + f"{D}/{DC}/finalize").ok, "cash flow: the draft finalised")
ent = cf()
check(sum(1 for e in ent if e.get("series_id") == S2["id"]) == 1 and any(e["kind"] == "invoice" and e.get("doc_id") == DC for e in ent),
      "cash flow: a finalised series invoice is an open invoice, not a series entry")
check(A.patch(B + f"{S}/{S2['id']}", json={"active": 0}).ok and not any(e.get("series_id") == S2["id"] for e in cf()), "cash flow: a paused series counts not")

# ================================================================== the bin
r = A.delete(B + f"{S}/{SQ['id']}")
check(r.ok and r.json()["item"]["deleted"] is True, "delete: into the bin")
check(SQ["id"] not in items_of(A) and any(x["id"] == SQ["id"] for x in A.get(B + S + "?bin=1").json()["items"]), "delete: out of the list, in the bin")
check(A.post(B + f"{S}/{SQ['id']}/run").status_code == 404 and A.patch(B + f"{S}/{SQ['id']}", json={"title": "x"}).status_code == 404, "a deleted series: 404")
r = A.post(B + f"{S}/{SQ['id']}/restore")
check(r.ok and SQ["id"] in items_of(A), "restore: back in the list")
check(dbx("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND action='series_create'", (ORG,))[0][0] > 0, "the office log records the series")

# ================================================================== rights
check(Bo.get(B + S).status_code == 403 and Bo.post(B + S, json={"template_id": TPL["id"], "every": "monthly", "start": "2027-01-01"}).status_code == 403
      and Bo.post(B + f"{S}/{S1['id']}/run").status_code == 403, "a member: 403")
assert Ca.put(B + O + "/settings", json={"company_fields": COMPANY}).ok
check(Ca.get(B + S).json()["items"] == [], "another organisation sees no series")
check(all(x.status_code == 404 for x in (Ca.patch(B + f"{S}/{S1['id']}", json={"title": "x"}), Ca.post(B + f"{S}/{S1['id']}/run"), Ca.delete(B + f"{S}/{S1['id']}"),
                                         Ca.post(B + f"{S}/{S1['id']}/restore"), Ca.post(B + S, json={"template_id": TPL["id"], "every": "monthly", "start": "2027-01-01"}))),
      "another organisation: its series and template 404")
CLC = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG", "street": "A 1", "zip": "1", "city": "B"}).json()["id"]
TC = invoice(Ca, CLC)
check(A.post(B + S, json={"template_id": TC["id"], "every": "monthly", "start": "2027-01-01"}).status_code == 404, "a template of another organisation: 404")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helfer", "display_name": "Helfer"})
AG = {**H, "Authorization": "Bearer " + r.json()["token"]}
check(all(x.status_code in (401, 403) for x in (requests.get(B + S, headers=AG), requests.post(B + f"{S}/{S1['id']}/run", headers=AG))), "an agent: 403")

# ================================================================== a freelancer (personal office)
st = Da.get(B + O + "/settings").json()
check(st.get("personal") == 1 and st.get("role") == "admin", "freelancer: the personal office")
assert Da.put(B + O + "/settings", json={"lang": "de", "company_fields": {**COMPANY, "name": "Dave Schnitt"}}).ok
CLD = Da.post(B + "/api/clients", json={"name": "Privatkunde Studio", "street": "Weg 3", "zip": "10115", "city": "Berlin", "country": "DE",
                                        "email_invoice": "buchhaltung@studio.example"}).json()["id"]
TD = invoice(Da, CLD, title="Schnitt {month}")
r = Da.post(B + S, json={"template_id": TD["id"], "every": "monthly", "start": "2027-03-01", "auto_send": 1})
check(r.status_code == 201, "freelancer: a series " + r.text[:200])
SD = r.json()
r = Da.post(B + f"{S}/{SD['id']}/run")
DD = doc(Da, r.json()["doc_id"]) if r.ok else {}
check(r.ok and r.json().get("sent") is True and DD.get("project_title") == "Schnitt März 2027" and (DD.get("number") or ""), "freelancer: sent with its number " + r.text[:200])
check(any(e.get("series_id") == SD["id"] for e in Da.get(B + O + "/cashflow?from=2027-03&months=3").json()["entries"]), "freelancer: the series in the own cash flow")
check(all(x.status_code == 404 for x in (A.patch(B + f"{S}/{SD['id']}", json={"title": "x"}), A.post(B + f"{S}/{SD['id']}/run"),
                                         A.post(B + S, json={"template_id": TD["id"], "every": "monthly", "start": "2027-01-01"}))) and SD["id"] not in items_of(A),
      "freelancer: the organisation's admin sees and reaches nothing of it")
check(Da.post(B + S, json={"template_id": TPL["id"], "every": "monthly", "start": "2027-01-01"}).status_code == 404 and Da.post(B + f"{S}/{S1['id']}/run").status_code == 404,
      "freelancer: nothing of the organisation")

# ================================================================== the watchdog
TW = invoice(A, CL, title="Wächter {month}")
p3 = first_of(TODAY, -2)
SW = A.post(B + S, json={"template_id": TW["id"], "every": "monthly", "start": p3.isoformat(), "title": "Waechter"}).json()
got = until(lambda: dbx("SELECT id, series_period FROM office_docs WHERE series_id=? ORDER BY series_period", (SW["id"],)), 60)
check(len(got) >= 1 and got[0][1] == p3.isoformat(), f"watchdog: the oldest missed period first {got}")
tk = until(lambda: dbx("SELECT title, url, content FROM tasks WHERE assignee_id=? AND url LIKE ?", (ALICE, f"%#office/offers/{got[0][0]}")) if got else [], 10)
check(bool(tk) and "Waechter" in tk[0][0] and "595" not in tk[0][0] and "595" not in (tk[0][2] or ""), f"watchdog: a task in the creator's inbox with the link, no amount {tk}")
got = until(lambda: (lambda x: x if len(x) >= 2 else None)(dbx("SELECT id, series_period FROM office_docs WHERE series_id=? ORDER BY series_period", (SW["id"],))), 60) or []
check(len(got) >= 2 and got[1][1] == first_of(TODAY, -1).isoformat(), f"watchdog: one period per run, the next one later {got}")
TW2 = invoice(A, CL, title="Lange her")
SW2 = A.post(B + S, json={"template_id": TW2["id"], "every": "monthly", "start": first_of(TODAY, -6).isoformat(), "title": "Lange her"}).json()
got = until(lambda: dbx("SELECT id, series_period FROM office_docs WHERE series_id=?", (SW2["id"],)), 60)
check(len(got) == 1 and got[0][1] == first_of(TODAY, 0).isoformat(), f"watchdog: more than 3 missed periods: only the newest {got}")
tk = dbx("SELECT content FROM tasks WHERE assignee_id=? AND url LIKE ?", (ALICE, f"%#office/offers/{got[0][0]}")) if got else []
check(bool(tk) and "Missed periods" in tk[0][0], f"watchdog: the task names the missed periods {tk}")
nx = items_of(A)[SW2["id"]]["next_date"]
check(nx == first_of(TODAY, 1).isoformat(), f"watchdog: next date after the newest {nx}")
TW3 = invoice(A, CL, title="Weg")
SW3 = A.post(B + S, json={"template_id": TW3["id"], "every": "monthly", "start": first_of(TODAY, 1).isoformat(), "title": "Vorlage weg"}).json()
check(A.delete(B + f"{D}/{TW3['id']}").ok, "the template draft deleted")
dbx("UPDATE office_inv_series SET next_date=? WHERE id=?", (TODAY.isoformat(), SW3["id"]))
off = until(lambda: dbx("SELECT active FROM office_inv_series WHERE id=? AND active=0", (SW3["id"],)), 60)
check(bool(off) and not dbx("SELECT 1 FROM office_docs WHERE series_id=?", (SW3["id"],)), "watchdog: a deleted template pauses the series, no invoice")
check(bool(dbx("SELECT 1 FROM tasks WHERE assignee_id=? AND title LIKE ?", (ALICE, "%Vorlage weg%paused%"))), "watchdog: a task says it is paused")
check(not dbx("SELECT 1 FROM office_docs WHERE series_id=? AND series_period>?", (S1["id"], "2027-02-28")), "watchdog: series with future periods make nothing")
check(dbx("SELECT COUNT(*) FROM office_docs WHERE series_id IS NOT NULL GROUP BY series_id, series_period HAVING COUNT(*) > 1") == [], "never two invoices for one period")
if DUP:
    check(dbx("SELECT series_id FROM office_docs WHERE id=?", (DUP,))[0][0] is None, "the copy stays outside the series")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
