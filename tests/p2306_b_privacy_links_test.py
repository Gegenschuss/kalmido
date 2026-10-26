#!/usr/bin/env python3
"""2.306.0 B (#2887): the operator's privacy statement and imprint. KALMIDO_PRIVACY_URL / KALMIDO_IMPRINT_URL and the two
fields in Administration > Server (the field wins, empty = the environment again) reach the login page's configuration
(/api/auth/info, without a session) and Settings > Help (/api/about); only plain http(s) addresses count (an unusable
environment value is no link), only an admin sets them. A person without an organisation sees them like everyone else.
freelancer-matrix: privacy links (login page, Settings > Help)
Starts its own container (fresh() with the two variables). usage: p2306_b_privacy_links_test.py <datadir>"""
import sys

from kt import B, check, done, fresh, sess, setup
from freelancer_fixture import freelancer

fresh({"KALMIDO_PRIVACY_URL": "https://example.com/privacy", "KALMIDO_IMPRINT_URL": "ftp://example.com/imprint"})
A = setup()
anon = sess()


def legal(s=anon, url="/api/auth/info"):
    r = s.get(B + url)
    assert r.ok, r.text
    return r.json().get("legal") or {}


# ---- the environment: an http(s) address is a link, anything else is none
L = legal()
check(L.get("privacy_url") == "https://example.com/privacy", "env: privacy link on the login page without a session " + repr(L))
check(L.get("imprint_url") == "", "env: a non-http(s) imprint address is no link " + repr(L))
ab = A.get(B + "/api/about").json()
check(ab.get("privacy_url_env") == "https://example.com/privacy" and ab.get("privacy_url") == "", "admin sees the env value as the default")

# ---- the setting in Administration > Server wins over the environment
r = A.patch(B + "/api/admin/settings", json={"privacy_url": "https://example.org/datenschutz", "imprint_url": "http://example.org/impressum"})
check(r.ok, "admin sets both fields " + r.text)
L = legal()
check(L == {"privacy_url": "https://example.org/datenschutz", "imprint_url": "http://example.org/impressum"}, "the setting wins " + repr(L))
check(legal(A, "/api/about") == L, "Settings > Help (about) has the same links")

# ---- only http(s) addresses, the old value stays on a refusal
for bad in ("ftp://example.org/x", "mailto:privacy@example.com", "example.org/privacy", "https://example.org/a b",
            "https://example.org/\"x", "https://example.org/" + "a" * 500, 42, ["https://example.org"]):
    r = A.patch(B + "/api/admin/settings", json={"privacy_url": bad})
    check(r.status_code == 400, f"refused: {bad!r:.40} -> {r.status_code}")
check(legal()["privacy_url"] == "https://example.org/datenschutz", "a refused value changes nothing")

# ---- empty = the environment again (and no link where there is none)
r = A.patch(B + "/api/admin/settings", json={"privacy_url": "", "imprint_url": None})
check(r.ok, "admin clears both fields " + r.text)
check(legal() == {"privacy_url": "https://example.com/privacy", "imprint_url": ""}, "cleared: the env value again, no imprint " + repr(legal()))

# ---- only an admin sets them; a person without an organisation sees them
FID, Fr = freelancer(B, A)
r = Fr.patch(B + "/api/admin/settings", json={"privacy_url": "https://example.net/mine"})
check(r.status_code == 403, f"a person who is not an admin may not set the link ({r.status_code})")
check(legal()["privacy_url"] == "https://example.com/privacy", "the refused change left the link as it was")
check(legal(Fr, "/api/about").get("privacy_url") == "https://example.com/privacy", "freelancer without an organisation: the link in Settings > Help")
check("privacy_url_env" not in Fr.get(B + "/api/about").json(), "freelancer: no admin fields in about")

sys.exit(done("p2306_b_privacy_links"))
