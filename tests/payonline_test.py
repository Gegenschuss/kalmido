#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.469.0 (#3459): online payment of invoices. Own container with a stand-in for the provider inside (stub_payonline.py, port 8099:
no real provider or account is called), the mail stub; invented names only.
 - off until set up; keys never in an answer nor plain in the database; a member cannot change it (freelancer-matrix: office)
 - pay link: the finalised PDF is frozen with the link, a draft / credit note / cancelled / switched off one has none; the amount comes
   from the database; pressing twice = one checkout
 - webhook: wrong, old and missing signature; the same event twice; a second event of the same payment; another organisation's
   session (tenant-matrix: office); part payment, refund, dispute, events in the wrong order, a direct debit that settles later
 - what cannot be booked is held and told, nothing is lost; a collective payout in the bank list counts nothing twice, its fees become
   a receipt; a person without an organisation does all of it in the personal office; the portal shows the button
usage: payonline_test.py <datadir>      (PAYONLINE_NOSTART=1 = the server already runs with both stubs)"""
import base64
import email
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, N, check, sess, until  # noqa: E402

O = "/api/office"
D = O + "/docs"
FEAT = "cal,comments,collab,office,clients"
STUB = "http://127.0.0.1:8099"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "hallo@beispiel.example",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
KEY, SECRET = "sk_test_good", "whsec_alpha_0123456789"
MAILENV = ["-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none", "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]

if os.environ.get("PAYONLINE_NOSTART") != "1":
    extra = ["-e KALMIDO_INSTANCE_MODE=workspaces", "-e KALMIDO_ORGCRYPT_DELAY=0", "-e KALMIDO_PAYONLINE_GO_RATE=40", "-e KALMIDO_SECRET_KEY=" + base64.b64encode(secrets.token_bytes(32)).decode(), f"-e KALMIDO_PAYONLINE_STRIPE_URL={STUB}", "-e KALMIDO_PAYONLINE_ALLOW_HOSTS=127.0.0.1:8099", " ".join(MAILENV)]
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    for f in ("stub_payonline.py", "stub_mail.py"):
        subprocess.run(["docker", "exec", "-i", CT, "sh", "-c", f"cat > /tmp/{f}"], input=open(os.path.join(N, f), "rb").read(), check=True)
        subprocess.run(["docker", "exec", "-d", CT, "python", f"/tmp/{f}"], check=True)
    time.sleep(1.0)
kt.docker_logs_on_first_fail()


def dbx(sql, args=()):
    return kt.dbx(sql, args, DATA)


def stub_log():
    p = os.path.join(DATA, "payonline.log")
    return [json.loads(x) for x in open(p).read().splitlines()] if os.path.exists(p) else []


def mails(to):
    out = []
    try:
        lines = open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return out
    for ln in lines:
        j = json.loads(ln)
        if any(to in x for x in j["to"]):
            txt = ""
            for part in email.message_from_string(j["raw"]).walk():
                if part.get_content_type() == "text/plain":
                    txt += part.get_payload(decode=True).decode("utf-8", "replace")
            out.append(txt)
    return out


s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
assert A.put(B + O + "/settings", json={"lang": "en", "company_fields": COMPANY}).ok
assert Ca.put(B + O + "/settings", json={"lang": "en", "company_fields": dict(COMPANY, name="Andere Firma AG")}).ok


def client(s, name, **kw):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Marktweg 5", "zip": "10115", "city": "Berlin", "country": "DE", **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def invoice(s, cl, finalise=True, rate=500):
    r = s.post(B + D, json={"kind": "invoice", "lang": "en", "client_id": cl, "project_title": "Schnitt", "service_from": "2026-05-01",
                            "items": [{"title": "Schnitt", "qty": 2, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if finalise:
        f = s.post(B + f"{D}/{did}/finalize")
        assert f.ok, f.text
    return did


def state(s, did):
    return s.get(B + f"{D}/{did}").json()


def pays(s, did):
    return s.get(B + f"{D}/{did}/payments").json()


def tok_of(url):
    return url.rsplit("/", 1)[1]


def link_of(s, did):
    """The pay link's token of invoice did (the switch hands it out)."""
    return tok_of(s.put(B + f"{D}/{did}/pay-online", json={"on": 1}).json()["url"])


def hook_of(s):
    return tok_of(s.get(B + O + "/payonline").json()["webhook_url"])


