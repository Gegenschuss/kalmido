#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.658.0 part C API test (#5015): an audio file of the file store in the sign-off -- played like an audio link (the
browser's <audio>, comments at a second, versions, the customer link); the file's access applies. Own container (start.sh,
workspaces). Invented companies, people and files only.
freelancer-matrix: videos
 - the type by the first bytes: MP3 (ID3 / a frame), WAV, OGG, FLAC, M4A, AAC (ADTS) are audio, a JPEG stays an image,
   anything else is nothing (in the app's container, vdm_sniff)
 - an MP3 uploaded at a task: kind video, provider audio, timed, its file in "Approvals", embed = content = the route of its
   bytes (audio/mpeg, a range request 206, sandboxed, nosniff); HTML named .mp3: 400
 - a comment at 00:42 keeps its second; a point {x, y}: 400; a WAV of the file store (file_id) = v2, v1 keeps its bytes
 - rights: a member who sees the task but not the file: 404 (review, bytes); another organisation: 404; another
   organisation's file as a version: 404
 - the customer link: the page plays the newest version's file from /s/q/<token>/media (<audio>, no question first: no
   third party), CSP media-src keeps https: and adds 'self'; the media route gives exactly that file (also with ?v=<v1>),
   a range 206; the file in the trash: gone (404), restored: back; the link revoked: 404; a decided link: 404
 - a person without an organisation: an MP3 of her own file store at a private task, a comment at a second, the customer
   link plays it; a stranger: 404
usage: p2658_c_audiofile_test.py <datadir>      (P2658C_NOSTART=1: a running server, no start.sh)"""
import ast
import os
import re
import struct
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
import kt  # noqa: E402
from kt import check, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,videos,files"
V = "/api/videos"

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x64" + bytes(range(256)) * 16
WAV = b"RIFF" + struct.pack("<I", 36 + 2000) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8) + b"data" + struct.pack("<I", 2000) + b"\x80" * 2000
HTML = b"<!doctype html><script>alert(1)</script>"


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", CT], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def store(s, name, data, mime, space):
    r = s.post(B + "/api/files/upload", files={"file": (name, data, mime)}, data={"space": space})
    check(r.status_code == 201, f"{name} into the file store ({space}) {r.status_code} {r.text[:200]}")
    return r.json()["items"][0]["id"] if r.status_code == 201 else 0


def page(tok):
    return requests.get(B + "/s/q/" + tok, headers={"Accept-Language": "en"}, allow_redirects=False)


def media(tok, **kw):
    return requests.get(B + f"/s/q/{tok}/media", allow_redirects=False, **kw)


if os.environ.get("P2658C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)

# ---- the type by the first bytes (in the app's container)
PROBE = r"""import app
from kalmido.videos.vdmedia import vdm_sniff, vdm_kind
cases = {"mp3id3": b"ID3\x04" + bytes(20), "mp3frame": b"\xff\xfb\x90\x64" + bytes(20), "wav": b"RIFF\x00\x00\x00\x00WAVEfmt ",
         "ogg": b"OggS\x00\x02" + bytes(20), "flac": b"fLaC\x00\x00\x00\x22", "m4a": b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00",
         "aac": b"\xff\xf1\x50\x80" + bytes(20), "jpeg": b"\xff\xd8\xff\xe0" + bytes(20), "mp4video": b"\x00\x00\x00\x20ftypisom",
         "html": b"<html>", "zero": bytes(32)}
