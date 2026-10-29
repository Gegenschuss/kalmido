#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.425.0 C API tests (#3453): receipt fetchers (a helper program that fetches invoices from portals). Invented names only,
generated PDFs.
 - a person without an organisation (her own office) connects a fetcher: the setup code decodes to {url, key, name}; the key
   (kbh_...) is stored only as a hash in its own table, never as an API token
 - the key reaches GET /fetcher, PUT /fetcher/status and POST /fetcher/documents only: every other API route 403, the web
   routes 401, an unknown key 401
 - a status report stores the portals (new ones start on); unknown fields (a password, a cookie) are refused and nothing is
   stored; a new error tells the person once (News "fetcherr"), the same error again does not, nobody else gets it, the
   notification switch "fetcher" turns it off
 - an upload: PDF only, lands in her documents with the source "abholer" and portal + order number (ext_id), recognised like
   an upload; the same file or the same order again answers duplicate (no second document); the portal must be reported
 - the person switches a portal off: the helper reads it, uploads for it 409; on again: fine
 - another person sees, switches and disconnects none of it; an account without the office has no fetchers (403), a key
   whose person turned the office off gets 403
 - an organisation's fetcher uploads into the organisation's documents; another member cannot make one of a foreign
   organisation; after its person left the organisation the key gets 403
 - disconnecting stops the key at once (401); a password change revokes the fetchers too
freelancer-matrix: files
tenant-matrix: document
usage: p2425_c_api_test.py <datadir>      (a fresh container; P2425C_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import base64
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

V = B + "/api/v1"
kt.fresh(prefix="P2425C")
A = kt.setup()
FEATS = "files,docs,comments,collab,office"


def bearer(tok):
    return {"Authorization": "Bearer " + tok}


def pdf(text):
    """A tiny generated PDF (unique per text)."""
    return b"%PDF-1.4\n1 0 obj<<>>endobj\n% " + text.encode() + b"\ntrailer<<>>\n%%EOF\n"


def decode(code):
    assert code.startswith("kalmido-fetch:1:"), code
    raw = code[len("kalmido-fetch:1:"):]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


def up(key, body, portal="amazon", order="", name="rechnung.pdf", mime="application/pdf", data=None):
    d = {"portal": portal, **({"order": order} if order else {}), **(data or {})}
    return requests.post(V + "/fetcher/documents", headers=bearer(key), files={"file": (name, body, mime)}, data=d)


def status(key, portals):
    return requests.put(V + "/fetcher/status", headers=bearer(key), json={"portals": portals})


def news(s, kind="fetcherr"):
    return [x for x in s.get(B + "/api/news").json()["items"] if x["kind"] == kind]


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol (member), frida without an organisation, gina without office
ids = {}
for u in ("bob", "carol", "gina"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG), "setup: carol joins Alpha")
FRIDA, Fr = freelancer(B, A)
Ca, Gi = sess("carol"), sess("gina")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATS})
Gi.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "files,docs,comments,collab"})

# ==== a person without an organisation: her own office (freelancer-matrix: files)
j = Fr.get(B + "/api/docs/fetchers?ws=private").json()
check(j.get("api") is True and j.get("fetchers") == [], f"frida: the API is on, no fetcher yet {j}")
ntok = len(kt.dbx("SELECT id FROM api_tokens"))
r = Fr.post(B + "/api/docs/fetchers", json={"ws": "private", "name": "Mac Studio"})
check(r.status_code == 201 and r.json().get("target") == "Your own documents", f"frida connects a fetcher {r.status_code} {r.text[:200]}")
FX, C = r.json().get("id"), decode(r.json().get("code", "kalmido-fetch:1:"))
K = C.get("key", "")
check(C.get("url", "").startswith("http") and K.startswith("kbh_") and C.get("name") == "Mac Studio", f"the setup code: url, key, name {C}")
row = kt.dbx("SELECT token_hash, user_id, org_id FROM doc_fetchers WHERE id=?", (FX,))
check(row and row[0][0] != K and K not in row[0][0] and row[0][1] == FRIDA and row[0][2] is None, f"stored as a hash only, frida's own place {row}")
check(len(kt.dbx("SELECT id FROM api_tokens")) == ntok, "no API token was made")
check(K not in json.dumps(Fr.get(B + "/api/docs/fetchers?ws=private").json()), "the key is not listed again")
r = requests.get(V + "/fetcher", headers=bearer(K))
check(r.ok and r.json().get("name") == "Mac Studio" and r.json().get("target") == "Your own documents" and r.json().get("portals") == []
      and isinstance(r.json().get("max_mb"), int), f"GET /fetcher with the key {r.text[:200]}")

