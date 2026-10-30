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

from flask import g, jsonify, request, Response, send_file

from ..core.config import app, APP_VERSION, OFFICE_DIR
from ..core.i18n import tr
from ..core.db import connect, db, err
from ..core.access import Denied
from .model import office_feature, office_gate, office_logo_set, office_need_feature, office_org, office_settings
from ..core.orgcrypt import oc_read_file, oc_write_file
from .pdf import office_pdf, pdf_lang, pdf_to_8bit  # 2.296.0 D (#3172): + pdf_to_8bit, 2.357.0 D (#3183): + pdf_lang
from .einvoice import ein_build
from .terms import agb_offer_pdf  # 2.434.0 (#3619)

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
        im = pdf_to_8bit(im)  # 2.296.0 D (#3172): 16 bit grey scaled, not clipped to white
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


from .model import office_ctx as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


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


def _stored_or_missing(c, oid, r, ext, commit=True):
    """2.38.0 review: the stored file of r; None for a draft or an older finalised document that never had one (rendered
    from its snapshot). A finalised document whose stored file has gone (sha noted, file missing) answers 409 and logs
    store_missing instead of a silent new rendering that could differ from the original."""
    from .ledger import ofx_locked, ofx_log
    p = _stored(oid, r, ext)
    sha = r[ext + "_sha256"] if (ext + "_sha256") in r.keys() else ""
    if p or not ofx_locked(r) or not sha:
        return p
    ofx_log(c, oid, "store_missing", doc_id=r["id"], detail={"file": ext, "sha256": sha})
    if commit:  # 2.296.0 F (#3177): commit=False inside a larger transaction (office move): the log rides with it
        c.commit()
    raise Denied(409, tr("The stored file of this document is missing"))


def epdf_stored(c, oid, r, ext, commit=True):
    """2.296.0 C (#3177, GoBD): the plain bytes of the stored file of finalised row r (None: none stored, render it; 409 as
    _stored_or_missing when it has gone). A file whose SHA-256 differs from the one noted at storing (pdf_sha256 /
    xml_sha256) is never delivered: 409 + log store_mismatch. Rows stored before the hashes were noted are served as before."""
    from .ledger import ofx_locked
    if not ofx_locked(r):  # 2.296.0 F (#3177): a draft (e.g. a quotation taken back) always renders anew
        return None
    p = _stored_or_missing(c, oid, r, ext, commit)
    if not p:
        return None
    data = oc_read_file(c, p)
    sha = r[ext + "_sha256"] if (ext + "_sha256") in r.keys() else ""
    got = hashlib.sha256(data).hexdigest()
    if sha and got != sha:
        from .ledger import ofx_log
        ofx_log(c, oid, "store_mismatch", doc_id=r["id"], detail={"file": ext, "sha256": sha, "found": got})
        if commit:
            c.commit()
        raise Denied(409, tr("The stored file of this document does not match its checksum and is not delivered. Please tell the administrator."))
    return data


def _model(c, oid, did):
    from .docs import odoc_render
    model = odoc_render(c, did, oid)
    co = model.setdefault("company", {})
    if not model.get("locked"):  # 2.36.2: a finalised document prints the logo of its snapshot (set by odoc_render)
        lp = opdf_logo_path(oid)
        co["logo_path"] = lp if (office_settings(c, oid).get("logo") and os.path.isfile(lp)) else None
    from .docs import doc_row
    # 2.138.2 A (#2393): every kind that is not finalised (2.38.0: the invoice kinds only); 2.144.10 A (#2576): a trial one always
    r = doc_row(c, oid, did)
    epdf_mark(r, model)
    from .letters import lt_doc_sig
    lt_doc_sig(c, oid, r, model)  # 2.357.0 C (#3158): the own signature under quotations / reminders (office setting)
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


def epdf_store(c, oid, did, log_extra=None):
    """Called at the end of ofx_finalize (office.ledger): writes the PDF/A-3 (+ XML for invoice / credit) of the now
    frozen document below the organisation's office folder, notes pdf_sha256 / xml_sha256 in office_docs and logs
    "store". XRechnung without the client's buyer reference raises BadInput (400) -> the finalising is rolled back.
    log_extra: more keys for the log entry (2.357.0 #3221: catch_up of the one-time catch-up)."""
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
        c.__dict__.setdefault("epdf_new", []).append((int(oid), int(did), stem + "." + ext))  # 2.355.0 A (#2847): see epdf_sweep
        shas[ext] = hashlib.sha256(data).hexdigest()
    c.execute("UPDATE office_docs SET pdf_sha256=?, xml_sha256=? WHERE id=? AND org_id=?", (shas.get("pdf", ""), shas.get("xml", ""), did, oid))
    ofx_log(c, oid, "store", doc_id=did, detail={"pdf_sha256": shas.get("pdf", ""), "xml_sha256": shas.get("xml", ""), "format": fmt,
                                                 "pdf_bytes": len(pdf), "xml_bytes": len(xml or b""), **(log_extra or {})})
    return shas


