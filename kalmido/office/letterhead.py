"""2.120.0 E (#2091): the own letterhead of the office documents (a PDF behind every page of quotations, invoices,
credit notes, reminders and every later kind of office.docs).

The letterhead is one PDF: its page 1 goes behind page 1 of a document, its page 2 behind the following pages (a one page
letterhead goes behind all of them). It is read with office.bpread (no PDF library) and drawn as a form XObject, so its
fonts, pictures and vector graphics come along unchanged; a PDF that cannot be read (encrypted, unknown compression,
rotated pages) is refused at the upload with one plain sentence, never later in a document.

Stored sealed like the documents (orgcrypt) below <data dir>/office/<org id>/letterhead-<sha16>.pdf; the setting
office_settings.data["letterhead"] = {file, sha256, name, bytes, pages, sizes, prev, m1, m2, hide_head, hide_footer}:
m1 / m2 = the margins of page 1 / the following pages [top, right, bottom, left] in mm (page 1: top = where the address
field begins), hide_head = no logo / company name / fold marks of our own, hide_footer = no footer columns of our own
(number and page stay, under the body). prev = the file before the last upload / removal, kept for one undo step;
older files are deleted. Finalising freezes the letterhead with the sender (lhs-<sha16>.pdf, bp_snapshot), so a
finalised document re-rendered later (the accepted quotation) looks like the original; documents finalised before have
no letterhead in their snapshot and stay as they are.

Routes (office_gate + the office area one works in; writes need its admin, a person without organisation is the admin
of the personal office):
GET    /api/office/letterhead            the state (members read)
POST   /api/office/letterhead            multipart "file": a PDF up to BP_MAX_MB MB (admin)
PUT    /api/office/letterhead            {m1, m2, hide_head, hide_footer} (admin, partial)
DELETE /api/office/letterhead            removes it from the documents (admin; the file stays as prev for the undo)
POST   /api/office/letterhead/restore    {file}: the previous file again (admin; the undo of an upload / removal)
GET    /api/office/letterhead/preview    a sample invoice with the letterhead as PDF (members read)"""
import hashlib
import logging
import os
import re

from flask import jsonify, request

from ..core.config import app, OFFICE_DIR
from ..core.i18n import tr
from ..core.db import body, db, err
from ..core.access import Denied
from ..core.orgcrypt import oc_read_file, oc_write_file
from .model import office_gate, office_org, office_settings, office_settings_save
from .bpread import BpCopier, BpDoc, BpError, bp_check
from .pdf import A4_H, A4_W
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from ..core.pg import write_lock  # 2.149.0 G (#2517): pulled up from functions

log = logging.getLogger(__name__)

BP_MAX_MB = 10
BP_DEFAULT = {"m1": [45, 20, 32, 25], "m2": [30, 20, 32, 25], "hide_head": 1, "hide_footer": 1}
BP_FILE_RE = re.compile(r"letterhead-[0-9a-f]{16}\.pdf")
BP_SNAP_RE = re.compile(r"lhs-[0-9a-f]{16}\.pdf")
BP_MIN_WIDTH_MM = 100  # the text column never gets narrower


from .model import office_ctx as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def _dir(oid):
    return os.path.join(OFFICE_DIR, str(int(oid)))


def bp_state(s):
    """The letterhead setting with every key (defaults filled in)."""
    lh = dict(BP_DEFAULT)
    lh.update({k: v for k, v in (s.get("letterhead") or {}).items() if v is not None})
    lh["file"] = lh.get("file") if BP_FILE_RE.fullmatch(str(lh.get("file") or "")) else ""
    return lh


def bp_public(lh):
    """The state for the client: no server paths, no previous file name beyond the undo marker."""
    return {"on": bool(lh["file"]), "file": lh["file"], "name": lh.get("name") or "", "bytes": int(lh.get("bytes") or 0),
            "pages": int(lh.get("pages") or 0) if lh["file"] else 0, "m1": lh["m1"], "m2": lh["m2"],
            "hide_head": 1 if lh.get("hide_head") else 0, "hide_footer": 1 if lh.get("hide_footer") else 0,
            "prev": lh.get("prev") or ""}


def bp_margins_clean(v, name):
    """[top, right, bottom, left] in mm (0..150, one decimal) or BadInput."""
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        raise BadInput(tr("Invalid value: {0}", name))
    out = []
    for x in v:
        try:
            f = float(str(x).replace(",", ".").strip())
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", name)) from None
        if f != f or f < 0 or f > 150:
            raise BadInput(tr("Margins between 0 and 150 mm"))
        out.append(round(f, 1))
    if 210 - out[1] - out[3] < BP_MIN_WIDTH_MM:
        raise BadInput(tr("The text needs at least {0} mm between the left and the right margin", BP_MIN_WIDTH_MM))
    if 297 - out[0] - out[2] < 80:
        raise BadInput(tr("The margins leave too little room for the text"))
    return out


