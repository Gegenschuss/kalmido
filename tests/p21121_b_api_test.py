#!/usr/bin/env python3
"""2.112.1 B API tests (#2058): external share links of the file store ("Ablage"). Invented names, generated contents.
 - who: only who may share the node (its owners); view / edit shares, a stranger, an agent: refused; not for an agent's
   folder, a node in the trash, while the organisation's or the server's switch is off
 - the page /s/f/<token>: a file (name, size, download, preview of safe images only) and a folder (its folders and files,
   subfolders through ?p= inside the shared tree only); headers (CSP, noindex, no-store, no-referrer, nosniff, attachment)
 - every rule on every request: expiry, revoke (undo = restore), renew (the old address dies), trash (the node or a folder
   above), the creator loses the right to share, the organisation's switch, the server's switch -- always the same 404
 - password: the page asks, a download without the unlock cookie is refused, wrong / right password, guessing limited
 - traces: the node's history gets the views / downloads (no person, no address), the link counts views; the row badge
 - a person without an organisation (freelancer-matrix: files), other workspaces (tenant-matrix: fileextlink)
 - a move into another workspace ends the links; rollback: one new table + one new column
usage: p21121_b_api_test.py <datadir>      (a fresh container; P21121B_NOSTART=1: the container runs already)"""
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
IP = ["198.51.100.1"]  # the visitor's address (the test server trusts its gateway as a proxy); a new one per block


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
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if sql.lstrip().upper().startswith(("SELECT", "WITH")) else c.execute(sql, args)
        if write:
            c.commit()
        return r
    finally:
        c.close()


def up(s, name, data, parent=None, space=None, mime="application/octet-stream"):
    form = {"parent_id": str(parent)} if parent else {"space": space or "private"}
    r = s.post(B + "/api/files/upload", data=form, files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def folder(s, name, parent=None, space=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space or "private"})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def mk(s, nid, **b):
    return s.post(B + f"/api/files/nodes/{nid}/ext-links", json=b)


def path_of(url):
    return re.sub(r"^https?://[^/]+", "", url)


def newip():
    IP[0] = f"198.51.100.{int(IP[0].rsplit('.', 1)[1]) + 1}"


def pub(path, method="GET", cookies=None, **k):
    """A visitor without an account (own cookie jar unless given)."""
    jar = cookies if cookies is not None else requests.Session()
    return jar.request(method, B + path, headers={"X-Forwarded-For": IP[0]}, allow_redirects=False, timeout=30, **k)


if os.environ.get("P21121B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE}).json()["id"]
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com",
                                       "orgs": [ORG]})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "dave", "display_name": "Dave", "password": "password123", "email": "dave@example.com", "orgs": []})
assert r.ok, r.text
ids["dave"] = r.json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta Werkstatt", "admin_id": ids["dave"]}).json()["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "files:read", "files:write"], "username": "filebot", "display_name": "Filebot",
                                          "org_id": ORG})
assert r.status_code in (200, 201), r.text
AG, AGT = r.json()["id"], r.json()["token"]
AGH = {"Authorization": "Bearer " + AGT}

# ---- the organisation's tree: a shared folder with a file, a picture in a subfolder; a file outside it
F = folder(A, "Kundenordner Mai", space=f"org:{ORG}")
FA = up(A, "angebot.txt", b"Angebot Fruehling 2026\n", parent=F)
SUB = folder(A, "Bilder", parent=F)
PIC = up(A, "motiv.png", PNG, parent=SUB, mime="image/png")
OUT = up(A, "intern.txt", b"nur intern\n", space=f"org:{ORG}")
check(A.post(B + f"/api/files/nodes/{F}/shares", json={"user_id": ids["bob"], "role": "view"}).status_code == 201, "share: bob views the folder")
check(A.post(B + f"/api/files/nodes/{F}/shares", json={"user_id": ids["carol"], "role": "edit"}).status_code == 201, "share: carol edits it")