EV = [0]


def sign(raw, secret, ts=None):
    ts = int(time.time()) if ts is None else ts
    return f"t={ts},v1={hmac.new(secret.encode(), f'{ts}.'.encode() + raw, hashlib.sha256).hexdigest()}"


def event(hook, typ, obj, secret=SECRET, eid=None, ts=None, created=None):
    EV[0] += 1
    raw = json.dumps({"id": eid or f"evt_{EV[0]}", "type": typ, "created": created or int(time.time()), "data": {"object": obj}}).encode()
    return requests.post(B + f"/api/hooks/pay/{hook}", data=raw, headers={"Stripe-Signature": sign(raw, secret, ts), "Content-Type": "application/json"})


def paid(hook, cs, amount, pi=None, secret=SECRET, **kw):
    return event(hook, "checkout.session.completed", {"id": cs, "payment_status": "paid", "amount_total": amount, "currency": "eur", "payment_intent": pi or f"pi_{cs}"},
                 secret, **kw)


def go(tok, **form):
    """Presses Pay now -> (status, the checkout's address, its session id)."""
    r = requests.post(B + f"/s/pay/{tok}/go", data=form, allow_redirects=False)
    loc = r.headers.get("Location", "")
    return r.status_code, loc, loc.rsplit("/", 1)[-1]


# ---------------------------------------------------------------- off until set up
CL = client(A, "Beispielkunde AG", email="kunde@example.com")
BEFORE = invoice(A, CL)
g = A.get(B + O + "/payonline").json()
check(g["provider"] == "" and not g["ready"] and not g["enabled"] and g["webhook_url"] == "", f"off until set up: {g}")
check("pay_online" not in state(A, BEFORE), "no pay_online on an invoice while nothing is set up")
check(not dbx("SELECT 1 FROM office_pay_links"), "no link made while nothing is set up")
check(A.put(B + O + "/payonline", json={"provider": "stripe", "enabled": 1}).status_code == 409, "switching on without the key = 409")
check(A.put(B + O + "/payonline", json={"provider": "nobody"}).status_code == 400, "an unknown provider = 400")
check(Bo.put(B + O + "/payonline", json={"provider": "stripe"}).status_code == 403, "a member cannot set it up")

# ---------------------------------------------------------------- the connection
r = A.put(B + O + "/payonline", json={"provider": "stripe", "secret_key": KEY, "webhook_secret": SECRET})
check(r.ok and r.json()["key_set"] and r.json()["webhook_secret_set"] and not r.json()["enabled"] and "/api/hooks/pay/kpw_" in r.json()["webhook_url"], f"saved, still off: {r.text[:300]}")
check(KEY not in r.text and SECRET not in r.text, "the answer holds no secret")
r = A.put(B + O + "/payonline", json={"enabled": 1})
check(r.ok and r.json()["ready"], "switched on")
g = A.get(B + O + "/payonline")
check(g.ok and KEY not in g.text and SECRET not in g.text, "the secrets are never in the GET")
m = Bo.get(B + O + "/payonline")
check(m.ok and "webhook_url" not in m.json() and not m.json()["can_edit"], "a member sees no webhook address")
row = dbx("SELECT secret_key, webhook_secret, hook_token FROM office_payonline WHERE org_id=?", (ORG,))[0]
check(all(str(x).startswith("kenc1:") for x in row), f"key, secret and webhook token sealed at rest: {[str(x)[:8] for x in row]}")
HOOK = hook_of(A)
check(A.post(B + O + "/payonline/check").json().get("ok") is True, "connection check works")
check(not stub_log() or all(x["auth"] == f"Bearer {KEY}" for x in stub_log()), "the provider got the office's key")
r = A.put(B + O + "/payonline", json={"secret_key": "sk_test_wrong"})
check(A.post(B + O + "/payonline/check").json() == {"ok": False, "code": "auth"}, "a wrong key is reported")
A.put(B + O + "/payonline", json={"secret_key": KEY})

