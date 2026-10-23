#!/usr/bin/env python3
"""2.138.4 API tests, part C (#2377 #2378 #2380 #2381 #2382): hardening leftovers of 2.126.0.
 - #2377: a large background contacts import (600 cards) takes a pool connection per batch and ends with every contact;
   importing the same file again updates them all (the result as before); a person without an organisation too
 - #2378: moving a contact OUT of an imported (mirrored) address book copies it (single PATCH: copied true, the mirror keeps
   its contact; bulk move: copied counts them, normal contacts still move)
 - #2380: the customer portal's sign-in mail budget of a space (KALMIDO_PORTAL_LOGIN_SPACE, small here): once it is used
   up the space's admin gets exactly one News item "ptlimit" (an organisation) / the person herself (private space)
 - #2381: the error-report webhook takes its token in a header (Authorization: Bearer / X-Kalmido-Token) at
   /api/hooks/issues/<list id>; the path form keeps working; the app's log masks the token part of hook paths
 - #2382: after a new server key (+ rewrap-accounts): status counts the Paperless token that no longer opens, the settings
   say to enter it again, reindex-private rebuilds the private documents' search index with the new key
freelancer-matrix: pim, office, docs
usage: p21383_c_api_test.py <datadir>      (a fresh container with the mail stub and a server key)"""
import base64
import json
import os
import secrets
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, sess, until  # 2.192.0 (#2514): shared helpers (tests/kt.py)
O = "/api/office"
KEYS = [base64.b64encode(os.urandom(32)).decode() for _ in range(2)]
FEAT = "cal,comments,collab,contacts,office,clients,docs"


def start(key, keep=False):
    env_ = ["-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none",
            "-e", "KALMIDO_MAIL_FROM=kalmido@example.test", "-e", "KALMIDO_INSTANCE_MODE=workspaces",
            "-e", "KALMIDO_PORTAL_LOGIN_SPACE=2", "-e", "KALMIDO_ORGCRYPT_DELAY=0", "-e", "KALMIDO_SECRET_KEY=" + key]
    if not keep:
        subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
        subprocess.run(["rm", "-rf", DATA])
        os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
        subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                       env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(env_)))
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    r = c.execute(sql, args).fetchall()
    c.commit()
    return r


def cli(*args, stdin=None):
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args], input=stdin,
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout, r.stderr


