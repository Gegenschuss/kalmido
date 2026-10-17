#!/usr/bin/env python3
"""2.66.0 API tests (part A).
 - #1835 merging duplicate contacts (POST /api/contacts/merge, POST /api/contacts/merges/{id}/undo): the dry run lists what
   moves and changes nothing; the merge keeps the picked values, joins phones / e-mails (doubles dropped), moves task links
   (a task linked to both stays linked once), event attendances (an event with both lists the target once), the contact
   person of a client; the other contact's birthday task goes to the trash, the target's follows the picked birthday;
   CardDAV sync-collection reports the merged contact as gone (404) and the target as changed; the card shows the history
   (only to who may change it); undo puts everything back (same ids, uid, href, links, birthday task, CardDAV) once;
   a stranger gets 404, read-only 403, a mirrored address book / a group / too many / foreign ids 400, another scope 409;
   undo after the target was deleted brings the merged contacts back; the data export lists the merge without snapshot
usage: p266_a_api_test.py <datadir>"""
import os
import re
import subprocess
import sys
import time

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
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
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def contact(s, bid, given, family, **kw):
    r = s.post(B + "/api/contacts", json={"book_id": bid, "given": given, "family": family, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def merge(s, target, ids, pick=None, dry=False):
    return s.post(B + "/api/contacts/merge", json={"target": target, "ids": ids, "pick": pick or {}, **({"dry": True} if dry else {})})


def links(cid):
    return sorted(r[0] for r in dbx("SELECT task_id FROM contact_tasks WHERE contact_id=?", (cid,)))


def att(eid):
    return sorted(r[0] for r in dbx("SELECT contact_id FROM event_attendees WHERE event_id=?", (eid,)))


def occ_task(cid, kind="birthday"):
    r = dbx("SELECT o.task_id, t.deleted_at, t.due FROM contact_occ o LEFT JOIN tasks t ON t.id=o.task_id WHERE o.contact_id=? AND o.kind=?", (cid, kind))
    return tuple(r[0]) if r else None


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ids = {}
for u in ("bob", "carol", "eve"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code == 201, r.text
ALPHA = r.json()["id"]
A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [1, ids["bob"], ids["carol"]], "admins": [1]})  # carol: visible to bob (a share)
S = {u: sess(u) for u in ("bob", "carol", "eve")}
Bo, Ca, Ev = S["bob"], S["carol"], S["eve"]
for s in (A, Bo, Ca, Ev):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})

# ---- bob's own address book with a birthday list, carol may only read it
r = Bo.post(B + "/api/books", json={"name": "Bob's contacts", "org_id": None})
assert r.status_code == 201, r.text
BK = r.json()["id"]
BL = Bo.post(B + "/api/lists", json={"name": "Birthdays"}).json()["id"]
check(Bo.patch(B + f"/api/books/{BK}", json={"birthdays_list_id": BL}).ok, "setup: the birthday list")
check(Bo.put(B + f"/api/books/{BK}/members", json={"user_id": ids["carol"], "role": "view"}).ok, "setup: carol reads the book")
C1 = contact(Bo, BK, "Erika", "Muster", title="Boss", phones=[{"value": "+49 30 111", "pref": True}], emails=[{"value": "erika@example.com"}],
             bday="1980-05-12")
C2 = contact(Bo, BK, "Erika", "Mustermann", org="Acme", phones=[{"value": "+49 (30) 111", "pref": True}, {"value": "+49 170 222"}],
             emails=[{"value": "ERIKA@example.com"}, {"value": "e.m@example.com"}], bday="1981-06-01")
C3 = contact(Bo, BK, "Other", "Person")
H1, H2 = (dbx("SELECT href, uid FROM contacts WHERE id=?", (x,))[0] for x in (C1, C2))
T1 = Bo.post(B + "/api/tasks", json={"title": "Linked to both"}).json()["id"]
T2 = Bo.post(B + "/api/tasks", json={"title": "Linked to the second"}).json()["id"]
for t, cid in ((T1, C1), (T1, C2), (T2, C2)):
    check(Bo.post(B + f"/api/tasks/{t}/contacts", json={"contact_id": cid, "kind": "about"}).ok, "setup: task link")
