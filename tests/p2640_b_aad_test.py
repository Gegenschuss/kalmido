#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.640.0 part B API test (#3388): the id reservation of the E2E record binding (AAD v2). Invented names only; the server
never sees a key, the tests send ciphertext-shaped values.
 - list channel: POST /api/team/rooms/<rid>/msgid -> {id, resv}; a v 2 message is stored under exactly that id; the same
   reservation twice, without one, another person's or a forged id 400; a v 1 message (older app) still taken; another message
   after the reservation -> 409 chan_resv_stale (ids keep the order of the room); an open channel / a stranger refused
 - knowledge pages: POST /api/wiki/e2e/newid -> {id, resv}; a new page with v 2 ciphers under exactly that id; reuse / none /
   another person's 400; v 1 ciphers without one still taken; an open space 400, a space of another organisation 404; edit and
   the re-encryption after a key change take v 2
freelancer-matrix: team, wiki (frida: her private knowledge space; a list channel she has none of - nobody to share a list
with - so she is the stranger to alice's channel there)
usage: p2640_b_aad_test.py <datadir>      (a fresh container; P2640B_NOSTART=1 = the server already runs)"""
import base64
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def wrapped():
    return {"v": 1, "iv": b64(12), "ct": b64(48)}


def keys():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


def chan(v=2, gen=1):
    return {"v": v, "g": gen, "iv": b64(12), "ct": b64(64)}


def ct(v=2, gen=1, n=48):
    return "e2e1:" + json.dumps({"v": v, "g": gen, "iv": b64(12), "ct": b64(n)}, separators=(",", ":"))


def code(r):
    try:
        return r.json().get("code")
    except ValueError:
        return None


kt.fresh(prefix="P2640B")
A = kt.setup()
AID = kt.me_id(A)
uid = {}
for u in ("bob", "olga"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ol = sess("bob"), sess("olga")
for s in (Bo, Ol):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,wiki"})
FID, Fr = freelancer(B, A)
for s in (Fr, Bo, Ol):
    assert s.put(B + "/api/e2e/keys", json=keys()).ok

# ================================================================== list channel
# alice's list shared with bob (a freelancer has no list channel: nobody to share with); frida is a stranger to it
assert A.put(B + "/api/e2e/keys", json=keys()).ok
L = A.post(B + "/api/lists", json={"name": "Locked chat"}).json()["id"]
LO = A.post(B + "/api/lists", json={"name": "Open"}).json()["id"]
for lid in (L, LO):
    r = A.put(B + f"/api/lists/{lid}/members", json={"user_id": uid["bob"], "role": "edit"})
    check(r.ok, f"setup: bob in list {lid} " + r.text[:200])
rooms = {r["list_id"]: r["id"] for r in A.get(B + "/api/team").json()["rooms"] if r["kind"] == "list"}
RID, RO = rooms.get(L), rooms.get(LO)
check(RID and RO, "setup: the channels of both lists " + json.dumps(rooms))
r = A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": [{"user_id": AID, "wrapped": wrapped()}, {"user_id": uid["bob"], "wrapped": wrapped()}]})
check(r.ok, "setup: the list is being encrypted " + r.text[:200])
r = A.post(B + f"/api/team/rooms/{RID}/msgid")
check(r.status_code == 409, "msgid: not while the list is being encrypted " + r.text[:200])
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok, "setup: the lock is on " + r.text[:200])

r = A.post(B + f"/api/team/rooms/{RID}/msgid")
R1 = r.json() if r.ok else {}
check(r.ok and isinstance(R1.get("id"), int) and isinstance(R1.get("resv"), str), "msgid: an id and its mark " + r.text[:200])
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(), "msg_id": R1.get("id"), "resv": R1.get("resv")})
check(r.status_code == 201 and r.json()["id"] == R1.get("id") and r.json()["enc"]["v"] == 2, "post: a v 2 message under the reserved id " + r.text[:200])
check(kt.dbx("SELECT enc FROM tchat_msgs WHERE id=?", (R1.get("id"),))[0][0].startswith('{"v":2,'), "post: the server keeps v 2")
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(), "msg_id": R1.get("id"), "resv": R1.get("resv")})
check(r.status_code == 400, "post: the same reservation twice 400 " + r.text[:200])
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan()})
check(r.status_code == 400, "post: a v 2 message without a reservation 400")
R2 = A.post(B + f"/api/team/rooms/{RID}/msgid").json()
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(), "msg_id": R2["id"] + 1, "resv": R2["resv"]})
check(r.status_code == 400, "post: another id with the mark of a reservation 400")
RB = Bo.post(B + f"/api/team/rooms/{RID}/msgid").json()
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(), "msg_id": RB["id"], "resv": RB["resv"]})
check(r.status_code == 400, "post: the reservation of another member 400")
check(Ol.post(B + f"/api/team/rooms/{RID}/msgid").status_code in (403, 404), "msgid: a stranger 403/404 (not in the room)")
check(Fr.post(B + f"/api/team/rooms/{RID}/msgid").status_code in (403, 404), "msgid: the freelancer, a stranger to the room, 403/404")
check(A.post(B + f"/api/team/rooms/{RO}/msgid").status_code == 409, "msgid: an open channel 409")
# a v 1 message of an app from before 2.640: no reservation needed (it binds no id)
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(v=1)})
V1 = r.json().get("id") if r.status_code == 201 else None
check(V1 and r.json()["enc"]["v"] == 1, "post: a v 1 message still taken " + r.text[:200])
# another message after the reservation: the reserved id would land before it -> 409, nothing stored
R3 = A.post(B + f"/api/team/rooms/{RID}/msgid").json()
r = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(v=1)})
check(r.status_code == 201 and r.json()["id"] > R3["id"], "setup: bob writes after the reservation")
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(), "msg_id": R3["id"], "resv": R3["resv"]})
check(r.status_code == 409 and code(r) == "chan_resv_stale", "post: a reservation older than the newest message 409 chan_resv_stale " + r.text[:200])
check(not kt.dbx("SELECT 1 FROM tchat_msgs WHERE id=?", (R3["id"],)), "post: nothing stored under the stale id")
R4 = A.post(B + f"/api/team/rooms/{RID}/msgid").json()
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(), "msg_id": R4["id"], "resv": R4["resv"]})
check(r.status_code == 201 and r.json()["id"] == R4["id"], "post: a fresh reservation after the 409 " + r.text[:200])
r = A.patch(B + f"/api/team/messages/{V1}", json={"enc": chan()})
check(r.ok and r.json()["enc"]["v"] == 2, "edit: a v 2 cipher of a known message (no reservation) " + r.text[:200])
check(A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(v=3)}).status_code == 400, "post: an unknown version 400")

# ================================================================== knowledge pages
ORG = A.post(B + "/api/admin/orgs", json={"name": "Elsewhere", "admin_id": AID}).json()["id"]  # after the sharing above
r = Fr.post(B + "/api/wiki/e2e/newid", json={"space": "private"})
check(r.status_code == 400 and code(r) == "wiki_e2e_open", "newid: an open space 400 " + r.text[:200])
check(Fr.post(B + "/api/wiki/e2e/newid", json={"space": f"org:{ORG}"}).status_code == 404, "newid: a space of another organisation 404")
r = Fr.post(B + "/api/wiki/e2e/start", json={"space": "private", "keys": [{"user_id": FID, "wrapped": wrapped()}]})
check(r.ok and r.json()["mode"] == "encrypting", "setup: the private space is being encrypted " + r.text[:200])
check(Fr.post(B + "/api/wiki/e2e/newid", json={"space": "private"}).status_code == 409, "newid: not while the space is being encrypted")
td = Fr.get(B + "/api/wiki/e2e/todo", params={"space": "private"}).json()
if td.get("pages"):
    Fr.post(B + "/api/wiki/e2e/bulk", json={"space": "private", "pages": [{"id": p["id"], "path": ct() if p["path"] else None, "body": ct() if p["body"] else None} for p in td["pages"]]})
r = Fr.post(B + "/api/wiki/e2e/finish", json={"space": "private"})
check(r.ok and r.json()["mode"] == "on", "setup: the lock is on " + r.text[:200])

r = Fr.post(B + "/api/wiki/e2e/newid", json={"space": "private"})
W1 = r.json() if r.ok else {}
check(r.ok and isinstance(W1.get("id"), int) and isinstance(W1.get("resv"), str), "newid: an id and its mark " + r.text[:200])
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": ct(), "body": ct(), "id": W1.get("id"), "resv": W1.get("resv")})
check(r.status_code == 201 and r.json()["id"] == W1.get("id"), "create: a v 2 page under the reserved id " + r.text[:200])
check('"v":2' in (kt.dbx("SELECT path FROM wiki_pages WHERE id=?", (W1.get("id"),)) or [("",)])[0][0], "create: the server keeps v 2")
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": ct(), "body": ct(), "id": W1.get("id"), "resv": W1.get("resv")})
check(r.status_code == 400, "create: the same reservation twice 400 " + r.text[:200])
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": ct(), "body": ""})
check(r.status_code == 400, "create: v 2 without a reservation 400")
W2 = Fr.post(B + "/api/wiki/e2e/newid", json={"space": "private"}).json()
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": ct(), "id": W2["id"] + 1, "resv": W2["resv"]})
check(r.status_code == 400, "create: another id with the mark of a reservation 400")
assert Ol.post(B + "/api/wiki/e2e/start", json={"space": "private", "keys": [{"user_id": uid["olga"], "wrapped": wrapped()}]}).ok
Ol.post(B + "/api/wiki/e2e/finish", json={"space": "private"})
WO = Ol.post(B + "/api/wiki/e2e/newid", json={"space": "private"}).json()
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": ct(), "id": WO.get("id"), "resv": WO.get("resv")})
check(WO.get("id") and r.status_code == 400, "create: the reservation of another person (her own private space) 400 " + r.text[:200])
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": ct(v=1), "body": ct(v=1)})
P1 = r.json().get("id") if r.status_code == 201 else None
check(P1, "create: v 1 ciphers of an older app still taken " + r.text[:200])
r = Fr.patch(B + f"/api/wiki/pages/{P1}", json={"body": ct()})
check(r.ok, "edit: a v 2 cipher of a known page (no reservation) " + r.text[:200])
check(Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": ct(v=3)}).status_code in (400, 409), "create: an unknown version refused")
# the key change: the re-encryption takes v 2 ciphers of the new generation
r = Fr.post(B + "/api/wiki/e2e/rotate", json={"space": "private", "gen": 2, "keys": [{"user_id": FID, "wrapped": wrapped()}]})
check(r.ok, "rotate: generation 2 " + r.text[:200])
td = Fr.get(B + "/api/wiki/e2e/todo", params={"space": "private"}).json()
ids = [p["id"] for p in td.get("pages", [])]
check(W1.get("id") in ids and P1 in ids, "todo: the pages of generation 1 are to do " + json.dumps(td)[:300])
r = Fr.post(B + "/api/wiki/e2e/bulk", json={"space": "private", "pages": [{"id": p["id"], "path": ct(gen=2) if p["path"] else None,
                                                                            "body": ct(gen=2) if p["body"] else None} for p in td.get("pages", [])]})
check(r.ok and r.json()["left"]["pages"] == 0, "bulk: v 2 ciphers of generation 2 taken " + r.text[:200])

# Fable review 2.640 (#3388): the same reservation sent twice at the same moment - one is stored, the other 400 (was a 500 on the
# primary key in the channel, a misleading 409 on the knowledge page)
import threading  # noqa: E402


def twice(fn):
    out, go = [], threading.Barrier(2)

    def one():
        go.wait()
        out.append(fn().status_code)
    ts = [threading.Thread(target=one) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return sorted(out)


RC = A.post(B + f"/api/team/rooms/{RID}/msgid").json()
got = twice(lambda: A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(), "msg_id": RC.get("id"), "resv": RC.get("resv")}))
check(len(got) == 2 and got[0] < 300 and got[1] == 400, f"channel: one reservation sent twice at once -> one stored, one 400 {got}")
WC = Fr.post(B + "/api/wiki/e2e/newid", json={"space": "private"}).json()
got = twice(lambda: Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": ct(gen=2), "id": WC.get("id"), "resv": WC.get("resv")}))
check(len(got) == 2 and got[0] < 300 and got[1] == 400, f"wiki: one reservation sent twice at once -> one stored, one 400 {got}")

print(f"\np2640_b_aad: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
