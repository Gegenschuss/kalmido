"""2.50.0 (#1200): approvals with a simple electronic signature through a customer link (table office_signoffs).
A member of the organisation creates an approval link for a SENT quotation (kind offer) -- or, from a list's public link
(#329), for the acceptance of the project / a section / a milestone (kind acceptance). The customer opens /s/q/<token>
(server-rendered like the public list page, no scripts): sees the quotation (summary + PDF) or what is to be accepted,
types a name, ticks the box and accepts or declines (optional reason). Stored: name, e-mail (optional), time (UTC),
client address, user agent, the SHA-256 of what was shown (doc_hash) -> office_signoffs + office_doc_log. The quotation
is set to accepted / declined through docs.odoc_set_status, the same code as the status change in the app (purchase,
pipeline). After that the link shows only the confirmation; a second decision is impossible. A quotation changed
after the link was made voids the link.
Security: 256-bit token (only its hash is looked up, sealed copy for the creator), the same answer for unknown / expired /
revoked / voided links, rate limits per client address and per link, a form check value bound to the link (HMAC) plus
Sec-Fetch-Site, escaped text, length limits. This is a simple electronic signature (no advanced / qualified one)."""
import hashlib
import hmac
import html
import json
import secrets
import threading
from datetime import date, datetime, timedelta

from flask import g, jsonify, redirect, request

from ..core.config import app, APP_NAME, PUBLIC_URL, TZ
from ..core.i18n import N_, tr
from ..core.db import body, db, err, iso, local_now, now_utc, parse_iso, usettings
from ..core.pg import insert_id, system_ctx, write_lock
from ..core.access import acx_anon_bind, Denied, need_list
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from .model import office_role
from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, _token_hash, rate_ip
from ..accounts.login import auth_key, seal, unseal
from ..api.v1 import hit_limit
from ..notify.alerts import aa_count
from ..personal.timetrack import BadInput
from ..tasks.validation import valid_date
from ..lists.public import PUB_ACTOR, PUB_TOKEN_RE, pub_gone, pub_html, pub_limited, public_links_on

SIG_PREFIX = "/s/q/"
SIG_VIEW_RATE = 60          # page views per client address and minute
SIG_POST_RATE = 10          # decisions per client address and minute
SIG_BAD_LIMIT = 30          # unknown / expired tokens per address within the fail window (shared with the list links)
SIG_LINK_HOUR = 20          # decision attempts per link and hour
NAME_MAX, EMAIL_MAX, REASON_MAX, UA_MAX = 120, 200, 1000, 300
SIG_KINDS = ("offer", "acceptance", "document", "video")  # 2.93.0 A (#1927): document = a document made from a template (office/doctpl.py)
# 2.99.1 A (#1959): video = a video sign-off (videos/review.py; accept = "Approve", decline = "Request changes"); its page shows
# the player (no script of the provider, only static/pubvideo.js) and takes comments: its own CSP
SIG_VIDEO_CSP = ("default-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; script-src 'self'; "
                 "frame-src https://player.vimeo.com https://www.youtube-nocookie.com; media-src https:; form-action 'self'; "
                 "frame-ancestors 'none'; base-uri 'none'")
LOG_TEXT = {"accepted": "signoff_accepted", "declined": "signoff_declined"}
SIG_PDF_KEEP_DAYS = 30      # 2.86.0 (N17): a decided quotation's PDF stays downloadable this long when the link has no expiry
SIG_NOTE = N_("Simple electronic signature: usually enough to accept a quotation or confirm an acceptance; not for contracts that the law requires in written form (they need a qualified signature). This is not legal advice.")  # noqa: E501


# ---------------------------------------------------------------- helpers
def sig_token_new(c, purpose):
    tok = secrets.token_urlsafe(32)  # 256 bits
    return tok, _token_hash(tok), seal(c, purpose, tok)


def sig_purpose(r):
    if r["kind"] == "document":  # 2.93.0 A (#1927)
        return f"signoff:document:{r['gen_doc_id'] or 0}"
    if r["kind"] == "video":  # 2.99.1 A (#1959)
        return f"signoff:video:{r['video_id'] or 0}"
    return f"signoff:{r['kind']}:{r['doc_id'] or 0}:{r['list_id'] or 0}"


def sig_url(c, r):
    try:
        tok = unseal(c, sig_purpose(r), r["token"])
    except Exception:  # a changed server key: the link cannot be shown again (it still works for whoever has it)
        return None
    return PUBLIC_URL.rstrip("/") + SIG_PREFIX + tok


def sig_expiry(v):
    """'YYYY-MM-DD' | None -> stored expiry (valid through the end of that day) | None; BadInput on a bad date."""
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not valid_date(v) or v < local_now().date().isoformat():
        raise BadInput(tr("The expiry date must be today or later"))
    d = date.fromisoformat(v) + timedelta(days=1)
    return iso(datetime(d.year, d.month, d.day, tzinfo=TZ))