# ================================================================ who may make a link (tenant-matrix: fileextlink)
check(Bo.post(B + f"/api/files/nodes/{F}/ext-links", json={}).status_code == 403, "view share: no link (403)")
check(Ca.post(B + f"/api/files/nodes/{F}/ext-links", json={}).status_code == 403, "edit share: no link (only who may share)")
check(Da.post(B + f"/api/files/nodes/{F}/ext-links", json={}).status_code == 404, "another workspace: 404")
check(Da.get(B + f"/api/files/nodes/{F}/ext-links").status_code == 404, "another workspace: list 404")
check(Bo.get(B + f"/api/files/nodes/{F}/ext-links").status_code == 403, "view share: list 403")
r = requests.post(B + f"/api/files/nodes/{F}/ext-links", json={}, headers=AGH)
check(r.status_code in (401, 403, 404), f"agent token: refused ({r.status_code})")
check(not dbx("SELECT 1 FROM fs_ext_links"), "nothing stored after refusals")
r = mk(A, F, expires="2020-01-01")
check(r.status_code == 400, "expiry in the past refused")
r = mk(A, F, password="abc")
check(r.status_code == 400, "a password of 3 characters refused")

# ---- a folder link
r = mk(A, F, label="Kunde Nord")
check(r.ok and len(r.json()["links"]) == 1, "folder link made " + r.text[:200])
L1 = r.json()["links"][0]
FP = path_of(L1["url"])
check(FP.startswith("/s/f/") and len(FP) > 30 and L1["label"] == "Kunde Nord" and L1["has_password"] is False, "url / label / no password")
check(L1["expires_at"] and abs(datetime.fromisoformat(L1["expires_at"]) - datetime.now(timezone.utc) - timedelta(days=7)) < timedelta(minutes=5),
      "default expiry: 7 days")
row = dbx("SELECT token_hash, token, org_id, created_by FROM fs_ext_links WHERE id=?", (L1["id"],))[0]
tok = FP.rsplit("/", 1)[1]
check(tok not in row[1] and row[0] != tok and row[2] == ORG and row[3] == ALICE, "token stored sealed + hashed, org of the node, creator")
gone = pub("/s/f/" + "Q" * 32).text
r = pub(FP)
check(r.status_code == 200 and "angebot.txt" in r.text and "Bilder" in r.text and "intern.txt" not in r.text, "folder page: its content only")
check("Kunde Nord" not in r.text and "Alice" not in r.text and "<script" not in r.text.lower(), "page: no label, no names, no script")
h = r.headers
check("default-src 'none'" in h.get("Content-Security-Policy", "") and "noindex" in h.get("X-Robots-Tag", "")
      and "no-store" in h.get("Cache-Control", "") and h.get("Referrer-Policy") == "no-referrer", "page headers: CSP, noindex, no-store, no-referrer")
r = pub(f"{FP}?p={SUB}")
check(r.status_code == 200 and "motiv.png" in r.text and "angebot.txt" not in r.text, "subfolder through ?p=")
for bad, what in ((OUT, "a file outside"), (FA, "a file instead of a folder"), (999999, "an unknown id"), ("x", "no number")):
    check(pub(f"{FP}?p={bad}").status_code == 404, f"?p= {what}: 404")
r = pub(f"{FP}/d/{FA}")
check(r.status_code == 200 and r.content == b"Angebot Fruehling 2026\n", "download: the content")
check(r.headers.get("Content-Type", "").startswith("application/octet-stream") and "attachment" in r.headers.get("Content-Disposition", "")
      and r.headers.get("X-Content-Type-Options") == "nosniff" and "sandbox" in r.headers.get("Content-Security-Policy", "")
      and "no-store" in r.headers.get("Cache-Control", ""), "download headers: octet-stream, attachment, nosniff, sandbox")
check(pub(f"{FP}/d/{PIC}").status_code == 200, "download from a subfolder")
for bad, what in ((OUT, "a file outside the tree"), (SUB, "a folder"), (F, "the folder itself"), (999999, "an unknown id")):
    check(pub(f"{FP}/d/{bad}").status_code == 404, f"download {what}: 404")
