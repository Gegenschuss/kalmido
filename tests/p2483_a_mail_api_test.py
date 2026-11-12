#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.483.0 (#1902): agents and personal tokens read filed e-mails through the REST API v1 (GET /mails, GET /mails/{id}).
 - an organisation's agent: the mails of a project shared with it; a client's mails when it sees a project of that client;
   never a project not shared with it (404), never the mails "Not assigned" (also not its owner's), never a deleted one,
   never a mail of another organisation; an agent without a project of the client gets 404 for the client
 - a person's token: what the person sees (a member sees the organisation's client), but never "Not assigned" (also not
   the own ones); another organisation's person 404; a token limited to one project: only that project's mails
 - client_id / list_id: exactly one (400); the answer has no write flags, no file ids (tenant-matrix: hubmail)
 - a person without an organisation: her private client's mails with her token and with her own agent (through her private
   project of that client); her own "Not assigned" stays hidden, another person gets 404 (freelancer-matrix: hub)
usage: p2483_a_mail_api_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402  2.1021.0 (#5775): kt.proved
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402
from kt import B, DATA, FAILS, H, OKS, check, fresh, sess  # noqa: E402,F401

V = B + "/api/v1"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        if write:
            c.execute(sql, args)
            c.commit()
            return None
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def hdr(token):
    return {"Authorization": "Bearer " + token, "X-Requested-With": "kalmido"}


fresh(prefix="P2483A")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok, "setup: personal agents on")
ids = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, ERIN = ids["bob"], ids["carol"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ERIN})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
kt.proved()  # 2.1021.0 (#5775): an organisation admin invites by address only an account that proved it
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG), "setup: carol joins Alpha")
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})


def client(s, name, org=None):
    r = s.post(B + "/api/clients", json={"name": name, "email": f"{name.lower()}@example.com", **({"org_id": org} if org else {})})
    assert r.ok, r.text
    return r.json()["id"]


def project(s, name, cid, org=None):
    r = s.post(B + "/api/lists", json={"name": name, **({"org_id": org} if org else {})})
    assert r.ok, r.text
    lid = r.json()["id"]
    r = s.patch(B + f"/api/lists/{lid}", json={"client_id": cid})
    assert r.ok, r.text
    return lid


N_ = [0]


def mail(owner, org, cid=None, lid=None, subject="Hello", deleted=False, ws=None):
    N_[0] += 1
    mid = f"<p2483a-{N_[0]}@example.com>"
    dbx("INSERT INTO hub_mails(org_id,owner_id,client_id,list_id,ws,message_id,from_addr,from_name,subject,body,created_at,deleted_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (org, owner, cid, lid, ws or (f"o{org}" if org else f"u{owner}"), mid, "kunde@example.com", "Kunde", subject, "Text of " + subject,
         "2026-10-30T10:00:00Z", "2026-10-31T10:00:00Z" if deleted else None), write=True)
    return dbx("SELECT id FROM hub_mails WHERE message_id=?", (mid,))[0][0]


def get(h, path, **q):
    return requests.get(V + path, headers=h, params=q)


def ids_of(r):
    return sorted(m["id"] for m in (r.json().get("data") or [])) if r.ok else None


CB = client(Bo, "Acme", ORG)
LB = project(Bo, "Acme film", CB, ORG)       # shared with the agent
LX = project(Bo, "Acme secret", CB, ORG)     # not shared with the agent
CE = client(Er, "Betaco", ORG2)
LE = project(Er, "Betaco film", CE, ORG2)
m_list = mail(BOB, ORG, CB, LB, "Shoot dates")
m_client = mail(BOB, ORG, CB, None, "Invoice question")
m_x = mail(BOB, ORG, CB, LX, "Secret plan")
m_un = mail(BOB, ORG, None, None, "Not assigned yet")
m_del = mail(BOB, ORG, CB, None, "Deleted one", deleted=True)
m_beta = mail(ERIN, ORG2, CE, LE, "Beta mail")

