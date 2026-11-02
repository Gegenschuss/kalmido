#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.469.0 (#3749) API tests: a connected agent reads a credit card statement no reader could read (proposal kind
card_statement_read), own container (start.sh, org encryption on). Kalmido calls no model and sends nothing out. Every statement,
company and figure is invented and made here. tenant-matrix: office  freelancer-matrix: office
 - who may be asked: the switches, the file shared with the agent, the receipts right, a draft without positions; another
   organisation and a person who does not work on the statement: nobody and 404; a confirmed statement or one with positions 409
 - the input: what the documents API shows the agent of the PDF, its address, month and currency; the agent fetches the file itself
 - the answer strictly checked: unknown fields, amounts, days, currencies, kinds, too long, too many, nothing: 400
 - before Take over nothing is in the statement and the agent can change nothing; after it the positions are a draft: not
   counted until the person confirms, the sum checked as ever, sealed at rest, fees need no receipt; undo / redo, undo skips a change
   by hand; positions typed in meanwhile 409; the file unshared before the answer 403; the receipts right gone at Take over 403
 - a freelancer without an organisation does the same with the own agent; a locked month: Take over 409, nothing changed
usage: p2469_b_cardread_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer
from kt import FAILS, OKS, check, sess

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
K = O + "/cards"
R = O + "/rights"
KIND = "card_statement_read"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def pdf(lines):
    """A PDF with a text layer, one line of text per entry (hand-written, no library)."""
    stream = ("BT /F1 10 Tf 12 TL 40 760 Td\n" + "\n".join(f"({x}) Tj T*" for x in lines) + "\nET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def up(s, cid, month):
    """A statement no reader can read: 'Dieses Blatt' has no position."""
    r = s.post(B + f"{K}/{cid}/statements", files={"file": ("stmt.pdf", pdf(["Dieses Blatt hat keine Positionen"]), "application/pdf")}, data={"month": month})
    assert r.status_code == 201 and r.json()["read"] is False, r.text
    return r.json()["statement"]


def agents_for(s, sid):
    r = s.get(B + "/api/proposals/agents", params={"kind": KIND, "statement_id": sid})
    return [a["id"] for a in r.json().get("agents", [])] if r.ok else None


def ask(s, ag, sid):
    return s.post(B + "/api/proposals", json={"kind": KIND, "agent_id": ag, "statement_id": sid})


def answer(ag, jid, b):
    return ag.post(V + f"/agent/jobs/{jid}/proposal", json=b)


def apply(s, jid):
    return s.post(B + f"/api/proposals/{jid}/apply", json={"select": ["0"]})


def sheet(s, sid):
    return s.get(B + f"{K}/statements/{sid}").json()


def lines(s, sid):
    return sheet(s, sid).get("lines") or []


def job_input(ag, jid):
    j = ag.get(V + "/agent/events", params={"since": 0, "limit": 500}).json()
    ev = [e for e in j.get("data", j.get("events", [])) if e["event"] == "job_request" and e["data"]["job"]["id"] == jid]
    return ev[-1]["data"] if ev else {}


KEY = base64.b64encode(os.urandom(32)).decode()
Y = time.localtime().tm_year - 1
GOOD = {"total": "150,40", "lines": [
    {"day": f"{Y}-03-02", "booked": f"{Y}-03-03", "merchant": "Hotel Beispiel", "amount": "120.00", "orig_amount": "130.00", "orig_currency": "usd", "kind": "purchase"},
    {"day": f"{Y}-03-02", "merchant": "Auslandseinsatzentgelt", "amount": 2.40, "kind": "fee"},
    {"day": f"{Y}-03-09", "merchant": "<img src=x onerror=alert(1)>", "amount": "30"},
    {"day": f"{Y}-03-11", "merchant": "Gutschrift Beispiel", "amount": "-2.00"}]}

r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                   env={**os.environ, "EXTRA": os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"})
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    assert A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"}).ok
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
A.get(B + O + "/settings")
Ca.get(B + O + "/settings")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "readbot", "display_name": "Read Bot", "scopes": ["read", "office", "files:read"], "org_id": ORG})
assert r.status_code == 201, r.text
AG, AGS = r.json()["id"], tok(r.json()["token"])
CARD = A.post(B + K, json={"holder_id": ALICE, "last4": "1234"}).json()["id"]
CARDB = A.post(B + K, json={"holder_id": BOB, "last4": "5678"}).json()["id"]
ST = up(A, CARD, f"{Y}-03")
SID, NODE = ST["id"], ST["node_id"]
check(ST["reader"] == "manual" and not lines(A, SID), "setup: a statement no reader could read")

