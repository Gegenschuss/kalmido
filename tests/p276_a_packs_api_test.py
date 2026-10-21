#!/usr/bin/env python3
"""2.76.0 API tests, part A (#1023): the pack catalogue -- country and industry packs from a catalogue (env
KALMIDO_PACKS_CATALOG), installed per office area, against a fake catalogue inside the test container (fake_packs.py,
127.0.0.1:8099, allowed via KALMIDO_PACKS_ALLOW_HOSTS). Invented names only.
 - no catalogue: only the built-in packs, no fetch, install 404
 - list / search / kind filter, broken index entries skipped (counted), texts cleaned (no tags)
 - install a country pack (verified), choose it, finalise a quotation; an update (v2) shows and is installed; the finalised
   document stays exactly as it was (snapshot with pack_sha256 / pack_source); uninstall refused while it is the country
   pack (409 text), allowed after switching back to DE, restore (the undo)
 - the check: wrong checksum, too large, markup, code / kind mismatch -> 422; community without confirmation -> 409;
   an address in a private network / a redirect to one -> 502; unknown pack -> 404
 - rights: members read, cannot install (403); agents 403; another organisation sees nothing of it and keeps the built-in
   packs; a person without an organisation installs into their own office
 - an industry pack: installed, switched on, uninstall refused (rules), refused while an open quotation uses it
usage: p276_a_packs_api_test.py <datadir>"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,office,clients"
FK = "http://127.0.0.1:8099"
PACKS = os.path.join(N, "..", "kalmido", "office", "packs")
O, D = "/api/office", "/api/office/docs"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def start(extra=""):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + extra)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def setup():
    """alice: admin of Alpha, bob: member of Alpha, carol: admin of Beta, erin: no organisation (personal office)."""
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
    a = sess("alice")
    a.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
    uid = {}
    for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("erin", "Erin Free")):
        r = a.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
        assert r.ok, r.text
        uid[u] = r.json()["id"]
    me = a.get(B + "/api/state").json()["me"]["id"]
    org = a.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": me}).json()["id"]
    assert a.put(B + f"/api/orgs/{org}/members", json={"email": "bob@example.com", "role": "member"}).ok
    org2 = a.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carol"]}).json()["id"]
    dbx("DELETE FROM org_members WHERE user_id=?", (uid["erin"],), write=True)
    ss = {"alice": a, "bob": sess("bob"), "carol": sess("carol"), "erin": sess("erin")}
    for s in ss.values():
        s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
    ss["alice"].patch(B + "/api/settings", json={"workspace": f"org:{org}"})
    ss["bob"].patch(B + "/api/settings", json={"workspace": f"org:{org}"})
    ss["carol"].patch(B + "/api/settings", json={"workspace": f"org:{org2}"})
    ag = a.post(B + "/api/admin/agents", json={"username": "packbot", "display_name": "Packbot"}).json()
    return ss, org, org2, {"Authorization": "Bearer " + (ag.get("token") or ""), "X-Requested-With": "kalmido"}


def items(j, kind=None):
    return {(x["kind"], x["code"]): x for x in j.get("items") or [] if kind is None or x["kind"] == kind}


# ---------------------------------------------------------------- the pack files of the fake catalogue
DE = json.load(open(os.path.join(PACKS, "de.json"), encoding="utf-8"))
FILM = json.load(open(os.path.join(PACKS, "industry", "film.json"), encoding="utf-8"))


def country(code, name, name_en, std, red, version=1, community=False):
    p = json.loads(json.dumps(DE))
    p.update(code=code, name=name, name_en=name_en, version=version, community=community)
    p["tax"]["standard"], p["tax"]["reduced"] = std, red
    return p


FILES = {}


def put(path, obj):
    raw = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False, indent=1).encode()
    FILES[path] = raw
    return {"url": FK + "/" + path, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


AT1 = put("country/at-1.json", country("AT", "Österreich", "Austria", 20, 10))
AT2 = put("country/at-2.json", country("AT", "Österreich", "Austria", 21, 13, version=2))
LU1 = put("country/lu-1.json", country("LU", "Luxemburg", "Luxembourg", 17, 8))
XA = country("XA", "Markup", "Markup", 20, 10)
XA["labels"]["en"]["offer"] = "<b>Quotation</b>"
XA1 = put("country/xa-1.json", XA)
XB1 = put("country/xb-1.json", country("XB", "Prüfsumme", "Checksum", 20, 10))
XC1 = put("country/xc-1.json", country("XD", "Anderer Code", "Other code", 20, 10))
big = country("XE", "Groß", "Large", 20, 10)
big["texts"]["intro"]["en"] = "x" * (600 * 1024)
XE1 = put("country/xe-1.json", big)
PH = json.loads(json.dumps(FILM))
PH.update(code="photo", name={"de": "Foto", "en": "Photo"}, version=1)
PH1 = put("industry/photo-1.json", PH)
FI2 = put("industry/film-x.json", dict(json.loads(json.dumps(FILM)), kind="country"))  # kind mismatch inside the file
NO1 = put("country/no-1.json", country("NO", "Norwegen", "Norway", 25, 15))
# 2.76.0 review (N3): nested deeper than the recursive checks go -> 422, never a 500
XH1 = put("country/xh-1.json", ('{"code": "XH", "deep": ' + "[" * 950 + "]" * 950 + "}").encode())


def entry(kind, code, name, versions, verified=True, min_app="2.0.0", **kw):
    vs = [dict(v, version=n, released="2026-10-17", min_app=min_app) for n, v in versions]
    return dict({"kind": kind, "code": code, "name": name, "author": "Example Group", "license": "CC0-1.0",
                 "verified": verified, "versions": vs}, **kw)


def index(at_versions):
    return {"format": 1, "name": "Test packs", "updated": "2026-10-17", "packs": [
        entry("country", "AT", {"de": "Österreich", "en": "Austria"}, at_versions,
              description={"de": "Steuersätze <script>alert(1)</script>*Österreich*", "en": "Tax rates <script>alert(1)</script>*Austria*"},
              homepage="javascript:alert(1)"),
        entry("country", "LU", {"de": "Luxemburg", "en": "Luxembourg"}, [(1, LU1)], verified=False),
        entry("country", "XA", "Markup", [(1, XA1)]),
        entry("country", "XB", "Checksum", [(1, dict(XB1, sha256="0" * 64))]),
        entry("country", "XC", "Code", [(1, XC1)]),
        entry("country", "XE", "Large", [(1, {"url": XE1["url"], "sha256": XE1["sha256"]})]),
        entry("country", "XH", "Deep", [(1, XH1)]),
        entry("country", "NO", "Norway", [(1, dict(NO1, url="https://10.1.2.3/no-1.json"))]),
        entry("country", "SE", "Sweden", [(1, dict(NO1, url=FK + "/redirect-internal"))]),
        entry("industry", "photo", {"de": "Foto", "en": "Photo"}, [(1, PH1)], description="Shoot calculation for photo productions"),
        entry("industry", "film", {"de": "Film & Video", "en": "Film & Video"}, [(2, FI2)]),
        entry("country", "FI", "Finland", [(1, NO1)], min_app="99.0.0"),  # needs a newer app: listed without a latest version
        # broken entries: skipped one by one (4)
        {"kind": "country", "code": "at", "name": "lower case", "versions": [dict(AT1, version=1)]},
        {"kind": "plugin", "code": "XX", "name": "Unknown kind", "versions": [dict(AT1, version=1)]},
        entry("country", "XF", "Plain http elsewhere", [(1, dict(AT1, url="http://127.0.0.2:8099/country/at-1.json"))]),
        entry("country", "XG", "No checksum", [(1, {"url": AT1["url"]})]),
    ]}


def write_catalogue(at_versions):
    os.makedirs(os.path.join(DATA, "packs", "country"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "packs", "industry"), exist_ok=True)
    for path, raw in FILES.items():
        open(os.path.join(DATA, "packs", path), "wb").write(raw)
    json.dump(index(at_versions), open(os.path.join(DATA, "packs", "index.json"), "w"), ensure_ascii=False)


# ================================================================ 1. no catalogue
start()
S, ORG, ORG2, AGH = setup()
A = S["alice"]
j = A.get(B + O + "/catalog").json()
check(j.get("configured") is False and j.get("error") is None and j.get("fetched_at") is None and j.get("can_manage") is True
      and j.get("source") == "" and j.get("skipped") == 0, f"no catalogue: configured false, can_manage ({j})")
check(S["bob"].get(B + O + "/catalog").json().get("can_manage") is False, "no catalogue: a member reads, cannot manage")
check(set(items(j)) == {("country", "DE"), ("country", "XX"), ("industry", "film")} and all(x["builtin"] and x["badge"] == "verified" for x in j["items"]),
      f"no catalogue: only the built-in packs ({sorted(items(j))})")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "AT", "version": 1})
check(r.status_code == 404, f"no catalogue: install 404 ({r.status_code})")
j = A.get(B + O + "/packs").json()
check([p["code"] for p in j["packs"]] == ["DE", "XX"] and j["packs"][0]["source"] == "builtin" and j["packs"][0]["badge"] == "verified"
      and [x["code"] for x in j.get("industry") or []] == ["film"], f"GET packs: built-in DE + film ({j.get('industry')})")

# ================================================================ 2. with the fake catalogue
start(f" -e KALMIDO_PACKS_CATALOG={FK}/index.json -e KALMIDO_PACKS_ALLOW_HOSTS=127.0.0.1:8099")
write_catalogue([(1, AT1)])
shutil.copy(os.path.join(N, "fake_packs.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_packs.py"], check=True)
S, ORG, ORG2, AGH = setup()
A, Bo, Ca, Er = S["alice"], S["bob"], S["carol"], S["erin"]

cols = {r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name='office_pack_installs'")}
check({"org_id", "kind", "code", "version", "sha256", "data", "meta", "badge", "source", "installed_at", "installed_by", "removed_at"} <= cols,
      f"new table office_pack_installs ({sorted(cols)})")
check(all(x[0] for x in dbx("SELECT relrowsecurity FROM pg_class WHERE relname='office_pack_installs'")), "row-level security on office_pack_installs")

# ---- list, search, filter
j = None
for _ in range(20):  # the fake catalogue may need a moment to listen
    j = A.post(B + O + "/catalog/refresh", json={}).json()
    if not j.get("error"):
        break
    time.sleep(0.5)
it = items(j)
check(j.get("configured") is True and j.get("source") == "127.0.0.1" and j.get("error") is None and j.get("fetched_at"),
      f"catalogue fetched ({ {k: j.get(k) for k in ('configured', 'source', 'error', 'fetched_at')} })")
check(j.get("skipped") == 4, f"four broken entries skipped ({j.get('skipped')})")
check(("country", "AT") in it and ("industry", "photo") in it and ("country", "XF") not in it and ("country", "XG") not in it,
      f"valid entries listed, broken ones not ({sorted(it)})")
at = it.get(("country", "AT")) or {}
check(at.get("name") == "Austria" and at.get("badge") == "verified" and at.get("builtin") is False and at.get("installed") is None
      and (at.get("latest") or {}).get("version") == 1 and at.get("update") is False and at.get("author") == "Example Group",
      f"AT: name in my language, verified, latest v1 ({at})")
check("<" not in at.get("description", "") and "*Austria*" in at.get("description", "") and at.get("homepage") == "",
      f"AT: tags removed from the description, javascript: homepage dropped ({at.get('description')!r}, {at.get('homepage')!r})")
check(it[("country", "DE")]["builtin"] and it[("industry", "film")]["builtin"] and it[("country", "LU")]["badge"] == "community",
      "built-in DE / film, LU community")
check(sorted([x["code"] for x in j["items"]][:3]) == ["DE", "XX", "film"], f"built-in packs first ({[x['code'] for x in j['items']][:4]})")  # 2.147.0 (#2461): + XX
check(j.get("can_manage") is True, "admin: can_manage")
check(items(A.get(B + O + "/catalog?q=austr").json()).keys() == {("country", "AT")}, "search: q matches the name")
check(items(A.get(B + O + "/catalog?q=example%20group&kind=industry").json()).keys() == {("industry", "photo"), ("industry", "film")},
      "search: author + kind filter")
check(set(items(A.get(B + O + "/catalog?kind=industry").json())) == {("industry", "film"), ("industry", "photo")}, "kind filter: industry")
jb = Bo.get(B + O + "/catalog")
check(jb.ok and jb.json().get("can_manage") is False and ("country", "AT") in items(jb.json()), "member: reads the catalogue, cannot manage")

# ---- rights
check(Bo.post(B + O + "/packs/install", json={"kind": "country", "code": "AT", "version": 1}).status_code == 403, "member: install 403")
check(Bo.post(B + O + "/catalog/refresh", json={}).status_code == 403, "member: refresh 403")
check(requests.get(B + O + "/catalog", headers=AGH).status_code == 403, "agent: catalogue 403")
check(requests.post(B + O + "/packs/install", headers=AGH, json={"kind": "country", "code": "AT", "version": 1}).status_code == 403, "agent: install 403")
check(A.post(B + O + "/packs/install", json={"kind": "plugin", "code": "AT", "version": 1}).status_code == 400, "unknown kind: 400")
check(A.post(B + O + "/packs/install", json={"kind": "country", "code": "AT", "version": "1"}).status_code == 400, "version must be a number: 400")
check(A.post(B + O + "/packs/install", json={"kind": "country", "code": "ZZ", "version": 1}).status_code == 404, "not in the catalogue: 404")
check(A.post(B + O + "/packs/install", json={"kind": "country", "code": "AT", "version": 7}).status_code == 404, "unknown version: 404")
check(items(A.get(B + O + "/catalog").json())[("country", "FI")]["latest"] is None, "a pack for a newer app: no installable version")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "FI", "version": 1})
check(r.status_code == 422 and any(p.startswith("min_app") for p in r.json().get("problems") or []), f"min_app too high: 422 ({r.status_code} {r.text[:200]})")

# ---- the check
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "XB", "version": 1})
check(r.status_code == 422 and any("sha256" in p for p in r.json().get("problems") or []) and r.json().get("error") == "The pack failed the check",
      f"wrong checksum: 422 ({r.status_code} {r.text[:200]})")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "XE", "version": 1})
check(r.status_code == 422 and any("size" in p for p in r.json().get("problems") or []), f"too large: 422 ({r.status_code} {r.text[:200]})")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "XH", "version": 1})
check(r.status_code == 422, f"nested very deep: 422, not 500 ({r.status_code} {r.text[:200]})")  # 2.76.0 review (N3)
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "XA", "version": 1})
check(r.status_code == 422 and any("markup" in p for p in r.json().get("problems") or []), f"markup: 422 ({r.status_code} {r.text[:200]})")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "XC", "version": 1})
check(r.status_code == 422 and any(p.startswith("code") for p in r.json().get("problems") or []), f"code mismatch: 422 ({r.status_code} {r.text[:200]})")
r = A.post(B + O + "/packs/install", json={"kind": "industry", "code": "film", "version": 2})
check(r.status_code == 422 and any(p.startswith("kind") for p in r.json().get("problems") or []), f"kind mismatch: 422 ({r.status_code} {r.text[:200]})")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "NO", "version": 1})
check(r.status_code == 502, f"pack in a private network: 502 ({r.status_code} {r.text[:200]})")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "SE", "version": 1})
check(r.status_code == 502, f"redirect to an internal address: 502 ({r.status_code} {r.text[:200]})")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "LU", "version": 1})
check(r.status_code == 409 and r.json().get("error") == "Community packs need your confirmation", f"community without confirmation: 409 ({r.status_code})")
check(dbx("SELECT COUNT(*) FROM office_pack_installs")[0][0] == 0, "nothing stored by the refused installs")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "LU", "version": 1, "accept_community": True})
check(r.ok and r.json()["installed"]["badge"] == "community", f"community with confirmation: installed ({r.status_code} {r.text[:200]})")

# ---- install AT, choose it, finalise a quotation
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "AT", "version": 1})
check(r.ok and r.json()["installed"]["version"] == 1 and r.json()["installed"]["badge"] == "verified"
      and r.json()["installed"]["installed_by_name"] == "Alice Admin" and r.json()["item"]["installed"], f"AT v1 installed ({r.status_code} {r.text[:300]})")
check(any(x.get("action") == "pack_install" for x in A.get(B + O + "/log?limit=20").json().get("log") or []), "office log: pack_install")
pk = {p["code"]: p for p in A.get(B + O + "/packs").json()["packs"]}
check(pk.get("AT", {}).get("source") == "installed" and pk["AT"]["tax"]["standard"] == 20 and pk["DE"]["source"] == "builtin",
      f"GET packs: AT installed ({sorted(pk)})")
check(A.get(B + O + "/packs/AT").ok and Bo.get(B + O + "/packs/AT").ok, "GET packs/AT: admin and member of Alpha")
check(Ca.get(B + O + "/packs/AT").status_code == 404 and "AT" not in [p["code"] for p in Ca.get(B + O + "/packs").json()["packs"]],
      "tenant-matrix: office -- another organisation does not see the installed pack")
check(items(Ca.get(B + O + "/catalog").json())[("country", "AT")]["installed"] is None, "another organisation: AT not installed there")
check(Ca.put(B + O + "/settings", json={"pack": "AT"}).status_code == 400, "another organisation cannot choose AT")
check(Ca.get(B + O + "/settings").json()["pack"]["code"] == "DE", "another organisation keeps the built-in pack")
check(A.put(B + O + "/settings", json={"pack": "AT"}).ok, "Alpha chooses AT")
st = A.get(B + O + "/settings").json()
check(st["pack"]["code"] == "AT" and st["pack"]["tax"]["standard"] == 20, f"settings: the pack AT ({st['pack'].get('code')})")
S1 = A.post(B + O + "/services", json={"name_de": "Schnitt", "name_en": "Editing", "category": "Video", "daily_rate": 1000}).json()["id"]
DOC = A.post(B + D, json={"project_title": "Imagefilm"}).json()["id"]
r = A.put(B + f"{D}/{DOC}/items", json={"items": [{"service_id": S1, "qty": 1}]})
check(r.ok and r.json()["totals"]["net"] == 1000 and r.json()["totals"]["gross"] == 1200, f"AT: 20 % VAT ({r.json().get('totals') if r.ok else r.text[:200]})")
r = A.post(B + f"{D}/{DOC}/finalize")
check(r.ok and r.json()["locked"] is True, "quotation finalised " + r.text[:200])
SNAP = json.loads(dbx("SELECT tax_snapshot FROM office_docs WHERE id=?", (DOC,))[0][0])
check(SNAP.get("pack") == "AT" and SNAP.get("version") == "1" and SNAP.get("pack_sha256") == AT1["sha256"] and SNAP.get("pack_source") == "127.0.0.1",
      f"snapshot: pack AT v1, sha256 + source ({ {k: SNAP.get(k) for k in ('pack', 'version', 'pack_sha256', 'pack_source')} })")
R1 = A.get(B + f"{D}/{DOC}/render").json()

# ---- an update
write_catalogue([(2, AT2), (1, AT1)])
j = A.post(B + O + "/catalog/refresh", json={}).json()
at = items(j)[("country", "AT")]
check(at["update"] is True and at["latest"]["version"] == 2 and at["installed"]["version"] == 1, f"update v2 shown ({at})")
r = A.post(B + O + "/packs/install", json={"kind": "country", "code": "AT", "version": 2})
check(r.ok and r.json()["installed"]["version"] == 2 and r.json()["item"]["update"] is False, f"update installed ({r.status_code} {r.text[:200]})")
check(A.get(B + O + "/settings").json()["pack"]["tax"]["standard"] == 21, "the settings now use v2 (21 %)")
check(json.loads(dbx("SELECT tax_snapshot FROM office_docs WHERE id=?", (DOC,))[0][0]) == SNAP, "finalised document: snapshot unchanged after the update")
check(A.get(B + f"{D}/{DOC}/render").json() == R1, "finalised document: rendering unchanged after the update")
DOC2 = A.post(B + D, json={"project_title": "Zweitfilm"}).json()["id"]
r = A.put(B + f"{D}/{DOC2}/items", json={"items": [{"service_id": S1, "qty": 1}]})
check(r.ok and r.json()["totals"]["gross"] == 1210, f"a new quotation uses v2 (21 %): {r.json().get('totals') if r.ok else r.text[:200]}")
# 2.76.0 review (M1): the open documents an update / removal would recalculate (a hint, never blocking)
at = items(A.get(B + O + "/catalog").json())[("country", "AT")]
check(at["affects"] == 1 and at["affects_text"] == "1 open documents will be calculated with the new rates and texts.", f"catalogue: affects 1 ({at.get('affects')})")
check(items(A.get(B + O + "/catalog").json())[("country", "LU")]["affects"] == 0, "a pack not in effect: affects 0")

# ---- uninstall + restore
r = A.delete(B + O + "/packs/installed/country/AT")
check(r.status_code == 409 and r.json().get("error") == "This pack is the country pack of this office. Choose another one first.",
      f"uninstall refused while chosen ({r.status_code} {r.text[:200]})")
check(items(A.get(B + O + "/catalog").json())[("country", "AT")]["in_use"] is True, "catalogue: in_use")
check(Bo.delete(B + O + "/packs/installed/country/AT").status_code == 403, "member: uninstall 403")
check(A.put(B + O + "/settings", json={"pack": "DE"}).ok, "back to DE")
r = A.delete(B + O + "/packs/installed/country/AT")
check(r.ok, f"uninstalled after switching ({r.status_code} {r.text[:200]})")
check("AT" not in [p["code"] for p in A.get(B + O + "/packs").json()["packs"]] and A.get(B + O + "/packs/AT").status_code == 404, "AT gone from the area")
check(A.put(B + O + "/settings", json={"pack": "AT"}).status_code == 400, "AT cannot be chosen any more")
check(A.get(B + f"{D}/{DOC}/render").json() == R1, "finalised document: rendering unchanged after the uninstall")
check(A.get(B + f"{D}/{DOC}/pdf").ok, "finalised document: PDF still there")
check(A.delete(B + O + "/packs/installed/country/AT").status_code == 404, "uninstall twice: 404")
r = A.post(B + O + "/packs/installed/country/AT/restore")
check(r.ok and r.json()["installed"]["version"] == 2, f"restore (undo): v2 back ({r.status_code} {r.text[:200]})")
check(A.post(B + O + "/packs/installed/country/AT/restore").status_code == 409, "restore while active: 409")
check(A.delete(B + O + "/packs/installed/country/DE").status_code == 400, "a built-in pack cannot be removed: 400")
check(A.delete(B + O + "/packs/installed/country/QQ").status_code == 404, "not installed: 404")
check(A.delete(B + O + "/packs/installed/plugin/AT").status_code == 404, "unknown kind: 404")

# ---- an industry pack
r = A.post(B + O + "/packs/install", json={"kind": "industry", "code": "photo", "version": 1})
check(r.ok and r.json()["installed"]["version"] == 1, f"industry pack installed ({r.status_code} {r.text[:200]})")
ind = {x["code"]: x for x in A.get(B + O + "/packs").json().get("industry") or []}
check(ind.get("photo", {}).get("source") == "installed" and ind.get("photo", {}).get("name_en") == "Photo" and ind.get("film", {}).get("source") == "builtin",
      f"GET packs: industry list ({ind})")
check("photo" not in [x["code"] for x in Ca.get(B + O + "/packs").json().get("industry") or []], "another organisation: no photo pack")
r = A.put(B + O + "/settings", json={"industry_packs": ["film", "photo"]})
check(r.ok and r.json()["settings"]["industry_packs"] == ["film", "photo"], f"photo switched on ({r.text[:200]})")
check(Ca.put(B + O + "/settings", json={"industry_packs": ["photo"]}).json()["settings"]["industry_packs"] == [], "another organisation: photo dropped")
r = A.delete(B + O + "/packs/installed/industry/photo")
check(r.status_code == 409 and r.json().get("error") == "This pack is switched on in the calculation rules. Switch it off first.",
      f"uninstall refused while switched on ({r.status_code} {r.text[:200]})")
DOC3 = A.post(B + D, json={"project_title": "Fotoshooting"}).json()["id"]
r = A.post(B + f"{D}/{DOC3}/parts", json={"kind": "shoot", "title": "Shooting"})
check(r.status_code in (200, 201), "shoot part created " + r.text[:200])
PART = dbx("SELECT id, sheet FROM office_doc_parts WHERE doc_id=? AND kind='shoot'", (DOC3,))
if PART and PART[0][1].startswith("{"):
    sh = json.loads(PART[0][1])
    sh["pack"] = "photo"
    dbx("UPDATE office_doc_parts SET sheet=? WHERE id=?", (json.dumps(sh), PART[0][0]), write=True)
check(A.put(B + O + "/settings", json={"industry_packs": ["film"]}).ok, "photo switched off")
r = A.delete(B + O + "/packs/installed/industry/photo")
check(r.status_code == 409 and r.json().get("error") == "1 open quotations use this pack.", f"uninstall refused: an open quotation uses it ({r.status_code} {r.text[:200]})")
A.delete(B + f"{D}/{DOC3}")
r = A.delete(B + O + "/packs/installed/industry/photo")
check(r.ok, f"industry pack uninstalled ({r.status_code} {r.text[:200]})")

# ---- the personal office of a person without an organisation
j = Er.get(B + O + "/catalog").json()
check(j.get("can_manage") is True and items(j)[("country", "AT")]["installed"] is None, "personal office: can manage, AT not installed")
r = Er.post(B + O + "/packs/install", json={"kind": "country", "code": "AT", "version": 1})
check(r.ok and r.json()["installed"]["version"] == 1, f"personal office: installs AT v1 ({r.status_code} {r.text[:200]})")
check(Er.put(B + O + "/settings", json={"pack": "AT"}).ok and Er.get(B + O + "/settings").json()["pack"]["tax"]["standard"] == 20,
      "personal office: AT v1 chosen (20 %)")
check(A.get(B + O + "/settings").json()["pack"]["code"] == "DE" and items(A.get(B + O + "/catalog").json())[("country", "AT")]["installed"]["version"] == 2,
      "Alpha keeps its own installation (v2), DE chosen")
check(items(Ca.get(B + O + "/catalog").json())[("country", "AT")]["installed"] is None, "Beta: still nothing installed")
rows = dbx("SELECT org_id, code, version FROM office_pack_installs WHERE removed_at IS NULL ORDER BY org_id, code")
check(len({x[0] for x in rows}) == 2 and ORG2 not in {x[0] for x in rows}, f"installations in two areas only ({rows})")

print(f"p276_a_packs_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
