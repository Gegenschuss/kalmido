#!/usr/bin/env python3
"""2.447.0 (#3761): without a login every text follows one rule: the browser's language, else English, never silently the
first admin's. Signed in: the person's language. Errors of a browser outside the API are pages in that language."""
# kalmido-suite: fresh
import os
import re
import subprocess
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kt import B, check, done, fresh, H, sess, setup  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
FR, PAGE = {"Accept-Language": "fr-CA,de;q=0.5"}, {"Accept": "text/html"}

fresh()
A = setup()
A.patch(B + "/api/settings", json={"lang": "de"})  # the first admin speaks German: nobody signed out may get German from that


def anon(**more):
    s = requests.Session()
    s.headers.update(H)
    s.headers.update(more)
    return s


def wrong(s):
    return s.post(B + "/api/auth/login", json={"username": "nobody", "password": "wrong-password"}).json().get("error")


w = wrong(anon(**FR))
check("incorrect" in w, "signed out, French browser: the error is French " + str(w))
w = wrong(anon())
check(w == "Wrong username or password", "signed out, no browser language: English, not the first admin's German " + str(w))
w = wrong(anon(**{"Accept-Language": "pl"}))
check(w == "Wrong username or password", "signed out, a language the app does not have: English " + str(w))
check(anon(**FR).get(B + "/api/auth/info").json()["lang"] == "fr", "the login page says the same as the errors (fr)")
check(anon().get(B + "/api/auth/info").json()["lang"] == "en", "... and without a browser language English")

r = anon(**FR, **PAGE).post(B + "/")
check(r.status_code == 405 and 'lang="fr"' in r.text and "Méthode" in r.text and r.headers.get("Allow"), f"405 in a browser: a French page {r.status_code} {r.text[:120]}")
check("<html" not in anon().get(B + "/api/test/boom").text.lower(), "the API stays JSON")
r = anon().post(B + "/api/auth/login", data="{", headers={"Content-Type": "application/json"})
check(r.status_code in (400, 401) and "<html" not in r.text.lower(), f"a broken body on the API: no Flask page {r.status_code}")

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
code = ("import app\nfrom flask import g\nfrom kalmido.core.i18n import lang\n"
        "with app.app.test_request_context('/s/x', headers={'Accept-Language': 'fr'}):\n    g.user = {'id': 0}\n    print('LANG', lang())")
out = subprocess.run(["docker", "exec", "-w", "/app", CT, "python", "-c", code], capture_output=True, text=True)
check("LANG fr" in out.stdout, "the visitor of a public link (user id 0) follows the browser " + (out.stdout + out.stderr)[-200:])

A.headers.update({**FR, **PAGE})
r = A.get(B + "/does-not-exist")
check(r.status_code == 404 and 'lang="de"' in r.text and "Seite nicht gefunden" in r.text, "signed in: the 404 page in the person's language, not the browser's " + r.text[:120])
r = A.get(B + "/test/boom")
check(r.status_code == 500 and 'lang="de"' in r.text and "Etwas ist schiefgelaufen" in r.text and "Internal Server Error" not in r.text, f"500 in a browser: a page in the person's language {r.status_code}")

with open(os.path.join(N, "..", "static", "js", "reloadguard.js"), encoding="utf-8") as f:
    guard = f.read()
check(all(re.search(rf"\b{x}: \['", guard) for x in ("en", "de", "fr", "es", "it", "nl")), "the reload notice knows all six languages")
with open(os.path.join(N, "..", "static", "i18n.js"), encoding="utf-8") as f:
    check("function i18nStatic() { document.documentElement.lang = I18N.code;" in f.read(), "html lang follows the loaded language before the login")
sys.exit(done("p2447_a_lang"))
