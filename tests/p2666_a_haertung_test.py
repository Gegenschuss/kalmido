#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.666.0 part A (#4074): security hardening, one fallback check per point (red without its fix). Own container (start.sh
through kt.fresh, restarted once without PUBLIC_URL at the end). Invented companies, people and files only.
freelancer-matrix: office
 - 1) unlocking a locked folder (decrypting): the plain bytes go through the upload checks like moving a file out (an HTML
   file declared as a PNG picture is stored as application/octet-stream, not image/png)
 - 10) a signature link works at most 90 days: an expiry further ahead is 400; an open link made 91 days ago is gone (the
   page 404, the list shows it not live), also without an own expiry date
 - 12) the Peppol status fetch and the receiver lookup (provider calls with the office's key) need the right to send
   ("release") like sending: a group person without it 403, with it through; a person without organisation (own office) through
 - 13) a point of Money switched off: somebody without the right gets 403, not the feature's 404 (no answer about the switch);
   the admin still 404 (a guest without office groups; a group person is stopped by the path gate before already)
 - 15) POST /api/office/receipt-mail with a list as the body: 400 (organisation and a person without organisation)
 - 5) without PUBLIC_URL: a new receipt fetcher and a new scan inbox are refused (503, no row, never the request's Host in a code), the hosted MCP
   metadata answer 503 instead of naming the request's Host as issuer; the connected apps list still answers (no address)
 (2) IMAP expunge: p2240_a_mail_test.py; (3) org import undo: p2237_d_orgimport_test.py; #5112: p2658_c_audiofile_test.py)
usage: p2666_a_haertung_test.py <datadir>      (P2666A_NOSTART=1 / KMT_NOSTART=1: the first container runs already)"""
import base64
import datetime as dt
import json
import os
import sys

import requests

import kt
from kt import B, PASSWORD, check, dbx, sess
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "cal,comments,collab,office,clients,docs,files,contacts"
O = B + "/api/office"
ENV = {"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": KEY, "KALMIDO_ORGCRYPT_DELAY": "0"}
CO = {"name": "Studio Beispiel GmbH", "street": "Hafenweg 2", "zip": "12345", "city": "Musterstadt", "iban": "DE02120300000000202051",
      "tax_number": "12/345/67890"}


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def keys_body():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32)},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(120)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(120)}}


def wrapped():
    return {"v": 1, "iv": b64(12), "ct": b64(48)}


def ct(gen=1):
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(90)}, separators=(",", ":"))


def kenc(gen=1):
    return b"KENC\x02" + gen.to_bytes(4, "big") + os.urandom(12) + os.urandom(64)


def office(s, ws):
    """An office with a client and a draft invoice -> the invoice's id."""
    r = s.put(O + "/settings", json={"company_fields": CO, "lang": "en", "currency": "EUR"})
    check(r.ok, f"{ws}: office settings {r.status_code} {r.text[:160]}")
    cl = s.post(B + "/api/clients", json={"name": "Kunde Beispiel", "email": "kunde@example.com", "street": "Musterweg 1", "zip": "12345",
                                          "city": "Musterstadt", **({"org_id": ws} if isinstance(ws, int) else {})})
    check(cl.status_code in (200, 201), f"{ws}: a client {cl.status_code} {cl.text[:160]}")
    d = s.post(O + "/docs", json={"kind": "invoice", "client_id": cl.json().get("id"), "project_title": "Schnitt", "service_from": "2026-10-01",
                                  "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
    check(d.status_code in (200, 201), f"{ws}: a draft invoice {d.status_code} {d.text[:160]}")
    return d.json().get("id", 0)


kt.fresh(env=ENV, prefix="P2666A")
A = kt.setup()
ME = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ME}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
FRI, Fr = freelancer(B, A, "frida", features=FEAT)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Member", "password": PASSWORD, "email": "carol@example.com"})
assert r.ok, r.text
CAROL = r.json()["id"]
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com", "role": "member"}).ok, "carol joins the organisation")
Ca = sess("carol")
Ca.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})

