#!/usr/bin/env python3
"""Webhooks: settings API (validation, limits, secret shown once and stored sealed, IDOR), delivery of every event kind
to a stub receiver inside the container (stub_webhook.py), HMAC-SHA256 signature (verified here like a receiver would),
headers, payload content (the owner's view: own tags, list, actor, via web / api / public link), event scoping (only
lists the owner sees, the chosen events, collaboration switches, disabled users), retries with backoff (shortened via
KALMIDO_WEBHOOK_BACKOFF) -> turned off + admin alert, redirects not followed, timeouts, response bodies ignored, the SSRF
guard (http:// only for allowed hosts, private / loopback / link-local / CGNAT addresses and DNS names pointing there,
checked when connecting), "Send test", the delivery log (last 50, no bodies), cascade on user delete and KALMIDO_WEBHOOKS=0.
Starts its OWN test containers (start.sh).
usage: webhooks_test.py <datadir>"""
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
STUB = "http://127.0.0.1:8097"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def start(extra):
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA)
    subprocess.run(["cp", os.path.join(N, "stub_webhook.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=" ".join(extra)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webhook.py"])
    time.sleep(0.8)


def hooks_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "wh.log")) if x.strip()]
    except FileNotFoundError:
        return []


def wait_for(pred, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(0.3)
    return pred()


def got(path, event=None, n=1, timeout=15):
    """Requests of the stub for this path (and event) once at least n arrived."""
    def f():
        x = [r for r in hooks_log() if r["path"] == path and (event is None or r["headers"].get("X-Kalmido-Event") == event)]
        return x if len(x) >= n else None
    return wait_for(f, timeout) or []


def verify(req, secret):
    sig = dict(p.split("=", 1) for p in req["headers"]["X-Kalmido-Signature"].split(","))
    want = hmac.new(secret.encode(), sig["t"].encode() + b"." + req["body"].encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig["v1"], want) and abs(time.time() - int(sig["t"])) < 300


def mk(s, url, events, name="", expect=201):
    r = s.post(B + "/api/me/webhooks", json={"name": name, "url": url, "events": events})
    assert r.status_code == expect, (url, r.status_code, r.text)
    return r.json()


ALL = ["task.created", "task.updated", "task.completed", "task.reopened", "task.deleted", "comment.created", "list.shared"]

# ================================================================== 1. KALMIDO_WEBHOOKS=0
start(["-e KALMIDO_WEBHOOKS=0", "-e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097"])
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "password": "password123"}).ok
A = sess("alice")
check(A.get(B + "/api/state").json()["webhooks"] == {"enabled": False}, "off: state says disabled")
check(A.post(B + "/api/me/webhooks", json={"url": STUB + "/ok", "events": ALL}).status_code == 409, "off: adding refused")
check(A.get(B + "/api/me/webhooks").json()["enabled"] is False, "off: list says disabled")
dbx("INSERT INTO webhooks(user_id,name,url,events,secret,enabled,created_at,updated_at) VALUES(1,'x',?,?,'',1,'2026','2026')",
    (STUB + "/ok", ",".join(ALL)))
A.post(B + "/api/tasks", json={"title": "not sent"})
time.sleep(3)
check(not hooks_log() and not dbx("SELECT 1 FROM webhook_queue"), "off: nothing queued or sent")

# ================================================================== 2. main container
start(["--add-host evil.test:127.0.0.1", "--add-host meta.test:169.254.169.254", "--add-host ten.test:10.1.2.3",
       "--add-host cgnat.test:100.64.1.1", "-e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097", "-e KALMIDO_WEBHOOK_BACKOFF=1,1,1,1",
       "-e KALMIDO_WEBHOOK_TICK=1", "-e KALMIDO_ADMIN_ALERTS=1", "-e KALMIDO_ADMIN_ALERT_WINDOW=3"])
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
for u in ("bob", "carol"):
    assert A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"}).ok
A.patch(B + "/api/users/1", json={"ntfy_topic": "admintopic"})
Bo, Ca = sess("bob"), sess("carol")
check(A.get(B + "/api/state").json()["webhooks"] == {"enabled": True}, "state: webhooks on")