# ---------------------------------------------------------------- the link: frozen with the finalised document
draft = invoice(A, CL, finalise=False)
check(not dbx("SELECT 1 FROM office_pay_links WHERE doc_id=?", (draft,)), "a draft has no link")
PLAIN = A.get(B + f"{D}/{BEFORE}/pdf").content
I1 = invoice(A, CL)
LINKED = A.get(B + f"{D}/{I1}/pdf").content
check(len(LINKED) > len(PLAIN) + 200, f"the PDF of a linked invoice has more (QR + text): {len(PLAIN)} -> {len(LINKED)}")
check(state(A, I1)["pay_online"]["url"].startswith("http"), "the document shows the link to admins")
check("url" not in state(Bo, I1)["pay_online"], "a member's view has no link")
T1 = link_of(A, I1)
pg = requests.get(B + f"/s/pay/{T1}")
check(pg.ok and ("1,190.00" in pg.text or "1.190,00" in pg.text), f"the page shows the open amount: {pg.text[:300]}")
check("Beispiel Film GmbH" in pg.text and "Beispielkunde" not in pg.text, "only the nearest: company, not the client")
check("https://checkout.stripe.com" in pg.headers.get("Content-Security-Policy", ""), "the form may lead to the provider")
check(pg.headers.get("X-Robots-Tag", "").startswith("noindex"), "noindex")
check(requests.get(B + "/s/pay/" + "x" * 43).status_code == 404, "an unknown token = 404")

# ---------------------------------------------------------------- checkout
st, url, cs = go(T1)
check(st == 303 and url.startswith("https://checkout.stripe.com/"), f"Pay now goes to the provider: {st} {url}")
reqs = [x for x in stub_log() if x["path"] == "/v1/checkout/sessions"]
check(len(reqs) == 1 and reqs[0]["form"]["line_items[0][price_data][unit_amount]"] == "119000" and reqs[0]["form"]["line_items[0][price_data][currency]"] == "eur",
      f"amount and currency from the database: {reqs}")
check(reqs and reqs[0]["idem"], "an idempotency key goes along")
st2, url2, _ = go(T1)
check(st2 == 303 and url2 == url and len([x for x in stub_log() if x["path"] == "/v1/checkout/sessions"]) == 1, "pressed twice: the same checkout")
check(requests.post(B + f"/s/pay/{T1}/go", data={"amount": "99999"}, allow_redirects=False).status_code == 400, "more than open = 400")

# ---------------------------------------------------------------- webhook: the signature first
raw = json.dumps({"id": "evt_bad", "type": "checkout.session.completed", "data": {"object": {"id": cs, "payment_status": "paid", "amount_total": 119000, "currency": "eur"}}}).encode()
U = B + f"/api/hooks/pay/{HOOK}"
check(requests.post(U, data=raw).status_code == 400, "no signature = 400")
check(requests.post(U, data=raw, headers={"Stripe-Signature": sign(raw, "whsec_other")}).status_code == 400, "a wrong signature = 400")
check(requests.post(U, data=raw, headers={"Stripe-Signature": sign(raw, SECRET, int(time.time()) - 400)}).status_code == 400, "an old signature = 400")
check(requests.post(U, data=raw + b" ", headers={"Stripe-Signature": sign(raw, SECRET)}).status_code == 400, "a changed body = 400")
check(requests.post(B + "/api/hooks/pay/kpw_nothing", data=raw, headers={"Stripe-Signature": sign(raw, SECRET)}).status_code == 404, "an unknown webhook token = 404")
check(pays(A, I1)["payments"] == [] and not dbx("SELECT 1 FROM office_pay_events"), "nothing read or booked before a good signature")

# ---------------------------------------------------------------- the payment
PDF_BEFORE = hashlib.sha256(A.get(B + f"{D}/{I1}/pdf").content).hexdigest()
r = paid(HOOK, cs, 119000, eid="evt_once")
check(r.ok and r.json() == {"ok": True}, f"the event is taken: {r.text}")
d = state(A, I1)
check(d["status"] == "paid", f"paid: {d['status']}")
p = pays(A, I1)["payments"]
check(len(p) == 1 and p[0]["amount"] == "1190.00" and p[0]["method"] == "online" and "online_ref" not in p[0] and p[0]["created_by"] is None, f"one payment, method online: {p}")
r = paid(HOOK, cs, 119000, eid="evt_once")
check(r.ok and r.json().get("duplicate") and len(pays(A, I1)["payments"]) == 1, "the same event twice = one payment")
r = event(HOOK, "checkout.session.async_payment_succeeded", {"id": cs, "amount_total": 119000, "currency": "eur", "payment_intent": f"pi_{cs}"})
check(r.ok and len(pays(A, I1)["payments"]) == 1, "another event of the same payment = one payment")
check(hashlib.sha256(A.get(B + f"{D}/{I1}/pdf").content).hexdigest() == PDF_BEFORE, "the finalised PDF stays the same after the payment")
pg = requests.get(B + f"/s/pay/{T1}")
check(pg.ok and "This invoice is paid" in pg.text, "a paid invoice says so")
check(go(T1)[0] == 200 and len([x for x in stub_log() if x["path"] == "/v1/checkout/sessions"]) == 1, "a paid invoice gets no new checkout")
check(requests.post(B + f"{D}/{BEFORE}/payments", json={"amount": "1", "method": "online"}, cookies=A.cookies, headers=kt.H).status_code == 400, "method online is not for a hand")

