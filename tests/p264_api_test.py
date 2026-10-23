#!/usr/bin/env python3
"""2.64.0 API tests: #1864 the files of private spaces encrypted at rest with an account key per person.
 - without KALMIDO_SECRET_KEY: private files plain, no account keys (user_keys empty)
 - restart with a server key: the start-up pass seals every plain file of a private space (attachments, project files,
   the file store, chat files with agents) with its owner's account key (header = -owner id); the log line
   "encrypted at rest:" holds counts only (no key, no content)
 - new uploads of a person without an organisation (task and comment attachments, project files, the file store,
   chats with agents, the drop upload): sealed with -uid on disk, downloads byte for byte, sizes = the plain sizes,
   one key row per person, the storage check finds no problem, the text API reads the sealed file
 - a shared private list: the owner's key, every member reads, a stranger and an agent without a share get 404
 - moves: task into an organisation's list and back, list into an organisation and back, a new list owner -> the
   files are resealed for their new space and stay readable
 - deleting an account: a file sealed with its key that lies in a list handed over is resealed for the new owner,
   the key row is gone, the files of its basket are gone
 - orgcrypt_cli: decrypt-private / encrypt-private / status / decrypt-all / encrypt-all
 - uploaded bytes that look sealed come back unchanged
 - a wrong server key: 500 code orgcrypt without content; rewrap-accounts with the earlier key from stdin
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY. Invented data only.
usage: p264_api_test.py <datadir>"""
import base64
import json
import os
import re
import struct
import subprocess
import sys
import time

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
KEY2 = base64.b64encode(os.urandom(32)).decode()
MAGIC = b"KENC1\n"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def start(key=KEY, keep=False, delay="0"):
    extra = ["-e KALMIDO_INSTANCE_MODE=workspaces", "-e KALMIDO_ORGCRYPT_DELAY=" + delay, "-e KALMIDO_ORGCRYPT_PAUSE=0"] + \
        (["-e KALMIDO_SECRET_KEY=" + key] if key else [])
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra), **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def cli(*args, stdin=None):
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args], input=stdin,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout, r.stderr


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr


def full(rel):
    return os.path.join(DATA, "attachments", rel)


def raw(path):
    with open(path, "rb") as f:
        return f.read()


def space(path):
    """The space id in a sealed file's header (> 0 organisation, < 0 the account -id), None when plain."""
    with open(path, "rb") as f:
        h = f.read(14)
    return struct.unpack(">q", h[6:14])[0] if h[:6] == MAGIC and len(h) == 14 else None


def wait_space(path, sid, secs=30):
    for _ in range(secs * 4):
        if space(path) == sid:
            return True
        time.sleep(0.25)
    return False


# every stored file with the space it lies in now (as admin/orgcrypt_cli.py SPACE_SQL)
SPACE_SQL = ("SELECT 'attachment' AS k, a.id, a.path, a.size, l.org_id, l.owner_id FROM attachments a JOIN tasks t ON t.id=a.task_id "
             "JOIN lists l ON l.id=t.list_id WHERE a.path<>'' "
             "UNION ALL SELECT 'list_file', f.id, f.path, f.size, l.org_id, l.owner_id FROM list_files f JOIN lists l ON l.id=f.list_id WHERE f.path<>'' "
             "UNION ALL SELECT 'fs_version', v.id, v.path, v.size, n.org_id, n.owner_id FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id WHERE v.path<>'' "
             "UNION ALL SELECT 'chat_file', f.id, f.path, f.size, NULL, m.user_id FROM chat_files f JOIN agent_chat m ON m.id=f.message_id WHERE f.path<>''")


def sweep():
    """[(kind, id, full path, expected space, header space or 'missing')] over every stored file."""
    out = []
    for r in dbx(SPACE_SQL):
        p = full(r["path"])
        sid = int(r["org_id"]) if r["org_id"] else -int(r["owner_id"])
        out.append((r["k"], r["id"], p, sid, space(p) if os.path.isfile(p) else "missing"))
    return out


def private_left_plain():
    return [x for x in sweep() if x[3] < 0 and x[4] != x[3]]


def wait_private_sealed(secs=60):
    for _ in range(secs * 2):
        if not private_left_plain():
            return True
        time.sleep(0.5)
    return False


