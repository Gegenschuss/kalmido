"""2.113.2 (#2253): the office's terms and conditions (AGB) as a PDF per language (de / en), sent along with quotations.

Storage: the office folder like the logo and the stored document PDFs (<data dir>/office/<org_id>/), one file per content
terms-<lang>-<sha16>.pdf (content-addressed, never overwritten: an older state stays readable for quotations that went out
with it and for open approval links), sealed at rest with oc_write_file / read with oc_read_file. Flat below the
organisation folder, so the backup's member rule and the restore (admin/backup.py) cover it unchanged. The current state per
language is office_settings.terms = {"de": {file, sha256, date, name, bytes, uploaded_at}, "en": {...}}, set only by the
routes below (excluded from the general settings PATCH and the master data import, like the logo).

Routes (office_gate + office_org; members read, the office's admin writes; a personal office = its owner is the admin):
GET    /api/office/terms                    {terms: {de: meta | null, en: meta | null}, admin}
POST   /api/office/terms/<lang>             multipart file (PDF only: header %PDF-, at most AGB_MAX_MB) + date (YYYY-MM-DD,
                                            default today) -> the new current state of that language
GET    /api/office/terms/<lang>/file        the current file (?inline=1 shows it in the browser)
DELETE /api/office/terms/<lang>             removes the entry only (the file stays for quotations already sent)
POST   /api/office/terms/<lang>/restore     {sha256, date, name}: puts a state back that is stored in this office (the undo
                                            step of "Remove"); 404 for a file of another office or a changed content
Every change goes into the office log (target "terms").

Freezing: finalising a document (ledger.ofx_finalize) notes the current state of the document's language in
office_docs.terms (JSON {lang, date, sha256, file, name}) BEFORE anything is rendered. A finalised document uses exactly that
state (PDF line, mail attachment, approval link, decision record); a draft uses the current state. A quotation finalised
without a frozen state (older ones) never gets a line or an attachment (no wrong state). Invoices / credit notes / reminders
may attach the terms on request (unticked by default): their frozen state, else the current one (they print no line).
2.434.0 (#3619): a quotation with the line carries the terms as the last pages of its PDF wherever it goes out (download,
preview, mail, approval link, portal; agb_offer_pdf), joined on output -- the stored PDF stays as it was finalised.
Documents made from templates (doctpl.py, kinds contract / confirmation) freeze the state when they are finished
(office_gen_docs.terms) and offer it on their approval link. Only the document's language counts: terms in the other
language only = no line, no attachment. 2.185.0 C (#2520): a document in another app language (nl, fr, es, it) takes the
English terms, the German ones when there are no English ones."""
import datetime
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import urllib.parse

from flask import jsonify, request

from ..core.config import app, OFFICE_DIR
from ..core.i18n import LANGS, N_, tr
from ..core.db import body, bump, db, err, gset, gsetting, iso, local_now, now_utc
from ..core.retention import ret_on, ret_report  # 2.272.0 A (#3026)
from ..core.access import Denied
from ..core.orgcrypt import oc_read_file, oc_write_file
from .model import office_gate, office_org, office_role, office_settings, office_settings_lock, office_settings_save
from .doclang import doc_lg
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions

AGB_LANGS = ("de", "en")
AGB_MAX_MB = 10
AGB_MAIL_MAX_MB = 20  # all attachments of one document mail together
AGB_FILE_RE = re.compile(r"terms-(de|en)-[0-9a-f]{16}\.pdf")
AGB_NAME_MAX = 120
AGB_GEN_KINDS = ("contract", "confirmation")  # documents from templates that carry the terms (framework contract, order confirmation)
# printed in the document's language (like the other print words of office/pdf.py)
AGB_LINE = N_("Our terms and conditions (as of {0}) apply, see attachment.|terms")  # 2.185.0 C (#2520): was a de / en table
AGB_ATTACH = {"de": "AGB-Stand-{0}.pdf", "en": "Terms-{0}.pdf"}
# 2.434.0 (#3619): the quotation PDF + the terms pages behind it, joined by pypdf in a limited child process (like
# docs/split.py): stdin = 8 bytes length + the quotation + the terms, stdout = the joined PDF
AGB_JOIN_WORKER = r"""
import io, resource, struct, sys
for k, v in ((resource.RLIMIT_AS, 1024 << 20), (resource.RLIMIT_CPU, 60), (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_CORE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
import logging, warnings
logging.disable(logging.CRITICAL)
warnings.simplefilter("ignore")
from pypdf import PdfReader, PdfWriter
src = sys.stdin.buffer.read()
n = struct.unpack(">Q", src[:8])[0]
w = PdfWriter()
for part in (src[8:8 + n], src[8 + n:]):
    r = PdfReader(io.BytesIO(part))
    if r.is_encrypted and not r.decrypt(""):
        sys.exit(3)
    for pg in r.pages:
        w.add_page(pg)
b = io.BytesIO()
w.write(b)
if len(b.getvalue()) > 2 * len(src) + (16 << 20):
    sys.exit(4)
sys.stdout.buffer.write(b.getvalue())
"""