# ---------------------------------------------------------------- 1) unlocking: the upload checks
check(Fr.put(B + "/api/e2e/keys", json=keys_body()).ok, "frida sets up her keys")
r = Fr.post(B + "/api/files/folders", json={"name": "Tresor", "space": "private"})
assert r.status_code == 201, r.text
SAFE = r.json()["id"]
r = Fr.post(B + f"/api/files/lock/{SAFE}/start", json={"keys": [{"user_id": FRI, "wrapped": wrapped()}]})
check(r.ok, f"lock: start {r.text[:160]}")
check(Fr.post(B + f"/api/files/lock/{SAFE}/finish", json={}).ok, "lock: finish")
r = Fr.post(B + "/api/files/lock/upload", data={"parent_id": str(SAFE), "name": ct()}, files={"file": ("encrypted.kenc", kenc(), "application/octet-stream")})
check(r.status_code == 201, f"an encrypted file in the locked folder {r.status_code} {r.text[:160]}")
F1 = r.json()["items"][0]["id"] if r.status_code == 201 else 0
r = Fr.post(B + f"/api/files/lock/{SAFE}/stop", json={"password": PASSWORD})
check(r.ok and r.json().get("mode") == "decrypting", f"unlock: decrypting {r.text[:160]}")
HTML = b"<!doctype html><script>alert(1)</script>"
r = Fr.post(B + f"/api/files/lock/{SAFE}/convert/{F1}", data={"name": "bild.png", "type": "image/png"},
            files={"file": ("x", HTML, "application/octet-stream")})
check(r.ok, f"the plain file back {r.status_code} {r.text[:160]}")
m = one("SELECT mime FROM fs_nodes WHERE id=?", (F1,))
check(m == "application/octet-stream", f"#4074 1: HTML declared as a PNG is no picture after unlocking (the type check of an upload) {m}")
r = Fr.post(B + f"/api/files/lock/{SAFE}/finish", json={})
check(r.ok and r.json().get("mode") is None, f"open again {r.text[:160]}")
check(Fr.get(B + f"/api/files/nodes/{F1}/content").content == HTML, "the bytes are the plain ones")

