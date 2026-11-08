#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.658.0 A (#5099): a scheduled document flow "0 days after Added" in the first hour after local midnight.
doc_meta.created_at is a UTC timestamp; the tick (docs/flows.py fl_tick) compared its first 10 characters (the UTC day) with the
local day, so between 0:00 and 1:00 Berlin time (23:00-24:00 UTC) a new document lay before the flow's first day and was not
tagged - p2581_c_flows went red in the CI runs after midnight. The server's clock is set to 00:30 Berlin time (KALMIDO_TEST_NOW).
 - the tick tags a document that came in at 00:30 local time, exactly once (one run row, stamp = the local day)
 - a person without an organisation (frida) - the flows are hers
freelancer-matrix: files
usage: p2658_a_flows_night_test.py <datadir>      (a fresh container; P2658A_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, dbx, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

NIGHT = "2026-11-08T23:30:00+00:00"  # = 2026-11-09 00:30 in Berlin (winter time)
os.environ["KALMIDO_TEST_NOW"], os.environ["KALMIDO_TEST_NOW_AT"] = NIGHT, str(int(time.time()))
kt.fresh(env={"KALMIDO_DOCFLOW_TICK_S": "1", "TZ": "Europe/Berlin"}, prefix="P2658A")
A = kt.setup()


def night_pdf(lines):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({x}) '" for x in lines) + " ET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def night_doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def night_tags(s, nid):
    return sorted(t["name"] for t in (night_doc(s, nid) or {}).get("tags") or [])


FR, Fr = freelancer(B, A, "frida")
r = Fr.post(B + "/api/docs/rules", json={"ws": "private", "name": "Frist", "trigger": "scheduled", "days": 0, "from": "added",
                                          "tags": ["Frist"]})
check(r.status_code == 201, f"a scheduled flow is saved {r.status_code} {r.text[:200]}")
r = Fr.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("nacht.pdf", night_pdf(["Mahnung", "Zahlungsfrist"]), "application/pdf"))])
check(r.status_code == 201, f"upload {r.status_code} {r.text[:200]}")
nid = r.json()["ids"][0]
check(until(lambda: (night_doc(Fr, nid) or {}).get("state") in ("done", "failed"), 90), "the document is read")
created = str(dbx("SELECT created_at FROM doc_meta WHERE node_id=?", (nid,))[0][0])
check(created.startswith("2026-11-08T23:"), f"the test clock: the document came in at 23:xx UTC = 00:xx Berlin ({created})")
check(until(lambda: "Frist" in night_tags(Fr, nid), 30), "scheduled after midnight: the tick tagged the new document")
fid = [x["id"] for x in Fr.get(B + "/api/docs/settings?ws=private").json()["rules"] if x.get("name") == "Frist"][0]
rows = dbx("SELECT stamp FROM doc_flow_runs WHERE rule_id=? AND node_id=?", (fid, nid))
check(len(rows) == 1 and str(rows[0][0]) == "2026-11-09", f"one run row, stamped with the local day {[tuple(x) for x in rows]}")
check(Fr.patch(B + f"/api/docs/{nid}", json={"tags": []}).ok, "the tag taken off by hand")
r2 = Fr.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("nacht2.pdf", night_pdf(["Erinnerung"]), "application/pdf"))])
n2 = r2.json()["ids"][0]
check(until(lambda: "Frist" in night_tags(Fr, n2), 60), "the next tick tagged a second document")
check("Frist" not in night_tags(Fr, nid), "the first document is not tagged a second time")
sys.exit(kt.done("p2658_a_flows_night"))
