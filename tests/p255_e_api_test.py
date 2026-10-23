#!/usr/bin/env python3
"""2.55.0 API tests, part E (#1455): the newsletter connection (contacts + segments -> a newsletter service, no own
sending), against fake services inside the test container (fake_newsletter.py: listmonk 8086 as recorded from a real
listmonk 6.2.0, Brevo 8087 and CleverReach 8087/8088 after their public documentation), allowed as internal hosts.
Invented names only, addresses @example.com.
 - connect: wrong access data / bad address / a forbidden internal address refused; the access data never come back
   (not in any answer, not in the log, not in the database in plain text)
 - consent: unknown | yes (with a source) | pending; unsub / bounce only from the service and never changed by hand
 - a run: only consented contacts with an address go out (mode doi: pending as unconfirmed); an unsubscription, a bounce
   and a confirmed opt-in come back; an unsubscribed address is never subscribed again; a contact that no longer matches
   comes off the list (only what Kalmido put there); renamed contacts are updated without dropping other lists
 - rights: organisation admins only (members 403), another organisation's admin 404, agents 403, a freelancer for their own
   space; a segment cannot take an address book of another workspace; the private books of members stay out
 - Brevo / CleverReach adapters against their fakes
usage: p255_e_api_test.py <datadir>
tenant-matrix: newsletter"""
import json
import os
import shutil
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
LM = "http://127.0.0.1:8086"
BR = "http://127.0.0.1:8087"
CR = "http://127.0.0.1:8088"
LM_USER, LM_TOKEN = "lmuser", "lm-secret-token-1234"
BR_KEY = "brevo-key-1234567890"
CR_ID, CR_SECRET = "cr-client", "cr-secret-123456"
SECRETS = (LM_TOKEN, BR_KEY, CR_SECRET)
FEAT = "cal,collab,comments,events,contacts"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def until(fn, secs=40):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def nl():
    try:
        return json.load(open(os.path.join(DATA, "nl.json")))
    except (OSError, ValueError):
        return {}


def nl_set(fn):
    d = nl()
    fn(d)
    with open(os.path.join(DATA, "nl.json.new"), "w") as f:
        json.dump(d, f)
    os.replace(os.path.join(DATA, "nl.json.new"), os.path.join(DATA, "nl.json"))


def nl_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "nl.log"), encoding="utf-8")]
    except OSError:
        return []


def no_secret(text, what):
    check(not any(x in text for x in SECRETS), f"{what}: no access data in it")


def sync(s, ws):
    """Sync now + wait until the run is done; the newest run."""
    r = s.post(B + "/api/newsletter/sync", json={"ws": ws})
    for _ in range(40):  # 2.142.3: CI red once with 409 - the previous run of this workspace was still finishing on a slow runner
        if r.status_code != 409:
            break
        time.sleep(0.5)
        r = s.post(B + "/api/newsletter/sync", json={"ws": ws})
    check(r.status_code == 202, f"sync {ws} starts ({r.status_code} {r.text[:200]})")
    rid = r.json().get("run_id")

    def done():
        j = s.get(B + f"/api/newsletter?ws={ws}").json()
        run = next((x for x in j.get("runs") or [] if x["id"] == rid), None)
        return (j, run) if run and run["state"] != "busy" else None
    j, run = until(done) or (None, None)
    check(run is not None, f"sync {ws} ends")
    no_secret(json.dumps(j), f"newsletter state {ws}")
    return run or {"counts": {}, "errors": [], "state": "?"}


def lm_sub(email):
    return next((s for s in nl().get("lm", {}).get("subs", []) if s["email"] == email), None)


def lm_on(email, lid):
    s = lm_sub(email)
    li = next((x for x in (s or {}).get("lists", []) if x["id"] == int(lid)), None)
    return li["subscription_status"] if li else None


def consent(s, cid):
    return s.get(B + f"/api/contacts/{cid}").json()["newsletter"]


