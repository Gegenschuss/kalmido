#!/usr/bin/env python3
"""2.139.0 C API tests (#2386, own container, org encryption on, knowledge page texts sealed at rest):
 - search: a page whose key is missing is found by its name only and marked 'x:' (not read again at every search); once the
   key is back the next search reads it again and finds its text
 - the message of an unreadable page names the way out (organisation: the recovery key; private space: the server key) and
   that it can only be deleted; save / rename stay refused, deleting works
 - import: a page of the same name that cannot be read is skipped by name (never overwritten), the rest is imported; the page
   "Imported files" that cannot be read skips the files for it and is named
 - browser lock (encrypting): an unreadable page no longer stops the switch -- it is skipped and named in todo, the rest is
   converted, finish works; the page stays unreadable (409) afterwards
 - a person without an organisation (freelancer-matrix: wiki): the private variant of the message, search after the key is back
usage: p2139_c_api_test.py <datadir>      (P2139C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import io
import json
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
KEY = base64.b64encode(os.urandom(32)).decode()
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        if write:
            c.execute(q, args)
            c.commit()
            return None
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def setting(k, v):
    sql("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT (key) DO UPDATE SET value=excluded.value", (k, v), write=True)


def page(s, space, path, body=""):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def raw(pid):
    return sql("SELECT body FROM wiki_pages WHERE id=?", (pid,))[0][0]


def marks(pid):
    return sorted(h for (h,) in sql("SELECT h FROM wiki_words WHERE page_id=? AND (h LIKE 'u:%' OR h LIKE 'x:%')", (pid,)))


def found(s, space, q):
    r = s.get(B + "/api/wiki/search", params={"space": space, "q": q})
    assert r.ok, r.text
    return [p["id"] for p in r.json().get("pages", [])]


def key_take(table, col, sid):
    """The key row of a space goes (saved): its sealed texts can no longer be opened."""
    cols = [r[0] for r in sql("SELECT column_name FROM information_schema.columns WHERE table_name=? ORDER BY ordinal_position", (table,))]
    row = sql(f"SELECT {', '.join(cols)} FROM {table} WHERE {col}=?", (sid,))
    assert row, (table, sid)
    sql(f"DELETE FROM {table} WHERE {col}=?", (sid,), write=True)
    return cols, list(row[0])


def key_back(table, col, saved):
    """The saved key row is back (as after a restore with the recovery key); a key made meanwhile is replaced."""
    cols, vals = saved
    sid = vals[cols.index(col)]
    sql(f"DELETE FROM {table} WHERE {col}=?", (sid,), write=True)
    sql(f"INSERT INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", vals, write=True)


def zip_of(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


def imp(s, space, raw_zip, **params):
    return s.post(B + "/api/wiki/import", params={"space": space, **params}, files={"file": ("export.zip", raw_zip, "application/zip")})


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def ct(gen=1, n=48):
    """A ciphertext of a space with the lock (shape only)."""
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(n)}, separators=(",", ":"))


if os.environ.get("P2139C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
setting("wiki_encrypt", "1")

# ---------------------------------------------------------------- search: the key goes and comes back
ORG = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE}).json()["id"]
SP = f"org:{ORG}"
lost = page(A, SP, "Lost/Page", "Kumquat secret words")
check(raw(lost).startswith("kenc1:") and "Kumquat" not in raw(lost), "setup: the page text is sealed at rest")
sealed = raw(lost)
check(found(A, SP, "Kumquat") == [lost], "setup: the text is found while the key is there")
saved = key_take("org_keys", "org_id", ORG)
sql("DELETE FROM wiki_words WHERE page_id=?", (lost,), write=True)  # its index is built again (as after a change elsewhere)
check(found(A, SP, "Kumquat") == [], "key missing: the text is not found")
check(found(A, SP, "Lost") == [lost], "key missing: the page is found by its name")
m1 = marks(lost)
check(len(m1) == 1 and m1[0].startswith("x:"), f"key missing: the page is marked unreadable (x:), not done (u:) {m1}")
found(A, SP, "Lost")
check(marks(lost) == m1, "another search with the same key state does not read it again (same mark)")
key_back("org_keys", "org_id", saved)
check(found(A, SP, "Kumquat") == [lost], "key back: the next search reads the page again and finds its text")
m2 = marks(lost)
check(len(m2) == 1 and m2[0].startswith("u:"), f"key back: the page is indexed (u:) {m2}")

# ---------------------------------------------------------------- the message names the way out
saved = key_take("org_keys", "org_id", ORG)
r = A.get(B + f"/api/wiki/pages/{lost}")
e = r.json().get("error", "") if r.status_code == 409 else ""
check(r.status_code == 409 and r.json().get("code") == "wiki_unreadable" and "kenc1:" not in r.text, f"unreadable: 409 wiki_unreadable {r.status_code} {r.text[:200]}")
check("recovery key" in e and "organisation" in e and "only be deleted" in e, "the message names the recovery key and deleting: " + e)
r = A.patch(B + f"/api/wiki/pages/{lost}", json={"body": "overwritten"})
check(r.status_code == 409 and r.json().get("code") == "wiki_unreadable" and "only be deleted" in r.json().get("error", "") and raw(lost) == sealed,
      f"a save is refused with the same message, the text stays {r.status_code} {r.text[:200]}")
r = A.patch(B + f"/api/wiki/pages/{lost}", json={"path": "Lost/Renamed"})
check(r.status_code == 409 and r.json().get("code") == "wiki_unreadable", f"a rename is refused {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- import: the unreadable page is skipped, the rest comes in
r = imp(A, SP, zip_of({"Lost/Page.md": "replaced text", "Fresh.md": "Fresh text"}), replace="1")
j = r.json() if r.ok else {}
why = {x["name"]: x["reason"] for x in j.get("skipped_detail", [])}
check(r.ok and len(j.get("created", [])) == 1 and "Lost/Page.md" in why and "cannot be read" in why["Lost/Page.md"],
      f"import: the unreadable page is skipped by name, the new one created {r.status_code} {r.text[:300]}")
check(raw(lost) == sealed, "import: the unreadable page is not overwritten")
check(lost not in j.get("updated", []), "import: the unreadable page is not counted as updated")
# the page "Imported files" (it lists files nobody links) cannot be read: those files are skipped, the page is named
key_back("org_keys", "org_id", saved)
imf = page(A, SP, "Imported files", "an old list")
check(raw(imf).startswith("kenc1:"), "setup: the list page is sealed")
saved = key_take("org_keys", "org_id", ORG)
r = imp(A, SP, zip_of({"loose.png": PNG, "Other.md": "Other text"}))
j = r.json() if r.ok else {}
why = {x["name"]: x["reason"] for x in j.get("skipped_detail", [])}
check(r.ok and len(j.get("created", [])) == 1 and "Imported files" in why and "loose.png" in why,
      f"import: the unreadable list page is named, its file skipped, the page imported {r.status_code} {r.text[:400]}")
check(raw(imf).startswith("kenc1:") and len(sql("SELECT 1 FROM wiki_pages WHERE path='Imported files' AND org_id=?", (ORG,))) == 1,
      "import: the unreadable list page stays as it is (no second one)")
r = A.delete(B + f"/api/wiki/pages/{imf}")
check(r.ok, f"an unreadable page can be deleted {r.status_code} {r.text[:200]}")
key_back("org_keys", "org_id", saved)

# ---------------------------------------------------------------- browser lock: an unreadable page is skipped, the rest converted
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Delta", "admin_id": ALICE}).json()["id"]
SP2 = f"org:{ORG2}"
keys = {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
        "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
        "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}
assert A.put(B + "/api/e2e/keys", json=keys).ok
gone = page(A, SP2, "Gone", "Mango unreadable")
fine = page(A, SP2, "Fine", "Apricot readable")
setting("wiki_encrypt", "0")
assert A.patch(B + f"/api/wiki/pages/{fine}", json={"body": "Apricot readable"}).ok  # plain again: readable without the key
check(raw(gone).startswith("kenc1:") and not raw(fine).startswith("kenc1:"), "setup: one sealed page, one plain page")
key_take("org_keys", "org_id", ORG2)
r = A.post(B + "/api/wiki/e2e/start", json={"space": SP2, "keys": [{"user_id": ALICE, "wrapped": {"v": 1, "iv": b64(12), "ct": b64(48)}}]})
check(r.ok and r.json().get("mode") == "encrypting", f"browser lock: started {r.status_code} {r.text[:200]}")
gen = r.json().get("gen", 1) if r.ok else 1
r = A.get(B + "/api/wiki/e2e/todo", params={"space": SP2})
td = r.json() if r.ok else {}
pg = {p["id"]: p for p in td.get("pages", [])}
sk = {x["id"]: x["path"] for x in (td.get("left") or {}).get("skipped", [])}
check(r.ok and set(pg) == {gone, fine} and pg[gone]["body"] is None and pg[gone]["path"] == "Gone" and pg[fine]["body"] == "Apricot readable",
      f"todo does not fail: the unreadable page comes without its text, the rest whole {r.status_code} {r.text[:300]}")
check(sk == {gone: "Gone"}, f"todo names the skipped page {sk}")
r = A.post(B + "/api/wiki/e2e/bulk", json={"space": SP2, "pages": [{"id": gone, "path": ct(gen)}, {"id": fine, "path": ct(gen), "body": ct(gen)}]})
check(r.ok and r.json().get("left", {}).get("pages") == 0, f"after the bulk nothing countable is left (the unreadable text does not count) {r.status_code} {r.text[:200]}")
r = A.get(B + "/api/wiki/e2e/todo", params={"space": SP2})
td = r.json() if r.ok else {}
check(r.ok and td.get("pages") == [] and [x["id"] for x in td["left"].get("skipped", [])] == [gone],
      f"todo again: no page to convert, the skipped one still named {r.text[:300]}")
r = A.post(B + "/api/wiki/e2e/finish", json={"space": SP2})
check(r.ok and r.json().get("mode") == "on", f"finish works with the unreadable page skipped {r.status_code} {r.text[:200]}")
r = A.get(B + f"/api/wiki/pages/{gone}")
check(r.status_code == 409 and r.json().get("code") == "wiki_unreadable", f"the skipped page stays unreadable (its text untouched) {r.status_code}")
r = A.get(B + "/api/wiki", params={"space": SP2, "bodies": "1"})
check(r.ok and {p["id"]: p.get("body") for p in r.json().get("pages", [])}.get(gone) == "", f"the page list with texts does not fail {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: wiki)
setting("wiki_encrypt", "1")
FID, Fr = freelancer(B, A, features="cal,comments,collab,wiki")
fp = page(Fr, "private", "Diary", "Papaya private notes")
check(raw(fp).startswith("kenc1:"), "freelancer: the private page text is sealed (setup)")
fsaved = key_take("user_keys", "user_id", FID)
sql("DELETE FROM wiki_words WHERE page_id=?", (fp,), write=True)
r = Fr.get(B + f"/api/wiki/pages/{fp}")
e = r.json().get("error", "") if r.status_code == 409 else ""
check(r.status_code == 409 and r.json().get("code") == "wiki_unreadable" and "server key" in e and "only be deleted" in e and "organisation" not in e,
      f"freelancer: the private variant of the message {r.status_code} {e}")
check(found(Fr, "private", "Papaya") == [] and found(Fr, "private", "Diary") == [fp], "freelancer: key missing = found by name only")
key_back("user_keys", "user_id", fsaved)
check(found(Fr, "private", "Papaya") == [fp], "freelancer: key back = the text is found again")
r = Fr.get(B + f"/api/wiki/pages/{fp}")
check(r.ok and r.json().get("body") == "Papaya private notes", f"freelancer: the page reads again {r.status_code}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
