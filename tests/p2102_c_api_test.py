#!/usr/bin/env python3
"""2.102.0 API tests, part C (#2201): questionnaires -- the client link. Own container (start.sh), invented companies and
people only (@example.com).
 - the link: GET /api/forms/<id>/client-link?client=<id> (owner / list admins; a client of the list's space) = the form's
   link + ?k=<client>.<signature>; a client of another space 400, another organisation's client 400 / 404, a member who does
   not manage the list 403, another organisation 404; GET /api/clients/<id>/forms = the open forms of the client's space
   with the link for this client (a private client: the private lists' forms only; another organisation 404)
 - the page: ?k= goes along as a hidden field ck (a forged one too: the same page), without it no field
 - sending: a valid link = this client, before the e-mail matching (another client's address); a forged signature, the
   link of another form or of a client that left the list's space = ignored without a word (the same answer), the e-mail
   matching as before; without a link everything as before; a classic form without e-mail matching takes the link too;
   a private list's form takes its owner's private client; "Send another one" keeps the link
 - tenant-matrix: form (the client link of a form of another organisation: 404)
usage: p2102_c_api_test.py <datadir>      (a fresh container; P2102C_NOSTART=1 = the server already runs)"""
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def stamp_of(text):
    m = re.search(r'name="stamp" value="([^"]+)"', text)
    return m.group(1) if m else ""


def tok(f):
    return f["url"].rsplit("/", 1)[1]


def last_task(lid):
    r = dbx("SELECT id, title, content FROM tasks WHERE list_id=? ORDER BY id DESC LIMIT 1", (lid,))
    return r[0] if r else (0, "", "")


def entry_client(tid):
    r = dbx("SELECT client_id FROM form_entries WHERE task_id=?", (tid,))
    return r[0][0] if r else "none"


SENDS = [0]


def send(t, data, s):
    """A send; at most 6 per address and minute (FORM_SEND_RATE): every sixth waits for the next minute."""
    if SENDS[0] and SENDS[0] % 6 == 0:
        time.sleep(RATE_S + 1)  # 2.149.0 (#2513): a new rate window
    SENDS[0] += 1
    return s.post(B + "/f/" + t, data=data, headers=H)


