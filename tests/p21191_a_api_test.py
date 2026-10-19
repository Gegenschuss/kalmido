#!/usr/bin/env python3
"""2.119.1 API tests, part A: the contacts list and its tools. Invented names and example.com addresses only.
 - #2081 more than 500 contacts: GET /api/contacts gives every contact page by page (limit / offset, no overlap, the total)
 - #2080 CSV: POST /api/books/<id>/import?preview=1 reads a CSV (Outlook de in Windows-1252 with ;, Outlook en, Google with
   a BOM and ",", Excel's UTF-16 "Unicode text" with tabs) and suggests a field per column; the import with the suggestion or
   a mapping of the person's own; the same file again updates (no doubles); a bad mapping / no table: 400; read-only: refused;
   GET /api/books/<id>/export.csv (BOM, semicolons, Outlook's header names, formulas defused) reads back into the same contacts;
   the REST API's import stays vCard only
 - #2084 POST /api/contacts/dupcheck finds the same e-mail / phone (other notation) / name, only in the address books one
   sees (another organisation's never); an import answers how many new contacts look like one there (also in the background)
 - #2085 GET /api/contacts/groups counts per group; POST renames / deletes a label over the writable address books (read-only
   ones counted, contacts stay), the answer's old labels restore it (POST /api/contacts/bulk action restore = the undo step)
 - the same as a person without an organisation (freelancer)
tenant-matrix: book, contact
freelancer-matrix: pim
usage: p21191_a_api_test.py <datadir>      (a fresh container; P21191A_NOSTART=1: the container runs already)"""
import codecs
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, FEATURES  # noqa: E402

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


if not os.environ.get("P21191A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["contacts"]})
IDS = {}
for u in ("carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    IDS[u] = r.json()["id"]
Ca, Da = sess("carol"), sess("dave")
for s in (A, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": IDS["dave"]})
assert r.ok, r.text
BETA = r.json()["id"]
A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [IDS["dave"]], "admins": [IDS["dave"]]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})  # Alice and Carol share an address book in it
assert r.ok, r.text
ALPHA = r.json()["id"]
A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [ALICE, IDS["carol"]], "admins": [ALICE]})


