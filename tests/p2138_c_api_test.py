#!/usr/bin/env python3
"""2.138.0 API tests, part C: the upload token and the calendar feed secret kept only as hashes (#1907), the recovery key
of an organisation wraps its key, key renewal on the command line, step-up + News when it is shown (#1972). One container
(start.sh) with KALMIDO_SECRET_KEY; invented names, companies and the test IBAN only.
#1907 (part_a):
 - tokens from before (plain in users.drop_token / ical_token): the start-up step turns them into hashes, the old
   shortcut and the old subscription keep working, no plain value stays in the database; the step is idempotent
 - a new upload token is in the answer of POST /api/me/drop-token once; /api/me and /api/state only say whether one is
   set (+ since when), the database holds only the hash; a new one ends the old one at once
 - the HTTP Shortcuts download carries a new token each time (the old one stops), refused cross-site and for a child
 - calendar feed: create / rotate answer the link once, GET /api/ical and a second create only {active, created_at};
   rotate: old link 404 at once; off: inactive; a wrong secret 404, someone else's id 404
 - child accounts: no token at creation, cannot create one, /drop refuses a child's hash
 - exports: /api/export.json carries neither token nor hash; the export filter drops the hash columns
 - a person without an organisation (freelancer-matrix: share-drop, calendar-feed): drop + feed work the same
#1972 (after part_a):
 - showing: "R2-" + 13 groups, the same key again on the next showing, "new" makes another one (the first one stops
   working for rewrap); wrong password 403, member 403, other organisation 404; office log entry + News for the other
   admins (not for the one who showed it, not for members), never with the value
 - step-up: an admin with the authenticator app needs the code too (none / wrong 403, right 200); an account without a
   password needs a fresh sign-in (old session 403)
 - rewrap (new server key): the current recovery key restores the data, an earlier one does not; the earlier format (the
   raw organisation key, as 2.125 and older showed it) still works until the key is rotated
 - rotate: aborted after the key switch the server still reads everything (fields + sealed file), the recovery key 409;
   the next run finishes: values / file re-encrypted with the new key, the earlier key and recovery keys no longer open
   anything, a new recovery key on stdout, News "rotated" for the admins; recovery --recovery-out writes a 0600 file
 - a person without an organisation (freelancer-matrix: orgcrypt) reaches the recovery key of the own personal office
   (organisation id 0 in the route), a person without a personal office gets 404
usage: p2138_c_api_test.py <datadir>      (P2138C_NOSTART=1 = the server already runs with a KALMIDO_SECRET_KEY)"""
import base64
import hashlib
import hmac
import io
import json
import os
import struct
import subprocess
import sys
import time
import zipfile

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEYS = [base64.b64encode(os.urandom(32)).decode() for _ in range(4)]
TEST_IBAN = "DE89370400440532013000"
O = "/api/office"
FAILS, OKS = [], [0]
PUB = "https://kalmido.example"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(key, keep=False):
    if os.environ.get("P2138C_NOSTART") == "1" and not keep:
        return
    extra = ["-e KALMIDO_INSTANCE_MODE=workspaces", "-e KALMIDO_ORGCRYPT_DELAY=0", "-e KALMIDO_SECRET_KEY=" + key]
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra), **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def cli(*args, stdin=None, env=()):
    e = [x for k in env for x in ("-e", k)]
    r = subprocess.run(["docker", "exec", "-i", *e, CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args], input=stdin,
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout, r.stderr


def py(code):
    """2.138.0 C (#1972): a few lines of Python inside the container (the server's modules, its server key)."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


def text_pdf(lines):
    """2.138.0 C (#1972): a one-page PDF with a text layer (as p248_b_api_test.py)."""
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


def doc_hits(s, q):
    r = s.get(B + "/api/docs", params={"facets": "0", "ws": f"org:{ORG}", "q": q})
    return [d["id"] for d in r.json()["docs"]] if r.ok else None


def totp(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    o = mac[-1] & 15
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def raw_org_key(master_b64, oid):
    """The organisation key as 2.125 and older showed it (13 groups of base32), unwrapped here with the server key the test set."""
    kek = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-orgkey-kek-v1").derive(base64.b64decode(master_b64))
    w = one("SELECT wrapped FROM org_keys WHERE org_id=?", (oid,))
    raw = base64.urlsafe_b64decode(w[3:] + "=" * (-len(w[3:]) % 4))
    k = AESGCM(kek).decrypt(raw[:12], raw[12:], b"kalmido-orgkey|%d" % oid)
    s = base64.b32encode(k).decode().rstrip("=")
    return "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def show(s, oid, **b):
    return s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123", **b})


def news(s, kind="orgkey"):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x["kind"] == kind]


def iban(s):
    return (s.get(B + O + "/settings").json().get("company_fields") or {}).get("iban")


def sha(t):
    return hashlib.sha256(t.encode()).hexdigest()


def drop(tok, text):
    return requests.post(B + "/drop", headers={"Authorization": "Bearer " + tok}, data={"text": text})


def feed(url):
    return requests.get(B + url.replace(PUB, ""))


def in_app(code):
    """Runs code in the app container (the start-up step on its own, without a restart)."""
    return subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)


MIGRATE = ("import app\nfrom kalmido.core.pg import system_ctx\nfrom kalmido.core.tokenhash import tkh_migrate\nc = app.connect()\n"
           "with system_ctx(c):\n    n = tkh_migrate(c)\nc.commit()\nprint(n)")



def part_a(A):
    """#1907: upload token + calendar feed secret as hashes (alice, bob, the child kimi, the freelancer frida)."""
    A.post(B + "/api/admin/setup", json={"org_name": "Delta", "lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
    A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
    ids = {"alice": A.get(B + "/api/me").json()["id"]}
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123",
                                       "email": "bob@example.com"})
    assert r.ok, r.text
    ids["bob"] = r.json()["id"]
    r = A.post(B + "/api/users", json={"username": "kimi", "display_name": "Kimi", "password": "password123", "kid": True,
                                       "parents": [ids["bob"]]})
    assert r.ok, r.text
    ids["kimi"] = r.json()["id"]
    Bo = sess("bob")

    # ================================================================== new accounts: no token until created
    row = dbx("SELECT drop_token, drop_token_hash, ical_token, ical_token_hash FROM users WHERE id=?", (ids["bob"],))[0]
    check(all(x is None for x in row), f"a new account has no upload token / feed yet {tuple(row)}")
    me = Bo.get(B + "/api/me").json()
    check("drop_token" not in me and me.get("drop_token_set") is False, f"/api/me: no token, drop_token_set false {me.get('drop_token_set')}")

    # ================================================================== tokens from before keep working
    OLD_DROP, OLD_ICAL = "olddrop-" + "a" * 30, "oldical-" + "b" * 40
    dbx("UPDATE users SET drop_token=?, drop_token_hash=NULL, ical_token=?, ical_token_hash=NULL WHERE id=?", (OLD_DROP, OLD_ICAL, ids["alice"]))
    p = in_app(MIGRATE)
    check(p.returncode == 0 and "stored 1 accounts" in p.stdout, f"start-up step converts one account rc={p.returncode} {p.stdout[-80:]!r} {p.stderr[-400:]}")
    row = dbx("SELECT drop_token, drop_token_hash, ical_token, ical_token_hash FROM users WHERE id=?", (ids["alice"],))[0]
    check(row[0] is None and row[2] is None and row[1] == sha(OLD_DROP) and row[3] == sha(OLD_ICAL), f"only the hashes stay {tuple(row)}")
    r = drop(OLD_DROP, "From the old shortcut")
    check(r.ok, f"the old shortcut still works ({r.status_code} {r.text[:80]})")
    check(dbx("SELECT 1 FROM tasks WHERE title='From the old shortcut'"), "old shortcut: the task is there")
    r = feed(f"{PUB}/ical/{ids['alice']}.{OLD_ICAL}.ics")
    check(r.ok and "BEGIN:VCALENDAR" in r.text, f"the old subscription still works ({r.status_code})")
    p = in_app(MIGRATE)
    check(p.returncode == 0 and "stored" not in p.stdout, f"start-up step is idempotent rc={p.returncode} {p.stdout[-80:]!r} {p.stderr[-200:]}")
    check(not dbx("SELECT 1 FROM users WHERE drop_token IS NOT NULL OR ical_token IS NOT NULL"), "no plain token in the database")
    gi = A.get(B + "/api/ical").json()
    check(gi.get("url") is None and gi.get("active") is True, f"GET /api/ical: the converted feed is active, no link {gi}")

    # ================================================================== upload token: shown once
    r = A.post(B + "/api/me/drop-token")
    check(r.ok and len(r.json().get("drop_token") or "") >= 24 and r.json().get("drop_token_at"), f"new token in the answer {r.status_code}")
    T1 = r.json()["drop_token"]
    check(tuple(dbx("SELECT drop_token, drop_token_hash FROM users WHERE id=?", (ids["alice"],))[0]) == (None, sha(T1)), "database: only the hash")
    check(drop(OLD_DROP, "old again").status_code in (401, 403, 404), "a new token ends the old one at once")
    check(drop(T1, "With the new token").ok, "the new token works")
    me = A.get(B + "/api/me")
    st = A.get(B + "/api/state")
    check(T1 not in me.text and T1 not in st.text and me.json().get("drop_token_set") is True and me.json().get("drop_token_at"),
          "/api/me and /api/state: only set + since when")
    check(st.json()["me"].get("drop_token_set") is True, "state.me.drop_token_set")
    check(drop(T1[:-1] + ("x" if T1[-1] != "x" else "y"), "wrong").status_code in (401, 403, 404), "a wrong token is refused")
    check(drop("", "empty").status_code in (401, 403, 404), "an empty token is refused")
    check(requests.post(B + "/drop", data={"text": "no header"}).status_code in (401, 403, 404), "no token is refused")

    # ================================================================== HTTP Shortcuts: a new token per download
    r = A.get(B + "/api/me/share/httpshortcuts.zip", headers={"Sec-Fetch-Site": "same-origin"})
    check(r.ok and r.headers.get("Cache-Control") == "no-store", f"zip download {r.status_code}")
    T2 = json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("shortcuts.json"))["categories"][0]["shortcuts"][0]["headers"][0]["value"][7:]
    check(T2 and T2 != T1 and drop(T2, "zip token").ok and drop(T1, "before zip").status_code in (401, 403, 404), "the zip carries a new token, the old one stops")
    check(tuple(dbx("SELECT drop_token, drop_token_hash FROM users WHERE id=?", (ids["alice"],))[0]) == (None, sha(T2)), "zip: database only the hash")
    r = A.get(B + "/api/me/share/httpshortcuts.zip", headers={"Sec-Fetch-Site": "cross-site"})
    check(r.status_code == 403 and drop(T2, "still").ok, f"zip refused cross-site, token unchanged ({r.status_code})")
    # 2.138.0 C (#1907): a browser without Sec-Fetch-Site: only with this host in Origin / Referer
    for hd, want, what in (({}, 403, "no header"), ({"Referer": "https://evil.example/page"}, 403, "a foreign Referer"),
                           ({"Origin": "https://evil.example"}, 403, "a foreign Origin"), ({"Sec-Fetch-Site": "same-site"}, 403, "same-site")):
        r = A.get(B + "/api/me/share/httpshortcuts.zip", headers=hd)
        check(r.status_code == want and drop(T2, "still " + what).ok, f"zip without Sec-Fetch-Site: {what} -> {want} ({r.status_code})")
    r = A.get(B + "/api/me/share/httpshortcuts.zip", headers={"Referer": B + "/"})
    T2 = json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("shortcuts.json"))["categories"][0]["shortcuts"][0]["headers"][0]["value"][7:] if r.ok else T2
    check(r.ok and drop(T2, "own Referer").ok, f"zip without Sec-Fetch-Site, own Referer: 200 ({r.status_code})")

    # ================================================================== calendar feed: link once
    r = Bo.post(B + "/api/ical", json={"action": "create"}).json()
    U1 = r.get("url") or ""
    check(U1.startswith(f"{PUB}/ical/{ids['bob']}.") and r.get("active") is True and r.get("created_at"), f"create: link once {r}")
    check(feed(U1).ok, "the new link works")
    sec = U1.rsplit("/", 1)[1][:-4].split(".", 1)[1]
    check(tuple(dbx("SELECT ical_token, ical_token_hash FROM users WHERE id=?", (ids["bob"],))[0]) == (None, sha(sec)), "feed: database only the hash")
    r = Bo.post(B + "/api/ical", json={"action": "create"}).json()
    check(r.get("url") is None and r.get("active") is True and feed(U1).ok, f"a second create: no link, the old one keeps working {r}")
    g = Bo.get(B + "/api/ical")
    check(g.json().get("url") is None and sec not in g.text and g.json().get("active") is True, "GET /api/ical: no link")
    check(feed(f"{PUB}/ical/{ids['alice']}.{sec}.ics").status_code == 404, "bob's secret with alice's id: 404")
    check(feed(f"{PUB}/ical/{ids['bob']}.{sec[:-2]}xx.ics").status_code == 404, "a wrong secret: 404")
    U2 = Bo.post(B + "/api/ical", json={"action": "rotate"}).json().get("url") or ""
    check(U2 and U2 != U1 and feed(U1).status_code == 404 and feed(U2).ok, "rotate: old link dead at once, the new one works")
    r = Bo.post(B + "/api/ical", json={"action": "off"}).json()
    check(r.get("active") is False and r.get("url") is None and feed(U2).status_code == 404
          and dbx("SELECT ical_token_hash FROM users WHERE id=?", (ids["bob"],))[0][0] is None, f"off: feed gone {r}")
    check(Bo.post(B + "/api/ical", json={"action": "nope"}).status_code == 400, "unknown action 400")
    check(requests.post(B + "/api/ical", json={"action": "rotate"}, headers=H).status_code in (401, 403), "the feed settings need a login")

    # ================================================================== child accounts
    K = sess("kimi")
    check(dbx("SELECT drop_token_hash FROM users WHERE id=?", (ids["kimi"],))[0][0] is None, "a child account has no token")
    check(K.post(B + "/api/me/drop-token").status_code == 403, "a child cannot create an upload token")
    check(K.get(B + "/api/me/share/httpshortcuts.zip").status_code == 403, "a child gets no HTTP Shortcuts import")
    KT = "kid-" + "c" * 30
    dbx("UPDATE users SET drop_token_hash=? WHERE id=?", (sha(KT), ids["kimi"]))
    check(drop(KT, "kid drop").status_code in (401, 403, 404) and not dbx("SELECT 1 FROM tasks WHERE title='kid drop'"), "/drop refuses a child's token")
    check(K.get(B + "/api/me").json().get("drop_token_set") is False, "/api/me: a child shows no token")

    # ================================================================== exports
    ex = A.get(B + "/api/export.json")
    check(ex.ok and T2 not in ex.text and sha(T2) not in ex.text and "drop_token_hash" not in ex.text and "ical_token_hash" not in ex.text,
          "export.json: neither token nor hash")
    p = in_app("from kalmido.admin.orgexport import OX_SECRET_COLS as S\nprint(int({'drop_token_hash', 'ical_token_hash'} <= S))")
    check(p.stdout.strip().endswith("1"), f"organisation / account export drop the hash columns {p.stdout[-20:]} {p.stderr[-200:]}")

    # ================================================================== freelancer-matrix: share-drop, calendar-feed
    FID, Fr = freelancer(B, A, "frida")
    ft = Fr.post(B + "/api/me/drop-token").json().get("drop_token") or ""
    check(ft and drop(ft, "Freelancer drop").ok, "freelancer: upload token + /drop")
    fl = Fr.post(B + "/api/ical", json={"action": "create"}).json().get("url") or ""
    check(fl and feed(fl).ok and Fr.get(B + "/api/ical").json().get("url") is None, "freelancer: feed link once, works")
    fz = Fr.get(B + "/api/me/share/httpshortcuts.zip", headers={"Sec-Fetch-Site": "same-origin"})
    check(fz.ok and drop(ft, "freelancer old").status_code in (401, 403, 404), "freelancer: zip download replaces the token")



