#!/usr/bin/env python3
"""2.140.0 API tests, part A (shopping list amounts + prices, recipes -> shopping list, meal plan beyond seven days), own
container (start.sh). Invented items only.
 - #2131: a shopping item carries fam {kind: shop, qty, unit, price} (texts "1,5" / "2,49" are read, nonsense is 400);
   an existing title like "2x Milch" stays as it is; a leading amount of an ingredient goes to the amount field
 - #2132: a list of family "recipes", a recipe (fam kind recipe, serves) with ingredients below a heading and numbered
   steps (left out), preview of its ingredients scaled to servings, a meal pointing to the recipe takes its ingredients,
   an open item of the same name gets the amount added (same unit, or it had none), another unit is skipped
 - #2132: GET /api/family?week=..&days=..: the meal plan of 1-62 days from that Monday, the recipes with their ingredients
 - API v1 + rights: /api/v1/family?days, /api/v1/tasks/{id}/to-shopping with servings / preview, unknown keys 400; a
   stranger gets 404; a meal pointing to a recipe its owner cannot see gets nothing from it
 - freelancer-matrix: personal (a person without an organisation: the same family routes)
usage: p2140_a_api_test.py <datadir>      (P2140A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
from datetime import timedelta

import requests

import testclock
from freelancer_fixture import FEATURES, freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


class Api:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token}

    def __getattr__(self, m):
        return lambda path, **kw: requests.request(m.upper(), B + "/api/v1" + path, headers=self.h, **kw)


def task(S, tid):
    return next((t for t in S.get(B + "/api/state").json()["tasks"] if t["id"] == tid), None)


def open_items(S, lid):
    return {t["title"]: t for t in S.get(B + "/api/state").json()["tasks"] if t["list_id"] == lid and t["status"] == 0 and not t.get("parent_id")}


if not os.environ.get("P2140A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
assert A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"}).ok
today = testclock.today()
mon = today - timedelta(days=today.weekday())

RECIPE = """Lasagne for four

## Ingredients
- 500 g Hackfleisch
- 2 Zwiebeln
- [x] Salz
- 1 Dose Tomaten

