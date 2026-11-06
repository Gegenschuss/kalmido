#!/usr/bin/env python3
# kalmido-suite:
"""2.607.0 C API tests (#4872): "Apply what was learned" on documents (POST /api/docs/apply-learned) and "Recognise again"
adding tags. Invented names and generated file contents only.
 - only the sorting with the stored text: no new recognition (state, method, text, done_at, archive number, date and amount
   stay), empty sender / type / folder are filled by a rule, a value set by hand stays, a tag set by hand stays and the new
   tag comes along; an automatic value is found anew when the rule changes; nothing new = nothing changed
 - one undo step for every part (the run token): the values, the folder and the marks come back, a value changed since stays
 - a document the recognition still works on is skipped; a view-only document is counted (denied), a stranger's is left out
 - "Recognise again" keeps the tags set by hand and adds the rule's tag (was: the tags were fixed as a whole)
 - freelancer-matrix: files (a person without an organisation: apply, undo, recognise again)
usage: p2607_c_learn_api_test.py <datadir>"""
import os
import sys

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, setup, until

DATA = sys.argv[1]
fresh()
A = setup()
r = A.post(B + "/api/orgs", json={"name": "Alpha"})
assert r.ok, r.text
ORG = r.json()["id"]
uid = {"alice": 1}
for u, orgs in (("bob", [ORG]), ("carol", [])):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,docs,files"}).ok
FID, Fr = freelancer(B, A)


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.execute(sql, args)
    c.commit()
    c.close()


def doc(s, ws, name, body):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, f"Rechnung 12.03.2031\nGesamt 123,45 EUR\n{body}\n".encode(), "text/plain"))])
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json()["state"] == "done", 90)
    return nid


def get(s, nid):
    return s.get(B + f"/api/docs/{nid}").json()


def tags(s, nid):
    return {t["name"]: t["auto"] for t in get(s, nid)["tags"]}


def name(d, f):
    return (d.get(f) or {}).get("name")


def learn(s, ids, **kw):
    r = s.post(B + "/api/docs/apply-learned", json={"ids": ids, **kw})
    check(r.ok, f"apply-learned {r.status_code} {r.text[:160]}")
    return r.json() if r.ok else {}


def raw(nid):
    return dbx("SELECT state, method, text, done_at, asn, doc_date, amount, redo_prev, tries FROM doc_meta WHERE node_id=?", (nid,))[0]


