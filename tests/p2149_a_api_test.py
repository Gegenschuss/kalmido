#!/usr/bin/env python3
"""2.149.0 API tests, part A: the office's web and agent routes alike (#2521), the documents' words through tr() (#2520).
Own container (start.sh with the webhook stub). Invented companies, people and figures only, addresses @example.com.
 - #2521 agents (organisation): a quotation draft, its change (head + positions) and the invoice / reminder drafts write the
   same office log lines as a person's ("create" with from_id, "update" diff, "items" before / after); an agent's invoice
   still needs an accepted quotation (409 for a draft or a sent one), a person's route makes one from every status on
   purpose (#2235); a payment suggestion above the open amount 409 like a person's payment (exceeds_open stays, false);
   a person's head / position change still works (now under the document lock)
 - #2521 a person without an organisation (freelancer-matrix: office): the same in the personal office; the project
   proposal's undo keeps the quotation once an invoice was made from it (named in skipped) and still deletes an untouched
   one; an invoice series' "make now" sends the webhook invoice.created
 - #2520 the words: every new key's German text is the old inline German word for word, its English display the old
   English; a German and an English invoice draft / progress invoice / cash discount line print as before
usage: p2149_a_api_test.py <datadir>   (P2149A_NOSTART=1: the container runs already with the webhook stub)"""
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:8097"
O = "/api/office"
D = O + "/docs"
V = B + "/api/v1/office"
TODAY = testclock.today().isoformat()
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def got(path, event, pred=None, timeout=15):
    """Payloads the stub received on path for event (and pred(data)), waiting up to timeout seconds for the first."""
    def f():
        out = []
        try:
            rows = [json.loads(x) for x in open(os.path.join(DATA, "wh.log")) if x.strip()]
        except FileNotFoundError:
            rows = []
        for r in rows:
            if r["path"] != path or r["headers"].get("X-Kalmido-Event") != event:
                continue
            p = json.loads(r["body"])
            if pred is None or pred(p["data"]):
                out.append(p)
        return out
    t0 = time.time()
    while time.time() - t0 < timeout:
        x = f()
        if x:
            return x
        time.sleep(0.3)
    return f()