# ---------------------------------------------------------------- set-up
start(KEYS[0])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
part_a(sess("alice"))
A = sess("alice")
ids = {}
for u, n in (("bruno", "Bruno Admin"), ("carol", "Carol Member"), ("dave", "Dave Other"), ("erin", "Erin Single")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da, Er = sess("bruno"), sess("carol"), sess("dave"), sess("erin")
FEAT = "cal,comments,collab,office,clients,time"
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for u, role in (("bruno", "admin"), ("carol", "member"), ("erin", "admin")):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": role}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["dave"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG), (Er, ORG), (Da, ORG2)):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{o}"})
r = A.put(B + O + "/settings", json={"company_fields": {"name": "Studio Nordlicht GmbH", "iban": TEST_IBAN, "bic": "COBADEFFXXX"}})
check(r.ok and iban(A) == TEST_IBAN, "office company with an IBAN " + r.text[:150])
L = A.post(B + "/api/lists", json={"name": "Projekt Nordlicht", "org_id": ORG}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Schnittplan", "list_id": L}).json()["id"]
BODY = b"Schnittplan Version 3\n" * 40
check(A.post(B + f"/api/tasks/{T}/attachments", files={"file": ("plan.txt", BODY, "text/plain")}).ok, "attachment upload")
AID = one("SELECT id FROM attachments WHERE task_id=?", (T,))
APATH = os.path.join(DATA, "attachments", one("SELECT path FROM attachments WHERE id=?", (AID,)))
with open(APATH, "rb") as f:
    check(f.read(6) == b"KENC1\n", "attachment sealed")
ENC0 = one("SELECT iban FROM office_company WHERE org_id=?", (ORG,))
check(str(ENC0).startswith("kenc1:"), "IBAN encrypted at rest")

# ---------------------------------------------------------------- showing, step-up, News
st = A.get(B + f"/api/orgs/{ORG}/encryption").json()
check(st.get("step") == "password" and st.get("recovery") is False and st.get("rotating") in (None, False, ""), f"state before: step password, no recovery copy {st}")
check(show(A, ORG, password="wrong-one").status_code == 403, "wrong password 403")
check(show(Ca, ORG).status_code == 403, "member 403")
check(show(Da, ORG).status_code == 404, "other organisation 404")
r = show(A, ORG)
R1 = r.json().get("recovery_key", "") if r.ok else ""
check(r.ok and R1.startswith("R2-") and len(R1.replace("-", "")) == 54 and R1.count("-") == 13 and r.json().get("new") is False
      and r.headers.get("Cache-Control") == "no-store", f"recovery key: R2- + 13 groups, made on the first showing {r.status_code} {r.text[:120]}")
check(R1.replace("-", "")[2:] != raw_org_key(KEYS[0], ORG).replace("-", ""), "the recovery key is not the organisation key")
r = show(A, ORG)
check(r.ok and r.json().get("recovery_key") == R1 and r.json().get("new") is False, "showing again: the same recovery key")
check(A.get(B + f"/api/orgs/{ORG}/encryption").json().get("recovery") is True, "state: recovery copy present")
nb = news(Bo)
check(nb and nb[0]["data"].get("org_id") == ORG and nb[0]["data"].get("action") == "shown" and nb[0]["actor_id"] == ALICE,
      f"News for the other admin (bruno) {nb[:1]}")
check(not news(A) and not news(Ca), "no News for the one who showed it, none for a member")
blob = json.dumps(dbx("SELECT data FROM notifications")) + json.dumps(dbx("SELECT detail FROM office_doc_log"))
check(R1 not in blob and R1.replace("-", "")[2:] not in blob, "the value is in no News item and no log entry")
check(any(x["action"] == "recovery_key" for x in A.get(B + O + "/log").json()["log"]), "office log entry")
r = show(A, ORG, new=True)
R2 = r.json().get("recovery_key", "") if r.ok else ""
check(r.ok and R2.startswith("R2-") and R2 != R1 and r.json().get("new") is True, "new: another recovery key")
check(any(x["data"].get("action") == "new" for x in news(Bo)), "News: a new recovery key")
# the authenticator app: password + code
r = Bo.post(B + "/api/me/2fa/totp", json={"password": "password123"})
SEC = r.json()["secret"].replace(" ", "")
step0 = int(time.time() // 30)
assert Bo.post(B + "/api/me/2fa/totp/confirm", json={"code": totp(SEC, step0)}).ok
check(Bo.get(B + f"/api/orgs/{ORG}/encryption").json().get("step") == "totp", "state: step totp")
r = show(Bo, ORG)
check(r.status_code == 403 and r.json().get("need") == "totp" and "recovery_key" not in r.json(), "with the app set up: password alone 403 (need totp)")
check(show(Bo, ORG, code="000000").status_code == 403, "wrong code 403")
r = show(Bo, ORG, code=totp(SEC, step0 + 1))
check(r.ok and r.json().get("recovery_key") == R2, "password + code: 200, the current key " + r.text[:120])
# an account without a password (single sign-on): only with a fresh sign-in
dbx("UPDATE users SET password_hash=NULL WHERE id=?", (ids["erin"],))
check(Er.get(B + f"/api/orgs/{ORG}/encryption").json().get("step") == "fresh", "no password: step fresh")
r = Er.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={})
check(r.ok and r.json().get("recovery_key") == R2, "no password, fresh sign-in: 200 " + r.text[:120])
dbx("UPDATE sessions SET created_at='2020-01-01T00:00:00Z' WHERE user_id=?", (ids["erin"],))
r = Er.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={})
check(r.status_code == 403 and r.json().get("need") == "fresh", "no password, old sign-in: 403 (sign in again) " + r.text[:120])

