#!/usr/bin/env python3
"""2.273.0 D (#3051) API tests, own container (kt.fresh): small data-loss fixes.
 - TickTick import: a list of the same name that is archived is NOT matched (its tasks would be invisible); a new list is made
 - CSV round trip: a Markdown line "- x" in a task's notes comes back from the Kalmido CSV without the guard apostrophe (any-CSV
   import and the table import), the export keeps the guard; a real leading apostrophe elsewhere stays
 - bank CSV: a purpose text of 450 characters is stored in full; importing the same file again is still found as a duplicate
 - deleting an office document clears version_of of the copy that pointed at it; F2: the other copies of the chain point at the
   oldest remaining one (one chain, not one per copy)
 - the upload route cleans up its files when saving fails halfway (source check: no way to force that error from outside)
freelancer-matrix: tasks, office, sheets (every part runs as a person without an organisation)
"""
import io
import os
import re

import kt
from kt import B, FAILS, OKS, check  # noqa: F401
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")

kt.fresh()
A = kt.setup(lang="en")
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": "office,sheets,clients,comments"})


def lists(s):
    return s.get(B + "/api/state").json()["lists"]


# ---- 1: TickTick into an archived list of the same name
lid = Fr.post(B + "/api/lists", json={"name": "Altes Projekt"}).json()["id"]
check(Fr.patch(B + f"/api/lists/{lid}", json={"archived": 1}).ok, "list archived")
tt = ('"Folder Name","List Name","Title","Status","taskId","Order"\n'
      '"","Altes Projekt","Importierte Aufgabe","0","t1","1"\n')
r = Fr.post(B + "/api/import/ticktick", files={"file": ("t.csv", tt.encode(), "text/csv")})
check(r.ok, "TickTick import accepted: " + r.text[:120])
same = [x for x in lists(Fr) if x["name"] == "Altes Projekt"]
tasks = Fr.get(B + "/api/state").json()["tasks"]
imp = next((t for t in tasks if t["title"] == "Importierte Aufgabe"), None)
check(imp is not None and imp["list_id"] != lid, f"#3051: the task is not in the archived list ({imp and imp['list_id']} vs {lid})")
active = [x for x in same if not x.get("archived") and x["id"] == (imp or {}).get("list_id")]
check(len(active) == 1, "#3051: it went to a new, active list of that name")

# ---- 2: CSV round trip
l2 = Fr.post(B + "/api/lists", json={"name": "Markdown"}).json()["id"]
t2 = Fr.post(B + "/api/tasks", json={"title": "Mit Liste", "list_id": l2, "content": "- eins\n- zwei"}).json()["id"]
ex = Fr.get(B + f"/api/lists/{l2}/export.csv?done=1")
check(ex.ok and "'- eins" in ex.content.decode("utf-8-sig"), "#3051: the export keeps the formula guard")
r = Fr.post(B + "/api/import/csv", files={"file": ("m.csv", ex.content, "text/csv")}, data={"list_name": "Zurueck"})
check(r.ok, "any-CSV import of the export: " + r.text[:160])
back = [t for t in Fr.get(B + "/api/state").json()["tasks"] if t["title"] == "Mit Liste" and t["id"] != t2]
cont = [Fr.get(B + f"/api/tasks/{t['id']}").json() for t in back]
cont = [(c.get("task") or c).get("content", "") for c in cont]
check(cont and all(c.startswith("- eins") for c in cont), f"#3051: notes come back without the apostrophe {cont!r}")
sheet_csv = "A;B\n'- x;'=1+1\nIt's;'plain\n".encode()
r = Fr.post(B + "/api/sheets/import", data={"space": "private", "title": "Rueckweg"}, files={"file": ("s.csv", sheet_csv, "text/csv")})
check(r.status_code == 201, "sheet import: " + r.text[:160])
sid = (r.json().get("sheet") or {}).get("id") if r.ok else None
txt = Fr.get(B + f"/api/sheets/{sid}").text if sid else ""
check("'- x" not in txt and "- x" in txt, "#3051: the table cell lost the guard apostrophe")
check("It's" in txt and "'plain" in txt, "#3051: other apostrophes stay")

# ---- 4: bank CSV, long purpose
O, D = "/api/office", "/api/office/docs"
Fr.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                                      "country": "DE", "vat_id": "DE123456789", "iban": "DE02120300000000202051"}})
words = " ".join(f"Wort{i:03d}" for i in range(60))  # 420 characters
csv_text = f"Buchungstag;Auftraggeber;Verwendungszweck;Betrag\n02.01.2026;Example Shop;{words};-4,50\n"
mp = {"date": 0, "amount": 3, "amount_in": None, "amount_out": None, "title": 2, "counterpart": 1, "decimal": ",", "date_format": "DD.MM.YYYY"}
r = Fr.post(B + O + "/bank/import", json={"text": csv_text, "filename": "k.csv", "mapping": mp})
check(r.status_code == 201 and r.json().get("count") == 1, "bank import: " + r.text[:160])
items = Fr.get(B + O + "/bank/tx").json().get("items") or []
pur = (items[0].get("purpose") if items else "") or ""
check(len(pur) == len(words) and pur.endswith("Wort059"), f"#3051: the purpose is stored in full ({len(pur)} of {len(words)})")
r = Fr.post(B + O + "/bank/import", json={"text": csv_text, "filename": "k.csv", "mapping": mp})
check((r.status_code == 400 and "othing" in r.text) or (r.ok and r.json().get("count") == 0), "#3051: the same file again is all duplicates: " + r.text[:160])

# ---- 7: delete a quotation, the copy loses version_of
CL = Fr.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]
q1 = Fr.post(B + D, json={"project_title": "Imagefilm", "client_id": CL}).json()["id"]
Fr.put(B + f"{D}/{q1}/items", json={"items": [{"kind": "service", "title": "Dreh", "qty": 1, "unit": "day", "rate": 1000}]})
r = Fr.post(B + f"{D}/{q1}/duplicate")
check(r.status_code == 201, "duplicate of a draft quotation: " + r.text[:160])
q2 = r.json()["id"]
check(Fr.get(B + f"{D}/{q2}").json().get("version_of") == q1, "the copy points at the first quotation")
r = Fr.post(B + f"{D}/{q2}/duplicate")  # 2.273.0 F2 (#3051): a third version (the chain points at the first quotation)
check(r.status_code == 201, "a second copy: " + r.text[:160])
q3 = r.json()["id"]
check(Fr.get(B + f"{D}/{q3}").json().get("version_of") == q1, "the second copy points at the first quotation too")
r = Fr.delete(B + f"{D}/{q1}")
check(r.ok, "the first quotation deleted: " + r.text[:160])
check(Fr.get(B + f"{D}/{q2}").json().get("version_of") is None, "#3051: version_of is empty once the first quotation is gone")
check(Fr.get(B + f"{D}/{q3}").json().get("version_of") == q2, "2.273.0 F2 (#3051): the rest of the chain points at the oldest remaining version")

# ---- 6: upload cleanup (source check)
src = open(os.path.join(SRC, "kalmido", "tasks", "attachments.py"), encoding="utf-8").read()
route = src[src.index("def attachment_upload"):src.index("def save_attachments")]
check(re.search(r"try:\s+e = save_attachments\(.*?except Exception:.*?unlink_files\(saved\)\s+raise", route, re.S) is not None,
      "#3051: the upload route unlinks its files when saving raises")
body = src[src.index("def save_attachments"):]
check(body.index("saved.append(rel)") < body.index("h6d_save(f, full)"), "#3051: the file is listed before it is written")
raise SystemExit(kt.done("p2273_f_small"))
