#!/usr/bin/env python3
"""2.192.0 C (#2514): fills an OLDER release's empty test server with typical invented data and dumps its database -- the
fixture tests/fixtures/upgrade/<version>.sql.gz (+ <version>.json: what that release showed through its API) that
p2192_c_upgrade_test.py starts the current server on. Written against the API of 2.101.0 (the release of the first dump);
it runs inside the old release's tests/ folder (tools/make_upgrade_dump.sh copies it there), so it needs nothing but
requests and docker (no kt.py: that came later).

    python3 upgrade_seed.py <datadir>     (the old server runs: start.sh; KALMIDO_TEST_PORT as in start.sh)
    # shots: 'P2192C_DUMP_SHOTS'          the folder the dump + JSON are written to (default: tests/fixtures/upgrade)

Data (invented, addresses @example.com): instance admin alice with the organisation "Nordwind Studio", member bob, frida
without an organisation (her own private space and personal office); an org project and a private list with tasks (due
date + time, repeat rule, subtasks, a done task), comments of two people, an attachment, an org office (client, quotation
with items, invoice from it, finalized), frida's personal office (client + quotation), time entries, a personal agent."""
import gzip
import json
import os
import subprocess
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KALMIDO_TEST_DATA") or os.path.join(HERE, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
PW = "password123"
FEATURES = ("cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,comments,events,contacts,files,docs,"
            "clients,office,workload,forms,wiki")
OUT = os.environ.get("P2192C_DUMP_SHOTS") or os.path.join(HERE, "fixtures", "upgrade")


def ok(r, what):
    assert r.status_code < 300, f"{what}: {r.status_code} {r.text[:300]}"
    return r.json() if r.content else {}


def login(user):
    s = requests.Session()
    s.headers.update(H)
    ok(s.post(B + "/api/auth/login", json={"username": user, "password": PW}), "login " + user)
    return s


s0 = requests.Session()
s0.headers.update(H)
ok(s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": PW}), "setup")
A = login("alice")
ok(A.post(B + "/api/admin/setup", json={"org_name": "Nordwind Studio", "lang": "en", "collab_all": True, "time_all": True,
                                       "modules": ["cal", "habits", "pomo", "stats", "deps", "fields"]}),
   "admin setup")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ok(A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done", "workspace": f"org:{ORG}"}), "alice settings")
BOB = ok(A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Beispiel", "password": PW,
                                        "email": "bob@example.com", "orgs": [ORG]}), "bob")["id"]
FRIDA = ok(A.post(B + "/api/users", json={"username": "frida", "display_name": "Frida Frei", "password": PW,
                                          "email": "frida@example.com", "orgs": []}), "frida")["id"]
Bo, Fr = login("bob"), login("frida")
ok(Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"}), "bob settings")
ok(Fr.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"}), "frida settings")

# lists + tasks
TEAM = ok(A.post(B + "/api/lists", json={"name": "Nordwind Projekte", "org_id": ORG, "kind": "project", "time_tracking": True}), "team")["id"]
ok(A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": BOB, "role": "edit"}), "bob in team")
PRIV = ok(A.post(B + "/api/lists", json={"name": "Alice privat", "org_id": None}), "alice private")["id"]
T1 = ok(A.post(B + "/api/tasks", json={"list_id": TEAM, "title": "Imagefilm schneiden", "due": "2026-03-04", "due_time": "18:30"}), "t1")["id"]
ok(A.patch(B + f"/api/tasks/{T1}", json={"repeat": "FREQ=WEEKLY;BYDAY=MO"}), "t1 repeat")
for t in ("Rohschnitt", "Farbkorrektur"):
    ok(A.post(B + "/api/tasks", json={"list_id": TEAM, "title": t, "parent_id": T1}), "subtask")
T2 = ok(A.post(B + "/api/tasks", json={"list_id": TEAM, "title": "Musik lizenzieren", "due": "2026-04-01"}), "t2")["id"]
T3 = ok(A.post(B + "/api/tasks", json={"list_id": TEAM, "title": "Angebot schicken"}), "t3")["id"]
ok(A.post(B + f"/api/tasks/{T3}/complete", json={}), "t3 done")
for t in ("Steuerunterlagen sortieren", "Zahnarzt anrufen"):
    ok(A.post(B + "/api/tasks", json={"list_id": PRIV, "title": t, "repeat": "FREQ=MONTHLY" if t[0] == "S" else ""}), "private task")
ok(A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Erste Fassung bis Freitag"}), "comment alice")
ok(Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "Ton kommt am Donnerstag"}), "comment bob")
ok(A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("briefing.txt", b"Briefing Imagefilm\n" * 10, "text/plain")}), "attachment")
FL = ok(Fr.post(B + "/api/lists", json={"name": "Frida Kunden", "kind": "project", "time_tracking": True}), "frida list")["id"]
FT = ok(Fr.post(B + "/api/tasks", json={"list_id": FL, "title": "Website-Texte", "due": "2026-05-15"}), "frida task")["id"]
ok(Fr.post(B + f"/api/tasks/{FT}/comments", json={"body": "Entwurf liegt bei"}), "frida comment")

# office: the org's (alice = org admin) and frida's personal one
ok(A.put(B + "/api/office/settings", json={"company_fields": {"name": "Nordwind Studio GmbH", "street": "Hafenweg 1", "zip": "20457",
                                                             "city": "Hamburg", "country": "DE", "tax_number": "12/345/67890",
                                                             "iban": "DE02120300000000202051", "bic": "BYLADEM1001"}}), "org office settings")
CL = ok(A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln",
                                         "country": "DE", "org_id": ORG}), "org client")["id"]