# ---------------------------------------------------------------- a new server key: rewrap with the recovery key
start(KEYS[1], keep=True)
A = sess("alice")
check(A.get(B + f"/api/orgs/{ORG}/encryption").json().get("key_ok") is False, "new server key: key_ok false")
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin=R1 + "\n")
check(rc == 1 and R1 not in out + err_, f"rewrap: the earlier recovery key (replaced by new) is refused {rc} {out[-200:]}")
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin=R2.lower().replace("-", " ") + "\n")
check(rc == 0 and "stored with the current server key" in out and R2 not in out + err_, f"rewrap with the current recovery key {rc} {out[-200:]} {err_[-200:]}")
check(iban(A) == TEST_IBAN and A.get(B + f"/api/attachments/{AID}").content == BODY, "after rewrap: field + file readable")
r = show(A, ORG)
check(r.ok and r.json().get("recovery_key") == R2 and r.json().get("new") is False, "after rewrap: the same recovery key can be shown again")
# the earlier format (2.125 and older showed the organisation key itself) works until the key is rotated
LEGACY = raw_org_key(KEYS[1], ORG)
start(KEYS[2], keep=True)
A = sess("alice")
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin=LEGACY + "\n")
check(rc == 0 and "stored with the current server key" in out, f"rewrap with a recovery key of the earlier format {rc} {out[-200:]}")
check(iban(A) == TEST_IBAN, "after rewrap (earlier format): readable")
# 2.138.0 C (#1972): the stored copy of R lay under the earlier server key - it goes, R is never replaced silently
RW2 = one("SELECT recovery_wrapped FROM org_keys WHERE org_id=?", (ORG,))
check(RW2 and one("SELECT recovery_secret FROM org_keys WHERE org_id=?", (ORG,)) is None, "rewrap (earlier format): the stale copy of R dropped")
check(A.get(B + f"/api/orgs/{ORG}/encryption").json().get("recovery_stale") is True, "state: recovery_stale")
r = show(A, ORG)
check(r.status_code == 409 and "recovery_key" not in r.text, f"showing a recovery key that cannot be opened: 409 {r.status_code} {r.text[:120]}")
rc, out, err_ = py("from kalmido.core.db import connect\nfrom kalmido.core import orgcrypt as oc\nc = connect()\n"
                   f"w = oc.rck_wrapped(c, {ORG})\nc.commit()\nprint('same' if w == oc.rck_row(c, {ORG})['recovery_wrapped'] else 'other')")
