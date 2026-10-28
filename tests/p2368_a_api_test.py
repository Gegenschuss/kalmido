#!/usr/bin/env python3
# kalmido-suite:
"""2.368.0 (#2979, #2987) API tests: English workspaces get English office documents and English file store folders, own
container (start.sh). Invented companies and people only. freelancer-matrix: office
 - #2979 a new office that picks the International (base) pack writes its documents in English with QUO-… numbers and the
   English cover letter; a language the admin chose stays on a pack switch, a number scheme set by hand stays too
 - #2987 the documents folder is named in the person's language ("Documents", German "Dokumente"); an existing "Dokumente"
   folder is still found (no second one), the settings name the real inbox path; a folder "Eingang" below it stays the inbox
 - each for an organisation's admin and for a person without organisation (personal office)
usage: p2368_a_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, done, sess, B, H, DATA  # noqa: E402,F401
import dbx as dbxm  # noqa: E402


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def dbx_name(nid):
    r = dbx("SELECT name FROM fs_nodes WHERE id=?", (nid,)) if nid else []
    return r[0][0] if r else None

if not os.environ.get("KMT_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, F = freelancer(B, A)
F.patch(B + "/api/settings", json={"lang": "en"})
O = "/api/office"
D = O + "/docs"
YEAR = time.localtime().tm_year


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


for who, S in (("org admin", A), ("freelancer", F)):
    # ---- #2979 the International pack chosen in a new office: English documents, QUO-… numbers
    r = S.put(B + O + "/settings", json={"pack": "XX"})
    st = r.json().get("settings") or {} if r.ok else {}
    check(r.ok and st.get("lang") == "en" and st.get("offer_scheme") == "QUO-{yyyy}-{seq:03}" and st.get("invoice_scheme") == "INV-{yyyy}-{seq:03}",
          f"{who}: #2979 base pack: language en, the pack's schemes {r.text[:300]}")
    r = S.post(B + D, json={"kind": "offer", "project_title": "Harbour film", "recipient": {"name": "Example Ltd", "lines": ["High Street 1"]}})
    j = r.json() if r.status_code == 201 else {}
    check(j.get("number") == f"QUO-{YEAR}-001", f"{who}: #2979 new quotation numbered QUO-… {r.text[:200]}")
    doc = S.get(B + f"{D}/{j.get('id')}").json() if j.get("id") else {}
    check(doc.get("lang") == "en" and "Dear Sir or Madam" in str(doc) and "Sehr geehrte" not in str(doc),
          f"{who}: #2979 the quotation is English with the English cover letter ({doc.get('lang')})")
    r = S.post(B + D, json={"kind": "invoice", "recipient": {"name": "Example Ltd", "lines": ["High Street 1"]}, "items": [{"title": "Edit", "qty": 1, "rate": 100}]})
    check(r.status_code == 201 and S.get(B + f"{D}/{r.json()['id']}").json().get("lang") == "en", f"{who}: #2979 new invoice in English {r.text[:160]}")
    # ---- a scheme set by hand stays on a switch; the pack's scheme follows the pack
    S.put(B + O + "/settings", json={"invoice_scheme": "B-{seq:03}"})
    st = S.put(B + O + "/settings", json={"pack": "DE"}).json().get("settings") or {}
    check(st.get("offer_scheme") == "KVA-{yyyy}-{seq:03}" and st.get("invoice_scheme") == "B-{seq:03}" and st.get("lang") == "de",
          f"{who}: #2979 back to DE: the pack's quotation scheme and language, the own invoice scheme stays {st.get('offer_scheme')} {st.get('invoice_scheme')} {st.get('lang')}")
    # ---- a language the admin chose stays on a switch
    S.put(B + O + "/settings", json={"lang": "de"})
    st = S.put(B + O + "/settings", json={"pack": "XX"}).json().get("settings") or {}
    check(st.get("lang") == "de" and st.get("offer_scheme") == "QUO-{yyyy}-{seq:03}",
          f"{who}: #2979 a chosen language stays, the scheme follows the pack {st.get('lang')} {st.get('offer_scheme')}")

# ---- #2987 the documents folder in the person's language
r = F.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("note.pdf", tiny_pdf("Example note"), "application/pdf"))])
check(r.status_code in (200, 201), "#2987 English: upload " + r.text[:160])
st = F.get(B + "/api/docs/settings", params={"ws": "private"}).json()
root = st.get("root_id")
check(root and dbx_name(root) == "Documents" and st.get("inbox_path") == "Documents/Inbox",
      f"#2987 English: folder Documents, settings name Documents/Inbox ({dbx_name(root)}, {st.get('inbox_path')})")
GID, G = freelancer(B, A, name="gerda")
G.patch(B + "/api/settings", json={"lang": "de"})
G.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("brief.pdf", tiny_pdf("Beispielbrief"), "application/pdf"))])
st = G.get(B + "/api/docs/settings", params={"ws": "private"}).json()
check(dbx_name(st.get("root_id")) == "Dokumente" and st.get("inbox_path") == "Dokumente/Eingang",
      f"#2987 German: folder Dokumente ({st.get('inbox_path')})")
# an English person with the German folder of before: found again, no second one; "Eingang" below it is the inbox
G.patch(B + "/api/settings", json={"lang": "en"})
r = G.post(B + "/api/files/folders", json={"name": "Eingang", "parent_id": st.get("root_id")})
check(r.status_code in (200, 201), "#2987 inbox folder made " + r.text[:120])
G.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("second.pdf", tiny_pdf("Second note"), "application/pdf"))])
st2 = G.get(B + "/api/docs/settings", params={"ws": "private"}).json()
check(st2.get("root_id") == st.get("root_id") and st2.get("inbox_path") == "Dokumente/Eingang" and
      not any(f["name"] == "Eingang" for f in st2.get("folders") or []),
      f"#2987 old German folder kept, its inbox still recognised and kept out of the folder list ({st2.get('inbox_path')}, {[f['name'] for f in st2.get('folders') or []]})")
check(len(dbx("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND owner_id=? AND org_id IS NULL AND kind='folder' AND deleted_at IS NULL", (GID,))) == 1,
      "#2987 no second documents folder after the language switch")

sys.exit(done("p2368_a_api"))