def mark(name):
    """Invented file content with a unique marker (to look for it in logs)."""
    return f"{name} MARK-{os.urandom(6).hex()}\n".encode() * 20


def plist(s, name, kind=None):
    j = {"name": name, "org_id": None}
    if kind:
        j["kind"] = kind
    r = s.post(B + "/api/lists", json=j)
    assert r.ok, r.text
    lid = r.json()["id"]
    if one("SELECT org_id FROM lists WHERE id=?", (lid,)) is not None:
        s.patch(B + f"/api/lists/{lid}", json={"org_id": None})
    return lid


def task(s, lid, title):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


def attach(s, tid, name, data):
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, data, "text/plain")})
    check(r.ok, f"upload {name} " + r.text[:150])
    return one("SELECT id FROM attachments WHERE task_id=? AND name=? ORDER BY id DESC LIMIT 1", (tid, name))


def att_path(aid):
    return full(one("SELECT path FROM attachments WHERE id=?", (aid,)))


def listfile(s, lid, name, data):
    r = s.post(B + f"/api/lists/{lid}/files", files={"file": (name, data, "text/plain")})
    check(r.ok, f"project file {name} " + r.text[:150])
    return one("SELECT id FROM list_files WHERE list_id=? AND name=? ORDER BY id DESC LIMIT 1", (lid, name))


def fsup(s, name, data):
    r = s.post(B + "/api/files/upload", data={"space": "private"}, files={"file": (name, data, "text/plain")})
    check(r.status_code == 201, f"file store upload {name} " + r.text[:150])
    return r.json()["items"][0]["id"] if r.status_code == 201 else None


def fs_last(nid):
    return dbx("SELECT path, size FROM fs_versions WHERE node_id=? ORDER BY no DESC LIMIT 1", (nid,))[0]


def chatfile(s, uid, name, data, ag=None):
    r = s.post(B + f"/api/agents/{ag or AG}/chat", data={"body": "file " + name}, files=[("file", (name, data, "text/plain"))])
    check(r.status_code == 201, f"chat file {name} " + r.text[:150])
    return one("SELECT f.id FROM chat_files f JOIN agent_chat m ON m.id=f.message_id WHERE m.user_id=? AND f.name=? ORDER BY f.id DESC LIMIT 1",
               (uid, name))


def chat_path(fid):
    return full(one("SELECT path FROM chat_files WHERE id=?", (fid,)))


def get(s, kind, i):
    url = {"attachment": f"/api/attachments/{i}", "list_file": f"/api/list-files/{i}", "fs": f"/api/files/nodes/{i}/content",
           "chat": f"/api/chat-files/{i}"}[kind]
    return s.get(B + url)


def same(s, kind, i, data):
    r = get(s, kind, i)
    return r.status_code == 200 and r.content == data


def status_json(out):
    try:
        return json.loads(out[out.index("{"):])
    except ValueError:
        return {}


# ================================================================ (i) without KALMIDO_SECRET_KEY, files for the migration
start(key=None)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Solo"), ("dave", "Dave Solo"), ("erin", "Erin Leaving")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
FEAT = "cal,comments,collab"
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "claude", "display_name": "Claude"})
AG, AGT = r.json()["id"], r.json()["token"]
AGH = {"Authorization": "Bearer " + AGT, "X-Requested-With": "kalmido"}
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "vera", "display_name": "Vera"})  # (b): in no other list
AG3, AGH3 = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}
AG2 = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "otto", "display_name": "Otto"}).json()["id"]  # dave's agent

CL = plist(Ca, "Carol privat")
assert Ca.put(B + f"/api/lists/{CL}/members", json={"user_id": AG, "role": "edit", "bridge_ok": True}).ok  # carol may chat with the agent
CT1 = task(Ca, CL, "Steuer")
C0 = {"att": mark("carol attachment"), "lf": mark("carol project file"), "fs": mark("carol file store"), "chat": mark("carol chat")}
CA0 = attach(Ca, CT1, "c0.txt", C0["att"])
CP = plist(Ca, "Carol Projekt", kind="project")
CLF0 = listfile(Ca, CP, "c0p.txt", C0["lf"])
CFS0 = fsup(Ca, "c0f.txt", C0["fs"])
CCH0 = chatfile(Ca, CAROL, "c0c.txt", C0["chat"])
check(all(x[4] is None for x in sweep()), f"without a server key: every stored file plain {[x[:2] + x[3:] for x in sweep() if x[4] is not None]}")
check(raw(att_path(CA0)) == C0["att"] and raw(chat_path(CCH0)) == C0["chat"], "without a server key: the bytes on disk are the uploaded ones")
check(one("SELECT COUNT(*) FROM user_keys") == 0, "without a server key: no account keys")
st0 = A.get(B + "/api/admin/storage-check").json()
check(not st0["problems"], f"without a server key: storage check clean {st0['problems']}")