# ---------------------------------------------------------------- #2520: the words (no server needed)
# key -> (the old inline German, the old English or None where the old fallback was German in both languages)
OLD = {
    "Invoice|document": ("Rechnung", "Invoice"), "Credit note|document": ("Gutschrift", "Credit note"),
    "Payment reminder|document": ("Zahlungserinnerung", "Payment reminder"), "Reminder|document": ("Mahnung", "Reminder"),
    "Final reminder|document": ("Letzte Mahnung", "Final reminder"), "Delivery note|document": ("Lieferschein", "Delivery note"),
    "Proof of service|document": ("Leistungsnachweis", "Proof of service"), "Quotation|document": ("Angebot", "Quotation"),
    "Invoice no.|document": ("Rechnung Nr.", None), "{0} No.|document": ("{0} Nr.", "{0} No."), "Draft|document number": ("Entwurf", "Draft"),
    "Credit note for invoice no.|document": ("zu Rechnung Nr.", "Credit note for invoice no."), "Ref./PO no.|document": ("Ref./PO-Nr.", None),
    "Project title|document": ("Projekttitel", None), "Customer no.|document": ("Kunden-Nr.", "Customer no."), "Date|document": ("Datum", None),
    "Service period|document": ("Leistungszeitraum", "Service period"), "Period of service|document": ("Leistungszeitraum", "Period of service"),
    "Due on|document": ("Fällig am", "Due on"), "Exchange rate €1|document": ("Wechselkurs 1 €", "Exchange rate €1"),
    "Tax amount equals EUR {tax}, rate EUR 1 = USD {rate}|document": ("Steuerbetrag entspricht {tax} EUR, Kurs 1 EUR = {rate} USD",
                                                                     "Tax amount equals EUR {tax}, rate EUR 1 = USD {rate}"),
    "Amount outstanding|document": ("Offener Betrag", "Amount outstanding"), "Reminder fee|document": ("Mahngebühr", "Reminder fee"),
    "Total amount due|document": ("Gesamtbetrag", "Total amount due"), "Due|document": ("Fällig", "Due"), "Amount|document": ("Betrag", "Amount"),
    "Subtotal|document": ("Zwischensumme", "Subtotal"), "Total|invoice": ("Rechnungsbetrag", "Total"), "Total|credit note": ("Gutschriftsbetrag", "Total"),
    "Already paid|document": ("Bereits bezahlt", "Already paid"), "Received / accepted|document": ("Erhalten / abgenommen", "Received / accepted"),
    "Payable by {date} without deduction.|document": ("Zahlbar bis {date} ohne Abzug.", "Payable by {date} without deduction."),
    "Quotation no.|document": ("Angebot Nr.", None), "Valid until|document": ("Gültig bis", None), "Exceptions|document": ("Ausnahmen", None),
    "Exclusive|document": ("Exklusiv", None), "yes|document": ("ja", "yes"), "Page {x} of {y}|document": ("Seite {x} von {y}", "Page {x} of {y}"),
    "Part|document": ("Teil", "Part"), "Film production|document": ("Filmherstellung", "Film production"),
    "Progress invoice|document": ("Abschlagsrechnung", "Progress invoice"), "Final invoice|document": ("Schlussrechnung", "Final invoice"),
    "Progress payment no. {n} on quotation {num}|document": ("Abschlag Nr. {n} auf Angebot {num}", "Progress payment no. {n} on quotation {num}"),
    "Share at {pct} % VAT|document": ("Anteil {pct} % USt", "Share at {pct} % VAT"),
    "{p} % of the quotation's net|document": ("{p} % des Angebots-Netto", "{p} % of the quotation's net"),
    "Less progress invoices already issued|document": ("Abzüglich bereits berechneter Abschläge", "Less progress invoices already issued"),
    "Less progress invoice no. {num} of {date}|document": ("Abzüglich Abschlagsrechnung Nr. {num} vom {date}", "Less progress invoice no. {num} of {date}"),
    "Net {net}, VAT {pct} % {tax}, gross {gross}{paid}|document": ("Netto {net}, USt {pct} % {tax}, brutto {gross}{paid}",
                                                                   "Net {net}, VAT {pct} % {tax}, gross {gross}{paid}"),
    " (paid)|document": (" (bezahlt)", " (paid)"), " (open)|document": (" (offen)", " (open)"), "Amount remaining|document": ("Restbetrag", "Amount remaining"),
    "When paid by {date} {pct} % cash discount (= {amt}), payable {pay}.|document": ("Bei Zahlung bis {date} {pct} % Skonto (= {amt}), zahlbar {pay}.",
                                                                                     "When paid by {date} {pct} % cash discount (= {amt}), payable {pay}."),
}
I18N = os.path.join(N, "..", "static", "i18n")
de = json.load(open(os.path.join(I18N, "de.json"), encoding="utf-8"))
for k, (old_de, old_en) in OLD.items():
    check(de.get(k) == old_de, f"#2520: de.json {k!r} = the old German {old_de!r} (is {de.get(k)!r})")
    if old_en is not None:
        check(k[:k.find("|")] == old_en, f"#2520: the English display of {k!r} is the old {old_en!r}")
for lg in ("es", "fr", "it", "nl"):
    t = json.load(open(os.path.join(I18N, lg + ".json"), encoding="utf-8"))
    check(all(isinstance(t.get(k), str) and t[k] for k in OLD), f"#2520: {lg}.json has every document word")
SRC = os.path.join(N, "..", "kalmido", "office")
code = "".join(open(os.path.join(SRC, f), encoding="utf-8").read() for f in ("invoices.py", "docs.py", "parts.py", "abschlag.py"))
check(all(k in code for k in OLD), "#2520: every key is used by the office code")
for bad in ('"Entwurf"', '"Rechnungsbetrag"', '"Zahlbar bis', '"Abschlagsrechnung"', '"Teil")', '"Seite {x} von {y}"'):
    check(bad not in code, f"#2520: no inline German {bad} left in the documents' code")

# ---------------------------------------------------------------- the server
if not os.environ.get("P2149A_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_webhook.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                       env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_WEBHOOK_TICK=1"),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webhook.py"])
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
FEAT = "cal,comments,collab,office,clients"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
A.get(B + O + "/settings")
A.put(B + O + "/settings", json={"company_fields": COMPANY, "agents_read": 1})
CL = A.post(B + "/api/clients", json={"name": "Musterfirma GmbH", "street": "Weg 2", "zip": "10115", "city": "Berlin", "country": "DE"}).json()["id"]
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.status_code == 201, "setup: a personal agent " + r.text[:200])
AG, AH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok, "setup: the agent may draft office documents")


