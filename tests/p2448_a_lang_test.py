#!/usr/bin/env python3
"""2.448.0 (#3765): whoever reads a text decides its language. Texts kept for later are built for their reader or stored as
key + values. The first admin speaks German here, so a text that silently falls back to them shows.
 - poll: the mail about the chosen time in the language the voter saw when voting; an older vote without one: the owner's
 - invoice series: the reason in the task follows each admin, also from the timer
 - agent card: the person's language, not the agent's (guard: the office context already acts as the person)
 - planned proposal: the title in the language of the person the plan works for
 - import: the stored state keeps key + values, the status answers in the language of who asks
 - history: an encrypted file is stored as the key, the reader's app translates it
 2.454.0 (#3808), the rest of it:
 - invoice series: a failed check of finalising or sending (the missing fields too) follows each admin
 - account import: the areas that stay behind (preview, warning) follow who reads the state
 - wiki import: a check text of the background run follows who reads the state
 - proposal: the title in a task's history is kept as a key, the asker's words stay in title
 The cases without the series run for a person without an organisation (tests/freelancer_fixture.py)."""
# kalmido-suite: fresh
import base64
import email
import email.policy
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, DATA, check, dbx, done, fresh, H, sess, setup, until  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
O = "/api/office"
KENC = b"KENC\x01" + b"\0" * 64


def in_ct(code):
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def speak(s, lg):
    assert s.patch(B + "/api/settings", json={"lang": lg}).ok


def mails(to):
    try:
        rows = [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []
    return [m for m in rows if to in json.dumps(m["to"])]


fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025",
       "KALMIDO_SMTP_TLS": "none", "KALMIDO_MAIL_FROM": "kalmido@example.test"})
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
A = setup()
speak(A, "de")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, Fr = freelancer(B, A)

# ================================================================ poll: each voter in their own language
r = Fr.post(B + "/api/polls", json={"title": "Lunch", "tz": "Europe/Berlin", "options": [
    {"start": "2031-03-10T10:00", "end": "2031-03-10T11:00"}, {"start": "2031-03-11T10:00", "end": "2031-03-11T11:00"}]})
check(r.status_code == 201, "a poll " + r.text[:200])
P = r.json()["poll"]
PATH = "/s/v/" + P["url"].rsplit("/s/v/", 1)[1]
OPT = P["options"][0]["id"]


def voter(lg):
    v = requests.Session()
    v.headers.update({**H, "Accept-Language": lg})
    return v, v.get(B + PATH).text.split('name="stamp" value="', 1)[1].split('"', 1)[0]


def vote(who, name, mail):
    v, stamp = who
    d = {"name": name, "email": mail, "stamp": stamp, f"a{OPT}": "y"}
    r = until(lambda: (lambda x: x if x.status_code == 200 else None)(v.post(B + PATH, data=d)), 15, step=1.2)  # the page's minimum time, few tries: votes are rate limited
    check(r is not None, f"{name} votes")


FV, DV, NV = voter("fr"), voter("de"), voter("nl")
vote(FV, "Anne", "anne@example.com")
vote(DV, "Bert", "bert@example.com")
vote(NV, "Cleo", "cleo@example.com")
langs = dict(dbx("SELECT name, lang FROM sched_poll_votes"))
check(langs == {"Anne": "fr", "Bert": "de", "Cleo": "nl"}, f"the vote keeps the language {langs}")
dbx("UPDATE sched_poll_votes SET lang='' WHERE name='Cleo'")  # a vote of an older version
r = Fr.post(B + f"/api/polls/{P['id']}/decide", json={"option_id": OPT, "mail": True})
check(r.ok and r.json()["mailed"] == 3, "decided, three mails " + r.text[:200])
m = until(lambda: len(mails("@example.com")) >= 3 and True, 20)
check(m, "the mails went out")
sub = {x: str(email.message_from_string(mails(x + "@example.com")[0]["raw"], policy=email.policy.default)["subject"]) if mails(x + "@example.com") else ""
       for x in ("anne", "bert", "cleo")}
check(sub["anne"] == "Date fixée : Lunch", "French voter: French mail " + str(sub))
check(sub["bert"] == "Termin steht: Lunch", "German voter: German mail " + str(sub))
check(sub["cleo"] == "Date set: Lunch", "no language stored: the owner's (English) " + str(sub))

# ================================================================ invoice series: two admins, two languages, one timer
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Admin", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "admin"}).ok
Bo = sess("bob")
for s in (A, Bo):
    assert s.patch(B + "/api/settings", json={"features": FEATURES, "tour": "done", "workspace": f"org:{ORG}"}).ok
