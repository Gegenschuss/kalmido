#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.528.0 part B (#4305, A10): the properties of a project (lists.props, 2.412.0 #3552) with `_prev` are merged key by key
under the list's lock instead of replacing the whole value. Two sessions of a person without an organisation, the owner of
a software project (freelancer-matrix: lists):
 - device 1 switches video on, device 2 (still seeing none) switches dependencies off: both stay
 - device 1 (not knowing of device 2's change) switches video back: dependencies stay off
 - a key another device changed meanwhile to another value stays, reported as conflict "props:<key>"; the answer carries
   the merged value (props)
 - the undo of a type change (props as text, _prev with the type) still puts its value back
 - without _prev (agents, old clients): the whole value as before; an invalid value is still 400
usage: p2528_b_props_test.py <datadir>"""
import json

from freelancer_fixture import freelancer, login
from kt import B, check, dbx, done, fresh, setup

fresh(prefix="P2528BP")
A = setup()
FID, D1 = freelancer(B, A)
D2 = login(B, "frida")  # the same person on a second device
r = D1.post(B + "/api/lists", json={"name": "App", "kind": "project", "ptype": "software"})
check(r.ok, f"project {r.status_code} {r.text[:160]}")
SW = r.json()["id"]
U = B + f"/api/lists/{SW}"


def props():
    v = dbx("SELECT props FROM lists WHERE id=?", (SW,))[0][0]
    return json.loads(v) if v else {}


r = D1.patch(U, json={"props": {"video": 1}, "_prev": {"props": {}}})
check(r.ok and props() == {"video": 1} and not r.json().get("conflicts"), f"device 1: video on {r.text[:200]}")
r = D2.patch(U, json={"props": {"deps": 0}, "_prev": {"props": {}}})
check(r.ok and props() == {"deps": 0, "video": 1}, f"device 2: deps off, video of device 1 stays {props()} {r.text[:200]}")
check(json.loads(r.json().get("props") or "{}") == {"deps": 0, "video": 1}, f"the answer carries the merged value {r.text[:200]}")
check(not r.json().get("conflicts"), "no conflict for different keys")

r = D1.patch(U, json={"props": {}, "_prev": {"props": {"video": 1}}})
check(r.ok and props() == {"deps": 0}, f"device 1: video as the type again, deps of device 2 stays {props()}")

# the same key changed elsewhere meanwhile
check(D2.patch(U, json={"props": {"deps": 0, "time": 0}, "_prev": {"props": {"deps": 0}}}).ok and props() == {"deps": 0, "time": 0}, "device 2: time off")
r = D1.patch(U, json={"props": {"deps": 0, "time": 1, "tags": 0}, "_prev": {"props": {"deps": 0}}})
cf = r.json().get("conflicts") or []
check(r.ok and props() == {"deps": 0, "tags": 0, "time": 0}, f"device 1: its time on loses against the newer off, its tags change goes through {props()}")
check([c["field"] for c in cf] == ["props:time"] and cf[0]["server"] == 0 and cf[0]["mine"] == 1, f"conflict props:time {cf}")
# the same new value on both: no conflict
r = D1.patch(U, json={"props": {"deps": 0, "time": 0, "tags": 0}, "_prev": {"props": {"deps": 0}}})
check(r.ok and not r.json().get("conflicts"), f"the value it has already: no conflict {r.text[:200]}")

# the undo of a type change (props as the stored text, _prev with the type): back as before
before = dbx("SELECT props FROM lists WHERE id=?", (SW,))[0][0]
r = D1.patch(U, json={"ptype": "agency"})
after = dbx("SELECT props FROM lists WHERE id=?", (SW,))[0][0]
r = D1.patch(U, json={"ptype": "software", "props": before, "_prev": {"ptype": "agency", "props": after}})
check(r.ok and dbx("SELECT props FROM lists WHERE id=?", (SW,))[0][0] == before, f"the undo of the type change puts props back {props()} {r.text[:200]}")

# without _prev: the whole value as before; invalid values 400
r = D2.patch(U, json={"props": {"video": 1}})
check(r.ok and props() == {"video": 1}, f"without _prev the whole value {props()}")
r = D2.patch(U, json={"props": {"nope": 1}, "_prev": {"props": {}}})
check(r.status_code == 400 and props() == {"video": 1}, f"an unknown key with _prev: 400 {r.status_code}")
raise SystemExit(done("p2528_b_props"))
