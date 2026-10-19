#!/usr/bin/env python3
"""2.69.0 API tests, part A (#1846): the Paperless-ngx import on a hosted server, the storage quota, the queue and the import
of an uploaded export ZIP (document_exporter). Against the fake Paperless-ngx of p248_d (fake_paperless.py, 127.0.0.1:8098)
and ZIP files built here. Invented names only, generated file contents.
 - self-hosted unchanged: an internal host on the allow list works; the preview estimates the size (about, from /metadata/)
 - queue: two workspaces import at once -> the second waits (place 1), never two runs at the same time
 - quota: an estimate above the free space warns, the run stops cleanly when the storage is full ("3 of 5"), nothing half;
   full before the start = 413 (URL and ZIP); a ZIP that surely does not fit = 413
 - ZIP: uploaded in parts (sealed, 0600, gone after the run), tags / correspondents / types with counts, the mapping
   (rename / folder / leave out), text + custom fields + notes + serial number, the day of a UTC time; again = nothing twice;
   --split-manifest + a top folder; attacks: not a ZIP, no manifest, encrypted, a too large manifest, deep JSON, a path
   with ../, a missing / doubled file, a zip bomb; wrong part number / size
 - rights: a member 403, an outsider 404, an agent refused, the upload belongs to its uploader; Stop of a waiting ZIP run
   discards the upload
 - hosted: the section is there, only public HTTPS (http, loopback, private, link-local, ULA, IPv4-in-IPv6, CGNAT, a name
   on a private address: refused, also with the allow list set); a stored http:// address fails with the reason; ZIP works
usage: p269_a_api_test.py <datadir>"""
import io
import json
import os
import random
import shutil
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
PL = "http://127.0.0.1:8098"
FAILS, OKS = [], [0]
RND = random.Random(1846)


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


def sh(cmd):
    """A shell command inside the app container (the uploads lie below its /data)."""
    return subprocess.run(["docker", "exec", CT, "sh", "-c", cmd], capture_output=True, text=True).stdout.strip()


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def tiny_pdf(text, pad=0):
    """A one-page PDF with a text layer (hand-written), pad = random bytes after it (a bigger file that does not compress)."""
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
    if pad:
        out += b"%" + bytes(RND.getrandbits(8) for _ in range(pad))
    return out


# ---- the fake Paperless-ngx (URL way): 5 documents of ~600 KB
KB600 = 600 * 1024
PLDATA = {
    "tags": [{"id": 1, "name": "Tax", "document_count": 5}], "correspondents": [], "document_types": [], "custom_fields": [],
    "documents": [{"id": i, "title": f"Letter {i}", "content": f"Letter number {i}", "created": "2025-03-0%d" % i, "correspondent": None,
                   "document_type": None, "tags": [1], "archive_serial_number": None, "original_file_name": f"l{i}.pdf", "custom_fields": [],
                   "notes": [], "file": tiny_pdf(f"Letter {i}", KB600).decode("latin-1")} for i in range(1, 6)],
    "notes": {}}


def pl_write():
    with open(os.path.join(DATA, "pl.json"), "w") as f:
        json.dump(PLDATA, f)


def state(s, ws):
    return s.get(B + f"/api/paperless?ws={ws}").json()


def run_idle(s, ws, secs=90):
    return until(lambda: (lambda j: j if ((j.get("conn") or {}).get("run") or {}).get("state") == "idle" else None)(state(s, ws)), secs)


def zip_idle(s, ws, secs=90):
    return until(lambda: (lambda j: j if (j.get("zip") or {}).get("state") == "done" and j["zip"]["run"]["state"] == "idle" else None)(state(s, ws)), secs)


def docs(s, ws):
    return s.get(B + f"/api/docs?ws={ws}").json().get("docs") or []


# ---- export ZIPs (the format of document_exporter: manifest.json with Django records, files next to it)
def rec(model, pk, **fields):
    return {"model": model, "pk": pk, "fields": fields}


