#!/usr/bin/env python3
"""2.97.0 API tests, part D (#2050, #2051), own container (start.sh). Invented names only. The server never sees a space key or
a plain text of a space with the lock: these tests send ciphertext-shaped values (the WebCrypto round trip is in p297_d_ui.js).
 - a private space with the lock -> an open organisation: the dry run names both states and warns that the pages are no longer
   end-to-end encrypted; the move needs the generations of the dry run (409), plain texts for an open target (400), every page
   with path and text (400), no folder (400); a taken name 409; the page is readable in the organisation, links rebuilt
 - the way back (the undo) into the space with the lock: only ciphertexts of its current generation (plain 400, another
   generation 400), no links on the server, no names in the history
 - lock -> lock: a ciphertext taken over unchanged from the source 400; fresh ones ok; a key change since the dry run 409
 - a person without a key of the target space: the dry run blocks, the move 409
 - an agent 403, a person without an organisation 409 (freelancer-matrix: wiki)
 - the history line of a move (page, table): workspaces by name only for their members, else neutral without ids
 - the nightly cleanup: a stored version file without a row (older than a day) goes, a fresh one and a used one stay
usage: p297_d_api_test.py <datadir>      (a fresh container; P297D_NOSTART=1 = the server already runs)"""
import base64
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402; 2.148.1 (#2480): an invited member accepts

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "sheets,wiki,collab,comments,files"


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def e2e_keys():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


def wrapped():
    return {"v": 1, "iv": b64(12), "ct": b64(48)}


def ct(gen=1, n=48):
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(n)}, separators=(",", ":"))


def mv(s, **b):
    return s.post(B + "/api/wiki/move-space", json=b)


def page(s, path, text="", space="private"):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def paths(s, space):
    return {p["path"]: p["id"] for p in s.get(B + "/api/wiki", params={"space": space}).json()["pages"]}


def lock(s, space, user_ids):
    """Switch the lock of a space on and convert its pages (shape-only ciphertexts of generation 1)."""
    r = s.post(B + "/api/wiki/e2e/start", json={"space": space, "keys": [{"user_id": u, "wrapped": wrapped()} for u in user_ids]})
    assert r.ok, r.text
    for _ in range(5):
        t = s.get(B + "/api/wiki/e2e/todo", params={"space": space}).json()
        if not t["pages"]:
            break
        rows = [{"id": p["id"], **{f: ct(t["gen"]) for f in ("path", "body") if p[f] is not None}} for p in t["pages"]]
        assert s.post(B + "/api/wiki/e2e/bulk", json={"space": space, "pages": rows}).ok
    r = s.post(B + "/api/wiki/e2e/finish", json={"space": space})
    assert r.ok, r.text


if not os.environ.get("P297D_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_FS_GC_EVERY=1")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u in ("bob", "carol", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "frank" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": uid["carol"]})
assert r.status_code in (200, 201), r.text
GAMMA = r.json()["id"]
GSP = f"org:{GAMMA}"
Bo, Ca, Fr = sess("bob"), sess("carol"), sess("frank")
for s in (A, Bo, Ca, Fr):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}

# ================================================================ #2051: the history line, neutral for non-members
G1 = page(Ca, "Gamma note", "from gamma", GSP)
r = mv(Ca, pages=[G1], space=GSP, to=SP)
check(r.ok, "carol moves a page of Gamma into Alpha " + r.text[:200])
g = A.get(B + f"/api/wiki/pages/{G1}")
m = g.json().get("moved") or {}
check(g.ok and m.get("from") is None and m.get("from_name") == "Organisation" and m.get("to") == SP and m.get("to_name") == "Alpha",
      "alice (not in Gamma): the source only as 'Organisation' " + str(m))
