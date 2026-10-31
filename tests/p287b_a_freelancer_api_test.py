#!/usr/bin/env python3
"""2.87.9 API tests, part A (#1919 / #1918): every area as a person WITHOUT an organisation (fixture "Selbstständige",
tests/freelancer_fixture.py) on a server that has an organisation. Invented names only.
 - the freelancer works in the own private workspace and the own personal office (its own admin there): lists, tasks,
   comments, attachments, office documents, knowledge pages, files, calendars, contacts, time, the own agent, absences,
   budget, settings -- every write of a scenario answers 2xx
 - the sweep: EVERY GET route of the matrix areas of tests/freelancer_coverage_test.py, called as the freelancer (the web
   routes with the session, /api/v1 with a personal token, the agent API with the token of the freelancer's own agent);
   placeholders get the ids of the freelancer's own objects. No 401 / 403 / 5xx, except the few in ALLOW with the reason;
   2.421.0 A (#2936): no other 4xx either, except EXPECT_4XX (status + reason, stale = red); at most MAX_SKIPPED routes
   without an id of an own object (QUERY gives the GETs that need one their query)
 - nothing of the organisation leaks into the private workspace (state, people list, office)
usage: p287b_a_freelancer_api_test.py <datadir>      (a fresh container; KMT_NOSTART=1 = the server already runs)"""
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlencode

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import freelancer_coverage_test as cov  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, su_get  # 2.192.0 (#2514): shared helpers (tests/kt.py); 2.223.2 C: su_get
D = "2030-03-04"
# route -> why a 401 / 403 is right for a freelancer, too (the same answer an organisation member without that role gets)
ALLOW = {
    # 2.207.0 (#2763): only a scan inbox key reaches it (p2207_a_scan_keys_test.py calls it as the freelancer with one)
    "GET /api/v1/documents/upload-target": "a personal token has no docs:upload (only a scan inbox key has it)",
    # 2.425.0 (#3453): only a receipt fetcher's own key reaches it (p2425_c_api_test.py calls it as the freelancer with one)
    "GET /api/v1/fetcher": "a personal token is no receipt fetcher key",
}
# 2.421.0 A (#2936): route -> (status, why) of a 4xx other than 401 / 403 that is right for the freelancer, too (every other
# 4xx of the sweep fails like a 403; an exception whose status does not come any more fails as stale)
EXPECT_4XX = {
    "GET /api/assistant": (404, "the assistant is off on the test server (the operator's switch, the same for every person)"),
    "GET /api/assistant/log": (404, "the assistant is off on the test server (the operator's switch, the same for every person)"),
    "GET /api/attachments/{}/preview": (415, "the own attachment is a text file: no preview (the same for every person)"),
    "GET /api/files/nodes/{}/preview": (415, "the own file is a text file: no server preview (the same for every person)"),
    "GET /api/bookmarks/{}/image": (404, "the test server fetches no preview picture of the bookmarked page"),
    "GET /api/docs/{}/einvoice": (404, "the own document is a plain text receipt, no e-invoice"),
    "GET /api/docs/{}/split": (409, "the own document is no PDF with two pages or more"),
    "GET /api/docs/{}/thumb": (404, "the own document is a text receipt: no thumbnail"),
    "GET /api/hubmail/targets": (404, "no filed mail on the test server (?mail= names one)"),
    "GET /api/life/karakeep/lists": (400, "Karakeep (an outside service) is not connected"),
    "GET /api/newsletter/lists": (404, "no newsletter connection (an outside service)"),
    "GET /api/paperless/preview": (404, "no Paperless connection (an outside service)"),
    "GET /api/paperless/zip/preview": (404, "no Paperless ZIP uploaded"),
    "GET /api/lists/{}/e2e/todo": (409, "no encryption change is running for the private list"),
    "GET /api/wiki/e2e/todo": (409, "no encryption change is running for the private workspace"),
    "GET /api/office/docs/{}/timesheet.pdf": (400, "no time entries of the client in the period (the own entries are on a list without a client)"),
    "GET /api/office/logo": (404, "no logo uploaded in the personal office"),
    "GET /api/office/books/archive/files/{}": (404, "no past DATEV year imported into the personal office, the id is a file of the file store"),
    "GET /api/office/move/check": (404, "the freelancer has no organisation to move the personal office into"),
    "GET /api/tasks/{}/enc-note": (404, "no encrypted note on the own task"),
    "GET /api/tasks/{}/note-lock": (404, "the note of the own task is not locked"),
    "GET /api/trash/lists/{}/export.zip": (404, "the own list is not in the trash"),
    "GET /api/v1/office/letters/{}": (404, "an agent reads only the letters it drafted itself; the freelancer wrote this one"),
}
# 2.421.0 A (#2936): GET routes of the matrix areas the sweep cannot fill (no id of an own object): may only shrink
MAX_SKIPPED = 88  # 29.10.2026: 108 before the setup made tables, polls, bookmarks, letters, contracts, questionnaires