def drec(pk, title, fname, **kw):
    f = {"title": title, "content": "", "created": "2025-01-01T00:00:00Z", "correspondent": None, "document_type": None, "tags": [],
         "archive_serial_number": None, "original_filename": fname, "mime_type": "application/pdf", "checksum": "x" * 32}
    f.update(kw)
    return {"model": "documents.document", "pk": pk, "fields": f, "__exported_file_name__": fname,
            "__exported_thumbnail_name__": fname + "-thumbnail.webp"}


def build_zip(records, files, top="", split=False, comp=zipfile.ZIP_DEFLATED):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", comp) as z:
        if split:  # --split-manifest: the documents (+ their notes / field values) in <name>-manifest.json next to the file
            main = [x for x in records if x["model"] not in ("documents.document", "documents.note", "documents.customfieldinstance")]
            z.writestr(top + "manifest.json", json.dumps(main))
            for x in records:
                if x["model"] == "documents.document":
                    own = [x] + [y for y in records if y["model"] in ("documents.note", "documents.customfieldinstance") and y["fields"].get("document") == x["pk"]]
                    z.writestr(top + x["__exported_file_name__"] + "-manifest.json", json.dumps(own))
        else:
            z.writestr(top + "manifest.json", json.dumps(records))
        z.writestr(top + "metadata.json", json.dumps({"version": "2.17.1"}))
        for name, data in files.items():
            z.writestr(top + name, data)
    return b.getvalue()


def upload(s, ws, data, name="export.zip", stop_after=None):
    r = s.post(B + "/api/paperless/zip", json={"ws": ws, "size": len(data), "name": name})
    if not r.ok:
        return r
    z = r.json()["zip"]
    n, chunk = z["next"], z["chunk"]
    while n * chunk < len(data):
        if stop_after is not None and n >= stop_after:
            return r
        r = s.post(B + "/api/paperless/zip/part", data={"ws": ws, "n": str(n)}, files={"part": ("part", data[n * chunk:(n + 1) * chunk])})
        if not r.ok:
            return r
        n += 1
    return checked(s, ws, r)


def checked(s, ws, r):
    """2.81.0 (#1874): the last part only stores (state check); the worker checks in the background -> the state once it is done."""
    if r.ok and (r.json().get("zip") or {}).get("state") == "check":
        until(lambda: (state(s, ws).get("zip") or {}).get("state") != "check", 60)
        r = s.get(B + f"/api/paperless?ws={ws}")
    return r


CHUNK_KB = 64
SECRET = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
BASE_EXTRA = (os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098 -e KALMIDO_SECRET_KEY=" + SECRET
              + f" -e KALMIDO_PAPERLESS_ZIP_CHUNK_KB={CHUNK_KB} -e KALMIDO_PAPERLESS_ZIP_MAX_MB=30")
env = dict(os.environ, EXTRA=BASE_EXTRA)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_paperless.py"), DATA)
pl_write()
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_paperless.py"])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["bob"]})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id NOT IN (?,?)", (ORG, ids["bob"], ids["carol"]), write=True)
dbx("DELETE FROM org_members WHERE user_id=?", (ids["erin"],), write=True)  # erin: a freelancer without an organisation
r = A.post(B + "/api/admin/agents", json={"username": "plbot", "display_name": "Plbot"})
assert r.status_code == 201, r.text
AGT = r.json().get("token") or ""
for s in (A, Bo):
    s.post(B + "/api/auth/logout")
A, Bo, Ca, Er = sess("alice"), sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    f = s.get(B + "/api/state").json()["settings"].get("features") or ""
    if "docs" not in f.split(","):
        s.patch(B + "/api/settings", json={"features": f + ",docs"})
OWS, EWS = f"org:{ORG}", "private"
EU = f"u{ids['erin']}"

# ---- rollback: one new table, row-level security on it
check([x[0] for x in dbx("SELECT relrowsecurity FROM pg_class WHERE relname='pl_uploads'")] == [True], "pl_uploads: new table with row-level security")

