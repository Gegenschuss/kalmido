"""2.98.0 B (#1954): questionnaires -- the forms (team/forms.py) get own questions (short / long text, choice, date,
number, file, yes / no); a submission becomes a task at the customer. Built by part B.

A form with questions (forms.questions, a JSON list; '[]' = the classic form with subject / description, unchanged) shows
them instead of subject and description: all on one page (no script needed) or one question per step (forms.one_per_step;
the steps are sections switched by links and the CSS :target -- still no script, the public pages' CSP allows none).
Required answers, number / date / choice values, the file types and sizes are checked on the server; a refused send shows
the page again with the typed answers (files must be chosen again) and opens the step of the first problem. A sent
questionnaire becomes a task in the form's list as before (title = form title + sender), the answers as Markdown in its
description (a heading per question, a choice as a list), files as attachments of the task (sealed, scanned and counted
like every attachment, core/pages.py save_attachment_bytes). forms.client_match: the sender's e-mail is matched to the ONE
client of the list's space with that address (organisation of the list, or the list owner's private clients; never
another space), forms.client_new (default off): an unknown address becomes a new client there, else the task notes
"client unknown". form_entries keeps the answers by question id for the evaluation (the list of submissions and a CSV in
the form dialog, for the people who manage the form)."""
import csv
import hashlib
import hmac
import io
import json
import re
import secrets

from flask import Response, jsonify, request

from ..core.config import app
from ..core.db import db, iso, now_utc
from ..core.i18n import N_, lang, tr, dec_comma
from ..personal.timetrack import _csv_cell
from ..core.errors import BadInput
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions
from ..core.access import Denied  # 2.149.0 G (#2517): pulled up from functions

FQ_KINDS = ("short", "long", "choice", "multi", "date", "number", "file", "yesno")
FQ_MAX, FQ_LABEL_MAX, FQ_HELP_MAX = 30, 300, 500
FQ_OPTS_MAX, FQ_OPT_MAX = 20, 120
FQ_SHORT_MAX, FQ_LONG_MAX = 500, 8000
FQ_FILES_MAX = 3  # file questions per form (each takes one file of at most FRM_FILE_MAX)
FQ_ID_RE = re.compile(r"[a-z0-9]{6,16}")
# the file types a questionnaire takes: pictures, PDF, office formats, text (never scripts, pages or programs; no SVG)
FQ_EXT = frozenset(("png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
                    "odt", "ods", "odp", "rtf", "txt", "csv", "md"))
FQ_NEW_CLIENTS_DAY = 20  # new clients one form may make per day (client_new on)
FQ_ENTRIES_MAX = 2000    # rows of the evaluation / CSV
FQ_YES, FQ_NO = N_("Yes"), N_("No")


def fq_list(r):
    """The questions of form row r ([] = a classic form)."""
    try:
        v = json.loads((r["questions"] if "questions" in r.keys() else "") or "[]")
    except (ValueError, TypeError):
        return []
    return v if isinstance(v, list) else []


