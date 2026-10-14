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
drafts and other kinds). epdf_doc_files(c, org_id, doc_id) hands the files to the mail dispatch of office.ledger / web."""
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
from .model import office_gate, office_logo_set, office_org, office_settings
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
        if model.get("kind") in ("invoice", "credit", "reminder"):  # 2.38.0: a draft invoice is marked as such
            model["draft_mark"] = tr("Draft", lg=model.get("lang") or "de")
    model.pop("internal", None)  # never printed
    return model


def epdf_format(c, oid, r):
    """The e-invoice format of row r: its own einvoice_format, else the organisation's setting, else zugferd."""
    fmt = (r["einvoice_format"] if "einvoice_format" in r.keys() else "") or office_settings(c, oid).get("einvoice_format") or "zugferd"
    return fmt if fmt in ("zugferd", "xrechnung") else "zugferd"


def _render(c, oid, r, model=None):
    """(pdf bytes, xml bytes or None, format) of document row r from its print model (the snapshot when finalised)."""
    from .ledger import ofx_locked
    model = model or _model(c, oid, r["id"])
    xml, fmt = None, ""
    if r["kind"] in EPDF_KINDS_XML and ofx_locked(r):
        fmt = epdf_format(c, oid, r)
        xml = ein_build(model, fmt)
    when = None
    if ofx_locked(r):
        try:
            when = datetime.datetime.fromisoformat(str(r["locked_at"]).replace("Z", "+00:00")).astimezone()
        except ValueError:
            when = None
    meta = {"when": when, "producer": f"Kalmido {APP_VERSION}", "xml_profile": "EN 16931", "doc_type": "INVOICE"}
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
    ofx_log(c, oid, "xml", doc_id=did, dedupe_min=10)
    c.commit()
    x = _stored_or_missing(c, oid, r, "xml")
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
