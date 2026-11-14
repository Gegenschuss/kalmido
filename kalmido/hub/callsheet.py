"""2.855.0 (#1956): the call sheet of a shoot day (Film-Tagesdispo) -- a PDF to send to everybody on the day.

One shoot day = one job of the disposition (hub/dispo.py: the bookings made together, hub_bookings.job). The call sheet
takes what the app already knows -- the day, the title and the crew of the job (people, contacts, open places of a crew
function as "– ?? –"), the project (lists) and its client, the production's master data (office_company of the area: the
organisation or a freelancer's personal office), the phone numbers / e-mails of the contacts the viewer may read anyway,
the shots of the chosen day of the project's shot list (lists/shoot.py, a project of type shoot) -- and adds the day details
a person types in (hub_callsheets.data: set phone, location, parking / directions, public transport, call times per
department, shoot start, lunch, wrap, strike, weather as text, important, cast, transport) plus a directions sketch the
person uploads (hub_callsheets.sketch: PNG / JPEG, virus scan + photo metadata like every upload, files/upsafe.py up_check).
No weather, map or address service: the location's address only becomes a link "Open in maps" that the reader's device
opens (decision 09.11.2026); nothing is sent anywhere by the server. No public link (decision 04.11.2026: a PDF to send).

Rights exactly as the disposition: signed in, no agent (403), no kid account, the module "dispo" on, a member of the area
(organisations without guests / accounting, or the own personal area; else 404). Only with the industry Film & Video
(the industry of the asked area, accounts/onboarding.py ind_of_area; else 404 as if there was nothing). Saving needs a role that changes
content, carries the version read (expect_updated_at; 409 with the current state, core/conflict.py) under write_lock, and bumps
the change counter.
2.872.0 (#5532): the call sheet is a kind of the shared core (hub/dspkern.py, kind "callsheet", a part of its shoot day): the
write right is the core's (obj_need of the shoot day / the call sheet, no own check), the day details are saved by obj_write
(history, undo step of the person, rev / updated_by), the sketch through the core's adapters (its history shows a mark, never
the picture); it goes into the core's trash with the last booking of its shoot day and comes back with a booking.

GET  /api/team/dispo/callsheet/<job>?org=      the stored details + what comes from the app (auto)
PUT  /api/team/dispo/callsheet/<job>?org=      {data: {...}, sketch?: data URI | "" (remove), expect_updated_at?}
GET  /api/team/dispo/callsheet/<job>/pdf?org=  the PDF (?inline=1: shown in the browser instead of downloaded)
GET  /api/team/dispo/callsheet/<job>/sketch?org=  the stored sketch (the dialog's preview)
GET  /api/team/dispo/callsheet/<job>/history?org=  2.872.0 (#5532): who changed the call sheet when, and which details
GET  /api/team/dispo/callsheets?list=<id>      2.988.0 (#5651): the call sheets of a project (its tab "Call sheets")
POST /api/team/dispo/callsheets                {list_id, date}: a new call sheet of the project; its shoot day (one open place
                                               of the disposition on that day) is made in the background
2.986.0 (#5649): client and agency are chosen from the contacts (data.client_contact / data.agency_contact = a contact id):
the client still comes from the project's client file and a contact chosen replaces it; the agency is one contact (company +
person, phone, e-mail of the contact). Only contacts of the area's address books the viewer may read (the rule of cs_people,
cs_contact): an id of any other book is refused on saving (400) and shown nowhere (the dialog, the PDF, its distribution
line). The agency chosen is remembered at the project (lists.cs_agency_id, by a person who edits the project) and fills a new
call sheet of the project. The free texts data.client / data.agency stay as the fallback (older call sheets keep theirs).
2.993.0 (#5650): the call sheet (dialog and PDF) carries three logos in a row at the top: production left (the office logo of
the area, the one of quotations and invoices, office/pdfweb.py), agency in the middle, client right (the photo of the contact
chosen, no field of its own). A logo missing leaves its place empty, the others keep theirs. A missing contact photo can be
uploaded at the call sheet: it is saved at the contact as its photo through the contacts' own way (contacts/web.py
op_contact_edit: the contact's write right, 403 else, the person's undo step, vCard / sync) and so counts everywhere.
GET  /api/team/dispo/callsheet/<job>/logo?org=             the production's logo (PNG; 404 without one)
GET  /api/team/dispo/callsheet/<job>/photo/<contact>?org=  the photo of a contact of the area the viewer reads (404 else)
PUT  /api/team/dispo/callsheet/<job>/photo/<contact>?org=  {photo: data URI PNG / JPEG}: the contact's new photo (the logo)
2.1155.0 (#5652): the call sheet by e-mail, the PDF attached, to the distribution (crew, agency, client; see cs_mail_post).
GET  /api/team/dispo/callsheet/<job>/mail?org=   the form: the recipients, those without an address, subject, text, sender
POST /api/team/dispo/callsheet/<job>/mail?org=   {to: [...], subject?, text?, preview?}: the preview, else one mail each
2.1158.0 (#4566 A): the packing list of the shoot day (cs_pack, in auto and the PDF): the devices booked for the day (a
booking of a device, a set with its devices; from a quotation with its quantity, hub_bookings.qty) with category and
quantity, plus the rows of the quotation's equipment set without a device of the master data as text lines. What is ticked
off is part of the day details (data.pack: the keys of the ticked lines), saved like them through obj_write."""
import base64
import binascii
import hashlib
import io
import json
import os
import re
import secrets
from datetime import date
from urllib.parse import quote

from flask import Response, jsonify, request
from PIL import Image

from ..core.config import app
from ..core.i18n import LANGS, N_, lang, tr
from ..core.db import body, bump, iso, iso_ms, local_now, now_utc
from ..core.access import Denied, list_role, live_sql, WRITE_ROLES, list_archived_sql
from ..core.conflict import ccf_check
from ..core.errors import BadInput
from ..core.orgcrypt import OrgCryptError, oc_dec_fields, oc_enc_fields
from ..core.pg import insert_id, write_lock
from ..accounts.orgroles import need_org_write, org_writes
from ..accounts.onboarding import inds_of_area  # review 2.802 F3: the asked area's industry; 2.988.0 (#5651): one of several
from ..team.clients import client_rows  # review 2.802 F1
from ..collab.liste2e import le2e_mode
from ..files.scan import SC_RETRY_TEXT, sc_needs_retry
from ..files.upsafe import UploadRefused, up_check
from ..lists.shoot import sht_days
from ..lists.templates import ptype_ok
from ..office.model import pb_personal  # 2.988.0 (#5651): a private project's area
from ..office.model import office_settings  # 2.993.0 (#5650): the office logo of the area
from ..office.pdfweb import opdf_logo_path, opdf_logo_process  # 2.993.0 (#5650)
from ..office.rights import ofr_allows  # 2.1158.0 (#4566 A): the packing list's categories / text lines
from ..contacts.model import PHOTO_MAX, book_role, need_contact  # 2.993.0 (#5650): a logo = the contact's photo
from ..contacts.web import op_contact_edit  # 2.993.0 (#5650): the contacts' own way of saving it
from ..office.pdf import (A4_H, C_INK, C_INK2, C_RULE, C_RULE2, MM, PDF_CW, PDF_L, _Page, pdf_date, pdf_image_object,
                          pdf_logo_fit, pdf_text_width, pdf_wrap, pdf_write)
from .dispo import DSP_SLOT, _area, _gate, dsp_book_ids

CS_JOB_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
CS_IMG_MAX = 4 * 1024 * 1024  # the directions sketch: PNG / JPEG of at most 4 MB (a phone screenshot)
CS_IMG_PIX = 12_000_000  # 2.855.0 (#1956, review F5): and at most 12 megapixels (every PDF decodes it; a phone photo has 12)
CS_MAPS = "https://www.google.com/maps/search/?api=1&query="  # opened by the reader's device only (app, else browser)
CS_OPEN = "– ?? –"  # an open place of the crew (as on the paper call sheets)
# the editable single fields: key -> max length
CS_TEXT = {"subtitle": 200, "day_no": 12, "set_name": 120, "set_phone": 60, "client": 400, "agency": 400, "loc_name": 200,
           "loc_address": 300, "parking": 1500, "transit": 1000, "shoot_start": 20, "lunch_from": 20, "lunch_to": 20,
           "wrap": 20, "strike": 20, "weather": 400, "important": 3000, "attachments": 1000, "shot_day": 200}
# the editable tables: key -> (columns, rows at most); a cell holds at most 200 characters
CS_ROWS = {"calls": (("dept", "time"), 30),
           "contacts": (("role", "name", "phone"), 12),
           "cast": (("role", "name", "phone", "arrival", "makeup", "costume", "ready"), 60),
           "transport": (("vehicle", "from", "to", "riders", "cargo", "call"), 30)}
CS_CELL = 200
CS_REFS = ("client_contact", "agency_contact")  # 2.986.0 (#5649): contact ids of the day details
CS_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
CS_PACK_RE = re.compile(r"^(e:[1-9][0-9]{0,17}|t:[0-9a-f]{10})$")  # 2.1158.0 (#4566 A): a line of the packing list (cs_pack)
CS_PACK_MAX = 300


# ---------------------------------------------------------------- reading
def cs_gate(job):
    """(c, uid, oid, bookings of the job) for a person who may see the disposition of the job's area, else 401/403/404."""
    c, uid = _gate()
    if not CS_JOB_RE.match(job or ""):
        raise Denied(404)
    oid = _area(c, uid, request.args.get("org"))
    # review 2.802 F3: the industry of the asked area, not of the workspace switch; 2.988.0 (#5651): Film & Video among its
    # industries (2.828.0 #5511: several at once -- the first one alone hid the call sheets of an area with two)
    if "film" not in inds_of_area(c, oid):
        raise Denied(404)
    rows = [dict(r) for r in c.execute(f"SELECT * FROM hub_bookings WHERE org_id=? AND job=? AND {live_sql()} ORDER BY id",
                                       (oid, job))]
    if not rows:
        raise Denied(404)
    return c, uid, oid, rows


