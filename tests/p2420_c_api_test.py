#!/usr/bin/env python3
"""2.42.0 (#833) organisation export, stage 1 -- an encrypted archive of one organisation.
 - rights: an organisation admin starts, polls, downloads, deletes; a member 403, the admin of another organisation 404, a
   person without organisation 404, an agent token 401/403 (people only)
 - content: the organisation's list with task, subtask, comment, attachments and the office (company fields with the test
   IBAN, a finalised quotation with its PDF) are in it, decrypted (no "kenc1:" value, no sealed file); a private list of a
   member and the list of another organisation are not; no secrets (password hashes, session / token hashes, the agent
   token, 2FA fields)
 - the tool tools/kalmido_export_decrypt.py opens it with the recovery key (stdin and --key-file), checks the manifest;
   a wrong key, a shortened file and a flipped byte fail; several 1 MiB blocks
 - the office log notes the export; after 24 hours the archive is gone (state + the watchdog's clean-up after a restart)
 - without KALMIDO_SECRET_KEY the export is refused (409, enabled false)
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY and the mode workspaces.
usage: p2420_c_api_test.py <datadir>"""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
TOOL = os.path.join(N, "..", "tools", "kalmido_export_decrypt.py")
TEST_IBAN = "DE89370400440532013000"
FAILS, OKS = [], [0]
TMP = os.path.join(os.path.dirname(os.path.abspath(DATA)), f"p2420c-{os.getpid()}")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(with_key=True, keep=False):
    extra = ["-e KALMIDO_INSTANCE_MODE=workspaces"] + (["-e KALMIDO_SECRET_KEY=" + KEY] if with_key else [])
    env = dict(os.environ, EXTRA=" ".join(extra), **({"KEEP": "1"} if keep else {}))
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


def recovery_key(oid):
    """The organisation's recovery key, read inside the container through core/orgcrypt.py (the value never leaves the test)."""
    code = ("import kalmido\nfrom kalmido.core.db import connect\nfrom kalmido.core.orgcrypt import oc_recovery_key\n"
            f"c = connect()\nprint('RK=' + oc_recovery_key(c, {int(oid)}))\nc.commit()\nc.close()\n")
    r = subprocess.run(["docker", "exec", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
    keys = [x[3:] for x in r.stdout.splitlines() if x.startswith("RK=")]
    assert keys and keys[0], r.stdout[-500:] + r.stderr[-500:]
    return keys[0]


def tool(args, stdin=""):
    return subprocess.run([sys.executable, TOOL, *args], input=stdin, capture_output=True, text=True, timeout=300)


def wait_done(s, oid, secs=120):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/orgs/{oid}/export").json()
        if j.get("state") != "running":
            return j
        time.sleep(0.25)
    return j


os.makedirs(TMP, exist_ok=True)
start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Private")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients", "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AG_TOKEN = ag["token"]
AGH = {"Authorization": "Bearer " + AG_TOKEN, "X-Requested-With": "kalmido"}

# ---------------------------------------------------------------- data: an organisation list, a private list, another organisation
L = A.post(B + "/api/lists", json={"name": "Alpha Projekt", "org_id": ORG}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Orgaufgabe Schnittplan", "list_id": L}).json()["id"]
ST = A.post(B + "/api/tasks", json={"title": "Unteraufgabe Tonmischung", "list_id": L, "parent_id": T}).json()["id"]
check(A.post(B + f"/api/tasks/{T}/comments", json={"body": "Kommentar Abnahme Freitag"}).ok, "comment on the organisation's task")
ATT = b"attachment of the organisation " + os.urandom(16).hex().encode()
r = A.post(B + f"/api/tasks/{T}/attachments", files=[("file", ("plan.txt", ATT, "text/plain"))])
check(r.ok, "attachment uploaded " + r.text[:120])
ATT_ID = max(a["id"] for a in r.json()["attachments"])
BIG = [os.urandom(900 * 1024), os.urandom(900 * 1024)]  # random: the zip cannot shrink them -> several 1 MiB blocks
for i, data in enumerate(BIG):
    check(A.post(B + f"/api/tasks/{T}/attachments", files=[("file", (f"big{i}.bin", data, "application/octet-stream"))]).ok, f"big attachment {i}")
LP = A.post(B + "/api/lists", json={"name": "Privat Tagebuch", "org_id": None}).json()["id"]
A.post(B + "/api/tasks", json={"title": "Privataufgabe Zahnarzt", "list_id": LP})
check(dbx("SELECT org_id FROM lists WHERE id=?", (LP,))[0][0] is None, "the private list has no organisation")
LB = Ca.post(B + "/api/lists", json={"name": "Beta Liste", "org_id": ORG2}).json()["id"]
Ca.post(B + "/api/tasks", json={"title": "Betaaufgabe Fremdorganisation", "list_id": LB})

# office: company fields (bank, tax), a client, a service, a finalised quotation (its PDF in the office folder)
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
O = "/api/office"
r = A.put(B + O + "/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "street": "Testweg 1", "zip": "20457", "city": "Hamburg",
                                                        "country": "de", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
                                                        "bic": "COBADEFFXXX", "bank_name": "Beispielbank"}})
check(r.ok, "company fields saved " + r.text[:160])
SV = A.post(B + O + "/services", json={"name_de": "Schnitt", "name_en": "Editing", "category": "Video", "daily_rate": 1000}).json()["id"]
CL = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "de"}).json()["id"]
r = A.post(B + O + "/docs", json={"project_title": "Imagefilm Export", "client_id": CL})
check(r.status_code == 201, "quotation " + r.text[:160])
DOC = r.json()["id"]
check(A.put(B + f"{O}/docs/{DOC}/items", json={"items": [{"service_id": SV, "qty": 2}]}).ok, "positions")
check(A.post(B + f"{O}/docs/{DOC}/finalize").ok, "quotation finalised")
check(A.get(B + f"{O}/docs/{DOC}/pdf").ok, "PDF of the finalised quotation")
office_files = []
for root, _d, files in os.walk(os.path.join(DATA, "office", str(ORG))):
    office_files += [os.path.join(root, f) for f in files]
