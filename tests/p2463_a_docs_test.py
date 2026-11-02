#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.463.0 (#3889) GET /api/v1/office/docs: open=1 and an agent's list restriction count before the page is cut, pages by
before / next_cursor as /api/office/docs. Invented data only, as a person without an organisation and her agent.
 - an old open invoice behind 500 newer paid ones is found
 - open keeps its meaning for the other kinds (a credit note, a sent quotation)
 - a page by next_cursor: every document once, the last page without a cursor; a bad cursor is refused
 - an agent limited to one list: its old document behind 500 of another list is found, the others stay out
usage: p2463_a_docs_test.py <datadir>"""
# freelancer-matrix: office
import json
import sys

import requests

import kt
from kt import B, check, dbx
from freelancer_fixture import H, freelancer

kt.fresh(prefix="P2463A")
A = kt.setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, Fr = freelancer(B, A)
r = Fr.get(B + "/api/office/docs?kind=invoice")
check(r.ok, "the own office answers " + r.text[:120])
OID = r.json()["org_id"]
check(Fr.put(B + "/api/office/settings", json={"agents_read": 1}).ok, "agents may read")


def doc(kind, number, status, date, list_id=None):
    dbx("INSERT INTO office_docs(org_id, kind, number, status, lang, currency, recipient, date, project_title, due_date, rights, fields, totals, "
        "created_by, created_at, updated_at, locked_at, list_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (OID, kind, number, status, "en", "EUR", json.dumps({"name": "client", "lines": []}), date, "", "2030-01-01", "{}", "[]",
         json.dumps({"net": 10, "gross": 12}), FID, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", list_id))


r = Fr.post(B + "/api/my/agents", json={"username": "docbot", "display_name": "Doc Bot", "scopes": ["read", "office"]})
check(r.status_code == 201, "an agent " + r.text[:200])
AID, AH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
check(Fr.patch(B + f"/api/office/agents/{AID}", json={"office_drafts": True}).ok, "the agent's office switch")


def docs(q):
    r = requests.get(B + "/api/v1/office/docs?" + q, headers=AH)
    check(r.ok, f"{q}: answers " + r.text[:160])
    return r.json()


# ---- open=1 behind the 500 newest
doc("invoice", "OLD-1", "issued", "2001-01-01")
for i in range(505):
    doc("invoice", f"PAID-{i}", "paid", f"20{10 + i % 16}-02-{1 + i % 28:02d}")
j = docs("kind=invoice&open=1")
check([x["number"] for x in j["data"]] == ["OLD-1"], f"#3889: the old open invoice is found: {[x['number'] for x in j['data']][:5]}")
check(j["next_cursor"] is None, "#3889: one page, no cursor")
check(len(docs("kind=invoice")["data"]) == 500, "without open: 500 as ever")

# ---- the meaning of open stays for the other kinds
doc("credit", "CR-1", "issued", "2002-01-01")
doc("credit", "CR-2", "draft", "2002-01-02")
doc("offer", "OF-1", "sent", "2002-01-03")
doc("offer", "OF-2", "draft", "2002-01-04")
check([x["number"] for x in docs("kind=credit&open=1")["data"]] == ["CR-1"], "#3889: an issued credit note stays open")
check([x["number"] for x in docs("kind=offer&open=1")["data"]] == ["OF-1"], "#3889: a sent quotation stays open")

# ---- pages
seen, cur, pages = [], "", 0
while True:
    j = docs("kind=invoice&limit=200" + (f"&before={cur}" if cur else ""))
    seen += [x["id"] for x in j["data"]]
    pages += 1
    cur = j["next_cursor"]
    if not cur or pages > 5:
        break
check(pages == 3 and len(seen) == 506 and len(set(seen)) == 506, f"#3889: every document once in three pages: {pages}, {len(seen)}, {len(set(seen))}")
check(requests.get(B + "/api/v1/office/docs?kind=invoice&before=nonsense", headers=AH).status_code == 400, "#3889: a bad cursor is refused")
check(len(docs("kind=invoice&limit=9999")["data"]) == 500, "#3889: never more than 500")

# ---- an agent limited to one list
r = Fr.post(B + "/api/lists", json={"name": "Mine"})
L1 = r.json()["id"]
L2 = Fr.post(B + "/api/lists", json={"name": "Other"}).json()["id"]
doc("offer", "IN-1", "draft", "2001-02-02", L1)
for i in range(505):
    doc("offer", f"OUT-{i}", "draft", f"20{10 + i % 16}-03-{1 + i % 28:02d}", L2)
dbx("UPDATE agents SET list_ids=? WHERE user_id=?", (str(L1), AID))
j = docs("kind=offer&status=draft")
nums = [x["number"] for x in j["data"]]
check("IN-1" in nums and not any(n.startswith("OUT-") for n in nums), f"#3889: the agent's list counts before the cut: {nums[:5]}")

sys.exit(kt.done("p2463_a_docs"))
