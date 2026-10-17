#!/usr/bin/env python3
"""2.87.9 API tests, part A (#1919 / #1918): every area as a person WITHOUT an organisation (fixture "Selbstständige",
tests/freelancer_fixture.py) on a server that has an organisation. Invented names only.
 - the freelancer works in the own private space and the own personal office (its own admin there): lists, tasks,
   comments, attachments, office documents, knowledge pages, files, calendars, contacts, time, the own agent, absences,
   budget, settings -- every write of a scenario answers 2xx
 - the sweep: EVERY GET route of the matrix areas of tests/freelancer_coverage_test.py, called as the freelancer (the web
   routes with the session, /api/v1 with a personal token, the agent API with the token of the freelancer's own agent);
   placeholders get the ids of the freelancer's own objects. No 401 / 403 / 5xx, except the few in ALLOW with the reason
 - nothing of the organisation leaks into the private space (state, people list, office)
usage: p287b_a_freelancer_api_test.py <datadir>      (a fresh container; KMT_NOSTART=1 = the server already runs)"""
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import freelancer_coverage_test as cov  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
D = "2030-03-04"
# route -> why a 401 / 403 is right for a freelancer, too (the same answer an organisation member without that role gets)
ALLOW = {
}


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


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

# ================================================================== tasks + lists in the private space
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
IDS["attachment"] = a.get("id") or ((a.get("attachments") or [{}])[0]).get("id")
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
# freelancer-matrix: personal
bu = ok(F.post(B + "/api/budget/lists", json={"name": "Money"}), "personal: a budget", (200, 201))
IDS["budget"] = bu.get("list_id")
ok(F.post(B + "/api/life/health", json={"type": "appointment", "title": "Checkup", "who": "Kim", "date": "2030-01-10", "time": "09:30"}),
   "personal: Home & life", (200, 201))
# freelancer-matrix: own
ok(F.patch(B + "/api/settings", json={"week_start": 1}), "own: settings")
tk = ok(F.post(B + "/api/me/tokens", json={"name": "all", "scopes": [x for x in ("read", "write", "comments", "structure", "delete",
                                                                                  "attachments:read", "attachments:write", "time", "export",
                                                                                  "calendar", "contacts", "private", "account", "files:read",
                                                                                  "files:write", "office", "pinboard", "layouts", "import")]}),
        "own: a personal API token", (200, 201))
PT = {"Authorization": "Bearer " + tk.get("token", "")}

# ================================================================== the sweep: every GET of the matrix areas
# the placeholders: the path up to "{}" -> the id of the freelancer's own object (first match wins)
SUBST = [
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


def fill(path):
    out = ""
    for part in path.split("{}")[:-1]:
        out += part
        key = next((k for rx, k in SUBST if re.search(rx, out)), None)
        if not key or not IDS.get(key):
            return None
        out += str(IDS[key])
    return out + path.split("{}")[-1]


swept, skipped, bad = 0, [], []
for route, kind in sorted(cov.ROUTES.items()):
    m, path = route.split(" ", 1)
    if m != "GET" or cov.KINDS[kind][0] != "matrix":
        continue
    url = fill(path)
    if url is None:
        skipped.append(route)
        continue
    if path.startswith("/api/v1/agent"):
        r = requests.get(B + url, headers=AT)
    elif path.startswith("/api/v1/"):
        r = requests.get(B + url, headers=PT)
        if r.status_code == 403 and "Only agent accounts" in r.text:  # the agent side of the office / layouts: the own agent's token
            r = requests.get(B + url, headers=AT)
    else:
        r = F.get(B + url)
    swept += 1
    if r.status_code in (401, 403) and route in ALLOW:
        continue
    if r.status_code in (401, 403) or r.status_code >= 500:
        bad.append(route)
        check(False, f"sweep: {route} as the freelancer -> {r.status_code} {r.text[:160]}")
    elif r.status_code >= 400:
        print(f"note: {route} -> {r.status_code} {r.text[:100]}")
for route in ALLOW:
    check(route in cov.ROUTES, f"ALLOW names {route}, which is no route of the coverage list")
print(f"sweep: {swept} GET routes as the freelancer, {len(bad)} refused / broken, {len(skipped)} without a known id: "
      + ", ".join(skipped[:60]))
check(swept >= 300, f"sweep: {swept} GET routes called")

print(f"p287b_a_freelancer_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
