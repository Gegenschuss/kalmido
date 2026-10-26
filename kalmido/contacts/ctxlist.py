"""Contacts: the list's tools (2.119.1 A). CSV import / export next to vCard (#2080), a hint on likely duplicates when a
contact is created or imported (#2084) and managing the groups over all contacts (#2085).

CSV (#2080): Outlook (German + English), Google Contacts and a plain spreadsheet. The file is read on the server (UTF-8 with
or without BOM, UTF-16 from Excel's "Unicode text", else Windows-1252; delimiter ; , or tab), the columns get a suggested
field (ctx_guess), the person may change it (the app's mapping step), and every row becomes a vCard that takes the same
way as a .vcf file (import_vcards: batches, background, progress). A row's UID comes from its content, so importing the
same file again updates instead of doubling. The export writes the Outlook (English) header names (Outlook, Google and this
importer read them back), UTF-8 with BOM and semicolons (Excel opens it as it is) and defuses formulas (CSV injection: a
cell starting with = + - @ gets a ' in front; the importer drops it again).

Duplicates (#2084): only within the address books the person sees (my_book_ids), never merged automatically: the editor
asks before it creates a contact that has the same e-mail, phone or name as one there, and an import answers how many of
its new contacts look like one already there (the app offers the merge view for them).

Groups (#2085): groups are CATEGORIES labels of the contacts. GET lists them with their counts; renaming / deleting a label
changes every contact of the address books one may change (imported, mirrored ones stay; counted) and answers the old
labels, which POST /api/contacts/bulk action restore puts back (the app's one undo step). The contacts get a new version /
ETag and the books a new ctag (ms_write), so the phones sync the change."""
import codecs
import csv
import hashlib
import io
import json
import re

from flask import jsonify, request, Response

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, db, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_feat
from ..core.pg import like_escape
from ..core.errors import BadInput, UnknownFields
from ..contacts.model import (contact_brief, contacts_on, my_book_ids, need_book, render_vcard, vc_date, FIELD_MAX, ITEMS_MAX,
                              NOTE_MAX)

# ---- CSV (#2080)
CTX_DELIMS = (";", ",", "\t")
CTX_SAMPLE = 5
CTX_TYPES = {"email": ("home", "work", "other"), "phone": ("cell", "home", "work", "fax", "other"), "adr": ("home", "work", "other")}
CTX_ADR = ("street", "code", "city", "region", "country")
# the fields a column can go to ('' = ignore): name parts, company, typed e-mails / phones, address parts per kind, the rest
CTX_FIELDS = ("", "fn", "given", "middle", "family", "prefix", "suffix", "nickname", "org", "dept", "title",
              *[f"email:{t}" for t in CTX_TYPES["email"]], *[f"phone:{t}" for t in CTX_TYPES["phone"]],
              *[f"adr:{t}:{p}" for t in CTX_TYPES["adr"] for p in CTX_ADR], "url", "bday", "anniversary", "note", "groups")
