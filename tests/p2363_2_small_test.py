#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.363.2 (#3106): the small rest of the import / export audit. Invented names only (example.com).
 - task CSV: a priority as a number; import records: past the last 20 only those past their undo time go
 - leads, trips, legacy services: readable errors, the row numbers of the spreadsheet
 - contacts: unreadable cards with name and reason, cp1252 fallback, the book's limit says how far the file came
 - calendar: the message tells the causes apart; bank: a wrong field name is no empty file
 - fixed costs: CSV and the sheet with the header row
 - account export (person without organisation): a gone and a broken file are listed in the manifest, a private filed mail
   names its .eml; the organisation export the same, with the pictures, without the mail code of a data protection sheet
 - organisation import: the filed-mail mark of a file store node points at the new mail
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P23632_NOSTART=1 = the server already runs like that).
usage: p2363_2_small_test.py <datadir>"""
# freelancer-matrix: own
# tenant-matrix: own
import base64
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timedelta, timezone

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer
from kt import FAILS, OKS, check, sess, su_get

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def box(code, *args):
    """Python in the app container (the stored files live there)."""
    r = subprocess.run(["docker", "exec", CT, "python", "-c", code, *args], capture_output=True, text=True)
    check(r.returncode == 0, f"the container step works {r.stderr[-400:]}")
    return r.stdout.strip()


def break_files(gone, broken):
    """Removes the stored files gone, makes broken a sealed file that is cut off (paths relative to the attachments' folder)."""
    box("""import json, os, sys
from kalmido.core.config import ATT_DIR
from kalmido.core.orgcrypt import MAGIC
for p in json.loads(sys.argv[1]):
    os.remove(os.path.join(ATT_DIR, p))
for p in json.loads(sys.argv[2]):
    open(os.path.join(ATT_DIR, p), "wb").write(MAGIC + b"x")
""", json.dumps(gone), json.dumps(broken))


def att(s, tid, name):
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, b"invented " + name.encode(), "text/plain")})
    check(r.ok, f"attachment {name}: {r.status_code} {r.text[:200]}")
    return one("SELECT path FROM attachments WHERE task_id=? AND name=?", (tid, name))


def err_of(r):
    try:
        return r.json().get("error") or ""
    except ValueError:
        return ""


def xlsx(sheets):
    """[(name, rows of text cells)] -> the bytes of a small .xlsx (inline strings)."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    types = "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                    for i in range(1, len(sheets) + 1))
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + types + "</Types>",
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8"?><workbook {ns} xmlns:r="{rel}"><sheets>'
        + "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, (n, _r) in enumerate(sheets, 1)) + "</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1)) + "</Relationships>"}
    for i, (_n, rows) in enumerate(sheets, 1):
        body = "".join(f'<row r="{ri}">' + "".join(f'<c r="{chr(65 + ci)}{ri}" t="inlineStr"><is><t>{v}</t></is></c>' for ci, v in enumerate(row)) + "</row>"
                       for ri, row in enumerate(rows, 1))
        files[f"xl/worksheets/sheet{i}.xml"] = f'<?xml version="1.0" encoding="UTF-8"?><worksheet {ns}><sheetData>{body}</sheetData></worksheet>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


def office_small(s, who):
    """What runs the same for an organisation's admin and a person without organisation."""
    # leads: the row in the sheet (title line, blank line), plain words instead of field names
    r = s.post(B + O + "/leads/import", json={"text": f"Name;Company;E-mail;Follow-up;Value\n\nErika {who};Studio;nomail;;\nMax {who};Muster;;gestern;\nEva {who};Muster;;;viel\n"})
    rows = r.json().get("rows") or []
    check(r.ok and [x.get("n") for x in rows] == [3, 4, 5], f"{who}: the leads count the spreadsheet's rows {r.text[:300]}")
    txt = " ".join(x.get("error") or "" for x in rows)
    check(not any(w in txt for w in ("follow_up", ": email", ": value")) and "E-mail" in txt and "Follow-up" in txt and "Value" in txt,
          f"{who}: the leads' errors name the column {txt}")
    # trips: the sheet's row, not the position among the ticked ones
    r = s.post(B + O + "/trips/import", json={"trips": [{"row": 17, "date_from": "nonsense", "date_to": "nonsense", "dest": "Koeln", "people": [{"name": "Rita Reise"}], "purpose": "job"}]})
    check(r.status_code == 400 and "17" in err_of(r), f"{who}: a bad trip names row 17 {r.status_code} {r.text[:200]}")
    # legacy: no technical names; rows above the header count
    r = s.post(B + O + "/legacy/import", json={"clients": [{"row": 5, "name": "Altkunde", "action": "merge", "merge_id": "x"}]})
    check(r.status_code == 400 and "merge_id" not in err_of(r) and "5" in err_of(r), f"{who}: merge_id stays out of the message {r.text[:200]}")
    r = s.post(B + O + "/legacy/import", json={"clients": [{"row": 6, "name": "Altkunde", "action": "wat"}]})
    check(r.status_code == 400 and "action" not in err_of(r) and "6" in err_of(r), f"{who}: action stays out of the message {r.text[:200]}")
    book = xlsx([("Services", [[""], ["Service", "Daily rate"], ["Kamera", "500"]])])
    r = s.post(B + O + "/legacy/preview", files={"file": ("alt.xlsx", book)})
    sv = (r.json().get("services") or [{}]) if r.ok else [{}]
    check(sv[0].get("row") == 3, f"{who}: the service is in row 3 of the sheet {r.status_code} {r.text[:300]}")
    # bank: another field name
    r = s.post(B + O + "/bank/import/preview", files={"file": ("a.csv", b"Datum;Betrag\n01.10.2026;5,00\n")})
    check(r.status_code == 400 and "files" in err_of(r) and "empty" not in err_of(r), f"{who}: the missing field is named {r.status_code} {r.text[:200]}")
    # fixed costs: CSV, and the sheet with the header row instead of the first one
    r = s.post(B + O + "/fixed-costs/import/preview", files={"file": ("kosten.csv", "Name;Betrag;Monat\nMiete;800;0\n".encode())})
    check(r.ok and [x.get("label") for x in r.json().get("rows") or []] == ["Miete"], f"{who}: fixed costs from CSV {r.status_code} {r.text[:300]}")
    wb = xlsx([("Deckblatt", [["Kosten 2026"]]), ("Kosten", [["Name", "Betrag", "Monat"], ["Miete", "800", "0"]])])
    r = s.post(B + O + "/fixed-costs/import/preview", files={"file": ("kosten.xlsx", wb)})
    check(r.ok and [x.get("label") for x in r.json().get("rows") or []] == ["Miete"], f"{who}: the sheet with the header row {r.status_code} {r.text[:300]}")


