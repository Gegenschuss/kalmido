#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.362.2 (#3099 #3105): a person without an organisation gets everything in one export. Invented names only (example.com).
 With the server key:
  #3099 the account export carries the personal office (readable, personal-office/ with the same parts as its own export, the
        receipt files too), the import preview names it as staying behind; the files of the knowledge pages and (#3134) of templates are in the file
  #3865 the import takes the files of templates back: sealed, on the new template, counted against the storage, once, with the undo
  #3099 the office archive (organisation 0) carries the receipts, the filed documents the office points at and their folders;
        never a file in the trash, never another person's node an office row names; a second person imports it privately:
        the cash entry and the equipment point at their files again, the file downloads
  #3105 the retention export has the procedure documentation, the number ranges, the dunning marks and the contracts (an
        organisation's project in a personal export: p2239_c_loeschung_test.py, #2874)
 Without the server key (a second start of the server):
  #3099 the office archive and the organisation export are a plain ZIP (state plain, no 409, mode as usual), the import reads them
Starts its OWN container twice (start.sh).
usage: p2362_2_export_test.py <datadir>"""
# freelancer-matrix: own
# freelancer-matrix: office
# tenant-matrix: own
import base64
import csv
import io
import json
import os
import subprocess
import sys
import time
import zipfile

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer
from kt import FAILS, OKS, check, sess, su_get

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"


def ok(r, what, codes=(200, 201, 202, 204)):
    check(r.status_code in codes, f"{what}: {r.status_code} {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {}


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


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


def start(extra):
    env = dict(os.environ, EXTRA="-e KALMIDO_INSTANCE_MODE=workspaces " + extra)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
    A = sess("alice")
    A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
    A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
    return A


def upload(s, data, name="export.bin"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid, secs=180):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def acct_export(s, **body):
    ok(s.post(B + "/api/account/export", json=body), "account export starts")
    for _ in range(480):
        j = s.get(B + "/api/account/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    check(j.get("state") == "done", f"account export done {j}")
    return su_get(s, B + "/api/account/export/file").content


def ox_export(s, oid):
    ok(s.post(B + f"/api/orgs/{oid}/export"), f"export of {oid} starts")
    for _ in range(480):
        j = s.get(B + f"/api/orgs/{oid}/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    check(j.get("state") == "done", f"export of {oid} done {j}")
    return j, su_get(s, B + f"/api/orgs/{oid}/export/file").content


def setup_office(s):
    ok(s.put(B + O + "/settings", json={"company_fields": {"name": "Frida Studio", "street": "Hafenweg 2", "zip": "12345", "city": "Musterstadt",
                                                            "iban": "DE02120300000000202051", "tax_number": "12/345/67890"},
                                        "lang": "en", "currency": "EUR"}), "office settings")
    c = ok(s.post(B + "/api/clients", json={"name": "Kundin Muster", "email": "kundin@example.com"}), "client").get("id")
    return c, ok(s.post(B + O + "/docs", json={"kind": "invoice", "client_id": c, "items": [{"title": "Dreh", "qty": 1, "rate": 100}]}), "draft invoice").get("id")


def receipt(s, name, text):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files={"files": (name, tiny_pdf(text), "application/pdf")})
    check(r.status_code == 201, f"{name} uploaded {r.status_code} {r.text[:160]}")
    nid = r.json()["ids"][0] if r.status_code == 201 else 0
    ok(s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Travel", "keep": True}), f"{name} is a receipt")
    return nid


# ---------------------------------------------------------------- with the server key
A = start(f"-e KALMIDO_SECRET_KEY={KEY}")
FID, F = freelancer(B, A)
BID, Bo = freelancer(B, A, "bert")
GID, G = freelancer(B, A, "gerd")
CL, INV = setup_office(F)
PB = one("SELECT id FROM orgs WHERE personal_of=?", (FID,))
check(PB, "setup: the personal office exists")
R1 = receipt(F, "taxi-beleg.pdf", "Taxi Beleg")  # a receipt of the office
FILED = receipt(F, "kasse-bild.pdf", "Kasse Bild")  # the picture of a cash entry
GONE = receipt(F, "weg-beleg.pdf", "Weg Beleg")  # in the trash: not in the archive
PLAIN = F.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("notiz.txt", b"nur eine Notiz im Dokumentenraum\n", "text/plain")}).json()["ids"][0]  # no office file
dbx("UPDATE fs_nodes SET deleted_at=? WHERE id=?", ("2026-10-20T10:00:00+00:00", GONE))  # in the trash
FOREIGN = receipt(Bo, "bert-geheim.pdf", "Bert Geheim")  # another person's node
now = "2026-10-20T10:00:00+00:00"
BOOK = dbx("INSERT INTO office_cashbooks(org_id, name, created_at, updated_at) VALUES(?,?,?,?) RETURNING id", (PB, "Kasse", now, now))[0][0]
dbx("INSERT INTO office_cash_entries(org_id, book_id, no, day, node_id, created_at, updated_at) VALUES(?,?,1,'2026-10-20',?,?,?)", (PB, BOOK, FILED, now, now))
dbx("INSERT INTO office_equipment(org_id, name, receipt_node_id, created_at, updated_at) VALUES(?,?,?,?,?)", (PB, "Kamera", FOREIGN, now, now))  # never in the file
# 2.977.0 (#5282): the head in office_procdocs, the version in the core's obj_versions (kind procdoc)
PDH = dbx("INSERT INTO office_procdocs(org_id) VALUES(?) RETURNING id", (PB,))[0][0]
dbx("INSERT INTO obj_versions(kind, ref_id, no, org_id, body, created_at, updated_at) VALUES('procdoc',?,1,?,'{\"s\":\"Verfahren Frida\"}',?,?)",
    (PDH, PB, now, now))
dbx("INSERT INTO office_dunning_marks(org_id, doc_id, level, created_at) VALUES(?,?,1,?)", (PB, INV, now))
dbx("INSERT INTO office_numbers(org_id, kind, period, last) VALUES(?,'invoice','2026',7) ON CONFLICT DO NOTHING", (PB,))
dbx("""INSERT INTO office_signoffs(org_id, doc_id, title, token_hash, token, ip, user_agent, signer_name, created_at)
       VALUES(?,?,?,?,?,?,?,?,?)""", (PB, INV, "Freigabe", "h1", "t1", "203.0.113.9", "Testbrowser", "Kim Kundin", now))
dbx("INSERT INTO office_agreements(org_id, name, created_at, updated_at) VALUES(?,?,?,?)", (PB, "Versicherung Studio", now, now))

# a knowledge page with a picture in the private workspace
zb = io.BytesIO()
with zipfile.ZipFile(zb, "w") as z:
    z.writestr("Plan.md", "# Plan\n\n![[skizze.png]]\n")
    z.writestr("skizze.png", b"\x89PNG\r\n\x1a\nkeinbild")
r = F.post(B + "/api/wiki/import", params={"space": "private"}, files={"file": ("export.zip", zb.getvalue(), "application/zip")})
check(r.ok, f"knowledge import {r.status_code} {r.text[:200]}")

# #3134: a template with its own copy of a task's file
TL = F.post(B + "/api/lists", json={"name": "Vorlagen Projekt"}).json()["id"]
TT = F.post(B + "/api/tasks", json={"list_id": TL, "title": "Mit Datei"}).json()["id"]
check(F.post(B + f"/api/tasks/{TT}/attachments", files={"file": ("plan.txt", b"der Vorlagen Plan\n", "text/plain")}).ok, "setup: the file of the task")
r = F.post(B + "/api/templates", json={"list_id": TL, "name": "Vorlage mit Datei"})
check(r.ok and r.json()["skipped_files"] == [], f"setup: the template {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- #3099: the account export
raw = acct_export(F)
z = zipfile.ZipFile(io.BytesIO(raw))
names = z.namelist()
man = json.loads(z.read("manifest.json"))
P = "personal-office/"
check(P + "office/company.json" in names and P + "clients.json" in names and P + "office/documents.json" in names, f"#3099 the office is in the file {[n for n in names if n.startswith(P)][:12]}")
check((man.get("personal_office") or {}).get("rows"), f"#3099 the manifest names it {man.get('personal_office')}")
comp = json.loads(z.read(P + "office/company.json"))
check("Frida Studio" in json.dumps(comp), "#3099 the company data read in plain text")
check(any(n.startswith(P + f"files/store/{R1}-") for n in names), "#3099 the receipt file is in the file")
listed = {f["path"] for f in man["files"]}
check(P + "office/company.json" in listed and "checksum.sha256" in names and P + "office/company.json" in z.read("checksum.sha256").decode(), "#3099 office parts are in the manifest and the checksums")
check(not any("the organisation's office" in x for x in man["not_included"]), "#3099 no pointer to an export a person without organisation does not have")
check(F.get(B + "/api/account/export").ok, "the state of the export")
iid = upload(F, raw, "konto.zip")
j = wait(F, iid)
check(j.get("state") == "preview", f"#3099 the import reads the file {j.get('state')} {j.get('error')}")
pv = j.get("preview") or {}
# 2.464.0 (#3865): the import reads them now (before: named as staying behind, #3134)
check(not any("templates" in x["what"] for x in pv.get("not_taken", [])), f"#3865 the files of templates come along {pv.get('not_taken')}")
check(pv.get("office_copy") is True and any(x["what"] == "Office" for x in pv.get("not_taken", [])), f"#3099 the preview names the office {pv.get('not_taken')}")
F.delete(B + f"/api/account/import/{iid}")

wf = json.loads(z.read("data/wiki_files.json"))
check(wf and any(n.startswith("files/wiki_files/") for n in names) and wf[0].get("file"), f"#3099 the file of the knowledge page {wf}")
tf = json.loads(z.read("data/template_files.json"))
check(len(tf) == 1 and tf[0]["name"] == "plan.txt" and "path" not in tf[0] and z.read(tf[0]["file"]) == b"der Vorlagen Plan\n", f"#3134 the file of the template, readable {tf}")
check(not any(n.startswith(f"files/private_files/{GONE}-") for n in names), "a file in the trash stays out")

# ---------------------------------------------------------------- 2.464.0 (#3865): the files of templates come back with the import


dbx_w = dbxm.connect(DATA)


def imp(s, quota=None):
    iid = upload(s, raw, "konto.zip")
    check(wait(s, iid).get("state") == "preview", "#3865 the preview")
    dbx_w.execute("UPDATE users SET storage_quota_mb=? WHERE id=?", (quota, GID))  # after the upload: it counts against the storage too
    ok(s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": "private", "people": {}}), "#3865 the import starts")
    return wait(s, iid)


def tfiles():
    return dbx("SELECT id, template_id, node_key, name, size, path, scan FROM template_files WHERE user_id=? ORDER BY id", (GID,))


L0 = G.post(B + "/api/lists", json={"name": "Voll"}).json()["id"]
T0 = G.post(B + "/api/tasks", json={"list_id": L0, "title": "Gross"}).json()["id"]
for i in range(3):
    ok(G.post(B + f"/api/tasks/{T0}/attachments", files={"file": (f"gross{i}.bin", os.urandom(400000), "application/octet-stream")}), "#3865 setup: the storage fills")
j = imp(G, 1)
check(j.get("state") == "stopped" and not tfiles(), f"#3865 a full storage keeps the file of the template out {j.get('state')} {tfiles()}")
# 2.905.0 (#5288): templates.owner_id (was user_id)
check(one("SELECT COUNT(*) FROM templates WHERE owner_id=?", (GID,)) == 1, "#3865 the template itself came")
check(any("storage is full" in w["text"] for w in j["result"]["warnings"]), f"#3865 and it is named {j['result']['warnings']}")
ok(G.post(B + f"/api/imports/{j['result']['import_id']}/undo", json={}), "#3865 setup: undo of the full run")
dbx_w.execute("UPDATE users SET storage_quota_mb=NULL WHERE id=?", (GID,))

j = imp(G)
check(j.get("state") == "done" and (j["result"]["created"] or {}).get("template_files") == 1, f"#3865 the import takes the file {j.get('state')} {j.get('result')}")
tr0 = tfiles()
# 2.905.0 (#5288): templates.owner_id (was user_id)
gtpl = one("SELECT id FROM templates WHERE owner_id=?", (GID,))
check(len(tr0) == 1 and tr0[0]["name"] == "plan.txt" and tr0[0]["template_id"] == gtpl and tr0[0]["path"].startswith(f"tplfiles/{gtpl}/"), f"#3865 the row on the new template {tr0}")
gfull = os.path.join(DATA, "attachments", tr0[0]["path"])
with open(gfull, "rb") as fh:
    check(b"der Vorlagen Plan" not in fh.read(), "#3865 sealed on disk")
r = ok(G.post(B + f"/api/templates/{gtpl}/apply", json={"name": "Aus Import"}), "#3865 the template is used")
fid = dbx("SELECT a.id FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.name='plan.txt'", (r["list_id"],))
check(fid and G.get(B + f"/api/attachments/{fid[0][0]}").content == b"der Vorlagen Plan\n", f"#3865 the task from the template has the file {fid}")
j = imp(G)
check(len(tfiles()) == 1, f"#3865 a second import of the same file adds no copy {tfiles()}")
# a template of an earlier import without its file (imported before #3865): the file joins it, its undo takes only the file
dbx_w.execute("DELETE FROM template_files WHERE user_id=?", (GID,))
j = imp(G)
tr1 = tfiles()
check(len(tr1) == 1 and tr1[0]["template_id"] == gtpl, f"#3865 the file comes to the earlier template {tr1}")
ok(G.post(B + f"/api/imports/{j['result']['import_id']}/undo", json={}), "#3865 undo of that run")
check(not tfiles() and one("SELECT COUNT(*) FROM templates WHERE id=?", (gtpl,)) == 1 and not os.path.exists(os.path.join(DATA, "attachments", tr1[0]["path"])), "#3865 its undo takes the file, the template stays")
for x in reversed(dbx("SELECT id FROM imports WHERE user_id=? AND undone_at IS NULL ORDER BY id", (GID,))):
    G.post(B + f"/api/imports/{x['id']}/undo", json={})
# 2.905.0 (#5288): templates.owner_id (was user_id)
check(one("SELECT COUNT(*) FROM templates WHERE owner_id=?", (GID,)) == 0, "#3865 undoing the first run takes the template")
j = imp(G)
gfull = os.path.join(DATA, "attachments", tfiles()[0]["path"])
check(os.path.exists(gfull), "#3865 the file is there again")
ok(G.post(B + f"/api/imports/{j['result']['import_id']}/undo", json={}), "#3865 undo")
check(not tfiles() and not os.path.exists(gfull), "#3865 the undo with the template leaves no file behind")
# 2.480.0 (#3470): every version of the private files is in the file now; only the histories stay out
check(not any("older versions" in x for x in man["not_included"]) and any("history of your knowledge pages" in x for x in man["not_included"]),
      f"#3099 #3470 the manifest leaves neither the page files nor older file versions out {man['not_included']}")

# Mandantengrenze: an account export with the office option never carries another person's rows
check(not any(f"{FOREIGN}-" in n for n in names), "#3099 another person's node stays out, also when an office row names it")

# ---------------------------------------------------------------- #3099: the office archive -> a second person
_j, ox = ox_export(F, 0)
check(ox[:13] == b"KALMIDO-ORGX\n", "the office archive stays encrypted with the key")
rk = F.post(B + "/api/orgs/0/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(rk, "recovery key")
iid = upload(G, ox)
j = wait(G, iid)
check(j.get("state") == "key", f"asks for the recovery key {j.get('state')}")
check(G.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
j = wait(G, iid)
check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
r = G.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": "private", "people": {}})
check(r.status_code == 202, f"import starts {r.text[:200]}")
j = wait(G, iid)
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')} {(j.get('result') or {}).get('warnings')}")
PG = one("SELECT id FROM orgs WHERE personal_of=?", (GID,))
nid = one("SELECT node_id FROM office_cash_entries WHERE org_id=?", (PG,))
check(nid and nid != FILED, f"#3099 the cash entry points at its file again {nid}")
check(one("SELECT owner_id FROM fs_nodes WHERE id=?", (nid,)) == GID and one("SELECT org_id FROM fs_nodes WHERE id=?", (nid,)) is None, "#3099 the file is gerd's")
# 2.506.0 (#4299): only what this run brought: the files of the runs undone above lie in the trash now
RUN_NODES = [x[1] for x in json.loads(one("SELECT created FROM imports WHERE id=?", (j["result"]["import_id"],)))["oi"] if x[0] == "fs_nodes"]
gnames = [x[0] for x in dbx(f"SELECT name FROM fs_nodes WHERE owner_id=? AND kind='file' AND id IN ({','.join('?' * len(RUN_NODES))})", (GID, *RUN_NODES))]
check("taxi-beleg.pdf" in gnames and "kasse-bild.pdf" in gnames, f"#3099 the receipts came along {gnames}")
check("weg-beleg.pdf" not in gnames and "notiz.txt" not in gnames and "bert-geheim.pdf" not in gnames, f"#3099 trash, other documents and another person's stay out {gnames}")
check(one("SELECT receipt_node_id FROM office_equipment WHERE org_id=?", (PG,)) is None, "#3099 the foreign node's reference is empty")
check(one("SELECT category FROM rc_receipts r JOIN fs_nodes n ON n.id=r.node_id WHERE n.owner_id=? AND n.name='taxi-beleg.pdf'", (GID,)) == "Travel", "#3099 the receipt stays a receipt")

# ---------------------------------------------------------------- review: one file that does not open never stops the copy
BROKEN = receipt(F, "kaputt.pdf", "Kaputt Beleg")
vp = one("SELECT path FROM fs_versions WHERE node_id=?", (BROKEN,))
full = os.path.join(DATA, "attachments", vp)
check(open(full, "rb").read(4) == b"KENC", "setup: the file is sealed")
whole = open(full, "rb").read()
with open(full, "r+b") as f:
    f.truncate(20)
raw = acct_export(F)
z = zipfile.ZipFile(io.BytesIO(raw))
man = json.loads(z.read("manifest.json"))
bad = [x for x in man["locked_files"] if x.get("name") == "kaputt.pdf"] + [x for x in man["missing"] if x["file"].endswith("kaputt.pdf")]  # 2.363.2 (#3106): the private copy is under "missing"
check(len(bad) >= 2 and not any("kaputt" in n for n in z.namelist()), f"#3099 the broken file is named, the export runs {man['locked_files']} {man['missing']}")
check(any(n.startswith(P + f"files/store/{R1}-") for n in z.namelist()), "#3099 the other files are there")
with open(full, "wb") as f:  # whole again (a row delete here can meet the server's own background work)
    f.write(whole)

# ---------------------------------------------------------------- #3105: the retention export
r = su_get(F, B + "/api/retention/me/export.zip")
check(r.ok and r.content[:2] == b"PK", f"retention ZIP {r.status_code}")
z = zipfile.ZipFile(io.BytesIO(r.content))
names = z.namelist()
for arc, needle in (("books/procedure-documentation.csv", "Verfahren Frida"), ("books/number-ranges.csv", "invoice"), ("invoices/dunning.csv", "doc_id"),
                    ("contracts/agreements.csv", "Versicherung Studio")):
    check(arc in names and needle in z.read(arc).decode("utf-8-sig"), f"#3105 {arc} {[n for n in names if n.endswith('.csv')][:30]}")
so = z.read("invoices/signoffs.csv").decode("utf-8-sig")
check("Kim Kundin" in so and "203.0.113.9" not in so and "Testbrowser" not in so, f"#3105 the sign-off without the network address {so[:300]}")
# 2.955.0 (#3811): the approval link's token and its hash never go into the CSV (orgexport OX_SECRET_COLS in _clean)
sohead = next(csv.reader(io.StringIO(so), delimiter=";"), [])
check("signer_name" in sohead and not {"token", "token_hash"} & set(sohead), f"#3811 the sign-off CSV without token / token_hash {sohead}")
idx = z.read("00-index.txt").decode()
check("books/" in idx and "contracts/" in idx, "#3105 the index names the new folders")
rows = list(csv.reader(io.StringIO(z.read("books/procedure-documentation.csv").decode("utf-8-sig")), delimiter=";"))
check(len(rows) == 2, f"#3105 one version of the procedure documentation {len(rows)}")

# ---------------------------------------------------------------- 2.370.0 (#2781): files the virus scanner locked stay out, listed
check(any(n.startswith(f"receipts/{R1}-") for n in names), "#2781 setup: the receipt is in the export")
check(json.loads(z.read("manifest.json"))["locked_files"] == [], "#2781 nothing locked: an empty list")
od = os.path.join(DATA, "office", str(PB))
os.makedirs(od, exist_ok=True)
for fn in ("gesperrt-vertrag.pdf", "offen-vertrag.pdf"):
    with open(os.path.join(od, fn), "wb") as f:
        f.write(tiny_pdf(fn))
LCF = dbx("INSERT INTO office_contract_files(org_id, contract_id, name, file, created_at) VALUES(?,1,?,?,?) RETURNING id", (PB, "Vertrag.pdf", "gesperrt-vertrag.pdf", now))[0][0]
dbx("INSERT INTO upload_scan(kind, ref_id, ver, org_id, state, sig, created_at) VALUES('ocf',?,0,?,'infected','Test-Signatur-1',?)", (LCF, PB, now))
RV = one("SELECT cur_version FROM fs_nodes WHERE id=?", (R1,))
dbx("INSERT INTO upload_scan(kind, ref_id, ver, state, sig, created_at) VALUES('fs',?,?,'infected','Test-Signatur-2',?) "
    "ON CONFLICT (kind, ref_id, ver) DO UPDATE SET state='infected', sig='Test-Signatur-2'", (R1, RV, now))
r = su_get(F, B + "/api/retention/me/export.zip")
check(r.ok and r.content[:2] == b"PK", f"#2781 the export runs {r.status_code}")
z = zipfile.ZipFile(io.BytesIO(r.content))
names = z.namelist()
man = json.loads(z.read("manifest.json"))
lock = {(x["area"], x["id"]): x for x in man["locked_files"]}
check("office-files/offen-vertrag.pdf" in names and "office-files/gesperrt-vertrag.pdf" not in names, f"#2781 the locked office file stays out, the other one is in {[n for n in names if n.startswith('office-files')]}")
check(not any(n.startswith(f"receipts/{R1}-") for n in names), "#2781 the locked receipt stays out")
check(lock.get(("ocf", LCF), {}).get("signature") == "Test-Signatur-1" and lock.get(("fs", R1), {}).get("signature") == "Test-Signatur-2", f"#2781 both in locked_files with the reason {man['locked_files']}")
check(not any("gesperrt-vertrag" in m or "taxi-beleg" in m for m in man["missing"]), f"#2781 locked is not missing {man['missing']}")
rc = {x["node_id"]: x for x in csv.DictReader(io.StringIO(z.read("receipts/receipts.csv").decode("utf-8-sig")), delimiter=";")}
check(rc.get(str(R1), {}).get("file") == "", "#2781 the receipt keeps its line in the list, without a file")
check("Test-Signatur-2" in z.read("00-index.txt").decode(), "#2781 the index names it")

# ---------------------------------------------------------------- without the server key
A = start("")
FID, F = freelancer(B, A)
setup_office(F)
PB = one("SELECT id FROM orgs WHERE personal_of=?", (FID,))
R1 = receipt(F, "taxi-beleg.pdf", "Taxi Beleg")
g = F.get(B + "/api/orgs/0/export").json()
check(g.get("enabled") is False, f"#3099 the state says there is no server key {g}")
j, data = ox_export(F, 0)
check(j.get("plain") is True and str(j.get("file", "")).endswith(".zip"), f"#3099 no key: a plain ZIP instead of a 409 {j}")
check(data[:2] == b"PK", f"#3099 the download is that ZIP {data[:16]!r}")
z = zipfile.ZipFile(io.BytesIO(data))
man = json.loads(z.read("manifest.json"))
check("no server key" in man.get("decrypted", ""), f"#3099 the manifest says so {man.get('decrypted')}")
check(any(n.startswith(f"files/store/{R1}-") for n in z.namelist()), "#3099 the receipt is in the plain archive")
GID, G = freelancer(B, A, "gerd")
iid = upload(G, data, "buero.zip")
j = wait(G, iid)
check(j.get("state") == "preview", f"#3099 the plain archive is read without a recovery key {j.get('state')} {j.get('error')}")
r = G.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": "private", "people": {}})
check(r.status_code == 202, f"import starts {r.text[:200]}")
j = wait(G, iid)
check(j.get("state") == "done", f"#3099 the plain archive is imported {j.get('state')} {j.get('error')}")
check(one("SELECT name FROM fs_nodes WHERE owner_id=? AND kind='file'", (GID,)) == "taxi-beleg.pdf", "#3099 the receipt came along")
ORG = ok(A.post(B + "/api/admin/orgs", json={"name": "Alpha Quelle", "admin_id": one("SELECT id FROM users WHERE username='alice'")}), "an organisation").get("id")
j, data = ox_export(A, ORG)
check(j.get("plain") is True and data[:2] == b"PK", f"#3099 an organisation's export too {j}")

print(f"p2362_2_export: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
