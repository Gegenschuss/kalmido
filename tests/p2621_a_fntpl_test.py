#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.621.0 A (#4600) the archive import of old PDFs: file name templates instead of only the fixed names.
Invented companies and names only.
freelancer-matrix: office
tenant-matrix: office
 - GET /api/office/legacy/archive/templates lists the templates; the standard is chosen until another one is kept
 - the standard (no template sent, or template "standard") reads the names of before exactly as before
 - every fixed template reads its example (kind, number, client, date, sure); an own template from the fixed blocks + one
   separator reads its example; a name that does not fit the template is "not sure"
 - an unknown template name, a block twice, an unknown block or separator = 400, the kept choice stays
 - the choice is kept per office area: the organisation's choice is not the person's own office, nor another
   organisation's; a member (no admin) 403
 - the organisation's admin and a person without an organisation (personal office) alike
usage: p2621_a_fntpl_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402

L = "/api/office/legacy"
TPL = "/api/office/legacy/archive/templates"  # the route of the templates (tenant_coverage_test.py looks for its path)
FEAT = "cal,comments,collab,clients,office,docs,files,contacts"

kt.fresh(prefix="P2621A")
assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
for u in ("bob", "carol"):
    assert A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
Bo, Ca = sess("bob"), sess("carol")
CID = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta Example", "admin_id": CID}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{o}"})
check(A.put(B + "/api/office/settings", json={"lang": "de", "currency": "EUR"}).ok, "setup: office settings")
_, Fr = freelancer(B, A)

OLD = ["0815_Nordwind_KV02_311225_AB.pdf", "657_Nordwind_2026-03-11_R.pdf", "12_Kunde_Imagefilm__2026-01-02_R.pdf",
       "12_Kunde_Titel_entwurf_R.pdf", "Muster_Beteiligung_KV04_2026-02-01.pdf", "irgendwas.pdf"]


def parse(s, names, **tpl):
    r = s.post(B + L + "/archive/parse", json={"names": names, **tpl})
    return r.status_code, (r.json() if r.ok else {})


def kept(s):
    r = s.get(B + TPL)
    return r.json().get("current") if r.ok else f"http {r.status_code}"


