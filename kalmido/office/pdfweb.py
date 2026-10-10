"""2.36.1 (#1021, part D): the PDF of a quotation and the company logo of the office module.

GET /api/office/docs/<id>/pdf   the document as a PDF file (office_gate + the organisation one works in; a document of
                                another organisation is 404), Content-Disposition with the document number.
POST / GET / DELETE /api/office/logo   the organisation's logo for the print: PNG / JPEG / WebP up to LOGO_MAX_MB, scaled
                                to at most LOGO_MAX_PX width and stored as PNG below <data dir>/office/<org_id>/logo.png
                                (organisation admin writes, members see it). SVG is not accepted (no renderer in the PDF).
The office folder is part of the backups (admin/backup.py: OFFICE_DIR), next to the attachments."""
import io
import os
import re

from flask import jsonify, request, Response, send_file

from ..core.config import app, OFFICE_DIR
from ..core.i18n import tr
from ..core.db import db, err
from ..core.access import Denied
from .model import office_gate, office_logo_set, office_org, office_settings
from .pdf import office_pdf

LOGO_MAX_MB = 4
LOGO_MAX_PX = 1600
LOGO_FILE = "logo.png"


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


@app.get("/api/office/docs/<int:did>/pdf")
def opdf_doc_pdf(did):
    """The quotation as PDF (members of the organisation). ?inline=1 shows it in the browser instead of downloading."""
    from .docs import odoc_render
    c, uid, oid = _ctx()
    model = odoc_render(c, did, oid)
    co = model.setdefault("company", {})
    if not model.get("locked"):  # 2.36.2: a finalised document prints the logo of its snapshot (set by odoc_render)
        lp = opdf_logo_path(oid)
        co["logo_path"] = lp if (office_settings(c, oid).get("logo") and os.path.isfile(lp)) else None
    model.pop("internal", None)  # never printed
    from .ledger import ofx_log
    ofx_log(c, oid, "pdf", doc_id=did, dedupe_min=10)
    c.commit()
    data = office_pdf(model)
    number = re.sub(r"[^A-Za-z0-9._-]+", "-", str(model.get("number") or "")).strip("-") or f"doc-{did}"
    inline = request.args.get("inline") == "1"
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'{"inline" if inline else "attachment"}; filename="{number}.pdf"'
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


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
    os.makedirs(os.path.dirname(lp), mode=0o755, exist_ok=True)
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
