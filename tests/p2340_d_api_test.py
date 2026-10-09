#!/usr/bin/env python3
"""2.34.0 API tests (agent D), own container (start.sh).
 - #368 GET /api/v1/attachments/{id}/text: a PDF's text layer (pages, max_chars + truncated), a scanned PDF (no_text_layer,
   message, no OCR), a damaged PDF (error unreadable), text files (UTF-8), images (kind image + url), other files (kind
   other); rights as the file itself: an agent only sees files of lists shared with it (a private list, a task in the trash,
   a deleted comment, an unknown id -> 404), the scope attachments:read (403 without it), unknown / bad parameters (400),
   larger than 20 MB (413), the cache per file content (textcache/), OpenAPI (path + scope); the MCP tool read_attachment
   against the real server (text, an image as an MCP image item, the scope filter)
 - #260 POST /api/pdf-text (the briefing field): the text of an uploaded PDF, nothing stored; not a PDF -> 400, a scan ->
   no_text_layer, without the CSRF header / login refused, at most 10 per account in 10 minutes (429, review H1)
usage: p2340_d_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
MCP = os.path.join(N, "..", "mcp", "kalmido_mcp.py")
FAILS, OKS = [], [0]


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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def make_pdf(pages):
    """A minimal PDF: one page per string (Helvetica); '' = a page without a text layer (a filled square, like a scan)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(len(pages)))}] /Count {len(pages)} >>"]
    font = 3 + 2 * len(pages)
    for i, t in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font} 0 R >> >> /Contents {4 + 2 * i} 0 R >>")
        esc = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        st = f"BT /F1 12 Tf 72 720 Td ({esc}) Tj ET" if t else "0 0 1 rg 10 10 100 100 re f"
        objs.append(f"<< /Length {len(st.encode('latin-1'))} >>\nstream\n{st}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs):
        offs.append(len(out))
        out += f"{i + 1} 0 obj\n{o}\nendobj\n".encode("latin-1")
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()


PDF = make_pdf(["Kickoff briefing for the new website", "Budget (draft): 12000 EUR, launch in March"])
SCAN = make_pdf(["", ""])
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
TXT = "Briefing: Größe, Maße und Übergaben\nZeile zwei".encode("utf-8")

subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})


def agent(name, scopes):
    r = A.post(B + "/api/admin/agents", json={"scopes": scopes, "username": name, "display_name": name.title()})
    check(r.ok, f"setup: agent {name} " + r.text[:200])
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


CL, CLH = agent("claude", ["read", "tasks:write", "comments", "attachments:read"])
RO, ROH = agent("reader", ["read"])  # no attachments:read
W = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
P = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": CL, "role": "edit"}).ok, "setup: claude in the list")
WR = A.post(B + "/api/lists", json={"name": "Reader's list"}).json()["id"]  # one agent per list: the reader works here
check(A.put(B + f"/api/lists/{WR}/members", json={"user_id": RO, "role": "edit"}).ok, "setup: the reader in its list")
TR = A.post(B + "/api/tasks", json={"title": "For the reader", "list_id": WR}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Website", "list_id": W}).json()["id"]
TP = A.post(B + "/api/tasks", json={"title": "Secret", "list_id": P}).json()["id"]
TD = A.post(B + "/api/tasks", json={"title": "Gone soon", "list_id": W}).json()["id"]


def upload(tid, name, data, mime):
    r = A.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, data, mime)})
    check(r.ok, f"setup: upload {name} " + r.text[:200])
    return dbx("SELECT id FROM attachments WHERE task_id=? AND name=? ORDER BY id DESC LIMIT 1", (tid, name))[0][0]


F_PDF = upload(T, "briefing.pdf", PDF, "application/pdf")
F_SCAN = upload(T, "scan.pdf", SCAN, "application/pdf")
F_BAD = upload(T, "broken.pdf", b"%PDF-1.4\nthis is not a pdf at all", "application/pdf")
F_TXT = upload(T, "notes.md", TXT, "text/markdown")
F_PNG = upload(T, "screen.png", PNG, "image/png")
F_ZIP = upload(T, "archive.zip", b"PK\x03\x04" + b"\x00" * 50, "application/zip")
F_PRIV = upload(TP, "private.pdf", PDF, "application/pdf")
F_DEL = upload(TD, "trash.pdf", PDF, "application/pdf")
F_RO = upload(TR, "reader.pdf", PDF, "application/pdf")


def text(aid, h=CLH, **q):
    return requests.get(V + f"/attachments/{aid}/text", headers=h, params=q)


