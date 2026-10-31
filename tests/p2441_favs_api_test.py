#!/usr/bin/env python3
# kalmido-suite:
"""2.441.0 API tests (#3592): GET /api/favorites/targets across tenants. Stored keys can name anything, so each target is checked
with the rights of its own area. Invented names only.
 - tenant-matrix: favtarget: a person outside the organisation stores the keys of its page, quotation and table: all in "gone",
   no name, route or workspace of them in the answer
 - a member gets them with the organisation as workspace
 - freelancer-matrix: tasks: a person without an organisation gets her own page as Private
usage: p2441_favs_api_test.py <datadir>"""
import sys

from kt import FAILS, B, check, done, fresh, sess, setup

fresh()
a = setup()
a.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["wiki", "sheets", "office", "files"]})
st = a.get(B + "/api/state").json()
ORG = st["me"]["workspaces"][0]["id"]
a.patch(B + "/api/settings", json={"workspace": "org:%d" % ORG, "features": "wiki,sheets,office,files"})
for u in ("berta", "frida"):
    r = a.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": u + "@example.com", "orgs": []})
    check(r.status_code < 300, "user " + u + " " + str(r.status_code))
PG = a.post(B + "/api/wiki/pages", json={"space": "org:%d" % ORG, "path": "Secret handbook"}).json()["id"]
OF = a.post(B + "/api/office/docs", json={"project_title": "Secret film"}).json()["id"]
KEYS = ["r:wiki:%d" % PG, "r:office_doc:%d" % OF]

b = sess("berta", "password123")
check(b.patch(B + "/api/settings", json={"fav_items": KEYS}).status_code == 200, "the keys can be stored by anybody")
t = b.get(B + "/api/favorites/targets")
check(t.status_code == 200 and not t.json()["items"] and sorted(t.json()["gone"]) == sorted(KEYS), "outside: all gone " + t.text[:200])
check("Secret" not in t.text and "org:" not in t.text, "outside: nothing of the targets leaves")

a.patch(B + "/api/settings", json={"fav_items": KEYS})
t = a.get(B + "/api/favorites/targets").json()
check(t["items"].get(KEYS[0], {}).get("name") == "Secret handbook" and t["items"][KEYS[0]]["ws"] == "org:%d" % ORG, "a member reads the page " + str(t)[:200])
check(not t["gone"], "a member: none gone " + str(t["gone"]))

f = sess("frida", "password123")
f.patch(B + "/api/settings", json={"features": "wiki"})
own = f.post(B + "/api/wiki/pages", json={"space": "private", "path": "My notes"}).json()["id"]
f.patch(B + "/api/settings", json={"fav_items": ["r:wiki:%d" % own]})
t = f.get(B + "/api/favorites/targets").json()
check(t["items"].get("r:wiki:%d" % own, {}).get("ws") == "private", "without an organisation: her own page " + str(t)[:200])

done("p2441_favs_api")
sys.exit(1 if FAILS else 0)
