#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1026.0 (#5280, stage Q6c of the cross-cutting core): one search registry, one route per side. Own container. Invented
names only.
 - acceptance (decision of 09.11.2026): per area a word that stands ONLY in the content of one object is found by the area's
   own search AND by the general search (GET /api/search: the hits / groups the command palette's "Everywhere" shows) --
   tasks (notes), contacts (note), events (description), notes (text), knowledge pages (text), documents (recognised text),
   messages (a comment), bookmarks (note)
 - events are searchable for the first time: a word start of title / place / description, umlauts either way; an invited
   person finds the event as attendee (no calendar), another person not; the index follows a changed description
 - the old routes are gone (no second way): /api/search/messages, /api/files/search, /api/wiki/search, /api/v1/files/search;
   an unknown kind is a 400
 - the API: GET /api/v1/search?kind=all gives only the kinds the token may read (never office), kind=events without the scope
   calendar is a 403 with required_scope, with it the event is found; kind=contacts&trash=1 lists the trash without q
 - the last ILIKE searches: a bookmark is found at a word start, not by a part inside a word (only the site's name takes a part)
freelancer-matrix: search (a person without an organisation finds her own event and contact through the one search; nobody else does)
usage: p21026_a_search_test.py <datadir>"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

V = B + "/api/v1"
D = "2026-12-03"


def everywhere(s, q):
    """The general search as the palette asks it: {'tasks': {ids}, kind: [hits]}."""
    r = s.get(B + "/api/search", params={"q": q, "limit": 8})
    check(r.status_code == 200, f"GET /api/search {q}: {r.status_code} {r.text[:160]}")
    j = r.json() if r.ok else {}
    return {"tasks": {h["task"]["id"] for h in j.get("hits", [])}, **(j.get("groups") or {})}


def ids(hits):
    return {h.get("id") for h in hits or []}


def kind(s, k, q, **kw):
    r = s.get(B + "/api/search", params={"kind": k, "q": q, **kw})
    check(r.status_code == 200, f"GET /api/search?kind={k} {q}: {r.status_code} {r.text[:160]}")
    return r.json() if r.ok else {}


def made(r, what):
    check(r.status_code in (200, 201), f"setup: {what} {r.status_code} {r.text[:160]}")
    return r.json() if r.ok else {}


kt.fresh(prefix="P21026A")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "dora"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    org_join(B, u, ORG)
FID, Fr = freelancer(B, A)
Bo, Do = kt.sess("bob"), kt.sess("dora")
for s in (Bo, Do, Fr):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
st = A.get(B + "/api/state").json()
INBOX = next(x["id"] for x in st["lists"] if x.get("is_inbox"))
LP = made(A.post(B + "/api/lists", json={"name": "Garten"}), "a project")["id"]

# ================================================================== the objects, each with a word only in its content
T1 = made(A.post(B + "/api/tasks", json={"title": "Wochenplan", "list_id": LP, "content": "Brombeerhecke schneiden"}), "a task")["id"]
CT1 = made(A.post(B + "/api/contacts", json={"fn": "Erika Beispiel", "note": "kennt die Pflaumenbaum-Sorten"}), "a contact")
CT1 = (CT1.get("contact") or CT1)["id"]
EV1 = made(A.post(B + "/api/events", json={"title": "Treffen", "start": f"{D}T10:00", "end": f"{D}T11:00", "tz": "Europe/Berlin",
                                             "location": "Fähranleger", "description": "Zitronenfalter beobachten"}), "an event")
EV1 = (EV1.get("event") or EV1)["id"]
N1 = made(A.post(B + f"/api/lists/{LP}/notes", json={"title": "Protokoll", "body": "Rhabarberkuchen für alle"}), "a note")
N1 = (N1.get("note") or N1)["id"]
SP = f"org:{ORG}"
W1 = made(A.post(B + "/api/wiki/pages", json={"space": SP, "path": "Rezepte/Marmelade", "body": "Quittengelee kochen"}), "a page")["id"]
r = A.post(B + "/api/docs", data={"ws": SP}, files=[("files", ("beleg.txt", "Rechnung Holunderblüte Lieferung".encode(), "text/plain"))])
DOC = made(r, "a document")["ids"][0]
until(lambda: A.get(B + f"/api/docs/{DOC}").json().get("state") in ("done", "failed"), 120)
C1 = made(A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Die Stachelbeere ist reif"}), "a comment")
C1 = C1.get("id") or (C1.get("comment") or {}).get("id")
BM = made(A.post(B + "/api/bookmarks", json={"url": "https://example.com/obst", "title": "Obstgarten", "note": "Mirabellenhain im Herbst"}),
          "a bookmark")["bookmark"]["id"]

# ================================================================== acceptance: area search AND general search
r = A.get(B + "/api/tasks", params={"scope": "search", "q": "brombeer", "limit": 50})
check(T1 in {t["id"] for t in r.json().get("tasks", [])}, "tasks: the area search finds the word in the notes")
check(T1 in everywhere(A, "brombeer")["tasks"], "tasks: the general search finds it too")

check(CT1 in {x["id"] for x in A.get(B + "/api/contacts", params={"q": "pflaumenbaum"}).json().get("items", [])},
      "contacts: the area search finds the word in the note")
check(CT1 in ids(kind(A, "contacts", "pflaumenbaum").get("contacts")), "contacts: kind=contacts finds it")
check(CT1 in ids(everywhere(A, "pflaumenbaum").get("contacts")), "contacts: the general search finds it too")

ev = kind(A, "events", "zitronenfalter").get("events") or []
check(EV1 in ids(ev), f"events: kind=events finds the word in the description {ev}")
e1 = next((x for x in ev if x["id"] == EV1), {})
check(e1.get("title") == "Treffen" and e1.get("role") == "owner" and e1.get("cal_id") and "Zitronenfalter" in (e1.get("snippet") or ""),
      f"events: the hit has title, role, calendar and a snippet with the word {e1}")
check(EV1 in ids(everywhere(A, "zitronenfalter").get("events")), "events: the general search finds it too")
check(EV1 in ids(kind(A, "events", "faehranl").get("events")), "events: umlauts either way ('faehranl' finds 'Fähranleger')")
check(EV1 in ids(kind(A, "events", "treff").get("events")), "events: a word start of the title")
check(not ids(kind(A, "events", "itronen").get("events")), "events: no part inside a word")

check(N1 in {n["id"] for n in A.get(B + "/api/notes", params={"q": "rhabarber"}).json().get("notes", [])}, "notes: the area search finds the text")
check(N1 in ids(everywhere(A, "rhabarber").get("notes")), "notes: the general search finds it too")

wk = kind(A, "wiki", "quittengelee")
check(W1 in {p["id"] for p in wk.get("pages", [])}, f"knowledge pages: kind=wiki finds the word in the text {wk}")
gw = everywhere(A, "quittengelee").get("wiki") or []
check(W1 in ids(gw) and any("Quittengelee" in (p.get("snippet") or "") for p in gw),
      f"knowledge pages: the general search finds the text too, with its snippet (was: names only) {gw}")

fs = kind(A, "files", "holunderbl")
check(DOC in {x["id"] for x in fs.get("items", [])}, f"documents: kind=files finds the recognised text {str(fs)[:200]}")
check(DOC in ids(everywhere(A, "holunderbluete").get("files")), "documents: the general search finds it too (ü as ue)")

mm = kind(A, "messages", "stachelbeere")
check(any(h["art"] == "c" and h["id"] == C1 for h in mm.get("hits", [])), f"messages: kind=messages finds the comment {str(mm)[:200]}")
check(any(h["id"] == C1 for h in everywhere(A, "stachelbeere").get("messages") or []), "messages: the general search finds it too")

check(BM in {x["id"] for x in A.get(B + "/api/bookmarks", params={"q": "mirabellen"}).json().get("items", [])},
      "bookmarks: the area search finds the note (word start, no ILIKE)")
check(BM not in {x["id"] for x in A.get(B + "/api/bookmarks", params={"q": "abellen"}).json().get("items", [])},
      "bookmarks: no part inside a word (question 14)")
check(BM in ids(everywhere(A, "mirabellen").get("bookmarks")), "bookmarks: the general search finds it too")

# ================================================================== rights of the events
check(EV1 not in ids(kind(Bo, "events", "zitronenfalter").get("events")), "events: bob does not find alice's private event")
check(EV1 not in ids(everywhere(Bo, "zitronenfalter").get("events")), "... nor in the general search")
EV2 = made(A.post(B + "/api/events", json={"title": "Kranichzug", "start": f"{D}T14:00", "end": f"{D}T15:00", "tz": "Europe/Berlin",
                                             "attendees": [{"user_id": uid["bob"]}]}), "an event with bob invited")
EV2 = (EV2.get("event") or EV2)["id"]
inv = [x for x in kind(Bo, "events", "kranichzug").get("events") or [] if x["id"] == EV2]
check(inv and inv[0]["role"] == "attendee" and inv[0]["cal_id"] is None, f"events: the invited bob finds it as attendee, no calendar {inv}")
check(EV2 not in ids(kind(Do, "events", "kranichzug").get("events")), "events: dora (not invited) finds it not")
made(A.patch(B + f"/api/events/{EV1}", json={"description": "Schwalbenschwanz beobachten"}), "the description changed")
check(EV1 not in ids(kind(A, "events", "zitronenfalter").get("events")), "events: the index follows a change (old word gone)")
check(EV1 in ids(kind(A, "events", "schwalbenschwanz").get("events")), "... the new word found")

# ================================================================== one route: the old ones are gone
for p in ("/api/search/messages", "/api/files/search", "/api/wiki/search"):
    r = A.get(B + p, params={"q": "stachelbeere"})
    check(r.status_code in (404, 405), f"the old route {p} is gone ({r.status_code})")
check(A.get(B + "/api/search", params={"q": "x", "kind": "nonsense"}).status_code == 400, "an unknown kind is a 400")

# ================================================================== the API
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "comments"], "username": "robo", "display_name": "Robo"})
check(r.ok, "setup: an agent " + r.text[:100])
TOK = {"Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/me/tokens", json={"name": "voll", "scopes": ["read", "calendar", "contacts", "files:read", "wiki:read"]})
check(r.ok, "setup: a token of alice with the scopes " + r.text[:100])
AT = {"Authorization": "Bearer " + (r.json().get("token") or "")}
r = requests.get(V + "/search", headers=AT, params={"q": "zitronenfalter", "kind": "events"})
check(r.status_code == 200 and not r.json().get("data"), f"API events: the old word is gone {r.status_code} {r.text[:120]}")
r = requests.get(V + "/search", headers=AT, params={"q": "schwalbenschwanz", "kind": "events"})
check(r.status_code == 200 and EV1 in ids(r.json().get("data")), f"API kind=events finds the event {r.status_code} {r.text[:200]}")
r = requests.get(V + "/search", headers=AT, params={"q": "pflaumenbaum", "kind": "all"})
g = r.json().get("groups", {}) if r.ok else {}
check(r.status_code == 200 and CT1 in ids(g.get("contacts")) and "office" not in g, f"API kind=all: contacts in, never office {str(g)[:200]}")
r = requests.get(V + "/search", headers=AT, params={"q": "quittengelee", "kind": "wiki"})
check(r.status_code == 200 and W1 in ids(r.json().get("data")), f"API kind=wiki finds the page by its text {r.status_code} {r.text[:200]}")
r = requests.get(V + "/search", headers=AT, params={"q": "holunderbl", "kind": "files"})
check(r.status_code == 200 and DOC in ids(r.json().get("data")), f"API kind=files (was /files/search) {r.status_code} {r.text[:200]}")
r = requests.get(V + "/files/search", headers=AT, params={"q": "holunderbl"})
check(r.status_code == 404, f"API: /files/search is gone ({r.status_code})")
r = requests.get(V + "/search", headers=AT, params={"kind": "contacts", "trash": "1"})
check(r.status_code == 200 and "trash_days" in r.json(), f"API kind=contacts&trash=1 lists the trash without q {r.status_code} {r.text[:160]}")
r = requests.get(V + "/search", headers=AT, params={"q": "stachelbeere", "scope": "messages"})
check(r.status_code == 200 and any(h["id"] == C1 for h in r.json().get("data", [])), "API: scope=messages stays the older name of kind=messages")
r = requests.get(V + "/search", headers=TOK, params={"q": "schwalbenschwanz", "kind": "events"})
check(r.status_code == 403 and (r.json().get("required_scope") == "calendar" or "calendar" in r.text.lower()),
      f"API: an agent without the scope calendar gets a 403 for kind=events {r.status_code} {r.text[:160]}")
