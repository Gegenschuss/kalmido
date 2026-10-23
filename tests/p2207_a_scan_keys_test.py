#!/usr/bin/env python3
"""2.207.0 A API tests (#2763): scan inboxes for the folder watcher. Invented names only, generated file contents.
 - a person without an organisation makes a scan inbox of her own documents (one folder): the setup code decodes to
   {url, key, name}; an upload with the key lands in that folder and answers only {id, name}; ws / parent_id / other fields
   and JSON are refused (400); every other route of the API refuses the key (403); upload-target names the place
 - the key shows in the API tokens (upload only, its permissions cannot be changed); docs:upload is refused for ordinary
   tokens and for agents
 - an inbox of an organisation: the upload lands there; a folder of somebody else as the place is refused; after the person
   left the organisation the key gets 403; a folder in the trash 409; a revoked key 401
 - the admin's limit for personal tokens can switch docs:upload off and on again
 - the folder watcher downloads: fixed names only, 404 without the file, the file once it is there; the mail note is
   remembered per person
freelancer-matrix: files
usage: p2207_a_scan_keys_test.py <datadir>      (a fresh container; P2207A_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import base64
import json
import os
import subprocess
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, sess  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402

V = B + "/api/v1"
FW = "/tmp/fw2207"
kt.fresh(env={"KALMIDO_FOLDERWATCH_DIR": FW}, prefix="P2207A")
A = kt.setup()


def bearer(tok):
    return {"Authorization": "Bearer " + tok}


def up(tok, name="scan.txt", body=b"Rechnung Beispiel 4711", data=None, files=None):
    return requests.post(V + "/documents", headers=bearer(tok), files=files or {"file": (name, body, "text/plain")}, data=data or {})


def decode(code):
    assert code.startswith("kalmido-scan:1:"), code
    raw = code[len("kalmido-scan:1:"):]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


def node(nid):
    r = kt.dbx("SELECT parent_id, org_id, owner_id, name FROM fs_nodes WHERE id=?", (nid,))
    return r[0] if r else None


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol (member), frida without an organisation
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG), "setup: carol joins Alpha")
FRIDA, Fr = freelancer(B, A)
Ca = sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "files,docs,comments,collab"})


def first_doc(s, ws):
    r = s.post(B + "/api/docs", files={"files": ("start.txt", b"Start Beispiel", "text/plain")}, data={"ws": ws})
    assert r.ok, r.text
    return s.get(B + f"/api/docs/settings?ws={ws}").json()["root_id"]


# ==== a person without an organisation: her own documents (freelancer-matrix: files)
j = Fr.get(B + "/api/docs/scan-keys?ws=private").json()
check(j.get("api") is True and j.get("keys") == [] and j.get("downloads") == [] and j.get("mail_notice") is False,
      f"frida: the API is on, no inbox, no programs on this server, the mail note not read yet {j}")
ROOT = first_doc(Fr, "private")
r = Fr.post(B + "/api/files/folders", json={"name": "Belege", "parent_id": ROOT})
check(r.ok, f"setup: a folder Belege in frida's documents {r.text[:200]}")
FOLD = r.json().get("id")
check(any(f["id"] == FOLD for f in Fr.get(B + "/api/docs/settings?ws=private").json()["folders"]), "the folder is offered as a place")
r = Fr.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Scanner", "parent_id": FOLD})
check(r.status_code == 201 and r.json().get("name") == "Scanner" and "Belege" in r.json().get("target", ""), f"frida makes a scan inbox {r.text[:200]}")
K1ID, C1 = r.json().get("id"), decode(r.json().get("code", "kalmido-scan:1:"))
K1 = C1.get("key", "")
check(C1.get("url", "").startswith("http") and K1.startswith("abk_") and C1.get("name") == "Scanner", f"the setup code: url, key, name {C1}")
check(kt.dbx("SELECT token_hash, scopes FROM api_tokens WHERE id=?", (K1ID,))[0][0].startswith("u:"), "stored with its own hash prefix")
check(K1 not in json.dumps(Fr.get(B + "/api/docs/scan-keys?ws=private").json()), "the key is not listed again")
r = up(K1, "scan1.txt")
check(r.status_code == 201 and set(r.json()) == {"id", "name"}, f"upload with the key: 201 {{id, name}} only {r.status_code} {r.text[:200]}")
D1 = r.json().get("id")
n = node(D1)
check(n and n[0] == FOLD and n[1] is None and n[2] == FRIDA, f"the document lies in frida's folder Belege {n}")
check(kt.until(lambda: Fr.get(B + f"/api/docs/{D1}").ok, 10), "frida sees the document")
check(up(K1, data={"ws": "private"}).status_code == 400, "a ws field: 400")
check(up(K1, data={"parent_id": str(ROOT)}).status_code == 400, "a parent_id field: 400")
check(up(K1, data={"title": "x"}).status_code == 400, "a title field: 400")
check(up(K1, files={"other": ("a.txt", b"x", "text/plain")}).status_code == 400, "another file field: 400")
check(requests.post(V + "/documents", headers=bearer(K1), json={"name": "a.txt", "content_base64": "eA=="}).status_code == 400, "JSON: 400")
for m, p in (("GET", "/documents"), ("GET", "/me"), ("GET", f"/files/{D1}/content"), ("GET", f"/documents/{D1}"), ("GET", "/lists"),
             ("PATCH", f"/documents/{D1}"), ("POST", "/files"), ("GET", "/agent/events")):
    r = requests.request(m, V + p, headers=bearer(K1), json={} if m != "GET" else None)
    check(r.status_code == 403 and "only upload" in r.text, f"{m} {p} with the upload key: 403 {r.status_code} {r.text[:120]}")
r = requests.get(V + "/documents/upload-target", headers=bearer(K1))
check(r.ok and r.json().get("name") == "Scanner" and r.json().get("target") == "Your own documents / Belege" and isinstance(r.json().get("max_mb"), int),
      f"upload-target names the place {r.text[:200]}")
check(requests.get(V + "/documents/upload-target", headers=bearer("abk_" + "x" * 40)).status_code == 401, "upload-target with an unknown key: 401")

# ---- the API tokens: listed, upload only, not changeable; docs:upload never for ordinary tokens / agents
toks = Fr.get(B + "/api/me/tokens").json()
t = next((x for x in toks["tokens"] if x["id"] == K1ID), {})
check(t.get("upload_only") is True and t.get("effective_scopes") == ["docs:upload"], f"the key in the API tokens: upload only {t}")
check(not any(o["scope"] == "docs:upload" for o in toks["scopes"]), "docs:upload is not offered for new tokens")
check(Fr.patch(B + f"/api/me/tokens/{K1ID}", json={"scopes": ["read", "files:write"]}).status_code == 400, "its permissions cannot be changed")
check(Fr.patch(B + f"/api/me/tokens/{K1ID}", json={"name": "Scanner Flur"}).ok, "its name can")
check(Fr.post(B + "/api/me/tokens", json={"name": "x", "scopes": ["read", "docs:upload"]}).status_code == 400, "an ordinary token with docs:upload: 400")
r = Fr.post(B + "/api/me/tokens", json={"name": "files", "scopes": ["read", "files:write"]})
PT = r.json().get("token", "")
check(requests.get(V + "/documents/upload-target", headers=bearer(PT)).status_code == 403, "upload-target with an ordinary token: 403")
r = A.post(B + "/api/admin/agents", json={"username": "scanbot", "display_name": "Scanbot", "scopes": ["read", "docs:upload"]})
check(r.status_code == 400, f"an agent with docs:upload: 400 {r.status_code} {r.text[:160]}")
check("docs:upload" not in A.get(B + "/api/admin/agent-policy").json()["scope_limit"]["agents"], "agents' limit never lists docs:upload")

# ---- the admin's limit for personal tokens
pol = A.get(B + "/api/admin/agent-policy").json()
check("docs:upload" in pol["scope_limit"]["tokens"], "no limit: docs:upload allowed")
keep = [x for x in pol["scope_limit"]["tokens"] if x not in ("docs:upload", "admin-read")]
check(A.put(B + "/api/admin/agent-policy", json={"scope_limit": {"tokens": keep}}).ok, "the admin unticks docs:upload")
r = up(K1)
check(r.status_code == 403, f"over the limit the key is refused: {r.status_code} {r.text[:160]}")
check(A.put(B + "/api/admin/agent-policy", json={"scope_limit": {"tokens": keep + ["docs:upload"]}}).ok and up(K1).status_code == 201, "ticked again: it works")

# ==== an organisation: carol's inbox of Alpha
ORT = first_doc(Bo, f"org:{ORG}")
check(Fr.post(B + "/api/docs/scan-keys", json={"ws": f"org:{ORG}", "name": "X"}).status_code == 404, "frida cannot make an inbox of Alpha")
check(Ca.post(B + "/api/docs/scan-keys", json={"ws": f"org:{ORG}", "name": "Y", "parent_id": FOLD}).status_code == 400, "carol: frida's folder as the place: 400")
check(Ca.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Y", "parent_id": FOLD}).status_code == 400, "carol: frida's folder in her own space: 400")
check(Ca.post(B + "/api/docs/scan-keys", json={"ws": f"org:{ORG}", "name": " "}).status_code == 400, "a name is needed")
r = Ca.post(B + "/api/docs/scan-keys", json={"ws": f"org:{ORG}", "name": "Alpha Scanner"})
check(r.status_code == 201 and r.json().get("target") == "Alpha", f"carol makes an inbox of Alpha {r.text[:200]}")
K2ID, K2 = r.json().get("id"), decode(r.json().get("code", "kalmido-scan:1:")).get("key", "")
r = up(K2, "alpha.txt")
check(r.status_code == 201 and node(r.json().get("id"))[1] == ORG, f"the upload lands in Alpha's documents {r.text[:160]}")
lst = Ca.get(B + f"/api/docs/scan-keys?ws=org:{ORG}").json()["keys"]
check([k["id"] for k in lst] == [K2ID] and Ca.get(B + "/api/docs/scan-keys?ws=private").json()["keys"] == [], "listed only in Alpha's settings")
check(Fr.delete(B + f"/api/docs/scan-keys/{K2ID}").status_code == 404, "somebody else cannot revoke it")
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{CAROL}").ok, "setup: bob takes carol out of Alpha")
r = up(K2)
check(r.status_code == 403, f"after leaving Alpha the key gets 403 {r.status_code} {r.text[:160]}")
check(requests.get(V + "/documents/upload-target", headers=bearer(K2)).status_code == 403, "upload-target too")

# ---- the folder in the trash: 409; revoked: 401
check(Fr.delete(B + f"/api/files/nodes/{FOLD}").ok, "setup: frida moves Belege to the trash")
r = up(K1)
check(r.status_code == 409, f"the folder is gone: 409 {r.status_code} {r.text[:160]}")
j = Fr.get(B + "/api/docs/scan-keys?ws=private").json()["keys"]
check(j and j[0]["ok"] is False, f"the settings mark the inbox {j}")
r = Fr.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Direkt"})
K3ID, K3 = r.json().get("id"), decode(r.json().get("code", "kalmido-scan:1:")).get("key", "")
r = up(K3)
check(r.status_code == 201 and node(r.json()["id"])[0] == ROOT, "an inbox without a folder: into the documents directly")
check(Fr.delete(B + f"/api/docs/scan-keys/{K3ID}").ok and up(K3).status_code == 401, "revoked: 401 at once")
check(Fr.delete(B + f"/api/me/tokens/{K1ID}").ok and up(K1).status_code == 401, "revoked in the API tokens: 401")

# ---- the folder watcher downloads, the mail note
check(Fr.get(B + "/api/docs/folder-watcher/evil.sh").status_code == 404, "an unknown name: 404")
check(Fr.get(B + "/api/docs/folder-watcher/SHA256SUMS").status_code == 404, "no file on this server: 404")
subprocess.run(["docker", "exec", CT, "sh", "-c", f"mkdir -p {FW} && printf 'abc  kalmido-folder-watcher-windows.exe\\n' > {FW}/SHA256SUMS"], check=True)
r = Fr.get(B + "/api/docs/folder-watcher/SHA256SUMS")
check(r.ok and r.text.startswith("abc") and "attachment" in r.headers.get("Content-Disposition", ""), f"the file once it is there {r.status_code}")
d = Fr.get(B + "/api/docs/settings?ws=private").json()["scan"]["downloads"]
check([x["file"] for x in d] == ["SHA256SUMS"], f"the settings list the programs there are {d}")
check(requests.get(B + "/api/docs/folder-watcher/SHA256SUMS", headers={"X-Requested-With": "kalmido"}).status_code in (401, 403), "signed in only")
check(Fr.post(B + "/api/docs/mail-notice").ok and Fr.get(B + "/api/docs/scan-keys?ws=private").json()["mail_notice"] is True, "the mail note is remembered")
check(Ca.get(B + "/api/docs/scan-keys?ws=private").json()["mail_notice"] is False, "per person")

sys.exit(kt.done("p2207_a_scan_keys"))
