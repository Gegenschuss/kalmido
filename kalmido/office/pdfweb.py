"""2.36.1 (#1021, part D): the PDF of a quotation and the company logo of the office module.

GET /api/office/docs/<id>/pdf   the document as a PDF file (office_gate + the organisation one works in; a document of
                                another organisation is 404), Content-Disposition with the document number.
POST / GET / DELETE /api/office/logo   the organisation's logo for the print: PNG / JPEG / WebP up to LOGO_MAX_MB, scaled
                                to at most LOGO_MAX_PX width and stored as PNG below <data dir>/office/<org_id>/logo.png
                                (organisation admin writes, members see it). SVG is not accepted (no renderer in the PDF).
The office folder is part of the backups (admin/backup.py: OFFICE_DIR), next to the attachments.

2.38.0 (#1021 P5): finalising stores the document's files -- epdf_store(c, org_id, doc_id) writes the PDF/A-3 (and, for an
invoice / credit note, the e-invoice XML; ZUGFeRD = embedded in the PDF as well, XRechnung = separate only) as
<data dir>/office/<org_id>/doc<id>-<kind>-<number>.pdf / .xml (flat below the organisation folder so the backup's member
rule and restore cover them unchanged), notes both SHA-256 in office_docs and logs "store". GET .../pdf serves the
stored file of a finalised document (a draft is rendered with a "Draft" mark), GET .../xml the stored XML (409 for
drafts and other kinds). epdf_doc_files(c, org_id, doc_id) hands the files to the mail dispatch of office.ledger / web.

2.99.0 C (#2195): a quotation accepted online (office/signoff.py) gets its accepted version as its own file
doc<id>-<number>.accepted-<signoff id>.pdf (qac_pdf: the signature box instead of the empty lines); the customer's
download and GET .../pdf of the app serve it (?original=1 the original), the original file is never changed."""
import datetime
import hashlib
import io
import os
import re

from flask import jsonify, request, Response, send_file

from ..core.config import app, APP_VERSION, OFFICE_DIR
from ..core.i18n import tr
from ..core.db import db, err
from ..core.access import Denied
from .model import office_feature, office_gate, office_logo_set, office_need_feature, office_org, office_settings
from ..core.orgcrypt import oc_read_file, oc_write_file
from .pdf import office_pdf
from .einvoice import ein_build

LOGO_MAX_MB = 4
LOGO_MAX_PX = 1600
LOGO_FILE = "logo.png"


def rx_office_perms(base=None):
    """2.39.1 (#1210 N8): at start-up the office folder and its organisation folders (made 0755 before 2.39.0) become
    0700. Only folders this process owns, no symlinks; errors are ignored (read-only mounts, foreign owners)."""
    base = base or OFFICE_DIR
    try:
        names = [""] + [n for n in os.listdir(base) if re.fullmatch(r"\d{1,12}", n)]
    except OSError:
        return
    for n in names:
        p = os.path.join(base, n) if n else base
        try:
            st = os.lstat(p)
            if os.path.isdir(p) and not os.path.islink(p) and st.st_uid == os.getuid() and st.st_mode & 0o077:
                os.chmod(p, 0o700)
        except OSError:
            pass


def opdf_logo_path(oid):
    return os.path.join(OFFICE_DIR, str(int(oid)), LOGO_FILE)