# ---------------------------------------------------------------- helpers
def agb_path(oid, name):
    """The path of a stored terms file of office area oid (None for a foreign / malformed name or a missing file)."""
    if not isinstance(name, str) or not AGB_FILE_RE.fullmatch(name):
        return None
    p = os.path.join(OFFICE_DIR, str(int(oid)), name)
    return p if os.path.isfile(p) else None


def agb_lang(lang):
    return "en" if str(lang or "").lower().startswith("en") else "de"


def agb_all(c, oid):
    """{de: meta | None, en: meta | None}: the current states whose file is there."""
    t = office_settings(c, oid).get("terms") or {}
    out = {}
    for lg in AGB_LANGS:
        m = t.get(lg) if isinstance(t, dict) else None
        out[lg] = dict(m) if isinstance(m, dict) and agb_path(oid, m.get("file")) else None
    return out


def agb_cands(lang):
    """2.185.0 C (#2520): the terms languages a document in lang may use, in order: de / en its own; any other app language
    the English ones, else the German ones."""
    s = str(lang or "").lower()
    return AGB_LANGS[::-1] if not s.startswith("en") and s != "de" and s in LANGS else (agb_lang(lang),)


def agb_pick(c, oid, lang):
    """2.185.0 C (#2520): (terms language, current meta | None) for a document in lang (see agb_cands)."""
    a = agb_all(c, oid)
    cands = agb_cands(lang)
    return next(((lg, a[lg]) for lg in cands if a.get(lg)), (cands[0], None))


def agb_current(c, oid, lang):
    return agb_pick(c, oid, lang)[1]


def agb_ref(meta, lang):
    """The short reference noted with a document / a decision: {lang, date, sha256, file, name}."""
    return {"lang": agb_lang(lang), "date": meta.get("date") or "", "sha256": meta.get("sha256") or "",
            "file": meta.get("file") or "", "name": meta.get("name") or ""}


def agb_frozen(v):
    """The frozen state of a row value (office_docs.terms / office_gen_docs.terms) or None."""
    try:
        d = json.loads(v) if isinstance(v, str) and v else None
    except ValueError:
        return None
    return d if isinstance(d, dict) and d.get("file") and d.get("sha256") else None


def agb_doc_terms(c, oid, r):
    """The terms state of document row r (office_docs) when the file is there, else None (see the module text)."""
    from .ledger import ofx_locked
    if ofx_locked(r):
        t = agb_frozen(r["terms"] if "terms" in r.keys() else None)
        if t and t.get("lang") in agb_cands(r["lang"]) and agb_path(oid, t["file"]):
            return t
        if r["kind"] == "offer":
            return None  # a quotation never shows a state it was not finalised with
    lg, cur = agb_pick(c, oid, r["lang"])
    return agb_ref(cur, lg) if cur else None


def agb_freeze(c, oid, r):
    """ledger.ofx_finalize: note the current state of the document's language in office_docs.terms (before rendering)."""
    lg, cur = agb_pick(c, oid, r["lang"])
    c.execute("UPDATE office_docs SET terms=? WHERE id=? AND org_id=?",
              (json.dumps(agb_ref(cur, lg), ensure_ascii=False) if cur else None, r["id"], oid))


def agb_gen_freeze(c, oid, kind, lang):
    """doctpl.dt_final: the JSON to note in office_gen_docs.terms (None for other kinds or without terms)."""
    if kind not in AGB_GEN_KINDS:
        return None
    lg, cur = agb_pick(c, oid, lang)
    return json.dumps(agb_ref(cur, lg), ensure_ascii=False) if cur else None


def agb_gen_terms(c, oid, d):
    """The frozen state of a finished document from a template (dict with "terms") when its file is there."""
    t = agb_frozen((d or {}).get("terms"))
    return t if t and agb_path(oid, t["file"]) else None