# ================================================================ (d) restart with a server key: the start-up pass seals
start(key=KEY, keep=True)
A, Bo, Ca, Da, Er = sess("alice"), sess("bob"), sess("carol"), sess("dave"), sess("erin")  # a new server key: log in again
check(wait_private_sealed(), f"start-up pass: no plain file of a private space left {[x[:2] + x[3:] for x in private_left_plain()]}")
sw = sweep()
check(sw and all(x[4] == x[3] for x in sw if x[3] < 0), "start-up pass: every private file carries its owner's account key in the header")
check(space(att_path(CA0)) == -CAROL and space(chat_path(CCH0)) == -CAROL, "start-up pass: carol's attachment and chat file -> -carol")
check(same(Ca, "attachment", CA0, C0["att"]) and same(Ca, "list_file", CLF0, C0["lf"]) and same(Ca, "fs", CFS0, C0["fs"])
      and same(Ca, "chat", CCH0, C0["chat"]), "start-up pass: all four downloads are the originals")
lg = ""
for _ in range(40):
    lg = logs()
    if "encrypted at rest:" in lg:
        break
    time.sleep(0.25)
m = re.search(r"encrypted at rest: (\d+) fields, (\d+) files in (\d+) organisations and the private spaces, (\d+) files resealed", lg)
check(m and int(m.group(2)) >= 4, f"server log: the start-up line with counts {m.group(0) if m else lg[-400:]}")
check(KEY not in lg and not any(v.decode().split(" MARK-")[1][:12] in lg for v in C0.values()), "server log: neither the key nor file contents")
check(sorted(r[0] for r in dbx("SELECT user_id FROM user_keys")) == [CAROL], "user_keys: exactly carol's row (the one person with files)")

# ================================================================ (a) new uploads of a person without an organisation
D = {k: mark("dave " + k) for k in ("att", "com", "lf", "fs", "fs2", "chat", "drop")}
DL = plist(Da, "Dave privat")
r = Da.put(B + f"/api/lists/{DL}/members", json={"user_id": AG2, "role": "edit", "bridge_ok": True})
assert r.ok, r.text
DT = task(Da, DL, "Umzug")
DA = attach(Da, DT, "d.txt", D["att"])
r = Da.post(B + f"/api/tasks/{DT}/comments", data={"body": "file"}, files=[("file", ("dc.txt", D["com"], "text/plain"))])
check(r.ok, "comment with a file " + r.text[:150])
DCOM = one("SELECT id FROM attachments WHERE task_id=? AND comment_id IS NOT NULL ORDER BY id DESC LIMIT 1", (DT,))
DP = plist(Da, "Dave Projekt", kind="project")
DLF = listfile(Da, DP, "dp.txt", D["lf"])
DFS = fsup(Da, "df.txt", D["fs"])
DFS_V1 = fs_last(DFS)["path"]
check(fsup(Da, "df.txt", D["fs2"]) == DFS, "file store: the same name again = a new version")
DCH = chatfile(Da, DAVE, "dch.txt", D["chat"], AG2)
dt = Da.post(B + "/api/me/drop-token").json()["drop_token"]
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + dt}, data={"text": "from the phone"}, files=[("file", ("drop.txt", D["drop"], "text/plain"))])
check(r.status_code == 200, f"drop upload {r.status_code} {r.text[:100]}")
DDROP = one("SELECT a.id FROM attachments a JOIN tasks t ON t.id=a.task_id JOIN lists l ON l.id=t.list_id WHERE l.is_inbox=1 AND l.owner_id=? "
            "AND a.name='drop.txt' ORDER BY a.id DESC LIMIT 1", (DAVE,))
