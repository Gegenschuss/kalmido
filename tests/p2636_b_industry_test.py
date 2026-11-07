#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.636.0 B (#4952): the second built-in industry pack "Agency & services" (code agency) next to Film & Video.
Invented names only.
 - the choices of GET /api/industry name both packs; an organisation's admin chooses Agency & services (PUT /api/industry),
   a member reads it and may not choose (403)
 - its defaults are there: the office offers the pack's calculation (GET /api/office/settings industry: project days,
   services, tools and equipment, the services as suggested functions), not the film one; the film-only things stay off:
   the sample is the neutral website relaunch, not the image film
 - the archive import's file name template follows the industry: Agency & services starts with date_number_client (GET
   .../archive/templates current + industry; a name of that form is read without sending a template), a template the
   admin keeps (also "standard") outranks it; Film & Video keeps the standard
 - a person without an organisation (freelancer) alike for her own area
freelancer-matrix: industry (frida chooses Agency & services for her own area: the pack, the template, the neutral sample)
tenant-matrix: industry (Acme's admin chooses, Acme's member 403, Beta stays without)
usage: p2636_b_industry_test.py <datadir>"""
import sys

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

A = kt.setup()
FEATS = "cal,timeline,matrix,collab,time,progress,deps,fields,office,clients,docs,files,contacts"
NEUTRAL, NCHECK = "Example: Website relaunch for Example Ltd", "Example: Launch checklist"
TPL = "/api/office/legacy/archive/templates"
PARSE = "/api/office/legacy/archive/parse"


def ind(s):
    return s.get(B + "/api/state").json().get("industry") or {}


def sample_names(s):
    sm = s.get(B + "/api/state").json().get("sample") or {}
    return sorted(x["name"] for x in sm.get("lists", []))


def packs(s):
    """The calculation packs the office offers (GET /api/office/settings industry)."""
    r = s.get(B + "/api/office/settings")
    return (r.json().get("industry") or []) if r.ok else None


def tpl(s):
    r = s.get(B + TPL)
    return r.json() if r.ok else {"http": r.status_code}


def agency_checks(s, who, client):
    """Agency & services chosen for s's area: its pack, its file name template, the neutral sample."""
    p = f"{who}: "
    ps = packs(s)
    code = [x.get("code") for x in ps or []]
    pk = (ps or [{}])[0]
    check(code == ["agency"], p + f"the office offers the agency calculation only {code}")
    en = (pk.get("labels") or {}).get("en") or {}
    roles = [r.get("en") for r in pk.get("roles") or []]
    check(en.get("shoot_days") == "Project days" and en.get("staff") == "Services" and en.get("set") == "Tools and equipment",
          p + f"the pack's own words {en.get('shoot_days')} / {en.get('staff')} / {en.get('set')}")
    check("Project lead" in roles and "Design" in roles and "Director" not in roles, p + f"services as suggested functions {roles}")
    check("meals" not in (pk.get("blocks") or []) and "staff" in pk.get("blocks", []), p + f"blocks {pk.get('blocks')}")
    t = tpl(s)
    check(t.get("current") == "date_number_client" and t.get("industry") == "date_number_client",
          p + f"the archive import starts with the industry's file name template {t}")
    r = s.post(B + PARSE, json={"names": [f"2026-03-11_RE-2026-004_{client}.pdf"]})
    x = (r.json().get("items") or [{}])[0] if r.ok else {}
    check(r.ok and x.get("kind") == "invoice" and x.get("number") == "RE-2026-004" and x.get("date") == "2026-03-11" and x.get("sure") is True
          and (r.json().get("template") or {}).get("name") == "date_number_client", p + f"a name of that form is read without a template {r.status_code} {x}")
    check(s.post(B + "/api/sample", json={}).ok and sample_names(s) == sorted([NEUTRAL, NCHECK]),
          p + "the neutral sample, not the image film " + str(sample_names(s)))
    check(s.delete(B + "/api/sample").ok, p + "sample removed")