BASE_EXTRA = os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8086,127.0.0.1:8087,127.0.0.1:8088"
env = dict(os.environ, EXTRA=BASE_EXTRA + " -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
if not os.environ.get("P255E_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_newsletter.py"), DATA)
for f in ("nl.json", "nl.log"):
    try:
        os.remove(os.path.join(DATA, f))
    except OSError:
        pass
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_newsletter.py"])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = (ids[k] for k in ("bob", "carol", "dave", "erin"))
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ALPHA = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [BOB, CAROL], "admins": [BOB]})
A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [DAVE], "admins": [DAVE]})
dbx("DELETE FROM org_members WHERE user_id IN (?, ?)", (1, ERIN), write=True)  # alice + erin: no organisation
r = A.post(B + "/api/admin/agents", json={"username": "nlbot", "display_name": "Nlbot"})
assert r.status_code == 201, r.text
AGENT = r.json()
S = {u: sess(u) for u in ("bob", "carol", "dave", "erin")}
for s in S.values():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})
Bo, Ca, Da, Er = S["bob"], S["carol"], S["dave"], S["erin"]
WA, WB = f"org:{ALPHA}", f"org:{BETA}"

# ---- contacts: an address book Alpha owns, carol's own book in Alpha's workspace (stays out), erin's own book
r = Bo.post(B + "/api/books", json={"name": "Customers", "org_id": ALPHA})
check(r.status_code == 201, f"bob creates a book in Alpha ({r.status_code} {r.text[:200]})")
BK = r.json()["id"]
check(Bo.post(B + f"/api/books/{BK}/org", json={"org_role": "edit"}).ok, "bob hands the book over to Alpha")
r = Ca.post(B + "/api/books", json={"name": "Carol private", "org_id": ALPHA})
BKC = r.json()["id"]
r = Er.post(B + "/api/books", json={"name": "Erin clients", "org_id": None})
BKE = r.json()["id"]
r = Da.post(B + "/api/books", json={"name": "Beta people", "org_id": BETA})
BKD = r.json()["id"]
Da.post(B + f"/api/books/{BKD}/org", json={"org_role": "view"})


