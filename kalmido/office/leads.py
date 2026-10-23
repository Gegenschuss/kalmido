"""2.94.0 A (#1930): leads before the sales pipeline -- deals in the stage "lead" (office_deals, office/pipeline.py: one table,
no second store) with a source (LEAD_SOURCES), a next step, a follow-up day and the lead's contact data (contact person,
company, e-mail, phone). People (admins of the office area, like the pipeline; a personal office: its owner) read and
change leads over the pipeline's routes and here convert a lead into a client + deal (stage inquiry), undo that, and
import leads from a CSV file (preview, then take over; duplicates by e-mail skipped). The appointment booking
(calendars/apptbook.py, part B) makes a lead with lead_from_booking. Agents (scope office, the switches of
office/agentdocs.py, acting for an admin of the area) list leads, add leads and change the next step / follow-up / note
of a lead -- never convert, delete or set another stage. Leads never count in the pipeline's sums or forecast."""
import re
from datetime import date

from flask import g, jsonify

from ..core.config import app
from ..core.db import body, bump, db, iso, local_now, now_utc
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..core.pg import insert_id, system_ctx
from ..core.orgcrypt import oc_enc_fields
from ..core.errors import BadInput
from ..api.common import v1_view
from .calc import dec, dstr, money
from .model import office_on, office_role, pb_cl_org, pb_cl_sql
from .rights import ofr_rights
from .pipeline import (EMAIL_RE, LEAD_SOURCES, MAX_DEALS, PL2_PROB, _client_ok, _ctx, _one, _row, _txt, _update,
                       pl2_clean, pl2_list, pl2_public)

LEAD_IMPORT_MAX = 1000  # rows per CSV import
LEAD_V1_FIELDS = ("id", "title", "contact", "company", "email", "phone", "source", "next_step", "follow_up", "note",
                  "created_at", "updated_at")
LEAD_V1_IN = ("title", "contact", "company", "email", "phone", "source", "next_step", "follow_up", "note")
LEAD_V1_PATCH = ("next_step", "follow_up", "note")
LEAD_ADMIN_ONLY = N_("Only the admins of the office see the pipeline.")
# the CSV columns: normalised header (lower case, letters and digits only) -> field
LEAD_COLS = {
    "name": "contact", "contact": "contact", "contactperson": "contact", "person": "contact", "fullname": "contact",
    "kontakt": "contact", "ansprechpartner": "contact", "ansprechperson": "contact", "nombre": "contact", "nom": "contact",
    "nome": "contact", "naam": "contact", "contacto": "contact", "contatto": "contact", "contactpersoon": "contact",
    "company": "company", "organisation": "company", "organization": "company", "firma": "company", "unternehmen": "company",
    "empresa": "company", "entreprise": "company", "societe": "company", "azienda": "company", "bedrijf": "company",
    "email": "email", "mail": "email", "emailaddress": "email", "emailadresse": "email", "correo": "email", "courriel": "email",
    "phone": "phone", "telephone": "phone", "tel": "phone", "telefon": "phone", "mobile": "phone", "mobil": "phone",
    "handy": "phone", "telefono": "phone", "telefoon": "phone", "telefonnummer": "phone",
    "source": "source", "quelle": "source", "fuente": "source", "origine": "source", "fonte": "source", "bron": "source",
    "nextstep": "next_step", "naechsterschritt": "next_step", "nachsterschritt": "next_step", "nchsterschritt": "next_step",
    "prochaineetape": "next_step", "siguientepaso": "next_step", "prossimopasso": "next_step", "volgendestap": "next_step",
    "followup": "follow_up", "followupdate": "follow_up", "wiedervorlage": "follow_up", "seguimiento": "follow_up",
    "relance": "follow_up", "richiamo": "follow_up", "opvolging": "follow_up",
    "note": "note", "notes": "note", "notiz": "note", "notizen": "note", "bemerkung": "note", "kommentar": "note",
    "nota": "note", "notas": "note", "notitie": "note", "comment": "note",
    "value": "value", "wert": "value", "betrag": "value", "amount": "value", "valor": "value", "valeur": "value",
    "valore": "value", "waarde": "value",
    "title": "title", "titel": "title", "deal": "title", "betreff": "title", "subject": "title",
}


def _norm(h):
    h = (h or "").strip().lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("é", "e").replace("è", "e")
    return re.sub(r"[^a-z0-9]", "", h)


