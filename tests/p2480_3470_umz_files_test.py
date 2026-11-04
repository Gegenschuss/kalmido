#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.480.0 (#3470): the account export takes the contents of the private space along, the import restores them.
Invented names only (example.com). A person without an organisation (freelancer_fixture):
 - a file of the private file store in a folder with two versions, a file of a private knowledge page and of a private table
   -> the export holds every version (the current one under the node, the older one under files/store/<node>-v1-...), the
   page file and the table file; the manifest no longer names older file versions as missing
 - a second person without an organisation imports it: the preview no longer names files, tables and knowledge pages as
   staying behind; afterwards both versions, the page file and the table file read back with the same bytes, sealed at rest
   (the plain text is nowhere on the disk), counted against the storage; the undo takes them away again
 - the space check: a third person with 1 MB of storage gets the refusal before the run, with what the files need
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2480_NOSTART=1 = the server already runs like that).
freelancer-matrix: own
usage: p2480_3470_umz_files_test.py <datadir>"""
import base64
import io
import json
import os
import subprocess
import sys
import zipfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else kt.DATA
KEY = base64.b64encode(os.urandom(32)).decode()
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
V1 = b"Umzugsplan erste Fassung " + os.urandom(8).hex().encode()
V2 = b"Umzugsplan zweite Fassung " + os.urandom(8).hex().encode()


def export_of(s):
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    j = until(lambda: (lambda x: x if x.get("state") != "running" else None)(s.get(B + "/api/account/export").json()), 120)
    assert j and j.get("state") == "done", j
    r = kt.su_get(s, B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


def state_of(s, iid):
    j = s.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid, until(lambda: state_of(s, iid), 180) or {}


def run(s, iid):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}})
    check(r.status_code == 202, f"the run starts {r.status_code} {r.text[:200]}")
    return until(lambda: state_of(s, iid), 180) or {}


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def on_disk(rel):
    with open(os.path.join(DATA, "attachments", rel), "rb") as f:
        return f.read()


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2480")
A = kt.setup()
FID, Fr = freelancer(B, A, features=FEATURES + ",sheets")  # the person moving, without an organisation
GID, Gi = freelancer(B, A, "gina", features=FEATURES + ",sheets")  # the target account, without an organisation too

# ---------------------------------------------------------------- the private space of the person moving
r = Fr.post(B + "/api/files/folders", json={"space": "private", "name": "Umzug Ordner"})
check(r.status_code == 201, f"a private folder {r.status_code} {r.text[:120]}")
FOLDER = r.json()["id"]
r = Fr.post(B + "/api/files/upload", data={"parent_id": str(FOLDER)}, files={"file": ("plan.txt", V1, "text/plain")})
check(r.status_code == 201, f"a private file {r.status_code} {r.text[:120]}")
NID = r.json()["items"][0]["id"]
r = Fr.post(B + f"/api/files/nodes/{NID}/versions", files={"file": ("plan.txt", V2, "text/plain")})
check(r.status_code == 201, f"its second version {r.status_code} {r.text[:120]}")
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Umzug Wissen", "body": "Seite mit Bild"})
check(r.ok, f"a private knowledge page {r.status_code} {r.text[:120]}")
WP = r.json().get("id") or (r.json().get("page") or {}).get("id")
r = Fr.post(B + f"/api/wiki/pages/{WP}/files", files={"file": ("bild.png", PNG, "image/png")})
check(r.status_code == 201, f"a picture on the page {r.status_code} {r.text[:120]}")
r = Fr.post(B + "/api/sheets", json={"title": "Umzug Tabelle", "space": "private"})
check(r.status_code == 201, f"a private table {r.status_code} {r.text[:120]}")
SH = r.json()
CF = Fr.post(B + f"/api/sheets/{SH['id']}/columns", json={"title": "Datei", "kind": "file"}).json()["column"]["id"]
r = Fr.post(B + f"/api/sheets/{SH['id']}/files", data={"row_id": str(SH["rows"][0]["id"]), "col_id": str(CF)},
            files={"file": ("beleg.pdf", PDF, "application/pdf")})
check(r.status_code == 201, f"a file cell {r.status_code} {r.text[:120]}")

# ---------------------------------------------------------------- the export
EX = export_of(Fr)
with zipfile.ZipFile(io.BytesIO(EX)) as z:
    names = set(z.namelist())
    man = json.loads(z.read("manifest.json"))
    D = {n[5:-5]: json.loads(z.read(n)) for n in names if n.startswith("data/") and n.endswith(".json")}
    old = f"files/store/{NID}-v1-plan.txt"
    check(old in names and z.read(old) == V1, f"#3470 the older version is in the file {sorted(n for n in names if n.startswith('files/'))}")
    cur = next((x.get("file") for x in D.get("private_files", []) if x["id"] == NID), None)
    check(cur and z.read(cur) == V2, f"#3470 the current version under the node {cur}")
    check(sorted(v["no"] for v in D.get("private_versions", []) if v["node_id"] == NID) == [1, 2], f"#3470 both version rows {D.get('private_versions')}")
    wf = (D.get("wiki_files") or [{}])[0].get("file")
    sf = (D.get("sheet_files") or [{}])[0].get("file")
    check(wf and z.read(wf) == PNG and sf and z.read(sf) == PDF, f"the page file and the table file are in the file {wf} {sf}")
check(not any("older versions" in x for x in man.get("not_included", [])), f"#3470 'not included' no longer names older versions {man.get('not_included')}")

# ---------------------------------------------------------------- the import into a fresh account
iid, j = upload(Gi, EX)
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
nt = {x.get("what") for x in (j.get("preview") or {}).get("not_taken") or []}
check(not nt & {"My files", "Tables", "Knowledge pages"}, f"#3470 the preview no longer names them as staying behind {nt}")
j = run(Gi, iid)
check(j.get("state") == "done", f"the import is done {j.get('state')} {j.get('error')} {j.get('result')}")
IMP = (j.get("result") or {}).get("import_id")
WARN = json.dumps((j.get("result") or {}).get("warnings"), ensure_ascii=False)[:600]
gn = kt.dbx("SELECT id, parent_id, cur_version FROM fs_nodes WHERE owner_id=? AND org_id IS NULL AND name='plan.txt' AND deleted_at IS NULL", (GID,))
check(len(gn) == 1, f"#3470 the file arrives once in the private file store {gn}")
GN = gn[0][0] if gn else 0
check(gn and one("SELECT name FROM fs_nodes WHERE id=?", (gn[0][1],)) == "Umzug Ordner", "#3470 ... in its folder")
check(Gi.get(B + f"/api/files/nodes/{GN}/content").content == V2, f"#3470 the current version reads back with the same bytes {WARN}")
check(Gi.get(B + f"/api/files/nodes/{GN}/content?v=1").content == V1, "#3470 the older version too")
paths = [r[0] for r in kt.dbx("SELECT path FROM fs_versions WHERE node_id=? ORDER BY no", (GN,))]
check(len(paths) == 2 and all(on_disk(p) not in (V1, V2) for p in paths), "#3470 both versions are sealed at rest")
check(one("SELECT COUNT(*) FROM fs_versions WHERE node_id=? AND created_by=?", (GN, GID)) == 2, "#3470 they count against the importer's storage")
gw = kt.dbx("SELECT f.id, f.path FROM wiki_files f JOIN wiki_pages p ON p.id=f.page_id WHERE p.owner_id=? AND p.org_id IS NULL AND f.deleted_at IS NULL", (GID,))
check(len(gw) == 1 and Gi.get(B + f"/api/wiki/files/{gw[0][0]}").content == PNG and on_disk(gw[0][1]) != PNG,
      f"#3470 the page file reads back, sealed at rest {gw}")
gs = kt.dbx("SELECT f.id, f.sheet_id, f.path FROM sheet_files f JOIN sheets s ON s.id=f.sheet_id WHERE s.owner_id=? AND s.org_id IS NULL AND f.deleted_at IS NULL", (GID,))
check(len(gs) == 1 and Gi.get(B + f"/api/sheets/{gs[0][1]}/files/{gs[0][0]}").content == PDF and on_disk(gs[0][2]) != PDF,
      f"#3470 the table file reads back, sealed at rest {gs}")
cell = one("SELECT raw FROM sheet_cells WHERE sheet_id=? AND raw LIKE 'file:%'", (gs[0][1] if gs else 0,))
check(cell == f"file:{gs[0][0] if gs else 0}", f"#3470 the file cell points at the new file {cell}")
check(IMP and Gi.post(B + f"/api/imports/{IMP}/undo", json={}).ok, "the undo")
# 2.506.0 (#4299): into the trash (the file with its folder), the bytes stay for a restore
check(one("SELECT deleted_at FROM fs_nodes WHERE id=(SELECT parent_id FROM fs_nodes WHERE id=?)", (GN,))
      and not kt.dbx("SELECT 1 FROM wiki_files f JOIN wiki_pages p ON p.id=f.page_id WHERE p.owner_id=? AND p.deleted_at IS NULL", (GID,)),
      "#3470 the undo takes the files away again")

# ---------------------------------------------------------------- the space check before the run
big = b"Z" * 900_000  # below 1 MB per file in the tests, compresses well: the upload is small, the files are not
r = Fr.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("gross.bin", big, "application/octet-stream")})
check(r.status_code == 201, f"setup: a large private file {r.status_code}")
BIG = r.json()["items"][0]["id"]
check(Fr.post(B + f"/api/files/nodes/{BIG}/versions", files={"file": ("gross.bin", big[:-1] + b"Y", "application/octet-stream")}).status_code == 201,
      "setup: its second version")
EX2 = export_of(Fr)
HID, Hn = freelancer(B, A, "hanna")
check(A.patch(B + f"/api/users/{HID}", json={"storage_quota_mb": 1}).ok, "setup: hanna has 1 MB")
iid, j = upload(Hn, EX2)
err = json.dumps(j.get("error"), ensure_ascii=False)
check(j.get("state") == "invalid" and "too small for the files" in err, f"#3470 refused before the run, with the sizes {j.get('state')} {err[:300]}")
check(not kt.dbx("SELECT 1 FROM fs_nodes WHERE owner_id=?", (HID,)), "#3470 nothing was written")

# 2.480.0 review (#3470): a file encrypted in the browser has no bytes in the export: its versions are no rows and the file
# no node (else a node whose current version points at nothing, one warning per version)
LOCKED = r"""
import json
from kalmido.admin.acctimport import umz_private_oi
data = {"private_files": [{"id": 1, "kind": "folder", "name": "Ordner"}, {"id": 2, "kind": "file", "name": "a.txt", "parent_id": 1},
                          {"id": 3, "kind": "file", "name": "zu.bin", "parent_id": 1}],
        "private_versions": [{"id": 10, "node_id": 2, "no": 1, "file": "files/private_files/2-a.txt"},
                             {"id": 11, "node_id": 3, "no": 1}, {"id": 12, "node_id": 3, "no": 2}]}
oi = umz_private_oi(data, {"files/private_files/2-a.txt": (None, 0)})
print(json.dumps({k: [r.get("id") for r in v] for k, v in oi.items()}))
"""
r = subprocess.run(["docker", "exec", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test"), "python3", "-c", LOCKED],
                   capture_output=True, text=True, timeout=120)
got = json.loads((r.stdout or "{}").strip().splitlines()[-1] if r.stdout.strip() else "{}")
ids = sorted(i for v in got.values() for i in v)
check(r.returncode == 0 and 3 not in ids and 11 not in ids and 12 not in ids and 2 in ids and 10 in ids and 1 in ids,
      f"#3470 review: a locked file (no bytes) is left out, versions and node {got} {r.stderr[-300:]}")

sys.exit(kt.done("p2480_3470_umz_files"))
