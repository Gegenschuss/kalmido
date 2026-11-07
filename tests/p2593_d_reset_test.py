#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.593.0 Teil D (#4590). Invented names only (example.com); the person is one without an organisation (freelancer-matrix: own).
"Reset settings" under Settings > Account (POST /api/settings/reset):
 - the preview (dry_run) lists only what differs from the standard, by readable name and group, and changes nothing
 - the reset puts only the look and comfort settings back; the account, the sign-in (password, 2FA, tokens, app passwords),
   the language and formats, privacy choices, favourites, other people's and the organisation's / server's settings stay
 - one undo puts every old value back (also an active saved arrangement), a second undo is a 404
 - an agent token and a personal API token never reach it (the route is not under /api/v1/, no session = no reset)
usage: p2593_d_reset_test.py"""
import json
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402


def own(uid):
    return dict(kt.dbx("SELECT key, value FROM user_settings WHERE user_id=?", (uid,)))


SERVER_KEYS = ("default_features", "default_lang", "collab_all", "time_all", "signup_mode", "org_invites", "twofa_required",
               "passkey_login", "public_links", "org_encrypt", "storage_quota_mb", "mail_day_limit")


def server_side():
    """What the reset must never touch: the server's settings, the organisations, the sign-in of the accounts."""
    # the admin's choices of the server (not its runtime keys: the watchdog and the counters write those at any time)
    return (kt.dbx("SELECT key, value FROM settings WHERE key IN (" + ",".join("?" * len(SERVER_KEYS)) + ") ORDER BY key", SERVER_KEYS),
            kt.dbx("SELECT id, name, icon FROM orgs ORDER BY id"),
            kt.dbx("SELECT id, password_hash, totp_secret, display_name, email FROM users ORDER BY id"),
            kt.dbx("SELECT COUNT(*) FROM api_tokens")[0][0], kt.dbx("SELECT COUNT(*) FROM app_passwords")[0][0])


def reset(s, **kw):
    return s.post(B + "/api/settings/reset", json=kw)


def keys_of(j):
    return {k for it in j.get("items") or [] for k in it["keys"]}


kt.fresh(prefix="P2593D")
A = kt.setup()
FID, Fr = freelancer(B, A)
ALICE = A.get(B + "/api/me").json()["id"]
# what differs already right after the fixture (it switches every module on): part of the preview
BASE = keys_of(reset(Fr, dry_run=True).json())
check("features" in BASE, f"the fixture's modules differ from the standard {sorted(BASE)}")
A.patch(B + "/api/settings", json={"start_page": "today", "look": json.dumps({"theme": "dark"})})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Beispiel Org", "admin_id": ALICE}).json().get("id")
check(bool(ORG), "an organisation exists for the boundary checks")

# the freelancer's own changes: look and comfort (reset) and others that must stay
CHANGED = {"look": json.dumps({"theme": "light", "density": "compact", "fsize": 110}),
           "start_page": "today", "side_icons": "emoji", "side_count": "0", "notify": json.dumps({"comment": {"push": False}}),
           "show_done_views": json.dumps({"today": 0}), "ws_colors": json.dumps({"private": "red"}), "quiet_from": "21:00",
           "dashboard": json.dumps({"order": ["today", "news"], "hidden": ["stats"]})}
STAY = {"lang": "de", "week_start": "mon", "time_rounding": "15", "chat_read_receipts": "0", "freebusy_share": "off",
        "photo_meta_strip": "0", "fav_lists": "", "work_start": "08:00",
        "push_title_only": "1"}  # review F10: "title only" (no text on the lock screen) is a privacy choice and stays
r = Fr.patch(B + "/api/settings", json={**CHANGED, **STAY})
check(r.ok, f"settings saved {r.status_code} {r.text[:200]}")
r = Fr.patch(B + "/api/settings", json={"comment_order": "old", "lang": "en"})  # explicitly stored, but the standard; English for the texts
check(r.ok, "a setting stored with its standard value")
STAY["lang"] = "en"
kt.dbx("UPDATE users SET totp_secret='JBSWY3DPEHPK3PXP' WHERE id=?", (FID,))  # 2FA set (only its stored secret matters here)
t = Fr.post(B + "/api/me/tokens", json={"name": "skript", "scopes": ["read", "account"]})
check(t.status_code == 201, f"a personal API token {t.status_code} {t.text[:200]}")
TOK = t.json().get("token", "") if t.status_code == 201 else ""
ag = Fr.post(B + "/api/my/agents", json={"username": "helfer", "display_name": "Helfer", "scopes": ["read"]})
AGTOK = (ag.json().get("token") or "") if ag.ok else ""
check(bool(AGTOK), f"an agent with a token {ag.status_code}")
# a saved arrangement of the start page, active
sv = Fr.post(B + "/api/layouts/saved", json={"key": "dashboard", "name": "Fokus", "layout": CHANGED["dashboard"], "activate": True})
SVID = (sv.json().get("saved") or {}).get("id") if sv.ok else None
check(bool(SVID), f"a saved arrangement {sv.status_code} {sv.text[:200]}")

BEFORE, SRV, ALICE_S = own(FID), server_side(), own(ALICE)