def _save(c, oid, lh):
    s = office_settings(c, oid)
    s["letterhead"] = {k: lh.get(k) for k in ("file", "sha256", "name", "bytes", "pages", "prev", "m1", "m2", "hide_head", "hide_footer")}
    office_settings_save(c, oid, s)


def bp_purge(oid, keep):
    """Deletes the letterhead files of oid that are neither current nor kept for the undo (the frozen lhs- copies of
    finalised documents stay)."""
    d = _dir(oid)
    try:
        names = os.listdir(d)
    except OSError:
        return
    for n in names:
        if BP_FILE_RE.fullmatch(n) and n not in keep:
            try:
                os.remove(os.path.join(d, n))
            except OSError:
                pass


def bp_read(c, oid, name, snap=False):
    """The plain bytes of letterhead file name of oid (None when missing or the name is not one of ours)."""
    if not name or not (BP_SNAP_RE if snap else BP_FILE_RE).fullmatch(str(name)):
        return None
    p = os.path.join(_dir(oid), name)
    if not os.path.isfile(p):
        return None
    return oc_read_file(c, p)


def bp_snapshot(c, oid, s):
    """At finalising (office.ledger): the current letterhead frozen with the sender -> {file: lhs-<sha16>.pdf, pages,
    m1, m2, hide_head, hide_footer}, {} without one. The copy is content-addressed and never overwritten."""
    lh = bp_state(s)
    if not lh["file"]:
        return {}
    src = os.path.join(_dir(oid), lh["file"])
    if not os.path.isfile(src):
        return {}
    name = "lhs-" + lh["file"][len("letterhead-"):]
    dst = os.path.join(_dir(oid), name)
    if not os.path.isfile(dst):
        with open(src, "rb") as fh:
            raw = fh.read()  # copied as stored (sealed stays sealed with the same organisation key)
        with open(dst + ".part", "wb") as fh:
            fh.write(raw)
        os.replace(dst + ".part", dst)
    return {"file": name, "pages": int(lh.get("pages") or 1), "m1": lh["m1"], "m2": lh["m2"],
            "hide_head": 1 if lh.get("hide_head") else 0, "hide_footer": 1 if lh.get("hide_footer") else 0}


def bp_emitter(data):
    """The letterhead bytes -> (pages, emit(objs, i) -> object number) for office.pdf (bp_layout); None when it cannot
    be read (logged; the document is printed without it, never broken)."""
    try:
        doc = BpDoc(data)
        n = min(2, len(doc.pages))
        for i in range(n):  # dry run: every object resolves before a document depends on it
            BpCopier(doc, []).form(i, (1, 0, 0, 1, 0, 0))
    except (BpError, ValueError, IndexError, KeyError, TypeError, RecursionError, MemoryError) as e:  # 2.120.0 review H1: + MemoryError
        log.warning("letterhead unreadable at print time: %s", e)
        return None
    run = {}

    def emit(objs, i):
        if run.get("objs") is not objs:  # one copier per written PDF: shared fonts / pictures are written once
            run["objs"], run["cp"] = objs, BpCopier(doc, objs)
        x0, y0, x1, y1 = doc.page_box(i)
        w, h = x1 - x0, y1 - y0
        sc = min(A4_W / w, A4_H / h)
        return run["cp"].form(i, (sc, 0, 0, sc, (A4_W - w * sc) / 2 - x0 * sc, A4_H - h * sc - y0 * sc))
    return n, emit


def bp_model(c, oid, did, model):
    """office.pdfweb _model: puts the letterhead into the print model (model["letterhead"], see office.pdf bp_layout):
    a draft the current one, a finalised document the one frozen with it (none when it was finalised without)."""
    try:
        if model.get("locked"):
            from .docs import _j, doc_row
            snd = _j(doc_row(c, oid, did)["sender"], {}) or {}
            lh = snd.get("letterhead") if isinstance(snd.get("letterhead"), dict) else None
            data = bp_read(c, oid, lh.get("file"), snap=True) if lh else None
        else:
            lh = bp_state(office_settings(c, oid))
            data = bp_read(c, oid, lh["file"]) if lh["file"] else None
    except OSError as e:
        log.warning("letterhead of office %s not readable: %s", oid, e)
        return model
    if not data:
        return model
    em = bp_emitter(data)
    if em:
        model["letterhead"] = {"m1": lh.get("m1") or BP_DEFAULT["m1"], "m2": lh.get("m2") or BP_DEFAULT["m2"],
                               "hide_head": 1 if lh.get("hide_head") else 0, "hide_footer": 1 if lh.get("hide_footer") else 0,
                               "pages": em[0], "emit": em[1]}
    return model


