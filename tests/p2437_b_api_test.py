#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.437.0 B API tests (#3621): the quotation status "superseded" with its reference replaces_id. Invented companies only.
 - duplicating a sent / accepted quotation with {replaces: true}: the old one is superseded at once, the copy carries
   replaces_id, both name each other (replaces / replaced_by), a retry with the same client_ref changes nothing
 - without replaces (a supplement): no reference, both may be accepted, nothing is superseded
 - a reference with the old one set back to sent: accepting the new one (by hand, by the client's link) supersedes it, a deal
   of the old quotation follows and is won
 - superseded counts nowhere: cash flow, purchases; list filter; the approval link of the old one is void, no new link
 - status rules: no superseded from a draft, back from superseded by hand works
 - deleting the draft of the copy gives the old quotation its status back
 - the agent API shows status and links; a person without an organisation has all of it (freelancer-matrix: office)
usage: p2437_b_api_test.py <datadir>"""
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
MONTH = "2026-11"

subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
FID, Fr = freelancer(B, A)


def anon(path):
    return requests.get(B + path, allow_redirects=False, headers={"Accept-Language": "en"})


def customer(path, **d):
    return requests.post(B + path, data=d, allow_redirects=False, headers={"User-Agent": "TestBrowser/1.0", "Accept-Language": "en"})


def run(S, who):
    P = lambda path, **kw: S.post(B + path, **kw)  # noqa: E731
    G = lambda path: S.get(B + path).json()  # noqa: E731
    check(S.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel"}, "lang": "en"}).ok, f"{who}: office settings")
    cl = S.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstrasse 5", "zip": "50000", "city": "Koeln", "country": "DE"}).json()["id"]

    def offer(status="sent"):
        r = P(D, json={"kind": "offer", "client_id": cl, "service_from": f"{MONTH}-05", "items": [{"title": "Schnitt", "qty": 1, "rate": 1000, "cost": 200}]})
        check(r.status_code == 201, f"{who}: quotation " + r.text[:160])
        if status != "draft":
            check(P(f"{D}/{r.json()['id']}/status", json={"status": status}).ok, f"{who}: set {status}")
        return r.json()["id"]

    def planned():
        return {e["doc_id"] for e in G(f"{O}/cashflow?from={MONTH}&months=2").get("entries", []) if e.get("kind") == "offer"}

    def bought():
        return {e.get("doc_id") for e in G(f"{O}/cashflow?from={MONTH}&months=2").get("entries", []) if e.get("kind") == "purchase"}

    def status(did):
        return G(f"{D}/{did}")["status"]

    # ---- yes on duplicating: superseded at once, both directions
    q1 = offer("accepted")
    check(q1 in planned(), f"{who}: an accepted quotation is in the cash flow")
    check(q1 in bought(), f"{who}: its purchase is in the plan ({bought()})")
    r = P(f"{D}/{q1}/duplicate", json={"replaces": True, "client_ref": f"{who}-dup-1"})
    check(r.status_code == 201 and r.json()["replaces_id"] == q1 and r.json()["status"] == "draft", f"{who}: the copy replaces the old one " + r.text[:200])
    q2 = r.json()["id"]
    old, new = G(f"{D}/{q1}"), G(f"{D}/{q2}")
    check(old["status"] == "superseded" and old["status_text"] == "Superseded", f"{who}: the old one is superseded at once ({old['status']})")
    check([x["id"] for x in old["replaced_by"]] == [q2] and old["replaces"] is None, f"{who}: the old one names the new one")
    check(new["replaces"]["id"] == q1 and new["replaces"]["status"] == "superseded" and new["replaced_by"] == [], f"{who}: the new one names the old one")
    check(q1 not in planned() and q1 not in bought(), f"{who}: superseded: not in the cash flow, no purchase")
    check(q1 in [x["id"] for x in G(f"{D}?kind=offer&status=superseded")["docs"]], f"{who}: the list filter finds it")
    check("superseded" in old["statuses"], f"{who}: listed among the statuses")
    r = P(f"{D}/{q1}/duplicate", json={"replaces": True, "client_ref": f"{who}-dup-1"})
    check(r.ok and r.json()["id"] == q2, f"{who}: the same request again is the same copy")
    r = P(f"{D}/{q1}/duplicate", json={"replaces": True})
    check(r.status_code == 201 and r.json().get("replaces_id") is None, f"{who}: a superseded quotation is not replaced twice " + r.text[:120])
    S.delete(B + f"{D}/{r.json()['id']}")

    # ---- a supplement: no reference, both accepted
    n1 = offer("accepted")
    r = P(f"{D}/{n1}/duplicate", json={})
    n2 = r.json()["id"]
    check(r.status_code == 201 and r.json().get("replaces_id") is None, f"{who}: no answer = no reference")
    check(status(n1) == "accepted", f"{who}: the original stays accepted")
    check(P(f"{D}/{n2}/status", json={"status": "accepted"}).ok and status(n1) == "accepted" and status(n2) == "accepted", f"{who}: a supplement: both accepted")
    d = offer("draft")
    r = P(f"{D}/{d}/duplicate", json={"replaces": True})
    check(r.status_code == 201 and r.json().get("replaces_id") is None and status(d) == "draft", f"{who}: a draft cannot be replaced")
    inv = P(D, json={"kind": "invoice", "client_id": cl, "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]}).json()["id"]
    check(P(f"{D}/{inv}/duplicate", json={"replaces": True}).json().get("replaces_id") is None, f"{who}: invoices have no reference")

    # ---- the status rules
    check(P(f"{D}/{d}/status", json={"status": "superseded"}).status_code == 409, f"{who}: no superseded from a draft")
    check(P(f"{D}/{inv}/status", json={"status": "superseded"}).status_code == 400, f"{who}: not an invoice status")

    # ---- set back, then accepted by hand: superseded automatically, the deal follows
    a1 = offer("sent")
    a2 = P(f"{D}/{a1}/duplicate", json={"replaces": True}).json()["id"]
    check(status(a1) == "superseded", f"{who}: superseded by the copy")
    deal = P(O + "/deals", json={"title": "Imagefilm", "stage": "offer", "value": "1000", "client_id": cl}).json()
    r = S.patch(B + O + f"/deals/{deal['id']}", json={"offer_id": a1})
    check(r.ok, f"{who}: a deal of the old quotation " + r.text[:120])
    check(P(f"{D}/{a1}/status", json={"status": "sent"}).ok and status(a1) == "sent", f"{who}: back from superseded by hand")
    check(P(f"{D}/{a2}/status", json={"status": "sent"}).ok and status(a1) == "sent", f"{who}: sending the new one changes nothing")
    check(P(f"{D}/{a2}/status", json={"status": "accepted"}).ok, f"{who}: the new one accepted")
    check(status(a1) == "superseded", f"{who}: accepting supersedes the old one automatically")
    dl = next(x for x in G(O + "/deals")["items"] if x["id"] == deal["id"])
    check(dl["offer_id"] == a2 and dl["stage"] == "won", f"{who}: the deal moved to the new quotation and is won ({dl['offer_id']}, {dl['stage']})")

    # ---- the client's link: the old one is void, the new one supersedes it
    c1 = offer("sent")
    t1 = P(f"{D}/{c1}/signoff", json={}).json()["url"].split("/s/q/")[1]
    check(anon("/s/q/" + t1).status_code == 200, f"{who}: the link works while sent")
    c2 = P(f"{D}/{c1}/duplicate", json={"replaces": True}).json()["id"]
    check(anon("/s/q/" + t1).status_code in (404, 410), f"{who}: the link of the superseded quotation is void ({anon('/s/q/' + t1).status_code})")
    r = customer("/s/q/" + t1, do="accept", name="Erika Example", ok="1")
    check(r.status_code in (404, 410) and status(c1) == "superseded", f"{who}: it cannot be accepted any more ({r.status_code}, {status(c1)})")
    check(P(f"{D}/{c1}/signoff", json={}).status_code == 409, f"{who}: no new link on a superseded quotation")
    check(P(f"{D}/{c1}/status", json={"status": "sent"}).ok, f"{who}: back to sent")
    check(P(f"{D}/{c2}/status", json={"status": "sent"}).ok, f"{who}: the new one sent")
    t2 = P(f"{D}/{c2}/signoff", json={}).json()["url"].split("/s/q/")[1]
    pg = anon("/s/q/" + t2).text
    r = customer("/s/q/" + t2, f=re.findall(r'name="f" value="([0-9a-f]+)"', pg)[0], do="accept", name="Erika Example", ok="1")
    check(r.status_code == 303 and status(c2) == "accepted", f"{who}: the client accepts the new one ({r.status_code}, {status(c2)})")
    check(status(c1) == "superseded", f"{who}: the client's acceptance supersedes the old one")

    # ---- deleting the draft of the copy: the old status is back
    for st in ("sent", "accepted"):
        x1 = offer(st)
        x2 = P(f"{D}/{x1}/duplicate", json={"replaces": True}).json()["id"]
        check(status(x1) == "superseded", f"{who}: {st}: superseded")
        check(S.delete(B + f"{D}/{x2}").ok, f"{who}: {st}: the draft goes")
        check(status(x1) == st, f"{who}: {st}: the old status is back ({status(x1)})")

    # ---- the agent API sees status and links
    tag = who[:3]
    check(S.put(B + O + "/settings", json={"agents_read": 1}).ok, f"{who}: agents may read")
    r = P("/api/my/agents", json={"username": f"{tag}bot", "display_name": "Office Bot", "scopes": ["read", "office"]})
    check(r.status_code == 201, f"{who}: an agent " + r.text[:200])
    AH = {**H, "Authorization": "Bearer " + r.json()["token"]}
    check(S.patch(B + f"{O}/agents/{r.json()['id']}", json={"office_drafts": True}).ok, f"{who}: the agent's office switch")
    r = requests.get(B + f"/api/v1/office/docs/{q1}", headers=AH)
    j = r.json() if r.ok else {}
    check(r.ok and j["status"] == "superseded" and [x["id"] for x in j["replaced_by"]] == [q2], f"{who}: an agent reads status and link " + r.text[:200])
    check(all("list_id" not in x for x in j.get("replaced_by") or []), f"{who}: list_id stays internal")
    r = requests.get(B + "/api/v1/office/docs?kind=offer&status=superseded", headers=AH)
    check(r.ok and q1 in [x["id"] for x in r.json()["data"]], f"{who}: the agents' list filter " + r.text[:160])


A.patch(B + "/api/settings", json={"features": "cal,comments,office,clients", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
run(A, "instance")
run(Fr, "freelancer")

print(f"p2437_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