def ag(m, path, hd=AH, **kw):
    return requests.request(m, V + path, headers=hd, **kw)


def log_of(s, did):
    return [x for x in s.get(B + O + "/log", params={"limit": 500}).json()["log"] if x.get("doc_id") == did]


def agent_chain(s, hd, uid, client, tag):
    """The agent's way through one office area (organisation or personal office) as person s (uid)."""
    r = ag("POST", "/offers", hd, json={"client_id": client, "title": f"Imagefilm {tag}", "items": [{"text": "Kamera", "qty": 1, "unit": "day", "price": 800}]})
    check(r.status_code == 201, f"{tag}: an agent's quotation draft " + r.text[:200])
    q = r.json()["doc"]["id"]
    lg = log_of(s, q)
    check(any(x["action"] == "create" and x["user_id"] == uid for x in lg), f"{tag}: the quotation draft has its office log line 'create' {[x['action'] for x in lg]}")
    r = ag("PATCH", f"/offers/{q}", hd, json={"title": f"Imagefilm {tag} lang", "items": [{"text": "Kamera", "qty": 2, "unit": "day", "price": 800}]})
    check(r.ok, f"{tag}: the agent changes its draft " + r.text[:200])
    lg = log_of(s, q)
    up = [x for x in lg if x["action"] == "update"]
    check(up and "project_title" in (up[-1]["detail"].get("after") or {}), f"{tag}: the change has its 'update' line with the diff {up[-1:]}")
    it = [x for x in lg if x["action"] == "items"]
    check(it and it[-1]["detail"].get("before") and it[-1]["detail"].get("after") and it[-1]["detail"]["before"] != it[-1]["detail"]["after"],
          f"{tag}: the positions have their 'items' line before / after")
    check(ag("POST", f"/offers/{q}/invoice", hd, json={}).status_code == 409, f"{tag}: an agent makes no invoice from a draft quotation (409)")
    check(s.post(B + f"{D}/{q}/finalize").ok and s.post(B + f"{D}/{q}/status", json={"status": "sent"}).ok, f"{tag}: the person finalises and sends it")
    check(ag("POST", f"/offers/{q}/invoice", hd, json={}).status_code == 409, f"{tag}: ... nor from a sent one (409, the agent sets no status)")
    check(s.get(B + f"{D}/{q}").json()["status"] == "sent", f"{tag}: the quotation stays sent")
    check(s.post(B + f"{D}/{q}/status", json={"status": "accepted"}).ok, f"{tag}: the quotation is accepted")
    r = ag("POST", f"/offers/{q}/invoice", hd, json={})
    check(r.status_code == 201 and r.json()["doc"]["kind"] == "invoice", f"{tag}: the agent's invoice draft " + r.text[:200])
    inv = r.json()["doc"]["id"]
    cr = [x for x in log_of(s, inv) if x["action"] == "create"]
    check(cr and cr[0]["detail"].get("from_id") == q and cr[0]["detail"].get("kind") == "invoice" and cr[0]["user_id"] == uid,
          f"{tag}: the invoice draft has its 'create' line with from_id like a person's {cr}")
    s.patch(B + f"{D}/{inv}", json={"service_from": TODAY, "service_to": TODAY})
    r = s.post(B + f"{D}/{inv}/finalize")
    check(r.ok, f"{tag}: the person finalises the invoice " + r.text[:200])
    r = ag("POST", "/reminders", hd, json={"invoice_ids": [inv], "level": 1})
    check(r.status_code == 201, f"{tag}: the agent's reminder draft " + r.text[:200])
    rem = r.json()["doc"]["id"] if r.status_code == 201 else 0
    cr = [x for x in log_of(s, rem) if x["action"] == "create"]
    check(cr and cr[0]["detail"].get("kind") == "reminder" and cr[0]["detail"].get("doc_ids") == [inv], f"{tag}: the reminder has its 'create' line {cr}")
    gross = float(s.get(B + f"{D}/{inv}").json()["totals"]["gross"])
    r = ag("POST", "/payment-suggestions", hd, json={"invoice_id": inv, "amount": f"{gross + 100:.2f}", "date": TODAY})
    check(r.status_code == 409, f"{tag}: a payment suggestion above the open amount: 409 like a person's payment ({r.status_code} {r.text[:160]})")
    r = ag("POST", "/payment-suggestions", hd, json={"invoice_id": inv, "amount": "100.00", "date": TODAY})
    check(r.status_code == 201 and r.json().get("exceeds_open") is False, f"{tag}: below it 201, exceeds_open stays (false) " + r.text[:200])
    r = ag("POST", "/payment-suggestions", hd, json={"invoice_id": inv, "amount": f"{gross:.2f}", "date": TODAY})
    check(r.status_code == 201, f"{tag}: the whole open amount is no excess " + r.text[:160])
    # a person's route: an invoice from every status (#2235), head and positions under the document lock
    q2 = s.post(B + D, json={"client_id": client, "project_title": f"Entwurf {tag}"}).json()["id"]
    check(s.patch(B + f"{D}/{q2}", json={"project_title": f"Entwurf {tag} 2"}).ok, f"{tag}: a person changes the head")
    check(s.put(B + f"{D}/{q2}/items", json={"items": [{"kind": "service", "title": "Schnitt", "qty": 1, "unit": "day", "rate": 600}]}).ok,
          f"{tag}: a person changes the positions")
    r = s.post(B + f"{D}/{q2}/invoice", json={})
    check(r.status_code == 201, f"{tag}: a person still makes an invoice from a draft quotation (#2235) " + r.text[:160])
    check(s.get(B + f"{D}/{q2}").json()["status"] == "draft", f"{tag}: the quotation's status stays as it was")
    cr = [x for x in log_of(s, r.json().get("id")) if x["action"] == "create"]
    check(cr and cr[0]["detail"].get("from_id") == q2, f"{tag}: a person's invoice has its 'create' line as before {cr}")
    return q, inv


