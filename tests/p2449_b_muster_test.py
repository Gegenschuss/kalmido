#!/usr/bin/env python3
"""2.449.0 B (#3768): the samples and the film pack in every document language, in a personal office (own admin).
freelancer-matrix: office
 - all 13 document samples and 4 letter blocks in fr / es / it / nl: an own text, no English fallback, the same variables and
   optional parts as the English sample; taking one over makes a template in that language
 - non-disclosure agreement, data processing agreement, privacy information and consent say "machine translated, check
   before use" in their text and to the picker; German and English samples do not
 - a small business gets the gross total in the translated samples as well
 - the film pack in fr: the sheet's words and a crew role of the pack in French, in a language the pack lacks nothing breaks
 - the procedure documentation: only with the German pack; a person on another pack gets 404 and no button flag, an area
   with saved versions keeps them
 - the fixed costs template reads back in French; the account export names what it leaves out in the person's language
usage: p2449_b_muster_test.py <datadir>"""
# kalmido-suite: fresh
import io
import json
import re
import sys
import time
import zipfile

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup, su_get

fresh(prefix="P2449B")
A = setup()
_, F = freelancer(B, A)
_, G = freelancer(B, A, "fiona")
LANGS = ("fr", "es", "it", "nl")
MT = {"fr": "Traduction automatique, à vérifier avant utilisation", "es": "Traducción automática, revisar antes de usar",
      "it": "Traduzione automatica, verificare prima dell'uso", "nl": "Machinaal vertaald, vóór gebruik controleren"}
LEGAL = ("nda", "privacy_dpa", "privacy_info", "privacy_consent")
DT = "/api/office/doc-templates"
BL = "/api/office/letter-blocks"
VARS = re.compile(r"\{\{[a-z.]+\}\}")


def starters(path, lg):
    r = F.get(B + path + "/starters", params={"lang": lg})
    assert r.ok, r.text
    return {x["key"]: x for x in r.json()["starters"]}


# ---------------------------------------------------------------- samples
EN, BEN = starters(DT, "en"), starters(BL, "en")
check(len(EN) == 13 and len(BEN) == 4, f"13 document samples, 4 letter blocks {len(EN)} {len(BEN)}")
for lg in LANGS:
    S, BK = starters(DT, lg), starters(BL, lg)
    for k, e in EN.items():
        s = S[k]
        check(s["lang"] == lg and s["name"] != e["name"], f"{lg}/{k}: own name {s['name']}")
        check(s["body"] != e["body"] and "Dear Sir" not in s["body"] and "Kind regards" not in s["body"], f"{lg}/{k}: no English text")
        check(sorted(VARS.findall(s["body"])) == sorted(VARS.findall(e["body"])), f"{lg}/{k}: the same variables")
        check(s["body"].count("[[") == e["body"].count("[[") == e["body"].count("]]") == s["body"].count("]]"), f"{lg}/{k}: the same optional parts")
        check(s["body"].split("\n")[0].startswith("# "), f"{lg}/{k}: starts with its heading")
        check(bool(s["machine"]) == (k in LEGAL) and (MT[lg] in s["body"]) == (k in LEGAL), f"{lg}/{k}: the hint only on the four legal samples")
    for k, e in BEN.items():
        check(BK[k]["name"] != e["name"] and BK[k]["body"] != e["body"], f"{lg}/{k}: letter block in its language")
        check(BK[k]["body"].count("[") == e["body"].count("["), f"{lg}/{k}: the same placeholders")
DE = starters(DT, "de")
check(not any(x["machine"] for x in list(DE.values()) + list(EN.values())), "German and English samples carry no hint")
check("Sehr geehrte" in DE["letter"]["body"] and "Dear Sir" in EN["letter"]["body"], "de / en as before")
r = F.post(B + DT, json={"starter": "nda", "lang": "fr"})
check(r.ok and r.json()["lang"] == "fr" and r.json()["name"] == "Accord de confidentialité" and MT["fr"] in r.json()["body"], "take over: the French template " + r.text[:200])
r = F.post(B + DT, json={"starter": "dunning", "lang": "nl"})
check(r.ok and r.json()["name"] == "Aanmaning", "take over: a letter sample " + r.text[:200])
r = F.post(B + BL, json={"starter": "objection", "lang": "es"})
check(r.ok and r.json()["name"] == "Recurso", "take over: a letter block " + r.text[:200])
check("hors TVA" in starters(DT, "fr")["contract"]["body"], "net plus VAT in French")
check(F.put(B + "/api/office/settings", json={"small_business": True}).ok, "small business on")
for lg, w in (("fr", "hors TVA"), ("es", "más IVA"), ("it", "più IVA"), ("nl", "excl. btw")):
    b = starters(DT, lg)["confirmation"]["body"]
    check(w not in b and "{{offer.gross}}" in b, f"{lg}: a small business gets the total")