def fq_clean(raw):
    """Checks a list of questions from the dialog / the API; returns the JSON to store. Keeps a known id (the answers of
    earlier submissions stay mapped after a rename or a new order), gives new questions a random one."""
    if not isinstance(raw, list) or len(raw) > FQ_MAX:
        raise BadInput(tr("At most {0} questions per form", FQ_MAX))
    out, seen, files = [], set(), 0
    for q in raw:
        if not isinstance(q, dict):
            raise BadInput(tr("Invalid value: {0}", "questions"))
        kind = q.get("kind")
        if kind not in FQ_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        label = re.sub(r"\s+", " ", str(q.get("label") or "")).strip()[:FQ_LABEL_MAX]
        if not label:
            raise BadInput(tr("Every question needs a text"))
        hlp = q.get("help") or ""
        req = q.get("required", False)
        if not isinstance(hlp, str) or not isinstance(req, bool):
            raise BadInput(tr("Invalid value: {0}", "questions"))
        qid = q.get("id")
        if not isinstance(qid, str) or not FQ_ID_RE.fullmatch(qid) or qid in seen:
            qid = secrets.token_hex(4)
        seen.add(qid)
        item = {"id": qid, "kind": kind, "label": label, "help": hlp.strip()[:FQ_HELP_MAX], "required": req}
        if kind in ("choice", "multi"):
            opts = q.get("options")
            if not isinstance(opts, list):
                raise BadInput(tr("Invalid value: {0}", "options"))
            clean = []
            for o in opts[:FQ_OPTS_MAX]:
                o = re.sub(r"\s+", " ", str(o if isinstance(o, (str, int, float)) else "")).strip()[:FQ_OPT_MAX]
                if o and o not in clean:
                    clean.append(o)
            if len(clean) < 2:
                raise BadInput(tr("A choice needs at least two options"))
            item["options"] = clean
        if kind == "file":
            files += 1
            if files > FQ_FILES_MAX:
                raise BadInput(tr("At most {0} file questions per form", FQ_FILES_MAX))
        out.append(item)
    return json.dumps(out, ensure_ascii=False)


def fq_clean_form(b, out):
    """clean_form's part for the questionnaire fields (adds to out)."""
    if "questions" in b:
        out["questions"] = fq_clean(b["questions"])
    for k in ("one_per_step", "client_match", "client_new"):
        if k in b:
            if not isinstance(b[k], bool):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = 1 if b[k] else 0


def fq_public(r):
    return {"questions": fq_list(r), "one_per_step": bool(r["one_per_step"]), "client_match": bool(r["client_match"]),
            "client_new": bool(r["client_new"])}


def fq_file_count(qs):
    return sum(1 for q in qs if q["kind"] == "file")


# ---- the page
def _req(q, lg):
    return f' <span class="fqreq" aria-hidden="true">*</span><span class="vh">{tr("required", lg=lg)}</span>' if q["required"] else ""


def fq_question_html(q, lg, vals, step):
    """One question's field. vals = {qid: [typed values]}; step = no required attributes (hidden steps would block)."""
    import html
    e = html.escape
    qid, kind = q["id"], q["kind"]
    name, fid = f"q_{qid}", f"fq-{qid}"
    have = vals.get(qid) or []
    req = " required" if q["required"] and not step and kind != "multi" else ""
    hid = f"fqh-{qid}"
    hlp = f'<p class="fqh" id="{hid}">{e(q["help"])}</p>' if q["help"] else ""
    desc = f' aria-describedby="{hid}"' if q["help"] else ""
    if kind in ("choice", "multi", "yesno"):
        opts = [("yes", tr(FQ_YES, lg=lg)), ("no", tr(FQ_NO, lg=lg))] if kind == "yesno" else [(o, o) for o in q["options"]]
        typ = "checkbox" if kind == "multi" else "radio"
        items = "".join(f'<label class="fqo"><input type="{typ}" name="{name}" value="{e(v)}"{" checked" if v in have else ""}'
                        f'{req if typ == "radio" else ""}> <span>{e(t)}</span></label>' for v, t in opts)
        return f'<fieldset class="fq"{desc}><legend>{e(q["label"])}{_req(q, lg)}</legend>{hlp}{items}</fieldset>'
    v = e(have[0]) if have else ""
    if kind == "long":
        field = f'<textarea id="{fid}" name="{name}" rows="5" maxlength="{FQ_LONG_MAX}"{req}{desc}>{v}</textarea>'
    elif kind == "date":
        field = f'<input id="{fid}" name="{name}" type="date" value="{v}"{req}{desc}>'
    elif kind == "number":
        field = f'<input id="{fid}" name="{name}" inputmode="decimal" maxlength="40" value="{v}"{req}{desc}>'
    elif kind == "file":
        from .forms import FRM_FILE_MAX
        acc = ",".join("." + x for x in sorted(FQ_EXT))
        field = (f'<input id="{fid}" name="{name}" type="file" accept="{acc}"{req}{desc}>'
                 f'<p class="fqh">{e(tr("Pictures, PDF, office files or text, at most {0} MB", FRM_FILE_MAX // (1024 * 1024), lg=lg))}</p>')
    else:
        field = f'<input id="{fid}" name="{name}" maxlength="{FQ_SHORT_MAX}" value="{v}"{req}{desc}>'
    return f'<div class="fq"><label for="{fid}">{e(q["label"])}{_req(q, lg)}</label>{hlp}{field}</div>'


