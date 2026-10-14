#!/usr/bin/env python3
"""2.43.0 API tests, part A (calculating with custom fields), own container (start.sh). Invented names and amounts only.
 - #1328 formula fields: + - * / with precedence, brackets, round(x, n), field names ({Name} or one word), empty fields = 0
   or an empty result, division by 0 = empty, errors with the position / field name, no field may use itself, circular
   references are refused, renaming a field keeps the formula (shown with the new name), writing a formula = 400 (web,
   batch and the agent API), the delete count names the formulas that use a field, the value reaches the agent read-only
 - #1328 sum row + key figures: PATCH /api/lists/{id} {col_sums, kpis} for the owner / list admins only, the list carries
   them; GET /api/lists/{id}/kpis computes sum / count / average / ratio with open / done and a choice as condition;
   members read, an agent only with the list shared, never a health list
usage: p2430_a_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
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


if not os.environ.get("P2430_A_NOSTART"):  # (a quick local run against a running server sets it)
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,fields,life,health"})
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}

L = A.post(B + "/api/lists", json={"name": "Claims", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"})


def field(name, typ, **kw):
    r = A.post(B + f"/api/lists/{L}/fields", json={"name": name, "type": typ, **kw})
    return r


FA = field("Amount", "number", options={"unit": "EUR"}).json()
FR = field("Refunded", "number", options={"unit": "EUR"}).json()
FS = field("State", "select", options={"options": [{"name": "open"}, {"name": "rejected"}]}).json()
FT = field("Note", "text").json()
check(FA.get("id") and FR.get("id") and FS.get("id") and FT.get("id"), "setup: fields")
OPEN, REJ = (o["id"] for o in FS["options"]["options"])

# ================================================================== #1328: formula fields
r = field("Outstanding", "formula", formula="{Amount} - Refunded", options={"unit": "EUR"})
FO = r.json()
check(r.ok and FO["type"] == "formula" and FO["options"]["expr"] == f"{{#{FA['id']}}} - {{#{FR['id']}}}" and FO["options"]["formula"] == "{Amount} - {Refunded}"
      and FO["options"]["unit"] == "EUR", f"#1328: a formula is stored with field ids, shown with names {r.status_code} {r.text[:300]}")
for bad, want in [("{Amount} * (2", "character 14"), ("2 +", "ends too early"), ("{Amount} $ 3", "“$”"), ("{Nope} + 1", "Nope"),
                  ("{Note} * 2", "Note"), ("round(1, 9)", "digits"), ("", "empty"), ("pow(2, 3)", "pow")]:
    r = field("Bad", "formula", formula=bad)
    check(r.status_code == 400 and want in r.json().get("error", ""), f"#1328: {bad!r} refused with a clear message {r.status_code} {r.text[:200]}")
r = A.patch(B + f"/api/fields/{FO['id']}", json={"formula": "{Outstanding} + 1"})
check(r.status_code == 400 and "itself" in r.json().get("error", ""), f"#1328: a formula cannot use itself {r.text[:200]}")
FQ = field("Rate", "formula", formula="round({Refunded} / {Amount} * 100, 1)").json()
FP = field("Prec", "formula", formula="2 + 3 * (4 - 1) - 10 / 4 + -1").json()
FB = field("Blank", "formula", formula="{Amount} + {Refunded}", options={"empty": "blank"}).json()
check(FQ.get("id") and FP.get("id") and FB.get("id"), "#1328: formulas with round, precedence, empty = blank")
r = A.patch(B + f"/api/fields/{FQ['id']}", json={"formula": "{Outstanding} + {Rate}"})
check(r.status_code == 400 and "itself" in r.json().get("error", ""), f"#1328: own name refused {r.text[:200]}")
r = A.patch(B + f"/api/fields/{FO['id']}", json={"formula": "{Amount} - {Refunded} + {Rate} * 0"})
check(r.ok, f"#1328: a formula may read another formula {r.text[:200]}")
r = A.patch(B + f"/api/fields/{FQ['id']}", json={"formula": "{Outstanding} / 2"})
check(r.status_code == 400 and "circular" in r.json().get("error", ""), f"#1328: a circular reference is refused {r.text[:200]}")
A.patch(B + f"/api/fields/{FO['id']}", json={"formula": "{Amount} - {Refunded}"})


def mk(title, amount=None, refunded=None, state=None):
    fv = {}
    if amount is not None:
        fv[str(FA["id"])] = amount
    if refunded is not None:
        fv[str(FR["id"])] = refunded
    if state:
        fv[str(FS["id"])] = state
    r = A.post(B + "/api/tasks", json={"title": title, "list_id": L, "fields": fv})
    assert r.ok, r.text
    return r.json()


T1 = mk("Pharmacy", "100", "40", OPEN)
T2 = mk("Physio", "50", "50", OPEN)
T3 = mk("Glasses", "80", None, REJ)
T4 = mk("Empty one")
fo, fq, fp, fb = (str(x["id"]) for x in (FO, FQ, FP, FB))
check(T1["fields"].get(fo) == "60" and T1["fields"].get(fq) == "40" and T1["fields"].get(fp) == "7.5" and T1["fields"].get(fb) == "140",
      f"#1328: computed values on the new task {T1['fields']}")
check(T3["fields"].get(fo) == "80" and T3["fields"].get(fq) == "0" and fb not in T3["fields"], f"#1328: empty = 0, or an empty result {T3['fields']}")
check(fq not in T4["fields"] and T4["fields"].get(fo) == "0", f"#1328: division by 0 = empty {T4['fields']}")
st = A.get(B + "/api/state").json()
tt = {t["id"]: t for t in st["tasks"]}
check(tt[T2["id"]]["fields"].get(fo) == "0" and tt[T2["id"]]["fields"].get(fq) == "100", f"#1328: the state carries the values {tt[T2['id']]['fields']}")
r = A.patch(B + f"/api/tasks/{T1['id']}", json={"fields": {str(FR["id"]): "70"}})
check(r.ok and r.json()["fields"].get(fo) == "30", f"#1328: a changed number changes the formula at once {r.text[:200]}")
r = A.patch(B + f"/api/tasks/{T1['id']}", json={"fields": {fo: "5"}})
check(r.status_code == 400 and "calculated" in r.json().get("error", ""), f"#1328: writing a formula = 400 {r.status_code} {r.text[:200]}")
r = A.post(B + "/api/tasks/batch", json={"ids": [T1["id"]], "action": "patch", "data": {"fields": {fo: "5"}}})
check(A.get(B + "/api/state").json()["tasks"] and [t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == T1["id"]][0]["fields"].get(fo) == "30",
      f"#1328: a batch cannot set it either {r.status_code} {r.text[:200]}")
# renaming a field: the formula follows (stored with ids)
A.patch(B + f"/api/fields/{FA['id']}", json={"name": "Amount total"})
fs = {f["id"]: f for f in A.get(B + "/api/state").json()["fields"]}
check(fs[FO["id"]]["options"]["formula"] == "{Amount total} - {Refunded}", f"#1328: renaming shows the new name in the formula {fs[FO['id']]['options']}")
r = A.patch(B + f"/api/tasks/{T2['id']}", json={"fields": {str(FA["id"]): "60"}})
check(r.ok and r.json()["fields"].get(fo) == "10", "#1328: and still computes")
r = A.get(B + f"/api/fields/{FR['id']}/count")
check(r.ok and set(r.json().get("used_by", [])) >= {"Outstanding", "Rate"}, f"#1328: the delete count names the formulas that use it {r.text[:200]}")
r = A.get(B + f"/api/fields/{FT['id']}/count")
check(r.ok and r.json().get("used_by") == [], "#1328: a field no formula uses")
# a member without admin rights cannot add a formula field
r = Bo.post(B + f"/api/lists/{L}/fields", json={"name": "Mine", "type": "formula", "formula": "1 + 1"})
check(r.status_code == 403, f"#1328: a member cannot add fields {r.status_code}")

# ================================================================== #1328: sum row + key figures (settings of the list)
KP = [{"title": "Outstanding total", "agg": "sum", "field": FO["id"], "state": "open"},
      {"title": "Refunded", "agg": "sum", "field": FR["id"]},
      {"title": "Rejected", "agg": "count", "cond_field": FS["id"], "cond_value": REJ},
      {"title": "Rate", "agg": "ratio", "field": FR["id"], "field2": FA["id"]},
      {"title": "Average", "agg": "avg", "field": FA["id"], "state": "done"}]
r = Bo.patch(B + f"/api/lists/{L}", json={"kpis": KP})
check(r.status_code == 403, f"#1328: a member without admin rights cannot set key figures {r.status_code}")
r = Bo.patch(B + f"/api/lists/{L}", json={"col_sums": {f"f:{FA['id']}": "avg"}})
check(r.status_code == 403, f"#1328: … nor the sum row {r.status_code}")
r = A.patch(B + f"/api/lists/{L}", json={"kpis": [{"agg": "sum", "field": FS["id"]}]})
check(r.status_code == 400, f"#1328: a key figure needs a number field {r.status_code}")
r = A.patch(B + f"/api/lists/{L}", json={"kpis": [{"agg": "count", "cond_field": FS["id"], "cond_value": "nope"}]})
check(r.status_code == 400, f"#1328: an unknown option as condition is refused {r.status_code}")
r = A.patch(B + f"/api/lists/{L}", json={"col_sums": {f"f:{FA['id']}": "median"}})
check(r.status_code == 400, f"#1328: an unknown calculation is refused {r.status_code}")
r = A.patch(B + f"/api/lists/{L}", json={"kpis": KP, "col_sums": {f"f:{FA['id']}": "avg", f"f:{FO['id']}": "sum"}})
check(r.ok, f"#1328: the owner sets key figures and the sum row {r.status_code} {r.text[:200]}")
lst = [x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == L][0]
check(lst.get("col_sums") == {f"f:{FA['id']}": "avg", f"f:{FO['id']}": "sum"} and len(lst.get("kpis", [])) == 5 and "tb_sums" not in lst and "fx_kpis" not in lst,
      f"#1328: the list carries both for every member {lst.get('col_sums')} {len(lst.get('kpis', []))}")
A.post(B + f"/api/tasks/{T2['id']}/complete")
# T1 100/70 open, T2 60/50 done, T3 80/- rejected open, T4 empty open
r = Bo.get(B + f"/api/lists/{L}/kpis")
k = {x["title"]: x for x in r.json().get("data", [])} if r.ok else {}
check(r.ok and k["Outstanding total"]["value"] == 110 and k["Outstanding total"]["unit"] == "EUR", f"#1328: sum of open tasks {k.get('Outstanding total')}")
check(k.get("Refunded", {}).get("value") == 120, f"#1328: sum of all {k.get('Refunded')}")
check(k.get("Rejected", {}).get("value") == 1 and k["Rejected"]["unit"] == "", f"#1328: count with a choice as condition {k.get('Rejected')}")
check(abs((k.get("Rate", {}).get("value") or 0) - 120 / 240 * 100) < 0.001 and k["Rate"]["unit"] == "%", f"#1328: ratio in % {k.get('Rate')}")
check(k.get("Average", {}).get("value") == 60, f"#1328: average of done tasks {k.get('Average')}")
r = Ca.get(B + f"/api/lists/{L}/kpis")
check(r.status_code == 404, f"#1328: someone without the list sees no key figures {r.status_code}")

# ================================================================== agents: read only, only shared lists, never health
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "helper", "display_name": "Helper"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x"), **H}
r = requests.get(V + f"/lists/{L}/kpis", headers=AGH)
check(r.status_code == 404, f"#1328: an agent without the list sees no key figures {r.status_code}")
A.put(B + f"/api/lists/{L}/members", json={"user_id": ag.get("id"), "role": "edit"})
r = requests.get(V + f"/lists/{L}/kpis", headers=AGH)
check(r.ok and len(r.json().get("data", [])) == 5, f"#1328: with the list shared it reads them {r.status_code} {r.text[:200]}")
r = requests.get(V + f"/tasks/{T1['id']}", headers=AGH)
tj = r.json() if r.ok else {}
tj = tj.get("data", tj)
check(r.ok and tj.get("fields", {}).get(fo) == "30", f"#1328: the agent reads the computed value {r.status_code} {str(tj.get('fields'))[:200]}")
r = requests.patch(V + f"/tasks/{T1['id']}", headers=AGH, json={"fields": {fo: "1"}})
check(r.status_code == 400, f"#1328: the agent cannot set a formula {r.status_code} {r.text[:200]}")
r = A.post(B + "/api/life/health", json={"type": "appointment", "title": "Checkup", "who": "Kim", "date": "2030-01-10", "time": "09:30"})
HL = r.json()["tasks"][0]["list_id"] if r.ok else None
if HL:
    A.post(B + f"/api/lists/{HL}/fields", json={"name": "Cost", "type": "number"})
    hf = [f for f in A.get(B + "/api/state").json()["fields"] if f["list_id"] == HL]
    A.patch(B + f"/api/lists/{HL}", json={"kpis": [{"title": "Cost", "agg": "sum", "field": hf[0]["id"] if hf else None}]})
    A.put(B + f"/api/lists/{HL}/members", json={"user_id": ag.get("id"), "role": "edit"})
    r = requests.get(V + f"/lists/{HL}/kpis", headers=AGH)
    check(r.status_code == 404, f"#1328: never the key figures of a health list for an agent {r.status_code}")
    check(A.get(B + f"/api/lists/{HL}/kpis").ok, "#1328: the owner sees them")
else:
    check(False, f"setup: a health list {r.status_code} {r.text[:200]}")

print(f"p2430_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
