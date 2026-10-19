#!/usr/bin/env python3
"""2.93.0 API tests, part A (#1927, office: document templates, documents, signature by customer link), own container
(start.sh, org encryption on). Invented companies, people and figures only.
tenant-matrix: office
 - templates: the samples (German / English), "use sample" as own template, create / change / archive / restore, bad
   kind / empty name 400, the text encrypted at rest
 - documents: made from a template for a client (required) + project list + quotation of that client; client / list /
   quotation of another organisation 404, a quotation of another client 404; the preview fills the variables (client,
   address, contact, project, quotation number / date / total, company, today) and keeps unknown / empty ones marked;
   "finish" fills them for good (unknown -> empty), freezes the text (SHA-256), files the PDF in the office documents
   space in a folder of the client (the admin reaches it, the member and other organisations do not); PATCH / finish
   again 409; "edit a copy" = a new draft; archive + restore
 - signature link (signoff kind document): only for a finished signable document; the customer page shows the text
   escaped (no scripts) + the PDF; form check value, tick required; signing sets the document signed, a second decision
   is impossible; the signed PDF is filed next to the original and carries the text's SHA-256; a revoked / expired /
   unknown link gives the same answer; the quotation approval links behave as before (one smoke test)
 - rights: an organisation member 403, an agent 403, another organisation 404; a person without organisation (personal
   office) uses everything (private client and list)
usage: p293_a_api_test.py <datadir>      (P293A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import hashlib
import os
import re
import subprocess
import sys
import time
import zlib

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
TP = O + "/doc-templates"
GD = O + "/gen-docs"


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


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def anon(path, **kw):
    return requests.get(B + path, allow_redirects=False, **kw)


def form_key(html):
    m = re.search(r'name="f" value="([0-9a-f]+)"', html)
    return m.group(1) if m else ""


def post(tok, **d):
    return requests.post(B + "/s/q/" + tok, data=d, allow_redirects=False, headers={"User-Agent": "TestBrowser/1.0"})


def pdf_hex(data):
    """The text of a PDF written by Kalmido: its content streams inflated (the text is in <hex> strings)."""
    out = b""
    # Kalmido ends a stream with "\nendstream": a compressed stream may itself end in a CR byte (1 in 256), "\r?" cut it off (CI red, 2.145.1 #2439)
    for m in re.finditer(rb"stream\r?\n(.*?)\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out.decode("latin-1")


def in_pdf(data, text):
    return text.encode("cp1252").hex() in pdf_hex(data)


if os.environ.get("P293A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do = sess("bob"), sess("carol"), sess("dora")
for s in (A, Bo, Ca, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345",
                                                                                   "city": "Musterstadt", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 5", "zip": "20000", "city": "Hamburg", "country": "DE",
                                       "contact": "Erika Beispiel"}).json()["id"]
CLB = A.post(B + "/api/clients", json={"name": "Kunde Zwei AG"}).json()["id"]
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG"}).json()["id"]
L = A.post(B + "/api/lists", json={"name": "Imagefilm Frühling", "org_id": ORG}).json()["id"]
L2 = Ca.post(B + "/api/lists", json={"name": "Fremdprojekt", "org_id": ORG2}).json()["id"]
LP = A.post(B + "/api/lists", json={"name": "Privat Alice", "org_id": None}).json()["id"]  # Alice's private list: not of the office area
r = A.post(B + O + "/docs", json={"kind": "offer", "client_id": CL, "project_title": "Imagefilm", "items": [{"title": "Schnitt", "qty": 2, "rate": 500}]})
assert r.status_code == 201, r.text
OF = r.json()["id"]
OFN = A.get(B + f"{O}/docs/{OF}").json()
OFB = A.post(B + O + "/docs", json={"kind": "offer", "client_id": CLB, "items": [{"title": "Ton", "qty": 1, "rate": 100}]}).json()["id"]
OF2 = Ca.post(B + O + "/docs", json={"kind": "offer", "client_id": CL2, "items": [{"title": "Fremd", "qty": 1, "rate": 100}]}).json()["id"]

# ---------------------------------------------------------------- rights first
for path in (TP, TP + "/starters", GD):
    check(Bo.get(B + path).status_code == 403, f"member: 403 on {path}")
    check(requests.get(B + path, headers=AGH).status_code == 403, f"agent: 403 on {path}")
check(Bo.post(B + TP, json={"starter": "nda"}).status_code == 403 and requests.post(B + TP, json={"starter": "nda"}, headers=AGH).status_code == 403,
      "member / agent cannot create a template")

# ---------------------------------------------------------------- templates
st = A.get(B + TP + "/starters").json()
# 2.117.0 (#2283): the letter samples follow the three contract samples
check([x["key"] for x in st["starters"]][:3] == ["contract", "confirmation", "nda"] and st["lang"] == "de" and "Vertrag" in st["starters"][0]["body"]
      and st["note"], f"samples in the office's document language (de) {[x['name'] for x in st['starters']]}")
ste = A.get(B + TP + "/starters?lang=en").json()
check(ste["lang"] == "en" and ste["starters"][2]["name"] == "Non-disclosure agreement" and "{{client.name}}" in ste["starters"][2]["body"], "samples in English")
check(A.get(B + TP + "/starters?lang=fr").status_code == 400, "an unknown language: 400")
r = A.post(B + TP, json={"starter": "contract"})
check(r.status_code == 201 and r.json()["kind"] == "contract" and r.json()["lang"] == "de" and r.json()["sign"] == 1, f"use sample: contract {r.status_code}")
TC = r.json()["id"]
r = A.post(B + TP, json={"starter": "confirmation", "lang": "en"})
check(r.status_code == 201 and r.json()["name"] == "Order confirmation" and r.json()["sign"] == 0, "use sample: order confirmation in English (not signable)")
TO = r.json()["id"]
check(A.post(B + TP, json={"starter": "lease"}).status_code == 400, "an unknown sample: 400")
check(A.post(B + TP, json={"kind": "poster", "name": "X", "body": "x"}).status_code == 400, "a bad kind: 400")  # 2.106.0 (#2028): letter is a kind now
check(A.post(B + TP, json={"kind": "other", "name": "  ", "body": "x"}).status_code == 400, "an empty name: 400")
BODY = ("# Vereinbarung {{client.name}}\n\nZwischen {{company.name}}, {{company.address}} und {{client.name}}, {{client.address}}.\n"
        "Ansprechpartner: {{client.contact}}\n\n## Projekt\n- Projekt: {{project.title}}\n- Angebot {{offer.number}} vom {{offer.date}} über {{offer.total}}\n\n"
        "Unbekannt: [{{client.shoesize}}] Datum {{today}}\n<script>alert(1)</script>")
r = A.post(B + TP, json={"kind": "other", "name": "Eigene Vorlage", "lang": "de", "body": BODY, "sign": 1})
check(r.status_code == 201 and r.json()["body"] == BODY, "own template")
TT = r.json()["id"]
row = sql("SELECT body FROM office_doc_templates WHERE id=?", (TT,))[0]
check(str(row[0]).startswith("kenc1:") and "Vereinbarung" not in str(row[0]), "the template's text is encrypted at rest")
check(A.patch(B + f"{TP}/{TT}", json={"name": "Eigene Vorlage 2"}).json()["name"] == "Eigene Vorlage 2", "rename a template")
check(Ca.patch(B + f"{TP}/{TT}", json={"name": "x"}).status_code == 404 and Ca.delete(B + f"{TP}/{TT}").status_code == 404, "another organisation: 404")
check(Bo.patch(B + f"{TP}/{TT}", json={"name": "x"}).status_code == 403, "member: 403 on change")
check(A.delete(B + f"{TP}/{TT}").ok and TT not in [t["id"] for t in A.get(B + TP).json()["templates"]], "archive a template")
check(TT in [t["id"] for t in A.get(B + TP + "?archived=1").json()["templates"]], "archived templates on request")
check(A.post(B + f"{TP}/{TT}/restore").ok and TT in [t["id"] for t in A.get(B + TP).json()["templates"]], "restore (the undo)")
j = A.get(B + TP).json()
check(len(j["vars"]) == 10 and j["vars"][0]["key"] == "client.name" and {k["key"] for k in j["kinds"]} == {"contract", "confirmation", "nda", "other", "letter"},  # 2.106.0 (#2028): kind letter
      "the variables and kinds")
check(Ca.get(B + TP).json()["templates"] == [], "another organisation: its own empty templates")

# ---------------------------------------------------------------- documents
check(A.post(B + GD, json={"template_id": TT}).status_code == 400, "a document needs a client (400)")
check(A.post(B + GD, json={"template_id": TT, "client_id": CL2}).status_code == 404, "a client of another organisation: 404")
check(A.post(B + GD, json={"template_id": TT, "client_id": CL, "list_id": L2}).status_code == 404, "a list of another organisation: 404")
check(A.post(B + GD, json={"template_id": TT, "client_id": CL, "list_id": LP}).status_code == 404, "a private list outside the office area: 404")
check(A.post(B + GD, json={"template_id": TT, "client_id": CL, "doc_id": OF2}).status_code == 404, "a quotation of another organisation: 404")
check(A.post(B + GD, json={"template_id": TT, "client_id": CL, "doc_id": OFB}).status_code == 404, "a quotation of another client: 404")
check(Ca.post(B + GD, json={"template_id": TT, "client_id": CL2}).status_code == 404, "another organisation's template: 404")
r = A.post(B + GD, json={"template_id": TT, "client_id": CL, "list_id": L, "doc_id": OF})
check(r.status_code == 201 and r.json()["status"] == "draft" and r.json()["body"] == BODY and r.json()["sign"] == 1 and r.json()["title"] == "Eigene Vorlage 2"
      and r.json()["client_name"] == "Kunde Eins GmbH" and r.json()["list_name"] == "Imagefilm Frühling", f"a draft from the template {r.status_code} {r.text[:200]}")
G = r.json()["id"]
check(str(sql("SELECT body FROM office_gen_docs WHERE id=?", (G,))[0][0]).startswith("kenc1:"), "the document's text is encrypted at rest")
pv = A.post(B + GD + "/preview", json={"gen_doc_id": G}).json()
t = pv["text"]
check("Vereinbarung Kunde Eins GmbH" in t and "Beispiel Film GmbH, Musterweg 1, 12345 Musterstadt" in t and "Kundenweg 5\n20000 Hamburg" in t  # 2.114.4 (#2280): the client address on own lines
      and "Ansprechpartner: Erika Beispiel" in t and "Projekt: Imagefilm Frühling" in t, f"preview: client, company, address, contact, project {t[:300]}")
check(f"Angebot {OFN['number']} vom" in t and "1.190,00" in t, f"preview: quotation number and total (gross) {OFN.get('number')}")
check("[{{client.shoesize}}]" in t and pv["missing"] == ["client.shoesize"], f"preview: the unknown variable stays marked {pv['missing']}")
check(pv["blocks"][0] == ["h1", "Vereinbarung Kunde Eins GmbH"] and ["h2", "Projekt"] in pv["blocks"] and any(b[0] == "li" for b in pv["blocks"]), "preview: headings and lists")
pv2 = A.post(B + GD + "/preview", json={"body": "{{offer.number}}|{{project.title}}|{{client.name}}", "client_id": CLB}).json()
check(pv2["text"] == "{{offer.number}}|{{project.title}}|Kunde Zwei AG" and pv2["missing"] == ["offer.number", "project.title"], f"preview: empty values marked {pv2}")
check(A.post(B + GD + "/preview", json={"body": "x", "client_id": CL2}).status_code == 404, "preview with another organisation's client: 404")
# 2.93.0 (#1927) review: a value at the start of a line never becomes a heading / list item
CLM = A.post(B + "/api/clients", json={"name": "# Kopf - GmbH"}).json()["id"]
pv3 = A.post(B + GD + "/preview", json={"body": "{{client.name}}\n\nText", "client_id": CLM}).json()
check(pv3["blocks"][0][0] == "p" and pv3["blocks"][0][1] == "#\u00a0Kopf - GmbH", f"a value with markup stays text {pv3['blocks'][:1]}")
check(A.post(B + GD + "/preview", json={"body": "{{client.name}}", "client_id": CL, "doc_id": OF2}).status_code == 404, "preview with another organisation's quotation: 404")
check(A.post(B + GD + "/preview", json={"body": "x {{client.name.__class__}} {{7*7}}"}).json()["text"] == "x {{client.name.__class__}} {{7*7}}",
      "nothing is evaluated (unknown names stay as they are, no expressions)")
r = A.patch(B + f"{GD}/{G}", json={"title": "Vereinbarung Imagefilm"})
check(r.ok and r.json()["title"] == "Vereinbarung Imagefilm", "change the draft's title")
check(A.patch(B + f"{GD}/{G}", json={"doc_id": OFB}).status_code == 404, "PATCH: a quotation of another client 404")
# 2.93.0 (#1927) review: changing the client of a draft with a quotation drops the old client's quotation
GX = A.post(B + GD, json={"template_id": TT, "client_id": CL, "doc_id": OF}).json()["id"]
r = A.patch(B + f"{GD}/{GX}", json={"client_id": CLB})
check(r.ok and r.json()["client_id"] == CLB and r.json()["doc_id"] is None, f"PATCH client: the old quotation dropped ({r.status_code} {r.text[:160]})")
check(A.patch(B + f"{GD}/{GX}", json={"client_id": CL, "doc_id": OFB}).status_code == 404, "PATCH client + a quotation of another client: still 404")
A.delete(B + f"{GD}/{GX}")  # out of the list checks below
check(Bo.patch(B + f"{GD}/{G}", json={"title": "x"}).status_code == 403 and Ca.patch(B + f"{GD}/{G}", json={"title": "x"}).status_code == 404, "member 403, other 404")
check(Ca.get(B + f"{GD}/{G}").status_code == 404 and Ca.post(B + f"{GD}/{G}/final").status_code == 404 and Ca.get(B + f"{GD}/{G}/pdf").status_code == 404,
      "another organisation reaches no document (404)")
r = A.get(B + f"{GD}/{G}/pdf")
check(r.ok and r.content[:5] == b"%PDF-" and in_pdf(r.content, "Kunde Eins GmbH"), "a draft's preview PDF")
check(in_pdf(r.content, "ENTWURF") or in_pdf(r.content, "DRAFT"), "2.93.0 (#1927) review: the draft's PDF is marked as draft")
r = A.post(B + f"{GD}/{G}/final")
check(r.ok and r.json()["status"] == "final" and r.json()["node_id"], f"finish ({r.status_code} {r.text[:200]})")
F = r.json()
check("{{" not in F["body"] and "Unbekannt: [] Datum" in F["body"] and "&lt;" not in F["body"], "finished: variables filled, the unknown one empty")
check(F["body_hash"] == hashlib.sha256(F["body"].encode()).hexdigest(), "finished: SHA-256 of the frozen text")
check(A.patch(B + f"{GD}/{G}", json={"body": "neu"}).status_code == 409 and A.post(B + f"{GD}/{G}/final").status_code == 409, "a finished document: PATCH / finish 409")
NID = F["node_id"]
n = sql("SELECT n.org_id, n.kind, p.name, n.name FROM fs_nodes n JOIN fs_nodes p ON p.id=n.parent_id WHERE n.id=?", (NID,))
check(n and n[0][0] == ORG and n[0][1] == "file" and n[0][2] == "Kunde Eins GmbH" and n[0][3].endswith(".pdf"), f"the PDF in the documents space, folder of the client {n}")
check(A.get(B + f"/api/docs/{NID}").ok, "the admin reaches the filed PDF")
check(Bo.get(B + f"/api/docs/{NID}").status_code in (403, 404) and Ca.get(B + f"/api/docs/{NID}").status_code in (403, 404), "member / other organisation do not")
r = A.get(B + f"{GD}/{G}/pdf")
check(r.ok and r.content[:5] == b"%PDF-" and in_pdf(r.content, "Kunde Eins GmbH"), "the finished PDF")
check(not in_pdf(r.content, "ENTWURF") and not in_pdf(r.content, "DRAFT"), "2.93.0 (#1927) review: the finished PDF carries no draft mark")
lst = A.get(B + GD).json()
check([d["id"] for d in lst["docs"]] == [G] and lst["clients"] and any(x["id"] == L for x in lst["lists"]) and not any(x["id"] in (L2, LP) for x in lst["lists"])
      and any(o["id"] == OF for o in lst["offers"]), "the list with clients / lists of the area / quotations")
check([d["id"] for d in A.get(B + GD + f"?client_id={CL}&brief=1").json()["docs"]] == [G] and A.get(B + GD + f"?client_id={CLB}").json()["docs"] == []
      and [d["id"] for d in A.get(B + GD + f"?list_id={L}&status=final").json()["docs"]] == [G], "filter by client / project / status")
check(A.get(B + GD + "?status=x").status_code == 400, "a bad status filter: 400")
r = A.post(B + GD, json={"copy_of": G})
check(r.status_code == 201 and r.json()["status"] == "draft" and r.json()["body"] == F["body"] and r.json()["client_id"] == CL, "edit a copy = a new draft")
GC = r.json()["id"]
check(A.delete(B + f"{GD}/{GC}").ok and GC not in [d["id"] for d in A.get(B + GD).json()["docs"]], "archive a document")
check(A.post(B + f"{GD}/{GC}/restore").ok and GC in [d["id"] for d in A.get(B + GD).json()["docs"]], "restore (the undo)")
r = A.post(B + GD, json={"template_id": TO, "client_id": CL, "doc_id": OF})
GO = r.json()["id"]
check(r.status_code == 201 and r.json()["sign"] == 0 and r.json()["kind"] == "confirmation", "an order confirmation from the quotation")
A.post(B + f"{GD}/{GO}/final")
check(A.post(B + f"{GD}/{GO}/signoff", json={}).status_code == 409, "not signable: no link (409)")
check(A.post(B + f"{GD}/{GC}/signoff", json={}).status_code == 409, "a draft: no link (409)")

# ---------------------------------------------------------------- signature by customer link
check(Bo.post(B + f"{GD}/{G}/signoff", json={}).status_code == 403 and Ca.post(B + f"{GD}/{G}/signoff", json={}).status_code == 404, "member 403 / other 404: no link")
check(A.post(B + f"{GD}/{G}/signoff", json={"expires": "2020-01-01"}).status_code == 400, "an expiry in the past: 400")
r = A.post(B + f"{GD}/{G}/signoff", json={})
check(r.ok and r.json()["live"] and r.json()["url"] and r.json()["kind"] == "document" and r.json()["gen_doc_id"] == G, f"signature link ({r.status_code} {r.text[:160]})")
S1 = r.json()
TOK = S1["url"].split("/s/q/")[1]
check(len(TOK) >= 43 and S1["doc_hash"] == F["body_hash"], "256-bit token, the hash of the text")
row = sql("SELECT token_hash, token, gen_doc_id, doc_id FROM office_signoffs WHERE id=?", (S1["id"],))[0]
check(row[0] == hashlib.sha256(TOK.encode()).hexdigest() and TOK not in row[1] and row[2] == G and row[3] is None, "stored: hash + sealed copy, the document")
check(Bo.get(B + f"{GD}/{G}/signoffs").status_code == 403 and Ca.get(B + f"{GD}/{G}/signoffs").status_code == 404, "member 403 / other 404: the links")
check(Bo.post(B + f"{O}/signoffs/{S1['id']}/revoke").status_code == 403 and Ca.post(B + f"{O}/signoffs/{S1['id']}/revoke").status_code == 404,
      "member cannot stop a document link (403), another organisation 404")
pg = anon("/s/q/" + TOK)
check(pg.status_code == 200 and "Kunde Eins GmbH" in pg.text and "Vereinbarung Imagefilm" in pg.text and F["body_hash"] in pg.text, f"the page shows the document ({pg.status_code})")
check("&lt;script&gt;" in pg.text and not re.search(r"<script", pg.text, re.I), "the text escaped, no scripts")
check("default-src 'none'" in pg.headers.get("Content-Security-Policy", "") and "noindex" in pg.headers.get("X-Robots-Tag", ""), "strict CSP, noindex")
check("qualified signature" in pg.text or "qualifizierte" in pg.text, "the note on the simple electronic signature")
pdf = anon(f"/s/q/{TOK}/pdf")
check(pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and in_pdf(pdf.content, "Kunde Eins GmbH"), "the PDF through the link")
FK = form_key(pg.text)
check(post(TOK, f="0" * 64, name="Max Muster", ok="1", do="accept").status_code == 403, "a wrong form check value: 403")
check(post(TOK, f=FK, name="Max Muster", do="accept").status_code == 400, "sign without the tick: 400")
r = post(TOK, f=FK, name="Max <b>Muster</b>", email="max@example.com", ok="1", do="accept")
check(r.status_code == 303, f"signed ({r.status_code})")
pg = anon("/s/q/" + TOK)
check(pg.status_code == 200 and 'name="f"' not in pg.text and "&lt;b&gt;Muster" in pg.text, "afterwards only the confirmation (escaped name)")
check(post(TOK, f=FK, name="Someone Else", do="decline").status_code == 303, "a second decision is ignored")
d = A.get(B + f"{GD}/{G}").json()
check(d["status"] == "signed" and d["signed_node_id"] and d["signoff"]["state"] == "accepted" and d["signoff"]["signer_name"] == "Max <b>Muster</b>",
      f"the document is signed, the signed PDF filed {d.get('status')} {d.get('signed_node_id')}")
SN = d["signed_node_id"]
n = sql("SELECT n.org_id, p.name, n.name FROM fs_nodes n JOIN fs_nodes p ON p.id=n.parent_id WHERE n.id=?", (SN,))
check(n and n[0][0] == ORG and n[0][1] == "Kunde Eins GmbH" and SN != NID, f"the signed PDF next to the original {n}")
r = A.get(B + f"{GD}/{G}/pdf?signed=1")
check(r.ok and in_pdf(r.content, F["body_hash"]) and in_pdf(r.content, "Max <b>Muster</b>"), "the signed PDF carries the SHA-256 of the text and the name")
check(not in_pdf(A.get(B + f"{GD}/{G}/pdf").content, F["body_hash"]), "the original has no signature block")
p2 = anon(f"/s/q/{TOK}/pdf")
check(p2.status_code == 200 and in_pdf(p2.content, F["body_hash"]), "the customer gets the signed PDF after signing")
check(A.get(B + f"{GD}/{GO}/pdf?signed=1").status_code == 404, "no signed PDF of an unsigned document")
log = A.get(B + O + "/log?limit=50").json()["log"]
check(any(x["action"] == "signoff_accepted" and x.get("target") == "gen_doc" for x in log), "the office log has the signature")
# a second document: decline, revoke, expiry, the same answer as unknown
G2 = A.post(B + GD, json={"template_id": TC, "client_id": CL}).json()["id"]
A.post(B + f"{GD}/{G2}/final")
S2 = A.post(B + f"{GD}/{G2}/signoff", json={}).json()
T2 = S2["url"].split("/s/q/")[1]
S3 = A.post(B + f"{GD}/{G2}/signoff", json={}).json()
T3 = S3["url"].split("/s/q/")[1]
UNKNOWN = anon("/s/q/" + "z" * 43)
check(anon("/s/q/" + T2).status_code == 404 and anon("/s/q/" + T2).text == UNKNOWN.text, "a new link stops the older one (the same answer as unknown)")
sql("UPDATE office_signoffs SET expires_at=? WHERE id=?", ("2020-01-01T00:00:00+00:00", S3["id"]), write=True)
check(anon("/s/q/" + T3).status_code == 404 and anon("/s/q/" + T3).text == UNKNOWN.text, "expired: the same answer")
sql("UPDATE office_signoffs SET expires_at=NULL WHERE id=?", (S3["id"],), write=True)
pg = anon("/s/q/" + T3)
check(post(T3, f=form_key(pg.text), name="Erika Beispiel", do="decline", reason="Noch offen").status_code == 303
      and A.get(B + f"{GD}/{G2}").json()["status"] == "declined", "declined -> the document is declined")
G3 = A.post(B + GD, json={"template_id": TC, "client_id": CL}).json()["id"]
A.post(B + f"{GD}/{G3}/final")
S4 = A.post(B + f"{GD}/{G3}/signoff", json={}).json()
T4 = S4["url"].split("/s/q/")[1]
check(A.post(B + f"{O}/signoffs/{S4['id']}/revoke").ok and anon("/s/q/" + T4).text == UNKNOWN.text, "revoked: the same answer as unknown")
S5 = A.post(B + f"{GD}/{G3}/signoff", json={}).json()
T5 = S5["url"].split("/s/q/")[1]
check(anon("/s/q/" + T5).status_code == 200, "a new link works")
check(A.delete(B + f"{GD}/{G3}").ok and anon("/s/q/" + T5).text == UNKNOWN.text, "archiving the document stops its link")
# 2.93.0 (#1927) review: archived while the customer has the page open -> the same void answer, nothing signed
G6 = A.post(B + GD, json={"template_id": TC, "client_id": CL}).json()["id"]
A.post(B + f"{GD}/{G6}/final")
T6 = A.post(B + f"{GD}/{G6}/signoff", json={}).json()["url"].split("/s/q/")[1]
FK6 = form_key(anon("/s/q/" + T6).text)
sql("UPDATE office_gen_docs SET archived=1 WHERE id=?", (G6,), write=True)  # archived, the link row still open (the race window)
r = post(T6, f=FK6, name="Max Muster", ok="1", do="accept")
check(r.status_code == 404 and r.text == UNKNOWN.text, f"archived before the decision: the same void answer ({r.status_code})")
st6 = sql("SELECT d.status, s.state FROM office_gen_docs d JOIN office_signoffs s ON s.gen_doc_id=d.id WHERE d.id=?", (G6,))[0]
check(st6[0] == "final" and st6[1] == "open", f"archived before the decision: status stays {st6}")
G7 = A.post(B + GD, json={"template_id": TC, "client_id": CL}).json()["id"]
A.post(B + f"{GD}/{G7}/final")
T7 = A.post(B + f"{GD}/{G7}/signoff", json={}).json()["url"].split("/s/q/")[1]
FK7 = form_key(anon("/s/q/" + T7).text)
check(A.delete(B + f"{GD}/{G7}").ok, "archive with an open link")
r = post(T7, f=FK7, name="Max Muster", ok="1", do="accept")
check(r.status_code == 404 and r.text == UNKNOWN.text and A.get(B + f"{GD}/{G7}").json()["status"] == "final", "archived through the app: decision void, status stays")
# 2.93.0 (#1927) review: titles are one line; quotes / line breaks never break the file name header
G8 = A.post(B + GD, json={"template_id": TC, "client_id": CL, "title": 'Vertrag "A"\r\nX-Evil: 1'}).json()
check("\n" not in G8["title"] and "\r" not in G8["title"] and G8["title"] == 'Vertrag "A" X-Evil: 1', f"title: line breaks out {G8['title']!r}")
r = A.patch(B + f"{GD}/{G8['id']}", json={"title": "Zeile 1\nZeile 2"})
check(r.ok and r.json()["title"] == "Zeile 1 Zeile 2", "PATCH title: line breaks out")
A.post(B + f"{GD}/{G8['id']}/final")
sql("UPDATE office_gen_docs SET title=? WHERE id=?", ('Alt "x"\nY: 1 – €', G8["id"]), write=True)  # an older row with a raw title
r = A.get(B + f"{GD}/{G8['id']}/pdf")
cd = r.headers.get("Content-Disposition", "")
check(r.ok and cd.startswith("attachment; filename*=UTF-8''") and '"' not in cd and "\n" not in cd and "Y" not in r.headers, f"admin PDF: clean file name {cd!r}")
T8 = A.post(B + f"{GD}/{G8['id']}/signoff", json={}).json()["url"].split("/s/q/")[1]
r = anon(f"/s/q/{T8}/pdf")
cd = r.headers.get("Content-Disposition", "")
check(r.status_code == 200 and cd.startswith("attachment; filename*=UTF-8''") and '"' not in cd and "\n" not in cd, f"customer PDF: clean file name {r.status_code} {cd!r}")
sql("UPDATE office_gen_docs SET body_hash=? WHERE id=?", ("0" * 64, G2), write=True)  # (decided already: no effect on the page)
check(anon("/s/q/" + T3).status_code == 200, "a decided link keeps its confirmation page")

# ---------------------------------------------------------------- the quotation approval links stay as they were (smoke test)
A.post(B + f"{O}/docs/{OF}/status", json={"status": "sent"})
r = A.post(B + f"{O}/docs/{OF}/signoff", json={})
check(r.ok and r.json()["kind"] == "offer" and r.json()["gen_doc_id"] is None, "a quotation approval link as before")
TQ = r.json()["url"].split("/s/q/")[1]
pg = anon("/s/q/" + TQ)
check(pg.status_code == 200 and "Imagefilm" in pg.text, "the quotation page as before")
check(post(TQ, f=form_key(pg.text), name="Max Muster", ok="1", do="accept").status_code == 303 and A.get(B + f"{O}/docs/{OF}").json()["status"] == "accepted",
      "the quotation accepted as before")

# ---------------------------------------------------------------- a person without organisation (personal office)  # freelancer-matrix: office
check(Do.get(B + O + "/settings").json().get("role") == "admin", "personal office: Dora is its admin")
Do.put(B + O + "/settings", json={"lang": "en", "company_fields": {"name": "Dora Film", "street": "Weg 2", "zip": "12345", "city": "Musterstadt", "country": "DE"}})
CP = Do.post(B + "/api/clients", json={"name": "Privatkunde Eins", "street": "Weg 1", "zip": "10000", "city": "Berlin", "country": "DE"}).json()["id"]
LD = Do.post(B + "/api/lists", json={"name": "Dora Projekt"}).json()["id"]
st = Do.get(B + TP + "/starters").json()
check(st["lang"] == "en" and st["starters"][0]["name"] == "Service agreement", "personal office: samples in its document language (en)")
TD = Do.post(B + TP, json={"starter": "nda"}).json()["id"]
check(A.patch(B + f"{TP}/{TD}", json={"name": "x"}).status_code == 404 and Ca.get(B + f"{GD}/{G}").status_code == 404, "others reach nothing of the personal office")
check(Do.post(B + GD, json={"template_id": TD, "client_id": CL}).status_code == 404, "personal office: an organisation's client 404")
check(Do.post(B + GD, json={"template_id": TD, "client_id": CP, "list_id": L}).status_code == 404, "personal office: an organisation's list 404")
r = Do.post(B + GD, json={"template_id": TD, "client_id": CP, "list_id": LD})
check(r.status_code == 201 and r.json()["list_name"] == "Dora Projekt", f"personal office: a document {r.status_code} {r.text[:160]}")
GP = r.json()["id"]
check(str(sql("SELECT body FROM office_gen_docs WHERE id=?", (GP,))[0][0]).startswith("kenc1:"), "personal office: encrypted at rest")
pv = Do.post(B + GD + "/preview", json={"gen_doc_id": GP}).json()
check("Privatkunde Eins, Weg 1\n10000 Berlin" in pv["text"] and "Dora Projekt" in pv["text"] and "Dora Film" in pv["text"], "personal office: the preview")
F = Do.post(B + f"{GD}/{GP}/final").json()
check(F["status"] == "final" and F["node_id"], "personal office: finished")
n = sql("SELECT n.org_id, n.owner_id, p.name FROM fs_nodes n JOIN fs_nodes p ON p.id=n.parent_id WHERE n.id=?", (F["node_id"],))
DORA = Do.get(B + "/api/state").json()["me"]["id"]
check(n and n[0][0] is None and n[0][1] == DORA and n[0][2] == "Privatkunde Eins", f"personal office: the PDF in Dora's private documents {n}")
check(A.get(B + f"/api/docs/{F['node_id']}").status_code in (403, 404), "personal office: the PDF is not the others'")
S = Do.post(B + f"{GD}/{GP}/signoff", json={}).json()
TP_ = S["url"].split("/s/q/")[1]
pg = anon("/s/q/" + TP_)
check(pg.status_code == 200 and "Dora Film" in pg.text, "personal office: the customer page")
check(in_pdf(anon(f"/s/q/{TP_}/pdf").content, "Privatkunde Eins"), "personal office: the customer's PDF has the recipient")
check(post(TP_, f=form_key(pg.text), name="Paula Privat", ok="1", do="accept").status_code == 303, "personal office: signed")
d = Do.get(B + f"{GD}/{GP}").json()
check(d["status"] == "signed" and d["signed_node_id"], "personal office: signed PDF filed")
check(in_pdf(Do.get(B + f"{GD}/{GP}/pdf?signed=1").content, F["body_hash"]), "personal office: the hash in the signed PDF")
check(requests.get(B + GD, headers=AGH).status_code == 403, "agent: 403 (also with data)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