# normalised header (ctx_norm) -> field: Outlook en / de, Google (old and new export), plain spreadsheets en / de
_H = {
    "name": "fn", "full name": "fn", "display name": "fn", "anzeigename": "fn", "vollständiger name": "fn",
    "first name": "given", "given name": "given", "vorname": "given",
    "middle name": "middle", "additional name": "middle", "weitere vornamen": "middle", "zweiter vorname": "middle",
    "last name": "family", "family name": "family", "surname": "family", "nachname": "family", "familienname": "family",
    "name prefix": "prefix", "anrede": "prefix", "titel": "prefix", "salutation": "prefix",
    "suffix": "suffix", "name suffix": "suffix", "namenszusatz": "suffix",
    "nickname": "nickname", "spitzname": "nickname",
    "company": "org", "organization": "org", "organisation": "org", "organization name": "org", "organization 1 name": "org",
    "firma": "org", "unternehmen": "org",
    "department": "dept", "organization department": "dept", "organization 1 department": "dept", "abteilung": "dept",
    "job title": "title", "organization title": "title", "organization 1 title": "title", "position": "title", "funktion": "title",
    "berufsbezeichnung": "title",
    "email": "email:home", "e mail": "email:home", "mail": "email:home", "email address": "email:home", "e mail address": "email:home",
    "e mail adresse": "email:home", "email adresse": "email:home", "e mail 2 address": "email:other", "e mail 3 address": "email:other",
    "e mail 2 adresse": "email:other", "e mail 3 adresse": "email:other", "business email": "email:work", "work email": "email:work",
    "e mail geschäftlich": "email:work", "e mail privat": "email:home",
    "mobile phone": "phone:cell", "mobile": "phone:cell", "mobiltelefon": "phone:cell", "handy": "phone:cell", "mobil": "phone:cell",
    "mobilnummer": "phone:cell", "handynummer": "phone:cell",
    "home phone": "phone:home", "home phone 2": "phone:home", "telefon privat": "phone:home", "telefon privat 2": "phone:home",
    "business phone": "phone:work", "business phone 2": "phone:work", "company main phone": "phone:work",
    "telefon geschäftlich": "phone:work", "telefon geschäftlich 2": "phone:work", "telefon firma": "phone:work",
    "business fax": "phone:fax", "home fax": "phone:fax", "fax geschäftlich": "phone:fax", "fax privat": "phone:fax", "fax": "phone:fax",
    "other phone": "phone:other", "primary phone": "phone:other", "weiteres telefon": "phone:other", "haupttelefon": "phone:other",
    "phone": "phone:other", "telephone": "phone:other", "telefon": "phone:other", "tel": "phone:other", "telefonnummer": "phone:other",
    "web page": "url", "website": "url", "webseite": "url", "homepage": "url", "url": "url", "internet": "url",
    "birthday": "bday", "geburtstag": "bday", "geburtsdatum": "bday", "date of birth": "bday",
    "anniversary": "anniversary", "jahrestag": "anniversary",
    "notes": "note", "note": "note", "notizen": "note", "notiz": "note", "bemerkung": "note", "bemerkungen": "note", "kommentar": "note",
    "categories": "groups", "kategorien": "groups", "kategorie": "groups", "group membership": "groups", "labels": "groups",
    "group": "groups", "groups": "groups", "gruppe": "groups", "gruppen": "groups",
    "street": "adr:home:street", "straße": "adr:home:street", "strasse": "adr:home:street", "address": "adr:home:street",
    "adresse": "adr:home:street", "anschrift": "adr:home:street",
    "postal code": "adr:home:code", "zip": "adr:home:code", "zip code": "adr:home:code", "postcode": "adr:home:code", "plz": "adr:home:code",
    "postleitzahl": "adr:home:code",
    "city": "adr:home:city", "ort": "adr:home:city", "stadt": "adr:home:city", "wohnort": "adr:home:city",
    "state": "adr:home:region", "region": "adr:home:region", "bundesland": "adr:home:region",
    "country": "adr:home:country", "land": "adr:home:country",
}
# Outlook: "<kind> <part>" (en: Business Street, Home Postal Code ...; de: Straße geschäftlich, Postleitzahl privat ...)
_KIND = {"home": "home", "business": "work", "other": "other", "privat": "home", "geschäftlich": "work", "weitere": "other",
         "weiterer": "other", "weiteres": "other"}
_PART = {"street": "street", "city": "city", "state": "region", "postal code": "code", "country region": "country", "country": "country",
         "straße": "street", "ort": "city", "region": "region", "bundesland kanton": "region", "postleitzahl": "code", "land region": "country"}


def ctx_norm(h):
    """A header name -> lower case words (punctuation and the '* ' of Google's labels dropped)."""
    return re.sub(r"[^\wäöüß]+", " ", (h or "").lower().replace("e-mail", "e mail")).strip()


