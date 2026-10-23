#!/usr/bin/env python3
"""2.122.0 API tests, part C: #2098 documents created through the API (person token, agent only where shared, a person without
an organisation), #2100 the documents list as CSV (only visible ids, BOM, formula guard, German numbers), #2101 the OCR language
choice (a function, no Tesseract needed). Invented names only.
freelancer-matrix: files
tenant-matrix: document
usage: p2122_c_api_test.py <datadir>      (a fresh container; P2122C_NOSTART=1: the container runs already)"""
import base64
import importlib.util
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, until  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
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


def text_pdf(lines):
    """A one-page PDF with a text layer (hand-written, no library)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET").encode("latin-1")
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
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def b64(lines):
    return base64.b64encode(text_pdf(lines)).decode()


# ---- setup: alice (instance admin, private), Alpha = bob (admin) + carol, alice's agent, erin = a person without an organisation
if not os.environ.get("P2122C_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["bob"]})
assert r.status_code == 201, r.text
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"username": "alicebot", "display_name": "Alicebot"})
assert r.status_code == 201, r.text
PAG, PAGT = r.json()["id"], r.json().get("token") or ""
dbx("DELETE FROM org_members WHERE user_id=?", (PAG,), write=True)
dbx("UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?", (PAG,), write=True)  # alice's personal agent
AGS = tok(PAGT)
TA = tok(A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"])
FID, Fr = freelancer(B, A)
TF = tok(Fr.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"])


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/v1/documents/{nid}")), secs)


# ---- #2098: create through the API
r = TA.post(B + "/api/v1/documents", json={"name": "plan.pdf", "content_base64": b64(["Rechnung Nr. 4711", "Betrag 119,00 EUR"]),
                                           "title": "Stromrechnung Oktober", "sender": "Stadtwerke Musterstadt", "type": "Rechnung",
                                           "tags": ["Energie"], "date": "2026-10-05", "amount": "119.00", "currency": "EUR"})
check(r.status_code == 201, f"person token creates a document ({r.status_code} {r.text[:150]})")
D1 = r.json().get("id") if r.ok else 0
j = done(TA, D1) if D1 else None
check(j and j["state"] == "done" and j["name"].startswith("Stromrechnung Oktober"), f"recognised like an upload ({j and j['state']} {j and j['name']})")
check(j and j["sender"] and j["sender"]["name"] == "Stadtwerke Musterstadt" and [t["name"] for t in j["tags"]] == ["Energie"]
      and j["date"] == "2026-10-05" and j["amount"] == "119.00", "the given fields are taken")
check(any(x["id"] == D1 for x in A.get(B + "/api/docs").json()["docs"]), "the web list shows it")
r = TA.post(B + "/api/v1/documents", files={"file": ("brief.pdf", text_pdf(["Brief"]), "application/pdf")}, data={"sender": "Frau Beispiel"})
check(r.status_code == 201, f"multipart upload ({r.status_code} {r.text[:120]})")
check(TA.post(B + "/api/v1/documents", json={"name": "x.pdf", "content_base64": b64(["x"]), "bogus": 1}).status_code == 400, "unknown field: 400")
check(TA.post(B + "/api/v1/documents", json={"name": "x.pdf"}).status_code == 400, "no content: 400")
check(TA.post(B + "/api/v1/documents", json={"name": "x.pdf", "content_base64": "%%%"}).status_code == 400, "bad base64: 400")
check(TA.post(B + "/api/v1/documents", json={"name": "x.pdf", "content_base64": ""}).status_code == 400, "empty file: 400")
# an organisation workspace: only for a member
r = Bo.get(B + "/api/state").json()["me"].get("workspaces") or []
org = r[0]["id"] if r else None
Tb = tok(Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"])
r = Tb.post(B + "/api/v1/documents", json={"name": "o.pdf", "content_base64": b64(["Alpha paper"]), "ws": f"org:{org}"})
check(r.status_code == 201 and r.json().get("org_id") == org, f"member creates in the organisation ({r.status_code} {r.text[:120]})")
DB = r.json().get("id") if r.ok else 0
check(TA.post(B + "/api/v1/documents", json={"name": "o.pdf", "content_base64": b64(["no"]), "ws": f"org:{org}"}).status_code in (403, 404),
      "a person outside the organisation: refused")
check(not any(x["id"] == DB for x in A.get(B + "/api/docs").json()["docs"]), "the organisation's document stays out of alice's list")
# the agent: only into what is shared with it (or its own result folder)
root = A.get(B + "/api/docs/settings", params={"ws": "private"}).json()["root_id"]
r = AGS.post(B + "/api/v1/documents", json={"name": "a.pdf", "content_base64": b64(["agent"]), "parent_id": root})
check(r.status_code in (403, 404), f"agent without a share: refused ({r.status_code})")
r = A.post(B + f"/api/files/nodes/{root}/shares", json={"agent_id": PAG, "role": "view"})
check(r.status_code == 201, "share the documents folder (view)")
check(AGS.post(B + "/api/v1/documents", json={"name": "a.pdf", "content_base64": b64(["agent"]), "parent_id": root}).status_code in (403, 404),
      "agent with view only: refused")
sid = dbx("SELECT id FROM fs_shares WHERE node_id=? AND agent_id=?", (root, PAG))[0][0]
check(A.patch(B + f"/api/files/shares/{sid}", json={"role": "edit"}).ok, "share -> edit")
r = AGS.post(B + "/api/v1/documents", json={"name": "a.pdf", "content_base64": b64(["Agent letter"]), "parent_id": root, "title": "Agentenbrief"})
check(r.status_code == 201, f"agent with edit creates ({r.status_code} {r.text[:120]})")
DA = r.json().get("id") if r.ok else 0
check(DA and dbx("SELECT 1 FROM fs_log WHERE node_id=? AND agent=1 AND action='upload'", (DA,)), "the agent's creation is in the history")
check(DA in [x["id"] for x in A.get(B + "/api/docs").json()["docs"]], "alice sees the agent's document")
r = AGS.post(B + "/api/v1/documents", json={"name": "own.pdf", "content_base64": b64(["Agent result"])})
check(r.status_code in (201, 409), f"agent without parent_id: its own result folder ({r.status_code})")
# review (2.122.0): an agent's sender on level "agent" is a suggestion to review, not a set value (like PATCH)
check(A.put(B + "/api/docs/settings", json={"ws": "private", "levels": {"sender": "agent"}}).ok, "level sender = agent")
r = AGS.post(B + "/api/v1/documents", json={"name": "s.pdf", "content_base64": b64(["Agent sender"]), "parent_id": root, "sender": "Agentur Muster"})
DS = r.json().get("id") if r.ok else 0
check(DS and done(AGS, DS), f"agent creates with a sender ({r.status_code})")
row = dbx("SELECT sender_id, review FROM doc_meta WHERE node_id=?", (DS,))
check(row and row[0][0] is None and row[0][1] == 1, f"level agent: the sender waits for review ({row})")
check(A.put(B + "/api/docs/settings", json={"ws": "private", "levels": {"sender": "learn"}}).ok, "level sender back")
check(TA.post(B + "/api/v1/documents", json={"name": "w.pdf", "content_base64": b64(["w"]), "parent_id": root, "ws": "private"}).status_code == 400,
      "ws together with parent_id: 400")
# a person without an organisation
r = TF.post(B + "/api/v1/documents", json={"name": "f.pdf", "content_base64": b64(["Freelancer paper"]), "title": "Belegfreiberuf"})
check(r.status_code == 201, f"freelancer creates with a person token ({r.status_code} {r.text[:120]})")
DF = r.json().get("id") if r.ok else 0
check(DF and done(TF, DF) and Fr.get(B + "/api/docs").json()["total"] >= 1, "freelancer sees it in the web list")
check(not any(x["id"] == DF for x in A.get(B + "/api/docs").json()["docs"]), "private stays private")

# ---- #2100: CSV
done(TA, D1)
r = TA.post(B + "/api/v1/documents", json={"name": "e.pdf", "content_base64": b64(["Evil"]), "title": '=SUM(1;2)',
                                           "sender": "@evil", "amount": "-5.00", "currency": "EUR"})
DE = r.json()["id"]
done(TA, DE)
r = A.post(B + "/api/docs/export.csv", json={"ids": [D1, DE, DB, 999999]})
check(r.status_code == 200 and r.headers["content-type"].startswith("text/csv"), f"CSV answer ({r.status_code} {r.headers.get('content-type')})")
raw = r.content
check(raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM")
txt = raw.decode("utf-8-sig")
lines = [x for x in txt.split("\r\n") if x]
check(lines[0] == "Date,Received,Title,Sender,Type,Tags,Amount,Currency,Folder,File name,To review", f"header ({lines[0][:90]})")
check(len(lines) == 3, f"only the visible ones (the organisation's and the unknown id are left out): {len(lines)} lines")
check("Stromrechnung Oktober" in txt and "Stadtwerke Musterstadt" in txt and "119.00" in txt and "Energie" in txt, "the fields of a document")
check("'=SUM(1;2)" in txt and "'@evil" in txt, f"formula text gets a ' in front ({txt[-300:]!r})")
check(",-5.00," in txt, "a plain negative number stays a number")
check(Bo.post(B + "/api/docs/export.csv", json={"ids": [D1]}).text.strip().count("\n") == 0, "bob gets nothing of alice's document")
check(AGS.post(B + "/api/docs/export.csv", json={"ids": [D1]}).status_code in (401, 403), "no agent on the web route")
check(Fr.post(B + "/api/docs/export.csv", json={"ids": [DF]}).status_code == 200, "freelancer exports its own")
A.patch(B + "/api/settings", json={"lang": "de"})
r = A.post(B + "/api/docs/export.csv", json={"ids": [D1]})
t = r.content.decode("utf-8-sig")
check(t.startswith("Datum;Eingegangen;Titel;Absender;Typ;Tags;Betrag;Währung;Ordner;Dateiname;Zu prüfen") and ";119,00;" in t, f"German: semicolon + decimal comma ({t[:120]!r})")
A.patch(B + "/api/settings", json={"lang": "en"})

# ---- #2101: the OCR language choice
spec = importlib.util.spec_from_file_location("ocr_c", os.path.join(N, "..", "kalmido", "docs", "ocr.py"))
ocr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ocr)
allhave = {"deu", "eng", "fra", "ita", "spa", "nld", "osd"}
check(ocr.ocr_langs("fr", allhave) == ("fra+deu+eng", []), f"French: its language first, then the base ({ocr.ocr_langs('fr', allhave)})")
check(ocr.ocr_langs("de", allhave) == ("deu+eng", []), "German: the base only")
check(ocr.ocr_langs("nl-NL", allhave)[0] == "nld+deu+eng", "a region suffix is ignored")
check(ocr.ocr_langs("xx", allhave) == ("deu+eng", []), "an unknown language: the base")
check(ocr.ocr_langs("it", {"deu", "eng"}) == ("deu+eng", ["ita"]), "a missing language: carried on with the rest, reported")
check(ocr.ocr_langs("es", {"eng"}) == ("eng", ["spa", "deu"]), "only some installed: those")
check(ocr.ocr_langs("es", set())[0] == "deu+eng", "none known: the base string (the check says no OCR)")
st = A.get(B + "/api/docs/settings", params={"ws": "private"}).json()
check("ocr_missing" in st and isinstance(st["ocr_missing"], list), "the settings carry the missing languages")

print(f"p2122_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
