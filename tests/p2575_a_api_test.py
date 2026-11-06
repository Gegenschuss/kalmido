#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.575.0 part A (#3778): own module cards (accounts/modcards.py). Own container (mode workspaces). Invented names only.
tenant-matrix: modcard
freelancer-matrix: modcards
 - an organisation's admin makes cards (modules, default card, people); a member reads only the cards that apply to them
   and cannot make / change / delete one (403); a stranger sees and changes nothing (404), not a private card either
 - the cap: assigned cards add up (no default on top), without an assignment the default card; /api/state carries it per
   workspace (mods_cap); the server refuses a module outside the cap while the organisation is the workspace (space,
   setting workspace, an object of the organisation by id) and lets it through in Private; nothing is deleted
 - the main switch on (an agent's setup proposal writes only that) does not reach past the cap
 - one default card per organisation; a module added later is "new" on a card until it is saved again; 409 on an old version
 - the setting ws_mods_off is checked strictly
 - a person without an organisation: own cards in Private (make, change, apply through the settings, delete); no default,
   no people, no organisation space
usage: p2575_a_api_test.py <datadir>"""
import ast
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, FAILS, OKS, check, sess  # noqa: E402,F401

FEAT = "cal,events,contacts,comments,collab,files,docs,wiki,sheets,time,pomo,habits"

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2575A")

# the modules a card can hold = every module of Settings > Modules (family.py PM_FULL) + the documents (modcards.py keeps a copy)
_src = open(os.path.join(N, "..", "kalmido", "family", "family.py"), encoding="utf-8").read()
PM_FULL = ast.literal_eval(re.search(r"^PM_FULL = (\(.*?\))\n", _src, re.S | re.M).group(1))


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
uid, S = {}, {}
for u in ("bob", "gina", "rita"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo, Gi, Ri = S["bob"], S["gina"], S["rita"]
BOB, GINA = uid["bob"], uid["gina"]

r = A.post(B + "/api/admin/orgs", json={"name": "Northwind"})
assert r.status_code in (200, 201), r.text
K = r.json()["id"]
sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (K, ALICE), write=True)
for who in (BOB, GINA):
    mail = sql("SELECT email FROM users WHERE id=?", (who,))[0][0]
    r = A.put(B + f"/api/orgs/{K}/members", json={"email": mail, "role": "member"})
    assert r.ok, r.text
WS = f"org:{K}"

# an organisation's page before any card (it stays: nothing is deleted)
r = A.post(B + "/api/wiki/pages", json={"space": WS, "path": "Team/Handbook", "body": "hello"})
check(r.status_code == 201, "an organisation's knowledge page " + r.text[:160])
PG = r.json().get("id") if r.status_code == 201 else 0
check(Bo.get(B + f"/api/wiki/pages/{PG}").status_code == 200, "no card yet: Bob opens the organisation's page")
check(Bo.get(B + f"/api/modcards?space={WS}").json().get("cap") is None, "no card yet: no cap")
check(Bo.get(B + f"/api/modcards?space={WS}").json().get("mods") == list(PM_FULL) + ["docs"], "a card holds every module of Settings > Modules")

# ================================================================== the admin's cards
r = A.post(B + "/api/modcards", json={"space": WS, "name": "Basics", "icon": "users", "mods": ["wiki", "time"], "dflt": True})
check(r.status_code == 201 and r.json()["card"]["dflt"] and r.json()["card"]["mods"] == ["time", "wiki"], "admin: the default card " + r.text[:200])
C1 = r.json()["card"]["id"]
r = A.post(B + "/api/modcards", json={"space": WS, "name": "Tables", "mods": ["sheets"], "people": [BOB]})
check(r.status_code == 201 and r.json()["card"]["people"] == [BOB], "admin: a card for Bob " + r.text[:200])
C2 = r.json()["card"]["id"]
r = A.post(B + "/api/modcards", json={"space": WS, "name": "Time", "icon": "clock", "mods": ["time"], "people": [BOB]})
check(r.status_code == 201, "admin: a second card for Bob")
C3 = r.json()["card"]["id"]
check(A.post(B + "/api/modcards", json={"space": WS, "name": "Bad", "mods": ["nope"]}).status_code == 400, "an unknown module is a 400")
check(A.post(B + "/api/modcards", json={"space": WS, "name": "Bad", "mods": [], "people": [uid["rita"]]}).status_code == 400,
      "a person outside the organisation cannot get a card")
check(A.post(B + "/api/modcards", json={"space": WS, "name": "", "mods": []}).status_code == 400, "a card needs a name")

j = A.get(B + f"/api/modcards?space={WS}").json()
check(j.get("admin") and len(j.get("cards") or []) == 3 and {m["id"] for m in j.get("members") or []} >= {BOB, GINA},
      "admin: every card and the members to assign")

# ================================================================== rights: a member, a stranger
j = Bo.get(B + f"/api/modcards?space={WS}").json()
check(not j.get("admin") and sorted(c["id"] for c in j.get("cards") or []) == sorted([C2, C3]) and "members" not in j,
      "member: only the own cards, no member list " + str(j)[:200])
check(j.get("cap") == ["time", "sheets"], "member: the cap = the union of the own cards (no default on top) " + str(j.get("cap")))
check(Gi.get(B + f"/api/modcards?space={WS}").json().get("cap") == ["time", "wiki"], "without a card: the default card")
check(Bo.post(B + "/api/modcards", json={"space": WS, "name": "Mine", "mods": ["wiki"]}).status_code == 403, "member: no new card (403)")
check(Bo.patch(B + f"/api/modcards/{C2}", json={"mods": ["wiki", "sheets"]}).status_code == 403, "member: cannot widen a card (403)")
check(Bo.delete(B + f"/api/modcards/{C2}").status_code == 403, "member: cannot delete a card (403)")
check(Ri.get(B + f"/api/modcards?space={WS}").status_code == 404, "stranger: the organisation's cards are not there (404)")
check(Ri.patch(B + f"/api/modcards/{C1}", json={"name": "x"}).status_code == 404, "stranger: cannot change a card (404)")
check(Ri.delete(B + f"/api/modcards/{C1}").status_code == 404, "stranger: cannot delete a card (404)")
st = Bo.get(B + "/api/state").json()
w = next((x for x in (st.get("me") or {}).get("workspaces") or [] if x.get("id") == K), {})
check(w.get("mods_cap") == ["time", "sheets"], "state: the cap per workspace " + str(w)[:160])

# ================================================================== the server's lock
check(Bo.get(B + f"/api/wiki?space={WS}").status_code == 403, "Bob: knowledge pages of the organisation refused (not on his cards)")
check(Bo.get(B + f"/api/wiki/pages/{PG}").status_code == 403, "Bob: the organisation's page by id refused")
check(Bo.get(B + "/api/wiki?space=private").status_code == 200, "Bob: his own pages in Private stay")
check(Bo.get(B + f"/api/sheets?space={WS}").status_code != 403, "Bob: tables (on his card) work in the organisation")
check(Gi.get(B + f"/api/sheets?space={WS}").status_code == 403, "Gina: tables refused (not on the default card)")
check(Gi.get(B + f"/api/wiki/pages/{PG}").status_code == 200, "Gina: the page (on the default card) opens")
Bo.patch(B + "/api/settings", json={"workspace": WS})
check(Bo.get(B + "/api/wiki").status_code == 403, "Bob: the setting workspace counts as well")
# the main switch on (what an agent's setup proposal writes) does not reach past the cap
Bo.patch(B + "/api/settings", json={"features": FEAT + ",reading"})
check(Bo.get(B + "/api/wiki").status_code == 403, "the main switch does not reach past the cap")
# review job 2963: the budget has its own routes and is refused outside the cap as well (it was only hidden in the app)
Bo.patch(B + "/api/settings", json={"features": FEAT + ",reading,budget"})
check(Bo.get(B + f"/api/budget?space={WS}").status_code == 403, "Bob: the budget of the organisation refused (not on his cards)")
check(Bo.get(B + "/api/budget?space=private").status_code != 403, "Bob: his own budget in Private stays")
Bo.patch(B + "/api/settings", json={"workspace": "private"})
check(sql("SELECT COUNT(*) FROM wiki_pages WHERE id=?", (PG,))[0][0] == 1, "nothing is deleted")

# ================================================================== default, new module, version
r = A.post(B + "/api/modcards", json={"space": WS, "name": "All", "mods": ["wiki", "sheets", "time"], "dflt": True})
check(r.status_code == 201, "a second default card")
C4 = r.json()["card"]["id"]
d = {c["id"]: c for c in A.get(B + f"/api/modcards?space={WS}").json()["cards"]}
check(d[C4]["dflt"] and not d[C1]["dflt"], "one default card per organisation")
check(Gi.get(B + f"/api/sheets?space={WS}").status_code != 403, "Gina follows the new default card")
sql("UPDATE module_cards SET known=? WHERE id=?", ("cal,timeline", C2), write=True)  # as if saved before an update
c2 = next(c for c in A.get(B + f"/api/modcards?space={WS}").json()["cards"] if c["id"] == C2)
check("sheets" in c2["new_mods"] and "wiki" in c2["new_mods"], "a module added later is new on the card")
check(c2["mods"] == ["sheets"], "a new module stays off on the card")
check("new_mods" not in Bo.get(B + f"/api/modcards?space={WS}").json()["cards"][0], "a member does not see the hint")
r = A.patch(B + f"/api/modcards/{C2}", json={"name": "Tables", "expect_updated_at": "2000-01-01T00:00:00.000+00:00"})
check(r.status_code == 409 and r.json().get("card", {}).get("id") == C2, "an old version is a 409 with the current card")
r = A.patch(B + f"/api/modcards/{C2}", json={"name": "Tables and more", "expect_updated_at": c2["updated_at"]})
check(r.ok and r.json()["card"]["new_mods"] == [] and r.json()["card"]["name"] == "Tables and more", "saved: no new module any more")
# review job 2963: a person on the card disabled later - the admin can still save the card as it is
sql("UPDATE users SET disabled=1 WHERE id=?", (BOB,), write=True)
r = A.patch(B + f"/api/modcards/{C2}", json={"people": [BOB]})
sql("UPDATE users SET disabled=0 WHERE id=?", (BOB,), write=True)
check(r.ok, "a disabled person on the card does not block saving it " + r.text[:160])
r = A.patch(B + f"/api/modcards/{C3}", json={"people": []})
check(r.ok and r.json()["card"]["people"] == [], "admin: the people of a card change")
check(Bo.get(B + f"/api/modcards?space={WS}").json().get("cap") == ["sheets"], "Bob: the cap follows")
check(A.delete(B + f"/api/modcards/{C2}").ok, "admin: a card is deleted")
check(sql("SELECT COUNT(*) FROM module_card_people WHERE card_id=?", (C2,))[0][0] == 0, "its people go with it")
check(Bo.get(B + f"/api/modcards?space={WS}").json().get("cap") == ["time", "wiki", "sheets"], "Bob: without a card the default again")

# ================================================================== my own hidden modules per workspace
check(Bo.patch(B + "/api/settings", json={"ws_mods_off": '{"private":["nope"]}'}).status_code == 400, "ws_mods_off: an unknown module is a 400")
check(Bo.patch(B + "/api/settings", json={"ws_mods_off": '{"elsewhere":["wiki"]}'}).status_code == 400, "ws_mods_off: an unknown workspace is a 400")
r = Bo.patch(B + "/api/settings", json={"ws_mods_off": '{"%s":["wiki","sheets"],"private":[]}' % WS})
check(r.ok and Bo.get(B + "/api/state").json()["settings"].get("ws_mods_off") == '{"%s":["wiki","sheets"]}' % WS, "ws_mods_off: stored cleanly")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/modcards", json={"space": "private", "name": "Evenings", "icon": "heart", "mods": ["habits", "reading", "cal"]})
check(r.status_code == 201 and r.json()["card"]["space"] == "private" and "people" not in r.json()["card"], "freelancer: an own card " + r.text[:160])
FC = r.json()["card"]["id"]
check(Fr.post(B + "/api/modcards", json={"space": "private", "name": "X", "mods": [], "dflt": True}).status_code == 400, "freelancer: no default card in Private")
check(Fr.post(B + "/api/modcards", json={"space": "private", "name": "X", "mods": [], "people": [FID]}).status_code == 400, "freelancer: no people in Private")
check(Fr.get(B + f"/api/modcards?space={WS}").status_code == 404, "freelancer: no organisation's cards")
j = Fr.get(B + "/api/modcards").json()
check([c["id"] for c in j.get("cards") or []] == [FC] and j.get("cap") is None, "freelancer: the own cards, no cap")
check(Bo.get(B + "/api/modcards").json().get("cards") == [], "another person does not see her private card")
check(Bo.patch(B + f"/api/modcards/{FC}", json={"name": "mine"}).status_code == 404, "another person cannot change her card (404)")
r = Fr.patch(B + f"/api/modcards/{FC}", json={"mods": ["habits", "reading", "cal", "wiki"]})
check(r.ok and r.json()["card"]["mods"] == ["cal", "habits", "reading", "wiki"], "freelancer: the card changes")
# applying it (the client: settings.js mc_apply) = the main switches of a person without an organisation
r = Fr.patch(B + "/api/settings", json={"features": "cal,habits,reading,wiki", "ws_mods_off": "{}"})
check(r.ok and Fr.get(B + "/api/state").json()["settings"].get("features") == "cal,habits,reading,wiki", "freelancer: a card applied")
check(Fr.get(B + "/api/wiki?space=private").status_code == 200, "freelancer: no lock in Private")
check(Fr.delete(B + f"/api/modcards/{FC}").ok and Fr.get(B + "/api/modcards").json()["cards"] == [], "freelancer: the card is deleted")
check(Fr.get(B + "/api/state").json()["settings"].get("features") == "cal,habits,reading,wiki", "deleting a card changes no module")

sys.exit(kt.done("p2575_a_api"))