def opdf_logo_process(raw):
    """Upload bytes -> PNG bytes (at most LOGO_MAX_PX wide, transparency kept, no metadata); ValueError with a message."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ValueError(tr("Photos are not available on this server"))
    Image.MAX_IMAGE_PIXELS = 30_000_000
    try:
        try:
            im = Image.open(io.BytesIO(raw))
        except Exception:  # noqa: BLE001  (SVG, PDF, text: not a raster picture Pillow knows)
            raise ValueError(tr("Please choose a PNG, JPEG or WebP picture (PNG at least 600 px wide prints sharply)")) from None
        if im.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError(tr("Please choose a PNG, JPEG or WebP picture (PNG at least 600 px wide prints sharply)"))
        if im.width * im.height > 30_000_000:
            raise ValueError(tr("This picture cannot be read"))
        im.load()
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P", "PA") else im.convert("RGB")
        if im.width > LOGO_MAX_PX:
            im = im.resize((LOGO_MAX_PX, max(1, round(im.height * LOGO_MAX_PX / im.width))), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)
        return out.getvalue(), im.width, im.height
    except ValueError:
        raise
    except Exception:  # noqa: BLE001  (truncated, bomb, unknown)
        raise ValueError(tr("This picture cannot be read")) from None


def _ctx(admin=False):
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=admin)


# ---------------------------------------------------------------- 2.38.0 (#1021 P5): the stored files of a finalised document
EPDF_KINDS_XML = ("invoice", "credit")


def epdf_name(r):
    """The file name stem of document row r: <number> for a quotation, <kind>-<number> for the invoice kinds."""
    number = re.sub(r"[^A-Za-z0-9._-]+", "-", str(r["number"] or "")).strip("-") or f"doc-{r['id']}"
    return number if r["kind"] == "offer" else f"{r['kind']}-{number}"


def _stored(oid, r, ext):
    """Path of the stored file of row r (None when there is none)."""
    p = os.path.join(OFFICE_DIR, str(int(oid)), f"doc{int(r['id'])}-{epdf_name(r)}.{ext}")
    return p if os.path.isfile(p) else None


def _stored_or_missing(c, oid, r, ext):
    """2.38.0 review: the stored file of r; None for a draft or an older finalised document that never had one (rendered
    from its snapshot). A finalised document whose stored file has gone (sha noted, file missing) answers 409 and logs
    store_missing instead of a silent new rendering that could differ from the original."""
    from .ledger import ofx_locked, ofx_log
    p = _stored(oid, r, ext)
    sha = r[ext + "_sha256"] if (ext + "_sha256") in r.keys() else ""
    if p or not ofx_locked(r) or not sha:
        return p
    ofx_log(c, oid, "store_missing", doc_id=r["id"], detail={"file": ext, "sha256": sha})
    c.commit()
    raise Denied(409, tr("The stored file of this document is missing"))


def _model(c, oid, did):
    from .docs import odoc_render
    model = odoc_render(c, did, oid)
    co = model.setdefault("company", {})
    if not model.get("locked"):  # 2.36.2: a finalised document prints the logo of its snapshot (set by odoc_render)
        lp = opdf_logo_path(oid)
        co["logo_path"] = lp if (office_settings(c, oid).get("logo") and os.path.isfile(lp)) else None
    from .docs import doc_row
    # 2.138.2 A (#2393): every kind that is not finalised (2.38.0: the invoice kinds only); 2.144.10 A (#2576): a trial one always
    epdf_mark(doc_row(c, oid, did), model)
    model.pop("internal", None)  # never printed
    from .letterhead import bp_model
    return bp_model(c, oid, did, model)  # 2.120.0 E (#2091): the own letterhead (a finalised document: the one frozen with it)


def epdf_is_draft(r):
    """2.138.2 A (#2393): document row r prints as a draft: not finalised and still in status draft (a quotation set to
    sent / accepted / declined without finalising is locked the same way since 2.39.0 and its customer link serves it)."""
    from .ledger import ofx_locked
    return not ofx_locked(r) and (r["status"] or "draft") == "draft"


def epdf_mark(r, model):
    """2.144.10 A (#2576): the one mark of document row r's print model: SAMPLE / MUSTER for a trial document (finalised or
    not; it wins over DRAFT), DRAFT / ENTWURF for a draft (epdf_is_draft), none otherwise. Idempotent."""
    if r["trial"]:
        return epdf_draft(model, tr("SAMPLE", lg=model.get("lang") or "de"))
    if epdf_is_draft(r):
        return epdf_draft(model)
    return model


def epdf_draft(model, word=None):
    """2.138.2 A (#2393): marks the print model of a document that is not finalised: DRAFT / ENTWURF (the document's
    language) in bold at the number of the key data and as the light diagonal mark on every page (pdf.py). Coupled to
    "not finalised" in _render, so no PDF of a draft (button, preview, download, mail, agents) goes out unmarked."""
    word = word or tr("Draft", lg=model.get("lang") or "de").upper()
    model["draft_mark"] = word
    meta = model.get("meta")
    if isinstance(meta, list) and meta and isinstance(meta[0], (list, tuple)) and len(meta[0]) >= 2:
        num = str(meta[0][1] or "").strip()
        if num.upper() != word and not num.endswith(" · " + word):
            num = "" if num in ("Entwurf", "Draft") else num  # invoices.py prints "Entwurf" / "Draft" without a number
            meta[0] = [meta[0][0], f"{num} · {word}" if num else word]
    return model


def epdf_format(c, oid, r):
    """The e-invoice format of row r: its own einvoice_format, else the organisation's setting, else zugferd."""
    s = office_settings(c, oid)
    fmt = (r["einvoice_format"] if "einvoice_format" in r.keys() else "") or s.get("einvoice_format") or "zugferd"
    from .packs import office_pack_for
    offered = [f for f in (((office_pack_for(s) or {}).get("einvoice") or {}).get("formats") or ["zugferd"]) if f in ("zugferd", "xrechnung")]
    return fmt if fmt in offered else (offered[0] if offered else "zugferd")  # 2.147.0 (#2461): only what the country pack offers