# ---- self-hosted unchanged: the internal host on the allow list
j = state(A, "private")
check(j.get("available") is True and j.get("hosted") is False and j.get("zip") is None, f"self-hosted: available, no upload yet ({j})")
r = A.put(B + "/api/paperless", json={"ws": "private", "url": PL, "token": "pl-secret"})
check(r.ok, f"self-hosted: an allowed internal host connects as before ({r.status_code} {r.text[:200]})")
r = A.put(B + "/api/paperless", json={"ws": "private", "url": "http://10.255.255.1:8098", "token": "pl-secret"})
check(r.status_code == 400 and "private network" in r.json().get("error", ""), f"self-hosted: another internal host blocked with the old hint ({r.text[:160]})")
p = A.get(B + "/api/paperless/preview?ws=private").json()
sz = p.get("size") or {}
check(sz.get("exact") is False and sz.get("need") and abs(sz["need"] - 5 * len(tiny_pdf("Letter 1", KB600))) < 50_000 and sz.get("free") is None and sz.get("fits") == "yes",
      f"preview: about the size from the metadata of a sample, no limit = fits ({sz})")

# ---- the queue: two workspaces at once -> one runs, the other waits
r = Bo.put(B + "/api/paperless", json={"ws": OWS, "url": PL, "token": "pl-secret"})
check(r.ok, f"the organisation connects ({r.status_code})")
PLDATA["delay"] = 0.5
pl_write()
check(A.post(B + "/api/paperless/import", json={"ws": "private"}).ok, "alice starts")
until(lambda: state(A, "private")["conn"]["run"]["state"] == "busy", 20)
r = Bo.post(B + "/api/paperless/import", json={"ws": OWS})
run = r.json()["conn"]["run"] if r.ok else {}
check(r.ok and run.get("state") == "queued" and run.get("place") == 1, f"the second import waits: place 1 in the queue ({run})")
both, seen_q = False, False
t0 = time.time()
while time.time() - t0 < 60:
    a, b = state(A, "private")["conn"]["run"]["state"], state(Bo, OWS)["conn"]["run"]["state"]
    both = both or (a == "busy" and b == "busy")
    seen_q = seen_q or b == "queued"
    if a == "idle" and b == "idle":
        break
    time.sleep(0.3)
check(seen_q and not both, f"never two imports at the same time (queued seen {seen_q}, both busy {both})")
check(len(docs(A, "private")) == 5 and len(docs(Bo, OWS)) == 5, f"both came in after each other ({len(docs(A, 'private'))}, {len(docs(Bo, OWS))})")
PLDATA["delay"] = 0
pl_write()

# ---- the storage quota (erin, a freelancer): 2 MB, 5 documents of 600 KB
check(A.patch(B + f"/api/users/{ids['erin']}", json={"storage_quota_mb": 2}).ok, "setup: erin gets 2 MB")
r = Er.put(B + "/api/paperless", json={"ws": EWS, "url": PL, "token": "pl-secret"})
check(r.ok, f"erin connects ({r.status_code})")
p = Er.get(B + "/api/paperless/preview?ws=private").json()
sz = p.get("size") or {}
check(sz.get("fits") == "maybe" and sz.get("free") and sz["free"] <= 2 * 1024 * 1024 and sz.get("exact") is False,
      f"preview: about 3 MB for 2 MB free = a warning, the start stays allowed ({sz})")
check(Er.post(B + "/api/paperless/import", json={"ws": EWS}).ok, "the start is allowed")
j = run_idle(Er, EWS)
run = (j or {}).get("conn", {}).get("run", {})
n_in = len(docs(Er, EWS))
check(run.get("error", "").startswith("quota") and "of 5 documents" in run.get("error_text", "") and 1 <= run.get("new", 0) < 5,
      f"the run stops when the storage is full and says how far it came ({run})")
check(n_in == run.get("new") and dbx("SELECT COUNT(*) FROM pl_imported WHERE ws=?", (EU,))[0][0] == n_in
      and dbx("SELECT COUNT(*) FROM fs_nodes WHERE owner_id=? AND kind='file' AND deleted_at IS NULL", (ids["erin"],))[0][0] == n_in,
      f"nothing half: every document that came in is complete, the one that did not fit is not there ({n_in})")
check(A.patch(B + f"/api/users/{ids['erin']}", json={"storage_quota_mb": 1}).ok, "setup: erin's quota below what she uses")
r = Er.post(B + "/api/paperless/import", json={"ws": EWS})
check(r.status_code == 413 and r.json().get("code") == "quota_exceeded", f"full before the start: 413 ({r.status_code} {r.text[:160]})")
r = Er.post(B + "/api/paperless/zip", json={"ws": EWS, "size": 1000, "name": "e.zip"})
check(r.status_code == 413, f"full: no ZIP upload either ({r.status_code})")