# ---------------------------------------------------------------- the organisation boundary
Ca.put(B + O + "/payonline", json={"provider": "stripe", "secret_key": KEY, "webhook_secret": "whsec_beta_0123456789", "enabled": 1})
HOOK2 = hook_of(Ca)
I2 = invoice(A, CL)
T2 = link_of(A, I2)
_st, _u, cs2 = go(T2)
r = paid(HOOK2, cs2, 119000, secret="whsec_beta_0123456789")
check(r.ok and pays(A, I2)["payments"] == [] and state(A, I2)["status"] != "paid", "Beta's webhook never reaches Alpha's invoice")
check(event(HOOK2, "checkout.session.completed", {"id": cs2, "payment_status": "paid", "amount_total": 119000, "currency": "eur"}, SECRET).status_code == 400,
      "Alpha's secret does not open Beta's webhook")
check(Ca.put(B + f"{D}/{I2}/pay-online", json={"on": 0}).status_code == 404, "Beta cannot switch Alpha's invoice")
check(Ca.get(B + f"{D}/{I2}").status_code == 404, "Beta does not see Alpha's invoice")

# ---------------------------------------------------------------- part payment
check(A.post(B + f"{D}/{I2}/payments", json={"amount": "190", "date": str(kt.today())}).status_code == 201, "a part by hand")
pg = requests.get(B + f"/s/pay/{T2}")
check("1,000.00" in pg.text or "1.000,00" in pg.text, "the page shows what is left")
_st, _u, cs3 = go(T2)
check(stub_log()[-1]["form"]["line_items[0][price_data][unit_amount]"] == "100000", "the checkout asks what is left")
check(any(x["path"].endswith(f"/{cs2}/expire") for x in stub_log()), "the older checkout is ended at the provider")
_st, _u, cs4 = go(T2, amount="250,50")
check(stub_log()[-1]["form"]["line_items[0][price_data][unit_amount]"] == "25050", "a part the customer typed")
r = paid(HOOK, cs4, 25050)
d = state(A, I2)
check(r.ok and d["status"] in ("sent", "issued"), f"part paid: {d['status']}")
check(pays(A, I2)["paid"] == "440.50", f"both payments count: {pays(A, I2)['paid']}")

# ---------------------------------------------------------------- refund and dispute
I3 = invoice(A, CL)
_st, _u, cs5 = go(link_of(A, I3))
paid(HOOK, cs5, 119000)
PI5 = f"pi_{cs5}"
r = event(HOOK, "charge.refunded", {"payment_intent": PI5, "amount_refunded": 19000})
j = pays(A, I3)
check(r.ok and j["paid"] == "1000.00" and state(A, I3)["status"] != "paid", f"a part refund: {j['paid']}")
amounts = [x["amount"] for x in j["payments"]]
check(amounts == ["1190.00", "-1190.00", "1000.00"], f"reversal + the rest, nothing deleted: {amounts}")
event(HOOK, "charge.refunded", {"payment_intent": PI5, "amount_refunded": 19000})
check(pays(A, I3)["paid"] == "1000.00" and len(pays(A, I3)["payments"]) == 3, "the same refund under another event id changes nothing")
event(HOOK, "charge.refunded", {"payment_intent": PI5, "amount_refunded": 119000})
check(pays(A, I3)["paid"] == "0.00" and state(A, I3)["status"] != "paid", "a full refund: open again")
I4 = invoice(A, CL)
_st, _u, cs6 = go(link_of(A, I4))
r = event(HOOK, "charge.refunded", {"payment_intent": f"pi_{cs6}", "amount_refunded": 19000})
check(r.ok and pays(A, I4)["payments"] == [] and dbx("SELECT state FROM office_pay_events WHERE ref=?", (f"pi_{cs6}",))[0][0] == "wait", "a refund before its payment waits")
paid(HOOK, cs6, 119000)
check(pays(A, I4)["paid"] == "1000.00", f"the wrong order ends right: {pays(A, I4)['paid']}")
I5 = invoice(A, CL)
_st, _u, cs7 = go(link_of(A, I5))
paid(HOOK, cs7, 119000)
event(HOOK, "charge.dispute.funds_withdrawn", {"payment_intent": f"pi_{cs7}", "amount": 119000})
check(pays(A, I5)["paid"] == "0.00", "a lost dispute takes the money back")
event(HOOK, "charge.dispute.funds_reinstated", {"payment_intent": f"pi_{cs7}", "amount": 119000})
check(pays(A, I5)["paid"] == "1190.00" and state(A, I5)["status"] == "paid", "a won dispute brings it back")