paths = {"att": att_path(DA), "com": att_path(DCOM), "lf": full(one("SELECT path FROM list_files WHERE id=?", (DLF,))),
         "fs": full(DFS_V1), "fs2": full(fs_last(DFS)["path"]), "chat": chat_path(DCH), "drop": att_path(DDROP) if DDROP else ""}
for k, p in paths.items():
    check(p and os.path.isfile(p) and space(p) == -DAVE and D[k][:20] not in raw(p), f"(a) {k}: sealed with dave's account key on disk ({space(p) if p else None})")
check(same(Da, "attachment", DA, D["att"]) and same(Da, "attachment", DCOM, D["com"]) and same(Da, "list_file", DLF, D["lf"])
      and same(Da, "fs", DFS, D["fs2"]) and same(Da, "chat", DCH, D["chat"]) and same(Da, "attachment", DDROP, D["drop"]),
      "(a) every download is byte for byte the upload")
r = Da.get(B + f"/api/files/nodes/{DFS}/content", params={"v": 1})
check(r.ok and r.content == D["fs"], "(a) file store: the first version byte for byte")
r = Da.get(B + f"/api/attachments/{DA}", headers={"Range": "bytes=0-9"})
check(r.status_code in (200, 206) and r.content == D["att"][:len(r.content)], "(a) range request answers plain bytes")
sizes = [one("SELECT size FROM attachments WHERE id=?", (DA,)) == len(D["att"]), one("SELECT size FROM attachments WHERE id=?", (DCOM,)) == len(D["com"]),
         one("SELECT size FROM list_files WHERE id=?", (DLF,)) == len(D["lf"]), fs_last(DFS)["size"] == len(D["fs2"]),
         one("SELECT size FROM chat_files WHERE id=?", (DCH,)) == len(D["chat"])]
check(all(sizes), f"(a) sizes in the database = the plain sizes {sizes}")
check(sorted(r[0] for r in dbx("SELECT user_id FROM user_keys")) == sorted([CAROL, DAVE]), "(a) user_keys: one row per person with files")
sc = A.get(B + "/api/admin/storage-check").json()
check(not sc["problems"] and sc["checked"] >= 8, f"(a) storage check without problems {sc['problems']}")
tk = Da.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "attachments:read"]}).json().get("token", "")
r = requests.get(B + f"/api/v1/attachments/{DA}/text", headers={"Authorization": "Bearer " + tk})
check(r.ok and "dave att MARK-" in r.json().get("text", ""), "(a) text API reads the sealed file " + r.text[:120])
check(Ca.get(B + f"/api/attachments/{DA}").status_code == 404 and Ca.get(B + f"/api/chat-files/{DCH}").status_code == 404
      and Ca.get(B + f"/api/list-files/{DLF}").status_code == 404, "(a) another person: 404 (rights unchanged)")

# ================================================================ (b) a shared private list
SL = plist(A, "Alice geteilt")
r = A.put(B + f"/api/lists/{SL}/members", json={"user_id": BOB, "role": "edit"})
assert r.ok, r.text
ST = task(A, SL, "Gemeinsam")
SB = mark("bob in alice's list")
SA = attach(Bo, ST, "b.txt", SB)
check(space(att_path(SA)) == -ALICE, f"(b) a member's upload is sealed with the list owner's key ({space(att_path(SA))})")
check(same(Bo, "attachment", SA, SB) and same(A, "attachment", SA, SB), "(b) member and owner read it byte for byte")
check(Da.get(B + f"/api/attachments/{SA}").status_code == 404, "(b) a stranger: 404")
r = requests.get(B + f"/api/v1/attachments/{SA}", headers=AGH3)
check(r.status_code == 404, f"(b) an agent without a share: 404 ({r.status_code})")
r = A.put(B + f"/api/lists/{SL}/members", json={"user_id": AG3, "role": "edit", "bridge_ok": True})
assert r.ok, r.text
r = requests.get(B + f"/api/v1/attachments/{SA}", headers=AGH3)
check(r.status_code == 200 and r.content == SB, f"(b) the agent with the list shared reads it ({r.status_code})")
check(one("SELECT COUNT(*) FROM user_keys WHERE user_id=?", (BOB,)) == 0, "(b) no account key made for the uploading member")