D = time.strftime("%Y-%m-%d")
E1 = Bo.post(B + "/api/events", json={"title": "Meeting", "start": f"{D}T10:00", "attendees": [{"contact_id": C2}]}).json()["id"]
E2 = Bo.post(B + "/api/events", json={"title": "Both", "start": f"{D}T12:00", "attendees": [{"contact_id": C1}, {"contact_id": C2}]}).json()["id"]
check(att(E1) == [C2] and att(E2) == sorted([C1, C2]), "setup: event attendees " + str((att(E1), att(E2))))
r = Bo.post(B + "/api/clients", json={"name": "Acme Ltd", "org_id": None, "contacts": [{"name": "Erika Mustermann", "contact_id": C2}]})
check(r.status_code == 201, "setup: a client with the contact person " + r.text[:200])
CL = r.json().get("id")
KP = dbx("SELECT id FROM office_client_contacts WHERE client_id=?", (CL,))[0][0]
check(dbx("SELECT contact_id FROM office_client_contacts WHERE id=?", (KP,))[0][0] == C2, "setup: the contact person is linked to C2")
B1, B2 = occ_task(C1), occ_task(C2)
check(B1 and B2 and B1[1] is None and B2[1] is None, "setup: both have a birthday task " + str((B1, B2)))

# ---- CardDAV: a sync token before the merge
PW = Bo.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]
dav = requests.Session()
dav.auth = ("bob", PW)
SYNC = ('<?xml version="1.0" encoding="utf-8"?><d:sync-collection xmlns:d="DAV:"><d:sync-token>{}</d:sync-token>'
        '<d:sync-level>1</d:sync-level><d:prop><d:getetag/></d:prop></d:sync-collection>')
COLL = B + f"/dav/addressbooks/bob/b{BK}/"


def dsync(tok=""):
    r = dav.request("REPORT", COLL, data=SYNC.format(tok), headers={"Depth": "1", "Content-Type": "application/xml"})
    assert r.status_code == 207, (r.status_code, r.text[:300])
    resp = re.findall(r"<D:response>(.*?)</D:response>", r.text, re.S)
    out = {}
    for x in resp:
        href = re.search(r"<D:href>([^<]+)</D:href>", x).group(1).rsplit("/", 1)[-1]
        out[href] = "404" if "404 Not Found" in x and "getetag" not in x else (re.search(r"getetag[^>]*>([^<]+)<", x) or [None, ""])[1]
    return out, re.search(r"<D:sync-token>([^<]+)</D:sync-token>", r.text).group(1)


st0, TOK = dsync()
check(H1[0] in st0 and H2[0] in st0, "setup: CardDAV lists both cards")

