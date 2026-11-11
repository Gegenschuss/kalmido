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
call sheet of the project. The free texts data.client / data.agency stay as the fallback (older call sheets keep theirs)."""
import base64
import binascii
import hashlib
import io
import json
import re
import secrets
from datetime import date
from urllib.parse import quote

from flask import Response, jsonify, request
from PIL import Image

from ..core.config import app
from ..core.i18n import LANGS, N_, lang, tr
from ..core.db import body, bump, iso, iso_ms, local_now, now_utc
from ..core.access import Denied, list_role, live_sql, WRITE_ROLES
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
from ..office.pdf import (A4_H, C_INK, C_INK2, C_RULE, C_RULE2, MM, PDF_CW, PDF_L, _Page, pdf_date, pdf_image_object,
                          pdf_text_width, pdf_wrap, pdf_write)
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
                           "AND kind='individual' AND emails ILIKE ? ESCAPE '\\' LIMIT 20", (*books, "%" + re.sub(r"([%_\\])", r"\\\1", mail.lower()) + "%")):
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


def cs_contact_info(r):
    """{id, company, person, phone, email} of a contact row (2.986.0, #5649): an organisation contact is the company, a person
    carries the company of the contact's field "organisation"."""
    name = (r["fn"] or f"{r['given'] or ''} {r['family'] or ''}").strip()
    company, person = (name, "") if r["kind"] == "org" else ((r["org"] or "").strip(), name)
    return {"id": r["id"], "company": company, "person": person, "phone": _first(r["phones"], ("cell", "mobile")),
            "email": _first(r["emails"])}


def cs_contact(c, uid, oid, cid, books=None):
    """2.986.0 (#5649): the contact cid as cs_contact_info when it is a person / an organisation in an address book of the area
    uid may read (dsp_book_ids, the rule of cs_people), else None -- an id of another book shows nothing."""
    if not cid:
        return None
    books = dsp_book_ids(c, uid, oid) if books is None else books
    if not books:
        return None
    r = c.execute(f"SELECT id, kind, fn, given, family, org, emails, phones FROM contacts WHERE id=? AND book_id IN ({cs_book_q(books)}) "
                  f"AND kind IN ('individual', 'org') AND {live_sql()}", (int(cid), *books)).fetchone()
    return cs_contact_info(r) if r else None


def cs_contacts(c, uid, oid, books=None):
    """2.986.0 (#5649): the choice of the dialog: [{id, company, person, phone, email}] of the people and organisations of the
    area's address books uid may read (the same books as dsp_contacts of the disposition's places)."""
    books = dsp_book_ids(c, uid, oid) if books is None else books
    if not books:
        return []
    return [cs_contact_info(r) for r in c.execute(
        f"SELECT id, kind, fn, given, family, org, emails, phones FROM contacts WHERE book_id IN ({cs_book_q(books)}) "
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
    """{name, lines: [address, phone, mail]} of the area's master data (office_company; a personal area: the own office)."""
    r = c.execute("SELECT name, street, zip, city, email, phone FROM office_company WHERE org_id=?", (oid,)).fetchone()
    name = (r["name"] if r else "") or ""
    if not name:
        o = c.execute("SELECT name, personal_of FROM orgs WHERE id=?", (oid,)).fetchone()
        name = (o["name"] or "") if o and not o["personal_of"] else ""
    lines = []
    if r:
        lines = [x for x in ((r["street"] or "").strip(), " ".join(x for x in ((r["zip"] or "").strip(), (r["city"] or "").strip()) if x),
                             (r["phone"] or "").strip(), (r["email"] or "").strip()) if x]
    return {"name": name, "lines": lines}


def cs_shot_days(c, uid, proj):
    """[(day name, [shots])] of the project's shot list (lists/shoot.py sht_days), [] for another project type."""
    if not proj.get("shoot"):
        return []
    return sht_days(c, uid, proj["list_id"])


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
    return {"date": d0, "start": t0, "end": t1, "title": rows[0]["title"] or "", "project": proj.get("name", ""),
            "client": proj.get("client") or {}, "production": cs_production(c, oid), "crew": crew,
            "shot_days": [n for n, s in days], "list_id": proj.get("list_id"),
            "client_contact": cs_contact(c, uid, oid, d.get("client_contact"), books),
            "agency_contact": cs_contact(c, uid, oid, d.get("agency_contact"), books),
            "agency_default": cs_contact(c, uid, oid, proj.get("agency_id"), books),
            **({"contacts": cs_contacts(c, uid, oid, books)} if choice else {})}


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


def cs_sketch_in(c, uid, oid, v):
    """A sketch (data URI or base64) -> (base64 text, mime): PNG / JPEG only, at most CS_IMG_MAX bytes, through the shared
    upload checks (virus scan, photo metadata such as the place a photo was taken, files/upsafe.py up_check); a picture the
    scanner could not check is refused (no later scan for this one)."""
    if not isinstance(v, str) or not v.strip():
        raise BadInput(tr("Invalid value: {0}", "sketch"))
    raw = v.strip()
    m = re.match(r"data:([a-z/+.-]+);base64,", raw)
    if m:
        raw = raw[m.end():]
    if len(raw) > CS_IMG_MAX * 4 // 3 + 8:
        raise BadInput(tr("The picture is too large (at most {0} MB)", CS_IMG_MAX // (1024 * 1024)))
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise BadInput(tr("Invalid value: {0}", "sketch")) from None
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
    old = c.execute("SELECT cs_agency_id, archived FROM lists WHERE id=? FOR UPDATE", (lid,)).fetchone()
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


# ---------------------------------------------------------------- the PDF
CS_FS = 9.0
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
          ([T(N_("Shots of the day"))] if shots else []) + ([T(N_("Directions sketch"))] if r and r.get("sketch") else []) + \
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


@app.get("/api/team/dispo/callsheet/<job>/pdf")
def cs_pdf_route(job):
    """The call sheet of shoot day `job` as a PDF (see the module text)."""
    c, uid, oid, rows = cs_gate(job)
    data = cs_pdf(c, uid, oid, job, rows)
    fn = (re.sub(r"[^A-Za-z0-9._-]+", "-", rows[0]["title"] or "")[:50].strip("-") or "shoot") + "-" + min(b["start"][:10] for b in rows)
    disp = "inline" if request.args.get("inline") else "attachment"
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'{disp}; filename="callsheet-{fn}.pdf"',
                                                               "Cache-Control": "no-store"})



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
    r = c.execute("SELECT id, name, org_id, owner_id, archived, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
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