# ---- settings API: validation + SSRF at save time
for url, what in (("http://example.com/hook", "http:// to a public host"), ("https://10.1.2.3/x", "private IP"),
                  ("https://127.0.0.1/x", "loopback"), ("https://169.254.169.254/latest", "link-local / metadata"),
                  ("https://[::1]/x", "IPv6 loopback"), ("https://100.64.1.1/x", "CGNAT"), ("https://localhost/x", "localhost"),
                  ("ftp://example.com/x", "ftp"), ("https://user:pw@example.com/x", "credentials in the URL"), ("javascript:alert(1)", "javascript"),
                  ("https://exa mple.com/", "space"), ("", "empty"), ("https://" + "a" * 2100 + ".com", "too long"), ("http://127.0.0.1:8098/x", "allowed host, other port")):
    r = A.post(B + "/api/me/webhooks", json={"url": url, "events": ["task.created"]})
    check(r.status_code == 400, f"refused at save: {what} ({r.status_code})")
check(A.post(B + "/api/me/webhooks", json={"url": STUB + "/ok", "events": []}).status_code == 400, "at least one event")
check(A.post(B + "/api/me/webhooks", json={"url": STUB + "/ok", "events": ["task.exploded"]}).status_code == 400, "unknown event refused")
check(A.post(B + "/api/me/webhooks", json={"url": STUB + "/ok", "events": ["task.created"]}, headers={"X-Requested-With": ""}).status_code == 403,
      "CSRF header needed")
w1 = mk(A, STUB + "/a", ALL, "all")
check(w1["secret"].startswith("whsec_") and len(w1["secret"]) >= 40, "secret whsec_… shown on creation")
S1 = w1["secret"]
lst = A.get(B + "/api/me/webhooks").json()
check(lst["enabled"] and lst["events"] == ALL and len(lst["hooks"]) == 1 and "secret" not in lst["hooks"][0], "list: never the secret")
row = dbx("SELECT secret FROM webhooks WHERE id=?", (w1["id"],))[0][0]
raw = open(os.path.join(DATA, "tasks.db"), "rb").read() + (open(os.path.join(DATA, "tasks.db-wal"), "rb").read()
                                                          if os.path.exists(os.path.join(DATA, "tasks.db-wal")) else b"")
check(row.startswith("v1.") and S1 not in row and S1.encode() not in raw, "secret stored sealed, never in clear text")
check(Bo.patch(B + f"/api/me/webhooks/{w1['id']}", json={"url": STUB + "/x"}).status_code == 404
      and Bo.delete(B + f"/api/me/webhooks/{w1['id']}").status_code == 404 and Bo.get(B + f"/api/me/webhooks/{w1['id']}/log").status_code == 404
      and Bo.post(B + f"/api/me/webhooks/{w1['id']}/test").status_code == 404, "IDOR: other users' webhooks are 404")
check(A.patch(B + f"/api/me/webhooks/{w1['id']}", json={"url": "http://ten.test/x"}).status_code == 400, "patch: same URL checks")

# ---- deliveries: every event, signature, headers, payload
wb = mk(Bo, STUB + "/b", ALL, "bob")
lid = A.post(B + "/api/lists", json={"name": "Garden"}).json()["id"]
t = A.post(B + "/api/tasks", json={"title": "Water roses", "list_id": lid, "tags": ["garden"], "due": "2026-10-01", "priority": 5}).json()
r = got("/a", "task.created")
check(len(r) == 1, "task.created delivered once")
if r:
    req, p = r[0], json.loads(r[0]["body"])
    check(verify(req, S1), "signature verifies (HMAC-SHA256 of t.body)")
    check(not verify(req, "whsec_wrong"), "wrong secret does not verify")
    h = req["headers"]
    check(h.get("Content-Type") == "application/json" and h.get("X-Kalmido-Event") == "task.created" and h.get("X-Kalmido-Attempt") == "1"
          and h.get("X-Kalmido-Delivery") == p["id"] and h.get("User-Agent", "").startswith("Kalmido/"), "headers " + str({k: v for k, v in h.items() if k.startswith("X-")}))
    check(p["event"] == "task.created" and p["webhook_id"] == w1["id"] and p["actor"] == {"id": 1, "name": "Alice"} and p["via"] == "web"
          and p["data"]["task"]["title"] == "Water roses" and p["data"]["task"]["tags"] == ["garden"] and p["data"]["task"]["priority"] == "high"
          and p["data"]["list"] == {"id": lid, "name": "Garden"}, "payload " + json.dumps(p)[:400])
    check("secret" not in req["body"] and "token" not in req["body"] and "password" not in req["body"], "no secrets in the payload")