# ================================================================== #1835: rights and refusals
before = dbx("SELECT COUNT(*) FROM merge_runs")[0][0]
check(merge(Ev, C1, [C2], dry=True).status_code == 404, "#1835: a stranger: 404")
check(merge(Ca, C1, [C2], dry=True).status_code == 403, "#1835: read only: 403")
check(merge(Bo, C1, []).status_code == 400, "#1835: one contact alone: 400")
check(merge(Bo, C1, [C2] + list(range(900000, 900010))).status_code == 400, "#1835: more than 10: 400")
check(merge(Bo, C1, [C2], {"family": C3}).status_code == 400, "#1835: a pick outside the merge: 400")
check(merge(Bo, C1, [C2], {"uid": C2}).status_code == 400, "#1835: an unknown pick field: 400")
check(merge(Bo, C1, [999999]).status_code == 404, "#1835: an unknown id: 404")
r = Bo.post(B + "/api/contacts", json={"book_id": BK, "fn": "Team", "kind": "group"})
GR = r.json()["id"]
check(merge(Bo, C1, [GR]).status_code == 400, "#1835: a group: 400")
# an organisation's address book (bob may change it) does not merge with his own book
r = A.post(B + "/api/books", json={"name": "Alpha customers", "org_id": ALPHA})
OB = r.json()["id"]
A.post(B + f"/api/books/{OB}/org", json={"org_role": "edit"})
CO = contact(A, OB, "Erika", "Org")
r = merge(Bo, C1, [CO], dry=True)
check(r.status_code == 409, f"#1835: across the organisation boundary: 409 ({r.status_code} {r.text[:120]})")
# a mirror of an external CardDAV account
SRC = dbx("INSERT INTO contact_srcs(user_id,name,url,created_at) VALUES(?,?,?,?) RETURNING id", (ids["bob"], "Ext", "https://dav.example.com/", "2026-01-01T00:00:00Z"), write=True)[0][0]
r = Bo.post(B + "/api/books", json={"name": "Mirror", "org_id": None})
MB = r.json()["id"]
CM = contact(Bo, MB, "Erika", "Mirror")
dbx("UPDATE books SET src_id=? WHERE id=?", (SRC, MB), write=True)
r = merge(Bo, C1, [CM], dry=True)
check(r.status_code == 400 and "sync" in r.text, f"#1835: a mirrored address book: 400 ({r.status_code} {r.text[:120]})")
check(dbx("SELECT COUNT(*) FROM merge_runs")[0][0] == before, "#1835: no refused merge wrote a run")

# ================================================================== #1835: the dry run
PICK = {"family": C2, "bday": C2}
r = merge(Bo, C1, [C2], PICK, dry=True)
j = r.json() if r.ok else {}
L = j.get("lines", [])
check(r.ok and "Task links: 2" in L and "Event attendances: 2" in L and "Contact person at clients: 1" in L, "#1835: the overview counts the links " + str(L))
check("Phone numbers added: 1" in L and "E-mail addresses added: 1" in L, "#1835: ... and the joined phones / e-mails " + str(L))
check(any("Erika Mustermann" in x and "trash" in x for x in L), "#1835: ... and the birthday task that goes " + str(L))
check(j.get("fields", {}).get("family") == "Mustermann" and "photo" not in j.get("fields", {}), "#1835: the dry run shows the new fields")
check(Bo.get(B + f"/api/contacts/{C2}").ok and links(C2) == sorted([T1, T2]) and att(E1) == [C2] and occ_task(C2)[1] is None
      and dbx("SELECT COUNT(*) FROM merge_runs")[0][0] == before, "#1835: the dry run changed nothing")
r = merge(Bo, C1, [C3], dry=True)
check(r.ok and r.json()["lines"][0] == "No links", "#1835: without links: one line 'No links' " + r.text[:200])

# ================================================================== #1835: the merge
r = merge(Bo, C1, [C2], PICK)
j = r.json() if r.ok else {}
RUN = j.get("run_id")
t = j.get("target", {})
check(r.ok and RUN and t.get("id") == C1, "#1835: merged " + r.text[:200])
check(t.get("family") == "Mustermann" and t.get("bday") == "1981-06-01" and t.get("title") == "Boss" and t.get("org") == "Acme",
      "#1835: picked values, the target's, the first set one " + str({k: t.get(k) for k in ("family", "bday", "title", "org")}))
