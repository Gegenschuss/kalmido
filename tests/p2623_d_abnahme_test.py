#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.623.0 part D API test (#4765): the approval (video sign-offs, data and API stay "videos") is a module of its own.
 - the module "videos" is on by default (a new account, a person without an organisation) and sits in the server's module
   list (family.py PM_FULL, the client's FEATS) and the module cards (modcards.py)
 - module off (Settings > Modules, the person's own switch): POST /api/videos is refused (409, like every module), at a task,
   a project and a client; nothing is deleted: the existing review stays listed and readable, takes a new version and a
   comment, goes to the trash and comes back from it with the module still off; module on again = creating works again
 - the same for a person without an organisation (frida, her own admin)
 - the one-shot migration (features_rev 12): an account from before (features without videos, rev 11) gets the module once
   at the start; one that switched it off afterwards keeps it off
tenant-matrix: video
freelancer-matrix: videos
usage: p2623_d_abnahme_test.py <datadir>      (a fresh container; P2623D_NOSTART=1 = the server already runs)"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, sess  # noqa: E402

started = kt.fresh(prefix="P2623D")
A = kt.setup()
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": kt.PASSWORD, "email": "bob@example.com"})
assert r.ok, r.text
BID = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
Bo.patch(B + "/api/settings", json={"features": Bo.get(B + "/api/state").json()["settings"]["features"] + ",clients"})
FID, Fr = freelancer(B, A)
URL = "https://vimeo.com/123456789"


def feats(s):
    return [x for x in (s.get(B + "/api/state").json()["settings"].get("features") or "").split(",") if x]


def set_videos(s, on):
    fs = [x for x in feats(s) if x != "videos"] + (["videos"] if on else [])
    r = s.patch(B + "/api/settings", json={"features": ",".join(fs)})
    assert r.ok, r.text


def places(s, who):
    lid = s.post(B + "/api/lists", json={"name": "Imagefilm " + who, "kind": "project"}).json()["id"]
    tid = s.post(B + "/api/tasks", json={"title": "Rohschnitt " + who, "list_id": lid}).json()["id"]
    cr = s.post(B + "/api/clients", json={"name": "Kunde " + who})
    cid = cr.json().get("id") if cr.ok else None
    if who == "frida":
        check(cid, f"frida: her own client {cr.status_code} {cr.text[:200]}")
    return {"task_id": tid, "list_id": lid, **({"client_id": cid} if cid else {})}


def module_checks(s, who):
    check("videos" in feats(s), f"{who}: the module Approval is on by default {feats(s)}")
    pl = places(s, who)
    made = {}
    for k, v in pl.items():
        r = s.post(B + "/api/videos", json={k: v, "title": f"Schnitt {who} {k}", "url": URL})
        check(r.ok, f"{who}: module on, a review at the {k} {r.status_code} {r.text[:200]}")
        made[k] = r.json().get("id") if r.ok else None
    set_videos(s, False)
    check("videos" not in feats(s), f"{who}: the module switched off")
    for k, v in pl.items():
        r = s.post(B + "/api/videos", json={k: v, "title": "Neu", "url": URL})
        check(r.status_code == 409 and "Approvals are turned off" in r.text, f"{who}: module off, no new review at the {k} {r.status_code} {r.text[:200]}")
        rows = s.get(B + f"/api/videos?{k}={v}").json().get("reviews") or []
        check([x["id"] for x in rows] == [made[k]], f"{who}: module off, the existing review at the {k} is still listed {[x['id'] for x in rows]}")
    vid = made["task_id"]
    check(s.get(B + f"/api/videos/{vid}").ok, f"{who}: module off, the review opens")
    r = s.post(B + f"/api/videos/{vid}/versions", json={"url": "https://vimeo.com/223456789"})
    check(r.ok, f"{who}: module off, the existing review takes a new version {r.status_code} {r.text[:200]}")
    vs = (r.json().get("versions") or []) if r.ok else []
    r = s.post(B + f"/api/videos/{vid}/comments", json={"body": "Schnitt zu hart", "version_id": vs[-1]["id"] if vs else None, "at_sec": 12})
    check(r.ok, f"{who}: module off, the existing review takes a comment {r.status_code} {r.text[:200]}")
    check(s.delete(B + f"/api/videos/{vid}").ok, f"{who}: module off, the review goes to the trash")
    tr = s.get(B + "/api/videos/trash").json().get("reviews") or []
    check(vid in [x["id"] for x in tr], f"{who}: module off, the trash lists it")
    r = s.post(B + f"/api/videos/{vid}/restore", json={})
    check(r.ok, f"{who}: module off, it comes back from the trash {r.status_code} {r.text[:200]}")
    rows = s.get(B + f"/api/videos?task_id={pl['task_id']}").json().get("reviews") or []
    check([x["id"] for x in rows] == [vid], f"{who}: restored at its task {[x['id'] for x in rows]}")
    set_videos(s, True)
    r = s.post(B + "/api/videos", json={"task_id": pl["task_id"], "title": "Feinschnitt", "url": URL})
    check(r.ok, f"{who}: module on again, creating works again {r.status_code} {r.text[:200]}")


# the server's module lists name it (Settings > Modules = the client's FEATS = PM_FULL; the module cards)
mc = A.get(B + "/api/modcards?space=private")
check(mc.ok and "videos" in (mc.json().get("mods") or []), f"the module cards know the module {mc.status_code} {mc.text[:300]}")
check("videos" in FEATURES.split(","), "the freelancer fixture switches it on like a new account")

module_checks(Bo, "bob")
module_checks(Fr, "frida")  # a person without an organisation: her own switch in her own space

# the one-shot migration (own container only: it restarts on the same data)
if started:
    set_videos(Bo, False)  # bob switched it off himself: stays off
    with dbxm.connect(os.path.join(kt.DATA, "tasks.db"), timeout=10) as c:
        c.execute("UPDATE user_settings SET value='cal,collab,comments' WHERE user_id=? AND key='features'", (FID,))
        c.execute("UPDATE user_settings SET value='11' WHERE user_id=? AND key='features_rev'", (FID,))
        c.execute("UPDATE user_settings SET value='12' WHERE user_id=? AND key='features_rev'", (BID,))
        c.commit()
    kt.fresh(keep=True)
    Fr, Bo = sess("frida"), sess("bob")
    check(feats(Fr) == ["cal", "collab", "comments", "videos"], f"migration: an account from before gets the module once {feats(Fr)}")
    check("videos" not in feats(Bo), f"migration: switched off after it, it stays off {feats(Bo)}")
    rev = kt.dbx("SELECT value FROM user_settings WHERE user_id=? AND key='features_rev'", (FID,))
    check(rev and str(rev[0][0]) == "12", f"migration: features_rev 12 {rev}")
sys.exit(kt.done("p2623_d_abnahme"))
