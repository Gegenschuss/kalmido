#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.556.0 B (#4685) API tests, own container: "New for you" after an update (kalmido/accounts/whatsnew.py).
The example file is <data dir>/whatsnew-test.json (test containers read it instead of static/whatsnew.json, which only the
release process writes); its versions are built around the running version (GET /api/about).
 - a new person (no seen version): GET /api/whatsnew sets the running version, nothing to show
 - a seen version before: every version after it up to the running one with sentences, newest first; a version without
   sentences and one newer than the running one stay out; the person's language, English as the fallback
 - the parts compare as numbers ("2.99.0" is older than "2.549.0"); a seen version older than the file reaches: older + link
 - POST /api/whatsnew/seen: the running version is seen, nothing to show any more; PATCH /api/settings cannot set it
 - the switch whatsnew_on = 0: nothing to show; a missing or broken file: nothing to show, no error
The case without an organisation (freelancer fixture) runs the same way.
freelancer-matrix: own
usage: p2556_b_whatsnew_api_test.py <datadir>"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, DATA, check, dbx, done  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

WN = os.path.join(DATA, "whatsnew-test.json")
if os.path.exists(WN):
    os.remove(WN)
kt.fresh(prefix="P2556B")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
AID = A.get(B + "/api/state").json()["me"]["id"]
CUR = A.get(B + "/api/about").json()["version"]
MA, MI, _P = (int(x) for x in CUR.split("."))
V = lambda m: f"{MA}.{m}.0"  # noqa: E731
FILE = {"versions": [
    {"version": V(MI + 1), "date": "2026-12-01", "items": [{"en": "From the future", "de": "Aus der Zukunft"}]},
    {"version": CUR, "date": "2026-11-05", "items": [{"en": "Newest one", "de": "Das Neueste"}, {"en": "Only English"}]},
    {"version": V(MI - 1), "date": "2026-11-04", "items": [{"en": "Middle one", "de": "Das Mittlere"}]},
    {"version": V(MI - 2), "date": "2026-11-03", "items": []},
    {"version": V(MI - 10), "date": "2026-10-20", "items": [{"en": "Oldest one", "de": "Das Älteste"}]},
]}


def write(d):
    with open(WN, "w", encoding="utf-8") as f:
        f.write(d if isinstance(d, str) else json.dumps(d))


def seen_db(uid):
    r = dbx("SELECT value FROM user_settings WHERE user_id=? AND key='whatsnew_seen'", (uid,))
    return r[0][0] if r else None


def set_seen(uid, v):
    dbx("INSERT INTO user_settings(user_id, key, value) VALUES(?, 'whatsnew_seen', ?) "
        "ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value", (uid, v))


def news(s):
    r = s.get(B + "/api/whatsnew")
    check(r.status_code == 200, f"GET /api/whatsnew answers 200 ({r.status_code} {r.text[:200]})")
    return r.json() if r.ok else {}


def run(who, s, uid):
    write(FILE)
    # ---- a new person: the running version, no dialog
    check(seen_db(uid) in (None, ""), f"{who}: no seen version at the start (a new account stores the default '') {seen_db(uid)!r}")
    j = news(s)
    check(j.get("versions") == [] and j.get("seen") == CUR and j.get("current") == CUR, f"{who}: new person: nothing to show, seen = running {j}")
    check(seen_db(uid) == CUR, f"{who}: new person: the running version is stored ({seen_db(uid)})")
    check(news(s).get("versions") == [], f"{who}: new person: still nothing on the second look")
    # ---- a version between the oldest and the empty one seen before
    set_seen(uid, V(MI - 5))
    j = news(s)
    vs = [v["version"] for v in j.get("versions", [])]
    check(vs == [CUR, V(MI - 1)], f"{who}: the two versions since the seen one, newest first; empty and future ones out {vs}")
    check(j.get("versions", [{}])[0].get("items") == ["Newest one", "Only English"] and j["versions"][1]["items"] == ["Middle one"],
          f"{who}: the sentences in English {j.get('versions')}")
    check(j.get("versions", [{}])[0].get("date") == "2026-11-05", f"{who}: the date of a version comes along")
    check(j.get("on") is True and j.get("older") is False, f"{who}: switch on, the file reaches the seen version {j.get('older')}")
    s.patch(B + "/api/settings", json={"lang": "de"})
    j = news(s)
    check(j.get("versions", [{}])[0].get("items") == ["Das Neueste", "Only English"], f"{who}: German, English as the fallback {j.get('versions')}")
    s.patch(B + "/api/settings", json={"lang": "en"})
    # ---- numbers, not text: "MA.99.0" sorts after "MA.549.0" as a string, but is older
    old = f"{MA}.{int('9' * (len(str(MI)) - 1))}.0"
    set_seen(uid, old)
    j = news(s)
    vs = [v["version"] for v in j.get("versions", [])]
    check(vs == [CUR, V(MI - 1), V(MI - 10)], f"{who}: seen {old} is older than every version (parts as numbers) {vs}")
    check(j.get("older") is True and j.get("link", "").startswith("https://"), f"{who}: older than the file reaches: the hint with the link {j.get('older')} {j.get('link')}")
    # ---- seen: nothing any more; PATCH cannot set it
    r = s.post(B + "/api/whatsnew/seen")
    check(r.ok and r.json().get("seen") == CUR and seen_db(uid) == CUR, f"{who}: POST /api/whatsnew/seen stores the running version {r.text[:200]}")
    check(news(s).get("versions") == [], f"{who}: after seen: nothing to show")
    s.patch(B + "/api/settings", json={"whatsnew_seen": V(MI - 5)})
    check(seen_db(uid) == CUR, f"{who}: PATCH /api/settings does not set the seen version ({seen_db(uid)})")
    # ---- the switch
    r = s.patch(B + "/api/settings", json={"whatsnew_on": "0"})
    on = dbx("SELECT value FROM user_settings WHERE user_id=? AND key='whatsnew_on'", (uid,))
    check(r.ok and on and on[0][0] == "0", f"{who}: the switch is stored off {r.text[:200]}")
    check(s.get(B + "/api/state").json()["settings"].get("whatsnew_on") == "0", f"{who}: the state names the switch off")
    set_seen(uid, V(MI - 5))
    j = news(s)
    check(j.get("on") is False and j.get("versions") == [] and j.get("older") is False, f"{who}: switch off: nothing to show {j}")
    s.patch(B + "/api/settings", json={"whatsnew_on": "1"})
    # ---- no file / a broken one: nothing, no error
    os.remove(WN)
    j = news(s)
    check(j.get("versions") == [] and j.get("older") is False, f"{who}: no file: nothing to show {j}")
    write("{broken")
    check(news(s).get("versions") == [], f"{who}: a broken file: nothing to show")
    write({"versions": [{"version": "not a version", "items": [{"en": "x"}]}, {"version": CUR, "items": "nope"}, 7]})
    check(news(s).get("versions") == [], f"{who}: malformed entries are skipped")
    os.remove(WN)


run("alice", A, AID)
FID, Fr = freelancer(B, A)
run("freelancer", Fr, FID)  # freelancer-matrix: own -- GET /api/whatsnew, POST /api/whatsnew/seen without an organisation
sys.exit(done("p2556_b_whatsnew_api"))