check(GSP not in g.text and "Gamma" not in json.dumps(m), "alice: no id or name of Gamma in the history line")
m = Ca.get(B + f"/api/wiki/pages/{G1}").json().get("moved") or {}
check(m.get("from") == GSP and m.get("from_name") == "Gamma", "carol (member of Gamma): its name " + str(m))
SID = Bo.post(B + "/api/sheets", json={"title": "Budget", "space": "private"}).json()["id"]
check(Bo.post(B + f"/api/sheets/{SID}/move-space", json={"to": SP}).ok, "bob moves his table into Alpha")
m = A.get(B + f"/api/sheets/{SID}").json().get("moved") or {}
check(m.get("from") is None and m.get("from_name") == "private space", "alice: bob's private space without key or person " + str(m))
m = Bo.get(B + f"/api/sheets/{SID}").json().get("moved") or {}
check(m.get("from") == "private" and m.get("from_name") == "Private", "bob: his own private space " + str(m))

# ================================================================ #2050: private with the lock -> open organisation
SEC = page(Ca, "Secret", "see [[Other]] and #5")
OTH = page(Ca, "Other", "")
assert Ca.put(B + "/api/e2e/keys", json=e2e_keys()).ok
lock(Ca, "private", [uid["carol"]])
src = {r["id"]: r for r in dbx("SELECT id, path, body FROM wiki_pages WHERE id IN (?, ?)", (SEC, OTH))}
check(src[SEC]["path"].startswith("e2e1:"), "carol's private space is locked")

r = mv(Ca, pages=[SEC], space="private", to=SP, dry=1)
d = r.json() if r.ok else {}
e = d.get("e2e") or {}
check(r.ok and d.get("block") is None and d.get("count") == 1, "dry run: 1 page, no block " + r.text[:300])
check((e.get("from") or {}).get("mode") == "on" and (e.get("from") or {}).get("gen") == 1 and (e.get("to") or {}).get("mode") is None,
      "dry run: both states " + str(e))
check(any("no longer end-to-end encrypted" in n for n in d.get("notes", [])), "dry run: the warning " + str(d.get("notes")))
check(mv(Ca, folder="Plan", space="private", to=SP, dry=1).status_code == 400, "a folder by name: 400 (the browser names the pages)")
good = {"id": SEC, "path": "Moved/Secret", "body": "see [[Other]] and #5"}
check(mv(Ca, pages=[good], space="private", to=SP).status_code == 409, "without the generations of the dry run: 409")
r = mv(Ca, pages=[good], space="private", to=SP, gens={"from": 2, "to": 0})
check(r.status_code == 409 and r.json().get("code") == "wiki_e2e_gen", "another generation than now: 409 " + r.text[:200])
G = {"from": 1, "to": 0}
check(mv(Ca, pages=[{**good, "body": ct(1)}], space="private", to=SP, gens=G).status_code == 400, "a ciphertext into an open space: 400")
check(mv(Ca, pages=[{"id": SEC, "path": "Moved/Secret"}], space="private", to=SP, gens=G).status_code == 400, "a page without its text: 400")
check(mv(Ca, pages=[good, good], space="private", to=SP, gens=G).status_code == 400, "a page twice: 400")
check(mv(Ca, pages=[{**good, "id": G1}], space="private", to=SP, gens=G).status_code == 404, "a page of another space: 404")
TK = page(A, "Moved/Secret", "", SP)
r = mv(Ca, pages=[good], space="private", to=SP, gens=G)
check(r.status_code == 409 and "Moved/Secret" in r.json().get("taken", []), "a taken name: 409 " + r.text[:200])
check(A.delete(B + f"/api/wiki/pages/{TK}").ok, "(the taken page goes)")
check(dbx("SELECT org_id FROM wiki_pages WHERE id=?", (SEC,))[0]["org_id"] is None, "after the refusals the page is still carol's")
r = requests.post(B + "/api/wiki/move-space", json={"pages": [good], "space": "private", "to": SP, "gens": G}, headers=AGH)
check(r.status_code in (401, 403), "an agent: refused " + str(r.status_code))
r = mv(Ca, pages=[good], space="private", to=SP, gens=G)
check(r.ok and r.json().get("space") == SP and [x["id"] for x in r.json().get("moved", [])] == [SEC], "locked -> open: moved " + r.text[:300])
g = A.get(B + f"/api/wiki/pages/{SEC}").json()
check(g.get("path") == "Moved/Secret" and g.get("body") == "see [[Other]] and #5", "alice reads the plain page in Alpha " + str(g)[:200])
links = dbx("SELECT to_path, to_task FROM wiki_links WHERE from_id=?", (SEC,))
check(any(x["to_task"] == 5 for x in links) and any(x["to_path"] == "other" for x in links), "links rebuilt in the open target " + str(links))
hist = dbx("SELECT detail FROM space_moves WHERE kind='wiki' AND obj_id=? ORDER BY id DESC", (SEC,))
check(hist and "e2e1:" not in hist[0]["detail"] and json.loads(hist[0]["detail"]).get("to") == "Moved/Secret", "history: no ciphertext " + str(hist[:1]))

