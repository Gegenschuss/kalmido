#!/usr/bin/env python3
"""2.368.4 A (#2989): texts without a signed-in reader and the names of holidays and states follow the language of the person
they are for; #2990: one English word for one thing. Own container. Invented data only.
freelancer-matrix: hub
 - the absences link: the owner's language (title, kinds, holidays), whoever fetches it, German and English
 - holidays and states in the reader's language in the absences answer and the "Calendars" window
 - the block pages of polls, forms and file requests in the language of the page they replace, not of the signed-in account
 - the daily summary names the basket in the reader's language
 - #2990: the checker refuses the variants of the glossary, the code has none, the languages kept their wording
usage: p23684_a_lang_test.py <datadir>"""
# kalmido-suite: fresh
import importlib.util
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import date

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, setup  # noqa: E402

fresh()
A = setup()
FID, Fr = freelancer(B, A)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
N = os.path.dirname(os.path.abspath(__file__))


def inside(code):
    out = subprocess.run(["docker", "exec", "-w", "/app", CT, "python", "-c", code], capture_output=True, text=True)
    return out.stdout + out.stderr


# ---- the absences link and the names, for a person without an organisation
assert Fr.patch(B + "/api/settings", json={"holiday_state": "BY", "lang": "de"}).ok
check(Fr.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-02-01", "end_date": "2027-02-01", "half_day": "am"}).ok,
      "an absence of the person without an organisation")
url = Fr.post(B + "/api/team/absences/feed", json={"action": "create"}).json()["url"]
P = urllib.parse.urlparse(url).path
ics = requests.get(B + P).text.replace("\r\n ", "")
check("SUMMARY:Neujahr" in ics and "· Abwesenheiten" in ics and "vormittags" in ics, "the link, German owner: German " + ics[:300])
ics = requests.get(B + P, headers={"Accept-Language": "fr"}).text.replace("\r\n ", "")
check("SUMMARY:Neujahr" in ics, "the fetching calendar app does not choose the language")
j = Fr.get(B + "/api/team/absences/feed").json()
check(j["states"]["BY"] == "Bayern" and j["states"]["AT"] == "Österreich", "the states in German " + str(j["states"]))
assert Fr.patch(B + "/api/settings", json={"lang": "en"}).ok
ics = requests.get(B + P).text.replace("\r\n ", "")
check("SUMMARY:New Year's Day" in ics and "Neujahr" not in ics and "· Absences" in ics and "morning" in ics, "the link, English owner: English " + ics[:300])
j = Fr.get(B + "/api/team/absences/feed").json()
check(j["states"]["BY"] == "Bavaria" and j["states"]["AT"] == "Austria" and j["states"]["BW"] == "Baden-Württemberg", "the states in English")
hol = [e for e in Fr.get(B + "/api/calendars/events", params={"from": "2027-10-01", "to": "2027-10-10"}).json().get("events", []) if e.get("holiday")]
check([e["title"] for e in hol] == ["German Unity Day"], f"the calendar view: an English name {hol}")
assert Fr.patch(B + "/api/settings", json={"holiday_state": "AT", "lang": "de"}).ok
hol = [e["title"] for e in Fr.get(B + "/api/calendars/events", params={"from": "2027-12-24", "to": "2027-12-28"}).json().get("events", []) if e.get("holiday")]
check(hol == ["Christtag", "Stefanitag"], f"Austria keeps its own names in German {hol}")
assert Fr.patch(B + "/api/settings", json={"lang": "en", "holiday_state": "BY"}).ok

# ---- a block page: the visitor's language, also when the browser is signed in with an account in another language
assert A.patch(B + "/api/settings", json={"lang": "de"}).ok
UID = A.get(B + "/api/me").json().get("id") or dbx("SELECT id FROM users WHERE username='alice'")[0][0]
for mod, fn in (("kalmido.calendars.polls", "tpo_page_get"), ("kalmido.team.forms", "form_page"), ("kalmido.files.filereq", "frq_page")):
    code = (f"import app, importlib\nfrom flask import g\nm = importlib.import_module('{mod}')\n"
            "import kalmido.api.common as ac\nm.hit_limit = ac.hit_limit = lambda *a, **k: True\n"
            "with app.app.test_request_context('/x', headers={'Accept-Language': 'fr'}):\n"
            f"    g.user = {{'id': {UID}, 'kid': 0}}\n    r = m.{fn}('x')\n    r = r[0] if isinstance(r, tuple) else r\n    print('PAGE', r.get_data(as_text=True))")
    out = inside(code)
    check("Zu viele" not in out and "Trop de" in out, f"{fn}: the block page in French " + out[-300:])