check(out.strip().endswith("same") and one("SELECT recovery_wrapped FROM org_keys WHERE org_id=?", (ORG,)) == RW2,
      f"export header: the existing recovery_wrapped, no new one {rc} {out[-200:]} {err_[-300:]}")
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin=R2 + "\n")
check(rc == 0 and "already usable" in out, f"the recovery key in the safe still opens the key {rc} {out[-200:]} {err_[-200:]}")
r = show(A, ORG)
check(r.ok and r.json().get("recovery_key") == R2 and A.get(B + f"/api/orgs/{ORG}/encryption").json().get("recovery_stale") is False,
      "after rewrap with it: the same recovery key shown again " + r.text[:120])
r = show(A, ORG, new=True)
R3 = r.json().get("recovery_key", "") if r.ok else ""
check(r.ok and R3.startswith("R2-") and R3 != R2 and r.json().get("new") is True, "a new one only when asked " + r.text[:120])

# 2.138.0 C (#1972): a document of the organisation, found by its words (the index is keyed with the org key)
r = A.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files=[("files", ("zaun.pdf", text_pdf(["Zaunkoenigweg Wartungsvertrag"]), "application/pdf"))])
DOC = r.json()["ids"][0] if r.status_code == 201 else None
for _ in range(90):
    if DOC and A.get(B + f"/api/docs/{DOC}").json().get("state") in ("done", "failed"):
        break
    time.sleep(1)