def cs_row(c, oid, job, trash=False):
    """The call sheet of shoot day (oid, job), decrypted; one in the core's trash only with trash=True (2.872.0, #5532)."""
    r = c.execute("SELECT * FROM hub_callsheets WHERE org_id=? AND job=?", (oid, job)).fetchone()
    if r is None or (r["deleted_at"] and not trash):
        return None
    return oc_dec_fields(c, oid, "hub_callsheets", r)


def cs_data(r):
    try:
        d = json.loads((r or {}).get("data") or "{}")
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def _first(items, prefer=()):
    """The value of the first item of a vCard list (emails / phones as JSON), a preferred type first (cell for phones)."""
    try:
        v = json.loads(items or "[]")
    except ValueError:
        return ""
    v = [x for x in v if isinstance(x, dict) and str(x.get("value") or "").strip()]
    for p in prefer:
        for x in v:
            t = x.get("type")
            if p in (t if isinstance(t, list) else [str(t or "")]) or p in str(t or "").lower():
                return str(x["value"]).strip()
    return str(v[0]["value"]).strip() if v else ""


def cs_people(c, uid, oid, rows):
    """The crew of the job: [{function, name, mail, phone, open}] in booking order. Mail / phone only from the address books
    of the area uid may read (a contact booked, or a contact with the e-mail of a member booked); never from somewhere else
    (2.855.0 review F2: not from the person's private books or another organisation's, hub/dispo.py dsp_book_ids)."""
    books = dsp_book_ids(c, uid, oid)
    q = ",".join("?" * len(books))

    def contact(cid):
        if not books:
            return None
        return c.execute(f"SELECT fn, given, family, emails, phones FROM contacts WHERE id=? AND book_id IN ({q}) AND {live_sql()}",
                         (cid, *books)).fetchone()

    def by_mail(mail):
        if not books or not mail:
            return None
        for r in c.execute(f"SELECT fn, given, family, emails, phones FROM contacts WHERE book_id IN ({q}) AND {live_sql()} "
                           "AND kind='individual' AND CAST(emails AS text) ILIKE ? ESCAPE '\\' LIMIT 20", (*books, "%" + re.sub(r"([%_\\])", r"\\\1", mail.lower()) + "%")):
            try:  # review 2.802 F4: a contact with broken e-mail JSON is skipped, not a 500
                ems = json.loads(r["emails"] or "[]")
            except ValueError:
                continue
            if any(str(x.get("value") or "").strip().lower() == mail.lower() for x in (ems if isinstance(ems, list) else []) if isinstance(x, dict)):
                return r
        return None

    out = []
    for b in rows:
        k = b["resource_kind"]
        if k not in ("user", "contact", "slot"):
            continue
        fn = (b.get("slot_name") or "").strip()
        p = {"function": fn, "name": b["res_label"] or "", "mail": "", "phone": "", "open": k == "slot"}
        if k == "slot":
            p["name"] = CS_OPEN
            p["function"] = fn or (b["res_label"] or "")
        else:
            r = contact(b["resource_id"]) if k == "contact" else None
            if k == "user":
                u = c.execute("SELECT email FROM users WHERE id=?", (b["resource_id"],)).fetchone()
                r = by_mail((u["email"] or "").strip() if u else "")
            if r:
                p["mail"] = _first(r["emails"])
                p["phone"] = _first(r["phones"], ("cell", "mobile"))
        out.append(p)
    return out


def cs_book_q(books):
    return ",".join("?" * len(books))


def cs_contact_info(r, wb=()):
    """{id, company, person, phone, email, photo, can_photo} of a contact row (2.986.0, #5649): an organisation contact is the
    company, a person carries the company of the contact's field "organisation". 2.993.0 (#5650): photo = it has one (the
    logo), can_photo = its address book is one of wb (uid edits it: the upload is offered; the server checks again)."""
    name = (r["fn"] or f"{r['given'] or ''} {r['family'] or ''}").strip()
    company, person = (name, "") if r["kind"] == "org" else ((r["org"] or "").strip(), name)
    return {"id": r["id"], "company": company, "person": person, "phone": _first(r["phones"], ("cell", "mobile")),
            "email": _first(r["emails"]), "photo": bool(r["has_photo"]), "can_photo": r["book_id"] in wb}


CS_CT_COLS = "id, book_id, kind, fn, given, family, org, emails, phones, photo<>'' AS has_photo"  # 2.993.0 (#5650): + book, photo flag


def cs_write_books(c, uid, books):
    """2.993.0 (#5650): the ids of `books` uid may change contacts in (role owner / edit, contacts/model.py book_role)."""
    if not books:
        return set()
    return {b["id"] for b in c.execute(f"SELECT * FROM books WHERE id IN ({cs_book_q(books)})", books)
            if book_role(c, uid, b) in ("owner", "edit")}


def cs_contact(c, uid, oid, cid, books=None, wb=None):
    """2.986.0 (#5649): the contact cid as cs_contact_info when it is a person / an organisation in an address book of the area
    uid may read (dsp_book_ids, the rule of cs_people), else None -- an id of another book shows nothing."""
    if not cid:
        return None
    books = dsp_book_ids(c, uid, oid) if books is None else books
    if not books:
        return None
    r = c.execute(f"SELECT {CS_CT_COLS} FROM contacts WHERE id=? AND book_id IN ({cs_book_q(books)}) "
                  f"AND kind IN ('individual', 'org') AND {live_sql()}", (int(cid), *books)).fetchone()
    return cs_contact_info(r, cs_write_books(c, uid, books) if wb is None else wb) if r else None


def cs_contacts(c, uid, oid, books=None, wb=None):
    """2.986.0 (#5649): the choice of the dialog: [{id, company, person, phone, email, photo, can_photo}] of the people and
    organisations of the area's address books uid may read (the same books as dsp_contacts of the disposition's places)."""
    books = dsp_book_ids(c, uid, oid) if books is None else books
    if not books:
        return []
    wb = cs_write_books(c, uid, books) if wb is None else wb
    return [cs_contact_info(r, wb) for r in c.execute(
        f"SELECT {CS_CT_COLS} FROM contacts WHERE book_id IN ({cs_book_q(books)}) "
        f"AND kind IN ('individual', 'org') AND {live_sql()} ORDER BY lower(fn), id LIMIT 500", books)]