check(F.put(B + "/api/office/settings", json={"small_business": False}).ok, "small business off")

# ---------------------------------------------------------------- film pack
check(F.put(B + "/api/office/settings", json={"industry_packs": ["film"]}).ok, "film pack on")
D = F.post(B + "/api/office/docs", json={}).json()["id"]
r = F.patch(B + f"/api/office/docs/{D}", json={"lang": "fr"})
check(r.ok, "the document in French " + r.text[:200])
r = F.post(B + f"/api/office/docs/{D}/parts", json={"kind": "shoot", "title": "Tournage"})
check(r.ok, "shoot part " + r.text[:200])
d = F.get(B + f"/api/office/docs/{D}").json()
P = next(p for p in d["parts"] if p["kind"] == "shoot")
r = F.patch(B + f"/api/office/docs/{D}/parts/{P['id']}", json={"sheet": {**P["sheet"], "staff": [
    {"name": "Kamera", "name_en": "Camera", "rate": 100, "qty": 1}, {"name": "Eigene Rolle", "name_en": "Own role", "rate": 100, "qty": 1}]}})
check(r.ok, "staff " + r.text[:200])
P = next(p for p in F.get(B + f"/api/office/docs/{D}").json()["parts"] if p["kind"] == "shoot")
L = P["calc"]["labels"]
check(L.get("title") == "Calcul des coûts de tournage" and L.get("staff") == "Équipe", f"the sheet's words in French {L.get('title')}")
names = [x["label"] for x in P["calc"]["lines"] if x["block"] == "staff"]
check(names == ["Caméra", "Own role"], f"a role of the pack in French, an own one as it is {names}")

# ---------------------------------------------------------------- procedure documentation
check(F.get(B + "/api/office/settings").json().get("procdoc") is True, "German pack: offered")
check(F.get(B + "/api/office/procdoc").ok, "German pack: it opens")
r = F.put(B + "/api/office/procdoc", json={"own": {}, "lang": "de"})
check(r.ok, "a saved version " + r.text[:200])
check(G.put(B + "/api/office/settings", json={"pack": "XX"}).ok, "other person: base pack")
check(G.get(B + "/api/office/settings").json().get("procdoc") is False, "base pack: not offered")
for u in ("/api/office/procdoc", "/api/office/procdoc/versions", "/api/office/procdoc.md"):
    check(G.get(B + u).status_code == 404, f"base pack: {u} 404")
check(F.put(B + "/api/office/settings", json={"pack": "XX"}).ok, "the person with a version changes the pack")
check(F.get(B + "/api/office/settings").json().get("procdoc") is True and len(F.get(B + "/api/office/procdoc/versions").json()["items"]) == 1, "saved versions stay reachable")
check(F.put(B + "/api/office/settings", json={"pack": "DE"}).ok, "back to the German pack")

# ---------------------------------------------------------------- fixed costs template, export manifest
check(G.patch(B + "/api/settings", json={"lang": "fr"}).ok, "French app")
t = G.get(B + "/api/office/fixed-costs/import/template")
check(t.ok and b"Montant (net)" in zipfile.ZipFile(io.BytesIO(t.content)).read("xl/worksheets/sheet1.xml"), "the template's header in French")
r = G.post(B + "/api/office/fixed-costs/import/preview", files={"file": ("t.xlsx", t.content)})
check(r.ok and len(r.json().get("rows") or []) == 2, f"the French template reads back {r.status_code} {r.text[:200]}")
for lg in ("es", "it", "nl", "fr"):  # the Dutch "Bedrag (netto)" was no known column (review of 2.449.0); French stays for what follows
    G.patch(B + "/api/settings", json={"lang": lg})
    r = G.post(B + "/api/office/fixed-costs/import/preview", files={"file": ("t.xlsx", G.get(B + "/api/office/fixed-costs/import/template").content)})
    check(r.ok and len(r.json().get("rows") or []) == 2, f"the template reads back in {lg} {r.status_code} {r.text[:200]}")
r = G.post(B + "/api/account/export")
check(r.status_code == 202, "export starts " + r.text[:200])
for _ in range(480):  # polls the export's state until it is no longer running
    if G.get(B + "/api/account/export").json().get("state") != "running":
        break
    time.sleep(0.25)
r = su_get(G, B + "/api/account/export/file")
man = json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("manifest.json"))
check(any("mots de passe" in x for x in man["not_included"]) and not any(x.startswith("passwords") for x in man["not_included"]), "the manifest in French")
check(any(x.startswith("pas encore dans l’export du compte: ") and "chat_saves" in x for x in man["not_included"]), f"#3841: the reasons of the tables left out in French, the names stay: {man['not_included'][-1]}")
sys.exit(done("p2449_b_muster"))