# ---- a ZIP export: tags / correspondents / types, custom fields, notes, two of them as folder / left out
TAGS = [rec("documents.tag", 1, name="Tax", match="tax office", matching_algorithm=1, is_insensitive=True, color="#a6cee3"),
        rec("documents.tag", 2, name="Archive 2025", match="", matching_algorithm=0, is_insensitive=True),
        rec("documents.tag", 3, name="Ignore me", match="", matching_algorithm=6, is_insensitive=True)]
CORR = [rec("documents.correspondent", 7, name="Example Utility", match="utility", matching_algorithm=3, is_insensitive=False)]
TYPES = [rec("documents.documenttype", 9, name="Invoice", match="", matching_algorithm=6, is_insensitive=True)]
FIELDS = [rec("documents.customfield", 4, name="Contract number", data_type="string", extra_data={}),
          rec("documents.customfield", 5, name="Status", data_type="select",
              extra_data={"select_options": [{"id": "aB3xY9", "label": "Open"}, {"id": "Qw7rT2", "label": "Paid"}]})]
PDF1, PDF2 = tiny_pdf("Power bill May", 90_000), tiny_pdf("Tax notice", 90_000)
GOOD = TAGS + CORR + TYPES + FIELDS + [
    drec(11, "Power bill May", "0000011.pdf", content="Power bill May total 42.00 EUR", created="2025-05-02T22:30:00Z",
         correspondent=7, document_type=9, tags=[1, 2], archive_serial_number=17),
    drec(12, "Tax notice", "0000012.pdf", content="Notice of assessment", created="2025-02-01", document_type=9, tags=[1, 3]),
    rec("documents.note", 1, note="Paid on 10 May", document=11, user=1),
    rec("documents.customfieldinstance", 1, document=11, field=4, value_text="C-123"),
    rec("documents.customfieldinstance", 2, document=11, field=5, value_select="Qw7rT2")]
ZGOOD = build_zip(GOOD, {"0000011.pdf": PDF1, "0000012.pdf": PDF2, "0000011.pdf-thumbnail.webp": b"RIFF"}, top="export-2026/")
check(len(ZGOOD) > 2 * CHUNK_KB * 1024, f"setup: the ZIP spans several parts ({len(ZGOOD)})")

# rights first -- tenant-matrix: paperless
check(Ca.post(B + "/api/paperless/zip", json={"ws": OWS, "size": len(ZGOOD)}).status_code == 403, "a member cannot upload for the organisation")
check(Er.post(B + "/api/paperless/zip", json={"ws": OWS, "size": len(ZGOOD)}).status_code == 404, "an outsider: 404")
ag = requests.Session()
ag.headers.update({**H, "Authorization": "Bearer " + AGT})
check(ag.post(B + "/api/paperless/zip", json={"ws": "private", "size": 1000}).status_code in (401, 403, 404), "an agent cannot upload")
check(ag.get(B + "/api/paperless/zip/preview?ws=private").status_code in (401, 403, 404), "an agent sees no preview")
check(Bo.post(B + "/api/paperless/zip", json={"ws": OWS, "size": 31 * 1024 * 1024}).status_code == 413, "larger than KALMIDO_PAPERLESS_ZIP_MAX_MB: 413")
check(Bo.post(B + "/api/paperless/zip", json={"ws": OWS, "size": "12"}).status_code == 400, "a size that is not a number: 400")

# a part at a time: sealed, 0600, in a folder of its own
r = upload(Bo, OWS, ZGOOD, "export-2026.zip", stop_after=1)
z = r.json().get("zip") or {}
check(r.ok and z.get("state") == "upload" and z.get("next") == 1 and z.get("mine") is True, f"the first part is in ({z})")
zid = z.get("id")
check(sh(f"stat -c %a /data/paperless-zip/{zid}") == "700" and sh(f"stat -c %a /data/paperless-zip/{zid}/part-000000") == "600",
      "the upload: folder 0700, part 0600")