def contacts_small(s, uid, org):
    bid = s.post(B + "/api/books", json={"name": "Importe", "org_id": org}).json()["id"]
    vcf = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Jürgen Müller €\r\nEND:VCARD\r\nBEGIN:VCARD\r\nVERSION:3.0\r\nNOTE:nur Notiz\r\nEND:VCARD\r\n"
    r = s.post(B + f"/api/books/{bid}/import", files={"file": ("a.vcf", vcf.encode("cp1252"))})
    j = r.json()
    check(r.ok and j.get("created") == 1 and j.get("errors") == 1 and (j.get("bad") or [{}])[0].get("reason"), f"the unreadable card has a reason {r.text[:300]}")
    check(one("SELECT fn FROM contacts WHERE book_id=?", (bid,)) == "Jürgen Müller €", "cp1252: the Euro sign comes through")
    now = datetime.now(timezone.utc).isoformat()
    dbx("""INSERT INTO contacts(book_id, uid, href, fn, created_by, created_at, updated_at)
           SELECT ?, 'seed-' || g, 'seed-' || g || '.vcf', 'Seed', ?, ?, ? FROM generate_series(1, 19998) g""", (bid, uid, now, now))
    many = "".join(f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:limit-{i}\r\nFN:Grenze {i}\r\nEND:VCARD\r\n" for i in range(3))
    r = s.post(B + f"/api/books/{bid}/import", files={"file": ("b.vcf", many.encode())})
    check(r.status_code == 409 and err_of(r).rstrip().endswith(": 1"), f"the limit says how far the file came {r.status_code} {r.text[:200]}")


def calendar_small(s):
    cal = s.post(B + "/api/evcals", json={"name": "Termine", "org_id": None}).json()["id"]
    head = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Example//EN\r\n"
    good = "BEGIN:VEVENT\r\nUID:a@example.com\r\nDTSTAMP:20261001T000000Z\r\nDTSTART:20261002T090000Z\r\nSUMMARY:Probe\r\nEND:VEVENT\r\n"
    said = {}
    for key, text in (("cut", head + good), ("none", head + "END:VCALENDAR\r\n"), ("open", head + "BEGIN:VEVENT\r\nUID:b@example.com\r\nEND:VCALENDAR\r\n")):
        r = s.post(B + f"/api/evcals/{cal}/import", files={"file": ("x.ics", text.encode())})
        check(r.status_code == 400, f"calendar {key}: refused {r.status_code} {r.text[:200]}")
        said[key] = err_of(r)
    check(len(set(said.values())) == 3 and "end" in said["cut"] and "no events" in said["none"], f"three causes, three messages {said}")


def imports_keep(s, uid):
    """More than IMPORT_KEEP records: the ones that can still be undone stay, whatever their position."""
    now = datetime.now(timezone.utc)
    fresh_at, old_at = now.isoformat(), (now - timedelta(hours=30)).isoformat()
    for i in range(5):
        dbx("INSERT INTO imports(user_id, source, file_name, created_at) VALUES(?,?,?,?)", (uid, "csv", f"frisch{i}.csv", fresh_at))
    for i in range(30):
        dbx("INSERT INTO imports(user_id, source, file_name, created_at) VALUES(?,?,?,?)", (uid, "csv", f"alt{i}.csv", old_at))
    r = s.post(B + "/api/import/csv", files={"file": ("zahl.csv", b"Title,Priority\nDrei,3\nFuenf,5\nWort,high\nUnklar,9\n")}, data={"dry_run": "0"})
    check(r.ok, f"the import works {r.status_code} {r.text[:300]}")
    pr = {x["title"]: x["priority"] for x in dbx("SELECT title, priority FROM tasks WHERE title IN ('Drei','Fuenf','Wort','Unklar')")}
    check(pr == {"Drei": 3, "Fuenf": 5, "Wort": 5, "Unklar": 0}, f"#3106: priorities as numbers {pr}")
    rows = s.get(B + "/api/imports").json()["imports"]
    names = [x["file_name"] for x in rows]
    check(all(f"frisch{i}.csv" in names for i in range(5)), f"the imports that can still be undone stay {len(names)}")
    check(one("SELECT COUNT(*) FROM imports WHERE user_id=? AND file_name LIKE 'alt%'", (uid,)) == 19, "past the last 20 only the expired ones go")
    check(sum(1 for x in rows if x["can_undo"]) >= 6, "the list offers all of them for undo")


def wait_upload(s, iid, secs=240):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "a.kalmido-export"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


# ---------------------------------------------------------------- server, people
if not os.environ.get("P23632_NOSTART"):
    env = dict(os.environ, EXTRA=f"-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
orgs = {}
for name in ("Alpha Quelle", "Gamma Leer"):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE})
    assert r.status_code == 201, r.text
    orgs[name] = r.json()["id"]
