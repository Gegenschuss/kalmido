#!/usr/bin/env python3
"""2.784.0 (#5387): loads the business year of the invented "Muster GmbH" (tests/fixtures/muster_gmbh_<year>.json) as a demo
organisation into a Kalmido instance -- the same events, through the same code (tools/muster_gmbh_play.py), as the test
suite tests/muster_gmbh_jahr_test.py checks. NEVER against the live instance.

Everything comes from the environment, nothing from the repository:
  KALMIDO_DEMO_URL        base URL of the instance (e.g. a staging or local instance)
  KALMIDO_DEMO_ALLOW      comma separated host names the loader may write to (the staging host); localhost / 127.0.0.1 are
                          always allowed. A host that is not on the list, or any host of the live domain, is refused hard.
  KALMIDO_DEMO_USER / KALMIDO_DEMO_PASSWORD   an instance admin (creates the organisation); or
  KALMIDO_DEMO_COOKIE     the "name=value" session cookie of a logged-in instance admin
  KALMIDO_DEMO_HEADERS    optional JSON object of extra request headers (e.g. what a proxy in front of the instance needs)

  python3 tools/muster_gmbh_demo.py [--year 2025] [--dry-run]

The organisation is called "Muster GmbH" (the fixture's company name); the loader stops when one with that name exists
already (load once; delete the organisation to load it again). The admin's current workspace is switched to it. Exit codes:
0 loaded, 2 refused (address / settings), 1 a step failed (the step and the answer are printed)."""
import argparse
import json
import os
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from muster_gmbh_play import PlayError, play  # noqa: E402

LIVE_DOMAINS = ("kalmido.com",)  # the live instance and everything under its domain: never
LOCAL = ("localhost", "127.0.0.1", "::1")


def allowed(url, allow_env):
    """(True, host) when url may be written to: http(s), a host on the allow list (or local), never the live domain."""
    p = urlsplit(url or "")
    host = (p.hostname or "").lower().rstrip(".")
    if p.scheme not in ("http", "https") or not host:
        return False, f"no valid URL: {url!r}"
    if any(host == d or host.endswith("." + d) for d in LIVE_DOMAINS):
        return False, f"refused: {host} is the live instance"
    allow = {h.strip().lower().rstrip(".") for h in (allow_env or "").split(",") if h.strip()}
    if host not in LOCAL and host not in allow:
        return False, f"refused: {host} is not in KALMIDO_DEMO_ALLOW"
    return True, host


def main(argv=None):
    ap = argparse.ArgumentParser(description="Load the Muster GmbH demo year into a staging / local Kalmido (never live).")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--dry-run", action="store_true", help="only check the address and the fixture")
    a = ap.parse_args(argv)
    url = (os.environ.get("KALMIDO_DEMO_URL") or "").rstrip("/")
    ok, why = allowed(url, os.environ.get("KALMIDO_DEMO_ALLOW"))
    if not ok:
        print(why, file=sys.stderr)
        return 2
    path = os.path.join(HERE, "..", "tests", "fixtures", f"muster_gmbh_{a.year}.json")
    if not os.path.exists(path):
        print(f"no fixture for {a.year}: {path}", file=sys.stderr)
        return 2
    with open(path, encoding="utf-8") as f:
        fx = json.load(f)
    if a.dry_run:
        print(f"ok: {why}, fixture {a.year} with {len(fx['rechnungen'])} invoices, {len(fx['belege'])} receipts, {len(fx['bank']['zeilen'])} bank lines")
        return 0
    import requests
    s = requests.Session()
    s.headers.update({"X-Requested-With": "kalmido"})
    try:
        s.headers.update(json.loads(os.environ.get("KALMIDO_DEMO_HEADERS") or "{}"))
    except ValueError:
        print("KALMIDO_DEMO_HEADERS is no JSON object", file=sys.stderr)
        return 2
    cookie = os.environ.get("KALMIDO_DEMO_COOKIE") or ""
    if cookie:
        name, _, val = cookie.partition("=")
        s.cookies.set(name.strip(), val.strip(), domain=urlsplit(url).hostname)
    else:
        user, pw = os.environ.get("KALMIDO_DEMO_USER"), os.environ.get("KALMIDO_DEMO_PASSWORD")
        if not (user and pw):
            print("set KALMIDO_DEMO_USER and KALMIDO_DEMO_PASSWORD, or KALMIDO_DEMO_COOKIE", file=sys.stderr)
            return 2
        r = s.post(url + "/api/auth/login", json={"username": user, "password": pw})
        if not r.ok:
            print(f"login failed: {r.status_code}", file=sys.stderr)
            return 2
    st = s.get(url + "/api/state")
    if not st.ok:
        print(f"not logged in: {st.status_code}", file=sys.stderr)
        return 2
    me = st.json()["me"]["id"]
    name = fx["firma"]["name"]
    orgs = s.get(url + "/api/admin/orgs")
    if not orgs.ok:
        print(f"the account is no instance admin: {orgs.status_code}", file=sys.stderr)
        return 2
    rows = orgs.json() if isinstance(orgs.json(), list) else orgs.json().get("items") or orgs.json().get("orgs") or []
    if any((o.get("name") or "") == name for o in rows):
        print(f"an organisation {name!r} exists already: delete it to load the demo again", file=sys.stderr)
        return 2
    r = s.post(url + "/api/admin/orgs", json={"name": name, "admin_id": me})
    if not r.ok:
        print(f"organisation not created: {r.status_code} {r.text[:200]}", file=sys.stderr)
        return 1
    oid = r.json()["id"]
    s.patch(url + "/api/settings", json={"workspace": f"org:{oid}"})
    try:
        play(s, url, fx, f"org:{oid}", me, log=lambda x: print("loaded:", x, flush=True))
    except PlayError as e:
        print(f"failed: {e}", file=sys.stderr)
        return 1
    print(f"done: {name} (organisation {oid}) with the year {a.year} on {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
