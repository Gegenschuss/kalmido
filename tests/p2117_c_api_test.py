#!/usr/bin/env python3
"""2.117.0 API tests, part C (#2262): the PDF metadata reads "Kalmido v<version>" (Info Producer + Creator and the XMP
pdf:Producer + xmp:CreatorTool, equal), for a quotation and an invoice, in an organisation and for a person without one.
Own container (start.sh), invented companies only. P2117C_OUT=<dir> keeps the PDFs (for a validator run).
usage: p2117_c_api_test.py <datadir>      (a fresh container; P2117C_NOSTART=1 = the server already runs)"""
import io
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
D = "/api/office/docs"
OUT = os.environ.get("P2117C_OUT") or ""
FAILS, OKS = [], [0]
try:
    with open(os.path.join(N, "..", "VERSION")) as fh:
        VER = fh.read().strip()
except OSError:
    VER = ""


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def meta_ok(data, what):
    rd = PdfReader(io.BytesIO(data))
    info = rd.metadata or {}
    prod, cre = str(info.get("/Producer") or ""), str(info.get("/Creator") or "")
    check(re.fullmatch(r"Kalmido v\d+\.\d+\.\d+\S*", prod) is not None, f"{what}: Info Producer '{prod}'")
    check(cre == prod, f"{what}: Info Creator '{cre}' equals the producer")
    if VER:
        check(prod == "Kalmido v" + VER, f"{what}: producer '{prod}' carries VERSION {VER}")
    xmp = (rd.xmp_metadata.stream.get_data().decode("utf-8", "replace") if rd.xmp_metadata else "")
    if xmp:  # the PDF/A XMP packet (e-invoices) says the same
        m1, m2 = re.search(r"<pdf:Producer>([^<]*)<", xmp), re.search(r"<xmp:CreatorTool>([^<]*)<", xmp)
        check(m1 and m2 and m1.group(1) == prod and m2.group(1) == prod, f"{what}: XMP producer / creator tool equal the Info dict")


def keep(name, data):
    if OUT:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, name + ".pdf"), "wb") as fh:
            fh.write(data)


if not os.environ.get("P2117C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
FID, F = freelancer(B, A)  # freelancer-matrix: office

for who, S in (("org", A), ("freelancer", F)):
    for kind in ("offer", "invoice"):
        r = S.post(B + D, json={"kind": kind, "lang": "en", "project_title": f"Metadata {who} {kind}",
                                "items": [{"title": "Concept", "qty": 1, "rate": 800}]})
        check(r.status_code == 201, f"{who} {kind}: create {r.status_code} {r.text[:160]}")
        doc = r.json().get("id")
        r = S.get(B + f"{D}/{doc}/pdf")
        check(r.status_code == 200 and r.content.startswith(b"%PDF"), f"{who} {kind}: the PDF {r.status_code}")
        if r.status_code == 200:
            meta_ok(r.content, f"{who} {kind}")
            keep(f"{who}-{kind}", r.content)

print(f"p2117_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
