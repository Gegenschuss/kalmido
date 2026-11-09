#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.773.0 part C API test (#5330): the customer link of a sign-off (/s/q/<token>/media, videos/vdmedia.py vdm_pub_send)
notes a guest's fetch of the file in the file's history and does not hand out a sealed file above a size limit. Own
container (org encryption on, the limit set small through KALMIDO_REVIEW_LINK_SEALED_MAX_MB). Invented companies, people and
files only.
freelancer-matrix: videos
 - a guest's fetch from byte 0: one history entry (action ext_view, detail "approval <id>", no person); a seek (a range not
   from byte 0): no further entry; the owner sees the entry in the file's history
 - a sealed file above the limit: 413 through the link, no content, nothing in the history; signed in it still plays
 - a sealed file below the limit: 200 through the link as before
 - a person without an organisation: the guest's fetch of her link is in her file's history too
usage: p2773_c_reviewlink_log_test.py <datadir>      (a fresh container; P2773C_NOSTART=1 = the server already runs)"""
import base64
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
LIMIT = 2048  # bytes (the switch in MB below)
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY,
              "KALMIDO_REVIEW_LINK_SEALED_MAX_MB": str(LIMIT / (1024 * 1024))}, prefix="P2773C")
FEAT = "cal,comments,collab,office,clients,videos,files"
V = "/api/videos"
SMALL = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x64" + bytes(range(256)) * 2     # 526 bytes: below the limit
BIG = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x64" + bytes(range(256)) * 16      # 4110 bytes: above it


def media(tok, **kw):
    return requests.get(B + f"/s/q/{tok}/media", allow_redirects=False, **kw)


def sealed(fid):
    """Whether the current version of file fid is stored sealed (core/orgcrypt.py), asked inside the app container."""
    code = f"""import json, os
import app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.core.config import ATT_DIR
from kalmido.core import orgcrypt as oc
c = connect()
with system_ctx(c):
    rel = c.execute("SELECT v.path FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id AND v.no=n.cur_version WHERE n.id=?", ({int(fid)},)).fetchone()[0]
print(json.dumps(oc.oc_is_sealed_file(os.path.join(ATT_DIR, rel))))"""
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else f"error {r.stderr[-400:]}"


def link_log(fid):
    return [tuple(x) for x in dbx("SELECT action, detail, user_id FROM fs_log WHERE node_id=? AND action='ext_view' ORDER BY id", (fid,))]


def review(s, task, name, data):
    r = s.post(B + V, files={"file": (name, data, "audio/mpeg")}, data={"task_id": str(task), "title": name})
    check(r.ok, f"an MP3 upload at a task ({name}) {r.status_code} {r.text[:300]}")
    R = r.json() if r.ok else {"id": 0, "versions": [{"file_id": 0, "content": "/x"}]}
    so = s.post(B + f"{V}/{R['id']}/signoff", json={})
    check(so.ok, f"a customer link ({name}) {so.status_code} {so.text[:200]}")
    return R, (so.json()["url"].split("/s/q/")[1] if so.ok else "x")


A = kt.setup()
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Tonstudio Gamma", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
L = A.post(B + "/api/lists", json={"name": "Hoerspiel Folge 3", "org_id": ORG}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Mischung", "list_id": L}).json()["id"]

# ---- below the limit: the guest gets the file, the fetch is in the file's history (once per play, not per seek)
R1, TOK1 = review(A, T, "mix-klein.mp3", SMALL)
F1 = R1["versions"][0]["file_id"]
check(sealed(F1) is True, f"setup: the workspace's file is stored sealed {sealed(F1)}")
check(link_log(F1) == [], f"no guest entry before the first fetch {link_log(F1)}")
m = media(TOK1)
check(m.status_code == 200 and m.content == SMALL, f"a sealed file below the limit plays through the link {m.status_code}")
log = link_log(F1)
check(log == [("ext_view", f"approval {R1['id']}", None)], f"the guest's fetch: one history entry, no person {log}")
m = media(TOK1, headers={"Range": "bytes=100-199"})
check(m.status_code == 206 and m.content == SMALL[100:200], f"the guest seeks: 206 {m.status_code}")
check(len(link_log(F1)) == 1, f"a seek adds no entry {link_log(F1)}")
m = media(TOK1, headers={"Range": "bytes=0-"})
check(m.status_code in (200, 206) and len(link_log(F1)) == 2, f"playing again from byte 0: a second entry {len(link_log(F1))}")
n = A.get(B + f"/api/files/nodes/{F1}")
hist = [x for x in (n.json().get("log") or []) if x.get("action") == "ext_view"] if n.ok else []
check(n.ok and hist and hist[0].get("detail") == f"approval {R1['id']}" and not hist[0].get("user_id"),
      f"the owner sees the link's fetch in the file's history {n.status_code} {hist[:1]}")

# ---- above the limit: a defined answer without the content, signed in it plays
R2, TOK2 = review(A, T, "mix-gross.mp3", BIG)
F2 = R2["versions"][0]["file_id"]
check(sealed(F2) is True, f"setup: the large file is stored sealed {sealed(F2)}")
m = media(TOK2)
check(m.status_code == 413 and BIG[:64] not in m.content and b"ID3" not in m.content[:16]
      and m.headers.get("Content-Type", "").startswith("text/html"), f"a sealed file above the limit: 413 without content {m.status_code}")
check("File too large for the link" in m.text and "noindex" in m.headers.get("X-Robots-Tag", ""), f"the answer says why, noindex {m.text[:200]}")
check(media(TOK2, headers={"Range": "bytes=0-99"}).status_code == 413, "a range does not get around it")
check(link_log(F2) == [], f"nothing handed out, nothing in the history {link_log(F2)}")
r = A.get(B + R2["versions"][0]["content"])
check(r.ok and r.content == BIG, f"signed in the large file still plays {r.status_code}")
check(media("A" * 43).status_code == 404, "an unknown token stays 404")

# ---- a person without an organisation
FRI, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes Hoerbuch"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Kapitel 1", "list_id": FL}).json()["id"]
FR, FTOK = review(Fr, FT, "kapitel.mp3", SMALL)
FF = FR["versions"][0]["file_id"]
m = media(FTOK)
check(m.status_code == 200 and m.content == SMALL, f"frida's customer plays the file {m.status_code}")
check(link_log(FF) == [("ext_view", f"approval {FR['id']}", None)], f"frida: the guest's fetch is in her file's history {link_log(FF)}")

sys.exit(kt.done("p2773_c_reviewlink_log"))