r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "mailbot", "display_name": "Mailbot", "org_id": ORG})
assert r.status_code in (200, 201), r.text
AG, AGH = r.json()["id"], hdr(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "lonebot", "display_name": "Lonebot", "org_id": ORG})
assert r.status_code in (200, 201), r.text
AG2H = hdr(r.json()["token"])
check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: Acme film shared with the agent")

# ================================================================ 1. the organisation's agent
r = get(AGH, "/mails", list_id=LB)
check(r.ok and ids_of(r) == [m_list], f"agent: the mails of its shared project ({r.status_code} {r.text[:200]})")
one = (r.json().get("data") or [{}])[0] if r.ok else {}
check(one.get("subject") == "Shoot dates" and one.get("client_id") == CB and one.get("list_id") == LB and one.get("list_name") == "Acme film",
      f"agent: subject, client and project in the list ({one})")
check(not ({"mine", "can_write", "folder_id", "eml_id", "note", "body"} & set(one)), f"agent: no write flags, file ids or text in the list ({sorted(one)})")
r = get(AGH, "/mails", client_id=CB)
check(r.ok and ids_of(r) == sorted([m_list, m_client]), f"agent: the client's mails through its project, not the other project's, not deleted ({ids_of(r)})")
r = get(AGH, f"/mails/{m_client}")
check(r.ok and r.json().get("body") == "Text of Invoice question" and "body_short" in r.json() and isinstance(r.json().get("attachments"), list),
      f"agent: one client mail with its text ({r.status_code} {r.text[:200]})")
check(not ({"can_write", "folder_id", "eml_id"} & set(r.json() if r.ok else {})), "agent: one mail without write flags / file ids")
for mid, why in ((m_x, "a project not shared with it"), (m_un, "\"Not assigned\""), (m_del, "a deleted mail"), (m_beta, "another organisation")):
    check(get(AGH, f"/mails/{mid}").status_code == 404, f"agent: {why} = 404")
check(get(AGH, "/mails", list_id=LX).status_code == 404, "agent: the list of a project not shared with it = 404")  # tenant: GET /api/v1/mails
check(get(AGH, "/mails", list_id=LE).status_code == 404 and get(AGH, "/mails", client_id=CE).status_code == 404,
      "agent: another organisation's project / client = 404")
check(get(AG2H, "/mails", client_id=CB).status_code == 404 and get(AG2H, f"/mails/{m_client}").status_code == 404,
      "an agent without a project of the client: the client's mails = 404")
check(get(AGH, "/mails").status_code == 400 and get(AGH, "/mails", client_id=CB, list_id=LB).status_code == 400,
      "client_id / list_id: exactly one, else 400")
check(get(AGH, "/mails", list_id=LB, q="shoot").ok and ids_of(get(AGH, "/mails", list_id=LB, q="nothingmatches")) == [],
      "agent: q searches the shared mails")
r = get(AGH, "/mails", client_id=CB, limit=1)
check(r.ok and len(r.json()["data"]) == 1 and r.json().get("next_cursor"), f"agent: pages of limit (next_cursor) ({r.text[:160]})")
r2 = get(AGH, "/mails", client_id=CB, limit=1, cursor=r.json().get("next_cursor") or "")
check(r2.ok and len(r2.json()["data"]) == 1 and r2.json()["data"][0]["id"] != r.json()["data"][0]["id"] and r2.json()["next_cursor"] is None,
      "agent: the second page")
# the app route keeps its 403 for agents (only the API route reads)
check(requests.get(B + f"/api/hubmail/mails/{m_list}", headers=AGH).status_code in (401, 403), "agent: the app route stays closed")