check(sh(f"ls /data/attachments 2>/dev/null | grep -c paperless-zip") in ("", "0"), "not below the attachments (not in the backups)")
r = Bo.post(B + "/api/paperless/zip/part", data={"ws": OWS, "n": "5"}, files={"part": ("part", ZGOOD[:CHUNK_KB * 1024])})
check(r.status_code == 409, f"a part out of order: 409 ({r.status_code})")
r = Bo.post(B + "/api/paperless/zip/part", data={"ws": OWS, "n": "1"}, files={"part": ("part", ZGOOD[:100])})
check(r.status_code == 400, f"a short part that is not the last one: 400 ({r.status_code})")
check(Ca.post(B + "/api/paperless/zip/part", data={"ws": OWS, "n": "1"}, files={"part": ("part", b"x")}).status_code == 403,
      "a member cannot send parts")
# the first part once more (its answer was lost), then the rest
r = Bo.post(B + "/api/paperless/zip/part", data={"ws": OWS, "n": "0"}, files={"part": ("part", ZGOOD[:CHUNK_KB * 1024])})
check(r.ok and r.json()["zip"]["next"] == 1, f"the last part again is taken ({r.status_code})")
chunk = z["chunk"]
n = 1
while n * chunk < len(ZGOOD):
    r = Bo.post(B + "/api/paperless/zip/part", data={"ws": OWS, "n": str(n)}, files={"part": ("part", ZGOOD[n * chunk:(n + 1) * chunk])})
    n += 1
# 2.81.0 (#1874): the answer of the last part comes at once (the check runs in the worker), then the export is ready
z = r.json().get("zip") or {}
check(r.ok and z.get("state") == "check" and z.get("got") == len(ZGOOD), f"the last part answers at once: being checked ({z.get('state')})")
z = checked(Bo, OWS, r).json().get("zip") or {}
check(z.get("state") == "ready" and z.get("got") == len(ZGOOD), f"all parts in: ready ({z.get('state')} {z.get('error_text')})")
check(Ca.get(B + f"/api/paperless/zip/preview?ws={OWS}").status_code == 403, "a member sees no preview of the upload")
check((state(Ca, OWS).get("zip") or {}).get("mine") is False, "a member sees that there is one, not as theirs")
p = Bo.get(B + f"/api/paperless/zip/preview?ws={OWS}").json()
check(p.get("count") == 2 and p.get("already") == 0 and p.get("zip") is True, f"ZIP preview: 2 documents ({p.get('count')}, {p.get('already')})")
tags = {t["name"]: t for t in p.get("tags", [])}
check(set(tags) == {"Tax", "Archive 2025", "Ignore me"} and tags["Tax"]["count"] == 2 and tags["Archive 2025"]["count"] == 1
      and all(t["to"] == "tag" for t in tags.values()), f"ZIP preview: the tags with their counts ({p.get('tags')})")
check(tags["Tax"].get("match") == "tax office" and tags["Tax"].get("algo") == 1 and tags["Tax"].get("insens") is True,
      "ZIP preview: the tags carry Paperless' matching (for the rules of part B)")
check([x["name"] for x in p.get("senders", [])] == ["Example Utility"] and [x["name"] for x in p.get("types", [])] == ["Invoice"],
      f"ZIP preview: correspondents -> senders, types ({p.get('senders')}, {p.get('types')})")
# 2.69.0 (#1847): the ZIP way takes over the matching rules too (Tax any, Example Utility literal + case-sensitive; auto counted)
pr = p.get("rules") or {}
check(pr.get("convert") == 2 and pr.get("auto") == 2 and pr.get("dup") == 0, f"ZIP preview: 2 rules to take over, 2 auto ({pr})")
sz = p.get("size") or {}
check(sz.get("exact") is True and sz.get("need") == len(PDF1) + len(PDF2), f"ZIP preview: the exact size of the originals ({sz}, {len(PDF1) + len(PDF2)})")
mapping = {"tags": {"2": {"to": "folder", "name": "Archive 2025"}, "3": {"to": "skip", "name": ""}, "1": {"to": "tag", "name": "Taxes"}},
           "senders": {}, "types": {"9": "Bill"}}