def py(code, env=()):
    e = [x for k in env for x in ("-e", k)]
    r = subprocess.run(["docker", "exec", "-i", *e, CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


def status_json(out):
    try:
        return json.loads(out[out.index("{"):])
    except ValueError:
        return {}


def news(s, kind):
    r = s.get(B + "/api/news")
    return [x for x in r.json().get("items", []) if x["kind"] == kind] if r.ok else []


def vcards(n, prefix):
    return "".join("\r\n".join(["BEGIN:VCARD", "VERSION:3.0", f"UID:{prefix}-{i}", f"FN:Probe Person {i}", f"N:Person {i};Probe;;;",
                                f"EMAIL:probe.{prefix}.{i}@example.com", "END:VCARD"]) + "\r\n" for i in range(n))


def bg_import(s, bk, text):
    r = s.post(B + f"/api/books/{bk}/import?background=1", files={"file": ("a.vcf", text, "text/vcard")})
    if r.status_code != 202:
        return r.status_code, {"error": r.text[:200]}
    iid = r.json().get("import_id", "x")
    st = until(lambda: (lambda j: j if j.get("state") in ("done", "failed") else None)(s.get(B + f"/api/books/imports/{iid}").json()), 180)
    return r.status_code, st or {}


def text_pdf(lines):
    """A one-page PDF with a text layer (as p2138_c_api_test.py)."""
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({x}) '" for x in lines) + " ET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


# ---------------------------------------------------------------- setup: Alpha (alice admin, bob member), frida without org
start(KEYS[0])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments", "clients", "contacts"]})
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"}).ok
Bo = sess("bob")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FR_ID, FR = freelancer(B, A, "frida")

# ============================================================ #2377: a large background import, a connection per batch
src = open(os.path.join(N, "..", "kalmido", "contacts", "web.py"), encoding="utf-8").read()
run = src[src.index("def lv_import_run("):src.index("def op_import_state(")]
check(run.index("connect()") > run.index("for i in range(0, len(cards), IMPORT_BATCH)"),
      "#2377: the background import takes its connection inside the batch loop")
BK = A.post(B + "/api/books", json={"name": "Big import"}).json()["id"]
TXT = vcards(600, "p2377")
code, st = bg_import(A, BK, TXT)
check(code == 202 and st.get("state") == "done" and st.get("created") == 600 and st.get("done") == 600,
      f"#2377: 600 cards in the background: all created {code} {str(st)[:200]}")
check(dbx("SELECT COUNT(*) FROM contacts WHERE book_id=?", (BK,))[0][0] == 600, "#2377: 600 contacts stored")
code, st = bg_import(A, BK, TXT)
check(st.get("state") == "done" and st.get("updated") == 600 and st.get("created") == 0,
      f"#2377: the same file again updates all of them (as before) {str(st)[:200]}")
FBK = FR.post(B + "/api/books", json={"name": "Frida import"}).json()["id"]  # freelancer-matrix: pim
code, st = bg_import(FR, FBK, vcards(450, "f2377"))
check(code == 202 and st.get("state") == "done" and st.get("created") == 450, f"#2377: a person without an organisation {str(st)[:200]}")

# ============================================================ #2378: out of a mirrored address book = a copy
srcid = dbx("INSERT INTO contact_srcs(user_id,name,url,status,created_at) VALUES(?,?,?,?,?) RETURNING id",
            (ALICE, "Outside", "https://contacts.example/book", "error", "2026-01-01T00:00:00+00:00"))[0][0]
MB = A.post(B + "/api/books", json={"name": "Mirror"}).json()["id"]
TB = A.post(B + "/api/books", json={"name": "Own"}).json()["id"]
OB = A.post(B + "/api/books", json={"name": "Other own"}).json()["id"]
mc = [A.post(B + "/api/contacts", json={"book_id": MB, "given": f"Mira{i}", "family": "Probe", "emails": [{"value": f"mira{i}@example.com"}]}).json()["id"]
      for i in range(3)]
own = A.post(B + "/api/contacts", json={"book_id": OB, "given": "Otto", "family": "Probe"}).json()["id"]
dbx("UPDATE books SET src_id=? WHERE id=?", (srcid, MB))
r = A.patch(B + f"/api/contacts/{mc[0]}", json={"book_id": TB, "note": "copied"})
j = r.json() if r.ok else {}
check(r.ok and j.get("copied") is True and j.get("id") != mc[0] and j.get("book_id") == TB and j.get("note") == "copied",
      f"#2378: PATCH book_id out of the mirror answers a new contact with copied {r.status_code} {r.text[:200]}")
check(dbx("SELECT book_id, note FROM contacts WHERE id=?", (mc[0],)) == [(MB, "")], "#2378: the mirror keeps its contact unchanged")
r = A.post(B + "/api/contacts/bulk", json={"ids": [mc[1], mc[2], own], "action": "move", "book_id": TB})
j = r.json() if r.ok else {}
check(r.ok and j.get("copied") == 2 and j.get("moved") == 1, f"#2378: bulk move: two copied, one moved {r.status_code} {r.text[:200]}")
check(dbx("SELECT COUNT(*) FROM contacts WHERE book_id=?", (MB,))[0][0] == 3 and
      dbx("SELECT COUNT(*) FROM contacts WHERE book_id=?", (TB,))[0][0] == 4, "#2378: mirror 3, target 3 copies + the moved one")
r = A.post(B + "/api/contacts/bulk", json={"ids": [mc[1]], "action": "move", "book_id": TB})
check(r.ok and r.json().get("conflicts") == [mc[1]], f"#2378: copying the same contact again = a conflict, no duplicate {r.text[:160]}")
fsrc = dbx("INSERT INTO contact_srcs(user_id,name,url,status,created_at) VALUES(?,?,?,?,?) RETURNING id",
           (FR_ID, "Outside", "https://contacts.example/frida", "error", "2026-01-01T00:00:00+00:00"))[0][0]
FMB = FR.post(B + "/api/books", json={"name": "Frida mirror"}).json()["id"]  # freelancer-matrix: pim
FTB = FR.post(B + "/api/books", json={"name": "Frida own"}).json()["id"]
fc = FR.post(B + "/api/contacts", json={"book_id": FMB, "given": "Fara", "family": "Probe"}).json()["id"]
dbx("UPDATE books SET src_id=? WHERE id=?", (fsrc, FMB))
r = FR.patch(B + f"/api/contacts/{fc}", json={"book_id": FTB})
check(r.ok and r.json().get("copied") is True and dbx("SELECT book_id FROM contacts WHERE id=?", (fc,)) == [(FMB,)],
      f"#2378: a person without an organisation copies out of her mirror {r.status_code} {r.text[:160]}")

# ============================================================ #2380: the space's sign-in mail budget used up -> one News item
COMPANY = {"street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE", "email": "hallo@studio.example"}


def portal_setup(s, name, tag):
    assert s.put(B + O + "/settings", json={"company": {"name": name}, "lang": "de", "company_fields": {"name": name, **COMPANY}}).ok
    assert s.put(B + O + "/settings", json={"portal_docs": 1}).ok
    out = []
    for i in range(4):
        r = s.post(B + "/api/clients", json={"name": f"Kunde {tag}{i}", "email": f"kunde.{tag}{i}@example.com"})
        assert r.status_code == 201, r.text
        out.append(r.json()["id"])
    return out


A.patch(B + "/api/admin/settings", json={"public_links": True})
CL = portal_setup(A, "Studio Nordlicht GmbH", "a")
codes = [A.post(B + O + f"/clients/{x}/portal-link", json={}).status_code for x in CL]
check(all(x < 300 for x in codes[:2]) and codes[2:] == [429, 429], f"#2380: two links in the hour, then the space's budget (429) {codes}")
na = news(A, "ptlimit")
check(len(na) == 1 and na[0]["data"].get("org_id") == ORG and na[0]["data"].get("limit") == 2,
      f"#2380: the organisation's admin gets exactly one notice {[x.get('data') for x in na]}")
check(not news(Bo, "ptlimit"), "#2380: a member gets none")
FCL = portal_setup(FR, "Frida Frei Design", "f")  # freelancer-matrix: office
codes = [FR.post(B + O + f"/clients/{x}/portal-link", json={}).status_code for x in FCL]
nf = news(FR, "ptlimit")
check(all(x < 300 for x in codes[:2]) and codes[2] == 429 and len(nf) == 1 and not nf[0]["data"].get("org_id"),
      f"#2380: a person without an organisation: her own notice, once {codes} {[x.get('data') for x in nf]}")
check(len(news(A, "ptlimit")) == 1, "#2380: the other space's budget is its own")
psrc = open(os.path.join(N, "..", "kalmido", "team", "portal.py"), encoding="utf-8").read()
check(psrc.count("pt_limit_note(c, p[") == 1, "#2380: the portal's own sign-in form tells the owner too")
# 2.138.4 (#2380, review): the sign-in route stays on its handler - an unknown portal token is no server error
r = requests.post(B + "/p/" + secrets.token_urlsafe(24) + "/login", data={"email": "kunde@example.com"}, allow_redirects=False)
check(r.status_code < 500, f"#2380: POST /p/<token>/login answers without a server error {r.status_code}")

# ============================================================ #2381: the error-report token in a header
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
r = A.patch(B + f"/api/lists/{P}/error-hook", json={"state": "on"})
j = r.json() if r.ok else {}
TOK, HOOK = j.get("token", ""), j.get("hook_url", "")
check(r.ok and TOK and HOOK.endswith(f"/api/hooks/issues/{P}") and j.get("url", "").endswith(f"/api/hooks/issues/{P}/{TOK}"),
      f"#2381: on: the URL without the token, the token and the older URL {r.status_code} {r.text[:200]}")
check(TOK not in A.get(B + f"/api/lists/{P}/error-hook").text, "#2381: the token is never shown again")
rep = {"title": "TypeError in checkout", "body": "stack", "fingerprint": "fp-2381-a"}
r = requests.post(B + f"/api/hooks/issues/{P}", json=rep, headers={"Authorization": "Bearer " + TOK})
check(r.ok and r.json().get("task_id"), f"#2381: Authorization: Bearer takes the report {r.status_code} {r.text[:160]}")
r = requests.post(B + f"/api/hooks/issues/{P}", json={**rep, "fingerprint": "fp-2381-b"}, headers={"X-Kalmido-Token": TOK})
check(r.ok and r.json().get("task_id"), f"#2381: X-Kalmido-Token takes the report {r.status_code} {r.text[:160]}")
r = requests.post(B + f"/api/hooks/issues/{P}/{TOK}", json={**rep, "fingerprint": "fp-2381-c"})
check(r.ok and r.json().get("task_id"), f"#2381: the path form keeps working {r.status_code} {r.text[:160]}")
bad = [requests.post(B + f"/api/hooks/issues/{P}", json=rep, headers=h).status_code
       for h in ({}, {"Authorization": "Bearer wrong-token"}, {"X-Kalmido-Token": ""}, {"Authorization": "Basic " + TOK})]
check(bad == [404] * 4, f"#2381: no / a wrong / an empty token, another scheme: 404 {bad}")
FP = FR.post(B + "/api/lists", json={"name": "Frida app", "kind": "project"}).json()["id"]
fj = FR.patch(B + f"/api/lists/{FP}/error-hook", json={"state": "on"}).json()
r = requests.post(B + f"/api/hooks/issues/{FP}", json=rep, headers={"Authorization": "Bearer " + fj.get("token", "")})
check(r.ok and r.json().get("task_id"), f"#2381: a person without an organisation: the header form {r.status_code} {r.text[:160]}")
rc, out, err_ = py("import logging, sys\nimport kalmido\nfrom kalmido.core.config import app\n"
                   "h = logging.StreamHandler(sys.stdout)\napp.logger.addHandler(h)\nlogging.getLogger('waitress').addHandler(h)\n"
                   "app.logger.error('Exception on /api/hooks/issues/7/SECRETPROBE123 [POST]')\n"
                   "logging.getLogger('waitress').error('Exception while serving %s', '/api/hooks/deploy/3/SECRETPROBE456')\n")
check(rc == 0 and "SECRETPROBE" not in out + err_ and "/api/hooks/issues/7/***" in out and "/api/hooks/deploy/3/***" in out,
      f"#2381: the app's log masks hook tokens {rc} {out[-300:]} {err_[-300:]}")

# ============================================================ #2382: Paperless token + private index after a new server key
WS = f"u{FR_ID}"
rc, out, err_ = py(f"from kalmido.paperless.ngx import pl_seal_token\nprint(pl_seal_token({WS!r}, 'probe-token-2382'))")
SEALED = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""
check(SEALED.startswith("kenc1:"), f"#2382: setup: a sealed Paperless token {rc} {err_[-200:]}")
dbx("INSERT INTO pl_sources(org_id, ws, url, token, created_by, created_at, updated_at) VALUES(NULL,?,?,?,?,?,?)",
    (WS, "https://paperless.example.com", SEALED, FR_ID, "2026-10-20T10:00:00+00:00", "2026-10-20T10:00:00+00:00"))
r = FR.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("zaun.pdf", text_pdf(["Quittenhecke Wartungsvertrag"]), "application/pdf"))])
DOC = r.json()["ids"][0] if r.status_code == 201 else None
until(lambda: DOC and FR.get(B + f"/api/docs/{DOC}").json().get("state") in ("done", "failed"), 90)  # freelancer-matrix: docs


