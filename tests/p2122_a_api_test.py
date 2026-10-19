#!/usr/bin/env python3
"""2.122.0 API tests, part A (#2097): file requests -- a client uploads files into a folder of the file store through a
public link /u/<token>. Own container (start.sh), invented companies and people only (@example.com).
 - managing: GET / POST /api/files/nodes/<id>/requests (write right on the folder), PATCH / DELETE /api/files/requests/<id>,
   POST .../restore; the end date is required (at most 90 days), limits and kinds are checked; the token is stored sealed
   and hashed; a person with the write right sees the requests but manages only the own; another organisation 404
   (tenant-matrix: file_request)
 - the page: title + note, never the folder's name or files; unknown, revoked, expired, removed, folder in the trash,
   creator without the write right, folder in another workspace: the same answer; switched-off public links too
 - uploading: into the folder as a file of the creator (history "frq_upload"), a free name instead of overwriting, a clean
   name (no path), the type from the name and the content (programs, HTML, SVG, a picture that is none: refused), size per
   file, number of files, the signed stamp, the honeypot, a cross-site send, a JSON answer for the page's script
 - the subfolder per request; the News item of the creator, bundled (one per link and 10 minutes), switched off = none
 - a person without an organisation (freelancer-matrix: files): the own private folder, the same link
usage: p2122_a_api_test.py <datadir>      (a fresh container; P2122A_NOSTART=1 = the server already runs)"""
import base64
import hashlib
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def tok(r):
    return r["url"].rsplit("/u/", 1)[1]


SENDS = [0]


def stamp(t, s=None):
    import re
    p = (s or requests).get(B + "/u/" + t)
    m = re.search(r'name="stamp" value="([^"]+)"', p.text)
    return m.group(1) if m else ""


def up(t, files, st, name="", js=False, s=None, extra=None):
    """One send (at most FRQ_SEND_RATE per address and minute: every 25th waits for the next minute)."""
    if SENDS[0] and SENDS[0] % 25 == 0:
        time.sleep(61)
    SENDS[0] += 1
    hd = {"X-Kalmido-Upload": "1"} if js else {}
    return (s or requests).post(B + "/u/" + t, data={"stamp": st, "name": name, **(extra or {})},
                                files=[("file", f) for f in files], headers=hd)


def kids(fid):
    return [r[0] for r in dbx("SELECT name FROM fs_nodes WHERE parent_id=? AND deleted_at IS NULL ORDER BY id", (fid,))]