r = Bo.post(B + "/api/paperless/zip/import", json={"ws": OWS, "mapping": mapping})
check(r.ok, f"ZIP import started ({r.status_code} {r.text[:200]})")
j = zip_idle(Bo, OWS)
run = ((j or {}).get("zip") or {}).get("run") or {}
check(run.get("new") == 2 and run.get("failed") == 0 and run.get("total") == 2 and not run.get("error"), f"ZIP import: 2 new ({run})")
le = run.get("learn") or {}
check(le.get("rules_new") == 2 and le.get("trained") == 2 and "unsupported" not in le, f"ZIP import: 2 rules taken over, 2 documents learnt ({le})")
zr = [{k: v for k, v in x.items() if k != "id"} for x in Bo.get(B + f"/api/docs/settings?ws=org:{ORG}").json().get("rules") or []]
check({"kind": "exact", "match": "utility", "case": True, "sender": "Example Utility"} in zr
      and {"kind": "any", "match": "tax office", "tags": ["Taxes"]} in zr, f"ZIP import: the rules with the mapped targets ({zr})")
check(sh(f"test -e /data/paperless-zip/{zid} && echo yes") == "", "the upload is gone after the run")
ds = until(lambda: (lambda x: x if len([d for d in x if d["name"] in ("Power bill May.pdf", "Tax notice.pdf") and d["state"] in ("done", "failed")]) == 2 else None)(docs(Bo, OWS)), 60) or []  # 2.80.3: recognised (an import makes its preview since 2.80.2)
by = {d["name"]: d for d in ds}
pb, tn = by.get("Power bill May.pdf"), by.get("Tax notice.pdf")
check(pb and tn, f"two documents, named after the title ({sorted(by)})")
if pb and tn:
    check(pb["date"] == "2025-05-03" and tn["date"] == "2025-02-01", f"the day of a UTC time in the server's zone, a plain day ({pb['date']}, {tn['date']})")
    check((pb.get("sender") or {}).get("name") == "Example Utility" and (pb.get("type") or {}).get("name") == "Bill",
          f"correspondent -> sender, type renamed ({pb.get('sender')}, {pb.get('type')})")
    check([t["name"] for t in pb["tags"]] == ["Taxes"] and [t["name"] for t in tn["tags"]] == ["Taxes"], f"tag renamed, left out ({pb['tags']}, {tn['tags']})")
    check((pb.get("folder") or {}).get("name") == "Archive 2025" and not tn.get("folder"), f"a tag as folder ({pb.get('folder')})")
    full = Bo.get(B + f"/api/docs/{pb['id']}").json()
    t = full.get("text") or ""
    cf = {x["name"]: x.get("label") for x in full.get("custom_fields") or []}  # 2.108.0 (#2179): custom fields are fields now
    check("Power bill May total 42.00 EUR" in t and "Archive serial number: 17" in t and "Paid on 10 May" in t
          and cf.get("Contract number") == "C-123" and cf.get("Status") == "Paid", f"text + serial number + note, custom fields as fields ({t[:300]!r}, {cf})")
    f = Bo.get(B + f"/api/docs/{pb['id']}/file")
    check(f.ok and f.content == PDF1, "the original file, unchanged")
check(not any(d["org_id"] == ORG for d in docs(A, "all")), "alice (no member) sees none of them")
# again: nothing twice (the same export; --split-manifest, no top folder)
ZSPLIT = build_zip(GOOD, {"0000011.pdf": PDF1, "0000012.pdf": PDF2}, split=True)
r = upload(Bo, OWS, ZSPLIT)
check(r.ok and r.json()["zip"]["state"] == "ready", f"--split-manifest without a top folder: ready ({r.text[:200]})")
p = Bo.get(B + f"/api/paperless/zip/preview?ws={OWS}").json()
check(p.get("count") == 2 and p.get("already") == 2 and (p.get("size") or {}).get("need") == 0, f"the preview knows both ({p.get('already')}, {p.get('size')})")
Bo.post(B + "/api/paperless/zip/import", json={"ws": OWS})
run = ((zip_idle(Bo, OWS) or {}).get("zip") or {}).get("run") or {}
check(run.get("new") == 0 and run.get("skipped") == 2, f"a second import of the export brings nothing twice ({run})")