def bp_letter(c, oid):
    """2.184.0 C (#2581): the current letterhead for a letter's PDF (office.letters lt_pdf) in the form of model["letterhead"]
    (see office.pdf bp_layout); None without one or when it cannot be read (the letter is printed with its own head)."""
    try:
        lh = bp_state(office_settings(c, oid))
        data = bp_read(c, oid, lh["file"]) if lh["file"] else None
    except OSError as e:
        log.warning("letterhead of office %s not readable: %s", oid, e)
        return None
    em = bp_emitter(data) if data else None
    if not em:
        return None
    return {"m1": lh.get("m1") or BP_DEFAULT["m1"], "m2": lh.get("m2") or BP_DEFAULT["m2"],
            "hide_head": 1 if lh.get("hide_head") else 0, "hide_footer": 1 if lh.get("hide_footer") else 0,
            "pages": em[0], "emit": em[1]}


# ---------------------------------------------------------------- routes
@app.get("/api/office/letterhead")
def bp_get():
    c, uid, oid = _ctx()
    return jsonify(letterhead=bp_public(bp_state(office_settings(c, oid))))


@app.post("/api/office/letterhead")
def bp_upload():
    """multipart "file" (admin): a PDF up to BP_MAX_MB MB; 400 with a plain sentence when it cannot be used."""
    from .ledger import ofx_log
    c, uid, oid = _ctx(admin=True)
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(BP_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > BP_MAX_MB * 1024 * 1024:
        return err(tr("The file is too large (at most {0} MB)", BP_MAX_MB), 413)
    from ..files.scan import sc_scan  # 2.148.1 E (#2496): virus scan like every upload
    from ..files.upsafe import UploadRefused
    try:
        sc_scan(f.filename or "letterhead.pdf", raw)
    except UploadRefused as e:
        return err(str(e))
    try:
        pages, sizes = bp_check(raw)
    except (BpError, ValueError, IndexError, KeyError, TypeError, RecursionError, MemoryError) as e:  # 2.120.0 review H1: + MemoryError
        log.info("letterhead refused: %s", e)
        return err(tr("This PDF cannot be used as letterhead. Please save it again as a plain PDF (not protected, A4)."))
    if any(abs(w / h - A4_W / A4_H) > 0.03 for w, h in sizes):
        return err(tr("The letterhead must be an A4 page in portrait format."))
    write_lock(c, f"office_letterhead_{int(oid)}")
    sha = hashlib.sha256(raw).hexdigest()
    name = f"letterhead-{sha[:16]}.pdf"
    d = _dir(oid)
    os.makedirs(d, mode=0o700, exist_ok=True)
    p = os.path.join(d, name)
    if not os.path.isfile(p):
        oc_write_file(c, oid, p, raw, fresh=True)  # sealed with the office area's key at rest, like the documents
    lh = bp_state(office_settings(c, oid))
    prev = lh["file"] if lh["file"] != name else lh.get("prev") or ""
    fname = re.sub(r"[\x00-\x1f\x7f/\\]", "", os.path.basename(f.filename or ""))[:120]
    lh.update(file=name, sha256=sha, name=fname, bytes=len(raw), pages=pages, prev=prev)
    _save(c, oid, lh)
    bp_purge(oid, {name, prev})
    ofx_log(c, oid, "upload", target="letterhead", detail={"bytes": len(raw), "pages": pages, "sha256": sha})
    c.commit()
    return jsonify(letterhead=bp_public(lh))


@app.put("/api/office/letterhead")
def bp_put():
    """{m1?, m2?, hide_head?, hide_footer?} (admin): the margins and switches, saved at once (the settings page autosaves)."""
    from .ledger import ofx_log
    c, uid, oid = _ctx(admin=True)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    write_lock(c, f"office_letterhead_{int(oid)}")
    lh = bp_state(office_settings(c, oid))
    before = {k: lh.get(k) for k in ("m1", "m2", "hide_head", "hide_footer")}
    for k in ("m1", "m2"):
        if k in b:
            lh[k] = bp_margins_clean(b[k], k)
    for k in ("hide_head", "hide_footer"):
        if k in b:
            lh[k] = 1 if b[k] in (1, True, "1", "true") else 0
    w1, w2 = 210 - lh["m1"][1] - lh["m1"][3], 210 - lh["m2"][1] - lh["m2"][3]
    if min(w1, w2) < BP_MIN_WIDTH_MM:
        return err(tr("The text needs at least {0} mm between the left and the right margin", BP_MIN_WIDTH_MM))
    after = {k: lh.get(k) for k in before}
    if after != before:
        _save(c, oid, lh)
        ofx_log(c, oid, "update", target="letterhead", detail={"before": before, "after": after})
        c.commit()
    return jsonify(letterhead=bp_public(lh))


@app.delete("/api/office/letterhead")
def bp_delete():
    """Admin: no letterhead in the documents from now on; the file stays as prev for one undo step (restore)."""
    from .ledger import ofx_log
    c, uid, oid = _ctx(admin=True)
    write_lock(c, f"office_letterhead_{int(oid)}")
    lh = bp_state(office_settings(c, oid))
    if lh["file"]:
        lh["prev"], lh["file"] = lh["file"], ""
        lh.update(sha256="", bytes=0, pages=0)
        _save(c, oid, lh)
        bp_purge(oid, {lh["prev"]})
        ofx_log(c, oid, "delete", target="letterhead")
        c.commit()
    return jsonify(letterhead=bp_public(lh))


@app.post("/api/office/letterhead/restore")
def bp_restore():
    """{file} (admin): the previous letterhead file (prev) becomes the current one again -- the undo of an upload or a
    removal; the current one becomes prev in turn (redo). 404 when the file has gone."""
    from .ledger import ofx_log
    c, uid, oid = _ctx(admin=True)
    b = body() or {}
    want = str(b.get("file") or "") if isinstance(b, dict) else ""
    write_lock(c, f"office_letterhead_{int(oid)}")
    lh = bp_state(office_settings(c, oid))
    if want == lh["file"]:
        return jsonify(letterhead=bp_public(lh))
    if not want:  # the undo of an upload onto no letterhead: none again, the uploaded file stays as prev
        lh["prev"], lh["file"] = lh["file"], ""
        lh.update(sha256="", bytes=0, pages=0)
    else:
        if want != lh.get("prev") or not BP_FILE_RE.fullmatch(want):
            raise Denied(404)
        data = bp_read(c, oid, want)
        if not data:
            raise Denied(404)
        pages, _sizes = bp_check(data)
        lh["prev"], lh["file"] = lh["file"], want
        lh.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), pages=pages)
    _save(c, oid, lh)
    ofx_log(c, oid, "update", target="letterhead", detail={"restored": want})
    c.commit()
    return jsonify(letterhead=bp_public(lh))