agent_chain(A, AH, ALICE, CL, "org")

# ---------------------------------------------------------------- #2520: German and English documents print as before
def render(s, did):
    r = s.get(B + f"{D}/{did}/render")
    assert r.ok, r.text
    return r.json()


def doc_lang_checks(s, client, lang, tag):
    q = s.post(B + D, json={"client_id": client, "project_title": f"Sprache {lang}", "lang": lang}).json()["id"]
    s.put(B + f"{D}/{q}/items", json={"items": [{"kind": "service", "title": "Kamera", "qty": 1, "unit": "day", "rate": 1000}]})
    s.post(B + f"{D}/{q}/finalize")
    s.post(B + f"{D}/{q}/status", json={"status": "sent"})
    s.post(B + f"{D}/{q}/status", json={"status": "accepted"})
    qn = s.get(B + f"{D}/{q}").json()["number"]
    inv = s.post(B + f"{D}/{q}/invoice", json={}).json()["id"]
    m = render(s, inv)
    num = m["meta"][0][1]
    check(num == ("Draft" if lang == "en" else "Entwurf"), f"#2520 {tag}: the draft number reads as before ({lang}: {num!r})")
    r = s.patch(B + f"{D}/{inv}", json={"skonto_pct": 2, "skonto_days": 10, "payment_days": 30})
    check(r.ok, f"#2520 {tag}: cash discount set " + r.text[:160])
    pt = (render(s, inv).get("payment") or {}).get("text") or ""
    check(("When paid by " if lang == "en" else "Bei Zahlung bis ") in pt and ("% cash discount" if lang == "en" else "% Skonto") in pt,
          f"#2520 {tag}: the cash discount line as before ({pt!r})")
    r = s.post(B + f"{D}/{q}/invoice", json={"inv_type": "progress", "pct": 30})
    check(r.status_code == 201, f"#2520 {tag}: a progress invoice " + r.text[:160])
    m = render(s, r.json()["id"])
    check(m["title"] == ("Progress invoice" if lang == "en" else "Abschlagsrechnung"), f"#2520 {tag}: the progress invoice's title ({m['title']!r})")
    items = [ln for ln in m.get("lines") or [] if ln.get("kind") == "item"]
    want = (f"Progress payment no. 1 on quotation {qn}" if lang == "en" else f"Abschlag Nr. 1 auf Angebot {qn}")
    check(items and items[0].get("title") == want, f"#2520 {tag}: the progress position reads as before ({[x.get('title') for x in items]})")
    check(items and ("30 % of the quotation's net" if lang == "en" else "30 % des Angebots-Netto") in (items[0].get("detail") or ""),
          f"#2520 {tag}: its detail ({items[0].get('detail') if items else ''!r})")