def agb_fmt_date(v, lang):
    """2026-10-19 -> 19.10.2026 (de) / 2026-10-19 (en)."""
    try:
        d = datetime.date.fromisoformat(str(v or ""))
    except ValueError:
        return str(v or "")
    return d.strftime("%d.%m.%Y") if agb_lang(lang) == "de" else d.isoformat()


def agb_print_line(c, oid, r, fmt_date=None):
    """docs.odoc_render: the line "our terms apply, see attachment" of a quotation ('' without terms in its language)."""
    if r["kind"] != "offer":
        return ""
    t = agb_doc_terms(c, oid, r)
    if not t:
        return ""
    return tr(AGB_LINE, (fmt_date(t["date"]) if fmt_date else "") or agb_fmt_date(t["date"], r["lang"]), lg=doc_lg(r["lang"]))


def agb_attachment(c, oid, t):
    """(file name, bytes, mime) of terms state t for a mail, or None when the file has gone."""
    p = agb_path(oid, t.get("file"))
    if not p:
        return None
    return (AGB_ATTACH[agb_lang(t.get("lang"))].format(t.get("date") or "undated"), oc_read_file(c, p), "application/pdf")


def agb_join(pdf, terms):
    """The bytes of PDF pdf with the pages of PDF terms behind it; ValueError when pypdf cannot read / join them."""
    p = subprocess.run([sys.executable, "-I", "-c", AGB_JOIN_WORKER], input=struct.pack(">Q", len(pdf)) + pdf + terms,
                       capture_output=True, timeout=90, close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    if p.returncode != 0 or not p.stdout.startswith(b"%PDF-"):
        raise ValueError("unreadable")
    return p.stdout


def agb_offer_pdf(c, oid, r, pdf):
    """2.434.0 (#3619): the PDF of document row r as it goes out (download, preview, mail, approval link, portal): a
    quotation that prints the terms line ("see attachment", agb_print_line: its frozen state, a draft the current one) gets
    the terms pages behind its own; the stored document PDF stays as it is. Other kinds, no terms, or terms that cannot be
    read / joined: pdf unchanged (a log line, never a 500)."""
    if r["kind"] != "offer":
        return pdf
    t = agb_doc_terms(c, oid, r)
    if not t:
        return pdf
    try:
        a = agb_attachment(c, oid, t)
        if not a:
            raise OSError("terms file gone")
        return agb_join(pdf, a[1])
    except (OSError, ValueError, Denied, subprocess.SubprocessError) as e:
        print("office: terms not appended to the quotation", r["id"], type(e).__name__, flush=True)
        return pdf


def agb_mail_files(c, oid, r, b, files):
    """invoices.inv_send: (files + the terms, terms ref | None). b["terms"]: true / false; missing = on for quotations only.
    413 when the mail would get too large. 2.434.0 (#3619): a quotation carries its terms as the last pages of its PDF
    (agb_offer_pdf) -- no second file, the ref still goes into the log; only when the pages cannot be joined (a terms file
    pypdf cannot read) they go along as their own file as before."""
    if r["kind"] == "offer":
        out, joined = list(files), False
        for i, f in enumerate(out):
            if f[2] == "application/pdf":
                j = agb_offer_pdf(c, oid, r, f[1])
                joined = j is not f[1]
                out[i] = (f[0], j, f[2])
                break
        if joined:
            if sum(len(f[1]) for f in out) > AGB_MAIL_MAX_MB * 1024 * 1024:
                raise Denied(413, tr("The attachments are too large for one mail (at most {0} MB)", AGB_MAIL_MAX_MB))
            return out, agb_doc_terms(c, oid, r)
    want = b.get("terms")
    want = r["kind"] == "offer" if want is None else want in (1, True, "1", "true")
    t = agb_doc_terms(c, oid, r) if want else None
    a = agb_attachment(c, oid, t) if t else None
    if not a:
        return files, None
    if sum(len(f[1]) for f in files) + len(a[1]) > AGB_MAIL_MAX_MB * 1024 * 1024:
        raise Denied(413, tr("The attachments are too large for one mail (at most {0} MB)", AGB_MAIL_MAX_MB))
    return list(files) + [a], t


def agb_public(meta):
    return {k: meta.get(k) for k in ("date", "sha256", "name", "bytes", "uploaded_at")} if meta else None


def agb_clean_name(v):
    v = os.path.basename(str(v or "").replace("\\", "/"))
    v = re.sub(r"[\x00-\x1f\x7f\"]+", "", v).strip()
    return (v or "terms.pdf")[:AGB_NAME_MAX]


def agb_disposition(name, inline=False):
    """Content-Disposition with a plain ASCII fallback and the UTF-8 name."""
    ascii_ = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "terms.pdf"
    return f"{'inline' if inline else 'attachment'}; filename=\"{ascii_}\"; filename*=UTF-8''{urllib.parse.quote(name)}"


def agb_file_response(c, oid, t, name, inline=False):
    from .pdfweb import _file_response
    p = agb_path(oid, t.get("file"))
    if not p:
        raise Denied(404)
    resp = _file_response(oc_read_file(c, p), "terms.pdf", "application/pdf", inline=inline)
    resp.headers["Content-Disposition"] = agb_disposition(name, inline)
    if inline:  # 2.113.2 (#2253) review: an uploaded PDF shown on the app's origin runs sandboxed (no scripts, no forms)
        resp.headers["Content-Security-Policy"] = "sandbox"
    return resp


def agb_set(c, oid, lang, meta):
    office_settings_lock(c, oid)  # 2.269.0 B (#3014)
    s = office_settings(c, oid)
    t = dict(s.get("terms") or {})
    old = t.get(lang)
    if isinstance(old, dict) and (not meta or old.get("file") != meta.get("file")):  # 2.143.0 D (#2259): the file's time = when it stopped being current
        p = agb_path(oid, old.get("file"))
        try:
            if p:
                os.utime(p)
        except OSError:
            pass
    if meta:
        t[lang] = meta
    else:
        t.pop(lang, None)
    s["terms"] = t
    office_settings_save(c, oid, s)


AGB_KEEP_DAYS = 30  # a replaced / removed state stays this long (the undo step "restore"), then it goes if nothing names it
AGB_TICK = {"at": 0.0}


def agb_purge(c, oid, now=None, purge=True):
    """2.143.0 D (#2259): deletes the stored terms files of office area oid that are not the current state of their language, are
    named by no row of office_docs / office_gen_docs (the trash included; open approval links reach their file only through
    these rows) and stopped being current at least AGB_KEEP_DAYS ago (file time, see agb_set). Files go after the commit
    (nothing is read). Returns the number of files removed. 2.272.0 A (#3026): purge=False only counts (switch "files")."""
    d = os.path.join(OFFICE_DIR, str(int(oid)))
    try:
        names = [n for n in os.listdir(d) if AGB_FILE_RE.fullmatch(n)]
    except OSError:
        return 0
    if not names:
        return 0
    now = now or datetime.datetime.now(datetime.timezone.utc)
    limit = (now - datetime.timedelta(days=AGB_KEEP_DAYS)).timestamp()
    keep = set()
    t = office_settings(c, oid).get("terms") or {}
    for lg in AGB_LANGS:
        m = t.get(lg) if isinstance(t, dict) else None
        if isinstance(m, dict):
            keep.add(m.get("file"))
            if (m.get("uploaded_at") or "") > iso(now - datetime.timedelta(days=AGB_KEEP_DAYS)):
                keep.update(n for n in names if n.startswith(f"terms-{lg}-"))  # replaced a short while ago: the older ones stay
    for tbl in ("office_docs", "office_gen_docs"):
        for r in c.execute(f"SELECT terms FROM {tbl} WHERE org_id=? AND terms IS NOT NULL AND terms<>''", (oid,)):
            f = agb_frozen(r["terms"])
            if f:
                keep.add(f["file"])
    n = 0
    for name in names:
        if name in keep:
            continue
        p = os.path.join(d, name)
        try:
            if os.path.getmtime(p) <= limit:
                if purge:
                    os.remove(p)
                n += 1
        except OSError:
            continue  # the next round tries again
    return n


def agb_purge_tick(c):
    """Watchdog: agb_purge for every office area (organisations and personal offices), at most every 6 hours."""
    import time
    if time.time() - AGB_TICK["at"] < 6 * 3600:
        return 0
    AGB_TICK["at"] = time.time()
    n = 0
    with system_ctx(c):  # the watchdog walks every office area (organisations and personal offices), no person behind it
        ids = [r["id"] for r in c.execute("SELECT id FROM orgs").fetchall()]
        if not gsetting(c, "agb_grace_at"):
            agb_grace(ids)  # 2.143.0 D (#2259, review): once, before the first round
            gset(c, "agb_grace_at", iso(now_utc()))
            c.commit()
            return 0
        purge = ret_on("files")  # 2.272.0 A (#3026): files nothing names, like orf_tick (off = count only)
        for oid in ids:
            n += agb_purge(c, oid, purge=purge)
        ret_report(c, "files", {"terms_files": n}, purge, run="terms_files")
    c.commit()
    return n


def agb_grace(ids):
    """Files stored before 2.143.0 carry their upload time, not the time they were replaced or removed: once, every terms
    file gets the time of now, so the full AGB_KEEP_DAYS (and the undo step "restore") start for them as well."""
    t = datetime.datetime.now(datetime.timezone.utc).timestamp()
    for oid in ids:
        d = os.path.join(OFFICE_DIR, str(int(oid)))
        try:
            names = [n for n in os.listdir(d) if AGB_FILE_RE.fullmatch(n)]
        except OSError:
            continue
        for name in names:
            try:
                os.utime(os.path.join(d, name), (t, t))
            except OSError:
                pass


def agb_valid_date(v):
    v = (v or "").strip() if isinstance(v, str) else ""
    if not v:
        return local_now().date().isoformat()
    try:
        d = datetime.date.fromisoformat(v)
    except ValueError:
        return None
    return d.isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) and 2000 <= d.year <= 2100 else None


