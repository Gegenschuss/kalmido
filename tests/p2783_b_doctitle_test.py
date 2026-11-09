#!/usr/bin/env python3
# kalmido-suite:
"""2.783.0 B API tests (#4882): a document's title from the area's title pattern (sender, type, date). Invented names and
generated file contents only.
 - the settings: pattern "{Absender} {Typ} {Datum}" and "Title automatically" on by default; a pattern without a placeholder 400
 - a new document whose rule gives sender / type: the title after the pattern, date as DD.MM.YYYY; no sender: no double space
 - a date alone gives no automatic title (the file name stays); "Title automatically" off: the file name stays
 - a title typed by hand (title_manual) stays on "Recognise again"; an old title from before #4882 (title_manual NULL) too;
   an emptied title is free again: "Recognise again" sets the pattern's
 - "Suggest title": GET title-suggest, saved with title_manual false; the undo (the title before, set by hand) back
 - "Apply what was learned" sets the title with the sender it finds, its undo takes it back
 - "Set title from pattern" for the chosen documents (POST /api/docs/bulk title_pattern) and its undo (restore)
 - "Create task" keeps its title "type sender" (the same joining function)
 - freelancer-matrix: files (a person without an organisation: the same run in her private area)
usage: p2783_b_doctitle_test.py <datadir>"""
import os
import sys

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, setup, until

DATA = sys.argv[1]
fresh()
A = setup()
assert A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,docs,files"}).ok
FID, Fr = freelancer(B, A)


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.execute(sql, args)
    c.commit()
    c.close()


def doc(s, ws, name, body):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, f"Schreiben 12.03.2026\nGesamt 123,45 EUR\n{body}\n".encode(), "text/plain"))])
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json()["state"] == "done", 90)
    return nid


def get(s, nid):
    return s.get(B + f"/api/docs/{nid}").json()


def done_at(nid):
    return dbx("SELECT done_at FROM doc_meta WHERE node_id=?", (nid,))[0][0]


def redo(s, nid):
    t0 = done_at(nid)
    assert s.post(B + f"/api/docs/{nid}/redo").ok
    check(until(lambda: get(s, nid)["state"] == "done" and done_at(nid) != t0, 90), f"recognised again {nid}")
    return get(s, nid)


def patch(s, nid, body):
    r = s.patch(B + f"/api/docs/{nid}", json=body)
    check(r.ok, f"PATCH {body} {r.status_code} {r.text[:120]}")
    return r.json() if r.ok else {}


def put(s, ws, body):
    return s.put(B + "/api/docs/settings", json={"ws": ws, **body})