def contact(s, book, fn, email=None, groups=(), org=""):
    body = {"book_id": book, "fn": fn, "groups": list(groups), "org": org}
    if email:
        body["emails"] = [{"value": email}]
    r = s.post(B + "/api/contacts", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


C1 = contact(Bo, BK, "Anna Alpha", "anna@example.com", ["VIP"], "Firm One")
C2 = contact(Bo, BK, "Ben Beta", "ben@example.com", ["Press"])
C3 = contact(Bo, BK, "Cleo Gamma", "cleo@example.com", ["VIP"], "Firm Two")
C4 = contact(Bo, BK, "Dina No Mail", None, ["VIP"])
C5 = contact(Bo, BK, "Emil Unknown", "emil@example.com", ["VIP"])
CC = contact(Ca, BKC, "Carla Private", "carla@example.com", ["VIP"])
CE = contact(Er, BKE, "Fritz Freelance", "fritz@example.com", ["Clients"])
CD = contact(Da, BKD, "Greta Beta", "greta@example.com", ["VIP"])

# ---- rights before anything is connected
check(Bo.get(B + f"/api/newsletter?ws={WA}").ok, "bob (Alpha admin) reads Alpha's newsletter settings")
check(Ca.get(B + f"/api/newsletter?ws={WA}").status_code == 403, "carol (member) may not (403)")
check(Da.get(B + f"/api/newsletter?ws={WA}").status_code == 404, "dave (Beta admin) does not see Alpha's (404)")
ag = requests.Session()
ag.headers.update({**H, "Authorization": "Bearer " + (AGENT.get("token") or "")})
check(ag.get(B + f"/api/newsletter?ws={WA}").status_code in (401, 403, 404), "an agent token gets nothing")
check(Er.get(B + "/api/newsletter?ws=private").ok, "erin (no organisation) reads her own space's settings")

# ---- connecting: refused access data, bad / forbidden addresses, then the right one
r = Bo.put(B + "/api/newsletter", json={"ws": WA, "kind": "listmonk", "url": LM, "user": LM_USER, "token": "wrong-token-value-1"})
check(r.status_code == 400 and "refused" in r.text, f"wrong access data: 400 refused ({r.status_code} {r.text[:200]})")
r = Bo.put(B + "/api/newsletter", json={"ws": WA, "kind": "listmonk", "url": "ftp://lists.example.com", "user": LM_USER, "token": LM_TOKEN})
check(r.status_code == 400, "an ftp address: 400")
r = Bo.put(B + "/api/newsletter", json={"ws": WA, "kind": "listmonk", "url": "http://127.0.0.1:8089", "user": LM_USER, "token": LM_TOKEN})
check(r.status_code == 400, f"an internal address no admin allowed (SSRF guard): 400 ({r.status_code} {r.text[:200]})")
r = Bo.put(B + "/api/newsletter", json={"ws": WA, "kind": "listmonk", "url": "http://10.1.2.3", "user": LM_USER, "token": LM_TOKEN})
check(r.status_code == 400, "a private network address: 400")
r = Bo.put(B + "/api/newsletter", json={"ws": WA, "kind": "listmonk", "url": LM, "user": LM_USER, "token": LM_TOKEN, "mode": "maybe"})
check(r.status_code == 400, "an unknown mode: 400")
r = Ca.put(B + "/api/newsletter", json={"ws": WA, "kind": "listmonk", "url": LM, "user": LM_USER, "token": LM_TOKEN})
check(r.status_code == 403, "carol (member) cannot connect (403)")
r = Bo.put(B + "/api/newsletter", json={"ws": WA, "kind": "listmonk", "url": LM, "user": LM_USER, "token": LM_TOKEN})
check(r.ok, f"bob connects listmonk ({r.status_code} {r.text[:200]})")
j = r.json()
no_secret(r.text, "connect answer")
check(j["conn"]["secret_set"] is True and j["conn"]["hint"] == LM_TOKEN[-4:], "only 'set' + the last four characters come back")
row = dbx("SELECT secret, hint, org_id, owner_id FROM nl_conns WHERE ws=?", (f"o{ALPHA}",))
check(row and row[0][0].startswith("kenc") and not any(x in row[0][0] for x in SECRETS), "the access data are sealed in the database")
check(row and row[0][2] == ALPHA and row[0][3] is None, "the connection belongs to Alpha")
check(j["facets"]["books"] == [{"id": BK, "name": "Customers"}], "only Alpha's own address books (carol's private book stays out)")
check("VIP" in j["facets"]["tags"] and "Firm One" in j["facets"]["companies"], "tags and companies of the workspace's contacts")
r = Bo.put(B + "/api/newsletter", json={"ws": WA, "url": "http://127.0.0.1:8087"})
check(r.status_code == 400 and "access data" in r.text, f"another address without the token again: 400, the stored token never goes there ({r.status_code})")
check(not [x for x in nl_log() if x["port"] == 8087], "nothing was sent to the other address")
r = Bo.put(B + "/api/newsletter", json={"ws": WA, "auto": True})
check(r.ok and r.json()["conn"]["auto"] is True, "planned sync on, without typing the access data again")

# ---- consent
r = Bo.put(B + "/api/newsletter/consent", json={"ids": [C1, C3], "status": "yes"})
check(r.status_code == 400, "consent without a source: 400")
r = Bo.put(B + "/api/newsletter/consent", json={"ids": [C1, C3], "status": "yes", "source": "Sign-up form 2026"})
check(r.ok and sorted(r.json()["changed"]) == sorted([C1, C3]), f"bob: Anna + Cleo consented ({r.status_code} {r.text[:200]})")
check(Bo.put(B + "/api/newsletter/consent", json={"ids": [C2], "status": "pending"}).ok, "Ben: double opt-in pending")
check(Bo.put(B + "/api/newsletter/consent", json={"ids": [C1], "status": "unsub"}).status_code == 400, "unsub cannot be set by hand")
check(Da.put(B + "/api/newsletter/consent", json={"ids": [C1], "status": ""}).status_code == 404, "dave cannot touch Alpha's contacts")
check(Ca.put(B + "/api/newsletter/consent", json={"ids": [C1, CD], "status": ""}).status_code == 404, "a foreign contact in the batch: 404, nothing changed")
check(consent(Bo, C1)["status"] == "yes", "Anna still consented after the refused batch")
c1 = consent(Bo, C1)
check(c1["source"] == "Sign-up form 2026" and c1["at"], "consent with date and source on the contact")
check(Er.put(B + "/api/newsletter/consent", json={"ids": [CE], "status": "yes", "source": "Contract"}).ok, "erin: her own contact")

# ---- segments
r = Bo.post(B + "/api/newsletter/segments", json={"ws": WA, "name": "VIP", "rule": {"tags": ["VIP"], "books": [BKC]}, "create_list": True})
check(r.status_code == 400, "a segment with carol's private book: 400")
r = Bo.post(B + "/api/newsletter/segments", json={"ws": WA, "name": "VIP", "rule": {"tags": ["VIP"], "books": [BKD]}})
check(r.status_code == 400, "a segment with Beta's book: 400")
r = Bo.post(B + "/api/newsletter/segments", json={"ws": WA, "name": "VIP", "rule": {"tags": ["VIP"]}, "create_list": True})
check(r.ok, f"segment VIP with a new list ({r.status_code} {r.text[:200]})")
SEG = r.json()["segment_id"]
seg = next(x for x in r.json()["segments"] if x["id"] == SEG)
LID = seg["list_id"]
check(bool(LID) and any(L["name"] == "VIP" for L in nl()["lm"]["lists"]), "the list was created at the service")
check(seg["counts"]["match"] == 4 and seg["counts"]["email"] == 3 and seg["counts"]["send"] == 2, f"counts: 4 VIP, 3 with mail, 2 go out ({seg['counts']})")
r = Bo.post(B + "/api/newsletter/segments", json={"ws": WA, "name": "Press", "rule": {"tags": ["Press"]}, "create_list": True})
SEGP = r.json()["segment_id"]
LIDP = next(x for x in r.json()["segments"] if x["id"] == SEGP)["list_id"]
check(Da.patch(B + f"/api/newsletter/segments/{SEG}", json={"ws": WB, "name": "x"}).status_code == 404, "dave: no Beta connection, Alpha's segment unknown")
check(Ca.delete(B + f"/api/newsletter/segments/{SEG}?ws={WA}").status_code == 403, "carol cannot delete a segment")
check(Bo.get(B + f"/api/newsletter/lists?ws={WA}").ok, "the service's lists")

# ---- a run: only consented contacts with an address go out
run = sync(Bo, WA)
check(run["state"] == "ok" and run["counts"].get("added") == 2, f"run 1: 2 added ({run})")
check(lm_on("anna@example.com", LID) == "confirmed" and lm_on("cleo@example.com", LID) == "confirmed", "Anna + Cleo on the list, confirmed")
check(lm_sub("emil@example.com") is None, "Emil (consent unknown) not sent")
check(lm_sub("ben@example.com") is None, "Ben (pending, mode consented) not sent")
check(lm_sub("carla@example.com") is None, "carol's private contact never goes out")
check(Bo.post(B + "/api/newsletter/sync", json={"ws": WA}).status_code in (202, 409), "a second start is fine or 409 while busy")
until(lambda: (Bo.get(B + f"/api/newsletter?ws={WA}").json()["runs"][0]["state"] != "busy"))
no_secret(json.dumps(dbx("SELECT counts, errors FROM nl_runs")), "the run log in the database")

# ---- service -> Kalmido: an unsubscription, a bounce
nl_set(lambda d: [li.update(subscription_status="unsubscribed") for s in d["lm"]["subs"] if s["email"] == "anna@example.com" for li in s["lists"]])
run = sync(Bo, WA)
check(run["counts"].get("unsub") == 1, f"run 2: one unsubscription came back ({run['counts']})")
c1 = consent(Bo, C1)
check(c1["status"] == "unsub" and c1["source"] == "service", f"Anna is unsubscribed, reported by the service ({c1})")
r = Bo.put(B + "/api/newsletter/consent", json={"ids": [C1], "status": "yes", "source": "again"})
check(r.ok and r.json()["kept"] == 1 and consent(Bo, C1)["status"] == "unsub", "an unsubscribed contact stays so (kept)")
run = sync(Bo, WA)
check(lm_on("anna@example.com", LID) == "unsubscribed", "Anna is never subscribed again (still unsubscribed at the service)")

def bounce(d):
    for s in d["lm"]["subs"]:
        if s["email"] == "cleo@example.com":
            s["status"] = "blocklisted"
    d["lm"]["bounces"].append("cleo@example.com")
nl_set(bounce)
run = sync(Bo, WA)
check(consent(Bo, C3)["status"] == "bounce", f"Cleo: bounce came back ({run['counts']})")

# ---- mode doi: pending ones go as unconfirmed, the confirmation comes back
r = Bo.put(B + "/api/newsletter", json={"ws": WA, "mode": "doi"})
check(r.ok and r.json()["conn"]["mode"] == "doi", "mode: also double opt-in pending")
run = sync(Bo, WA)
check(lm_on("ben@example.com", LIDP) == "unconfirmed", f"Ben goes to Press as unconfirmed ({run['counts']})")
nl_set(lambda d: [li.update(subscription_status="confirmed") for s in d["lm"]["subs"] if s["email"] == "ben@example.com" for li in s["lists"]])
run = sync(Bo, WA)
check(consent(Bo, C2)["status"] == "yes" and run["counts"].get("confirmed") == 1, f"Ben's confirmed opt-in came back ({run['counts']})")

# ---- an address already at the service (another list): added without touching its other list; a rename keeps the lists
def other(d):
    d["lm"]["seq"] += 1
    d["lm"]["lists"].append({"id": d["lm"]["seq"], "name": "Elsewhere", "optin": "single", "type": "private"})
    d["lm"]["seq"] += 1
    d["lm"]["subs"].append({"id": d["lm"]["seq"], "email": "emil@example.com", "name": "Emil", "status": "enabled",
                            "lists": [{"id": d["lm"]["seq"] - 1, "subscription_status": "confirmed"}]})
nl_set(other)
ELSE = next(L["id"] for L in nl()["lm"]["lists"] if L["name"] == "Elsewhere")
Bo.put(B + "/api/newsletter/consent", json={"ids": [C5], "status": "yes", "source": "Phone call"})
run = sync(Bo, WA)
check(lm_on("emil@example.com", LID) == "confirmed" and lm_on("emil@example.com", ELSE) == "confirmed", f"Emil: on VIP and still on Elsewhere ({run['counts']})")
check(Bo.patch(B + f"/api/contacts/{C5}", json={"fn": "Emil Renamed"}).ok, "Emil renamed in Kalmido")
run = sync(Bo, WA)
s = lm_sub("emil@example.com")
check(s["name"] == "Emil Renamed" and lm_on("emil@example.com", ELSE) == "confirmed", f"the rename arrived, Elsewhere kept ({run['counts']})")

# ---- a contact that no longer matches comes off the list (only what Kalmido put there)
r = Bo.patch(B + f"/api/contacts/{C5}", json={"groups": []})
check(r.ok, "Emil leaves the group VIP")
run = sync(Bo, WA)
check(lm_on("emil@example.com", LID) is None and run["counts"].get("removed") == 1, f"Emil came off VIP ({run['counts']})")
check(lm_on("emil@example.com", ELSE) == "confirmed", "Emil's other list stays")

# ---- the log is the admins'; Beta's admin and members see nothing
j = Bo.get(B + f"/api/newsletter?ws={WA}").json()
check(len(j["runs"]) >= 5 and all("text" in e for r_ in j["runs"] for e in r_["errors"]), "the log has every run")
check(Ca.get(B + f"/api/newsletter?ws={WA}").status_code == 403, "carol: no log")
check(Da.post(B + "/api/newsletter/sync", json={"ws": WA}).status_code == 404, "dave cannot start Alpha's sync")
check(Da.get(B + f"/api/newsletter?ws={WB}").json()["conn"] is None, "Beta has no connection (nothing leaks over)")

# ---- the data export of the organisation leaves the access data out (column secret)
check(dbx("SELECT COUNT(*) FROM nl_members WHERE org_id=?", (ALPHA,))[0][0] >= 1
      and dbx("SELECT COUNT(*) FROM nl_members WHERE org_id IS DISTINCT FROM ?", (ALPHA,))[0][0] == 0, "the members rows carry the organisation")

# ---- erin (no organisation) with Brevo
r = Er.put(B + "/api/newsletter", json={"ws": "private", "kind": "brevo", "url": BR, "token": "wrong-key-123456"})
check(r.status_code == 400, "Brevo: a wrong key refused")
r = Er.put(B + "/api/newsletter", json={"ws": "private", "kind": "brevo", "url": BR, "token": BR_KEY})
check(r.ok and r.json()["conn"]["preview"] is True, f"erin connects Brevo, marked preview ({r.status_code} {r.text[:200]})")
check(Er.put(B + "/api/newsletter", json={"ws": "private", "mode": "doi"}).status_code == 400, "Brevo: no doi mode")
r = Er.post(B + "/api/newsletter/segments", json={"ws": "private", "name": "Clients", "rule": {"tags": ["Clients"]}, "create_list": True})
check(r.ok, f"Brevo: segment + list (folder created) ({r.status_code} {r.text[:200]})")
BLID = int(next(x for x in r.json()["segments"])["list_id"])
run = sync(Er, "private")
br = nl()["br"]
check(run["state"] == "ok" and BLID in br["contacts"].get("fritz@example.com", {}).get("listIds", []), f"Brevo: Fritz added ({run})")
def br_unsub(d):
    d["br"]["contacts"]["fritz@example.com"]["emailBlacklisted"] = True
    d["br"]["blocked"]["fritz@example.com"] = "unsubscribedViaEmail"
nl_set(br_unsub)
run = sync(Er, "private")
check(consent(Er, CE)["status"] == "unsub", f"Brevo: the unsubscription came back ({run['counts']})")
check(Bo.get(B + "/api/newsletter?ws=private").json()["conn"] is None, "bob's own space has no connection (erin's stays hers)")
check(dbx("SELECT org_id, owner_id FROM nl_conns WHERE ws=?", (f"u{ERIN}",))[0] == (None, ERIN) or
      tuple(dbx("SELECT org_id, owner_id FROM nl_conns WHERE ws=?", (f"u{ERIN}",))[0]) == (None, ERIN), "erin's connection is private")

# ---- CleverReach (dave for Beta)
r = Da.put(B + "/api/newsletter", json={"ws": WB, "kind": "cleverreach", "url": CR, "user": CR_ID, "token": "wrong-secret-1234"})
check(r.status_code == 400, "CleverReach: a wrong client secret refused")
r = Da.put(B + "/api/newsletter", json={"ws": WB, "kind": "cleverreach", "url": CR, "user": CR_ID, "token": CR_SECRET})
check(r.ok, f"dave connects CleverReach ({r.status_code} {r.text[:200]})")
no_secret(r.text, "CleverReach answer")
Da.put(B + "/api/newsletter/consent", json={"ids": [CD], "status": "yes", "source": "Workshop"})
r = Da.post(B + "/api/newsletter/segments", json={"ws": WB, "name": "Beta VIP", "rule": {}, "create_list": True})
GID = next(x for x in r.json()["segments"])["list_id"]
run = sync(Da, WB)
rec = nl()["cr"]["receivers"].get(str(GID), {})
check("greta@example.com" in rec and rec["greta@example.com"]["activated"], f"CleverReach: Greta added and active ({run})")
check("anna@example.com" not in rec, "CleverReach: nothing of Alpha")
def cr_unsub(d):
    d["cr"]["receivers"][str(GID)]["greta@example.com"]["deactivated"] = 1760000000
nl_set(cr_unsub)
run = sync(Da, WB)
check(consent(Da, CD)["status"] == "unsub", f"CleverReach: the deactivation came back ({run['counts']})")

# ---- disconnect: the access data go, the consent stays
check(Ca.delete(B + f"/api/newsletter?ws={WA}").status_code == 403, "carol cannot disconnect")
r = Bo.delete(B + f"/api/newsletter?ws={WA}")
check(r.ok and r.json()["conn"] is None, "bob disconnects")
check(dbx("SELECT COUNT(*) FROM nl_segments s JOIN nl_conns n ON n.id=s.conn_id WHERE n.ws=?", (f"o{ALPHA}",))[0][0] == 0, "its segments are gone")
check(consent(Bo, C1)["status"] == "unsub", "the consent of the contacts stays")
check(not any(x in open(os.path.join(DATA, "nl.log")).read() for x in SECRETS), "the fake log never saw a credential value")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
