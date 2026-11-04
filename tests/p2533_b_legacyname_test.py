#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.533.0 B (#4499) the archive import of old PDFs: file names of invoices and the client / project fields.
Invented companies and names only; the PDFs are generated here (a one-page text layer).
freelancer-matrix: office
 - one underscore before the date + _R is a recognised invoice ("657_Client_2026-03-11_R": sure, number, client, date;
   was: two underscores required, "not recognised"); a title with one or two underscores before the date as before; a last
   field before _R that is no date stays unsure
 - client and project of the file name the wrong way round ("Client_Project_KV04_..."): the address read from the PDF
   names the first field -> the proposal swap {client_name, client_id, project}; the second field naming the PDF's company,
   or no file_name sent: no swap
 - the organisation's admin and a person without an organisation (personal office) alike
usage: p2533_b_legacyname_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402

L = "/api/office/legacy"
FEAT = "cal,comments,collab,clients,office,docs,files,contacts"

kt.fresh(prefix="P2533B")
assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.put(B + "/api/office/settings", json={"company_fields": {"name": "Example Studio GmbH", "street": "Hafenweg 1", "zip": "20457",
                                                                   "city": "Hamburg", "country": "DE"}, "lang": "de", "currency": "EUR"}).ok,
      "setup: office settings")
_, Fr = freelancer(B, A)


def text_pdf(lines, tag=""):
    """A one-page PDF whose text layer holds lines top to bottom (as tests/p2561_a_api_test.py)."""
    ops, y = [], 830
    for t in lines:
        t = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT /F1 8 Tf 40 {y} Td ({t}) Tj ET")
        y -= 11
    content = ("\n".join(ops) + f"\n% {tag}").encode("cp1252")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


def pdf_to(firm, tag):
    return text_pdf(["KOSTENVORANSCHLAG", "Datum: 01.02.26", "Sehr geehrte Damen und Herren,", firm, "Lea Test", "Hauptweg 9",
                     "54321 Andersstadt", "Angebot Nr.: X-001", "Projekttitel: Beispielfilm"], tag)


def address(s, pdf, name=None, cid=""):
    data = {"client_id": str(cid)}
    if name is not None:
        data["file_name"] = name
    r = s.post(B + L + "/archive/address", files={"file": ("a.pdf", pdf, "application/pdf")}, data=data)
    return r.json() if r.ok else {"http": r.status_code, "body": r.text[:200]}


for who, s in (("org", A), ("freelancer", Fr)):
    p = f"{who}: "
    ka = s.post(B + "/api/clients", json={"name": f"Beispiel-Kakao {who} GmbH", "city": "Andersstadt", "country": "DE"}).json()["id"]
    mm = s.post(B + "/api/clients", json={"name": f"Muster{who} Medien GmbH", "city": "Andersstadt", "country": "DE"}).json()["id"]
    names = [f"657_Beispiel-Kakao {who}_2026-03-11_R.pdf", "12_Kunde_Imagefilm__2026-01-02_R.pdf", "12_Kunde_Imagefilm_2026-01-02_R.pdf",
             "12_Kunde_Titel_entwurf_R.pdf"]
    r = s.post(B + L + "/archive/parse", json={"names": names})
    check(r.ok, p + "parse " + r.text[:200])
    it = r.json().get("items") or [{}] * 4
    x = it[0]
    check(x.get("kind") == "invoice" and x.get("sure") is True and x.get("project_no") == "657" and x.get("client_id") == ka
          and x.get("date") == "2026-03-11" and x.get("project") == "",
          p + f"#4499 one underscore before the date + _R: a recognised invoice {x}")
    for y in it[1:3]:
        check(y.get("kind") == "invoice" and y.get("sure") is True and y.get("project") == "Imagefilm" and y.get("client_name") == "Kunde"
              and y.get("date") == "2026-01-02", p + f"#4499 a title before the date (one or two underscores) {y}")
    check(it[3].get("sure") is False and it[3].get("kind") == "invoice", p + f"#4499 no date before _R: unsure as before {it[3]}")

    kv = f"Muster{who}_Beteiligung_KV04_2026-02-01.pdf"
    j = address(s, pdf_to(f"Muster{who} Medien GmbH", f"{who}-1"), kv)
    check(j.get("status") == "ok" and j.get("swap") == {"client_name": f"Muster{who}", "client_id": mm, "project": "Beteiligung", "project_no": ""},
          p + f"#4499 the PDF names the first field: client and project swapped {j}")
    j = address(s, pdf_to(f"Beteiligung {who} Holding AG", f"{who}-2"), kv)
    check(j.get("status") == "ok" and not j.get("swap"), p + f"#4499 the second field is the PDF's company: no swap {j}")
    j = address(s, pdf_to(f"Muster{who} Medien GmbH", f"{who}-3"))
    check(j.get("status") == "ok" and not j.get("swap"), p + f"#4499 without file_name: no swap (as before) {j}")
    # review 2.533.0 (#4499): the second field hit another client (the file name's client_id), the first field has no client:
    # after the swap the address does not keep the wrong client, it proposes a new one
    bh = s.post(B + "/api/clients", json={"name": f"Beteiligung {who} Holding AG", "city": "Andersstadt", "country": "DE"}).json()["id"]
    j = address(s, pdf_to(f"Neufirma{who} Studio GmbH", f"{who}-4"), f"Neufirma{who}_Beteiligung_KV04_2026-02-01.pdf", bh)
    check(j.get("status") == "ok" and (j.get("swap") or {}).get("client_name") == f"Neufirma{who}" and j.get("client_id") is None
          and j.get("new_client") is True, p + f"#4499 swap away from a wrongly matched client: no client_id, new client proposed {j}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
