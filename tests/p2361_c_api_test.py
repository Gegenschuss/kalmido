#!/usr/bin/env python3
"""2.36.1 API tests, part C: quotations of Office & finance (#1021), own container in mode workspaces (start.sh).
 - CRUD of /api/office/docs: a new quotation takes the organisation's settings (language, currency, exchange rate, raw
   data factor, producing quotient / rate, validity, intro / closing text blocks, default rights) and reserves a number
   of the scheme at once; PATCH changes the head and returns the totals; PUT items replaces the positions (a service_id
   fills title in the document's language, rate, tax and flags); the KV02 figures through the server: net 20380.00,
   including raw data 23802.50, 4.5 producing days
 - numbers: KVA-{yyyy}-{seq:03} counts per year (a document dated in another year starts its own counter), a manual
   number must be unique, POST /number reserves the next one, duplicate = a new draft with the next number
 - framework contract: PATCH contract_id presets raw data included, its rights (snapshot with texts) and closing; its
   special rates win over the catalogue; the rights snapshot stays when the catalogue text changes; apply_contract false
   keeps the document
 - status (sent sets sent_at), render = the print model (labels in the document's language, formatted amounts, EN / USD)
 - tenant matrix (tenant-matrix: office): the second organisation and a private person see nothing (404 / 400), a member
   creates and changes, only the admin deletes (403) and sees costs / margin, an agent token gets 403, feature off 403
usage: p2361_c_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
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


FEAT = "cal,comments,collab,office,clients"
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Private")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
# mode workspaces: Alpha (alice admin, bob member), Beta (carol admin), dave in no organisation
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"})
assert r.ok, (r.status_code, r.text)
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
wss = {n: {w["id"]: w.get("role") for w in s.get(B + "/api/state").json()["me"].get("workspaces") or []} for n, s in (("alice", A), ("bob", Bo), ("carol", Ca), ("dave", Da))}
assert wss["alice"].get(ORG) == "admin" and wss["bob"].get(ORG) == "member" and list(wss["carol"]) == [ORG2] and wss["dave"] == {}, wss
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
D = "/api/office/docs"

# ---------------------------------------------------------------- settings + master data (B's routes), invented data only
r = A.put(B + "/api/office/settings", json={"company": {"name": "Studio Nordlicht GmbH", "lines": ["Studio Nordlicht GmbH", "Hafenstraße 12", "20457 Hamburg"]},
                                            "lang": "de", "currency": "EUR", "fx_usd": 1.09, "prod_quotient": 3, "raw_factor": 0.25, "producing_rate": 600,
                                            "offer_valid_days": 30, "offer_scheme": "KVA-{yyyy}-{seq:03}"})
check(r.ok, "settings saved " + r.text[:200])
check(A.get(B + "/api/office/settings").ok, "GET settings (seeds the text blocks)")
texts = A.get(B + "/api/office/texts").json()
TX = texts.get("texts") or texts.get("rows") or texts.get("items") or []
check(len(TX) >= 8, f"the pack's text blocks are seeded ({len(TX)})")
tid = lambda kind, key: next((t["id"] for t in TX if t["kind"] == kind and t["key"] == key), None)
T_UNL, T_WEM, T_IWU = tid("rights_time", "unlimited"), tid("rights_territory", "world_ex_music"), tid("rights_media", "internal_web_unpaid")
T_1Y, T_WORLD = tid("rights_time", "1y"), tid("rights_territory", "world")
check(T_UNL and T_WEM and T_IWU and T_1Y and T_WORLD, "the rights catalogue has the KV02 entries")
check(A.put(B + "/api/office/settings", json={"rights_default": {"time_id": T_UNL, "territory_id": T_WEM, "media_id": T_IWU}}).ok, "default rights set")


def svc(name_de, name_en, rate, cat="Video", raw=0, prod=0, intext="intern", unit="day", tax="standard"):
    r = A.post(B + "/api/office/services", json={"name_de": name_de, "name_en": name_en, "category": cat, "daily_rate": rate, "hourly_rate": None,
                                                 "raw_fee": raw, "producing": prod, "intext": intext, "unit": unit, "tax": tax})
    assert r.status_code == 201, r.text
    return r.json()["id"]


S_STORY = svc("Storyboard-Erstellung", "Storyboard creation", 980)
S_GENV = svc("Generative Medienherstellung (Video)", "Generative media (video)", 960, raw=1, prod=1)
S_GENA = svc("Generative Medienherstellung (Audio)", "Generative media (audio)", 960, raw=1, prod=1, cat="Audio")
S_ANIM = svc("Animation 2D / Motion Design", "Animation 2D / motion design", 1080, raw=1, prod=1, intext="extern")
S_CUT = svc("Schnitt", "Editing", 980, raw=1, prod=1)
S_STOCK = svc("Stockfootage HD", "Stock footage HD", 75, cat="Stock", intext="extern", unit="piece")
S_MUSCUT = svc("Musikschnitt", "Music editing", 980, cat="Audio", raw=1, prod=1)
S_TRACK = svc("Musik-Track inkl. Auswahl und Lizenzierung", "Music track incl. licence", 300, cat="Audio", prod=1, intext="extern", unit="piece")
S_SOUND = svc("Sound Design", "Sound design", 980, cat="Audio", raw=1, prod=1)
S_MIX = svc("Tonschnitt & Mischung", "Sound editing & mix", 580, cat="Audio", raw=1, prod=1)
S_SUBB = svc("Untertitel, Grundgebühr", "Subtitles, base fee", 210, cat="Office", raw=1, unit="flat")
S_SUBM = svc("Untertitel (ohne Transskript), Minutenpreis", "Subtitles, per minute", 50, cat="Office", raw=1, unit="minute")
S_LIC = svc("Nutzungsrechte Musik", "Music licence", 100, cat="Buyout", tax="reduced", unit="flat")
CL = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "contact": "z. Hd. Max Mustermann", "address": "Marktstraße 5\n50667 Köln"}).json()["id"]

# ---------------------------------------------------------------- create: defaults from the settings
r = A.post(B + D, json={"project_title": "Imagefilm Herbstkampagne", "client_id": CL, "project_ref": "PO-4711"})
check(r.status_code == 201, "a new quotation " + r.text[:200])
d = r.json()
DOC = d["id"]
check(d["number"] == "KVA-2026-001" or d["number"].startswith("KVA-") and d["number"].endswith("-001"), f"the first number of the scheme: {d['number']}")
check(d["lang"] == "de" and d["currency"] == "EUR" and d["fx_rate"] == 1.09 and d["raw_factor"] == 0.25 and d["prod_quotient"] == 3 and d["producing_rate"] == 600, f"defaults from the settings: {d['lang']} {d['currency']} {d['fx_rate']} {d['raw_factor']} {d['prod_quotient']} {d['producing_rate']}")
check(d["status"] == "draft" and d["raw_mode"] == "optional" and d["vat_mode"] == "vat" and d["discount_pct"] == 0, "a draft, raw data optional, VAT")
check(d["date"] and d["valid_until"] > d["date"], f"dated today, valid 30 days: {d['date']} .. {d['valid_until']}")
check(d["recipient"]["name"] == "Beispielkunde AG" and d["recipient"]["lines"][1:] == ["z. Hd. Max Mustermann", "Marktstraße 5", "50667 Köln"], f"the recipient from the client: {d['recipient']}")
check(d["intro"].startswith("Sehr geehrte Damen und Herren,") and d["closing"], f"intro / closing from the text blocks: {d['intro'][:60]!r}")
check(d["rights"]["time"]["text"] == "unbegrenzt" and d["rights"]["territory"]["text"] == "weltweit außer Musik auf Messe/Event (DE)" and d["rights"]["media"]["text"] == "intern, web, unpaid media", f"default rights as a snapshot with texts: {d['rights']}")
check(d["rights"]["note"] == "Im Übrigen gelten unsere AGB.", f"rights note from the text blocks: {d['rights']['note']}")
check(d["items"] == [] and d["totals"]["net"] == 0 and d["can_delete"] is True, "empty, admin may delete")

# ---------------------------------------------------------------- the KV02 positions through the server
KV = [
    {"kind": "heading", "title": "Video"},
    {"service_id": S_STORY, "qty": 3, "detail": "(enthält Reference Frames für die Produktion)"},
    {"service_id": S_GENV, "qty": 4}, {"service_id": S_GENA, "qty": 1},
    {"service_id": S_ANIM, "qty": 4.5, "cost": 600}, {"service_id": S_CUT, "qty": 2},
    {"service_id": S_STOCK, "qty": 10, "cost": 75},
    {"service_id": S_MUSCUT, "qty": "0,5", "producing": 0},
    {"service_id": S_TRACK, "qty": 1, "cost": 300},
    {"service_id": S_SOUND, "qty": 1}, {"service_id": S_MIX, "qty": 0.5},
    {"kind": "text", "detail": "Untertitel liefern wir als SRT-Datei."},
    {"service_id": S_SUBB, "qty": 1}, {"service_id": S_SUBM, "qty": 2},
]
r = A.put(B + f"{D}/{DOC}/items", json={"items": KV})
check(r.ok, "positions saved " + r.text[:300])
d = r.json()
t = d["totals"]
check(t["net"] == 20380 and t["raw_amount"] == 3422.5 and t["net_incl_raw"] == 23802.5 and t["producing_days"] == 4.5, f"KV02 parity through the server: {t.get('net')} / {t.get('net_incl_raw')} / {t.get('producing_days')}")
check(t["costs"] == 3750 and t["margin"] == 16630, f"admin sees costs / margin: {t.get('costs')} / {t.get('margin')}")
its = d["items"]
check(len(its) == 14 and its[1]["title"] == "Storyboard-Erstellung" and its[1]["rate"] == 980 and its[1]["unit"] == "day" and its[1]["tax"] == "standard", f"a service fills title (DE), rate, unit, tax: {its[1]}")
check(its[2]["raw_fee"] == 1 and its[2]["producing"] == 1 and its[7]["producing"] == 0 and its[7]["raw_fee"] == 1 and its[7]["qty"] == 0.5, "flags from the catalogue, overridable per position; comma quantity")
check(its[6]["unit"] == "piece" and its[6]["intext"] == "extern" and its[6]["cost"] == 75, f"stock: piece, external, cost {its[6]}")
check(its[0]["kind"] == "heading" and its[11]["kind"] == "text" and its[11]["detail"] == "Untertitel liefern wir als SRT-Datei.", "heading and text block kept in order")
kinds = [l["kind"] for l in t["lines"]]
check(kinds.count("item") == 12 and kinds[-2:] == ["producing", "raw"] and kinds[0] == "heading", f"print lines: {kinds}")
check(A.get(B + f"{D}/{DOC}").json()["totals"]["net"] == 20380, "GET returns the cached totals")
lst = A.get(B + D + "?kind=offer").json()
check(lst["role"] == "admin" and len(lst["docs"]) == 1 and lst["docs"][0]["net"] == 20380 and lst["docs"][0]["net_text"] == "20.380,00 €" and lst["docs"][0]["recipient_name"] == "Beispielkunde AG" and lst["docs"][0]["net_incl_raw"] == 23802.5, f"the list row: {lst['docs'][0]}")
check(len(A.get(B + D + "?q=Herbst").json()["docs"]) == 1 and len(A.get(B + D + "?q=nirgends").json()["docs"]) == 0, "search by project title")

# ---------------------------------------------------------------- head changes: discount, raw mode, language, USD, novat
d = A.patch(B + f"{D}/{DOC}", json={"discount_pct": "10"}).json()
check(d["totals"]["discount"] == 1768 and d["totals"]["net"] == 20380 - 1768 and [l for l in d["totals"]["lines"] if l["kind"] == "discount"][0]["total"] == -1768, f"10 % discount on the 12 positions: {d['totals']['discount']} / {d['totals']['net']}")
d = A.patch(B + f"{D}/{DOC}", json={"discount_pct": 0, "raw_mode": "included"}).json()
check(d["totals"]["net"] == 23802.5 and d["totals"]["net_excl_raw"] == 20380 and d["totals"]["net_incl_raw"] is None, f"raw data included: {d['totals']['net']} / {d['totals']['net_excl_raw']}")
d = A.patch(B + f"{D}/{DOC}", json={"raw_mode": "optional", "currency": "USD", "fx_rate": "1,09"}).json()
check(d["currency"] == "USD" and d["fx_rate"] == 1.09 and d["totals"]["net"] == 22214.2 and d["totals"]["lines"][1]["rate"] == 1068.2, f"USD: 980 x 1.09, net 22214.20: {d['totals']['net']}")
d = A.patch(B + f"{D}/{DOC}", json={"currency": "EUR", "vat_mode": "novat"}).json()
check(d["totals"]["net"] == 20380 and d["totals"]["gross"] == 20380 and d["totals"]["tax_lines"] == [], "novat: no tax lines")
d = A.patch(B + f"{D}/{DOC}", json={"vat_mode": "vat"}).json()
check(d["totals"]["gross"] == 24252.2 and d["totals"]["tax_lines"][0]["pct"] == 19, f"VAT again: gross {d['totals']['gross']}")
r = A.patch(B + f"{D}/{DOC}", json={"lang": "fr"})
check(r.status_code == 400, "lang fr: 400")
r = A.patch(B + f"{D}/{DOC}", json={"date": "09.10.2026"})
check(r.status_code == 400, "a German date is refused (ISO only)")
r = A.patch(B + f"{D}/{DOC}", json={"raw_factor": 11})
check(r.status_code == 400, "raw factor 11: 400")
d = A.patch(B + f"{D}/{DOC}", json={"rights": {"time": {"id": T_1Y}, "exceptions": "Musik nur online", "exclusive": 1}, "fields": [{"name": "Leistungszeitraum", "value": "November 2026"}, {"name": "", "value": ""}]}).json()
check(d["rights"]["time"] == {"id": T_1Y, "text": "1 Jahr ab Erstveröffentlichung"} and d["rights"]["territory"]["text"].startswith("weltweit außer") and d["rights"]["exceptions"] == "Musik nur online" and d["rights"]["exclusive"] == 1, f"rights: an id takes the catalogue text, the rest stays: {d['rights']}")
check(d["fields"] == [{"name": "Leistungszeitraum", "value": "November 2026"}], f"own fields, empty ones dropped: {d['fields']}")
d = A.patch(B + f"{D}/{DOC}", json={"rights": {"time": "nach Absprache"}}).json()
check(d["rights"]["time"] == {"id": None, "text": "nach Absprache"}, "free text per dimension")
A.patch(B + f"{D}/{DOC}", json={"rights": {"time": {"id": T_UNL}, "exceptions": "", "exclusive": 0}})

# ---------------------------------------------------------------- render (the print model)
rd = A.get(B + f"{D}/{DOC}/render").json()
check(rd["kind"] == "offer" and rd["lang"] == "de" and rd["title"] == "Kostenvoranschlag" and rd["number"] == d["number"] and rd["company"]["name"] == "Studio Nordlicht GmbH", f"render head: {rd.get('title')} {rd.get('number')}")
check(rd["totals"]["net_text"] == "20.380,00 €" and rd["totals"]["net_incl_raw_text"] == "23.802,50 €" and rd["totals"]["rows"] == [["Summe Netto", "20.380,00 €"], ["inklusive Rohdaten", "23.802,50 €"]], f"render totals: {rd['totals']['rows']}")
check(rd["totals"]["vat_note"] == "Alle Preise zuzüglich 7 % bzw. 19 % MwSt." and rd["totals"]["show_tax_lines"] is False, "the offer shows the VAT note only")
check(rd["rights"]["title"] == "Rechteübertragung" and rd["rights"]["rows"] == [["Zeitliche Auswertung", "unbegrenzt"], ["Räumliche Auswertung", "weltweit außer Musik auf Messe/Event (DE)"], ["Mediale Auswertung", "intern, web, unpaid media"]] and rd["rights"]["note"] == "Im Übrigen gelten unsere AGB.", f"KV02 rights texts DE: {rd['rights']}")
check(rd["meta"][0] == ["Angebot Nr.", d["number"]] and rd["meta"][2] == ["Kunde", "Beispielkunde AG"] and rd["meta"][3] == ["Ref./PO-Nr.", "PO-4711"] and rd["meta"][1][1].count(".") == 2, f"meta rows with DE labels and dd.mm.yyyy: {rd['meta']}")
check(rd["recipient"]["lines"][0] == "Beispielkunde AG" and rd["intro"].startswith("Sehr geehrte") and rd["signature"] == "Mit freundlichen Grüßen" and rd["fields"] == [{"name": "Leistungszeitraum", "value": "November 2026"}], "recipient, intro, signature, fields")
line = [l for l in rd["lines"] if l["kind"] == "item"][3]
check(line["qty_text"] == "4,5" and line["unit_text"] == "Tage" and line["rate_text"] == "1.080,00 €" and line["total_text"] == "4.860,00 €" and line["tax_pct"] == 19, f"a formatted line: {line}")
check(rd["labels"]["pos"] == "Pos." and rd["labels"]["units"]["day"] == "Tage" and rd["labels"]["page_of"] == "Seite {x} von {y}" and rd["formats"]["date"] == "dd.mm.yyyy", "labels and formats of the pack")
check(rd["internal"] == {"costs": 3750, "margin": 16630} and rd["fx_note"] == "" and rd["company"]["logo"] is False and "logo_path" not in rd["company"] and rd["company"]["color"].startswith("#"), f"internal for the admin, no fx note in EUR: {rd['internal']}")
# EN + USD
d = A.patch(B + f"{D}/{DOC}", json={"lang": "en", "currency": "USD", "rights": {"time": {"id": T_UNL}, "territory": {"id": T_WEM}, "media": {"id": T_IWU}}}).json()
rd = A.get(B + f"{D}/{DOC}/render").json()
check(rd["title"] == "Quotation" and rd["totals"]["rows"][0][0] == "Net Total" and rd["totals"]["rows"][1][0] == "including raw data" and rd["totals"]["net_text"] == "$22,214.20", f"EN / USD render: {rd['title']} {rd['totals']['rows']}")
check(rd["rights"]["rows"] == [["Duration of License", "in perpetuity"], ["Territorial Rights", "worldwide except music on trade shows / live events (DE)"], ["Rights by Medium", "internal use, web, unpaid media"]], f"KV02 rights texts EN: {rd['rights']['rows']}")
check(rd["fx_note"] == "Exchange rate €1: $1.09" and rd["fx_rate"] == 1.09 and rd["totals"]["vat_note"] == "All prices plus 7 % or 19 % VAT.", f"USD shows the exchange rate: {rd['fx_note']}")
check([l for l in rd["lines"] if l["kind"] == "producing"][0]["detail"] == "4.5 days = 14 production days / 3, rounded to half days", "EN producing explanation")
# the positions keep the DE titles they were saved with (snapshot); a new position in EN takes the EN name
d = A.put(B + f"{D}/{DOC}/items", json={"items": [{"service_id": S_STORY, "qty": 1}]}).json()
check(d["items"][0]["title"] == "Storyboard creation" and d["items"][0]["rate"] == 980, f"EN document: the service's English name, rate in EUR: {d['items'][0]}")
A.patch(B + f"{D}/{DOC}", json={"lang": "de", "currency": "EUR"})
A.put(B + f"{D}/{DOC}/items", json={"items": KV})

# ---------------------------------------------------------------- numbers: per year, manual, unique, reserve, duplicate
d2 = A.post(B + D, json={"project_title": "Zweites Projekt"}).json()
check(d2["number"].endswith("-002"), f"the second number: {d2['number']}")
d3 = A.post(B + D, json={"project_title": "Nächstes Jahr", "date": "2027-03-01"}).json()
check(d3["number"] == "KVA-2027-001", f"a document dated 2027 starts the 2027 counter: {d3['number']}")
d4 = A.post(B + D, json={"project_title": "Noch eins", "date": "2027-03-02"}).json()
check(d4["number"] == "KVA-2027-002", f"2027 counts on: {d4['number']}")
r = A.post(B + f"{D}/{d4['id']}/number", json={"number": d3["number"]})
check(r.status_code == 400 and "already" in r.text, "a used number is refused " + r.text[:100])
r = A.post(B + f"{D}/{d4['id']}/number", json={"number": "ANG-FREI-7"})
check(r.ok and r.json()["number"] == "ANG-FREI-7", "a free manual number")
r = A.post(B + f"{D}/{d4['id']}/number", json={})
check(r.ok and r.json()["number"] == "KVA-2027-003", f"reserve the next one of the scheme: {r.json()}")
r = A.post(B + f"{D}/{DOC}/duplicate")
check(r.status_code == 201 and r.json()["status"] == "draft" and r.json()["number"].endswith("-003") and r.json()["totals"]["net"] == 20380 and len(r.json()["items"]) == 14 and r.json()["project_title"] == "Imagefilm Herbstkampagne", f"duplicate: a new draft with the next number and the positions: {r.json()['number']} {r.json()['totals'].get('net')}")
DUP = r.json()["id"]
check(A.get(B + f"{D}/{DUP}/render").json()["number"] == r.json()["number"], "the copy renders with its own number")
r = A.put(B + "/api/office/settings", json={"offer_scheme": "{yy}-{seq:04}-{client}"})
check(r.ok, "scheme with client slug")
d5 = A.post(B + D, json={"project_title": "Slug", "client_id": CL}).json()
check(d5["number"] == d5["date"][2:4] + "-0004-Beispielkunde-AG", f"the scheme's placeholders: {d5['number']}")
A.put(B + "/api/office/settings", json={"offer_scheme": "KVA-{yyyy}-{seq:03}"})

# ---------------------------------------------------------------- framework contract preset
r = A.post(B + "/api/office/contracts", json={"name": "Rahmenvertrag Agentur Beispiel", "client_id": CL, "date": "2026-01-15", "raw_included": 1,
                                              "rights_time_id": T_1Y, "rights_territory_id": T_WORLD, "rights_media_id": T_IWU,
                                              "rights_note_de": "Gemäß § 3 des Rahmenvertrags.", "closing_de": "Es gelten die Konditionen des Rahmenvertrags.",
                                              "rates": {str(S_CUT): 900}})
check(r.status_code == 201, "a framework contract " + r.text[:200])
CT = r.json()["id"]
d = A.patch(B + f"{D}/{DOC}", json={"contract_id": CT}).json()
check(d["raw_mode"] == "included" and d["totals"]["net"] == 23802.5 and d["totals"]["net_excl_raw"] == 20380, f"contract: raw data included: {d['raw_mode']} {d['totals']['net']}")
check(d["rights"]["time"]["text"] == "1 Jahr ab Erstveröffentlichung" and d["rights"]["territory"]["text"] == "weltweit" and d["rights"]["media"]["text"] == "intern, web, unpaid media" and d["rights"]["note"] == "Gemäß § 3 des Rahmenvertrags.", f"contract: rights preset: {d['rights']}")
check(d["closing"] == "Es gelten die Konditionen des Rahmenvertrags." and d["contract"]["name"] == "Rahmenvertrag Agentur Beispiel" and d["contract"]["rates"] == {str(S_CUT): 900}, f"contract: closing and the contract in the document: {d.get('contract')}")
d = A.put(B + f"{D}/{DOC}/items", json={"items": [{"service_id": S_CUT, "qty": 1}, {"service_id": S_CUT, "qty": 1, "rate": 950}]}).json()
check(d["items"][0]["rate"] == 900 and d["items"][1]["rate"] == 950, f"the contract's special rate wins over the catalogue, an explicit rate over both: {[i['rate'] for i in d['items']]}")
A.put(B + f"{D}/{DOC}/items", json={"items": KV})
# the snapshot survives a change of the catalogue text
A.patch(B + f"/api/office/texts/{T_1Y}", json={"text_de": "1 Jahr ab Erstveröffentlichung (neu)"})
check(A.get(B + f"{D}/{DOC}").json()["rights"]["time"]["text"] == "1 Jahr ab Erstveröffentlichung", "the rights snapshot keeps its text when the catalogue changes")
d = A.patch(B + f"{D}/{DOC}", json={"contract_id": None}).json()
check(d["contract_id"] is None and d["raw_mode"] == "included" and d["rights"]["time"]["text"] == "1 Jahr ab Erstveröffentlichung", "removing the contract keeps the document as it is (deviation per document)")
d = A.patch(B + f"{D}/{DOC}", json={"contract_id": CT, "apply_contract": False, "raw_mode": "optional"}).json()
check(d["contract_id"] == CT and d["raw_mode"] == "optional", "apply_contract false: the contract is linked without presets")
r = A.patch(B + f"{D}/{DOC}", json={"contract_id": 999999})
check(r.status_code == 404, "unknown contract: 404")

# ---------------------------------------------------------------- status
r = A.post(B + f"{D}/{DOC}/status", json={"status": "sent"})
check(r.ok and r.json()["status"] == "sent" and r.json()["sent_at"], "sent sets sent_at")
sent_at = r.json()["sent_at"]
r = A.post(B + f"{D}/{DOC}/status", json={"status": "accepted"})
check(r.ok and r.json()["status"] == "accepted" and r.json()["sent_at"] == sent_at and r.json()["status_text"] == "Accepted", "accepted keeps sent_at")
check(A.post(B + f"{D}/{DOC}/status", json={"status": "paid"}).status_code == 400, "unknown status 400")
check([x["status"] for x in A.get(B + D + "?status=accepted").json()["docs"]] == ["accepted"], "filter by status")

# ---------------------------------------------------------------- tenant matrix (tenant-matrix: office)
check(Ca.get(B + D).status_code == 200 and Ca.get(B + D).json()["docs"] == [] and Ca.get(B + D).json()["org_id"] == ORG2, "the second organisation sees no document of the first")
for m, p in (("GET", f"{D}/{DOC}"), ("PATCH", f"{D}/{DOC}"), ("PUT", f"{D}/{DOC}/items"), ("POST", f"{D}/{DOC}/number"), ("POST", f"{D}/{DOC}/status"),
             ("POST", f"{D}/{DOC}/duplicate"), ("DELETE", f"{D}/{DOC}"), ("GET", f"{D}/{DOC}/render")):
    r = Ca.request(m, B + p, json={"status": "draft", "items": []})
    check(r.status_code == 404, f"other organisation: {m} {p} -> 404 (got {r.status_code})")
r = Da.get(B + D)
check(r.status_code == 400 and "organisation" in r.text, f"a private person without an organisation: 400 with a hint ({r.status_code} {r.text[:80]})")
check(Da.post(B + D, json={}).status_code == 400 and Da.get(B + f"{D}/{DOC}").status_code == 400, "private person: nothing")
r = requests.get(B + D, headers=AGH)
check(r.status_code in (401, 403), f"an agent token is refused: 401/403 ({r.status_code})")
check(requests.get(B + f"{D}/{DOC}", headers=AGH).status_code in (401, 403) and requests.post(B + D, headers=AGH, json={}).status_code in (401, 403), "agent: refused on every docs route")
check(requests.get(B + "/api/v1/office/docs", headers=AGH).status_code == 404, "no /api/v1 route for the module in stage 1")
# a member of the organisation
r = Bo.get(B + D)
check(r.ok and r.json()["role"] == "member" and len(r.json()["docs"]) >= 5, "bob (member) sees the organisation's quotations")
bd = Bo.get(B + f"{D}/{DOC}").json()
check("costs" not in bd["totals"] and "margin" not in bd["totals"] and bd["items"][4]["cost"] is None and bd["can_delete"] is False, "a member sees no costs / margin and cannot delete")
check(Bo.get(B + f"{D}/{DOC}/render").json()["internal"] is None, "render: no internal block for a member")
r = Bo.post(B + D, json={"project_title": "Bobs Angebot"})
check(r.status_code == 201, "a member creates")
BD = r.json()["id"]
r = Bo.put(B + f"{D}/{BD}/items", json={"items": [{"service_id": S_ANIM, "qty": 2, "cost": 500}]})
check(r.ok and r.json()["totals"]["net"] == 2160 + 300 and A.get(B + f"{D}/{BD}").json()["items"][0]["cost"] == 0, "a member changes positions; a cost it sends is ignored (0) -- " + str(A.get(B + f"{D}/{BD}").json()["items"][0]["cost"]))
check(Bo.patch(B + f"{D}/{BD}", json={"project_title": "Bobs Angebot 2"}).json()["project_title"] == "Bobs Angebot 2", "a member edits the head")
r = Bo.delete(B + f"{D}/{BD}")
check(r.status_code == 403, f"a member cannot delete: 403 ({r.status_code})")
r = A.delete(B + f"{D}/{BD}")
check(r.ok and A.get(B + f"{D}/{BD}").status_code == 404, "the admin deletes")
check(Bo.get(B + f"{D}/{BD}").status_code == 404, "deleted = 404")
Bo.patch(B + "/api/settings", json={"features": "cal,comments"})
check(Bo.get(B + D).status_code == 403, "feature off: 403")
Bo.patch(B + "/api/settings", json={"features": FEAT})
# a client of the other organisation cannot be used as recipient
r = Ca.post(B + "/api/clients", json={"name": "Fremder Kunde"})
if r.status_code == 201:
    check(A.patch(B + f"{D}/{DOC}", json={"client_id": r.json()["id"]}).status_code == 404, "a client of another organisation: 404")
# deleting the organisation's client keeps the document (SET NULL)
check(A.delete(B + f"/api/clients/{CL}").ok and A.get(B + f"{D}/{DOC}").json()["client_id"] is None and A.get(B + f"{D}/{DOC}").json()["recipient"]["name"] == "Beispielkunde AG", "client deleted: the document keeps its recipient snapshot")
# a used service is archived, not deleted, and the position keeps its title
r = A.delete(B + f"/api/office/services/{S_STORY}")
check(r.ok and A.get(B + f"{D}/{DOC}").json()["items"][1]["title"] == "Storyboard-Erstellung", "a service in use is archived; the position keeps its snapshot " + r.text[:80])

print(f"p2361_c_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