check(DOC and doc_hits(A, "zaunkoenigweg") == [DOC], f"document of the organisation found by a word before the rotation {r.status_code} {r.text[:150]}")
DW0 = {x[0] for x in dbx("SELECT h FROM doc_words WHERE node_id=?", (DOC,))}

# ---------------------------------------------------------------- rotate: aborted after the switch, then finished
WR0 = one("SELECT wrapped FROM org_keys WHERE org_id=?", (ORG,))
rc, out, err_ = cli("rotate", "--org", str(ORG), env=("KALMIDO_TEST_ROT_ABORT=1", "KALMIDO_ORGCRYPT_ROT_SETTLE=0"))
check(rc == 1 and "not finished" in out and "R2-" not in out, f"rotate aborted after the key switch {rc} {out[-300:]} {err_[-300:]}")
check(one("SELECT wrapped_rot FROM org_keys WHERE org_id=?", (ORG,)) == WR0 and one("SELECT wrapped FROM org_keys WHERE org_id=?", (ORG,)) != WR0,
      "during the rotation: the earlier key kept in wrapped_rot")
check(one("SELECT iban FROM office_company WHERE org_id=?", (ORG,)) == ENC0, "nothing re-encrypted yet")
check(iban(A) == TEST_IBAN and A.get(B + f"/api/attachments/{AID}").content == BODY, "during the rotation the server reads field + file (falls back to the earlier key)")
check(A.get(B + f"/api/orgs/{ORG}/encryption").json().get("rotating"), "state: rotating")
check(show(A, ORG).status_code == 409, "recovery key while the rotation runs: 409")
# a value written during the rotation is sealed with the new key and stays readable
A.put(B + O + "/settings", json={"company_fields": {"name": "Studio Nordlicht GmbH", "iban": TEST_IBAN, "bic": "DEUTDEFFXXX"}})
ENC1 = one("SELECT iban FROM office_company WHERE org_id=?", (ORG,))
rc, out, err_ = cli("rotate", "--org", str(ORG), env=("KALMIDO_ORGCRYPT_ROT_SETTLE=0",))
lines = [x.strip() for x in out.splitlines() if x.strip().startswith("R2-")]
RN = lines[0] if lines else ""
check(rc == 0 and RN and RN not in err_, f"rotate finished, the new recovery key on stdout {rc} {out[-300:]} {err_[-2500:]}")
check(one("SELECT wrapped_rot FROM org_keys WHERE org_id=?", (ORG,)) is None and one("SELECT rotated_at FROM org_keys WHERE org_id=?", (ORG,))
      and one("SELECT wrapped_prev FROM org_keys WHERE org_id=?", (ORG,)) is None, "after the rotation: earlier key gone, rotated_at noted")