# ---------------------------------------------------------------- approval links (office/signoff.py)
def agb_sig_terms(c, r):
    """The terms of approval link r, or None: a quotation's like its PDF line (frozen when finalised, a quotation sent without
    finalising the current state), a finished document's frozen state."""
    if r["kind"] == "offer" and r["doc_id"]:
        d = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (r["doc_id"], r["org_id"])).fetchone()
        return agb_doc_terms(c, r["org_id"], d) if d is not None else None
    if r["kind"] == "document" and r["gen_doc_id"]:
        d = c.execute("SELECT terms FROM office_gen_docs WHERE id=? AND org_id=?", (r["gen_doc_id"], r["org_id"])).fetchone()
        return agb_gen_terms(c, r["org_id"], {"terms": d["terms"]}) if d is not None else None
    return None


def agb_sig_html(c, r, lg, token, prefix):
    """The download link of the terms on the customer's page ('' without frozen terms)."""
    import html
    t = agb_sig_terms(c, r)
    if not t:
        return ""
    e = html.escape
    return (f'<p><a class="pdf" href="{prefix}{e(token)}/terms" download rel="nofollow">'
            f'{e(tr("Download the terms and conditions (PDF, as of {0})", agb_fmt_date(t["date"], lg), lg=lg))}</a></p>')


