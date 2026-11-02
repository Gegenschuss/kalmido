#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.391.0 C (#3362): webhooks, API tokens and repository connections set up through /api/v1 (scope integrations), as a
person without an organisation (freelancer-matrix: own, lists, tasks) and as an organisation admin.
 - the scope integrations: never for agents (refused at creation, absent from an agent's effective scopes also with "write"),
   never part of the legacy "write"; a token without it gets 403 required_scope integrations; tokens also need account
 - a token creates a token never more than itself: scopes, addresses, projects and lifetime (not given = the calling
   token's); the new token works, revoking it stops it at once
 - secrets once: the token value, a webhook's signing secret, a repository's hook secret only in the answer that makes them;
   never in a list and never in the server's log; a repository's access token is never returned
 - webhooks only with a token for all projects; an organisation's webhooks only for its admins
 - repository connections: the project's owner (a stranger 404), the version field, removing
Fake GitHub (tests/fake_git.py, :8090) and the webhook stub (tests/stub_webhook.py, :8097) inside the container; invented
names only."""
import base64
import json
import os
import shutil
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, done, until  # noqa: E402

V = B + "/api/v1"
GH, STUB = "http://127.0.0.1:8090", "http://127.0.0.1:8097"
GHTOK = "ghp_fridaRepoAccess0042"
KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()  # a server key: repository tokens and hook secrets are sealed with it
if kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_CALENDAR_ALLOW_HOSTS": "127.0.0.1", "KALMIDO_WEBHOOK_ALLOW_HOSTS": "127.0.0.1:8097",
                 "KALMIDO_WEBHOOK_TICK": "1"}, prefix="P2391C"):
    for f in ("fake_git.py", "stub_webhook.py"):
        shutil.copy(os.path.join(N, f), DATA)
    with open(os.path.join(DATA, "git.json"), "w") as fh:
        json.dump({"8090": {"frida/app": {"token": GHTOK, "default_branch": "main"}}}, fh)
    for f in ("fake_git.py", "stub_webhook.py"):
        subprocess.run(["docker", "exec", "-d", CT, "python", "/data/" + f])
kt.docker_logs_on_first_fail()
A = kt.setup(lang="en")
FID, F = freelancer(B, A, "frida")
_, Fe = freelancer(B, A, "fenna")


class Api:
    def __init__(self, tok):
        self.tok = tok
        self.h = {"Authorization": "Bearer " + tok}

    def __getattr__(self, m):
        return lambda p, **k: requests.request(m.upper(), V + p, headers=self.h, timeout=60, **k)


def web_token(s, name, scopes, **extra):
    r = s.post(B + "/api/me/tokens", json={"name": name, "scopes": scopes, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def need(r, scope):
    return r.status_code == 403 and (r.json().get("error") or {}).get("required_scope") == scope


SECRETS = [GHTOK]

# ---- the scope: people only, never in "write"
spec = requests.get(V + "/openapi.json").json()["paths"]
ROUTES = [("get", "/me/tokens"), ("post", "/me/tokens"), ("delete", "/me/tokens/{id}"), ("get", "/me/webhooks"), ("post", "/me/webhooks"),
          ("patch", "/me/webhooks/{id}"), ("delete", "/me/webhooks/{id}"), ("post", "/me/webhooks/{id}/secret"), ("post", "/me/webhooks/{id}/test"),
          ("get", "/me/webhooks/{id}/log"), ("get", "/orgs/{id}/webhooks"), ("post", "/orgs/{id}/webhooks/{webhook_id}/secret"),
          ("post", "/lists/{id}/repos"), ("patch", "/repos/{id}"), ("delete", "/repos/{id}"), ("put", "/lists/{id}/repos/version-field")]
check(all(spec.get(p, {}).get(m, {}).get("x-kalmido-scope") == "integrations" for m, p in ROUTES),
      f"OpenAPI: every setup route needs integrations {[(m, p) for m, p in ROUTES if spec.get(p, {}).get(m, {}).get('x-kalmido-scope') != 'integrations']}")
check(spec["/lists/{id}/repos"]["get"]["x-kalmido-scope"] == "read", "OpenAPI: reading a project's repositories stays read")
offer = [o["scope"] for o in F.get(B + "/api/me/tokens").json()["scopes"]]
check("integrations" in offer, "a person may pick integrations for a token")
r = A.post(B + "/api/admin/agents", json={"username": "setupbot", "display_name": "Setupbot", "scopes": ["read", "integrations"]})
check(r.status_code == 400, f"an agent cannot get integrations {r.status_code} {r.text[:120]}")
r = A.post(B + "/api/admin/agents", json={"username": "setupbot", "display_name": "Setupbot", "scopes": ["read", "write"]})
assert r.status_code == 201, r.text
AG = Api(r.json()["token"])
check("integrations" not in AG.get("/me").json()["token"]["effective_scopes"], "an agent with write: no integrations")
check(need(AG.get("/me/webhooks"), "integrations") and need(AG.post("/me/tokens", json={"name": "x"}), "integrations"),
      "an agent is refused with required_scope integrations")
old = Api(web_token(F, "old", ["write"])["token"])
check("integrations" not in old.get("/me").json()["token"]["effective_scopes"] and need(old.get("/me/webhooks"), "integrations"),
      "the legacy write never stands for integrations")
noacc = Api(web_token(F, "noacc", ["read", "integrations"])["token"])
r = noacc.get("/me/tokens")
check(r.status_code == 403 and noacc.get("/me/webhooks").ok, f"tokens need account too, webhooks not {r.status_code}")

# ---- a token never makes more than itself (freelancer-matrix: own)
T1 = web_token(F, "setup", ["read", "structure", "account", "integrations"], expires_days=30)
SECRETS.append(T1["token"])
S1 = Api(T1["token"])
r = S1.get("/me/tokens")
check(r.ok and all("token" not in t for t in r.json()["data"]) and T1["token"] not in r.text and {"setup", "old"} <= {t["name"] for t in r.json()["data"]},
      f"GET /me/tokens lists the tokens without their value {r.text[:200]}")
r = S1.post("/me/tokens", json={"name": "more", "scopes": ["read", "time"]})
check(r.status_code == 403, f"more scopes than the calling token: 403 {r.status_code}")
check(S1.post("/me/tokens", json={"name": "w", "scopes": ["write"]}).status_code == 403, "write = more than the calling token: 403")
check(S1.post("/me/tokens", json={"name": "adm", "scopes": ["read", "admin-read"]}).status_code == 403, "admin-read for a non-admin: 403")
check(S1.post("/me/tokens", json={"name": "long", "expires_days": 365}).status_code == 403, "a longer life than the calling token: 403")
check(S1.post("/me/tokens", json={"name": "bad", "nope": 1}).status_code == 400, "an unknown field: 400")
r = S1.post("/me/tokens", json={"name": "child", "scopes": ["read", "structure"]})
check(r.status_code == 201 and r.json()["token"].startswith("abk_") and r.json()["effective_scopes"] == ["read", "structure"]
      and r.json()["expires_at"] and r.json()["expires_at"] <= T1["expires_at"],
      f"a token with fewer scopes, the calling token's expiry {r.text[:200]}")
child = r.json()
SECRETS.append(child["token"])
C1 = Api(child["token"])
check(C1.get("/me").ok and need(C1.get("/me/webhooks"), "integrations"), "the new token works with its own scopes")
r = S1.post("/me/tokens", json={"name": "short", "expires_days": 5})
check(r.status_code == 201 and r.json()["expires_at"] < T1["expires_at"], "a shorter life: 201")
S1.delete(f"/me/tokens/{r.json()['id']}")
check(S1.delete(f"/me/tokens/{child['id']}").ok and C1.get("/me").status_code == 401, "revoked: the token stops at once")
check(S1.delete(f"/me/tokens/{child['id']}").status_code == 404, "revoked twice: 404")
check(Api(web_token(Fe, "fenna", ["read", "account", "integrations"])["token"]).delete(f"/me/tokens/{T1['id']}").status_code == 404,
      "another person's token: 404")
# addresses: within the calling token's (every IPv4 address in two halves, so the test client always passes)
T2 = web_token(F, "nets", ["read", "account", "integrations"], allowed_ips=["0.0.0.0/1", "128.0.0.0/1"])
SECRETS.append(T2["token"])
S2 = Api(T2["token"])
check(S2.post("/me/tokens", json={"name": "any", "allowed_ips": ["0.0.0.0/0"]}).status_code == 403, "more addresses: 403")
check(S2.post("/me/tokens", json={"name": "v6", "allowed_ips": ["::/0"]}).status_code == 403, "an IPv6 network outside: 403")
r = S2.post("/me/tokens", json={"name": "ten", "allowed_ips": ["10.0.0.0/8"]})
check(r.status_code == 201 and r.json()["allowed_ips"] == ["10.0.0.0/8"], f"a narrower network: 201 {r.text[:160]}")
r = S2.post("/me/tokens", json={"name": "same"})
check(r.status_code == 201 and r.json()["allowed_ips"] == ["0.0.0.0/1", "128.0.0.0/1"] and r.json()["expires_at"] is None,
      f"no addresses given = the calling token's; no expiry on both {r.text[:160]}")
# projects: within the calling token's
P1 = F.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
P2 = F.post(B + "/api/lists", json={"name": "Website", "kind": "project"}).json()["id"]
T3 = web_token(F, "one", ["read", "account", "integrations"], list_ids=[P1])
SECRETS.append(T3["token"])
S3 = Api(T3["token"])
check(S3.post("/me/tokens", json={"name": "p2", "list_ids": [P2]}).status_code == 403
      and S3.post("/me/tokens", json={"name": "both", "list_ids": [P1, P2]}).status_code == 403, "more projects: 403")
r = S3.post("/me/tokens", json={"name": "inherit"})
check(r.status_code == 201 and r.json()["list_ids"] == [P1], f"no projects given = the calling token's {r.text[:160]}")
check(S3.get("/me/webhooks").status_code == 403, "webhooks need a token for all projects")

# ---- webhooks (freelancer-matrix: own)
r = S1.post("/me/webhooks", json={"name": "Zapier", "url": STUB + "/frida", "events": ["task.created"]})
check(r.status_code == 201 and r.json().get("secret", "").startswith("whsec_"), f"a webhook with its secret once {r.text[:160]}")
WH, sec1 = r.json()["id"], r.json().get("secret", "")
SECRETS.append(sec1)
r = S1.get("/me/webhooks")
check(r.ok and [h["id"] for h in r.json()["data"]] == [WH] and "secret" not in r.json()["data"][0] and sec1 not in r.text
      and "task.created" in r.json()["events"], "the list: never the secret")
r = S1.patch(f"/me/webhooks/{WH}", json={"name": "Zapier 2", "events": ["task.created", "task.completed"]})
check(r.ok and r.json()["name"] == "Zapier 2" and r.json()["events"] == ["task.created", "task.completed"] and "secret" not in r.json(), "change it")
check(S1.patch(f"/me/webhooks/{WH}", json={"url": "http://10.0.0.5/x"}).status_code == 400, "an internal address: 400 (the app's check)")
r = S1.post(f"/me/webhooks/{WH}/secret")
check(r.ok and r.json()["secret"].startswith("whsec_") and r.json()["secret"] != sec1, "a new secret, shown once")
SECRETS.append(r.json()["secret"])
# 2.391.0 review B1: with an Idempotency-Key (the MCP client sends one with every write) a secret shown once is never kept in
# idem_keys; a repeat of the key gets {"ok": true} and changes nothing, never the secret a second time
for k, path, body, word in (("p2391c-tok", "/me/tokens", {"name": "idem", "scopes": ["read"]}, "abk_"),
                            ("p2391c-sec", f"/me/webhooks/{WH}/secret", None, "whsec_")):
    hk = {**S1.h, "Idempotency-Key": k}
    r = requests.post(V + path, headers=hk, json=body, timeout=60)
    got = r.json().get("token") or r.json().get("secret") or ""
    SECRETS.append(got) if got else None
    row = kt.dbx("SELECT status, body FROM idem_keys WHERE k=?", (k,))
    check(r.ok and got.startswith(word) and row and row[0][0] == r.status_code and row[0][1] is None,
          f"B1: {path} with a key: the answer with the secret is not stored ({r.status_code} {row})")
    r2 = requests.post(V + path, headers=hk, json=body, timeout=60)
    check(r2.headers.get("Idempotent-Replayed") == "true" and word not in r2.text, f"B1: {path} sent again: no secret ({r2.text[:80]})")
    if path == "/me/tokens":
        S1.delete(f"/me/tokens/{r.json()['id']}")
r = S1.post(f"/me/webhooks/{WH}/test")
check(r.ok and r.json()["ok"] is True, f"the ping reaches the stub {r.text[:160]}")
r = until(lambda: [x for x in S1.get(f"/me/webhooks/{WH}/log").json()["items"] if x["event"] == "ping"], 15)
check(r and r[0]["ok"], "the delivery log has the ping")
Fe_t = Api(web_token(Fe, "fenna2", ["read", "integrations"])["token"])
check(Fe_t.patch(f"/me/webhooks/{WH}", json={"name": "x"}).status_code == 404 and Fe_t.delete(f"/me/webhooks/{WH}").status_code == 404,
      "another person's webhook: 404")
check(S1.delete(f"/me/webhooks/{WH}").ok and S1.get("/me/webhooks").json()["data"] == [], "delete it")

# ---- an organisation's webhooks: its admins only
r = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": A.get(B + "/api/state").json()["me"]["id"]})
assert r.ok, r.text
ORG = r.json()["id"]
TA = web_token(A, "admin", ["read", "integrations"])
SECRETS.append(TA["token"])
SA = Api(TA["token"])
r = SA.post(f"/orgs/{ORG}/webhooks", json={"name": "Org", "url": STUB + "/org", "events": ["task.created"]})
check(r.status_code == 201 and r.json()["secret"].startswith("whsec_"), f"an organisation webhook by its admin {r.text[:160]}")
OW = r.json()["id"]
SECRETS.append(r.json()["secret"])
check(SA.get(f"/orgs/{ORG}/webhooks").ok and [h["id"] for h in SA.get(f"/orgs/{ORG}/webhooks").json()["data"]] == [OW]
      and SA.get("/me/webhooks").json()["data"] == [], "listed under the organisation, not as the admin's own")
check(S1.get(f"/orgs/{ORG}/webhooks").status_code in (403, 404) and S1.post(f"/orgs/{ORG}/webhooks/{OW}/secret").status_code in (403, 404),
      "a person outside the organisation: refused")
check(SA.patch(f"/orgs/{ORG}/webhooks/{OW}", json={"enabled": False}).json()["enabled"] is False
      and SA.post(f"/orgs/{ORG}/webhooks/{OW}/secret").ok and SA.get(f"/orgs/{ORG}/webhooks/{OW}/log").ok, "change, rotate, log")
check(SA.post(f"/orgs/{ORG}/webhooks/{OW}/test").ok and SA.delete(f"/orgs/{ORG}/webhooks/{OW}").ok, "test and delete")

# ---- repository connections (freelancer-matrix: lists, tasks)
until(lambda: os.path.exists(os.path.join(DATA, "git.log")), 20)  # fake_git.py opens its log when it starts
r = S1.post(f"/lists/{P1}/repos", json={"provider": "github", "base_url": GH, "repo": "frida/app", "token": GHTOK})
check(r.status_code == 201 and r.json()["full_name"] == "frida/app" and r.json()["token"] is True and GHTOK not in r.text,
      f"connected; the access token only stored {r.text[:200]}")
RID = r.json().get("id", 0)
r = S1.get(f"/lists/{P1}/repos")
check(r.ok and [x["id"] for x in r.json()["data"]] == [RID] and GHTOK not in r.text, "read back without the access token")
check(S1.post(f"/lists/{P1}/repos", json={"provider": "github", "base_url": GH, "repo": "frida/app"}).status_code == 409, "connected twice: 409")
check(S1.post(f"/lists/{P1}/repos", json={"provider": "github", "base_url": GH, "repo": "frida/app", "secret": 1}).status_code == 400, "unknown field: 400")
check(Fe_t.post(f"/lists/{P1}/repos", json={"provider": "github", "base_url": GH, "repo": "frida/app"}).status_code == 404
      and Fe_t.delete(f"/repos/{RID}").status_code == 404, "a stranger: 404")
r = S1.patch(f"/repos/{RID}", json={"hook": "on"})
hook = r.json().get("hook_secret", "")
check(r.ok and len(hook) > 20 and r.json()["hook"] is True, f"the inbound hook on, its secret once {r.text[:160]}")
SECRETS.append(hook)
check(hook not in S1.get(f"/lists/{P1}/repos").text and hook not in F.get(B + f"/api/lists/{P1}/repos").text, "the hook secret is never read again")
check(S1.patch(f"/repos/{RID}", json={"author_name": "Frida Bot", "author_email": "bot@example.com"}).json()["author_name"] == "Frida Bot",
      "the git author")
r = S1.put(f"/lists/{P1}/repos/version-field", json={"field": "off"})
check(r.ok and F.get(B + f"/api/lists/{P1}/repos").json()["version_field"] == r.json(), f"the version field off {r.text[:160]}")
check(S1.put(f"/lists/{P1}/repos/version-field", json={"field": "nope"}).status_code == 400, "an invalid version field: 400")
check(AG.post(f"/lists/{P1}/repos", json={"repo": "frida/app"}).status_code == 403, "an agent: 403")
# 2.391.0 review S1: a folder repository (it belongs to a folder, not to one project) is out of reach of a token limited to
# projects - also when it is carried by a project the token may use; a token for all projects keeps the app's own rules
FR = kt.dbx("INSERT INTO git_conns(list_id, provider, base_url, owner, repo, next_at, created_by, created_at) "
            "VALUES(?, 'gitea', 'http://127.0.0.1:9', 'frida', 'site', 9e12, ?, '2026-10-01T00:00:00Z') RETURNING id", (P2, FID))[0][0]
kt.dbx("INSERT INTO git_folders(conn_id, owner_id, folder, created_at) VALUES(?, ?, 'Work', '2026-10-01T00:00:00Z')", (FR, FID))
check(S3.patch(f"/repos/{FR}", json={"author_name": "X"}).status_code == 404 and S3.delete(f"/repos/{FR}").status_code == 404
      and kt.dbx("SELECT COUNT(*) FROM git_conns WHERE id=?", (FR,))[0][0] == 1, "S1: a folder repository with a project-limited token: 404")
check(S1.delete(f"/repos/{RID}").ok and S1.get(f"/lists/{P1}/repos").json()["data"] == [], "removed")

# ---- no secret in the server's log
log = subprocess.run(["docker", "logs", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
check(all(s and s not in log for s in SECRETS), "no token, signing secret or access token in the server's log")

sys.exit(done("p2391_c_setup_api"))
