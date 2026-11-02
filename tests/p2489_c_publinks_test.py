#!/usr/bin/env python3
"""2.489.0 C (#2656): "Allow public links" per kind (Settings > Administration) under the instance switch. Invented data
only. freelancer-matrix: files
 - PATCH /api/admin/settings public_links_off = [kind, ...] (lists files uploads calendar signoff wiki forms portal pay);
   another value 400; /api/about and /api/state carry the kinds switched off; nothing set = every kind on (an existing
   server keeps its behaviour)
 - a kind off: the server refuses to make a link of that kind (409 like the instance switch) and a link made before does
   not open (the same answer as with the instance switch off); the other kinds keep working; on again = the old link
   opens again (nothing deleted)
 - switching a kind back on opens the server: it asks for the account password like the instance switch; off needs none
 - the instance switch off = every kind off, whatever the kinds say; only instance admins change the kinds (freelancer 403)
 - a person without an organisation is held by the same switch (own project link refused while lists are off)
usage: p2489_c_publinks_test.py <datadir>"""
# kalmido-suite: fresh
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, docker_logs_on_first_fail, done, fresh, setup

fresh(prefix="P2489CL")
docker_logs_on_first_fail()
A = setup()
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "comments,collab,files,docs"})
A.patch(B + "/api/admin/settings", json={"password": "password123", "public_links": True})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
S = "/api/admin/settings"


def off_now():
    return A.get(B + "/api/about").json().get("public_links_off"), A.get(B + "/api/state").json().get("public_links_off")


def page(p):
    return requests.get(B + p, allow_redirects=False)


check(off_now() == ([], []), f"a server without the setting: every kind on {off_now()}")
for bad in (["nope"], "lists", [1], {"lists": False}):
    check(A.patch(B + S, json={"public_links_off": bad}).status_code == 400, f"invalid public_links_off {bad!r}: 400")
check(off_now() == ([], []), "nothing stored after invalid input")

# a project link and an upload link, made while everything is on
L = A.post(B + "/api/lists", json={"name": "Example shoot"}).json()["id"]
r = A.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"})
check(r.ok, "a project link " + r.text[:200])
LP = r.json()["link"]["url"]
LP = LP[LP.index("/s/"):]
check(page(LP).status_code == 200, "the project link opens")
F = A.post(B + "/api/files/folders", json={"name": "Example uploads", "space": f"org:{ORG}"}).json()["id"]
U = f"/api/files/nodes/{F}/requests"
r = A.post(B + U, json={"title": "Your files", "days": 14})
check(r.status_code == 201, "an upload link " + r.text[:200])
UP = r.json()["url"]
UP = UP[UP.index("/u/"):]
check(page(UP).status_code == 200, "the upload link opens")

# the answers of the instance switch off, to compare with
A.patch(B + S, json={"public_links": False})
GONE_L, GONE_U = page(LP).status_code, page(UP).status_code
check(GONE_L != 200 and GONE_U != 200, f"instance switch off: neither opens {GONE_L} {GONE_U}")
A.patch(B + S, json={"password": "password123", "public_links": True})

# ---- lists off
r = A.patch(B + S, json={"public_links_off": ["lists"]})
check(r.ok and r.json().get("public_links_off") == ["lists"], "lists off: no password needed " + r.text[:200])
check(off_now() == (["lists"], ["lists"]) and A.get(B + "/api/state").json()["public_links"] is True, "about + state: lists off, the instance switch stays on")
check(page(LP).status_code == GONE_L, f"lists off: the project link does not open, like the instance switch {page(LP).status_code}")
L2 = A.post(B + "/api/lists", json={"name": "Second shoot"}).json()["id"]
check(A.put(B + f"/api/lists/{L2}/public-link", json={"mode": "view"}).status_code == 409, "lists off: no new project link (409)")
check(A.get(B + f"/api/lists/{L2}/public-link").json().get("enabled") is False, "lists off: the dialog hears it")
check(page(UP).status_code == 200, "lists off: the upload link still opens")
r = A.post(B + U, json={"title": "Still fine", "days": 3})
check(r.status_code == 201, "lists off: a new upload link still works " + r.text[:120])

# ---- uploads off, lists back on: asks for the password
r = A.patch(B + S, json={"public_links_off": ["uploads"]})
check(r.status_code == 403 and r.json().get("password_needed") is True, f"a kind back on asks for the password {r.status_code}")
check(off_now()[0] == ["lists"], "without the password nothing changed")
r = A.patch(B + S, json={"public_links_off": ["uploads"], "password": "password123"})
check(r.ok and r.json().get("public_links_off") == ["uploads"], "with the password: uploads off, lists on " + r.text[:200])
check(page(LP).status_code == 200, "lists on again: the old project link opens (nothing deleted)")
check(page(UP).status_code == GONE_U, f"uploads off: the upload link does not open, like the instance switch {page(UP).status_code}")
check(A.post(B + U, json={"title": "Off", "days": 3}).status_code == 409, "uploads off: no new upload link (409)")
check(A.get(B + U).json().get("public_links") is False, "uploads off: the dialog hears it")

# ---- the instance switch off = all off; kinds stay stored
A.patch(B + S, json={"public_links": False})
check(page(LP).status_code == GONE_L and A.put(B + f"/api/lists/{L2}/public-link", json={"mode": "view"}).status_code == 409,
      "instance switch off: lists off although their kind is on")
r = A.patch(B + S, json={"public_links_off": [], "password": "password123"})
check(r.ok and page(LP).status_code == GONE_L and page(UP).status_code == GONE_U, "every kind on, the instance switch still off: nothing opens")
A.patch(B + S, json={"password": "password123", "public_links": True})
check(page(LP).status_code == 200 and page(UP).status_code == 200, "both on again: both links open")

# ---- a person without an organisation: no admin of the kinds, held by them like everybody
FID, Fr = freelancer(B, A)
check(Fr.patch(B + S, json={"public_links_off": []}).status_code == 403, "freelancer: the kinds are the instance admin's (403)")
FL = Fr.post(B + "/api/lists", json={"name": "Frida's project"}).json()["id"]
A.patch(B + S, json={"public_links_off": ["lists"]})
check(Fr.put(B + f"/api/lists/{FL}/public-link", json={"mode": "view"}).status_code == 409, "freelancer, lists off: no project link")
A.patch(B + S, json={"public_links_off": [], "password": "password123"})
check(Fr.put(B + f"/api/lists/{FL}/public-link", json={"mode": "view"}).ok, "freelancer, lists on: the project link")

sys.exit(done("p2489_c_publinks"))