check(not got("/b", timeout=2), "scoping: bob does not get events of alice's private list")
A.patch(B + f"/api/tasks/{t['id']}", json={"title": "Water the roses", "due": "2026-10-02"})
r = got("/a", "task.updated")
check(r and json.loads(r[0]["body"])["data"]["changes"] == ["title", "due"], "task.updated with changes " + (r[0]["body"][:300] if r else ""))
A.post(B + f"/api/tasks/{t['id']}/complete", json={})
r = got("/a", "task.completed")
check(r and json.loads(r[0]["body"])["data"]["task"]["status"] == "done", "task.completed")
time.sleep(1.5)
check(len(got("/a", "task.updated", timeout=0)) == 1, "completing sends task.completed, not also task.updated")
A.post(B + f"/api/tasks/{t['id']}/reopen", json={})
check(got("/a", "task.reopened"), "task.reopened")
A.post(B + f"/api/tasks/{t['id']}/comments", json={"body": "looks dry"})
r = got("/a", "comment.created")
check(r and json.loads(r[0]["body"])["data"]["comment"]["text"] == "looks dry", "comment.created with the text")
A.delete(B + f"/api/tasks/{t['id']}")
r = got("/a", "task.deleted")
check(r and json.loads(r[0]["body"])["data"]["permanent"] is False and json.loads(r[0]["body"])["data"]["task"]["deleted"] is True, "task.deleted (trash)")
A.delete(B + f"/api/tasks/{t['id']}?hard=1")
r = got("/a", "task.deleted", n=2)
check(len(r) == 2 and json.loads(r[1]["body"])["data"]["permanent"] is True and json.loads(r[1]["body"])["data"]["task"]["title"] == "Water the roses",
      "task.deleted (permanent) with the last known data")
# sharing: list.shared to the owner and the new member; afterwards bob gets the list's events (his own tags)
A.put(B + f"/api/lists/{lid}/members", json={"user_id": 2, "role": "view"})
ra, rb = got("/a", "list.shared"), got("/b", "list.shared")
check(ra and rb and json.loads(rb[0]["body"])["data"]["member"]["id"] == 2 and json.loads(rb[0]["body"])["data"]["role"] == "view", "list.shared to owner + member")
t2 = A.post(B + "/api/tasks", json={"title": "Mow", "list_id": lid, "tags": ["alice-tag"]}).json()
rb = got("/b", "task.created")
check(rb and json.loads(rb[0]["body"])["data"]["task"]["title"] == "Mow" and json.loads(rb[0]["body"])["data"]["task"]["tags"] == [],
      "shared (view only): bob gets task.created, without alice's tags")
check(verify(rb[0], wb["secret"]) if rb else False, "bob's delivery signed with bob's secret")
# via API: payload says so
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
requests.post(B + "/api/v1/tasks", headers={"Authorization": "Bearer " + tok}, json={"title": "via api", "list_id": lid})
r = wait_for(lambda: [x for x in hooks_log() if x["path"] == "/a" and '"via api"' in x["body"]])
check(r and json.loads(r[0]["body"])["via"] == "api", "via = api for API changes")
# event filter: carol only wants completions
wc = mk(Ca, STUB + "/c", ["task.completed"], "carol")
A.put(B + f"/api/lists/{lid}/members", json={"user_id": 3, "role": "edit"})
A.post(B + "/api/tasks", json={"title": "no event for carol", "list_id": lid})
A.post(B + f"/api/tasks/{t2['id']}/complete", json={})
rc = got("/c", "task.completed")
time.sleep(1.5)
check(rc and all(x["headers"]["X-Kalmido-Event"] == "task.completed" for x in hooks_log() if x["path"] == "/c"), "only the chosen events")
# collaboration off for everyone: shared lists are the owner's only -> no more events for bob / carol
A.patch(B + "/api/admin/settings", json={"collab_all": False})
n_b = len([x for x in hooks_log() if x["path"] == "/b"])
A.post(B + "/api/tasks", json={"title": "collab off", "list_id": lid})
got("/a", "task.created", n=4)
time.sleep(1.5)
check(len([x for x in hooks_log() if x["path"] == "/b"]) == n_b, "collaboration off: members get nothing")
A.patch(B + "/api/admin/settings", json={"collab_all": True})
# disabled user: nothing for them
A.patch(B + "/api/users/2", json={"disabled": True})
A.post(B + "/api/tasks", json={"title": "bob disabled", "list_id": lid})
got("/a", "task.created", n=5)
time.sleep(1.5)
check(len([x for x in hooks_log() if x["path"] == "/b"]) == n_b, "disabled user: no deliveries")
A.patch(B + "/api/users/2", json={"disabled": False})
Bo = sess("bob")

