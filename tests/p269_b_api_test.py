#!/usr/bin/env python3
"""2.69.0 API tests, part B (#1847): a Paperless-ngx import teaches Kalmido -- against the fake Paperless-ngx inside the test
container (fake_paperless.py, 127.0.0.1:8098, allowed as an internal host). Invented names only, generated file contents.
 - the matching of tags / correspondents / document types becomes document rules: any, all, literal -> exact, regex, fuzzy,
   with the mapped target (renamed, a tag as a folder; a left-out label = no rule), case-sensitive kept; auto reported as
   learnt by Kalmido, a pattern too long / too complex reported, none = nothing
 - the preview counts them; the switch off = no rules (the learning still runs)
 - a second import makes no doubles, a deleted taken-over rule does not come back
 - the classifier learns the imported values once at the end of the run (models + the documents marked as trained)
 - the rules only go into the workspace of the import (an organisation's import never touches a private space)
 - a case-sensitive rule only matches the pattern as written (an upload through the normal route)
usage: p269_b_api_test.py <datadir>"""
import json
import os
import shutil
import subprocess
import sys
import time

import requests
from freelancer_fixture import org_join  # 2.148.1 (#2480): an invited member accepts

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

from kt import FAILS, OKS, check, sess, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
PL = "http://127.0.0.1:8098"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


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
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out.decode("latin-1")


def doc(i, title, **kw):
    d = {"id": i, "title": title, "content": "", "created": "2025-01-01", "correspondent": None, "document_type": None, "tags": [],
         "archive_serial_number": None, "original_file_name": f"doc{i}.pdf", "custom_fields": [], "notes": [], "file": tiny_pdf(title)}
    d.update(kw)
    return d


def lab(i, name, algo, match="", insens=True, n=1):
    return {"id": i, "name": name, "document_count": n, "matching_algorithm": algo, "match": match, "is_insensitive": insens}


PLDATA = {
    "tags": [lab(1, "Tax", 1, "tax steuer"), lab(2, "Archive 2025", 3, "archive copy"), lab(3, "Ignore me", 2, "never mind"),
             lab(4, "Auto tag", 6), lab(5, "Bad regex", 4, "(a+)+b"), lab(6, "Case", 4, r"ACME\d+", insens=False),
             lab(10, "Long", 1, "x" * 250), lab(11, "No rule", 0, "")],
    "correspondents": [lab(7, "Example Utility", 5, "Example Utlity"), lab(8, "Nobody", 0)],
    "document_types": [lab(9, "Invoice", 4, "invoice|bill")],
    "custom_fields": [],
    "documents": [
        doc(11, "Power bill May", content="Power bill May total 42.00 EUR steuer", correspondent=7, document_type=9, tags=[1, 2]),
        doc(12, "Tax notice", content="Notice of assessment tax", document_type=9, tags=[1, 6]),
        doc(13, "Copy", file=tiny_pdf("Power bill May"))]}


def pl_write():
    with open(os.path.join(DATA, "pl.json"), "w") as f:
        json.dump(PLDATA, f)


def pl_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "pl.log"), encoding="utf-8")]
    except OSError:
        return []


def run_idle(s, ws="private", secs=60):
    def done():
        j = s.get(B + f"/api/paperless?ws={ws}").json()
        r = (j.get("conn") or {}).get("run") or {}
        return j if r.get("state") == "idle" else None
    return until(done, secs)


def docs(s, ws="private"):
    return s.get(B + f"/api/docs?ws={ws}").json().get("docs") or []


BASE_EXTRA = os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098"
# 2.48.0 review (S2): the token is always sealed with a key derived from the server key -> the container has one
env = dict(os.environ, EXTRA=BASE_EXTRA + " -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_paperless.py"), DATA)
pl_write()
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_paperless.py"])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["bob"]})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
check((Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG)), "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id NOT IN (?,?)", (ORG, ids["bob"], ids["carol"]), write=True)
dbx("DELETE FROM org_members WHERE user_id=?", (ids["erin"],), write=True)  # erin: a freelancer without an organisation
r = A.post(B + "/api/admin/agents", json={"username": "plbot", "display_name": "Plbot"})
assert r.status_code == 201, r.text
AGT = r.json().get("token") or ""
for s in (A, Bo):
    s.post(B + "/api/auth/logout")