def ok(r, what, codes=(200, 201, 204)):
    check(r.status_code in codes, f"{what}: {r.status_code} {r.text[:200]}")
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


if not os.environ.get("KMT_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "collab_all": True, "time_all": True,
                                     "modules": ["cal", "habits", "pomo", "stats", "deps", "fields"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123",
                                   "email": "bob@example.com", "orgs": [ORG]})
assert r.ok, r.text
OL = A.post(B + "/api/lists", json={"name": "Nordwind board", "org_id": ORG}).json()["id"]
OT = A.post(B + "/api/tasks", json={"list_id": OL, "title": "Org-only task"}).json()["id"]
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})  # the server's switch (the same for everybody)
FID, F = freelancer(B, A)
IDS = {}

# ================================================================== tasks + lists in the private workspace
# freelancer-matrix: tasks, lists
L = ok(F.post(B + "/api/lists", json={"name": "Client projects", "kind": "project", "time_tracking": True}), "lists: a private project", (200, 201))
IDS["list"] = L.get("id")
check(L.get("org_id") in (None, 0), f"lists: the list is private {L.get('org_id')}")
T = ok(F.post(B + "/api/tasks", json={"list_id": IDS["list"], "title": "Cut the trailer", "due": D}), "tasks: a task", (200, 201))
IDS["task"] = T.get("id")
ST = ok(F.post(B + "/api/tasks", json={"list_id": IDS["list"], "title": "Colour grading", "parent_id": IDS["task"]}), "tasks: a subtask", (200, 201))
ok(F.patch(B + f"/api/tasks/{IDS['task']}", json={"title": "Cut the trailer v2", "tags": ["film"]}), "tasks: change")
c = ok(F.post(B + f"/api/tasks/{IDS['task']}/comments", json={"body": "note to self"}), "tasks: a comment", (200, 201))
IDS["comment"] = c.get("id")
a = ok(F.post(B + f"/api/tasks/{IDS['task']}/attachments", files={"file": ("brief.txt", b"brief", "text/plain")}), "tasks: an attachment", (200, 201))
IDS["attachment"] = ((a.get("attachments") or [{}])[-1]).get("id")  # 2.421.0 A (#2936): the upload answers the task, not the file
s = ok(F.post(B + "/api/sections", json={"list_id": IDS["list"], "name": "Now"}), "lists: a section", (200, 201))
IDS["section"] = s.get("id")
n = ok(F.post(B + f"/api/lists/{IDS['list']}/notes", json={"title": "Ideas", "body": "x"}), "lists: a note", (200, 201))
IDS["note"] = n.get("id")
ok(F.post(B + f"/api/tasks/{ST.get('id')}/complete"), "tasks: complete a subtask", (200, 201, 204))
st = F.get(B + "/api/state").json()
check(any(x["id"] == IDS["list"] for x in st.get("lists", [])) and not any(x["id"] == OL for x in st.get("lists", [])),
      "tasks: the state has the own list, not the organisation's")