def epdf_sweep(c):
    """2.355.0 A (#2847): the files epdf_store wrote on connection c whose finalising was not committed (rolled back, failed
    commit) are removed -- never a stored file with a number that was not given. Reads the committed state on its own
    connection while c (still holding the document lock) is not yet rolled back; a finalised row keeps its files."""
    new = c.__dict__.pop("epdf_new", None)
    if not new:
        return
    x = None
    try:
        x = connect()
        for oid, did, path in new:
            r = x.execute("SELECT locked_at FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
            if (r is None or not r["locked_at"]) and os.path.isfile(path):
                os.remove(path)
    except Exception as e:  # noqa: BLE001 -- only tidying: a file left behind is never served for a draft (epdf_stored)
        print("office: removing an uncommitted document file failed:", e, flush=True)
    finally:
        if x is not None:
            x.close()


@app.teardown_request
def epdf_sweep_request(_):
    c = g.get("db")
    if c is not None and c.__dict__.get("epdf_new"):
        epdf_sweep(c)


def epdf_xrechnung(xml):
    """2.434.0 (#3616): True when the stored e-invoice XML is an XRechnung (its guideline id names it)."""
    return b"urn:xeinkauf.de:kosit:xrechnung" in (xml or b"")


def epdf_doc_files(c, oid, did, zugferd_xml=False):
    """[(file name, bytes, mime)] of document did for the mail dispatch: the stored PDF (and XML for an invoice / credit
    note); a finalised document without stored files (older) or a draft is rendered on the fly.
    2.434.0 (#3616): the XML only for an XRechnung (there it is the invoice itself, the PDF a reading copy); a ZUGFeRD PDF
    carries its factur-x.xml inside, so mail and DATEV get the PDF alone. zugferd_xml=True keeps the XML (books export)."""
    from .docs import doc_row
    r = doc_row(c, oid, did)
    name = epdf_name(r)
    out = []
    p, x = epdf_stored(c, oid, r, "pdf"), epdf_stored(c, oid, r, "xml")  # 2.296.0 C (#3177): checked against the hashes
    if p is not None:
        out.append((name + ".pdf", p, "application/pdf"))  # 2.42.0 (#828): decrypted
        if x is not None and (zugferd_xml or epdf_xrechnung(x)):
            out.append((name + ".xml", x, "application/xml"))
        return out
    pdf, xml, fmt = _render(c, oid, r)
    out.append((name + ".pdf", pdf, "application/pdf"))
    if xml and (zugferd_xml or fmt == "xrechnung"):
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
    lang = pdf_lang(model.get("lang"))  # 2.357.0 D (#3183): the document's language (was de / en only)
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


def epdf_out(c, oid, r, pdf):
    """2.434.0 (#3619): the PDF of document row r as it leaves Kalmido: a quotation with the terms line gets the terms
    pages behind it (terms.agb_offer_pdf); the stored file stays as it is."""
    return agb_offer_pdf(c, oid, r, pdf)


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
    acc = qac_signoff(c, oid, r) if request.args.get("original") != "1" and not g.get("ofd_original") else None  # 2.238.0 A (#2863)
    if acc:  # 2.99.0 C (#2195): a quotation accepted online opens as accepted (?original=1 the original as sent)
        return _file_response(epdf_out(c, oid, r, qac_pdf(c, oid, r, acc)), epdf_name(r) + "-accepted.pdf", "application/pdf", inline=request.args.get("inline") == "1")
    data = epdf_stored(c, oid, r, "pdf")  # 2.42.0 (#828): the stored PDF/A-3 is sealed at rest, served as the original (2.296.0 C #3177: hash checked)
    if data is None:
        data = _render(c, oid, r)[0]
    return _file_response(epdf_out(c, oid, r, data), epdf_name(r) + ".pdf", "application/pdf", inline=request.args.get("inline") == "1")


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
    x = epdf_stored(c, oid, r, "xml")  # 2.296.0 C (#3177): hash checked
    if x is None:  # 2.147.0 (#2460): a stored XML stays reachable (it is part of the document); a new one only while e-invoices are on
        office_need_feature(c, oid, "docs.einvoice")
    ofx_log(c, oid, "xml", doc_id=did, dedupe_min=10)
    c.commit()
    data = x if x is not None else _render(c, oid, r)[1]  # 2.42.0 (#828)
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