Q = ok(A.post(B + "/api/office/docs", json={"kind": "offer", "project_title": "Imagefilm", "client_id": CL,
                                            "service_from": "2026-02-01", "service_to": "2026-02-28"}), "offer")["id"]
ok(A.put(B + f"/api/office/docs/{Q}/items", json={"items": [{"title": "Drehtag", "qty": 2, "rate": 900},
                                                            {"title": "Schnitt", "qty": 3, "rate": 650}]}), "offer items")
INV = ok(A.post(B + f"/api/office/docs/{Q}/invoice"), "invoice")["id"]
ok(A.post(B + f"/api/office/docs/{INV}/finalize"), "finalize")
FCL = ok(Fr.post(B + "/api/clients", json={"name": "Kleinkunde GbR", "city": "Berlin", "country": "DE"}), "frida client")["id"]
FQ = ok(Fr.post(B + "/api/office/docs", json={"kind": "offer", "project_title": "Texte", "client_id": FCL}), "frida offer")["id"]
ok(Fr.put(B + f"/api/office/docs/{FQ}/items", json={"items": [{"title": "Text", "qty": 4, "rate": 120}]}), "frida items")

# time entries + agent
ok(A.post(B + "/api/time/entries", json={"task_id": T1, "start": "2026-02-10T09:00", "minutes": 90, "note": "Sichtung"}), "time alice")
ok(Bo.post(B + "/api/time/entries", json={"task_id": T1, "start": "2026-02-11T10:00", "minutes": 45}), "time bob")
ok(Fr.post(B + "/api/time/entries", json={"list_id": FL, "start": "2026-02-12T08:00", "minutes": 30}), "time frida")
ok(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}), "agent policy")
AG = ok(A.post(B + "/api/my/agents", json={"username": "nordbot", "display_name": "Nordwind Bot", "scopes": ["read", "tasks:write"]}), "agent")["id"]
ok(A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": AG, "role": "edit"}), "agent in team")


# what this release shows: the suite compares the upgraded server's answers with it
def view(s):
    st = s.get(B + "/api/state").json()
    lists = {x["id"]: x["name"] for x in st["lists"]}
    tasks = sorted((lists.get(t["list_id"], "?"), t["title"], t.get("due") or "", t.get("due_time") or "", t.get("repeat") or "",
                    bool(t.get("parent_id")), t.get("status") or 0,
                    sorted(a["name"] for a in t.get("attachments") or [])) for t in st["tasks"])
    return {"lists": sorted(lists.values()), "tasks": tasks}


def comments(s, tid):
    return sorted(c["body"] for c in s.get(B + f"/api/tasks/{tid}/timeline").json()["comments"])


def docs(s):
    out = []
    for kind in ("offer", "invoice"):
        for d in s.get(B + "/api/office/docs", params={"kind": kind}).json()["docs"]:
            full = s.get(B + f"/api/office/docs/{d['id']}").json()
            out.append({"id": d["id"], "kind": kind, "number": full.get("number") or "", "net": full["totals"]["net"],
                        "gross": full["totals"]["gross"]})
    return sorted(out, key=lambda d: d["id"])


def minutes(s):
    es = s.get(B + "/api/time/entries", params={"scope": "all", "from": "2026-01-01"}).json()["entries"]
    return sorted(round((e.get("seconds") or e.get("minutes", 0) * 60) / 60) for e in es)


EXP = {
    "version": open(os.path.join(HERE, "..", "VERSION")).read().strip(),
    "password": PW, "org": ORG, "ids": {"team": TEAM, "private": PRIV, "t1": T1, "t2": T2, "frida_list": FL, "frida_task": FT,
                                        "offer": Q, "invoice": INV, "frida_offer": FQ, "agent": AG, "bob": BOB, "frida": FRIDA},
    "users": {u: view(s) for u, s in (("alice", A), ("bob", Bo), ("frida", Fr))},
    "comments": {"t1": comments(A, T1), "frida_task": comments(Fr, FT)},
    "docs": {"alice": docs(A), "frida": docs(Fr)},
    "clients": {"alice": sorted(c["name"] for c in A.get(B + "/api/clients").json()["clients"]),
                "frida": sorted(c["name"] for c in Fr.get(B + "/api/clients").json()["clients"])},
    "minutes": {"alice": minutes(A), "frida": minutes(Fr)},
    "agents": sorted(a["username"] for a in A.get(B + "/api/my/agents").json()["agents"]),
}
assert EXP["docs"]["alice"] and EXP["docs"]["frida"] and EXP["minutes"]["alice"], EXP

with open(os.path.join(DATA, ".kalmido-db"), encoding="utf-8") as f:
    DBC, DBN = f.read().split()
r = subprocess.run(["docker", "exec", DBC, "pg_dump", "-U", "kalmido", "-d", DBN, "--no-owner", "--no-privileges"],
                   capture_output=True, check=True)
os.makedirs(OUT, exist_ok=True)
v = EXP["version"]
with gzip.GzipFile(os.path.join(OUT, v + ".sql.gz"), "wb", 9, mtime=0) as f:
    f.write(r.stdout)
with open(os.path.join(OUT, v + ".json"), "w", encoding="utf-8") as f:
    json.dump(EXP, f, ensure_ascii=False, indent=1, sort_keys=True)
    f.write("\n")
print(json.dumps({k: EXP[k] for k in ("version", "ids", "agents")}))
print(f"upgrade_seed: dump {len(r.stdout)} bytes -> {OUT}/{v}.sql.gz")
print("upgrade_seed: 1 ok, 0 failed")
