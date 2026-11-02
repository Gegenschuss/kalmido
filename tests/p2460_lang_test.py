#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.460.0 API tests (#3767): own office texts per language and a language per client, once in the personal office of a person
without an organisation (freelancer fixture; freelancer-matrix: office) and once in an organisation's office. Invented
companies and names only.
 - services / equipment / crew / text blocks / contracts keep nl, fr, es, it in trans; empty ones and unknown languages fall away,
   a wrong shape is 400; the search finds the words, never the JSON's field names
 - a French document takes the French text; a language without its text takes the English one and says so (lang_gaps, lang_notes),
   the German one without English; German and English documents work as before
 - a client's doc_lang: new documents take it, choosing the client on a draft swaps the texts, a language sent along wins, an
   unknown language is 400
 - the office's own closings per language, the terms PDF in French
usage: p2460_lang_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402
import requests  # noqa: E402

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
A.patch(B + "/api/settings", json={"workspace": f"org:{r.json()['id']}"})
FID, Fr = freelancer(B, A)


def run(S, who):
    def ok(cond, what):
        check(cond, f"{who}: {what}")

    r = S.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht"}, "lang": "de", "currency": "EUR", "invoice_closing_en": "Own closing",
                                         "invoice_closing_fr": "Clôture propre"})
    ok(r.ok, "settings " + r.text[:200])

    def post(kind, body):
        r = S.post(B + f"{O}/{kind}", json=body)
        assert r.status_code in (200, 201), (kind, r.text)
        return r.json()

    sv = post("services", {"name_de": "Kamera", "name_en": "Camera", "unit": "day", "daily_rate": 100, "trans": {"fr": {"name": "Caméra", "x": "weg"}, "nl": {"name": "  "}, "xx": {"name": "Nein"}}})
    ok(sv["trans"] == {"fr": {"name": "Caméra"}}, f"a service keeps fr only ({sv.get('trans')})")
    ok(S.post(B + f"{O}/services", json={"name_de": "X", "trans": "fr"}).status_code == 400, "trans must be an object")
    ok(post("services", {"name_de": "Alt", "trans": "{}"})["trans"] == {}, "the raw column of an older export is taken")
    ok(S.post(B + f"{O}/services", json={"name_de": "X", "trans": {"fr": "x"}}).status_code == 400, "a language must be an object")
    only_de = post("services", {"name_de": "Nur Deutsch", "unit": "day", "daily_rate": 10})
    q = S.get(B + f"{O}/services", params={"q": "Caméra"}).json()
    q = q if isinstance(q, list) else next(v for v in q.values() if isinstance(v, list))
    ok([x["id"] for x in q] == [sv["id"]], f"the search finds the translation ({q})")
    q = S.get(B + f"{O}/services", params={"q": "name"}).json()
    q = q if isinstance(q, list) else next(v for v in q.values() if isinstance(v, list))
    ok(not [x for x in q if x["id"] == sv["id"]], "the search never matches the JSON's field names")
    eq = post("equipment", {"name": "Stativ", "name_en": "Tripod", "trans": {"es": {"name": "Trípode"}}})
    ok(eq["trans"] == {"es": {"name": "Trípode"}}, "equipment keeps es")
    crew = post("crew", {"name_de": "Ton", "name_en": "Sound", "rate_day": 300, "trans": {"it": {"name": "Fonico"}}})
    ok(crew["trans"] == {"it": {"name": "Fonico"}}, "a crew role keeps it")
    role = post("roles", {"name_de": "Schnitt", "trans": {"fr": {"name": "Montage"}}})
    ok(role["trans"] == {"fr": {"name": "Montage"}}, "a freelancer role keeps fr")
    ct = post("contracts", {"name": "Rahmen", "closing_de": "Gruß", "closing_en": "Regards", "trans": {"fr": {"closing": "Salutations", "rights_note": "Note"}}})
    ok(ct["trans"]["fr"]["closing"] == "Salutations", "a contract keeps both fields")
    up = S.patch(B + f"{O}/services/{sv['id']}", json={"trans": {"fr": {"name": "Caméra"}, "it": {"name": "Telecamera"}}})
    ok(up.ok and up.json()["trans"]["it"]["name"] == "Telecamera", "a saved translation changes " + up.text[:160])

    def client(**kw):
        r = S.post(B + "/api/clients", json=dict({"street": "Rue 5", "zip": "75001", "city": "Paris", "country": "FR"}, **kw))
        assert r.status_code == 201, r.text
        return r.json()

    ok(S.post(B + "/api/clients", json={"name": "Falsch", "doc_lang": "xx"}).status_code == 400, "an unknown client language is 400")
    fr = client(name="Lumière SARL", doc_lang="fr")
    ok(S.get(B + f"/api/clients/{fr['id']}").json()["billing"]["doc_lang"] == "fr", "the client keeps its language")
    plain = client(name="Ohne Sprache")

    items = [{"kind": "service", "service_id": sv["id"], "qty": 1}, {"kind": "service", "service_id": only_de["id"], "qty": 1}]
    d = S.post(B + D, json={"kind": "offer", "client_id": fr["id"], "items": items}).json()
    ok(d.get("lang") == "fr", f"a new document takes the client's language ({d.get('lang')})")
    r = S.patch(B + f"{D}/{d['id']}", json={"items": items})
    d = S.get(B + f"{D}/{d['id']}").json()
    titles = [x["title"] for x in d["items"]]
    ok("Caméra" in titles, f"the French name on the position ({titles})")
    ok("Nur Deutsch" in titles, "without the language and without English: the German name")
    ok(any("Nur Deutsch" in x and "German used" in x for x in d.get("lang_gaps") or []), f"the document says so ({d.get('lang_gaps')})")
    ok(not any("Kamera" in x for x in d.get("lang_gaps") or []), "no note for the name that exists")

    r = S.patch(B + f"{D}/{d['id']}", json={"lang": "nl"})
    j = r.json()
    ok("Camera" in [x["title"] for x in j["items"]], "no Dutch name: English on the position")
    ok(any("Kamera" in x and "English used" in x for x in j.get("lang_notes") or []), f"the language switch says so ({j.get('lang_notes')})")
    r = S.patch(B + f"{D}/{d['id']}", json={"lang": "de"})
    ok("Kamera" in [x["title"] for x in r.json()["items"]] and not r.json().get("lang_gaps"), "German as before")

    e = S.post(B + D, json={"kind": "offer", "client_id": fr["id"], "lang": "en"}).json()
    ok(e.get("lang") == "en", "a language sent along wins over the client's")
    r = S.patch(B + f"{D}/{e['id']}", json={"client_id": str(fr["id"])})
    ok(r.json().get("lang") == "en", "the same client sent as text is no new client: the language chosen by hand stays")

    dr = S.post(B + D, json={"kind": "invoice"}).json()
    ok(dr.get("lang") == "de", "no client: the office's language")
    r = S.patch(B + f"{D}/{dr['id']}", json={"client_id": fr["id"], "recipient_from_client": True})
    ok(r.json().get("lang") == "fr" and "Clôture propre" in (r.json().get("closing") or ""), f"choosing the client swaps language and closing ({r.json().get('lang')}, {r.json().get('closing')!r})")
    r = S.patch(B + f"{D}/{dr['id']}", json={"lang": "it"})
    ok(r.json().get("closing") == "Own closing", "no own Italian closing: the English one")
    ok(any("English used" in x for x in r.json().get("lang_notes") or []), f"and it says so ({r.json().get('lang_notes')})")
    r2 = S.post(B + D, json={"kind": "invoice", "client_id": plain["id"]}).json()
    ok(r2.get("lang") == "de", "a client without a language: the office's")

    r = S.post(B + O + "/terms/fr", files={"file": ("cgv.pdf", PDF, "application/pdf")})
    ok(r.ok, "terms in French " + r.text[:160])
    ok("fr" in S.get(B + O + "/terms").json()["terms"], "the French terms are listed")


run(Fr, "freelancer")
run(A, "organisation")
print(f"p2460_lang: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
