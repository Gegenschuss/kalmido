#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1013.0 (#5513): undo across devices, the rest of #5394 -- budget categories and templates record their steps in the
core's step groups and go back from the list "Recent steps" (POST /api/undo/to/<id>), also from another device. Own
container, invented names only.  freelancer-matrix: undo, budget
 - a category renamed and its limit changed on the laptop: the phone lists the step (area budget, kind budget_cat, its name in
   the label), the copy holds the limit sealed; back -> the old name and limit, redo -> the new ones; its order alone is no step
 - a category into the trash (an entry on it loses it): back -> the category is there and the entry has it again; redo -> in the
   trash again, the entry without it
 - a template's amount changed: the label never names its sealed title ("Budget template"), the copy holds no plain title;
   back -> the old amount, redo -> the new one; into the trash -> back -> it is there again
 - a person without an organisation: the same
usage: p21013_a_budundo_test.py <datadir>"""
import base64
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_ORGCRYPT_PAUSE": "0"}, prefix="P21013AB")
kt.docker_logs_on_first_fail()
FEAT = "budget,collab,comments"
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = kt.me_id(A)
LAP = {"X-Kalmido-Device": "Laptop (Test)"}
FID, Fr = freelancer(B, A, features=FEAT)
M = "2026-11"


def one(q, args=()):
    r = kt.dbx(q, args)
    return r[0][0] if r else None


def lst(s):
    r = s.get(B + "/api/undo")
    return r.json().get("items", []) if r.ok else []


def newest(s):
    x = lst(s)
    return x[0] if x else {}


def back(s, gid):
    r = s.post(B + f"/api/undo/to/{gid}")
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:200]}


def redo(s, gid):
    r = s.post(B + f"/api/undo/{gid}/redo")
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:200]}


def run(s, user, who):
    phone = kt.sess(user, headers={"X-Kalmido-Device": "Phone (Test)"})  # a second sign-in = another device
    lid = s.post(B + "/api/budget/lists", json={}).json()["list_id"]

    def cat(cid):
        return next((x for x in s.get(B + f"/api/budget/{lid}", params={"month": M}).json()["cats"] if x["id"] == cid), None)

    r = s.post(B + f"/api/budget/{lid}/cats", json={"name": "Garden", "kind": "out", "limit": "100"})
    check(r.status_code == 201, f"{who} (setup): a category {r.status_code} {r.text[:160]}")
    cid = r.json()["id"]
    check(str(one("SELECT lim FROM budget_cats WHERE id=?", (cid,)) or "").startswith("kenc1:"), f"{who} (setup): its limit is sealed")

    # ------------------------------------------------------------ a category changed
    r = s.patch(B + f"/api/budget/cats/{cid}", json={"name": "Garden and balcony", "limit": "150"}, headers=LAP)
    g = newest(phone)
    check(r.ok and r.json().get("undo_group") == g.get("id") and g.get("area") == "budget" and g.get("kind") == "budget_cat"
          and "Garden" in (g.get("label") or ""), f"{who}: the phone lists the category's step with its name {r.status_code} {g}")
    snap = one("SELECT snap FROM obj_undo WHERE group_id=?", (g.get("id"),)) or ""
    check("kenc1:" in snap, f"{who}: the copy holds the limit sealed")
    res = back(phone, g["id"])
    c_ = cat(cid) or {}
    check(res.get("undone") == [g["id"]] and c_.get("name") == "Garden" and c_.get("limit") == 100,
          f"{who}: taken back from the phone: the old name and limit {res} {c_}")
    res = redo(phone, g["id"])
    c_ = cat(cid) or {}
    check(res.get("redone") == 1 and c_.get("name") == "Garden and balcony" and c_.get("limit") == 150, f"{who}: redo: the new ones {res} {c_}")
    r = s.patch(B + f"/api/budget/cats/{cid}", json={"sort": 9})
    check(r.ok and "undo_group" not in r.json() and newest(phone).get("id") == g["id"], f"{who}: the order alone is no step {newest(phone)}")

    # ------------------------------------------------------------ a category into the trash and back
    r = s.post(B + f"/api/budget/{lid}/entries", json={"day": f"{M}-05", "amount": "12,50", "kind": "out", "title": "Seeds", "cat_id": cid})
    check(r.status_code == 201, f"{who} (setup): an entry on the category {r.status_code} {r.text[:160]}")
    eid = r.json()["id"]
    r = s.delete(B + f"/api/budget/cats/{cid}", headers=LAP)
    g = newest(phone)
    check(r.ok and g.get("kind") == "budget_cat" and g.get("id") == r.json().get("undo_group") and cat(cid) is None
          and one("SELECT cat_id FROM budget_entries WHERE id=?", (eid,)) is None, f"{who}: the category's trash is a step {r.status_code} {g}")
    res = back(phone, g["id"])
    check(res.get("undone") == [g["id"]] and cat(cid) is not None and one("SELECT cat_id FROM budget_entries WHERE id=?", (eid,)) == cid,
          f"{who}: taken back: the category is there, the entry has it again {res}")
    res = redo(phone, g["id"])
    check(res.get("redone") == 1 and cat(cid) is None and one("SELECT cat_id FROM budget_entries WHERE id=?", (eid,)) is None,
          f"{who}: redo: in the trash again, the entry without it {res}")
    check(back(phone, g["id"]).get("undone") == [g["id"]] and cat(cid) is not None, f"{who}: and back once more")

    # ------------------------------------------------------------ a template
    r = s.post(B + f"/api/budget/{lid}/recurring", json={"title": "Allotment rent", "amount": "40", "kind": "out", "per": "month",
                                                         "start": M, "cat_id": cid})
    check(r.status_code == 201, f"{who} (setup): a template {r.status_code} {r.text[:160]}")
    rid = r.json()["id"]

    def tpl():
        r = s.get(B + f"/api/budget/recurring/{rid}")
        return r.json() if r.ok else {"status": r.status_code}

    r = s.patch(B + f"/api/budget/recurring/{rid}", json={"amount": "45"}, headers=LAP)
    g = newest(phone)
    check(r.ok and g.get("kind") == "budget_rec" and g.get("label") == "Changed: Budget template" and "Allotment" not in (g.get("label") or ""),
          f"{who}: the template's step, never its sealed title in the label {r.status_code} {g}")
    snap = one("SELECT snap FROM obj_undo WHERE group_id=?", (g.get("id"),)) or ""
    check("kenc1:" in snap and "Allotment" not in snap, f"{who}: the copy holds the template sealed")
    res = back(phone, g["id"])
    check(res.get("undone") == [g["id"]] and tpl().get("amount") == 40 and tpl().get("title") == "Allotment rent",
          f"{who}: taken back: the old amount, still readable {res} {tpl()}")
    res = redo(phone, g["id"])
    check(res.get("redone") == 1 and tpl().get("amount") == 45, f"{who}: redo: the new amount {res} {tpl()}")
    r = s.delete(B + f"/api/budget/recurring/{rid}", headers=LAP)
    g = newest(phone)
    check(r.ok and g.get("kind") == "budget_rec" and tpl().get("status") == 404, f"{who}: the template's trash is a step {r.status_code} {g}")
    res = back(phone, g["id"])
    check(res.get("undone") == [g["id"]] and tpl().get("amount") == 45 and rid in [x["id"] for x in s.get(B + f"/api/budget/{lid}/recurring").json()["items"]],
          f"{who}: taken back: the template is there again {res} {tpl()}")


run(A, "alice", "alice")
run(Fr, "frida", "frida")
sys.exit(kt.done("p21013_a_budundo"))
