#!/usr/bin/env python3
"""2.46.1 API tests (part B), own container (start.sh).

 - #1591: the switch "Switch on all modules": off = lists and tasks only whatever the purpose, on = every module (Office
   adds its business modules), stored as mods_all; without the field the purpose's own set as before
 - #1602: POST /api/me/purpose creates the sample project only with examples true (off by default)
 - #1615: Family starts with the shopping list (areas) + ONE list Family (sections Household, Birthdays, Meal plan,
   Deadlines); birthdays / deadlines without a list go to its sections, meals are marked on the task (any list counts);
   old lists of the kinds Birthdays / Household / Meal plan stay the targets
 - #1641: Administration > Encryption lists what is encrypted and what not; every encrypted field of orgcrypt (FIELDS,
   JSON_KEYS) has its category, the list comes with the same rights as the encryption state
"""
import ast
import os
import subprocess
import sys

import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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


# ================================================================== #1641: static: every encrypted field has its category
src = open(os.path.join(N, "..", "kalmido", "core", "orgcrypt.py"), encoding="utf-8").read()
tops = {t.id: n.value for n in ast.parse(src).body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
fields, jkeys, cats = (ast.literal_eval(tops[k]) if k != "PM_CRYPT_CATS" else
                       {ast.literal_eval(kk): None for kk in tops[k].keys} for k in ("FIELDS", "JSON_KEYS", "PM_CRYPT_CATS"))
check(set(fields) <= set(cats) and set(jkeys) <= set(cats), f"#1641: every FIELDS table / JSON_KEYS entry has a category {set(fields) | set(jkeys) - set(cats)}")
check({"files", "tokens"} <= set(cats), "#1641: files and tokens are listed too")

subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
check(A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).ok, "bob")
Bo = sess("bob")

# ================================================================== #1641: the lists
sc = A.get(B + "/api/admin/orgcrypt").json().get("scope") or {}
check("Bank and tax data of the company" in sc.get("encrypted", []) and "Files of organisations" in sc["encrypted"]
      and len(sc["encrypted"]) == len(set(sc["encrypted"])), f"#1641: encrypted, each category once {sc}")
check(sc.get("plain") == ["Tasks", "Notes", "Descriptions", "Comments", "Contacts", "Chats"], f"#1641: not encrypted {sc.get('plain')}")
A.patch(B + "/api/settings", json={"lang": "de"})
sc = A.get(B + "/api/admin/orgcrypt").json()["scope"]
check("Aufgaben" in sc["plain"] and "Bank- und Steuerdaten der Firma" in sc["encrypted"], f"#1641: in the user's language {sc}")
A.patch(B + "/api/settings", json={"lang": "en"})
orgs = A.get(B + "/api/orgs").json().get("orgs") or []
if orgs:
    st = A.get(B + f"/api/orgs/{orgs[0]['id']}/encryption").json()
    check((st.get("scope") or {}).get("plain", [None])[0] == "Tasks", "#1641: the organisation's state carries the lists too")
check(Bo.get(B + "/api/admin/orgcrypt").status_code == 403, "#1641: not for a non-admin")

# ================================================================== #1591: "Switch on all modules"
ALLM = {"cal", "timeline", "matrix", "kanban", "habits", "pomo", "stats", "comments", "collab", "time", "progress", "deps", "fields",
        "family", "events", "contacts", "contracts", "home", "care", "health", "review", "travel", "reading"}
for p in ("me", "family", "team", "office"):
    r = Bo.post(B + "/api/me/purpose", json={"purpose": p, "all_modules": False})
    fs = set(r.json()["features"].split(",")) - {""}
    check(r.ok and not fs & (ALLM | {"clients", "workload", "forms", "office"}), f"#1591: {p} + switch off = lists and tasks only {fs}")
st = Bo.get(B + "/api/state").json()["settings"]
check(st["mods_all"] == "0" and st["purpose"] == "office", "#1591: the switch is stored (mods_all)")
r = Bo.post(B + "/api/me/purpose", json={"purpose": "me", "all_modules": True})
fs = set(r.json()["features"].split(","))
# 2.56.1 (#1808): "all on" = every module of Settings > Modules, whatever the purpose
FULLM = ALLM | {"agents", "clients", "workload", "forms", "office", "wiki", "files", "dispo"}
check(FULLM <= fs, f"#1591/#1808: switch on = every module, also agents, wiki, file store, business {FULLM - fs}")
fs = set(Bo.post(B + "/api/me/purpose", json={"purpose": "office", "all_modules": True}).json()["features"].split(","))
check(ALLM | {"clients", "workload", "forms", "office"} <= fs, "#1591: Office + switch on adds the business modules")
check(Bo.get(B + "/api/state").json()["settings"]["mods_all"] == "1", "#1591: stored on")
# 2.56.1 (#1808, review): the server's module list is the client's FEATS (a new module must go into both)
import re as _re
_feats = _re.findall(r"\['([a-z]+)', N_\(", open(os.path.join(N, "..", "static", "js", "core.js"), encoding="utf-8").read().split("const FEATS = [", 1)[1].split("];", 1)[0])
_pmf = ast.literal_eval(open(os.path.join(N, "..", "kalmido", "family", "family.py"), encoding="utf-8").read().split("PM_FULL = ", 1)[1].split(")\n", 1)[0] + ")")
check(_feats and list(_pmf) == _feats, f"#1808: PM_FULL (server) = FEATS (client) {set(_feats) ^ set(_pmf)}")
# 2.56.1 (#1808): off after "all on" switches every module off again, also agents, wiki, file store, dispatch
fs = set(Bo.post(B + "/api/me/purpose", json={"purpose": "office", "all_modules": False}).json()["features"].split(",")) - {""}
check(not fs & FULLM, f"#1808: switch off after all on = lists and tasks only {fs & FULLM}")
fs = set(Bo.post(B + "/api/me/purpose", json={"purpose": "me"}).json()["features"].split(","))
check("cal" in fs and "kanban" not in fs, f"#1591: without the field the purpose's own set (as before) {fs}")
check(Bo.post(B + "/api/me/purpose", json={"purpose": "me", "all_modules": "yes"}).status_code == 400, "#1591: all_modules must be a boolean")
check(Bo.patch(B + "/api/settings", json={"mods_all": "0", "features": "cal"}).ok and Bo.get(B + "/api/state").json()["settings"]["mods_all"] == "0",
      "#1591: the settings switch (PATCH, one step with the modules)")