# ================================================================== organisations (tenant-matrix: industry)
mk = lambda name, **kw: A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": kt.PASSWORD, "email": f"{name}@example.com", **kw}).json()["id"]  # noqa: E731
OL = mk("olive", orgs=[])
OID = A.post(B + "/api/admin/orgs", json={"name": "Acme", "admin_id": OL}).json()["id"]
BE = mk("bea", orgs=[])
BID = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": BE}).json()["id"]
mk("tom", orgs=[OID])
Ol, Tm, Be = sess("olive"), sess("tom"), sess("bea")
for s, o in ((Ol, OID), (Tm, OID), (Be, BID)):
    s.patch(B + "/api/settings", json={"features": FEATS, "tour": "done", "lang": "en", "workspace": f"org:{o}"})
check(Ol.put(B + "/api/office/settings", json={"lang": "de", "currency": "EUR"}).ok, "Acme: office settings")
i0 = ind(Ol)
ch = {c["code"]: c["name"] for c in i0.get("choices") or []}
check(i0.get("code") == "" and i0.get("can_set") is True and ch == {"agency": "Agency & services", "film": "Film & Video"},
      "Acme's admin: no industry yet, both packs to choose " + str(i0))
check(tpl(Ol).get("current") == "standard", "no industry: the standard file names " + str(tpl(Ol)))
r = Tm.put(B + "/api/industry", json={"industry": "agency"})
check(r.status_code == 403, f"member: PUT 403 ({r.status_code})")
r = Ol.put(B + "/api/industry", json={"industry": "agency"})
check(r.ok and r.json()["industry"]["code"] == "agency", "Acme's admin chooses Agency & services " + r.text[:160])
check(Ol.get(B + "/api/office/settings").json()["settings"]["industry_packs"] == ["agency"], "one truth: industry_packs")
check(ind(Tm).get("code") == "agency" and ind(Tm).get("can_set") is False, "the member reads the organisation's industry")
Ol.post(B + "/api/clients", json={"name": "Nordwind Acme GmbH", "city": "Andersstadt", "country": "DE"})
agency_checks(Ol, "Acme's admin", "Nordwind Acme GmbH")
check(ind(Be).get("code") == "" and packs(Be) == [] and tpl(Be).get("current") == "standard", "Beta stays without (pack, template)")
# a template the admin keeps outranks the industry's (also the standard)
r = Ol.post(B + PARSE, json={"names": ["x.pdf"], "template": "standard"})
check(r.ok and tpl(Ol).get("current") == "standard" and tpl(Ol).get("industry") == "date_number_client", "the kept standard outranks the industry " + str(tpl(Ol)))
# Film & Video: unchanged (the standard names, the film calculation)
r = Ol.put(B + "/api/industry", json={"industry": "film"})
check(r.ok and [x.get("code") for x in packs(Ol) or []] == ["film"] and tpl(Ol).get("industry") == "standard",
      "Film & Video: the film pack only, its template the standard " + str(tpl(Ol)))
r = Ol.put(B + "/api/industry", json={"industry": "agency"})
check(r.ok and Ol.get(B + "/api/office/settings").json()["settings"]["industry_packs"] == ["agency"], "back to Agency & services: film off again")

# ================================================================== a person without organisation (freelancer-matrix: industry)
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEATS, "tour": "done", "lang": "en"})
check(Fr.put(B + "/api/office/settings", json={"lang": "de", "currency": "EUR"}).ok, "frida: office settings")
check(tpl(Fr).get("current") == "standard", "frida: no industry, the standard file names " + str(tpl(Fr)))
r = Fr.put(B + "/api/industry", json={"industry": "agency"})
check(r.ok and r.json()["industry"]["code"] == "agency", "frida: Agency & services for her own area " + r.text[:160])
Fr.post(B + "/api/clients", json={"name": "Nordwind Frida GmbH", "city": "Andersstadt", "country": "DE"})
agency_checks(Fr, "frida", "Nordwind Frida GmbH")
check(ind(Ol).get("code") == "agency" and Fr.put(B + "/api/industry", json={"industry": ""}).ok and tpl(Fr).get("current") == "standard",
      "frida: none again = the standard; Acme's choice untouched")

sys.exit(kt.done("p2636_b_industry"))