## Method
1. Zwiebeln schneiden
2. Alles schichten
"""


def run(S, who):
    # ---------------------------------------------------------------- #2131: amount + price of a shopping item
    SH = S.post(B + "/api/lists", json={"name": "Shop " + who, "family": "shopping"}).json()["id"]
    r = S.post(B + "/api/tasks", json={"title": "Milk", "list_id": SH, "fam": {"kind": "shop", "qty": "1,5", "unit": " l ", "price": "2,49"}})
    check(r.status_code in (200, 201), f"{who}: an item with amount + price " + r.text[:200])
    MILK = r.json()["id"]
    f = task(S, MILK)["fam"]
    check(f == {"kind": "shop", "qty": 1.5, "unit": "l", "price": 2.49}, f"{who}: stored as numbers, unit trimmed {f}")
    for bad in ({"kind": "shop", "qty": -1}, {"kind": "shop", "price": "abc"}, {"kind": "shop", "colour": "red"}, {"kind": "shop", "unit": 5},
                {"kind": "shop", "qty": 1_000_000}):
        check(S.patch(B + f"/api/tasks/{MILK}", json={"fam": bad}).status_code == 400, f"{who}: refused {bad}")
    check(S.patch(B + f"/api/tasks/{MILK}", json={"fam": {"kind": "shop", "qty": "½"}}).ok and task(S, MILK)["fam"] == {"kind": "shop", "qty": 0.5},
          f"{who}: ½ is read, the price the client left out is gone")
    check(S.patch(B + f"/api/tasks/{MILK}", json={"fam": None}).ok and "fam" not in task(S, MILK), f"{who}: amount removed")
    r = S.post(B + "/api/tasks", json={"title": "2x Butter", "list_id": SH})
    check(r.ok and task(S, r.json()["id"])["title"] == "2x Butter" and "fam" not in task(S, r.json()["id"]), f"{who}: a title with an amount stays as it is")

    # ---------------------------------------------------------------- #2132: recipes
    r = S.post(B + "/api/lists", json={"name": "Recipes " + who, "family": "recipes"})
    check(r.ok and next(l for l in S.get(B + "/api/state").json()["lists"] if l["id"] == r.json()["id"])["family"] == "recipes", f"{who}: a Recipes list")
    RL = r.json()["id"]
    RID = S.post(B + "/api/tasks", json={"title": "Lasagne", "list_id": RL, "content": RECIPE, "fam": {"kind": "recipe", "serves": 4}}).json()["id"]
    check(task(S, RID)["fam"] == {"kind": "recipe", "serves": 4}, f"{who}: recipe for four")
    check(S.patch(B + f"/api/tasks/{RID}", json={"fam": {"kind": "recipe", "serves": 0}}).status_code == 400, f"{who}: serves 0 refused")
    r = S.post(B + f"/api/tasks/{RID}/to-shopping", json={"preview": True, "servings": 6, "list_id": SH})
    j = r.json()
    check(r.ok and [(x["name"], x["qty"], x["unit"]) for x in j["items"]] == [("Hackfleisch", 750, "g"), ("Zwiebeln", 3, ""), ("Tomaten", 1.5, "Dose")]
          and j["serves"] == 4 and not any(x["have"] for x in j["items"]), f"{who}: preview for six, no method steps, Salz ticked " + r.text[:300])
    check(len(open_items(S, SH)) == 2, f"{who}: the preview wrote nothing")

    # a meal of the meal plan that points to the recipe (no notes of its own)
    MEALS = S.post(B + "/api/lists", json={"name": "Meals " + who, "family": "meals"}).json()["id"]
    d1 = (today + timedelta(days=25)).isoformat()
    ML = S.post(B + "/api/tasks", json={"title": "Lasagne", "list_id": MEALS, "due": d1, "fam": {"kind": "meal", "recipe": RID, "serves": 2}}).json()["id"]
    check(task(S, ML)["fam"] == {"kind": "meal", "recipe": RID, "serves": 2}, f"{who}: the meal remembers the recipe")
    j = S.post(B + f"/api/tasks/{ML}/to-shopping", json={"preview": True, "servings": 2, "list_id": SH}).json()
    check(j.get("recipe_id") == RID and [(x["name"], x["qty"]) for x in j["items"]][:2] == [("Hackfleisch", 250), ("Zwiebeln", 1)],
          f"{who}: the meal takes the recipe's ingredients, scaled to two {j}")
    j = S.post(B + f"/api/tasks/{ML}/to-shopping", json={"servings": 2, "list_id": SH}).json()
    its = open_items(S, SH)
    check(sorted(x["title"] for x in j["added"]) == ["Hackfleisch", "Tomaten", "Zwiebeln"] and its["Hackfleisch"]["fam"] == {"kind": "shop", "qty": 250, "unit": "g"},
          f"{who}: onto the list with the amounts {j}")
    j = S.post(B + f"/api/tasks/{ML}/to-shopping", json={"list_id": SH, "items": [{"name": "Zwiebeln", "qty": 2}, {"name": "hackfleisch", "qty": 1, "unit": "kg"}]}).json()
    its = open_items(S, SH)
    check([x["title"] for x in j["merged"]] == ["Zwiebeln"] and its["Zwiebeln"]["fam"]["qty"] == 3 and j["skipped"] == ["hackfleisch"] and j["added"] == [],
          f"{who}: same name + unit = the amount added, another unit skipped {j}")
    SALT = S.post(B + "/api/tasks", json={"title": "Salz", "list_id": SH}).json()["id"]
    j = S.post(B + f"/api/tasks/{ML}/to-shopping", json={"list_id": SH, "items": ["1 Prise Salz", "500 g Mehl"]}).json()
    check([x["id"] for x in j["merged"]] == [SALT] and task(S, SALT)["fam"] == {"kind": "shop", "qty": 1, "unit": "Prise"}, f"{who}: an item without an amount gets one {j}")
    check([(x["title"], x["qty"], x["unit"]) for x in j["added"]] == [("Mehl", 500, "g")], f"{who}: a text item: the amount is split off")
    check(S.post(B + f"/api/tasks/{ML}/to-shopping", json={"items": [{"name": "X", "colour": 1}]}).status_code == 400, f"{who}: unknown item key 400")
    check(S.post(B + f"/api/tasks/{ML}/to-shopping", json={"servings": 0}).status_code == 400, f"{who}: servings 0 refused")
    # a meal with notes of its own keeps using them
    M2 = S.post(B + "/api/tasks", json={"title": "Soup", "list_id": MEALS, "due": d1, "content": "- Karotten", "fam": {"kind": "meal", "recipe": RID}}).json()["id"]
    j = S.post(B + f"/api/tasks/{M2}/to-shopping", json={"preview": True}).json()
    check([x["name"] for x in j["items"]] == ["Karotten"] and j["recipe_id"] is None, f"{who}: own notes first {j}")

    # ---------------------------------------------------------------- #2132: the meal plan beyond seven days
    wk = (today + timedelta(days=21)).isoformat()
    ov = S.get(B + f"/api/family?week={wk}&days=14").json()
    wmon = today + timedelta(days=21) - timedelta(days=(today + timedelta(days=21)).weekday())
    inr = wmon.isoformat() <= d1 <= (wmon + timedelta(days=13)).isoformat()
    check(ov["week"] == wmon.isoformat() and ov["days"] == 14 and (ML in {m["task_id"] for m in ov["meals"]}) == inr, f"{who}: 14 days from that Monday")
    m = next((m for m in ov["meals"] if m["task_id"] == ML), None)
    check(not inr or (m["recipe_id"] == RID and m["serves"] == 2), f"{who}: the meal names its recipe")
    ov = S.get(B + "/api/family?week=" + (today + timedelta(days=25)).isoformat()).json()
    check(ov["days"] == 7 and ML in {m["task_id"] for m in ov["meals"]}, f"{who}: the week weeks ahead (default 7 days)")
    rc = next((x for x in ov["recipes"] if x["task_id"] == RID), None)
    check(rc and rc["serves"] == 4 and rc["ingredients"][0] == {"name": "Hackfleisch", "qty": 500, "unit": "g", "text": "500 g Hackfleisch"}
          and ML not in {x["task_id"] for x in ov["recipes"]}, f"{who}: the recipes with their ingredients {rc}")
    check(S.get(B + "/api/family?days=0").status_code == 400 and S.get(B + "/api/family?days=63").status_code == 400, f"{who}: days 1-62")

    # ---------------------------------------------------------------- API v1
    tok = S.post(B + "/api/me/tokens", json={"name": "fam " + who, "scopes": ["read", "tasks:write", "structure"]}).json()["token"]
    V = Api(tok)
    r = V.get(f"/family?week={wk}&days=14")
    check(r.ok and r.json()["days"] == 14 and any(x["task_id"] == RID for x in r.json()["recipes"]), f"{who}: v1 family with days + recipes " + r.text[:200])
    r = V.post(f"/tasks/{RID}/to-shopping", json={"preview": True, "servings": 8, "list_id": SH})
    check(r.ok and r.json()["items"][0]["qty"] == 1000 and r.json()["items"][0]["have"], f"{who}: v1 preview, scaled, on the list already " + r.text[:200])
    check(V.post(f"/tasks/{RID}/to-shopping", json={"foo": 1}).status_code == 400, f"{who}: v1 unknown key 400")
    r = V.get(f"/tasks/{SALT}")
    check(r.ok and r.json()["family"] == {"kind": "shop", "qty": 1, "unit": "Prise"}, f"{who}: v1 task: the amount in family " + r.text[:200])
    r = V.patch(f"/tasks/{SALT}", json={"family": {"kind": "shop", "qty": 2, "unit": "Prise", "price": 0.99}})
    check(r.ok and r.json()["family"]["price"] == 0.99, f"{who}: v1 sets amount + price")
    return RID


# freelancer-matrix: personal (a person without an organisation: the same routes in its private space)
RID = run(A, "alice")
FID, Fr = freelancer(B, A)
run(Fr, "freelancer")

# ---------------------------------------------------------------- rights
EID, Ev = freelancer(B, A, "eve")
check(Ev.post(B + f"/api/tasks/{RID}/to-shopping", json={"preview": True}).status_code == 404, "a stranger: 404")
EM = Ev.post(B + "/api/tasks", json={"title": "Borrowed", "due": today.isoformat(), "fam": {"kind": "meal", "recipe": RID}})
check(EM.status_code in (200, 201), "a meal may name any id " + EM.text[:200])
j = Ev.post(B + f"/api/tasks/{EM.json()['id']}/to-shopping", json={"preview": True}).json()
check(j["items"] == [] and j["recipe_id"] is None, "… but gets nothing of a recipe it cannot see")
check(Ev.post(B + f"/api/tasks/{EM.json()['id']}/to-shopping", json={}).status_code == 400, "… and nothing goes to its list")
check(not any(x["task_id"] == RID for x in Ev.get(B + "/api/family").json()["recipes"]), "a stranger does not see the recipe")

print(f"p2140_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