ORG, ORG2 = orgs["Alpha Quelle"], orgs["Gamma Leer"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)

# ---------------------------------------------------------------- imports, as organisation and as a person without one (P4)
office_small(A, "org")
office_small(Fr, "free")
contacts_small(Fr, FID, None)
calendar_small(Fr)
imports_keep(Fr, FID)

# ---------------------------------------------------------------- account export of a person without organisation
LF = Fr.post(B + "/api/lists", json={"name": "Frei"}).json()["id"]
TF = Fr.post(B + "/api/tasks", json={"list_id": LF, "title": "Mit Dateien"}).json()["id"]
keep, gone, broken = att(Fr, TF, "bleibt.txt"), att(Fr, TF, "weg.txt"), att(Fr, TF, "kaputt.txt")
check(Fr.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("mail.eml", b"From: kunde@example.com\n\nHallo\n")}).ok, "the .eml in the private store")
EML = one("SELECT id FROM fs_nodes WHERE owner_id=? AND name='mail.eml'", (FID,))
NOW = datetime.now(timezone.utc).isoformat()
dbx("""INSERT INTO hub_mails(owner_id, ws, message_id, from_addr, subject, body, created_at, eml_id, files) VALUES(?,?,?,?,?,?,?,?,?)""",
    (FID, f"u{FID}", "<p1@example.com>", "kunde@example.com", "Hallo", "Text", NOW, EML, json.dumps([EML])))
break_files([gone], [broken])
r = Fr.post(B + "/api/account/export")
check(r.status_code == 202, f"account export started {r.text[:200]}")
j = {}
for _ in range(240):
    j = Fr.get(B + "/api/account/export").json()
    if j.get("state") != "running":
        break
    time.sleep(0.25)