# ---- PDF with a text layer
r = text(F_PDF)
j = r.json()
check(r.status_code == 200 and j["kind"] == "pdf" and j["pages"] == 2 and j["pages_read"] == 2 and j["truncated"] is False
      and j["no_text_layer"] is False and "Kickoff briefing for the new website" in j["text"] and "12000 EUR" in j["text"],
      "#368: the text layer of both pages " + r.text[:300])
check(j["text"].index("Kickoff") < j["text"].index("Budget") and "\n\n" in j["text"], "#368: pages in order, a blank line between")
check(j["id"] == F_PDF and j["task_id"] == T and j["comment_id"] is None and j["name"] == "briefing.pdf" and j["mime"] == "application/pdf"
      and j["url"] == f"/api/v1/attachments/{F_PDF}" and j["chars"] == len(j["text"]) and j["message"] is None, "#368: the file's fields")
cache = os.path.join(DATA, "textcache")
check(os.path.isdir(cache) and any(n.endswith(".json") for n in os.listdir(cache)), "#368: the result is cached per content")
r = text(F_PDF, max_chars=7)
check(r.status_code == 200 and r.json()["text"] == "Kickoff" and r.json()["truncated"] is True and r.json()["chars"] == 7, "#368: max_chars cuts, truncated")
check(text(F_PRIV, h={"Authorization": CLH["Authorization"]}).status_code == 404, "#368: a file of a list not shared with the agent -> 404")
# the same content in another task is served from the cache (same answer)
r2 = text(F_PDF)
check(r2.json()["text"] == j["text"], "#368: a second read answers the same")

# ---- scanned, damaged, text, image, other
r = text(F_SCAN)
j = r.json()
check(r.status_code == 200 and j["kind"] == "pdf" and j["no_text_layer"] is True and j["text"] == "" and "OCR" in (j["message"] or ""),
      "#368: a scanned PDF: no_text_layer with a hint, no OCR " + r.text[:300])
r = text(F_BAD)
check(r.status_code == 200 and r.json().get("error") == "unreadable" and r.json()["text"] is None and r.json()["message"], "#368: a damaged PDF -> error unreadable " + r.text[:200])
r = text(F_TXT)
check(r.status_code == 200 and r.json()["kind"] == "text" and r.json()["text"] == TXT.decode("utf-8"), "#368: a text file in UTF-8 " + r.text[:200])
r = text(F_PNG)
check(r.status_code == 200 and r.json()["kind"] == "image" and r.json()["text"] is None and r.json()["url"] == f"/api/v1/attachments/{F_PNG}"
      and r.json()["message"], "#368: an image points to the file")
r = text(F_ZIP)
check(r.status_code == 200 and r.json()["kind"] == "other" and r.json()["text"] is None, "#368: other files: nothing to read")

# ---- rights, scope, parameters
check(text(F_RO, h=ROH).status_code == 403 and requests.get(V + f"/attachments/{F_RO}", headers=ROH).status_code == 403,
      "#368: without attachments:read -> 403 (like the file itself)")
check(text(F_PDF, h=ROH).status_code in (403, 404), "#368: the reader and a file of another list: refused")
check(text(999999).status_code == 404, "#368: an unknown id -> 404")
check(A.delete(B + f"/api/tasks/{TD}").ok and text(F_DEL).status_code == 404, "#368: a task in the trash -> 404")
check(text(F_PDF, max_chars=0).status_code == 400 and text(F_PDF, max_chars=200001).status_code == 400, "#368: max_chars outside 1-200000 -> 400")
check(text(F_PDF, page=2).status_code == 400, "#368: an unknown parameter -> 400")
tok = A.post(B + "/api/me/tokens", json={"name": "mine", "scopes": ["read", "attachments:read"]}).json()["token"]
check(text(F_PRIV, h={"Authorization": "Bearer " + tok}).status_code == 200, "#368: a person's own token reads her private file")
# a comment's file: readable while the comment lives
cm = A.post(B + f"/api/tasks/{T}/comments", data={"body": "see the file"}, files={"file": ("minutes.txt", b"Minutes of the call", "text/plain")})
check(cm.ok, "setup: a comment with a file " + cm.text[:200])
F_CM = dbx("SELECT id FROM attachments WHERE task_id=? AND name='minutes.txt'", (T,))[0][0]
check(text(F_CM).json().get("text") == "Minutes of the call", "#368: a comment's file")
cid = dbx("SELECT comment_id FROM attachments WHERE id=?", (F_CM,))[0][0]
check(A.delete(B + f"/api/comments/{cid}").ok and text(F_CM).status_code == 404, "#368: the comment deleted -> 404")
# larger than 20 MB (the test server takes 1 MB uploads: the recorded size says more)
F_BIG = upload(T, "big.txt", b"a" * 1000, "text/plain")
dbx("UPDATE attachments SET size=? WHERE id=?", (20 * 1024 * 1024 + 10, F_BIG), write=True)
r = text(F_BIG)
check(r.status_code == 413 and r.json()["error"]["code"] == "too_large", "#368: larger than 20 MB -> 413 " + r.text[:200])
# OpenAPI: the path with its scope
spec = requests.get(V + "/openapi.json", headers=CLH).json()
op = spec["paths"].get("/attachments/{id}/text", {}).get("get") or {}
check(op.get("x-kalmido-scope") == "attachments:read" and "AttachmentText" in json.dumps(op), "#368: OpenAPI documents the path + scope")

