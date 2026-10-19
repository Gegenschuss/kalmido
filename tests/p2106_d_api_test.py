#!/usr/bin/env python3
"""2.106.0 API tests, part D (#2031, agents draft letters), own container (start.sh). Invented companies, people and texts only.
tenant-matrix: office
freelancer-matrix: office
 - API v1 (scope office, the switches of the office drafts): an agent creates a letter draft (status draft, agent_id set,
   a chat card), with answers = a document shared with it in the office's documents space (linked as answers); a document
   not shared, a private one, one of another organisation: 404; an agent without its office switch / with the privacy
   switch off: 403; a member as requested_by: refused
 - it sees only its own letters (list, read; a person's letter 404), changes only its own draft (400 once sent), links
   only its own draft with a shared document; the people's letter routes (incl. marking as sent) are 403 for agent tokens
 - the button at a document: GET /api/office/letters/doc/<id>/agents names only agents the document is shared with (others
   = the number that could), members 403, another organisation 404; ask-agent without a share 403 with a readable text
   (nothing shared automatically), with a share the event letter_draft_requested reaches the agent
 - OpenAPI with x-kalmido-scope office
 - a person without an organisation (personal office) and her own agent: the same flow; another office's agent: 404
usage: p2106_d_api_test.py <datadir>      (P2106D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import json
import os
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,files,docs"
O = "/api/office"
V = B + "/api/v1/office"


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


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


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


def upload(s, name, lines, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text_pdf(lines), "application/pdf"))])
    if not r.ok:
        print(r.status_code, r.text[:300])
        app_log()
    assert r.ok, r.text
    return r.json()["ids"][0]


def share(s, nid, aid):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json={"agent_id": aid, "role": "view"})
    check(r.status_code == 201, f"setup: share document {nid} with agent {aid} ({r.status_code} {r.text[:150]})")


def my_agent(s, name, org=None, scopes=("read", "office", "files:read")):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": list(scopes), "org_id": org})
    assert r.status_code == 201, r.text
    return r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}


def ag(h, m, path="", **kw):
    return requests.request(m, V + path, headers=h, **kw)


def events(h, kind="letter_draft_requested"):
    r = requests.get(B + "/api/v1/agent/events", params={"since": 0, "limit": 200}, headers=h)
    return [e for e in r.json().get("data", []) if e["event"] == kind] if r.ok else []


if os.environ.get("P2106D_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
for s in (A, Ca):
    s.get(B + O + "/settings")
CL = A.post(B + "/api/clients", json={"name": "Musterfirma GmbH", "address": "Weg 2\n10115 Berlin"}).json()["id"]

AG, AH = my_agent(A, "letterbot", ORG)
AG2, AH2 = my_agent(A, "quietbot", ORG)  # its office switch stays off
CB, CH = my_agent(Ca, "betabot", ORG2)
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok, "setup: the office switch of the agent")
check(Ca.patch(B + f"{O}/agents/{CB}", json={"office_drafts": True}).ok, "setup: the office switch of Beta's agent")

D1 = upload(A, "anhoerung.pdf", ["Finanzamt Musterstadt", "Anhoerung zur Steuererklaerung 2025", "Frist 30.11.2026"], f"org:{ORG}")
D2 = upload(A, "mahnung.pdf", ["Beispiel Versicherung AG", "Erinnerung Beitrag"], f"org:{ORG}")
DP = upload(A, "privat.pdf", ["Private Post", "Nachbarschaftsfest"], "private")
DC = upload(Ca, "beta.pdf", ["Beta Post", "Angebot Druckerei"], f"org:{ORG2}")
share(A, D1, AG)
A.post(B + f"/api/files/nodes/{DP}/shares", json={"agent_id": AG, "role": "view"})  # a private document (may be refused: the boundary)
share(Ca, DC, CB)

# ---------------------------------------------------------------- the switches
r = ag(AH, "POST", "/letters", json={"subject": "Test", "body": "Text"})
check(r.status_code == 403, f"privacy switch off: 403 ({r.status_code} {r.text[:150]})")
check(A.get(B + f"{O}/letters/doc/{D1}/agents").json().get("data") == [], "privacy switch off: no agent at the document")
check(A.put(B + O + "/settings", json={"agents_read": 1}).ok, "setup: the area's privacy switch on")
r = ag(AH2, "POST", "/letters", json={"subject": "Test", "body": "Text"})
check(r.status_code == 403, f"an agent without its office switch: 403 ({r.status_code})")
r = ag(AH, "POST", "/letters", json={"subject": "Test", "body": "Text", "requested_by": BOB})
check(r.status_code in (403, 404), f"a member (whom the personal agent does not serve) as requested_by: refused ({r.status_code})")
r = ag(AH, "POST", "/letters", json={"subject": "", "body": ""})
check(r.status_code == 400, f"neither subject nor text: 400 ({r.status_code})")
r = ag(AH, "POST", "/letters", json={"subject": "X", "status": "sent"})
check(r.status_code == 400, f"unknown fields (status): 400 ({r.status_code})")

# ---------------------------------------------------------------- drafts
r = ag(AH, "POST", "/letters", json={"subject": "Kündigung Wartungsvertrag", "body": "Hiermit kündigen wir den Vertrag.", "client_id": CL})
if r.status_code >= 500:
    app_log()
check(r.status_code == 201, f"a letter draft without answers: 201 ({r.status_code} {r.text[:200]})")
L1 = r.json() if r.status_code == 201 else {}
check(L1.get("status") == "draft" and L1.get("agent_id") == AG and L1.get("client_id") == CL and L1.get("app_url") == f"#office/letters/{L1.get('id')}",
      f"the draft: status draft, agent_id, client, app_url {L1}")
check(bool(L1.get("chat_message_id")), "the card in the person's chat (notify default true)")
r = A.get(B + f"/api/agents/{AG}/chat")
chat = json.dumps(r.json(), ensure_ascii=False) if r.ok else r.text  # umlauts are escaped in the raw JSON
check("Kündigung Wartungsvertrag" in chat and f"#office/letters/{L1.get('id')}" in chat, "the card names the subject and opens the letter")
h = A.get(B + f"{O}/letters/{L1.get('id')}")
check(h.ok and h.json().get("agent_id") == AG and h.json().get("status") == "draft", f"the admin sees the agent's draft ({h.status_code})")
for nid, what in ((D2, "not shared"), (DP, "private (another documents space)"), (DC, "of another organisation"), (999999, "missing")):
    r = ag(AH, "POST", "/letters", json={"answers": nid, "subject": "Antwort", "body": "Text"})
    check(r.status_code == 404, f"answers = a document {what}: 404 ({r.status_code} {r.text[:120]})")
r = ag(AH, "POST", "/letters", json={"answers": D1, "subject": "Stellungnahme zur Anhörung", "body": "Sehr geehrte Damen und Herren,\n\nanbei.", "notify": False})
if r.status_code >= 500:
    app_log()
check(r.status_code == 201, f"a draft that answers a shared document: 201 ({r.status_code} {r.text[:200]})")
L2 = r.json() if r.status_code == 201 else {}
check({"node_id": D1, "kind": "answers"} in (L2.get("links") or []) and "chat_message_id" not in L2, f"linked as answers, no card with notify false {L2.get('links')}")
r = A.post(B + f"{O}/letters", json={"subject": "Brief einer Person", "body": "Text"})
LP = r.json().get("id") if r.status_code == 201 else 0
check(bool(LP), f"setup: a person's letter ({r.status_code})")

r = ag(AH, "GET", "/letters")
ids = [x["id"] for x in r.json().get("data", [])] if r.ok else []
check(r.ok and set(ids) == {L1.get("id"), L2.get("id")}, f"the list: only the agent's own drafts {ids}")
check(ag(AH, "GET", f"/letters/{LP}").status_code == 404, "a person's letter: 404")
check(ag(AH, "GET", f"/letters/{L1.get('id')}").json().get("subject") == "Kündigung Wartungsvertrag", "reading its own draft")
check(ag(AH, "GET", "/letters", params={"status": "x"}).status_code == 400, "an unknown status: 400")
check(ag(CH, "GET", f"/letters/{L1.get('id')}").status_code in (403, 404), "another organisation's agent: not its letter")

r = ag(AH, "PATCH", f"/letters/{L1.get('id')}", json={"subject": "Kündigung zum Jahresende"})
check(r.ok and r.json().get("subject") == "Kündigung zum Jahresende", f"changing its own draft ({r.status_code} {r.text[:120]})")
check(ag(AH, "PATCH", f"/letters/{LP}", json={"subject": "X"}).status_code == 404, "changing a person's letter: 404")
check(ag(AH, "PATCH", f"/letters/{L1.get('id')}", json={"status": "sent"}).status_code == 400, "setting the status: 400 (unknown field)")
r = ag(AH, "POST", f"/letters/{L1.get('id')}/links", json={"node_id": D1, "kind": "reply"})
check(r.status_code == 201 and {"node_id": D1, "kind": "reply"} in r.json().get("links", []), f"linking its draft with a shared document ({r.status_code})")
check(ag(AH, "POST", f"/letters/{L1.get('id')}/links", json={"node_id": D2}).status_code == 404, "linking a document not shared: 404")
check(ag(AH, "POST", f"/letters/{L1.get('id')}/links", json={"node_id": D1, "kind": "copy"}).status_code == 400, "an unknown kind: 400")
check(ag(AH, "POST", f"/letters/{LP}/links", json={"node_id": D1}).status_code == 404, "linking a person's letter: 404")

# the people's routes stay closed to agent tokens: no sending, no marking as sent
for m, p in (("POST", f"{O}/letters/{L1.get('id')}/sent"), ("GET", f"{O}/letters/{L1.get('id')}"), ("POST", f"{O}/letters"),
             ("POST", f"{O}/letters/doc/{D1}/ask-agent"), ("GET", f"{O}/letters/doc/{D1}/agents")):
    r = requests.request(m, B + p, headers=AH, json={"agent_id": AG})
    check(r.status_code == 403, f"agent token on the people's route {m} {p}: 403 ({r.status_code})")
check(requests.post(V + f"/letters/{L1.get('id')}/sent", headers=AH, json={}).status_code in (404, 405), "no sending route in the API v1")
r = A.post(B + f"{O}/letters/{L1.get('id')}/sent", json={"channel": "post"})
check(r.ok and r.json().get("status") == "sent", f"setup: a person marks the draft as sent ({r.status_code} {r.text[:120]})")
check(ag(AH, "PATCH", f"/letters/{L1.get('id')}", json={"subject": "Später"}).status_code == 400, "changing a sent letter: 400")
check(ag(AH, "POST", f"/letters/{L1.get('id')}/links", json={"node_id": D1}).status_code == 400, "linking a sent letter: 400")
check(L1.get("id") not in [x["id"] for x in ag(AH, "GET", "/letters").json().get("data", [])], "the default list: drafts only")
check(L1.get("id") in [x["id"] for x in ag(AH, "GET", "/letters", params={"status": "all"}).json().get("data", [])], "status all: its sent letter too")

# ---------------------------------------------------------------- the button at a document
r = A.get(B + f"{O}/letters/doc/{D1}/agents")
check(r.ok and r.json().get("data") == [{"id": AG, "name": "Letterbot"}], f"the agents the document is shared with (not the one without switch) {r.text[:200]}")
r = A.get(B + f"{O}/letters/doc/{D2}/agents")
check(r.ok and r.json().get("data") == [] and r.json().get("others") == 1, f"not shared: no agent, one that could {r.text[:200]}")
check(Bo.get(B + f"{O}/letters/doc/{D1}/agents").status_code == 403, "a member: 403")
check(Ca.get(B + f"{O}/letters/doc/{D1}/agents").status_code == 404, "another organisation: 404")
check(A.get(B + f"{O}/letters/doc/{DP}/agents").status_code == 404, "a private document at the organisation's office: 404")
r = A.post(B + f"{O}/letters/doc/{D2}/ask-agent", json={"agent_id": AG})
check(r.status_code == 403 and "Share the document with the agent first" in r.text, f"ask without a share: 403 with a readable text ({r.status_code} {r.text[:150]})")
check(requests.get(B + f"/api/v1/documents/{D2}", headers=AH).status_code == 404, "nothing shared automatically (the agent still cannot read it)")
check(A.post(B + f"{O}/letters/doc/{D1}/ask-agent", json={"agent_id": AG2}).status_code == 404, "ask an agent without its office switch: 404")
check(A.post(B + f"{O}/letters/doc/{D1}/ask-agent", json={"agent_id": "x"}).status_code == 400, "agent_id not a number: 400")
check(Bo.post(B + f"{O}/letters/doc/{D1}/ask-agent", json={"agent_id": AG}).status_code == 403, "a member may not ask: 403")
r = A.post(B + f"{O}/letters/doc/{D1}/ask-agent", json={"agent_id": AG, "note": "Bitte freundlich, Frist verlängern lassen."})
if r.status_code >= 500:
    app_log()
check(r.ok and r.json().get("ok"), f"ask the agent ({r.status_code} {r.text[:150]})")
ev = events(AH)
d = ev[-1]["data"] if ev else {}
check(len(ev) == 1 and d.get("node_id") == D1 and d.get("requested_by") == ALICE and d.get("title") == "anhoerung.pdf"
      and d.get("note") == "Bitte freundlich, Frist verlängern lassen." and d.get("office", {}).get("id") == ORG and d.get("org_id") == ORG
      and "create_letter_draft" in d.get("hint", ""), f"the event letter_draft_requested reaches the agent {d}")
check(not events(AH2) and not events(CH), "no other agent hears of it")

# ---------------------------------------------------------------- OpenAPI, the office log
spec = requests.get(B + "/api/v1/openapi.json").json()
pp = spec.get("paths", {})
check(all(pp.get(p, {}).get(m, {}).get("x-kalmido-scope") == "office" for p, m in (("/office/letters", "get"), ("/office/letters", "post"),
      ("/office/letters/{id}", "get"), ("/office/letters/{id}", "patch"), ("/office/letters/{id}/links", "post"))), "OpenAPI: the letter routes with scope office")
check("letter_draft_requested" in requests.get(B + "/api/v1/agent", headers=AH).text, "GET /agent lists the event")

# ---------------------------------------------------------------- a person without an organisation, her own agent
FID, Fr = freelancer(B, A)
Fr.get(B + O + "/settings")
check(Fr.put(B + O + "/settings", json={"agents_read": 1}).ok, "freelancer: the privacy switch of her personal office")
FA, FH = my_agent(Fr, "fridabot")
check(Fr.patch(B + f"{O}/agents/{FA}", json={"office_drafts": True}).ok, "freelancer: the office switch of her agent")
DF = upload(Fr, "kasse.pdf", ["Krankenkasse Beispiel", "Beitragsbescheid 2027"], "private")
r = Fr.get(B + f"{O}/letters/doc/{DF}/agents")
check(r.ok and r.json().get("data") == [] and r.json().get("others") == 1, f"freelancer: not shared yet {r.text[:150]}")
share(Fr, DF, FA)
r = Fr.get(B + f"{O}/letters/doc/{DF}/agents")
check(r.ok and [x["id"] for x in r.json().get("data", [])] == [FA], f"freelancer: her agent at her document {r.text[:150]}")
check(Fr.post(B + f"{O}/letters/doc/{DF}/ask-agent", json={"agent_id": FA}).ok, "freelancer: asks her agent")
ev = events(FH)
check(ev and ev[-1]["data"].get("node_id") == DF and ev[-1]["data"].get("org_id") is None and ev[-1]["data"]["office"].get("personal") is True,
      f"freelancer: the event (personal office) {ev[-1]['data'] if ev else None}")
r = ag(FH, "POST", "/letters", json={"answers": DF, "subject": "Widerspruch Beitragsbescheid", "body": "Gegen den Bescheid lege ich Widerspruch ein."})
if r.status_code >= 500:
    app_log()
check(r.status_code == 201 and r.json().get("agent_id") == FA, f"freelancer: her agent drafts the answer ({r.status_code} {r.text[:150]})")
LF = r.json().get("id") if r.status_code == 201 else 0
check(Fr.get(B + f"{O}/letters/{LF}").ok, "freelancer: she opens the draft in her office")
check(A.get(B + f"{O}/letters/{LF}").status_code == 404, "freelancer: another office does not see it")
check(ag(AH, "POST", "/letters", json={"answers": DF, "subject": "X", "body": "Y"}).status_code == 404, "another office's agent: her document 404")
check(ag(AH, "GET", f"/letters/{LF}").status_code == 404, "another office's agent: her letter 404")
check(Fr.get(B + f"{O}/letters/doc/{D1}/agents").status_code == 404, "freelancer: an organisation's document 404")

print(f"p2106_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
