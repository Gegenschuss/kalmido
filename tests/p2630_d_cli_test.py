#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.630.0 D (#4520): the command line mcp/kalmido_cli.py against the test server, run as a program (KALMIDO_URL /
KALMIDO_TOKEN in its environment, as a script would use it). Invented projects and titles only. freelancer-matrix: agents
 - add (inbox and --project, --notes from stdin, --due, --priority), list (--project, --status, --search, --json), show by
   id and by ticket key (notes + comments), comment (by key, text from stdin), done (the task is done in the API; again
   = no error)
 - errors: a wrong token = exit 1 and a clear message on stderr (nothing on stdout); a read-only token: add / comment /
   done = exit 1 with the scope hint and nothing written; no KALMIDO_URL / KALMIDO_TOKEN = exit 2; a bad task reference =
   exit 2; an unknown task = exit 1
 - all as a person without an organisation (the own project, a personal token) and as an organisation's admin
usage: p2630_d_cli_test.py <datadir>      (KMT_NOSTART=1 / P2630D_NOSTART=1: a running server)"""
import json
import os
import subprocess
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

N = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(N, "..", "mcp", "kalmido_cli.py")
V = B + "/api/v1"

fresh(prefix="P2630D")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, F = freelancer(B, A)


def token(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "cli " + "-".join(scopes), "scopes": list(scopes)})
    assert r.ok, r.text
    return r.json()["token"]


def cli(tok, *args, stdin=None, url=B):
    env = {k: v for k, v in os.environ.items() if not k.startswith("KALMIDO_")}
    if url is not None:
        env["KALMIDO_URL"] = url
    if tok is not None:
        env["KALMIDO_TOKEN"] = tok
    p = subprocess.run([sys.executable, CLI, *args], input=stdin, capture_output=True, text=True, env=env, timeout=60)
    return p.returncode, p.stdout, p.stderr


def js(tok, *args, stdin=None):
    rc, out, err = cli(tok, "--json", *args, stdin=stdin)
    assert rc == 0, (args, rc, out, err)
    return json.loads(out)


def run(who, s):
    tok = token(s, ("read", "tasks:write", "comments"))
    ro = token(s, ("read",))
    H = {"Authorization": "Bearer " + tok}
    P = s.post(B + "/api/lists", json={"name": f"Garden plan {who}"}).json()["id"]
    r = s.patch(B + f"/api/lists/{P}", json={"ticket_key": "GRD"})
    check(r.ok, f"{who}: the project gets the ticket key GRD ({r.status_code} {r.text[:120]})")

    # add: inbox, then the project with notes from stdin, a due date and a priority
    rc, out, err = cli(tok, "add", "Buy seeds")
    check(rc == 0 and "created" in out and "Buy seeds" in out and not err, f"{who}: add into the inbox ({rc} {out!r} {err!r})")
    t = js(tok, "add", "Dig the beds", "--project", str(P), "--notes", "-", "--due", "2026-12-01", "--priority", "high",
           stdin="Two beds\nnear the fence\n")
    tid = t.get("id")
    got = requests.get(V + f"/tasks/{tid}", headers=H).json()
    check(got.get("list_id") == P and got.get("notes") == "Two beds\nnear the fence" and got.get("due") == "2026-12-01"
          and got.get("priority") == "high" and got.get("key") == "GRD-1",
          f"{who}: add --project/--notes -/--due/--priority wrote the task: {[got.get(k) for k in ('list_id', 'notes', 'due', 'priority', 'key')]}")
    t2 = js(tok, "add", "Water the roses", "--project", str(P))

    # list
    rc, out, err = cli(tok, "list", "--project", str(P))
    check(rc == 0 and "GRD-1" in out and "Dig the beds" in out and "[high]" in out and "2026-12-01" in out
          and "Water the roses" in out and "Buy seeds" not in out, f"{who}: list --project, readable ({rc} {out!r} {err!r})")
    j = js(tok, "list", "--search", "roses")
    check([x["id"] for x in j["data"]] == [t2["id"]] and j["more"] is False, f"{who}: list --search --json: {j}")
    j = js(tok, "list", "--project", str(P), "--limit", "1")
    check(len(j["data"]) == 1 and j["more"] is True, f"{who}: list --limit 1 says there is more: {j}")

    # comment by key, text from stdin; show by key and by id
    rc, out, err = cli(tok, "comment", "GRD-1", "-", stdin="Start on the left side\n")
    check(rc == 0 and f"#{tid}" in out, f"{who}: comment by ticket key ({rc} {out!r} {err!r})")
    cm = requests.get(V + f"/tasks/{tid}/comments", headers=H).json().get("data") or []
    check([c.get("body") for c in cm] == ["Start on the left side"], f"{who}: the comment is on the task: {[c.get('body') for c in cm]}")
    rc, out, err = cli(tok, "show", "GRD-1")
    check(rc == 0 and "GRD-1  Dig the beds" in out and "near the fence" in out and "Comments (1):" in out
          and "Start on the left side" in out, f"{who}: show by key: notes and comments ({rc} {out!r} {err!r})")
    j = js(tok, "show", str(tid))
    check(j.get("id") == tid and len(j.get("comments") or []) == 1, f"{who}: show --json by id has the comments")

    # done
    rc, out, err = cli(tok, "done", f"#{tid}")
    st = requests.get(V + f"/tasks/{tid}", headers=H).json().get("status")
    check(rc == 0 and out.startswith("done GRD-1") and st == "done", f"{who}: done completes the task ({rc} {out!r} {st})")
    rc, out, err = cli(tok, "done", "GRD-1")
    check(rc == 0, f"{who}: done again changes nothing and is no error ({rc} {err!r})")
    j = js(tok, "list", "--project", str(P), "--status", "done")
    check([x["id"] for x in j["data"]] == [tid], f"{who}: list --status done: {[x['id'] for x in j['data']]}")

    # errors
    rc, out, err = cli("abk_" + "x" * 40, "list")
    check(rc == 1 and not out and "HTTP 401" in err and "KALMIDO_TOKEN" in err, f"{who}: a wrong token = exit 1 + message ({rc} {out!r} {err!r})")
    rc, out, err = cli(ro, "add", "Should not exist", "--project", str(P))
    n = len(requests.get(V + "/tasks", headers=H, params={"q": "Should not exist", "status": "all"}).json().get("data") or [])
    check(rc == 1 and "HTTP 403" in err and "scope" in err and n == 0, f"{who}: a read-only token cannot add ({rc} {err!r} {n})")
    rc, out, err = cli(ro, "done", str(t2["id"]))
    st = requests.get(V + f"/tasks/{t2['id']}", headers=H).json().get("status")
    check(rc == 1 and "HTTP 403" in err and st == "open", f"{who}: a read-only token cannot complete ({rc} {err!r} {st})")
    rc, out, err = cli(ro, "comment", str(t2["id"]), "hi")
    check(rc == 1 and "HTTP 403" in err, f"{who}: a read-only token cannot comment ({rc} {err!r})")
    rc, out, err = cli(ro, "show", str(t2["id"]))
    check(rc == 0 and "Water the roses" in out, f"{who}: a read-only token can show ({rc} {err!r})")
    rc, out, err = cli(tok, "show", "999999")
    check(rc == 1 and "HTTP 404" in err and not out, f"{who}: an unknown task = exit 1 ({rc} {err!r})")
    rc, out, err = cli(tok, "show", "not a task")
    check(rc == 2 and "ticket key" in err, f"{who}: a bad task reference = exit 2 ({rc} {err!r})")
    rc, out, err = cli(None, "list")
    check(rc == 2 and "KALMIDO_TOKEN" in err, f"{who}: no token = exit 2 ({rc} {err!r})")
    rc, out, err = cli(tok, "list", url=None)
    check(rc == 2 and "KALMIDO_URL" in err, f"{who}: no address = exit 2 ({rc} {err!r})")


run("freelancer", F)
run("admin", A)
sys.exit(done("p2630_d_cli"))
