#!/usr/bin/env python3
# kalmido-suite:
"""2.352.0 G (#2752, #2754): review fixes to "every list is a project" and the shortened mail view -- invented names only.
 (M3) the shortened HTML of a deeply nested large mail is quick (capped text per node, depth cap -> the whole mail) and the
      input is cut to the size the cleaner shows
 (M4) folder repositories: a life-area (health, read later), a family list in the folder never uses the folder's repository
 (M5) project mailbox: no address for a life-area / family / read-later list (409 like the inbox), an existing address of a
      list that became one stops receiving; a kid account never reads a filed mail node (hbm_node_ok)
 (N14) a participant gets no sprints in /api/state and no project file trash
 (N15) an old kind=project list can become a family list (the stored kind is not read any more)
 (P4) the same for a person without an organisation (M4, M5, N15)
usage: p2352_g_review_test.py <datadir>
freelancer-matrix: lists, hub"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, sess  # noqa: E402

MAILENV = {"KALMIDO_MAIL_ADDRESS": "tasks@example.test", "KALMIDO_IMAP_HOST": "127.0.0.1", "KALMIDO_IMAP_PORT": "1143",
           "KALMIDO_IMAP_SSL": "0", "KALMIDO_IMAP_USER": "kalmido", "KALMIDO_IMAP_PASSWORD": "secret", "KALMIDO_IMAP_INTERVAL": "600"}
kt.fresh(env=MAILENV, prefix="P2352G")
A = kt.setup()
FEAT = "cal,collab,comments,events,progress,family,life"
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
FID, Fr = freelancer(B, A, features=FEAT)


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(sql, args)
        r = cur.fetchall() if "RETURNING" in sql.upper() or sql.lstrip().upper().startswith("SELECT") else None
        c.commit()
        return r
    finally:
        c.close()


def in_app(code, timeout=120):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app, json\n" + code],
                       capture_output=True, text=True, timeout=timeout)
    out = r.stdout.strip().splitlines()
    if not out or not out[-1].startswith("{"):
        print("IN_APP FAILED:", r.stdout[-1500:], r.stderr[-2500:], flush=True)
        return {}
    return json.loads(out[-1])


def me_id(s):
    return s.get(B + "/api/state").json()["me"]["id"]


def mklist(s, name, **kw):
    r = s.post(B + "/api/lists", json={"name": name, **kw})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================ M3: the shortened HTML stays quick, a too deep mail stays whole
M3 = r"""
import time
from kalmido.integrations.mailtrim_html import md_trim_html
from kalmido.hub import mailview
words = "invented words of a long newsletter\n" * 250  # many lines per level: the old code split + cleaned all of them per level
deep = "".join("<div>" + words for _ in range(190)) + "<blockquote>older quote</blockquote>" + "</div>" * 190
t = time.time(); out = md_trim_html(deep); dt = time.time() - t
too = "".join("<div>x" for _ in range(260)) + "<blockquote>older quote</blockquote>" + "</div>" * 260
t = time.time(); out2 = md_trim_html(too); dt2 = time.time() - t
big = "<p>" + "a" * (mailview.MH_HTML_MAX + 50000) + "</p><blockquote>older quote</blockquote>"
t = time.time(); out3 = mailview.mh_short(big); dt3 = time.time() - t
print(json.dumps({"len": len(deep), "dt": dt, "quote_gone": "older quote" not in out, "kept": out.count("invented words"),
                  "dt2": dt2, "whole": out2 == too, "dt3": dt3, "cut": len(out3) <= mailview.MH_HTML_MAX + 100}))