r = requests.get(V + "/search", headers=TOK, params={"q": "schwalbenschwanz", "kind": "all"})
check(r.status_code == 200 and "events" not in r.json().get("groups", {}) and "contacts" not in r.json().get("groups", {}),
      f"API kind=all: a kind without the scope is left out quietly {r.status_code} {r.text[:160]}")

# ================================================================== a person without an organisation
FE = made(Fr.post(B + "/api/events", json={"title": "Atelier", "start": f"{D}T09:00", "end": f"{D}T10:00", "tz": "Europe/Berlin",
                                            "description": "Leinwandrahmen bestellen"}), "frida's event")
FE = (FE.get("event") or FE)["id"]
FC = made(Fr.post(B + "/api/contacts", json={"fn": "Rahmenbauer Nord", "note": "liefert Keilrahmen"}), "frida's contact")
FC = (FC.get("contact") or FC)["id"]
fg = everywhere(Fr, "leinwandrahmen")
check(FE in ids(fg.get("events")), f"freelancer: the general search finds her own event {str(fg)[:200]}")
check(FC in ids(everywhere(Fr, "keilrahmen").get("contacts")), "freelancer: ... and her own contact by its note")
check(FE not in ids(everywhere(A, "leinwandrahmen").get("events")), "freelancer: alice does not find frida's event")
check(EV1 not in ids(everywhere(Fr, "schwalbenschwanz").get("events")), "freelancer: frida does not find alice's event")

sys.exit(kt.done("p21026_a_search"))
