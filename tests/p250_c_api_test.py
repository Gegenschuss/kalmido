#!/usr/bin/env python3
"""2.50.0 API tests, part C: #329 the customer view of a public list link (the owner chooses what the customer sees:
progress, sections, due dates, assignee, tags, single custom fields, task files, organisation name; "only tasks with tag";
filtered on the server, team comments never) and #1200 approval links with a simple electronic signature (accept / decline
a sent quotation, acceptance of a list / milestone): token only as hash, form check value, the same 404 for unknown /
expired / revoked / voided links, the protocol (name, time, address, user agent, SHA-256), the quotation's status, one
decision only, rate limits, and the workspace boundary (tenant-matrix: signoff). Invented names only.
usage: p250_c_api_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
import hashlib
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def anon(path, **kw):
    return requests.get(B + path, allow_redirects=False, **kw)


def form_key(html):
    m = re.search(r'name="f" value="([0-9a-f]+)"', html)
    return m.group(1) if m else ""


if not os.environ.get("P250C_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
FEAT = "cal,comments,collab,office,clients"
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ids = {}
for u, dn in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Private")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": dn, "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE})
assert r.ok, r.text
ORG = r.json()["id"]
assert A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [ALICE, BOB], "admins": [ALICE]}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.ok, r.text
ORG2 = r.json()["id"]
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})

# ================================================================ #329 the customer view
L = A.post(B + "/api/lists", json={"name": "Imagefilm Kunde"}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Other project"}).json()["id"]
SEC = A.post(B + "/api/sections", json={"list_id": L, "name": "Dreh"}).json()["id"]
F1 = A.post(B + f"/api/lists/{L}/fields", json={"name": "Budget", "type": "number", "options": {"unit": "EUR"}}).json()["id"]
F2 = A.post(B + f"/api/lists/{L}/fields", json={"name": "Internal note", "type": "text"}).json()["id"]
FX = A.post(B + f"/api/lists/{L2}/fields", json={"name": "Elsewhere", "type": "text"}).json()["id"]
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
assert r.ok, r.text
T1 = A.post(B + "/api/tasks", json={"list_id": L, "title": "Rohschnitt liefern", "ltags": ["kunde"], "assignee_id": BOB, "due": "2030-05-04",
                                    "section_id": SEC, "fields": {str(F1): "1200", str(F2): "SECRET-FIELD"}}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"list_id": L, "title": "Interne Kalkulation", "due": "2030-05-05"}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"list_id": L2, "title": "Fremde Aufgabe"}).json()["id"]
A.post(B + f"/api/tasks/{T1}/comments", json={"body": "INTERNAL-COMMENT-XYZ"})
up = A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("storyboard.txt", b"frames 1-12", "text/plain")})
check(up.ok, f"a task file ({up.status_code})")
ATT = (up.json().get("attachments") or [{}])[-1].get("id") if up.ok else 0
up2 = A.post(B + f"/api/tasks/{T3}/attachments", files={"file": ("other.txt", b"other list", "text/plain")})
ATT_OTHER = (up2.json().get("attachments") or [{}])[-1].get("id") if up2.ok else 0
r = A.put(B + f"/api/lists/{L}/public-link", json={"mode": "tick"})
check(r.ok, f"public link created ({r.status_code} {r.text[:120]})")
k = r.json()["link"]
TOK = k["url"].split("/s/")[1]
check(k["show"] == {"progress": False, "sections": True, "due": True, "assignees": False, "tags": False, "files": False, "brand": False,
                    "fields": [], "tag": None}, f"a new link shows what 2.49 showed (sections + due dates) {k['show']}")
check({f["id"] for f in k["options"]["fields"]} == {F1, F2} and [t["name"] for t in k["options"]["tags"]] == ["kunde"],
      f"the dialog offers the list's fields and tags {k['options']}")
check(A.get(B + f"/api/lists/{L}/public-link").json().get("options", {}).get("fields"), "GET offers the options without a link too")
p = anon("/s/" + TOK).text
check("Rohschnitt liefern" in p and "Interne Kalkulation" in p and "Dreh" in p, "default: tasks + section heading")
for bad in ("Bob Member", "kunde", "1200", "SECRET-FIELD", "storyboard.txt", "INTERNAL-COMMENT-XYZ", "Alpha Studio", 'class="prog"'):
    check(bad not in p, f"default page without {bad!r}")
# switch on
r = A.put(B + f"/api/lists/{L}/public-link", json={"show": {"progress": True, "assignees": True, "tags": True, "files": True, "brand": True,
                                                            "fields": [F1]}})
check(r.ok and r.json()["link"]["show"]["fields"] == [F1], f"show saved ({r.text[:160]})")
p = anon("/s/" + TOK).text
for want in ("Bob Member", ">kunde<", "Budget", "1200 EUR", "storyboard.txt", "Alpha Studio", 'class="prog"', "0 of 2 done", "w0"):
    check(want in p, f"switched on: page has {want!r}")
for bad in ("SECRET-FIELD", "Internal note", "INTERNAL-COMMENT-XYZ", "Fremde Aufgabe", "other.txt", "bob@"):
    check(bad not in p, f"never on the page: {bad!r}")
check(not re.search(r"<script", p, re.I), "no scripts on the page")
# files: only through the token, only task files of shown tasks
r = anon(f"/s/{TOK}/file/{ATT}")
check(r.status_code == 200 and r.content == b"frames 1-12" and "attachment" in r.headers.get("Content-Disposition", "")
      and "sandbox" in r.headers.get("Content-Security-Policy", "") and r.headers.get("Cache-Control") == "no-store, private",
      f"file download through the link ({r.status_code} {r.headers.get('Content-Disposition')})")
gone = anon("/s/" + "x" * 32)
check(gone.status_code == 404, "unknown token: 404")
r = anon(f"/s/{TOK}/file/{ATT_OTHER}")
check(r.status_code == 404 and r.text == gone.text, f"a file of another list: the same 404 ({r.status_code})")
check(anon(f"/s/{'y' * 32}/file/{ATT}").status_code == 404, "a file with an unknown token: 404")
# fields / tags of another list refused, the owner only
check(A.put(B + f"/api/lists/{L}/public-link", json={"show": {"fields": [FX]}}).status_code == 400, "a field of another list: 400")
check(A.put(B + f"/api/lists/{L}/public-link", json={"show": {"tag": 999999}}).status_code == 400, "an unknown tag: 400")
check(A.put(B + f"/api/lists/{L}/public-link", json={"show": {"files": "yes"}}).status_code == 400, "a non-boolean switch: 400")
check(Bo.put(B + f"/api/lists/{L}/public-link", json={"show": {"files": True}}).status_code in (403, 404), "a member who is not the owner: refused")
check(Ca.put(B + f"/api/lists/{L}/public-link", json={"show": {"files": True}}).status_code in (403, 404), "another organisation: refused")
# only tasks with tag
TAG = A.get(B + f"/api/lists/{L}/public-link").json()["link"]["options"]["tags"][0]["id"]
r = A.put(B + f"/api/lists/{L}/public-link", json={"show": {"tag": TAG, "sections": False, "due": False}})
p = anon("/s/" + TOK).text
check("Rohschnitt liefern" in p and "Interne Kalkulation" not in p, "only tasks with the tag")
check("<h2>Dreh</h2>" not in p and "4 May" not in p and "2030" not in p, "sections and due dates off")
r = requests.post(B + f"/s/{TOK}/tick", data={"task": T2, "to": "done"}, allow_redirects=False)
check(r.status_code == 404, f"ticking a task the link does not show: 404 ({r.status_code})")
check(A.get(B + f"/api/tasks/{T2}").json().get("status") == 0, "the hidden task stays open")
# files off -> the download stops
A.put(B + f"/api/lists/{L}/public-link", json={"show": {"files": False}})
check(anon(f"/s/{TOK}/file/{ATT}").status_code == 404, "files switched off: the download is 404")

# ================================================================ #1200 approval of a quotation
r = A.put(B + "/api/office/settings", json={"company": {"name": "Alpha Studio GmbH", "lines": ["Alpha Studio GmbH", "Beispielweg 1"]},
                                            "lang": "de", "currency": "EUR"})
check(r.ok, "office settings " + r.text[:120])
SV = A.post(B + "/api/office/services", json={"name_de": "Schnitt", "name_en": "Editing", "category": "Video", "daily_rate": 900, "hourly_rate": None,
                                              "raw_fee": 0, "producing": 0, "intext": "intern", "unit": "day", "tax": "standard"}).json()["id"]
r = A.post(B + "/api/office/docs", json={"project_title": "Imagefilm Herbst", "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG"]}})
assert r.status_code == 201, r.text
DOC = r.json()["id"]
A.put(B + f"/api/office/docs/{DOC}/items", json={"items": [{"service_id": SV, "qty": 2}]})
r = A.post(B + f"/api/office/docs/{DOC}/signoff", json={})
check(r.status_code == 409, f"a draft gets no approval link ({r.status_code})")
check(A.post(B + f"/api/office/docs/{DOC}/status", json={"status": "sent"}).ok, "quotation sent")
r = A.post(B + f"/api/office/docs/{DOC}/signoff", json={})
check(r.ok and r.json()["live"] and r.json()["url"], f"approval link of a sent quotation ({r.status_code} {r.text[:160]})")
S1 = r.json()
STOK = S1["url"].split("/s/q/")[1]
check(len(STOK) >= 43, "the token has 256 bits")
row = dbx("SELECT token_hash, token FROM office_signoffs WHERE id=?", (S1["id"],))[0]
check(row[0] == hashlib.sha256(STOK.encode()).hexdigest() and STOK not in row[1], "stored: the SHA-256 and a sealed copy, never the token")
# tenant matrix
check(Ca.get(B + f"/api/office/docs/{DOC}/signoffs").status_code == 404, "another organisation: the quotation's links 404")
check(Ca.post(B + f"/api/office/docs/{DOC}/signoff", json={}).status_code == 404, "another organisation cannot create a link")
check(Ca.post(B + f"/api/office/signoffs/{S1['id']}/revoke").status_code == 404, "another organisation cannot stop a link")
check(Da.post(B + f"/api/office/signoffs/{S1['id']}/revoke").status_code in (403, 404), "a private person cannot stop a link")
check(Bo.get(B + f"/api/office/docs/{DOC}/signoffs").ok, "a member of the organisation sees the links")
# the page
pg = anon("/s/q/" + STOK)
check(pg.status_code == 200 and "Imagefilm Herbst" in pg.text and "Schnitt" in pg.text and "1.800,00" in pg.text, f"the page shows the quotation ({pg.status_code})")
check("default-src 'none'" in pg.headers.get("Content-Security-Policy", "") and "noindex" in pg.headers.get("X-Robots-Tag", ""), "strict CSP, noindex")
check("qualified signature" in pg.text or "qualifizierte" in pg.text, "the note on the simple electronic signature")
check(not re.search(r"<script", pg.text, re.I), "no scripts on the approval page")
pdf = anon(f"/s/q/{STOK}/pdf")
check(pdf.status_code == 200 and pdf.content[:4] == b"%PDF", "the PDF through the link")
FK = form_key(pg.text)
post = lambda tok, **d: requests.post(B + "/s/q/" + tok, data=d, allow_redirects=False, headers={"User-Agent": "TestBrowser/1.0"})  # noqa: E731
check(post(STOK, f="0" * 64, name="Max Muster", ok="1", do="accept").status_code == 403, "a wrong form check value: 403")
r = requests.post(B + "/s/q/" + STOK, data={"f": FK, "name": "Max Muster", "ok": "1", "do": "accept"}, allow_redirects=False,
                  headers={"Sec-Fetch-Site": "cross-site"})
check(r.status_code == 403, "a cross-site post: 403")
check(post(STOK, f=FK, name="Max Muster", do="accept").status_code == 400, "accept without the tick: 400")
check(post(STOK, f=FK, name="M", ok="1", do="accept").status_code == 400, "a name that is too short: 400")
check(A.get(B + f"/api/office/docs/{DOC}").json()["status"] == "sent", "nothing decided yet")
r = post(STOK, f=FK, name="Max <b>Muster</b>", email="max@example.com", ok="1", do="accept")
check(r.status_code == 303, f"accepted ({r.status_code})")
check(A.get(B + f"/api/office/docs/{DOC}").json()["status"] == "accepted", "the quotation is accepted")
pg = anon("/s/q/" + STOK)
check(pg.status_code == 200 and "&lt;b&gt;Muster" in pg.text and "<b>Muster" not in pg.text and 'name="f"' not in pg.text,
      "afterwards only the confirmation (escaped name, no form)")
check(post(STOK, f=FK, name="Someone Else", do="decline").status_code == 303, "a second decision is ignored")
lst = A.get(B + f"/api/office/docs/{DOC}/signoffs").json()["signoffs"]
x = lst[0]
check(x["state"] == "accepted" and x["signer_name"] == "Max <b>Muster</b>" and x["signer_email"] == "max@example.com" and x["ip"]
      and x["user_agent"] == "TestBrowser/1.0" and x["signed_at"] and x["doc_hash"] == S1["doc_hash"] and not x["live"] and not x["url"],
      f"the protocol {x}")
log = A.get(B + f"/api/office/docs/{DOC}/log").json().get("log") or []
acts = [e["action"] for e in log]
check("signoff_accepted" in acts and "signoff_link" in acts and "status" in acts, f"office log {acts}")
ent = next((e for e in log if e["action"] == "signoff_accepted"), {})
check((ent.get("detail") or {}).get("name") == "Max <b>Muster</b>" and (ent.get("detail") or {}).get("doc_hash") == S1["doc_hash"], "the log has name + hash")

# a second quotation: decline, change voids, revoke, expiry
r = A.post(B + f"/api/office/docs/{DOC}/duplicate")
DOC2 = r.json()["id"]
A.post(B + f"/api/office/docs/{DOC2}/status", json={"status": "sent"})
S2 = A.post(B + f"/api/office/docs/{DOC2}/signoff", json={}).json()
T2K = S2["url"].split("/s/q/")[1]
S3 = A.post(B + f"/api/office/docs/{DOC2}/signoff", json={}).json()
check(anon("/s/q/" + T2K).status_code == 404, "a new link stops the older one of the same quotation")
T3K = S3["url"].split("/s/q/")[1]
dbx("UPDATE office_docs SET project_title=? WHERE id=?", ("Changed after the link", DOC2), write=True)
r = anon("/s/q/" + T3K)
check(r.status_code == 404 and r.text == anon("/s/q/" + "z" * 43).text, "a quotation changed after the link: the same 404 as unknown")
dbx("UPDATE office_docs SET project_title=? WHERE id=?", ("Imagefilm Herbst", DOC2), write=True)
check(anon("/s/q/" + T3K).status_code == 200, "back as it was: the link works again")
dbx("UPDATE office_signoffs SET expires_at=? WHERE id=?", ("2020-01-01T00:00:00+00:00", S3["id"]), write=True)
check(anon("/s/q/" + T3K).status_code == 404, "expired: 404")
dbx("UPDATE office_signoffs SET expires_at=NULL WHERE id=?", (S3["id"],), write=True)
pg = anon("/s/q/" + T3K)
r = post(T3K, f=form_key(pg.text), name="Erika Beispiel", do="decline", reason="Zu teuer")
check(r.status_code == 303 and A.get(B + f"/api/office/docs/{DOC2}").json()["status"] == "declined", "declined -> the quotation is declined")
x = A.get(B + f"/api/office/docs/{DOC2}/signoffs").json()["signoffs"][0]
check(x["state"] == "declined" and x["reason"] == "Zu teuer", "the reason is stored")
check(A.post(B + f"/api/office/docs/{DOC2}/signoff", json={}).status_code == 409, "a decided quotation gets no new link")
DOC3 = A.post(B + f"/api/office/docs/{DOC}/duplicate").json()["id"]
A.post(B + f"/api/office/docs/{DOC3}/status", json={"status": "sent"})
S4 = A.post(B + f"/api/office/docs/{DOC3}/signoff", json={"expires": "2099-12-31"}).json()
check(S4.get("expires_at", "")[:13] in ("2099-12-31T22", "2099-12-31T23", "2100-01-01T00"), f"expiry through the end of the day {S4.get('expires_at')}")
check(A.post(B + f"/api/office/docs/{DOC3}/signoff", json={"expires": "2001-01-01"}).status_code == 400, "an expiry in the past: 400")
S4 = A.post(B + f"/api/office/docs/{DOC3}/signoff", json={}).json()
T4K = S4["url"].split("/s/q/")[1]
r = Bo.post(B + f"/api/office/signoffs/{S4['id']}/revoke")
check(r.ok and r.json()["revoked_at"], "a member stops the link")
check(anon("/s/q/" + T4K).status_code == 404, "stopped: 404")

# ================================================================ #1200 acceptance of a list
MS = A.post(B + "/api/tasks", json={"list_id": L, "title": "Abnahme Rohschnitt", "ms": 1}).json()["id"]
j = A.get(B + f"/api/lists/{L}/signoffs").json()
check([m["id"] for m in j["milestones"]] == [MS] and [s["id"] for s in j["sections"]] == [SEC], f"the dialog offers milestones and sections {j}")
check(A.post(B + f"/api/lists/{L}/signoffs", json={"task_id": T3}).status_code == 400, "a task of another list: 400")
check(Ca.get(B + f"/api/lists/{L}/signoffs").status_code in (403, 404), "another organisation: the list's links refused")
check(Da.post(B + f"/api/lists/{L}/signoffs", json={}).status_code in (403, 404), "a private person cannot create one")
check(Bo.post(B + f"/api/lists/{L}/signoffs", json={}).status_code in (403, 404), "a member who is not the owner cannot create one")
r = A.post(B + f"/api/lists/{L}/signoffs", json={"task_id": MS})
check(r.ok and r.json()["title"] == "Imagefilm Kunde: Abnahme Rohschnitt", f"acceptance of a milestone ({r.text[:120]})")
SA = r.json()
TA = SA["url"].split("/s/q/")[1]
p = anon("/s/" + TOK).text
check(f'href="/s/q/{TA}"' in p, "the customer page links the acceptance request")
check(Ca.post(B + f"/api/lists/{L}/signoffs/{SA['id']}/revoke").status_code in (403, 404), "another organisation cannot stop it")
A.post(B + f"/api/tasks/{MS}/complete")
pg = anon("/s/q/" + TA)
check(pg.status_code == 200 and "Abnahme Rohschnitt" in pg.text, "ticking the milestone off does not void the link")
r = post(TA, f=form_key(pg.text), name="Max Muster", ok="1", do="accept")
check(r.status_code == 303, "acceptance confirmed")
x = A.get(B + f"/api/lists/{L}/signoffs").json()["signoffs"][0]
check(x["state"] == "accepted" and x["signer_name"] == "Max Muster", "the list's protocol")
check("Accepted: Imagefilm Kunde: Abnahme Rohschnitt" in anon("/s/" + TOK).text, "the customer page shows the acceptance")

# ================================================================ rate limit of decisions (per client address)
SR = A.post(B + f"/api/lists/{L}/signoffs", json={}).json()
TR = SR["url"].split("/s/q/")[1]
fk = form_key(anon("/s/q/" + TR).text)
codes = [post(TR, f=fk, name="", do="accept").status_code for _ in range(14)]
check(429 in codes and set(codes) <= {400, 429}, f"decisions per address are limited {codes}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