A, Bo, Ca, Er = sess("alice"), sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    f = s.get(B + "/api/state").json()["settings"].get("features") or ""
    if "docs" not in f.split(","):
        s.patch(B + "/api/settings", json={"features": f + ",docs"})


MAP = {"tags": {"2": {"to": "folder", "name": "Archive 2025"}, "3": {"to": "skip", "name": ""}, "1": {"to": "tag", "name": "Taxes"}},
       "senders": {}, "types": {"9": "Bill"}}


def rules(s, ws="private"):
    return s.get(B + f"/api/docs/settings?ws={ws}").json().get("rules") or []


def strip(r):
    return {k: v for k, v in r.items() if k != "id"}


def import_all(s, ws="private", mapping=MAP):
    r = s.post(B + "/api/paperless/import", json={"ws": ws, "mapping": mapping})
    check(r.ok, f"import started in {ws} ({r.status_code} {r.text[:200]})")
    j = run_idle(s, ws, 90)
    return ((j or {}).get("conn") or {}).get("run") or {}


# ---- the new table + column (rollback: additive only)
check(dbx("SELECT 1 FROM information_schema.columns WHERE table_name='pl_sources' AND column_name='run_learn'"), "pl_sources.run_learn")
check(all(x[0] for x in dbx("SELECT relrowsecurity FROM pg_class WHERE relname='pl_rules'")) and dbx("SELECT 1 FROM pg_class WHERE relname='pl_rules'"),
      "pl_rules with row-level security")

r = A.put(B + "/api/paperless", json={"ws": "private", "url": PL, "token": "pl-secret"})
check(r.ok, f"connected ({r.status_code} {r.text[:200]})")

# ---- preview: what comes along
p = A.get(B + "/api/paperless/preview?ws=private").json()
pr = p.get("rules") or {}
# before the first import nothing is left out yet: "Ignore me" counts too (the mapping comes with the start)
check(pr.get("convert") == 6 and pr.get("dup") == 0 and pr.get("on") is True, f"preview: 6 rules to take over ({pr})")
check(pr.get("auto") == 1, f"preview: 1 auto counted apart ({pr.get('auto')})")
bad = {(b["name"], b["why"]) for b in pr.get("unsupported") or []}
check(bad == {("Bad regex", "pattern"), ("Long", "long")} and pr.get("unsupported_n") == 2, f"preview: too complex / too long reported ({bad})")
check(all("algo" in t and "match" in t for t in p.get("tags", [])), "preview: the labels carry their matching")
p2 = A.get(B + "/api/paperless/preview?ws=private")
# the mapping saved with the import decides (renamed / folder / skip); before it, every label is itself
check(p2.ok, "preview again")

# ---- import: rules + learning
check(not dbx("SELECT 1 FROM doc_models WHERE ws='u1'"), "no models before the import")
run = import_all(A)
le = run.get("learn") or {}
check(run.get("new") == 2, f"import: 2 new ({run})")
check(le.get("rules_new") == 5 and le.get("rules_dup") == 0 and le.get("trained") == 2, f"import result: 5 rules, 2 documents learnt ({le})")
check("unsupported" not in le, "the stored summary keeps numbers only, no label names")
check(le.get("auto") == 1 and le.get("unsupported_n") == 2, f"import result: auto + not taken over reported ({le})")
rs = [strip(x) for x in rules(A)]
want = [{"kind": "any", "match": "tax steuer", "tags": ["Taxes"]},
        {"kind": "exact", "match": "archive copy", "folder": "Archive 2025"},
        {"kind": "regex", "match": r"ACME\d+", "case": True, "tags": ["Case"]},
        {"kind": "fuzzy", "match": "Example Utlity", "sender": "Example Utility"},
        {"kind": "regex", "match": "invoice|bill", "type": "Bill"}]
for w in want:
    check(w in rs, f"rule taken over: {w} ({rs})")
