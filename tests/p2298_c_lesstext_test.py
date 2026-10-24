#!/usr/bin/env python3
"""2.298.0 C (#3187): less text in knowledge, agents, settings and account; the error texts that said nothing.
 - a bare 404 (Denied() without a text) says "Not found. Maybe deleted or no longer shared with you." instead of "unknown",
   in English and in German; a 403 keeps "No permission (view only)"
 - the same for a person without an organisation (freelancer-matrix: settings)
 - the four broken German texts are fixed (static check of de.json): "keinm", "Eine Unterhaltung" with the wrong article,
   "im Eingabezeile ... in der aktuellen Projekt"; the encryption texts say "auch nicht der Betreiber" everywhere
usage: p2298_c_lesstext_test.py <datadir>      (KMT_NOSTART=1 / P2298C_NOSTART=1: a running server)"""
import json
import os
import sys

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

N = os.path.dirname(os.path.abspath(__file__))
NF_EN = "Not found. Maybe deleted or no longer shared with you."
NF_DE = "Nicht gefunden. Vielleicht gelöscht oder nicht mehr mit dir geteilt."

# ---------------------------------------------------------------- static: the German texts (no server needed)
DE = json.load(open(os.path.join(N, "..", "static", "i18n", "de.json"), encoding="utf-8"))
vals = [v for v in DE.values() if isinstance(v, str)] + [x for v in DE.values() if isinstance(v, list) for x in v]
check(not any("keinm " in v or "Teile eine Projekt" in v for v in vals), "no 'keinm' / 'Teile eine Projekt' left")
check(not any("In einem Ende-zu-Ende-verschlüsselten Unterhaltung" in v for v in vals), "no 'In einem ... Unterhaltung' left")
check(not any("im Eingabezeile" in v or "in der aktuellen Projekt" in v for v in vals), "no 'im Eingabezeile' / 'in der aktuellen Projekt' left")
check(DE.get("Files cannot be sent in an end-to-end encrypted conversation") == "In verschlüsselten Unterhaltungen gehen keine Dateien.",
      "the encrypted-conversation file text")
check(DE.get("This conversation is no longer available.") == "Diese Unterhaltung ist nicht mehr verfügbar.", "the text instead of 'Fehler room'")
check(DE.get(NF_EN) == NF_DE, "the German 404 text")
check(not any("auch nicht der Administrator" in v or "auch nicht die Administratoren" in v for v in vals),
      "encryption texts: 'auch nicht der Betreiber' everywhere")
for k in ("Too many requests, wait a moment", "Server error, please try again later", "File too large", "Login failed. Please try again."):
    check(k in DE, f"the status text is translated: {k}")

# ---------------------------------------------------------------- server: the 404 text
fresh(prefix="P2298C")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,comments,collab,wiki"})


def nf(s, lang, want, who):
    s.patch(B + "/api/settings", json={"lang": lang})
    r = s.get(B + "/api/wiki/pages/999999")
    check(r.status_code == 404 and r.json().get("error") == want, f"{who} ({lang}): a missing page {r.status_code} {r.text[:120]}")


nf(A, "en", NF_EN, "admin")
nf(A, "de", NF_DE, "admin")
A.patch(B + "/api/settings", json={"lang": "en"})
_, F = freelancer(B, A)
nf(F, "en", NF_EN, "without an organisation")
nf(F, "de", NF_DE, "without an organisation")
sys.exit(done("p2298_c_lesstext"))
