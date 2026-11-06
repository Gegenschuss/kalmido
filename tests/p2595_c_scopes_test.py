#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.595.0 (#4505): a personal API token never has the agents' scopes office, layouts and import.
 - creating (Settings and POST /api/v1/me/tokens) or changing a personal token with one of them: 400, nothing stored or changed;
   the same for a person without an organisation
 - a personal token stored with them before (written into the database here) shows them neither in scopes nor in
   effective_scopes (token list, /api/v1/me), and a token it creates cannot get them
 - an agent gets office / layouts / import as before
Invented names only."""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
import dbx as dbxm  # noqa: E402
from kt import B, DATA, check, done  # noqa: E402

V = B + "/api/v1"
ONLY = ("office", "layouts", "import")
kt.fresh()
A = kt.setup(lang="en")
FID, Fr = freelancer(B, A, "frida")


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    c.execute(q, args)
    c.commit()
    c.close()


def bearer(t):
    return {"Authorization": "Bearer " + t}


for who, s in (("admin", A), ("freelancer", Fr)):
    # ---- refused when created or changed (rollback: before the fix 201 / 200 with the scope stored)
    for sc in ONLY:
        r = s.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", sc]})
        check(r.status_code == 400, f"{who}: a personal token with {sc}: 400 ({r.status_code} {r.text[:160]})")
    n = len(s.get(B + "/api/me/tokens").json()["tokens"])
    check(n == 0, f"{who}: nothing stored ({n})")
    r = s.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "tasks:write", "account", "integrations"]})
    check(r.status_code == 201, f"{who}: a token with other scopes as ever {r.text[:160]}")
    TID, TOK = r.json()["id"], r.json()["token"]
    r = s.patch(B + f"/api/me/tokens/{TID}", json={"scopes": ["read", "import"]})
    check(r.status_code == 400, f"{who}: changing a personal token to import: 400 ({r.status_code})")
    t = next(x for x in s.get(B + "/api/me/tokens").json()["tokens"] if x["id"] == TID)
    check(t["scopes"] == ["account", "integrations", "read", "tasks:write"], f"{who}: the token stays as it was {t['scopes']}")
    r = requests.post(V + "/me/tokens", headers=bearer(TOK), json={"name": "sub", "scopes": ["read", "layouts"]})
    check(r.status_code == 400, f"{who}: a token creating a token with layouts: 400 ({r.status_code} {r.text[:160]})")

    # ---- stored before the fix: neither shown nor effective (rollback: shown in scopes and effective_scopes)
    sql("UPDATE api_tokens SET scopes=? WHERE id=?", ("read,tasks:write,account,integrations,office,layouts,import", TID))
    t = next(x for x in s.get(B + "/api/me/tokens").json()["tokens"] if x["id"] == TID)
    check(not set(ONLY) & set(t["scopes"]) and not set(ONLY) & set(t["effective_scopes"]) and "tasks:write" in t["effective_scopes"],
          f"{who}: an old token with agent scopes: not shown, not effective ({t['scopes']} / {t['effective_scopes']})")
    me = requests.get(V + "/me", headers=bearer(TOK)).json()["token"]
    check(not set(ONLY) & set(me["scopes"]) and not set(ONLY) & set(me["effective_scopes"]),
          f"{who}: /api/v1/me shows none of them ({me['scopes']} / {me['effective_scopes']})")
    r = requests.post(V + "/me/tokens", headers=bearer(TOK), json={"name": "sub", "scopes": ["read", "office"]})
    check(r.status_code == 400, f"{who}: the old token cannot hand office on ({r.status_code})")
    r = requests.post(V + "/me/tokens", headers=bearer(TOK), json={"name": "sub", "scopes": ["read", "tasks:write"]})
    check(r.status_code == 201 and not set(ONLY) & set(r.json()["effective_scopes"]), f"{who}: other scopes as ever {r.text[:160]}")

# ---- an agent keeps them
r = A.post(B + "/api/admin/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office", "layouts", "import"]})
check(r.status_code == 201 and set(ONLY) <= set(r.json()["effective_scopes"]), f"an agent gets office, layouts and import {r.text[:240]}")
if r.status_code == 201:
    me = requests.get(V + "/me", headers=bearer(r.json()["token"])).json()["token"]
    check(set(ONLY) <= set(me["effective_scopes"]), f"... and has them on its token ({me['effective_scopes']})")

sys.exit(done("p2595_c_scopes"))
