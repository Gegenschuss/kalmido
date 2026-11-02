#!/usr/bin/env python3
"""2.470.0 part C API tests (#3596, point 4): the sharing defaults of a workspace.
 - nothing stored: today's values (7 days, 14 days / 25 MB / 20 files / documents + pictures), also for a new link without "expires"
 - an organisation: its admin sets them (PATCH /api/orgs/<id>), a member reads them but cannot change them, a second
   organisation sees nothing; private: the person alone (PATCH /api/settings), in every case a person without an
   organisation too (freelancer-matrix: files), and without the office module
 - limits stay hard: a default above a limit, an unknown field or kind, no kind at all: 400; a stored value above today's
   limit is held to it when read; an explicit value of the dialog still wins
 - the organisation's switch "external links" still decides
usage: pr2470_c_api_test.py <datadir>      (a fresh container, KMT_NOSTART: it runs already)"""
import json
import os
import sys
from datetime import datetime

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402


def usess(user):
    s = sess(user)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    return s


def folder(s, name, space="private"):
    r = s.post(B + "/api/files/folders", json={"name": name, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def link_days(s, nid, body):
    """A new link with this body -> (its days of validity, None = no end; the answer's default)."""
    r = s.post(B + f"/api/files/nodes/{nid}/ext-links", json=body)
    assert r.ok, r.text
    j = r.json()
    x = next(y for y in j["links"] if y["id"] == j["id"])
    if not x["expires_at"]:
        return None, j["default_expires"]
    t = lambda v: datetime.fromisoformat(v.replace("Z", "+00:00"))  # noqa: E731
    return round((t(x["expires_at"]) - t(x["created_at"])).total_seconds() / 86400), j["default_expires"]


def limits(s, nid):
    return s.get(B + f"/api/files/nodes/{nid}/requests").json()["limits"]


def dbw(sql, args=()):
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def sd(s, space):
    return s.get(B + "/api/share-defaults", params={"space": space})


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "TASKS_MAX_FILE_MB": "50"})
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE}).json()["id"]
ids = {}
for u, orgs in (("bob", [ORG]), ("dora", [])):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": orgs})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, DORA = usess("bob"), usess("dora")
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta Studio", "admin_id": ids["dora"]}).json()["id"]
BUILTIN = {"link_expires": "7d", "req_days": 14, "req_mb": 25, "req_files": 20, "req_types": ["docs", "images"]}

# ================================================================ nothing stored: today's values
j = sd(A, f"org:{ORG}").json()
check(j["defaults"] == BUILTIN and j["stored"] == {} and j["can_edit"] is True, f"the built-in values, the admin may edit {j}")
OF = folder(A, "Kunden", f"org:{ORG}")
check(link_days(A, OF, {}) == (7, "7d"), "a link without expires: 7 days as before")
lim = limits(A, OF)
check((lim["default_days"], lim["default_mb"], lim["default_files"], lim["default_types"]) == (14, 25, 20, ["docs", "images"]), f"file requests as before {lim}")

# ================================================================ an organisation: its admin
STD = {"link_expires": "30d", "req_days": 30, "req_mb": 10, "req_files": 5, "req_types": ["media", "images", "docs"]}
r = A.patch(B + f"/api/orgs/{ORG}", json={"share_defaults": STD})
check(r.ok, f"the admin sets the defaults {r.status_code} {r.text[:200]}")
j = sd(A, f"org:{ORG}").json()
check(j["defaults"]["link_expires"] == "30d" and j["defaults"]["req_types"] == ["docs", "images", "media"], f"stored {j['defaults']}")
r = BOB.patch(B + f"/api/orgs/{ORG}", json={"share_defaults": {"link_expires": "none"}})
check(r.status_code == 403, f"a member cannot change them {r.status_code}")
j = sd(BOB, f"org:{ORG}").json()
check(j["defaults"]["link_expires"] == "30d" and j["can_edit"] is False, f"a member reads them {j}")
check(link_days(A, OF, {}) == (30, "30d"), "a new link without expires takes the default")
check(link_days(A, OF, {"expires": "1d"})[0] == 1, "an explicit choice still wins")
lim = limits(A, OF)
check((lim["default_days"], lim["default_mb"], lim["default_files"]) == (30, 10, 5) and lim["max_files"] == 200 and lim["days"] == 90, f"the dialog's values, limits unchanged {lim}")
r = A.post(B + f"/api/files/nodes/{OF}/requests", json={"title": "Belege", "days": 3})
check(r.status_code == 201, r.text[:200])
row = kt.dbx("SELECT max_mb, max_files, types FROM fs_upload_requests WHERE id=?", (r.json()["id"],))[0]
check(tuple(row) == (10, 5, "docs,images,media"), f"a request without values takes the defaults {tuple(row)}")
r = A.post(B + f"/api/files/nodes/{OF}/requests", json={"title": "Grosse", "days": 3, "max_mb": 20, "max_files": 100, "types": ["archives"]})
check(r.status_code == 201, f"a request may go above the default, up to the limits {r.text[:200]}")
OP = folder(A, "Privat")
check(link_days(A, OP, {}) == (7, "7d"), "the organisation's default stays out of my private files")

