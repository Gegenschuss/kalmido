#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.570.0 (#4770): undo with a version check, the rest of #4704 - bookmarks, documents, the office archive's correction and
the standard arrangements. Invented names only (example.com). Two sessions of the same account each time: A reads, B
changes, A writes back with the old version -> 409 with the current state, B's change stays; without expect_updated_at the
old behaviour. Guarded:
 - a bookmark's preview fetch (background) no longer moves updated_at: an undo against the version of the own save still
   goes through after it (before: refused for nothing), the fetch stamps fetched_at
 - a document's recognition run (background) no longer moves updated_at (its own run_at); a name change of another session
   is a new version too
 - the office archive's correction: a version (never corrected = created_at), 409 against it
 - the instance standard of a view and a project page's standard carry a version (versions / std_at / mine_at)
 - bookmarks, documents and the archive as a person without an organisation (freelancer-matrix: reading, files, office)
usage: p2570_b_undo_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, login  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def run_sql(q, args=()):
    """A write in the suite's database (kt.dbx only reads)."""
    import dbx as dbxm
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"), timeout=10)
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


def in_app(code):
    """Lines of Python inside the container; prints the JSON of `out`."""
    head = "import json\nimport app\n"
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", kt.CT, "python", "-c", head + code + "\nprint('OUT' + json.dumps(out))"],
                       capture_output=True, text=True, timeout=200)
    for line in r.stdout.splitlines():
        if line.startswith("OUT"):
            return json.loads(line[3:])
    raise AssertionError(r.stdout[-800:] + r.stderr[-1500:])


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2570B")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
A2 = kt.sess("alice")
FID, Fr = freelancer(B, A)
Fr2 = login(B, "frida")


# ---------------------------------------------------------------- bookmarks
def bookmarks(s1, s2, who):
    r = s1.post(B + "/api/bookmarks", json={"url": f"http://10.1.2.3/{who}", "title": "Erster Titel"})
    check(r.status_code == 201, f"{who}: a bookmark " + r.text[:160])
    bid = r.json()["bookmark"]["id"]
    d = until(lambda: (lambda j: j if j.get("preview") not in ("pending", "image") else None)(s1.get(B + f"/api/bookmarks/{bid}").json()), 40)
    check(d and d.get("preview") == "failed", f"{who}: the refused address: preview failed {d and d.get('preview')}")
    r = s1.patch(B + f"/api/bookmarks/{bid}", json={"title": "Zweiter Titel"})
    check(r.ok, f"{who}: A renames " + r.text[:160])
    u1 = r.json()["updated_at"]
    # the background fetch again (as after a new link / the watchdog): it must not move the version
    run_sql("UPDATE bookmarks SET preview='pending' WHERE id=?", (bid,))
    in_app(f"from kalmido.life.bookmarks import bm_fetch_one\nbm_fetch_one({bid})\nout = 1")
    row = kt.dbx("SELECT preview, updated_at, fetched_at FROM bookmarks WHERE id=?", (bid,))[0]
    check(row[0] == "failed" and row[1] == u1 and row[2], f"{who}: the fetch ran, updated_at stays, fetched_at set {row} / {u1}")
    r = s1.patch(B + f"/api/bookmarks/{bid}", json={"title": "Erster Titel", "expect_updated_at": u1})
    check(r.ok and r.json()["title"] == "Erster Titel", f"{who}: A's undo after the fetch goes through (before: 409 for nothing) " + r.text[:160])
    u2 = r.json()["updated_at"]
    r = s2.patch(B + f"/api/bookmarks/{bid}", json={"note": "von B"})
    check(r.ok, f"{who}: B adds a note")
    r = s1.patch(B + f"/api/bookmarks/{bid}", json={"title": "Zweiter Titel", "expect_updated_at": u2})
    check(r.status_code == 409 and (r.json().get("current") or {}).get("note") == "von B",
          f"{who}: A's redo with the old version: 409 with the current bookmark " + r.text[:200])
    check(one("SELECT title FROM bookmarks WHERE id=?", (bid,)) == "Erster Titel" and one("SELECT note FROM bookmarks WHERE id=?", (bid,)) == "von B",
          f"{who}: nothing overwritten")
    r = s1.patch(B + f"/api/bookmarks/{bid}", json={"title": "Ohne Version"})
    check(r.ok and r.json()["title"] == "Ohne Version", f"{who}: without expect_updated_at the old behaviour " + r.text[:160])


bookmarks(A, A2, "member")
bookmarks(Fr, Fr2, "freelancer")


# ---------------------------------------------------------------- documents
def docs(s1, s2, who):
    r = s1.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (f"rechnung-{who}.txt", b"Rechnung 12.03.2026 Betrag 10,00 EUR", "text/plain"))])
    check(r.ok, f"{who}: a document " + r.text[:160])
    nid = r.json()["ids"][0]
    fin = lambda: until(lambda: (lambda x: x.json() if x.ok and x.json()["state"] in ("done", "failed") else None)(s1.get(B + f"/api/docs/{nid}")), 90)  # noqa: E731
    d = fin()
    check(d, f"{who}: the first recognition run is over")
    r = s1.patch(B + f"/api/docs/{nid}", json={"due": "2027-01-15"})
    check(r.ok, f"{who}: A sets the due date " + r.text[:160])
    u1 = r.json()["updated_at"]
    run_sql("UPDATE doc_meta SET state='wait' WHERE node_id=?", (nid,))  # the queue takes it again (background)
    d = fin()
    check(d and d["updated_at"] == u1 and one("SELECT run_at FROM doc_meta WHERE node_id=?", (nid,)),
          f"{who}: the recognition ran again, updated_at stays, run_at set {d and d['updated_at']} / {u1}")
    r = s1.patch(B + f"/api/docs/{nid}", json={"due": None, "expect_updated_at": u1})
    check(r.ok and not r.json()["due"], f"{who}: A's undo after the run goes through (before: 409 for nothing) " + r.text[:160])
    u2 = r.json()["updated_at"]
    r = s2.patch(B + f"/api/docs/{nid}", json={"name": f"umbenannt-{who}.txt"})
    check(r.ok and r.json()["updated_at"] != u2, f"{who}: B renames - a new version " + r.text[:160])
    r = s1.patch(B + f"/api/docs/{nid}", json={"due": "2027-01-15", "expect_updated_at": u2})
    check(r.status_code == 409 and (r.json().get("current") or {}).get("name") == f"umbenannt-{who}.txt",
          f"{who}: A's redo with the old version: 409 with the current document " + r.text[:200])
    check(not one("SELECT due_date FROM doc_meta WHERE node_id=?", (nid,)), f"{who}: the due date was not written")
    r = s1.patch(B + f"/api/docs/{nid}", json={"due": "2027-02-01"})
    check(r.ok and r.json()["due"] == "2027-02-01", f"{who}: without expect_updated_at the old behaviour " + r.text[:160])