def sig_doc_hash(c, oid, did):
    """SHA-256 of a quotation's printed content (canonical JSON of the print model's customer-facing parts)."""
    from .docs import odoc_render
    m = odoc_render(c, did, oid)
    keep = {k: m.get(k) for k in ("kind", "number", "date", "valid_until", "currency", "vat_mode", "project_title", "project_ref",
                                  "service_from", "service_to", "recipient", "intro", "lines", "totals", "rights", "closing", "fields",
                                  "parts")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest(), m


def sig_list_hash(c, r):
    """SHA-256 of what an acceptance covers: the list / section / milestone name and its tasks (ids + titles; ticking
    tasks off does not void the link, the states at the decision go into the protocol)."""
    tasks = [[t["id"], t["title"]] for t in sig_list_tasks(c, r)]
    return hashlib.sha256(json.dumps([r["title"], tasks], ensure_ascii=False).encode()).hexdigest()


def sig_list_tasks(c, r):
    if r["task_id"]:
        sql, args = "id=? OR parent_id=?", (r["task_id"], r["task_id"])
    elif r["section_id"]:
        sql, args = "section_id=? AND parent_id IS NULL", (r["section_id"],)
    else:
        sql, args = "parent_id IS NULL", ()
    return [dict(t) for t in c.execute(f"SELECT id, title, status FROM tasks WHERE list_id=? AND deleted_at IS NULL AND status <> -1 AND ({sql}) "
                                       "ORDER BY sort, id LIMIT 500", (r["list_id"], *args))]


def sig_crypt_org(c, r):
    """2.50.0 (#1200 review): the organisation whose key protects the signer's data of approval r: its own, or for a
    private list's sign-off the personal office of the list's owner (None without one: stored plain like other private data)."""
    if not r["org_id"] and r["kind"] == "video" and r["video_id"]:  # 2.99.1 A (#1959): a private review: its owner's personal office
        with system_ctx(c):  # as below
            x = c.execute("SELECT o.id FROM video_reviews v JOIN orgs o ON o.personal_of=v.owner_id WHERE v.id=?", (r["video_id"],)).fetchone()
        return x[0] if x else None
    if r["org_id"] or not r["list_id"]:
        return r["org_id"]
    with system_ctx(c):  # the public page reads as "anon" without an organisation; only the key holder is resolved here
        x = c.execute("SELECT o.id FROM lists l JOIN orgs o ON o.personal_of=l.owner_id WHERE l.id=?", (r["list_id"],)).fetchone()
    return x[0] if x else None


def sig_dec(c, r):
    """r with the signer's data decrypted (see sig_crypt_org)."""
    oid = sig_crypt_org(c, r)
    if not oid:
        return dict(r)
    if r["org_id"]:
        return oc_dec_fields(c, oid, "office_signoffs", r)
    with system_ctx(c):  # the owner's personal key, outside the anon / member context of this request
        return oc_dec_fields(c, oid, "office_signoffs", r)


def sig_enc(c, r, vals):
    """vals with the signer's data encrypted (see sig_crypt_org)."""
    oid = sig_crypt_org(c, r)
    if not oid:
        return dict(vals)
    if r["org_id"]:
        return oc_enc_fields(c, oid, "office_signoffs", vals)
    with system_ctx(c):  # as in sig_dec
        return oc_enc_fields(c, oid, "office_signoffs", vals)


def sig_public(c, r, full=True):
    """full=False (members of the office who are not its admin): without the signer's e-mail, address and device
    (2.50.0 #1200 review: personal data of the customer only for the admins / the list's owner)."""
    d = sig_dec(c, r)
    live = d["state"] == "open" and not d["revoked_at"] and not (d["expires_at"] and parse_iso(d["expires_at"]) <= now_utc())
    return {"id": d["id"], "kind": d["kind"], "doc_id": d["doc_id"], "gen_doc_id": d.get("gen_doc_id"), "video_id": d.get("video_id"), "list_id": d["list_id"], "section_id": d["section_id"],
            "task_id": d["task_id"], "title": d["title"], "state": d["state"], "expires_at": d["expires_at"], "revoked_at": d["revoked_at"],
            "signer_name": d["signer_name"], "signer_email": d["signer_email"], "reason": d["reason"], "signed_at": d["signed_at"],
            "ip": d["ip"], "user_agent": d["user_agent"], "doc_hash": d["doc_hash"], "created_at": d["created_at"], "created_by": d["created_by"],
            "live": live, "url": sig_url(c, d) if live else None,
            **({} if full else {"signer_email": None, "ip": None, "user_agent": None})}


def sig_notify(c, r, st, name):
    """Push to the link's creator (notification switch "approval"): the customer decided."""
    uid = r["created_by"]
    if not uid:
        return None
    try:
        from ..collab.news import notif_ok
        s = usettings(c, uid)
        lid = r["list_id"]
        if r["kind"] == "video":  # 2.99.1 A (#1959): the list of the review's task / project (its mute switch)
            from ..videos.review import vdr_list_of, vdr_sig_row
            v = vdr_sig_row(c, r)
            lid = vdr_list_of(c, v) if v else None
        if not notif_ok(c, uid, s, "approval", "push", lid):
            return None
    except Exception:
        return None
    from ..notify.push import notify
    lg = s.get("lang") or "en"
    what = r["title"] or ""
    title = tr("Approved by the customer", lg=lg) if st == "accepted" else tr("Declined by the customer", lg=lg)
    if r["kind"] == "document" and st == "accepted":  # 2.93.0 A (#1927)
        title = tr("Signed by the customer", lg=lg)
    msg = f"{name}: {what}"
    click = f"#office/offers/{r['doc_id']}" if r["doc_id"] else f"#office/gendocs/{r['gen_doc_id']}" if r["kind"] == "document" else f"#l/{r['list_id']}"
    if r["kind"] == "video":  # 2.99.1 A (#1959)
        from ..videos.review import vdr_click, vdr_sig_row
        v = vdr_sig_row(c, r)
        click = vdr_click(v) if v else "#"
        title = tr("Video approved by the customer", lg=lg) if st == "accepted" else tr("Changes requested by the customer", lg=lg)
    return lambda: notify(uid, title, msg, prio="4", click=click, s=s)


# ---------------------------------------------------------------- managing (members of the organisation / list owner)
def sig_create(c, oid, kind, title, doc_hash, uid, expires, doc_id=None, list_id=None, section_id=None, task_id=None, gen_doc_id=None,
               video_id=None):
    """A new link (an open link of the same object is revoked first: one live link per object). -> (row, token)."""
    ts = iso(now_utc())
    if video_id:  # 2.99.1 A (#1959): a video sign-off
        c.execute("UPDATE office_signoffs SET revoked_at=? WHERE video_id=? AND state='open' AND revoked_at IS NULL", (ts, video_id))
    elif gen_doc_id:  # 2.93.0 A (#1927): a document made from a template
        c.execute("UPDATE office_signoffs SET revoked_at=? WHERE gen_doc_id=? AND state='open' AND revoked_at IS NULL", (ts, gen_doc_id))
    elif doc_id:
        c.execute("UPDATE office_signoffs SET revoked_at=? WHERE doc_id=? AND state='open' AND revoked_at IS NULL", (ts, doc_id))
    else:
        c.execute("UPDATE office_signoffs SET revoked_at=? WHERE list_id=? AND kind='acceptance' AND state='open' AND revoked_at IS NULL "
                  "AND section_id IS NOT DISTINCT FROM ? AND task_id IS NOT DISTINCT FROM ?", (ts, list_id, section_id, task_id))
    proto = {"kind": kind, "doc_id": doc_id, "list_id": list_id, "gen_doc_id": gen_doc_id, "video_id": video_id}
    tok, h, sealed = sig_token_new(c, sig_purpose(proto))
    sid = insert_id(c, "INSERT INTO office_signoffs(org_id, kind, doc_id, list_id, section_id, task_id, gen_doc_id, video_id, title, token_hash, token, "
                       "expires_at, state, doc_hash, created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?,?)",
                    (oid, kind, doc_id, list_id, section_id, task_id, gen_doc_id, video_id, title[:300], h, sealed, expires, doc_hash, uid, ts))
    return c.execute("SELECT * FROM office_signoffs WHERE id=?", (sid,)).fetchone(), tok


@app.post("/api/office/docs/<int:did>/signoff")
def sig_offer_new(did):
    """{expires: YYYY-MM-DD | null} -> a new approval link of a sent quotation (members, like a status change)."""
    from .docs import _ctx, doc_row
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    if r["kind"] != "offer" or r["status"] != "sent":
        return err(tr("Approval links exist for sent quotations only"), 409)
    if not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    b = body()
    try:
        exp = sig_expiry((b if isinstance(b, dict) else {}).get("expires"))
    except BadInput as x:
        return err(str(x))
    write_lock(c, f"office_signoff_doc_{int(did)}")
    h, m = sig_doc_hash(c, oid, did)
    title = " ".join(x for x in (m.get("title") or "", r["number"] or "", r["project_title"] or "") if x)
    row, tok = sig_create(c, oid, "offer", title, h, uid, exp, doc_id=did)
    ofx_log(c, oid, "signoff_link", doc_id=did, detail={"signoff": row["id"], "expires_at": exp, "doc_hash": h})
    c.commit()
    return jsonify(sig_public(c, row, office_role(c, uid, oid) == "admin"))


@app.get("/api/office/docs/<int:did>/signoffs")
def sig_offer_list(did):
    """The approval links of a quotation with their protocol (newest first)."""
    from .docs import _ctx, doc_row
    c, uid, oid = _ctx()
    doc_row(c, oid, did)
    rows = c.execute("SELECT * FROM office_signoffs WHERE doc_id=? AND org_id=? ORDER BY id DESC LIMIT 50", (did, oid)).fetchall()
    adm = office_role(c, uid, oid) == "admin"
    return jsonify(signoffs=[sig_public(c, r, adm) for r in rows])


@app.post("/api/office/signoffs/<int:sid>/revoke")
def sig_offer_revoke(sid):
    """Stops an open approval link at once (a decided one stays as it is: the protocol is kept)."""
    from .docs import _ctx
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    r = c.execute("SELECT * FROM office_signoffs WHERE id=? AND org_id=? AND (doc_id IS NOT NULL OR gen_doc_id IS NOT NULL)", (sid, oid)).fetchone()
    if not r:
        raise Denied(404)
    if r["gen_doc_id"] and office_role(c, uid, oid) != "admin":  # 2.93.0 A (#1927): documents are the admins' (like office/doctpl.py)
        raise Denied(403)
    if r["state"] == "open" and not r["revoked_at"]:
        c.execute("UPDATE office_signoffs SET revoked_at=? WHERE id=?", (iso(now_utc()), sid))
        ofx_log(c, oid, "signoff_revoke", target="gen_doc" if r["gen_doc_id"] else "doc", doc_id=r["doc_id"],
                detail={"signoff": sid, **({"gen_doc": r["gen_doc_id"]} if r["gen_doc_id"] else {})})
        c.commit()
    return jsonify(sig_public(c, c.execute("SELECT * FROM office_signoffs WHERE id=?", (sid,)).fetchone(), office_role(c, uid, oid) == "admin"))


# acceptance of a list (the owner of the list; from the list dialog > Public link)
def sig_list_target(c, lid, b):
    """(section_id, task_id, title) of an acceptance request body {section_id?, task_id?} (milestone = task with ms=1)."""
    sec, tid = b.get("section_id"), b.get("task_id")
    lname = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0]
    if tid is not None:
        t = c.execute("SELECT id, title FROM tasks WHERE id=? AND list_id=? AND deleted_at IS NULL AND ms=1", (tid if isinstance(tid, int) else -1, lid)).fetchone()
        if not t:
            raise BadInput(tr("Invalid value: {0}", "task_id"))
        return None, t["id"], f"{lname}: {t['title']}"
    if sec is not None:
        s = c.execute("SELECT id, name FROM sections WHERE id=? AND list_id=?", (sec if isinstance(sec, int) else -1, lid)).fetchone()
        if not s:
            raise BadInput(tr("Invalid value: {0}", "section_id"))
        return s["id"], None, f"{lname}: {s['name']}"
    return None, None, lname