def ctx_guess_one(h, title_is_prefix):
    n = ctx_norm(h)
    if n == "title":  # Outlook's "Title" is Mr. / Ms. (next to "Job Title"); alone it is the job title
        return "prefix" if title_is_prefix else "title"
    if n in _H:
        return _H[n]
    m = re.fullmatch(r"(home|business|other) (street|city|state|postal code|country region|country)", n)
    if m:
        return f"adr:{_KIND[m.group(1)]}:{_PART[m.group(2)]}"
    m = re.fullmatch(r"(?:(weitere|weiterer|weiteres) )?(straße|ort|region|bundesland kanton|postleitzahl|land region)(?: (privat|geschäftlich))?", n)
    if m and (m.group(1) or m.group(3)):
        return f"adr:{_KIND[m.group(1) or m.group(3)]}:{_PART[m.group(2)]}"
    # Google: "E-mail 1 - Value", "Phone 2 - Value", "Address 1 - Street", "Website 1 - Value" (the type / label columns are read with them)
    m = re.fullmatch(r"(e mail|phone|website|address) (\d+) (value|street|city|region|postal code|country)", n)
    if m:
        k, part = m.group(1), m.group(3)
        if k == "e mail":
            return "email:other"
        if k == "phone":
            return "phone:other"
        if k == "website":
            return "url"
        return "adr:home:" + {"postal code": "code"}.get(part, part)
    return ""


def ctx_guess(headers):
    norm = {ctx_norm(h) for h in headers}
    tp = "job title" in norm
    out = [ctx_guess_one(h, tp) for h in headers]
    seen = set()
    for i, f in enumerate(out):  # a single field (name, company ...) only once: the first column wins
        if f and not f.startswith(("email:", "phone:", "adr:")) and f not in ("url", "groups", "note"):
            if f in seen:
                out[i] = ""
            seen.add(f)
    return out


def ctx_decode(raw):
    """The bytes of a text file -> (text, encoding name)."""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", "replace"), "utf-16"  # 2.119.1 review F4 (#2080): a cut file is no 500
    if raw.startswith(codecs.BOM_UTF8):
        return raw[3:].decode("utf-8", "replace"), "utf-8"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace"), "windows-1252"


def ctx_delim(text):
    """The header line decides (names rarely hold a delimiter); a tie goes to the sniffer of the first lines."""
    n = {d: text.split("\n", 1)[0].count(d) for d in CTX_DELIMS}
    best = sorted(n.values(), reverse=True)
    if best[0] and best[0] != best[1]:
        return max(n, key=n.get)
    try:
        return csv.Sniffer().sniff(text[:20000], delimiters="".join(CTX_DELIMS)).delimiter
    except csv.Error:
        return ";"


def ctx_read(raw):
    """CSV bytes -> {headers, rows, delimiter, encoding}; BadInput when it is no table with a header line."""
    text, enc = ctx_decode(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text:
        raise BadInput(tr("This is not a contacts file (vCard or CSV)"))
    d = ctx_delim(text)
    try:
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=d) if any(x.strip() for x in r)]
    except csv.Error:  # 2.119.1 review F11 (#2080): e.g. a cell over csv.field_size_limit -> 400, not 500
        raise BadInput(tr("This is not a contacts file (vCard or CSV)"))
    if len(rows) < 2:
        raise BadInput(tr("This is not a contacts file (vCard or CSV)"))
    headers = [h.strip() for h in rows[0]]
    if len(headers) < 2 and not any(ctx_guess(headers)):
        raise BadInput(tr("This is not a contacts file (vCard or CSV)"))
    return {"headers": headers, "rows": rows[1:], "delimiter": d, "encoding": enc}


def ctx_preview(raw):
    t = ctx_read(raw)
    n = len(t["headers"])
    return {"format": "csv", "columns": t["headers"], "guess": ctx_guess(t["headers"]), "rows": len(t["rows"]),
            "sample": [[(r[i] if i < len(r) else "")[:80] for i in range(n)] for r in t["rows"][:CTX_SAMPLE]],
            "delimiter": {"\t": "tab"}.get(t["delimiter"], t["delimiter"]), "encoding": t["encoding"]}


def ctx_mapping(m, n):
    if m is None:
        return None
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "mapping")) from None
    if not isinstance(m, list) or len(m) > n + 50 or any(x not in CTX_FIELDS for x in m):
        raise BadInput(tr("Invalid value: {0}", "mapping"))
    return (m + [""] * n)[:n]