def _render(c, oid, r, model=None):
    """(pdf bytes, xml bytes or None, format) of document row r from its print model (the snapshot when finalised)."""
    from .ledger import ofx_locked
    model = model or _model(c, oid, r["id"])
    epdf_mark(r, model)  # 2.138.2 A (#2393): never an unmarked draft, whichever model came in; 2.144.10 A (#2576): nor trial
    xml, fmt = None, ""
    if r["kind"] in EPDF_KINDS_XML and ofx_locked(r) and not r["trial"] and office_feature(c, oid, "docs.einvoice"):  # 2.147.0 (#2459, #2460); 2.144.10 A (#2576): no e-invoice for a trial one
        fmt = epdf_format(c, oid, r)
        xml = ein_build(model, fmt)
    when = None
    if ofx_locked(r):
        try:
            when = datetime.datetime.fromisoformat(str(r["locked_at"]).replace("Z", "+00:00")).astimezone()
        except ValueError:
            when = None
    meta = {"when": when, "producer": f"Kalmido v{APP_VERSION}", "xml_profile": "EN 16931", "doc_type": "INVOICE"}
    pdf = office_pdf(model, xml=xml if fmt == "zugferd" else None, meta=meta)
    return pdf, xml, fmt


def epdf_store(c, oid, did):
    """Called at the end of ofx_finalize (office.ledger): writes the PDF/A-3 (+ XML for invoice / credit) of the now
    frozen document below the organisation's office folder, notes pdf_sha256 / xml_sha256 in office_docs and logs
    "store". XRechnung without the client's buyer reference raises BadInput (400) -> the finalising is rolled back."""
    from .docs import doc_row
    from .ledger import ofx_log
    r = doc_row(c, oid, did)
    pdf, xml, fmt = _render(c, oid, r)
    d = os.path.join(OFFICE_DIR, str(int(oid)))
    os.makedirs(d, mode=0o700, exist_ok=True)  # 2.39.0 (#1209 audit N8)
    stem = os.path.join(d, f"doc{int(did)}-{epdf_name(r)}")
    shas = {}
    for ext, data in (("pdf", pdf), ("xml", xml)):
        if data is None:
            continue
        oc_write_file(c, oid, stem + "." + ext, data)  # 2.42.0 (#828): sealed with the organisation's key at rest (tmp + replace)
        shas[ext] = hashlib.sha256(data).hexdigest()
    c.execute("UPDATE office_docs SET pdf_sha256=?, xml_sha256=? WHERE id=? AND org_id=?", (shas.get("pdf", ""), shas.get("xml", ""), did, oid))
    ofx_log(c, oid, "store", doc_id=did, detail={"pdf_sha256": shas.get("pdf", ""), "xml_sha256": shas.get("xml", ""), "format": fmt,
                                                 "pdf_bytes": len(pdf), "xml_bytes": len(xml or b"")})
    return shas