# ================================================================== #1602: the sample project only on request
r = A.post(B + "/api/me/purpose", json={"purpose": "team"})
check(r.ok and r.json()["created"] == [] and A.get(B + "/api/state").json().get("sample") is None, "#1602: team without examples: no sample project")
r = A.post(B + "/api/me/purpose", json={"purpose": "software", "examples": False})
check(r.json()["created"] == [], "#1602: software, examples false: no project")
r = A.post(B + "/api/me/purpose", json={"purpose": "software", "examples": True})
check(len(r.json()["created"]) == 1, "#1602: examples true: the software project")

# ================================================================== #1615: the list Family with sections
from datetime import timedelta  # noqa: E402
for u in ("carol", "dave"):
    check(A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"}).ok, u)
Ca, Da = sess("carol"), sess("dave")
Ca.patch(B + "/api/settings", json={"lang": "de"})
r = Ca.post(B + "/api/me/purpose", json={"purpose": "family"})
st = Ca.get(B + "/api/state").json()
fl = {l["family"]: l for l in st["lists"] if l["family"]}
check(r.ok and len(r.json()["created"]) == 2 and set(fl) == {"shopping", "family"}, f"#1615: two starter lists without the switch {sorted(fl)}")
FAM, SHOP = fl["family"]["id"], fl["shopping"]["id"]
check(fl["family"]["name"] == "Familie" and fl["family"]["color"] == "" and fl["shopping"]["color"] == "", "#1615/#1608: named, no colour")
fsec = {x["name"]: x["id"] for x in st["sections"] if x["list_id"] == FAM}
check(list(fsec) == ["Haushalt", "Geburtstage", "Essensplan", "Fristen"], f"#1615: the four sections {list(fsec)}")
check(len([x for x in st["sections"] if x["list_id"] == SHOP]) == 8 and fl["shopping"]["checklist"] == 1, "#1615: the shopping list with its areas, done at the bottom")
check(not [t for t in st["tasks"] if t["list_id"] in (FAM, SHOP)], "#1602: no example entries without the switch")
O = Ca.post(B + "/api/family/occasions", json={"name": "Oma", "date": "1950-03-04"}).json()
check(O["list_id"] == FAM and O["section_id"] == fsec["Geburtstage"], "#1615: a birthday without a list: Familie / Geburtstage")
D = Ca.post(B + "/api/family/deadlines", json={"type": "passport", "who": "Kim", "expires": (testclock.today() + timedelta(days=400)).isoformat()}).json()
check(D["list_id"] == FAM and D["section_id"] == fsec["Fristen"], "#1615: a deadline without a list: Familie / Fristen")
O2 = Ca.post(B + "/api/family/occasions", json={"name": "Opa", "date": "--05-06", "list_id": FAM}).json()
check(O2["section_id"] == fsec["Geburtstage"], "#1615: the list Familie chosen: in its section")
OTHER = Ca.post(B + "/api/lists", json={"name": "Wochenende"}).json()["id"]
M = Ca.post(B + "/api/tasks", json={"title": "Pizza", "list_id": OTHER, "due": testclock.today().isoformat(), "fam": {"kind": "meal"}}).json()
check(M.get("fam") == {"kind": "meal"}, f"#1615: a task marked as a meal {M.get('fam')}")
check(Ca.post(B + "/api/tasks", json={"title": "x", "list_id": OTHER, "fam": {"kind": "meal", "x": 1}}).status_code == 400, "#1615: a meal mark takes nothing else")
ov = Ca.get(B + "/api/family").json()
check(M["id"] in {m["task_id"] for m in ov["meals"]}, "#1615: a meal in any list counts in the week plan")
check(Ca.post(B + "/api/me/purpose", json={"purpose": "family"}).json()["created"] == [], "#1615: once")
# an old list Birthdays stays the target (existing data unchanged)
OLD = Da.post(B + "/api/lists", json={"name": "Geburtstage alt", "family": "birthdays"}).json()["id"]
Da.post(B + "/api/me/purpose", json={"purpose": "family"})
check(not [l for l in Da.get(B + "/api/state").json()["lists"] if l["family"] == "family"], "#1615: an old family list: no list Family")
check(Da.post(B + "/api/family/occasions", json={"name": "X", "date": "--01-02"}).json()["list_id"] == OLD, "#1615: the old Birthdays list stays the target")
MP = Da.post(B + "/api/lists", json={"name": "Essen", "family": "meals"}).json()["id"]
T = Da.post(B + "/api/tasks", json={"title": "Suppe", "list_id": MP, "due": testclock.today().isoformat()}).json()
check(T["id"] in {m["task_id"] for m in Da.get(B + "/api/family").json()["meals"]}, "#1615: an old Meal plan list still counts")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
