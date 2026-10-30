#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.428.0 API tests, part B (#3579): the documents list sorted by the server, ?sort=date|added|sender|amount|due|title and
?dir=asc|desc. Own container (start.sh, server key on: amounts and sender names are sealed and still sort right).
Invented names and generated file contents only.
 - default = document date, newest first; every sort both ways; empty values (no amount / due date / sender) last in both
   directions; amounts as numbers (9.50 before 120), sender names case-insensitive; the pages stay right (limit / offset);
   an unknown sort or direction falls back to the default (never part of the SQL)
 - freelancer-matrix: files (a person without an organisation sorts their own documents the same way)
usage: p2428_b_api_test.py <datadir>      (a fresh container; P2428B_NOSTART=1: the container runs already)"""
import base64
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess, until  # noqa: E402


def doc_new(s, name, text, **fields):
    """A text document, recognised, then its fields set by hand."""
    r = s.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, text.encode(), "text/plain"))])
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    if fields:
        r = s.patch(B + f"/api/docs/{nid}", json=fields)
        assert r.ok, r.text
    return nid


def order(s, **params):
    r = s.get(B + "/api/docs", params={"ws": "private", "facets": "0", **params})
    return [d["id"] for d in r.json()["docs"]] if r.ok else (r.status_code, r.text[:200])


if not os.environ.get("P2428B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
A.patch(B + "/api/settings", json={"lang": "en", "features": "files,docs", "tour": "done"})

D1 = doc_new(A, "c-brief.txt", "Ein Brief ohne Belang", date="2025-03-01", due="2025-04-10", amount="120.00", sender="Baeckerei Nord")
D2 = doc_new(A, "a-rechnung.txt", "Eine kleine Rechnung", date="2025-01-15", due="2025-02-01", amount="9.50", sender="zeta GmbH")
D3 = doc_new(A, "b-vertrag.txt", "Ein Vertrag", date="2025-06-20", amount="1000", sender="Alpha AG")
D4 = doc_new(A, "d-notiz.txt", "Eine Notiz", date="2024-12-01")
seal = A.get(B + f"/api/docs/{D3}").json()
check(seal.get("amount") in ("1000", "1000.00") and (seal.get("sender") or {}).get("name") == "Alpha AG", f"the fields are set {seal.get('amount')} {seal.get('sender')}")

check(order(A) == [D3, D1, D2, D4], f"default: document date, newest first {order(A)}")
check(order(A, sort="date", dir="asc") == [D4, D2, D1, D3], "document date, oldest first")
check(order(A, sort="added") == [D4, D3, D2, D1] and order(A, sort="added", dir="asc") == [D1, D2, D3, D4], "date of arrival both ways")
check(order(A, sort="sender") == [D3, D1, D2, D4], f"sender A-Z (case-insensitive), without sender last {order(A, sort='sender')}")
check(order(A, sort="sender", dir="desc") == [D2, D1, D3, D4], "sender Z-A, without sender still last")
check(order(A, sort="amount") == [D3, D1, D2, D4], f"amount highest first, as numbers (sealed), without amount last {order(A, sort='amount')}")
check(order(A, sort="amount", dir="asc") == [D2, D1, D3, D4], "amount lowest first, without amount still last")
check(order(A, sort="due", dir="asc") == [D2, D1, D3, D4], f"due date soonest first, without due date last {order(A, sort='due', dir='asc')}")
check(order(A, sort="due", dir="desc") == [D1, D2, D4, D3], "due date latest first, without due date last")
check(order(A, sort="title") == [D2, D3, D1, D4] and order(A, sort="title", dir="desc") == [D4, D1, D3, D2], "title both ways")
# the pages follow the sort (the server sorts, not the page)
p1 = A.get(B + "/api/docs", params={"ws": "private", "facets": "0", "sort": "amount", "limit": 2}).json()
p2 = A.get(B + "/api/docs", params={"ws": "private", "facets": "0", "sort": "amount", "limit": 2, "offset": 2}).json()
check([d["id"] for d in p1["docs"]] == [D3, D1] and [d["id"] for d in p2["docs"]] == [D2, D4] and p1["total"] == p2["total"] == 4, "pages of a sealed sort")
p2 = A.get(B + "/api/docs", params={"ws": "private", "facets": "0", "sort": "due", "dir": "asc", "limit": 2, "offset": 2}).json()
check([d["id"] for d in p2["docs"]] == [D3, D4], "pages of a plain sort")
check(order(A, sort="amount", offset=10) == [], "a page behind the end is empty")
# only sorts of the allow list
check(order(A, sort="n.name; DROP TABLE doc_meta") == [D3, D1, D2, D4] and order(A, sort="title", dir="sideways") == [D2, D3, D1, D4],
      "an unknown sort / direction falls back to the default")
check(order(A, sort="amount", q="Rechnung") == [D2], "the sort with a search")

# ---- a person without an organisation (freelancer-matrix: files)
FR, Fr = freelancer(B, A, "frida", features="files,docs")
E1 = doc_new(Fr, "miete.txt", "Miete Beispiel", date="2025-02-01", amount="800")
E2 = doc_new(Fr, "porto.txt", "Porto Beispiel", date="2025-03-01", amount="2.40")
check(order(Fr) == [E2, E1] and order(Fr, sort="amount") == [E1, E2] and order(Fr, sort="amount", dir="asc") == [E2, E1], "freelancer: sorts the own documents")
check(D1 not in order(Fr, sort="amount") and E1 not in order(A, sort="amount"), "the sort never shows documents of others")

print(f"p2428_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