def run(s, ws, who):
    # the rules only (what was learned would make the checks depend on the models' guesses); the rule comes AFTER the uploads
    assert s.put(B + "/api/docs/settings", json={"ws": ws, "levels": {f: "rules" for f in ("sender", "type", "tags", "folder")}}).ok
    d1 = doc(s, ws, "power-a.txt", "Stadtwerke Nord Abschlag")
    d2 = doc(s, ws, "power-b.txt", "Stadtwerke Nord Jahresrechnung")
    check(get(s, d1)["sender"] is None, who + ": no sender before the rule")
    assert s.patch(B + f"/api/docs/{d1}", json={"type": "Letter", "tags": ["Mine"]}).ok          # by hand
    assert s.patch(B + f"/api/docs/{d2}", json={"sender": "Hand Sender", "date": "2031-01-02"}).ok  # by hand
    r = s.post(B + "/api/docs/rules", json={"ws": ws, "kind": "any", "match": "Stadtwerke", "sender": "Stadtwerke Nord",
                                            "type": "Bill", "tags": ["Energy"], "folder": "Utilities"})
    check(r.status_code == 201, who + ": rule " + r.text[:120])
    rid = r.json().get("id")
    before = {n: raw(n) for n in (d1, d2)}
    x1, x2 = get(s, d1), get(s, d2)
    j = learn(s, [d1, d2])
    check(j.get("set") == 2 and sorted(j.get("changed") or []) == sorted([d1, d2]) and j.get("run"), who + ": two sorted " + str(j))
    for n in (d1, d2):  # no recognition run: the stored text, state, method, archive number, date, amount stay
        check(raw(n) == before[n], f"{who}: no new recognition on {n}: {raw(n)[:2]} vs {before[n][:2]}")
    a, b = get(s, d1), get(s, d2)
    check(name(a, "sender") == "Stadtwerke Nord" and a["auto"].get("sender") == "rule", who + ": empty sender filled " + str(a["sender"]))
    check(name(a, "type") == "Letter", who + ": the type set by hand stays " + str(a["type"]))
    check(tags(s, d1) == {"Mine": "", "Energy": "rule"}, who + ": the tag set by hand stays, the rule's comes along " + str(tags(s, d1)))
    check(name(a, "folder") == "Utilities", who + ": empty folder filled " + str(a["folder"]))
    check(name(b, "sender") == "Hand Sender" and name(b, "type") == "Bill", who + ": hand sender stays, empty type filled " + str((b["sender"], b["type"])))
    check(b["date"] == "2031-01-02" and a["date"] == x1["date"] and a["amount"] == x1["amount"], who + ": date / amount stay")
    check(a["asn"] == x1["asn"] and b["asn"] == x2["asn"], who + ": no new archive number")
    j2 = learn(s, [d1, d2])
    check(j2.get("changed") == [] and j2.get("set") == 0, who + ": the same again = nothing new " + str(j2))

    # undo: one step for both (the run token), the folder back, the marks back
    u = learn(s, [d1, d2], undo=True, run=j["run"])
    check(u.get("back") == 2, who + ": both back " + str(u))
    a, b = get(s, d1), get(s, d2)
    check(a["sender"] is None and "sender" not in a["auto"] and tags(s, d1) == {"Mine": ""}, who + ": undo: sender and tag off " + str((a["sender"], tags(s, d1))))
    check(a["folder"] is None and a["parent_id"] == x1["parent_id"], who + ": undo: back in its folder " + str((a["folder"], a["parent_id"], x1["parent_id"])))
    check(b["type"] is None and name(b, "sender") == "Hand Sender", who + ": undo: type off, hand sender stays")
    check(learn(s, [d1], undo=True, run=j["run"]).get("back") == 0, who + ": a second undo does nothing")

    # an automatic value is found anew; a value changed by hand since the sorting stays on the undo
    j = learn(s, [d1])
    check(j.get("set") == 1, who + ": sorted again " + str(j))
    assert s.patch(B + f"/api/docs/rules/{rid}", json={"kind": "any", "match": "Stadtwerke", "sender": "Stadtwerke Sued", "tags": ["Energy"]}).ok
    j = learn(s, [d1])
    check(name(get(s, d1), "sender") == "Stadtwerke Sued" and j.get("set") == 1, who + ": the automatic sender found anew " + str(get(s, d1)["sender"]))
    assert s.patch(B + f"/api/docs/{d1}", json={"sender": "Typed Later"}).ok
    learn(s, [d1], undo=True, run=j["run"])
    check(name(get(s, d1), "sender") == "Typed Later", who + ": undo keeps a value set since")

    # the recognition still works on it: skipped, nothing written
    dbw("UPDATE doc_meta SET state='run' WHERE node_id=?", (d2,))
    j = learn(s, [d2])
    check(j.get("skipped") == 1 and j.get("changed") == [], who + ": a running recognition is skipped " + str(j))
    dbw("UPDATE doc_meta SET state='done' WHERE node_id=?", (d2,))

    # 2.607.0 (#4872): "Recognise again" adds the rule's tag to the one set by hand (was: tags fixed as a whole); hand type stays
    d3 = doc(s, ws, "power-c.txt", "Stadtwerke Nord Mahnung")
    assert s.patch(B + f"/api/docs/{d3}", json={"tags": ["Mine"], "type": "Letter", "sender": ""}).ok
    t0 = raw(d3)[3]
    assert s.post(B + f"/api/docs/{d3}/redo").ok
    until(lambda: get(s, d3)["state"] == "done" and raw(d3)[3] != t0, 90)
    c = get(s, d3)
    check(tags(s, d3) == {"Mine": "", "Energy": "rule"}, who + ": recognise again adds the tag " + str(tags(s, d3)))
    check(name(c, "type") == "Letter", who + ": recognise again keeps the hand type " + str(c["type"]))
    check(name(c, "sender") == "Stadtwerke Sued", who + ": recognise again fills the empty sender " + str(c["sender"]))
    return d1


N1 = run(Fr, "private", "freelancer")
j = learn(Ca, [N1])
check(j.get("changed") == [] and j.get("denied") == 0 and j.get("skipped") == 0, "tenant: a stranger's document is left out " + str(j))
check(Ca.post(B + "/api/docs/apply-learned", json={"ids": []}).status_code == 400, "no ids: 400")
check(Ca.post(B + "/api/docs/apply-learned", json={"ids": [N1], "undo": True}).status_code == 400, "undo without run: 400")
run(A, f"org:{ORG}", "org")
# a document Bob may only view: counted, not changed
P = doc(A, "private", "view-only.txt", "Stadtwerke Nord")
r = A.post(B + f"/api/files/nodes/{P}/shares", json={"user_id": uid["bob"], "role": "view"})
check(r.ok, "share view-only " + r.text[:120])
assert A.post(B + "/api/docs/rules", json={"ws": "private", "kind": "any", "match": "Stadtwerke", "sender": "Stadtwerke Nord"}).status_code == 201
j = learn(Bo, [P])
check(j.get("denied") == 1 and j.get("changed") == [] and get(A, P)["sender"] is None, "view-only: denied, unchanged " + str(j))
done("p2607_c_learn_api")