"""
j = in_app(M3, timeout=900)
check(j.get("len", 0) > 1000000 and j.get("dt", 99) < 5, f"M3: 190 levels / {j.get('len')} characters shortened in {j.get('dt')} s (< 5 s)")
check(j.get("quote_gone") and j.get("kept") == 47500, f"M3: the deep mail is still shortened right (quote out, text kept) {j}")
check(j.get("whole") and j.get("dt2", 99) < 5, f"M3: deeper than 200 levels -> the whole mail unchanged {j.get('whole')} {j.get('dt2')}")
check(j.get("cut") and j.get("dt3", 99) < 5, f"M3: mh_short works on the shown size only {j.get('cut')} {j.get('dt3')}")


# ================================================================ M4 + M5 + N15 for a person in the instance and a freelancer
def kinds_checks(s, who):
    uid = me_id(s)
    plain = mklist(s, "Code " + who, folder="Repo " + who)
    health = mklist(s, "Doctor " + who, folder="Repo " + who)
    fam = mklist(s, "Shopping " + who, folder="Repo " + who)
    read = mklist(s, "Articles " + who, folder="Repo " + who)
    dbw("UPDATE lists SET life='health' WHERE id=?", (health,))
    dbw("UPDATE lists SET family='shopping' WHERE id=?", (fam,))
    dbw("UPDATE lists SET life='reading' WHERE id=?", (read,))
    # M4: a folder repository straight into the database (never polled; the API would ask the provider)
    cid = dbw("INSERT INTO git_conns(list_id, provider, base_url, owner, repo, next_at, created_by, created_at) "
              "VALUES(?, 'gitea', 'http://127.0.0.1:9', 'acme', ?, 9e12, ?, '2026-10-01T00:00:00Z') RETURNING id",
              (plain, "repo-" + who.lower(), uid))[0][0]
    dbw("INSERT INTO git_folders(conn_id, owner_id, folder, created_at) VALUES(?, ?, ?, '2026-10-01T00:00:00Z')", (cid, uid, "Repo " + who))
    r = s.get(B + f"/api/lists/{plain}/repos").json()
    check((r.get("folder") or {}).get("uses") and len(r.get("folder_repos") or []) == 1, f"M4 {who}: the plain project uses the folder repository {r.get('folder')}")
    for lid, nm in ((health, "health"), (fam, "family"), (read, "read later")):
        r = s.get(B + f"/api/lists/{lid}/repos").json()
        check(not (r.get("folder") or {}).get("uses") and not r.get("folder_repos"), f"M4 {who}: a {nm} list never uses the folder repository {r.get('folder')}")
    j = in_app(f"""
from kalmido.core.config import app as kapp
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.integrations.gitfolder import gf_lists_of_conn, gf_conns_of_lists
c = connect()
with kapp.test_request_context('/api/state'):
    with system_ctx(c):
        print(json.dumps({{"lists": sorted(gf_lists_of_conn(c, {cid})), "bulk": sorted(int(k) for k in gf_conns_of_lists(c, [{plain}, {health}, {fam}, {read}]))}}))
""")
    check(j.get("lists") == [plain] and j.get("bulk") == [plain], f"M4 {who}: polling links only the plain project {j}")
    # M5: the project mailbox
    r = s.post(B + "/api/hubmail/address", json={"list_id": plain})
    check(r.ok and "@" in (r.json().get("address") or ""), f"M5 {who}: a plain project has an e-mail address {r.status_code} {r.text[:120]}")
    for lid, nm in ((health, "health"), (fam, "family"), (read, "read later")):
        r = s.post(B + "/api/hubmail/address", json={"list_id": lid})
        check(r.status_code == 409, f"M5 {who}: no e-mail address for a {nm} list {r.status_code} {r.text[:120]}")
    j = in_app(f"""
from kalmido.core.config import app as kapp
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.hub.hubmail import _holder_ok
c = connect()
with kapp.test_request_context('/api/state'):
    with system_ctx(c):
        print(json.dumps({{"plain": _holder_ok(c, "list", {uid}, None, None, {plain}) is not None,
                          "health": _holder_ok(c, "list", {uid}, None, None, {health}) is not None,
                          "family": _holder_ok(c, "list", {uid}, None, None, {fam}) is not None}}))
