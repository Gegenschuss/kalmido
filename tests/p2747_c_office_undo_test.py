#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.747.0 (#5252): undo across devices, stage 4 -- the office's steps in the core's step groups (kalmido/office/oubar.py,
office/owrite.py ow_kind label=, core/writes.py obj_track undo_label=, office/undogrp.py). Own container (org encryption
on, the SMTP stub). Invented names and figures only.
freelancer-matrix: office (a person without an organisation: her step labelled, her finalising a barrier, "bis hierher" stops)
 - a write of an office row lands in a group of area "office" whose label names the object: a document by kind and
   number (a draft: its object number), a client by its name, a service by its name, a letter only by its object number
   (its subject is sealed: never in the label)
 - finalising, sending (the mail and "marked sent"), a payment and its reversal, the DATEV copy, the DATEV export and the
   period lock write a barrier row of the person (state barrier, no parts); an agent's finalising writes none
 - POST /api/undo/to/<id> stops at the barrier: the newer group goes back, the older one stays, the answer names the barrier
 - the editor session (X-Kalmido-Undo, POST /api/office/undo/doc/<id>) undo / redo / all as before; after finalising: 409
 - the office kinds ow_write writes: every tracked office kind has a check of its own or is noaccess on purpose; a fixed
   cost (UGO_ADMIN) goes back from the list for the office's admin
 - the old watchdog section of the office copies is gone (oun_prune), the core's undo_prune is there