# ================================================================ (c) moves between spaces
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s, o in ((A, ORG), (Bo, ORG)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
OL = A.post(B + "/api/lists", json={"name": "Org-Liste", "org_id": ORG}).json()["id"]
check(one("SELECT org_id FROM lists WHERE id=?", (OL,)) == ORG, "(c) organisation list")
AP = plist(A, "Alice privat")
AT = task(A, AP, "Wandern")
AD = mark("alice moves")
AA = attach(A, AT, "a.txt", AD)
ap = att_path(AA)
check(space(ap) == -ALICE, "(c) alice's private file -> -alice")
r = A.patch(B + f"/api/tasks/{AT}", json={"list_id": OL})
check(r.ok and wait_space(ap, ORG) and same(A, "attachment", AA, AD), f"(c) task into the organisation's list: resealed with the org key ({space(ap)}) " + r.text[:100])
r = A.patch(B + f"/api/tasks/{AT}", json={"list_id": AP})
check(r.ok and wait_space(ap, -ALICE) and same(A, "attachment", AA, AD), f"(c) task back into the private list: -alice ({space(ap)})")
r = A.patch(B + f"/api/lists/{AP}", json={"org_id": ORG})
check(r.ok and wait_space(ap, ORG) and same(A, "attachment", AA, AD), f"(c) private list into the organisation: org key ({space(ap)}) " + r.text[:100])
r = A.patch(B + f"/api/lists/{AP}", json={"org_id": None})
check(r.ok and one("SELECT org_id FROM lists WHERE id=?", (AP,)) is None and wait_space(ap, -ALICE) and same(A, "attachment", AA, AD),
      f"(c) list back out of the organisation: -alice ({space(ap)}) " + r.text[:100])
r = A.post(B + f"/api/lists/{AP}/owner", json={"user_id": BOB})
check(r.ok and wait_space(ap, -BOB) and same(Bo, "attachment", AA, AD), f"(c) new list owner bob: -bob ({space(ap)}) " + r.text[:100])

# ================================================================ (f) deleting an account (the kick waits long: the deletion comes first)
start(key=KEY, keep=True, delay="120")
A, Bo, Er = sess("alice"), sess("bob"), sess("erin")
EL = plist(Er, "Erin Liste")
ET = task(Er, EL, "Übergabe")
ED = mark("erin handed over")
EA = attach(Er, ET, "e.txt", ED)
ep = att_path(EA)
edt = Er.post(B + "/api/me/drop-token").json()["drop_token"]
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + edt}, data={"text": "basket"}, files=[("file", ("eb.txt", mark("erin basket"), "text/plain"))])
EB = one("SELECT a.id FROM attachments a JOIN tasks t ON t.id=a.task_id JOIN lists l ON l.id=t.list_id WHERE l.is_inbox=1 AND l.owner_id=?", (ERIN,))
ebp = att_path(EB) if EB else ""
check(space(ep) == -ERIN and ebp and space(ebp) == -ERIN, "(f) erin's files sealed with her account key")
# 2.87.0 (#1984): a list goes only to a person one may see -- erin (outside the organisation) and bob are connected
dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?, ?, '2026-10-18T10:00:00.000Z') ON CONFLICT DO NOTHING", tuple(sorted((BOB, ERIN))))
r = Er.post(B + f"/api/lists/{EL}/owner", json={"user_id": BOB})
check(r.ok and space(ep) == -ERIN, f"(f) list handed to bob, the file still has erin's key (the kick waits) " + r.text[:100])
r = A.delete(B + f"/api/users/{ERIN}")
check(r.ok, "(f) erin's account deleted " + r.text[:150])
check(one("SELECT COUNT(*) FROM user_keys WHERE user_id=?", (ERIN,)) == 0, "(f) erin's key row is gone")
check(space(ep) == -BOB and same(Bo, "attachment", EA, ED), f"(f) the handed-over list's file resealed for bob and readable ({space(ep)})")
check(ebp and not os.path.exists(ebp), "(f) the files of her basket are gone")
start(key=KEY, keep=True)
A, Bo, Ca, Da = sess("alice"), sess("bob"), sess("carol"), sess("dave")