docs(A, A2, "member")
docs(Fr, Fr2, "freelancer")

# ---------------------------------------------------------------- the office archive's correction (the personal office)
O = "/api/office"
rid = Fr.post(B + O + "/legacy/archive/run").json()["run_id"]
r = Fr.post(B + O + "/legacy/archive", data={"run_id": rid, "kind": "invoice", "number": "ALT-1", "client_name": "Altkunde",
                                             "date": "2024-05-02", "amount": "100.00"},
            files={"file": ("alt-1.pdf", tiny_pdf("Rechnung ALT-1"), "application/pdf")})
check(r.status_code == 201, "an archived invoice " + r.text[:160])
aid = r.json()["id"]
g = Fr.get(B + O + f"/legacy/archive/{aid}").json()
check(g.get("updated_at") and g["updated_at"] == one("SELECT created_at FROM office_archive WHERE id=?", (aid,))
      and one("SELECT updated_at FROM office_archive WHERE id=?", (aid,)) == "", "never corrected: its version is created_at " + str(g.get("updated_at")))
r = Fr.patch(B + O + f"/legacy/archive/{aid}", json={"paid": 1, "expect_updated_at": g["updated_at"]})
check(r.ok and r.json().get("paid") == 1 and r.json().get("updated_at") not in ("", g["updated_at"]), "A marks it paid: a new version " + r.text[:160])
u1 = r.json()["updated_at"]
r = Fr2.patch(B + O + f"/legacy/archive/{aid}", json={"amount": "200.00"})
check(r.ok, "B corrects the amount " + r.text[:160])
r = Fr.patch(B + O + f"/legacy/archive/{aid}", json={"paid": 0, "expect_updated_at": u1})
check(r.status_code == 409 and (r.json().get("current") or {}).get("amount") == 200.0, "A's undo with the old version: 409 with the entry " + r.text[:200])
check(one("SELECT paid FROM office_archive WHERE id=?", (aid,)) == 1, "paid stays")
r = Fr.patch(B + O + f"/legacy/archive/{aid}", json={"paid": 0})
check(r.ok and r.json().get("paid") == 0, "without expect_updated_at the old behaviour " + r.text[:160])

# ---------------------------------------------------------------- the standard arrangements
LA, LB = json.dumps({"hidden": ["tasks"]}), json.dumps({"hidden": ["habits"]})
r = A.put(B + "/api/layouts/std/view_today", json={"layout": LA})
check(r.ok and r.json().get("versions", {}).get("view_today"), "the instance standard answers its version " + r.text[:200])
v1 = r.json()["versions"]["view_today"]
check(A2.put(B + "/api/layouts/std/view_today", json={"layout": LB}).ok, "B sets another standard")
r = A.put(B + "/api/layouts/std/view_today", json={"layout": "", "expect_updated_at": v1})
check(r.status_code == 409 and json.loads((r.json().get("current") or {}).get("layouts", {}).get("view_today") or "{}") == {"hidden": ["habits"]},
      "an undo of the standard with the old version: 409 with the standards " + r.text[:200])
check(A.get(B + "/api/layouts/std").json()["versions"]["view_today"] != v1, "GET carries the versions")

L = A.post(B + "/api/lists", json={"name": "Projekt Layout"}).json()["id"]
check(A.patch(B + f"/api/lists/{L}", json={"kind": "project"}).ok, "a project list")
r = A.put(B + f"/api/lists/{L}/layout", json={"layout": LA, "scope": "standard"})
check(r.ok and r.json().get("std_at"), "a project page's standard answers std_at " + r.text[:200])
s1 = r.json()["std_at"]
check(A2.put(B + f"/api/lists/{L}/layout", json={"layout": LB, "scope": "standard"}).ok, "B changes the project standard")
r = A.put(B + f"/api/lists/{L}/layout", json={"layout": "", "scope": "standard", "expect_updated_at": s1})
check(r.status_code == 409 and json.loads((r.json().get("current") or {}).get("std") or "{}") == {"hidden": ["habits"]},
      "an undo of the project standard with the old version: 409 " + r.text[:200])
r = A.put(B + f"/api/lists/{L}/layout", json={"layout": LA, "scope": "mine"})
check(r.ok and r.json().get("mine_at"), "the own arrangement answers mine_at")
r = A.put(B + f"/api/lists/{L}/layout", json={"layout": "", "scope": "mine", "expect_updated_at": r.json()["mine_at"]})
check(r.ok and r.json().get("mine") == "", "the own arrangement's undo with its version goes through " + r.text[:160])

sys.exit(kt.done("p2570_b_undo"))