# ==== the preview
p = reset(Fr, dry_run=True)
check(p.ok, f"preview {p.status_code} {p.text[:200]}")
pj = p.json()
want = BASE | set(CHANGED)
check(keys_of(pj) == want, f"the preview lists exactly what differs: {sorted(keys_of(pj) ^ want)}")
check("comment_order" not in keys_of(pj), "a setting stored with its standard value is not listed")
check(not keys_of(pj) & set(STAY), "language, formats, privacy, working hours are never in the preview")
groups = {it["group"] for it in pj["items"]}
check(groups == {"look", "side", "start", "views", "notify", "mods", "filters", "colours"}, f"groups of the preview {sorted(groups)}")
check(all(it["label"] and it["group_label"] for it in pj["items"]), "every entry has a readable name and group")
check(pj.get("undo") is False, "nothing to undo yet")
check(own(FID) == BEFORE, "the preview changes nothing")

# ==== agents and API tokens: never
for name, h in (("agent token", AGTOK), ("API token", TOK)):
    r = requests.post(B + "/api/settings/reset", headers={"Authorization": "Bearer " + h, "X-Requested-With": "kalmido"}, json={})
    check(r.status_code in (401, 403), f"{name} on /api/settings/reset: {r.status_code}")
    r = requests.post(B + "/api/v1/settings/reset", headers={"Authorization": "Bearer " + h}, json={})
    check(r.status_code in (403, 404, 405), f"{name} on /api/v1/settings/reset: {r.status_code}")
check(own(FID) == BEFORE, "after the tries with tokens nothing changed")

# ==== the reset
SRV = server_side()  # after the token tries (a refused bearer token may leave a rate entry in the server's settings)
r = reset(Fr)
check(r.ok and r.json().get("undo") is True, f"reset {r.status_code} {r.text[:200]}")
check(keys_of(r.json()) == want, "the answer names what went back")
AFTER = own(FID)
check(AFTER.get("look") == "{}", f"the look is saved empty (every device takes its defaults): {AFTER.get('look')!r}")
for k, v in (("start_page", "home"), ("side_icons", "line"), ("side_count", "1"), ("notify", ""), ("dashboard", ""), ("ws_colors", "{}"),
             ("quiet_from", "22:00"), ("show_done_views", "{}"), ("show_done_default", "0")):
    check(AFTER.get(k) == v, f"{k} is stored with the standard of a new account: {AFTER.get(k)!r}")
st = Fr.get(B + "/api/state").json()["settings"]
check(st["start_page"] == "home" and st["side_icons"] == "line" and st["notify"] == "", "the state shows the standard")
check(set(st["features"].split(",")) != set(BEFORE["features"].split(",")), "the modules are back to the server's standard")
check("reset_undo" not in st, "the kept old values never go to the client")
for k, v in STAY.items():
    check(AFTER.get(k, "") == v, f"{k} stays ({AFTER.get(k)!r})")
check(AFTER.get("tour") == BEFORE.get("tour"), "the tour state stays")
NOW = server_side()
check(NOW == SRV, f"server settings, organisations, passwords, 2FA, tokens and app passwords unchanged {sorted(set(map(tuple, NOW[0])) ^ set(map(tuple, SRV[0])))[:6]} {[a == b for a, b in zip(NOW, SRV)]}")
check(own(ALICE) == ALICE_S, "the other account's settings unchanged")
act = kt.dbx("SELECT active FROM view_layouts WHERE id=?", (SVID,))
check(act and act[0][0] == 0, "the active saved arrangement ends (it stays saved)")
check(kt.dbx("SELECT COUNT(*) FROM view_layouts WHERE id=?", (SVID,))[0][0] == 1, "the saved arrangement is not deleted")
p = reset(Fr, dry_run=True).json()
check(p["items"] == [] and p["undo"] is True, f"after the reset: nothing differs, an undo is there {p}")

# ==== the undo
r = reset(Fr, undo=True)
check(r.ok, f"undo {r.status_code} {r.text[:200]}")
check(own(FID) == BEFORE, f"every old value is back: {sorted(set(own(FID).items()) ^ set(BEFORE.items()))[:6]}")
act = kt.dbx("SELECT active FROM view_layouts WHERE id=?", (SVID,))
check(act and act[0][0] == 1, "the saved arrangement is active again")
r = reset(Fr, undo=True)
check(r.status_code == 404, f"only one undo: {r.status_code}")
check(reset(Fr, dry_run=True).json()["undo"] is False, "the undo is used up")

# ==== the reset_undo value cannot be written by the client
r = Fr.patch(B + "/api/settings", json={"reset_undo": json.dumps({"vals": {"lang": "fr"}})})
check(r.ok and own(FID).get("reset_undo", "") == "", "PATCH /api/settings never stores reset_undo")

# ==== the admin of an organisation: the same, the organisation stays
SRV = server_side()
r = reset(A)
check(r.ok and {"look", "start_page"} <= keys_of(r.json()), f"the admin's reset {r.status_code}")
check(server_side() == SRV, f"the organisation and the server settings stay after the admin's reset {[a == b for a, b in zip(server_side(), SRV)]}")
sys.exit(kt.done("p2593_d_reset"))