# ================================================================ 2. personal tokens
r = Bo.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read"]})
assert r.ok, r.text
BOH = hdr(r.json()["token"])
r = get(BOH, "/mails", client_id=CB)
check(r.ok and ids_of(r) == sorted([m_list, m_client, m_x]), f"bob's token: every mail of his client, not deleted ({ids_of(r)})")
check(get(BOH, f"/mails/{m_un}").status_code == 404, "bob's token: his own \"Not assigned\" mail stays in the app (404)")
r = Ca.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read"]})
CAH = hdr(r.json()["token"])
check(get(CAH, f"/mails/{m_client}").ok, "carol's token (a member who sees the client): the client's mail")
r = Er.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read"]})
ERH = hdr(r.json()["token"])
check(get(ERH, "/mails", client_id=CB).status_code == 404 and get(ERH, f"/mails/{m_client}").status_code == 404
      and get(ERH, f"/mails/{m_list}").status_code == 404, "another organisation's person: 404")
check(get(ERH, f"/mails/{m_beta}").ok, "erin reads her own organisation's mail")
r = Bo.post(B + "/api/me/tokens", json={"name": "one project", "scopes": ["read"], "list_ids": [LB]})
assert r.ok, r.text
BLH = hdr(r.json()["token"])
r = get(BLH, "/mails", client_id=CB)
check(r.ok and ids_of(r) == [m_list, m_client], f"a token limited to Acme film: the client's mails without the other project's ({ids_of(r)})")
check(get(BLH, f"/mails/{m_x}").status_code == 404 and get(BLH, "/mails", list_id=LX).status_code == 404, "... the other project = 404")

# ================================================================ 3. a person without an organisation (freelancer-matrix: hub)
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
FC = client(Fr, "Privatkunde")
FL = project(Fr, "Privatprojekt", FC)
m_f = mail(FID, None, FC, None, "Private client mail")
m_fl = mail(FID, None, FC, FL, "Private project mail")
m_fun = mail(FID, None, None, None, "Private not assigned")
r = Fr.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read"]})
FH = hdr(r.json()["token"])
r = get(FH, "/mails", client_id=FC)
check(r.ok and ids_of(r) == sorted([m_f, m_fl]), f"freelancer: her private client's mails with her token ({r.status_code} {r.text[:160]})")
check(get(FH, f"/mails/{m_f}").ok and get(FH, f"/mails/{m_fun}").status_code == 404, "freelancer: one mail; her \"Not assigned\" stays hidden")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read"], "org_id": "private"})
check(r.ok, "freelancer: her own agent " + r.text[:160])
FA, FAH = r.json().get("id"), hdr(r.json().get("token", ""))
check(get(FAH, "/mails", client_id=FC).status_code == 404, "her agent without a project of the client: 404")
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "view"}).ok, "setup: her project shared with her agent")
# review 2.483 F1: the data lock "Private e-mails" (on by default) hides the mails of her private space from her agent
check(get(FAH, "/mails", client_id=FC).status_code == 404 and get(FAH, "/mails", list_id=FL).status_code == 404
      and get(FAH, f"/mails/{m_f}").status_code == 404 and get(FAH, f"/mails/{m_fl}").status_code == 404,
      "her agent with the default data lock \"Private e-mails\": 404")
check(Fr.patch(B + f"/api/agents/{FA}/data-lock", json={"areas": {"mail": False}}).ok, "setup: she opens private e-mails for her agent")
# 2.395.0 (#3380): her agent is a guest (view) of the project: its mails only once she, her own project admin, switches it on
r = get(FAH, "/mails", client_id=FC)
check(r.ok and ids_of(r) == [m_f] and get(FAH, "/mails", list_id=FL).status_code == 404 and get(FAH, f"/mails/{m_fl}").status_code == 404,
      f"#3380 her agent as a guest: the project's mail hidden without the switch ({ids_of(r)})")