# ---------------------------------------------------------------- who may be asked
check(agents_for(A, SID) == [] and ask(A, AG, SID).status_code == 404, "the switches off: nobody, 404")
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok and A.put(B + O + "/settings", json={"agents_read": 1}).ok, "setup: the switches")
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:projects"]}).ok, "setup: the agent with the receipts right")
check(agents_for(A, SID) == [] and ask(A, AG, SID).status_code == 404, "the file not shared with the agent: nobody, 404")
r = A.post(B + f"/api/files/nodes/{NODE}/shares", json={"agent_id": AG, "role": "view"})
check(r.ok, "setup: the file shared with the agent " + r.text[:200])
SHARE = r.json().get("id")
check(agents_for(A, SID) == [AG], "the agent can be asked")
check(agents_for(Bo, SID) == [] and ask(Bo, AG, SID).status_code == 404, "a person who does not work on this statement: nobody, 404")
check(agents_for(Ca, SID) == [] and ask(Ca, AG, SID).status_code == 404, "another organisation: nobody, 404")
check(A.post(B + "/api/proposals", json={"kind": KIND, "agent_id": AG, "statement_id": SID, "field": "intro"}).status_code == 400, "unknown keys of the request 400")
check(A.post(B + "/api/proposals", json={"kind": KIND, "agent_id": AG}).status_code == 400, "no statement 400")

# ---------------------------------------------------------------- the request and the input
r = ask(A, AG, SID)
check(r.status_code == 201, "the request " + r.text[:200])
J1 = r.json()["id"]
ev = job_input(AGS, J1)
inp = ev.get("input") or {}
d = inp.get("document") or {}
check(ev.get("kind") == KIND and d.get("id") == NODE and d.get("content_url") == f"/api/v1/files/{NODE}/content", f"the input: the PDF's address {str(inp)[:300]}")
check(inp.get("statement", {}).get("id") == SID and inp["statement"]["month"] == f"{Y}-03" and "1234" not in str(inp.get("statement")), "the input: the statement, not the card's digits " + str(inp.get("statement")))
check((ev.get("limits") or {}).get("card_lines_max") == 2000, "the limits carry the positions")
f = AGS.get(B + d.get("content_url", "/x"))
check(f.ok and f.content[:5] == b"%PDF-", "the agent fetches the file itself with its token")
check(AGS.get(B + f"{K}/statements/{SID}").status_code in (401, 403, 404) and AGS.get(V + "/office/cards").status_code in (401, 403, 404), "the agent never reaches the cards themselves")
a = sheet(A, SID).get("agent_read") or {}
check(a.get("job") == J1 and a.get("state") == "requested" and a.get("agent", {}).get("id") == AG, f"the sheet: the agent is reading {a}")

# ---------------------------------------------------------------- the answer, strictly checked
one = {"day": f"{Y}-03-02", "merchant": "x", "amount": "1.00"}
for bad, what in (({"foo": 1, "lines": [one]}, "an unknown field"), ({"lines": []}, "no position"), ({}, "nothing"), ({"lines": "x"}, "not a list"),
                  ({"lines": [one] * 2001}, "too many"), ({"lines": [{**one, "foo": 1}]}, "an unknown field of a position"), ({"lines": ["x"]}, "a position no object"),
                  ({"lines": [{**one, "amount": "1.234,56"}]}, "a thousands point"), ({"lines": [{**one, "amount": "1.234"}]}, "three decimals"),
                  ({"lines": [{**one, "amount": "0"}]}, "amount zero"), ({"lines": [{**one, "amount": None}]}, "no amount"), ({"lines": [{**one, "amount": True}]}, "amount a bool"),
                  ({"lines": [{**one, "amount": "1e5"}]}, "an exponent"), ({"lines": [{**one, "amount": "NaN"}]}, "NaN"), ({"lines": [{**one, "amount": "100000001"}]}, "too much"),
                  ({"lines": [{**one, "day": "2026-13-01"}]}, "a bad day"), ({"lines": [{**one, "day": None}]}, "no day"), ({"lines": [{**one, "day": "1999-12-31"}]}, "a day too old"),
                  ({"lines": [{**one, "booked": "morgen"}]}, "a bad booking day"), ({"lines": [{**one, "merchant": ""}]}, "no merchant"), ({"lines": [{**one, "merchant": "x" * 201}]}, "a merchant too long"),
                  ({"lines": [{**one, "merchant": ["x"]}]}, "a merchant no text"), ({"lines": [{**one, "kind": "bonus"}]}, "an unknown kind"),
                  ({"lines": [{**one, "orig_amount": "1.00"}]}, "a foreign amount without currency"), ({"lines": [{**one, "orig_currency": "USD"}]}, "a currency without amount"),
                  ({"lines": [{**one, "orig_amount": "1.00", "orig_currency": "dollar"}]}, "a bad currency"), ({"lines": [one], "total": "-5"}, "a negative total")):
    r = answer(AGS, J1, bad)
    check(r.status_code == 400, f"answer: {what} 400 ({r.status_code})")