@app.get("/api/lists/<int:lid>/signoffs")
def sig_list_list(lid):
    c = db()
    need_list(c, lid, owner=True)
    rows = c.execute("SELECT * FROM office_signoffs WHERE list_id=? AND kind='acceptance' ORDER BY id DESC LIMIT 50", (lid,)).fetchall()
    ms = [{"id": r["id"], "title": r["title"]} for r in c.execute("SELECT id, title FROM tasks WHERE list_id=? AND ms=1 AND deleted_at IS NULL ORDER BY sort, id LIMIT 100", (lid,))]
    secs = [{"id": r["id"], "name": r["name"]} for r in c.execute("SELECT id, name FROM sections WHERE list_id=? ORDER BY sort, id", (lid,))]
    return jsonify(signoffs=[sig_public(c, r) for r in rows], milestones=ms, sections=secs, enabled=public_links_on(c))


@app.post("/api/lists/<int:lid>/signoffs")
def sig_list_new(lid):
    """{section_id? | task_id? (a milestone), expires?} -> an acceptance link (the list's owner)."""
    from ..lists.public import need_pub_owner
    c = db()
    need_pub_owner(c, lid)
    if not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    b = body()
    b = b if isinstance(b, dict) else {}
    try:
        sec, tid, title = sig_list_target(c, lid, b)
        exp = sig_expiry(b.get("expires"))
    except BadInput as x:
        return err(str(x))
    write_lock(c, f"office_signoff_list_{int(lid)}")
    oid = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    proto = {"list_id": lid, "section_id": sec, "task_id": tid, "title": title}
    row, tok = sig_create(c, oid, "acceptance", title, sig_list_hash(c, proto), g.user["id"], exp, list_id=lid, section_id=sec, task_id=tid)
    c.commit()
    return jsonify(sig_public(c, row))