def epdf_doc_files(c, oid, did):
    """[(file name, bytes, mime)] of document did for the mail dispatch: the stored PDF (and XML for an invoice / credit
    note); a finalised document without stored files (older) or a draft is rendered on the fly."""
    from .docs import doc_row
    r = doc_row(c, oid, did)
    name = epdf_name(r)
    out = []
    p, x = _stored_or_missing(c, oid, r, "pdf"), _stored_or_missing(c, oid, r, "xml")
    if p:
        out.append((name + ".pdf", oc_read_file(c, p), "application/pdf"))  # 2.42.0 (#828): decrypted
        if x:
            out.append((name + ".xml", oc_read_file(c, x), "application/xml"))
        return out
    pdf, xml, _fmt = _render(c, oid, r)
    out.append((name + ".pdf", pdf, "application/pdf"))
    if xml:
        out.append((name + ".xml", xml, "application/xml"))
    return out


def qac_signoff(c, oid, r):
    """2.99.0 C (#2195): the newest online acceptance of quotation row r that still covers its content (the signoff row,
    signer data decrypted) or None: open / declined links, other kinds and a quotation changed since stay the original."""
    from .signoff import sig_dec, sig_doc_hash
    if r["kind"] != "offer":
        return None
    s = c.execute("SELECT * FROM office_signoffs WHERE org_id=? AND doc_id=? AND kind='offer' AND state='accepted' ORDER BY id DESC LIMIT 1",
                  (oid, r["id"])).fetchone()
    if not s or sig_doc_hash(c, oid, r["id"])[0] != s["doc_hash"]:
        return None
    return sig_dec(c, s)


def qac_path(oid, r, sid):
    """The accepted version of quotation row r (signoff sid): its own file next to the original, which stays as it is."""
    return os.path.join(OFFICE_DIR, str(int(oid)), f"doc{int(r['id'])}-{epdf_name(r)}.accepted-{int(sid)}.pdf")


def qac_pdf(c, oid, r, s):
    """2.99.0 C (#2195): the PDF of quotation row r as accepted through signoff s (decrypted row): the stored file, else
    rendered from the print model (the snapshot when finalised) with the box "accepted online by <name> at <time UTC>,
    SHA-256 of the quotation <doc_hash>" instead of the empty signature lines and stored sealed next to the original
    (written by the acceptance, sig_decide; a failed write leaves it to the next read). The hash is the one of the
    accepted content, as in the protocol."""
    p = qac_path(oid, r, s["id"])
    if os.path.isfile(p):
        return oc_read_file(c, p)
    model = _model(c, oid, r["id"])
    lang = "en" if model.get("lang") == "en" else "de"
    model["accepted"] = {"head": tr("Simple electronic signature", lg=lang),
                         "rows": [[tr("Accepted online by", lg=lang), s["signer_name"] or ""],
                                  [tr("Time (UTC)", lg=lang), (s["signed_at"] or "")[:19].replace("T", " ")],
                                  [tr("SHA-256 of the quotation", lg=lang), s["doc_hash"] or ""]],
                         "foot": tr("Accepted through a customer link of {0}.", (model.get("company") or {}).get("name") or "", lg=lang)}
    data = _render(c, oid, r, model)[0]
    try:
        os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
        oc_write_file(c, oid, p, data)  # sealed with the organisation's key at rest, like the original (epdf_store)
    except Exception as e:  # noqa: BLE001 -- the customer still gets the PDF; the next read tries again
        print("qac_pdf store failed", r["id"], type(e).__name__, flush=True)
    return data


