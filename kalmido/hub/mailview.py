"""2.141.0 B (#2140, #2139): the HTML view of a filed e-mail and a task / an event made from it (hub/hubmail.py files the mails).

HTML view (#2140): the text/html part of the original .eml (the file store, read with the mail's rights: hbm_can) is served by
its OWN route, not as an iframe srcdoc -- a srcdoc frame inherits the app's CSP (img-src 'self' data:), so "Load images" could
not work there and the mail would run under the app's origin rules; the own answer carries its own strict CSP instead:
default-src 'none', inline styles, img-src data: (+ https: after "Load images"), no fonts / frames / forms / base / scripts,
frame-ancestors 'self' and the CSP sandbox (opaque origin, also when the URL is opened in a tab). The client frames it in an
<iframe sandbox> without allow-scripts / allow-same-origin. On top the HTML is cleaned here (an allow list of tags and
attributes: script / iframe / object / embed / form / meta / link / base / svg and every on* attribute go, javascript: and
other non-web URLs go, links open in a new tab with noopener / noreferrer) -- two walls, each holds alone. Embedded cid:
pictures become data: URLs (image types only, size capped); external pictures and CSS url() stay out until "Load images"
(counted for the quiet hint). A broken or unreadable .eml, or a mail without an HTML part = no HTML (the text view stays).

Mail -> task / event (#2139): a task in a list / an event in a calendar of the mail's workspace where the person may write;
title = the subject without Re / Fwd, description = the start of the text + the sender. hub_mail_links remembers the mail
(kind task | event, ref_id). The task / event shows "E-mail: <subject>" only to who may read the mail (else "E-mail" without
subject or id); the mail shows its tasks / events to who may see them. Agents never reach these routes (the hub gate), the
task itself is a normal task (its events as ever), the mail stays invisible for them."""
import base64
import email
import email.policy
import html
import re
from html.parser import HTMLParser

from flask import jsonify, make_response, request

from ..core.config import app
from ..core.pg import insert_id
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..core.access import Denied, WRITE_ROLES, acx_lists_sql, list_role, need_task, need_feat
from ..accounts.session import me
from .hubmail import _gate, _need_mail, _open, hbm_can

MH_HTML_MAX = 500000        # characters of an HTML part shown (like HBM_BODY_MAX, more room for the markup)
MH_EML_MAX = 40 << 20       # a larger .eml is not opened for the HTML view (the text view stays)
MH_CID_MAX = 3 << 20        # one embedded picture at most
MH_CID_TOTAL = 12 << 20     # all embedded pictures of one mail at most
MH_TEXT_MAX = 1500          # characters of the mail text taken into a new task / event
MH_IMG_TYPES = ("image/png", "image/gif", "image/jpeg", "image/webp", "image/bmp")

# ---- the HTML cleaner (allow list) -----------------------------------------------------------------------------------
_TAGS = frozenset("""a abbr address article aside b bdi bdo big blockquote br caption center cite code col colgroup dd del details dfn
div dl dt em figcaption figure font footer h1 h2 h3 h4 h5 h6 header hr i img ins kbd li main mark nav ol p pre q s samp section small
span strike strong sub summary sup table tbody td tfoot th thead tr tt u ul wbr""".split())
_VOID = frozenset(("br", "col", "hr", "img", "wbr"))
# every element without an end tag (never waited for when it is dropped)
_VOID_ALL = _VOID | frozenset("area base basefont embed frame input keygen link meta param source track".split())
# dropped WITH their content (the head's own children: title, meta, link, base go; its style blocks stay, cleaned)
_DROP = frozenset("""script style title iframe frame frameset object embed applet noscript template svg math select textarea
option audio video canvas portal noembed noframes xml meta link base input button area map param source track""".split())
_ATTRS = frozenset("""align valign width height border cellpadding cellspacing bgcolor color face size colspan rowspan dir lang title alt
start type summary nowrap id name class style span headers scope abbr cite datetime reversed""".split())
_URL_RE = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
_CSS_AT = re.compile(r"@import[^;]*;?|@namespace[^;]*;?|@charset[^;]*;?|@font-face\s*\{[^}]*\}", re.I)
# a declaration that could run code or hide a word behind CSS escapes goes as a whole
_CSS_BAD = re.compile(r"[^;{}]*(?:expression\s*\(|javascript\s*:|vbscript\s*:|behavior\s*:|-moz-binding|image-set\s*\(|url\s*\((?![^)]*\))|\\)[^;{}]*", re.I)
_LINK_OK = re.compile(r"^(https?:|mailto:|tel:|#)", re.I)