# ---- retries with backoff -> turned off + admin alert
wf = mk(A, STUB + "/fail", ["task.created"], "failing")
A.post(B + "/api/tasks", json={"title": "will fail"})
r = got("/fail", n=5, timeout=25)
check(len(r) == 5 and [x["headers"]["X-Kalmido-Attempt"] for x in r] == ["1", "2", "3", "4", "5"]
      and len({x["headers"]["X-Kalmido-Delivery"] for x in r}) == 1, "5 attempts, same delivery id " + str([x["headers"].get("X-Kalmido-Attempt") for x in r]))
gaps = [r[i + 1]["at"] - r[i]["at"] for i in range(len(r) - 1)]
check(all(g >= 0.9 for g in gaps), "backoff between attempts " + str([round(g, 1) for g in gaps]))
w = wait_for(lambda: [x for x in A.get(B + "/api/me/webhooks").json()["hooks"] if x["id"] == wf["id"] and not x["enabled"]])
check(w and w[0]["disabled_reason"] == "failures" and w[0]["last"]["status"] == 500, "turned off after the last retry " + str(w[:1]))
time.sleep(4)
al = dbx("SELECT kind, message FROM admin_alerts WHERE kind='integration'")
check(any("Webhook" in m and "turned off" in m for _, m in al), "admin alert (integration) " + str(al))
check(not any("/fail" in m or STUB in m for _, m in al), "the alert does not name the URL")
lg = A.get(B + f"/api/me/webhooks/{wf['id']}/log").json()["items"]
check(len(lg) == 5 and all(not x["ok"] and x["status"] == 500 and x["error"] == "http" for x in lg) and "body" not in json.dumps(lg),
      "delivery log: 5 failed attempts, status only")
A.post(B + "/api/tasks", json={"title": "while off"})
time.sleep(2)
check(len(got("/fail", timeout=0)) == 5, "turned off: nothing more is sent")
r = A.patch(B + f"/api/me/webhooks/{wf['id']}", json={"enabled": True, "url": STUB + "/ok2"})
check(r.ok and r.json()["enabled"] and r.json()["disabled_reason"] == "", "turned on again (clears the reason)")

# ---- redirects, timeouts, response bodies
wr = mk(A, STUB + "/redirect", ["task.created"], "redir")
wbig = mk(A, STUB + "/big", ["task.created"], "big")
A.post(B + "/api/tasks", json={"title": "redirect me"})
check(got("/redirect"), "redirect target called once")
time.sleep(2)
check(not got("/ok-after-redirect", timeout=0), "redirect not followed")
lg = wait_for(lambda: A.get(B + f"/api/me/webhooks/{wr['id']}/log").json()["items"])
check(lg and lg[-1]["error"] == "redirect" and lg[-1]["status"] == 302, "redirect = failed delivery " + str(lg[-1:]))
lg = wait_for(lambda: A.get(B + f"/api/me/webhooks/{wbig['id']}/log").json()["items"])
check(lg and lg[0]["ok"] and lg[0]["status"] == 200, "large response body ignored (ok)")
A.patch(B + f"/api/me/webhooks/{wr['id']}", json={"enabled": False})
A.patch(B + f"/api/me/webhooks/{wbig['id']}", json={"enabled": False})

# ---- SSRF at connect time (DNS names that point inside), "Send test"
for host in ("evil.test:8097", "meta.test", "ten.test", "cgnat.test"):
    wx = mk(A, f"https://{host}/x", ["task.created"], host)
    r = A.post(B + f"/api/me/webhooks/{wx['id']}/test").json()
    check(not r["ok"] and r["error"] == "blocked" and r["error_text"], f"connect-time guard: {host} blocked ({r['error']})")
    A.delete(B + f"/api/me/webhooks/{wx['id']}")
