#!/usr/bin/env python3
"""2.47.3 API tests (part D), own container (start.sh).
 - #1738: Google photo links in a vCard file are fetched at the FILE import (allowlist *.googleusercontent.com, https only,
   size limit, SSRF guard, Google's placeholders skipped); importing again adds missing pictures without doubles; the fetch is
   replaced by a fake inside the server process (no internet in tests)
 - #1764: POST /api/v1/agent/chats/{uid} takes job_parent (only with job_id, a job of the same agent, not the job itself);
   the message shows job_id + job_parent; unknown / foreign / alone: 400
usage: p2473_d_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def py(code):
    p = subprocess.run(["docker", "exec", "-i", "-w", "/app", CT, "python", "-"], input=code, capture_output=True, text=True)
    return p.stdout.strip(), p.stderr[-600:]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["contacts"]})

# ================================================================== #1738 Google photo links at the vCard import
BK = A.post(B + "/api/books", json={"name": "Google"}).json()["id"]
GOOD = "https://lh3.googleusercontent.com/contacts/AG-example1"
DEFAULT = "https://lh3.googleusercontent.com/a/default-user=s100"
EVIL = "https://example.com/pic.jpg"
INTERNAL = "https://127.0.0.1/pic.jpg"


def card(uid, name, photo):
    return f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{name}\r\nUID:{uid}\r\n" + (f"PHOTO;VALUE=uri:{photo}\r\n" if photo else "") + "END:VCARD\r\n"


VCF = card("g1", "Ada Example", GOOD) + card("g2", "Bob Default", DEFAULT) + card("g3", "Cy Evil", EVIL) + card("g4", "Di Internal", INTERNAL) + card("g5", "Ed Plain", "")
open("/tmp/p2473_d.vcf", "w").write(VCF)
subprocess.run(["docker", "exec", "-i", CT, "sh", "-c", "cat > /tmp/p2473_d.vcf"], input=open("/tmp/p2473_d.vcf", "rb").read(), check=True)  # #2716: read-only root fs, no docker cp
# the fake: a JPEG-looking body of 3 KB for the allowed link, a tiny one for 'tiny', records every URL it is asked for
FAKE = '''
import sys
sys.path.insert(0, "/app")
import kalmido.calendars.subscriptions as S
from kalmido.contacts import model as M
from kalmido.core.db import connect
ASKED = []
def fake(url, **kw):
    ASKED.append(url)
    if "tiny" in url:
        return 200, {}, b"\\xff\\xd8\\xff" + b"0" * 100, url
    if "big" in url:
        return 200, {}, b"\\xff\\xd8\\xff" + b"0" * (M.PHOTO_MAX + 10), url
    if "html" in url:
        return 200, {}, b"<html>" + b"0" * 3000, url
    return 200, {}, b"\\xff\\xd8\\xff" + b"1" * 3000, url
S.cal_http = fake
c = connect()
uid = c.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
bid = %d
text = open("/tmp/p2473_d.vcf").read()
res = M.import_vcards(c, uid, bid, text, photos=30)
c.commit()
print(res["created"], res["updated"], len(ASKED), ASKED[0] if ASKED else "")
rows = c.execute("SELECT uid, photo FROM contacts WHERE book_id=? ORDER BY uid", (bid,)).fetchall()
print(",".join(r[0] + ":" + ("P" if r[1] else "-") for r in rows))
print(M.import_vcards(c, uid, bid, text, photos=30)["updated"], len(ASKED), c.execute("SELECT COUNT(*) FROM contacts WHERE book_id=?", (bid,)).fetchone()[0])
c.commit()
'''
out, err = py(FAKE % BK)
lines = out.split("\n")
check(len(lines) >= 3, f"fake import ran {err}")
if len(lines) >= 3:
    check(lines[0].startswith("5 0 1 " + GOOD + "=s256"), f"only the allowed link was fetched, with the size suffix: {lines[0]}")
    check(lines[1] == "g1:P,g2:-,g3:-,g4:-,g5:-", f"picture only for the allowed Google link: {lines[1]}")
    check(lines[2] == "5 1 5", f"second import: no doubles (5 contacts), fetches nothing new (the picture stays): {lines[2]}")
cs = A.get(B + "/api/contacts", params={"q": "Ada"}).json()["items"]
check(cs and cs[0].get("photo"), "the contact shows the picture")
r = A.get(B + f"/api/books/{BK}/export.vcf")
check(r.ok and r.text.count("PHOTO") == 4 and "googleusercontent.com/contacts" not in r.text, f"export: the fetched link is not kept next to the picture ({r.text.count('PHOTO')} PHOTO lines)")

# a picture that is too small (flat colour), too big, or not an image is dropped; a contact without a picture gets it at a re-import
BK2 = A.post(B + "/api/books", json={"name": "Google2"}).json()["id"]
VCF2 = card("t1", "Tiny", "https://lh3.googleusercontent.com/tiny") + card("t2", "Big", "https://lh3.googleusercontent.com/big") + card("t3", "Html", "https://lh3.googleusercontent.com/html")
open("/tmp/p2473_d.vcf", "w").write(VCF2)
subprocess.run(["docker", "exec", "-i", CT, "sh", "-c", "cat > /tmp/p2473_d.vcf"], input=open("/tmp/p2473_d.vcf", "rb").read(), check=True)  # #2716: read-only root fs, no docker cp
out, err = py(FAKE % BK2)
check(out.split("\n")[1:2] == ["t1:-,t2:-,t3:-"], f"too small / too big / not an image: no picture {out} {err}")

# the real route has no internet here: the import still works and the contact stays without a picture (no error, no hang)
r = A.post(B + f"/api/books/{BK2}/import", files={"file": ("c.vcf", card("r1", "Real Route", GOOD), "text/vcard")})
check(r.ok and r.json()["created"] == 1, f"import with a link that cannot be loaded still works {r.text[:200]}")
# CardDAV-style single parse never fetches: parse_vcard only notes the link
out, err = py('from kalmido.contacts.model import parse_vcard as p\nv = p("BEGIN:VCARD\\r\\nVERSION:3.0\\r\\nFN:X\\r\\nPHOTO;VALUE=uri:%s\\r\\nEND:VCARD\\r\\n")\nprint(repr(v["photo"]), v.get("photo_url"), "PHOTO" in v["extra"])' % GOOD)
check(out == f"'' {GOOD} True", f"parse keeps the link in extra and does not fetch: {out} {err}")
out, err = py("from kalmido.contacts.model import photo_url_ok as o\nprint([o(u) for u in ['https://lh3.googleusercontent.com/x','http://lh3.googleusercontent.com/x','https://googleusercontent.com/x','https://lh3.googleusercontent.com.evil.test/x','https://lh3.googleusercontent.com:8443/x','https://a:b@lh3.googleusercontent.com/x','https://x/a.googleusercontent.com/y']])")
check(out == "[True, False, False, False, False, False, False]", f"URL allowlist: {out} {err}")

# ================================================================== #1764 job_parent on a chat message
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "leadbot", "display_name": "Lead bot"})
AGT, AH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}
ALICE = A.get(B + "/api/state").json()["me"]["id"]
LST = A.post(B + "/api/lists", json={"name": "Jobs"}).json()["id"]
A.put(B + f"/api/lists/{LST}/members", json={"user_id": AGT, "role": "edit"})
V = B + "/api/v1"


def job(title):
    return requests.post(V + "/agent/jobs", headers=AH, json={"title": title, "user_id": ALICE, "state": "running"}).json()["id"]


def say(body, **kw):
    return requests.post(V + f"/agent/chats/{ALICE}", headers=AH, json={"body": body, **kw})


J1, J2 = job("Leader"), job("Part")
r = say("Job #%d: part speaks" % J2, job_id=J2, job_parent=J1)
check(r.status_code == 201 and r.json().get("job_id") == J2 and r.json().get("job_parent") == J1, f"job_parent is stored and returned {r.status_code} {r.text[:200]}")
r = say("Job #%d: leader speaks" % J1, job_id=J1)
check(r.status_code == 201 and r.json().get("job_parent") is None, "without job_parent: null")
check(say("x", job_parent=J1).status_code == 400, "job_parent alone (no job_id): 400")
check(say("x", job_id=J2, job_parent=J2).status_code == 400, "a job is not its own leader: 400")
check(say("x", job_id=J2, job_parent=999999).status_code == 400, "an unknown leader: 400")
check(say("x", job_id=J2, job_parent="abc").status_code == 400, "a bad number: 400")
m = [x for x in A.get(B + f"/api/agents/{AGT}/chat").json().get("messages", []) if x.get("job_parent")]
check(m and m[0]["job_parent"] == J1 and m[0]["job_id"] == J2, f"the person's chat shows job_parent {m[:1]}")
check(say("a note", kind="notice", job_id=J2, job_parent=J1).status_code == 400, "a notice takes no job fields: 400")

print(f"p2473_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