check(not any(x.get("id") == OT for x in st.get("tasks", [])), "tasks: no task of the organisation")
ok(F.get(B + "/api/tasks", params={"q": "trailer"}), "tasks: search")
ok(F.get(B + "/api/export.json"), "tasks: the export")
ok(F.put(B + f"/api/lists/{IDS['list']}/public-link", json={}), "lists: a public link of the private list", (200, 201))
ok(F.post(B + f"/api/lists/{IDS['list']}/signoffs", json={}), "lists: an approval link of the private list (its owner)", (200, 201))

# ================================================================== the personal office (its own admin)
# freelancer-matrix: office
o = ok(F.get(B + "/api/office/settings"), "office: opens without an organisation")
check(o.get("personal") == 1 and o.get("role") == "admin", f"office: the personal office, its own admin {o.get('personal')} {o.get('role')}")
ok(F.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Film", "street": "Hafenweg 1", "zip": "20457",
                                                                "city": "Hamburg", "country": "DE", "tax_number": "12/345/67890",
                                                                "iban": "DE02120300000000202051", "bic": "BYLADEM1001"}}),
   "office: company fields")
cl = ok(F.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"}), "office: a private client", (200, 201))
IDS["client"] = cl.get("id")
check(cl.get("org_id") is None, "office: the client is private")
q = ok(F.post(B + "/api/office/docs", json={"project_title": "Imagefilm", "client_id": IDS["client"],
                                                    "service_from": "2030-02-01", "service_to": "2030-02-28"}), "office: a quotation", (200, 201))
IDS["doc"] = q.get("id")
ok(F.put(B + f"/api/office/docs/{IDS['doc']}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 900}]}), "office: positions")
sv = ok(F.post(B + "/api/office/services", json={"name_de": "Schnitt", "unit": "day", "rate": 600}), "office: master data (a service)", (200, 201))
IDS["service"], IDS["officekind"] = sv.get("id"), "services"
inv = ok(F.post(B + f"/api/office/docs/{IDS['doc']}/invoice"), "office: an invoice from the quotation", (200, 201))
ok(F.post(B + f"/api/office/docs/{inv.get('id')}/finalize"), "office: finalise the invoice")
ok(F.get(B + f"/api/office/docs/{inv.get('id')}/pdf"), "office: the PDF")
# #1918: what an organisation's office reserves to its admins, the freelancer does in the personal office
ok(F.post(B + f"/api/office/docs/{inv.get('id')}/payments", json={"date": "2026-09-02", "amount": 100}), "office: record a payment (admin)", (200, 201))
q2 = ok(F.post(B + "/api/office/docs", json={"project_title": "Imagefilm 2", "client_id": IDS["client"]}), "office: a second quotation", (200, 201))
ok(F.put(B + f"/api/office/docs/{q2.get('id')}/items", json={"items": [{"service_id": IDS["service"], "qty": 1}]}), "office: its positions")
ok(F.post(B + f"/api/office/docs/{q2.get('id')}/status", json={"status": "sent"}), "office: quotation sent")
so = ok(F.post(B + f"/api/office/docs/{q2.get('id')}/signoff", json={}), "office: an approval link of the private quotation", (200, 201))
check(bool(so.get("url")), "office: the approval link has its address")
r = requests.get(B + "/s/q/" + (so.get("url") or "/s/q/x").split("/s/q/")[-1])
check(r.status_code == 200, f"office: the customer opens the approval page {r.status_code}")
ok(F.get(B + "/api/newsletter", params={"ws": "private"}), "office: the newsletter connection of the private workspace")
ok(F.get(B + "/api/paperless", params={"ws": "private"}), "office: the Paperless connection of the private workspace")

# ================================================================== knowledge pages
# freelancer-matrix: wiki
w = ok(F.post(B + "/api/wiki/pages", json={"space": "private", "path": "Kit/Camera", "body": "lens list"}), "wiki: a private page", (200, 201))
IDS["wiki"] = w.get("id")
ok(F.patch(B + f"/api/wiki/pages/{IDS['wiki']}", json={"body": "lens list v2"}), "wiki: change")
ok(F.get(B + "/api/wiki/search", params={"space": "private", "q": "lens"}), "wiki: search")

# ================================================================== files + documents
# freelancer-matrix: files
fo = ok(F.post(B + "/api/files/folders", json={"name": "Projects"}), "files: a folder", (200, 201))
IDS["folder"] = fo.get("id")
fu = ok(F.post(B + "/api/files/upload", data={"parent_id": str(IDS["folder"] or "")}, files={"file": ("plan.txt", b"plan")}),
        "files: an upload", (200, 201))
IDS["node"] = ((fu.get("items") or [{}])[0]).get("id")
du = ok(F.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("receipt.txt", b"Receipt 12,00 EUR", "text/plain"))]),
        "files: a document", (200, 201))