# ---------------------------------------------------------------- 10) signature links: at most 90 days
FL = Fr.post(B + "/api/lists", json={"name": "Imagefilm Beispiel"}).json()["id"]
far = (kt.today() + dt.timedelta(days=200)).isoformat()
r = Fr.post(B + f"/api/lists/{FL}/signoffs", json={"expires": far})
check(r.status_code == 400, f"#4074 10: an expiry 200 days ahead: 400 ({r.status_code} {r.text[:120]})")
r = Fr.post(B + f"/api/lists/{FL}/signoffs", json={"expires": (kt.today() + dt.timedelta(days=60)).isoformat()})
check(r.ok and r.json().get("expires_at"), f"60 days ahead: fine {r.status_code} {r.text[:120]}")
r = Fr.post(B + f"/api/lists/{FL}/signoffs", json={})
check(r.ok and r.json().get("live") and r.json().get("url"), f"a link without an expiry date {r.status_code} {r.text[:160]}")
SID, TOK = r.json().get("id", 0), (r.json().get("url") or "/s/q/x").split("/s/q/")[1]
pg = requests.get(B + "/s/q/" + TOK, headers={"Accept-Language": "en"}, allow_redirects=False)
check(pg.status_code == 200, f"the page opens {pg.status_code}")
old = (kt.now().astimezone(dt.timezone.utc) - dt.timedelta(days=91)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
dbx("UPDATE office_signoffs SET created_at=? WHERE id=?", (old, SID))
pg = requests.get(B + "/s/q/" + TOK, headers={"Accept-Language": "en"}, allow_redirects=False)
check(pg.status_code == 404, f"#4074 10: made 91 days ago, no expiry date: the link is gone ({pg.status_code})")
x = [s for s in Fr.get(B + f"/api/lists/{FL}/signoffs").json().get("signoffs", []) if s["id"] == SID]
check(x and x[0]["live"] is False and x[0]["url"] is None, f"#4074 10: the list shows it as over {x}")

# ---------------------------------------------------------------- 12) Peppol provider calls need the right to send
INV = office(A, ORG)
FINV = office(Fr, "private")
R = O + "/rights"


def group(name, levels, specials=()):
    g = A.post(R + "/groups", json={"from": "tpl:none", "name": name})
    assert g.status_code == 201, g.text
    r = A.patch(R + f"/groups/{g.json()['id']}", json={"levels": levels, "specials": list(specials)})
    assert r.ok, r.text
    r = A.put(R + f"/people/{CAROL}", json={"groups": [f"g:{g.json()['id']}"]})
    assert r.ok, r.text


group("Rechnungen ohne Versand", {"invoices": "edit", "offers": "edit"})
check(Ca.get(O + f"/docs/{INV}").ok, "carol reads the invoice (her group)")
for p in ("refresh", "lookup"):
    r = Ca.post(O + f"/docs/{INV}/peppol/{p}", json={})
    check(r.status_code == 403, f"#4074 12: {p} without the right to send: 403 ({r.status_code} {r.text[:120]})")
group("Versand", {"invoices": "edit", "offers": "edit"}, ["release"])
r = Ca.post(O + f"/docs/{INV}/peppol/refresh", json={})
check(r.ok, f"with the right to send: the status fetch answers {r.status_code} {r.text[:120]}")
r = Ca.post(O + f"/docs/{INV}/peppol/lookup", json={})
check(r.status_code == 409, f"with the right to send: the lookup gets to its own check (no Peppol id: 409) {r.status_code} {r.text[:120]}")
check(A.post(O + f"/docs/{INV}/peppol/lookup", json={}).status_code == 409, "the admin: the same 409")
check(Fr.post(O + f"/docs/{FINV}/peppol/refresh", json={}).ok and Fr.post(O + f"/docs/{FINV}/peppol/lookup", json={}).status_code == 409,
      "a person without organisation (her own office): through to the own checks")

# ---------------------------------------------------------------- 13) the switch of a function: no answer without the right
group("Nur Briefe", {"letters": "edit"})
r = A.put(O + "/settings", json={"features_off": ["money.kpi"]})
check(r.ok and r.json()["features"].get("money.kpi") is False, f"the admin switches the key figures off {r.status_code}")
r = Ca.get(O + "/kpi")
check(r.status_code == 403, f"#4074 13: no right for the key figures (an office group): 403 ({r.status_code} {r.text[:120]})")
r = A.post(B + "/api/users", json={"username": "gina", "display_name": "Gina Guest", "password": PASSWORD, "email": "gina@example.com"})
assert r.ok, r.text
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "gina@example.com", "role": "guest"}).ok, "gina joins as a guest (no office groups)")
Gi = sess("gina")
Gi.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
r = Gi.get(O + "/kpi")
check(r.status_code == 403, f"#4074 13: a guest (no office right): 403, not the feature's 404 ({r.status_code} {r.text[:120]})")
check(A.get(O + "/kpi").status_code == 404, "the admin: 404 (switched off)")
A.put(O + "/settings", json={"features_off": []})
check(Ca.get(O + "/kpi").status_code == 403 and Gi.get(O + "/kpi").status_code == 403 and A.get(O + "/kpi").ok,
      "on again: the admin 200, carol and the guest still 403")