@app.post("/api/lists/<int:lid>/signoffs/<int:sid>/revoke")
def sig_list_revoke(lid, sid):
    c = db()
    need_list(c, lid, owner=True)
    r = c.execute("SELECT * FROM office_signoffs WHERE id=? AND list_id=? AND kind='acceptance'", (sid, lid)).fetchone()
    if not r:
        raise Denied(404)
    if r["state"] == "open" and not r["revoked_at"]:
        c.execute("UPDATE office_signoffs SET revoked_at=? WHERE id=?", (iso(now_utc()), sid))
        c.commit()
    return jsonify(sig_public(c, c.execute("SELECT * FROM office_signoffs WHERE id=?", (sid,)).fetchone()))


# ---------------------------------------------------------------- the customer's page
def sig_find(c, token):
    """The signoff row of a token (any state) + its context bound, or None (unknown, revoked, expired while open,
    the quotation changed / no longer sent, the list gone)."""
    if not PUB_TOKEN_RE.fullmatch(token or ""):
        return None
    with system_ctx(c):  # resolve the token (one row) across organisations, then read inside exactly its organisation
        r = c.execute("SELECT * FROM office_signoffs WHERE token_hash=?", (_token_hash(token),)).fetchone()
    if not r or r["revoked_at"]:
        return None
    if r["state"] == "open" and r["expires_at"] and parse_iso(r["expires_at"]) <= now_utc():
        return None
    acx_anon_bind(c, r["org_id"])
    g.user, g.auth_via = PUB_ACTOR, "public"
    return r