print("SNIFF", sorted((k, vdm_sniff(v), vdm_kind(vdm_sniff(v))) for k, v in cases.items()))
"""
out = subprocess.run(["docker", "exec", CT, "python", "-c", PROBE], capture_output=True, text=True)
got = dict((k, (m, kd)) for k, m, kd in ast.literal_eval(out.stdout.split("SNIFF", 1)[1])) if "SNIFF" in out.stdout else {}
check(got.get("mp3id3") == ("audio/mpeg", "video") and got.get("mp3frame") == ("audio/mpeg", "video") and got.get("wav") == ("audio/wav", "video")
      and got.get("ogg") == ("audio/ogg", "video") and got.get("flac") == ("audio/flac", "video") and got.get("m4a") == ("audio/mp4", "video")
      and got.get("aac") == ("audio/aac", "video"), f"audio by its first bytes {got} {out.stderr[-500:]}")
check(got.get("jpeg") == ("image/jpeg", "image") and got.get("mp4video") == (None, None) and got.get("html") == (None, None)
      and got.get("zero") == (None, None), f"a JPEG stays an image, a video file / HTML / zeros are nothing {got}")

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE, BOB, CAROL = (s.get(B + "/api/state").json()["me"]["id"] for s in (A, Bo, Ca))
ORG = A.post(B + "/api/admin/orgs", json={"name": "Tonstudio Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
L = A.post(B + "/api/lists", json={"name": "Podcast Folge 7", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok
T = A.post(B + "/api/tasks", json={"title": "Mischung", "list_id": L}).json()["id"]
check(Bo.get(B + f"/api/tasks/{T}").ok, "bob sees the task (shared project)")

# ---- an MP3 uploaded at the task
r = A.post(B + V, files={"file": ("mix-v1.mp3", MP3, "audio/mpeg")}, data={"task_id": str(T), "title": "Mix"})
if not r.ok:
    app_log()
check(r.ok, f"an MP3 upload at a task {r.status_code} {r.text[:300]}")
R = r.json() if r.ok else {"id": 0, "versions": [{}]}
RID, V1 = R["id"], R["versions"][0]
check(R.get("kind") == "video" and V1.get("kind") == "video" and V1.get("provider") == "audio" and V1.get("timed") is True
      and V1.get("mime") == "audio/mpeg" and V1.get("file_id") and V1.get("file_name") == "mix-v1.mp3",
      f"the version is a timed audio of the file store {V1}")
check(V1.get("content") == f"{V}/{RID}/versions/{V1.get('id')}/file" and V1.get("embed") == V1.get("content"),
      f"the player plays the route of its bytes {V1.get('embed')} {V1.get('content')}")
r = A.get(B + (V1.get("content") or "/x"))
check(r.ok and r.headers.get("Content-Type", "").startswith("audio/mpeg") and r.content == MP3, f"the bytes as audio/mpeg {r.status_code} {r.headers.get('Content-Type')}")
check("sandbox" in r.headers.get("Content-Security-Policy", "") and r.headers.get("X-Content-Type-Options") == "nosniff", "sandboxed, nosniff")
r = A.get(B + (V1.get("content") or "/x"), headers={"Range": "bytes=100-199"})
check(r.status_code == 206 and r.content == MP3[100:200], f"seeking: a range request 206 {r.status_code} {len(r.content)}")
r = A.post(B + V, files={"file": ("fake.mp3", HTML, "audio/mpeg")}, data={"task_id": str(T)})
check(r.status_code == 400, f"HTML named .mp3: 400 {r.status_code}")

# ---- comments at a second, a second version from the file store
c = A.post(B + f"{V}/{RID}/comments", json={"body": "Hier knackt es", "at_sec": 42})
check(c.ok and [x for x in c.json().get("comments", []) if x["body"] == "Hier knackt es"][0]["at_sec"] == 42.0, f"a comment at 00:42 {c.status_code} {c.text[:200]}")
check(A.post(B + f"{V}/{RID}/comments", json={"body": "x", "pos": {"x": 0.5, "y": 0.5}}).status_code == 400, "a point on audio: 400")
FW = store(A, "mix-v2.wav", WAV, "audio/wav", f"org:{ORG}")
r = A.post(B + f"{V}/{RID}/versions", json={"file_id": FW})
check(r.ok and r.json()["versions"][-1].get("provider") == "audio" and r.json()["versions"][-1].get("mime") == "audio/wav"
      and r.json()["versions"][-1].get("file_id") == FW, f"a WAV of the file store = v2 {r.status_code} {r.text[:300]}")
V2 = r.json()["versions"][-1] if r.ok else {"id": 0, "content": "/x"}
check(A.get(B + V1["content"]).content == MP3 and A.get(B + V2["content"]).content == WAV, "v1 and v2 each play their own file")

# ---- rights: the file's access
check(Bo.get(B + f"{V}/{RID}").status_code == 404 and Bo.get(B + V1["content"]).status_code == 404, "bob sees the task but not the file: 404")
check(Ca.get(B + f"{V}/{RID}").status_code == 404 and Ca.get(B + V2["content"]).status_code == 404, "another organisation: 404")
FC = store(Ca, "fremd.mp3", MP3, "audio/mpeg", f"org:{ORG2}")
check(A.post(B + f"{V}/{RID}/versions", json={"file_id": FC}).status_code == 404, "another organisation's file as a version: 404")

# ---- the customer link: exactly the newest version's file, only while the link holds
so = A.post(B + f"{V}/{RID}/signoff", json={})
check(so.ok, f"a customer link for a stored audio {so.status_code} {so.text[:200]}")
TOK = so.json()["url"].split("/s/q/")[1] if so.ok else "x"
SID = so.json().get("id") if so.ok else 0
p = page(TOK)
check(p.status_code == 200 and f'<audio src="/s/q/{TOK}/media"' in p.text and 'data-prov="audio"' in p.text and "Load audio" not in p.text,
      f"the page plays the file from the link's media route, no question first {p.status_code}")
csp = p.headers.get("Content-Security-Policy", "")
check("media-src https: 'self'" in csp, f"CSP: https media as before + 'self' {csp}")
m = media(TOK)
check(m.status_code == 200 and m.headers.get("Content-Type", "").startswith("audio/wav") and m.content == WAV, f"the media route: the newest version's file {m.status_code}")
check(m.headers.get("X-Content-Type-Options") == "nosniff" and "sandbox" in m.headers.get("Content-Security-Policy", "")
      and "noindex" in m.headers.get("X-Robots-Tag", ""), f"sandboxed, nosniff, noindex {dict(m.headers)}")
check(media(TOK, params={"v": V1["id"]}).content == WAV, "no way to an older version's file")
m = media(TOK, headers={"Range": "bytes=0-43"})
check(m.status_code == 206 and m.content == WAV[:44], f"the customer seeks: 206 {m.status_code}")
check(media("A" * 43).status_code == 404, "an unknown token: 404")
check(A.delete(B + f"/api/files/nodes/{FW}").ok, "alice moves the WAV to the trash")
check(media(TOK).status_code == 404, "the file in the trash: the link does not give it")
check(A.post(B + f"/api/files/nodes/{FW}/restore").ok, "restored")
check(media(TOK).status_code == 200, "restored: the link plays it again")
check(A.post(B + f"{V}/{RID}/signoffs/{SID}/revoke").ok, "the link revoked")
r = requests.get(B + f"/s/q/{TOK}/media", allow_redirects=False)
check(r.status_code == 404 and page(TOK).status_code == 404, "revoked: page and file gone")
so = A.post(B + f"{V}/{RID}/signoff", json={})
TOK2 = so.json()["url"].split("/s/q/")[1] if so.ok else "x"
p = page(TOK2)
fm = re.search(r'class="fform sigf">.*?name="f" value="([^"]+)".*?name="v" value="([^"]+)"', p.text, re.S)
d = requests.post(B + "/s/q/" + TOK2, data={"f": fm.group(1) if fm else "", "v": fm.group(2) if fm else "", "name": "Kundin Example",
                                            "ok": "1", "do": "accept"}, allow_redirects=False, headers={"Accept-Language": "en"})
check(d.status_code in (200, 302, 303) and A.get(B + f"{V}/{RID}").json().get("state") == "approved", f"the customer approves {d.status_code}")
check(media(TOK2).status_code == 404, "decided: the file is no longer handed out")

# ---- a person without an organisation
FRI, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
FL = Fr.post(B + "/api/lists", json={"name": "Eigener Podcast"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Intro", "list_id": FL}).json()["id"]
FF = store(Fr, "intro.mp3", MP3, "audio/mpeg", "private")
r = Fr.post(B + V, json={"task_id": FT, "file_id": FF})
check(r.ok and r.json()["versions"][0].get("provider") == "audio", f"frida: an MP3 of her file store at her private task {r.status_code} {r.text[:300]}")
FR = r.json() if r.ok else {"id": 0, "versions": [{"content": "/x"}]}
c = Fr.post(B + f"{V}/{FR['id']}/comments", json={"body": "Lauter", "at_sec": 3})
check(c.ok, f"frida: a comment at 00:03 {c.status_code}")
check(Fr.get(B + FR["versions"][0]["content"]).content == MP3, "frida: the bytes")
check(Ca.get(B + f"{V}/{FR['id']}").status_code == 404 and Ca.get(B + FR["versions"][0]["content"]).status_code == 404, "a stranger: 404")
so = Fr.post(B + f"{V}/{FR['id']}/signoff", json={})
check(so.ok, f"frida: a customer link {so.status_code} {so.text[:200]}")
FTOK = so.json()["url"].split("/s/q/")[1] if so.ok else "x"
m = media(FTOK)
if m.status_code != 200:
    app_log()
check(m.status_code == 200 and m.content == MP3, f"frida's customer plays the file {m.status_code}")

sys.exit(kt.done("p2658_c_audiofile"))