# ---- the key's rights are narrow: nothing else of the API, nothing of the web app
for m, p in (("GET", "/me"), ("GET", "/documents"), ("GET", "/lists"), ("POST", "/documents"), ("GET", "/documents/upload-target"),
             ("GET", "/agent/events"), ("GET", "/files"), ("POST", "/tasks"), ("GET", "/openapi.json")):
    r = requests.request(m, V + p, headers=bearer(K), json={} if m != "GET" else None)
    ok = r.status_code == 200 if p == "/openapi.json" else r.status_code == 403 and "only upload receipts" in r.text
    check(ok, f"{m} {p} with the fetcher key: {'200 (the spec has no data)' if p == '/openapi.json' else '403'} - {r.status_code} {r.text[:120]}")
for m, p in (("GET", "/api/docs/fetchers?ws=private"), ("GET", "/api/state"), ("GET", "/api/docs?ws=private"), ("DELETE", f"/api/docs/fetchers/{FX}")):
    r = requests.request(m, B + p, headers={**bearer(K), "X-Requested-With": "kalmido"})
    check(r.status_code in (401, 403), f"web route {m} {p} with the fetcher key: 401/403 {r.status_code}")
check(requests.get(V + "/fetcher", headers=bearer("kbh_" + "x" * 43)).status_code == 401, "an unknown fetcher key: 401")
check(requests.get(V + "/fetcher", headers=bearer("abk_" + "x" * 43)).status_code == 401, "an unknown API token: 401")
r = Fr.post(B + "/api/me/tokens", json={"name": "files", "scopes": ["read", "files:write"]})
PT = r.json().get("token", "") if r.ok else ""
check(PT and requests.get(V + "/fetcher", headers=bearer(PT)).status_code == 403 and status(PT, []).status_code == 403,
      "an ordinary API token of frida reaches no fetcher route (403)")

# ---- the status report: stored, unknown fields refused (never stored)
r = up(K, pdf("vor dem Status"))
check(r.status_code == 400, f"an upload for a portal not reported yet: 400 {r.status_code}")
r = status(K, [{"key": "amazon", "name": "Amazon", "last_run": "2026-10-29T03:12:00Z", "new": 2, "error": ""}])
check(r.ok and r.json().get("portals") == [{"key": "amazon", "name": "Amazon", "enabled": True}], f"the first report: amazon is on {r.text[:200]}")
r = status(K, [{"key": "amazon", "name": "Amazon", "password": "geheim-4711"}])
check(r.status_code == 400 and r.json()["error"].get("fields") == ["password"], f"a password field: 400 unknown_field {r.text[:200]}")
r = requests.put(V + "/fetcher/status", headers=bearer(K), json={"portals": [], "cookies": "sid=geheim-4711"})
check(r.status_code == 400, f"a cookies field: 400 {r.status_code}")
dump = json.dumps(kt.dbx("SELECT * FROM doc_fetch_portals") + kt.dbx("SELECT * FROM doc_fetchers"), default=str)
check("geheim-4711" not in dump, "nothing of it is stored")
p = Fr.get(B + "/api/docs/fetchers?ws=private").json()["fetchers"][0]["portals"][0]
check(p["name"] == "Amazon" and p["new"] == 2 and p["last_run"].startswith("2026-10-29T03:12") and p["error"] == "" and p["enabled"] is True,
      f"frida sees the portal's state {p}")
check(status(K, [{"key": "Amazon!"}]).status_code == 400 and status(K, [{"key": "a", "new": -1}]).status_code == 400, "bad key / count: 400")

# ---- upload: PDF only, into her documents, source abholer + portal / order; repeats answer duplicate
r = up(K, pdf("Rechnung 302-111"), order="302-111", name="2026-10-03_Amazon_302-111.pdf")
check(r.status_code == 201 and r.json().get("duplicate") is False, f"the first receipt: 201 {r.status_code} {r.text[:200]}")
D1 = r.json().get("id")
m = kt.dbx("SELECT source, ext_id, org_id FROM doc_meta WHERE node_id=?", (D1,))
n = kt.dbx("SELECT owner_id, org_id FROM fs_nodes WHERE id=?", (D1,))
check(m and m[0][0] == "abholer" and m[0][1] == "abholer:amazon:302-111" and m[0][2] is None and n and tuple(n[0]) == (FRIDA, None),
      f"a document of frida's own, source abholer, portal + order {m} {n}")