def bp_sample(c, oid):
    """A sample invoice over two pages in the office area's language with its company data, logo and colour, for the
    preview (nothing stored, no number used)."""
    from .ledger import ofx_company, ofx_company_print, ofx_sender_line
    from .packs import office_pack_for
    s = office_settings(c, oid)
    lang = "en" if s.get("lang") == "en" else "de"
    pack = office_pack_for(s) or {}
    co = ofx_company_print(ofx_company(c, oid), s.get("company") or {}, lang, pack)
    co["sender_line"] = ofx_sender_line(co)
    lp = os.path.join(_dir(oid), os.path.basename(s.get("logo") or ""))
    co["logo_path"] = lp if s.get("logo") and os.path.isfile(lp) else None
    co["color"] = s.get("color") or ""
    lines = [{"kind": "item", "pos": str(i), "title": tr("Sample position {0}", i, lg=lang), "qty": 1, "unit": "",
              "qty_text": "1", "rate": 100, "tax_pct": 19, "total": 100} for i in range(1, 31)]
    return {"kind": "invoice", "lang": lang, "currency": s.get("currency") or "EUR", "number": tr("Sample", lg=lang),
            "date": "2026-01-15", "title": tr("Invoice", lg=lang), "company": co, "formats": pack.get("formats") or {},
            "recipient": {"name": "Muster GmbH", "lines": ["Muster GmbH", "Beispielstr. 1", "12345 Musterstadt"]},
            "lines": lines, "totals": {"net": 3000, "tax_lines": [{"pct": 19, "base": 3000, "amount": 570}], "gross": 3570},
            "draft_mark": tr("Sample", lg=lang)}


@app.get("/api/office/letterhead/preview")
def bp_preview():
    """A sample invoice with the current letterhead as PDF (inline); without one the sample shows the normal layout."""
    from .pdf import office_pdf
    from .pdfweb import _file_response
    c, uid, oid = _ctx()
    m = bp_sample(c, oid)
    lh = bp_state(office_settings(c, oid))
    data = bp_read(c, oid, lh["file"]) if lh["file"] else None
    em = bp_emitter(data) if data else None
    if em:
        m["letterhead"] = {"m1": lh["m1"], "m2": lh["m2"], "hide_head": lh.get("hide_head"), "hide_footer": lh.get("hide_footer"),
                           "pages": em[0], "emit": em[1]}
    return _file_response(office_pdf(m), "letterhead-preview.pdf", "application/pdf", inline=True)