class _Cleaner(HTMLParser):
    def __init__(self, cids, images):
        super().__init__(convert_charrefs=True)
        self.cids, self.images, self.out, self.css, self.ext = cids, images, [], [], 0
        self.skip = []      # the dropped elements we are inside of (their content goes too)
        self.in_style = False

    # a URL of a picture: data:image / cid: (embedded) / https (after "Load images") -- else nothing
    def _img(self, v):
        v = (v or "").strip()
        lv = v.lower()
        if lv.startswith("data:image/") and not lv.startswith("data:image/svg"):
            return v
        if lv.startswith("cid:"):
            return self.cids.get(v[4:].strip("<> ").lower(), "")
        if lv.startswith(("http:", "https:", "//")):
            self.ext += 1
            if self.images:
                return "https:" + v.split(":", 1)[1] if lv.startswith("http:") else ("https:" + v if lv.startswith("//") else v)
        return ""

    def _css(self, s):
        """A style value / block without what could load or run code; url() follows the picture rules."""
        def url(m):
            u = self._img(m.group(2))
            return "url('" + re.sub(r"[\s'\"()\\<>]", lambda ch: "%%%02X" % ord(ch.group()), u) + "')" if u else "none"
        return _URL_RE.sub(url, _CSS_BAD.sub("", _CSS_AT.sub("", s.replace("<", " "))))

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def _start(self, tag, attrs, closed):
        if self.skip:
            if tag not in _VOID_ALL and not closed:
                self.skip.append(tag)
            return
        if tag == "style":
            if not closed:
                self.in_style = True
                self.skip.append(tag)
            return
        if tag in _DROP:
            if tag not in _VOID_ALL and not closed:
                self.skip.append(tag)
            return
        if tag not in _TAGS:
            return  # unknown / unwanted tags go, their text stays (html, body, form, o:p ...)
        a = []
        href = None
        for k, v in attrs:
            k = (k or "").lower()
            if v is None:
                v = ""
            if k == "style":
                v = self._css(v)
                if v.strip():
                    a.append((k, v))
            elif k == "href" and tag == "a":
                v = v.strip()
                if _LINK_OK.match(v):
                    href = v
            elif k == "src" and tag == "img":
                u = self._img(v)
                if u:
                    a.append(("src", u))
            elif k == "background":
                u = self._img(v)
                if u:
                    a.append(("background", u))
            elif k in _ATTRS:
                a.append((k, v[:2000]))
        if tag == "a" and href is not None:
            a.insert(0, ("href", href))
            a += [("target", "_self")] if href.startswith("#") else [("target", "_blank"), ("rel", "noopener noreferrer")]
        self.out.append(f"<{tag}" + "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in a) + ">")

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
                if tag == "style" and not self.skip:
                    self.in_style = False
            elif tag in self.skip:  # badly nested: close up to it
                while self.skip and self.skip.pop() != tag:
                    pass
                self.in_style = bool(self.skip and "style" in self.skip)
            return
        if tag in _TAGS and tag not in _VOID:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.skip:
            if self.in_style and self.skip == ["style"]:
                self.css.append(self._css(data))
            return
        self.out.append(html.escape(data, quote=False))

    # comments (conditional comments too), declarations, processing instructions: dropped
    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass


_BASE_CSS = (":root{color-scheme:light}html{background:#fff;color:#1a1a1a}body{margin:0.75rem;font:0.875rem/1.45 system-ui,"
             "-apple-system,'Segoe UI',sans-serif;overflow-wrap:anywhere}img{max-width:100%}table{max-width:100%}pre{white-space:pre-wrap}")


def mh_clean(src, cids=None, images=False):
    """(document, number of external pictures / CSS URLs) of the HTML src, cleaned (allow list)."""
    p = _Cleaner(cids or {}, images)
    try:
        p.feed(src[:MH_HTML_MAX])
        p.close()
    except Exception:  # noqa: BLE001 -- the parser gives up on strange input: what was cleaned so far stays
        pass
    css = "".join(p.css)
    doc = ('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><base target="_blank">'
           f"<style>{_BASE_CSS}</style>" + (f"<style>{css}</style>" if css.strip() else "") + "</head><body>" + "".join(p.out) + "</body></html>")
    return doc, p.ext


def mh_parts(raw):
    """(the first text/html part that is no attachment, {content-id: data URL}) of a raw mail; html None when there is none."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    src, cids, total = None, {}, 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "").lower()
        cid = str(part.get("Content-ID") or "").strip().strip("<>").lower()
        if cid and ctype in MH_IMG_TYPES:
            try:
                data = part.get_payload(decode=True) or b""
            except Exception:  # noqa: BLE001
                data = b""
            if data and len(data) <= MH_CID_MAX and total + len(data) <= MH_CID_TOTAL:
                total += len(data)
                cids[cid] = f"data:{ctype};base64," + base64.b64encode(data).decode("ascii")
            continue
        if ctype == "text/html" and src is None and disp != "attachment" and not part.get_filename():
            try:
                src = part.get_content()
            except Exception:  # noqa: BLE001
                src = None
    return src, cids


def mh_of(c, m):
    """(html, cids) of hub mail row m (the rights checked before: _need_mail), or None (no .eml, unreadable, sealed with a
    key that does not open, too big, no HTML part)."""
    if not m["eml_id"]:
        return None
    from ..files.store import fs_read
    n = c.execute("SELECT id, org_id, size FROM fs_nodes WHERE id=? AND deleted_at IS NULL AND kind='file'", (m["eml_id"],)).fetchone()
    if not n or (n["org_id"] or None) != (m["org_id"] or None) or (n["size"] or 0) > MH_EML_MAX:
        return None
    try:
        raw = fs_read(c, n["id"])
        if not raw or len(raw) > MH_EML_MAX:
            return None
        src, cids = mh_parts(raw)
    except Exception as e:  # noqa: BLE001 -- a broken / locked / unreadable original: the text view stays
        print("hubmail: no html view", type(e).__name__, flush=True)
        return None
    return (src, cids) if src and src.strip() else None


def mh_csp(images):
    return ("default-src 'none'; style-src 'unsafe-inline'; img-src data:" + (" https:" if images else "") +
            "; frame-ancestors 'self'; base-uri 'none'; form-action 'none'; sandbox allow-popups allow-popups-to-escape-sandbox")


@app.get("/api/hubmail/mails/<int:mid>/html")
def mh_mail_html(mid):
    """The HTML part of a mail I see, cleaned, as a page for the sandboxed frame of the reading view (?images=1 = with
    external pictures). 404 when the mail has no HTML part."""
    c = db()
    _gate()
    m = _need_mail(c, mid)
    got = mh_of(c, m)
    if not got:
        raise Denied(404)
    images = request.args.get("images") in ("1", "true")
    doc, _n = mh_clean(got[0], got[1], images)
    resp = make_response(doc)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Content-Security-Policy"] = mh_csp(images)
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


def mh_info(c, m):
    """For the reading view (GET /api/hubmail/mails/<id>): {"html": bool, "html_ext": external pictures} + the links."""
    got = mh_of(c, m)
    ext = mh_clean(got[0], got[1], False)[1] if got else 0
    return {"html": bool(got), "html_ext": ext, "made": mh_made(c, m["id"])}


# ---- mail -> task / event ---------------------------------------------------------------------------------------------
def _org(x):
    return int(x) if x else None


def _defaults(c, m):
    """(title, description) for a task / an event from mail row m."""
    from ..integrations.mail import MAIL_PREFIX_RE
    d = _open(c, m)
    title = MAIL_PREFIX_RE.sub("", re.sub(r"\s+", " ", d["subject"] or "")).strip()
    text = (d["body"] or "").strip()
    if not title:
        title = text.split("\n", 1)[0][:120] if text else tr("E-mail")
    if len(text) > MH_TEXT_MAX:
        text = text[:MH_TEXT_MAX].rstrip() + " …"
    sender = f"{d['from_name']} <{d['from_addr']}>" if d["from_name"] and d["from_addr"] else (d["from_addr"] or d["from_name"] or "")
    desc = (text + "\n\n" if text else "") + (f"— {tr('E-mail from {0}', sender)}" if sender else "")
    return title[:300], desc.strip()


def _lists(c, uid, org):
    rows = c.execute(f"SELECT id, name, org_id, kind, e2e, archived FROM lists WHERE id IN {acx_lists_sql()} AND COALESCE(e2e,'')='' "
                     "AND archived=0 AND deleted_at IS NULL ORDER BY lower(name), id", (uid, uid)).fetchall()
    return [{"id": r["id"], "name": r["name"], "kind": r["kind"]} for r in rows
            if _org(r["org_id"]) == org and list_role(c, r["id"], uid) in WRITE_ROLES]


def _cals(c, uid, org):
    from ..events.model import can_write, my_cal_ids
    ids = {k: v for k, v in my_cal_ids(c, uid).items() if can_write(v)}
    if not ids:
        return []
    rows = c.execute(f"SELECT id, name, org_id, color FROM ev_cals WHERE id IN ({','.join('?' * len(ids))}) ORDER BY owner_id!=?, sort, id",
                     [*ids, uid]).fetchall()
    return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows if _org(r["org_id"]) == org]


def mh_made(c, mid):
    """The tasks / events made from mail mid that I see: [{kind, id, title}]."""
    from ..events.model import need_event
    out = []
    for r in c.execute("SELECT kind, ref_id FROM hub_mail_links WHERE mail_id=? ORDER BY id", (mid,)).fetchall():
        try:
            if r["kind"] == "task":
                need_task(c, r["ref_id"], write=False)
                t = c.execute("SELECT title, deleted_at FROM tasks WHERE id=?", (r["ref_id"],)).fetchone()
                if t and not t["deleted_at"]:
                    out.append({"kind": "task", "id": r["ref_id"], "title": t["title"]})
            elif r["kind"] == "event":
                e, _role = need_event(c, r["ref_id"])
                out.append({"kind": "event", "id": r["ref_id"], "title": e["title"], "start": e["start"]})
        except Denied:
            continue
    return out


def _link(c, m, kind, ref):
    c.execute("INSERT INTO hub_mail_links(mail_id, org_id, kind, ref_id, created_by, created_at) VALUES(?,?,?,?,?,?)",
              (m["id"], m["org_id"], kind, ref, me(), iso(now_utc())))


@app.get("/api/hubmail/mails/<int:mid>/make")
def mh_make_targets(mid):
    """The lists and calendars of the mail's workspace I may write in, the proposed title / description and what was made
    from the mail already (for the dialogs "Task from it" / "Event from it")."""
    c = db()
    _gate()
    uid = me()
    m = _need_mail(c, mid)
    org = _org(m["org_id"])
    title, desc = _defaults(c, m)
    return jsonify(lists=_lists(c, uid, org), calendars=_cals(c, uid, org), title=title, description=desc, made=mh_made(c, mid))


def _title(b, fallback):
    t = b.get("title")
    if t is not None and not isinstance(t, str):
        raise Denied(400, tr("Invalid value: {0}", "title"))
    return (re.sub(r"\s+", " ", t or "").strip() or fallback)[:300]


@app.post("/api/hubmail/mails/<int:mid>/task")
def mh_make_task(mid):
    """{list_id, title?, due?} -- a task from the mail in a list of its workspace where I may write (title = the subject
    without Re / Fwd, description = the start of the text + the sender); the task remembers the mail."""
    from ..collab.liste2eguard import le2b_list_locked
    from ..tasks.validation import log_act
    from ..agents.core import agent_added_events
    c = db()
    _gate()
    uid = me()
    m = _need_mail(c, mid)
    b = body() if isinstance(body(), dict) else {}
    lid, due = b.get("list_id"), b.get("due")
    if isinstance(lid, bool) or not isinstance(lid, int):
        return err(tr("Invalid value: {0}", "list_id"))
    if due not in (None, "") and not (isinstance(due, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", due)):
        return err(tr("Invalid value: {0}", "due"))
    if list_role(c, lid, uid) not in WRITE_ROLES:
        raise Denied(404)
    l = c.execute("SELECT org_id, e2e, archived FROM lists WHERE id=?", (lid,)).fetchone()
    if _org(l["org_id"]) != _org(m["org_id"]):
        return err(tr("The project belongs to another workspace"), 409)
    if l["archived"]:  # 2.141.0 B (#2139, review): not into an archived list
        raise Denied(404)
    if l["e2e"] or le2b_list_locked(c, lid):
        return err(tr("Not possible in a locked project"), 409)
    title0, desc = _defaults(c, m)
    title = _title(b, title0)
    ts = iso(now_utc())
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,sort,due,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                    (lid, title, desc, srt, due or None, ts, ts, uid))
    log_act(c, tid, "created", uid=uid)
    agent_added_events(c, tid, source="mail")  # a normal task for the list's agent (as a task by mail); the mail stays out
    _link(c, m, "task", tid)
    bump(c)
    c.commit()
    return jsonify(task_id=tid, list_id=lid, title=title, made=mh_made(c, mid)), 201


@app.post("/api/hubmail/mails/<int:mid>/event")
def mh_make_event(mid):
    """{cal_id, start (YYYY-MM-DD = all day, YYYY-MM-DDTHH:MM = one hour), title?} -- an event from the mail in a calendar of
    its workspace where I may write; the event remembers the mail."""
    from ..events.model import need_evcal
    from ..events.web import op_event_new
    c = db()
    _gate()
    need_feat("events")
    uid = me()
    m = _need_mail(c, mid)
    b = body() if isinstance(body(), dict) else {}
    cid, start = b.get("cal_id"), b.get("start")
    if isinstance(cid, bool) or not isinstance(cid, int):
        return err(tr("Invalid value: {0}", "cal_id"))
    if not isinstance(start, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?", start):
        return err(tr("Invalid value: {0}", "start"))
    cal, _role = need_evcal(c, cid, write=True)
    if _org(cal["org_id"]) != _org(m["org_id"]):
        return err(tr("The calendar belongs to another workspace"), 409)
    title0, desc = _defaults(c, m)
    ev = op_event_new(c, uid, {"cal_id": cid, "title": _title(b, title0), "description": desc, "start": start,
                               "all_day": len(start) == 10})
    _link(c, m, "event", ev["id"])
    bump(c)
    c.commit()
    return jsonify(event_id=ev["id"], start=ev.get("start"), title=ev.get("title"), made=mh_made(c, mid)), 201


@app.get("/api/hubmail/links")
def mh_links():
    """?task_id= | ?event_id= -- the mails a task / an event was made from: {mail_id, subject} for a mail I may read, else
    {mail_id: null, subject: ""} (no subject, no id: nothing leaks)."""
    from ..events.model import need_event
    c = db()
    _gate()
    uid = me()
    a = request.args
    try:
        tid, eid = int(a.get("task_id") or 0), int(a.get("event_id") or 0)
    except ValueError:
        raise Denied(400, tr("Invalid data")) from None
    if tid:
        need_task(c, tid, write=False)
        kind, ref = "task", tid
    elif eid:
        need_event(c, eid)
        kind, ref = "event", eid
    else:
        raise Denied(400, tr("Invalid data"))
    out = []
    for r in c.execute("SELECT DISTINCT mail_id FROM hub_mail_links WHERE kind=? AND ref_id=? ORDER BY mail_id", (kind, ref)).fetchall():
        m = c.execute("SELECT * FROM hub_mails WHERE id=?", (r["mail_id"],)).fetchone()
        if m and not m["deleted_at"] and hbm_can(c, uid, m):
            out.append({"mail_id": m["id"], "subject": _open(c, m)["subject"] or ""})
        else:
            out.append({"mail_id": None, "subject": ""})
    return jsonify(links=out)
