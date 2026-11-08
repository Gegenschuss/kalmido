#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.674.0 part A API test (#4190): memory of the large exports, the JSON limit, the ZIP plan, the account export.
Invented names and figures only (example.com).
 - JSON bodies: above 10 MB -> 413 with the limit in the text (before the route reads it), below goes through; the routes
   with a larger limit on purpose (core/jsonlimit.py JSON_BIG) all exist and do not answer 413 for 12 MB
 - the large exports share the two places of ABM_BUSY: with both taken (POST /api/test/exports/hold) the DATEV ZIP, the
   GoBD export and the knowledge export answer 429 with a plain text; the checks (?check=1) still answer (they build nothing);
   given back, the DATEV ZIP (EXTF + receipts) and the GoBD ZIP (index.xml + tables, the same counts as the check) come
   whole - for an organisation and for a person without an organisation (the personal office)
 - the knowledge export refuses 413 when its files pass the ZIP limit
 - the ZIP plan (GET /api/files/zip?check=1) stops at the first file over the limit: far fewer statements than the walk
   of the whole tree (before: the whole tree was walked, then refused)
 - the account export reads its tables in keyset pages (admin/acctexport.py umz_paged): with pages of 3 rows every task of
   the person is in data/tasks.json, an ordered query keeps its order
freelancer-matrix: office, files
usage: p2674_a_exports_test.py <datadir>      (a fresh container; P2674A_NOSTART=1 = the server already runs)"""
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, B, H, DATA  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FEAT = "cal,comments,collab,office,clients,docs,files,wiki"
O = "/api/office"
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')
TODAY = testclock.today()
Y = TODAY.year
P = f"?from={Y}-01-01&to={TODAY.isoformat()}"
DX = {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def in_ct(code, timeout=300):
    """Python code inside the server container (the app loaded) -> stdout + stderr."""
    try:
        r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app\n" + code],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    return r.stdout + r.stderr


def last_json(out):
    for ln in reversed(out.strip().splitlines()):
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except ValueError:
                return None
    return None


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def receipt(s, ws, name, amount):
    """A receipt of today: a document (upload) with amount + date and its assignment."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": TODAY.isoformat()}).ok
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": "19", "keep": True})
    assert r.ok, r.text
    return nid


def hold(on):
    r = A.post(B + "/api/test/exports/hold", json={"on": on})
    assert r.ok, r.text
    return r.json()["held"]


def zip_names(r):
    try:
        return zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    except zipfile.BadZipFile:
        return []