check(not [x for x in hooks_log() if x["path"] == "/x"], "blocked hosts were never contacted")
r = A.post(B + f"/api/me/webhooks/{w1['id']}/test").json()
pings = got("/a", "ping")
check(r["ok"] and r["status"] == 200 and pings and verify(pings[0], S1) and json.loads(pings[0]["body"])["event"] == "ping", "Send test: signed ping")
lg = A.get(B + f"/api/me/webhooks/{w1['id']}/log").json()["items"]
check(lg[0]["event"] == "ping" and lg[0]["ok"], "test shows in the log")
codes = [A.post(B + f"/api/me/webhooks/{w1['id']}/test").status_code for _ in range(21)]
check(429 in codes, "Send test: rate limited " + str(codes[-3:]))

# ---- secret rotation
ns = A.post(B + f"/api/me/webhooks/{w1['id']}/secret").json()["secret"]
check(ns != S1 and ns.startswith("whsec_"), "new secret")
A.post(B + "/api/tasks", json={"title": "after rotation"})
r = wait_for(lambda: [x for x in hooks_log() if x["path"] == "/a" and "after rotation" in x["body"]])
check(r and verify(r[0], ns) and not verify(r[0], S1), "signed with the new secret only")

# ---- log keeps the last 50
dbx("DELETE FROM webhook_log")
for i in range(55):
    Ca.post(B + "/api/tasks", json={"title": f"n{i}"})
wc2 = mk(Ca, STUB + "/c2", ["task.created"], "c2")
for i in range(55):
    Ca.post(B + "/api/tasks", json={"title": f"m{i}"})
got("/c2", n=55, timeout=30)
time.sleep(1.5)
check(dbx("SELECT COUNT(*) FROM webhook_log WHERE webhook_id=?", (wc2["id"],))[0][0] == 50, "delivery log: last 50 kept")
check(len(Ca.get(B + f"/api/me/webhooks/{wc2['id']}/log").json()["items"]) == 50, "log API: 50")
cols = [r[1] for r in dbx("PRAGMA table_info(webhook_log)")]
check("payload" not in cols and "body" not in cols, "log table has no bodies")

# ---- limits, cascade
for i in range(8):
    mk(Ca, STUB + f"/c{i + 3}", ["task.created"])
check(Ca.post(B + "/api/me/webhooks", json={"url": STUB + "/c99", "events": ["task.created"]}).status_code == 409, "at most 10 webhooks")
check(A.delete(B + f"/api/me/webhooks/{w1['id']}").ok and not dbx("SELECT 1 FROM webhook_log WHERE webhook_id=?", (w1["id"],)), "delete: log gone too")
Ca.post(B + "/api/tasks", json={"title": "queued"})
dbx("UPDATE webhook_queue SET next_at=next_at+3600")
A.put(B + f"/api/lists/{lid}/members", json={"user_id": 3, "role": "view"})
check(A.delete(B + "/api/users/3").ok, "delete carol")
check(not dbx("SELECT 1 FROM webhooks WHERE user_id=3") and not dbx("SELECT 1 FROM webhook_queue q LEFT JOIN webhooks w ON w.id=q.webhook_id WHERE w.id IS NULL"),
      "user deleted: webhooks + queue gone")
check(all(r[0] for r in dbx("SELECT enabled FROM webhooks WHERE id=?", (wb["id"],))), "bob's webhook untouched")

# ---- timeout (last: a hanging receiver blocks the delivery thread for 10 s per attempt)
wsl = mk(Bo, STUB + "/slow", ["task.created"], "slow")
Bo.post(B + "/api/tasks", json={"title": "slow"})
lg = wait_for(lambda: Bo.get(B + f"/api/me/webhooks/{wsl['id']}/log").json()["items"], 25)
check(lg and lg[-1]["error"] == "timeout" and 9000 <= lg[-1]["ms"] <= 12500, "10 s timeout " + str(lg[-1:]))
Bo.delete(B + f"/api/me/webhooks/{wsl['id']}")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
