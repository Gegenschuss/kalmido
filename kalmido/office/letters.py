"""2.153.0 (#2028): letters of an office area ("Korrespondenz"): letters to authorities, insurers, clients.

A letter (office_letters) has a recipient chosen from the office's clients or the address book (name, address lines and
e-mail frozen when chosen), a date (today by default), subject, text, greeting and signer (+ the signer's signature
picture, office_letter_profiles), the channel (post | email | registered | fax) and the status draft | sent | delivered
(tracking number with registered mail). The PDF is a DIN 5008 form B letter with the parts of the invoice PDF
(office/pdf.py: letterhead, sender line office/ledger.py ofx_sender_line, address field in the window, fold marks); sending
files it into the documents space with the recipient. Links to documents (answers / reply), the history, the follow-up and
the reference line: office/letterlinks.py; e-mail + text blocks: office/lettermail.py; agents: office/letteragent.py.

Every route: office_gate + office_org with the admin of the office area (like the document templates). Agents only make
drafts (letteragent.py); sending / finishing is done by a person. Subject, text, address and reference line encrypted."""
import base64
import binascii
import json
import re
from datetime import timedelta

from flask import Response, g, has_request_context, jsonify, request

from ..core.config import app, APP_VERSION
from ..core.pg import insert_id, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import N_, tr
from ..core.db import body, bump, err, iso, local_now, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .letterhead import bp_letter  # 2.184.0 C (#2581)
from .model import OFFICE_ADMIN_ONLY, office_gate, office_org, office_role, pb_cl_sql, pb_owner

LT_CHANNELS = (("post", N_("Post")), ("email", N_("E-mail")), ("registered", N_("Registered mail")), ("fax", N_("Fax")))
LT_CHANNEL_KEYS = tuple(k for k, _ in LT_CHANNELS)
LT_STATUS = (("draft", N_("Draft")), ("sent", N_("Sent")), ("delivered", N_("Delivered")))
LT_STATUS_KEYS = tuple(k for k, _ in LT_STATUS)
LT_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
LT_LINE_MAX, LT_ADDR_MAX, LT_BODY_MAX = 300, 600, 60000
LT_LIST_MAX = 500
LT_IMG_MAX = 300 * 1024  # the signature picture: PNG / JPEG of at most 300 KB
LT_GREETING = N_("Kind regards")
# the columns a draft may set (lt_clean); status / sent_at / msg_id / node_id are set by the sending steps only
LT_EDIT = ("client_id", "contact_id", "rcpt_name", "rcpt_address", "rcpt_email", "letter_date", "subject", "body", "ref_line",
           "greeting", "sign_name", "sign_image", "lang", "template_id", "channel", "tracking_no", "followup_days")


def lt_line(v, name, mx=LT_LINE_MAX):
    """One line of text (control characters and line breaks out, trimmed, at most mx)."""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", name))
    return LT_CTRL_RE.sub("", re.sub(r"[\r\n\t]+", " ", v)).strip()[:mx]


def lt_multi(v, name, mx):
    """Text with line breaks (\\r dropped, control characters out); longer than mx = 400."""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", name))
    v = LT_CTRL_RE.sub("", v.replace("\r\n", "\n").replace("\r", "\n"))
    if len(v) > mx:
        raise BadInput(tr("The text is too long"))
    return v.strip("\n")