ph = [x["value"] for x in t.get("phones", [])]
em = [x["value"] for x in t.get("emails", [])]
check(ph == ["+49 30 111", "+49 170 222"] and [x.get("pref") for x in t["phones"]] == [True, False], "#1835: phones joined, the double dropped, one preferred " + str(t.get("phones")))
check(em == ["erika@example.com", "e.m@example.com"], "#1835: e-mails joined (case-insensitive double dropped) " + str(em))
check(Bo.get(B + f"/api/contacts/{C2}").status_code == 404, "#1835: the other contact is gone")
check(links(C1) == sorted([T1, T2]) and links(C2) == [], "#1835: task links moved, the shared task linked once " + str(links(C1)))
check(att(E1) == [C1] and att(E2) == [C1], "#1835: event attendances moved, the event with both lists the target once " + str((att(E1), att(E2))))
check(dbx("SELECT contact_id FROM office_client_contacts WHERE id=?", (KP,))[0][0] == C1, "#1835: the client's contact person points to the target")
b1, b2 = dbx("SELECT deleted_at, due FROM tasks WHERE id=?", (B1[0],))[0], dbx("SELECT deleted_at FROM tasks WHERE id=?", (B2[0],))[0]
check(b2[0] is not None, "#1835: the other contact's birthday task is in the trash")
check(b1[0] is None and b1[1][5:] == "06-01", "#1835: the target's birthday task follows the picked birthday " + str(b1))
m = t.get("merges", [])
check(len(m) == 1 and m[0]["undo"] == "" and m[0]["summary"]["merged"][0]["fn"] == "Erika Mustermann" and m[0]["by_name"] == "Bob",
      "#1835: the card shows the merge in the history " + str(m)[:300])
check("merges" not in Ca.get(B + f"/api/contacts/{C1}").json(), "#1835: read only: no history on the card")
st1, TOK1 = dsync(TOK)
check(st1.get(H2[0]) == "404", "#1835: CardDAV sync reports the merged card as gone " + str(st1))
check(H1[0] in st1 and st1[H1[0]] not in ("404", "") and st1[H1[0]] != st0.get(H1[0]), "#1835: ... and the target as changed (new ETag)")
check(dav.get(COLL + H2[0]).status_code == 404, "#1835: GET of the merged card: 404")
ex = Bo.get(B + "/api/export.json").json()
mr = ex.get("merge_runs", [])
check(len(mr) == 1 and "snapshot" not in mr[0], "#1835: the data export lists the merge without the snapshot")

# ================================================================== #1835: undo
check(Ev.post(B + f"/api/contacts/merges/{RUN}/undo").status_code == 404, "#1835: undo by a stranger: 404")
check(Ca.post(B + f"/api/contacts/merges/{RUN}/undo").status_code == 403, "#1835: undo read only: 403")
check(Bo.post(B + f"/api/contacts/merges/{RUN + 1000}/undo").status_code == 404, "#1835: an unknown run: 404")
r = Bo.post(B + f"/api/contacts/merges/{RUN}/undo")
j = r.json() if r.ok else {}
check(r.ok and j.get("ok") and j.get("restored") == [C2] and j["target"]["id"] == C1, "#1835: undone " + r.text[:200])
c2 = Bo.get(B + f"/api/contacts/{C2}").json()
check(c2.get("id") == C2 and dbx("SELECT href, uid FROM contacts WHERE id=?", (C2,))[0] == H2 and c2.get("org") == "Acme"
      and len(c2.get("phones", [])) == 2, "#1835: the contact is back with its id, uid, href and fields")
t = j.get("target", {})
check(t.get("family") == "Muster" and t.get("bday") == "1980-05-12" and len(t.get("phones", [])) == 1 and len(t.get("emails", [])) == 1
      and t.get("org") == "", "#1835: the target has its old values " + str({k: t.get(k) for k in ("family", "bday", "org")}))