def stmts(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else None


if not (os.environ.get("P2674A_NOSTART") or os.environ.get("KMT_NOSTART")):
    # the test containers run with TASKS_MAX_FILE_MB=1 (a request limit of 4 MB, below the JSON limit): here the default 50
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e TASKS_MAX_FILE_MB=50")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A, features=FEAT)  # freelancer-matrix: office, files (the personal office, its own admin)
for s, name in ((A, "Beispiel Film GmbH"), (Fr, "Frida Film")):
    assert s.put(B + O + "/settings", json={"lang": "en", "currency": "EUR", "company_fields": {"name": name, **COMPANY}}).ok
    assert s.put(B + O + "/settings", json={"datev_extf": DX}).ok
RA = receipt(A, f"org:{ORG}", "alpha.pdf", "119.00")
RF = receipt(Fr, "private", "frida.pdf", "238.00")

# ---------------------------------------------------------------- the JSON limit
MB = 1024 * 1024
lim = last_json(in_ct("from kalmido.core.config import app\nfrom kalmido.core.jsonlimit import jl_cap\nimport json\n"
                      "print(json.dumps({'app': app.config['MAX_CONTENT_LENGTH'], 'plain': jl_cap('POST', '/api/tasks'), "
                      "'v1': jl_cap('POST', '/api/v1/files')}))")) or {}
APP, PLAIN, V1 = lim.get("app") or 0, lim.get("plain") or 0, lim.get("v1") or 0
check(APP and PLAIN == min(10 * MB, APP) and V1 == min(28 * MB, APP), f"the limits: 10 MB for JSON, 28 MB for /api/v1/files, never above the app's {lim}")
big = json.dumps({"title": "Zu gross", "pad": "a" * (PLAIN + MB)})
r = A.post(B + "/api/tasks", data=big, headers={"Content-Type": "application/json"})
check(r.status_code == 413 and f"{PLAIN // MB} MB" in (r.json().get("error") or ""), f"JSON above the limit: 413 with the limit ({r.status_code} {r.text[:160]})")
ok = json.dumps({"title": "Knapp drunter", "pad": "a" * (PLAIN - MB)})
r = A.post(B + "/api/tasks", data=ok, headers={"Content-Type": "application/json"})
check(r.status_code != 413 and r.ok, f"JSON below the limit still goes through ({r.status_code} {r.text[:160]})")
r = Fr.post(B + "/api/tasks", data=big, headers={"Content-Type": "application/json"})
check(r.status_code == 413, f"a person without an organisation: the same limit ({r.status_code})")
if V1 > PLAIN + MB:
    r = requests.post(B + "/api/v1/files", data=json.dumps({"name": "x.txt", "content": "a" * (PLAIN + MB // 2)}),
                      headers={"Content-Type": "application/json", "Authorization": "Bearer kal_invalid"})
    check(r.status_code != 413, f"POST /api/v1/files keeps its larger JSON limit (no 413 above 10 MB: {r.status_code})")
else:
    print(f"note: the request limit of this container ({APP // MB} MB) leaves no room above the JSON limit; the larger limit is checked by its value")
out = in_ct("from kalmido.core.config import app\nfrom kalmido.core.jsonlimit import JSON_BIG\nimport json\n"
            "have = {(m, r.rule) for r in app.url_map.iter_rules() for m in r.methods}\n"
            "print(json.dumps({'missing': sorted(' '.join(k) for k in JSON_BIG if k not in have), 'n': len(JSON_BIG)}))")
j = last_json(out) or {}
check(j.get("n", 0) >= 5 and j.get("missing") == [], f"every route of JSON_BIG exists ({j or out[-300:]})")

# ---------------------------------------------------------------- the shared places of the large exports
check(hold(True) == 2, "test switch: both places taken")
for who, s in (("organisation", A), ("person without an organisation", Fr)):
    r = s.get(B + O + "/datev/zip" + P)
    check(r.status_code == 429 and "export" in (r.json().get("error") or "").lower(), f"{who}: DATEV ZIP while both places are taken -> 429 ({r.status_code} {r.text[:160]})")
    r = s.get(B + O + "/gobd/export" + P)
    check(r.status_code == 429, f"{who}: GoBD export while both places are taken -> 429 ({r.status_code} {r.text[:160]})")
    r = s.get(B + O + "/datev/zip" + P + "&check=1")
    check(r.ok and r.json().get("files") == 1, f"{who}: the DATEV check needs no place ({r.status_code} {r.text[:160]})")
    r = s.get(B + O + "/gobd/export" + P + "&check=1")
    check(r.ok and r.json().get("counts", {}).get("receipts.csv") == 1, f"{who}: the GoBD check needs no place ({r.status_code} {r.text[:200]})")
assert Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Notizen", "body": "Hallo"}).ok
r = Fr.get(B + "/api/wiki/export?space=private")
check(r.status_code == 429, f"knowledge export while both places are taken -> 429 ({r.status_code} {r.text[:160]})")
check(hold(False) == 0, "test switch: the places given back")

for who, s, rid in (("organisation", A, RA), ("person without an organisation", Fr, RF)):
    r = s.get(B + O + "/datev/zip" + P)
    names = zip_names(r)
    check(r.ok and "no-store" in r.headers.get("Cache-Control", "") and any(n.startswith("EXTF_") for n in names)
          and any(n.startswith("Belege_") for n in names), f"{who}: the DATEV ZIP comes whole ({r.status_code} {names})")
    inner = []
    if r.ok:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        be = next((n for n in names if n.startswith("Belege_")), None)
        inner = zipfile.ZipFile(io.BytesIO(z.read(be))).namelist() if be else []
    check("document.xml" in inner and len(inner) == 2, f"{who}: the receipts archive: document.xml + the one receipt ({inner})")
    ch = s.get(B + O + "/gobd/export" + P + "&check=1").json().get("counts", {})
    r = s.get(B + O + "/gobd/export" + P)
    names = zip_names(r)
    check(r.ok and "no-store" in r.headers.get("Cache-Control", "") and "index.xml" in names and "bookings.csv" in names,
          f"{who}: the GoBD ZIP comes whole ({r.status_code} {names})")
    if r.ok:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        got = {n: z.read(n).decode("utf-8").count("\r\n") for n in names if n.endswith(".csv")}
        check(got == ch, f"{who}: the GoBD tables hold as many lines as the check counts ({got} / {ch})")
        rc = z.read("receipts.csv").decode("utf-8")
        check(rc.startswith(f'{rid};') and "\r\n" in rc, f"{who}: the receipt line is written whole ({rc[:80]!r})")
r = Fr.get(B + "/api/wiki/export?space=private")
check(r.ok and "Notizen.md" in zip_names(r), f"knowledge export with a free place ({r.status_code} {zip_names(r)})")

# ---------------------------------------------------------------- the knowledge export: the size limit of its files
pid = sql("SELECT id FROM wiki_pages WHERE owner_id=? AND org_id IS NULL AND path='Notizen'", (FID,))[0][0]
r = Fr.post(B + f"/api/wiki/pages/{pid}/files", files={"file": ("plan.pdf", tiny_pdf("Plan"), "application/pdf")})
check(r.status_code == 201, "a file on the page " + r.text[:160])
sql("UPDATE wiki_files SET size=? WHERE page_id=?", (5 * 1024 ** 4, pid), write=True)  # far above any ZIP limit
r = Fr.get(B + "/api/wiki/export?space=private")
check(r.status_code == 413, f"knowledge export above the ZIP limit -> 413 ({r.status_code} {r.text[:160]})")
sql("UPDATE wiki_files SET size=? WHERE page_id=?", (1000, pid), write=True)
check(Fr.get(B + "/api/wiki/export?space=private").ok, "knowledge export back within the limit")

# ---------------------------------------------------------------- the ZIP plan stops at the first file too many
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.post(B + "/api/files/folders", json={"name": "Gross"})
assert r.status_code == 201, r.text
TOP = r.json()["id"]
r = A.post(B + "/api/files/folders", json={"name": "a-erst", "parent_id": TOP})
assert r.status_code == 201, r.text
FIRST = r.json()["id"]
r = A.post(B + "/api/files/upload", data={"parent_id": str(FIRST)}, files={"file": ("x.txt", b"Inhalt")})
assert r.status_code == 201, r.text
XF = r.json()["items"][0]["id"]
for i in range(30):
    assert A.post(B + "/api/files/folders", json={"name": f"b{i:02d}", "parent_id": TOP}).status_code == 201
r = A.get(B + f"/api/files/zip?ids={TOP}&check=1")
n_all = stmts(r)
check(r.ok and r.json().get("files") == 1 and n_all, f"the check walks the whole tree ({r.status_code} {r.text[:120]}, n={n_all})")
sql("UPDATE fs_nodes SET size=? WHERE id=?", (5 * 1024 ** 4, XF), write=True)
r = A.get(B + f"/api/files/zip?ids={TOP}&check=1")
n_stop = stmts(r)
check(r.status_code == 413, f"one file above the size limit -> 413 ({r.status_code} {r.text[:120]})")
check(n_all and n_stop is not None and n_stop + 20 < n_all, f"the plan stops at the first file too many: {n_stop} statements, the whole walk {n_all}")
sql("UPDATE fs_nodes SET size=? WHERE id=?", (6, XF), write=True)

# ---------------------------------------------------------------- the account export in keyset pages
for i in range(8):
    assert Fr.post(B + "/api/tasks", json={"title": f"Aufgabe {i}"}).ok
want = sorted(x[0] for x in sql("SELECT id FROM tasks WHERE list_id IN (SELECT id FROM lists WHERE owner_id=?)", (FID,)))
code = f"""import io, json, zipfile
from kalmido.core.db import connect
from kalmido.admin import acctexport as ax
c = connect()
ax.umz_user_conn(c, {FID})
ax.UMZ_PAGE = 3
paged = [0]
orig = c.execute
def ex(q, args=None):
    if "_umz WHERE id>?" in q:
        paged[0] += 1
    return orig(q, args)
c.execute = ex
buf = io.BytesIO()
ax.umz_build(c, {FID}, buf, "t2674")
z = zipfile.ZipFile(buf)
tasks = json.loads(z.read("data/tasks.json"))
ordered = [r[0] for r in ax.umz_paged(c, "SELECT id FROM tasks WHERE list_id IN (SELECT id FROM lists WHERE owner_id=?) ORDER BY id DESC", ({FID},))]
c.rollback()
print(json.dumps({{"tasks": sorted(r["id"] for r in tasks), "paged": paged[0], "ordered": ordered}}))
"""
j = last_json(in_ct(code)) or {}
check(len(want) >= 8 and j.get("tasks") == want, f"account export: every task over several pages ({len(j.get('tasks') or [])} of {len(want)})")
check((j.get("paged") or 0) >= 2, f"account export: the tables are read in further pages ({j.get('paged')})")
check(j.get("ordered") == sorted(want, reverse=True), "account export: a query with its own order keeps it")

print(f"p2674_a_exports: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