# ---------------------------------------------------------------- 15) receipt-mail: a body that is no object
for s, who in ((A, "the organisation's admin"), (Fr, "a person without organisation")):
    r = s.post(O + "/receipt-mail", json=[1])
    check(r.status_code == 400, f"#4074 15: {who}: a list as the body: 400 ({r.status_code} {r.text[:120]})")
    r = s.post(O + "/receipt-mail", json="renew")
    check(r.status_code == 400, f"#4074 15: {who}: a string as the body: 400 ({r.status_code})")
    check(s.post(O + "/receipt-mail", json={}).status_code != 500, f"{who}: an object: no 500")

# ---------------------------------------------------------------- 5) without PUBLIC_URL: no Host header in codes / metadata
r = Fr.post(B + "/api/docs/fetchers", json={"ws": "private", "name": "Mac Studio"})  # (a foreign Host header: the session does not count, 401)
code = r.json().get("code", "") if r.status_code == 201 else ""
raw = code.split(":", 2)[-1] if code else ""
url = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))).get("url") if raw else ""
check(r.status_code == 201 and url == "https://kalmido.example", f"with PUBLIC_URL: the code names it {r.status_code} {url}")
r = Fr.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Scanner"})  # review E: the scan inbox's code as well
code = r.json().get("code", "") if r.status_code == 201 else ""
raw = code.split(":", 2)[-1] if code else ""
url = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))).get("url") if raw else ""
check(r.status_code == 201 and url == "https://kalmido.example", f"with PUBLIC_URL: the scan inbox code names it {r.status_code} {url}")
r = A.patch(B + "/api/admin/settings", json={"mcp_remote": True, "password": PASSWORD})
check(r.ok and r.json().get("mcp_remote") is True, f"hosted MCP switched on {r.status_code} {r.text[:120]}")
j = requests.get(B + "/.well-known/oauth-authorization-server", headers={"Host": "evil.example"}).json()
check(j.get("issuer") == "https://kalmido.example", f"with PUBLIC_URL: the issuer is PUBLIC_URL {j.get('issuer')}")

if kt.fresh(env={**ENV, "PUBLIC_URL": ""}, keep=True):
    check(kt.container_env("PUBLIC_URL") == "", "restarted without PUBLIC_URL")
    Fr = sess("frida")
    A = sess("alice")
    n = one("SELECT COUNT(*) FROM doc_fetchers WHERE user_id=?", (FRI,))
    r = Fr.post(B + "/api/docs/fetchers", json={"ws": "private", "name": "Laptop"})
    check(r.status_code == 503 and "code" not in r.json() and "PUBLIC_URL" in r.text,
          f"#4074 5: no PUBLIC_URL: no receipt fetcher (503, no code with the request's address) {r.status_code} {r.text[:160]}")
    check(one("SELECT COUNT(*) FROM doc_fetchers WHERE user_id=?", (FRI,)) == n, "#4074 5: and no row was made")
    # review E: the scan inbox's setup code (docs/scankeys.py) carried the same fallback to the request's Host
    n = one("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (FRI,))
    r = Fr.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Scanner"})
    check(r.status_code == 503 and "code" not in r.json() and "PUBLIC_URL" in r.text,
          f"#4074 5 review: no PUBLIC_URL: no scan inbox (503, no code with the request's address) {r.status_code} {r.text[:160]}")
    check(one("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (FRI,)) == n, "#4074 5 review: and no key was made")
    check(Fr.post(B + "/api/docs/scan-keys", json=[1]).status_code == 400, "#4074 review: a list as the body of a new scan inbox: 400")
    for p in ("/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource"):
        r = requests.get(B + p, headers={"Host": "evil.example"})
        check(r.status_code == 503 and "evil.example" not in r.text, f"#4074 5: {p} without PUBLIC_URL: 503, no foreign issuer {r.status_code} {r.text[:160]}")
    r = A.get(B + "/api/my/mcp-grants")
    check(r.ok and r.json().get("url") == "", f"the connected apps still answer, without an address {r.status_code} {r.text[:160]}")
else:
    print("P2666A_NOSTART: the restart without PUBLIC_URL is skipped", flush=True)

sys.exit(kt.done("p2666_a_haertung"))