r = pub(f"{FP}/v/{PIC}")
check(r.status_code == 200 and r.headers.get("Content-Type") == "image/png" and r.content == PNG and "sandbox" in r.headers.get("Content-Security-Policy", ""),
      "preview: a png inline with sandbox CSP")
check(pub(f"{FP}/v/{FA}").status_code == 404, "preview: text is never inline")
# a file named .png that is no picture: no preview (first bytes checked)
FAKE = up(A, "fake.png", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", parent=F, mime="image/png")
check(pub(f"{FP}/v/{FAKE}").status_code == 404, "preview: a fake png refused")
r = pub(f"{FP}/d/{FAKE}")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/octet-stream"), "a fake png only as a download")
log = dbx("SELECT action, user_id, detail FROM fs_log WHERE node_id=? AND action LIKE 'ext_%' ORDER BY id", (FA,))
check(("ext_download", None, "Kunde Nord") in [tuple(x) for x in log], "history: the download through the link (no person, the label) " + str(log))
check(dbx("SELECT COUNT(*) FROM fs_log WHERE node_id=? AND action='ext_view'", (F,))[0][0] >= 1, "history: the view of the folder")
j = A.get(B + f"/api/files/nodes/{F}/ext-links").json()
check(j["links"][0]["views"] >= 2 and j["links"][0]["last_seen_at"], "the link counts views + last opened")
check(j["enabled"] is True and j["blocked"] is None, "list: enabled, nothing blocks")
items = A.get(B + "/api/files", params={"space": f"org:{ORG}"}).json()["items"]
check(next(x for x in items if x["id"] == F).get("xl") is True and not next(x for x in items if x["id"] == OUT).get("xl"), "badge: the folder's row")
bitems = Bo.get(B + "/api/files", params={"space": "shared"}).json().get("items", [])
check(not any(x.get("xl") for x in bitems), "badge: only for who may share")
check(Bo.post(B + f"/api/files/ext-links/{L1['id']}/regenerate").status_code == 403, "renew: view share 403")
check(Da.delete(B + f"/api/files/ext-links/{L1['id']}").status_code == 404, "revoke: another workspace 404")
check(Da.post(B + f"/api/files/ext-links/{L1['id']}/restore").status_code == 404, "restore: another workspace 404")

# ---- expiry choices, several links per node
r = mk(A, FA, expires="none")
check(r.ok and next(x for x in r.json()["links"] if x["id"] == r.json()["id"])["expires_at"] is None, "no end date")
r = mk(A, FA, expires="1d", label="Kunde Sued")
check(r.ok and len(r.json()["links"]) == 2, "a second link of the same file")
r = mk(A, FA, expires=str(date.today() + timedelta(days=3)), tz="Europe/Berlin")
check(r.ok and len(r.json()["links"]) == 3, "a link until a date")
FL = path_of(r.json()["links"][-1]["url"])
r = pub(FL)
check(r.status_code == 200 and "angebot.txt" in r.text and f"/d/{FA}" in r.text and "Available until" in r.text, "file page: name, download, until")
check(pub(f"{FL}/d/{PIC}").status_code == 404 and pub(f"{FL}?p={SUB}").status_code == 200 and "motiv.png" not in pub(f"{FL}?p={SUB}").text,
      "a file link serves only that file")

# ---- expired, revoked (undo), renewed
newip()
dbx("UPDATE fs_ext_links SET expires_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds"), L1["id"]), write=True)
r = pub(FP)
check(r.status_code == 404 and r.text == gone, "expired: the same 404 as an unknown link")
check(pub(f"{FP}/d/{FA}").status_code == 404, "expired: no download")
check(A.get(B + f"/api/files/nodes/{F}/ext-links").json()["links"][0]["expired"] is True, "owner sees 'expired'")
dbx("UPDATE fs_ext_links SET expires_at=NULL WHERE id=?", (L1["id"],), write=True)
check(pub(FP).status_code == 200, "expiry removed: open again")
r = A.delete(B + f"/api/files/ext-links/{L1['id']}")
check(r.ok and not r.json()["links"] and pub(FP).status_code == 404 and pub(f"{FP}/d/{FA}").status_code == 404, "revoked: dead at once")
check(dbx("SELECT revoked_at FROM fs_ext_links WHERE id=?", (L1["id"],))[0][0], "revoked: kept for undo")
r = A.post(B + f"/api/files/ext-links/{L1['id']}/restore")
check(r.ok and pub(FP).status_code == 200, "undo of the revoke: the same address works again")
r = A.post(B + f"/api/files/ext-links/{L1['id']}/regenerate")
NP = path_of(r.json()["links"][0]["url"])
check(r.ok and NP != FP and pub(FP).status_code == 404 and pub(NP).status_code == 200, "renew: old address 404, new one works")
FP = NP