IDS["docnode"] = (du.get("ids") or [None])[0]
ok(F.put(B + "/api/docs/settings", json={"ws": "private", "inbox": True}), "files: document settings of the private workspace (its own admin)")

# ================================================================== calendars, contacts, CalDAV / CardDAV
# freelancer-matrix: pim
ca = ok(F.post(B + "/api/evcals", json={"name": "Shoots", "color": "#2dd4bf"}), "pim: a calendar", (200, 201))
IDS["evcal"] = ca.get("id")
ev = ok(F.post(B + "/api/events", json={"title": "Shoot day", "cal_id": IDS["evcal"], "start": f"{D}T09:00", "end": f"{D}T17:00"}),
        "pim: an event", (200, 201))
IDS["event"] = ev.get("id")
bk = ok(F.post(B + "/api/books", json={"name": "Clients"}), "pim: an address book", (200, 201))
IDS["book"] = bk.get("id")
ct = ok(F.post(B + "/api/contacts", json={"fn": "Erika Beispiel", "book_id": IDS["book"]}), "pim: a contact", (200, 201))
IDS["contact"] = ct.get("id")
pw = ok(F.post(B + "/api/me/app-passwords", json={"name": "phone"}), "pim: an app password", (200, 201)).get("password", "")
dav = requests.Session()
dav.auth = ("frida", pw)
r = dav.request("PROPFIND", B + "/dav/", headers={"Depth": "1"})
check(r.status_code == 207, f"pim: CalDAV / CardDAV with the app password {r.status_code}")

# ================================================================== time
# freelancer-matrix: time
te = ok(F.post(B + "/api/time/entries", json={"list_id": IDS["list"], "start": "2026-09-01T09:00", "minutes": 30}), "time: an entry", (200, 201))
IDS["timeentry"] = te.get("id")
h = ok(F.post(B + "/api/habits", json={"name": "Run", "goal": 2}), "time: a habit", (200, 201))
IDS["habit"] = h.get("id")

# ================================================================== the own agent
# freelancer-matrix: agents
ag = ok(F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot",
                                                      "scopes": ["read", "tasks:write", "comments", "office", "layouts"]}), "agents: an own agent", (200, 201))
IDS["agent"] = ag.get("id")
ok(F.put(B + f"/api/lists/{IDS['list']}/members", json={"user_id": IDS["agent"], "role": "edit"}), "agents: the agent in the private list")
# the personal office: the freelancer is its admin, so the freelancer switches the privacy switch and the agent's drafts
ok(F.put(B + "/api/office/settings", json={"agents_read": 1}), "agents: the office privacy switch (its own admin)")
ok(F.patch(B + f"/api/office/agents/{IDS['agent']}", json={"office_drafts": True}), "agents: office drafts for the own agent")
AT = {"Authorization": "Bearer " + ok(F.post(B + f"/api/my/agents/{IDS['agent']}/token"), "agents: its token").get("token", "")}
r = requests.get(V + "/lists", headers=AT)
check(r.ok and str(IDS["list"]) in r.text, f"agents: the agent sees the shared private list {r.status_code} {r.text[:200]}")
ok(F.post(B + f"/api/agents/{IDS['agent']}/chat", json={"body": "hello"}), "agents: a chat message", (200, 201))