check(kt.until(lambda: Fr.get(B + f"/api/docs/{D1}").ok, 10), "frida sees the document")
r = up(K, pdf("Rechnung 302-111"), name="nochmal.pdf")
check(r.status_code == 200 and r.json().get("duplicate") is True and r.json().get("id") == D1, f"the same file again: duplicate, the same document {r.text[:200]}")
r = up(K, pdf("Rechnung 302-111 neu geladen"), order="302-111")
check(r.status_code == 200 and r.json().get("duplicate") is True and r.json().get("id") == D1, f"the same order again: duplicate {r.text[:200]}")
check(len(kt.dbx("SELECT node_id FROM doc_meta WHERE source='abholer'")) == 1, "one document only")
check(kt.dbx("SELECT uploaded FROM doc_fetch_portals WHERE fetcher_id=? AND key='amazon'", (FX,))[0][0] == 1, "the portal counts one upload")
r = up(K, b"Rechnung als Text", name="r.txt", mime="text/plain")
check(r.status_code == 400, f"not a PDF: 400 {r.status_code}")
r = up(K, b"<html>%PDF-1.4</html>", name="r.pdf")
check(r.status_code == 400, f"a .pdf name without the PDF magic: 400 {r.status_code}")
check(up(K, pdf("x1"), data={"password": "geheim"}).status_code == 400, "an extra form field: 400")
check(requests.post(V + "/fetcher/documents", headers=bearer(K), json={"portal": "amazon"}).status_code == 400, "JSON instead of multipart: 400")
check(up(K, pdf("x2"), portal="ebay").status_code == 400, "an unknown portal: 400")
# 2.425.0 (#3453 review): larger than the upload limit (the test container: 1 MB) = 413 as docs/API.md says, nothing stored
r = up(K, b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 64), order="BIG")
check(r.status_code == 413 and not kt.dbx("SELECT 1 FROM doc_meta WHERE ext_id='abholer:amazon:BIG'"), f"too large: 413 {r.status_code}")

# ---- a new error tells frida once; the same error again does not; the switch turns it off
check(news(Fr) == [], "no notice yet")
status(K, [{"key": "amazon", "name": "Amazon", "error": "Amazon: please sign in again"}])
it = news(Fr)
check(len(it) == 1 and it[0]["data"].get("portal") == "Amazon" and it[0]["data"].get("error") == "Amazon: please sign in again" and it[0].get("to_me"),
      f"the error: one News item for frida (For you) {it}")
status(K, [{"key": "amazon", "name": "Amazon", "error": "Amazon: please sign in again"}])
check(len(news(Fr)) == 1, "the same error again: no second item")
check(news(Ca) == [] and news(Bo) == [], "nobody else gets it")
p = Fr.get(B + "/api/docs/fetchers?ws=private").json()["fetchers"][0]["portals"][0]
check(p["error"] == "Amazon: please sign in again" and p["error_at"], f"the settings show the error {p}")
status(K, [{"key": "amazon", "name": "Amazon", "error": ""}])
check(Fr.get(B + "/api/docs/fetchers?ws=private").json()["fetchers"][0]["portals"][0]["error"] == "", "fixed: the error is gone")
check(Fr.patch(B + "/api/settings", json={"notify": {"fetcher": {"news": False, "push": False}}}).ok, "frida switches the event off")
status(K, [{"key": "amazon", "name": "Amazon", "error": "Amazon: page changed"}])
check(len(news(Fr)) == 1, "switched off: no new item")
Fr.patch(B + "/api/settings", json={"notify": {"fetcher": {"news": True, "push": True}}})

# ---- the person switches a portal off; the helper reads it
r = Fr.patch(B + f"/api/docs/fetchers/{FX}/portals/amazon", json={"enabled": False})
check(r.ok, f"frida switches Amazon off {r.status_code} {r.text[:160]}")
check(requests.get(V + "/fetcher", headers=bearer(K)).json()["portals"][0]["enabled"] is False, "the helper reads it (GET /fetcher)")
check(status(K, [{"key": "amazon", "name": "Amazon"}]).json()["portals"][0]["enabled"] is False, "and in the answer of its report; a report does not switch it on")
check(up(K, pdf("aus")).status_code == 409, "an upload for a switched-off portal: 409")
check(Fr.patch(B + f"/api/docs/fetchers/{FX}/portals/amazon", json={"enabled": "no"}).status_code == 400, "enabled must be true / false")
check(Fr.patch(B + f"/api/docs/fetchers/{FX}/portals/ebay", json={"enabled": True}).status_code == 404, "an unknown portal: 404")
check(Fr.patch(B + f"/api/docs/fetchers/{FX}/portals/amazon", json={"enabled": True}).ok and up(K, pdf("wieder an")).status_code == 201, "on again: uploads work")