check(one("SELECT iban FROM office_company WHERE org_id=?", (ORG,)) == ENC1, "a value written during the rotation (new key) is left as it is")
check(str(one("SELECT bic FROM office_company WHERE org_id=?", (ORG,))).startswith("kenc1:") and iban(A) == TEST_IBAN
      and (A.get(B + O + "/settings").json().get("company_fields") or {}).get("bic") == "DEUTDEFFXXX", "after the rotation: fields readable")
check(A.get(B + f"/api/attachments/{AID}").content == BODY, "after the rotation: the sealed file readable")
rot_news = [x for x in news(Bo) if x["data"].get("action") == "rotated"]
check(rot_news and rot_news[0]["to_me"] and [x for x in news(A) if x["data"].get("action") == "rotated"], "News: rotated (all admins)")
r = show(A, ORG)
check(r.ok and r.json().get("recovery_key") == RN, "after the rotation the new recovery key is shown")
DW1 = {x[0] for x in dbx("SELECT h FROM doc_words WHERE node_id=?", (DOC,))}
check(DW1 and not DW1 & DW0 and doc_hits(A, "zaunkoenigweg") == [DOC] and doc_hits(A, "wartungsv") == [DOC],
      f"after the rotation: the word index made with the new key, the document found again ({len(DW0)} / {len(DW1)})")
