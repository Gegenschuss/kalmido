#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.565.0 D (#4713) API: an answer button holds 200 characters (was 80), own container (start.sh).
 - chat choices: a label of 200 characters stays whole, 250 are cut hard to 200 (no 400), an 80-character label of an
   older host stays valid; the same for a comment's choices and an approval card's yes / no labels
 - next_step: 200 characters become the button whole, 201 -> 400
 - a person without an organisation with a personal agent: the same in the own chat
freelancer-matrix: agents
usage: p2565_d_choices_test.py <datadir>      (KMT_NOSTART=1 / P2565D_NOSTART=1: a running server)"""
import sys

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, check, sess

V = B + "/api/v1"
L200 = ("Run the whole release check on the test machine, compare the result with the last build and write a short list "
        "of every difference with its area, then wait for my answer before anything goes")[:200].ljust(200, ".")
L250 = L200 + " and this tail is longer than any button may hold, it is cut away by the server at 200 characters ok"[:50]
assert len(L200) == 200 and len(L250) == 250

kt.fresh(prefix="P2565D")
requests.post(B + "/api/auth/setup", headers=kt.H, json={"username": "alice", "display_name": "Alice", "password": "password123"})
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ORG = ME["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
L = A.post(B + "/api/lists", json={"name": "App dev", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
T = A.post(B + "/api/tasks", json={"title": "Release", "list_id": L}).json()["id"]


def say(uid, h, **b):
    return requests.post(V + f"/agent/chats/{uid}", headers=h, json=b)


def labels(j):
    return [x["label"] for x in (j.get("choices") or {}).get("choices") or []]


def chat_cases(who, uid, h):
    r = say(uid, h, body="Which one?", choices=[{"id": "long", "label": L200}, {"id": "cut", "label": L250}, {"id": "old", "label": "o" * 80}])
    check(r.status_code == 201, f"{who}: choices with 200 / 250 characters are accepted {r.status_code} {r.text[:200]}")
    lb = labels(r.json()) if r.ok else []
    check(lb[:1] == [L200], f"{who}: a label of 200 characters stays whole {[len(x) for x in lb]}")
    check(len(lb) > 1 and lb[1] == L250[:200], f"{who}: 250 characters are cut hard to 200 {[len(x) for x in lb]}")
    check(len(lb) > 2 and lb[2] == "o" * 80, f"{who}: an older host's 80 characters stay valid")
    r = say(uid, h, body="Next?", next_step=L200)
    nx = [x for x in (r.json().get("choices") or {}).get("choices") or [] if x.get("next")] if r.ok else []
    check(r.status_code == 201 and [x["label"] for x in nx] == [L200], f"{who}: next_step of 200 characters is the button whole {r.status_code} {r.text[:200]}")
    r = say(uid, h, body="Next?", next_step=L200 + "x")
    check(r.status_code == 400, f"{who}: next_step of 201 characters -> 400 ({r.status_code})")
    r = say(uid, h, approval={"title": "Ship it", "yes_label": L250, "no_label": L200})
    lb = labels(r.json()) if r.ok else []
    check(r.status_code == 201 and lb == [L250[:200], L200], f"{who}: approval labels keep 200 characters {r.status_code} {[len(x) for x in lb]}")


chat_cases("member", ME["id"], AGH)
# a comment's buttons go through the same cleaning
r = requests.post(V + f"/tasks/{T}/comments", headers=AGH, json={"body": "Pick", "choices": [{"id": "a", "label": L250}, {"id": "b", "label": L200}]})
lb = labels(r.json()) if r.ok else []
check(r.ok and lb == [L250[:200], L200], f"comment: labels keep 200 characters, 250 are cut {r.status_code} {[len(x) for x in lb]} {r.text[:200]}")
# the person reads the full label in the chat
m = [x for x in A.get(B + f"/api/agents/{AG}/chat").json()["messages"] if x.get("body") == "Which one?"]
check(m and labels(m[0])[0] == L200, "member: the chat shows the 200-character label whole")

FID, Fr = freelancer(B, A)
fa = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida bot", "scopes": ["read", "tasks:write", "comments"]}).json()
ft = Fr.post(B + f"/api/my/agents/{fa['id']}/token", json={}).json()
chat_cases("freelancer", FID, {"Authorization": "Bearer " + ft["token"]})

sys.exit(kt.done("p2565_d_choices"))