def _file_response(data, name, mime, inline=False):
    resp = Response(data, mimetype=mime)
    resp.headers["Content-Disposition"] = f'{"inline" if inline else "attachment"}; filename="{name}"'
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.get("/api/office/docs/<int:did>/pdf")
def opdf_doc_pdf(did):
    """The document as PDF (members of the organisation). ?inline=1 shows it in the browser instead of downloading.
    2.38.0: a finalised document answers with its stored file (bytes identical for ever); a draft is rendered."""
    from .docs import doc_row
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    ofx_log(c, oid, "pdf", doc_id=did, dedupe_min=10)
    c.commit()
    acc = qac_signoff(c, oid, r) if request.args.get("original") != "1" else None
    if acc:  # 2.99.0 C (#2195): a quotation accepted online opens as accepted (?original=1 the original as sent)
        return _file_response(qac_pdf(c, oid, r, acc), epdf_name(r) + "-accepted.pdf", "application/pdf", inline=request.args.get("inline") == "1")
    p = _stored_or_missing(c, oid, r, "pdf")
    if p:
        data = oc_read_file(c, p)  # 2.42.0 (#828): the stored PDF/A-3 is sealed at rest, served as the original
    else:
        data = _render(c, oid, r)[0]
    return _file_response(data, epdf_name(r) + ".pdf", "application/pdf", inline=request.args.get("inline") == "1")


@app.get("/api/office/docs/<int:did>/xml")
def opdf_doc_xml(did):
    """The e-invoice XML of a finalised invoice / credit note (members of the organisation); 409 for drafts and other
    kinds. The stored file; an older finalised document without one is built from its snapshot."""
    from .docs import doc_row
    from .ledger import ofx_locked, ofx_log
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    if r["kind"] not in EPDF_KINDS_XML or not ofx_locked(r):
        raise Denied(409, tr("The e-invoice XML exists for finalised invoices and credit notes only."))
    if r["trial"]:  # 2.144.10 A (#2576)
        raise Denied(409, tr("A trial document has no e-invoice"))
    x = _stored_or_missing(c, oid, r, "xml")
    if not x:  # 2.147.0 (#2460): a stored XML stays reachable (it is part of the document); a new one only while e-invoices are on
        office_need_feature(c, oid, "docs.einvoice")
    ofx_log(c, oid, "xml", doc_id=did, dedupe_min=10)
    c.commit()
    if x:
        data = oc_read_file(c, x)  # 2.42.0 (#828)
    else:
        data = _render(c, oid, r)[1]
    return _file_response(data, epdf_name(r) + ".xml", "application/xml")


@app.get("/api/office/logo")
def opdf_logo_get():
    """The organisation's logo (PNG) for the settings preview; 404 without one."""
    c, uid, oid = _ctx()
    lp = opdf_logo_path(oid)
    if not office_settings(c, oid).get("logo") or not os.path.isfile(lp):
        raise Denied(404)
    resp = send_file(lp, mimetype="image/png", conditional=True, max_age=0)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/office/logo")
def opdf_logo_upload():
    """multipart "file" (organisation admin): PNG / JPEG / WebP up to LOGO_MAX_MB MB -> stored as PNG."""
    c, uid, oid = _ctx(admin=True)
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(LOGO_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > LOGO_MAX_MB * 1024 * 1024:
        return err(tr("The picture is too large (at most {0} MB)", LOGO_MAX_MB), 413)
    try:
        png, w, h = opdf_logo_process(raw)
    except ValueError as e:
        return err(str(e))
    lp = opdf_logo_path(oid)
    os.makedirs(os.path.dirname(lp), mode=0o700, exist_ok=True)  # 2.39.0 (#1209 audit N8)
    with open(lp + ".tmp", "wb") as fh:
        fh.write(png)
    os.replace(lp + ".tmp", lp)
    office_logo_set(c, oid, LOGO_FILE)
    from .ledger import ofx_log
    ofx_log(c, oid, "upload", target="logo", detail={"bytes": len(png), "width": w, "height": h})
    c.commit()
    return jsonify(logo=LOGO_FILE, width=w, height=h, bytes=len(png))


@app.delete("/api/office/logo")
def opdf_logo_delete():
    c, uid, oid = _ctx(admin=True)
    lp = opdf_logo_path(oid)
    try:
        os.remove(lp)
    except OSError:
        pass
    office_logo_set(c, oid, "")
    from .ledger import ofx_log
    ofx_log(c, oid, "delete", target="logo")
    c.commit()
    return jsonify(logo="")