# ---- attacks
def zip_err(data, what, want):
    r = upload(Bo, OWS, data, "bad.zip")
    z = (r.json().get("zip") or {}) if r.ok else {}
    check(z.get("state") == "bad" and want in (z.get("error_text") or ""), f"{what}: refused with the reason ({r.status_code} {z.get('error_text')})")
    if z.get("id"):
        check(sh(f"test -e /data/paperless-zip/{z['id']} && echo yes") == "", f"{what}: nothing stays on the disk")


zip_err(bytes(RND.getrandbits(8) for _ in range(5000)), "not a ZIP", "not a ZIP")
b = io.BytesIO()
zipfile.ZipFile(b, "w").close()
zip_err(b.getvalue(), "an empty ZIP", "No Paperless-ngx export")
b = io.BytesIO()
with zipfile.ZipFile(b, "w") as zz:
    zz.writestr("documents/a.pdf", PDF1)
zip_err(b.getvalue(), "no manifest", "No Paperless-ngx export")
enc = bytearray(ZGOOD)
i = enc.find(b"PK\x01\x02")
while i >= 0:
    enc[i + 8] |= 1  # the "encrypted" flag in the central directory
    i = enc.find(b"PK\x01\x02", i + 4)
zip_err(bytes(enc), "an encrypted ZIP", "Encrypted")
b = io.BytesIO()
with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as zz:
    zz.writestr("manifest.json", "[" + " " * (65 * 1024 * 1024) + "]")
zip_err(b.getvalue(), "a manifest above 64 MB", "too large manifest")
b = io.BytesIO()
with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as zz:
    zz.writestr("manifest.json", "[" * 100000 + "]" * 100000)
zip_err(b.getvalue(), "deeply nested JSON", "No Paperless-ngx export")
zip_err(build_zip({"not": "a list"}, {}), "a manifest that is no list", "No Paperless-ngx export")
# documents that misbehave: a path with ../, a missing file, the same file twice, a zip bomb; the others come in
BOMB = b"\0" * (5 * 1024 * 1024)
PDF3 = tiny_pdf("Escape attempt", 1000)
ATT = [drec(21, "Fine letter", "fine.pdf"), drec(22, "Escape attempt", "../../../tmp/evil.pdf"), drec(23, "Missing", "nope.pdf"),
       drec(24, "Same again", "fine.pdf"), drec(25, "Bomb", "bomb.pdf")]
ZATT = build_zip(ATT, {"fine.pdf": tiny_pdf("Fine letter", 1000), "../../../tmp/evil.pdf": PDF3, "bomb.pdf": BOMB})
r = upload(Bo, OWS, ZATT)
check(r.ok and r.json()["zip"]["state"] == "ready", f"the attack ZIP is an export ({r.text[:200]})")
Bo.post(B + "/api/paperless/zip/import", json={"ws": OWS})
run = ((zip_idle(Bo, OWS) or {}).get("zip") or {}).get("run") or {}
check(run.get("new") == 2 and run.get("skipped") == 1 and run.get("failed") == 2, f"2 new, the same file once, missing + bomb failed ({run})")
check(sh("test -e /tmp/evil.pdf && echo yes") == "" and sh("ls /data/paperless-zip | wc -l") in ("0", ""), "nothing unpacked onto the disk, nothing left over")
check(any(d["name"] == "Escape attempt.pdf" for d in docs(Bo, OWS)), "a ../ name is only a name (the title)")
check(not any("Bomb" in d["name"] for d in docs(Bo, OWS)), "the zip bomb did not come in")