# 2.138.0 C (#1972): finishing a rotation that no longer runs: an error, no recovery key that is stored nowhere
RWN = one("SELECT recovery_wrapped FROM org_keys WHERE org_id=?", (ORG,))
rc, out, err_ = py("from kalmido.core.db import connect\nfrom kalmido.core import orgcrypt as oc\nc = connect()\ntry:\n"
                   f"    oc.rck_rot_finish(c, {ORG})\n    print('finished')\nexcept oc.OrgCryptError:\n    print('refused')")
check(out.strip().endswith("refused") and one("SELECT recovery_wrapped FROM org_keys WHERE org_id=?", (ORG,)) == RWN,
      f"rck_rot_finish without a running rotation: refused, nothing changed {rc} {out[-200:]} {err_[-300:]}")
# the earlier keys no longer open anything: a new server key, then rewrap
start(KEYS[3], keep=True)
A = sess("alice")
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin=R3 + "\n")
check(rc == 1, f"rewrap: a recovery key from before the rotation is refused {rc} {out[-200:]}")
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin=LEGACY + "\n")
check(rc == 1 and "renewed" in out, f"rewrap: the earlier format is refused after the rotation {rc} {out[-200:]}")
rc, out, err_ = cli("rewrap", "--org", str(ORG), "--recovery-file", "-", stdin=RN + "\n")
check(rc == 0, f"rewrap with the recovery key of the rotation {rc} {out[-200:]} {err_[-200:]}")
check(iban(A) == TEST_IBAN and A.get(B + f"/api/attachments/{AID}").content == BODY, "after rewrap: field + file readable")
# recovery on the command line: into a new 0600 file, never over an existing one
rc, out, err_ = cli("recovery", "--org", str(ORG), "--recovery-out", "/tmp/p2138c-rk.txt")
mode = subprocess.run(["docker", "exec", CT, "stat", "-c", "%a", "/tmp/p2138c-rk.txt"], capture_output=True, text=True).stdout.strip()
check(rc == 0 and mode == "600" and "R2-" not in out, f"recovery --recovery-out: file 0600, nothing on stdout {rc} {mode} {out[-200:]}")
rc, out, err_ = cli("recovery", "--org", str(ORG), "--recovery-out", "/tmp/p2138c-rk.txt")
check(rc == 2, "recovery --recovery-out: an existing file is never overwritten")
subprocess.run(["docker", "exec", CT, "rm", "-f", "/tmp/p2138c-rk.txt"], capture_output=True)
rc, out, err_ = cli("status")
check(rc == 0 and '"rotated_at"' in out and "R2-" not in out, "status names rotated_at, no key")