check(Fr.patch(B + f"/api/lists/{FL}", json={"mail_guests": True}).ok, "#3380 she switches on: guests read the project's e-mails")
r = get(FAH, "/mails", client_id=FC)
check(r.ok and ids_of(r) == sorted([m_f, m_fl]), f"her agent: the private client's mails through the shared project ({ids_of(r)})")
check(get(FAH, f"/mails/{m_f}").ok and get(FAH, f"/mails/{m_fun}").status_code == 404, "her agent: one mail, never \"Not assigned\"")
check(get(BOH, f"/mails/{m_f}").status_code == 404 and get(AGH, f"/mails/{m_fl}").status_code == 404 and get(BOH, "/mails", client_id=FC).status_code == 404,
      "another person / another agent: the freelancer's mails = 404")

# ================================================================ 4. 2.395.0 (#3380): project mails = edit roles; guests with the project's switch
def app_list(s, lid):
    r = s.get(B + "/api/hubmail/mails", params={"list_id": lid})
    return r.json() if r.ok else {"status": r.status_code}


check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": CAROL, "role": "view"}).ok, "#3380 setup: carol a guest (view) of Acme film")
j = app_list(Ca, LB)
check(j.get("can_read") is False and j.get("mails") == [] and j.get("can_guests") is False and not j.get("address"),
      f"#3380 guest: no mails, no address, may not switch ({j})")
Bo.post(B + "/api/hubmail/address", json={"list_id": LB})  # the project's filing address exists (the guest still gets none)
check(not app_list(Ca, LB).get("address"), "#3380 guest: the project's address stays hidden")
check(Ca.get(B + f"/api/hubmail/mails/{m_list}").status_code == 404, "#3380 guest: one project mail = 404")
check(get(CAH, "/mails", list_id=LB).status_code == 404 and get(CAH, f"/mails/{m_list}").status_code == 404, "#3380 guest's token: 404")
check(Ca.patch(B + f"/api/lists/{LB}", json={"mail_guests": True}).status_code == 403, "#3380 a guest cannot switch it on")
j = app_list(Bo, LB)
check(j.get("can_read") is True and j.get("can_guests") is True and j.get("guests") is False and [m["id"] for m in j.get("mails", [])] == [m_list],
      f"#3380 owner: reads, may switch, default off ({ {k: j.get(k) for k in ('can_read', 'can_guests', 'guests')} })")
check(Bo.patch(B + f"/api/lists/{LB}", json={"mail_guests": True}).ok, "#3380 owner switches guests on")
j = app_list(Ca, LB)
check(j.get("can_read") is True and [m["id"] for m in j.get("mails", [])] == [m_list] and Ca.get(B + f"/api/hubmail/mails/{m_list}").ok
      and ids_of(get(CAH, "/mails", list_id=LB)) == [m_list], f"#3380 guest with the switch: reads (app + token) ({j.get('can_read')})")
r = get(BOH, f"/lists/{LB}")
check(r.ok and (r.json().get("data") or r.json()).get("mail_guests") is True, f"#3380 API v1: mail_guests in the project ({r.status_code})")
check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": CAROL, "role": "participant"}).ok, "#3380 setup: carol a participant")
check(Ca.get(B + f"/api/hubmail/mails/{m_list}").ok, "#3380 participant with the switch: reads")
check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": CAROL, "role": "admin"}).ok, "#3380 setup: carol a project admin")
check(Ca.patch(B + f"/api/lists/{LB}", json={"mail_guests": False}).ok and app_list(Ca, LB).get("guests") is False, "#3380 a project admin switches it off")
r = requests.patch(V + f"/lists/{LB}", headers=BOH, json={"mail_guests": True})
check(r.status_code in (400, 403) and get(BOH, f"/lists/{LB}").json().get("mail_guests") is False, f"#3380 not writable through the API v1 (app only) ({r.status_code} {r.text[:120]})")
check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": CAROL, "role": "edit"}).ok and Ca.get(B + f"/api/hubmail/mails/{m_list}").ok,
      "#3380 edit member: reads without the switch")
check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": CAROL, "role": "view"}).ok and Ca.get(B + f"/api/hubmail/mails/{m_list}").status_code == 404,
      "#3380 back to guest, switch off: 404 again")

print(f"p2483_a_mail_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