def sig_check(c, r):
    """None when an OPEN link still fits what it was made for, else True (= void, the same answer as unknown)."""
    if r["state"] != "open":
        return None
    if r["kind"] == "offer":
        d = c.execute("SELECT status FROM office_docs WHERE id=? AND org_id=?", (r["doc_id"], r["org_id"])).fetchone()
        if not d or d["status"] != "sent" or sig_doc_hash(c, r["org_id"], r["doc_id"])[0] != r["doc_hash"]:
            return True
        return None
    if r["kind"] == "document":  # 2.93.0 A (#1927): the document is finished, not archived, its text unchanged
        from .doctpl import dt_sig_valid
        return None if dt_sig_valid(c, r) else True
    if r["kind"] == "video":  # 2.99.1 A (#1959): the review is there (not in the trash) and has a version
        from ..videos.review import vdr_sig_valid
        return None if vdr_sig_valid(c, r) else True
    lr = c.execute("SELECT l.id FROM lists l JOIN users u ON u.id=l.owner_id WHERE l.id=? AND u.disabled=0", (r["list_id"],)).fetchone()
    if not lr or sig_list_hash(c, r) != r["doc_hash"]:
        return True
    return None


def sig_open(c, token):
    ip = rate_ip()
    if not public_links_on(c):
        return None, pub_gone()
    bad = [("pubbad:" + ip, SIG_BAD_LIMIT)]
    if _rate_blocked(bad):
        return None, pub_limited(_accept_lang())
    r = sig_find(c, token)
    if not r or sig_check(c, r):
        _rate_fail(bad)
        aa_count("security", "publink", ip)
        return None, pub_gone()
    return r, None


def sig_lang(c, r):
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in ("de", "en", "es", "fr", "it", "nl"):
            return code
    return "de"


def sig_form_key(c, r):
    return hmac.new(auth_key(c), f"sig:{r['id']}:{r['token_hash']}".encode(), hashlib.sha256).hexdigest()


def sig_offer_html(c, r, lg, token):
    from .calc import fmt_money
    e = html.escape
    m = sig_doc_hash(c, r["org_id"], r["doc_id"])[1]
    cur, dl = m.get("currency") or "EUR", m.get("lang") or "de"
    co = (m.get("company") or {}).get("name") or ""
    rows = []
    for ln in m.get("lines") or []:
        k = ln.get("kind")
        if k == "heading":
            rows.append(f'<tr class="hd"><td colspan="3">{e(ln.get("title") or "")}</td></tr>')
        elif k == "text":
            rows.append(f'<tr class="tx"><td colspan="3">{e(ln.get("text") or "")}</td></tr>')
        elif k in ("item", "producing", "raw", "discount"):
            q = " ".join(x for x in (ln.get("qty_text") or "", ln.get("unit_text") or "") if x)
            rows.append(f'<tr><td>{e(ln.get("title") or "")}</td><td class="q">{e(q)}</td><td class="m">{e(ln.get("total_text") or "")}</td></tr>')
    t = m.get("totals") or {}
    sums = f'<tr class="sum"><td colspan="2">{e(tr("Net", lg=lg))}</td><td class="m">{e(t.get("net_text") or "")}</td></tr>'
    if t.get("tax_total") is not None and t.get("gross") is not None:
        sums += (f'<tr class="sum"><td colspan="2">{e(tr("VAT", lg=lg))}</td><td class="m">{e(fmt_money(t["tax_total"], dl, cur))}</td></tr>'
                 f'<tr class="sum tot"><td colspan="2">{e(tr("Total", lg=lg))}</td><td class="m">{e(fmt_money(t["gross"], dl, cur))}</td></tr>')
    meta = " · ".join(e(f"{a}: {b}") for a, b in (m.get("meta") or []) if b)
    return (f'<header>{f"<div class=brand><span>{e(co)}</span></div>" if co else ""}<h1>{e(m.get("title") or "")} {e(m.get("number") or "")}</h1>'
            f'<p class="sub">{meta}</p></header>'
            + (f'<p class="intro">{e(m.get("project_title") or "")}</p>' if m.get("project_title") else "")
            + f'<table class="sig">{"".join(rows)}{sums}</table>'
            + f'<p><a class="pdf" href="{SIG_PREFIX}{e(token)}/pdf" download rel="nofollow">{e(tr("Download the quotation (PDF)", lg=lg))}</a></p>')