r = answer(AGS, J1, GOOD)
check(r.status_code == 201, "answer: the positions " + r.text[:200])
p = r.json().get("proposal") or {}
L = p.get("lines") or []
check(p.get("total") == "150.40" and L[1]["amount"] == "2.40" and L[2]["amount"] == "30.00" and L[0]["orig_currency"] == "USD", f"values normalised {str(p)[:300]}")
check(L[2]["kind"] == "purchase" and L[3]["kind"] == "credit", "the kind follows the sign when not given")
check(not lines(A, SID) and sheet(A, SID)["statement"]["total_missing"] is True, "nothing in the statement before Take over")
check((sheet(A, SID).get("agent_read") or {}).get("state") == "ready" and sheet(A, SID)["agent_read"]["lines"] == 4, "the sheet: the proposal is ready")
check(AGS.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code in (401, 403, 404), "the agent cannot take anything over")
v = A.get(B + f"/api/proposals/{J1}").json()
t = v.get("target") or {}
check(t.get("statement_id") == SID and t.get("editable") is True and t.get("sum") == "150.40" and t.get("fits") is True, f"the card: the sum against the total {t}")

# ---------------------------------------------------------------- take over: a draft, counted only when confirmed
check(Bo.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code in (403, 404), "another person cannot take it over")
r = apply(A, J1)
check(r.ok, "Take over " + r.text[:200])
ls = lines(A, SID)
S1 = sheet(A, SID)["statement"]
check(len(ls) == 4 and S1["state"] == "draft" and S1["total"] == "150.40" and S1["sum"] == "150.40", f"the positions in the draft, still unconfirmed {S1}")
check(ls[0]["orig_amount"] == "130.00" and ls[0]["orig_currency"] == "USD" and ls[0]["booked"] == f"{Y}-03-03", "foreign amount and booking day kept")
check(ls[1]["state"] == "noreceipt" and ls[0]["state"] == "open" and ls[3]["kind"] == "credit", "as a reader's positions: fees need no receipt")
check(ls[2]["merchant"] == "<img src=x onerror=alert(1)>", "the merchant stays a value, the client escapes it")
row = sql("SELECT merchant, amount FROM office_cc_lines WHERE id=?", (ls[0]["id"],))[0]
check(row[0] != "Hotel Beispiel" and row[1] != "120.00", "sealed at rest like a reader's position")
check("Hotel" not in (sql("SELECT applied FROM agent_jobs WHERE id=?", (J1,))[0][0] or ""), "the undo record holds no value")
check(ask(A, AG, SID).status_code == 409 and agents_for(A, SID) == [], "a statement with positions: no agent any more")

# undo / redo
check(A.post(B + f"/api/proposals/{J1}/undo").ok and not lines(A, SID) and sheet(A, SID)["statement"]["total_missing"] is True, "undo: positions and total gone")
check(A.post(B + f"/api/proposals/{J1}/redo").ok and len(lines(A, SID)) == 4 and sheet(A, SID)["statement"]["total"] == "150.40", "redo: back")
ls = lines(A, SID)
check(A.patch(B + f"{K}/lines/{ls[0]['id']}", json={"merchant": "Hotel Korrigiert"}).ok, "setup: a position corrected by hand")
r = A.post(B + f"/api/proposals/{J1}/undo")
check(len(lines(A, SID)) == 4 and lines(A, SID)[0]["merchant"] == "Hotel Korrigiert", f"undo skips a change by hand {r.text[:200]}")
check(A.post(B + f"{K}/statements/{SID}/confirm", json={}).ok and sheet(A, SID)["statement"]["state"] == "confirmed", "the person confirms through the usual step, the sum checked")
check(ask(A, AG, SID).status_code == 409, "a confirmed statement: 409")

