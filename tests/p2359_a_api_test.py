#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.359.0 A (#3023): errors of /api/* answer with JSON, never with Flask's HTML page (the web client took every HTML answer
for "session expired" and reloaded; an offline change on a temporary id then reloaded the page again and again)
 - PATCH /api/tasks/-5 (a temporary id, no route) -> 404 JSON; an unknown /api address -> 404 JSON; a wrong method -> 405 JSON
 - an uncaught server error on /api (the test route /api/test/boom, test containers only) -> 500 JSON; /api/v1 keeps its own
   error format; the same as a person without an organisation (freelancer-matrix: tasks)
 - pages outside /api stay as they were: an unknown page is the HTML "Page not found", /s/<unknown> the public page
usage: p2359_a_api_test.py <datadir>      (KMT_NOSTART=1 / P2359A_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

fresh(prefix="P2359A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, F = freelancer(B, A)


def is_json(r, code):
    try:
        j = r.json()
    except ValueError:
        j = None
    return r.status_code == code and r.headers.get("Content-Type", "").startswith("application/json") and isinstance(j, dict) and "error" in j


for who, s in (("admin", A), ("freelancer", F)):
    r = s.patch(B + "/api/tasks/-5", json={"title": "x"})
    check(is_json(r, 404), f"{who}: PATCH /api/tasks/-5 answers JSON 404 ({r.status_code} {r.headers.get('Content-Type')})")
    r = s.patch(B + "/api/notes/-5", json={"body": "x"})
    check(is_json(r, 404), f"{who}: PATCH /api/notes/-5 answers JSON ({r.status_code} {r.headers.get('Content-Type')})")
    r = s.get(B + "/api/no-such-thing")
    check(is_json(r, 404), f"{who}: an unknown /api address answers JSON 404 ({r.status_code})")
    r = s.put(B + "/api/state")
    check(is_json(r, 405), f"{who}: a wrong method answers JSON 405 ({r.status_code} {r.headers.get('Content-Type')})")
    for m in ("GET", "PATCH"):
        r = s.request(m, B + "/api/test/boom", json={})
        check(is_json(r, 500), f"{who}: an uncaught error answers JSON 500 ({m} {r.status_code} {r.headers.get('Content-Type')})")
        check("RuntimeError" not in r.text and "Traceback" not in r.text, f"{who}: the 500 answer shows no internals")

r = A.get(B + "/api/v1/no-such-thing")
check(r.status_code in (401, 404) and isinstance(r.json().get("error"), dict), f"/api/v1 keeps its own error format ({r.status_code} {r.text[:80]})")
r = A.get(B + "/no-such-page", headers={"Accept": "text/html"})
check(r.status_code == 404 and "text/html" in r.headers.get("Content-Type", ""), f"an unknown page outside /api stays HTML ({r.status_code})")
r = requests.get(B + "/s/no-such-link", headers={"Accept": "text/html"})
check(r.status_code in (404, 410) and "text/html" in r.headers.get("Content-Type", ""), f"an unknown public link keeps its page ({r.status_code})")
sys.exit(done("p2359_a_api"))