def hits(s, q):
    r = s.get(B + "/api/docs", params={"facets": "0", "ws": "private", "q": q})
    return [d["id"] for d in r.json().get("docs", [])] if r.ok else None


check(DOC and hits(FR, "quittenhecke") == [DOC], f"#2382: setup: the private document is found by a word {r.status_code} {r.text[:150]}")
c0 = FR.get(B + "/api/paperless", params={"ws": "private"}).json().get("conn") or {}
check(c0.get("token_set") and not c0.get("token_lost"), f"#2382: the token opens with the server key {c0}")
rc, out, err_ = cli("status")
st = status_json(out)
check(st.get("paperless_tokens") == {"ok": 1, "unreadable": 0} and st.get("docs", {}).get("private_index") == "unknown",
      f"#2382: status before: one token that opens, the index never rebuilt {st.get('paperless_tokens')} {st.get('docs')}")

start(KEYS[1], keep=True)  # a new server key
FR = sess("frida")
rc, out, err_ = cli("rewrap-accounts", "--old-key-file", "-", stdin=KEYS[0] + "\n")
check(rc == 0 and "reindex-private" in out and "to enter again: 1" in out and KEYS[0] not in out + err_,
      f"#2382: rewrap-accounts names the next step and the token to enter again {rc} {out[-300:]} {err_[-200:]}")
rc, out, err_ = cli("status")
st = status_json(out)
check(st.get("paperless_tokens") == {"ok": 0, "unreadable": 1}, f"#2382: status: the token no longer opens {st.get('paperless_tokens')}")
c1 = FR.get(B + "/api/paperless", params={"ws": "private"}).json().get("conn") or {}
check(c1.get("token_lost") is True and "enter it again" in (c1.get("error_text") or ""), f"#2382: the settings say to enter it again {c1}")
check(hits(FR, "quittenhecke") == [], f"#2382: the index of the old key finds nothing ({hits(FR, 'quittenhecke')})")
rc, out, err_ = cli("reindex-private")
t = status_json(out)
check(rc == 0 and t.get("indexed", 0) >= 1 and t.get("failed") == 0, f"#2382: reindex-private {rc} {out[-300:]} {err_[-200:]}")
check(hits(FR, "quittenhecke") == [DOC], "#2382: after reindex-private the document is found again")
check(FR.get(B + f"/api/docs/{DOC}").ok, "#2382: the document itself stays")
rc, out, err_ = cli("status")
check(status_json(out).get("docs", {}).get("private_index") == "current", "#2382: status: the index is on the current server key")

print(f"p21383_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