def sig_list_html(c, r, lg):
    e = html.escape
    items = "".join(f'<li class="t{" done" if t["status"] != 0 else ""}"><span class="chk{" on" if t["status"] != 0 else ""}" aria-hidden="true"></span>'
                    f'<div class="tt"><span class="ttl">{e(t["title"])}</span></div></li>' for t in sig_list_tasks(c, r))
    return (f'<header><h1>{e(r["title"])}</h1><p class="sub">{e(tr("Acceptance requested", lg=lg))}</p></header>'
            f'<ul class="tasks">{items}</ul>')


def sig_page(c, r, token, lg, error=None, code=200):
    e = html.escape
    note = e(tr(SIG_NOTE, lg=lg))
    if r["state"] != "open":
        d = sig_dec(c, r)
        doc = r["kind"] == "document"  # 2.93.0 A (#1927)
        h = (tr("Signed", lg=lg) if doc else tr("Accepted", lg=lg)) if d["state"] == "accepted" else tr("Declined", lg=lg)
        if r["kind"] == "video":  # 2.99.1 A (#1959)
            h = tr("Approved|video", lg=lg) if d["state"] == "accepted" else tr("Changes requested", lg=lg)
        when = d["signed_at"] or ""
        pdf_t = tr("Download the signed document (PDF)", lg=lg) if doc else tr("Download the quotation (PDF)", lg=lg)
        main = (f'<div class="msg"><h1>{e(h)}</h1><p>{e(r["title"])}</p><p>{e(tr("By {0} on {1} (UTC).", d["signer_name"] or "", when[:16].replace("T", " "), lg=lg))}</p>'
                + (f'<p><a class="pdf" href="{SIG_PREFIX}{e(token)}/pdf" download rel="nofollow">{e(pdf_t)}</a></p>'
                   if (r["kind"] == "offer" or (doc and d["state"] == "accepted")) and h6c_sig_pdf_ok(c, r) else "")  # 2.86.0 (N17)
                + f'<p class="sub">{e(tr("Thank you. You can close this page.", lg=lg))}</p></div>')
        return pub_html(h, main, lg)
    vid = r["kind"] == "video"  # 2.99.1 A (#1959)
    if r["kind"] == "document":  # 2.93.0 A (#1927)
        from .doctpl import dt_sig_html
        head = dt_sig_html(c, r, lg, token, SIG_PREFIX)
    elif vid:
        from ..videos.review import vdr_sig_html
        head = vdr_sig_html(c, r, lg, token, SIG_PREFIX)
    else:
        head = sig_offer_html(c, r, lg, token) if r["kind"] == "offer" else sig_list_html(c, r, lg)
    acc = (tr("I accept the quotation", lg=lg) if r["kind"] == "offer" else tr("I sign this document", lg=lg) if r["kind"] == "document"
           else tr("I approve this version of the video", lg=lg) if vid else tr("I confirm the acceptance", lg=lg))
    go = tr("Sign bindingly", lg=lg) if r["kind"] == "document" else tr("Approve|video", lg=lg) if vid else tr("Accept bindingly", lg=lg)
    no = tr("Request changes", lg=lg) if vid else tr("Decline", lg=lg)
    ver = ""
    if vid:
        from ..videos.review import vdr_sig_newest
        ver = f'<input type="hidden" name="v" value="{vdr_sig_newest(c, r)["id"]}">'
    form = (f'<form method="post" action="{SIG_PREFIX}{e(token)}" class="fform sigf">'
            f'<input type="hidden" name="f" value="{sig_form_key(c, r)}">{ver}'
            f'<label for="sg-name">{e(tr("Your name", lg=lg))}</label><input id="sg-name" name="name" maxlength="{NAME_MAX}" autocomplete="name" required>'
            f'<label for="sg-mail">{e(tr("E-mail (optional)", lg=lg))}</label><input id="sg-mail" name="email" type="email" maxlength="{EMAIL_MAX}" autocomplete="email">'
            f'<label class="ok"><input type="checkbox" name="ok" value="1"> {e(acc)}</label>'
            f'<button type="submit" name="do" value="accept">{e(go)}</button>'
            f'<details class="decl"><summary>{e(no)}</summary>'
            f'<label for="sg-why">{e(tr("Reason (optional)", lg=lg))}</label><textarea id="sg-why" name="reason" rows="3" maxlength="{REASON_MAX}"></textarea>'
            f'<button type="submit" name="do" value="decline" class="sec">{e(no)}</button></details>'
            + (f'<p class="err" role="alert">{e(error)}</p>' if error else "")
            + f'</form><p class="signote">{note}</p>')
    resp = pub_html(f"{r['title']} · {APP_NAME}", head + form, lg, code)
    if vid:
        resp.headers["Content-Security-Policy"] = SIG_VIDEO_CSP
    return resp