usage: p2747_c_office_undo_test.py <datadir>"""
import base64
import json
import os
import sys
from datetime import date, timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, done  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY,
              "KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
              "KALMIDO_MAIL_FROM": "kalmido@example.test"}, prefix="P2747C")
from obj_probe import in_app  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

shutil.copy(os.path.join(N, "stub_mail.py"), kt.DATA)  # the SMTP sink (127.0.0.1:1025 in the container, tests/stub_mail.py)
subprocess.run(["docker", "exec", "-d", kt.CT, "python", "/data/stub_mail.py"])
kt.until(lambda: subprocess.run(["docker", "exec", kt.CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1025), 1)"],
                                capture_output=True).returncode == 0, 15)

FEAT = "cal,comments,collab,office,clients,files,docs"
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
OFF = "/api/office"
D = OFF + "/docs"
TODAY = date.today()
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "email": "hallo@beispiel.example", "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
           "bank_name": "Beispielbank", "tax_number": "12/345/67890"}
SECRET = "Geheimer Betreff 5252"


def U(tok):
    return {"X-Kalmido-Undo": tok}


def groups(u):
    return [dict(r) for r in kt.dbx("SELECT id, state, parts, area, label_key, label_args, org_id FROM undo_groups WHERE user_id=? ORDER BY id", (u,))]


def last(u):
    g = groups(u)
    return g[-1] if g else {}


def args(g):
    return json.loads(g.get("label_args") or "[]")


def nparts(gid):
    return kt.dbx("SELECT COUNT(*) FROM obj_undo WHERE group_id=?", (gid,))[0][0]


def setup_office(s, tag):
    r = s.put(B + OFF + "/settings", json={"company_fields": COMPANY, "datev_email": "inbox@example.com",
                                         "datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
    assert r.ok, r.text
    r = s.post(B + "/api/clients", json={"name": f"Kunde {tag} GmbH", "street": "Weg 2", "zip": "10115", "city": "Berlin", "country": "DE",
                                         "email": f"kunde-{tag.lower()}@example.com"})
    assert r.ok, r.text
    return r.json()["id"]


def invoice(s, cl=None, rate=100):
    r = s.post(B + D, json={"kind": "invoice", "client_id": cl or CL, "service_from": TODAY.isoformat(), "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def barrier(u, key, what):
    g = last(u)
    check(g.get("state") == "barrier" and g.get("label_key") == key and g.get("area") == "office" and nparts(g["id"]) == 0,
          f"{what}: a barrier row ({key}) {g}")
    return g


CL = setup_office(A, "Alpha")

# ---------------------------------------------------------------- labels (ow_write / oun_pre name the object)
I1 = invoice(A)
check(A.patch(B + f"{D}/{I1}", json={"project_title": "Imagefilm"}, headers=U("a1" * 16)).ok, "alice: a step on the draft invoice")
g = last(ALICE)
check(g.get("state") == "done" and g.get("area") == "office" and g.get("label_key") == "Changed: {0}"
      and args(g) == [["{0} {1}", ["Invoice"], f"#{I1}"]], f"a draft invoice: area office, kind and object number {g}")
it = A.get(B + "/api/undo").json()["items"]
check(it and it[0]["id"] == g["id"] and it[0]["label"] == f"Changed: Invoice #{I1}", f"GET /api/undo: the label in the reader's language {it[:1]}")
A.patch(B + "/api/settings", json={"lang": "de"})
it = [x for x in A.get(B + "/api/undo").json()["items"] if x.get("area") != "self"]  # 2.985.0 (#5394): the language switch is a step of its own
check(it and it[0]["label"] == f"Geändert: Rechnung #{I1}", f"... and in German {it[:1]}")
A.patch(B + "/api/settings", json={"lang": "en"})
check(A.patch(B + f"/api/clients/{CL}", json={"note": "VIP"}).ok, "alice changes the client")
g = last(ALICE)
check(g.get("label_key") == "Changed: {0}" and args(g) == ["Kunde Alpha GmbH"] and g.get("area") == "office", f"a client: its name {g}")
r = A.post(B + OFF + "/services", json={"name_de": "Beratung", "daily_rate": 800})
SV = r.json()["id"]
check(A.patch(B + f"{OFF}/services/{SV}", json={"daily_rate": 900}).ok, "alice changes the service")
g = last(ALICE)
check(args(g) == ["Beratung"] and g.get("area") == "office", f"a service: its name {g}")
r = A.post(B + OFF + "/letters", json={"subject": SECRET, "body": "Invented text.", "client_id": CL})
check(r.status_code in (200, 201), f"a letter ({r.status_code} {r.text[:200]})")
LT = r.json()["id"]
check(A.patch(B + f"{OFF}/letters/{LT}", json={"body": "Invented text, longer."}).ok, "alice changes the letter")
g = last(ALICE)
check(args(g) == [["{0} {1}", ["Letter"], f"#{LT}"]] and SECRET not in (g.get("label_args") or ""),
      f"a letter: only its object number, never the sealed subject {g}")

# ---------------------------------------------------------------- barriers
r = A.post(B + f"{D}/{I1}/finalize")
check(r.ok, f"alice finalises the invoice ({r.status_code} {r.text[:200]})")
NUM = r.json().get("number")
g = barrier(ALICE, "Finalised: {0}", "finalising")
check(args(g) == [["{0} {1}", ["Invoice"], NUM]], f"the barrier names kind and number {g}")
check(A.get(B + "/api/undo").json()["items"][0]["label"] == f"Finalised: Invoice {NUM}", "listed with the number")
r = A.post(B + f"{D}/{I1}/payments", json={"amount": "50", "method": "transfer"})
check(r.status_code == 201, f"a payment ({r.status_code} {r.text[:200]})")
barrier(ALICE, "Payment recorded: {0}", "payment")
pid = A.get(B + f"{D}/{I1}/payments").json()["payments"][0]["id"]
check(A.delete(B + f"{D}/{I1}/payments/{pid}").ok, "the payment taken back")
barrier(ALICE, "Payment reversed: {0}", "payment reversal")
r = A.post(B + f"{D}/{I1}/send", json={"to": "kunde-alpha@example.com", "datev": True})
check(r.ok, f"sent (with the DATEV copy) ({r.status_code} {r.text[:300]})")
gs = [x for x in groups(ALICE) if x["state"] == "barrier"][-2:]
check([x["label_key"] for x in gs] == ["Sent: {0}", "Sent to DATEV: {0}"], f"sending: one barrier for the mail, one for the DATEV copy {gs}")
I2 = invoice(A, rate=200)
A.post(B + f"{D}/{I2}/finalize")
n0 = len(groups(ALICE))
check(A.post(B + f"{D}/{I2}/datev").ok, "the DATEV copy alone")
barrier(ALICE, "Sent to DATEV: {0}", "the DATEV copy")
check(A.post(B + f"{D}/{I2}/status", json={"status": "sent"}).ok, "marked sent by hand")
barrier(ALICE, "Sent: {0}", "marked sent")
check(len(groups(ALICE)) == n0 + 2, "one barrier each")
P = f"?from={(TODAY - timedelta(days=40)).isoformat()}&to={TODAY.isoformat()}"
n0 = len(groups(ALICE))
check(A.get(B + OFF + "/datev/extf" + P + "&check=1").ok and len(groups(ALICE)) == n0, "the DATEV check alone writes no barrier")
check(A.get(B + OFF + "/datev/extf" + P).ok, "the DATEV booking batch downloaded")
g = barrier(ALICE, "DATEV export: {0} to {1}", "DATEV export")
M = (TODAY.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
r = A.post(B + OFF + "/periods/lock", json={"through": M, "confirm": f"{M[5:7]}/{M[:4]}"})
check(r.ok, f"the previous month locked ({r.status_code} {r.text[:200]})")
g = barrier(ALICE, "Months locked up to {0}", "period lock")
check(args(g) == [f"{M[5:7]}/{M[:4]}"], f"the month named {g}")
r = A.post(B + OFF + "/letters", json={"subject": "Second letter", "body": "Invented.", "client_id": CL})
L2 = r.json()["id"]
check(A.post(B + f"{OFF}/letters/{L2}/sent", json={"channel": "post"}).ok, "a letter marked sent")
g = barrier(ALICE, "Sent: {0}", "a sent letter")
check(args(g) == [["{0} {1}", ["Letter"], f"#{L2}"]], f"by its object number {g}")

# ---- an agent: no barrier (agents record no steps); outside a request none either
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
AG = r.json()["id"]
out = in_app(f"""
from flask import g
from kalmido.core.config import app as fa
from kalmido.office.oubar import OUB_FINAL, oub_barrier
with fa.test_request_context('/api/office/docs/1/finalize', method='POST'):
    g.user = {{"id": {AG}}}
    print('AGENT', oub_barrier(c, None, {ORG}, OUB_FINAL, 'x'))