def cs_project(c, uid, rows):
    """{name, client: {name, contact, phone, email, address}, list_id, shoot, agency_id, role} of the job's project, when uid
    sees it (2.986.0, #5649: + the agency remembered at the project and uid's role there)."""
    lid = next((b["list_id"] for b in rows if b.get("list_id")), None)
    role = list_role(c, lid, uid) if lid else None
    if not role:
        return {}
    r = c.execute("SELECT id, name, ptype, client_id, cs_agency_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return {}
    locked = bool(le2e_mode(c, lid))
    out = {"list_id": r["id"], "name": "" if locked else (r["name"] or ""), "client": {}, "role": role, "locked": locked,
           "agency_id": r["cs_agency_id"], "shoot": (r["ptype"] or "") == "shoot" and not locked and ptype_ok(c, uid, "shoot")}
    if r["client_id"]:
        # review 2.802 F1: the client file's own reading rules (not guests / accounting, a private client = its creator only)
        cl = next(iter(client_rows(c, uid, only=r["client_id"])), None)
        if cl:
            out["client"] = {k: (cl[k] or "") for k in ("name", "contact", "phone", "email", "address")}
    return out


def cs_production(c, oid):
    """{name, lines: [address, phone, mail], logo} of the area's master data (office_company; a personal area: the own office);
    2.993.0 (#5650): logo = the area has an office logo (cs_logo_file)."""
    r = c.execute("SELECT name, street, zip, city, email, phone FROM office_company WHERE org_id=?", (oid,)).fetchone()
    name = (r["name"] if r else "") or ""
    if not name:
        o = c.execute("SELECT name, personal_of FROM orgs WHERE id=?", (oid,)).fetchone()
        name = (o["name"] or "") if o and not o["personal_of"] else ""
    lines = []
    if r:
        lines = [x for x in ((r["street"] or "").strip(), " ".join(x for x in ((r["zip"] or "").strip(), (r["city"] or "").strip()) if x),
                             (r["phone"] or "").strip(), (r["email"] or "").strip()) if x]
    return {"name": name, "lines": lines, "logo": bool(cs_logo_file(c, oid))}


def cs_logo_file(c, oid):
    """2.993.0 (#5650): the path of the area's office logo (office/pdfweb.py opdf_logo_path, the logo of quotations and
    invoices) when it has one, else None."""
    lp = opdf_logo_path(oid)
    return lp if office_settings(c, oid).get("logo") and os.path.isfile(lp) else None


CS_PHOTO_RE = re.compile(r"data:image/(jpeg|png|gif|webp);base64,(.+)", re.S)


def cs_photo_bytes(c, cid):
    """2.993.0 (#5650): (bytes, mime) of contact cid's photo (a data URI in contacts.photo), None without one. The caller
    checked that the person reads the contact (cs_contact)."""
    r = c.execute("SELECT photo FROM contacts WHERE id=?", (int(cid),)).fetchone()
    m = CS_PHOTO_RE.fullmatch((r["photo"] if r else "") or "")
    if not m:
        return None
    try:
        return base64.b64decode(m.group(2)), "image/" + m.group(1)
    except (binascii.Error, ValueError):
        return None


def cs_shot_days(c, uid, proj):
    """[(day name, [shots])] of the project's shot list (lists/shoot.py sht_days), [] for another project type."""
    if not proj.get("shoot"):
        return []
    return sht_days(c, uid, proj["list_id"])


def cs_pack(c, uid, oid, rows):
    """2.1158.0 (#4566 A): the packing list of the shoot day: [{key, name, category, qty, set, text}] -- the devices of its
    bookings (key "e:<device>"; a set: each of its devices, set = the set's name; the same device twice = the quantities added
    up), then the rows of the quotation's equipment set without a device of the master data (key "t:<hash of the name>",
    text True). Category and the text lines only for a person who may see the equipment area (office/rights.py ofr_allows,
    like the disposition's resources); the booked devices' names everybody of the disposition sees anyway."""
    from ..office.offerdispo import odp_set_rows
    eq_ok = ofr_allows(c, uid, oid, "equipment")
    out = {}

    def add(eid, name, qty, set_name=""):
        k = f"e:{int(eid)}"
        if k in out:
            out[k]["qty"] += qty
        else:
            out[k] = {"key": k, "eid": int(eid), "name": name or "?", "category": "", "qty": qty, "set": set_name, "text": False}

    names = {}
    for b in rows:
        q = max(1, int(b.get("qty") or 1))
        if b["resource_kind"] == "equipment":
            add(b["resource_id"], b["res_label"], q)
        elif b["resource_kind"] == "set":
            r = c.execute("SELECT name, items FROM office_sets WHERE id=? AND org_id=?", (b["resource_id"], oid)).fetchone()
            try:
                items = json.loads((r["items"] if r else "") or "[]")
            except ValueError:
                items = []
            for it in items if isinstance(items, list) else []:
                if isinstance(it, dict) and str(it.get("equipment_id", "")).isdigit():
                    try:
                        n = max(1, int(float(it.get("qty") or 1)))
                    except (TypeError, ValueError):
                        n = 1
                    add(int(it["equipment_id"]), "", n * q, (r["name"] if r else "") or b["res_label"] or "")
    ids = sorted({x["eid"] for x in out.values()})
    if ids:
        for e in c.execute(f"SELECT id, name, category FROM office_equipment WHERE org_id=? AND id IN ({','.join('?' * len(ids))})", (oid, *ids)):
            names[e["id"]] = (e["name"] or "", e["category"] or "")
    for x in out.values():
        nm, cat = names.get(x["eid"], ("", ""))
        if x["name"] == "?" or not x["name"]:
            x["name"] = nm or "?"
        x["category"] = cat if eq_ok else ""
    lines = sorted(out.values(), key=lambda x: (x["category"].casefold(), x["name"].casefold(), x["eid"]))
    if eq_ok:
        seen, text = set(), {}
        for b in rows:
            m = re.match(r"^d:([1-9][0-9]{0,17}):", b.get("offer_pos") or "")
            if not m or not b.get("offer_doc") or (b["offer_doc"], m.group(1)) in seen:
                continue
            seen.add((b["offer_doc"], m.group(1)))
            dr = c.execute("SELECT lang FROM office_docs WHERE id=? AND org_id=?", (b["offer_doc"], oid)).fetchone()
            if dr is None:
                continue
            for t in odp_set_rows(c, oid, b["offer_doc"], m.group(1), dr["lang"])[1]:
                k = "t:" + hashlib.sha256(t["name"].casefold().encode()).hexdigest()[:10]
                if k in text:
                    text[k]["qty"] += t["qty"]
                else:
                    text[k] = {"key": k, "eid": None, "name": t["name"], "category": "", "qty": t["qty"], "set": "", "text": True}
        lines += list(text.values())
    return [{k: v for k, v in x.items() if k != "eid"} for x in lines[:CS_PACK_MAX]]


def cs_when(rows):
    """(first day ISO, first time "HH:MM" or "", last time or "") of the job."""
    d0 = min(b["start"][:10] for b in rows)
    st = sorted(b["start"][11:16] for b in rows if "T" in b["start"] and b["start"][:10] == d0)
    en = sorted(b["end"][11:16] for b in rows if "T" in b["end"])
    return d0, (st[0] if st else ""), (en[-1] if en and en[-1] != "23:59" else "")


def cs_auto(c, uid, oid, rows, d=None, choice=True):
    """What the call sheet takes from the app (not stored): day, title, project, client, production, crew, shot list days.
    2.986.0 (#5649): + the contacts chosen in the day details d (client_contact / agency_contact, only readable ones), the
    agency remembered at the project (agency_default) and, with choice, the contacts to choose from."""
    d0, t0, t1 = cs_when(rows)
    proj = cs_project(c, uid, rows)
    crew = cs_people(c, uid, oid, rows)
    days = cs_shot_days(c, uid, proj)
    d = d or {}
    books = dsp_book_ids(c, uid, oid)
    wb = cs_write_books(c, uid, books)  # 2.993.0 (#5650): the books whose contacts uid may give a logo
    return {"date": d0, "start": t0, "end": t1, "title": rows[0]["title"] or "", "project": proj.get("name", ""),
            "client": proj.get("client") or {}, "production": cs_production(c, oid), "crew": crew,
            "shot_days": [n for n, s in days], "list_id": proj.get("list_id"),
            "client_contact": cs_contact(c, uid, oid, d.get("client_contact"), books, wb),
            "agency_contact": cs_contact(c, uid, oid, d.get("agency_contact"), books, wb),
            "agency_default": cs_contact(c, uid, oid, proj.get("agency_id"), books, wb),
            "pack": cs_pack(c, uid, oid, rows),  # 2.1158.0 (#4566 A)
            **({"contacts": cs_contacts(c, uid, oid, books, wb)} if choice else {})}


def cs_public(c, uid, oid, job, rows, r=None):
    r = r if r is not None else cs_row(c, oid, job)
    d = cs_data(r)
    a = cs_auto(c, uid, oid, rows, d)
    # review F3: a contact id this person may not read is not handed out (cs_put keeps it when the dialog saves)
    pub = {k: v for k, v in d.items() if k not in CS_REFS or (a.get(k) or {}).get("id") == v}
    return {"job": job, "org_id": oid, "data": pub, "sketch": bool(r and r.get("sketch")),
            "sketch_url": f"/api/team/dispo/callsheet/{job}/sketch?org={oid}" if r and r.get("sketch") else "",
            "updated_at": (r or {}).get("updated_at") or "", "can_edit": org_writes(c, uid, oid), "auto": a}


# ---------------------------------------------------------------- writing
def _cell(v, n):
    if v is None:
        return ""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise BadInput(tr("Invalid data"))
    return CS_CTRL.sub("", str(v)).strip()[:n]


def cs_clean(d):
    """The editable details of a call sheet, checked: unknown keys go, texts are cut, tables keep their columns."""
    if not isinstance(d, dict):
        raise BadInput(tr("Invalid data"))
    out = {}
    for k, n in CS_TEXT.items():
        if k in d:
            out[k] = _cell(d.get(k), n)
    for k in CS_REFS:  # 2.986.0 (#5649): a contact id (cs_put checks that the person may read it); none = "" / null / 0
        v = d.get(k)
        if v in (None, "", 0):
            continue
        if isinstance(v, str) and v.strip().isdigit():
            v = int(v.strip())
        if not isinstance(v, int) or isinstance(v, bool) or not 0 < v < 2 ** 62:
            raise BadInput(tr("Invalid value: {0}", k))
        out[k] = v
    v = d.get("pack")  # 2.1158.0 (#4566 A): the ticked lines of the packing list (cs_pack keys), sorted, each once
    if v is not None:
        if not isinstance(v, list) or len(v) > CS_PACK_MAX or not all(isinstance(x, str) and CS_PACK_RE.match(x) for x in v):
            raise BadInput(tr("Invalid value: {0}", "pack"))
        out["pack"] = sorted(set(v))
    for k, (cols, most) in CS_ROWS.items():
        v = d.get(k)
        if v is None:
            continue
        if not isinstance(v, list) or len(v) > most:
            raise BadInput(tr("Invalid value: {0}", k))
        rows = []
        for x in v:
            if not isinstance(x, dict):
                raise BadInput(tr("Invalid value: {0}", k))
            row = {col: _cell(x.get(col), CS_CELL) for col in cols}
            if any(row.values()):
                rows.append(row)
        out[k] = rows
    return {k: v for k, v in out.items() if v not in ("", [])}


def cs_sketch_in(c, uid, oid, v, key="sketch"):
    """A sketch (data URI or base64) -> (base64 text, mime): PNG / JPEG only, at most CS_IMG_MAX bytes, through the shared
    upload checks (virus scan, photo metadata such as the place a photo was taken, files/upsafe.py up_check); a picture the
    scanner could not check is refused (no later scan for this one). 2.993.0 (#5650): key = the field of the messages (a
    logo: "photo")."""
    if not isinstance(v, str) or not v.strip():
        raise BadInput(tr("Invalid value: {0}", key))
    raw = v.strip()
    m = re.match(r"data:([a-z/+.-]+);base64,", raw)
    if m:
        raw = raw[m.end():]
    if len(raw) > CS_IMG_MAX * 4 // 3 + 8:
        raise BadInput(tr("The picture is too large (at most {0} MB)", CS_IMG_MAX // (1024 * 1024)))
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise BadInput(tr("Invalid value: {0}", key)) from None
    if len(data) > CS_IMG_MAX:
        raise BadInput(tr("The picture is too large (at most {0} MB)", CS_IMG_MAX // (1024 * 1024)))
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime, name = "image/png", "sketch.png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime, name = "image/jpeg", "sketch.jpg"
    else:
        raise BadInput(tr("Please select a PNG or JPEG picture"))
    try:
        data, _mime, info = up_check(c, name, data, mime, uid, oid, kind="callsheet")
    except UploadRefused as e:
        raise BadInput(str(e)) from None
    if sc_needs_retry(info.get("scan"), data):
        raise BadInput(tr(SC_RETRY_TEXT))
    if not pdf_image_object(data):
        raise BadInput(tr("Please select a PNG or JPEG picture"))
    with Image.open(io.BytesIO(data)) as im:  # the size as stored (pdf_image_object answers the scaled-down one)
        pix = im.width * im.height
    if pix > CS_IMG_PIX:
        raise BadInput(tr("The picture has too many pixels (at most {0} megapixels)", CS_IMG_PIX // 1_000_000))
    return base64.b64encode(data).decode("ascii"), mime


def cs_make(c, uid, oid, job, data=None):
    """The row of the call sheet of shoot day (oid, job) on its first save (2.872.0, #5532) or made with its project's tab
    (2.988.0, #5651, data: the first day details): the core's columns, history "create". The caller holds the lock
    hub_callsheets-<oid>-<job> and checked the shoot day's right. -> the row (decrypted)."""
    from ..core.writes import obj_history_add
    from .dspkern import DSK_CS
    now = iso_ms(now_utc())
    txt = oc_enc_fields(c, oid, "hub_callsheets", {"data": json.dumps(cs_clean(data or {}), ensure_ascii=False)})["data"]
    rid = insert_id(c, "INSERT INTO hub_callsheets(org_id, job, data, sketch, sketch_mime, owner_id, rev, created_by, "
                       "created_at, updated_by, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (oid, job, txt, "", "", uid, 1, uid, now, uid, now))
    obj_history_add(c, uid, DSK_CS, rid, {}, {}, action="create", org_id=oid)
    return cs_row(c, oid, job)


@app.get("/api/team/dispo/callsheet/<job>")
def cs_get(job):
    """The call sheet of shoot day `job` (see the module text)."""
    c, uid, oid, rows = cs_gate(job)
    return jsonify(callsheet=cs_public(c, uid, oid, job, rows))


@app.put("/api/team/dispo/callsheet/<job>")
def cs_put(job):
    """{data: {...}, sketch?: data URI (a new sketch) | "" (none), expect_updated_at?}: saves the day details (the whole
    data object replaces the stored one). 409 {callsheet: the current state} when it changed since expect_updated_at.
    2.872.0 (#5532): through the shared core (module docstring): the shoot day's write right (obj_need), the details by
    obj_write, the sketch by the core's adapters; a first save makes the row with the core's columns (history "create")."""
    from ..core.objects import obj_need
    from ..core.writes import obj_history_add, obj_write
    from .dspkern import DSK_CS, dsk_need_day, dsk_sync
    c, uid, oid, rows = cs_gate(job)
    dsk_need_day(c, uid, rows[:1])  # the core's role of the shoot day (was orgroles.need_org_write)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    data = cs_clean(b.get("data") or {})
    sketch = None
    if "sketch" in b and b["sketch"] not in (None, False):
        sketch = ("", "") if b["sketch"] == "" else cs_sketch_in(c, uid, oid, b["sketch"])
    write_lock(c, f"hub_callsheets-{oid}-{job}")
    # review 2.872 F3: the shoot day read again under the lock (a delete of its last booking meanwhile: 404, no live row beside it)
    if not c.execute(f"SELECT 1 FROM hub_bookings WHERE org_id=? AND job=? AND {live_sql()} LIMIT 1", (oid, job)).fetchone():
        raise Denied(404)
    dsk_sync(c, uid, oid, job)  # a call sheet an older version left in the trash beside live bookings comes back first
    r = cs_row(c, oid, job)
    ccf_check(b, (r or {}).get("updated_at") or "", "callsheet", lambda: cs_public(c, uid, oid, job, rows, r))
    books = dsp_book_ids(c, uid, oid)
    was, kept = (cs_data(r) if r else {}), set()  # under the lock (review F1)
    for k in CS_REFS:  # 2.986.0 (#5649): only a contact the person may read in this area (an id of another book: 400)
        if was.get(k) and not cs_contact(c, uid, oid, was[k], books) and data.get(k) in (None, was[k]):
            # review F1: a contact chosen by someone who reads a book this person does not: it stays (the dialog hides it,
            # cs_public), so a change of the place does not drop it silently
            data[k] = was[k]
            kept.add(k)
        elif data.get(k) and not cs_contact(c, uid, oid, data[k], books):
            raise BadInput(tr("Invalid value: {0}", k))
    if r is None:
        r = cs_make(c, uid, oid, job)
    rid = r["id"]
    write_lock(c, f"obj-{DSK_CS}-{int(rid)}")  # the core's lock of the object (obj_write takes it again in this transaction)
    if sketch is not None and sketch[0] != (r.get("sketch") or ""):
        # review 2.872 F1: no undo step for the picture (core/writes.py undo_skip: it is in no copy, a step of megabytes would
        # make the person's step group too big); the history notes it with a mark of its hash, never the picture
        obj_need(c, uid, DSK_CS, rid, "write")
        vals = oc_enc_fields(c, oid, "hub_callsheets", {"sketch": sketch[0]})
        c.execute("UPDATE hub_callsheets SET sketch=?, sketch_mime=?, rev=rev+1, updated_at=?, updated_by=? WHERE id=?",
                  (vals["sketch"], sketch[1], iso_ms(now_utc()), uid, rid))
        obj_history_add(c, uid, DSK_CS, rid, {"sketch": _pic_mark(r.get("sketch"))}, {"sketch": _pic_mark(sketch[0])}, org_id=oid)
    if data != cs_data(r):
        obj_write(c, uid, DSK_CS, rid, {"data": data})
    cs_agency_keep(c, uid, rows, None if "agency_contact" in kept else data.get("agency_contact"))
    bump(c)
    c.commit()
    return jsonify(callsheet=cs_public(c, uid, oid, job, rows))


def cs_agency_keep(c, uid, rows, cid):
    """2.986.0 (#5649): the agency chosen is remembered at the job's project (lists.cs_agency_id) for its next call sheet --
    by a person who edits the project (owner, project admin, editor), not in a locked project; the project's history notes
    it (the id, no contact data). Anyone else: the call sheet is saved, the project stays as it was."""
    from ..core.writes import obj_history_add
    from ..lists.lmcore import LMC_KIND
    proj = cs_project(c, uid, rows) if cid else {}
    lid = proj.get("list_id")
    if not lid or proj.get("locked") or proj.get("role") not in ("owner", "admin", "edit") or proj.get("agency_id") == cid:
        return
    write_lock(c, f"obj-list-{int(lid)}")  # the project's lock (lists/lists.py, PATCH /api/lists/<id>)
    old = c.execute(f"SELECT cs_agency_id, {list_archived_sql('')} AS archived FROM lists WHERE id=? FOR UPDATE", (lid,)).fetchone()
    if old is None or old[0] == cid or old[1]:  # review F2: an archived project stays as it is
        return
    c.execute("UPDATE lists SET cs_agency_id=? WHERE id=?", (cid, lid))
    obj_history_add(c, uid, LMC_KIND, lid, {"cs_agency_id": old[0]}, {"cs_agency_id": cid})


@app.get("/api/team/dispo/callsheet/<job>/history")
def cs_history(job):
    """2.872.0 (#5532): the history of the call sheet (the core's obj_history, newest first): [{at, name, action, fields}]
    -- fields = the day details that changed (their keys, e.g. loc_name, calls; "sketch" for the picture), never their values."""
    from ..core.writes import obj_history
    from .dspkern import DSK_CS
    c, uid, oid, _rows = cs_gate(job)
    r = cs_row(c, oid, job)
    if r is None:
        return jsonify(history=[])
    out = []
    for h in obj_history(c, uid, DSK_CS, r["id"]):
        keys = set()
        for k in set(h["before"]) | set(h["after"]):
            if k == "data":
                a, z = (cs_data(_hist_plain(c, oid, h[x].get("data"))) for x in ("before", "after"))
                keys |= {x for x in set(a) | set(z) if a.get(x) != z.get(x)}
            else:
                keys.add(k)
        out.append({"at": h["at"], "name": h["name"], "action": h["action"], "fields": sorted(keys)})
    return jsonify(history=out)


def _pic_mark(b64):
    """The history's mark of a sketch: "" (none) or "picture:<8 hex of its SHA-256>" (review 2.872 F5: a replaced picture
    differs from the one before, so the history's merge of ten minutes never drops it as "changed back")."""
    from .dspkern import DSK_SKETCH
    return f"{DSK_SKETCH}:{hashlib.sha256((b64 or '').encode()).hexdigest()[:8]}" if b64 else ""


def _hist_plain(c, oid, v):
    """A value of the history's 'data' (sealed when the organisation's encryption was on) as {"data": plain JSON text}."""
    try:
        return oc_dec_fields(c, oid, "hub_callsheets", {"data": v or "{}"})
    except OrgCryptError:  # a key rotated since: the old sealed text cannot be read any more (no details then)
        return {"data": "{}"}


@app.get("/api/team/dispo/callsheet/<job>/sketch")
def cs_sketch(job):
    """The stored directions sketch (for the dialog's preview)."""
    c, _uid, oid, _rows = cs_gate(job)
    r = cs_row(c, oid, job)
    if not r or not r.get("sketch"):
        raise Denied(404)
    try:
        data = base64.b64decode(r["sketch"])
    except (binascii.Error, ValueError):
        raise Denied(404) from None
    return Response(data, mimetype=r["sketch_mime"] if r["sketch_mime"] in ("image/png", "image/jpeg") else "application/octet-stream",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"})


# ---------------------------------------------------------------- 2.993.0 (#5650): the logos
CS_LOGO_PX = (512, 384, 256)  # a logo saved as a contact photo: at most this long edge (the first that fits PHOTO_MAX)


def cs_img_response(data, mime):
    return Response(data, mimetype=mime, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                                  "Content-Disposition": "inline"})


@app.get("/api/team/dispo/callsheet/<job>/logo")
def cs_logo(job):
    """The production's logo (the office logo of the call sheet's area) as PNG; 404 without one."""
    c, _uid, oid, _rows = cs_gate(job)
    lp = cs_logo_file(c, oid)
    if not lp:
        raise Denied(404)
    with open(lp, "rb") as fh:
        return cs_img_response(fh.read(), "image/png")


def cs_photo_contact(c, uid, oid, cid):
    """The contact cid when uid reads it in an address book of the area (cs_contact), else 404."""
    ct = cs_contact(c, uid, oid, cid)
    if not ct:
        raise Denied(404)
    return ct


@app.get("/api/team/dispo/callsheet/<job>/photo/<int:cid>")
def cs_photo(job, cid):
    """The photo (= logo) of contact cid of the area (only one uid reads, cs_contact); 404 without one."""
    c, uid, oid, _rows = cs_gate(job)
    cs_photo_contact(c, uid, oid, cid)
    got = cs_photo_bytes(c, cid)
    if not got:
        raise Denied(404)
    return cs_img_response(*got)


def cs_logo_photo(data):
    """Checked picture bytes -> a contact photo as a data URI: the office logo's picture check and clean-up (office/pdfweb.py
    opdf_logo_process: PNG / JPEG / WebP, size, orientation, 8 bit, no metadata, transparency kept), then at most CS_LOGO_PX
    on the long edge as PNG (a logo keeps its shape and transparency; no square cut as a portrait), small enough for the
    contact's photo (contacts/model.py PHOTO_MAX, the vCard / sync carry it)."""
    try:
        png, _w, _h = opdf_logo_process(data)
    except ValueError as e:
        raise BadInput(str(e)) from None
    with Image.open(io.BytesIO(png)) as im:
        im.load()
        for px in CS_LOGO_PX:
            x = im.copy()
            x.thumbnail((px, px), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            if x.mode == "RGBA":
                x.save(out, "PNG", optimize=True)
                uri = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")
            else:
                x.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
                uri = "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")
            if len(uri) <= PHOTO_MAX:
                return uri
    raise BadInput(tr("The picture is too large (at most {0} MB)", CS_IMG_MAX // (1024 * 1024)))


@app.put("/api/team/dispo/callsheet/<job>/photo/<int:cid>")
def cs_photo_put(job, cid):
    """{photo: data URI (PNG / JPEG)}: the logo of a client / agency = the photo of contact cid (a contact of the area uid
    reads, else 404), saved at the contact by the contacts' own way (op_contact_edit: the write right of the contact, 403
    else, before the picture is looked at; the person's undo step; vCard and sync). -> {contact: cs_contact_info}."""
    c, uid, oid, _rows = cs_gate(job)
    cs_photo_contact(c, uid, oid, cid)
    need_contact(c, cid, write=True, uid=uid)  # 403 for a contact uid only reads (op_contact_edit checks it again)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    raw, _mime = cs_sketch_in(c, uid, oid, b.get("photo"), "photo")  # PNG / JPEG, size, pixels, virus scan, photo metadata
    uri = cs_logo_photo(base64.b64decode(raw))
    op_contact_edit(c, uid, cid, {"photo": uri})  # commits
    return jsonify(contact=cs_photo_contact(c, uid, oid, cid))


def cs_pdf_logos(c, oid, a):
    """[(bytes or None) x 3] of the PDF's logo row: production, agency, client (the contacts chosen, cs_auto)."""
    out = []
    lp = cs_logo_file(c, oid) if a["production"].get("logo") else None
    try:
        with open(lp, "rb") as fh:
            out.append(fh.read(16 * 1024 * 1024))
    except (OSError, TypeError):
        out.append(None)
    for k in ("agency_contact", "client_contact"):
        x = a.get(k)
        got = cs_photo_bytes(c, x["id"]) if x and x.get("photo") else None
        out.append(got[0] if got and cs_logo_small(got[0]) else None)
    return out


CS_LOGO_MAX_PX = 4_000_000  # 2.993.0 (#5650, fable F3): a contact photo larger than this is no logo of the PDF


def cs_logo_small(raw):
    """2.993.0 (#5650, fable F3): True when the contact photo's header names at most CS_LOGO_MAX_PX pixels. A photo that came
    by the contacts API, CardDAV or an import is checked only for its type and length there; a small PNG of many megapixels
    would be decoded for every call sheet PDF. Only the header is read (PIL opens lazily); unreadable = no logo."""
    try:
        with Image.open(io.BytesIO(raw)) as im:
            return im.width * im.height <= CS_LOGO_MAX_PX
    except Exception:  # noqa: BLE001 - any broken image is just no logo
        return False


# ---------------------------------------------------------------- the PDF
CS_FS = 9.0
CS_LOGO_H = 16 * MM  # 2.993.0 (#5650): the height of the logo row
CS_LH = 12.2
CS_TOP = 18 * MM
CS_BOTTOM = A4_H - 20 * MM


def cs_fit(s, width, size, bold=False):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    while s and pdf_text_width(s, size, bold) > width:
        s = s[:-2] + "…" if len(s) > 2 else ""
    return s


def cs_weekday(iso_day, lg):
    names = LANGS.get(lg, {}).get("_weekdays") if lg != "en" else None
    d = date.fromisoformat(iso_day)
    i = (d.weekday() + 1) % 7  # the translation files start with Sunday
    if isinstance(names, list) and len(names) == 7:
        return names[i]
    return ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")[i]


class CsDoc:
    """The pages of one call sheet with a running y and the page break of the tables."""

    def __init__(self, lg):
        self.lg, self.pages, self.images = lg, [], {}
        self.new()

    def new(self):
        self.p = _Page()
        self.pages.append(self.p)
        self.y = CS_TOP
        return self.p

    def need(self, h):
        if self.y + h > CS_BOTTOM:
            self.new()
            return True
        return False

    def heading(self, s, size=12):
        self.need(size + 30)
        self.p.text(PDF_L, self.y, cs_fit(s, PDF_CW, size, True), size, True)
        self.y += size + 8

    def para(self, s, size=CS_FS, bold=False, color=C_INK, x=PDF_L, width=PDF_CW):
        for ln in (pdf_wrap(s, size, width, bold) if s else []):
            self.need(size * 1.4)
            self.p.text(x, self.y, ln, size, bold, color)
            self.y += size * 1.38

    def kv(self, label, value, bold=False):
        """A row "label  value" (label grey on the left, the value wrapped on the right)."""
        if not value:
            return
        lw = 46 * MM
        lines = pdf_wrap(value, CS_FS + (0.6 if bold else 0), PDF_CW - lw, bold) or [""]
        self.need(CS_LH * len(lines))
        self.p.text(PDF_L, self.y, cs_fit(label, lw - 6, CS_FS, bold), CS_FS, bold, C_INK if bold else C_INK2)
        for i, ln in enumerate(lines):
            self.p.text(PDF_L + lw, self.y + i * CS_LH, ln, CS_FS + (0.6 if bold else 0), bold)
        self.y += CS_LH * len(lines) + 1

    def table(self, title, cols, rows, group=None):
        """cols [(label, share of the width)], rows [[cell texts]] (a row ["__group__", name] = a group line)."""
        xs, x = [], PDF_L
        for _h, f in cols:
            xs.append((x, PDF_CW * f))
            x += PDF_CW * f

        def head():
            for (h, _f), (cx, cw) in zip(cols, xs):
                self.p.text(cx, self.y, cs_fit(h, cw - 4, 8.2, True), 8.2, True, C_INK2)
            self.p.line(PDF_L, self.y + 12, PDF_L + PDF_CW, self.y + 12, 0.6, C_RULE)
            self.y += 17

        self.need(60)
        self.p.text(PDF_L, self.y, cs_fit(title, PDF_CW, 12, True), 12, True)
        self.y += 20
        head()
        for r in rows:
            if r and r[0] == "__group__":
                if self.need(40):
                    head()
                self.y += 3
                self.p.text(PDF_L, self.y, cs_fit(r[1], PDF_CW, 9, True), 9, True)
                self.y += 14
                continue
            cells = [(pdf_wrap(re.sub(r"\s+", " ", str(v or "")).strip(), 8.6, cw - 6) or [""])[:4] for v, (_cx, cw) in zip(r, xs)]
            h = 4 + 11 * max(len(v) for v in cells)
            if self.need(h):
                self.p.text(PDF_L, self.y, cs_fit(title, PDF_CW, 12, True), 12, True)
                self.y += 20
                head()
            for v, (cx, _cw) in zip(cells, xs):
                for i, ln in enumerate(v):
                    self.p.text(cx, self.y + i * 11, ln, 8.6)
            self.y += h
            self.p.line(PDF_L, self.y - 2, PDF_L + PDF_CW, self.y - 2, 0.3, C_RULE2)
        self.y += 14


def cs_pdf(c, uid, oid, job, rows):
    """The bytes of the call sheet PDF of shoot day `job`."""
    lg = lang(c, uid)
    T = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    r = cs_row(c, oid, job)
    d = cs_data(r)
    a = cs_auto(c, uid, oid, rows, d, choice=False)
    cc, ac = a["client_contact"], a["agency_contact"]  # 2.986.0 (#5649): the contacts chosen (only readable ones, cs_contact)
    doc = CsDoc(lg)
    # 2.993.0 (#5650): the logo row on top: production left, agency centre, client right; a missing one leaves its place empty
    logos = [pdf_image_object(x) if x else None for x in cs_pdf_logos(c, oid, a)]
    if any(logos):
        lw = (PDF_CW - 12) / 3
        for i, img in enumerate(logos):
            if not img:
                continue
            w, h = pdf_logo_fit(img, lw, CS_LOGO_H)
            x = PDF_L if i == 0 else PDF_L + (PDF_CW - w) / 2 if i == 1 else PDF_L + PDF_CW - w
            doc.images[f"CsL{i}"] = img
            doc.p.image(f"CsL{i}", x, doc.y + (CS_LOGO_H - h) / 2, w, h)
        doc.y += CS_LOGO_H + 10
    title = a["project"] or a["title"]
    prod = a["production"]
    cast = d.get("cast") or []
    client = a["client"]
    # the distribution line: everybody of the crew, the cast, the client's contact person (2.986.0, #5649: + the agency's)
    names = [x["name"] for x in a["crew"] if not x["open"]] + [x.get("name", "") for x in cast] + \
        [cc["person"] if cc else client.get("contact", ""), ac["person"] if ac else ""]
    seen, dist = set(), []
    for n in names:
        n = (n or "").strip()
        if n and n.casefold() not in seen:
            seen.add(n.casefold())
            dist.append(n)
    if dist:
        doc.para(T(N_("Distribution: {0}"), ", ".join(dist)), 7.6, color=C_INK2)
        doc.y += 4
    doc.para(title, 18, True)
    if d.get("subtitle") or (a["project"] and a["title"] and a["title"] != a["project"]):
        doc.para(d.get("subtitle") or a["title"], 11, color=C_INK2)
    doc.y += 8
    # three columns: production | client (and agency) | contacts
    cw3 = (PDF_CW - 12) / 3
    cols = []
    cols.append((T(N_("Production")), [prod["name"]] + prod["lines"]))
    cl = []
    card = lambda x: [v for v in (x["company"], x["person"], x["phone"], x["email"]) if v]  # noqa: E731
    if cc:
        cl += card(cc)
    elif d.get("client"):
        cl += d["client"].splitlines()
    elif client:
        cl += [client.get("name", ""), client.get("contact", ""), client.get("address", ""), client.get("phone", ""), client.get("email", "")]
    if ac:
        cl += ["", T(N_("Agency")) + ":"] + card(ac)
    elif d.get("agency"):
        cl += ["", T(N_("Agency")) + ":"] + d["agency"].splitlines()
    cols.append((T(N_("Client")), cl))
    contacts = d.get("contacts") or [{"role": x["function"], "name": x["name"], "phone": x["phone"]} for x in a["crew"] if x["function"] and not x["open"]][:8]
    cols.append((T(N_("Contacts")), [" ".join(v for v in (x.get("role", "") + (":" if x.get("role") else ""), x.get("name", ""), x.get("phone", "")) if v)
                                 for x in contacts]))
    y0, ymax = doc.y, doc.y
    for i, (h, lines) in enumerate(cols):
        x = PDF_L + i * (cw3 + 6)
        y = y0
        doc.p.text(x, y, cs_fit(h, cw3, 8.2, True), 8.2, True, C_INK2)
        y += 13
        for j, ln in enumerate(x for x in lines if x is not None):
            for w in (pdf_wrap(ln.strip(), 8.6, cw3 - 4, j == 0 and i < 2) if ln.strip() else [""])[:3]:
                if w:
                    doc.p.text(x, y, w, 8.6, j == 0 and i < 2)
                y += 11
            if y > y0 + 150:
                break
        ymax = max(ymax, y)
    doc.y = ymax + 8
    # the set phone, highlighted
    if d.get("set_phone") or d.get("set_name"):
        s = T(N_("Set phone")) + ": " + " – ".join(v for v in (d.get("set_name", ""), d.get("set_phone", "")) if v)
        doc.p.rect(PDF_L, doc.y - 3, PDF_CW, 18, "#fff2b3")
        doc.p.text(PDF_L + 6, doc.y + 1, cs_fit(s, PDF_CW - 12, 10.5, True), 10.5, True)
        doc.y += 24
    # DISPOSITION weekday, date (+ n. shoot day)
    day = a["date"]
    head = T(N_("CALL SHEET")) + " " + cs_weekday(day, lg) + ", " + pdf_date(day, lg)
    if d.get("day_no"):
        head += " · " + T(N_("Shoot day {0}"), d["day_no"])
    doc.p.line(PDF_L, doc.y, PDF_L + PDF_CW, doc.y, 0.8, C_INK)
    doc.y += 6
    doc.para(head, 14, True)
    doc.y += 4
    # location
    if d.get("loc_name") or d.get("loc_address"):
        doc.heading(T(N_("Location")), 11)
        doc.kv(T(N_("Location")), d.get("loc_name", ""), True)
        doc.kv(T(N_("Address")), d.get("loc_address", ""))
        if d.get("loc_address"):
            doc.need(CS_LH)
            lbl = T(N_("Open in maps"))
            doc.p.text(PDF_L + 46 * MM, doc.y, lbl, CS_FS, False, "#1a56b0")
            doc.p.uri(PDF_L + 46 * MM, doc.y - 1, pdf_text_width(lbl, CS_FS) + 2, CS_LH, CS_MAPS + quote(d["loc_address"], safe=""))
            doc.y += CS_LH + 1
        doc.kv(T(N_("Parking / directions")), d.get("parking", ""))
        doc.kv(T(N_("Public transport")), d.get("transit", ""))
        doc.y += 4
    # times
    doc.heading(T(N_("Times")), 11)
    for x in d.get("calls") or []:
        doc.kv(T(N_("Call on set: {0}"), x.get("dept", "")) if x.get("dept") else T(N_("Call on set")), x.get("time", ""))
    if not d.get("calls") and a["start"]:
        doc.kv(T(N_("Call on set")), a["start"])
    doc.kv(T(N_("Shoot start")), d.get("shoot_start", ""), True)
    if d.get("lunch_from") or d.get("lunch_to"):
        doc.kv(T(N_("Lunch break")), " – ".join(v for v in (d.get("lunch_from", ""), d.get("lunch_to", "")) if v))
    doc.kv(T(N_("Wrap")), d.get("wrap", "") or a["end"], True)
    doc.kv(T(N_("Strike until")), d.get("strike", ""), True)
    doc.kv(T(N_("Weather")), d.get("weather", ""))
    doc.y += 4
    if d.get("important"):
        lines = pdf_wrap(d["important"], 10, PDF_CW - 16, True)
        h = 22 + len(lines) * 13.5
        doc.need(h)
        doc.p.rect(PDF_L, doc.y, PDF_CW, h, C_INK, stroke=True, lw=1.2)
        doc.p.text(PDF_L + 8, doc.y + 6, T(N_("IMPORTANT")), 9, True)
        for i, ln in enumerate(lines):
            doc.p.text(PDF_L + 8, doc.y + 19 + i * 13.5, ln, 10, True)
        doc.y += h + 10
    # the attachments
    shots = []
    if d.get("shot_day"):
        shots = next((s for n, s in cs_shot_days(c, uid, {"shoot": bool(a["shot_days"]), "list_id": a["list_id"]}) if n == d["shot_day"]), [])
    att = [T(N_("Crew list"))] + ([T(N_("Cast"))] if cast else []) + ([T(N_("Transport"))] if d.get("transport") else []) + \
          ([T(N_("Shots of the day"))] if shots else []) + ([T(N_("Packing list"))] if a["pack"] else []) + \
          ([T(N_("Directions sketch"))] if r and r.get("sketch") else []) + \
          [x.strip() for x in (d.get("attachments") or "").splitlines() if x.strip()]
    doc.kv(T(N_("Attachments")), ", ".join(att))
    # page 2+: cast, crew, transport, shots
    doc.new()
    if cast:
        doc.table(T(N_("Cast")), [(T(N_("Role")), .16), (T(N_("Name")), .2), (T(N_("Phone")), .16), (T(N_("Arrival")), .12), (T(N_("Make-up")), .12),
                              (T(N_("Costume")), .12), (T(N_("Ready")), .12)],
                  [[x.get(k, "") for k in ("role", "name", "phone", "arrival", "makeup", "costume", "ready")] for x in cast])
    crew_rows = [["__group__", T(N_("Crew"))]] + [[x["function"], x["name"], x["mail"], x["phone"]] for x in a["crew"]]
    if cast:
        crew_rows += [["__group__", T(N_("Cast"))]] + [[x.get("role", ""), x.get("name", ""), "", x.get("phone", "")] for x in cast]
    if ac:
        crew_rows += [["__group__", T(N_("Agency"))], [ac["company"], ac["person"], ac["email"], ac["phone"]]]
    elif d.get("agency"):
        crew_rows += [["__group__", T(N_("Agency"))], ["", d["agency"].splitlines()[0], "", ""]]
    if cc:
        crew_rows += [["__group__", T(N_("Client"))], [cc["company"], cc["person"], cc["email"], cc["phone"]]]
    elif client.get("contact") or client.get("name"):
        crew_rows += [["__group__", T(N_("Client"))], [client.get("name", ""), client.get("contact", ""), client.get("email", ""), client.get("phone", "")]]
    doc.table(T(N_("Crew list")), [(T(N_("Function")), .24), (T(N_("Name")), .26), (T(N_("E-mail")), .3), (T(N_("Phone")), .2)], crew_rows)
    if d.get("transport"):
        doc.table(T(N_("Transport")), [(T(N_("Vehicle / driver")), .2), (T(N_("From")), .16), (T(N_("To")), .16), (T(N_("Passengers")), .18), (T(N_("Cargo")), .14),
                                   (T(N_("Call time")), .16)],
                  [[x.get("vehicle", ""), x.get("from", ""), x.get("to", ""), x.get("riders", ""), x.get("cargo", ""),
                    x.get("call", "") or T(N_("Own arrangement"))] for x in d["transport"]])
    if a["pack"]:  # 2.1158.0 (#4566 A): the packing list, ticked lines with [x]
        ticked = set(d.get("pack") or [])
        doc.table(T(N_("Packing list")), [("", .06), (T(N_("Device")), .46), (T(N_("Category")), .3), (T(N_("Quantity")), .18)],
                  [["[x]" if x["key"] in ticked else "[  ]", x["name"] + (f" ({x['set']})" if x["set"] else ""), x["category"],
                    str(x["qty"])] for x in a["pack"]])
    if shots:
        doc.table(T(N_("Shots of the day")) + ": " + d["shot_day"], [(T(N_("No.")), .07), (T(N_("Shot|shoot")), .33), (T(N_("Scene|shot")), .12),
                                                                 (T(N_("Shot size")), .16), (T(N_("Lens|shot")), .12), (T(N_("Location|shot")), .2)],
                  [[s["no"], s["title"], s.get("Scene|shot", ""), s.get("Shot size", ""), s.get("Lens|shot", ""), s.get("Location|shot", "")]
                   for s in shots])
    # the directions sketch: a page of its own, the parking / directions text below it
    if r and r.get("sketch"):
        try:
            img = pdf_image_object(base64.b64decode(r["sketch"]))
        except (binascii.Error, ValueError):
            img = None
        if img:
            doc.new()
            doc.images["Cs1"] = img
            doc.heading(T(N_("Directions sketch")), 12)
            w, h = img[0], img[1]
            box_h = CS_BOTTOM - doc.y - 120
            sc = min(PDF_CW / w, box_h / h)
            doc.p.image("Cs1", PDF_L, doc.y, w * sc, h * sc)
            doc.y += h * sc + 12
            if d.get("parking"):
                doc.para(T(N_("Parking / directions")), 9, True)
                doc.para(d["parking"], 9.5)
    # the footer of every page: company – project – as of, page n of N
    stand = local_now()
    foot = " – ".join(v for v in (prod["name"], title, T(N_("As of: {0}"), pdf_date(stand.date().isoformat(), lg) + " " + stand.strftime("%H:%M"))) if v)
    n = len(doc.pages)
    for i, pg in enumerate(doc.pages, 1):
        pg.line(PDF_L, A4_H - 15 * MM, PDF_L + PDF_CW, A4_H - 15 * MM, 0.4, C_RULE)
        pr = T(N_("Page {0} of {1}"), i, n)
        pw = pdf_text_width(pr, 7.6)
        pg.text(PDF_L, A4_H - 13 * MM, cs_fit(foot, PDF_CW - pw - 12, 7.6), 7.6, False, C_INK2)
        pg.text(PDF_L + PDF_CW - pw, A4_H - 13 * MM, pr, 7.6, False, C_INK2)
    return pdf_write(doc.pages, doc.images, title=T(N_("Call sheet")) + ": " + title, author=prod["name"])


def cs_pdf_name(rows):
    """The file name of the call sheet PDF of the job's bookings rows (download and mail attachment)."""
    fn = (re.sub(r"[^A-Za-z0-9._-]+", "-", rows[0]["title"] or "")[:50].strip("-") or "shoot") + "-" + min(b["start"][:10] for b in rows)
    return f"callsheet-{fn}.pdf"


@app.get("/api/team/dispo/callsheet/<job>/pdf")
def cs_pdf_route(job):
    """The call sheet of shoot day `job` as a PDF (see the module text)."""
    c, uid, oid, rows = cs_gate(job)
    data = cs_pdf(c, uid, oid, job, rows)
    disp = "inline" if request.args.get("inline") else "attachment"
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'{disp}; filename="{cs_pdf_name(rows)}"',
                                                               "Cache-Control": "no-store"})


# ---------------------------------------------------------------- 2.1155.0 (#5652): the call sheet by e-mail
# Decision of 14.11.2026: the call sheet goes out as a mail with the PDF attached; every recipient of the distribution
# (crew, agency, client) can be left out one by one; before sending there is always a preview with the recipients, the
# subject, the text and the PDF; no link. The mail leaves the way the office's document mails leave (office/mailsig.py: the
# person's signature, sender name, the workspace's mailbox or the server's address, Reply-To) and counts against the same
# day's limits (office/invoices.py h6c_send_budget, inv_own_text_quota); each recipient gets a mail of their own (the
# addresses of the crew and the client are not shown to one another). Only addresses of the distribution can be chosen --
# no address typed in -- so the call sheet is no way to mail anything to anybody.
CS_MAIL_MAX = 60  # recipients of one send at most (the crew of a big shoot day, agency and client)
CS_MAIL_TEXT = 5000
CS_MAIL_RE = re.compile(r"[^@\s,;<>()\"'\[\]]+@[^@\s,;<>()\"'\[\]]+\.[^@\s,;<>()\"'\[\]]+")
CS_GROUPS = ("crew", "agency", "client")


def cs_mail_rcpts(c, uid, oid, job, rows):
    """The distribution of the call sheet by e-mail: ([{email, name, group: crew | agency | client, role}] each address once,
    crew in booking order, then the agency, then the client; [{name, group, role}] of those without an address). Only the
    addresses the call sheet itself shows the person: the crew's from the area's address books (cs_people), the contacts
    chosen (cs_contact), else an address in the free text of agency / client, else the client file's (client_rows)."""
    d = cs_data(cs_row(c, oid, job))
    a = cs_auto(c, uid, oid, rows, d, choice=False)
    out, none, seen = [], [], set()

    def add(group, name, mail, role=""):
        mail, name, role = (mail or "").strip(), (name or "").strip(), (role or "").strip()
        if mail and len(mail) <= 254 and CS_MAIL_RE.fullmatch(mail):
            if mail.lower() not in seen:
                seen.add(mail.lower())
                out.append({"email": mail, "name": name or mail, "group": group, "role": role})
        elif name:
            none.append({"name": name, "group": group, "role": role})

    def free(group, text):
        m = CS_MAIL_RE.search(text)
        lines = [x.strip() for x in text.splitlines() if x.strip() and (not m or m.group(0) not in x)]
        add(group, lines[0] if lines else "", m.group(0) if m else "")

    for x in a["crew"]:
        if not x["open"]:
            add("crew", x["name"], x["mail"], x["function"])
    ac, cc, cl = a["agency_contact"], a["client_contact"], a["client"]
    if ac:
        add("agency", ac["person"] or ac["company"], ac["email"], ac["company"] if ac["person"] else "")
    elif d.get("agency"):
        free("agency", d["agency"])
    if cc:
        add("client", cc["person"] or cc["company"], cc["email"], cc["company"] if cc["person"] else "")
    elif d.get("client"):
        free("client", d["client"])
    elif cl.get("name") or cl.get("contact"):
        add("client", cl.get("contact") or cl.get("name"), cl.get("email"), cl.get("name") if cl.get("contact") else "")
    return out, none


def cs_mail_default(c, uid, rows):
    """(subject, text) of the call sheet's mail in the person's language (the language of the PDF): the project's name (the
    title of the shoot day without one) and the day."""
    lg = lang(c, uid)
    title = cs_project(c, uid, rows).get("name") or rows[0]["title"] or ""
    d0 = cs_when(rows)[0]
    day = cs_weekday(d0, lg) + ", " + pdf_date(d0, lg)
    return (tr(N_("Call sheet: {0} – {1}"), title, day, lg=lg).strip(" –"),
            tr(N_("Hello,\n\nattached is the call sheet for {0} on {1}."), title, day, lg=lg))


def cs_mail_way(c, uid, oid):
    """{way, address, note} of the person's mails from area oid (office/mailsig.py ofm_sender); way '' = no way out."""
    from ..office.mailsig import OFM_NOTE_BOX, OFM_NOTE_SERVER, ofm_sender
    snd = ofm_sender(c, oid, uid)
    note = tr(OFM_NOTE_BOX, snd["addr"]) if snd["via"] in ("workspace", "private") else tr(OFM_NOTE_SERVER) if snd["via"] else ""
    return {"way": snd["via"], "address": snd["addr"], "name": snd["name"] or "", "note": note}


@app.get("/api/team/dispo/callsheet/<job>/mail")
def cs_mail_get(job):
    """2.1155.0 (#5652): the form of the call sheet's mail: {recipients, without, subject, text, filename, sender, can_send}."""
    c, uid, oid, rows = cs_gate(job)
    rc, none = cs_mail_rcpts(c, uid, oid, job, rows)
    subject, text = cs_mail_default(c, uid, rows)
    return jsonify(recipients=rc, without=none, subject=subject, text=text, filename=cs_pdf_name(rows), sender=cs_mail_way(c, uid, oid),
                   can_send=org_writes(c, uid, oid), max=CS_MAIL_MAX)


@app.post("/api/team/dispo/callsheet/<job>/mail")
def cs_mail_post(job):
    """2.1155.0 (#5652): {to: [addresses of the distribution], subject?, text?, signature?, preview?}. preview true: what would
    go out -- {recipients, subject, text (with the signature), sender, reply_to, file: {name, size}}, nothing sent or counted.
    Else one mail per recipient with the PDF attached -> {sent: [address], failed: [{email, error}]}; nothing sent at all:
    the first refusal (409 the mail server, 429 a day's limit). The shoot day's write right (a read-only member 403); 409
    without a way out (no SMTP on the server and no mailbox); 400 for an address that is not in the distribution."""
    from ..office.invoices import _mail, h6c_send_budget, inv_clean_subject, inv_own_text_quota
    from ..office.ledger import ofx_log
    from ..office.letters import lt_multi
    from ..office.mailsig import ofm_mail, ofm_own_text, ofm_reply
    from .dspkern import dsk_need_day
    c, uid, oid, rows = cs_gate(job)
    dsk_need_day(c, uid, rows[:1])  # sending is a change of the shoot day's people's day: the write right of saving it
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    way = cs_mail_way(c, uid, oid)
    if not way["way"]:
        raise Denied(409, tr("E-mail sending is not set up on this server yet: whoever runs the server sets it up."))
    to = b.get("to")
    if not isinstance(to, list) or not to or len(to) > CS_MAIL_MAX or not all(isinstance(x, str) for x in to):
        raise BadInput(tr("Invalid value: {0}", "to"))
    rc, _none = cs_mail_rcpts(c, uid, oid, job, rows)
    known = {x["email"].lower(): x for x in rc}
    want = list(dict.fromkeys(x.strip().lower() for x in to))
    if any(x not in known for x in want):
        raise BadInput(tr("Invalid value: {0}", "to"))
    chosen = [known[x] for x in want]
    d_subject, d_text = cs_mail_default(c, uid, rows)
    subject = inv_clean_subject(b.get("subject")) or d_subject
    text = lt_multi(b.get("text"), "text", CS_MAIL_TEXT).strip()
    own = bool(text) and text != d_text.strip()
    mail = ofm_mail(c, oid, uid, text or d_text, {"signature": b.get("signature", True)})
    own = own or ofm_own_text(c, oid, uid, mail)
    rt = ofm_reply(c, oid, mail["profile"])
    pdf = cs_pdf(c, uid, oid, job, rows)
    fname = cs_pdf_name(rows)
    if b.get("preview"):
        return jsonify(recipients=chosen, subject=subject, text=mail["text"], sender=way, reply_to=rt or "",
                       file={"name": fname, "size": len(pdf)})
    if own:
        inv_own_text_quota(c, oid, uid)  # a member's own words to people outside: the organisation's day's limit (one send counts once)
    c.commit()
    sent, failed, first = [], [], None
    for x in chosen:
        try:
            h6c_send_budget(c, oid, uid, [x["email"]])  # the day's limits of the office mails (per area, person, address)
            ofx_log(c, oid, "send", target="callsheet", detail={"job": job, "to": x["email"], **({"own_text": 1} if own and not sent else {})})
            _mail(x["email"], subject, mail["text"], attachments=[(fname, pdf, "application/pdf")], from_name=mail["name"],
                  reply_to=rt, **mail["kw"])
        except Denied as e:  # nothing of this one is kept: neither its count nor its log entry
            c.rollback()
            first = first or e
            failed.append({"email": x["email"], "error": e.text()})
            continue
        c.commit()
        sent.append(x["email"])
    if not sent and first is not None:
        raise first
    return jsonify(sent=sent, failed=failed)



# ---------------------------------------------------------------- 2.988.0 (#5651): the tab "Call sheets" of a project
CS_LIST_MAX = 500  # the call sheets of one project shown at most (a year of shoot days, twice over)


def _cs_proj(c, uid, lid):
    """(c's list row, locked) of project lid when uid sees it, else 404. 2.988.0 (#5651)."""
    try:
        lid = int(lid)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid data")) from None
    if not list_role(c, lid, uid):
        raise Denied(404)
    r = c.execute(f"SELECT id, name, org_id, owner_id, {list_archived_sql('')} AS archived, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    if r is None or r["is_inbox"]:  # review 2.988 F6: the inbox is no project (the client offers no tab there)
        raise Denied(404)
    return r, bool(le2e_mode(c, lid))


def _cs_new_area(c, uid, lst):
    """The area a new shoot day of project lst goes into (its organisation; a private project: the personal area of its
    owner, only when uid is that owner -- hub/dispo.py dsp_create takes a private project of the own area only), or None."""
    if not lst["org_id"] and lst["owner_id"] != uid:
        return None
    pid = None if lst["org_id"] else pb_personal(c, uid, create=False)  # review 2.988 F5: a GET makes no personal area
    if not lst["org_id"] and pid is None:
        return None
    try:
        oid = _area(c, uid, lst["org_id"] or pid)
    except Denied:
        return None
    return oid if "film" in inds_of_area(c, oid) else None


def cs_list_rows(c, uid, lid):
    """[{job, org_id, date, start, title, day_no, location, updated_at}] of the call sheets of project lid uid may read: the
    core's rows of kind callsheet (obj_rows, the role per row: the module on, a member of the area) whose shoot day belongs to
    the project, in an area with the industry Film & Video; oldest shoot day first."""
    from ..core.objects import obj_rows
    from .dspkern import DSK_CS
    rows = obj_rows(c, uid, DSK_CS, f"EXISTS (SELECT 1 FROM hub_bookings b WHERE b.org_id=o.org_id AND b.job=o.job AND b.list_id=? "
                                     f"AND {live_sql('b')})", (int(lid),), limit=CS_LIST_MAX)
    film, out = {}, []
    for r, _role in rows:
        oid = r["org_id"]
        if oid not in film:
            film[oid] = "film" in inds_of_area(c, oid)
        if not film[oid]:
            continue
        # review 2.988 F7: a booking of this project first (a job's bookings share their title; ordered for one answer)
        bs = [dict(b) for b in c.execute(f"SELECT start, \"end\", title FROM hub_bookings WHERE org_id=? AND job=? AND {live_sql()} "
                                         "ORDER BY (list_id=?) DESC, id", (oid, r["job"], int(lid)))]
        if not bs:
            continue
        d = cs_data(oc_dec_fields(c, oid, "hub_callsheets", r))
        d0, t0, _t1 = cs_when(bs)
        out.append({"job": r["job"], "org_id": oid, "date": d0, "start": t0, "title": bs[0]["title"] or "",
                    "day_no": d.get("day_no") or "", "location": d.get("loc_name") or d.get("set_name") or "",
                    "updated_at": r["updated_at"] or ""})
    out.sort(key=lambda x: (x["date"], x["start"], x["job"]))
    return out


def cs_last_no(c, oid, lid):
    """The highest shoot day number of project lid's call sheets in area oid, the ones in the trash too (review 2.988 F4: a
    count gave a number twice after a delete); a number typed as text that is no whole number does not count."""
    best = 0
    for r in c.execute("SELECT cs.* FROM hub_callsheets cs WHERE cs.org_id=? AND EXISTS (SELECT 1 FROM hub_bookings b WHERE "
                       "b.org_id=cs.org_id AND b.job=cs.job AND b.list_id=?)", (oid, int(lid))):
        v = str(cs_data(oc_dec_fields(c, oid, "hub_callsheets", r)).get("day_no") or "").strip()
        if v.isdigit() and len(v) < 6:
            best = max(best, int(v))
    return best


@app.get("/api/team/dispo/callsheets")
def cs_list():
    """?list=<project>: {callsheets: [...] (cs_list_rows), can_add}. 2.988.0 (#5651). The module "dispo" on (else 403), the
    project visible (else 404); a project with the lock (end-to-end encryption) shows nothing (its name is sealed too)."""
    c, uid = _gate()
    lst, locked = _cs_proj(c, uid, request.args.get("list"))
    if locked:
        return jsonify(callsheets=[], can_add=False, locked=True)
    oid = _cs_new_area(c, uid, lst)
    can = bool(oid) and not lst["archived"] and list_role(c, lst["id"], uid) in WRITE_ROLES and org_writes(c, uid, oid)
    return jsonify(callsheets=cs_list_rows(c, uid, lst["id"]), can_add=can, locked=False)


@app.post("/api/team/dispo/callsheets")
def cs_new():
    """{list_id, date: YYYY-MM-DD}: a new call sheet of the project (2.988.0, #5651). Its shoot day is made in the background:
    one open place of the disposition on that day (resource 'slot', pencilled in, titled "Shoot day"; filled in
    the disposition like an open place from a quotation), then the call sheet's row (the core's history "create") with the
    next shoot day number of the project (cs_last_no + 1). Rights: the project's write role, the area's write role (the shoot day's right of the
    core, dspkern.dsk_need_day). Answers {callsheet: the row of the tab, booking_id} 201."""
    c, uid = _gate()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    lst, locked = _cs_proj(c, uid, b.get("list_id"))
    oid = _cs_new_area(c, uid, lst)
    if not oid:
        raise Denied(404)
    if locked or lst["archived"] or list_role(c, lst["id"], uid) not in WRITE_ROLES:  # review 2.988 F6: an archived project
        raise Denied(403, tr("You can only read this project"))
    need_org_write(c, uid, oid)  # a read-only member of the area: 403 before anything is made (as dsp_create)
    day = b.get("date")
    if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise BadInput(tr("Invalid value: {0}", "date"))
    try:
        date.fromisoformat(day)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "date")) from None
    from .dspkern import dsk_need_day
    write_lock(c, f"hub_callsheets-new-{int(lst['id'])}")  # two at once: the day numbers one after the other
    n = cs_last_no(c, oid, lst["id"])
    job = secrets.token_hex(8)
    now = iso(now_utc())  # as hub/dispo.py dsp_create
    bid = insert_id(c, "INSERT INTO hub_bookings(org_id,job,title,start,\"end\",resource_kind,resource_id,res_label,status,note,list_id,"
                       "created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (oid, job, tr("Shoot day"), day, day, DSP_SLOT, 0, tr("Crew")[:200],
                     "option", "", lst["id"], uid, now, now))
    dsk_need_day(c, uid, [c.execute("SELECT * FROM hub_bookings WHERE id=?", (bid,)).fetchone()])  # the core's floor (403 read-only)
    write_lock(c, f"hub_callsheets-{oid}-{job}")
    cs_make(c, uid, oid, job, {"day_no": str(n + 1)})
    # review 2.988 F3: the shoot day's title is "Shoot day", not the project's name -- the disposition (and its export) shows
    # titles to every member of the area, a project's name only to those who see the project (dispo.py dsp_export)
    bump(c)
    c.commit()
    row = next((x for x in cs_list_rows(c, uid, lst["id"]) if x["job"] == job), None)
    return jsonify(callsheet=row, booking_id=bid), 201  # booking_id: the browser's undo (DELETE ...bookings/<id>?all=1)