# ================================================================== people, absences, personal areas, own settings
# freelancer-matrix: team
u = ok(F.get(B + "/api/users"), "team: the people list")
names = {x.get("username") for x in (u.get("users") if isinstance(u, dict) else u) or []}
check("bob" not in names, f"team: nobody of the organisation in the freelancer's people list {sorted(names)}")
# freelancer-matrix: hub
ab = ok(F.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": D, "end_date": "2030-03-08"}), "hub: an own absence", (200, 201))
IDS["absence"] = ab.get("id")
# 409 = mail to tasks is not set up on the test server (the same answer for an organisation member); never 403 / 404
ok(F.post(B + "/api/hubmail/address", json={"ws": "private"}), "hub: an own mail address of the private workspace", (200, 201, 409))
ok(F.put(B + "/api/team/absences/holidays", json={"state": "HH"}), "hub: the public holidays of the personal area (its own admin)")
# freelancer-matrix: personal
bu = ok(F.post(B + "/api/budget/lists", json={"name": "Money"}), "personal: a budget", (200, 201))
IDS["budget"] = bu.get("list_id")
ok(F.post(B + "/api/life/health", json={"type": "appointment", "title": "Checkup", "who": "Kim", "date": "2030-01-10", "time": "09:30"}),
   "personal: Home & life", (200, 201))
# freelancer-matrix: own
ok(F.patch(B + "/api/settings", json={"week_start": "mon"}), "own: settings")
ok(F.post(B + "/api/account/export", json={}), "own: an account export", (200, 201, 202))
tk = ok(F.post(B + "/api/me/tokens", json={"name": "all", "scopes": [x for x in ("read", "write", "comments", "structure", "delete",
                                                                                  "attachments:read", "attachments:write", "time", "export",
                                                                                  "calendar", "contacts", "private", "account", "files:read",
                                                                                  "files:write", "office", "pinboard", "layouts", "import",
                                                                                  "sheets:read", "wiki:read", "wiki:write")]}),  # 2.89.1: tables of 2.89.0; 2.200.0 (#1781): knowledge pages
        "own: a personal API token", (200, 201))
PT = {"Authorization": "Bearer " + tk.get("token", "")}

# ================================================================== 2.421.0 A (#2936): more own objects, so the sweep fills more routes
def _id(x):
    return x.get("id") or next((v.get("id") for v in x.values() if isinstance(v, dict) and v.get("id")), None)


IDS["sheet"] = _id(ok(F.post(B + "/api/sheets", json={"title": "Rates", "space": "private"}), "sweep setup: a table", (200, 201)))
IDS["poll"] = _id(ok(F.post(B + "/api/polls", json={"title": "Shoot date", "duration": 60, "tz": "Europe/Berlin",
                                                     "options": [{"start": "2031-03-10T10:00"}, {"start": "2031-03-11T14:30"}]}),
                     "sweep setup: a scheduling poll", (200, 201)))
IDS["bookmark"] = _id(ok(F.post(B + "/api/bookmarks", json={"url": "https://example.com/kit"}), "sweep setup: a bookmark", (200, 201)))
IDS["letter"] = _id(ok(F.post(B + "/api/office/letters", json={"subject": "Follow-up"}), "sweep setup: a letter", (200, 201)))
IDS["agreement"] = _id(ok(F.post(B + "/api/office/agreements", json={"kind": "insurance", "name": "Equipment insurance", "task": 0}),
                          "sweep setup: a contract", (200, 201)))
IDS["form"] = _id(ok(F.post(B + f"/api/lists/{IDS['list']}/forms", json={"title": "Brief", "access": "public"}),
                     "sweep setup: a questionnaire", (200, 201)))
IDS["milestone"] = _id(ok(F.post(B + "/api/tasks", json={"list_id": IDS["list"], "title": "Delivery", "ms": 1}),
                          "sweep setup: a milestone", (200, 201)))
IDS["invoice"], IDS["pack"] = inv.get("id"), "xx"
IDS["cashbook"] = _id(ok(F.post(B + "/api/office/cashbooks", json={"name": "Till", "opening": "100.00", "opening_day": "2026-03-01"}),
                       "sweep setup: a cash book", (200, 201)))
ok(F.patch(B + f"/api/lists/{IDS['list']}", json={"folder": "Work"}), "sweep setup: the private list in a folder")
ok(F.put(B + "/api/office/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345"}}), "sweep setup: DATEV numbers")
IDS["card"] = ok(F.post(B + "/api/office/cards", json={"holder_id": FID, "last4": "1234"}), "office: a credit card", (200, 201)).get("id")  # 2.444.0 (#3447)
c = ok(F.post(B + f"/api/office/cards/{IDS['card']}/statements", files={"file": ("stmt.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}, data={"month": D[:7]}),
       "office: a statement of the card (no text: typed in)", (200, 201))
IDS["cardstmt"] = c["statement"]["id"]
IDS["cardline"] = ok(F.post(B + f"/api/office/cards/statements/{IDS['cardstmt']}/lines", json={"day": D, "merchant": "Lens rental", "amount": "10.00"}),
                     "office: a typed position", (200, 201))["line"]["id"]
c = ok(F.post(B + f"/api/office/cards/statements/{IDS['cardstmt']}/lines", json={"day": D, "merchant": "Typo", "amount": "1.00"}), "office: another", (200, 201))
ok(F.delete(B + f"/api/office/cards/lines/{c['line']['id']}"), "office: a typed position goes again")
IDS["collection"] = "wiki"  # 2.429.0 (#3580): a collection of the file store (empty is fine)
for _ in range(480):  # the account export of "own" runs in the background: its file once it is done
    if F.get(B + "/api/account/export").json().get("state") != "running":
        break
    time.sleep(0.25)

# ================================================================== the sweep: every GET of the matrix areas
# the placeholders: the path up to "{}" -> the id of the freelancer's own object (first match wins)
SUBST = [
    # 2.421.0 A (#2936): own objects of the setup above; file ids of other stores than the file store: none (skipped)
    (r"/sheets/\d+/files/$", None), (r"/sheets/$", "sheet"), (r"/polls/$", "poll"), (r"/bookmarks/$", "bookmark"),
    (r"/office/letters/$", "letter"), (r"/office/packs/$", "pack"), (r"/office/agreements/$", "agreement"), (r"/forms/$", "form"),
    (r"/office/cashbooks/$", "cashbook"),
    (r"/office/cards/lines/$", "cardline"), (r"/office/cards/statements/$", "cardstmt"), (r"/office/cards/$", "card"), (r"/files/collections/$", "collection"),
    (r"/budget/files/$", None), (r"/team/files/$", None), (r"/wiki/files/$", None), (r"/wiki/shared/files/$", None),
    (r"/lists/\d+/files/$", None),
    (r"/office/docs/$", "doc"), (r"/office/services/$", "service"), (r"/api(/v1)?/office/$", "officekind"),
    (r"/files/nodes/$", "node"), (r"/e2e/pub/$", "me"), (r"/api/docs/$", "docnode"), (r"/documents/$", "docnode"), (r"/clients/$", "client"),
    (r"/lists/$", "list"), (r"/list-files/$", None), (r"/tasks/$", "task"), (r"/comments/$", "comment"),
    (r"/attachments/$", "attachment"), (r"/sections/$", "section"), (r"/notes/$", "note"), (r"/wiki/pages/$", "wiki"),
    (r"/files/$", "node"), (r"/evcals/$", "evcal"), (r"/event-calendars/$", "evcal"), (r"/events/$", "event"),
    (r"/books/$", "book"), (r"/address-books/$", "book"), (r"/contacts/$", "contact"), (r"/time/entries/$", "timeentry"),
    (r"/habits/$", "habit"), (r"/my/agents/$", "agent"), (r"/agents/$", "agent"), (r"/users/$", "me"), (r"/avatar/$", "me"),
    (r"/absences/$", "absence"), (r"/budget/$", "budget"),
]
IDS["me"] = FID


# 2.421.0 A (#2936): route -> {placeholder key: the id to take instead} where the first own object is the wrong kind
USE = {"GET /api/files/nodes/{}/requests": {"node": "folder"}, "GET /api/office/docs/{}/peppol": {"doc": "invoice"},
       "GET /api/office/docs/{}/ubl": {"doc": "invoice"}, "GET /api/office/docs/{}/xml": {"doc": "invoice"},
       "GET /api/office/docs/{}/timesheet.pdf": {"doc": "invoice"}, "GET /api/tasks/{}/milestone": {"task": "milestone"},
       "GET /api/v1/tasks/{}/milestone": {"task": "milestone"}}
# 2.421.0 A (#2936): route -> the query a GET needs ({key} = an id of IDS), so it answers with data instead of a 400
FROM_TO = {"from": "2030-03-01", "to": "2030-03-31"}
QUERY = {
    "GET /api/calendars/events": FROM_TO, "GET /api/events": FROM_TO, "GET /api/occurrences": FROM_TO, "GET /api/v1/events": FROM_TO,
    "GET /api/events/freebusy": {"day": D, "users": "{me}"}, "GET /api/clients/usage": {"ids": "{client}"},
    "GET /api/files/search": {"q": "plan"}, "GET /api/v1/files/search": {"q": "plan"}, "GET /api/files/tagged": {"tag": "1"},
    "GET /api/files/zip": {"ids": "{node}"}, "GET /api/folders/agents": {"folder": "Work"},
    "GET /api/folders/notify-template": {"folder": "Work"}, "GET /api/folders/people/diff": {"folder": "Work", "role": "edit", "user_id": "{agent}"},
    "GET /api/folders/playbook": {"folder": "Work"}, "GET /api/folders/playbook/versions": {"folder": "Work"},
    "GET /api/folders/props": {"folder": "Work"}, "GET /api/folders/public-links": {"folder": "Work"}, "GET /api/folders/repos": {"folder": "Work"},
    "GET /api/hubmail/compose": {"client_id": "{client}"}, "GET /api/hubmail/mails": {"client_id": "{client}"},
    "GET /api/hubmail/links": {"task_id": "{task}"}, "GET /api/office/books/ustva": {"year": "2026", "period": "q3"},
    "GET /api/office/datev/extf": {"from": "2026-01-01", "to": "2026-12-31"}, "GET /api/office/datev/zip": {"from": "2026-01-01", "to": "2026-12-31"},
    "GET /api/office/letters/threads": {"client_id": "{client}"}, "GET /api/office/pack-switch": {"code": "XX"},
    "GET /api/office/time-open": {"from": "2026-09-01", "to": "2026-09-30"}, "GET /api/search": {"q": "trailer"},
    "GET /api/search/messages": {"q": "trailer"}, "GET /api/v1/search": {"q": "trailer"}, "GET /api/tags/count": {"tag": "film"},
    "GET /api/team/absences/check": {"user": "{me}", "date": D}, "GET /api/team/dispo/free": {"date": D},
    "GET /api/v1/dispo/free": {"date": D}, "GET /api/videos": {"task_id": "{task}"}, "GET /api/v1/videos": {"task_id": "{task}"},
    "GET /api/office/books/archive/accounts": {"year": "2026"}, "GET /api/office/books/archive/bookings": {"year": "2026"},
    "GET /api/wiki/query": {"page": "{wiki}", "q": "zeige: seiten"}, "GET /api/wiki/mentions": {"task": "{task}"}, "GET /api/forms/{}/client-link": {"client": "{client}"},
    "GET /api/files/collections/{}": {"space": "private"}, "GET /api/wiki/refs": {"file": "{node}"},
}


def fill(path, route=""):
    out = ""
    for part in path.split("{}")[:-1]:
        out += part
        key = next((k for rx, k in SUBST if re.search(rx, out)), None)
        key = USE.get(route, {}).get(key, key)
        if not key or not IDS.get(key):
            return None
        out += str(IDS[key])
    return out + path.split("{}")[-1]


swept, skipped, bad, expected = 0, [], [], set()
for route, kind in sorted(cov.ROUTES.items()):
    m, path = route.split(" ", 1)
    if m != "GET" or cov.KINDS[kind][0] != "matrix":
        continue
    url = fill(path, route)
    if url is None:
        skipped.append(route)
        continue
    if route in QUERY:
        url += "?" + urlencode({k: v.format(**IDS) for k, v in QUERY[route].items()})
    if path.startswith("/api/v1/agent"):
        r = requests.get(B + url, headers=AT)
    elif path.startswith("/api/v1/"):
        r = requests.get(B + url, headers=PT)
        if r.status_code == 403 and "Only agent accounts" in r.text:  # the agent side of the office / layouts: the own agent's token
            r = requests.get(B + url, headers=AT)
    else:
        r = F.get(B + url, headers={"Sec-Fetch-Site": "same-origin"})  # 2.138.0 (#1907): as a browser does (downloads of the own page only)
        if r.status_code == 403 and '"need"' in r.text:  # 2.223.2 C (#2871): a download behind the step-up: the password, then the ticket
            r = su_get(F, B + url, headers={"Sec-Fetch-Site": "same-origin"})
    swept += 1
    if r.status_code in (401, 403) and route in ALLOW:
        continue
    if route in EXPECT_4XX:  # 2.421.0 A (#2936): the listed answer, nothing else
        expected.add(route)
        check(r.status_code == EXPECT_4XX[route][0], f"sweep: {route} -> {r.status_code}, EXPECT_4XX says {EXPECT_4XX[route][0]} "
                                                     f"(fixed? then remove the exception) {r.text[:120]}")
        continue
    if r.status_code >= 400:  # 2.421.0 A (#2936): a 400 / 404 / 409 is a failure, too (was a note)
        bad.append(f"{route} -> {r.status_code}")
        check(False, f"sweep: {route} as the freelancer -> {r.status_code} {r.text[:160]}")
for route in ALLOW:
    check(route in cov.ROUTES, f"ALLOW names {route}, which is no route of the coverage list")
for route, (st, why) in EXPECT_4XX.items():
    check(400 <= st < 500 and st not in (401, 403) and len(why) > 15, f"EXPECT_4XX {route}: a 4xx other than 401 / 403 and its reason")
    check(route in expected, f"EXPECT_4XX names {route}, which the sweep did not call (no GET of a matrix area, or skipped)")
print(f"sweep: {swept} GET routes as the freelancer, {len(bad)} refused / broken, {len(skipped)} without a known id: "
      + ", ".join(skipped))
if bad:
    print("sweep: refused / broken: " + "; ".join(bad))
check(swept >= 300, f"sweep: {swept} GET routes called")
check(len(skipped) <= MAX_SKIPPED, f"sweep: {len(skipped)} GET routes without a known id, at most {MAX_SKIPPED}: create their "
                                   f"objects in the setup (SUBST / IDS) instead of raising the threshold")

print(f"p287b_a_freelancer_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
