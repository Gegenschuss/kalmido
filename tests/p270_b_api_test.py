#!/usr/bin/env python3
"""2.70.0 API tests (part B): #1357 tidy up contacts -- an agent proposes duplicates, the person merges them.
 - the request (POST /api/proposals {agent_id, kind: merge, book_id}): only an address book the person may change (read
   only 403, a stranger's 404), the event job_request carries id, name parts, company, e-mails and phones of THIS book's
   contacts and nothing else (no notes, addresses, birthdays, no other book); an agent of another organisation, one limited
   to selected lists, or an organisation's book for an agent outside it: 403; more than 2000 contacts 400
 - the proposal (POST /api/v1/agent/jobs/{id}/proposal {groups: [{target_id, ids, reason}]}): unknown / foreign ids, an
   id twice, a target outside its group, a group of one, too long a reason, unknown fields 400; a valid one 201
 - review: the groups come with their contacts loaded fresh (a contact changed or deleted since: the group is not ok),
   the input is not sent back; another person 404; the agent cannot apply its own proposal, the contact routes stay
   refused for agents
 - apply with a selection and another target: the ticked group is merged (task link moved, history names the agent), the
   unticked one stays, a changed group is skipped; apply twice 409; undo restores everything (one step), redo merges again
 - discard tells the agent; a freelancer without an organisation can do all of it with a private book
usage: p270_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,collab,comments,events,contacts,clients,family"


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else c.execute(sql, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


class Api:
    def __init__(self, tok):
        self.tok = tok
        self.h = {"Authorization": "Bearer " + tok}

    def get(self, p, **k):
        return requests.get(V + p, headers=self.h, timeout=30, **k)

    def post(self, p, **k):
        return requests.post(V + p, headers=self.h, timeout=30, **k)


def events(cl, kind):
    return [e for e in cl.get("/agent/events", params={"since": 0, "limit": 500}).json()["data"] if e["event"] == kind]


def contact(s, bid, given, family, **kw):
    r = s.post(B + "/api/contacts", json={"book_id": bid, "given": given, "family": family, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def agent(name, **patch):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": name, "display_name": name.title()})
    assert r.status_code in (200, 201), r.text
    aid = r.json()["id"]
    check(A.patch(B + f"/api/admin/agents/{aid}", json={"proposals": "all", **patch}).ok, f"setup: agent {name} " + str(patch))
    return aid, Api(r.json()["token"])


def ask(s, aid, bid, **kw):
    return s.post(B + "/api/proposals", json={"kind": "merge", "agent_id": aid, "book_id": bid, **kw})


def job_input(cl, jid):
    ev = [e for e in events(cl, "job_request") if e["data"]["job"]["id"] == jid]
    return ev[-1]["data"]["input"] if ev else {}


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "eve"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALPHA = A.post(B + "/api/admin/orgs", json={"name": "Alpha"}).json()["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta"}).json()["id"]
A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [1, ids["bob"], ids["carol"]], "admins": [1]})
A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [1], "admins": [1]})
S = {u: sess(u) for u in ("bob", "carol", "eve")}
Bo, Ca, Ev = S["bob"], S["carol"], S["eve"]
for s in (A, Bo, Ca, Ev):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})

AG, cl = agent("tidy", org_id=None)               # a private agent (no organisation)
AGA, cla = agent("alphabot", org_id=ALPHA)        # an agent of Alpha
AGB, clb = agent("betabot", org_id=BETA)          # an agent of Beta
AGL, cll = agent("listbot", org_id=None)          # limited to one list
LL = A.post(B + "/api/lists", json={"name": "Only this"}).json()["id"]
check(A.patch(B + f"/api/admin/agents/{AGL}", json={"list_ids": [LL]}).ok, "setup: listbot limited to one list")

# ---- bob's private book (carol reads it), his book in Alpha's workspace
r = Bo.post(B + "/api/books", json={"name": "Bob private", "org_id": None})
assert r.status_code == 201, r.text
BK = r.json()["id"]
check(Bo.put(B + f"/api/books/{BK}/members", json={"user_id": ids["carol"], "role": "view"}).ok, "setup: carol reads the book")
C1 = contact(Bo, BK, "Erika", "Muster", phones=[{"value": "+49 30 111"}], emails=[{"value": "erika@example.com"}],
             note="secret note", bday="1980-05-12", addresses=[{"street": "Hidden street 1", "city": "Town"}])
C2 = contact(Bo, BK, "Erika", "Mustermann", org="Acme", emails=[{"value": "ERIKA@example.com"}, {"value": "e.m@example.com"}])
C3 = contact(Bo, BK, "Max", "Beispiel", emails=[{"value": "max@example.com"}])
C4 = contact(Bo, BK, "M.", "Beispiel", phones=[{"value": "+49 170 555"}])
C5 = contact(Bo, BK, "Other", "Person")
C6 = contact(Bo, BK, "Other", "Persson")
r = Bo.post(B + "/api/books", json={"name": "Bob in Alpha", "org_id": ALPHA})
assert r.status_code == 201, r.text
OBK = r.json()["id"]
O1 = contact(Bo, OBK, "Team", "Contact", emails=[{"value": "team@example.com"}])
O2 = contact(Bo, OBK, "Team", "Kontakt", emails=[{"value": "team@example.com"}])
T1 = Bo.post(B + "/api/tasks", json={"title": "Call Erika"}).json()["id"]
check(Bo.post(B + f"/api/tasks/{T1}/contacts", json={"contact_id": C1, "kind": "about"}).ok, "setup: task link to C1")

# ================================================================== the request
check(ask(Bo, AG, BK, nope=1).status_code == 400, "request with an unknown field: 400")
check(ask(Ca, AG, BK).status_code == 403, "read-only book: 403")
check(ask(Ev, AG, BK).status_code == 404, "a stranger's book: 404")
check(ask(Bo, AG, 999999).status_code == 404, "unknown book: 404")
r = ask(Bo, AGB, OBK)
check(r.status_code == 403, f"Alpha's book to Beta's agent: 403 ({r.status_code})")
r = ask(Bo, AG, OBK)
check(r.status_code == 403, f"an organisation's book to an agent without organisation: 403 ({r.status_code})")
r = ask(Bo, AGL, BK)
check(r.status_code == 403, f"an agent limited to selected lists: 403 ({r.status_code})")
check(not events(clb, "job_request") and not events(cll, "job_request"), "refused requests reach no agent")
r = ask(Bo, AGA, OBK)
check(r.status_code == 201, f"Alpha's book to Alpha's agent: 201 ({r.status_code} {r.text[:200]})")
inp = job_input(cla, r.json()["id"]) if r.ok else {}
check(sorted(x["id"] for x in inp.get("contacts", [])) == sorted([O1, O2]), "the org book's input has only its contacts")

r = ask(Bo, AG, BK)
check(r.status_code == 201, f"request: 201 ({r.status_code} {r.text[:200]})")
J = r.json()["id"]
inp = job_input(cl, J)
cs = inp.get("contacts", [])
check(sorted(x["id"] for x in cs) == sorted([C1, C2, C3, C4, C5, C6]), "input: the six contacts of this book, no other book")
check(all(set(x) == {"id", "fn", "given", "family", "org", "emails", "phones"} for x in cs), "input: only the allowed fields")
raw = json.dumps(inp)
check("secret note" not in raw and "Hidden street" not in raw and "1980" not in raw and "team@example.com" not in raw,
      "input: no note, address, birthday, nothing of another book")
e1 = next((x for x in cs if x["id"] == C1), {})
check(e1.get("emails") == ["erika@example.com"] and e1.get("phones") == ["+49 30 111"] and e1.get("given") == "Erika", "input: e-mails / phones as values")
check(inp.get("book", {}).get("id") == BK and inp.get("limits", {}).get("contacts_max") == 2000, "input: book + limits")

# ================================================================== the proposal
GOOD = {"kind": "merge", "summary": "Two pairs look alike",
        "groups": [{"target_id": C1, "ids": [C1, C2], "reason": "Same e-mail address"},
                   {"target_id": C3, "ids": [C3, C4], "reason": "Same family name, initial"},
                   {"target_id": C5, "ids": [C5, C6], "reason": "Spelling variant"}]}


def bad(groups, what, **extra):
    r = cl.post(f"/agent/jobs/{J}/proposal", json={"kind": "merge", "groups": groups, **extra})
    check(r.status_code == 400, f"invalid proposal ({what}): 400 ({r.status_code} {r.text[:120]})")


bad([{"target_id": C1, "ids": [C1, 999999]}], "an unknown id")
bad([{"target_id": O1, "ids": [O1, C1]}], "an id of another book")
bad([{"target_id": C1, "ids": [C1, C2]}, {"target_id": C3, "ids": [C3, C2]}], "an id in two groups")
bad([{"target_id": C3, "ids": [C1, C2]}], "a target outside its group")
bad([{"target_id": C1, "ids": [C1]}], "a group of one")
bad([{"target_id": C1, "ids": [C1, C1]}], "an id twice in a group")
bad([{"target_id": C1, "ids": [C1, C2], "reason": "x" * 301}], "too long a reason")
bad([{"target_id": C1, "ids": [C1, C2], "nope": 1}], "an unknown field in a group")
bad([{"target_id": C1, "ids": list(range(1, 12))}], "more than ten in a group")
bad(None, "no groups field")
bad([{"target_id": C1, "ids": [C1, C2]}], "an unknown field", nope=1)
r = cl.post(f"/agent/jobs/{J}/proposal", json={"groups": []})
check(r.status_code == 201 and Bo.get(B + f"/api/proposals/{J}").json().get("dup_groups") == [], "no duplicates found: an empty proposal 201")
r = cl.post(f"/agent/jobs/{J}/proposal", json=GOOD)
check(r.status_code == 201, f"valid proposal: 201 ({r.status_code} {r.text[:200]})")

# ================================================================== review
v = Bo.get(B + f"/api/proposals/{J}").json()
gs = v.get("dup_groups") or []
check(v.get("state") == "ready" and len(gs) == 3 and all(g["ok"] for g in gs), "review: three groups, all fine")
check("contacts" not in (v.get("input") or {}) and v.get("input", {}).get("count") == 6, "review: the input is not sent back")
check([x["id"] for x in gs[0]["contacts"]] == [C1, C2] and gs[0]["contacts"][1]["emails"] == ["ERIKA@example.com", "e.m@example.com"],
      "review: the contacts loaded fresh")
check(Ca.get(B + f"/api/proposals/{J}").status_code == 404, "review: another person 404")
check(Bo.patch(B + f"/api/contacts/{C5}", json={"given": "Otto"}).ok, "setup: C5 renamed meanwhile")
v = Bo.get(B + f"/api/proposals/{J}").json()
g2 = (v.get("dup_groups") or [{}] * 3)[2]
check(g2.get("ok") is False and g2["contacts"][0]["state"] == "changed", "review: a changed contact greys its group out")

# the agent cannot apply, the contact routes stay refused for agents
hdr = {"Authorization": "Bearer " + cl.tok, "X-Requested-With": "kalmido"}
r = requests.post(B + f"/api/proposals/{J}/apply", headers=hdr, json={"select": ["0"]})
check(r.status_code in (401, 403, 404), f"the agent cannot apply its own proposal ({r.status_code})")
r = requests.post(B + "/api/proposals", headers=hdr, json={"kind": "merge", "agent_id": AG, "book_id": BK})
check(r.status_code in (401, 403, 404), f"the agent cannot ask for itself ({r.status_code})")
for m, p, b in (("GET", f"/api/contacts/{C1}", None), ("GET", "/api/contacts", None), ("POST", "/api/contacts/merge", {"target": C1, "ids": [C2]})):
    r = requests.request(m, B + p, headers=hdr, json=b)
    check(r.status_code in (401, 403, 404), f"agent on {m} {p}: refused ({r.status_code})")
check(Ca.post(B + f"/api/proposals/{J}/apply", json={"select": ["0"]}).status_code == 404, "another person cannot apply")

# ================================================================== apply: group 0 into C2, group 2 changed (skipped), group 1 not ticked
r = Bo.post(B + f"/api/proposals/{J}/apply", json={"select": ["0"], "edits": {"0": {"target_id": C3}}})
check(r.status_code == 400, f"a target outside the group: 400 ({r.status_code})")
r = Bo.post(B + f"/api/proposals/{J}/apply", json={"select": ["2"]})
check(r.status_code == 409, f"only a changed group: 409, nothing merged ({r.status_code})")
r = Bo.post(B + f"/api/proposals/{J}/apply", json={"select": ["0", "2"], "edits": {"0": {"target_id": C2}}})
check(r.status_code == 200 and r.json().get("merged") == 1 and r.json().get("skipped") == 1, f"apply: 1 merged, 1 skipped ({r.status_code} {r.text[:200]})")
check(not dbx("SELECT 1 FROM contacts WHERE id=?", (C1,)) and dbx("SELECT 1 FROM contacts WHERE id=?", (C2,)), "C1 merged into C2")
check([x[0] for x in dbx("SELECT contact_id FROM contact_tasks WHERE task_id=?", (T1,))] == [C2], "the task link moved to C2")
em = [x["value"].lower() for x in json.loads(dbx("SELECT emails FROM contacts WHERE id=?", (C2,))[0][0])]
check(em.count("erika@example.com") == 1 and "e.m@example.com" in em, "e-mails joined without doubles " + str(em))
check(all(dbx("SELECT 1 FROM contacts WHERE id=?", (x,)) for x in (C3, C4, C5, C6)), "the other groups stay unchanged")
summ = dbx("SELECT summary FROM merge_runs WHERE target_id=? ORDER BY id DESC", (C2,))
sd = summ[0][0] if summ else "{}"
sd = json.loads(sd) if isinstance(sd, str) else sd
check((sd.get("proposal") or {}).get("agent") == "Tidy" and (sd.get("proposal") or {}).get("job") == J, "the history names the agent's proposal")
card = Bo.get(B + f"/api/contacts/{C2}").json()
check(any((m.get("summary") or {}).get("proposal") for m in card.get("merges") or []), "the card's history shows it")
ap = [e for e in events(cl, "job") if e["data"]["job"]["id"] == J]
check(ap and ap[-1]["data"]["proposal"]["state"] == "applied" and ap[-1]["data"]["proposal"].get("merged") == 1, "the agent hears: applied")
check(Bo.post(B + f"/api/proposals/{J}/apply", json={"select": ["0"]}).status_code == 409, "apply twice: 409")

# ================================================================== undo / redo
check(Ca.post(B + f"/api/proposals/{J}/undo").status_code == 404, "another person cannot undo")
r = Bo.post(B + f"/api/proposals/{J}/undo")
check(r.ok and r.json().get("undone") == 1, f"undo: one merge back ({r.status_code} {r.text[:200]})")
check(dbx("SELECT fn FROM contacts WHERE id=?", (C1,)) and [x[0] for x in dbx("SELECT contact_id FROM contact_tasks WHERE task_id=?", (T1,))] == [C1],
      "undo: C1 is back with its task link")
em = [x["value"] for x in json.loads(dbx("SELECT emails FROM contacts WHERE id=?", (C2,))[0][0])]
check(em == ["ERIKA@example.com", "e.m@example.com"], "undo: C2 as before " + str(em))
check(Bo.post(B + f"/api/proposals/{J}/undo").status_code == 409, "undo twice: 409")
r = Bo.post(B + f"/api/proposals/{J}/redo")
check(r.ok and r.json().get("redone") == 1 and not dbx("SELECT 1 FROM contacts WHERE id=?", (C1,)), f"redo merges again ({r.status_code} {r.text[:200]})")
r = Bo.post(B + f"/api/proposals/{J}/undo")
check(r.ok and dbx("SELECT 1 FROM contacts WHERE id=?", (C1,)), "undo after redo: C1 back")

# ================================================================== a contact deleted meanwhile, discard
r = ask(Bo, AG, BK)
J2 = r.json()["id"] if r.ok else 0
check(cl.post(f"/agent/jobs/{J2}/proposal", json={"groups": [{"target_id": C3, "ids": [C3, C4]}, {"target_id": C1, "ids": [C1, C2]}]}).status_code == 201,
      "second proposal: 201")
check(Bo.delete(B + f"/api/contacts/{C4}").ok, "setup: C4 deleted meanwhile")
v = Bo.get(B + f"/api/proposals/{J2}").json()
g0 = (v.get("dup_groups") or [{}])[0]
check(g0.get("ok") is False and any(x["state"] == "gone" for x in g0.get("contacts", [])), "review: a deleted contact = gone")
check(Bo.post(B + f"/api/proposals/{J2}/discard").ok, "discard")
check(any(e["data"]["job"]["id"] == J2 and e["data"]["proposal"]["state"] == "discarded" for e in events(cl, "job")), "the agent hears: discarded")
check(dbx("SELECT 1 FROM contacts WHERE id=?", (C1,)) and dbx("SELECT 1 FROM contacts WHERE id=?", (C3,)), "discard changes nothing")

# ================================================================== a freelancer without an organisation, private book
r = Ev.post(B + "/api/books", json={"name": "Eve's contacts", "org_id": None})
check(r.status_code == 201, "freelancer: own book")
EB = r.json()["id"]
E1 = contact(Ev, EB, "Client", "One", emails=[{"value": "c1@example.com"}])
E2 = contact(Ev, EB, "Client", "1", emails=[{"value": "C1@example.com"}])
r = ask(Ev, AG, EB)
check(r.status_code == 201, f"freelancer: request 201 ({r.status_code} {r.text[:200]})")
J3 = r.json()["id"] if r.ok else 0
check(sorted(x["id"] for x in job_input(cl, J3).get("contacts", [])) == sorted([E1, E2]), "freelancer: input = her book only")
check(cl.post(f"/agent/jobs/{J3}/proposal", json={"groups": [{"target_id": E1, "ids": [E1, E2], "reason": "Same e-mail"}]}).status_code == 201,
      "freelancer: proposal 201")
r = Ev.post(B + f"/api/proposals/{J3}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("merged") == 1 and not dbx("SELECT 1 FROM contacts WHERE id=?", (E2,)), f"freelancer: applied ({r.status_code} {r.text[:200]})")
r = Ev.post(B + f"/api/proposals/{J3}/undo")
check(r.ok and dbx("SELECT 1 FROM contacts WHERE id=?", (E2,)), "freelancer: undo")

# ================================================================== more than 2000 contacts
r = Bo.post(B + "/api/books", json={"name": "Big", "org_id": None})
BIG = r.json()["id"]
dbx("INSERT INTO contacts(book_id,uid,href,fn,created_at,updated_at) SELECT ?, 'u' || g, 'h' || g || '.vcf', 'N' || g, '2026-01-01T00:00:00Z', "
    "'2026-01-01T00:00:00Z' FROM generate_series(1, 2001) g", (BIG,), write=True)
r = ask(Bo, AG, BIG)
check(r.status_code == 400 and "2000" in r.text, f"more than 2000 contacts: 400 with a hint ({r.status_code} {r.text[:160]})")

print(f"p270_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