def ctx_cell(v):
    v = (v or "").strip()
    if len(v) > 1 and v[0] == "'" and v[1] in "=+-@":  # our own export's guard against formulas
        v = v[1:]
    return v


def ctx_date(v):
    """A date of a spreadsheet -> 'YYYY-MM-DD' / '--MM-DD' / '' (ISO, 12.05.1980, 12.5., 5/12/1980 = Outlook en)."""
    v = v.strip()
    if not v or v in ("0.0.00", "00.00.0000", "1/0/00"):
        return ""
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})?", v)
    if m:
        y = m.group(3) or ""
        if len(y) == 2:
            y = ("19" if int(y) > now_utc().year % 100 else "20") + y
        v = f"{y}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if y else f"--{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
    if m:
        v = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return vc_date(v.split(" ")[0].split("T")[0], {})


def ctx_split(v, groups=False):
    parts = re.split(r"\s*:::\s*" + (r"|\s*[;,]\s*" if groups else ""), v)
    return [x.strip() for x in parts if x.strip()]


def ctx_type(v, kind, default):
    """Google's type / label cell ('* Work', 'Mobile', 'Privat') -> one of CTX_TYPES[kind]."""
    v = ctx_norm(v)
    for words, t in (((" mobile", " cell", " mobil", " handy"), "cell"), ((" work", " business", " arbeit", " geschäftlich"), "work"),
                     ((" home", " privat", " zuhause"), "home"), ((" fax",), "fax"), ((" other", " andere", " sonstige"), "other")):
        if any((" " + v).find(w) >= 0 for w in words) and t in CTX_TYPES[kind]:
            return t
    return default


def ctx_row(headers, row, mapping):
    """One CSV row -> the contact's columns (lists as lists) or None for an empty row."""
    v = {k: "" for k in ("fn", "given", "middle", "family", "prefix", "suffix", "nickname", "org", "dept", "title", "bday", "anniversary", "note")}
    lists = {"emails": [], "phones": [], "urls": [], "groups": []}
    adrs = {}
    for i, f in enumerate(mapping):
        if not f or i >= len(row):
            continue
        val = ctx_cell(row[i])
        if not val:
            continue
        num = re.search(r"\b(\d+)\b", ctx_norm(headers[i]))
        sib = None  # Google: the "<X> N - Type" / "- Label" column next to the value
        if num:
            stem = ctx_norm(headers[i]).split(num.group(1))[0]
            for j, h in enumerate(headers):
                hn = ctx_norm(h)
                if hn in (f"{stem}{num.group(1)} type", f"{stem}{num.group(1)} label") and j < len(row):
                    sib = row[j]
        if f in ("bday", "anniversary"):
            v[f] = ctx_date(val)
        elif f == "note":
            v[f] = (v[f] + "\n" + val if v[f] else val)[:NOTE_MAX]
        elif f == "groups":
            lists["groups"] += [g for g in ctx_split(val, True) if not g.startswith("*") and g.lower() != "mycontacts"]
        elif f == "url":
            lists["urls"] += [{"value": u if re.match(r"(?i)[a-z]+:", u) else "https://" + u, "type": []} for u in ctx_split(val)]
        elif f.startswith(("email:", "phone:")):
            kind, t = f.split(":")
            t = ctx_type(sib, kind, t) if sib else t
            lists["emails" if kind == "email" else "phones"] += [{"value": x[:FIELD_MAX], "type": [t]} for x in ctx_split(val)]
        elif f.startswith("adr:"):
            _, t, part = f.split(":")
            key = (t, num.group(1) if num and "address" in ctx_norm(headers[i]) else "")
            a = adrs.setdefault(key, {"type": [ctx_type(sib, "adr", t) if sib else t]})
            a[part] = (a.get(part, "") + " " + val).strip()[:FIELD_MAX] if part == "street" else val[:FIELD_MAX]
        else:
            v[f] = re.sub(r"[\x00-\x1f\x7f]", " ", val)[:FIELD_MAX]
    if not any(v.values()) and not any(lists.values()) and not adrs:
        return None
    for k in ("emails", "phones", "urls"):
        seen, out = set(), []
        for it in lists[k]:
            key = it["value"].lower()
            if key not in seen:
                seen.add(key)
                out.append(it)
        lists[k] = out[:ITEMS_MAX]
    lists["groups"] = list(dict.fromkeys(g[:100] for g in lists["groups"]))[:ITEMS_MAX]
    v.update(lists)
    v["addresses"] = [a for a in adrs.values() if any(a.get(p) for p in CTX_ADR)][:ITEMS_MAX]
    if not v["fn"]:
        v["fn"] = " ".join(x for x in (v["prefix"], v["given"], v["middle"], v["family"], v["suffix"]) if x) or v["org"]
    v["kind"] = "org" if not (v["given"] or v["family"]) and v["org"] and v["fn"] == v["org"] else "individual"
    return v


def ctx_cards(raw, mapping=None):
    """A CSV file -> the vCards of its rows (mapping: a field per column; None = the suggestion)."""
    t = ctx_read(raw)
    m = ctx_mapping(mapping, len(t["headers"])) if mapping is not None else ctx_guess(t["headers"])
    if not any(m):
        raise BadInput(tr("Choose at least one column"))
    out, ts = [], iso(now_utc())
    for row in t["rows"]:
        v = ctx_row(t["headers"], row, m)
        if v is None:
            continue
        r = {**v, **{k: json.dumps(v[k], ensure_ascii=False) for k in ("emails", "phones", "urls", "groups", "addresses")},
             "photo": "", "extra": "", "version": "3.0", "updated_at": ts}
        # the same row imported again updates the contact it made before (no second copy)
        dig = hashlib.sha1(json.dumps(v, sort_keys=True, ensure_ascii=False).encode("utf-8"), usedforsecurity=False).hexdigest()[:20]
        r["uid"] = "csv-" + dig
        out.append(render_vcard(r))
    return out


def ctx_is_csv(raw, name=""):
    head = raw[:4096]
    if b"BEGIN:VCARD" in head.upper() or b"B\x00E\x00G\x00I\x00N\x00:\x00V\x00C\x00A\x00R\x00D" in head.upper():
        return False
    return name.lower().endswith((".csv", ".txt", ".tsv")) or any(d.encode() in head for d in CTX_DELIMS)


# the export: Outlook's English header names (Outlook, Google and ctx_guess read them back)
CTX_OUT = ("Name", "First Name", "Middle Name", "Last Name", "Title", "Suffix", "Nickname", "Company", "Department", "Job Title",
           "E-mail Address", "E-mail 2 Address", "E-mail 3 Address", "Mobile Phone", "Home Phone", "Business Phone", "Business Fax",
           "Other Phone", "Home Street", "Home City", "Home State", "Home Postal Code", "Home Country/Region", "Business Street",
           "Business City", "Business State", "Business Postal Code", "Business Country/Region", "Other Street", "Other City",
           "Other State", "Other Postal Code", "Other Country/Region", "Web Page", "Birthday", "Anniversary", "Notes", "Categories")


def ctx_safe(v):
    """CSV injection: a cell a spreadsheet would read as a formula gets a ' in front."""
    v = str(v or "")
    if v[:1] in "+-" and re.fullmatch(r"[+-][\d\s()/.-]*", v):  # 2.119.1 review F3 (#2080): a phone number stays as it is
        return v
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def ctx_jl(v):
    try:
        x = json.loads(v or "[]")
        return x if isinstance(x, list) else []
    except ValueError:
        return []


def ctx_export_row(r):
    d = dict.fromkeys(CTX_OUT, "")
    d.update({"Name": r["fn"], "First Name": r["given"], "Middle Name": r["middle"], "Last Name": r["family"], "Title": r["prefix"],
              "Suffix": r["suffix"], "Nickname": r["nickname"], "Company": r["org"], "Department": r["dept"], "Job Title": r["title"],
              "Birthday": r["bday"], "Anniversary": r["anniversary"], "Notes": r["note"], "Categories": ";".join(ctx_jl(r["groups"]))})
    for k, x in zip(("E-mail Address", "E-mail 2 Address", "E-mail 3 Address"), ctx_jl(r["emails"])):
        d[k] = x.get("value", "")
    slot, other = {"cell": "Mobile Phone", "home": "Home Phone", "work": "Business Phone", "fax": "Business Fax"}, []
    for x in ctx_jl(r["phones"]):
        k = next((slot[t] for t in (x.get("type") or []) if t in slot), None)
        if k and not d[k]:
            d[k] = x.get("value", "")
        else:
            other.append(x.get("value", ""))
    d["Other Phone"] = " ::: ".join(other)
    pre = {"home": "Home", "work": "Business"}
    for a in ctx_jl(r["addresses"]):
        p = next((pre[t] for t in (a.get("type") or []) if t in pre), "Other")
        taken = lambda q: any(d[f"{q} {f}"] for f in ("Street", "City", "Postal Code", "Country/Region"))  # noqa: E731
        p = p if not taken(p) else "Other" if not taken("Other") else None
        if p:  # a fourth address has no column (Outlook's format knows three)
            d.update({f"{p} Street": a.get("street", ""), f"{p} City": a.get("city", ""), f"{p} State": a.get("region", ""),
                      f"{p} Postal Code": a.get("code", ""), f"{p} Country/Region": a.get("country", "")})
    urls = [x.get("value", "") for x in ctx_jl(r["urls"])]
    d["Web Page"] = " ::: ".join(urls)
    return [ctx_safe(d[k]) for k in CTX_OUT]


def ctx_export(c, uid, bid):
    need_book(c, bid)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(CTX_OUT)
    for r in c.execute("SELECT * FROM contacts WHERE book_id=? AND kind!='group' AND deleted_at IS NULL ORDER BY lower(CASE WHEN family!='' THEN family ELSE fn END), id", (bid,)):
        w.writerow(ctx_export_row(r))
    return "﻿" + buf.getvalue()


@app.get("/api/books/<int:bid>/export.csv")
def books_export_csv(bid):
    need_feat("contacts")
    r = Response(ctx_export(db(), me(), bid), 200, content_type="text/csv; charset=utf-8")
    r.headers["Content-Disposition"] = 'attachment; filename="contacts-%d.csv"' % bid
    return r


# ---- duplicates (#2084)
CTX_DUP_MAX = 5        # contacts the editor's hint names
CTX_DUP_PAIRS = 100    # new contacts of an import the answer lists (with their look-alikes)


def ctx_phone_key(v):
    d = re.sub(r"\D", "", v or "")
    return d[-9:] if len(d) >= 6 else ""


def ctx_name_key(v):
    v = re.sub(r"\s+", " ", (v or "").strip().lower())
    return v if len(v) >= 3 else ""


def ctx_keys(fn, emails, phones):
    out = set()
    for e in emails:
        x = ((e.get("value") if isinstance(e, dict) else e) or "").strip().lower()
        if "@" in x:
            out.add(("email", x))
    for p in phones:
        x = ctx_phone_key((p.get("value") if isinstance(p, dict) else p) or "")
        if x:
            out.add(("phone", x))
    if ctx_name_key(fn):
        out.add(("name", ctx_name_key(fn)))
    return out


def ctx_dupes_for(c, uid, fn, emails, phones, skip=None):
    """Contacts of the visible address books with the same e-mail, phone or name -> [(row, reasons)]."""
    keys = ctx_keys(fn, emails, phones)
    books = my_book_ids(c, uid)
    if not keys or not books:
        return []
    conds, args = [], []
    for k, x in keys:
        if k == "name":
            conds.append("lower(fn)=?")
            args.append(x)
        else:
            conds.append("search ILIKE ? ESCAPE '\\'")
            args.append("%" + like_escape(x) + "%")
    q = ",".join("?" * len(books))
    rows = c.execute(f"SELECT * FROM contacts WHERE book_id IN ({q}) AND kind!='group' AND deleted_at IS NULL AND ({' OR '.join(conds)}) ORDER BY id LIMIT 200",
                     [*books, *args]).fetchall()
    out = []
    for r in rows:
        if skip and r["id"] == skip:
            continue
        hit = ctx_keys(r["fn"], ctx_jl(r["emails"]), ctx_jl(r["phones"])) & keys
        if hit:
            out.append((r, sorted({k for k, _ in hit})))
    return out[:CTX_DUP_MAX]


def ctx_dupcheck(c, uid, b):
    bad = sorted(k for k in b if k not in ("fn", "given", "family", "middle", "prefix", "suffix", "org", "emails", "phones", "id"))
    if bad:
        raise UnknownFields(bad)
    if not contacts_on(c, uid):
        raise Denied(404)
    s = {k: b.get(k) if isinstance(b.get(k), str) else "" for k in ("fn", "given", "family", "middle", "prefix", "suffix", "org")}
    fn = s["fn"].strip() or " ".join(x.strip() for x in (s["prefix"], s["given"], s["middle"], s["family"], s["suffix"]) if x.strip()) or s["org"].strip()
    lst = lambda k: [x for x in (b.get(k) or [])[:ITEMS_MAX] if isinstance(x, (str, dict))] if isinstance(b.get(k), list) else []  # noqa: E731
    skip = b.get("id") if isinstance(b.get("id"), int) else None
    return {"items": [{**contact_brief(r), "reasons": why} for r, why in ctx_dupes_for(c, uid, fn, lst("emails"), lst("phones"), skip)]}


def ctx_import_dupes(c, uid, bid, since):
    """After an import: its new contacts (book bid, id > since) that look like another contact the person sees ->
    {dupes: count, dupe_groups: [{id, fn, like: [{id, fn}]}] (at most CTX_DUP_PAIRS, each with up to 9 look-alikes)}."""
    books = my_book_ids(c, uid)
    if bid not in books:
        return {"dupes": 0, "dupe_groups": []}
    # 2.119.1 review F10 (#2084): only the books of the import's workspace (a merge never crosses it), not every book
    books = [r[0] for r in c.execute(f"SELECT id FROM books WHERE id IN ({','.join('?' * len(books))}) AND org_id IS NOT DISTINCT FROM "
                                     "(SELECT org_id FROM books WHERE id=?)", [*books, bid])]
    q = ",".join("?" * len(books))
    idx, new, names = {}, [], {}
    for r in c.execute(f"SELECT id, book_id, fn, emails, phones FROM contacts WHERE book_id IN ({q}) AND kind!='group' AND deleted_at IS NULL ORDER BY id", list(books)):
        names[r["id"]] = r["fn"]
        ks = ctx_keys(r["fn"], ctx_jl(r["emails"]), ctx_jl(r["phones"]))
        for k in ks:
            idx.setdefault(k, []).append(r["id"])
        if r["book_id"] == bid and r["id"] > since:
            new.append((r["id"], ks))
    groups, n = [], 0
    for cid, ks in new:
        other = sorted({x for k in ks for x in idx.get(k, ()) if x != cid})
        if not other:
            continue
        n += 1
        if len(groups) < CTX_DUP_PAIRS:
            groups.append({"id": cid, "fn": names[cid], "like": [{"id": x, "fn": names[x]} for x in other[:9]]})
    return {"dupes": n, "dupe_groups": groups}


def ctx_max_id(c, bid):
    return c.execute("SELECT COALESCE(MAX(id), 0) FROM contacts WHERE book_id=?", (bid,)).fetchone()[0]


@app.post("/api/contacts/dupcheck")
def contacts_dupcheck():
    """{fn?, given?, family?, org?, emails?, phones?, id? (the contact itself)} -> {items: [contact + reasons]} (reads only)."""
    need_feat("contacts")
    return jsonify(ctx_dupcheck(db(), me(), body()))


# ---- groups (#2085)
def ctx_writable(c, books):
    if not books:
        return set()
    mirrored = {r[0] for r in c.execute(f"SELECT id FROM books WHERE src_id IS NOT NULL AND id IN ({','.join('?' * len(books))})", list(books)).fetchall()}
    return {b for b, role in books.items() if role in ("owner", "edit") and b not in mirrored}


def ctx_groups(c, uid):
    if not contacts_on(c, uid):
        raise Denied(404)
    books = my_book_ids(c, uid)
    if not books:
        return {"items": []}
    w = ctx_writable(c, books)
    acc = {}
    for r in c.execute(f"SELECT book_id, groups FROM contacts WHERE book_id IN ({','.join('?' * len(books))}) AND groups!='[]' AND deleted_at IS NULL", list(books)):
        for g in dict.fromkeys(ctx_jl(r["groups"])):
            if not isinstance(g, str) or not g.strip():
                continue
            e = acc.setdefault(g.casefold(), {"name": g, "count": 0, "writable": 0})
            e["count"] += 1
            e["writable"] += r["book_id"] in w
    return {"items": sorted(acc.values(), key=lambda x: x["name"].casefold())}


def ctx_groups_change(c, uid, b):
    """{action: rename, name, to} | {action: delete, name} -> {action, changed, skipped, undo: [{id, groups}]}."""
    from ..contacts.bulk import bk_gate, ms_groups, ms_write
    bad = sorted(k for k in b if k not in ("action", "name", "to"))
    if bad:
        raise UnknownFields(bad)
    action = b.get("action")
    if action not in ("rename", "delete"):
        raise BadInput(tr("Invalid value: {0}", "action"))
    name = (ms_groups([b.get("name")] if isinstance(b.get("name"), str) else None, "name") or [""])[0]
    if not name:
        raise BadInput(tr("Invalid value: {0}", "name"))
    to = ""
    if action == "rename":
        to = (ms_groups([b.get("to")] if isinstance(b.get("to"), str) else None, "to") or [""])[0]
        if not to:
            raise BadInput(tr("A name, please"))
        if to == name:
            raise BadInput(tr("Nothing to change"))
    if not contacts_on(c, uid):
        raise Denied(404)
    books = my_book_ids(c, uid)
    if not books:
        raise Denied(404)
    w = ctx_writable(c, books)
    key = name.casefold()
    rows, todo, undo, skipped = {}, {}, [], 0
    pat = "%" + like_escape(json.dumps(name, ensure_ascii=False)) + "%"
    for r in c.execute(f"SELECT * FROM contacts WHERE book_id IN ({','.join('?' * len(books))}) AND groups ILIKE ? ESCAPE '\\' AND deleted_at IS NULL", [*books, pat]).fetchall():
        g = ctx_jl(r["groups"])
        if not any(isinstance(x, str) and x.casefold() == key for x in g):
            continue
        if r["book_id"] not in w:
            skipped += 1
            continue
        g2 = []
        for x in g:
            y = to if isinstance(x, str) and x.casefold() == key else x
            if y and y.casefold() not in {z.casefold() for z in g2}:
                g2.append(y)
        if action == "delete":
            g2 = [x for x in g2 if x.casefold() != key]
        if g2 != g:
            rows[r["id"]] = r
            todo[r["id"]] = {"groups": json.dumps(g2[:ITEMS_MAX], ensure_ascii=False)}
            # 2.119.1 review F5 (#2085): the undo value as bulk restore will take it (strings, ITEMS_MAX, no commas)
            undo.append({"id": r["id"], "groups": ms_groups([x for x in g if isinstance(x, str)][:ITEMS_MAX], "groups")})
    if not todo and not skipped:
        raise Denied(404)
    bk_gate(c, N_("Change {0} contacts at once"), len(todo))
    ts = ms_write(c, rows, todo)
    undo = [{**u, "expect": ts} for u in undo]  # 2.273.0 C (#3048): the undo leaves a contact changed again since then
    return {"action": action, "changed": len(todo), "skipped": skipped, "undo": undo}


@app.get("/api/contacts/groups")
def contacts_groups():
    need_feat("contacts")
    return jsonify(ctx_groups(db(), me()))


@app.post("/api/contacts/groups")
def contacts_groups_change():
    need_feat("contacts")
    return jsonify(ctx_groups_change(db(), me(), body()))