print('OUTSIDE', oub_barrier(c, {ALICE}, {ORG}, OUB_FINAL, 'x'))
c.commit()""")
check("AGENT None" in out and "OUTSIDE None" in out and groups(AG) == [], f"an agent / no request: no barrier {out[-300:]}")

# ---------------------------------------------------------------- "bis hierher" stops at the barrier
check(A.patch(B + f"{OFF}/services/{SV}", json={"name_de": "Beratung A"}).ok, "service: step a")
GA = last(ALICE)["id"]
I4 = invoice(A, rate=400)
check(A.post(B + f"{D}/{I4}/finalize").ok, "an invoice finalised in between")
GB = barrier(ALICE, "Finalised: {0}", "the barrier in between")["id"]
check(A.patch(B + f"{OFF}/services/{SV}", json={"name_de": "Beratung B"}).ok, "service: step b")
GC = last(ALICE)["id"]
r = A.post(B + f"/api/undo/to/{GA}")
j = r.json() if r.ok else {}
sv = A.get(B + f"{OFF}/services/{SV}").json()
check(r.ok and j.get("undone") == [GC] and (j.get("stopped") or {}).get("id") == GB and sv.get("name_de") == "Beratung A",
      f"undo up to step a: b goes back, the barrier stops the run, a stays ({r.status_code} {j} {sv.get('name_de')})")
check("Finalised" in (j.get("text") or "") and (j.get("stopped") or {}).get("state") == "barrier", f"the answer names the barrier {j.get('text')}")
st = {x["id"]: x["state"] for x in groups(ALICE)}
check(st.get(GA) == "done" and st.get(GB) == "barrier" and st.get(GC) == "undone", f"the states {st.get(GA)} {st.get(GB)} {st.get(GC)}")
r = A.post(B + f"/api/undo/to/{GB}")
check(r.ok and (r.json().get("stopped") or {}).get("id") == GB and A.get(B + f"{D}/{I4}").json().get("locked"),
      f"the barrier itself cannot be undone: the invoice stays finalised ({r.status_code} {r.text[:200]})")

# ---------------------------------------------------------------- rights of now (review F10)
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob", "password": "password123",
                                   "email": "bob@example.com"})
BOB = r.json().get("id")
Bo = kt.sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
I6 = invoice(A, rate=600)
check(Bo.patch(B + f"{D}/{I6}", json={"project_title": "Bob's title"}).ok, "bob (member, no admin) changes a draft")
GBO = last(BOB)["id"]
r = Bo.post(B + f"/api/undo/to/{GBO}")
st = {x["id"]: x["state"] for x in groups(BOB)}
check(r.ok and st.get(GBO) == "noaccess" and [x["code"] for x in r.json().get("stayed") or []] == ["noaccess"]
      and A.get(B + f"{D}/{I6}").json().get("project_title") == "Bob's title",
      f"an office member without admin: noaccess, nothing written ({r.status_code} {r.text[:300]})")
check(A.patch(B + f"{D}/{I6}", json={"project_title": "Alice's title"}).ok, "alice changes it")
GAL = last(ALICE)["id"]
check(Bo.post(B + f"{D}/{I6}/finalize").ok, "bob finalises it (his barrier, not alice's)")
r = A.post(B + f"/api/undo/to/{GAL}")
j = r.json() if r.ok else {}
stay = j.get("stayed") or []
check(r.ok and [x["code"] for x in stay] == ["conflict"] and "Finalised or sent" in stay[0].get("reason", "")
      and A.get(B + f"{D}/{I6}").json().get("project_title") == "Alice's title",
      f"finalised meanwhile by someone else: conflict, it stays ({r.status_code} {j})")

# ---------------------------------------------------------------- the editor session as before
T = "c5" * 16
I5 = invoice(A, rate=500)
check(A.patch(B + f"{D}/{I5}", json={"project_title": "Eins"}, headers=U(T)).ok, "session: step 1")
check(A.patch(B + f"{D}/{I5}", json={"project_title": "Zwei"}, headers=U(T)).ok, "session: step 2")
r = A.post(B + f"/api/office/undo/doc/{I5}", json={"sess": T, "op": "undo"})
check(r.ok and r.json().get("project_title") == "Eins", f"session undo: one step back ({r.status_code} {r.text[:200]})")
r = A.post(B + f"/api/office/undo/doc/{I5}", json={"sess": T, "op": "redo"})
check(r.ok and r.json().get("project_title") == "Zwei", f"session redo ({r.status_code})")
r = A.post(B + f"/api/office/undo/doc/{I5}", json={"sess": T, "op": "all"})
check(r.ok and not r.json().get("project_title"), f"session all: back to the opening ({r.status_code} {r.text[:200]})")
r = A.post(B + f"/api/office/undo/doc/{I5}", json={"sess": T, "op": "redoall"})
check(r.ok and r.json().get("project_title") == "Zwei", f"session redoall ({r.status_code})")
check(A.post(B + f"{D}/{I5}/finalize").ok, "finalised")
r = A.post(B + f"/api/office/undo/doc/{I5}", json={"sess": T, "op": "undo"})
check(r.status_code == 409 and "Finalised or sent" in r.json().get("error", "") and A.get(B + f"{D}/{I5}").json().get("project_title") == "Zwei",
      f"after finalising: 409 with the message, it stays ({r.status_code} {r.text[:200]})")

# ---------------------------------------------------------------- the office kinds of ow_write are mapped
out = in_app("""
from kalmido.core.writes import OBJ_TRACK
from kalmido.core.undoweb import UNDO_NEED
from kalmido.office.undogrp import UGO_NOACCESS, UGO_ADMIN
office = sorted(k for k in OBJ_TRACK if k.startswith('office_') or k == 'client')
miss = [k for k in office if k not in UNDO_NEED and k not in UGO_NOACCESS]
both = [k for k in UGO_NOACCESS if k in UNDO_NEED]
area = sorted({OBJ_TRACK[k]['area'] for k in office})
print('MISS', miss, 'BOTH', both, 'AREA', area, 'N', len(office), 'SERIES', 'office_inv_series' in UNDO_NEED)""")
# 2.747.0 (review N3): an invoice series never goes back from the list (an old active / next_date would auto-send missed periods)
check("SERIES False" in out, f"office_inv_series: noaccess from the list {out[-200:]}")
check("MISS [] BOTH [] AREA ['office']" in out, f"every tracked office kind: a check of its own or noaccess on purpose, area office {out[-500:]}")
r = A.post(B + OFF + "/fixed-costs", json={"label": "Miete", "amount": "1000", "start": TODAY.replace(day=1).isoformat(), "repeat": "monthly"})
check(r.status_code == 201, f"a fixed cost ({r.status_code} {r.text[:200]})")
FC = r.json()["id"]
check(A.patch(B + f"{OFF}/fixed-costs/{FC}", json={"label": "Miete Studio"}).ok, "its label changed")
GF = last(ALICE)["id"]
r = A.post(B + f"/api/undo/to/{GF}")
fc = [x for x in (A.get(B + OFF + "/fixed-costs").json().get("items") or []) if x.get("id") == FC]
check(r.ok and r.json().get("undone") == [GF] and fc and fc[0].get("label") == "Miete",
      f"a fixed cost (UGO_ADMIN) goes back from the list ({r.status_code} {r.text[:200]} {fc[:1]})")

# ---------------------------------------------------------------- the watchdog
out = in_app("""
from kalmido.notify import push
import kalmido.office.undo as ou
print('PRUNE', hasattr(ou, 'oun_prune'), 'SECTION', 'office undo copies' in push.WD_SLOW)""")
check("PRUNE False SECTION False" in out, f"oun_prune and its watchdog section are gone (core/undogroups.py undo_prune does it) {out[-300:]}")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FCL = setup_office(Fr, "Frei")
r = Fr.post(B + OFF + "/services", json={"name_de": "Schnitt", "daily_rate": 500})
FSV = r.json()["id"]
check(Fr.patch(B + f"{OFF}/services/{FSV}", json={"name_de": "Schnitt 1"}).ok, "she changes her service")
g = last(FID)
check(args(g) == ["Schnitt"] and g.get("area") == "office", f"her step: labelled, area office {g}")
FG = g["id"]
FI = invoice(Fr, FCL)
check(Fr.post(B + f"{D}/{FI}/finalize").ok, "she finalises an invoice")
FB = barrier(FID, "Finalised: {0}", "her finalising")["id"]
check(Fr.patch(B + f"{OFF}/services/{FSV}", json={"name_de": "Schnitt 2"}).ok, "another change")
r = Fr.post(B + f"/api/undo/to/{FG}")
j = r.json() if r.ok else {}
check(r.ok and (j.get("stopped") or {}).get("id") == FB and Fr.get(B + f"{OFF}/services/{FSV}").json().get("name_de") == "Schnitt 1",
      f"her 'bis hierher' stops at her barrier ({r.status_code} {j})")
check(A.post(B + f"/api/undo/to/{FB}").status_code == 404, "her barrier: 404 for alice")

sys.exit(done("p2747_c_office_undo"))
