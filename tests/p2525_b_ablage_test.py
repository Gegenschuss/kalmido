#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.525.0 (#4195) the documents list and the mail filing read less: the visible nodes once per request, the row helpers
for all rows at once, the mail lists without the texts. Invented names and texts only.
 - who sees what stays the same: a person without an organisation sees only her own documents, an organisation's admin the
   organisation's and a document shared with him, the instance admin outside the organisation none of them, an agent of
   the person none of her documents that are not shared with it; the facets name only labels of visible documents
 - tags and the "shared" flag of every row as before (read for all rows at once)
 - the statements of GET /api/docs do not grow with the rows of the page (before: about four per row)
 - GET /api/hubmail/mails?list_id=: the statements do not grow with the mails (before: the project and its name per mail);
   the opened mail has its text; the search finds a word prefix of the text (the list rows carry no text any more)
   and a stranger still gets no mail of the project
usage: p2525_b_ablage_test.py <datadir>"""
# freelancer-matrix: files, docs, hub
import json
import re
import subprocess
import sys

import requests

import kt
from kt import B, CT, H, check, dbx
from freelancer_fixture import FEATURES, freelancer, login

kt.fresh(prefix="P2525BA")
kt.docker_logs_on_first_fail(tail=120, chars=9000)
A = kt.setup()
FID, Fr = freelancer(B, A)
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": kt.PASSWORD, "email": "bob@example.com", "orgs": []})
check(r.ok, "setup: bob " + r.text[:200])
BID = r.json()["id"]
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Example Studio", "admin_id": BID}).json()["id"]
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "files:read"]})
check(r.ok, "setup: frida's agent " + r.text[:200])
AGH = {**H, "Authorization": "Bearer " + r.json()["token"]}
AGID = r.json()["id"]
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')
TS = "2026-01-01T00:00:00+00:00"


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app, json\n" + code],
                       capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-1500:]


def doc(owner, oid, name):
    nid = dbx("INSERT INTO fs_nodes(kind, name, owner_id, org_id, mime, size, created_at, updated_at) VALUES('file',?,?,?,?,?,?,?) RETURNING id",
              (name, owner, oid, "application/pdf", 100, TS, TS))[0][0]
    dbx("INSERT INTO doc_meta(node_id, org_id, ws, state, doc_date, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        (nid, oid, f"o{oid}" if oid else f"u{owner}", "done", "2026-01-02", TS, TS))
    return nid


def tag(ws, oid, name, *nodes):
    # 2.1119.0 (#5277): the file store's tags are rows of the core (obj_tags scope ws / obj_tag_links kind fs_entry)
    tid = dbx("INSERT INTO obj_tags(scope_kind, scope_id, org_id, name, created_at) VALUES('ws',?,?,?,?) RETURNING id", (ws, oid, name, TS))[0][0]
    for n in nodes:
        dbx("INSERT INTO obj_tag_links(tag_id, kind, obj_id) VALUES(?,'fs_entry',?)", (tid, n))
    return tid


def seen(s, q=""):
    r = s.get(B + "/api/docs?limit=200" + q)
    check(r.ok, "the documents list answers " + r.text[:200])
    return r, r.json()


F1, F2, F3 = doc(FID, None, "frida-a.pdf"), doc(FID, None, "frida-b.pdf"), doc(FID, None, "frida-c.pdf")
O1, O2 = doc(BID, ORG, "studio-a.pdf"), doc(BID, ORG, "studio-b.pdf")
tag(f"u{FID}", None, "Taxes", F1, F2)
tag(f"u{FID}", None, "Aardvark", F1)
tag(f"o{ORG}", ORG, "Studio secret", O1)
dbx("INSERT INTO fs_shares(node_id, user_id, role, created_by, created_at) VALUES(?,?,?,?,?)", (F3, BID, "view", FID, TS))

# who sees what (the same as before the change)
_, j = seen(Fr)
check({d["id"] for d in j["docs"]} == {F1, F2, F3} and j["total"] == 3, f"frida (no organisation) sees only her own {[d['name'] for d in j['docs']]}")
by = {d["id"]: d for d in j["docs"]}
check([t["name"] for t in by[F1]["tags"]] == ["Aardvark", "Taxes"] and [t["name"] for t in by[F2]["tags"]] == ["Taxes"] and by[F3]["tags"] == [],
      f"#4195 the tags of every row, sorted, as before {[(by[x]['name'], by[x]['tags']) for x in by]}")
check(by[F3]["shared"] is True and by[F1]["shared"] is False, "#4195 the shared flag of every row as before")
names = {t["name"] for t in j["facets"]["tags"]}
check(names == {"Aardvark", "Taxes"}, f"frida's facets: only her own labels {names}")
_, j = seen(Bo)
check({d["id"] for d in j["docs"]} == {O1, O2, F3}, f"bob (organisation admin) sees the organisation's documents and the one shared with him {[d['name'] for d in j['docs']]}")
check("Studio secret" in {t["name"] for t in j["facets"]["tags"]}, "bob's facets have the organisation's label")
_, j = seen(A)
check(not {O1, O2, F1, F2, F3} & {d["id"] for d in j["docs"]}, f"the instance admin outside the organisation sees none of them {[d['name'] for d in j['docs']]}")
check(not {t["name"] for t in j["facets"]["tags"]} & {"Studio secret", "Taxes"}, "nor their labels in the facets")
r = requests.get(B + "/api/v1/documents?limit=100", headers=AGH)
check(r.ok and not {F1, F2, F3, O1, O2} & {int(str(d["id"])) for d in r.json()["data"]},
      f"frida's agent sees none of her documents not shared with it {r.status_code} {r.text[:200]}")
r = Fr.post(B + f"/api/files/nodes/{F2}/shares", json={"agent_id": AGID, "role": "view"})
check(r.status_code == 201, f"frida shares one document with her agent {r.status_code} {r.text[:200]}")
r = requests.get(B + "/api/v1/documents?limit=100", headers=AGH)
check(r.ok and {int(str(d["id"])) for d in r.json()["data"]} == {F2}, f"#4195 the agent sees exactly the shared one {r.text[:300]}")

# the statements of one list answer do not grow with its rows
r5, _ = seen(Fr)
for i in range(20):
    doc(FID, None, f"frida-more-{i}.pdf")
r25, j = seen(Fr)
check(j["total"] == 23 and len(j["docs"]) == 23, f"all 23 of frida's documents {j['total']}")
n5, n25 = nstmt(r5), nstmt(r25)
check(n5 > 0 and n25 - n5 <= 3, f"#4195 GET /api/docs: the statements do not grow with the rows ({n5} with 3 rows, {n25} with 23)")
print(f"PERF /api/docs statements 3 rows {n5}, 23 rows {n25}")

# the mail filing of a project
LID = Fr.post(B + "/api/lists", json={"name": "Example project"}).json()["id"]


def mail(subject, body):
    return dbx("INSERT INTO hub_mails(owner_id, list_id, ws, message_id, from_addr, from_name, subject, body, sent_at, created_at) "
               "VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id", (FID, LID, f"u{FID}", f"<{subject.replace(' ', '.')}@example.test>", "anna@example.com",
                                                             "Anna Example", subject, body, TS, TS))[0][0]


M1 = mail("Quarter report", "The zebrafinch numbers of the quarter")
for i in range(2):
    mail(f"Hello {i}", "Nothing to see")
out = in_app(f"from kalmido.core.db import connect\nfrom kalmido.hub import hubmail as H\nc = connect()\n"
             f"H._index(c, {M1}, 'u{FID}', {{'subject': 'Quarter report', 'from_name': 'Anna Example', 'from_addr': 'anna@example.com', "
             f"'body': 'The zebrafinch numbers of the quarter'}})\nc.commit()\nc.close()\nprint('indexed')")
check(out == "indexed", "setup: the search index of the mail " + out[-600:])


def mails(s, q=""):
    r = s.get(B + f"/api/hubmail/mails?list_id={LID}{q}")
    return r, (r.json() if r.ok else {})


r3, j = mails(Fr)
check(r3.ok and j["total"] == 3, f"the project's three mails {r3.status_code} {r3.text[:200]}")
check(all("body" not in m for m in j.get("mails", [])) and j["mails"][0]["list_name"] == "Example project", "the list rows: no text, the project's name")
for i in range(20):
    mail(f"More {i}", "Nothing to see")
r23, j = mails(Fr)
check(j.get("total") == 23, f"all 23 mails {j.get('total')}")
m3, m23 = nstmt(r3), nstmt(r23)
check(m3 > 0 and m23 - m3 <= 3, f"#4195 the mail list: the statements do not grow with the mails ({m3} with 3, {m23} with 23)")
print(f"PERF /api/hubmail/mails statements 3 mails {m3}, 23 mails {m23}")
r = Fr.get(B + f"/api/hubmail/mails/{M1}")
check(r.ok and "zebrafinch" in (r.json().get("mail") or r.json()).get("body", ""), "the opened mail has its text " + r.text[:200])
_, j = mails(Fr, "&q=zebraf")
check([m["id"] for m in j.get("mails", [])] == [M1], f"#4195 the search finds a word prefix of the text (rows without text) {j.get('total')}")
_, j = mails(Fr, "&q=giraffe")
check(j.get("total") == 0, "a word nowhere: no mail")
r, _ = mails(Bo)
check(r.status_code in (403, 404), f"a stranger gets no mail of the project {r.status_code}")

sys.exit(kt.done("p2525_b_ablage"))