# ---------------------------------------------------------------- the personal office of a person without an organisation
# freelancer-matrix: orgcrypt
FID, Fr = freelancer(B, A, "fanny")
check(Fr.get(B + "/api/orgs/0/encryption").status_code == 404, "freelancer without a personal office: 404")
r = Fr.put(B + O + "/settings", json={"company_fields": {"name": "Frida Film", "iban": TEST_IBAN}})
check(r.ok, "freelancer: personal office with an IBAN " + r.text[:150])
POID = one("SELECT id FROM orgs WHERE personal_of=?", (FID,))
check(POID and str(one("SELECT iban FROM office_company WHERE org_id=?", (POID,))).startswith("kenc1:"), "freelancer: IBAN encrypted with the personal office key")
st = Fr.get(B + "/api/orgs/0/encryption").json()
check(st.get("has_key") is True and st.get("step") == "password", f"freelancer: state of the personal office {st}")
check(Fr.post(B + f"/api/orgs/{POID}/encryption/recovery", json={"password": "password123"}).status_code == 404, "freelancer: the hidden id itself 404 (0 = mine)")
r = Fr.post(B + "/api/orgs/0/encryption/recovery", json={"password": "password123"})
FR = r.json().get("recovery_key", "") if r.ok else ""
check(r.ok and FR.startswith("R2-"), "freelancer: recovery key of the personal office " + r.text[:120])
check(Bo.post(B + "/api/orgs/0/encryption/recovery", json={"password": "password123"}).status_code == 404, "someone without a personal office: 404")
rc, out, err_ = cli("rewrap", "--org", str(POID), "--recovery-file", "-", stdin=FR + "\n")
check(rc == 0 and "already usable" in out, f"freelancer: the recovery key fits the personal office key {rc} {out[-200:]}")

print(f"p2138_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
