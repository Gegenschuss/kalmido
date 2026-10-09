#!/usr/bin/env python3
"""2.36.1 API tests, part B: Office & finance (#1021) -- module skeleton, country pack DE, master data; own container (start.sh).
 - the module needs the feature "office" and an organisation: 403 without the feature, 403 for kids and agent accounts,
   400 with a readable hint for a person without an organisation (and with the workspace switch on "all" in several)
 - the organisation's admin edits settings and master data (services, equipment, sets, text blocks, framework contracts);
   a member reads them and is refused on writes (403); foreign ids are 404 for everyone
 - the first call seeds the DE pack's rights catalogue + intro / closing into the text blocks; the country packs are listed
   and validated (DE valid, a broken pack lists its problems)
 - settings: validation (colour, language, currency, decimals with a comma, number scheme needs {seq}); the number preview
   follows the scheme; the counter runs per year
 - delete archives a row that a set / contract / document still uses, deletes an unused one
 - export / import round trip into a second organisation (ids of set items, contract rates and rights are remapped)
 - tenant matrix (mode workspaces): a second organisation and a private person see nothing of the first (marker below)
 - backup + restore keep the office tables; the tables are additive (the 2.36.0 image runs on with them)
usage: p2361_b_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
P = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PROXY_PORT", "3041")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,clients,office"


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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def wait_for(fn, t=8.0):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.4)
    return fn()


def restart(extra, **env):
    e = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + extra, **env)
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
r = A.post(B + "/api/users", json={"username": "lina", "display_name": "Lina", "password": "password123", "kid": True, "parents": [1]})
assert r.ok, r.text
LINA = r.json()["id"]
Bo, Ca, Da, Li = sess("bob"), sess("carol"), sess("dave"), sess("lina")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
O = "/api/office"

# ================================================================== schema: additive tables
tabs = {r[0] for r in dbx("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'office_%'")}
for t in ("office_settings", "office_services", "office_equipment", "office_sets", "office_texts", "office_contracts", "office_numbers"):
    check(t in tabs, f"schema: table {t}")
for t in ("office_services", "office_equipment", "office_sets", "office_texts", "office_contracts"):
    check(any(r[1] == "org_id" and r[3] == 1 for r in dbx(f"PRAGMA table_info({t})")), f"schema: {t}.org_id NOT NULL")
    check(any(r[1].endswith("_org") for r in dbx(f"PRAGMA index_list({t})")), f"schema: index on {t}(org_id)")

# ================================================================== the gate
r = Li.get(B + O + "/settings")
check(r.status_code == 403, "gate: a kid gets 403 " + str(r.status_code))
r = requests.get(B + O + "/settings", headers={**H, **CLH})
check(r.status_code in (401, 403), "gate: an agent token never reaches the module " + str(r.status_code))
r = requests.get(B + O + "/services", headers={**H, **CLH})
check(r.status_code in (401, 403), "gate: ... nor the master data " + str(r.status_code))
r = requests.get(P + O + "/settings", headers={**H, "Remote-User": "claude"})
check(r.status_code in (401, 403), "gate: an agent account behind the proxy gets 403 " + str(r.status_code))
Da.patch(B + "/api/settings", json={"features": "cal,comments"})
r = Da.get(B + O + "/settings")
check(r.status_code == 403 and "Office" in r.text, "gate: feature off -> 403 with the hint " + r.text[:100])
Da.patch(B + "/api/settings", json={"features": FEAT})
check(Da.get(B + "/api/me").status_code == 200, "setup: dave signed in")

# ================================================================== settings + seeded texts (organisation mode: one organisation)
r = A.get(B + O + "/settings")
check(r.ok and r.json()["org_id"] == ORG and r.json()["role"] == "admin", "settings: alice is the organisation's admin " + r.text[:200])
S0 = r.json()
check(S0["settings"]["pack"] == "DE" and S0["pack"]["tax"]["standard"] == 19 and S0["pack"]["tax"]["reduced"] == 7, "settings: pack DE with 19 / 7 %")
check(S0["settings"]["offer_scheme"] == "KVA-{yyyy}-{seq:03}" and S0["number_preview"] == f"KVA-{time.localtime().tm_year}-001", "settings: default scheme + preview " + str(S0.get("number_preview")))
check(S0["settings"]["prod_quotient"] == 3 and S0["settings"]["raw_factor"] == 0.25 and S0["settings"]["producing_rate"] == 600 and S0["settings"]["offer_valid_days"] == 30, "settings: calculation defaults")
r = Bo.get(B + O + "/settings")
check(r.ok and r.json()["role"] == "member", "settings: bob is a member " + r.text[:100])
r = A.get(B + O + "/texts")
TX = r.json()["items"]
kinds = {}
for t in TX:
    kinds.setdefault(t["kind"], []).append(t)
check(len(kinds.get("rights_time", [])) == 3 and len(kinds.get("rights_territory", [])) == 4 and len(kinds.get("rights_media", [])) == 4, "seed: the DE rights catalogue is in the text blocks " + str({k: len(v) for k, v in kinds.items()}))
check(any(t["text_de"] == "weltweit außer Musik auf Messe/Event (DE)" and t["text_en"] == "worldwide except music on trade shows / live events (DE)" for t in kinds.get("rights_territory", [])), "seed: the territory text with umlauts, DE + EN")
check(any(t["text_de"] == "unbegrenzt" and t["text_en"] == "in perpetuity" for t in kinds.get("rights_time", [])), "seed: 'unbegrenzt' / 'in perpetuity'")
check(len(kinds.get("intro", [])) == 1 and len(kinds.get("closing", [])) == 1, "seed: intro + closing once")
check(len(A.get(B + O + "/texts").json()["items"]) == len(TX), "seed: not twice")
RT = next(t for t in kinds["rights_time"] if t["key"] == "unlimited")
RR = next(t for t in kinds["rights_territory"] if t["key"] == "world_ex_music")
RM = next(t for t in kinds["rights_media"] if t["key"] == "internal_web_unpaid")

# ---- packs
r = A.get(B + O + "/packs")
check(r.ok and [p["code"] for p in r.json()["packs"]] == ["DE"], "packs: DE is shipped " + r.text[:100])
r = A.get(B + O + "/packs/DE")
check(r.ok and r.json()["pack"]["labels"]["en"]["rights_time"] == "Duration of License" and r.json()["pack"]["labels"]["de"]["rights"] == "Rechteübertragung", "packs: DE labels")
check(r.json()["pack"]["texts"]["vat_note"]["de"] == "Alle Preise zuzüglich 7 % bzw. 19 % MwSt." and r.json()["pack"]["einvoice"]["status"] == "planned", "packs: vat note + e-invoice planned")
check(A.get(B + O + "/packs/XX").status_code == 404 and A.get(B + O + "/packs/..").status_code == 404, "packs: unknown -> 404")
r = A.post(B + O + "/packs/validate", json={"pack": A.get(B + O + "/packs/DE").json()["pack"]})
check(r.ok and r.json()["problems"] == [], "validator: the DE pack is valid " + r.text[:100])
bad = json.loads(json.dumps(A.get(B + O + "/packs/DE").json()["pack"]))
bad["tax"]["standard"] = "19"
bad["labels"]["en"].pop("rights")
bad["texts"]["rights_time"] = [{"key": "x", "de": "a"}]
bad["formats"]["decimal"] = ";"
bad["texts"]["intro"]["de"] = "<script>alert(1)</script>"
r = A.post(B + O + "/packs/validate", json={"pack": bad})
pr = r.json().get("problems", [])
check(r.ok and len(pr) >= 5 and any("tax.standard" in x for x in pr) and any("labels.en.rights" in x for x in pr) and any("rights_time" in x for x in pr) and any("formats" in x for x in pr) and any("markup" in x for x in pr), "validator: a broken pack lists its problems " + str(pr))
check(Bo.post(B + O + "/packs/validate", json={"pack": bad}).status_code == 403, "validator: admin only")

# ================================================================== settings: write
r = Bo.put(B + O + "/settings", json={"lang": "en"})
check(r.status_code == 403, "settings: a member cannot write " + str(r.status_code))
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH", "lines": ["Hafenstraße 12", "20457 Hamburg"], "contact_lines": "Tel. 040 000000\nhallo@example.com", "bank_lines": []},
                                    "color": "#2F5D8A", "lang": "en", "currency": "EUR", "fx_usd": "1,12", "prod_quotient": "3", "raw_factor": "0,25", "producing_rate": "650,50", "offer_valid_days": 21,
                                    "rights_default": {"time_id": RT["id"], "territory_id": RR["id"], "media_id": RM["id"]}})
check(r.ok, "settings: saved " + r.text[:200])
S1 = r.json()["settings"]
check(S1["company"]["name"] == "Studio Nordlicht GmbH" and S1["company"]["lines"] == ["Hafenstraße 12", "20457 Hamburg"] and S1["company"]["contact_lines"] == ["Tel. 040 000000", "hallo@example.com"], "settings: company lines (list or text)")
check(S1["color"] == "#2f5d8a" and S1["lang"] == "en" and S1["fx_usd"] == 1.12 and S1["producing_rate"] == 650.5 and S1["raw_factor"] == 0.25 and S1["offer_valid_days"] == 21, "settings: colour lower-cased, decimals with a comma " + json.dumps(S1)[:300])
check(S1["rights_default"] == {"time_id": RT["id"], "territory_id": RR["id"], "media_id": RM["id"]}, "settings: default rights")
for body, what in (({"color": "blue"}, "colour"), ({"lang": "fr"}, "language"), ({"currency": "CHF"}, "currency"), ({"fx_usd": "abc"}, "rate"), ({"offer_scheme": "KVA-{yyyy}"}, "scheme without {seq}"),
                   ({"offer_scheme": "KVA-{foo}"}, "unknown placeholder"), ({"offer_scheme": "<b>{seq}</b>"}, "markup in the scheme"), ({"pack": "XX"}, "unknown pack"), ({"producing_service_id": 999999}, "foreign service"), ({"rights_default": {"time_id": 999999}}, "foreign text")):
    r = A.put(B + O + "/settings", json=body)
    check(r.status_code == 400, f"settings: {what} -> 400 " + str(r.status_code))
check(A.get(B + O + "/settings").json()["settings"]["color"] == "#2f5d8a", "settings: nothing changed by the bad ones")
r = A.put(B + O + "/settings", json={"offer_scheme": "A-{yy}-{seq:04}"})
check(r.ok and r.json()["number_preview"] == f"A-{str(time.localtime().tm_year)[2:]}-0001", "settings: scheme with {yy} + {seq:04} " + r.text[:120])
r = A.get(B + O + "/number-preview", params={"scheme": "Q{seq}"})
check(r.ok and r.json()["valid"] and r.json()["preview"] == "Q1", "number preview: Q{seq} -> Q1")
r = A.get(B + O + "/number-preview", params={"scheme": "Q"})
check(r.ok and not r.json()["valid"], "number preview: without {seq} invalid")
A.put(B + O + "/settings", json={"offer_scheme": "KVA-{yyyy}-{seq:03}"})

# ================================================================== master data: services
r = Bo.post(B + O + "/services", json={"name_de": "Kamera"})
check(r.status_code == 403, "services: a member cannot create " + str(r.status_code))
r = A.post(B + O + "/services", json={"name_de": "Kamera", "name_en": "Camera", "category": "Video", "unit": "day", "daily_rate": "980,00", "tax": "standard", "raw_fee": 1, "producing": 1, "intext": "extern", "sort": 1})
check(r.status_code == 201 and r.json()["daily_rate"] == 980 and r.json()["raw_fee"] == 1 and r.json()["producing"] == 1 and r.json()["org_id"] == ORG, "services: created " + r.text[:200])
SV1 = r.json()["id"]
r = A.post(B + O + "/services", json={"name_de": "Nutzungsrechte", "name_en": "Usage rights", "category": "Buyout", "unit": "flat", "daily_rate": 1500, "tax": "reduced", "sort": 2})
SV2 = r.json()["id"]
r = A.post(B + O + "/services", json={"name_de": "Schnitt", "name_en": "Editing", "category": "Video", "unit": "hour", "hourly_rate": 120, "producing": 1, "intext": "intern", "role": "Editor", "sort": 3})
SV3 = r.json()["id"]
check(A.post(B + O + "/services", json={"name_de": ""}).status_code == 400 and A.post(B + O + "/services", json={"name_de": "x", "unit": "week"}).status_code == 400
      and A.post(B + O + "/services", json={"name_de": "x", "tax": "half"}).status_code == 400 and A.post(B + O + "/services", json={"name_de": "x", "daily_rate": "-5"}).status_code == 400, "services: validation 400")
r = Bo.get(B + O + "/services")
check(r.ok and [x["id"] for x in r.json()["items"]] == [SV1, SV2, SV3], "services: a member lists them in order " + r.text[:100])
r = Bo.get(B + O + "/services", params={"q": "edit"})
check(r.ok and [x["id"] for x in r.json()["items"]] == [SV3], "services: search in DE / EN names")
r = A.patch(B + O + f"/services/{SV1}", json={"daily_rate": 1000, "tax": "exempt"})
check(r.ok and r.json()["daily_rate"] == 1000 and r.json()["tax"] == "exempt", "services: patched")
check(Bo.patch(B + O + f"/services/{SV1}", json={"daily_rate": 1}).status_code == 403, "services: a member cannot patch")
check(A.get(B + O + "/services/999999").status_code == 404 and A.patch(B + O + "/services/999999", json={}).status_code == 404 and A.delete(B + O + "/services/999999").status_code == 404, "services: unknown id 404")
check(A.get(B + O + "/widgets").status_code == 404, "unknown kind -> 404")

# ---- equipment + sets
EQ1 = A.post(B + O + "/equipment", json={"name": "Kamera-Set A", "category": "Kamera", "daily_rate": 250}).json()["id"]
EQ2 = A.post(B + O + "/equipment", json={"name": "Licht-Koffer", "category": "Licht", "daily_rate": "80,5"}).json()["id"]
r = A.post(B + O + "/sets", json={"name": "Interview-Set", "discount_pct": 10, "items": [{"equipment_id": EQ1, "qty": 1}, {"equipment_id": EQ2, "qty": 2}]})
check(r.status_code == 201 and r.json()["items"] == [{"equipment_id": EQ1, "qty": 1}, {"equipment_id": EQ2, "qty": 2}] and r.json()["discount_pct"] == 10, "sets: created with items " + r.text[:200])
SET1 = r.json()["id"]
check(A.post(B + O + "/sets", json={"name": "x", "items": [{"equipment_id": 999999}]}).status_code == 400, "sets: a foreign device -> 400")
check(A.get(B + O + "/equipment").json()["items"][1]["daily_rate"] == 80.5, "equipment: comma decimals")

# ---- texts + contracts
r = A.post(B + O + "/texts", json={"kind": "block", "key": "shooting-note", "text_de": "Drehtage inklusive Anreise.", "text_en": "Shooting days including travel."})
check(r.status_code == 201, "texts: created")
TB = r.json()["id"]
check(A.post(B + O + "/texts", json={"kind": "poem", "text_de": "x"}).status_code == 400, "texts: unknown kind 400")
CLIENT = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "org_id": ORG}).json()["id"]
r = A.post(B + O + "/contracts", json={"name": "Rahmenvertrag Beispielkunde", "client_id": CLIENT, "date": "2026-01-15", "raw_included": 1, "rights_time_id": RT["id"], "rights_territory_id": RR["id"],
                                      "rights_media_id": RM["id"], "rights_note_de": "Abweichend von § 3.", "rates": {str(SV1): "900", str(SV3): 100}, "closing_en": "Thank you."})
check(r.status_code == 201 and r.json()["raw_included"] == 1 and r.json()["rates"] == {str(SV1): 900, str(SV3): 100} and r.json()["client_id"] == CLIENT and r.json()["date"] == "2026-01-15", "contracts: created " + r.text[:300])
CT1 = r.json()["id"]
check(A.post(B + O + "/contracts", json={"name": "x", "date": "15.01.2026"}).status_code == 400 and A.post(B + O + "/contracts", json={"name": "x", "rates": {"999999": 1}}).status_code == 400
      and A.post(B + O + "/contracts", json={"name": "x", "rights_time_id": TB}).status_code == 201, "contracts: validation (date, foreign service)")
check(Bo.get(B + O + f"/contracts/{CT1}").ok and Bo.post(B + O + "/contracts", json={"name": "x"}).status_code == 403, "contracts: member reads, cannot write")

# ---- delete = archive when in use
r = A.delete(B + O + f"/equipment/{EQ1}")
check(r.ok and r.json()["result"] == "archived" and A.get(B + O + f"/equipment/{EQ1}").json()["archived"] == 1, "delete: a device in a set is archived " + r.text[:100])
r = A.delete(B + O + f"/texts/{RT['id']}")
check(r.ok and r.json()["result"] == "archived", "delete: a text block a contract uses is archived")
r = A.delete(B + O + f"/services/{SV1}")
check(r.ok and r.json()["result"] == "archived", "delete: a service with a contract rate is archived")
r = A.delete(B + O + f"/services/{SV2}")
check(r.ok and r.json()["result"] == "deleted" and A.get(B + O + f"/services/{SV2}").status_code == 404, "delete: an unused service is gone")
check(Bo.delete(B + O + f"/services/{SV3}").status_code == 403, "delete: a member cannot")
r = A.get(B + O + "/services")
check([x["id"] for x in r.json()["items"]] == [SV3], "list: archived rows are hidden by default")
check([x["id"] for x in A.get(B + O + "/services", params={"archived": "1"}).json()["items"]] == [SV1, SV3], "list: ?archived=1 shows them")
SV4 = A.post(B + O + "/services", json={"name_de": "Producing", "name_en": "Producing", "category": "Office", "daily_rate": 600}).json()["id"]
A.put(B + O + "/settings", json={"producing_service_id": SV4})
check(A.get(B + O + "/settings").json()["settings"]["producing_service_id"] == SV4, "settings: producing service set")
check(A.delete(B + O + f"/services/{SV4}").json()["result"] == "deleted" and A.get(B + O + "/settings").json()["settings"]["producing_service_id"] is None, "delete: the producing service reference is cleared")
check(A.delete(B + O + f"/services/{SV3}").json()["result"] == "archived" and A.patch(B + O + f"/services/{SV3}", json={"archived": 0}).json()["archived"] == 0, "delete: a service with a contract rate is archived, un-archive by patch")

# ================================================================== export
r = A.get(B + O + "/export")
check(r.ok and r.headers.get("Content-Disposition", "").startswith("attachment") and r.json()["kalmido_office"] == 1, "export: a JSON file " + r.headers.get("Content-Disposition", ""))
EXP = r.json()
check(len(EXP["services"]) == 2 and len(EXP["equipment"]) == 2 and len(EXP["sets"]) == 1 and len(EXP["contracts"]) == 2 and len(EXP["texts"]) == len(TX) + 1 and EXP["settings"]["company"]["name"] == "Studio Nordlicht GmbH", "export: everything is in it")
check(all("org_id" not in x for x in EXP["services"]) and "client_id" in EXP["contracts"][0], "export: rows without org_id")
check(Bo.get(B + O + "/export").ok, "export: a member may export")
r = A.post(B + O + "/import", json=EXP)
check(r.ok and r.json()["counts"]["services"] == {"added": 0, "updated": 0, "skipped": 2} and r.json()["counts"]["settings"] == "skipped", "import: the same file again adds nothing " + r.text[:200])
r = A.post(B + O + "/import", json={"kalmido_office": 1, "services": [{"name_de": "Ton", "name_en": "Sound", "category": "Audio", "daily_rate": 600, "raw_fee": 1}, {"name_de": "Schnitt", "hourly_rate": 150}]})
check(r.ok and r.json()["counts"]["services"] == {"added": 1, "updated": 0, "skipped": 1}, "import: additive by name " + r.text[:200])
check(A.get(B + O + f"/services/{SV3}").json()["hourly_rate"] == 120, "import: existing row untouched without overwrite")
r = A.post(B + O + "/import?overwrite=1", json={"kalmido_office": 1, "services": [{"name_de": "Schnitt", "hourly_rate": 150}]})
check(r.ok and r.json()["counts"]["services"]["updated"] == 1 and A.get(B + O + f"/services/{SV3}").json()["hourly_rate"] == 150, "import: overwrite updates by name")
check(Bo.post(B + O + "/import", json=EXP).status_code == 403, "import: admin only")
check(A.post(B + O + "/import", json={"services": "x"}).status_code == 400 and A.post(B + O + "/import", json=[1]).status_code == 400, "import: bad shapes 400")
r = A.post(B + O + "/import", files={"file": ("x.json", json.dumps({"kalmido_office": 1, "equipment": [{"name": "Stativ", "daily_rate": 20}]}), "application/json")})
check(r.ok and r.json()["counts"]["equipment"]["added"] == 1, "import: multipart file " + r.text[:100])

# ================================================================== mode workspaces: two organisations + a private person (tenant matrix)
restart("-e KALMIDO_INSTANCE_MODE=workspaces")
A, Bo, Ca, Da = sess("alice"), sess("bob"), sess("carol"), sess("dave")
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
# the instance admin administers the first organisation (organisation mode gave that implicitly; no restart in between)
check(A.patch(B + f"/api/admin/orgs/{ORG}", json={"admins": [ALICE]}).ok, "setup: alice is the first organisation's admin")
r1, r2 = A.delete(B + f"/api/orgs/{ORG}/members/{CAROL}"), A.delete(B + f"/api/orgs/{ORG}/members/{DAVE}")
check(r1.ok and r2.ok, f"setup: carol only in Beta, dave in no organisation {r1.status_code} {r2.status_code} {r1.text[:80]}")
r = Da.get(B + O + "/settings")
check(r.status_code == 400 and "organisation" in r.text.lower(), "tenant: a private person gets 400 with the hint " + r.text[:120])
check(Da.get(B + O + "/services").status_code == 400 and Da.post(B + O + "/services", json={"name_de": "x"}).status_code == 400, "tenant: ... on every route")
r = Ca.get(B + O + "/settings")
check(r.ok and r.json()["org_id"] == BETA and r.json()["role"] == "admin" and r.json()["settings"]["company"]["name"] == "", "tenant: carol works in Beta with fresh settings " + r.text[:200])
check(Ca.get(B + O + "/services").json()["items"] == [], "tenant: Beta has no services of the first organisation")
check(len(Ca.get(B + O + "/texts").json()["items"]) == len(TX), "tenant: Beta got its own seeded catalogue")
for path in (f"/services/{SV3}", f"/equipment/{EQ2}", f"/sets/{SET1}", f"/texts/{TB}", f"/contracts/{CT1}"):
    check(Ca.get(B + O + path).status_code == 404, "tenant: foreign row " + path + " -> 404")
    check(Ca.patch(B + O + path, json={"name": "hijack", "name_de": "hijack", "text_de": "hijack"}).status_code == 404, "tenant: foreign patch " + path + " -> 404")
    check(Ca.delete(B + O + path).status_code == 404, "tenant: foreign delete " + path + " -> 404")
check(A.get(B + O + f"/services/{SV3}").json()["name_de"] == "Schnitt", "tenant: nothing was changed")
check(Ca.post(B + O + "/sets", json={"name": "x", "items": [{"equipment_id": EQ2, "qty": 1}]}).status_code == 400, "tenant: a set cannot reference a foreign device")
check(Ca.post(B + O + "/contracts", json={"name": "x", "rights_time_id": TB}).status_code == 400 and Ca.post(B + O + "/contracts", json={"name": "x", "rates": {str(SV3): 5}}).status_code == 400
      and Ca.post(B + O + "/contracts", json={"name": "x", "client_id": CLIENT}).status_code == 400, "tenant: a contract cannot reference foreign texts / services / clients")
check(Ca.put(B + O + "/settings", json={"producing_service_id": SV3}).status_code == 400, "tenant: settings cannot point at a foreign service")
# alice in both organisations: the workspace switch decides
r = A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [CAROL, ALICE], "admins": [CAROL]})
check(r.ok, "setup: alice also a member of Beta " + r.text[:120])
r = A.get(B + O + "/settings")
check(r.status_code == 400, "tenant: in several organisations with the switch on 'all' -> 400 with the hint " + str(r.status_code))
A.patch(B + "/api/settings", json={"workspace": f"org:{BETA}"})
r = A.get(B + O + "/settings")
check(r.ok and r.json()["org_id"] == BETA and r.json()["role"] == "member", "tenant: the workspace switch picks Beta; alice is a member there")
check(A.post(B + O + "/services", json={"name_de": "x"}).status_code == 403, "tenant: ... and cannot write Beta's master data")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.get(B + O + "/settings").json()["org_id"] == ORG and A.get(B + O + f"/services/{SV3}").ok, "tenant: back in the first organisation")
# import the export into Beta: ids are remapped
r = Ca.post(B + O + "/import", json=EXP)
check(r.ok and r.json()["counts"]["sets"]["added"] == 1 and r.json()["counts"]["contracts"]["added"] == 2 and r.json()["counts"]["settings"] == "updated", "import into Beta: " + r.text[:200])
bs = {x["name_de"]: x for x in Ca.get(B + O + "/services", params={"archived": "1"}).json()["items"]}
be = {x["name"]: x for x in Ca.get(B + O + "/equipment", params={"archived": "1"}).json()["items"]}
bset = Ca.get(B + O + "/sets").json()["items"][0]
check(bset["items"][0]["equipment_id"] == be["Kamera-Set A"]["id"] and bset["items"][1]["equipment_id"] == be["Licht-Koffer"]["id"] and all(it["equipment_id"] not in (EQ1, EQ2) for it in bset["items"]), "import into Beta: set items point at Beta's devices " + json.dumps(bset["items"]))
bct = next(x for x in Ca.get(B + O + "/contracts").json()["items"] if x["name"] == "Rahmenvertrag Beispielkunde")
btx = {t["id"]: t for t in Ca.get(B + O + "/texts", params={"archived": "1"}).json()["items"]}
check(bct["rates"] == {str(bs["Kamera"]["id"]): 900, str(bs["Schnitt"]["id"]): 100} and bct["client_id"] is None, "import into Beta: contract rates remapped, no client " + json.dumps(bct["rates"]))
check(bct["rights_time_id"] in btx and btx[bct["rights_time_id"]]["text_de"] == "unbegrenzt" and bct["rights_time_id"] != RT["id"], "import into Beta: the rights point at Beta's text blocks")
cs = Ca.get(B + O + "/settings").json()["settings"]
check(cs["company"]["name"] == "Studio Nordlicht GmbH" and cs["rights_default"]["territory_id"] in btx and btx[cs["rights_default"]["territory_id"]]["key"] == "world_ex_music", "import into Beta: settings + default rights remapped")
check(A.get(B + O + f"/sets/{SET1}").json()["items"][0]["equipment_id"] == EQ1, "import into Beta: the first organisation is untouched")
# tenant-matrix: office

# ================================================================== backup + restore keep the office tables; rollback-safe layout
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, "backup: back up now " + r.text[:100])
items = wait_for(lambda: [x for x in A.get(B + "/api/admin/backups").json().get("items", []) if x["kind"] == "manual"], 30)
name = items[0]["name"] if items else ""
r = A.post(B + f"/api/admin/backups/{name}/verify", json={})
check(r.ok and r.json().get("ok"), "backup: verifies " + r.text[:200])
n_s, n_t = dbx("SELECT COUNT(*) FROM office_services")[0][0], dbx("SELECT COUNT(*) FROM office_texts")[0][0]
dbx("DELETE FROM office_services", write=True)
dbx("DELETE FROM office_texts", write=True)
dbx("DELETE FROM office_settings", write=True)
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": name})
check(r.ok and r.json().get("ok"), "backup: restore " + r.text[:200])
check(wait_for(lambda: dbx("SELECT COUNT(*) FROM office_services")[0][0] == n_s, 10) and dbx("SELECT COUNT(*) FROM office_texts")[0][0] == n_t and dbx("SELECT COUNT(*) FROM office_settings")[0][0] == 2, "backup: the office tables are back after the restore")
A = sess("alice")
check(A.get(B + O + f"/services/{SV3}").ok and A.get(B + O + "/settings").json()["settings"]["company"]["name"] == "Studio Nordlicht GmbH", "backup: ... and readable through the API")
# organisation delete cascades (ON DELETE CASCADE on every office table)
r = A.delete(B + f"/api/admin/orgs/{BETA}")
check(r.ok or r.status_code == 204, "cascade: delete Beta " + str(r.status_code) + r.text[:100])
check(dbx("SELECT COUNT(*) FROM office_services WHERE org_id=?", (BETA,))[0][0] == 0 and dbx("SELECT COUNT(*) FROM office_settings WHERE org_id=?", (BETA,))[0][0] == 0
      and dbx("SELECT COUNT(*) FROM office_texts WHERE org_id=?", (BETA,))[0][0] == 0, "cascade: Beta's office rows are gone, the first organisation's stay " + str(dbx("SELECT COUNT(*) FROM office_services")[0][0]))

print(f"p2361_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