# 2.149.0 (#2513): the minute of the rate limits shortened to RATE_S (test containers only, KALMIDO_TEST_RATE_WINDOW_S)
RATE_S = 60 if os.environ.get("P2102C_NOSTART") else 10
if not os.environ.get("P2102C_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                       env=dict(os.environ, EXTRA=(os.environ.get("EXTRA", "") + f" -e KALMIDO_TEST_RATE_WINDOW_S={RATE_S}").strip()))
    assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,agents,clients,workload,forms,office"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.patch(B + "/api/admin/settings", json={"public_links": True})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
BOB = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
ORG2 = dbx("INSERT INTO orgs(name,icon,created_at) VALUES('Other Example','','2026-10-01T00:00:00Z') RETURNING id")[0][0]
dbx("DELETE FROM org_members WHERE user_id=?", (CAROL,))
dbx("INSERT INTO org_members(org_id,user_id) VALUES(?,?)", (ORG2, CAROL))
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
FL = A.post(B + "/api/lists", json={"name": "Requests", "org_id": ORG}).json()["id"]
PL = A.post(B + "/api/lists", json={"name": "Private requests", "org_id": None}).json()["id"]
A.put(B + f"/api/lists/{FL}/members", json={"user_id": BOB, "role": "edit"})
ACME = A.post(B + "/api/clients", json={"name": "Acme Example", "email": "buyer@example.com", "org_id": ORG}).json().get("id")
BETA = A.post(B + "/api/clients", json={"name": "Beta Example", "org_id": ORG}).json().get("id")
FOREIGN = Ca.post(B + "/api/clients", json={"name": "Foreign Example", "email": "far@example.com"}).json().get("id")
SOLO = A.post(B + "/api/clients", json={"name": "Solo Example", "org_id": None}).json().get("id")
for i in range(1, 7):  # more addresses of Acme: at most 5 sends per address, form and hour (FRM_EMAIL_HOUR)
    dbx("INSERT INTO office_client_contacts(org_id,client_id,name,email,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (ORG, ACME, f"Buyer {i}", f"buyer{i}@example.com", "2026-10-19T00:00:00Z", "2026-10-19T00:00:00Z"))
check(ACME and BETA and FOREIGN and SOLO and dbx("SELECT org_id FROM clients WHERE id=?", (FOREIGN,))[0][0] == ORG2
      and dbx("SELECT org_id FROM clients WHERE id=?", (SOLO,))[0][0] is None, "clients: two of the organisation, one of another, one private")
FQ = A.post(B + f"/api/lists/{FL}/forms", json={"title": "Questionnaire", "access": "public", "client_match": True,
                                                "questions": [{"kind": "short", "label": "Project", "required": True}]}).json()
FC = A.post(B + f"/api/lists/{FL}/forms", json={"title": "Classic", "access": "public"}).json()
FP = A.post(B + f"/api/lists/{PL}/forms", json={"title": "Private questionnaire", "access": "public",
                                                "questions": [{"kind": "short", "label": "Project"}]}).json()
QID, PQID = FQ["questions"][0]["id"], FP["questions"][0]["id"]
check(FQ.get("id") and FC.get("id") and FP.get("id") and FC["client_match"] is False and FP["client_match"] is False, "three forms")

# ================================================================== the link
r = A.get(B + f"/api/forms/{FQ['id']}/client-link", params={"client": BETA})
LB = r.json().get("url", "")
KB = LB.partition("?k=")[2]
check(r.ok and LB.startswith(FQ["url"] + "?k=") and re.fullmatch(rf"{BETA}\.[0-9a-f]{{32}}", KB), "the link for a client: the form's link + ?k= " + r.text[:200])
check(A.get(B + f"/api/forms/{FQ['id']}/client-link", params={"client": BETA}).json()["url"] == LB, "the same link again (no random part)")
KBC = A.get(B + f"/api/forms/{FC['id']}/client-link", params={"client": BETA}).json()["url"].partition("?k=")[2]
check(KBC and KBC != KB, "another form, another signature")
check(A.get(B + f"/api/forms/{FQ['id']}/client-link", params={"client": SOLO}).status_code == 400, "a private client for an organisation's form: 400")
check(A.get(B + f"/api/forms/{FQ['id']}/client-link", params={"client": FOREIGN}).status_code in (400, 404), "another organisation's client: refused")
check(A.get(B + f"/api/forms/{FQ['id']}/client-link", params={"client": "x"}).status_code == 400, "no client id: 400")
check(Bo.get(B + f"/api/forms/{FQ['id']}/client-link", params={"client": BETA}).status_code == 403, "a member who does not manage the list: 403")
check(Ca.get(B + f"/api/forms/{FQ['id']}/client-link", params={"client": BETA}).status_code == 404, "tenant-matrix: form -- another organisation: 404")
r = A.get(B + f"/api/clients/{BETA}/forms")
fs = {f["id"]: f for f in r.json().get("forms", [])}
check(r.ok and set(fs) == {FQ["id"], FC["id"]} and fs[FQ["id"]]["url"] == LB and fs[FQ["id"]]["list_name"] == "Requests"
      and fs[FQ["id"]]["questions"] == 1, "a client's forms: the open forms of its space with its link " + r.text[:300])
r = A.get(B + f"/api/clients/{SOLO}/forms")
check(r.ok and [f["id"] for f in r.json()["forms"]] == [FP["id"]], "a private client: the private list's form only")
check(Ca.get(B + f"/api/clients/{BETA}/forms").status_code == 404, "another organisation's client: 404")
check(Bo.get(B + f"/api/clients/{BETA}/forms").json().get("forms") == [], "a member who manages no form: none")
A.patch(B + f"/api/forms/{FC['id']}", json={"enabled": False})
check([f["id"] for f in A.get(B + f"/api/clients/{BETA}/forms").json()["forms"]] == [FQ["id"]], "a closed form is not offered")
A.patch(B + f"/api/forms/{FC['id']}", json={"enabled": True})

# ================================================================== the page
anon = requests.Session()
anon.headers.update(H)
FORGED = KB[:-1] + ("0" if KB[-1] != "0" else "1")
p_ok, p_bad, p_none = (anon.get(B + "/f/" + tok(FQ) + q).text for q in ("?k=" + KB, "?k=" + FORGED, ""))
check(f'name="ck" value="{KB}"' in p_ok and f'name="ck" value="{FORGED}"' in p_bad and 'name="ck"' not in p_none,
      "the page carries ?k= as a hidden field (a forged one too), without it none")
strip = lambda t: re.sub(r'name="(stamp|ck)" value="[^"]*"', "", t)  # noqa: E731
check(strip(p_ok) == strip(p_bad) and "Beta" not in p_ok, "a right and a forged link: the same page, no client name")
check('name="ck"' not in anon.get(B + "/f/" + tok(FQ) + "?k=" + str(BETA) + ".<script>").text, "a value that is no link: no field")
time.sleep(0.2)
st = [stamp_of(anon.get(B + "/f/" + tok(FQ)).text) for _ in range(9)]
stc = [stamp_of(anon.get(B + "/f/" + tok(FC)).text) for _ in range(2)]
stp = [stamp_of(anon.get(B + "/f/" + tok(FP)).text) for _ in range(1)]
time.sleep(3.3)


ADDR = [f"buyer{i}@example.com" for i in range(1, 7)] + ["buyer@example.com"]


def q_send(ck=None, email=None, form=FQ, stamps=st, qid=QID):
    d = {f"q_{qid}": "A new website", "name": "Eve", "email": ADDR.pop() if email is None else email, "stamp": stamps.pop()}
    if ck is not None:
        d["ck"] = ck
    return send(tok(form), d, anon)


# ================================================================== sending
p = q_send(KB)
T = last_task(FL)
check(p.ok and "Your request has been sent." in p.text and entry_client(T[0]) == BETA and "Client: Beta Example" in T[2] and "Acme" not in T[2],
      "a valid link: this client, before the e-mail matching (an address of Acme) " + str(T[2][-200:]))
check(f'href="/f/{tok(FQ)}?k={KB}"' in p.text, "“Send another one” keeps the link")
answers = {}
for what, ck in (("forged", FORGED), ("another form's", KBC), ("garbage", "123.abc"), ("a bare id", str(BETA))):
    p = q_send(ck)
    T = last_task(FL)
    answers[what] = (p.status_code, re.sub(r'href="[^"]*"', "", p.text))
    check(p.ok and entry_client(T[0]) == ACME and "Client: Acme Example" in T[2] and "Beta" not in T[2],
          f"{what} link: ignored, the e-mail matching as before " + str(T[2][-200:]))
check(len(set(answers.values())) == 1, "the same answer for every ignored link")
p = q_send()
T = last_task(FL)
check(p.ok and entry_client(T[0]) == ACME, "without a link: the e-mail matching as before")
p = q_send(None, "")
T = last_task(FL)
check(p.ok and entry_client(T[0]) is None and "Client" not in T[2], "without a link and an address: no client, no note")
dbx("UPDATE clients SET org_id=? WHERE id=?", (ORG2, BETA))  # the client left the list's space (signature still right)
p = q_send(KB, "new@example.com")
T = last_task(FL)
check(p.ok and entry_client(T[0]) is None and "Beta" not in T[2] and "Client unknown: new@example.com" in T[2],
      "a client outside the list's space: the link is ignored " + str(T[2][-200:]))
dbx("UPDATE clients SET org_id=? WHERE id=?", (ORG, BETA))
p = send(tok(FC), {"subject": "Hello", "text": "Classic", "name": "Eve", "email": "buyer@example.com", "stamp": stc.pop(), "ck": KBC}, anon)
T = last_task(FL)
check(p.ok and T[1] == "Hello" and "Client: Beta Example" in T[2], "a classic form without e-mail matching takes the link too")
p = send(tok(FC), {"subject": "Hello again", "text": "Classic", "name": "Eve", "email": "buyer@example.com", "stamp": stc.pop()}, anon)
T = last_task(FL)
check(p.ok and T[1] == "Hello again" and "Client" not in T[2], "the classic form without a link: as before (no matching)")
KS = A.get(B + f"/api/forms/{FP['id']}/client-link", params={"client": SOLO}).json().get("url", "").partition("?k=")[2]
p = q_send(KS, "", FP, stp, PQID)
T = last_task(PL)
check(KS and p.ok and entry_client(T[0]) == SOLO and "Client: Solo Example" in T[2], "a private list's form: the owner's private client")

print(f"p2102_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