""")
    check(j.get("plain") and j.get("health") is False and j.get("family") is False, f"M5 {who}: a health / family list does not receive {j}")
    # N15: an old project (kind stored as project) becomes a family list
    old = mklist(s, "Old project " + who)
    dbw("UPDATE lists SET kind='project' WHERE id=?", (old,))
    r = s.patch(B + f"/api/lists/{old}", json={"family": "household"})
    check(r.ok, f"N15 {who}: an old kind=project list can become a family list {r.status_code} {r.text[:160]}")


kinds_checks(A, "Alice")
kinds_checks(Fr, "Frida")  # freelancer-matrix: lists, hub

# ================================================================ M5: a kid account never reads a filed mail node
r = A.post(B + "/api/users", json={"username": "kimi", "display_name": "Kimi", "password": kt.PASSWORD, "email": "kimi@example.com", "orgs": []})
assert r.ok, r.text
KID = r.json()["id"]
Ki = sess("kimi")
Ki.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
KL = mklist(Ki, "Kimi project")
MID = dbw("INSERT INTO hub_mails(owner_id, list_id, ws, message_id, subject, created_at) VALUES(?, ?, ?, '<p2352g@example.test>', 'Invented', "
          "'2026-10-01T00:00:00Z') RETURNING id", (KID, KL, f"u{KID}"))[0][0]
dbw("UPDATE users SET kid=1 WHERE id=?", (KID,))
j = in_app(f"""
from kalmido.core.config import app as kapp
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.hub.hubmail import hbm_node_ok, hbm_node_mail_ids
c = connect()
with kapp.test_request_context('/api/state'):
    with system_ctx(c):
        print(json.dumps({{"kid": hbm_node_ok(c, {KID}, {MID}), "ids": sorted(hbm_node_mail_ids(c, {KID})),
                          "admin": hbm_node_ok(c, {me_id(A)}, {MID})}}))
""")
check(j.get("kid") is False and j.get("ids") == [], f"M5: a kid account never reads a filed mail node {j}")

# ================================================================ N14: a participant sees no sprints and no project file trash
r = A.post(B + "/api/users", json={"username": "pia", "display_name": "Pia", "password": kt.PASSWORD, "email": "pia@example.com", "orgs": []})
assert r.ok, r.text
PIA = r.json()["id"]
Pi = sess("pia")
Pi.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
SP = mklist(A, "Sprint project")
check(A.put(B + f"/api/lists/{SP}/sprint-settings", json={"on": True}).ok, "N14: sprints on")
check(A.put(B + f"/api/lists/{SP}/members", json={"user_id": PIA, "role": "participant"}).ok, "N14: Pia participant")
A.post(B + "/api/tasks", json={"list_id": SP, "title": "Paint the invented fence", "assignee_id": PIA})
dbw("INSERT INTO list_files(list_id, name, size, path, user_id, created_at, deleted_at) VALUES(?, 'old-plan.txt', 3, 'x/old-plan.txt', ?, "
    "'2026-10-01T00:00:00Z', '2026-10-02T00:00:00Z')", (SP, me_id(A)))
la = next((x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == SP), {})
lp = next((x for x in Pi.get(B + "/api/state").json()["lists"] if x["id"] == SP), None)
check("sprints" in la, "N14: the owner gets the sprints")
check(lp is not None and "sprints" not in lp, f"N14: the participant gets no sprints {(lp or {}).get('sprints')} seen={lp is not None}")
oa, op = A.get(B + f"/api/lists/{SP}/overview").json(), Pi.get(B + f"/api/lists/{SP}/overview")
check(len(oa.get("files_trash") or []) == 1, "N14: the owner sees the project file trash")
check(op.status_code in (403, 404) or op.json().get("files_trash") == [], f"N14: the participant sees no project file trash {op.status_code}")

sys.exit(kt.done("p2352_g_review"))