check(links(C1) == [T1] and links(C2) == sorted([T1, T2]), "#1835: task links back " + str((links(C1), links(C2))))
check(att(E1) == [C2] and att(E2) == sorted([C1, C2]), "#1835: event attendances back " + str((att(E1), att(E2))))
check(dbx("SELECT contact_id FROM office_client_contacts WHERE id=?", (KP,))[0][0] == C2, "#1835: the contact person points to C2 again")
check(occ_task(C2) and occ_task(C2)[0] == B2[0] and occ_task(C2)[1] is None, "#1835: the birthday task of C2 is back from the trash " + str(occ_task(C2)))
check(dbx("SELECT due FROM tasks WHERE id=?", (B1[0],))[0][0][5:] == "05-12", "#1835: the target's birthday task has its old date")
st2, _ = dsync(TOK1)
check(st2.get(H2[0]) not in (None, "404", "") and st2.get(H1[0]) not in (None, "404"), "#1835: CardDAV sync sees the card again " + str(st2))
check(Bo.post(B + f"/api/contacts/merges/{RUN}/undo").status_code == 409, "#1835: undo twice: 409")
m = Bo.get(B + f"/api/contacts/{C1}").json().get("merges", [])
check(m and m[0]["undo"] == "undone" and m[0]["undone_at"], "#1835: the history says undone")
check(dbx("SELECT snapshot FROM merge_runs WHERE id=?", (RUN,))[0][0] == "{}", "#1835: the snapshot is emptied after the undo")

# ---- an old merge cannot be undone any more
r = merge(Bo, C1, [C3])
R2 = r.json().get("run_id")
dbx("UPDATE merge_runs SET created_at='2020-01-01T00:00:00Z' WHERE id=?", (R2,), write=True)
r = Bo.post(B + f"/api/contacts/merges/{R2}/undo")
check(r.status_code == 409 and "30" in r.text, "#1835: older than 30 days: 409 " + r.text[:120])
check(Bo.get(B + f"/api/contacts/{C1}").json()["merges"][0]["undo"] == "expired", "#1835: the history says expired")

# ---- undo after the target was deleted: the merged contacts come back
r = merge(Bo, C2, [C1])
R3 = r.json().get("run_id")
check(r.ok and Bo.delete(B + f"/api/contacts/{C2}").ok, "setup: merged into C2, then C2 deleted")
r = Bo.post(B + f"/api/contacts/merges/{R3}/undo")
j = r.json() if r.ok else {}
check(r.ok and j.get("target") is None and j.get("restored") == [C1] and j.get("note"), "#1835: undo without the target " + r.text[:200])
check(Bo.get(B + f"/api/contacts/{C1}").ok and links(C1) == [T1], "#1835: ... C1 is back with its own links " + str(links(C1)))
check(Ev.post(B + f"/api/contacts/merges/{R3}/undo").status_code == 404, "#1835: a stranger still gets 404")

# ---- 2.66.0 review (#1835): private address books of two people never merge (bob may edit carol's book: still 409) --
# before, the contact went into the other person's book and a client contact person's link no longer fitted
r = Ca.post(B + "/api/books", json={"name": "Carol's", "org_id": None})
CBK = r.json()["id"]
check(Ca.put(B + f"/api/books/{CBK}/members", json={"user_id": ids["bob"], "role": "edit"}).ok, "setup: carol shares her book with bob (edit)")
CX = contact(Ca, CBK, "Erika", "Carol")
for tgt, oth in ((CX, C1), (C1, CX)):
    r = merge(Bo, tgt, [oth], dry=True)
    check(r.status_code == 409, f"#1835: private books of two people: 409 ({r.status_code} {r.text[:120]})")
check(Bo.get(B + f"/api/contacts/{C1}").ok and Ca.get(B + f"/api/contacts/{CX}").ok, "#1835: ... both contacts stay")

# ---- 2.66.0 review: an agent token is refused on the merge routes (web only; 2.70.0 (#1357): agents propose, kind merge)
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "ctm-helper", "display_name": "Helper"}).json()
r = requests.post(B + "/api/contacts/merge", headers={"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"},
                  json={"target": C1, "ids": [C3], "dry": True})
check(r.status_code in (401, 403, 404), f"#1835: an agent token cannot merge contacts ({r.status_code})")

# ---- CSRF: without the app's header the write is refused
r = requests.post(B + "/api/contacts/merge", json={"target": C1, "ids": [C3]}, cookies=Bo.cookies)
check(r.status_code in (400, 401, 403), f"#1835: without X-Requested-With: refused ({r.status_code})")

print(f"p266_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