check(any(f.endswith(".pdf") for f in office_files), f"the office folder holds the PDF: {office_files}")

# ---------------------------------------------------------------- rights
P = f"/api/orgs/{ORG}/export"
check(Bo.get(B + P).status_code == 403 and Bo.post(B + P).status_code == 403, "member without admin: 403")
check(Ca.get(B + P).status_code == 404 and Ca.post(B + P).status_code == 404, "admin of another organisation: 404")
check(Da.post(B + P).status_code == 404, "person without organisation: 404")
check(requests.post(B + P, headers=AGH).status_code in (401, 403) and requests.get(B + P, headers=AGH).status_code in (401, 403), "agent token: refused")
check(requests.get(B + "/api/v1" + P, headers=AGH).status_code in (403, 404, 405), "no export in the agent API")
j = A.get(B + P).json()
check(j.get("enabled") is True and j.get("state") == "none", f"state before: {j}")

# ---------------------------------------------------------------- the export
r = A.post(B + P)
check(r.status_code == 202 and r.json()["state"] in ("running", "done"), "export started " + r.text[:160])
j = wait_done(A, ORG)
check(j.get("state") == "done" and j.get("file", "").endswith(".kalmido-export") and j.get("bytes", 0) > 1800000, f"export done: {j}")
check(j.get("file", "").startswith("alpha-studio-") and KEY not in j.get("file", ""), "file name: organisation + date, no secret")
check(Bo.get(B + P + "/file").status_code == 403 and Ca.get(B + P + "/file").status_code == 404, "download: member 403, other organisation 404")
r = A.get(B + P + "/file")
check(r.ok and r.content[:13] == b"KALMIDO-ORGX\n" and "attachment" in r.headers.get("Content-Disposition", ""), "download of the archive")
ARC = os.path.join(TMP, "org.kalmido-export")
with open(ARC, "wb") as f:
    f.write(r.content)