# ================================================================ the way back (undo) into the space with the lock
r = mv(Ca, pages=[SEC], space=SP, to="private", dry=1)
e = r.json().get("e2e") or {}
check(r.ok and r.json().get("block") is None and (e.get("to") or {}).get("gen") == 1 and not any(
    "no longer" in n for n in r.json().get("notes", [])), "dry run back: the target's generation, no warning " + r.text[:300])
G = {"from": 0, "to": 1}
check(mv(Ca, pages=[{"id": SEC, "path": "Secret", "body": "x"}], space=SP, to="private", gens=G).status_code == 400,
      "plain text into the space with the lock: 400")
check(mv(Ca, pages=[{"id": SEC, "path": ct(2), "body": ct(2)}], space=SP, to="private", gens=G).status_code == 400,
      "a ciphertext of another generation: 400")
check(mv(Ca, pages=[{"id": SEC, "path": "", "body": ""}], space=SP, to="private", gens=G).status_code == 400, "an empty path: 400")
back = {"id": SEC, "path": ct(1), "body": ct(1)}
r = mv(Ca, pages=[back], space=SP, to="private", gens=G)
check(r.ok and r.json().get("space") == "private" and "to" not in r.json()["moved"][0], "open -> locked: moved, no names in the answer " + r.text[:300])
row = dbx("SELECT org_id, owner_id, path, body, attrs FROM wiki_pages WHERE id=?", (SEC,))[0]
check(row["org_id"] is None and row["owner_id"] == uid["carol"] and row["path"] == back["path"] and row["attrs"] == "{}",
      "the page holds the ciphertexts in carol's space " + str(row)[:200])
check(not dbx("SELECT 1 FROM wiki_links WHERE from_id=?", (SEC,)), "no links kept for the space with the lock")
hist = dbx("SELECT detail FROM space_moves WHERE kind='wiki' AND obj_id=? ORDER BY id DESC", (SEC,))
check(json.loads(hist[0]["detail"]) == {"e2e": 1}, "history into the lock: no names " + hist[0]["detail"])
check(A.get(B + f"/api/wiki/pages/{SEC}").status_code == 404, "alice does not see it any more")

# ================================================================ lock -> lock, a key change in between
lock(Ca, GSP, [uid["carol"]])
r = mv(Ca, pages=[SEC], space="private", to=GSP, dry=1)
e = r.json().get("e2e") or {}
check(r.ok and r.json().get("block") is None and e["from"]["mode"] == "on" and e["to"]["mode"] == "on", "dry run lock -> lock " + r.text[:300])
G = {"from": 1, "to": 1}
cur = dbx("SELECT path, body FROM wiki_pages WHERE id=?", (SEC,))[0]
check(mv(Ca, pages=[{"id": SEC, "path": cur["path"], "body": cur["body"]}], space="private", to=GSP, gens=G).status_code == 400,
      "the source's ciphertexts taken over unchanged: 400")
check(mv(Ca, pages=[{"id": SEC, "path": ct(1), "body": cur["body"]}], space="private", to=GSP, gens=G).status_code == 400,
      "one field taken over unchanged: 400")