doc_lang_checks(A, CL, "de", "org")
doc_lang_checks(A, CL, "en", "org")

# ---------------------------------------------------------------- a person without an organisation
# freelancer-matrix: office
FID, F = freelancer(B, A)
F.get(B + O + "/settings")
F.put(B + O + "/settings", json={"company_fields": {**COMPANY, "name": "Frida Film"}, "agents_read": 1})
CLF = F.post(B + "/api/clients", json={"name": "Example Ltd", "street": "Marktweg 5", "zip": "50667", "city": "Köln", "country": "DE"}).json()["id"]
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "write", "office"]})
check(r.status_code == 201, "freelancer: her own agent " + r.text[:200])
FAG, FTOK = r.json()["id"], r.json()["token"]
FH = {**H, "Authorization": "Bearer " + FTOK}
check(F.patch(B + f"{O}/agents/{FAG}", json={"office_drafts": True}).ok, "freelancer: she switches her agent's office right on")
agent_chain(F, FH, FID, CLF, "freelancer")
doc_lang_checks(F, CLF, "de", "freelancer")

# the project proposal's undo (agents/propkinds2.py): the quotation stays once an invoice was made from it
W = F.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
F.put(B + f"/api/lists/{W}/members", json={"user_id": FAG, "role": "edit"})
OWN = {"name": "Image film Example", "client": {"name": "example ltd"}, "sections": ["Prep", "Shoot"],
       "tasks": [{"title": "Call back the client", "section": "Prep", "due": "2027-05-01"}],
       "shoot_days": [{"title": "Shoot day 1", "date": "2027-05-10", "location": "Studio"}],
       "offer": {"title": "Image film", "items": [{"text": "Camera day", "qty": 2, "unit": "day", "price": 900}]}}


def offer_apply():
    r_ = requests.post(B + "/api/v1/agent/proposals", headers=FH, json={"kind": "inquiry", "user_id": FID, "proposal": OWN})
    jid = r_.json().get("id") if r_.status_code == 201 else None
    check(jid and r_.json()["input"]["office"]["ok"] is True, f"undo: the agent's project proposal with the office ({r_.status_code} {r_.text[:160]})")
    r_ = F.post(B + f"/api/proposals/{jid}/apply", json={"select": ["0", "400", "400.0"]})
    check(r_.ok and r_.json().get("offer_id"), f"undo: applying makes the quotation draft ({r_.text[:160]})")
    return jid, (r_.json().get("offer_id") if r_.ok else None)


J1, Q1 = offer_apply()
r = F.post(B + f"{D}/{Q1}/invoice", json={})
check(r.status_code == 201, "undo: an invoice is made from the proposal's quotation draft " + r.text[:160])
r = F.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and F.get(B + f"{D}/{Q1}").ok and r.json().get("skipped"), f"undo: the quotation an invoice came from stays, named ({r.text[:200]})")
J2, Q2 = offer_apply()
r = F.post(B + f"/api/proposals/{J2}/undo")
check(r.ok and F.get(B + f"{D}/{Q2}").status_code == 404, f"undo: an untouched quotation draft still goes ({r.text[:200]})")

# the invoice series' "make now": the webhook invoice.created (like a person's copy)
r = F.post(B + "/api/me/webhooks", json={"name": "office", "url": STUB + "/frida", "events": ["invoice.created"]})
check(r.status_code == 201, f"series: a personal webhook {r.status_code} {r.text[:160]}")
tq = F.post(B + D, json={"client_id": CLF, "project_title": "Retainer"}).json()["id"]
F.put(B + f"{D}/{tq}/items", json={"items": [{"kind": "service", "title": "Betreuung", "qty": 1, "unit": "flat", "rate": 500}]})
tpl = F.post(B + f"{D}/{tq}/invoice", json={}).json()["id"]
r = F.post(B + O + "/series", json={"template_id": tpl, "every": "monthly", "start": TODAY})
check(r.status_code == 201, "series: created " + r.text[:200])
sid = r.json().get("id")
r = F.post(B + f"{O}/series/{sid}/run")
check(r.ok and r.json().get("doc_id"), "series: make now " + r.text[:200])
made = r.json().get("doc_id")
check(bool(got("/frida", "invoice.created", lambda d: d["invoice"]["id"] == made)), "series: the webhook invoice.created of the series' invoice")

print(f"p2149_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