check(b"Orgaufgabe" not in r.content and TEST_IBAN.encode() not in r.content and ATT not in r.content, "the archive is encrypted (no plain text)")
st_path = os.path.join(DATA, "exports", str(ORG))
check(os.path.isdir(st_path) and not os.path.isdir(os.path.join(DATA, "attachments", "exports")), "stored below the data folder, exports/<org>")
log = dbx("SELECT user_id, action, target, detail FROM office_doc_log WHERE org_id=? AND action='export' ORDER BY id", (ORG,))
check(any(x[0] == ALICE and x[2] == "org" for x in log), f"office log: who exported (size in the detail): {log}")

# ---------------------------------------------------------------- the tool
RK = recovery_key(ORG)
ZIP = os.path.join(TMP, "org.zip")
r = tool([ARC, "-o", ZIP], stdin=RK + "\n")
check(r.returncode == 0 and os.path.isfile(ZIP) and "entries checked" in r.stdout, "tool opens the archive with the recovery key (stdin) " + r.stdout + r.stderr)
KF = os.path.join(TMP, "key.txt")
with open(KF, "w") as f:
    f.write(RK.lower().replace("-", " "))
r = tool([ARC, "-o", os.path.join(TMP, "org2.zip"), "--key-file", KF])
check(r.returncode == 0, "tool: --key-file, spaces and lower case " + r.stderr)
wrong = base64.b32encode(os.urandom(32)).decode().rstrip("=")
r = tool([ARC, "-o", os.path.join(TMP, "w.zip")], stdin=wrong)
check(r.returncode == 1 and "wrong recovery key" in r.stderr and not os.path.exists(os.path.join(TMP, "w.zip")), "tool: a wrong key fails " + r.stderr)
r = tool([ARC, "-o", os.path.join(TMP, "w.zip")], stdin="not a key")
check(r.returncode == 1, "tool: not a key fails")
raw = open(ARC, "rb").read()
HL = 13 + 4 + int.from_bytes(raw[13:17], "big")  # magic + length + header
NB = (len(raw) - HL - 1) // ((1 << 20) + 16)  # full blocks before the last one
check(NB >= 1, f"the archive has several blocks ({NB + 1})")
for name, data in (("cut", raw[:-1000]),  # cut inside the last block
                   ("cut-block", raw[:HL + NB * ((1 << 20) + 16)]),  # the last block dropped: the one before it is not marked as the last
                   ("swap", raw[:HL] + raw[HL + (1 << 20) + 16:HL + 2 * ((1 << 20) + 16)] + raw[HL:HL + (1 << 20) + 16] + raw[HL + 2 * ((1 << 20) + 16):]),
                   ("flip", raw[:-40] + bytes([raw[-40] ^ 1]) + raw[-39:])):
    p = os.path.join(TMP, name + ".kalmido-export")
    with open(p, "wb") as f:
        f.write(data)
    r = tool([p, "-o", os.path.join(TMP, name + ".zip")], stdin=RK)
    check(r.returncode == 1 and not os.path.exists(os.path.join(TMP, name + ".zip")), f"tool: {name} fails " + r.stderr)

# ---------------------------------------------------------------- the content
z = zipfile.ZipFile(ZIP)
names = set(z.namelist())
man = json.loads(z.read("manifest.json"))
check(man["format"] == "kalmido-org-export" and man["format_version"] == 1 and man["org"]["id"] == ORG and man["kalmido_version"], "manifest head")
check(all(k in names for k in ("lists.json", "tasks.json", "comments.json", "attachments.json", "events.json", "books.json", "members.json",
                               "office/company.json", "office/documents.json", "office/document_items.json", "calendars.json")), f"areas: {sorted(names)[:60]}")