check(j.get("state") == "done" and j.get("missing") == 2, f"#3106: the export ends, two files are counted {j}")
r = su_get(Fr, B + "/api/account/export/file")
z = zipfile.ZipFile(io.BytesIO(r.content))
man = json.loads(z.read("manifest.json"))
why = {m["file"].rsplit("-", 1)[-1]: m["reason"] for m in man.get("missing") or []}
check(why == {"weg.txt": "not_found", "kaputt.txt": "unreadable"}, f"#3106: the manifest names both {man.get('missing')}")
check(any(n.endswith("bleibt.txt") for n in z.namelist()), "the intact file is in the ZIP")
hm = json.loads(z.read("data/hub_mails.json"))
check(len(hm) == 1 and hm[0].get("eml_file", "").endswith("mail.eml") and hm[0].get("eml_file") in z.namelist()
      and hm[0].get("attachment_files") == [hm[0].get("eml_file")] and "eml_id" not in hm[0] and "files" not in hm[0],
      f"#3106: a private filed mail names its files by path {hm}")

# ---------------------------------------------------------------- organisation export
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
LO = A.post(B + "/api/lists", json={"name": "Projekt", "org_id": ORG}).json()["id"]
TO = A.post(B + "/api/tasks", json={"list_id": LO, "title": "Mit Datei"}).json()["id"]
okp, badp = att(A, TO, "gut.txt"), att(A, TO, "defekt.txt")
FD = A.post(B + "/api/files/folders", json={"name": "Abgelegt", "space": f"org:{ORG}"}).json()["id"]
check(A.post(B + "/api/files/upload", data={"parent_id": FD}, files={"file": ("abgelegt.txt", b"invented mail file")}).ok, "a filed file")
NODE = one("SELECT id FROM fs_nodes WHERE name='abgelegt.txt' AND org_id=?", (ORG,))
MAIL = dbx("""INSERT INTO hub_mails(org_id, owner_id, ws, message_id, from_addr, subject, body, created_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id""",
           (ORG, ALICE, f"o{ORG}", "<o1@example.com>", "kunde@example.com", "Abgelegt", "Text", NOW))[0][0]
dbx("UPDATE fs_nodes SET hub_mail_id=? WHERE id=?", (MAIL, NODE))
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins", "email": "eins@example.com", "org_id": ORG}).json()["id"]
dbx("""INSERT INTO office_privacy_sheets(org_id, client_id, kind, code, code_hash, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)""",
    (ORG, CL, "info", "sealed-code-example", "hash-example", ALICE, NOW, NOW))
break_files([], [badp])
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, f"organisation export started {r.text[:200]}")
xs = {}
for _ in range(480):
    xs = A.get(B + f"/api/orgs/{ORG}/export").json()
    if xs.get("state") not in ("running", "queued"):
        break
    time.sleep(0.25)
check(xs.get("state") == "done" and xs.get("missing") == 1, f"#3106: one broken file does not end the export {xs}")
OX = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
_spec = importlib.util.spec_from_file_location("kx", os.path.join(N, "..", "tools", "kalmido_export_decrypt.py"))
KX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(KX)
with tempfile.TemporaryDirectory() as d:
    src, dst = os.path.join(d, "a.kalmido-export"), os.path.join(d, "a.zip")
    with open(src, "wb") as f:
        f.write(OX)
    KX.decrypt(src, dst, KX.parse_key(RK))
    with zipfile.ZipFile(dst) as zx:
        mx = json.loads(zx.read("manifest.json"))
        sheets = json.loads(zx.read("office/privacy_sheets.json"))
check([(m["reason"], m["file"].endswith("defekt.txt")) for m in mx.get("missing") or []] == [("unreadable", True)], f"#3106: the manifest names the broken file {mx.get('missing')}")
check(len(sheets) == 1 and sheets[0].get("code") == "" and sheets[0].get("code_hash") == "", f"#3106: the mail code stays out {sheets}")

# ---------------------------------------------------------------- organisation import: the mark of the filed mail
iid = upload(A, OX)
wait_upload(A, iid)
check(A.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": RK}).status_code == 202, "the recovery key is taken")
j = wait_upload(A, iid)
check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
r = A.post(B + f"/api/account/import/{iid}/run", json={"target": ORG2, "people": {}, "again": True})
check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
j = wait_upload(A, iid)
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')}")
NM = one("SELECT id FROM hub_mails WHERE org_id=?", (ORG2,))
mark = one("SELECT hub_mail_id FROM fs_nodes WHERE org_id=? AND name='abgelegt.txt'", (ORG2,))
check(NM and mark == NM and NM != MAIL, f"#3106: the node carries the new mail's id {NM} {mark} (old {MAIL})")

if FAILS:
    print(subprocess.run(["docker", "logs", "--tail", "60", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout[-6000:], flush=True)
print(f"p2363_2_small: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