@app.get("/s/q/<token>")
def sig_page_get(token):
    c = db()
    if hit_limit("sigv:" + rate_ip(), SIG_VIEW_RATE):
        return pub_limited(_accept_lang())
    r, bad = sig_open(c, token)
    if bad:
        return bad
    return sig_page(c, r, token, sig_lang(c, r))


def h6c_sig_pdf_ok(c, r):
    """2.86.0 (N17): after the decision the customer may still fetch the quotation as decided -- until the link's expiry
    (without one: SIG_PDF_KEEP_DAYS after the decision) and only while the document is unchanged. Open links: sig_open."""
    if r["state"] == "open":
        return True
    end = parse_iso(r["expires_at"]) if r["expires_at"] else (parse_iso(r["signed_at"]) + timedelta(days=SIG_PDF_KEEP_DAYS) if r["signed_at"] else None)
    if not end or end <= now_utc():
        return False
    if r["kind"] == "document":  # 2.93.0 A (#1927): the signed document while it is still the one signed
        from .doctpl import dt_hash, dt_sig_row
        d = dt_sig_row(c, r)
        return bool(d) and not d["archived"] and dt_hash(d["body"]) == r["doc_hash"]
    try:
        return sig_doc_hash(c, r["org_id"], r["doc_id"])[0] == r["doc_hash"]
    except Denied:  # the quotation is gone
        return False


@app.get("/s/q/<token>/pdf")
def sig_pdf_get(token):
    from .pdfweb import _file_response, _render, _stored_or_missing, epdf_name
    from .docs import doc_row
    from ..core.orgcrypt import oc_read_file
    c = db()
    if hit_limit("sigv:" + rate_ip(), SIG_VIEW_RATE):
        return pub_limited(_accept_lang())
    r, bad = sig_open(c, token)
    if bad:
        return bad
    if r["kind"] == "document":  # 2.93.0 A (#1927): written from the frozen text (the original, after signing the signed one)
        from .doctpl import dt_disposition, dt_sig_pdf
        x = dt_sig_pdf(c, r) if h6c_sig_pdf_ok(c, r) and r["state"] in ("open", "accepted") else None
        if not x:
            return pub_gone()
        resp = _file_response(x[0], "document.pdf", "application/pdf")
        resp.headers["Content-Disposition"] = dt_disposition(x[1])  # the title cleaned (quotes, line breaks), UTF-8
        resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp
    if r["kind"] != "offer" or not h6c_sig_pdf_ok(c, r):
        return pub_gone()
    d = doc_row(c, r["org_id"], r["doc_id"])
    try:
        p = _stored_or_missing(c, r["org_id"], d, "pdf")
    except Denied:
        return pub_gone()
    data = oc_read_file(c, p) if p else _render(c, r["org_id"], d)[0]
    resp = _file_response(data, epdf_name(d) + ".pdf", "application/pdf")
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _clean_text(v, mx):
    v = (v or "").replace("\r", "")
    v = "".join(ch for ch in v if ch == "\n" or ord(ch) >= 32)
    return v.strip()[:mx]