# ---------------------------------------------------------------- what can change between the answer and Take over
S2 = up(A, CARD, f"{Y}-04")
assert A.post(B + f"/api/files/nodes/{S2['node_id']}/shares", json={"agent_id": AG, "role": "view"}).ok
J2 = ask(A, AG, S2["id"]).json()["id"]
check(answer(AGS, J2, {"lines": [{**one, "day": f"{Y}-04-02"}]}).status_code == 201, "setup: an answer")
assert A.post(B + f"{K}/statements/{S2['id']}/lines", json={"day": f"{Y}-04-03", "merchant": "Von Hand", "amount": "9.00"}).status_code == 201
check(A.get(B + f"/api/proposals/{J2}").json()["target"]["editable"] is False, "the card: Take over no longer possible")
check(apply(A, J2).status_code == 409 and len(lines(A, S2["id"])) == 1, "positions typed in meanwhile: 409, nothing added")

S3 = up(A, CARD, f"{Y}-05")
r = A.post(B + f"/api/files/nodes/{S3['node_id']}/shares", json={"agent_id": AG, "role": "view"})
J3 = ask(A, AG, S3["id"]).json()["id"]
check(A.delete(B + f"/api/files/shares/{r.json()['id']}").ok, "setup: the file no longer shared")
check(answer(AGS, J3, GOOD).status_code == 403, "the file unshared before the answer: 403")

S4 = up(A, CARDB, f"{Y}-06")  # Bob's card and his own agent, the receipts right taken from him between asking and taking over
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob Bot", "scopes": ["read", "office", "files:read"], "org_id": ORG})
assert r.status_code == 201, r.text
BAG, BAGS = r.json()["id"], tok(r.json()["token"])
assert A.patch(B + f"{O}/agents/{BAG}", json={"office_drafts": True}).ok and A.put(B + f"{R}/people/{BAG}", json={"groups": ["tpl:projects"]}).ok
assert A.post(B + f"/api/files/nodes/{S4['node_id']}/shares", json={"user_id": BOB, "role": "edit"}).ok
assert A.post(B + f"/api/files/nodes/{S4['node_id']}/shares", json={"agent_id": BAG, "role": "view"}).ok
assert A.put(B + f"{R}/people/{BOB}", json={"groups": ["tpl:projects"]}).ok
r = ask(Bo, BAG, S4["id"])
check(r.status_code == 201, "the holder with the right and the file asks too " + r.text[:200])
J4 = r.json().get("id")
check(J4 and answer(BAGS, J4, {"lines": [{**one, "day": f"{Y}-06-02"}]}).status_code == 201, "setup: the answer for the holder")
check(A.put(B + f"{R}/people/{BOB}", json={"groups": ["tpl:none"]}).ok, "setup: the right taken away")
check(apply(Bo, J4).status_code in (403, 404) and not lines(A, S4["id"]), "the receipts right gone at Take over: refused, nothing added")

# ---------------------------------------------------------------- a person without an organisation, a locked month
# freelancer-matrix: office
FID, Fr = freelancer(B, A, "frida")
Fr.get(B + O + "/settings")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "office", "files:read"]})
check(r.status_code == 201, "freelancer: her own agent " + r.text[:200])
FAG, FAGS = r.json()["id"], tok(r.json()["token"])
check(Fr.patch(B + f"{O}/agents/{FAG}", json={"office_drafts": True}).ok and Fr.put(B + O + "/settings", json={"agents_read": 1}).ok, "freelancer: the switches")
FC = Fr.post(B + K, json={"holder_id": FID, "last4": "4321"}).json()["id"]
FS = up(Fr, FC, f"{Y}-03")
assert Fr.post(B + f"/api/files/nodes/{FS['node_id']}/shares", json={"agent_id": FAG, "role": "view"}).ok
check(agents_for(Fr, FS["id"]) == [FAG] and agents_for(A, FS["id"]) == [], "freelancer: her agent, nobody else's")
J5 = ask(Fr, FAG, FS["id"]).json().get("id")
check(J5 and answer(FAGS, J5, GOOD).status_code == 201 and apply(Fr, J5).ok and len(lines(Fr, FS["id"])) == 4, "freelancer: request, answer, taken over")
check(Fr.post(B + f"/api/proposals/{J5}/undo").ok and not lines(Fr, FS["id"]), "freelancer: undo")
J6 = ask(Fr, FAG, FS["id"]).json().get("id")
check(J6 and answer(FAGS, J6, GOOD).status_code == 201, "freelancer: another answer")
r = Fr.post(B + O + "/periods/lock", json={"through": f"{Y}-03", "confirm": f"03/{Y}"})
check(r.ok, "setup: the month locked " + r.text[:200])
check(apply(Fr, J6).status_code == 409 and not lines(Fr, FS["id"]), "a locked month: Take over 409, nothing changed")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