check(len(rs) == 5 and not any("never mind" == x.get("match") for x in rs), f"the left-out tag makes no rule ({len(rs)})")
feats = {x[0] for x in dbx("SELECT feature FROM doc_models WHERE ws='u1'")}
check({"sender", "type", "tags"} <= feats, f"the models learnt sender / type / tags ({sorted(feats)})")
tr_ = dbx("SELECT COUNT(*) FROM doc_meta d JOIN pl_imported p ON p.node_id=d.node_id AND p.dup=0 WHERE d.ws='u1' AND d.trained<>''")[0][0]
check(tr_ == 2, f"both imported documents marked as trained ({tr_})")
check(dbx("SELECT COUNT(*) FROM pl_rules WHERE ws='u1' AND rule_id IS NOT NULL")[0][0] == 5, "pl_rules: the origin of the 5 rules")
j = A.get(B + "/api/paperless?ws=private").json()
check(((j.get("conn") or {}).get("run") or {}).get("learn", {}).get("rules_new") == 5, "the connection shows what the last import learnt")

# ---- again: no doubles; a deleted rule does not come back
p = A.get(B + "/api/paperless/preview?ws=private").json()
check((p.get("rules") or {}).get("dup") == 5 and (p.get("rules") or {}).get("convert") == 0, f"preview again: all 5 already here ({p.get('rules')})")
gone = next(x for x in rules(A) if x.get("kind") == "exact")
check(A.delete(B + f"/api/docs/rules/{gone['id']}").ok, "a taken-over rule deleted")
run = import_all(A)
le = run.get("learn") or {}
check(le.get("rules_new") == 0 and le.get("rules_dup") == 5 and le.get("trained") == 0, f"second import: nothing new, nothing learnt twice ({le})")
check(len(rules(A)) == 4 and not any(x.get("kind") == "exact" for x in rules(A)), "the deleted rule stays deleted")

# ---- a case-sensitive rule (normal upload; the rules sort it)
def upload(s, name, text, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf(text), "application/pdf")})
    check(r.ok, f"upload {name} ({r.status_code} {r.text[:200]})")
    ids_ = (r.json().get("ids") or [None]) if r.ok else [None]
    return ids_[0]


def tag_names(s, nid):
    def ready():
        d = s.get(B + f"/api/docs/{nid}").json()
        return d if d.get("state") in ("done", "failed") else None
    d = until(ready, 60) or {}
    return {(t.get("name") if isinstance(t, dict) else str(t)) for t in d.get("tags") or []}, d


n1 = upload(A, "order-upper.pdf", "Order ACME123 received")
n2 = upload(A, "order-lower.pdf", "Order acme123 received")
t1, d1 = tag_names(A, n1)
t2, _d2 = tag_names(A, n2)
check("Case" in t1, f"case-sensitive regex: ACME123 tagged ({t1} {str(d1)[:200]})")
check("Case" not in t2, f"case-sensitive regex: acme123 not tagged ({t2})")

# ---- the switch off: no rules, the learning still runs (erin, a person without an organisation)
check(Er.put(B + "/api/paperless", json={"ws": "private", "url": PL, "token": "pl-secret"}).ok, "erin connected")
ER_WS = f"u{ids['erin']}"
run = import_all(Er, mapping={**MAP, "rules": False})
le = run.get("learn") or {}
check(le.get("rules_new") == 0 and le.get("rules_off") is True and le.get("trained") == 2, f"switch off: no rules, still learnt ({le})")
check(rules(Er) == [], "switch off: erin's space has no rules")

# ---- an organisation's import: rules in exactly that workspace
before = len(rules(A))
check(Bo.put(B + "/api/paperless", json={"ws": f"org:{ORG}", "url": PL, "token": "pl-secret"}).ok, "bob connects Alpha")
run = import_all(Bo, ws=f"org:{ORG}")
check((run.get("learn") or {}).get("rules_new") == 5, f"Alpha: 5 rules ({run.get('learn')})")
org_rows = dbx("SELECT ws, org_id FROM doc_rules WHERE created_by=?", (ids["bob"],))
check(org_rows and all(w == f"o{ORG}" and o == ORG for w, o in org_rows), f"Alpha's rules carry its workspace + org ({org_rows})")
check(len(rules(A)) == before and rules(Er) == [], "the other spaces are untouched")
check(all(x[0] == f"o{ORG}" for x in dbx("SELECT ws FROM pl_rules WHERE org_id=?", (ORG,))), "pl_rules of Alpha in Alpha")
check(Ca.get(B + f"/api/paperless/preview?ws=org:{ORG}").status_code in (403, 404), "a member without admin: no preview")

# ---- Kalmido only read
check(all(x.get("m") == "GET" for x in pl_log()), "only GET to Paperless-ngx")

print(f"p269_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