check(set(man["files"]) - {"manifest.json"} == names - {"manifest.json"}, "every entry has a checksum in the manifest")
text = "".join(z.read(n).decode("utf-8") for n in names if n.endswith(".json"))
lists = json.loads(z.read("lists.json"))
check([x["id"] for x in lists] == [L], f"only the organisation's list: {[x['name'] for x in lists]}")
tasks = json.loads(z.read("tasks.json"))
check({x["id"] for x in tasks} == {T, ST} and any(x["parent_id"] == T for x in tasks), "the task and its subtask")
check("Kommentar Abnahme Freitag" in z.read("comments.json").decode(), "the comment")
check("Privat Tagebuch" not in text and "Privataufgabe Zahnarzt" not in text, "the member's private list is not in it")
check("Beta Liste" not in text and "Betaaufgabe Fremdorganisation" not in text and "Carol Other" not in text, "the other organisation is not in it")
check(z.read(f"files/attachments/{ATT_ID}-plan.txt") == ATT, "the attachment, decrypted")
big = sorted(n for n in names if n.startswith("files/attachments/") and n.endswith(".bin"))
check(len(big) == 2 and sorted(z.read(n) for n in big) == sorted(BIG), "the big attachments, unchanged")
pdfs = [n for n in names if n.startswith("files/office/") and n.endswith(".pdf")]
check(pdfs and all(z.read(n)[:5] == b"%PDF-" for n in pdfs), f"the office PDF, decrypted: {pdfs}")
check(not any(z.read(n)[:6] == b"KENC1\n" for n in names if n.startswith("files/")), "no sealed file in the archive")
co = json.loads(z.read("office/company.json"))
check(co and co[0]["iban"] == TEST_IBAN and co[0]["tax_number"] == "12/345/67890", f"company fields in plain text: {co}")
items = json.loads(z.read("office/document_items.json"))
check(items and all("cost_enc" not in x for x in items) and items[0]["doc_id"] == DOC, "document positions, cost in plain text")
check("kenc1:" not in text, "no encrypted field value left")
mem = json.loads(z.read("members.json"))
check({m["id"]: m["role"] for m in mem}.get(ALICE) == "admin" and {m["id"] for m in mem} >= {ALICE, ids["bob"]} and ids["carol"] not in {m["id"] for m in mem},
      f"members with roles: {mem}")
check(all(set(m) <= {"id", "username", "display_name", "email", "kind", "disabled", "role"} for m in mem), "members: no other user fields")
secrets_db = [x[0] for x in dbx("SELECT password_hash FROM users WHERE password_hash IS NOT NULL")] + [x[0] for x in dbx("SELECT token_hash FROM sessions")] \
    + [x[0] for x in dbx("SELECT token_hash FROM api_tokens")]
leaks = [n for n in ("password_hash", "token_hash", "totp_secret", "pw_hash", "p256dh", "hook_secret", "drop_token", "ical_token") if f'"{n}"' in text]
check(not leaks, f"no secret field names: {leaks}")
check(not any(s and s in text for s in secrets_db) and AG_TOKEN not in text and KEY not in text, "no password hash, session / token hash, agent token or server key")
check(man["counts"].get("tasks.json") == 2 and "client_encrypted" in man and man["not_included"], "manifest: counts, client-encrypted, not included")

# delete now -> gone; a second export; 24 hours later the archive is gone
check(A.delete(B + P).ok and A.get(B + P).json()["state"] == "none" and A.get(B + P + "/file").status_code == 404, "delete now")
A.post(B + P)
j = wait_done(A, ORG)
check(j.get("state") == "done", "second export")
sp = os.path.join(DATA, "exports", str(ORG), "state.json")
st = json.load(open(sp))
st["expires_at"] = "2000-01-01T00:00:00+00:00"
with open(sp, "w") as f:
    json.dump(st, f)
check(A.get(B + P).json()["state"] == "none" and A.get(B + P + "/file").status_code == 404, "after 24 hours: no longer offered")
start(keep=True)  # the watchdog's first round after a start cleans up
gone = False
for _ in range(60):
    if not any(f.endswith(".kalmido-export") for f in os.listdir(os.path.join(DATA, "exports", str(ORG)))):
        gone = True
        break
    time.sleep(0.5)
check(gone, "after 24 hours: the file is removed by the clean-up")

# ---------------------------------------------------------------- without the server key: refused
start(with_key=False)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": 1})
assert r.status_code == 201, r.text
G = r.json()["id"]
check(A.get(B + f"/api/orgs/{G}/export").json().get("enabled") is False, "without the server key: enabled false")
r = A.post(B + f"/api/orgs/{G}/export")
check(r.status_code == 409 and "KALMIDO_SECRET_KEY" in r.text and "SELF-HOSTING" in r.text, "without the server key: refused with a hint " + r.text[:200])

shutil.rmtree(TMP, ignore_errors=True)
print(f"p2420_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
