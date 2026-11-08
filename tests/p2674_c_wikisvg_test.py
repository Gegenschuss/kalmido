#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.674.0 C (#4028, review F14 of 2.488.0): the files of a knowledge page through the API v1 (wiki/wkv1.py wkv_file_get).
 - an SVG drawing never comes as a picture: Content-Type application/octet-stream, as an attachment, "image": false in the list
   (the web app's own route /api/wiki/files/{id} keeps the cleaned SVG in its sandbox)
 - the agent's download is noted in the page node's history (fs_log) only when the bytes go out: not for HEAD, not for a file
   missing on the disk (404)
usage: p2674_c_wikisvg_test.py <datadir>"""
import base64

import requests

import kt
from kt import B, check, dbx, done, sess

V = B + "/api/v1"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "wiki,files,collab,comments", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/wiki/pages", json={"space": f"org:{ORG}", "path": "Drawings/Plan", "body": "text"})
assert r.status_code == 201, r.text
P = r.json()["id"]
r = A.post(B + f"/api/wiki/pages/{P}/files", files=[("file", ("Plan.svg", SVG, "image/svg+xml")), ("file", ("Dot.png", PNG, "image/png"))])
assert r.status_code == 201, r.text
FS, FP = [f["id"] for f in r.json()["files"]]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "wiki:read"], "username": "drawbot", "display_name": "Drawbot", "org_id": ORG})
assert r.status_code == 201, r.text
AG = r.json()["id"]
t = requests.Session()
t.headers.update({"Authorization": "Bearer " + r.json()["token"]})
FOLDER = {f["path"]: f["id"] for f in A.get(B + "/api/wiki", params={"space": f"org:{ORG}"}).json().get("folders", [])}.get("Drawings")
assert FOLDER, "the knowledge folder Drawings"
assert A.post(B + f"/api/files/nodes/{FOLDER}/shares", json={"agent_id": AG, "role": "view"}).status_code == 201
NODE = dbx("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (P,))[0][0]


def downloads():
    return dbx("SELECT COUNT(*) FROM fs_log WHERE node_id=? AND agent=1 AND action='download'", (NODE,))[0][0]


# ---------------------------------------------------------------- SVG: a download, never a picture
L = {x["id"]: x for x in t.get(V + f"/wiki/pages/{P}/files").json().get("data", [])}
check(L.get(FS, {}).get("image") is False and L.get(FS, {}).get("mime") == "image/svg+xml",
      f"F14: the SVG in the list: image false ({L.get(FS)})")
check(L.get(FP, {}).get("image") is True, "a PNG stays a picture")
n0 = downloads()
r = t.get(V + f"/wiki/files/{FS}")
ct, cd = r.headers.get("Content-Type", ""), r.headers.get("Content-Disposition", "")
check(r.status_code == 200 and ct.startswith("application/octet-stream") and cd.startswith("attachment") and b"<svg" in r.content,
      f"F14: the SVG through the API as a download ({r.status_code} {ct} {cd})")
check(r.headers.get("X-Content-Type-Options") == "nosniff", "the SVG download: nosniff")
check(downloads() == n0 + 1, "a GET of the bytes is noted once")
r = A.get(B + f"/api/wiki/files/{FS}")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/svg+xml") and "sandbox" in r.headers.get("Content-Security-Policy", ""),
      f"the web app's route keeps the SVG as a picture in its sandbox ({r.headers.get('Content-Type')})")

# ---------------------------------------------------------------- HEAD and a missing file: no download in the history
n1 = downloads()
r = t.head(V + f"/wiki/files/{FP}")
check(r.status_code == 200, f"HEAD answers ({r.status_code})")
r = t.head(V + f"/wiki/files/{FS}")
check(downloads() == n1, f"F14: HEAD is not noted as a download ({downloads()} vs {n1})")
t.get(V + f"/wiki/files/{FP}")
check(downloads() == n1 + 1, "the GET after it is")
dbx("UPDATE wiki_files SET path='wiki/missing-4028.bin' WHERE id=?", (FP,))
n2 = downloads()
r = t.get(V + f"/wiki/files/{FP}")
check(r.status_code == 404, f"a file missing on the disk: 404 ({r.status_code})")
check(downloads() == n2, "F14: a 404 is not noted as a download")

raise SystemExit(done("p2674_c_wikisvg"))
