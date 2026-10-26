#!/usr/bin/env python3
"""2.306.0 C (#2889 #2946): small data protection items.
freelancer-matrix: accounts, contacts, news (a person without an organisation keeps every function in the own private space)
 - new ntfy topics start with the host name of the address, not a fixed word; the account list shows no foreign topics
 - the contact import fetches linked photos only with the tick box on (photos=0 in the form: no fetch)
 - a deleted comment takes the excerpt copy out of its News items
 - browser error reports scrub the name and login of the reporting person
 - deleting an account removes its export folder at once
usage: p2306_c_privacy_small_test.py <datadir>      (KMT_NOSTART=1 / P2306C_NOSTART=1: a running server)"""
import os
import subprocess
import sys

import kt
from kt import B, CT, check, done, fresh, sess, setup
from freelancer_fixture import FEATURES, freelancer

FEAT = FEATURES + ",contacts"
OLD = "moa" + "rch"  # the fixed word the topics used to start with


def in_app(code):
    """Python inside the server container (app loaded, c = a connection in the system context) -> stdout + stderr."""
    body = "\n".join("    " + x for x in code.split("\n"))
    out = subprocess.run(["docker", "exec", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nc = connect()\n"
                          "with system_ctx(c):\n" + body + "\nc.close()"], capture_output=True, text=True)
    return out.stdout + out.stderr


fresh({"PUBLIC_URL": "https://tasks.example.org"}, prefix="P2306C")
A = setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bobby", "display_name": "Bobby Tables", "password": "password123", "email": "bobby@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bobby")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FID, Fr = freelancer(B, A, "frida", features=FEAT)

# ================================================================ ntfy topic prefix, no foreign topics
out = in_app("from kalmido.core.db import random_topic\nprint('topic', random_topic())")
check("topic tasks-example-org-tasks-" in out and OLD not in out, "#2889 a new topic starts with the host name, not a fixed word " + out[-200:])
out = in_app("import kalmido.core.db as d\nd.PUBLIC_URL = 'not a url'\nprint('topic', d.topic_prefix())\nd.PUBLIC_URL = ''\nprint('topic', d.topic_prefix())")
check(out.count("topic kalmido") == 2, "#2889 no usable host: the prefix falls back to kalmido " + out[-200:])
for s, who in ((A, "the admin"), (Bo, "a member")):
    tp = s.get(B + "/api/me").json().get("ntfy_topic", "")
    check(bool(tp) and not tp.startswith(OLD), f"#2889 {who} has a topic without the fixed word {tp}")
lst = A.get(B + "/api/users?all=1").json()["users"]
mine = next(u for u in lst if u["id"] == ALICE)
other = next(u for u in lst if u["id"] == BOB)
check(mine.get("ntfy_topic") and "ntfy_topic" not in other, f"#2889 the account list shows the own topic only {sorted(other)}")
page = A.get(B + "/api/users?all=1&limit=50").json()
rows = page.get("users") or page.get("items") or []
check(rows and all(("ntfy_topic" in u) == (u["id"] == ALICE) for u in rows), "#2889 the paged account list shows no foreign topics")
# the admin still sets a topic for somebody (the answer of the account list just does not show it)
r = A.patch(B + f"/api/users/{BOB}", json={"ntfy_topic": "bob-own-topic-123"})
check(r.ok and Bo.get(B + "/api/me").json().get("ntfy_topic") == "bob-own-topic-123", f"#2889 an admin can still set a topic {r.status_code}")

# ================================================================ contact photos: tick box off = no fetch
VCF = ("BEGIN:VCARD\nVERSION:3.0\nFN:Photo Person\nUID:c-photo-1\n"
       "PHOTO;VALUE=uri:https://lh3.googleusercontent.com/a/some-picture\nEND:VCARD\n")
for s, who in ((A, "admin"), (Fr, "freelancer")):
    bk = s.post(B + "/api/books", json={"name": "Photos " + who, "org_id": None})
    check(bk.status_code in (200, 201), f"#2889 setup: a book for the {who} {bk.status_code} {bk.text[:150]}")
    bid = bk.json()["id"]
    r = s.post(B + f"/api/books/{bid}/import", files={"file": ("p.vcf", VCF.encode(), "text/vcard")}, data={"photos": "0"})
    check(r.ok and r.json().get("created") == 1, f"#2889 the import with the tick box off works for the {who} {r.status_code} {r.text[:150]}")