def fq_fields(qs, lg, vals, step, tail, cur=None):
    """The questions of the page. step: one section per question plus a last one with tail (name, e-mail, send) and links
    Back / Next between them; cur = the question id of a refused answer (its step opens). Else all questions, then tail."""
    import html
    e = html.escape
    if not step:
        return "".join(fq_question_html(q, lg, vals, False) for q in qs) + tail
    n = len(qs) + 1
    at = next((i for i, q in enumerate(qs) if q["id"] == cur), 0 if cur is None else n - 1)
    out = []
    for i in range(n):
        body = fq_question_html(qs[i], lg, vals, True) if i < len(qs) else tail
        nav = (f'<a class="btn sec" href="#fqs-{i}">{e(tr("Back", lg=lg))}</a>' if i else "") \
            + (f'<a class="btn" href="#fqs-{i + 2}">{e(tr("Next", lg=lg))}</a>' if i < n - 1 else "")
        out.append(f'<section class="fqs{" cur" if i == at else ""}" id="fqs-{i + 1}" aria-label="{e(tr("Step {0} of {1}", i + 1, n, lg=lg))}">'
                   f'<p class="fqp">{e(tr("Step {0} of {1}", i + 1, n, lg=lg))}</p><progress class="fqbar" max="{n}" value="{i + 1}"></progress>'
                   f'{body}<nav class="fqnav">{nav}</nav></section>')
    return "".join(out)


def fq_vals(form):
    """The typed answers of a refused send (to show them again)."""
    return {k[2:]: [v.strip() for v in form.getlist(k)] for k in form.keys() if k.startswith("q_")}


# ---- reading a send
class FqRefused(Exception):
    def __init__(self, msg, qid=None):
        super().__init__(msg)
        self.qid = qid