# ================================================================ (e) the way back: decrypt-private / encrypt-private / status / decrypt-all / encrypt-all
OT = task(A, OL, "Org")
OA = attach(A, OT, "o.txt", b"org file\n")
check(space(att_path(OA)) == ORG, "(e) an organisation's file is sealed with its key")
rc, out, err_ = cli("decrypt-private")
check(rc == 0 and "still encrypted in private spaces: 0" in out, f"(e) decrypt-private {out[-300:]} {err_[-300:]}")
sw = sweep()
check(all(x[4] is None for x in sw if x[3] < 0), f"(e) decrypt-private: every private file plain {[x[:2] + x[3:] for x in sw if x[3] < 0 and x[4] is not None]}")
check(any(x[3] == ORG for x in sw) and all(x[4] == ORG for x in sw if x[3] == ORG), "(e) decrypt-private: the organisation's files stay sealed")
check(one("SELECT value FROM settings WHERE key='private_encrypt'") == "0", "(e) private_encrypt = 0")
OA2 = attach(A, OT, "o2.txt", b"org while private off\n")
check(space(att_path(OA2)) == ORG, "(e) an organisation's new file is still sealed while private_encrypt = 0")
check(same(Da, "attachment", DA, D["att"]) and same(Da, "chat", DCH, D["chat"]) and same(Da, "fs", DFS, D["fs2"]), "(e) downloads unchanged")
NP = attach(Da, DT, "n.txt", b"new while off\n")
check(space(att_path(NP)) is None and raw(att_path(NP)) == b"new while off\n", "(e) a new private upload stays plain while private_encrypt = 0")
rc, out, err_ = cli("encrypt-private")
check(rc == 0 and one("SELECT value FROM settings WHERE key='private_encrypt'") == "1", f"(e) encrypt-private {out[-200:]} {err_[-200:]}")
check(not private_left_plain(), f"(e) encrypt-private: every private file sealed again {[x[:2] + x[3:] for x in private_left_plain()]}")
check(same(Da, "attachment", NP, b"new while off\n") and same(Ca, "fs", CFS0, C0["fs"]), "(e) readable after encrypt-private")
rc, out, err_ = cli("status")
stj = status_json(out)
pv = stj.get("private", {})
check(rc == 0 and stj.get("private_encrypt") is True and pv.get("keys", 0) >= 3 and pv.get("keys_other_server_key") == 0
      and pv.get("files", {}).get("plain") == 0 and pv.get("files", {}).get("enc", 0) >= 8, f"(e) status with the private spaces {pv} {err_[-200:]}")
check(KEY not in out and KEY not in err_ and "wrapped" not in out, "(e) status: no key in the output")
rc, out, err_ = cli("decrypt-all")
check(rc == 0 and "still encrypted: 0" in out, f"(e) decrypt-all {out[-300:]} {err_[-300:]}")
sw = sweep()
check(sw and all(x[4] is None for x in sw), f"(e) decrypt-all: every file plain, the file store and chat files too {[x[:2] + x[3:] for x in sw if x[4] is not None]}")
check(raw(full(fs_last(DFS)["path"])) == D["fs2"] and raw(chat_path(DCH)) == D["chat"], "(e) decrypt-all: file store and chat file plain on disk")
check(same(Da, "attachment", DA, D["att"]) and same(A, "attachment", OA, b"org file\n"), "(e) decrypt-all: downloads unchanged")
rc, out, err_ = cli("encrypt-all")
sw = sweep()
check(rc == 0 and all(x[4] == x[3] for x in sw), f"(e) encrypt-all: every file sealed for its space again {[x[:2] + x[3:] for x in sw if x[4] != x[3]]} {out[-200:]}")
check(same(Da, "list_file", DLF, D["lf"]) and same(Ca, "chat", CCH0, C0["chat"]) and same(A, "attachment", OA, b"org file\n"),
      "(e) encrypt-all: downloads unchanged")