# ---- another person: nothing (tenant-matrix: document)
check(not any(f["id"] == FX for f in Ca.get(B + "/api/docs/fetchers?ws=private").json()["fetchers"]), "carol does not see frida's fetcher")
check(Ca.patch(B + f"/api/docs/fetchers/{FX}/portals/amazon", json={"enabled": False}).status_code == 404, "carol cannot switch frida's portal")
check(Ca.delete(B + f"/api/docs/fetchers/{FX}").status_code == 404, "carol cannot disconnect frida's fetcher")
check(requests.get(V + "/fetcher", headers=bearer(K)).json()["portals"][0]["enabled"] is True, "frida's portal is unchanged")

# ---- an account without the office: no fetchers; a key whose person turned the office off: 403
check(Gi.get(B + "/api/docs/fetchers?ws=private").status_code == 403, "gina (no office): GET 403")
check(Gi.post(B + "/api/docs/fetchers", json={"ws": "private", "name": "X"}).status_code == 403, "gina (no office): no new fetcher")
Fr.patch(B + "/api/settings", json={"features": ",".join(x for x in FEATURES.split(",") if x != "office")})
check(requests.get(V + "/fetcher", headers=bearer(K)).status_code == 403 and up(K, pdf("ohne Buero")).status_code == 403, "office off: the key gets 403")
Fr.patch(B + "/api/settings", json={"features": FEATURES})
check(requests.get(V + "/fetcher", headers=bearer(K)).ok, "office on again: fine")

# ==== an organisation: carol's fetcher of Alpha
check(Fr.post(B + "/api/docs/fetchers", json={"ws": f"org:{ORG}", "name": "X"}).status_code == 404, "frida cannot make a fetcher of Alpha")
r = Ca.post(B + "/api/docs/fetchers", json={"ws": f"org:{ORG}", "name": "Buero-PC"})
check(r.status_code == 201 and r.json().get("target") == "Alpha", f"carol connects a fetcher of Alpha {r.text[:200]}")
K2 = decode(r.json().get("code", "kalmido-fetch:1:")).get("key", "")
check(status(K2, [{"key": "telekom", "name": "Telekom"}]).ok, "carol's helper reports")
r = up(K2, pdf("Telekom Oktober"), portal="telekom", order="T-1")
D2 = r.json().get("id") if r.status_code == 201 else None
check(D2 and kt.dbx("SELECT org_id FROM fs_nodes WHERE id=?", (D2,))[0][0] == ORG, f"the receipt lands in Alpha's documents {r.text[:200]}")
check(not any(f["name"] == "Buero-PC" for f in Ca.get(B + "/api/docs/fetchers?ws=private").json()["fetchers"]), "listed with Alpha, not in carol's own")
check([f["name"] for f in Ca.get(B + f"/api/docs/fetchers?ws=org:{ORG}").json()["fetchers"]] == ["Buero-PC"], "listed with Alpha")
check(not Bo.get(B + f"/api/docs/fetchers?ws=org:{ORG}").json()["fetchers"], "bob (admin of Alpha) does not see carol's fetcher")
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{CAROL}").ok, "setup: bob takes carol out of Alpha")
check(requests.get(V + "/fetcher", headers=bearer(K2)).status_code == 403 and up(K2, pdf("danach"), portal="telekom").status_code == 403,
      "after carol left Alpha the key gets 403")
check(kt.dbx("SELECT 1 FROM doc_fetchers WHERE user_id=? AND org_id=?", (CAROL, ORG)) == [],
      "2.425.0 (#3453 review): leaving Alpha ends carol's fetcher of Alpha (coming back does not wake the old key)")

# ---- disconnect: the key stops at once; the documents stay
check(Fr.delete(B + f"/api/docs/fetchers/{FX}").ok, "frida disconnects her fetcher")
check(requests.get(V + "/fetcher", headers=bearer(K)).status_code == 401 and up(K, pdf("nach Trennen")).status_code == 401, "the key: 401")
check(kt.dbx("SELECT key FROM doc_fetch_portals WHERE fetcher_id=?", (FX,)) == [], "its portals are gone")
check(Fr.get(B + f"/api/docs/{D1}").ok, "the receipts it brought stay")
check(Fr.delete(B + f"/api/docs/fetchers/{FX}").status_code == 404, "again: 404")

# ---- a password change revokes the fetchers
r = Fr.post(B + "/api/docs/fetchers", json={"ws": "private", "name": "Laptop"})
K3 = decode(r.json().get("code", "kalmido-fetch:1:")).get("key", "") if r.ok else ""
check(K3 and requests.get(V + "/fetcher", headers=bearer(K3)).ok, "a new fetcher works")
r = Fr.patch(B + "/api/me", json={"password": "password456", "current_password": kt.PASSWORD})
check(r.ok, f"frida changes her password {r.status_code} {r.text[:160]}")
check(requests.get(V + "/fetcher", headers=bearer(K3)).status_code == 401, "after the change the fetcher key is revoked (401)")

sys.exit(kt.done("p2425_c"))