def lead_insert(c, oid, by, row):
    """One new deal row (checked columns of pl2_clean) in office area oid -> its id (no commit). by = who made it."""
    if c.execute("SELECT COUNT(*) FROM office_deals WHERE org_id=? AND deleted_at IS NULL", (oid,)).fetchone()[0] >= MAX_DEALS:
        raise BadInput(tr("Too many entries"))
    row = dict(row)
    row.setdefault("sort", float(c.execute("SELECT COALESCE(MIN(sort), 0) - 1 FROM office_deals WHERE org_id=?", (oid,)).fetchone()[0]))
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=by, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_deals", row)
    return insert_id(c, f"INSERT INTO office_deals({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def lead_title(b):
    """A lead's name when none was given: the company, else the person, else the e-mail."""
    return (b.get("title") or b.get("company") or b.get("contact") or b.get("email") or "").strip()


def lead_emails(c, oid):
    """The e-mails (lower case) of the deals of office area oid that are not in the bin (the duplicate check)."""
    return {(d.get("email") or "").strip().lower() for d in pl2_list(c, oid)} - {""}


# ---------------------------------------------------------------- from the appointment booking (part B)
def lead_from_booking(c, oid, by_uid, name, email="", phone="", note="", source="booking", follow_up=""):
    """A new lead (office_deals stage lead) in office area oid from a confirmed appointment booking (part B calls it at
    run time); returns the deal id or None (the booking holds anyway). by_uid must be an admin of oid (a personal office:
    its owner) with the office on. follow_up = the appointment's day (ISO; default today). An open lead with the same
    e-mail gets no twin: its id is returned. The caller commits."""
    if not oid or not by_uid:
        return None
    # a guest's request (the public booking page, nobody signed in): the area and the owner's role are checked here
    # explicitly before anything of office area oid is read or written
    with system_ctx(c):
        if office_role(c, by_uid, oid) != "admin" or not office_on(c, by_uid):
            return None
        try:
            b = {"contact": name, "email": email if isinstance(email, str) and EMAIL_RE.match(email.strip()) else "",
                 "phone": phone, "note": note, "source": source if source in LEAD_SOURCES else "booking",
                 "follow_up": follow_up or local_now().date().isoformat(), "stage": "lead"}
            b["title"] = lead_title(b)
            if not b["title"]:
                return None
            em = b["email"].strip().lower()
            if em:
                for d in pl2_list(c, oid):
                    if d["stage"] == "lead" and (d.get("email") or "").strip().lower() == em:
                        return d["id"]
            did = lead_insert(c, oid, by_uid, pl2_clean(c, oid, b))
        except BadInput:
            return None
        bump(c)
    return did


# ---------------------------------------------------------------- convert into a client + deal
def _client_matches(c, oid, d):
    """Clients of the office area with the lead's e-mail or the company's name (the client offers to take one)."""
    em, co = (d.get("email") or "").strip().lower(), (d.get("company") or "").strip().lower()
    if not em and not co:
        return []
    rows = c.execute(f"SELECT id, name, email FROM clients WHERE {pb_cl_sql(c, oid)} AND archived=0 AND "
                     "((? <> '' AND lower(email)=?) OR (? <> '' AND lower(name)=?)) ORDER BY lower(name), id LIMIT 10", (em, em, co, co)).fetchall()
    return [{"id": r["id"], "name": r["name"], "email": r["email"] or "", "same_email": bool(em) and (r["email"] or "").strip().lower() == em}
            for r in rows]


def _lead_row(c, oid, did):
    cur = pl2_public(c, oid, _row(c, oid, did))
    if cur["stage"] != "lead":
        raise Denied(409, tr("This is no lead any more"))
    return cur


@app.get("/api/office/deals/<int:did>/convert")
def lead_convert_check(did):
    """{matches: [{id, name, email, same_email}]}: existing clients that fit the lead (same e-mail or company name)."""
    c, uid, oid = _ctx()
    return jsonify(matches=_client_matches(c, oid, _lead_row(c, oid, did)))


@app.post("/api/office/deals/<int:did>/convert")
def lead_convert(did):
    """{client_id?}: the lead becomes a deal in the stage inquiry with a client -- client_id = an existing client of the
    office area, else a new one from company / contact / e-mail / phone (the contact as its contact person).
    -> {deal, client_id, client_new}; the client's undo calls .../unconvert."""
    from ..team.clients import clean_client
    from .contacts_cl import fk_add
    c, uid, oid = _ctx()
    cur = _lead_row(c, oid, did)
    b = body()
    if not isinstance(b, dict):
        b = {}
    cid, new = b.get("client_id"), False
    if cid is not None:
        if not isinstance(cid, int) or isinstance(cid, bool) or not _client_ok(c, oid, cid):
            raise BadInput(tr("Invalid value: {0}", "client_id"))
    else:
        name = (cur.get("company") or cur.get("contact") or cur.get("title") or "").strip()
        f = {"name": name, "contact": cur.get("contact") or "", "email": cur.get("email") or "", "phone": cur.get("phone") or "",
             "org_id": pb_cl_org(c, oid)}  # a personal office's clients are private clients
        f = clean_client(c, uid, f, new=True)
        if not f.get("name"):
            raise BadInput(tr("Please enter a name"))
        ts = iso(now_utc())
        f.update(org_id=pb_cl_org(c, oid), created_by=uid, created_at=ts, updated_at=ts)
        cid = insert_id(c, f"INSERT INTO clients({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values()))
        if f.get("contact"):  # the lead's person = the default contact person (removed with the client by the undo)
            fk_add(c, cid, pb_cl_org(c, oid), {"name": f["contact"], "email": f.get("email") or "", "phone": f.get("phone") or ""}, default=True)
        new = True
    row = pl2_clean(c, oid, {"stage": "inquiry"}, cur)
    row.update(client_id=cid, lead_client_id=cid if new else None)
    _update(c, oid, did, row)
    bump(c)
    c.commit()
    return jsonify(deal=_one(c, oid, did), client_id=cid, client_new=new)


def _client_used(c, cid, did):
    """Something besides deal did and its own contact persons refers to client cid (then the undo keeps it)."""
    # counting only, no contents: references from anywhere (other people's private rows too) keep the client
    with system_ctx(c):
        tabs = [r[0] for r in c.execute("SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema = current_schema() "
                                        "AND column_name='client_id' AND table_name NOT IN ('office_client_contacts', 'clients')").fetchall()]
        for t in tabs:
            if not re.fullmatch(r"[a-z0-9_]+", t):
                return True
            extra = " AND id<>?" if t == "office_deals" else ""
            if c.execute(f"SELECT 1 FROM {t} WHERE client_id=?{extra} LIMIT 1", (cid, did) if extra else (cid,)).fetchone():
                return True
    return False


@app.post("/api/office/deals/<int:did>/unconvert")
def lead_unconvert(did):
    """{remove_client?: bool}: the undo of convert -- the deal back to the stage lead without a client; remove_client also
    deletes the client convert made (lead_client_id), when nothing else uses it. -> {deal, client_removed}."""
    c, uid, oid = _ctx()
    cur = pl2_public(c, oid, _row(c, oid, did))
    if cur["stage"] != "inquiry":
        raise Denied(409, tr("The deal has moved on since"))
    b = body()
    rm = bool(b.get("remove_client")) if isinstance(b, dict) else False
    cid = cur["client_id"]
    made = c.execute("SELECT lead_client_id FROM office_deals WHERE id=? AND org_id=?", (did, oid)).fetchone()[0]
    row = pl2_clean(c, oid, {"stage": "lead"}, cur)
    row.update(client_id=None, lead_client_id=None)
    _update(c, oid, did, row)
    gone = False
    if rm and cid and cid == made and _client_ok(c, oid, cid):
        if not _client_used(c, cid, did):
            c.execute(f"DELETE FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (cid,))
            gone = True
    bump(c)
    c.commit()
    return jsonify(deal=_one(c, oid, did), client_removed=gone)


# ---------------------------------------------------------------- CSV import
def _day_of(s):
    s = (s or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s) or None
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{2}|\d{4})", s)
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _value_of(s):
    from ..life.budget import _parse_amount
    s = (s or "").strip()
    if not s:
        return dec(0)
    v = _parse_amount(s, "," if s.rfind(",") > s.rfind(".") else ".")
    return v if v is not None and v >= 0 else None


def _source_of(s):
    v = _norm(s)
    if not v:
        return "import", ""
    return (v, "") if v in LEAD_SOURCES else ("import", s.strip()[:80])


def lead_parse(c, oid, text):
    """CSV text -> (columns {field: header}, rows): every row {n, title, contact, company, email, phone, source,
    next_step, follow_up, note, value, error, dup}. Duplicates: the e-mail of a deal of the area or of an earlier row."""
    from ..life.budget import bud_csv_table
    if not isinstance(text, str) or not text.strip():
        raise BadInput(tr("The file is empty"))
    _d, header, rows = bud_csv_table(text)
    cols = {}
    for i, h in enumerate(header):
        f = LEAD_COLS.get(_norm(h))
        if f and f not in cols:
            cols[f] = i
    if not ({"contact", "company", "email", "title"} & set(cols)):
        raise BadInput(tr("No column for the name, the company or the e-mail found"))
    if len(rows) > LEAD_IMPORT_MAX:
        raise BadInput(tr("At most {0} rows per import", LEAD_IMPORT_MAX))
    have = lead_emails(c, oid)
    out = []
    for n, r in enumerate(rows, 1):
        cell = {f: (r[i] if i < len(r) else "").strip() for f, i in cols.items()}
        x = {"n": n, "error": None, "dup": False}
        for k, m in (("title", 200), ("contact", 200), ("company", 200), ("phone", 60), ("next_step", 300), ("note", 4000)):
            x[k] = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", cell.get(k, "")).strip()[:m]
        x["email"] = cell.get("email", "")[:200]
        x["source"], other = _source_of(cell.get("source", ""))
        if other:  # a source outside the list: kept as a line of the note
            x["note"] = (x["note"] + "\n" if x["note"] else "") + tr("Source: {0}", other)
        x["title"] = lead_title(x)[:200]
        fu, v = _day_of(cell.get("follow_up")), _value_of(cell.get("value"))
        x["follow_up"], x["value"] = fu or "", dstr(money(v)) if v is not None else "0.00"
        if not x["title"]:
            x["error"] = tr("Name missing")
        elif x["email"] and not EMAIL_RE.match(x["email"]):
            x["error"] = tr("Invalid value: {0}", "email")
        elif fu is None:
            x["error"] = tr("Invalid value: {0}", "follow_up")
        elif v is None:
            x["error"] = tr("Invalid value: {0}", "value")
        em = x["email"].lower()
        if not x["error"] and em:
            x["dup"] = em in have
            have.add(em)
        out.append(x)
    return {f: header[i] for f, i in cols.items()}, out


@app.post("/api/office/leads/import")
def lead_import():
    """{text, commit?: bool}: without commit the preview {columns, rows, count, dup_count, skipped} (nothing stored);
    with commit the rows without error and duplicate become leads (source from the file or "import")
    -> 201 {ids, count, dup_count, skipped}; the client's undo calls .../import/undo with the ids."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    cols, rows = lead_parse(c, oid, b.get("text"))
    ok = [x for x in rows if not x["error"] and not x["dup"]]
    counts = dict(count=len(ok), dup_count=sum(1 for x in rows if x["dup"]), skipped=sum(1 for x in rows if x["error"]))
    if not b.get("commit"):
        return jsonify(columns=cols, rows=rows[:LEAD_IMPORT_MAX], **counts)
    if not ok:
        raise BadInput(tr("Nothing to import"))
    n = c.execute("SELECT COUNT(*) FROM office_deals WHERE org_id=? AND deleted_at IS NULL", (oid,)).fetchone()[0]
    if n + len(ok) > MAX_DEALS:
        raise BadInput(tr("Too many entries"))
    base = float(c.execute("SELECT COALESCE(MIN(sort), 0) FROM office_deals WHERE org_id=?", (oid,)).fetchone()[0])
    ids = []
    for i, x in enumerate(ok):
        row = pl2_clean(c, oid, {k: x[k] for k in ("title", "contact", "company", "email", "phone", "source", "next_step", "follow_up", "note", "value")}
                        | {"stage": "lead"})
        row["sort"] = base - len(ok) + i
        ids.append(lead_insert(c, oid, uid, row))
    bump(c)
    c.commit()
    return jsonify(ids=ids, **counts), 201


@app.post("/api/office/leads/import/undo")
def lead_import_undo():
    """{ids}: the undo of an import -- these leads of the area (still leads) into the bin. -> {count}."""
    c, uid, oid = _ctx()
    b = body()
    ids = b.get("ids") if isinstance(b, dict) else None
    if not isinstance(ids, list) or not ids or len(ids) > LEAD_IMPORT_MAX or any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    ts, n = iso(now_utc()), 0
    for i in ids:
        n += c.execute("UPDATE office_deals SET deleted_at=? WHERE id=? AND org_id=? AND stage='lead' AND deleted_at IS NULL", (ts, i, oid)).rowcount
    bump(c)
    c.commit()
    return jsonify(count=n)


# ---------------------------------------------------------------- agents (scope office, the switches of agentdocs.py)
def _v1lead(c, rb, write=False):
    from .agentdocs import _v1ctx
    aid, oid, uid = _v1ctx(c, rb, write=write, target="leads")
    if office_role(c, uid, oid) != "admin" and ofr_rights(c, uid, oid) is None:  # the pipeline is for the area's admins: an agent acting for a member sees no lead
        raise Denied(403, tr(LEAD_ADMIN_ONLY))  # 2.187.0 C (#2476): a person ruled by office groups: _v1ctx checked the pipeline's level
    return aid, oid, uid


def lead_v1_public(d):
    out = {k: d.get(k) for k in LEAD_V1_FIELDS}
    out["app_url"] = "#office/pipeline"
    return out


@app.get("/api/v1/office/leads")
@v1_view
def v1_lead_list():
    from .agentdocs import _args
    a = _args(("due",))
    c = db()
    aid, oid, uid = _v1lead(c, a.get("requested_by"))
    today = local_now().date().isoformat()
    rows = [d for d in pl2_list(c, oid) if d["stage"] == "lead"]
    if a.get("due") in ("1", "true"):
        rows = [d for d in rows if d.get("follow_up") and d["follow_up"] <= today]
    rows.sort(key=lambda d: (d.get("follow_up") or "9999", d["id"]))
    c.commit()
    return jsonify(data=[lead_v1_public(d) for d in rows])


@app.post("/api/v1/office/leads")
@v1_view
def v1_lead_post():
    """{title?, contact?, company?, email?, phone?, source?, next_step?, follow_up?, note?} -> 201 the lead (stage lead)."""
    from .agentdocs import _json
    b = _json(LEAD_V1_IN)
    c = db()
    aid, oid, uid = _v1lead(c, b.get("requested_by"), write=True)
    x = {k: b[k] for k in LEAD_V1_IN if k in b}
    x["source"] = x.get("source") or "agent"
    x["title"] = lead_title({k: v if isinstance(v, str) else "" for k, v in x.items()})
    x["stage"] = "lead"
    did = lead_insert(c, oid, aid, pl2_clean(c, oid, x))
    bump(c)
    c.commit()
    return jsonify(lead_v1_public(pl2_public(c, oid, _row(c, oid, did)))), 201


@app.patch("/api/v1/office/leads/<int:did>")
@v1_view
def v1_lead_patch(did):
    """{next_step?, follow_up?, note?}: only these, only while the deal is a lead."""
    from .agentdocs import _json
    b = _json(LEAD_V1_PATCH)
    c = db()
    aid, oid, uid = _v1lead(c, b.get("requested_by"), write=True)
    cur = pl2_public(c, oid, _row(c, oid, did))
    if cur["stage"] != "lead":
        raise Denied(409, tr("This is no lead any more"))
    _update(c, oid, did, pl2_clean(c, oid, {k: b[k] for k in LEAD_V1_PATCH if k in b}, cur))
    bump(c)
    c.commit()
    return jsonify(lead_v1_public(pl2_public(c, oid, _row(c, oid, did))))


# ---------------------------------------------------------------- OpenAPI (called from api/openapi.py)
def lead_spec(paths, schemas, op, ok, errs, ref, pid, q):
    T = "Office"
    o = {"type": "object"}
    rb = q("requested_by", "The person this is for (an admin of the office; default: the agent's owner)", {"type": "integer"})
    props = {"title": {"type": "string", "description": "Default: the company, else the person"}, "contact": {"type": "string"},
             "company": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"},
             "source": {"type": "string", "enum": list(LEAD_SOURCES), "description": "Default: agent"},
             "next_step": {"type": "string"}, "follow_up": {"type": "string", "format": "date"}, "note": {"type": "string"},
             "requested_by": {"type": "integer"}}
    schemas["OfficeLeadInput"] = {"type": "object", "properties": props}
    rules = ("The switches of the office (the agent's \"May draft office documents\" and the area's \"Agents may read office "
             "data\") and a person who is an admin of the office. Leads only: never convert, delete or another stage.")
    paths["/office/leads"] = {
        "get": op("The leads of the office, by follow-up day (2.94.0)", T, ok(o) | errs("400", "403", "404"),
                  [q("due", "1 = only leads whose follow-up day has come", {"type": "string"}), rb], scope="office", desc=rules),
        "post": op("Add a lead (2.94.0)", T, ok(o, "Created", "201") | errs("400", "403", "404"), body=ref("OfficeLeadInput"),
                   scope="office", desc=rules)}
    paths["/office/leads/{id}"] = {"patch": op("Change the next step, follow-up day or note of a lead (2.94.0)", T, ok(o) | errs("400", "403", "404", "409"),
                                               [pid("id", "Lead id")], body={"type": "object", "properties": {
                                                   k: props[k] for k in LEAD_V1_PATCH + ("requested_by",)}}, scope="office",
                                               desc="Only while it is a lead (409 once a person converted it).")}