def book(s, name, **kw):
    r = s.post(B + "/api/books", json={"name": name, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def imp(s, bid, data, name="contacts.csv", mapping=None, **params):
    files = {"file": (name, data, "text/csv")}
    form = {"mapping": json.dumps(mapping)} if mapping is not None else {}
    return s.post(B + f"/api/books/{bid}/import", params=params, files=files, data=form)


def contacts(s, **params):
    return s.get(B + "/api/contacts", params={"limit": 2000, **params}).json()


def by_name(s, fn, bid=None):
    its = [c for c in contacts(s, q=fn, **({"book_id": bid} if bid else {}))["items"] if c["fn"] == fn]
    return s.get(B + f"/api/contacts/{its[0]['id']}").json() if its else None


def card(uid, fn, email="", tel=""):
    return (f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\nFN:{fn}\r\nN:{fn.split()[-1]};{fn.split()[0]};;;\r\n"
            + (f"EMAIL:{email}\r\n" if email else "") + (f"TEL;TYPE=cell:{tel}\r\n" if tel else "") + "END:VCARD\r\n")


# ================================================================ #2081 more than 500 contacts
BIG = book(A, "Many")
vcf = "".join(card(f"m{i:04d}", f"Person{i:04d} Many") for i in range(650))
r = A.post(B + f"/api/books/{BIG}/import", files={"file": ("many.vcf", vcf.encode(), "text/vcard")})
check(r.ok and r.json().get("created") == 650, f"#2081: 650 contacts imported ({r.status_code} {r.text[:200]})")
p1 = A.get(B + "/api/contacts", params={"book_id": BIG, "limit": 500}).json()
p2 = A.get(B + "/api/contacts", params={"book_id": BIG, "limit": 500, "offset": 500}).json()
ids1, ids2 = {c["id"] for c in p1["items"]}, {c["id"] for c in p2["items"]}
check(len(ids1) == 500 and p1["total"] == 650, f"#2081: page one has 500 of 650 ({len(ids1)} {p1['total']})")
check(len(ids2) == 150 and not ids1 & ids2, f"#2081: page two has the other 150, no overlap ({len(ids2)} {len(ids1 & ids2)})")
q = A.get(B + "/api/contacts", params={"book_id": BIG, "q": "Person0649"}).json()
check(q["total"] == 1 and q["items"][0]["fn"] == "Person0649 Many", "#2081: the search finds a contact beyond the first page")

# ================================================================ #2080 CSV import
BK = book(A, "Office")
OUT_DE = ("Anrede;Vorname;Weitere Vornamen;Nachname;Firma;Abteilung;Position;Straße geschäftlich;Ort geschäftlich;"
          "Postleitzahl geschäftlich;Land/Region geschäftlich;Mobiltelefon;Telefon geschäftlich;E-Mail-Adresse;Geburtstag;Notizen;Kategorien\r\n"
          "Herr;Jürgen;;Möller;Möller Bau;Einkauf;Leiter;Hauptstraße 5;Köln;50667;Deutschland;0170 1234567;0221 99887;juergen@example.com;12.05.1980;Erster Kontakt;\"Kunden;Familie\"\r\n"
          "Frau;Grete;;Schäfer;;;;;;;;;;grete@example.com;0.0.00;;Kunden\r\n"
          ";;;;;;;;;;;;;;;;\r\n")
RAW_DE = OUT_DE.encode("cp1252")
r = imp(A, BK, RAW_DE, "outlook.csv", preview=1)
pv = r.json() if r.ok else {}
g = dict(zip(pv.get("columns", []), pv.get("guess", [])))
check(r.ok and pv.get("format") == "csv" and pv.get("encoding") == "windows-1252" and pv.get("delimiter") == ";" and pv.get("rows") == 2,
      f"#2080 preview: Outlook de read (cp1252, ;, 2 rows, the empty row skipped) ({r.status_code} {str(pv)[:300]})")
want = {"Anrede": "prefix", "Vorname": "given", "Weitere Vornamen": "middle", "Nachname": "family", "Firma": "org", "Abteilung": "dept",
        "Position": "title", "Straße geschäftlich": "adr:work:street", "Ort geschäftlich": "adr:work:city", "Postleitzahl geschäftlich": "adr:work:code",
        "Land/Region geschäftlich": "adr:work:country", "Mobiltelefon": "phone:cell", "Telefon geschäftlich": "phone:work",
        "E-Mail-Adresse": "email:home", "Geburtstag": "bday", "Notizen": "note", "Kategorien": "groups"}
check(g == want, f"#2080 preview: every Outlook de column has its field ({ {k: v for k, v in g.items() if want.get(k) != v} })")
check(pv.get("sample", [[]])[0][1:2] == ["Jürgen"], f"#2080 preview: the sample is decoded ({pv.get('sample', [[]])[0][:3]})")
check(not contacts(A, book_id=BK)["items"], "#2080 preview: nothing stored")
r = imp(A, BK, RAW_DE, "outlook.csv")
check(r.ok and r.json().get("created") == 2 and r.json().get("errors") == 0, f"#2080: imported with the suggestion ({r.status_code} {r.text[:200]})")
j = by_name(A, "Herr Jürgen Möller", BK)
check(j is not None, "#2080: the display name is made of the name parts")
if j:
    check(j["given"] == "Jürgen" and j["family"] == "Möller" and j["prefix"] == "Herr" and j["org"] == "Möller Bau" and j["dept"] == "Einkauf"
          and j["title"] == "Leiter", f"#2080: the name and company fields ({ {k: j[k] for k in ('given', 'family', 'prefix', 'org', 'dept', 'title')} })")
    check([(x["value"], x["type"]) for x in j["phones"]] == [("0170 1234567", ["cell"]), ("0221 99887", ["work"])], f"#2080: the phones with their kinds ({j['phones']})")
    check([x["value"] for x in j["emails"]] == ["juergen@example.com"], f"#2080: the e-mail ({j['emails']})")
    a = (j["addresses"] or [{}])[0]
    check((a.get("street"), a.get("code"), a.get("city"), a.get("country"), a.get("type")) == ("Hauptstraße 5", "50667", "Köln", "Deutschland", ["work"]),
          f"#2080: the business address ({j['addresses']})")
    check(j["bday"] == "1980-05-12" and j["note"] == "Erster Kontakt" and j["groups"] == ["Kunden", "Familie"],
          f"#2080: birthday 12.05.1980, note, categories ({j['bday']} {j['note']!r} {j['groups']})")
gr = by_name(A, "Frau Grete Schäfer", BK)
check(gr is not None and gr["bday"] == "" and gr["groups"] == ["Kunden"], f"#2080: Outlook's empty date 0.0.00 stays empty ({gr and gr['bday']})")
r = imp(A, BK, RAW_DE, "outlook.csv")
check(r.ok and r.json().get("created") == 0 and r.json().get("updated") == 2 and len(contacts(A, book_id=BK)["items"]) == 2,
      f"#2080: the same file again updates, no doubles ({r.text[:200]})")

# Outlook en: "Title" is the salutation next to "Job Title"; a mapping of one's own wins over the suggestion
OUT_EN = ("Title,First Name,Last Name,Job Title,Company,E-mail Address,Business Phone,Home Street,Home City,Home Postal Code,Birthday,Categories\r\n"
          "Dr.,Ann,Example,Architect,Example Ltd,ann@example.com,+44 20 7946 0000,1 High St,London,EC1A 1AA,5/12/1985,Clients\r\n")
pv = imp(A, BK, OUT_EN.encode(), "en.csv", preview=1).json()
g = dict(zip(pv["columns"], pv["guess"]))
check(pv["delimiter"] == "," and g["Title"] == "prefix" and g["Job Title"] == "title" and g["Home Postal Code"] == "adr:home:code"
      and g["Business Phone"] == "phone:work", f"#2080 preview: Outlook en ({g})")
m = [*pv["guess"]]
m[pv["columns"].index("Job Title")] = ""            # not imported
m[pv["columns"].index("Business Phone")] = "phone:cell"
r = imp(A, BK, OUT_EN.encode(), "en.csv", mapping=m)
ann = by_name(A, "Dr. Ann Example", BK)
check(r.ok and ann and ann["title"] == "" and ann["phones"][0]["type"] == ["cell"] and ann["bday"] == "1985-05-12" and ann["groups"] == ["Clients"],
      f"#2080: the own mapping (column left out, other phone kind), US date ({r.text[:200]} {ann and (ann['title'], ann['phones'], ann['bday'])})")

# Google (UTF-8 with BOM, ",", quoted cells, " ::: " in one cell, the type columns, system labels dropped)
GOO = ('Name,Given Name,Family Name,Group Membership,E-mail 1 - Type,E-mail 1 - Value,Phone 1 - Type,Phone 1 - Value,'
       'Address 1 - Type,Address 1 - Street,Address 1 - City,Organization 1 - Name,Notes\r\n'
       '"Lina Sample",Lina,Sample,"Friends ::: * myContacts",* Work,"lina@example.com ::: lina.private@example.com",Mobile,+49 30 1234567,'
       'Home,"Ring 1, Hof",Berlin,"Sample, Inc.","line one\nline two"\r\n')
pv = imp(A, BK, codecs.BOM_UTF8 + GOO.encode(), "google.csv", preview=1).json()
g = dict(zip(pv["columns"], pv["guess"]))
check(pv["encoding"] == "utf-8" and pv["columns"][0] == "Name" and g["Name"] == "fn" and g["E-mail 1 - Value"] == "email:other"
      and g["E-mail 1 - Type"] == "" and g["Address 1 - Street"] == "adr:home:street" and g["Group Membership"] == "groups",
      f"#2080 preview: Google ({g})")
r = imp(A, BK, codecs.BOM_UTF8 + GOO.encode(), "google.csv")
li = by_name(A, "Lina Sample", BK)
check(r.ok and li is not None, f"#2080: Google imported ({r.text[:200]})")
if li:
    check([(x["value"], x["type"]) for x in li["emails"]] == [("lina@example.com", ["work"]), ("lina.private@example.com", ["work"])],
          f"#2080: two e-mails of one cell, the kind from the type column ({li['emails']})")
    check(li["phones"][0]["type"] == ["cell"] and li["groups"] == ["Friends"] and li["org"] == "Sample, Inc." and li["note"] == "line one\nline two",
          f"#2080: phone kind, system label dropped, quoted comma + line break ({li['phones']} {li['groups']} {li['org']!r} {li['note']!r})")
    check(li["addresses"][0].get("street") == "Ring 1, Hof" and li["addresses"][0].get("type") == ["home"], f"#2080: the address ({li['addresses']})")

# Excel's "Unicode text": UTF-16 with tabs, a plain sheet in German
XL = "Name\tE-Mail\tTelefon\tPLZ\tOrt\r\nOtto Tabelle\totto@example.com\t030 555\t10115\tBerlin\r\n"
pv = imp(A, BK, codecs.BOM_UTF16_LE + XL.encode("utf-16-le"), "sheet.txt", preview=1).json()
check(pv["encoding"] == "utf-16" and pv["delimiter"] == "tab" and pv["guess"] == ["fn", "email:home", "phone:other", "adr:home:code", "adr:home:city"],
      f"#2080 preview: Excel Unicode text ({pv.get('encoding')} {pv.get('delimiter')} {pv.get('guess')})")
r = imp(A, BK, codecs.BOM_UTF16_LE + XL.encode("utf-16-le"), "sheet.txt")
check(r.ok and by_name(A, "Otto Tabelle", BK) is not None, f"#2080: Excel sheet imported ({r.text[:200]})")

# refusals
check(imp(A, BK, RAW_DE, "outlook.csv", mapping=["given", "nosuchfield"]).status_code == 400, "#2080: an unknown field in the mapping: 400")
check(imp(A, BK, RAW_DE, "outlook.csv", mapping=[""] * 17).status_code == 400, "#2080: a mapping without any column: 400")
check(imp(A, BK, b"just one line", "x.csv").status_code == 400, "#2080: no table: 400")
SH = book(A, "Shared", org_id=ALPHA)
r = A.put(B + f"/api/books/{SH}/members", json={"user_id": IDS["carol"], "role": "view"})
check(r.ok, f"share an address book with Carol (view) ({r.text[:200]})")
check(imp(Ca, SH, RAW_DE, "outlook.csv").status_code in (403, 404), "#2080: a view-only member cannot import")
check(imp(Ca, SH, RAW_DE, "outlook.csv", preview=1).status_code in (403, 404), "#2080: ... nor preview")
check(imp(Da, BK, RAW_DE, "outlook.csv").status_code == 404, "#2080: another organisation's person: 404")
r = A.post(B + f"/api/v1/address-books/{BK}/import", json={"vcf": OUT_DE})
check(r.status_code in (400, 401, 403), f"#2080: the REST API's import stays vCard only ({r.status_code})")

# ================================================================ #2080 CSV export
j = by_name(A, "Herr Jürgen Möller", BK)
A.patch(B + f"/api/contacts/{j['id']}", json={"note": '=HYPERLINK("https://example.com","x")', "phones": [{"value": "+49 170 1234567", "type": ["cell"]}]})
r = A.get(B + f"/api/books/{BK}/export.csv")
check(r.ok and r.headers.get("content-type", "").startswith("text/csv") and "attachment" in r.headers.get("content-disposition", ""),
      f"#2080 export: a CSV download ({r.status_code} {r.headers.get('content-type')})")
raw = r.content
check(raw.startswith(codecs.BOM_UTF8), "#2080 export: UTF-8 with BOM (Excel)")
text = raw.decode("utf-8-sig")
head = text.split("\r\n", 1)[0].split(";")
check(head[:4] == ["Name", "First Name", "Middle Name", "Last Name"] and "E-mail Address" in head and "Categories" in head,
      f"#2080 export: semicolons + Outlook's header names ({head[:6]})")
check("'=HYPERLINK" in text and "'+49 170 1234567" in text and ";=HYPERLINK" not in text, "#2080 export: formulas defused (')")
check(Ca.get(B + f"/api/books/{SH}/export.csv").ok, "#2080 export: a view-only member may export")
check(Da.get(B + f"/api/books/{BK}/export.csv").status_code == 404, "#2080 export: another organisation's person: 404")
RT = book(A, "Roundtrip")
r = imp(A, RT, raw, "export.csv")
rt = by_name(A, "Herr Jürgen Möller", RT)
check(r.ok and r.json().get("created") == len(contacts(A, book_id=BK)["items"]) and rt is not None, f"#2080 export: reads back ({r.text[:200]})")
if rt:
    check(rt["note"] == '=HYPERLINK("https://example.com","x")' and rt["phones"][0]["value"] == "+49 170 1234567" and rt["prefix"] == "Herr"
          and rt["bday"] == "1980-05-12" and rt["groups"] == ["Kunden", "Familie"] and rt["addresses"][0]["city"] == "Köln",
          f"#2080 export: the round trip keeps the fields ({rt['note']!r} {rt['phones']} {rt['prefix']} {rt['bday']} {rt['groups']})")

# ================================================================ #2084 duplicates
DUP = book(A, "Dups")
r = A.post(B + "/api/contacts", json={"book_id": DUP, "given": "Max", "family": "Muster", "emails": [{"value": "max@example.com"}],
                                       "phones": [{"value": "+49 170 7654321", "type": ["cell"]}]})
MAX = r.json()["id"]
DBK = book(Da, "Beta book", org_id=BETA)
Da.post(B + "/api/contacts", json={"book_id": DBK, "given": "Hidden", "family": "Person", "emails": [{"value": "hidden@example.com"}]})


def dc(s, **b):
    r = s.post(B + "/api/contacts/dupcheck", json=b)
    assert r.ok, r.text
    return r.json()["items"]


x = dc(A, given="Maximilian", family="Other", emails=["MAX@example.com"])
check([i["id"] for i in x] == [MAX] and x[0]["reasons"] == ["email"], f"#2084: the same e-mail (other case) ({x})")
x = dc(A, given="Somebody", phones=["0170 7654321"])
check([i["id"] for i in x] == [MAX] and x[0]["reasons"] == ["phone"], f"#2084: the same phone in another notation ({x})")
x = dc(A, given="max", family="muster")
check([i["id"] for i in x] == [MAX] and x[0]["reasons"] == ["name"], f"#2084: the same name ({x})")
check(dc(A, given="Nobody", family="Here", emails=["nobody@example.com"]) == [], "#2084: no look-alike: empty")
check(dc(A, given="Max", family="Muster", id=MAX) == [], "#2084: the contact itself does not count")
check(dc(A, given="Hidden", family="Person", emails=["hidden@example.com"]) == [], "#2084: another organisation's contact is never named")
check(dc(Da, given="Max", family="Muster", emails=["max@example.com"]) == [], "#2084: ... and the other way round")
check(dc(Ca, given="Herr Jürgen", family="Möller", emails=["juergen@example.com"]) == [], "#2084: an address book not shared with Carol stays hidden")
check(A.post(B + "/api/contacts/dupcheck", json={"bogus": 1}).status_code == 400, "#2084: unknown fields: 400")
CSV_D = "First Name;Last Name;E-mail Address\r\nMaxi;Muster;max@example.com\r\nNew;Person;new.person@example.com\r\n"
r = imp(A, DUP, CSV_D.encode(), "d.csv")
jr = r.json()
check(r.ok and jr.get("created") == 2 and jr.get("dupes") == 1 and jr["dupe_groups"][0]["like"][0]["id"] == MAX
      and jr["dupe_groups"][0]["fn"] == "Maxi Muster", f"#2084: the import names its likely duplicate ({r.text[:300]})")
BGB = book(A, "Background")
rows = "".join(f"Bg{i:03d};Row;bg{i}@example.com\r\n" for i in range(120)) + "Max;Muster;other@example.com\r\n"
r = imp(A, BGB, ("First Name;Last Name;E-mail Address\r\n" + rows).encode(), "bg.csv", background=1)
st = r.json()
for _ in range(60):
    if st.get("state") in ("done", "failed") or "import_id" not in st:
        break
    time.sleep(1)
    st = A.get(B + f"/api/books/imports/{st['import_id']}").json()
check(r.status_code == 202 and st.get("state") == "done" and st.get("created") == 121 and st.get("dupes") == 1,
      f"#2084: a background import tells its likely duplicates too ({r.status_code} {str(st)[:300]})")

# ================================================================ #2085 groups
gs = {g["name"]: g for g in A.get(B + "/api/contacts/groups").json()["items"]}
check(gs.get("Kunden", {}).get("count") == 4 and gs["Kunden"]["writable"] == 4 and "Friends" in gs and "Clients" in gs,
      f"#2085: the groups with their counts ({ {k: v['count'] for k, v in gs.items()} })")
check(not Da.get(B + "/api/contacts/groups").json()["items"], "#2085: another organisation's person sees none of them")
before = {c["id"]: c for c in contacts(A, group="Kunden")["items"]}
ua = {i: A.get(B + f"/api/contacts/{i}").json()["updated_at"] for i in before}
r = A.post(B + "/api/contacts/groups", json={"action": "rename", "name": "kunden", "to": "Customers"})
jr = r.json()
check(r.ok and jr["changed"] == 4 and jr["skipped"] == 0 and len(jr["undo"]) == 4, f"#2085: rename (any case) ({r.text[:300]})")
check({c["id"] for c in contacts(A, group="Customers")["items"]} == set(before) and not contacts(A, group="Kunden")["items"],
      "#2085: the contacts are in the new group, none in the old")
jm = by_name(A, "Herr Jürgen Möller", BK)
check(jm["groups"] == ["Customers", "Familie"], f"#2085: the label keeps its place ({jm['groups']})")
check(all(A.get(B + f"/api/contacts/{i}").json()["updated_at"] != ua[i] for i in before), "#2085: the changed contacts get a new version (CardDAV)")
r = A.post(B + "/api/contacts/bulk", json={"action": "restore", "items": jr["undo"]})
check(r.ok and r.json().get("changed") == 4 and {c["id"] for c in contacts(A, group="Kunden")["items"]} == set(before),
      f"#2085: the undo step puts the old labels back ({r.text[:200]})")
r = A.post(B + "/api/contacts/groups", json={"action": "rename", "name": "Familie", "to": "Kunden"})
jm = by_name(A, "Herr Jürgen Möller", BK)
check(r.ok and jm["groups"] == ["Kunden"], f"#2085: renaming into a group the contact has: no double ({jm['groups']})")
r = A.post(B + "/api/contacts/groups", json={"action": "delete", "name": "Clients"})
check(r.ok and r.json()["changed"] >= 1 and not contacts(A, group="Clients")["items"] and by_name(A, "Dr. Ann Example", BK) is not None,
      f"#2085: delete removes the label, the contact stays ({r.text[:200]})")
check(A.post(B + "/api/contacts/groups", json={"action": "delete", "name": "No such group"}).status_code == 404, "#2085: an unknown group: 404")
check(A.post(B + "/api/contacts/groups", json={"action": "rename", "name": "Kunden"}).status_code == 400, "#2085: rename without a new name: 400")
check(A.post(B + "/api/contacts/groups", json={"action": "merge", "name": "Kunden"}).status_code == 400, "#2085: an unknown action: 400")
A.post(B + "/api/contacts", json={"book_id": SH, "given": "Shared", "family": "One", "groups": ["Readonly"]})
gc = {g["name"]: g for g in Ca.get(B + "/api/contacts/groups").json()["items"]}
check(gc.get("Readonly", {}).get("writable") == 0 and gc["Readonly"]["count"] == 1, f"#2085: Carol sees the shared group, read-only ({gc})")
r = Ca.post(B + "/api/contacts/groups", json={"action": "delete", "name": "Readonly"})
check(r.ok and r.json()["changed"] == 0 and r.json()["skipped"] == 1 and by_name(A, "Shared One", SH)["groups"] == ["Readonly"],
      f"#2085: in a read-only address book nothing changes (counted) ({r.text[:200]})")
check(Da.post(B + "/api/contacts/groups", json={"action": "delete", "name": "Kunden"}).status_code == 404, "#2085: another organisation's person: 404")
check(contacts(A, group="Kunden")["items"], "#2085: ... and Alice's group is still there")

# ================================================================ the freelancer (no organisation)
FID, Fr = freelancer(B, A)
FB = book(Fr, "Mine")
r = imp(Fr, FB, OUT_DE.encode("cp1252"), "outlook.csv", preview=1)
check(r.ok and r.json().get("rows") == 2, f"freelancer: CSV preview ({r.status_code})")
r = imp(Fr, FB, OUT_DE.encode("cp1252"), "outlook.csv")
check(r.ok and r.json().get("created") == 2 and r.json().get("dupes") == 0, f"freelancer: CSV import, no look-alikes of others ({r.text[:200]})")
check(Fr.get(B + f"/api/books/{FB}/export.csv").ok, "freelancer: CSV export")
check(Fr.get(B + f"/api/books/{BK}/export.csv").status_code == 404, "freelancer: another person's address book: 404")
x = Fr.post(B + "/api/contacts/dupcheck", json={"given": "Jürgen", "family": "Möller", "emails": ["juergen@example.com"]}).json()["items"]
check(len(x) == 1 and x[0]["book_id"] == FB, f"freelancer: dupcheck finds only the own contact ({x})")
gf = {g["name"]: g["count"] for g in Fr.get(B + "/api/contacts/groups").json()["items"]}
check(gf == {"Kunden": 2, "Familie": 1}, f"freelancer: only the own groups ({gf})")
r = Fr.post(B + "/api/contacts/groups", json={"action": "rename", "name": "Kunden", "to": "Kundschaft"})
check(r.ok and r.json()["changed"] == 2 and contacts(A, group="Kunden")["items"], "freelancer: renames the own group, Alice's stays")

print(f"p21191_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