# ---- the basket in the daily summary
assert A.patch(B + "/api/settings", json={"lang": "en"}).ok
assert Fr.patch(B + "/api/settings", json={"lang": "en"}).ok
LID = dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (FID,))[0][0]
dbx_set = inside(f"from kalmido.core.db import connect\nc = connect()\nc.execute(\"UPDATE lists SET name='Eingang' WHERE id={LID}\")\nc.commit()\nprint('OK')")
check("OK" in dbx_set, "an old inbox with the German default name " + dbx_set[-200:])
today = date.today().isoformat()
check(Fr.post(B + "/api/tasks", json={"title": "Pay the rent", "list_id": LID, "due": today}).ok, "a task due today in the basket")
out = inside("import app\nfrom kalmido.core.db import connect\nfrom kalmido.integrations.mail import digest_mail_content\n"
             f"print('MAIL', digest_mail_content(connect(), {FID}, '{today}')[1])")
check("Pay the rent · Basket" in out and "Eingang" not in out, "the daily summary names the basket, not the stored name: " + out[-300:])

r = requests.post(B + "/drop", headers={"Accept-Language": "fr"}, data={"text": "x"})
check(r.status_code == 403 and r.text.strip() == "non autorisé", "/drop refuses in the caller's language: " + r.text[:80])

# ---- #2990: the glossary is a rule of the checker
spec = importlib.util.spec_from_file_location("i18n_check", os.path.join(N, "..", "tools", "i18n_check.py"))
ck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ck)
bad = ck.glossary_errors(["Customer number", "Log in", "Accent color", "Customize Today", "Fetch mails", "Your vacation", "New inquiry", "Quotes"])
check(len(bad) == 8, "every variant is an error " + str(bad))
good = ["Client number", "Sign in", "Sign-in", "Accent colour", "Customise Today", "Fetch e-mails", "Your holiday", "New enquiry", "Quotations",
        "mailbox.org", "{0} mail-in address", "Reminder|pack", "Logo", "Log", "Registered mail", "Customer|pack"]
check(ck.glossary_errors(good) == [], "the glossary words, a domain, a pack text and a Log pass " + str(ck.glossary_errors(good)))
# 2.542.0 (#4605): "Private" is the own workspace, "personal" only for what a person owns
bad = ck.glossary_errors(["My files", "Your personal office", "Make personal", "My workspace", "Personal area"])
check(len(bad) == 5, "#4605: the third names of the own workspace are errors " + str(bad))
check(ck.glossary_errors(["Private|workspace", "Your private office", "Move to Private", "Personal agent of {0}", "Your personal agent", "Personal API tokens"]) == [],
      "#4605: private office, Private and what a person owns pass")
check(len(ck.private_term_errors({"x": "Meine Ablage", "y": "Dein persönliches Büro"}, "de.json")) == 2
      and ck.private_term_errors({"x": "Privat", "y": "Persönlicher Agent von {0}"}, "de.json") == [], "#4605: German third names are refused")
keys, _, _ = ck.extract()
check(ck.glossary_errors(keys) == [], "no variant in the code " + str(ck.glossary_errors(keys))[:300])
check("Client no.|customer" in keys and "Payment reminder|dunning" in keys and "Sign-in" in keys, "the renamed keys are in the code")
for lg in ("de", "es", "fr", "it", "nl"):
    with open(os.path.join(N, "..", "static", "i18n", lg + ".json"), encoding="utf-8") as f:
        d = json.load(f)
    check(not [k for k in ("Customer number", "Log in", "Log out", "Vacation", "Accent color", "Users") if k in d], lg + ": no old key left")
    if lg == "de":  # the German wording stays: a word of the English source changed, nothing else
        check(d["Client no.|customer"] == "Kundennummer" and d["Client number"] == "Mandantennummer" and d["Sign in"] == "Anmelden"
              and d["Holiday"] == "Urlaub" and d["Payment reminder|dunning"] == "Mahnung", "German stays as it was")
sys.exit(done("p23684_a_lang"))
