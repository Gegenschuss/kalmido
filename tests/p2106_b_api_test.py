#!/usr/bin/env python3
"""2.106.0 API tests, part B (#2028: letters <-> documents of the documents space), own container (start.sh, org
encryption on). Invented companies, people and figures only.
tenant-matrix: office
freelancer-matrix: office
 - recognition (plain rules): references ("Unser Zeichen", "Az.", "Versicherungsnummer", "Our ref" ...) and deadlines
   ("bis zum 31.10.2026", "spätestens am", "Frist", "innerhalb von 14 Tagen" / "within two weeks" from the document date);
   payment terms and periods are no deadline
 - the document side: GET /api/office/letters/doc/<nid> (letters of both directions, deadline, references); a member,
   another organisation, a document outside the office's space -> {available: false}
 - a new letter answering a document: recipient from the sender (the client with that name: address + e-mail), subject
   "Your letter of <date>", DIN 5008 reference line, the link "answers"; a foreign / private document 404
 - links: set / remove (both kinds, also at a sent letter), bad kind 400, the reference line filled at a draft without one
 - history: the thread of a letter (letters + documents over links, in date order), the threads of a client
 - deadline -> task (due = the deadline, the document linked; a second call sets the due date of the same task)
 - follow-up: a sent letter past its follow-up day without an answer -> one task; with an answer -> none
 - a document in the bin is not shown; the personal office of a person without organisation works the same
usage: p2106_b_api_test.py <datadir>      (P2106B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import json
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs,files"
LT = "/api/office/letters"


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


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall() if not write else c.execute(q, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def upload(s, name, text, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text.encode("utf-8"), "text/plain"))])
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    d = until(lambda: (lambda x: x.json() if x.ok and x.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), 90)
    assert d and d["state"] == "done", d
    return nid


def in_ct(code):
    """Runs python code in the test container, -> its JSON output."""
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


if os.environ.get("P2106B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"
               " -e KALMIDO_DOCS_SCAN_S=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)

# ---- recognition: plain rules, checked in the container
CASES = [
    ("Bitte senden Sie uns die Unterlagen bis zum 31.10.2026 zurück.", "2026-10-05", "2026-10-31"),
    ("Ihre Stellungnahme erwarten wir spätestens am 15. November 2026.", "2026-10-05", "2026-11-15"),
    ("Frist: 20.11.2026", "2026-10-05", "2026-11-20"),
    ("Sie können innerhalb von 14 Tagen Widerspruch einlegen.", "2026-10-05", "2026-10-19"),
    ("Bitte antworten Sie binnen zwei Wochen.", "2026-10-05", "2026-10-19"),
    ("Please reply within two weeks of this letter.", "2026-10-05", "2026-10-19"),
    ("Please send the form back no later than 30 October 2026.", "2026-10-05", "2026-10-30"),
    ("Please reply by 28 October 2026.", "2026-10-05", "2026-10-28"),
    ("Zahlbar innerhalb von 14 Tagen ohne Abzug.", "2026-10-05", None),         # a payment term: the due date of the documents area
    ("Zahlungsziel: innerhalb 30 Tagen netto.", "2026-10-05", None),
    ("Der Vertrag läuft vom 01.10.2026 bis zum 31.12.2026.", "2026-10-05", None),  # a period
    ("Signed by Erika Beispiel on 05.10.2026.", "2026-10-05", None),
    ("Sie können innerhalb von 14 Tagen Widerspruch einlegen.", None, None),    # no document date: no relative deadline
    ("Ihre Antwort bis zum 01.01.2020", "2026-10-05", None),                    # before the document date
]
REFS = [
    ("Unser Zeichen: VB-2026/4711\nDatum: 05.10.2026", [("theirs", "VB-2026/4711")]),
    ("Az. 12 K 345/26 Bitte stets angeben", [("theirs", "12 K 345/26")]),
    ("Ihr Zeichen: MB 77 Unser Zeichen: abc-99", [("ours", "MB 77"), ("theirs", "abc-99")]),
    ("Versicherungsnummer: 123 456 789\nKundennummer 4711 Datum 05.10.2026", [("policy", "123 456 789"), ("customer", "4711")]),
    ("Vers.-Nr. KV-55-1234", [("policy", "KV-55-1234")]),
    ("Steuernummer 12/345/67890", [("tax", "12/345/67890")]),
    ("Our ref: ABC/2026/17\nYour ref: X-5", [("theirs", "ABC/2026/17"), ("ours", "X-5")]),
    ("With reference to your letter of last week", []),
    ("Geschäftszeichen\nIII-4 / 2026-0815", [("theirs", "III-4 / 2026-0815")]),
]
res = in_ct("import json\nfrom kalmido.office.letterlinks import ltl_deadline, ltl_refs\n"
            f"C = {json.dumps(CASES)}\nR = {json.dumps([t for t, _ in REFS])}\n"
            "print(json.dumps({'dl': [(ltl_deadline(t, d) or {}).get('date') for t, d, _ in C], 'refs': [[(x['kind'], x['value']) for x in ltl_refs(t)] for t in R]}))")
for (t, _d, want), got in zip(CASES, res["dl"]):
    check(got == want, f"deadline of {t!r}: {got} (want {want})")
for (t, want), got in zip(REFS, res["refs"]):
    check([tuple(x) for x in got] == want, f"references of {t!r}: {got} (want {want})")

# ---- people: alice (admin of Alpha), bob (member of Alpha), carol (admin of Beta), dora (no organisation)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
DORA, Do = freelancer(B, A, "dora")
CL = A.post(B + "/api/clients", json={"name": "Versicherung Beispiel AG", "street": "Versicherungsweg 2", "zip": "20000", "city": "Hamburg",
                                       "country": "DE", "email": "post@versicherung.example.com"}).json()["id"]

TXT1 = ("Versicherung Beispiel AG\nVersicherungsweg 2\n20000 Hamburg\n\nDatum: 05.10.2026\nUnser Zeichen: VB-2026/4711\n"
        "Versicherungsnummer: 123 456 789\n\nSehr geehrte Damen und Herren,\nbitte senden Sie uns die Unterlagen bis zum 31.10.2026 zurück.\n")
D1 = upload(A, "Schreiben Versicherung.txt", TXT1, f"org:{ORG}")
A.patch(B + f"/api/docs/{D1}", json={"sender": "Versicherung Beispiel AG"})
D2 = upload(A, "Antwort Versicherung.txt", "Versicherung Beispiel AG\n\nDatum: 20.10.2026\nWir bestätigen den Eingang Ihrer Unterlagen.\n", f"org:{ORG}")
DP = upload(A, "Privat Alice.txt", "Datum: 06.10.2026\nPrivate Notiz bis zum 30.10.2026\n", "private")
DC = upload(Ca, "Beta Brief.txt", "Datum: 07.10.2026\nFremd bis zum 30.10.2026\n", f"org:{ORG2}")
DN = upload(A, "Ohne Frist.txt", "Datum: 08.10.2026\nNur zur Kenntnis.\n", f"org:{ORG}")

# ---- the document side
x = A.get(B + f"{LT}/doc/{D1}").json()
check(x.get("available") is True and x["letters"] == [] and x["task"] is None, f"document: available, nothing linked yet {x}")
check((x.get("deadline") or {}).get("date") == "2026-10-31" and "31.10.2026" in (x["deadline"].get("text") or ""), f"document: the deadline {x.get('deadline')}")
check(("theirs", "VB-2026/4711") in [(r["kind"], r["value"]) for r in x.get("refs", [])] and
      ("policy", "123 456 789") in [(r["kind"], r["value"]) for r in x.get("refs", [])], f"document: the references {x.get('refs')}")
check(Bo.get(B + f"{LT}/doc/{D1}").json() == {"available": False}, "document: a member of the organisation gets nothing")
check(Ca.get(B + f"{LT}/doc/{D1}").json() == {"available": False}, "document: another organisation gets nothing")
check(A.get(B + f"{LT}/doc/{DP}").json() == {"available": False}, "document: a private document is not of the organisation's office")
check(A.get(B + f"{LT}/doc/{DC}").json() == {"available": False}, "document: a document of another organisation")
check(A.get(B + f"{LT}/doc/99999999").json() == {"available": False}, "document: unknown id")
check(Do.get(B + f"{LT}/doc/{D1}").json() == {"available": False}, "document: a person without organisation, a foreign document")

# ---- a letter answering D1
r = A.post(B + LT, json={"answers": D1})
check(r.status_code == 201, f"answer: created ({r.status_code} {r.text[:200]})")
L1 = r.json()
check(L1.get("client_id") == CL and L1.get("rcpt_name") == "Versicherung Beispiel AG" and "Versicherungsweg 2" in (L1.get("rcpt_address") or "")
      and "20000 Hamburg" in (L1.get("rcpt_address") or "") and L1.get("rcpt_email") == "post@versicherung.example.com", f"answer: the recipient {L1}")
check(L1.get("subject") == "Your letter of 5 October 2026", f"answer: the subject {L1.get('subject')}")
rl = L1.get("ref_line") or ""
check("Your reference: VB-2026/4711" in rl and "Your message of 5 October 2026" in rl and "Policy number: 123 456 789" in rl, f"answer: the reference line {rl}")
x = A.get(B + f"{LT}/doc/{D1}").json()
check([(l["id"], l["kind"]) for l in x["letters"]] == [(L1["id"], "answers")], f"document: the answer is linked {x['letters']}")
x = A.get(B + f"{LT}/{L1['id']}/links").json()
check([(l["node_id"], l["kind"]) for l in x["links"]] == [(D1, "answers")] and x["docs_ws"] == f"org:{ORG}", f"letter: the links {x}")
check(x["ref_line"] == rl and x["followup"]["answered"] is False, f"letter: the suggested reference line {x}")
for s, nid, what in ((A, DP, "a private document"), (A, DC, "another organisation's document"), (A, 99999999, "an unknown document")):
    r = s.post(B + LT, json={"answers": nid})
    check(r.status_code == 404, f"answer to {what}: 404 ({r.status_code})")
check(Bo.post(B + LT, json={"answers": D1}).status_code == 403, "answer: a member 403")
check(Ca.post(B + LT, json={"answers": D1}).status_code == 404, "answer: another organisation 404")

# ---- links: set / remove
LB = A.post(B + LT, json={"subject": "Nachfrage"}).json()
r = A.post(B + f"{LT}/{LB['id']}/links", json={"node_id": D1, "kind": "answers"})
check(r.status_code == 201 and "VB-2026/4711" in (r.json().get("ref_line") or ""), f"link answers: the empty reference line is filled ({r.text[:200]})")
check("VB-2026/4711" in (A.get(B + f"{LT}/{LB['id']}").json().get("ref_line") or ""), "link answers: the letter has the reference line")
A.patch(B + f"{LT}/{LB['id']}", json={"ref_line": "Mein Bezug"})
r = A.post(B + f"{LT}/{LB['id']}/links", json={"node_id": DN, "kind": "answers"})
check(r.status_code == 201 and A.get(B + f"{LT}/{LB['id']}").json()["ref_line"] == "Mein Bezug", "link answers: a reference line typed in stays")
check(A.post(B + f"{LT}/{LB['id']}/links", json={"node_id": D1, "kind": "other"}).status_code == 400, "link: bad kind 400")
check(A.post(B + f"{LT}/{LB['id']}/links", json={"node_id": DC, "kind": "answers"}).status_code == 404, "link: another organisation's document 404")
check(A.post(B + f"{LT}/{LB['id']}/links", json={"node_id": DP, "kind": "answers"}).status_code == 404, "link: a private document 404")
check(Bo.post(B + f"{LT}/{LB['id']}/links", json={"node_id": D1, "kind": "answers"}).status_code == 403, "link: a member 403")
check(Ca.post(B + f"{LT}/{LB['id']}/links", json={"node_id": DC, "kind": "answers"}).status_code == 404, "link: a letter of another organisation 404")
r = A.delete(B + f"{LT}/{LB['id']}/links/{DN}?kind=answers")
check(r.ok and [l["node_id"] for l in r.json()["links"]] == [D1], f"unlink: gone ({r.text[:200]})")
check(A.delete(B + f"{LT}/{LB['id']}/links/{DN}?kind=answers").status_code == 404, "unlink again: 404")
check(Ca.delete(B + f"{LT}/{LB['id']}/links/{D1}").status_code == 404, "unlink: another organisation 404")
check(A.delete(B + f"{LT}/{LB['id']}/links/{D1}?kind=bad").status_code == 400, "unlink: bad kind 400")

# sent letter: the answer D2 arrives (reply), the history
r = A.post(B + f"{LT}/{L1['id']}/sent", json={"channel": "post", "followup_days": 14})
check(r.ok and r.json()["status"] == "sent" and r.json()["followup_due"], f"sent with a follow-up ({r.text[:200]})")
r = A.post(B + f"{LT}/{L1['id']}/links", json={"node_id": D2, "kind": "reply"})
check(r.status_code == 201 and r.json()["followup"]["answered"] is True, f"reply at a sent letter: answered ({r.text[:200]})")
x = A.get(B + f"{LT}/doc/{D2}").json()
check([(l["id"], l["kind"]) for l in x["letters"]] == [(L1["id"], "reply")], f"document: the reply side {x.get('letters')}")
L2 = A.post(B + LT, json={"answers": D2}).json()
th = A.get(B + f"{LT}/{L1['id']}/thread").json()["items"]
check((th[0]["type"], th[0]["id"]) == ("doc", D1) and [i["date"] for i in th] == sorted(i["date"] for i in th)
      and {("letter", L1["id"]), ("doc", D2), ("letter", L2["id"])} <= {(i["type"], i["id"]) for i in th},
      f"thread: in time order {[(i['type'], i['id'], i['date']) for i in th]}")
check({("letter", LB["id"])} <= {(i["type"], i["id"]) for i in th}, "thread: the other letter answering D1 belongs to it")
check(all(i["dir"] == ("out" if i["type"] == "letter" else "in") for i in th) and th[0]["href"] == f"#docs/{D1}", "thread: directions + links")
check(Bo.get(B + f"{LT}/{L1['id']}/thread").status_code == 403 and Ca.get(B + f"{LT}/{L1['id']}/thread").status_code == 404, "thread: member 403, other org 404")
t = A.get(B + f"{LT}/threads?client_id={CL}").json()["threads"]
check(len(t) == 1 and t[0]["count"] >= 4 and t[0]["topic"] == "Schreiben Versicherung", f"threads of the client {[(x['topic'], x['count']) for x in t]}")
check(A.get(B + f"{LT}/threads").status_code == 400, "threads: without client 400")
check(Ca.get(B + f"{LT}/threads?client_id={CL}").json()["threads"] == [], "threads: another organisation sees none")

# ---- deadline -> task
r = A.post(B + f"{LT}/doc/{D1}/deadline-task", json={})
check(r.status_code == 201 and r.json()["due"] == "2026-10-31" and r.json()["title"] == "Deadline: Schreiben Versicherung", f"deadline task ({r.text[:200]})")
TID = r.json().get("task_id")
t = A.get(B + f"/api/tasks/{TID}").json()
check((t.get("due") or "")[:10] == "2026-10-31" and f"#docs/{D1}" in (t.get("content") or ""), f"deadline task: due + link {t.get('due')}")
check(A.get(B + f"/api/docs/{D1}").json()["task_id"] == TID and A.get(B + f"{LT}/doc/{D1}").json()["task"]["id"] == TID, "deadline task: linked at the document")
r = A.post(B + f"{LT}/doc/{D1}/deadline-task", json={"due": "2026-11-05"})
check(r.ok and r.json()["existing"] is True and r.json()["task_id"] == TID and r.json()["old_due"][:10] == "2026-10-31", f"deadline task again: the same task ({r.text[:200]})")
check((A.get(B + f"/api/tasks/{TID}").json().get("due") or "")[:10] == "2026-11-05", "deadline task again: the due date set")
check(A.post(B + f"{LT}/doc/{D1}/deadline-task", json={"due": "31.10.2026"}).status_code == 400, "deadline task: bad date 400")
check(A.post(B + f"{LT}/doc/{DN}/deadline-task", json={}).status_code == 400, "deadline task: no deadline 400")
check(Bo.post(B + f"{LT}/doc/{D1}/deadline-task", json={}).status_code == 403, "deadline task: member 403")
check(Ca.post(B + f"{LT}/doc/{D1}/deadline-task", json={}).status_code == 404, "deadline task: other organisation 404")
check(A.post(B + f"{LT}/doc/{DP}/deadline-task", json={}).status_code == 404, "deadline task: a private document 404")

# ---- follow-up
L3 = A.post(B + LT, json={"subject": "Ohne Antwort", "rcpt_name": "Amt Beispiel"}).json()
A.post(B + f"{LT}/{L3['id']}/sent", json={"followup_days": 14})
sql("UPDATE office_letters SET followup_due='2020-01-01' WHERE id IN (?, ?)", (L3["id"], L1["id"]), write=True)
TICK = "import json\nfrom kalmido.core.db import connect\nfrom kalmido.office.letterlinks import ltl_followup_tick\nc = connect()\nprint(json.dumps(ltl_followup_tick(c, force=True)))\nc.close()"
in_ct(TICK)
r3 = sql("SELECT followup_task_id FROM office_letters WHERE id=?", (L3["id"],))[0][0]
r1 = sql("SELECT followup_task_id FROM office_letters WHERE id=?", (L1["id"],))[0][0]
check(bool(r3) and r1 is None, f"follow-up: a task for the letter without an answer only ({r3}, {r1})")
t = A.get(B + f"/api/tasks/{r3}").json() if r3 else {}
check(t.get("title") == "Follow-up: Ohne Antwort" and f"#office/letters/{L3['id']}" in (t.get("content") or ""), f"follow-up: the task {t.get('title')}")
check(in_ct(TICK) == 0 and sql("SELECT followup_task_id FROM office_letters WHERE id=?", (L3["id"],))[0][0] == r3, "follow-up: once only")
x = A.get(B + f"{LT}/{L3['id']}/links").json()["followup"]
check(x["task_id"] == r3 and x["answered"] is False, f"follow-up: shown at the letter {x}")

# ---- the bin: a deleted document is not shown
check(A.delete(B + f"/api/files/nodes/{D2}").ok, "delete the answer document")
x = A.get(B + f"{LT}/{L1['id']}/links").json()
check(D2 not in [l["node_id"] for l in x["links"]] and x["followup"]["answered"] is False, f"bin: the link is hidden {x}")
check(A.get(B + f"{LT}/doc/{D2}").json() == {"available": False}, "bin: the document side is empty")
check(("doc", D2) not in [(i["type"], i["id"]) for i in A.get(B + f"{LT}/{L1['id']}/thread").json()["items"]], "bin: not in the history")

# ---- a person without organisation (personal office, private documents)
DD = upload(Do, "Finanzamt.txt", "Finanzamt Beispielstadt\nDatum: 01.10.2026\nSteuernummer 12/345/67890\nAktenzeichen: ESt 2025-17\n"
            "Bitte reichen Sie die Belege innerhalb von vier Wochen ein.\n", "private")
x = Do.get(B + f"{LT}/doc/{DD}").json()
check(x.get("available") is True and (x.get("deadline") or {}).get("date") == "2026-10-29", f"freelancer: the document side {x}")
r = Do.post(B + LT, json={"answers": DD})
check(r.status_code == 201 and "Your reference: ESt 2025-17" in (r.json().get("ref_line") or "") and "Tax number: 12/345/67890" in r.json()["ref_line"],
      f"freelancer: the answer ({r.text[:250]})")
LD = r.json()["id"]
check(A.get(B + f"{LT}/{LD}").status_code == 404 and A.get(B + f"{LT}/{LD}/links").status_code == 404, "freelancer: the letter is not the others'")
check(A.get(B + f"{LT}/doc/{DD}").json() == {"available": False}, "freelancer: the document is not the others'")
check(Do.post(B + f"{LT}/{LD}/links", json={"node_id": D1, "kind": "reply"}).status_code == 404, "freelancer: a foreign document 404")
r = Do.post(B + f"{LT}/doc/{DD}/deadline-task", json={})
check(r.status_code == 201 and r.json()["due"] == "2026-10-29", f"freelancer: deadline task ({r.text[:200]})")
check(Do.get(B + f"{LT}/{LD}/thread").ok and Do.get(B + f"{LT}/{LD}/links").json()["docs_ws"] == "private", "freelancer: history + space of the picker")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
