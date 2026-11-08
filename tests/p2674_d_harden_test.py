#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.674.0 D (#4382): the 14 low findings of audit #2483, each with a test that is red without its fix. Own container with a
server key and a mail-in address (no IMAP server needed: mails are handed to the import functions directly). Invented data.
freelancer-matrix: office, files, wiki, docs
 - 1 a sent letter's PDF is the filed original (version 1) in a sandbox: a later version of the filed node never shows
   (organisation and a person without organisation)
 - 2 a shared knowledge page shows only raster pictures of the file store, by their bytes: a version marked SVG, a text file
   marked PNG -> 404 (was: every image/* type)
 - 3 a read-only member of the organisation reads a client's mail address but cannot make, renew or delete it; a member can
 - 4 "Send test" of a webhook / channel to a host no admin allowed: one code "unreachable", no milliseconds
 - 5 new plus addresses (tasks, hub, documents) are stored sealed + their SHA-256, the plain token is nowhere in the row;
   a mail finds them by the hash; a row of an older version (plain token, no hash) still works
 - 6 Paperless-ngx / Karakeep refuse http:// to a host no admin allowed when saving, an internal address keeps its old hint;
   a stored http:// address fails with the clear code needs_https when used (Paperless, newsletter, Karakeep)
 - 7 a message to a running agent job needs the right to address the agent in the task's project (agent_usable)
 - 8 GET /me/app-passwords needs "account"; team chat files need "attachments:read"; an agent chat file stays open to the
   agent with "read", a person's read-only token needs "attachments:read"; the day plan shows events as "Busy" without
   the calendar permission
 - 9 an office document for an agent filters its linked documents by the agent's list restriction (not the person's)
 - 10 a read-only agent token sends no Playbook proposal (403)
 - 11 the API's agent audit route keeps the hosted operator filter (op_own_agents) of the web route
 - 12 a receipt fetcher key runs out after a year; a key of an older version gets its year at its next use
 - 13 a table proposal without for_user_id goes only to a person who may address the agent
 - 14 the photo location switch says what switching it off shares (all five languages)
usage: p2674_d_harden_test.py <datadir>"""
import base64
import hashlib
import json
import os
import struct
import subprocess
import sys
import zlib
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, dbx, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.docker_logs_on_first_fail()
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_MAIL_ADDRESS": "tasks@example.test",
              "KALMIDO_IMAP_HOST": "127.0.0.1", "KALMIDO_IMAP_PORT": "1143", "KALMIDO_IMAP_SSL": "0", "KALMIDO_IMAP_USER": "kalmido",
              "KALMIDO_IMAP_PASSWORD": "secret", "KALMIDO_IMAP_INTERVAL": "3600"}, prefix="P2674D")
V = B + "/api/v1"
FEAT = "cal,events,collab,comments,files,docs,office,clients,wiki,reading,sheets"


def py(code):
    """Python inside the app container -> the last JSON line it printed."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=300)
    if r.returncode:
        print("PY FAILED:", r.stdout[-2000:], r.stderr[-3000:], flush=True)
    for ln in reversed((r.stdout or "").splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)
    return {}


def png(w=2, h=2):
    raw = b"".join(b"\x00" + b"\x80\x40\xc0" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def upload(s, name, data, mime, **form):
    r = s.post(B + "/api/files/upload", data=form, files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def bearer(tok):
    return {"Authorization": "Bearer " + tok}


A = kt.setup()
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
uid = {}
for u, role in (("bob", "member"), ("rita", "readonly")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ri = sess("bob"), sess("rita")
for s in (Bo, Ri):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office, files, wiki, docs

# ================================================================== 1: the letter PDF
FOREIGN = b"%PDF-1.4\n% P2674D-FOREIGN-VERSION\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
for who, s in (("org", A), ("freelancer", Fr)):
    s.put(B + "/api/office/settings", json={"lang": "de", "company_fields": {"name": "Beispiel GmbH", "street": "Musterweg 1",
                                                                           "zip": "12345", "city": "Musterstadt", "country": "DE"}})
    r = s.post(B + "/api/office/letters", json={"rcpt_name": "Beispielkunde AG", "rcpt_address": "Hauptstr. 2\n54321 Beispielort",
                                                "subject": "Brief 2674", "body": "Sehr geehrte Damen und Herren,\n\nText."})
    check(r.status_code == 201, f"1 {who}: letter created {r.text[:200]}")
    lid = r.json().get("id")
    r = s.post(B + f"/api/office/letters/{lid}/sent", json={})
    nid = r.json().get("node_id") if r.ok else None
    check(r.ok and nid, f"1 {who}: sent, the PDF filed {r.status_code} {r.text[:200]}")
    p1 = s.get(B + f"/api/office/letters/{lid}/pdf")
    check(p1.ok and p1.content.startswith(b"%PDF-") and "sandbox" in p1.headers.get("Content-Security-Policy", ""),
          f"1 {who}: the PDF inline in a sandbox ({p1.status_code} {p1.headers.get('Content-Security-Policy')})")
    r = s.post(B + f"/api/files/nodes/{nid}/versions", files={"file": ("brief.pdf", FOREIGN, "application/pdf")})
    check(r.status_code == 201, f"1 {who}: someone with edit puts a new version under the filed node {r.status_code} {r.text[:200]}")
    p2 = s.get(B + f"/api/office/letters/{lid}/pdf")
    check(p2.ok and b"P2674D-FOREIGN" not in p2.content and p2.content == p1.content,
          f"1 {who}: the letter still shows the filed original, not the new version")

# ================================================================== 2: pictures of shared knowledge pages
IMG = upload(Fr, "plan.png", png(), "image/png", space="private")
SVG = upload(Fr, "logo.png", png(3, 3), "image/png", space="private")
TXT = upload(Fr, "notiz.txt", b"keine Grafik", "text/plain", space="private")
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "P2674/Bilder",
                                         "body": f"![a](/api/files/nodes/{IMG}/content)\n\n![b](/api/files/nodes/{SVG}/content)\n\n"
                                                 f"![c](/api/files/nodes/{TXT}/content)\n"})
assert r.status_code == 201, r.text
PID = r.json()["id"]
r = Fr.post(B + "/api/wiki/shares", json={"page_id": PID, "kind": "link", "images": True})
T1 = r.json().get("url", "").rsplit("/", 1)[-1]
check(r.status_code == 201 and T1, "2: a public link with pictures " + r.text[:200])
q = requests.get(B + f"/s/w/{T1}/img/{PID}/{IMG}")
check(q.ok and q.content.startswith(b"\x89PNG") and q.headers.get("Content-Type", "").startswith("image/png"), f"2: a PNG still comes ({q.status_code})")
dbx("UPDATE fs_versions SET mime='image/svg+xml' WHERE node_id=?", (SVG,))
dbx("UPDATE fs_nodes SET mime='image/svg+xml' WHERE id=?", (SVG,))
check(requests.get(B + f"/s/w/{T1}/img/{PID}/{SVG}").status_code == 404, "2: a file store picture marked SVG never comes (was: every image/*)")
dbx("UPDATE fs_versions SET mime='image/png' WHERE node_id=?", (TXT,))
dbx("UPDATE fs_nodes SET mime='image/png' WHERE id=?", (TXT,))
check(requests.get(B + f"/s/w/{T1}/img/{PID}/{TXT}").status_code == 404, "2: a file marked PNG whose bytes are none: 404")

# ================================================================== 3: a client's mail address needs the write right
CID = A.post(B + "/api/clients", json={"name": "Kunde 2674", "org_id": ORG}).json()["id"]
check(any(x["id"] == CID for x in Ri.get(B + "/api/clients").json().get("clients", [])), "3: the read-only member sees the client")
r = Ri.post(B + "/api/hubmail/address", json={"client_id": CID})
check(r.status_code == 403, f"3: read-only cannot make the client's address ({r.status_code})")
r = A.post(B + "/api/hubmail/address", json={"client_id": CID})
ADDR_C = r.json().get("address", "")
check(r.ok and ADDR_C, "3: the admin makes it " + r.text[:200])
r = Ri.post(B + "/api/hubmail/address", json={"client_id": CID})
check(r.ok and r.json().get("address") == ADDR_C, "3: read-only reads the address that is there")
check(Ri.post(B + "/api/hubmail/address", json={"client_id": CID, "renew": True}).status_code == 403, "3: read-only cannot renew it")
check(Ri.delete(B + "/api/hubmail/address", params={"client_id": CID}).status_code == 403, "3: read-only cannot delete it")
check(A.post(B + "/api/hubmail/address", json={"client_id": CID}).json().get("address") == ADDR_C, "3: the address still works after the refusals")
r = Bo.post(B + "/api/hubmail/address", json={"client_id": CID, "renew": True})
check(r.ok and r.json().get("address") and r.json()["address"] != ADDR_C, "3: a member renews it " + r.text[:200])
ADDR_C = r.json().get("address", "")

# ================================================================== 4: one test answer for a host not allowed
r = A.post(B + "/api/me/webhooks", json={"name": "nirgends", "url": "https://p2674d-nowhere.invalid/hook", "events": ["task.created"]})
check(r.status_code == 201, "4: a webhook to a public name " + r.text[:200])
if r.ok:
    t = A.post(B + f"/api/me/webhooks/{r.json()['id']}/test").json()
    check(t.get("ok") is False and t.get("error") == "unreachable" and not t.get("ms") and t.get("status") is None and t.get("error_text"),
          f"4: webhook test: one code, no milliseconds ({t})")
r = A.post(B + "/api/me/channels", json={"kind": "slack", "url": "https://p2674d-nowhere.invalid/hook", "name": "nirgends"})
check(r.status_code in (200, 201), "4: a channel to a public name " + r.text[:200])
if r.ok:
    t = A.post(B + f"/api/me/channels/{r.json()['id']}/test").json()
    check(t.get("ok") is False and t.get("error") == "unreachable" and t.get("error_text") and "ms" not in t, f"4: channel test: one code ({t})")

# ================================================================== 5: plus address tokens sealed + hashed
r = A.post(B + "/api/me/mail/token", json={})
TA = r.json().get("address", "")
r = A.post(B + "/api/hubmail/address", json={"ws": "private"})
TH = r.json().get("address", "")
r = Fr.post(B + "/api/docs/mail", json={"ws": "private"})
TD = r.json().get("address", "")
tok = lambda a: a.split("+", 1)[1].split("@", 1)[0] if "+" in a else ""  # noqa: E731
check(tok(TA) and tok(TH) and tok(TD), f"5: three addresses made ({TA} {TH} {TD})")
for tbl, a in (("mail_tokens", TA), ("hub_tokens", TH), ("doc_mail", TD)):
    t = tok(a)
    rows = dbx(f"SELECT token, token_hash FROM {tbl} WHERE token_hash=?", (hashlib.sha256(t.encode()).hexdigest(),))
    check(len(rows) == 1 and rows[0][0].startswith("v1.") and t not in rows[0][0], f"5 {tbl}: stored sealed with its hash, no plain token ({rows})")
    check(not dbx(f"SELECT 1 FROM {tbl} WHERE token=?", (t,)), f"5 {tbl}: the plain token is in no row")
check(A.get(B + "/api/me/mail").json().get("address") == TA, "5: the settings still show the address")
ADDR_C2 = A.post(B + "/api/hubmail/address", json={"client_id": CID}).json().get("address")
check(ADDR_C2 == ADDR_C, "5: the client's address reads back the same")
dbx("INSERT INTO mail_tokens(token,user_id,list_id,created_at) VALUES(?,?,NULL,?)", ("p2674doldtoken1", FID, "2026-01-01T00:00:00Z"))
dbx("INSERT INTO hub_tokens(token,kind,user_id,org_id,client_id,list_id,created_at) VALUES(?,?,?,NULL,NULL,NULL,?)",
    ("p2674doldtoken2", "inbox", FID, "2026-01-01T00:00:00Z"))
j = py(r'''
import email.message, json, app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.integrations.mail import mail_target
from kalmido.hub import hubmail as H
from kalmido.docs import ingest as I
def msg(to):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "someone@example.com", to, "x"
    m.set_content("x")
    return m
c = connect()
out = {}
with system_ctx(c):
    out["task"] = mail_target(c, msg(%r))[0]
    out["task_old"] = mail_target(c, msg("tasks+p2674doldtoken1@example.test"))[0]
    out["task_wrong"] = mail_target(c, msg("tasks+p2674dnotatoken@example.test"))[0]
    r = H._hub_tok_row(c, %r)
    out["hub"] = r["user_id"] if r else None
    r = H._hub_tok_row(c, "p2674doldtoken2")
    out["hub_old"] = r["user_id"] if r else None
    r = I._doc_mail_row(c, ["p2674dnotatoken", %r])
    out["doc"] = r["user_id"] if r else None
c.rollback()
print(json.dumps(out))
''' % (TA, tok(TH), tok(TD)))
check(j.get("task") == ALICE and j.get("hub") == ALICE and j.get("doc") == FID, f"5: a mail finds the new addresses by their hash {j}")
check(j.get("task_old") == FID and j.get("hub_old") == FID, f"5: rows of an older version (plain token) still work {j}")
check(j.get("task_wrong") is None, f"5: an unknown token finds nothing {j}")

# ================================================================== 6: https or an allowed host
r = Fr.put(B + "/api/paperless", json={"ws": "private", "url": "http://paperless.example.com", "token": "pl-secret"})
check(r.status_code == 400 and "https://" in r.json().get("error", ""), f"6: Paperless over http:// to a public host: 400 ({r.text[:200]})")
r = Fr.put(B + "/api/paperless", json={"ws": "private", "url": "http://10.255.255.1:8098", "token": "pl-secret"})
check(r.status_code == 400 and "private network" in r.json().get("error", ""), f"6: an internal address keeps its old hint ({r.text[:200]})")
r = Fr.put(B + "/api/life/karakeep", json={"url": "http://karakeep.example.com", "token": "kk-secret"})
check(r.status_code == 400 and "https://" in r.text, f"6: Karakeep over http:// to a public host: 400 ({r.text[:200]})")
j = py(r'''
import json, app
from kalmido.core.db import connect
from kalmido.calendars.subscriptions import cal_http_refused
from kalmido.paperless import ngx as P
from kalmido.newsletter.adapters import NwlError, nwl_adapter
from kalmido.life import karakeep as K
from kalmido.accounts.login import seal
c = connect()
out = {"allowed": cal_http_refused(frozenset({("pl.example.com", None)}), "http://pl.example.com"),
       "public": cal_http_refused(frozenset(), "http://pl.example.com:8000/x"),
       "https": cal_http_refused(frozenset(), "https://pl.example.com"),
       "internal": cal_http_refused(frozenset(), "http://10.1.2.3")}
try:
    P._pl_get1(c, "http://pl.example.com", "tok", "/api/", 10, False, 1000)
except P.PlError as e:
    out["pl"] = e.code
try:
    nwl_adapter("listmonk", "http://lm.example.com", {"user": "u", "token": "t"}, frozenset()).check()
except NwlError as e:
    out["nwl"] = e.code
try:
    K.kk_req(c, {"user_id": %d, "url": "http://kk.example.com", "token": seal(c, K._purpose(%d), "k")}, "/bookmarks")
except K.KkError as e:
    out["kk"] = str(e.args[0] if e.args else e)
c.rollback()
print(json.dumps(out))
''' % (FID, FID))
check(j.get("allowed") is False and j.get("public") is True and j.get("https") is False and j.get("internal") is False,
      f"6: cal_http_refused: only http:// to a public host no admin allowed {j}")
check(j.get("pl") == "needs_https" and j.get("nwl") == "needs_https" and j.get("kk") == "needs_https",
      f"6: a stored http:// address fails clearly when used {j}")

# ================================================================== 7: a message to a running job
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "helfer", "display_name": "Helfer", "org_id": ORG})
AG, AGH = r.json()["id"], bearer(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "leser", "display_name": "Leser", "org_id": ORG})
RO, ROH = r.json()["id"], bearer(r.json()["token"])
L = A.post(B + "/api/lists", json={"name": "Projekt 2674"}).json()["id"]
for u_, role in ((uid["bob"], "edit"), (AG, "edit"), (RO, "view")):
    r = A.put(B + f"/api/lists/{L}/members", json={"user_id": u_, "role": role})
    check(r.ok, f"7: share the project with {u_} as {role} ({r.status_code} {r.text[:200]})")
A.patch(B + f"/api/lists/{L}", json={"agent_members": False})
TID = A.post(B + "/api/tasks", json={"title": "Aufgabe 2674", "list_id": L}).json()["id"]
r = requests.post(V + "/agent/jobs", headers=AGH, json={"title": "Arbeit", "task_id": TID})
JID = r.json().get("id")
check(r.status_code in (200, 201) and JID, "7: the agent starts a job on the task " + r.text[:200])
r = Bo.post(B + f"/api/agents/jobs/{JID}/action", json={"action": "message", "text": "Bitte stoppen"})
check(r.status_code == 403, f"7: an editor who may not address the agent cannot write to its job ({r.status_code} {r.text[:200]})")
r = A.post(B + f"/api/agents/jobs/{JID}/action", json={"action": "message", "text": "Weiter so"})
check(r.status_code != 403, f"7: the project owner may ({r.status_code} {r.text[:200]})")
A.patch(B + f"/api/lists/{L}", json={"agent_members": True})
r = Bo.post(B + f"/api/agents/jobs/{JID}/action", json={"action": "message", "text": "Jetzt darf ich"})
check(r.status_code != 403, f"7: with the project's switch for members, the editor may ({r.status_code} {r.text[:200]})")

# ================================================================== 8: scopes
ptok = lambda s, sc: bearer(s.post(B + "/api/me/tokens", json={"name": "t" + "-".join(sc), "scopes": sc}).json()["token"])  # noqa: E731
FR_READ, FR_ACC = ptok(Fr, ["read"]), ptok(Fr, ["read", "account"])
r = requests.get(V + "/me/app-passwords", headers=FR_READ)
check(r.status_code == 403 and (r.json().get("error") or {}).get("required_scope") == "account", f"8: app passwords with read only: 403 ({r.text[:200]})")
check(requests.get(V + "/me/app-passwords", headers=FR_ACC).ok, "8: with account: 200")
r = requests.get(V + "/team/files/999999", headers=AGH)
check(r.status_code == 403 and (r.json().get("error") or {}).get("required_scope") == "attachments:read", f"8: a team chat file needs attachments:read ({r.text[:200]})")
r = requests.get(V + "/chat-attachments/999999", headers=AGH)
check(r.status_code == 404, f"8: the agent reads its chat files with read (404 for an unknown one, not 403) ({r.status_code})")
r = requests.get(V + "/chat-attachments/999999", headers=FR_READ)
check(r.status_code == 403, f"8: a person's read-only token needs attachments:read for a chat file ({r.status_code})")
D = (kt.today() + timedelta(days=1)).isoformat()
CAL = Fr.post(B + "/api/evcals", json={"name": "Termine 2674", "org_id": None}).json()["id"]
r = Fr.post(B + "/api/events", json={"cal_id": CAL, "title": "Geheimer Termin", "start": f"{D}T10:00", "end": f"{D}T11:00", "tz": "Europe/Berlin"})
check(r.status_code == 201, "8: an event " + r.text[:200])
FR_CAL = ptok(Fr, ["read", "calendar"])
ev_ro = requests.get(V + "/dayplan", headers=FR_READ, params={"date": D}).json().get("events") or []
ev_cal = requests.get(V + "/dayplan", headers=FR_CAL, params={"date": D}).json().get("events") or []
check(ev_cal and ev_cal[0]["title"] == "Geheimer Termin", f"8: with calendar the day plan names the event {ev_cal}")
check(ev_ro and all(e["title"] != "Geheimer Termin" for e in ev_ro) and ev_ro[0]["start"] == ev_cal[0]["start"],
      f"8: without calendar the event is only busy time {ev_ro}")

# ================================================================== 9, 11, 13: inside the app (the routes need a hosted server / office / tables)
j = py(r'''
import json, app
from flask import g
from kalmido.core.config import app as fl
from kalmido.core.errors import BadInput, Denied
from kalmido.office import agentdocs as AD
from kalmido.agents import usage as U
from kalmido.agents import sheetprop as SP
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
out = {}
with fl.test_request_context("/api/v1/office/docs/1"):
    g.user, g.ofa_agent = {"id": 7}, {"id": 9}
    AD.doc_public = lambda c, oid, r, f, items=True: {"items": []}
    AD.oil_agent_filter = lambda d, sees: d.update(seen=sees({"list_id": 1, "kind": "offer"}))
    AD.ofa_doc_in_lists = lambda c, aid, x: aid
    out["f9"] = AD._doc_v1(None, 1, {"id": 1})["seen"]
with fl.test_request_context("/api/v1/admin/agents/%d/audit"):
    U.op_own_agents = lambda c: {999999}
    U.agent_row = lambda c, aid: {"user_id": aid}
    try:
        U.v1_admin_agent_audit.__wrapped__(%d)
        out["f11"] = "answered"
    except Denied as e:
        out["f11"] = e.code
c = connect()
with fl.test_request_context("/"), system_ctx(c):
    SP.shb_rights_row = lambda c, s: {"id": 0, "owner_id": %d, "created_by": %d}
    SP.ast2_person_ok = lambda c, pid, sheet, lid: True
    SP.agent_usable = lambda c, aid, pid, lid: False
    try:
        out["f13"] = SP.ast2_person(c, %d, {"id": 0}, 1, None)
    except BadInput:
        out["f13"] = "refused"
    SP.agent_usable = lambda c, aid, pid, lid: True
    out["f13_ok"] = SP.ast2_person(c, %d, {"id": 0}, 1, None)
c.rollback()
print(json.dumps(out))
''' % (AG, AG, ALICE, ALICE, AG, AG))
check(j.get("f9") == 9, f"9: linked office documents follow the agent's list restriction (agent 9, not the person 7) {j}")
check(j.get("f11") == 404, f"11: the API's audit route hides an agent outside op_own_agents {j}")
check(j.get("f13") == "refused" and j.get("f13_ok") == ALICE, f"13: without for_user_id only a person who may address the agent {j}")

# ================================================================== 10: a read-only agent and the Playbook
r = requests.post(V + f"/lists/{L}/playbook/proposals", headers=ROH, json={"text": "Neue Regeln", "note": "Vorschlag"})
check(r.status_code == 403, f"10: a read-only agent token sends no Playbook proposal ({r.status_code} {r.text[:200]})")
r = requests.post(V + f"/lists/{L}/playbook/proposals", headers=AGH, json={"text": "Neue Regeln", "note": "Vorschlag"})
check(r.status_code == 201, f"10: an agent that may write still does ({r.status_code} {r.text[:200]})")

# ================================================================== 12: receipt fetcher keys run out
r = Fr.post(B + "/api/docs/fetchers", json={"ws": "private", "name": "Mein Rechner"})
check(r.status_code == 201, "12: a receipt fetcher " + r.text[:200])
code = r.json().get("code", "")
raw = code.split(":", 2)[-1] if code else ""
FXK = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))).get("key") if raw else ""
FXID = r.json().get("id")
lst = Fr.get(B + "/api/docs/fetchers", params={"ws": "private"}).json().get("fetchers") or []
exp = (lst[0].get("expires_at") or "") if lst else ""
check(exp[:10] in {(kt.today() + timedelta(days=d)).isoformat() for d in (364, 365, 366)} and lst[0].get("expired") is False,
      f"12: a new key runs out in a year ({exp})")
check(requests.get(V + "/fetcher", headers=bearer(FXK)).ok, "12: the key works")
dbx("UPDATE doc_fetchers SET expires_at='2020-01-01T00:00:00+00:00' WHERE id=?", (FXID,))
r = requests.get(V + "/fetcher", headers=bearer(FXK))
check(r.status_code == 401, f"12: a key past its end: 401 ({r.status_code})")
check((Fr.get(B + "/api/docs/fetchers", params={"ws": "private"}).json().get("fetchers") or [{}])[0].get("expired") is True, "12: the list says expired")
dbx("UPDATE doc_fetchers SET expires_at=NULL WHERE id=?", (FXID,))
check(requests.get(V + "/fetcher", headers=bearer(FXK)).ok, "12: a key of an older version (no end) is not cut off")
got = dbx("SELECT expires_at FROM doc_fetchers WHERE id=?", (FXID,))
check(got and got[0][0] and got[0][0][:10] in {(kt.today() + timedelta(days=d)).isoformat() for d in (364, 365, 366)},
      f"12: ... and gets its year from that use ({got})")

# ================================================================== 14: the photo switch's hint
K14 = "Switched off, photos keep their location, also for anyone who opens them through a public link or a shared knowledge page."
ROOT = os.path.dirname(N)
langs = {lg: json.load(open(os.path.join(ROOT, "static", "i18n", lg + ".json"), encoding="utf-8")) for lg in ("de", "es", "fr", "it", "nl")}
check(all(langs[lg].get(K14) for lg in langs), "14: the hint in all five languages")
check(all(K14 in open(os.path.join(ROOT, "static", "js", f), encoding="utf-8").read() for f in ("settings.js", "photometa.js")),
      "14: the personal and the organisation's switch show it")

sys.exit(kt.done("p2674_d_harden"))