# ---- the trash
newip()
check(A.delete(B + f"/api/files/nodes/{SUB}").ok, "subfolder to the trash")
check(pub(f"{FP}?p={SUB}").status_code == 404 and pub(f"{FP}/d/{PIC}").status_code == 404 and pub(f"{FP}/v/{PIC}").status_code == 404,
      "trash: nothing of the subfolder")
check("Bilder" not in pub(FP).text, "trash: not listed")
check(mk(A, SUB).status_code == 404, "no link for a node in the trash")
A.post(B + f"/api/files/nodes/{SUB}/restore")
check(pub(f"{FP}/d/{PIC}").status_code == 200, "restored: back")
check(A.delete(B + f"/api/files/nodes/{F}").ok and pub(FP).status_code == 404 and pub(FL).status_code == 404, "shared folder in the trash: every link dead")
A.post(B + f"/api/files/nodes/{F}/restore")
check(pub(FP).status_code == 200, "restored: the link works again")

# ---- the creator loses the right to share
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": ids["carol"], "role": "admin"}).ok
r = mk(Ca, OUT, label="von Carol")
check(r.ok, "an admin of the organisation may make a link " + r.text[:200])
CP = path_of(r.json()["links"][0]["url"])
check(pub(CP).status_code == 200 and "intern.txt" in pub(CP).text, "carol's link works")
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": ids["carol"], "role": "member"}).ok
check(pub(CP).status_code == 404, "creator no longer admin: the link is dead")
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": ids["carol"], "role": "admin"}).ok
check(pub(CP).status_code == 200, "admin again: works again")
A.patch(B + f"/api/users/{ids['carol']}", json={"disabled": True})
check(pub(CP).status_code == 404, "creator disabled: dead")
A.patch(B + f"/api/users/{ids['carol']}", json={"disabled": False})
check(A.get(B + f"/api/files/nodes/{OUT}/ext-links").json()["links"][0]["by"] == "Carol", "other owners see who made a link")

# ---- the organisation's switch, the server's switch
newip()
orgs = A.get(B + "/api/orgs").json()["orgs"]
check(next(o for o in orgs if o["id"] == ORG)["ext_links"] is True, "organisation: switch on by default")
check(Bo.patch(B + f"/api/orgs/{ORG}", json={"ext_links": False}).status_code == 403, "organisation switch: admins only")
check(A.patch(B + f"/api/orgs/{ORG}", json={"ext_links": "no"}).status_code == 400, "organisation switch: a boolean")
check(A.patch(B + f"/api/orgs/{ORG}", json={"ext_links": False}).ok, "organisation switch off")
r = pub(FP)
check(r.status_code == 404 and r.text == gone and pub(f"{FP}/d/{FA}").status_code == 404, "organisation switch off: dead (same 404)")
r = mk(A, F)
check(r.status_code == 409, "organisation switch off: no new link")
check(A.get(B + f"/api/files/nodes/{F}/ext-links").json()["blocked"], "organisation switch off: the dialog says why")
check(dbx("SELECT COUNT(*) FROM fs_ext_links WHERE node_id=? AND revoked_at IS NULL", (F,))[0][0] == 1, "organisation switch off: nothing deleted")
A.patch(B + f"/api/orgs/{ORG}", json={"ext_links": True})
check(pub(FP).status_code == 200, "organisation switch on again: works")
A.patch(B + "/api/admin/settings", json={"public_links": False})
check(pub(FP).status_code == 404 and mk(A, F).status_code == 409, "server switch off: dead, no new link")
A.patch(B + "/api/admin/settings", json={"public_links": True})
check(pub(FP).status_code == 200, "server switch on again: works")