# ---- MCP read_attachment against this server
ENV = {**os.environ, "KALMIDO_URL": B + "/", "KALMIDO_TOKEN": CLH["Authorization"].split(" ", 1)[1]}
p = subprocess.Popen([sys.executable, MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=ENV)
seq = [0]


def rpc(method, params=None):
    seq[0] += 1
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": seq[0], "method": method, **({"params": params} if params is not None else {})}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())


rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
names = {t["name"] for t in rpc("tools/list")["result"]["tools"]}
check("read_attachment" in names, "#368: MCP lists read_attachment")
res = rpc("tools/call", {"name": "read_attachment", "arguments": {"attachment_id": F_PDF}})["result"]
check(res["isError"] is False and "12000 EUR" in res["structuredContent"]["text"], "#368: MCP read_attachment gives the PDF text")
res = rpc("tools/call", {"name": "read_attachment", "arguments": {"attachment_id": F_PNG}})["result"]
check(res["isError"] is False and res["content"][-1]["type"] == "image" and res["content"][-1]["mimeType"] == "image/png", "#368: MCP returns an image as image item")
res = rpc("tools/call", {"name": "read_attachment", "arguments": {"attachment_id": F_PRIV}})["result"]
check(res["isError"] is True, "#368: MCP: a file of a list not shared -> error")
p.stdin.close()
p.wait(5)
ENV2 = {**ENV, "KALMIDO_TOKEN": ROH["Authorization"].split(" ", 1)[1]}
p = subprocess.Popen([sys.executable, MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=ENV2)
rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
check("read_attachment" not in {t["name"] for t in rpc("tools/list")["result"]["tools"]}, "#368: MCP hides read_attachment without attachments:read")
p.stdin.close()
p.wait(5)

# ---- #260: the briefing field reads a PDF
n0 = dbx("SELECT COUNT(*) FROM attachments")[0][0]
r = A.post(B + "/api/pdf-text", files={"file": ("brief.pdf", PDF, "application/pdf")})
check(r.status_code == 200 and "Kickoff briefing" in r.json()["text"] and r.json()["pages"] == 2 and r.json()["no_text_layer"] is False,
      "#260: the briefing field gets the PDF's text " + r.text[:200])
check(dbx("SELECT COUNT(*) FROM attachments")[0][0] == n0, "#260: nothing is stored")
r = A.post(B + "/api/pdf-text", files={"file": ("scan.pdf", SCAN, "application/pdf")})
check(r.status_code == 200 and r.json()["no_text_layer"] is True and r.json()["message"], "#260: a scan -> no_text_layer + hint")
check(A.post(B + "/api/pdf-text", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 400, "#260: not a PDF -> 400")
check(A.post(B + "/api/pdf-text").status_code == 400, "#260: no file -> 400")
check(requests.post(B + "/api/pdf-text", files={"file": ("brief.pdf", PDF, "application/pdf")}, cookies=A.cookies).status_code in (400, 403),
      "#260: without the CSRF header refused")
check(requests.post(B + "/api/pdf-text", headers=H, files={"file": ("brief.pdf", PDF, "application/pdf")}).status_code == 401, "#260: not logged in -> 401")
# review H1: at most 10 PDFs per account in 10 minutes (3 counted above: brief, scan, a.txt)
codes = [A.post(B + "/api/pdf-text", files={"file": ("brief.pdf", PDF, "application/pdf")}).status_code for _ in range(9)]
check(codes == [200] * 7 + [429] * 2, "H1: /api/pdf-text throttled per account -> 429 " + str(codes))

print(f"p2340_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