# ================================================================ a second organisation sees nothing
check(sd(DORA, f"org:{ORG}").status_code == 404, "a stranger: 404 on the defaults")
check(DORA.patch(B + f"/api/orgs/{ORG}", json={"share_defaults": {}}).status_code in (403, 404), "a stranger cannot change them")
check(sd(DORA, f"org:{ORG2}").json()["defaults"] == BUILTIN, "the other organisation keeps the built-in values")
check(sd(A, "org:x").status_code == 400, "a broken space: 400")

# ================================================================ private: the person alone
r = A.patch(B + "/api/settings", json={"share_defaults": '{"link_expires":"none","req_files":3}'})
check(r.ok, f"my private defaults {r.status_code} {r.text[:200]}")
j = sd(A, "private").json()
check(j["defaults"]["link_expires"] == "none" and j["defaults"]["req_files"] == 3 and j["can_edit"] is True, f"private {j}")
check(link_days(A, OP, {}) == (None, "none"), "private: no end date as the default")
check(link_days(A, OF, {})[1] == "30d", "the organisation's files keep the organisation's default")
check(sd(BOB, "private").json()["defaults"] == BUILTIN, "the private defaults of one person are not another's")

# ================================================================ the limits stay hard
for what, v in (("a request of 91 days", {"req_days": 91}), ("no days", {"req_days": 0}), ("201 files", {"req_files": 201}), ("too many MB", {"req_mb": 999999}),
                ("an unknown validity", {"link_expires": "90d"}), ("a date", {"link_expires": "2030-01-01"}), ("an unknown field", {"foo": 1}), ("true as a number", {"req_mb": True}),
                ("an unknown kind", {"req_types": ["exe"]}), ("no kind", {"req_types": []})):
    check(A.patch(B + f"/api/orgs/{ORG}", json={"share_defaults": v}).status_code == 400, f"org: {what} refused")
    check(A.patch(B + "/api/settings", json={"share_defaults": json.dumps(v)}).status_code == 400, f"private: {what} refused")
dbw("UPDATE orgs SET share_defaults=? WHERE id=?", ('{"req_days":5000,"req_mb":999999,"req_files":999,"link_expires":"x","req_types":["exe"]}', ORG))
j = sd(A, f"org:{ORG}").json()["defaults"]
check(j == {"link_expires": "7d", "req_days": 90, "req_mb": sd(A, "private").json()["limits"]["max_mb"], "req_files": 200, "req_types": ["docs", "images"]}, f"a stored value is held to the limits {j}")
dbw("UPDATE orgs SET share_defaults='not json' WHERE id=?", (ORG,))
check(sd(A, f"org:{ORG}").json()["defaults"] == BUILTIN, "a broken stored value: the built-in values")
r = A.patch(B + f"/api/orgs/{ORG}", json={"share_defaults": {}})
check(r.ok and sd(A, f"org:{ORG}").json()["stored"] == {}, "back to the built-in values")

# ================================================================ the organisation's switch decides, whatever the default says
A.patch(B + f"/api/orgs/{ORG}", json={"share_defaults": {"link_expires": "none"}, "ext_links": False})
check(A.post(B + f"/api/files/nodes/{OF}/ext-links", json={}).status_code == 409, "links off in the organisation: no link, with any default")
A.patch(B + f"/api/orgs/{ORG}", json={"ext_links": True})

# ================================================================ a person without an organisation (freelancer-matrix: files)
FID, Fr = freelancer(B, A, features="files,docs")
check(sd(Fr, "private").json()["can_edit"] is True, "the freelancer edits the own defaults, the office module off")
check(Fr.patch(B + "/api/settings", json={"share_defaults": '{"link_expires":"1d","req_days":2}'}).ok, "saved")
FF = folder(Fr, "Eigene")
check(link_days(Fr, FF, {}) == (1, "1d"), "the link takes the default")
check(limits(Fr, FF)["default_days"] == 2, "the file request takes the default")
check(sd(Fr, f"org:{ORG}").status_code == 404, "no organisation to see")

sys.exit(kt.done("pr2470_c_api"))