def lt_row(c, oid, lid):
    """The decrypted letter lid of office area oid (dict); 404 when missing / of another area."""
    try:
        lid = int(lid)
    except (TypeError, ValueError):
        raise Denied(404) from None
    r = c.execute("SELECT * FROM office_letters WHERE id=? AND org_id=?", (lid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return oc_dec_fields(c, oid, "office_letters", r)


def lt_clean(c, oid, b, cur=None):
    """The editable columns of body b (dict) checked -> dict of columns to write. cur = the current row (PATCH).
    Clients / contacts / templates must belong to the area (404 otherwise)."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    out = {}
    for k in LT_EDIT:
        if k not in b:
            continue
        v = b[k]
        if k in ("client_id", "contact_id", "template_id"):
            if v in (None, "", 0):
                out[k] = None
                continue
            if isinstance(v, bool):
                raise BadInput(tr("Invalid value: {0}", k))
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise BadInput(tr("Invalid value: {0}", k)) from None
            if k == "client_id":
                from .model import pb_cl_sql
                ok = c.execute(f"SELECT 1 FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (v,)).fetchone()
            elif k == "template_id":
                ok = c.execute("SELECT 1 FROM office_doc_templates WHERE id=? AND org_id=?", (v, oid)).fetchone()
            else:
                ok = lt_contact_ok(c, oid, v)
            if not ok:
                raise Denied(404)
            out[k] = v
        elif k in ("body",):
            out[k] = lt_multi(v, k, LT_BODY_MAX)
        elif k == "rcpt_address":
            out[k] = lt_multi(v, k, LT_ADDR_MAX)
        elif k == "letter_date":
            v = lt_line(v, k, 10)
            if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
        elif k == "channel":
            if v not in LT_CHANNEL_KEYS:
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
        elif k == "sign_image":
            out[k] = 1 if v else 0
        elif k == "followup_days":
            if isinstance(v, bool):
                raise BadInput(tr("Invalid value: {0}", k))
            try:
                v = int(v or 0)
            except (TypeError, ValueError):
                raise BadInput(tr("Invalid value: {0}", k)) from None
            if not 0 <= v <= 365:
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
        elif k == "lang":
            out[k] = v if v in ("", "de", "en") else ""
        elif k == "rcpt_email":
            v = lt_line(v, k, 254)
            if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
                raise BadInput(tr("Invalid e-mail address"))
            out[k] = v
        else:
            out[k] = lt_line(v, k, 120 if k == "tracking_no" else LT_LINE_MAX)
    return out


def lt_uid():
    """The signed-in person of the request (None outside a request)."""
    u = g.get("user") if has_request_context() else None
    return u["id"] if u is not None else None


def lt_lang(c, oid, v=None):
    """'de' | 'en': the letter's language, else the office's document language."""
    from .doctpl import dt_lang
    return v if v in ("de", "en") else dt_lang(c, oid)


# ---------------------------------------------------------------- recipients: clients of the office, address book contacts
def lt_book_ids(c, oid, uid):
    """The address books (ids) person uid sees in the space of office area oid: a personal office = the books of the
    private space (no organisation), an organisation's office = that organisation's books. Never across the boundary."""
    from ..contacts.model import contacts_on, my_book_ids
    owner = pb_owner(c, oid)
    if not uid or (owner is not None and owner != uid) or not contacts_on(c, uid):
        return []
    ids = list(my_book_ids(c, uid))
    if not ids:
        return []
    cond = "org_id IS NULL" if owner is not None else f"org_id={int(oid)}"
    return [r[0] for r in c.execute(f"SELECT id FROM books WHERE id IN ({','.join('?' * len(ids))}) AND {cond}", ids)]


def lt_contact_ok(c, oid, cid):
    """True when address book contact cid may be used as a recipient in office area oid: its address book is one the
    current person sees in the office's space (lt_book_ids)."""
    r = c.execute("SELECT book_id FROM contacts WHERE id=?", (cid,)).fetchone()
    return bool(r) and r[0] in lt_book_ids(c, oid, lt_uid())


def lt_jl(v):
    try:
        x = json.loads(v or "[]")
        return x if isinstance(x, list) else []
    except ValueError:
        return []


def lt_pref(items):
    """The preferred entry of a contact's JSON list (pref first, else the first)."""
    items = [x for x in items if isinstance(x, dict)]
    return next((x for x in items if x.get("pref")), items[0] if items else None)


def lt_home(country):
    return (country or "").strip().upper() in ("", "DE", "DEU", "DEUTSCHLAND", "GERMANY")


def lt_client_rcpt(c, cl, attn="", lg=None):
    """The recipient snapshot of client cl (dict): its (legal) name, the address lines (attn = a contact person
    "z. Hd.", in language lg), the e-mail."""
    lines = [tr("Attn. {0}", attn, lg=lg)] if attn else []
    lines += [x for x in ((cl.get("street") or "").strip(), (cl.get("address_extra") or "").strip(),
                          " ".join(y for y in ((cl.get("zip") or "").strip(), (cl.get("city") or "").strip()) if y)) if x]
    if not lt_home(cl.get("country")):
        lines.append(cl["country"].strip())
    return {"client_id": cl["id"], "rcpt_name": cl.get("name") or "", "rcpt_address": "\n".join(lines),
            "rcpt_email": (cl.get("email_invoice") or cl.get("email") or "").strip()}


def lt_contact_rcpt(r):
    """The recipient snapshot of an address book contact: the organisation first when the person works there, the
    preferred address and e-mail."""
    fn = (r["fn"] or " ".join(x for x in (r["given"], r["family"]) if x)).strip()
    org = (r["org"] or "").strip()
    name, lines = (org, [fn]) if org and fn and org != fn else (fn or org, [])
    a = lt_pref(lt_jl(r["addresses"]))
    if a:
        lines += [x.strip() for x in str(a.get("street") or "").split("\n") if x.strip()]
        lines += [x for x in ((a.get("ext") or "").strip(), (a.get("pobox") or "").strip()) if x]
        city = " ".join(y for y in ((a.get("code") or "").strip(), (a.get("city") or "").strip()) if y)
        if city:
            lines.append(city)
        if not lt_home(a.get("country")):
            lines.append(str(a["country"]).strip())
    e = lt_pref(lt_jl(r["emails"]))
    return {"contact_id": r["id"], "rcpt_name": name, "rcpt_address": "\n".join(lines), "rcpt_email": ((e or {}).get("value") or "").strip()}


def lt_like(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def lt_recipients(c, oid, uid, q="", limit=20):
    """[{kind client | contact, label, sub, rcpt_*, client_id | contact_id}]: the office's clients (+ their contact
    persons as "z. Hd.") and the address book contacts the person sees in the office's space, matching q."""
    from .contacts_cl import fk_contacts
    words = [w for w in re.split(r"\s+", (q or "").lower().strip()) if w][:6]
    lg = lt_lang(c, oid)
    sql, args = f"SELECT * FROM clients WHERE {pb_cl_sql(c, oid)} AND archived=0", []
    for w in words:
        sql += " AND (name ILIKE ? ESCAPE '\\' OR display_name ILIKE ? ESCAPE '\\' OR city ILIKE ? ESCAPE '\\')"
        args += [lt_like(w)] * 3
    out = []
    for r in c.execute(sql + " ORDER BY lower(name), id LIMIT ?", args + [limit]).fetchall():
        cl = dict(r)
        x = lt_client_rcpt(c, cl)
        out.append({"kind": "client", "label": cl.get("display_name") or cl["name"], "sub": x["rcpt_address"].replace("\n", ", "), **x})
        for k in fk_contacts(c, cl["id"])[:5]:
            if k["name"]:
                y = lt_client_rcpt(c, cl, k["name"], lg)
                if k.get("email"):
                    y["rcpt_email"] = k["email"]
                out.append({"kind": "client", "label": f"{cl.get('display_name') or cl['name']} · {k['name']}", "sub": y["rcpt_address"].replace("\n", ", "), **y})
    books = lt_book_ids(c, oid, uid)
    if books:
        sql, args = f"SELECT * FROM contacts WHERE book_id IN ({','.join('?' * len(books))}) AND kind!='group'", list(books)
        for w in words:
            sql += " AND search ILIKE ? ESCAPE '\\'"
            args.append(lt_like(w))
        for r in c.execute(sql + " ORDER BY lower(CASE WHEN family!='' THEN family ELSE fn END), lower(fn), id LIMIT ?", args + [limit]).fetchall():
            x = lt_contact_rcpt(r)
            out.append({"kind": "contact", "label": x["rcpt_name"], "sub": x["rcpt_address"].replace("\n", ", ") or x["rcpt_email"], **x})
    return out


# ---------------------------------------------------------------- the signature profile of a person in an office area
def lt_profile(c, oid, uid):
    """The decrypted office_letter_profiles row of person uid in area oid (dict) or None."""
    if not uid:
        return None
    r = c.execute("SELECT * FROM office_letter_profiles WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    return dict(oc_dec_fields(c, oid, "office_letter_profiles", r)) if r else None


def lt_user_name(c, uid):
    r = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return (r["display_name"] or r["username"] or "") if r else ""


def lt_profile_public(c, oid, uid, lg=None):
    p = lt_profile(c, oid, uid) or {}
    img = p.get("image") or ""
    return {"greeting": p.get("greeting") or "", "name": p.get("name") or "", "has_image": bool(img),
            "image": f"data:{p.get('image_mime') or 'image/png'};base64,{img}" if img else "",
            "default_greeting": tr(LT_GREETING, lg=lg), "default_name": lt_user_name(c, uid)}


def lt_image_in(v):
    """A signature picture (data URI or base64) -> (base64 text, mime); PNG / JPEG only, at most LT_IMG_MAX bytes."""
    if not isinstance(v, str) or not v.strip():
        raise BadInput(tr("Invalid value: {0}", "image"))
    raw = v.strip()
    m = re.match(r"data:([a-z/+.-]+);base64,", raw)
    if m:
        raw = raw[m.end():]
    if len(raw) > LT_IMG_MAX * 4 // 3 + 8:
        raise BadInput(tr("The picture is too large (at most {0} KB)", LT_IMG_MAX // 1024))
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise BadInput(tr("Invalid value: {0}", "image")) from None
    if len(data) > LT_IMG_MAX:
        raise BadInput(tr("The picture is too large (at most {0} KB)", LT_IMG_MAX // 1024))
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    else:
        raise BadInput(tr("Please choose a PNG or JPEG picture"))
    from .pdf import pdf_image_object
    if not pdf_image_object(data):
        raise BadInput(tr("Please choose a PNG or JPEG picture"))
    from ..files.scan import sc_scan  # 2.153.0: virus scan like every upload (2.148.1 E, #2496)
    from ..files.upsafe import UploadRefused
    try:
        sc_scan("signature.png" if mime == "image/png" else "signature.jpg", data)
    except UploadRefused as e:
        raise BadInput(str(e)) from None
    return base64.b64encode(data).decode("ascii"), mime


def lt_profile_save(c, oid, uid, upd):
    """Writes the columns upd (greeting / name / image / image_mime) of uid's profile in area oid. No commit."""
    upd = oc_enc_fields(c, oid, "office_letter_profiles", {**upd, "updated_at": iso(now_utc())})
    if c.execute("SELECT 1 FROM office_letter_profiles WHERE org_id=? AND user_id=?", (oid, uid)).fetchone():
        c.execute(f"UPDATE office_letter_profiles SET {', '.join(k + '=?' for k in upd)} WHERE org_id=? AND user_id=?", list(upd.values()) + [oid, uid])
    else:
        row = {"org_id": oid, "user_id": uid, **upd}
        c.execute(f"INSERT INTO office_letter_profiles({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)


# ---------------------------------------------------------------- the letters
def lt_create(c, oid, uid, data, agent_id=None):
    """A new draft letter in office area oid from data (dict, checked by lt_clean) -> its id. uid = the person (None for
    an agent; agent_id then names it). Date defaults to today, language to the office's document language, greeting /
    signer / signature picture to the person's profile; a client / contact without a recipient name given fills the
    recipient snapshot. No commit (the caller commits)."""
    row = lt_clean(c, oid, data or {})
    if not row.get("letter_date"):
        row["letter_date"] = local_now().date().isoformat()
    row["lang"] = lt_lang(c, oid, row.get("lang"))
    if not row.get("rcpt_name") and not row.get("rcpt_address"):
        snap = None
        if row.get("client_id"):
            snap = lt_client_rcpt(c, dict(c.execute("SELECT * FROM clients WHERE id=?", (row["client_id"],)).fetchone()))
        elif row.get("contact_id"):
            snap = lt_contact_rcpt(c.execute("SELECT * FROM contacts WHERE id=?", (row["contact_id"],)).fetchone())
        if snap:
            row.update({k: v for k, v in snap.items() if k.startswith("rcpt_") and (k != "rcpt_email" or not row.get("rcpt_email"))})
    prof = lt_profile(c, oid, uid) or {}
    if "greeting" not in row:
        row["greeting"] = prof.get("greeting") or tr(LT_GREETING, lg=row["lang"])
    if "sign_name" not in row:
        row["sign_name"] = (prof.get("name") or lt_user_name(c, uid)) if uid else ""
    if "sign_image" not in row:
        row["sign_image"] = 1 if prof.get("image") else 0
    ts = iso(now_utc())
    row.update(org_id=oid, status="draft", created_by=uid, agent_id=agent_id, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_letters", row)
    lid = insert_id(c, f"INSERT INTO office_letters({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)
    return lid


def lt_update(c, oid, lid, data, draft_only=True):
    """Writes the checked columns of data into letter lid (400 when it is no draft and draft_only). No commit."""
    cur = lt_row(c, oid, lid)
    if draft_only and cur["status"] != "draft":
        raise BadInput(tr("Only a draft can be changed"))
    row = lt_clean(c, oid, data or {}, cur)
    if not row:
        return cur
    row["updated_at"] = iso(now_utc())
    row = oc_enc_fields(c, oid, "office_letters", row)
    c.execute(f"UPDATE office_letters SET {', '.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [cur["id"], oid])
    bump(c)
    return lt_row(c, oid, lid)


# ---------------------------------------------------------------- the PDF: DIN 5008 form B (office/pdf.py's parts, like doctpl.dt_pdf)
def lt_sig_image(c, oid, d):
    """The signature picture for letter d: only with sign_image and only the profile of the person who wrote it -- and only
    while that person prints / sends it (review 2.153.0: another admin never puts someone else's handwritten signature
    under a text); a draft of an agent (no writer) takes the picture of the person who handles it."""
    if not d.get("sign_image"):
        return None
    me = lt_uid()
    owner = d.get("created_by") or me
    if not owner or (me is not None and me != owner):
        return None
    p = lt_profile(c, oid, owner)
    if not p or not p.get("image"):
        return None
    from .pdf import pdf_image_object
    try:
        return pdf_image_object(base64.b64decode(p["image"]))
    except (binascii.Error, ValueError):
        return None


def lt_pdf(c, oid, d):
    """The PDF (bytes, PDF/A-3b) of letter d (a decrypted office_letters row): letterhead (logo or name), fold marks,
    the sender line (ledger.ofx_sender_line) and the recipient in the window, the date on the right, the reference line,
    the subject in bold, the text (paragraphs, "- " lists, "## " headings), greeting, signature picture, name; following
    pages with a small head; the footer as the other office PDFs. A draft says DRAFT."""
    from . import pdf as P
    from .docs import _fmt_date
    from .doctpl import _pack, dt_blocks, dt_company
    from .ledger import ofx_sender_line
    lang = lt_lang(c, oid, d.get("lang"))
    co = dt_company(c, oid, lang)
    accent = co.get("color") or "#2f5d8a"
    images = {}
    logo = None
    if co.get("logo_path"):
        try:
            with open(co["logo_path"], "rb") as fh:
                logo = P.pdf_image_object(fh.read(16 * 1024 * 1024))
        except OSError:
            logo = None
        if logo:
            images["Logo"] = logo
    sig = lt_sig_image(c, oid, d)
    if sig:
        images["Sig"] = sig
    subject = d.get("subject") or ""
    title = subject or tr("Letter", lg=lang)
    draft = tr("Draft", lg=lang).upper() if d.get("status") == "draft" else ""
    body_sz, lh = 10, 10 * 1.42
    pages = []
    # 2.184.0 C (#2581): an own letterhead (office.letterhead) lies under the letter as under the other office PDFs
    blh = bp_letter(c, oid)
    geo = P.bp_geometry(blh) if blh else None
    BPD = geo["bp"] if geo else None
    PL, PCW, PAT, PNT = (geo["l"], geo["cw"], geo["addr_top"], geo["next_top"]) if geo else (P.PDF_L, P.PDF_CW, P.PDF_ADDR_TOP, P.PDF_NEXT_TOP)
    PBB = (BPD["bottom"][0] if BPD["hide_footer"] else min(BPD["bottom"][0], P.PDF_BODY_BOTTOM)) if BPD else P.PDF_BODY_BOTTOM
    PBB2 = (BPD["bottom"][1] if BPD["hide_footer"] else min(BPD["bottom"][1], P.PDF_BODY_BOTTOM)) if BPD else P.PDF_BODY_BOTTOM
    hide_head = bool(BPD and BPD["hide_head"])

    def new_page(first):
        p = P._Page()
        if first:
            if hide_head:  # the letterhead brings logo, name and fold marks
                pass
            elif logo:
                sc = min(P.PDF_LOGO_MAX_W / logo[0], P.PDF_LOGO_MAX_H / logo[1])
                p.image("Logo", PL + PCW - logo[0] * sc, P.PDF_TOP + 2 * P.MM, logo[0] * sc, logo[1] * sc)
            else:
                p.text(PL + PCW, P.PDF_TOP + 4 * P.MM, co.get("name") or "", 15, True, P.C_INK, align="r", spacing=1.2)
                p.rect(PL + PCW - 12 * P.MM, P.PDF_TOP + 4 * P.MM + 24, 12 * P.MM, 2.2, accent)
            for y in (() if hide_head else (105 * P.MM, 148.5 * P.MM, 210 * P.MM)):  # fold marks + punch mark
                p.line(5 * P.MM, y, 9 * P.MM, y, 0.4, P.C_RULE)
            if draft:
                p.text(PL, P.PDF_TOP + 4 * P.MM, draft, 15, True, accent, spacing=1.2)
        else:
            hy = PNT - 18 * P.MM if BPD else 12 * P.MM
            hy = max(4 * P.MM, hy)
            if not hide_head:
                p.text(PL + PCW, hy, co.get("name") or "", 9, True, P.C_INK, align="r", spacing=0.6)
            p.text(PL, hy + 2, (draft + " · " if draft else "") + title, 8, draft != "", accent if draft else P.C_INK2)
            p.line(PL, hy + 12.5 * P.MM if BPD else 24.5 * P.MM, PL + PCW, hy + 12.5 * P.MM if BPD else 24.5 * P.MM, 0.5, accent)
        pages.append(p)
        return p

    page = new_page(True)
    sender = ofx_sender_line(co)
    while P.pdf_text_width(sender, 7) > P.PDF_ADDR_W and " · " in sender:
        sender = sender.rsplit(" · ", 1)[0]
    y = PAT
    page.text(PL, y, sender, 7, False, P.C_INK2)
    page.line(PL, y + 11, PL + P.PDF_ADDR_W, y + 11, 0.5, P.C_RULE2)
    addr = [x for x in [(d.get("rcpt_name") or "").strip()] + [ln.strip() for ln in (d.get("rcpt_address") or "").split("\n")] if x]
    yy = y + 16
    for ln in addr[:9]:
        for s in P.pdf_wrap(ln, body_sz, P.PDF_ADDR_W)[:1]:
            page.text(PL, yy, s, body_sz)
        yy += lh
    info_x = PL + P.PDF_ADDR_W + 8 * P.MM
    info_w = PCW - P.PDF_ADDR_W - 8 * P.MM
    page.text(info_x, y + 2, tr("Date", lg=lang), 8.6, False, P.C_INK2)
    page.text(info_x, y + 2, _fmt_date(d.get("letter_date") or local_now().date().isoformat(), _pack(c, oid)), 8.6, True, P.C_INK, align="r", width=info_w)
    if d.get("tracking_no") and d.get("channel") == "registered":
        page.text(info_x, y + 16, tr("Registered mail", lg=lang), 8.6, False, P.C_INK2)
        page.text(info_x, y + 16, d["tracking_no"][:30], 8, False, P.C_INK, align="r", width=info_w)
    y = PAT + P.PDF_ADDR_H + 8 * P.MM

    def room(h):
        nonlocal page, y
        if y + h > (PBB if len(pages) < 2 else PBB2):
            page = new_page(False)
            y = PNT
    if d.get("ref_line"):
        for s in P.pdf_wrap(d["ref_line"], 8.4, PCW):
            page.text(PL, y, s, 8.4, False, P.C_INK2)
            y += 8.4 * 1.4
        y += 6
    if subject:
        for s in P.pdf_wrap(subject, 11, PCW, True):
            room(11 * 1.42)
            page.text(PL, y, s, 11, True, P.C_INK)
            y += 11 * 1.42
        y += lh
    for k, t in dt_blocks(d.get("body") or ""):
        if k in ("h1", "h2"):
            room(22 + lh * 2)  # a heading never stays alone at the end of a page
            y += 4
            for s in P.pdf_wrap(t, 10.4, PCW, True):
                page.text(PL, y, s, 10.4, True, P.C_INK)
                y += 10.4 * 1.42
            y += 2
        elif k == "li":
            for j, s in enumerate(P.pdf_wrap(t, body_sz, PCW - 14)):
                room(lh)
                if j == 0:
                    page.text(PL + 3, y, "•", body_sz, False, P.C_INK)
                page.text(PL + 14, y, s, body_sz)
                y += lh
            y += 2
        else:
            for s in P.pdf_wrap(t, body_sz, PCW):
                room(lh)
                page.text(PL, y, s, body_sz)
                y += lh
            y += lh * 0.6
    # greeting, the signature picture, the name: kept together
    sig_h = 0
    if sig:
        sig_h = 16 * P.MM
        sig_w = min(60 * P.MM, sig[0] * sig_h / sig[1])
        sig_h = sig_w * sig[1] / sig[0]
    room(lh * 2 + (sig_h or lh * 2) + lh)
    y += lh * 0.4
    if d.get("greeting"):
        for s in P.pdf_wrap(d["greeting"], body_sz, PCW):
            page.text(PL, y, s, body_sz)
            y += lh
    if sig:
        page.image("Sig", PL, y + 2, sig_w, sig_h)
        y += sig_h + 6
    else:
        y += lh * 2
    sname = d.get("sign_name") or ""
    if not sname and not d.get("created_by") and lt_uid():  # an agent's draft: the name of the person who handles it
        me = lt_uid()
        sname = (lt_profile(c, oid, me) or {}).get("name") or lt_user_name(c, me)
    if sname:
        page.text(PL, y, sname, body_sz)
    total = len(pages)
    foot = " · ".join(str(x) for x in [co.get("name") or ""] + list(co.get("lines") or []) + list(co.get("contact_lines") or []) if str(x).strip())
    for n, p in enumerate(pages, 1):
        if BPD and BPD["hide_footer"]:  # the letterhead has its own footer: only the page count under the body
            p.text(PL + PCW, BPD["bottom"][n > 1] + 3 * P.MM, tr("Page {0} of {1}", n, total, lg=lang), 6.8, False, P.C_INK2, align="r")
            continue
        top = P.A4_H - 12 * P.MM - P.PDF_FOOT_H
        p.line(PL, top, PL + PCW, top, 0.5, P.C_RULE)
        for j, s in enumerate(P.pdf_wrap(foot, 6.9, PCW)[:3]):
            p.text(PL, top + 5 + j * 9.6, s, 6.9, False, P.C_INK2)
        p.text(PL + PCW, P.A4_H - 9 * P.MM, tr("Page {0} of {1}", n, total, lg=lang), 6.8, False, P.C_INK2, align="r")
    if BPD:
        P.bp_finish(pages, BPD)
    meta = {"when": now_utc(), "producer": f"Kalmido {APP_VERSION}"}
    return P.pdf_write(pages, images, title=title, author=co.get("name") or "", meta=meta)


def lt_file(c, oid, uid, d, data):
    """Files the PDF of sent letter d into the documents space of the office (sealed like every upload): in the folder of
    the client, without a client in the folder "Correspondence" -> the node id. ext_id letter:<id> = idempotent."""
    from ..docs import store as S
    from ..docs.ingest import docs_ingest
    owner = pb_owner(c, oid)
    who, org = (owner, None) if owner is not None else (uid, oid)
    title = re.sub(r"[\\/]+", "-", d.get("subject") or tr("Letter"))[:150]
    day = d.get("letter_date") or local_now().date().isoformat()
    meta = {"ext_id": f"letter:{d['id']}", "date": day, "type": tr("Letter"), "text": "\n\n".join(x for x in (d.get("subject"), d.get("body")) if x)}
    nid = docs_ingest(c, who, org, f"{day} {title}.pdf", data, "application/pdf", "office", meta)
    folder = tr("Correspondence")
    if d.get("client_id"):
        r = c.execute(f"SELECT name FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (d["client_id"],)).fetchone()
        folder = r["name"] if r and r["name"] else folder
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    fid = S.folder_by_name(c, node, who, folder) if node else None
    if fid and node["parent_id"] != fid:
        S.move_to_folder(c, node, fid)
    return nid


def lt_names(c, oid, rows):
    """{client id: name} of the letters' clients (the office's own only)."""
    cids = sorted({r["client_id"] for r in rows if r.get("client_id")})
    if not cids:
        return {}
    return {r["id"]: r["display_name"] or r["name"] for r in
            c.execute(f"SELECT id, name, display_name FROM clients WHERE id IN ({','.join('?' * len(cids))}) AND {pb_cl_sql(c, oid)}", cids)}


def lt_public(c, oid, d, names=None, brief=False):
    """The JSON form of a decrypted letter row (brief: without the text, for lists)."""
    keep = ("id", "client_id", "contact_id", "rcpt_name", "rcpt_address", "rcpt_email", "letter_date", "subject", "body", "ref_line",
            "greeting", "sign_name", "sign_image", "lang", "template_id", "channel", "status", "tracking_no", "sent_at", "delivered_at",
            "followup_days", "followup_due", "followup_task_id", "node_id", "agent_id", "created_by", "created_at", "updated_at")
    out = {k: d.get(k) for k in keep if not (brief and k == "body")}
    if names is None:
        names = lt_names(c, oid, [d])
    out.update(archived=int(d.get("archived") or 0), client_name=names.get(d.get("client_id"), ""),
               channel_label=tr(dict(LT_CHANNELS).get(d.get("channel"), "Post")), status_label=tr(dict(LT_STATUS).get(d.get("status"), "Draft")))
    return out


def lt_meta(c, oid, uid):
    """What the editor offers: clients of the office, letter templates, the person's profile, channels, states."""
    from .doctpl import dt_lang
    cls = [{"id": r["id"], "name": r["name"], "display_name": r["display_name"] or ""} for r in
           c.execute(f"SELECT id, name, display_name FROM clients WHERE {pb_cl_sql(c, oid)} AND archived=0 ORDER BY lower(name) LIMIT ?", (LT_LIST_MAX,))]
    tpls = [oc_dec_fields(c, oid, "office_doc_templates", r) for r in
            c.execute("SELECT * FROM office_doc_templates WHERE org_id=? AND kind='letter' AND archived=0 ORDER BY lower(name), id LIMIT ?", (oid, LT_LIST_MAX))]
    lang = dt_lang(c, oid)
    return {"clients": cls, "templates": [{"id": t["id"], "name": t["name"], "lang": t["lang"]} for t in tpls],
            "profile": lt_profile_public(c, oid, uid, lang), "lang": lang, "me": uid,
            "channels": [{"key": k, "label": tr(n)} for k, n in LT_CHANNELS], "statuses": [{"key": k, "label": tr(n)} for k, n in LT_STATUS]}


# ---------------------------------------------------------------- routes
def lt_org(c, uid):
    """The office area of uid for the correspondence: its admins only (like the document templates). office_org(admin=True)
    lets the accounting role read since 2.143.0 (#2151); letters are not bookkeeping, so the role itself must be admin
    (review A3, as letteragent._v1ctx)."""
    oid = office_org(c, uid, admin=True)
    if office_role(c, uid, oid) != "admin":
        raise Denied(403, tr(OFFICE_ADMIN_ONLY))
    return oid


def lt_ctx():
    """Admins of the office area only (like the document templates)."""
    from ..core.db import db
    c = db()
    uid = office_gate(c)
    return c, uid, lt_org(c, uid)


def lt_iid(v, name):
    if isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", name))
    try:
        return int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name)) from None


@app.get("/api/office/letters")
def lt_list():
    """?status=&client_id=&q=&archived=1&brief=1 -> {letters (newest first, without the text), + clients, templates,
    profile, channels, statuses unless brief}."""
    c, uid, oid = lt_ctx()
    sql, args = "SELECT * FROM office_letters WHERE org_id=?", [oid]
    if request.args.get("archived") != "1":
        sql += " AND archived=0"
    st = request.args.get("status") or ""
    if st:
        if st not in LT_STATUS_KEYS:
            raise BadInput(tr("Invalid value: {0}", "status"))
        sql += " AND status=?"
        args.append(st)
    if request.args.get("client_id"):
        sql += " AND client_id=?"
        args.append(lt_iid(request.args.get("client_id"), "client_id"))
    rows = [oc_dec_fields(c, oid, "office_letters", r) for r in c.execute(sql + " ORDER BY letter_date DESC, id DESC LIMIT ?", args + [LT_LIST_MAX])]
    words = [w for w in re.split(r"\s+", (request.args.get("q") or "").lower().strip()) if w][:6]
    if words:  # the texts are encrypted at rest: matched after decrypting
        rows = [d for d in rows if all(w in " ".join(str(d.get(k) or "") for k in ("rcpt_name", "rcpt_address", "rcpt_email", "subject", "ref_line", "tracking_no")).lower()
                                       for w in words)]
    names = lt_names(c, oid, rows)
    out = {"letters": [lt_public(c, oid, d, names, brief=True) for d in rows]}
    if request.args.get("brief") != "1":
        out.update(lt_meta(c, oid, uid))
    return jsonify(out)


# review 2.153.0: no sign_name / sign_image -- a copy is signed by the person copying it (their profile, lt_create)
LT_COPY = ("client_id", "contact_id", "rcpt_name", "rcpt_address", "rcpt_email", "subject", "body", "ref_line", "greeting",
           "lang", "template_id", "channel", "followup_days")


@app.post("/api/office/letters")
def lt_post():
    """A new draft {client_id?, contact_id?, rcpt_*?, letter_date?, subject?, body?, …} -> 201 + the letter.
    answers: document node id: recipient and reference line prefilled from the document (office/letterlinks.py
    ltl_prefill) and linked. copy_of: id = a copy of that letter as a new draft (today's date). template_id without a
    body: subject + text from the template, its variables filled (client.*, company.*, today)."""
    from .doctpl import dt_fill, dt_tpl, dt_values
    from .letterlinks import ltl_link, ltl_prefill
    c, uid, oid = lt_ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    data = {k: v for k, v in b.items() if k not in ("copy_of", "answers")}
    if b.get("copy_of") not in (None, ""):
        src = lt_row(c, oid, b["copy_of"])
        data = {**{k: src.get(k) for k in LT_COPY}, **data}
        if data.get("contact_id") and not lt_contact_ok(c, oid, data["contact_id"]):
            data["contact_id"] = None  # the contact is no longer reachable: the snapshot stays
    elif data.get("template_id") not in (None, "", 0) and data.get("body") in (None, ""):
        t = dt_tpl(c, oid, data["template_id"])
        lang = lt_lang(c, oid, data.get("lang") or t["lang"])
        cid = data.get("client_id") if data.get("client_id") not in ("", 0) else None
        data["body"] = dt_fill(t["body"], dt_values(c, oid, lang, cid))[0].strip("\n")
        data["lang"] = lang
        if not data.get("subject"):
            data["subject"] = t["name"]
    nid = b.get("answers")
    if nid not in (None, ""):
        if isinstance(nid, bool) or not str(nid).isdigit():
            raise BadInput(tr("Invalid value: {0}", "answers"))
        nid = int(nid)
        pre = ltl_prefill(c, oid, uid, nid) or {}
        data = {**pre, **{k: v for k, v in data.items() if v not in (None, "")}}
    lid = lt_create(c, oid, uid, data)
    if nid not in (None, ""):
        ltl_link(c, oid, lid, nid, "answers", uid=uid)
    c.commit()
    return jsonify(lt_public(c, oid, lt_row(c, oid, lid))), 201


@app.get("/api/office/letters/recipients")
def lt_recipients_get():
    """?q= -> {recipients: [{kind client | contact, label, sub, rcpt_name, rcpt_address, rcpt_email, client_id | contact_id}]}."""
    c, uid, oid = lt_ctx()
    return jsonify(recipients=lt_recipients(c, oid, uid, (request.args.get("q") or "")[:100]))


@app.get("/api/office/letters/profile")
def lt_profile_get():
    c, uid, oid = lt_ctx()
    return jsonify(lt_profile_public(c, oid, uid, lt_lang(c, oid)))


@app.put("/api/office/letters/profile")
def lt_profile_put():
    """{greeting?, name?, image?: PNG / JPEG as data URI or base64 (at most 300 KB)} -> the profile."""
    c, uid, oid = lt_ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    upd = {}
    for k in ("greeting", "name"):
        if k in b:
            upd[k] = lt_line(b[k], k, 120)
    if b.get("image") not in (None, ""):
        upd["image"], upd["image_mime"] = lt_image_in(b["image"])
    if upd:
        lt_profile_save(c, oid, uid, upd)
        c.commit()
    return jsonify(lt_profile_public(c, oid, uid, lt_lang(c, oid)))


@app.delete("/api/office/letters/profile/image")
def lt_profile_image_delete():
    c, uid, oid = lt_ctx()
    if lt_profile(c, oid, uid):
        lt_profile_save(c, oid, uid, {"image": "", "image_mime": ""})
        c.commit()
    return jsonify(lt_profile_public(c, oid, uid, lt_lang(c, oid)))


@app.get("/api/office/letters/<int:lid>")
def lt_get(lid):
    c, uid, oid = lt_ctx()
    return jsonify(lt_public(c, oid, lt_row(c, oid, lid)))


@app.patch("/api/office/letters/<int:lid>")
def lt_patch(lid):
    """A draft's fields (lt_clean); a sent letter: 409 (a change = "Edit a copy")."""
    c, uid, oid = lt_ctx()
    write_lock(c, f"office_letter_{int(lid)}")
    if lt_row(c, oid, lid)["status"] != "draft":
        return err(tr("A sent letter cannot be changed any more. Edit a copy instead."), 409)
    d = lt_update(c, oid, lid, body())
    c.commit()
    return jsonify(lt_public(c, oid, d))


@app.delete("/api/office/letters/<int:lid>")
def lt_delete(lid):
    """Archives a letter (a filed PDF stays in the documents space); POST .../restore takes it back (the undo)."""
    c, uid, oid = lt_ctx()
    lt_row(c, oid, lid)
    c.execute("UPDATE office_letters SET archived=1, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), lid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/office/letters/<int:lid>/restore")
def lt_restore(lid):
    c, uid, oid = lt_ctx()
    lt_row(c, oid, lid)
    c.execute("UPDATE office_letters SET archived=0, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), lid, oid))
    bump(c)
    c.commit()
    return jsonify(lt_public(c, oid, lt_row(c, oid, lid)))


@app.get("/api/office/letters/<int:lid>/pdf")
def lt_pdf_get(lid):
    """The PDF (inline; ?dl=1 as download): a sent letter = the filed file while the admin reaches it, else written anew;
    a draft = a preview marked DRAFT."""
    from ..files.store import fs_read, fs_role
    from .doctpl import dt_disposition
    c, uid, oid = lt_ctx()
    d = lt_row(c, oid, lid)
    data = None
    if d["status"] != "draft" and d.get("node_id"):
        n = c.execute("SELECT deleted_at FROM fs_nodes WHERE id=?", (d["node_id"],)).fetchone()
        if n and not n["deleted_at"] and fs_role(c, d["node_id"], uid):
            try:
                data = fs_read(c, d["node_id"])
            except Denied:
                data = None
    if data is None:
        data = lt_pdf(c, oid, d)
    resp = Response(data, mimetype="application/pdf")
    disp = dt_disposition(d.get("subject") or tr("Letter"))
    resp.headers["Content-Disposition"] = disp if request.args.get("dl") == "1" else disp.replace("attachment;", "inline;", 1)
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


def lt_mark_sent(c, oid, d, channel=None, tracking_no=None, followup_days=None, msg_id=None, uid=None):
    """Marks letter d (decrypted row, a draft) as sent today: status, sent_at, channel, tracking number, the follow-up date
    (sent + followup_days), msg_id (#2029); the PDF is written once and filed into the documents space (node_id; uid =
    the person filing it, default the signed-in one). No commit -> the new row (the caller commits, then docs_kick)."""
    if d["status"] != "draft":
        raise BadInput(tr("The letter has already been sent"))
    upd = {}
    if channel is not None:
        upd["channel"] = channel
    if tracking_no is not None:
        upd["tracking_no"] = tracking_no
    if followup_days is not None:
        upd["followup_days"] = followup_days
    if upd:
        d = lt_update(c, oid, d["id"], upd)
    days = int(d.get("followup_days") or 0)
    today = local_now().date()
    ts = iso(now_utc())
    c.execute("UPDATE office_letters SET status='sent', sent_at=?, followup_due=?, msg_id=?, updated_at=? WHERE id=? AND org_id=?",
              (ts, (today + timedelta(days=days)).isoformat() if days else None, msg_id or d.get("msg_id") or "", ts, d["id"], oid))
    d = lt_row(c, oid, d["id"])
    if not d.get("node_id"):
        nid = lt_file(c, oid, uid or lt_uid(), d, lt_pdf(c, oid, d))
        c.execute("UPDATE office_letters SET node_id=? WHERE id=? AND org_id=?", (nid, d["id"], oid))
    bump(c)
    return lt_row(c, oid, d["id"])


def lt_kick():
    from .doctpl import dt_kick
    dt_kick()


@app.post("/api/office/letters/<int:lid>/sent")
def lt_sent_post(lid):
    """Marks a draft as sent {channel?, tracking_no?, followup_days?}: the PDF is filed with the client. 409 when sent."""
    c, uid, oid = lt_ctx()
    b = body() or {}
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    write_lock(c, f"office_letter_{int(lid)}")
    d = lt_row(c, oid, lid)
    if d["status"] != "draft":
        return err(tr("The letter has already been sent"), 409)
    chk = lt_clean(c, oid, {k: b[k] for k in ("channel", "tracking_no", "followup_days") if k in b})
    d = lt_mark_sent(c, oid, d, chk.get("channel"), chk.get("tracking_no"), chk.get("followup_days"), uid=uid)
    c.commit()
    lt_kick()
    return jsonify(lt_public(c, oid, d))


@app.post("/api/office/letters/<int:lid>/delivered")
def lt_delivered_post(lid):
    """A sent letter arrived (status delivered, delivered_at); DELETE takes it back to sent (the undo)."""
    c, uid, oid = lt_ctx()
    write_lock(c, f"office_letter_{int(lid)}")
    d = lt_row(c, oid, lid)
    if d["status"] == "draft":
        return err(tr("Mark the letter as sent first."), 409)
    if d["status"] != "delivered":
        ts = iso(now_utc())
        c.execute("UPDATE office_letters SET status='delivered', delivered_at=?, updated_at=? WHERE id=? AND org_id=?", (ts, ts, lid, oid))
        bump(c)
        c.commit()
    return jsonify(lt_public(c, oid, lt_row(c, oid, lid)))


@app.delete("/api/office/letters/<int:lid>/delivered")
def lt_delivered_delete(lid):
    c, uid, oid = lt_ctx()
    write_lock(c, f"office_letter_{int(lid)}")
    d = lt_row(c, oid, lid)
    if d["status"] == "delivered":
        c.execute("UPDATE office_letters SET status='sent', delivered_at=NULL, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), lid, oid))
        bump(c)
        c.commit()
    return jsonify(lt_public(c, oid, lt_row(c, oid, lid)))


@app.post("/api/office/letters/<int:lid>/template")
def lt_template_post(lid):
    """Save as template {name?}: a document template of kind letter (office_doc_templates, #1927) with the letter's text
    (name = the subject) -> 201 + the template. The undo: DELETE /api/office/doc-templates/<id>."""
    from .doctpl import dt_tpl, dt_tpl_public
    c, uid, oid = lt_ctx()
    b = body() or {}
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    d = lt_row(c, oid, lid)
    name = lt_line(b.get("name"), "name", 200) or (d.get("subject") or "").strip()[:200] or tr("Letter")
    ts = iso(now_utc())
    row = oc_enc_fields(c, oid, "office_doc_templates", {"org_id": oid, "kind": "letter", "name": name, "lang": lt_lang(c, oid, d.get("lang")),
                                                          "body": d.get("body") or "", "sign": 0, "created_by": uid, "created_at": ts, "updated_at": ts})
    tid = insert_id(c, f"INSERT INTO office_doc_templates({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)
    c.commit()
    return jsonify(dt_tpl_public(dt_tpl(c, oid, tid))), 201
