#!/usr/bin/env python3
"""2.139.0 API tests, part B (#2128): voice messages in the team chat. Invented names only, no real recordings (the audio
files are a few bytes with the container signature: MP4/M4A, WebM, Ogg).
 - a voice message = a multipart message with voice=1 + duration_ms and exactly one file that is audio by its content
   (400 otherwise: a picture, a text, two files, voice=2); the name ending follows the content; the length is capped
 - attachments carry voice / duration_ms (app, REST API, the agent's team_message event); normal files voice false
 - served as audio/* inline (nosniff stays), Range requests answer 206 + Content-Range, also for a sealed file (the server
   runs with a master key: files at rest are encrypted); ?dl=1 = download
 - who may read: members of the conversation only (404 for others); an end-to-end encrypted DM and an archived channel
   refuse voice messages (409); the REST API for agents takes no voice field
 - the page headers allow the microphone for the app itself only and media from blob: (the preview before sending)
 - a person without an organisation: a voice message in a direct message between two people (freelancer-matrix: chat)
usage: p2139_b_api_test.py <datadir>      (a fresh container; P2139B_NOSTART=1 = the server already runs)"""
import base64
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
ENV = ["-e", "KALMIDO_ORGCRYPT_DELAY=0", "-e", f"KALMIDO_SECRET_KEY={KEY}"]
FAILS, OKS = [], [0]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
# a few bytes with the signature of each container (no real sound: the server checks the type, never decodes)
M4A = b"\x00\x00\x00\x1cftypM4A \x00\x00\x02\x00M4A isommp42" + b"\x00\x00\x00\x08free" + bytes(range(256)) * 8
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\xf2\x81\x04\x42\xf3\x81\x08\x42\x82\x84webm" + bytes(range(200)) * 4
OGG = b"OggS\x00\x02" + b"\x00" * 20 + b"\x01\x13OpusHead\x01\x01\x38\x01\x80\xbb\x00\x00\x00\x00\x00" + bytes(range(100)) * 4


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def j(r):
    try:
        return r.json()
    except ValueError:
        return {}


def voice(s, rid, data, name="Voice-message-20261020-1412.m4a", mime="audio/mp4", ms="4200", extra=None, files=None, body=None):
    d = {"voice": "1"}
    if ms is not None:
        d["duration_ms"] = ms
    if body is not None:
        d["body"] = body
    d.update(extra or {})
    return s.post(B + f"/api/team/rooms/{rid}/messages", data=d, files=files or [("file", (name, data, mime))])


def att(r):
    return (j(r).get("attachments") or [{}])[0]


def count(s, rid):
    return len(s.get(B + f"/api/team/rooms/{rid}/messages").json()["messages"])


if not os.environ.get("P2139B_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(ENV)),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    assert r.returncode == 0, r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta"}).json()["id"]
ids = {}
for u, o in (("bob", ORG), ("carol", ORG), ("eve", BETA)):
    r = A.post(B + "/api/users", json={"orgs": [o], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, EVE = ids["bob"], ids["carol"], ids["eve"]
Bo, Ca, Ev = sess("bob"), sess("carol"), sess("eve")
for x in (A, Bo, Ca, Ev):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "comments"], "username": "claude", "display_name": "Claude", "org_id": ORG})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
TEAM = A.post(B + "/api/lists", json={"name": "Team", "org_id": ORG}).json()["id"]
for uid in (BOB, CAROL):
    assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": uid, "role": "edit"}).ok

# ================================================================== page headers
r = A.get(B + "/")
pp, csp = r.headers.get("Permissions-Policy", ""), r.headers.get("Content-Security-Policy", "")
check("microphone=(self)" in pp and "camera=()" in pp and "geolocation=()" in pp, "headers: the microphone for the app itself only " + pp)
check("media-src 'self' https: blob:" in csp and "script-src 'self';" in csp, "headers: media from blob: (preview), scripts unchanged " + csp[:300])

# ================================================================== a voice message in a closed channel
r = A.post(B + "/api/team/channels", json={"name": "Studio", "org_id": ORG, "members": [BOB]})
assert r.status_code == 201, r.text
CH = r.json()["id"]
r = voice(Bo, CH, M4A)
a = att(r)
check(r.status_code == 201 and a.get("voice") is True and a.get("duration_ms") == 4200 and a.get("mime") == "audio/mp4"
      and a.get("name") == "Voice-message-20261020-1412.m4a" and a.get("size") == len(M4A) and j(r).get("body") == "",
      "voice: stored as a voice message (m4a) " + r.text[:300])
VF = a.get("id")
m = [x for x in A.get(B + f"/api/team/rooms/{CH}/messages").json()["messages"] if x["attachments"]]
check(m and m[-1]["attachments"][0]["voice"] is True and m[-1]["attachments"][0]["duration_ms"] == 4200, "voice: alice sees voice + duration_ms in the page")