speak(Bo, "fr")
A.get(B + O + "/settings")
A.put(B + O + "/settings", json={"company_fields": {"name": "Alpha GmbH", "street": "Weg 1", "zip": "10115", "city": "Berlin", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Example Ltd", "org_id": ORG, "street": "Marktweg 5", "zip": "50667", "city": "Koeln", "country": "DE"}).json()["id"]
Q = A.post(B + O + "/docs", json={"client_id": CL, "project_title": "Retainer"}).json()["id"]
A.put(B + f"{O}/docs/{Q}/items", json={"items": [{"kind": "service", "title": "Care", "qty": 1, "unit": "flat", "rate": 500}]})
TPL = A.post(B + f"{O}/docs/{Q}/invoice", json={}).json()["id"]
r = A.post(B + O + "/series", json={"template_id": TPL, "every": "monthly", "start": date.today().isoformat(), "auto_send": True, "title": "Rente"})
check(r.status_code == 201, "a series " + r.text[:200])
dbx("UPDATE office_inv_series SET created_by=? WHERE id=?", (FID, r.json()["id"]))  # its creator left: every admin of the area hears of it
in_ct("import app\nfrom kalmido.core.db import connect\nfrom kalmido.office import recurring as x\nx._RIN_LAST['at'] = -1e12\n"
      "c = connect()\nx.rin_tick(c)\nc.close()")
t = dict(dbx("SELECT created_by, content FROM tasks WHERE title LIKE '%Rente%'"))
check("Der Kunde hat keine E-Mail-Adresse" in t.get(ALICE, ""), f"the German admin reads German {t}")
check("Le client n’a pas d’adresse e-mail" in t.get(BOB, ""), f"the French admin reads French, whoever came first {t}")

# 2.454.0 (#3808): the same for a check that fails inside finalising (tax number and IBAN are missing here)
dbx("UPDATE clients SET email_invoice='billing@example.com' WHERE id=?", (CL,))
r = A.post(B + O + "/series", json={"template_id": TPL, "every": "monthly", "start": date.today().isoformat(), "auto_send": True, "title": "Zweite"})
check(r.status_code == 201, "a second series " + r.text[:200])
dbx("UPDATE office_inv_series SET created_by=? WHERE id=?", (FID, r.json()["id"]))
in_ct("import app\nfrom kalmido.core.db import connect\nfrom kalmido.office import recurring as x\nx._RIN_LAST['at'] = -1e12\n"
      "c = connect()\nx.rin_tick(c)\nc.close()")
t = dict(dbx("SELECT created_by, content FROM tasks WHERE title LIKE '%Zweite%'"))
check("Vor dem Festschreiben fehlt" in t.get(ALICE, "") and "Steuernummer oder USt-IdNr." in t.get(ALICE, ""), f"#3808: the German admin reads the check in German {t}")
check("Manque avant la clôture" in t.get(BOB, "") and "numéro fiscal" in t.get(BOB, ""), f"#3808: the French admin in French, the field names too {t}")

# ================================================================ agent card: the person reads it
Fr.get(B + O + "/settings")
speak(Fr, "de")
r = Fr.post(B + "/api/my/agents", json={"username": "lang-bot", "display_name": "Lang Bot", "scopes": ["read", "tasks:write", "comments", "office"]})
check(r.status_code == 201, "an agent, it takes over German " + r.text[:200])
AG, AH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
speak(Fr, "fr")
Fr.put(B + O + "/settings", json={"agents_read": 1})
check(Fr.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok, "the office switch of the agent")
r = requests.post(B + "/api/v1/office/letters", headers=AH, json={"subject": "Bonjour", "body": "Texte"})
check(r.status_code == 201, "the agent drafts a letter " + r.text[:200])
chat = json.dumps(Fr.get(B + f"/api/agents/{AG}/chat").json(), ensure_ascii=False)
check("Brouillon de lettre" in chat and "Briefentwurf" not in chat, "the card follows the person " + chat[:300])

# ================================================================ planned proposal: asked without a request
Fr.post(B + "/api/tasks", json={"title": "Call the printer"})
r = Fr.post(B + f"/api/agents/{AG}/schedules", json={"title": "Morning", "freq": "weekdays", "time": "07:30", "tz": "Europe/Berlin", "action": "triage"})
check(r.status_code == 201, "a triage plan " + r.text[:200])
past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
dbx("UPDATE agent_schedules SET next_at=? WHERE id=?", (past, r.json()["id"]))
t = until(lambda: dbx("SELECT title FROM agent_jobs WHERE agent_id=? AND kind='triage'", (AG,)), 30)
check(t and t[0][0] == "Trier le panier", f"the title in the person's language {t}")

# ================================================================ import: the status speaks to who asks
speak(Fr, "de")
JUNK = b"not a zip file " * 8
r = Fr.post(B + "/api/account/import", json={"size": len(JUNK), "name": "x.zip"})
check(r.ok, "an upload " + r.text[:200])
IID = r.json()["id"]
Fr.put(B + f"/api/account/import/{IID}?offset=0", data=JUNK, headers={"Content-Type": "application/octet-stream"})
st = until(lambda: (lambda j: j if j.get("state") == "invalid" else None)(Fr.get(B + f"/api/account/import/{IID}").json()), 30) or {}
check("kein Kalmido-Export" in (st.get("error") or ""), f"German while German {st}")
speak(Fr, "fr")
st = Fr.get(B + f"/api/account/import/{IID}").json()
check("export Kalmido" in (st.get("error") or ""), f"the same state read in French {st}")

# ================================================================ account import: what stays behind (2.454.0, #3808)
def sha(b):
    return hashlib.sha256(b).hexdigest()


def areas_zip():
    entries = {f"data/{t}.json": json.dumps(rows).encode() for t, rows in {"lists": [], "tasks": [], "wiki_pages": [{"id": 1}]}.items()}
    flist = [{"path": p, "size": len(x), "sha256": sha(x)} for p, x in entries.items()]
    m = json.dumps({"format": "kalmido-account", "v": 1, "kalmido_version": "test", "created_at": "2026-10-20T06:00:00Z",
                    "source": {"url": "https://example.com", "hosted": True}, "user": {"id": 1000, "name": "Test Person", "email": "test@example.com"},
                    "tables": {}, "files": flist, "client_encrypted": {}, "export_id": os.urandom(16).hex()}).encode()
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", m)
        z.writestr("checksum.sha256", (f"{sha(m)}  manifest.json\n" + "".join(f"{f['sha256']}  {f['path']}\n" for f in flist)).encode())
        for p, x in entries.items():
            z.writestr(p, x)
    return bio.getvalue()


check(Fr.delete(B + f"/api/account/import/{IID}").ok, "the junk upload goes")
ZIP = areas_zip()
speak(Fr, "de")
r = Fr.post(B + "/api/account/import", json={"size": len(ZIP), "name": "x.zip"})
check(r.ok, "an upload " + r.text[:200])
IID = r.json()["id"]
Fr.put(B + f"/api/account/import/{IID}?offset=0", data=ZIP, headers={"Content-Type": "application/octet-stream"})
st = until(lambda: (lambda j: j if j.get("state") == "preview" else None)(Fr.get(B + f"/api/account/import/{IID}").json()), 60) or {}
left = lambda j: [x["what"] for x in (j.get("preview") or {}).get("not_taken") or []]  # noqa: E731
check("Wissensseiten" in left(st), f"#3808: the preview in German {st}")
speak(Fr, "fr")
st = Fr.get(B + f"/api/account/import/{IID}").json()
check("Pages de connaissances" in left(st), f"#3808: the same preview read in French {left(st)}")
r = Fr.post(B + f"/api/account/import/{IID}/run", json={"target": "private", "people": {}})
check(r.status_code == 202, f"the run starts {r.text[:200]}")
st = until(lambda: (lambda j: j if j.get("state") == "done" else None)(Fr.get(B + f"/api/account/import/{IID}").json()), 60) or {}
speak(Fr, "de")
st = Fr.get(B + f"/api/account/import/{IID}").json()
w = " | ".join(x["text"] for x in (st.get("result") or {}).get("warnings") or [])
check("Diese Bereiche bleiben" in w and "Wissensseiten (1)" in w, f"#3808: the warning written under French, read in German {w}")
imp = Fr.get(B + "/api/imports").json()["imports"][0]["counts"]
check({"what": "Wissensseiten", "count": 1} in imp.get("not_taken", []), f"#3808: the import's record in German too {imp}")

# ================================================================ wiki import: a check of the background run (2.454.0, #3808)
speak(Fr, "de")
r = Fr.post(B + "/api/wiki/import/upload", json={"size": len(JUNK), "name": "x.zip", "space": "private", "replace": False})
check(r.ok, "a wiki upload " + r.text[:200])
WID = r.json()["id"]
Fr.put(B + f"/api/wiki/import/upload/{WID}?offset=0", data=JUNK, headers={"Content-Type": "application/octet-stream"})
st = until(lambda: (lambda j: j if j.get("state") == "failed" else None)(Fr.get(B + f"/api/wiki/import/upload/{WID}").json()), 30) or {}
check(st.get("error") == "Das ist keine ZIP-Datei", f"#3808: German while German {st}")
speak(Fr, "fr")
st = Fr.get(B + f"/api/wiki/import/upload/{WID}").json()
check(st.get("error") == "Ce n'est pas un fichier ZIP", f"#3808: the same state read in French {st}")

# ================================================================ history: the key, the reader's app translates it
tid = Fr.post(B + "/api/tasks", json={"title": "Sealed"}).json()["id"]
r = Fr.put(B + "/api/e2e/keys", json={"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32)},
                                      "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(120)},
                                      "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(120)}})
check(r.ok, "keys set up " + r.text[:200])
r = Fr.post(B + f"/api/tasks/{tid}/enc-attachments", files=[("file", ("encrypted.kenc", KENC, "application/octet-stream"))])
check(r.ok, "an encrypted file " + r.text[:200])
d = dbx("SELECT data FROM activity WHERE task_id=? AND kind='attach'", (tid,))[0][0]
d = json.loads(d) if isinstance(d, str) else d
check(d.get("enc") == 1 and d.get("names") == ["Encrypted file"], f"stored as the key, not the writer's French {d}")

sys.exit(done("p2448_a_lang"))