def agb_sig_note(c, r, lg):
    """The confirmation page's line naming the terms state ('' without)."""
    import html
    t = agb_sig_terms(c, r)
    return f'<p>{html.escape(tr("Terms and conditions as of {0}", agb_fmt_date(t["date"], lg), lg=lg))}</p>' if t else ""


def agb_sig_proto(c, r):
    """The terms state noted in the decision record: {lang, date, sha256} or None."""
    t = agb_sig_terms(c, r)
    return {k: t[k] for k in ("lang", "date", "sha256")} if t else None


# ---------------------------------------------------------------- routes
from .model import office_ctx as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def _lang(lang):
    if lang not in AGB_LANGS:
        raise Denied(404)
    return lang


def _answer(c, oid, uid, **extra):
    return jsonify(terms={lg: agb_public(m) for lg, m in agb_all(c, oid).items()}, admin=office_role(c, uid, oid) == "admin",
                   max_mb=AGB_MAX_MB, **extra)


@app.get("/api/office/terms")
def agb_get():
    """Members of the office: the current terms per language (metadata)."""
    c, uid, oid = _ctx()
    return _answer(c, oid, uid)


@app.post("/api/office/terms/<lang>")
def agb_upload(lang):
    """The office's admin: multipart "file" (PDF, at most AGB_MAX_MB MB) + "date" (YYYY-MM-DD, default today)."""
    from .ledger import ofx_log
    c, uid, oid = _ctx(admin=True)
    lang = _lang(lang)
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(AGB_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > AGB_MAX_MB * 1024 * 1024:
        return err(tr("The file is too large (at most {0} MB)", AGB_MAX_MB), 413)
    if not raw.startswith(b"%PDF-"):
        return err(tr("Only PDF files"))
    from ..files.scan import SC_RETRY_TEXT, sc_needs_retry, sc_scan  # 2.148.1 E (#2496): virus scan like every upload
    from ..files.upsafe import UploadRefused
    try:
        if sc_needs_retry(sc_scan(f.filename or "terms.pdf", raw), raw):  # 2.360.0 B (#2496): no later scan for this file, so checked now
            return err(tr(SC_RETRY_TEXT), 503)
    except UploadRefused as e:
        return err(str(e))
    day = agb_valid_date(request.form.get("date"))
    if not day:
        return err(tr("Invalid value: {0}", "date"))
    sha = hashlib.sha256(raw).hexdigest()
    name = f"terms-{lang}-{sha[:16]}.pdf"
    d = os.path.join(OFFICE_DIR, str(int(oid)))
    os.makedirs(d, mode=0o700, exist_ok=True)
    if not os.path.isfile(os.path.join(d, name)):  # content-addressed: the same content is stored once, never overwritten
        oc_write_file(c, oid, os.path.join(d, name), raw, fresh=True)
    meta = {"file": name, "sha256": sha, "date": day, "name": agb_clean_name(f.filename), "bytes": len(raw), "uploaded_at": iso(now_utc())}
    agb_set(c, oid, lang, meta)
    ofx_log(c, oid, "upload", target="terms", detail=dict(agb_ref(meta, lang), bytes=len(raw)))
    bump(c)
    c.commit()
    return _answer(c, oid, uid)


@app.get("/api/office/terms/<lang>/file")
def agb_file(lang):
    """Members of the office: the current terms file of the language (?inline=1 to look at it)."""
    c, uid, oid = _ctx()
    m = agb_current(c, oid, _lang(lang))
    if not m:
        raise Denied(404)
    return agb_file_response(c, oid, m, m.get("name") or "terms.pdf", inline=request.args.get("inline") == "1")


@app.delete("/api/office/terms/<lang>")
def agb_delete(lang):
    """The office's admin: removes the current entry (the file stays for documents that went out with it).
    Returns {removed: {sha256, date, name}} for the undo step (restore)."""
    from .ledger import ofx_log
    c, uid, oid = _ctx(admin=True)
    lang = _lang(lang)
    m = agb_current(c, oid, lang)
    if not m:
        raise Denied(404)
    agb_set(c, oid, lang, None)
    ofx_log(c, oid, "delete", target="terms", detail=agb_ref(m, lang))
    bump(c)
    c.commit()
    return _answer(c, oid, uid, removed={"sha256": m["sha256"], "date": m["date"], "name": m.get("name") or ""})


@app.post("/api/office/terms/<lang>/restore")
def agb_restore(lang):
    """The office's admin: {sha256, date, name} puts a stored state of this office back as the current one."""
    from .ledger import ofx_log
    c, uid, oid = _ctx(admin=True)
    lang = _lang(lang)
    b = body()
    if not isinstance(b, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(b.get("sha256") or "")):
        return err(tr("Invalid data"))
    sha = b["sha256"]
    name = f"terms-{lang}-{sha[:16]}.pdf"
    p = agb_path(oid, name)
    if not p:
        raise Denied(404)
    data = oc_read_file(c, p)
    if hashlib.sha256(data).hexdigest() != sha:
        raise Denied(404)
    day = agb_valid_date(b.get("date"))
    if not day:
        return err(tr("Invalid value: {0}", "date"))
    meta = {"file": name, "sha256": sha, "date": day, "name": agb_clean_name(b.get("name")), "bytes": len(data), "uploaded_at": iso(now_utc())}
    agb_set(c, oid, lang, meta)
    ofx_log(c, oid, "restore", target="terms", detail=agb_ref(meta, lang))
    bump(c)
    c.commit()
    return _answer(c, oid, uid)


@app.get("/api/office/docs/<int:did>/terms")
def agb_doc_get(did):
    """Members of the office: the terms state document did would send / prints ({terms: {lang, date, sha256, name} | null,
    default: ticked in the send dialog}); ?file=1 downloads that file."""
    from .docs import doc_row
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    t = agb_doc_terms(c, oid, r)
    if request.args.get("file") == "1":
        if not t:
            raise Denied(404)
        return agb_file_response(c, oid, t, AGB_ATTACH[agb_lang(t["lang"])].format(t["date"] or "undated"))
    # 2.434.0 (#3619): in_pdf = a quotation carries them as the last pages of its PDF (no checkbox in the send dialog)
    return jsonify(terms={k: t[k] for k in ("lang", "date", "sha256", "name")} if t else None, default=r["kind"] == "offer",
                   in_pdf=r["kind"] == "offer")