# served inline as audio, Range = 206 (the file is sealed at rest: the server runs with a master key)
r = A.get(B + f"/api/team/files/{VF}")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("audio/mp4") and r.content == M4A
      and r.headers.get("Content-Disposition", "").startswith("inline") and r.headers.get("X-Content-Type-Options") == "nosniff"
      and r.headers.get("Accept-Ranges") == "bytes", "file: audio/mp4 inline, nosniff, ranges " + str(dict(r.headers))[:400])
r = A.get(B + f"/api/team/files/{VF}", headers={"Range": "bytes=0-9"})
check(r.status_code == 206 and r.headers.get("Content-Range") == f"bytes 0-9/{len(M4A)}" and r.content == M4A[:10],
      f"file: Range bytes=0-9 -> 206 {r.status_code} {r.headers.get('Content-Range')}")
r = A.get(B + f"/api/team/files/{VF}", headers={"Range": f"bytes={len(M4A) - 16}-"})
check(r.status_code == 206 and r.content == M4A[-16:], "file: an open Range at the end -> 206 " + str(r.status_code))
r = Bo.get(B + f"/api/team/files/{VF}?dl=1")
check(r.ok and r.headers.get("Content-Disposition", "").startswith("attachment") and r.content == M4A, "file: ?dl=1 = download")
try:
    import dbx  # noqa: E402
    path = dbx.connect(DATA).execute("SELECT path FROM tchat_files WHERE id=?", (VF,)).fetchone()[0]
    raw = open(os.path.join(DATA, "attachments", path), "rb").read()
    check(M4A[:24] not in raw, "file: stored sealed at rest (Range above went through the decryption)")
except (PermissionError, FileNotFoundError, ImportError) as e:
    print("note: sealed state not readable here:", e)
check(Ca.get(B + f"/api/team/files/{VF}").status_code == 404 and Ev.get(B + f"/api/team/files/{VF}").status_code == 404,
      "file: carol (not a member) and eve (Beta) get 404")
check(Ca.get(B + f"/api/team/files/{VF}", headers={"Range": "bytes=0-9"}).status_code == 404, "file: no Range for others either")

# the name ending follows the content; webm / ogg; the length is capped / unknown
r = voice(Bo, CH, M4A, name="Voice-message.webm", mime="audio/webm")
check(r.status_code == 201 and att(r).get("name") == "Voice-message.m4a" and att(r).get("mime") == "audio/mp4", "voice: the ending follows the content " + r.text[:200])
r = voice(Bo, CH, WEBM, name="Voice-message.webm", mime="audio/webm;codecs=opus", ms="999999999")
check(r.status_code == 201 and att(r).get("mime") == "audio/webm" and att(r).get("duration_ms") == 5 * 60 * 1000 + 1000,
      "voice: webm, the length capped " + r.text[:200])
WF = att(r).get("id")
r = Bo.get(B + f"/api/team/files/{WF}", headers={"Range": "bytes=4-7"})
check(r.status_code == 206 and r.headers.get("Content-Type", "").startswith("audio/webm") and r.content == WEBM[4:8], "file: webm Range " + str(r.status_code))
r = voice(Bo, CH, OGG, name="Voice-message.ogg", mime="audio/ogg", ms="abc")
check(r.status_code == 201 and att(r).get("mime") == "audio/ogg" and att(r).get("duration_ms") is None, "voice: ogg, an unreadable length = null " + r.text[:200])
r = voice(Bo, CH, M4A, ms=None, body="Listen to this")
check(r.status_code == 201 and j(r).get("body") == "Listen to this" and att(r).get("voice") is True, "voice: with a text and no length " + r.text[:200])

# refused: not audio, more than one file, a wrong voice value (nothing stored)
n0 = count(Bo, CH)
r = voice(Bo, CH, PNG, name="pic.m4a", mime="audio/mp4")
check(r.status_code == 400 and "audio" in r.text, "voice: a picture is no voice message (400) " + r.text[:200])
r = voice(Bo, CH, b"just some text, not a recording", name="note.m4a", mime="audio/mp4")
check(r.status_code == 400, "voice: a text is no voice message (400) " + r.text[:200])
r = voice(Bo, CH, None, files=[("file", ("a.m4a", M4A, "audio/mp4")), ("file", ("b.m4a", M4A, "audio/mp4"))])
check(r.status_code == 400 and "exactly one" in r.text, "voice: two files (400) " + r.text[:200])
r = voice(Bo, CH, M4A, extra={"voice": "2"})
check(r.status_code == 400, "voice: voice=2 (400) " + r.text[:200])
check(count(Bo, CH) == n0, "voice: a refused voice message leaves nothing behind")

# a normal audio file: the player too, but no voice message
r = Bo.post(B + f"/api/team/rooms/{CH}/messages", data={"body": "The jingle"}, files=[("file", ("jingle.m4a", M4A, "audio/mp4"))])
a = att(r)
check(r.status_code == 201 and a.get("voice") is False and a.get("duration_ms") is None and a.get("mime") == "audio/mp4", "audio file: voice false " + r.text[:200])
# 2.139.0 review (F1): only a voice message (content checked as audio) plays inline; another audio file is a download
check(Bo.get(B + f"/api/team/files/{a.get('id')}").headers.get("Content-Disposition", "").startswith("attachment"), "audio file: a download")
r = Bo.post(B + f"/api/team/rooms/{CH}/messages", data={"body": "Notes"}, files=[("file", ("n.txt", b"notes", "text/plain"))])
check(r.status_code == 201 and att(r).get("voice") is False, "plain file: voice false")