@app.post("/s/q/<token>")
def sig_decide(token):
    c = db()
    r, bad = sig_open(c, token)
    if bad:
        return bad
    lg, ip = sig_lang(c, r), rate_ip()
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site" or not hmac.compare_digest(request.form.get("f") or "", sig_form_key(c, r)):
        return pub_html(tr("Not allowed", lg=lg), f'<div class="msg"><h1>{html.escape(tr("Not allowed", lg=lg))}</h1></div>', lg, 403)
    if r["state"] != "open":
        return redirect(SIG_PREFIX + token, 303)
    if hit_limit("sigp:" + ip, SIG_POST_RATE) or hit_limit(f"sigl:{r['id']}", SIG_LINK_HOUR, 3600):
        return pub_limited(lg)
    do = request.form.get("do")
    name = " ".join(_clean_text(request.form.get("name"), NAME_MAX).split())
    email = _clean_text(request.form.get("email"), EMAIL_MAX)
    reason = _clean_text(request.form.get("reason"), REASON_MAX) if do == "decline" else ""
    if do not in ("accept", "decline"):
        return sig_page(c, r, token, lg, tr("Invalid data", lg=lg), 400)
    if len(name) < 2:
        return sig_page(c, r, token, lg, tr("Please type your name.", lg=lg), 400)
    if email and ("@" not in email or " " in email):
        return sig_page(c, r, token, lg, tr("Please check the e-mail address.", lg=lg), 400)
    if r["kind"] == "video":  # 2.99.1 A (#1959): the decision names the version that was shown (a newer one: look at it first)
        from ..videos.review import vdr_sig_newest
        nv = vdr_sig_newest(c, r)
        if not nv or str(nv["id"]) != (request.form.get("v") or ""):
            return sig_page(c, r, token, lg, tr("There is a newer version. Please look at it first.", lg=lg), 409)
    if do == "accept" and request.form.get("ok") != "1":
        return sig_page(c, r, token, lg, tr("Please tick the box to sign.", lg=lg) if r["kind"] == "document" else tr("Please tick the box to accept.", lg=lg), 400)
    write_lock(c, f"office_signoff_{int(r['id'])}")  # two decisions at once: the second sees the first
    cur = c.execute("SELECT * FROM office_signoffs WHERE id=?", (r["id"],)).fetchone()
    if cur["state"] != "open" or cur["revoked_at"] or sig_check(c, cur):
        c.rollback()
        return redirect(SIG_PREFIX + token, 303)
    if r["kind"] == "video":  # 2.99.1 (#1959) review L1: a version added meanwhile (its lock) -> the newer one first
        write_lock(c, f"video_review_{int(cur['video_id'])}")
        nv = vdr_sig_newest(c, cur)
        if not nv or str(nv["id"]) != (request.form.get("v") or ""):
            c.rollback()
            return sig_page(c, r, token, lg, tr("There is a newer version. Please look at it first.", lg=lg), 409)
    st = "accepted" if do == "accept" else "declined"
    ts = iso(now_utc())
    ua = (request.headers.get("User-Agent") or "")[:UA_MAX]
    vals = sig_enc(c, r, {"signer_name": name, "signer_email": email or None, "reason": reason or None, "ip": ip, "user_agent": ua})
    c.execute("UPDATE office_signoffs SET state=?, signed_at=?, signer_name=?, signer_email=?, reason=?, ip=?, user_agent=? WHERE id=?",
              (st, ts, vals["signer_name"], vals["signer_email"], vals["reason"], vals["ip"], vals["user_agent"], r["id"]))
    proto = {"signoff": r["id"], "state": st, "name": name, "email": email, "reason": reason, "at": ts, "ip": ip, "user_agent": ua,
             "doc_hash": r["doc_hash"], "signature": "simple electronic signature"}
    if r["kind"] == "offer":
        from .docs import odoc_set_status
        from .ledger import ofx_log
        g.user = None  # the office log: no person (user_id NULL), the customer's name is in the detail
        try:
            ofx_log(c, r["org_id"], LOG_TEXT[st], doc_id=r["doc_id"], detail=proto)
            odoc_set_status(c, r["org_id"], r["doc_id"], st, None)  # the same status change as in the app (purchase, pipeline)
        finally:
            g.user = PUB_ACTOR
    elif r["kind"] == "document":  # 2.93.0 A (#1927): the document signed | declined; the signed PDF is filed by the next admin read
        from .doctpl import dt_sig_decided
        from .ledger import ofx_log
        proto["gen_doc"] = r["gen_doc_id"]
        g.user = None
        try:
            ofx_log(c, r["org_id"], LOG_TEXT[st], target="gen_doc", detail=proto)
            done = dt_sig_decided(c, r, st)
        finally:
            g.user = PUB_ACTOR
        if not done:  # archived meanwhile: nothing recorded, the same answer as a void link
            c.rollback()
            return pub_gone()
    elif r["kind"] == "video":  # 2.99.1 A (#1959): the review's state follows (approved | changes)
        from ..videos.review import vdr_sig_decided
        proto["version"] = {"id": nv["id"], "n": nv["n"], "url": nv["url"]}
        vdr_sig_decided(c, r, st, nv, name, reason, lg)
    elif r["list_id"]:
        proto["tasks"] = [[t["id"], t["title"], t["status"]] for t in sig_list_tasks(c, r)]
        c.execute("INSERT INTO list_activity(list_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)",
                  (r["list_id"], None, "signoff", json.dumps({"state": st, "name": name, "title": r["title"], "signoff": r["id"], "at": ts}, ensure_ascii=False), ts))
    push = sig_notify(c, r, st, name)
    c.commit()
    print("signoff", r["id"], st, flush=True)
    if push:
        threading.Thread(target=push, daemon=True).start()
    return redirect(SIG_PREFIX + token, 303)