# ---- a waiting ZIP run: the queue, and Stop discards the upload
dbx("UPDATE pl_sources SET run_state='busy', run_beat=? WHERE ws='u1'", (time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),), write=True)
ZQ = build_zip(TAGS + [drec(31, "Queued letter", "q.pdf")], {"q.pdf": tiny_pdf("Queued letter", 500)})
upload(Bo, OWS, ZQ)
r = Bo.post(B + "/api/paperless/zip/import", json={"ws": OWS})
time.sleep(6)  # the worker looks every 5 s
zr = (state(Bo, OWS).get("zip") or {}).get("run") or {}
check(zr.get("state") == "queued" and zr.get("place") == 1, f"a ZIP run waits behind a running import ({zr})")
zid = state(Bo, OWS)["zip"]["id"]
check(Bo.delete(B + f"/api/paperless/zip?ws={OWS}").status_code == 409, "a waiting upload cannot be discarded (stop it first)")
r = Bo.post(B + "/api/paperless/zip/stop", json={"ws": OWS})
check(r.ok and r.json().get("zip") is None and sh(f"test -e /data/paperless-zip/{zid} && echo yes") == "",
      f"Stop of a waiting ZIP run discards its upload ({r.text[:160]})")
dbx("UPDATE pl_sources SET run_state='' WHERE ws='u1'", write=True)
# a ZIP that surely does not fit (erin: 3 MB, ~1.8 MB used)
check(A.patch(B + f"/api/users/{ids['erin']}", json={"storage_quota_mb": 3}).ok, "setup: erin 3 MB")
big = {f"b{i}.pdf": tiny_pdf(f"Big {i}", 700 * 1024) for i in range(3)}
ZBIG = build_zip([drec(40 + i, f"Big {i}", f"b{i}.pdf") for i in range(3)], big)
r = upload(Er, EWS, ZBIG)
check(r.ok and r.json()["zip"]["state"] == "ready", f"erin uploads ({r.status_code})")
p = Er.get(B + "/api/paperless/zip/preview?ws=private").json()
check((p.get("size") or {}).get("fits") == "no", f"the preview says it does not fit ({p.get('size')})")
r = Er.post(B + "/api/paperless/zip/import", json={"ws": EWS})
check(r.status_code == 413 and "storage is free" in r.json().get("error", ""), f"start: 413 with the sizes ({r.status_code} {r.text[:160]})")
check(Bo.get(B + "/api/paperless/zip/preview?ws=private").status_code == 404, "another person's upload: 404 (bob's own space has none)")
check(Er.delete(B + "/api/paperless/zip?ws=private").json().get("zip") is None, "discard the upload")

# ---- a hosted server: public HTTPS only (the allow list stays set and does not apply)
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env={**env, "KEEP": "1", "EXTRA": BASE_EXTRA + " -e KALMIDO_HOSTED=1"})
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_paperless.py"])
A, Bo, Er = sess("alice"), sess("bob"), sess("erin")
j = state(A, "private")
check(j.get("available") is True and j.get("hosted") is True, f"hosted: the section is there ({j.get('available')}, {j.get('hosted')})")
for url in ("http://127.0.0.1:8098", "https://127.0.0.1:8098", "https://localhost:8098", "https://10.1.2.3", "https://198.18.0.1",
            "https://169.254.169.254", "https://[::1]:8098", "https://[fd12:3456::1]", "https://[::ffff:127.0.0.1]:8098",
            "https://100.64.0.1", "https://0.0.0.0:8098"):
    r = A.put(B + "/api/paperless", json={"ws": "private", "url": url, "token": "pl-secret"})
    e = r.json().get("error", "") if r.status_code == 400 else ""
    check(r.status_code == 400 and "public HTTPS" in e and "An admin can allow" not in e, f"hosted: {url} refused with the hosted reason ({r.status_code} {e[:120]})")
r = A.get(B + "/api/paperless/preview?ws=private")
check(r.status_code == 502 and "public HTTPS" in r.json().get("error", ""), f"hosted: a stored http:// address fails with the reason ({r.status_code} {r.text[:160]})")
r = upload(Er, EWS, build_zip([drec(51, "Hosted letter", "h.pdf")], {"h.pdf": tiny_pdf("Hosted letter", 500)}))
check(r.ok and r.json()["zip"]["state"] == "ready", f"hosted: a ZIP uploads ({r.status_code} {r.text[:160]})")
Er.post(B + "/api/paperless/zip/import", json={"ws": EWS})
run = ((zip_idle(Er, EWS) or {}).get("zip") or {}).get("run") or {}
check(run.get("new") == 1 and any(d["name"] == "Hosted letter.pdf" for d in docs(Er, EWS)), f"hosted: the ZIP import works ({run})")

print(f"p269_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