# ---------------------------------------------------------------- a direct debit settles later
I6 = invoice(A, CL)
_st, _u, cs8 = go(link_of(A, I6))
r = event(HOOK, "checkout.session.completed", {"id": cs8, "payment_status": "unpaid", "amount_total": 119000, "currency": "eur", "payment_intent": f"pi_{cs8}"})
check(r.ok and pays(A, I6)["payments"] == [], "a direct debit under way is no payment yet")
event(HOOK, "checkout.session.async_payment_failed", {"id": cs8})
check(pays(A, I6)["payments"] == [] and dbx("SELECT state FROM office_pay_sessions WHERE ext_id=?", (cs8,))[0][0] == "failed", "a failed one books nothing")
I6b = invoice(A, CL)
_st, _u, cs9 = go(link_of(A, I6b))
event(HOOK, "checkout.session.completed", {"id": cs9, "payment_status": "unpaid", "amount_total": 119000, "currency": "eur", "payment_intent": f"pi_{cs9}"})
event(HOOK, "checkout.session.async_payment_succeeded", {"id": cs9, "amount_total": 119000, "currency": "eur", "payment_intent": f"pi_{cs9}"})
check(pays(A, I6b)["paid"] == "1190.00", "the settled one is booked")

# ---------------------------------------------------------------- what cannot be booked is held
I7 = invoice(A, CL)
_st, _u, cs10 = go(link_of(A, I7))
r = paid(HOOK, cs10, 500)
g = A.get(B + O + "/payonline").json()
check(r.ok and pays(A, I7)["payments"] == [] and [h["reason"] for h in g["held"]] == ["mismatch"], f"another amount than the session's is held: {g['held']}")
hid = g["held"][0]["id"]
check(A.post(B + O + f"/payonline/events/{hid}/retry").status_code == 409, "a difference is not booked by trying again")
check(A.post(B + O + f"/payonline/events/{hid}/done").json()["held"] == [], "a person closes it")
I8 = invoice(A, CL)
_st, _u, cs11 = go(link_of(A, I8))
check(A.post(B + f"{D}/{I8}/payments", json={"amount": "1190", "date": str(kt.today())}).status_code == 201, "paid by bank meanwhile")
r = paid(HOOK, cs11, 119000)
g = A.get(B + O + "/payonline").json()
check(r.ok and pays(A, I8)["paid"] == "1190.00" and [h["reason"] for h in g["held"]] == ["closed"], f"paid twice: nothing counted twice, it is held: {g['held']}")
check(state(A, I8)["pay_online"]["held"], "the invoice shows it too")
check(until(lambda: dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='integfail'", (ALICE,)), 5), "the admin is told")
check(Bo.post(B + O + f"/payonline/events/{g['held'][0]['id']}/done").status_code == 403, "a member cannot close it")
event(HOOK, "charge.refunded", {"payment_intent": f"pi_{cs11}", "amount_refunded": 119000})
check(A.get(B + O + "/payonline").json()["held"] == [] and pays(A, I8)["paid"] == "1190.00", "refunded at the provider: the hold ends, the invoice stays")

# 2.469.0 (#3459, Fable-Review): the amount in either language; a group of three digits is no cents
I9 = invoice(A, CL)
T9 = link_of(A, I9)
for typed, want in (("1,000.50", "100050"), ("1.000,50", "100050"), ("1.000", "100000"), ("1,5", "150"), ("7", "700")):
    st9, _u, _c = go(T9, amount=typed)
    last = [x for x in stub_log() if x["path"] == "/v1/checkout/sessions"][-1]
    check(st9 == 303 and last["form"]["line_items[0][price_data][unit_amount]"] == want, f"typed {typed} = {want} cents: {st9} {last['form']['line_items[0][price_data][unit_amount]']}")
for typed in ("1,2,x", "1..2", "-5", "NaN", "2.000,00"):
    check(requests.post(B + f"/s/pay/{T9}/go", data={"amount": typed}, allow_redirects=False).status_code == 400, f"no amount up to what is open: {typed}")
# what waited for a held payment ends with it
I10 = invoice(A, CL)
_st, _u, cs12 = go(link_of(A, I10))
event(HOOK, "charge.refunded", {"payment_intent": f"pi_{cs12}", "amount_refunded": 19000})
check(A.post(B + f"{D}/{I10}/payments", json={"amount": "1190", "date": str(kt.today())}).status_code == 201, "paid by bank meanwhile")
paid(HOOK, cs12, 119000)
g = A.get(B + O + "/payonline").json()
hid = [h for h in g["held"] if h["reason"] == "closed"][0]["id"]
check(dbx("SELECT state FROM office_pay_events WHERE ref=?", (f"pi_{cs12}",))[0][0] == "wait", "the refund waits for the held payment")
check(A.post(B + O + f"/payonline/events/{hid}/done").ok, "a person closes the held payment")
check(dbx("SELECT state FROM office_pay_events WHERE ref=?", (f"pi_{cs12}",))[0][0] == "done", "the waiting refund does not wait for ever")
check(pays(A, I10)["paid"] == "1190.00", "the hand payment stands")
# a part refund told while the payment is held counts when it is booked at last
I11 = invoice(A, CL)
_st, _u, cs13 = go(link_of(A, I11))
A.post(B + f"{D}/{I11}/payments", json={"amount": "1190", "date": str(kt.today())})
paid(HOOK, cs13, 119000)
event(HOOK, "charge.refunded", {"payment_intent": f"pi_{cs13}", "amount_refunded": 19000})
g = A.get(B + O + "/payonline").json()
hid = [h for h in g["held"] if h["reason"] == "closed"][0]["id"]
hp = pays(A, I11)["payments"][0]["id"]
check(A.delete(B + f"{D}/{I11}/payments/{hp}").ok, "the hand payment reversed")
check(A.post(B + O + f"/payonline/events/{hid}/retry").ok, "tried again")
check(pays(A, I11)["paid"] == "1000.00", f"the invoice gets what is left of the held payment: {pays(A, I11)['paid']}")

# ---------------------------------------------------------------- credit note, cancelled, switch
I9 = invoice(A, CL)
T9 = link_of(A, I9)
check(A.put(B + f"{D}/{I9}/pay-online", json={"on": 0}).json()["on"] is False, "the invoice's switch")
check(requests.get(B + f"/s/pay/{T9}").status_code == 404 and go(T9)[0] == 404, "switched off: not available, no checkout")
check(A.put(B + f"{D}/{I9}/pay-online", json={"on": 1}).json()["on"] is True, "switched on again")
check(requests.get(B + f"/s/pay/{T9}").ok, "available again")
r = A.post(B + f"{D}/{I9}/credit", json={})
check(r.status_code in (200, 201), f"a credit note: {r.text[:200]}")
CR = r.json()["id"]
check(A.post(B + f"{D}/{CR}/finalize").ok, "finalised")
check("pay_online" not in state(A, CR), "a credit note has no online payment")
check(A.put(B + f"{D}/{CR}/pay-online", json={"on": 1}).status_code == 409, "a credit note cannot be switched on")
check(state(A, I9)["status"] == "cancelled", "the full credit note cancels the invoice")
check(requests.get(B + f"/s/pay/{T9}").status_code == 404 and go(T9)[0] == 404, "cancelled: not available, no checkout")

# ---------------------------------------------------------------- the mail
I10 = invoice(A, CL)
n0 = len(mails("kunde@example.com"))
r = A.post(B + f"{D}/{I10}/send", json={"to": "kunde@example.com"})
check(r.ok, f"sent: {r.text[:200]}")
got = until(lambda: len(mails("kunde@example.com")) > n0 and mails("kunde@example.com"), 15) or [""]
check("/s/pay/" in got[-1], f"the mail carries the pay link: {got[-1][:300]}")

# ---------------------------------------------------------------- the customer portal
check(A.put(B + O + "/settings", json={"portal_docs": 1}).ok, "documents in the portal")
n0 = len(mails("kunde@example.com"))
check(A.post(B + O + f"/clients/{CL}/portal-link", json={}).ok, "portal link")
got = until(lambda: len(mails("kunde@example.com")) > n0 and mails("kunde@example.com"), 15) or [""]
m = re.search(r"/portal/login/([A-Za-z0-9_-]{30,64})", got[-1])
P = requests.Session()
if m:
    P.post(B + f"/portal/login/{m.group(1)}", allow_redirects=False)
pg = P.get(B + "/portal")
check(pg.ok and "Pay now" in pg.text and "/s/pay/" in pg.text, "the portal offers it for the open invoice")

# ---------------------------------------------------------------- the payout in the bank list
day = str(kt.today())
event(HOOK, "payout.paid", {"id": "po_1", "amount": 119000 - 150, "currency": "eur", "arrival_date": int(time.time())})
event(HOOK, "payout.paid", {"id": "po_1", "amount": 119000 - 150, "currency": "eur", "arrival_date": int(time.time())})
check(len(dbx("SELECT 1 FROM office_pay_payouts WHERE ext_id='po_1'")) == 1, "a payout once")
PAYS0 = dbx("SELECT COUNT(*) FROM office_payments WHERE org_id=?", (ORG,))[0][0]
tx = dbx("INSERT INTO office_bank_tx(org_id, day, amount, counterpart, purpose, hash, created_at) VALUES(?,?,?,?,?,?,?) RETURNING id", (ORG, day, "1188.50", "Stripe Payments", "STRIPE PAYOUT", "h1", day))[0][0]
tx2 = dbx("INSERT INTO office_bank_tx(org_id, day, amount, counterpart, purpose, hash, created_at) VALUES(?,?,?,?,?,?,?) RETURNING id", (ORG, day, "77.00", "STRIPE", "payout", "h2", day))[0][0]
items = {x["id"]: x for x in A.get(B + O + "/bank/tx?state=open").json()["items"]}
sug = items[tx]["suggestions"]
check(sug and sug[0]["kind"] == "payout" and sug[0]["id"] and len(sug) == 1, f"a payout is suggested, no invoice: {sug}")
check(items[tx2]["suggestions"][0]["kind"] == "payout" and not items[tx2]["suggestions"][0]["id"], "the provider's name is enough")
r = A.post(B + O + f"/bank/tx/{tx}/match", json={"kind": "payout", "id": sug[0]["id"]})
check(r.ok and r.json()["match"]["kind"] == "payout", f"matched: {r.text[:200]}")
check(dbx("SELECT COUNT(*) FROM office_payments WHERE org_id=?", (ORG,))[0][0] == PAYS0, "no second payment: nothing counts twice")
check(A.post(B + O + f"/bank/tx/{tx2}/match", json={"kind": "payout", "id": sug[0]["id"]}).status_code == 409, "a payout matches one booking")
fee = dbx("SELECT fee_minor, node_id FROM office_pay_payouts WHERE ext_id='po_1'")[0]
check(fee[0] == 150 and fee[1], f"the fees are read and filed as a receipt: {fee}")
check(dbx("SELECT 1 FROM rc_receipts WHERE node_id=? AND paid_at=?", (fee[1], day)), "the receipt is paid that day")
check(until(lambda: A.get(B + O + f"/books/euer?year={day[:4]}").json()["expense_total"]["gross"] == "1.50", 20), "the fees count as an expense")
r = A.post(B + O + f"/bank/tx/{tx}/unmatch")
check(r.ok and r.json()["was"]["kind"] == "payout", "the match can be undone")
check(A.post(B + O + f"/bank/tx/{tx}/match", json={"kind": "payout", "id": sug[0]["id"]}).ok and len(dbx("SELECT 1 FROM rc_receipts r JOIN office_pay_payouts p ON p.node_id=r.node_id WHERE p.ext_id='po_1'")) == 1, "matched again: the fees once")

# ---------------------------------------------------------------- a person without an organisation
FID, Fr = freelancer(B, A)
check(Fr.put(B + O + "/settings", json={"lang": "en", "company_fields": dict(COMPANY, name="Frida Film")}).ok, "the personal office")
r = Fr.put(B + O + "/payonline", json={"provider": "stripe", "secret_key": KEY, "webhook_secret": "whsec_frida_0123456789", "enabled": 1})
check(r.ok and r.json()["ready"] and r.json()["can_edit"], f"she sets it up herself: {r.text[:200]}")
FC = client(Fr, "Kundin Frida", email="kundin@example.com")
FI = invoice(Fr, FC)
FT = link_of(Fr, FI)
_st, _u, fcs = go(FT)
r = paid(hook_of(Fr), fcs, 119000, secret="whsec_frida_0123456789")
check(r.ok and pays(Fr, FI)["paid"] == "1190.00" and state(Fr, FI)["status"] == "paid", f"the personal office's webhook books: {r.text[:200]}")
FO = dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
check(dbx("SELECT 1 FROM office_pay_sessions WHERE org_id=? AND ext_id=?", (FO, fcs)), "the session stands in her area")
r = paid(HOOK, fcs, 119000)
check(r.ok and len(pays(Fr, FI)["payments"]) == 1, "Alpha's webhook does not reach her invoice")

old = hook_of(Fr)
new = tok_of(Fr.post(B + O + "/payonline/rotate").json()["webhook_url"])
check(new != old and paid(old, fcs, 119000, secret="whsec_frida_0123456789").status_code == 404, "a new webhook address: the old one stops at once")

# ---------------------------------------------------------------- a locked month (Frida's office: a lock has no way back)
FS = "whsec_frida_0123456789"
FH = hook_of(Fr)
FI2, FI3 = invoice(Fr, FC), invoice(Fr, FC)
_st, _u, fcs2 = go(link_of(Fr, FI2))
_st, _u, fcs3 = go(link_of(Fr, FI3))
paid(FH, fcs2, 119000, secret=FS)
last = kt.dbx("SELECT to_char((date_trunc('month', ?::date) - interval '1 day')::date, 'YYYY-MM')", (str(kt.today()),), DATA)[0][0]
dbx("UPDATE office_payments SET date=? WHERE doc_id=?", (last + "-15", FI2))
r = Fr.post(B + O + "/periods/lock", json={"through": last, "confirm": f"{last[5:]}/{last[:4]}"})
check(r.ok, f"the last month locked: {r.text[:200]}")
event(FH, "charge.refunded", {"payment_intent": f"pi_{fcs2}", "amount_refunded": 19000}, FS)
g = Fr.get(B + O + "/payonline").json()
check([h["reason"] for h in g["held"]] == ["locked"] and pays(Fr, FI2)["paid"] == "1190.00", f"a refund of a locked month is held, nothing changes: {g['held']}")
check(Fr.post(B + O + f"/payonline/events/{g['held'][0]['id']}/retry").json()["held"], "trying again while locked: still held")
r = paid(FH, fcs3, 119000, secret=FS, created=int(time.time()) - 86400 * 45)
p3 = pays(Fr, FI3)["payments"]
check(r.ok and len(p3) == 1 and p3[0]["date"] == str(kt.today()), f"a payment of a locked month lands today: {p3}")

# ---------------------------------------------------------------- never in a log
logs = subprocess.run(["docker", "logs", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
check(KEY not in logs and SECRET not in logs, "no secret in the server's log")
check(T1 not in logs and HOOK not in logs, "no token in the server's log")

# ---------------------------------------------------------------- 2.469.0 (#3459, Fable-Review): the move into an organisation
FI3 = invoice(Fr, FC)
_st, _u, _cs = go(link_of(Fr, FI3))
ORGX = A.post(B + "/api/admin/orgs", json={"name": "Umzug Werk", "admin_id": FID}).json()["id"]
Fr.patch(B + "/api/settings", json={"workspace": "private"})
j = Fr.get(B + f"/api/office/move/check?org={ORGX}").json()
check(any("online payment" in x.lower() or "online-zahlung" in x.lower() for x in j.get("conflicts", [])), f"a checkout under way stops the move: {j.get('conflicts')}")
check(any("pay link" in x.lower() or "bezahl-link" in x.lower() for x in j.get("notes", [])), f"the move names the pay links: {j.get('notes')}")

# ---------------------------------------------------------------- limits of the public routes
check(any(requests.post(B + "/s/pay/" + "y" * 43 + "/go").status_code == 429 for _ in range(45)), "the pay page's start route is limited per address")

sys.exit(kt.done("payonline"))