if not os.environ.get("P2122A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,files,docs"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.patch(B + "/api/admin/settings", json={"public_links": True})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
BOB = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
ORG2 = dbx("INSERT INTO orgs(name,icon,created_at) VALUES('Other Example','','2026-10-01T00:00:00Z') RETURNING id")[0][0]
dbx("DELETE FROM org_members WHERE user_id=?", (CAROL,))
dbx("INSERT INTO org_members(org_id,user_id) VALUES(?,?)", (ORG2, CAROL))
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
F = A.post(B + "/api/files/folders", json={"name": "Clients Secret Folder", "space": f"org:{ORG}"}).json()["id"]
A.post(B + "/api/files/upload", data={"parent_id": F}, files=[("file", ("secret-plan.pdf", PDF, "application/pdf"))])
check(kids(F) == ["secret-plan.pdf"], "the folder with a file of its own")

# ================================================================== managing
U = f"/api/files/nodes/{F}/requests"
check(A.post(B + U, json={"title": "Your documents"}).status_code == 400, "no end date: 400")
check(A.post(B + U, json={"title": "Your documents", "days": 91}).status_code == 400, "more than 90 days: 400")
check(A.post(B + U, json={"title": "Your documents", "expires_at": "2020-01-01"}).status_code == 400, "an end date in the past: 400")
check(A.post(B + U, json={"title": "", "days": 14}).status_code == 400, "no title: 400")
check(A.post(B + U, json={"title": "X", "days": 14, "types": ["exe"]}).status_code == 400, "an unknown kind: 400")
check(A.post(B + U, json={"title": "X", "days": 14, "max_mb": 0}).status_code == 400, "max_mb 0: 400")
check(A.post(B + U, json={"title": "X", "days": 14, "max_files": 1000}).status_code == 400, "max_files over the limit: 400")
r = A.post(B + U, json={"title": "Your documents", "note": "Please upload the logo.\nThank you.", "days": 14})
Q = r.json()
check(r.status_code == 201 and Q["state"] == "active" and Q["types"] == ["docs", "images"] and Q["max_files"] == 20 and "/u/" in Q.get("url", ""),
      "a request: 201 with its link and the defaults " + r.text[:300])
T = tok(Q)
row = dbx("SELECT token, token_hash, org_id, created_by FROM fs_upload_requests WHERE id=?", (Q["id"],))[0]
check(row[0] != T and T not in row[0] and row[1] == hashlib.sha256(T.encode()).hexdigest() and row[2] == ORG,
      "the token is stored sealed + hashed, the folder's organisation")
r = A.get(B + U)
check(r.ok and [x["id"] for x in r.json()["requests"]] == [Q["id"]] and r.json()["requests"][0]["url"] == Q["url"]
      and r.json()["limits"]["days"] == 90, "the folder's list " + r.text[:200])
check(A.get(B + U.replace(str(F), "999999")).status_code == 404, "an unknown folder: 404")
fid_file = dbx("SELECT id FROM fs_nodes WHERE parent_id=? AND name='secret-plan.pdf'", (F,))[0][0]
check(A.post(B + f"/api/files/nodes/{fid_file}/requests", json={"title": "X", "days": 3}).status_code == 409, "a file, no folder: 409")
# tenant-matrix: file_request -- another organisation: 404; a member without the write right: 404 (does not see the folder)
check(Ca.get(B + U).status_code == 404 and Ca.post(B + U, json={"title": "X", "days": 3}).status_code == 404, "another organisation: 404")
check(Ca.patch(B + f"/api/files/requests/{Q['id']}", json={"revoked": True}).status_code == 404 and
      Ca.delete(B + f"/api/files/requests/{Q['id']}").status_code == 404, "another organisation cannot change / remove it: 404")
check(Bo.get(B + U).status_code == 404, "a member without access to the folder: 404")
sh = A.post(B + f"/api/files/nodes/{F}/shares", json={"user_id": BOB, "role": "view"}).json()
check(Bo.get(B + U).status_code == 403, "view only: 403")
A.patch(B + f"/api/files/shares/{sh['id']}", json={"role": "edit"})
r = Bo.get(B + U)
bq = r.json()["requests"][0] if r.ok else {}
check(r.ok and "url" not in bq and bq["manage"] is False and bq["created_by_name"] == "Alice", "an editor sees the requests, not someone else's link")
check(Bo.patch(B + f"/api/files/requests/{Q['id']}", json={"revoked": True}).status_code == 403, "an editor cannot stop someone else's: 403")

# ================================================================== the page
anon = requests.Session()
p = anon.get(B + "/u/" + T)
check(p.ok and "Your documents" in p.text and "Please upload the logo." in p.text and "Thank you." in p.text, "the page: title and note")
check("Clients Secret Folder" not in p.text and "secret-plan" not in p.text and "Alice" not in p.text, "the page never shows the folder, its files or the creator")
check("script-src 'self'" in p.headers.get("Content-Security-Policy", "") and "noindex" in p.headers.get("X-Robots-Tag", ""), "the page's headers: own script only, noindex")
check(anon.get(B + "/u/v/up.js").ok and "X-Kalmido-Upload" in anon.get(B + "/u/v/up.js").text, "the page's script")
GONE = anon.get(B + "/u/" + "x" * 32)
check(GONE.status_code == 404 and "no longer open" in GONE.text, "an unknown link: 404")
check(anon.get(B + "/u/<b>").status_code == 404, "garbage: 404")
ST = stamp(T, anon)
time.sleep(2.2)

# ================================================================== uploading
r = up(T, [("logo.png", PNG, "text/html")], ST, "Eve Example", s=anon)
check(r.ok and "1 file has arrived" in r.text, "an upload: the thank-you page " + r.text[-300:])
n = dbx("SELECT id, created_by, owner_id, org_id, mime FROM fs_nodes WHERE parent_id=? AND name='logo.png'", (F,))
check(n and n[0][1] == 1 and n[0][3] == ORG and n[0][4] == "image/png", "the file is the creator's in the folder, its type from the name (not the sender's) " + str(n))
NID = n[0][0] if n else 0
check(A.get(B + f"/api/files/nodes/{NID}/content").content == PNG, "the creator reads the content")
lg = dbx("SELECT user_id, action, detail FROM fs_log WHERE node_id=? AND action='frq_upload'", (NID,))
check(lg and lg[0][0] == 1 and "Your documents" in lg[0][2] and "Eve Example" in lg[0][2], "the history: received through the file request " + str(lg))
r = up(T, [("logo.png", PNG, "image/png")], ST, js=True, s=anon)
check(r.ok and r.json().get("ok") and r.json()["n"] == 1, "the script's send: JSON " + r.text[:200])
check(kids(F) == ["secret-plan.pdf", "logo.png", "logo (2).png"], "the same name again: a second file, nothing overwritten " + str(kids(F)))
r = up(T, [("../../etc/passwd.pdf", PDF, "application/pdf")], ST, js=True, s=anon)
check(r.ok and "passwd.pdf" in kids(F) and not any(".." in k or "/" in k for k in kids(F)), "a path in the name: only the name stays")
for nm, data, what in (("run.exe", b"MZ" + b"\0" * 100, "a program"), ("page.html", b"<html><script>x</script></html>", "HTML"),
                       ("pic.svg", b"<svg onload='x'></svg>", "SVG"), ("fake.png", b"<html><body>no picture</body></html>", "HTML as a picture"),
                       ("fake.pdf", b"just text", "text as a PDF"), ("tool.txt", b"#!/bin/sh\necho hi\n", "a script as text"),
                       ("song.mp3", b"ID3" + b"\0" * 50, "a kind the request does not allow"), ("noext", b"plain", "no ending")):
    r = up(T, [(nm, data, "application/pdf")], ST, js=True, s=anon)
    check(r.status_code == 400 and "not accepted" in r.json().get("error", ""), f"{what}: refused " + r.text[:200])
check(not {"run.exe", "page.html", "pic.svg", "fake.png", "fake.pdf", "tool.txt", "song.mp3", "noext"} & set(kids(F)), "nothing refused was stored")
r = up(T, [("empty.pdf", b"", "application/pdf")], ST, js=True, s=anon)
check(r.status_code == 400, "an empty file: 400")
check(up(T, [("a.pdf", PDF, "")], "", js=True, s=anon).status_code == 400, "without the stamp: 400")
check(up(T, [("a.pdf", PDF, "")], ST[:-1] + ("0" if ST[-1] != "0" else "1"), js=True, s=anon).status_code == 400, "a forged stamp: 400")
r = up(T, [("bot.pdf", PDF, "")], ST, js=True, s=anon, extra={"website": "http://spam.example.com"})
check(r.ok and "bot.pdf" not in kids(F), "the honeypot: pretends, stores nothing")
r = requests.post(B + "/u/" + T, data={"stamp": ST}, files=[("file", ("x.pdf", PDF, ""))], headers={"Sec-Fetch-Site": "cross-site"})
check(r.status_code == 403 and "x.pdf" not in kids(F), "a cross-site send: 403")
r = up(T, [("a.pdf", PDF, ""), ("b.pdf", PDF, "")], ST, s=anon)
check(r.ok and "2 files have arrived" in r.text, "two files in one plain send " + r.text[-200:])
# a signed-in person of another organisation uses the link like a visitor: the file is the creator's
SC = stamp(T, Ca)
time.sleep(2.2)
r = up(T, [("from-carol.pdf", PDF, "")], SC, js=True, s=Ca)
c_row = dbx("SELECT created_by, org_id FROM fs_nodes WHERE name='from-carol.pdf'")
check(r.ok and c_row == [(1, ORG)], "signed in elsewhere: like a visitor, the creator's file " + str(c_row))

# ---- size and number of files
Q2 = A.post(B + U, json={"title": "Small", "days": 3, "max_mb": 1, "max_files": 2, "types": ["docs"]}).json()
T2 = tok(Q2)
S2 = stamp(T2, anon)
time.sleep(2.2)
r = up(T2, [("big.pdf", PDF + b"0" * (1024 * 1024 + 10), "")], S2, js=True, s=anon)
check(r.status_code in (400, 413) and "big.pdf" not in kids(F), "larger than the request's limit: refused " + str(r.status_code))
r = up(T2, [("p.png", PNG, "")], S2, js=True, s=anon)
check(r.status_code == 400 and "not accepted" in r.json().get("error", ""), "a picture where only documents are allowed: refused")
r = up(T2, [("one.pdf", PDF, ""), ("two.pdf", PDF, ""), ("three.pdf", PDF, "")], S2, js=True, s=anon)
check(r.status_code == 400 and "At most 2" in r.json().get("error", "") and "one.pdf" not in kids(F), "more files than allowed in one send: 400")
check(up(T2, [("one.pdf", PDF, ""), ("two.pdf", PDF, "")], S2, js=True, s=anon).ok, "up to the number: ok")
r = up(T2, [("three.pdf", PDF, "")], S2, js=True, s=anon)
check(r.status_code == 409 and "no more files" in r.json().get("error", ""), "the number reached: 409")
check("takes no more files" in anon.get(B + "/u/" + T2).text, "the page says so")
q2 = [x for x in A.get(B + U).json()["requests"] if x["id"] == Q2["id"]][0]
check(q2["count"] == 2, "the list counts the files")

# ================================================================== the link stops: every way the same answer
GT = GONE.text


def gone(t, what):
    r = anon.get(B + "/u/" + t)
    check(r.status_code == 404 and r.text == GT, what + ": the same answer as an unknown link")


r = A.patch(B + f"/api/files/requests/{Q['id']}", json={"revoked": True})
check(r.ok and r.json()["state"] == "revoked", "stop: revoked")
gone(T, "stopped")
check(up(T, [("late.pdf", PDF, "")], ST, js=True, s=anon).status_code == 404, "stopped: no upload")
r = A.patch(B + f"/api/files/requests/{Q['id']}", json={"revoked": False})
check(r.ok and r.json()["state"] == "active" and anon.get(B + "/u/" + T).ok, "open again (the undo of a stop)")
check(A.patch(B + f"/api/files/requests/{Q['id']}", json={"days": 91}).status_code == 400, "extend beyond 90 days: 400")
check(A.patch(B + f"/api/files/requests/{Q['id']}", json={"days": 30}).json()["expires_at"] > Q["expires_at"], "extend")
dbx("UPDATE fs_upload_requests SET expires_at='2026-01-01T00:00:00Z' WHERE id=?", (Q["id"],))
gone(T, "expired")
check([x["state"] for x in A.get(B + U).json()["requests"] if x["id"] == Q["id"]] == ["expired"], "the list: expired")
A.patch(B + f"/api/files/requests/{Q['id']}", json={"days": 14})
check(anon.get(B + "/u/" + T).ok, "extended again: works")
check(A.delete(B + f"/api/files/requests/{Q['id']}").ok, "remove")
gone(T, "removed")
check(Q["id"] not in [x["id"] for x in A.get(B + U).json()["requests"]], "removed: not in the list")
check(A.post(B + f"/api/files/requests/{Q['id']}/restore").ok and anon.get(B + "/u/" + T).ok, "restore (the undo of a remove)")
check(A.delete(B + f"/api/files/nodes/{F}").ok, "the folder into the trash")
gone(T, "folder in the trash")
A.post(B + f"/api/files/nodes/{F}/restore")
check(anon.get(B + "/u/" + T).ok, "the folder back: works again")
dbx("UPDATE fs_upload_requests SET org_id=NULL WHERE id=?", (Q["id"],))
gone(T, "folder in another workspace than the request")
dbx("UPDATE fs_upload_requests SET org_id=? WHERE id=?", (ORG, Q["id"]))
# the creator loses the write right: Bob's request stops
r = Bo.post(B + U, json={"title": "Bob asks", "days": 5})
QB = r.json()
check(r.status_code == 201 and QB.get("url"), "an editor creates an own request")
check(Bo.patch(B + f"/api/files/requests/{QB['id']}", json={"title": "Bob asks again"}).ok, "and changes it")
A.delete(B + f"/api/files/shares/{sh['id']}")
gone(tok(QB), "the creator without the write right")
qb = [x for x in A.get(B + U).json()["requests"] if x["id"] == QB["id"]][0]
check(qb["state"] == "inactive" and qb["manage"] is True and qb.get("url"), "the folder's owner sees it as not working and may manage it")
A.patch(B + "/api/admin/settings", json={"public_links": False})
gone(T, "public links switched off")
check(A.post(B + U, json={"title": "Off", "days": 3}).status_code == 409, "public links off: no new request (409)")
A.patch(B + "/api/admin/settings", json={"public_links": True})

# ================================================================== the subfolder, the News item
Q3 = A.post(B + U, json={"title": "Acme Example logos", "days": 3, "subfolder": True}).json()
T3 = tok(Q3)
S3 = stamp(T3, anon)
time.sleep(2.2)
up(T3, [("a1.pdf", PDF, "")], S3, js=True, s=anon)
up(T3, [("a2.pdf", PDF, "")], S3, js=True, s=anon)
up(T3, [("a3.pdf", PDF, ""), ("a4.pdf", PDF, "")], S3, s=anon)  # two in one plain send: the same subfolder
sub = dbx("SELECT sub_id FROM fs_upload_requests WHERE id=?", (Q3["id"],))[0][0]
check(sub and kids(sub) == ["a1.pdf", "a2.pdf", "a3.pdf", "a4.pdf"] and [k for k in kids(F) if k.startswith("Acme")] == ["Acme Example logos"],
      "the subfolder per request, one only " + str(kids(F)))
items = [x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "filereq" and x["data"].get("req") == Q3["id"]]
check(len(items) == 1 and items[0]["data"]["n"] == 4 and items[0]["data"]["node"] == sub and items[0].get("to_me"),
      "ONE News item for the creator, the count raised (bundled), For you " + str(items)[:300])
A.patch(B + "/api/settings", json={"notify": {"filereq": {"news": False, "push": False}}})
Q4 = A.post(B + U, json={"title": "Quiet", "days": 3}).json()
S4 = stamp(tok(Q4), anon)
time.sleep(2.2)
up(tok(Q4), [("q.pdf", PDF, "")], S4, js=True, s=anon)
check(not [x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "filereq" and x["data"].get("req") == Q4["id"]],
      "the event switched off in the notification settings: no News item")
check(not [x for x in Bo.get(B + "/api/news").json()["items"] if x["kind"] == "filereq"], "nobody else gets it")

# ================================================================== freelancer-matrix: files
FID, Fr = freelancer(B, A)
PF = Fr.post(B + "/api/files/folders", json={"name": "Customer uploads", "space": "private"}).json()["id"]
r = Fr.post(B + f"/api/files/nodes/{PF}/requests", json={"title": "For my client", "days": 7})
QF = r.json()
check(r.status_code == 201 and Fr.get(B + f"/api/files/nodes/{PF}/requests").ok, "freelancer: a request in the private space")
SF = stamp(tok(QF), anon)
time.sleep(2.2)
r = up(tok(QF), [("brief.pdf", PDF, "")], SF, js=True, s=anon)
fr = dbx("SELECT created_by, org_id FROM fs_nodes WHERE parent_id=? AND name='brief.pdf'", (PF,))
check(r.ok and fr == [(FID, None)], "freelancer: the client's file lands in the private folder " + str(fr))
check(Fr.patch(B + f"/api/files/requests/{QF['id']}", json={"revoked": True}).ok and Fr.delete(B + f"/api/files/requests/{QF['id']}").ok
      and Fr.post(B + f"/api/files/requests/{QF['id']}/restore").ok, "freelancer: stop, remove, restore")
check(A.get(B + f"/api/files/nodes/{PF}/requests").status_code == 404, "another person's private folder: 404 (also for the instance admin)")

print(f"p2122_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