def run(s, ws, who):
    st = s.get(B + f"/api/docs/settings?ws={ws}").json()
    check(st.get("title_pattern") == "{Absender} {Typ} {Datum}" and st.get("title_auto") is True, who + ": the default pattern, on " + str((st.get("title_pattern"), st.get("title_auto"))))
    # a date alone: no automatic title (rules only, nothing learned: no guesses)
    assert put(s, ws, {"levels": {f: "rules" for f in ("sender", "type", "tags", "folder")}}).ok
    d0 = doc(s, ws, "power-a.txt", "Stadtwerke Nord Abschlag")
    x = get(s, d0)
    check(x["title"] == "power-a" and x["title_own"] is False and x["title_manual"] is False, who + ": a date alone gives no title " + repr(x["title"]))
    for body in ({"ws": ws, "kind": "any", "match": "Stadtwerke", "sender": "Stadtwerke Nord", "type": "Bill"},
                 {"ws": ws, "kind": "any", "match": "Gutschrift", "type": "Credit"}):
        r = s.post(B + "/api/docs/rules", json=body)
        check(r.status_code == 201, who + ": rule " + r.text[:120])

    # a new document: sender + type + date after the pattern
    d1 = doc(s, ws, "power-b.txt", "Stadtwerke Nord Jahresrechnung")
    x = get(s, d1)
    check(x["title"] == "Stadtwerke Nord Bill 12.03.2026" and x["title_manual"] is False, who + ": the title after the pattern " + repr(x["title"]))
    check(x["name"] == "power-b.txt", who + ": the file keeps its name " + x["name"])
    # no sender: the empty part goes with its separator (no double space, none in front)
    d2 = doc(s, ws, "credit.txt", "Gutschrift Kundennummer 4")
    x = get(s, d2)
    check(x["title"] == "Credit 12.03.2026", who + ": no sender, no double space " + repr(x["title"]))

    # "Apply what was learned": the title comes with the sender the rule finds now; its undo takes it back
    j = s.post(B + "/api/docs/apply-learned", json={"ids": [d0]}).json()
    x = get(s, d0)
    check(x["title"] == "Stadtwerke Nord Bill 12.03.2026" and x["title_manual"] is False, who + ": apply what was learned sets the title " + repr(x["title"]))
    u = s.post(B + "/api/docs/apply-learned", json={"ids": [d0], "undo": True, "run": j.get("run")}).json()
    x = get(s, d0)
    check(u.get("back") == 1 and x["title"] == "power-a" and x["title_own"] is False, who + ": its undo takes the title back " + repr(x["title"]))

    # a title typed by hand stays on "Recognise again"
    x = patch(s, d1, {"title": "Strom 2031"})
    check(x.get("title_manual") is True, who + ": typed = set by hand")
    x = redo(s, d1)
    check(x["title"] == "Strom 2031" and x["title_manual"] is True, who + ": recognise again keeps the hand title " + repr(x["title"]))
    # an old title (from before #4882: title_manual NULL) counts as set by hand
    dbw("UPDATE doc_meta SET title='Alter Titel', title_manual=NULL WHERE node_id=?", (d2,))
    check(get(s, d2)["title_manual"] is True, who + ": an old title counts as set by hand")
    x = redo(s, d2)
    check(x["title"] == "Alter Titel", who + ": an old document is not rewritten " + repr(x["title"]))
    # emptied = free again: the next recognition sets the pattern's title
    x = patch(s, d2, {"title": ""})
    check(x.get("title_manual") is False and x.get("title") == "credit", who + ": emptied: the file name's, free again " + repr(x.get("title")))
    x = redo(s, d2)
    check(x["title"] == "Credit 12.03.2026", who + ": then recognise again sets the pattern's " + repr(x["title"]))

    # "Suggest title": the pattern once, over the hand title; the undo brings the hand title back (still set by hand)
    r = s.get(B + f"/api/docs/{d1}/title-suggest")
    check(r.ok and r.json().get("title") == "Stadtwerke Nord Bill 12.03.2026", who + ": suggest " + r.text[:120])
    x = patch(s, d1, {"title": r.json().get("title"), "title_manual": False})
    check(x.get("title") == "Stadtwerke Nord Bill 12.03.2026" and x.get("title_manual") is False, who + ": the suggestion saved, not by hand")
    x = patch(s, d1, {"title": "Strom 2031", "title_manual": True})
    check(x.get("title") == "Strom 2031" and x.get("title_manual") is True, who + ": undo: the hand title back")
    x = redo(s, d1)
    check(x["title"] == "Strom 2031", who + ": ... and it stays on recognise again " + repr(x["title"]))

    # "Set title from pattern" for the chosen documents, one undo step
    patch(s, d2, {"title": "Gutschrift Hand"})
    r = s.post(B + "/api/docs/bulk", json={"ids": [d1, d2], "title_pattern": True})
    j = r.json() if r.ok else {}
    check(r.ok and sorted(j.get("changed") or []) == sorted([d1, d2]), who + ": bulk title " + r.text[:160])
    a, b = get(s, d1), get(s, d2)
    check(a["title"] == "Stadtwerke Nord Bill 12.03.2026" and b["title"] == "Credit 12.03.2026" and not a["title_manual"] and not b["title_manual"],
          who + ": both after the pattern " + repr((a["title"], b["title"])))
    check(all(set(x) == {"id", "title", "title_manual"} for x in j.get("before") or [{}]), who + ": the undo carries the title only " + str(j.get("before")))
    r = s.post(B + "/api/docs/bulk", json={"restore": j.get("before")})
    a, b = get(s, d1), get(s, d2)
    check(r.ok and a["title"] == "Strom 2031" and b["title"] == "Gutschrift Hand" and a["title_manual"] and b["title_manual"],
          who + ": bulk undo: the hand titles back " + repr((a["title"], b["title"])))
    check(name_of(a, "sender") == "Stadtwerke Nord" and a["auto"].get("sender") == "rule", who + ": the undo leaves the sender's mark " + str(a["auto"]))

    # the pattern: own order and separators; a pattern without a placeholder is refused
    r = put(s, ws, {"title_pattern": "nothing here"})
    check(r.status_code == 400, who + ": a pattern without a placeholder 400 " + str(r.status_code))
    r = put(s, ws, {"title_pattern": "{Datum} - {Typ} - {Absender}"})
    check(r.ok and r.json().get("title_pattern") == "{Datum} - {Typ} - {Absender}", who + ": own pattern " + r.text[:120])
    d3 = doc(s, ws, "credit-2.txt", "Gutschrift Kundennummer 5")
    check(get(s, d3)["title"] == "12.03.2026 - Credit", who + ": own pattern, the empty sender with its dash gone " + repr(get(s, d3)["title"]))
    # "Title automatically" off: a new document keeps the file name; "Suggest title" still works
    assert put(s, ws, {"title_auto": False, "title_pattern": ""}).ok
    st = s.get(B + f"/api/docs/settings?ws={ws}").json()
    check(st["title_auto"] is False and st["title_pattern"] == "{Absender} {Typ} {Datum}", who + ": off, empty pattern = the default")
    d4 = doc(s, ws, "power-c.txt", "Stadtwerke Nord Mahnung")
    check(get(s, d4)["title"] == "power-c", who + ": off: the file name stays " + repr(get(s, d4)["title"]))
    check(s.get(B + f"/api/docs/{d4}/title-suggest").json().get("title") == "Stadtwerke Nord Bill 12.03.2026", who + ": suggest while off")
    assert put(s, ws, {"title_auto": True}).ok

    # "Create task" keeps its title (type + sender, "Pay:" with an amount)
    r = s.post(B + f"/api/docs/{d4}/task")
    check(r.status_code == 201 and r.json().get("title") in ("Bill Stadtwerke Nord", "Pay: Bill Stadtwerke Nord"), who + ": task title " + r.text[:120])


def name_of(d, f):
    return (d.get(f) or {}).get("name")


run(A, "private", "alice")
run(Fr, "private", "freelancer")
check(Fr.get(B + f"/api/docs/{dbx('SELECT MIN(node_id) FROM doc_meta')[0][0]}/title-suggest").status_code in (403, 404), "another person's document: no suggestion")
sys.exit(done("p2783_b_doctitle"))