# ================================================================ (g) uploaded bytes that look sealed come back unchanged
G = raw(ap)  # bob's file (the list handed over in (c)) as it lies on disk
check(G[:6] == MAGIC and space(ap) == -BOB, "(g) the source bytes look sealed (another person's space)")
GT = task(Ca, CL, "Fremd")
GA = attach(Ca, GT, "g.bin", G)
check(space(att_path(GA)) == -CAROL, f"(g) stored with carol's key ({space(att_path(GA))})")
r = get(Ca, "attachment", GA)
check(r.status_code == 200 and r.content == G and AD not in r.content, "(g) attachment: the download is exactly the uploaded bytes")
GF = fsup(Ca, "g.bin", G)
r = get(Ca, "fs", GF)
check(r.status_code == 200 and r.content == G, "(g) file store: the download is exactly the uploaded bytes")
GC = chatfile(Ca, CAROL, "g.bin", G)
r = get(Ca, "chat", GC)
check(r.status_code == 200 and r.content == G, "(g) chat file: the download is exactly the uploaded bytes")
GL = listfile(Ca, CP, "g.bin", G)
r = get(Ca, "list_file", GL)
check(r.status_code == 200 and r.content == G, "(g) project file: the download is exactly the uploaded bytes")
rc, out, err_ = cli("decrypt-private")
gp = [att_path(GA), full(fs_last(GF)["path"]), chat_path(GC), full(one("SELECT path FROM list_files WHERE id=?", (GL,)))]
check(rc == 0 and '"kept": 4' in out and all(space(p) == -CAROL for p in gp), f"(g) decrypt-private keeps such uploads sealed (kept, exit 0) {rc} {out[-300:]}")
check(same(Ca, "attachment", GA, G) and same(Ca, "fs", GF, G) and same(Ca, "chat", GC, G) and same(Ca, "list_file", GL, G)
      and same(Da, "attachment", DA, D["att"]), "(g) after decrypt-private: every download unchanged")
check(all(x[4] is None for x in sweep() if x[3] < 0 and x[2] not in gp), "(g) decrypt-private: the other private files plain")
rc, out, err_ = cli("encrypt-private")
check(rc == 0 and not private_left_plain() and same(Ca, "attachment", GA, G), f"(g) encrypt-private again {out[-200:]}")

# ================================================================ (h) a wrong server key, rewrap-accounts with the earlier one
start(key=KEY2, keep=True)
Ca, Da = sess("carol"), sess("dave")
r = get(Da, "attachment", DA)
check(r.status_code == 500 and (r.headers.get("Content-Type", "").startswith("application/json") and r.json().get("code") == "orgcrypt")
      and b"MARK-" not in r.content, f"(h) wrong server key: 500 code orgcrypt without content {r.status_code} {r.text[:200]}")
rc, out, err_ = cli("status")
stj = status_json(out)
check(stj.get("private", {}).get("keys_other_server_key", 0) >= 3, f"(h) status: account keys of another server key {stj.get('private')} {rc} {err_[-200:]}")
check(KEY not in out + err_ and KEY2 not in out + err_, "(h) status: no key in the output")
rc, out, err_ = cli("rewrap-accounts", "--old-key-file", "-", stdin="not a key\n")
check(rc == 2, f"(h) rewrap-accounts refuses something that is not a key {rc} {out[-200:]}")
row0 = sorted(tuple(r) for r in dbx("SELECT user_id, wrapped FROM user_keys"))
rc, out, err_ = cli("rewrap-accounts", "--old-key-file", "-", stdin=base64.b64encode(os.urandom(32)).decode() + "\n")
check(rc == 1 and sorted(tuple(r) for r in dbx("SELECT user_id, wrapped FROM user_keys")) == row0, f"(h) rewrap-accounts with a wrong earlier key: exit 1, nothing changed {rc} {out[-200:]}")
rc, out, err_ = cli("rewrap-accounts", "--old-key-file", "-", stdin=KEY + "\n")
check(rc == 0 and '"other": 0' in out and KEY not in out + err_ and KEY2 not in out + err_, f"(h) rewrap-accounts from stdin {out[-200:]} {err_[-200:]}")
check(same(Da, "attachment", DA, D["att"]) and same(Ca, "chat", CCH0, C0["chat"]) and same(Ca, "attachment", GA, G),
      "(h) after rewrap-accounts: private files readable with the new server key")
rc, out, err_ = cli("status")
check(status_json(out).get("private", {}).get("keys_other_server_key") == 0, "(h) status: no account key of another server key left")
check(KEY not in logs(), "(h) server log: never the key")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
if FAILS:
    print("FAILED:", *FAILS, sep="\n  ")
    sys.exit(1)