# ---- an agent's folder, a link node
AF = folder(A, "Filebot Ergebnisse", space=f"org:{ORG}")
dbx("UPDATE fs_nodes SET agent_id=? WHERE id=?", (AG, AF), write=True)
r = mk(A, AF)
check(r.status_code == 409, "an agent's folder: no link")
r = requests.get(B + f"/api/v1/files/{F}", headers=AGH)
check(r.status_code == 404 and "/s/f/" not in r.text, "v1: an agent sees neither the folder nor its links")
check(requests.post(B + f"/api/files/ext-links/{L1['id']}/regenerate", headers=AGH).status_code in (401, 403, 404), "agent token: no renew")

# ---- password
newip()
r = mk(A, PIC, password="sesame123", label="mit Passwort")
PP = path_of(next(x for x in r.json()["links"] if x["id"] == r.json()["id"])["url"])
check(r.ok and next(x for x in r.json()["links"] if x["id"] == r.json()["id"])["has_password"] is True, "password link made")
check(dbx("SELECT pw_hash FROM fs_ext_links WHERE id=?", (r.json()["id"],))[0][0] not in ("", None, "sesame123"), "password stored hashed")
r = pub(PP)
check(r.status_code == 200 and 'type="password"' in r.text and "motiv.png" not in r.text, "password page, nothing of the file")
check(pub(f"{PP}/d/{PIC}").status_code == 404 and pub(f"{PP}/v/{PIC}").status_code == 404, "no download / preview without unlocking")
r = pub(PP + "/unlock", "POST", data={"password": "wrong"})
check(r.status_code == 401 and not r.cookies, "wrong password: 401, no cookie")
jar = requests.Session()
r = pub(PP + "/unlock", "POST", cookies=jar, data={"password": "sesame123"})
ck = r.headers.get("Set-Cookie", "")
check(r.status_code == 303 and "HttpOnly" in ck and "SameSite=Strict" in ck and f"Path={PP}" in ck, "unlock: cookie (HttpOnly, Strict, path) " + ck)
check(pub(PP, cookies=jar).status_code == 200 and "motiv.png" in pub(PP, cookies=jar).text, "unlocked: the page")
check(pub(f"{PP}/d/{PIC}", cookies=jar).content == PNG, "unlocked: the download")
check('type="password"' in pub(PP).text, "another browser stays locked")
forged = requests.Session()
forged.cookies.set(f"kalmido_fsxl{dbx('SELECT id FROM fs_ext_links WHERE pw_hash IS NOT NULL')[0][0]}", "0" * 64, path=PP)
check('type="password"' in pub(PP, cookies=forged).text, "forged cookie refused")
newip()
codes = [pub(PP + "/unlock", "POST", data={"password": f"guess{i}"}).status_code for i in range(11)]
check(codes.index(429) == 10 and set(codes[10:]) == {429}, "password guessing: 10 per address, then 429 " + str(codes))
check(pub(PP + "/unlock", "POST", data={"password": "sesame123"}).status_code == 429, "blocked even with the right password")