# ================================================================== agents: read it, cannot send one
assert A.post(B + f"/api/team/rooms/{CH}/members", json={"user_id": CL}).ok
cur = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
r = voice(Bo, CH, M4A, body=f"<@{CL}> please listen", ms="1500")
ev = [e for e in requests.get(V + f"/agent/events?since={cur}&limit=50", headers=CLH).json()["data"] if e.get("event") == "team_message"]
ea = ev[-1]["data"]["message"]["attachments"] if ev else []
check(len(ea) == 1 and ea[0]["voice"] is True and ea[0]["duration_ms"] == 1500 and ea[0]["url"].startswith("/api/v1/team/files/"),
      "agent: team_message carries voice + duration_ms " + str(ea)[:300])
rr = requests.get(V + f"/team/rooms/{CH}/messages", headers=CLH)
va = [f for x in rr.json()["data"] for f in x["attachments"] if f["voice"]]
check(rr.ok and len(va) >= 3 and all("duration_ms" in f for f in va), "agent: REST messages carry voice / duration_ms")
r = requests.get(V + f"/team/files/{VF}", headers={**CLH, "Range": "bytes=0-3"})
check(r.status_code == 206 and r.content == M4A[:4], "agent: downloads a voice message (Range too) " + str(r.status_code))
r = requests.post(V + f"/team/rooms/{CH}/messages", headers=CLH, data={"body": "x", "voice": "1"}, files=[("file", ("v.m4a", M4A, "audio/mp4"))])
check(r.status_code == 400, "agent: the REST API takes no voice field " + r.text[:200])

# ================================================================== refused conversations
r = A.post(B + "/api/team/channels", json={"name": "Old", "org_id": ORG, "members": [BOB]})
OLD = r.json()["id"]
assert A.patch(B + f"/api/team/rooms/{OLD}", json={"archived": True}).ok
check(voice(A, OLD, M4A).status_code == 409, "archived channel: no voice message")


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def keys():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


assert A.put(B + "/api/e2e/keys", json=keys()).ok and Bo.put(B + "/api/e2e/keys", json=keys()).ok
DM = A.post(B + "/api/team/dm", json={"user_id": BOB}).json()["id"]
check(A.post(B + f"/api/team/rooms/{DM}/e2e", json={"on": True}).ok, "e2e: the DM is encrypted")
check(voice(A, DM, M4A).status_code == 409, "e2e: an encrypted DM refuses a voice message")
A.post(B + f"/api/team/rooms/{DM}/e2e", json={"on": False})
r = voice(A, DM, M4A)
check(r.status_code == 201 and att(r).get("voice") is True, "e2e off: the DM takes it " + r.text[:200])
DF = att(r).get("id")
check(Bo.get(B + f"/api/team/files/{DF}", headers={"Range": "bytes=0-9"}).status_code == 206, "DM: bob plays it (206)")
check(Ca.get(B + f"/api/team/files/{DF}").status_code == 404, "DM: carol gets 404")

# ================================================================== a person without an organisation
# freelancer-matrix: chat
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
import dbx  # noqa: E402,F811  (two freelancers work together through a group of the instance, as in p2113b_b)
DBC = dbx.connect(DATA)
DBC.execute("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)", ("Freelance pool", "", "2026-10-20T08:00:00", ALICE))
GID = DBC.execute("SELECT id FROM groups WHERE name=?", ("Freelance pool",)).fetchone()[0]
for x in (FID, FIO):
    DBC.execute("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GID, x, "2026-10-20T08:00:00"))
r = Fr.post(B + "/api/team/dm", json={"user_id": FIO})
check(r.ok, "freelancer: a direct message with fiona " + r.text[:200])
FDM = j(r).get("id")
r = voice(Fr, FDM, WEBM, name="Voice-message.webm", mime="audio/webm", ms="3000")
check(r.status_code == 201 and att(r).get("voice") is True and att(r).get("duration_ms") == 3000, "freelancer: sends a voice message " + r.text[:200])
FF = att(r).get("id")
r = Fi.get(B + f"/api/team/files/{FF}", headers={"Range": "bytes=0-3"})
check(r.status_code == 206 and r.content == WEBM[:4] and r.headers.get("Content-Type", "").startswith("audio/webm"), "freelancer: fiona plays it (206)")
check(Bo.get(B + f"/api/team/files/{FF}").status_code == 404 and A.get(B + f"/api/team/files/{FF}").status_code == 404,
      "freelancer: bob and the instance admin get 404")
check(voice(Fr, FDM, PNG, name="x.m4a").status_code == 400, "freelancer: a picture is refused as a voice message")

print(f"p2139_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