uid_a = ALICE
V2 = VCF.replace("c-photo-1", "c-photo-2")
out = in_app("import kalmido.contacts.model as m\ncalls = []\nm.photo_fetch = lambda u: calls.append(u) or ''\n"
             "r = c.execute(\"SELECT id FROM books WHERE name LIKE 'Photos admin%'\").fetchone()\n"
             f"v = {V2!r}\n"
             f"m.import_vcards(c, {ALICE}, r[0], v, photos=0)\nprint('off', len(calls))\n"
             f"m.import_vcards(c, {ALICE}, r[0], v.replace('c-photo-2', 'c-photo-3'), photos=15)\nprint('on', len(calls))\nc.rollback()")
check("off 0" in out and "on 1" in out, "#2889 photos=0 fetches nothing, photos>0 fetches the link " + out[-300:])

# ================================================================ a deleted comment: no excerpt left in News
L = Fr.post(B + "/api/lists", json={"name": "Frida list"}).json()["id"]
T = Fr.post(B + "/api/tasks", json={"title": "Task with comment", "list_id": L}).json()["id"]
cm = Fr.post(B + f"/api/tasks/{T}/comments", json={"body": "a comment"})
check(cm.status_code in (200, 201), f"#2889 setup: a comment {cm.status_code} {cm.text[:150]}")
CID = cm.json().get("id") or cm.json().get("comment", {}).get("id")
out = in_app("import json\nc.execute('INSERT INTO notifications(user_id,kind,task_id,comment_id,data,created_at) VALUES(?,?,?,?,?,?)',\n"
             f"          ({FID}, 'comment', {T}, {CID}, json.dumps({{'excerpt': 'private words', 'ext_name': 'Guest'}}), '2026-01-01T00:00:00'))\n"
             "c.commit()\nprint('inserted')")
check("inserted" in out, "#2889 setup: a News item with an excerpt copy " + out[-200:])
r = Fr.delete(B + f"/api/comments/{CID}")
check(r.ok, f"#2889 the comment is deleted {r.status_code}")
out = in_app(f"import json\nr = c.execute('SELECT data FROM notifications WHERE comment_id={CID}').fetchone()\n"
             "d = r[0] if isinstance(r[0], dict) else json.loads(r[0])\nprint('data', sorted(d))")
check("data ['ext_name']" in out, "#2889 the excerpt copy is gone from the News item, the rest stays " + out[-200:])

# ================================================================ browser error reports: names scrubbed
out = in_app("from kalmido.integrations.errorreports import cer_text\n"
             "print('t1', cer_text('Bobby Tables cannot read x of bobby', 300, ('Bobby Tables', 'bobby')))\n"
             "print('t2', cer_text('ab is short', 300, ('ab', 'x')))\n"
             "print('t3', cer_text('Bobby failed', 300))")
check("t1 <name> cannot read x of <name>" in out, "#2889 the display name and login of the reporting person are scrubbed " + out[-200:])
check("t2 ab is short" in out and "t3 Bobby failed" in out, "#2889 very short names and calls without names stay as before " + out[-200:])
out = in_app("from kalmido.integrations.errorreports import cer_text\nprint('t4', cer_text('Maximum call stack of max', 300, ('max',)))")
check("t4 Maximum call stack of <name>" in out, "#2889 review: a login is replaced as a whole word only " + out[-200:])
out = in_app("from kalmido.office.model import office_scheme_clean\nfrom kalmido.core.errors import BadInput\n"
             "print('ok4', office_scheme_clean('{client}-{project}-{initials}-{client}-{seq:03}'))\n"
             "try:\n    office_scheme_clean('{client}-{project}-{initials}-{client}-{project}-{seq:03}')\nexcept BadInput as e:\n    print('bad5')")
check("ok4 {client}" in out and "bad5" in out, "#2875 review: a number scheme with five text blocks is refused, four stay " + out[-200:])

# ================================================================ account deletion: the export folder goes at once
out = in_app("from kalmido.admin.acctexport import UMZ_DIR\nimport os\n"
             f"p = os.path.join(UMZ_DIR, '{BOB}')\nos.makedirs(p, exist_ok=True)\nopen(os.path.join(p, 'x.zip.enc'), 'w').write('x')\nprint('made', os.path.isdir(p))")
check("made True" in out, "#2889 setup: an export folder " + out[-200:])
r = A.delete(B + f"/api/users/{BOB}")
check(r.ok, f"#2889 the account is deleted {r.status_code} {r.text[:150]}")
out = in_app("from kalmido.admin.acctexport import UMZ_DIR\nimport os\n"
             f"print('exists', os.path.exists(os.path.join(UMZ_DIR, '{BOB}')))")
check("exists False" in out, "#2889 the export folder is gone with the account " + out[-200:])

sys.exit(done("p2306_c_privacy_small"))