for who, s in (("org", A), ("freelancer", Fr)):
    p = f"{who}: "
    nw = s.post(B + "/api/clients", json={"name": f"Nordwind {who} GmbH", "city": "Andersstadt", "country": "DE"}).json()["id"]
    r = s.get(B + TPL)
    j = r.json() if r.ok else {}
    check(r.ok and j.get("current") == "standard" and {t["name"] for t in j.get("templates") or []}
          >= {"standard", "date_number_client", "number_client_date", "client_number", "custom"}
          and "date" in (j.get("fields") or []) and "_" in (j.get("seps") or []), p + f"the templates, the standard chosen {r.status_code} {j}")

    # the standard: without a template and with "standard" the same reading of the old names
    st0, j0 = parse(s, OLD)
    st1, j1 = parse(s, OLD, template="standard")
    check(st0 == 200 and st1 == 200 and j0.get("items") == j1.get("items") and len(j0.get("items") or []) == len(OLD),
          p + f"the standard reads the old names as without a template {st0} {st1}")
    it = j0.get("items") or [{}] * len(OLD)
    check(it[0].get("kind") == "offer" and it[0].get("project_no") == "0815" and it[0].get("client_name") == "Nordwind"
          and it[0].get("number") == "0815_Nordwind_KV02_311225_AB", p + f"standard: the quotation as before {it[0]}")
    check(it[1].get("kind") == "invoice" and it[1].get("sure") is True and it[1].get("date") == "2026-03-11" and it[1].get("project_no") == "657",
          p + f"standard: the invoice as before {it[1]}")
    check(it[5].get("kind") == "invoice" and it[5].get("sure") is False and it[5].get("number") == "irgendwas", p + f"standard: a free name as before {it[5]}")

    # every fixed template reads its example
    for tpl, name, want in (("date_number_client", f"2026-03-11_RE-2026-004_Nordwind {who}.pdf",
                             {"kind": "invoice", "number": "RE-2026-004", "client_id": nw, "date": "2026-03-11", "sure": True}),
                            ("number_client_date", f"KV12_Nordwind {who}_11.03.2026.pdf",
                             {"kind": "offer", "number": "KV12", "client_id": nw, "date": "2026-03-11", "sure": True}),
                            ("client_number", f"Nordwind {who}_R-104.pdf",
                             {"kind": "invoice", "number": "R-104", "client_id": nw, "date": "", "sure": True})):
        st, j = parse(s, [name, "nichts_passt_hier.pdf"], template=tpl)
        x, y = (j.get("items") or [{}, {}])[:2]
        check(st == 200 and all(x.get(k) == v for k, v in want.items()) and (j.get("template") or {}).get("name") == tpl,
              p + f"template {tpl} reads its example {st} {x}")
        check(tpl == "client_number" or y.get("sure") is False, p + f"template {tpl}: a name that does not fit is not sure {y}")
        check(kept(s) == tpl, p + f"template {tpl} kept for the office area")

    # an own template from the fixed blocks
    st, j = parse(s, [f"Angebot-0815-Nordwind {who}-2026-01-05.pdf"], template="custom", fields=["kind", "number", "client", "date"], sep="-")
    x = (j.get("items") or [{}])[0]
    check(st == 200 and x.get("kind") == "offer" and x.get("number") == "0815" and x.get("client_id") == nw and x.get("date") == "2026-01-05"
          and x.get("sure") is True, p + f"own template kind-number-client-date reads its example {st} {x}")
    j = s.get(B + TPL).json()
    check(j.get("current") == "custom" and j.get("custom") == {"fields": ["kind", "number", "client", "date"], "sep": "-"}, p + f"own template kept {j}")

    # wrong input: 400, the kept choice stays
    for bad in ({"template": "nope"}, {"template": 7}, {"template": "custom", "fields": ["date", "date"]},
                {"template": "custom", "fields": ["number", "regex"]}, {"template": "custom", "fields": ["number"], "sep": "|"},
                {"template": "custom", "fields": []}, {"template": "custom", "fields": ["skip"]}, {"template": "custom", "fields": "date"}):
        st, _ = parse(s, ["a.pdf"], **bad)
        check(st == 400, p + f"wrong template {bad} = 400, got {st}")
    check(kept(s) == "custom", p + "after the wrong ones the own template is still kept")
    # without a template the kept one reads; switching to a fixed one keeps the own blocks for later
    st, j = parse(s, [f"Rechnung-77-Nordwind {who}-2026-02-03.pdf"])
    x = (j.get("items") or [{}])[0]
    check(st == 200 and x.get("kind") == "invoice" and x.get("number") == "77" and x.get("date") == "2026-02-03", p + f"no template sent: the kept one reads {x}")
    parse(s, [], template="standard")
    j = s.get(B + TPL).json()
    check(j.get("current") == "standard" and (j.get("custom") or {}).get("sep") == "-", p + f"back to the standard, the own blocks stay {j}")

# per office area: the organisation's choice is not another one's
check(parse(A, [], template="client_number")[0] == 200 and kept(A) == "client_number", "org: client_number kept")
check(kept(Fr) == "standard", "freelancer: the organisation's choice does not reach the personal office")
check(kept(Ca) == "standard", "tenant-matrix: office -- another organisation keeps its own template (standard)")
check(parse(Ca, [], template="date_number_client")[0] == 200 and kept(A) == "client_number",
      "tenant-matrix: office -- another organisation's choice leaves this one's alone")
A.patch(B + "/api/settings", json={"workspace": "private"})
check(kept(A) == "standard", "the admin's own Private office keeps its own template")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(kept(A) == "client_number", "back in the organisation: its choice")
check(Bo.get(B + TPL).status_code == 403 and parse(Bo, [], template="standard")[0] == 403 and kept(A) == "client_number",
      "a member (no admin): 403, nothing kept")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