# ================================================================ a person without an organisation (freelancer-matrix: files)
newip()
FID, Fr = freelancer(B, A)
FF = up(Fr, "portfolio.txt", b"Portfolio 2026\n")
FD = folder(Fr, "Projekte")
r = Fr.post(B + f"/api/files/nodes/{FF}/ext-links", json={"label": "Agentur"})
check(r.ok, "freelancer: a link of the own file " + r.text[:200])
FRP = path_of(r.json()["links"][0]["url"])
check(dbx("SELECT org_id FROM fs_ext_links WHERE node_id=?", (FF,))[0][0] is None, "freelancer: the link is private (org_id NULL)")
check(pub(FRP).status_code == 200 and pub(f"{FRP}/d/{FF}").content == b"Portfolio 2026\n", "freelancer: page + download")
check(Fr.get(B + f"/api/files/nodes/{FF}/ext-links").ok and Fr.post(B + f"/api/files/nodes/{FD}/ext-links", json={}).ok, "freelancer: list, folder link")
xid = r.json()["links"][0]["id"]
r = Fr.post(B + f"/api/files/ext-links/{xid}/regenerate")
check(r.ok and pub(FRP).status_code == 404, "freelancer: renew")
check(Fr.delete(B + f"/api/files/ext-links/{xid}").ok and Fr.post(B + f"/api/files/ext-links/{xid}/restore").ok, "freelancer: revoke + undo")
check(A.get(B + f"/api/files/nodes/{FF}/ext-links").status_code == 404 and A.delete(B + f"/api/files/ext-links/{xid}").status_code == 404,
      "the instance admin cannot manage a private person's links (404)")
check(Da.get(B + f"/api/files/nodes/{FF}/ext-links").status_code == 404, "another person: 404")
check(pub(f"{path_of(Fr.get(B + f'/api/files/nodes/{FF}/ext-links').json()['links'][0]['url'])}/d/{FA}").status_code == 404,
      "a private link never serves an organisation's file")

# ---- a move into another workspace ends the links
newip()
MV = up(A, "umzug.txt", b"zieht um\n")
r = mk(A, MV)
MP = path_of(r.json()["links"][0]["url"])
check(pub(MP).status_code == 200, "private link before the move")
r = A.post(B + "/api/files/move-space", json={"ids": [MV], "to": f"org:{ORG}"})
check(r.ok, "moved into the organisation " + r.text[:200])
check(pub(MP).status_code == 404 and not dbx("SELECT 1 FROM fs_ext_links WHERE node_id=?", (MV,)), "the move ended the link")

# ---- the folder ZIP (files/bulk.py of part A; joined after the merge)
r = pub(f"{FP}/zip")
if r.status_code == 404 and "Download all as ZIP" not in pub(FP).text:
    print("skip: folder ZIP (files/bulk.py not in this branch)")
else:
    check(r.status_code == 200 and r.content[:2] == b"PK" and "attachment" in r.headers.get("Content-Disposition", ""), "ZIP of the folder")
    check(pub(f"{FP}/zip?p={OUT}").status_code == 404, "ZIP: nothing outside the tree")

# ---- the boundary check, cascade, rollback
check(not dbx("SELECT x.id FROM fs_ext_links x JOIN fs_nodes n ON n.id=x.node_id WHERE x.org_id IS DISTINCT FROM n.org_id"),
      "every link in its node's workspace")
cols = {r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name='orgs'")}
check("ext_links" in cols, "rollback: orgs.ext_links is a new column with a default (older versions ignore it)")
n0 = dbx("SELECT COUNT(*) FROM fs_ext_links WHERE node_id=?", (FA,))[0][0]
check(n0 >= 3, "links of the file before purging")
dbx("DELETE FROM fs_nodes WHERE id=?", (FA,), write=True)
check(not dbx("SELECT 1 FROM fs_ext_links WHERE node_id=?", (FA,)), "a node removed for good: its links go with it")

# ---- unknown tokens are limited (last: it locks this address for every public link)
newip()
codes = [pub("/s/f/" + secrets.token_urlsafe(24)).status_code for _ in range(32)]
check(404 in codes and codes[-1] == 429, "unknown tokens: limited per address " + str(codes[-4:]))

print(f"p21121_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
