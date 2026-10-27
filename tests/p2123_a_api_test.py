#!/usr/bin/env python3
"""2.123.0 A API tests (#2105, #2102, #2106), own container (start.sh) with a server key (encryption at rest on). Invented
names and texts only.
 - #2105 the text of a page is sealed at rest ("kenc1:" in the database, never the plain text) in an organisation and in a
   private space; reading, template, rename with relink, mentions, export / import, the move private <-> organisation work;
   sealing is off until encrypt-wiki; a plain page from before (written straight into the database) is read and sealed by encrypt-wiki; the way back
   decrypt-wiki (wiki_encrypt=0) leaves every page text and version plain, new saves stay plain, encrypt-wiki seals again
 - #2102 the history: saves of one person within 10 minutes share a version, another person / later = a new one, at most
   100 per page, reading a version, restoring (a new version, 409 on a stale expect_updated_at), versions sealed and moved
   with the page; another organisation / person 404 (tenant-matrix: wiki), a person without an organisation keeps the
   history of its private pages (freelancer-matrix: wiki); a space with the lock keeps none
 - #2106 the search over the word index: more than 30 hits page by page (limit / offset / more), words in the name first,
   prefixes, a page written straight into the database is found (indexed on the search), ?space= only that space, nothing
   of another organisation or a space with the lock
usage: p2123_a_api_test.py <datadir>      (P2123A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import io
import os
import subprocess
import sys
import time
import zipfile

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall() if not write else c.execute(q, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


def cli(*args):
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args], capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def page(s, space, path, text=""):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def raw(pid):
    return sql("SELECT body FROM wiki_pages WHERE id=?", (pid,))[0][0]


def vers(s, pid):
    r = s.get(B + f"/api/wiki/pages/{pid}/versions")
    return r.json().get("versions", []) if r.ok else None


def save(s, pid, text, **kw):
    r = s.patch(B + f"/api/wiki/pages/{pid}", json={"body": text, **kw})
    assert r.ok, r.text
    return r.json()


def search(s, q, **kw):
    r = s.get(B + "/api/wiki/search", params={"q": q, **kw})
    assert r.ok, r.text
    return r.json()


if os.environ.get("P2123A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,wiki"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"
FID, Fr = freelancer(B, A)
_, Fo = freelancer(B, A, "fiona")

# ================================================================ #2105 sealed at rest
# 2.123.0 (#2105): sealing is off until an admin runs encrypt-wiki (2.122 must read the pages after an update and a rollback)
P0 = page(Bo, SP, "Ablauf/Vorher", "Vor dem Einschalten geschrieben")
check(raw(P0) == "Vor dem Einschalten geschrieben", "#2105: by default (wiki_encrypt unset) a new page text stays plain")
rc, out = cli("encrypt-wiki")
check(rc == 0 and raw(P0).startswith("kenc1:"), "#2105: encrypt-wiki switches sealing on and seals the plain page " + out[-300:])
TEXT = "# Ablauf\nDer Zitronenbaum wird im Herbst geschnitten. Siehe [[Ablauf/Werkzeug]]."
P1 = page(Bo, SP, "Ablauf/Garten", TEXT)
check(raw(P1).startswith("kenc1:") and "Zitronenbaum" not in raw(P1), "#2105: the text of an organisation page is sealed in the database")
check(A.get(B + f"/api/wiki/pages/{P1}").json().get("body") == TEXT, "#2105: a member reads the plain text")
check(Ca.get(B + f"/api/wiki/pages/{P1}").status_code == 404, "#2105: another organisation 404")
check(sql("SELECT path FROM wiki_pages WHERE id=?", (P1,))[0][0] == "Ablauf/Garten", "#2105: the name stays plain (unique name, links)")
# freelancer-matrix: wiki -- a person without an organisation: its private page sealed with its account key
FP = page(Fr, "private", "Notizen/Kunde", "Private Notiz zum Kunden Kumquat")
check(raw(FP).startswith("kenc1:") and "Kumquat" not in raw(FP), "#2105: a private page of a freelancer is sealed")
check(Fr.get(B + f"/api/wiki/pages/{FP}").json().get("body") == "Private Notiz zum Kunden Kumquat", "#2105: the freelancer reads it")
check(Fo.get(B + f"/api/wiki/pages/{FP}").status_code == 404 and A.get(B + f"/api/wiki/pages/{FP}").status_code == 404,
      "#2105: nobody else reads a private page")
# a template, a rename with relink, a mention
TP = page(Bo, SP, "Templates/Protokoll", "## Protokoll\n- Teilnehmer\n")
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Protokolle/Montag", "template_id": TP})
check(r.status_code == 201 and r.json().get("body") == "## Protokoll\n- Teilnehmer\n", "#2105: a page from a template gets the plain text " + r.text[:200])
TOOL = page(Bo, SP, "Ablauf/Werkzeug", "Schere")
r = Bo.patch(B + f"/api/wiki/pages/{TOOL}", json={"path": "Ablauf/Geraete"})
g = Bo.get(B + f"/api/wiki/pages/{P1}").json()
check(r.ok and r.json().get("relinked") == 1 and "[[Ablauf/Geraete]]" in g["body"] and raw(P1).startswith("kenc1:"),
      "#2105: a rename changes the [[link]] in the sealed text " + r.text[:200])
TASK = Bo.post(B + "/api/tasks", json={"title": "Baum schneiden"}).json()["id"]
MP = page(Bo, "private", "Erinnerung", f"Denk an #{TASK}")
men = Bo.get(B + "/api/wiki/mentions", params={"task": TASK}).json().get("pages", [])
check([p["id"] for p in men] == [MP], "#2105: mentions still find the page " + str(men))
# export / import
r = Bo.get(B + "/api/wiki/export", params={"space": SP})
z = zipfile.ZipFile(io.BytesIO(r.content)) if r.ok else None
check(z is not None and "Zitronenbaum" in z.read("Ablauf/Garten.md").decode(), "#2105: the export holds the plain text")
b = io.BytesIO()
with zipfile.ZipFile(b, "w") as zz:
    zz.writestr("Import/Eins.md", "Importierter Text mit Holunder")
r = Fr.post(B + "/api/wiki/import", params={"space": "private"}, files={"file": ("x.zip", b.getvalue(), "application/zip")})
IP = (r.json().get("created") or [None])[0] if r.ok else None
check(IP and raw(IP).startswith("kenc1:") and Fr.get(B + f"/api/wiki/pages/{IP}").json()["body"] == "Importierter Text mit Holunder",
      "#2105: an imported page is sealed and reads plain " + r.text[:200])
r = Fr.post(B + "/api/wiki/import", params={"space": "private", "replace": "1"}, files={"file": ("x.zip", b.getvalue(), "application/zip")})
check(r.ok and raw(IP).startswith("kenc1:"), "#2105: an import that replaces a page seals it too")
# move private <-> organisation: the key of the target
MV = page(Bo, "private", "Umzug/Seite", "Text der umziehenden Seite mit Quitte")
save(Bo, MV, "Text der umziehenden Seite mit Quitte, zweite Fassung")
r = Bo.post(B + "/api/wiki/move-space", json={"pages": [MV], "space": "private", "to": SP, "dest": ""})
check(r.ok and A.get(B + f"/api/wiki/pages/{MV}").json().get("body") == "Text der umziehenden Seite mit Quitte, zweite Fassung"
      and raw(MV).startswith("kenc1:"), "#2105: private -> organisation: sealed for the organisation, a member reads it " + r.text[:200])
vv = vers(A, MV)
# 2.360.0 (#2496): into an organisation the earlier (private) versions do not go along -- its members would read them
check(vv == [] and not sql("SELECT 1 FROM wiki_versions WHERE page_id=?", (MV,)), "#2496: no private versions in the organisation " + str(vv)[:200])
save(A, MV, "Text der umziehenden Seite mit Quitte, dritte Fassung")  # a version made in the organisation
# 2.361.2 (#2923): a member takes a page out of the organisation only after an admin released the request
rq = Bo.post(B + f"/api/orgs/{ORG}/out-requests", json={"kind": "wiki", "id": MV}).json().get("id")
check(A.post(B + f"/api/orgs/{ORG}/out-requests/{rq}", json={"decision": "approve"}).ok, "#2923: alice releases bob's request")
r = Bo.post(B + "/api/wiki/move-space", json={"pages": [MV], "space": SP, "to": "private", "dest": ""})
check(r.ok and Bo.get(B + f"/api/wiki/pages/{MV}").json().get("body", "").endswith("dritte Fassung")
      and A.get(B + f"/api/wiki/pages/{MV}").status_code == 404, "#2105: and back into the private space " + r.text[:200])
vv = vers(Bo, MV) or []
check(len(vv) >= 1 and all(Bo.get(B + f"/api/wiki/pages/{MV}/versions/{v['id']}").ok for v in vv), "#2102: versions readable after the way back")
check(all(x[0].startswith("kenc1:") for x in sql("SELECT body FROM wiki_versions WHERE page_id=? AND body<>''", (MV,))),
      "#2102: the versions are sealed in the database")

# a plain page from before 2.123 (written straight into the database): read, found, sealed by the pass
sql("INSERT INTO wiki_pages(org_id, owner_id, path, body, attrs, created_by, updated_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
    (ORG, None, "Alt/Vorher", "Ein alter Text mit Mispel", "{}", ALICE, ALICE, "2026-01-02T10:00:00.000+00:00", "2026-01-02T10:00:00.000+00:00"), write=True)
OLD = sql("SELECT id FROM wiki_pages WHERE path='Alt/Vorher'")[0][0]
check(A.get(B + f"/api/wiki/pages/{OLD}").json().get("body") == "Ein alter Text mit Mispel", "#2105: a plain page from before reads as before")
check([p["id"] for p in search(A, "mispel")["pages"]] == [OLD], "#2106: a page from before is indexed on the search")
rc, out = cli("encrypt-wiki")
check(rc == 0 and raw(OLD).startswith("kenc1:"), "#2105: encrypt-wiki seals the plain page " + out[-300:])
check(A.get(B + f"/api/wiki/pages/{OLD}").json().get("body") == "Ein alter Text mit Mispel", "#2105: and it reads the same")

# ================================================================ #2102 the history
H1 = page(Bo, SP, "Verlauf/Seite", "eins")
save(Bo, H1, "eins zwei")
save(Bo, H1, "eins zwei drei")
v = vers(Bo, H1)
check(v is not None and len(v) == 1 and v[0]["current"] and v[0]["by_name"] == "Bob Member", "#2102: saves of one person within 10 minutes = one version " + str(v))
save(A, H1, "eins zwei drei vier")
v = vers(Bo, H1)
check(len(v) == 2 and v[0]["by_name"] == "Alice Admin" and v[0]["current"] and not v[1]["current"], "#2102: another person = a new version " + str(v))
sql("UPDATE wiki_versions SET created_at='2026-01-01T08:00:00.000+00:00' WHERE id=?", (v[0]["id"],), write=True)
save(A, H1, "eins zwei drei vier fuenf")
v = vers(Bo, H1)
check(len(v) == 3, "#2102: the same person after more than 10 minutes = a new version " + str(len(v)))
d = Bo.get(B + f"/api/wiki/pages/{H1}/versions/{v[-1]['id']}").json()
check(d.get("body") == "eins zwei drei" and d.get("path") == "Verlauf/Seite", "#2102: a version with its text " + str(d)[:200])
check(sql("SELECT body FROM wiki_versions WHERE id=?", (v[-1]["id"],))[0][0].startswith("kenc1:"), "#2102: a version is sealed at rest")
# restore: a stale expect_updated_at = 409, then restore = a new version; the Undo of the app = the text before again
r = Bo.post(B + f"/api/wiki/pages/{H1}/versions/{v[-1]['id']}/restore", json={"expect_updated_at": "2000-01-01T00:00:00.000+00:00"})
check(r.status_code == 409 and r.json().get("page"), "#2102: restore after someone else saved: 409 with the page " + r.text[:200])
cur = Bo.get(B + f"/api/wiki/pages/{H1}").json()
r = Bo.post(B + f"/api/wiki/pages/{H1}/versions/{v[-1]['id']}/restore", json={"expect_updated_at": cur["updated_at"]})
check(r.ok and r.json().get("body") == "eins zwei drei" and r.json().get("restored") == v[-1]["id"], "#2102: restore " + r.text[:200])
v2 = vers(Bo, H1)
check(len(v2) == 4 and v2[0]["current"] and v2[0]["by_name"] == "Bob Member", "#2102: the restore is a new version on top " + str(len(v2)))
check(Bo.patch(B + f"/api/wiki/pages/{H1}", json={"body": cur["body"]}).ok and Bo.get(B + f"/api/wiki/pages/{H1}").json()["body"] == cur["body"],
      "#2102: the Undo of the app (the text before) works")
# rights: another organisation / a person who cannot see the page
check(Ca.get(B + f"/api/wiki/pages/{H1}/versions").status_code == 404 and Ca.get(B + f"/api/wiki/pages/{H1}/versions/{v[0]['id']}").status_code == 404
      and Ca.post(B + f"/api/wiki/pages/{H1}/versions/{v[0]['id']}/restore", json={}).status_code == 404,
      "#2102: another organisation 404 (list, read, restore)")
check(Bo.get(B + f"/api/wiki/pages/{P1}/versions/{v[0]['id']}").status_code == 404, "#2102: a version of another page 404")
# the limit: at most 100 per page (the oldest go)
for i in range(120):
    sql("INSERT INTO wiki_versions(page_id, org_id, owner_id, path, body, size, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (H1, ORG, None, "Verlauf/Seite", f"alt {i}", 5, ALICE, f"2025-01-01T00:{i // 60:02d}:{i % 60:02d}.000+00:00", "2025-01-01T00:00:00.000+00:00"), write=True)
save(A, H1, "nach dem Limit")
n = sql("SELECT COUNT(*) FROM wiki_versions WHERE page_id=?", (H1,))[0][0]
check(n == 100, f"#2102: at most 100 versions per page ({n})")
# freelancer-matrix: wiki -- the history of a private page of a person without an organisation
save(Fr, FP, "Private Notiz zum Kunden Kumquat, geaendert")
fv = vers(Fr, FP)
check(fv and len(fv) >= 1 and Fr.get(B + f"/api/wiki/pages/{FP}/versions/{fv[-1]['id']}").ok, "#2102: the freelancer reads its history " + str(fv)[:200])
r = Fr.post(B + f"/api/wiki/pages/{FP}/versions/{fv[-1]['id']}/restore", json={})
check(r.ok, "#2102: the freelancer restores a version " + r.text[:200])
check(Fo.get(B + f"/api/wiki/pages/{FP}/versions").status_code == 404 and Fo.post(B + f"/api/wiki/pages/{FP}/versions/{fv[-1]['id']}/restore", json={}).status_code == 404,
      "#2102: another person 404 on a private history")
# trash: the page goes to the trash and comes back with its history
check(Bo.delete(B + f"/api/wiki/pages/{H1}").ok and Bo.get(B + f"/api/wiki/pages/{H1}/versions").status_code == 404, "#2102: a page in the trash has no reachable history")
check(Bo.post(B + "/api/wiki/restore", json={"ids": [H1]}).ok and len(vers(Bo, H1) or []) == 100, "#2102: back from the trash with its history")

# ================================================================ #2106 the search
for i in range(35):
    page(A, SP, f"Obst/Seite {i:02d}", f"Hier steht etwas ueber die Sternfrucht Nummer {i}")
TITLE = page(A, SP, "Obst/Sternfrucht Sorten", "Liste der Sorten")
r = search(A, "sternfrucht")
check(r["total"] == 36 and len(r["pages"]) == 30 and r["more"] and r["pages"][0]["id"] == TITLE and "body" not in r["pages"][0],
      f"#2106: 36 hits, 30 on the first page, the name hit first ({r['total']}, {len(r['pages'])}, {r['more']})")
r2 = search(A, "sternfrucht", offset=30)
check(len(r2["pages"]) == 6 and not r2["more"] and not {p["id"] for p in r2["pages"]} & {p["id"] for p in r["pages"]}, "#2106: offset 30 = the other 6")
check(search(A, "sternfr")["total"] == 36 and search(A, "sternfx")["total"] == 0, "#2106: a prefix finds the word, another one nothing")
check(search(A, "sternfrucht nummer 17")["total"] == 1, "#2106: every word must match (nummer 17)")
r = search(A, "sternfrucht", limit=5)
check(len(r["pages"]) == 5 and r["more"], "#2106: limit")
check(search(Bo, "sternfrucht", space="private")["total"] == 0 and search(Bo, "sternfrucht", space=SP)["total"] == 36, "#2106: ?space= only that space")
check(search(Ca, "sternfrucht")["total"] == 0 and search(Fr, "sternfrucht")["total"] == 0, "#2106: nothing of another organisation / for a freelancer")
check([p["id"] for p in search(Fr, "kumquat")["pages"]] == [FP] and search(Fo, "kumquat")["total"] == 0, "#2106: the freelancer finds its private page, nobody else")
# a text changed straight in the database (an older version): indexed again on the next search
sql("UPDATE wiki_pages SET body=?, updated_at='2026-03-03T03:03:03.000+00:00' WHERE id=?", ("Jetzt mit Pitahaya", TITLE), write=True)
check([p["id"] for p in search(A, "pitahaya")["pages"]] == [TITLE], "#2106: a page changed elsewhere is indexed again")
# a space with the lock: the server neither searches nor keeps a history
LK = page(Ca, SP2, "Geheim/Seite", "Geheimer Text mit Physalis")
save(Ca, LK, "Geheimer Text mit Physalis, zwei")
check(search(Ca, "physalis")["total"] == 1, "#2106: found while the space is open")
sql("INSERT INTO wiki_spaces(org_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (ORG2,), write=True)
check(search(Ca, "physalis")["total"] == 0, "#2106: a space with the lock is searched in the browser only")
r = Ca.get(B + f"/api/wiki/pages/{LK}/versions")
check(r.ok and r.json() == {"versions": [], "e2e": True}, "#2102: a space with the lock shows no history " + r.text[:200])

# ================================================================ #2105 the way back (before running 2.122) and again
rc, out = cli("decrypt-wiki")
check(rc == 0, "#2105: decrypt-wiki " + out[-300:])
sealed = sql("SELECT COUNT(*) FROM wiki_pages WHERE left(body, 6)='kenc1:'")[0][0] + sql("SELECT COUNT(*) FROM wiki_versions WHERE left(body, 6)='kenc1:'")[0][0]
check(sealed == 0 and raw(P1) == Bo.get(B + f"/api/wiki/pages/{P1}").json()["body"] and "Zitronenbaum" in raw(P1),
      f"#2105: after decrypt-wiki every page text and version is plain ({sealed} sealed)")
check(raw(FP) == Fr.get(B + f"/api/wiki/pages/{FP}").json()["body"], "#2105: the private pages too")
save(Bo, P1, TEXT + "\nNach dem Rueckweg.")
check(not raw(P1).startswith("kenc1:"), "#2105: with wiki_encrypt=0 a new save stays plain (2.122 reads it)")
check(search(Bo, "rueckweg")["total"] == 1, "#2106: the search works on plain texts")
rc, out = cli("encrypt-wiki")
check(rc == 0 and raw(P1).startswith("kenc1:") and raw(FP).startswith("kenc1:"), "#2105: encrypt-wiki seals again " + out[-300:])
check(Bo.get(B + f"/api/wiki/pages/{P1}").json()["body"].endswith("Nach dem Rueckweg."), "#2105: and it reads the same")
rc, out = cli("status")
check(rc == 0 and '"wiki_encrypt": true' in out, "#2105: status names the switch and the counts " + out[-200:])

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