r = mv(Ca, pages=[{"id": SEC, "path": ct(1), "body": ""}], space="private", to=GSP, gens=G)
check(r.ok and r.json().get("space") == GSP, "lock -> lock with fresh ciphertexts (an empty text stays empty) " + r.text[:200])
r = Ca.post(B + "/api/wiki/e2e/rotate", json={"space": GSP, "gen": 2, "keys": [{"user_id": uid["carol"], "wrapped": wrapped()}]})
check(r.ok, "carol changes the key of Gamma " + r.text[:200])
r = mv(Ca, pages=[{"id": SEC, "path": ct(1), "body": ct(1)}], space=GSP, to="private", gens={"from": 1, "to": 1})
check(r.status_code == 409 and r.json().get("code") == "wiki_e2e_gen", "the key changed since the dry run: 409 " + r.text[:200])
check(dbx("SELECT org_id FROM wiki_pages WHERE id=?", (SEC,))[0]["org_id"] == GAMMA, "... and nothing moved")

# ================================================================ no key of the target space
r = Ca.put(B + f"/api/orgs/{GAMMA}/members", json={"email": "bob@example.com", "role": "member"})
assert r.ok and org_join(B, "bob", GAMMA), r.text  # 2.148.1 (#2480): bob accepts the invitation
BP = page(Bo, "Bob idea", "plain")
r = mv(Bo, pages=[BP], space="private", to=GSP, dry=1)
check(r.ok and "cannot unlock" in (r.json().get("block") or ""), "bob without a key of Gamma: the dry run blocks " + r.text[:200])
r = mv(Bo, pages=[{"id": BP, "path": ct(2), "body": ct(2)}], space="private", to=GSP, gens={"from": 0, "to": 2})
check(r.status_code == 409 and "cannot unlock" in r.json().get("error", ""), "... and the move 409 " + r.text[:200])
check(paths(Bo, "private").get("Bob idea") == BP, "bob's page stays")

# ================================================================ a person without an organisation
# freelancer-matrix: wiki
FID, Fl = freelancer(B, A, features=FEATURES + ",wiki")
FP = page(Fl, "Mine", "an idea")
assert Fl.put(B + "/api/e2e/keys", json=e2e_keys()).ok
lock(Fl, "private", [FID])
check(mv(Fl, pages=[FP], space="private", to=SP, dry=1).status_code == 409, "freelancer with the lock: no organisation (409)")
check(mv(Fl, pages=[FP], space="private", to="private", dry=1).status_code == 409, "freelancer: the same space 409")

# ================================================================ #2051: the nightly cleanup of stored versions
r = Bo.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("note.txt", b"keep me")})
assert r.status_code == 201, r.text
NID = r.json()["items"][0]["id"]
REL = dbx("SELECT path FROM fs_versions WHERE node_id=?", (NID,))[0]["path"]
AT = os.path.join(DATA, "attachments")
check(os.path.isfile(os.path.join(AT, REL)), "the version file lies in the data directory " + REL)
code = ("import os, time; d = '/data/attachments/files/%d'; t = time.time() - 3 * 86400\n"
        "open(d + '/0rphan0ld', 'wb').write(b'x'); open(d + '/0rphanNew', 'wb').write(b'y')\n"
        "os.utime(d + '/0rphan0ld', (t, t)); os.utime('/data/attachments/%s', (t, t))") % (NID, REL)
p = subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)
check(p.returncode == 0, "orphans written in the container " + p.stderr[-300:])
gone = False
for _ in range(40):
    if not os.path.exists(os.path.join(AT, "files", str(NID), "0rphan0ld")):
        gone = True
        break
    time.sleep(0.5)
check(gone, "the old file without a row is removed")
check(os.path.exists(os.path.join(AT, "files", str(NID), "0rphanNew")), "a fresh file without a row stays (an upload in progress)")
check(os.path.isfile(os.path.join(AT, REL)), "the old version file with its row stays")
check(Bo.get(B + f"/api/files/nodes/{NID}/content").content == b"keep me", "the file still opens")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