def fq_read(qs, form, files, lg, anon, form_id):
    """The answers of a send: ({qid: value | [values] | file name}, [(name, mime, data)]); raises FqRefused (message, the
    question) for a missing required answer, a wrong value, a file too large / of a wrong type."""
    from .forms import FRM_FILE_MAX, h6d_form_bytes
    from ..tasks.attachments import safe_name, unexec_name
    ans, ups = {}, []
    for q in qs:
        qid, kind, key = q["id"], q["kind"], "q_" + q["id"]
        label = q["label"]
        if kind == "file":
            fs = files.get(key)
            data = fs.read(FRM_FILE_MAX + 1) if fs and fs.filename else b""
            if len(data) > FRM_FILE_MAX:
                raise FqRefused(tr("The file is too large (at most {0} MB).", FRM_FILE_MAX // (1024 * 1024), lg=lg), qid)
            if data:
                nm = safe_name(fs.filename)
                if nm.rsplit(".", 1)[-1].lower() not in FQ_EXT or "." not in nm:
                    raise FqRefused(tr("“{0}”: this file type is not accepted (pictures, PDF, office files or text).", label, lg=lg), qid)
                if anon and h6d_form_bytes(form_id, len(data)):
                    raise FqRefused(tr("This form takes no more files right now. Please try again later or send your report without a file.", lg=lg), qid)
                ups.append((unexec_name(nm), "", data))
                ans[qid] = ups[-1][0]
            elif q["required"]:
                raise FqRefused(tr("Please answer “{0}”.", label, lg=lg), qid)
            continue
        vs = [v.strip() for v in form.getlist(key) if v.strip()]
        if not vs:
            if q["required"]:
                raise FqRefused(tr("Please answer “{0}”.", label, lg=lg), qid)
            continue
        if kind == "multi":
            bad = [v for v in vs if v not in q["options"]]
            if bad:
                raise FqRefused(tr("Please check your answer to “{0}”.", label, lg=lg), qid)
            ans[qid] = [o for o in q["options"] if o in vs]
            continue
        v = vs[0]
        if kind == "choice" and v not in q["options"] or kind == "yesno" and v not in ("yes", "no"):
            raise FqRefused(tr("Please check your answer to “{0}”.", label, lg=lg), qid)
        if kind == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise FqRefused(tr("“{0}”: please enter a date.", label, lg=lg), qid)
        if kind == "date":
            import datetime
            try:
                datetime.date.fromisoformat(v)
            except ValueError:
                raise FqRefused(tr("“{0}”: please enter a date.", label, lg=lg), qid) from None
        if kind == "number":
            n = v.replace(" ", "").replace(" ", "")
            n = n.replace(".", "").replace(",", ".") if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", n) else n.replace(",", ".")
            try:
                f = float(n)
            except ValueError:
                f = None
            if f is None or f != f or abs(f) > 1e15:
                raise FqRefused(tr("“{0}”: please enter a number.", label, lg=lg), qid)
            v = n
        ans[qid] = v[:FQ_LONG_MAX if kind == "long" else FQ_SHORT_MAX]
    return ans, ups


def fq_text_of(qs, ans):
    """All typed text of a send (for the link limit)."""
    return " ".join(" ".join(v) if isinstance(v, list) else str(v) for v in ans.values())


def fq_shown(q, v, lg):
    if v is None or v == "" or v == []:
        return "—"
    if q["kind"] == "yesno":
        return tr(FQ_YES if v == "yes" else FQ_NO, lg=lg)
    if q["kind"] == "multi":
        return "\n".join("- " + x for x in v)
    if q["kind"] == "choice":
        return "- " + v
    if q["kind"] == "file":
        return tr("{0} (attachment)", v, lg=lg)
    return v


def fq_markdown(qs, ans, lg):
    """The answers as Markdown for the task's description (a heading per question)."""
    parts = []
    for q in qs:
        parts.append("### " + q["label"] + "\n" + fq_shown(q, ans.get(q["id"]), lg))
    return "\n\n".join(parts)


# ---- the client of a send
def fq_client(c, f, email, name, lg):
    """(client id or None, a note for the task) for a sent questionnaire with client_match on. Only the list's space: the
    client of the list itself, else the ONE client of the list's organisation (or the list owner's private clients) with
    this address (client e-mail, contact persons, linked address book contacts -- hub/hubmail.py hbm_match). Unknown:
    a new client there when the form allows it (client_new), else a note."""
    from ..hub.hubmail import hbm_match
    lr = c.execute("SELECT client_id, org_id FROM lists WHERE id=?", (f["list_id"],)).fetchone()
    if lr and lr["client_id"]:
        cl = c.execute("SELECT id, name, org_id, created_by FROM clients WHERE id=?", (lr["client_id"],)).fetchone()
        if cl and cl["org_id"] == lr["org_id"] and (cl["org_id"] or cl["created_by"] == f["l_owner"]):
            return cl["id"], tr("Client: {0}", cl["name"], lg=lg)
    if not email:
        return None, ""
    cid = hbm_match(c, f["l_owner"], f["l_org"], [email.lower()])
    if cid:
        cl = c.execute("SELECT name FROM clients WHERE id=?", (cid,)).fetchone()
        return cid, tr("Client: {0}", cl["name"] if cl else "", lg=lg)
    from .clients import clients_on
    if f["client_new"] and clients_on(c, f["l_owner"]) and not hit_limit(f"fqnc:{f['id']}", FQ_NEW_CLIENTS_DAY, 86400):
        from ..core.pg import insert_id
        ts = iso(now_utc())
        nm = (name or email)[:80]
        cid = insert_id(c, "INSERT INTO clients(org_id,name,email,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (f["l_org"], nm, email, f["l_owner"], ts, ts))
        return cid, tr("New client created: {0} <{1}> (please check)", nm, email, lg=lg)
    return None, tr("Client unknown: {0}", email, lg=lg)


# ---- 2.102.0 C (#2201): the client link -- the form's link with ?k=<client id>.<signature> (server key, form id, client id):
# a send through it belongs to that client, before any e-mail matching. Only a client of the list's space counts (checked
# again on every send, the list may have moved); a missing, forged or foreign value is ignored without a word (the page and
# the answer stay the same), then everything goes on as before.
FQ_CK_RE = re.compile(r"[1-9][0-9]{0,17}\.[0-9a-f]{32}")


def fq_ck_sig(c, fid, cid):
    from ..accounts.login import auth_key
    return hmac.new(auth_key(c), f"kalmido-form-client|{fid}|{cid}".encode(), hashlib.sha256).hexdigest()[:32]


def fq_ck_in():
    """The client link value of the request (the page's ?k=, the hidden field ck of a send) when it looks like one, else ''."""
    v = request.form.get("ck") if request.method == "POST" else request.args.get("k")
    return v if isinstance(v, str) and FQ_CK_RE.fullmatch(v) else ""


def fq_space_client(c, f, cid):
    """Client row cid when it is of the space of form row f's list (the organisation of the list, or the list owner's private
    clients), else None -- the same space as the e-mail matching."""
    cl = c.execute("SELECT id, name, org_id, created_by FROM clients WHERE id=?", (cid,)).fetchone()
    if cl and (cl["org_id"] or None) == (f["l_org"] or None) and (cl["org_id"] or cl["created_by"] == f["l_owner"]):
        return cl
    return None


def fq_ck_client(c, f, v):
    """(client id, note) of a signed client link value v for form row f; (None, '') when it is missing, forged, another
    form's or of a client outside the list's space."""
    if not v or not FQ_CK_RE.fullmatch(v):
        return None, ""
    cid, sig = v.split(".")
    if not hmac.compare_digest(fq_ck_sig(c, f["id"], int(cid)), sig):
        return None, ""
    cl = fq_space_client(c, f, int(cid))
    return (cl["id"], tr("Client: {0}", cl["name"], lg=lang(c, f["l_owner"]))) if cl else (None, "")


def fq_ck_url(c, f, cid):
    from .forms import form_url
    return form_url(c, f) + "?k=" + f"{cid}.{fq_ck_sig(c, f['id'], cid)}"


def fq_list_space(c, lid):
    r = c.execute("SELECT org_id, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    return {"l_org": r["org_id"], "l_owner": r["owner_id"]}


@app.get("/api/forms/<int:fid>/client-link")
def fq_client_link(fid):
    """The link of a form for one client (?client=<id>; owner / list admins, a client of the list's space they see): {url}."""
    from .clients import need_client
    c = db()
    f = _form_of(c, fid)
    try:
        cid = int(request.args.get("client") or "")
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "client")) from None
    need_client(c, cid)
    fs = {**dict(f), **fq_list_space(c, f["list_id"])}
    if not fq_space_client(c, fs, cid):
        raise BadInput(tr("This client is not in the workspace of the list"))
    return jsonify(url=fq_ck_url(c, fs, cid))


@app.get("/api/clients/<int:cid>/forms")
def fq_client_forms(cid):
    """The open forms a client's link can be copied of: forms of lists of the client's space that I manage
    {forms: [{id, title, list_id, list_name, questions, url}]} (url = the link for this client)."""
    from .clients import need_client
    from .forms import _gate, need_form_manager
    c = db()
    _gate()
    cl = need_client(c, cid)
    q = """SELECT f.*, l.org_id AS l_org, l.owner_id AS l_owner, l.name AS l_name FROM forms f JOIN lists l ON l.id=f.list_id
           WHERE f.enabled=1 AND l.archived=0 AND """
    rows = (c.execute(q + "l.org_id=? ORDER BY lower(l.name), f.id", (cl["org_id"],)) if cl["org_id"]
            else c.execute(q + "l.org_id IS NULL AND l.owner_id=? ORDER BY lower(l.name), f.id", (cl["created_by"],))).fetchall()
    out = []
    for f in rows:
        try:
            need_form_manager(c, f["list_id"])
        except (Denied, BadInput):
            continue
        if fq_space_client(c, f, cid):
            out.append({"id": f["id"], "title": f["title"], "list_id": f["list_id"], "list_name": f["l_name"],
                        "questions": len(fq_list(f)), "url": fq_ck_url(c, f, cid)})
    return jsonify(forms=out)


def fq_entry_save(c, tid, f, cid, sender, email, ans):
    c.execute("INSERT INTO form_entries(task_id,form_id,client_id,sender,email,answers,created_at) VALUES(?,?,?,?,?,?,?)",
              (tid, f["id"], cid, sender[:120], email[:200], json.dumps(ans, ensure_ascii=False), iso(now_utc())))


# ---- the evaluation (people who manage the form)
def _form_of(c, fid):
    from .forms import _form_row, _gate
    _gate()
    return _form_row(c, fid)


def fq_entries(c, f):
    """The submissions of form row f: the tasks it made that are still in its list (not in the trash). The client's name
    only while the client is of the list's space (a list that moved on takes no other space's names along)."""
    lorg = c.execute("SELECT org_id FROM lists WHERE id=?", (f["list_id"],)).fetchone()[0]
    rows = c.execute("""SELECT e.*, t.title, t.status, cl.name AS cl_name, cl.org_id AS cl_org FROM form_entries e
                        JOIN tasks t ON t.id=e.task_id LEFT JOIN clients cl ON cl.id=e.client_id
                        WHERE e.form_id=? AND t.list_id=? AND t.deleted_at IS NULL ORDER BY e.created_at DESC, e.task_id DESC LIMIT ?""",
                     (f["id"], f["list_id"], FQ_ENTRIES_MAX)).fetchall()
    out = []
    for r in rows:
        try:
            ans = json.loads(r["answers"] or "{}")
        except ValueError:
            ans = {}
        cl = {"id": r["client_id"], "name": r["cl_name"]} if r["client_id"] and r["cl_org"] == lorg else None
        out.append({"task_id": r["task_id"], "title": r["title"], "done": r["status"] != 0, "created_at": r["created_at"],
                    "sender": r["sender"], "email": r["email"], "client": cl, "answers": ans if isinstance(ans, dict) else {}})
    return out


@app.get("/api/forms/<int:fid>/entries")
def fq_entries_get(fid):
    """The submissions of a questionnaire (owner / list admins): {questions, entries: [{task_id, title, done, created_at,
    sender, email, client, answers: {question id: value}}]} (newest first, at most FQ_ENTRIES_MAX)."""
    c = db()
    f = _form_of(c, fid)
    return jsonify(questions=fq_list(f), entries=fq_entries(c, f))


@app.get("/api/forms/<int:fid>/entries.csv")
def fq_entries_csv(fid):
    """The same as CSV: one row per submission, a column per question (formulas defused like the other exports)."""
    c = db()
    f = _form_of(c, fid)
    qs = fq_list(f)
    lg = lang()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if dec_comma(lg) else ",", lineterminator="\r\n")
    w.writerow([tr("Date"), tr("Task"), tr("Name"), tr("E-mail"), tr("Client"), tr("Done")] + [_csv_cell(q["label"]) for q in qs])
    for en in fq_entries(c, f):
        a = en["answers"]
        cells = []
        for q in qs:
            v = a.get(q["id"])
            v = "; ".join(v) if isinstance(v, list) else (tr(FQ_YES if v == "yes" else FQ_NO) if q["kind"] == "yesno" and v else v)
            cells.append(_csv_cell(v))
        w.writerow([en["created_at"][:16].replace("T", " "), _csv_cell(en["title"]), _csv_cell(en["sender"]), _csv_cell(en["email"]),
                    _csv_cell((en["client"] or {}).get("name")), tr("Yes") if en["done"] else ""] + cells)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f"{f['title']}-{now_utc().date().isoformat()}.csv")
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})

