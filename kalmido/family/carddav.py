"""Family: birthdays and anniversaries from CardDAV contacts."""
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from flask import jsonify

from ..core.config import _origin, app
from ..core.i18n import lang, N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc, parse_iso
from ..accounts.session import GATE, me
from ..core.access import Denied, list_role, need_list, WRITE_ROLES
from ..tasks.validation import as_int, DATE_MIN_Y
from ..calendars.subscriptions import (
    _cal_limited, _CAL_LOCK, _dav_href, _dav_responses, _dav_xml, cal_allow, CAL_ERR, cal_err_text, cal_href_ok,
    cal_http, cal_norm_url, CAL_ON, cal_rate, cal_seal, CAL_TICK, cal_unseal, cal_url_hint, CalError, DAV_NS, need_cal,
)
from ..family.family import (
    _jparse, CONTACT_CARDS_MAX, CONTACT_EVERY_MIN, CONTACT_SRCS_MAX, FAM_LEAD_MAX, fam_list, FAM_NAME_MAX, occ_create,
    occ_next, occ_rule,
)


# ---- CardDAV: birthdays + anniversaries from contacts (private per user, like calendar subscriptions)
CARDDAV_NS = "urn:ietf:params:xml:ns:carddav"


def _card_propfind(url, depth, props, auth, allow):
    body = ('<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">'
            f'<d:prop>{props}</d:prop></d:propfind>')
    st, _, data, final = cal_http(url, "PROPFIND", body.encode(), {"Depth": str(depth), "Content-Type": "application/xml; charset=utf-8"},
                                  auth, allow)
    if st != 207:
        raise CalError("not_calendar")
    return final, _dav_responses(_dav_xml(data), final)


def _is_book(props):
    rt = props.get(f"{{{DAV_NS}}}resourcetype")
    return rt is not None and rt.find(f"{{{CARDDAV_NS}}}addressbook") is not None


def carddav_books(url, auth, allow):
    """The address books of a CardDAV account (the URL may be the server, the principal or one address book)."""
    o = _origin(url)
    root = f"{o[0]}://{'[' + o[1] + ']' if ':' in o[1] else o[1]}:{o[2]}" if o else url
    home = cup = None
    for cand in dict.fromkeys((url, root + "/.well-known/carddav")):
        try:
            final, rs = _card_propfind(cand, 0, "<d:resourcetype/><d:current-user-principal/><card:addressbook-home-set/>", auth, allow)
        except CalError as e:
            if e.code in ("auth", "blocked", "tls", "timeout", "too_large"):
                raise
            continue
        if not rs:
            continue
        href, props = rs[0]
        if _is_book(props):
            return [href]
        home = _dav_href(props.get(f"{{{CARDDAV_NS}}}addressbook-home-set"), final)
        cup = _dav_href(props.get(f"{{{DAV_NS}}}current-user-principal"), final)
        if home or cup:
            break
    if not home and cup:
        if not cal_href_ok(url, cup):
            raise CalError("redirect")
        final, rs = _card_propfind(cup, 0, "<card:addressbook-home-set/>", auth, allow)
        home = _dav_href(rs[0][1].get(f"{{{CARDDAV_NS}}}addressbook-home-set"), final) if rs else None
    if not home:
        raise CalError("not_book")
    if not cal_href_ok(url, home):
        raise CalError("redirect")
    final, rs = _card_propfind(home, 1, "<d:resourcetype/>", auth, allow)
    books = [h for h, p in rs if _is_book(p) and cal_href_ok(url, h)]
    if not books:
        raise CalError("not_book")
    return books[:10]


def carddav_cards(book, auth, allow):
    """address-data of every card of an address book (REPORT addressbook-query)."""
    body = ('<?xml version="1.0" encoding="utf-8"?><card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">'
            '<d:prop><d:getetag/><card:address-data/></d:prop></card:addressbook-query>')
    st, _, data, _ = cal_http(book, "REPORT", body.encode(), {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}, auth, allow)
    if st != 207:
        raise CalError("not_book")
    return [el.text for el in _dav_xml(data).iter(f"{{{CARDDAV_NS}}}address-data") if el.text and el.text.strip()][:CONTACT_CARDS_MAX]


def _vdate(v, params):
    """A vCard date -> (month, day, year | None) or None: 19460512, 1946-05-12, --0512, --05-12, 1946-05-12T..., Apple's
    X-APPLE-OMIT-YEAR / the years 1604 and 0000 mean: no year."""
    v = (v or "").strip()
    m = re.match(r"^(\d{4}|--)-?(\d{2})-?(\d{2})", v)
    if not m:
        return None
    mo, dy = int(m.group(2)), int(m.group(3))
    try:
        date(2000, mo, dy)
    except ValueError:
        return None
    y = int(m.group(1)) if m.group(1).isdigit() else None
    if y is not None and ("x-apple-omit-year" in params.lower() or y in (0, 1604) or not DATE_MIN_Y <= y <= local_now().year):
        y = None
    return mo, dy, y


def vcard_occasions(text):
    """[(uid, kind, name, month, day, year)] of the vCards in text (BDAY, ANNIVERSARY, X-ANNIVERSARY, Apple's X-ABDATE with
    the label Anniversary)."""
    out = []
    text = re.sub(r"\r?\n[ \t]", "", str(text or "").replace("\r\n", "\n"))
    for blk in re.findall(r"BEGIN:VCARD(.*?)END:VCARD", text, re.S | re.I):
        props, labels = [], {}
        for ln in blk.split("\n"):
            m = re.match(r"^(?:([\w-]+)\.)?([\w-]+)((?:;[^:]*)?):(.*)$", ln.strip())
            if not m:
                continue
            grp, name, params, val = (m.group(1) or "").lower(), m.group(2).upper(), m.group(3) or "", m.group(4)
            props.append((grp, name, params, val))
            if name == "X-ABLABEL":
                labels[grp] = val
        get = lambda n: next((v for _g, k, _p, v in props if k == n), "")  # noqa: E731
        fn = get("FN").replace("\\,", ",").replace("\\;", ";").strip()
        if not fn:
            parts = get("N").split(";")
            fn = " ".join(x for x in (parts[1] if len(parts) > 1 else "", parts[0]) if x).strip()
        fn = re.sub(r"\s+", " ", fn)[:FAM_NAME_MAX]
        uid = get("UID").strip()[:200] or "fn:" + hashlib.sha1(fn.encode(), usedforsecurity=False).hexdigest()[:16]
        if not fn:
            continue
        seen = set()
        for grp, name, params, val in props:
            kind = "birthday" if name == "BDAY" else "anniversary" if name in ("ANNIVERSARY", "X-ANNIVERSARY") else \
                "anniversary" if name == "X-ABDATE" and "anniversary" in labels.get(grp, "").lower() else None
            if not kind or kind in seen:
                continue
            d = _vdate(val, params)
            if d:
                seen.add(kind)
                out.append((uid, kind, fn, *d))
    return out


CONTACT_ERR = dict(CAL_ERR, not_book=N_("No address book found at this address"),
                   no_list=N_("The list for the birthdays is gone: choose another one"))


def contact_err_text(stored):
    code, _, detail = (stored or "error").partition(":")
    if code in ("not_book", "not_calendar"):
        return tr(CONTACT_ERR["not_book"])
    if code == "no_list":
        return tr(CONTACT_ERR["no_list"])
    return cal_err_text(stored)


def contact_public(c, r):
    return {"id": r["id"], "name": r["name"], "url_hint": r["url_hint"], "username": r["username"], "list_id": r["list_id"],
            "lead_days": r["lead"], "status": r["status"], "error": r["error"], "error_text": contact_err_text(r["error"]) if r["error"] else "",
            "synced_at": r["synced_at"], "count": r["count"]}


_CONTACT_BUSY = set()


def contacts_sync(c, sid):
    """Reads the address books of source sid; a new birthday / anniversary becomes a yearly task, a changed date or name
    updates its task (the title only while it is still the generated one). Removed contacts leave their tasks alone."""
    with _CAL_LOCK:
        if sid in _CONTACT_BUSY:
            return False
        _CONTACT_BUSY.add(sid)
    try:
        s = c.execute("SELECT * FROM contact_srcs WHERE id=?", (sid,)).fetchone()
        if not s:
            return False
        c.execute("UPDATE contact_srcs SET tried_at=? WHERE id=?", (iso(now_utc()), sid))
        c.commit()
        upd = {}
        try:
            allow = cal_allow(c)
            url = cal_unseal(c, s["user_id"], s["url"])
            auth = (s["username"], cal_unseal(c, s["user_id"], s["password"]))
            occs = []
            for b in carddav_books(url, auth, allow):
                for card in carddav_cards(b, auth, allow):
                    occs += [(*o, b) for o in vcard_occasions(card)]
            lid = s["list_id"]
            if not lid or list_role(c, lid, s["user_id"]) not in WRITE_ROLES:
                lid = fam_list(c, s["user_id"], "birthdays", create=False)
                if not lid:
                    raise CalError("no_list")
                c.execute("UPDATE contact_srcs SET list_id=? WHERE id=?", (lid, sid))
            lg = lang(c, s["user_id"])
            n = 0
            for uid_, kind, name, mo, dy, y, book in occs[:CONTACT_CARDS_MAX]:
                book_s = cal_seal(c, s["user_id"], book)
                dig = f"{name}|{mo}|{dy}|{y}"
                ln = c.execute("SELECT * FROM contact_links WHERE src_id=? AND uid=? AND kind=?", (sid, uid_, kind)).fetchone()
                t = c.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (ln["task_id"],)).fetchone() if ln and ln["task_id"] else None
                n += 1
                if t:
                    if ln["digest"] == dig:
                        continue
                    f = _jparse(t["fam"]) or {}
                    old_title = tr("Birthday: {0}", f.get("name", ""), lg=lg) if kind == "birthday" else tr("Anniversary: {0}", f.get("name", ""), lg=lg)
                    f.update(name=name, **({"year": y} if y else {}))
                    if not y:
                        f.pop("year", None)
                    sets = {"fam": json.dumps(f, ensure_ascii=False, separators=(",", ":")), "updated_at": iso(now_utc())}
                    if t["title"] == old_title:
                        sets["title"] = tr("Birthday: {0}", name, lg=lg) if kind == "birthday" else tr("Anniversary: {0}", name, lg=lg)
                    if not t["due"] or (date.fromisoformat(t["due"]).month, date.fromisoformat(t["due"]).day) != (mo, dy):
                        sets.update(due=occ_next(mo, dy).isoformat(), repeat=occ_rule(mo, dy), reminded="[]")
                    c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), t["id"]])
                    c.execute("UPDATE contact_links SET digest=?, book=? WHERE src_id=? AND uid=? AND kind=?", (dig, book_s, sid, uid_, kind))
                    continue
                if ln:  # its task was deleted by hand: not created again
                    if not ln["book"]:
                        c.execute("UPDATE contact_links SET book=? WHERE src_id=? AND uid=? AND kind=?", (book_s, sid, uid_, kind))
                    continue
                tid = occ_create(c, s["user_id"], {"name": name, "kind": kind, "date": f"--{mo:02d}-{dy:02d}", "year": y,
                                                   "lead_days": s["lead"], "list_id": lid, "src": f"carddav:{sid}"}, check=False)
                # the vCard UID also goes into the task itself (fam.card), so the link survives removing the source
                f = _jparse(c.execute("SELECT fam FROM tasks WHERE id=?", (tid,)).fetchone()[0]) or {}
                f["card"] = uid_[:200]
                c.execute("UPDATE tasks SET fam=? WHERE id=?", (json.dumps(f, ensure_ascii=False, separators=(",", ":")), tid))
                c.execute("INSERT OR REPLACE INTO contact_links(src_id,uid,kind,task_id,digest,book) VALUES(?,?,?,?,?,?)", (sid, uid_, kind, tid, dig, book_s))
            upd.update(status="ok", error="", fails=0, count=n, synced_at=iso(now_utc()))
            bump(c)
        except Exception as e:  # noqa: BLE001
            ce = e if isinstance(e, CalError) else CalError("error", type(e).__name__)
            if not isinstance(e, CalError):
                print("contacts sync: source", sid, "failed:", type(e).__name__, e, flush=True)
            upd.update(status="error", error=ce.stored(), fails=s["fails"] + 1)
        c.execute(f"UPDATE contact_srcs SET {', '.join(k + '=?' for k in upd)} WHERE id=?", (*upd.values(), sid))
        c.commit()
        return True
    finally:
        with _CAL_LOCK:
            _CONTACT_BUSY.discard(sid)


def contacts_due(c):
    """cal_loop: the address books whose daily sync is due."""
    now = now_utc()
    for r in c.execute("""SELECT s.id, s.tried_at FROM contact_srcs s JOIN users u ON u.id=s.user_id WHERE u.disabled=0""").fetchall():
        if not r["tried_at"] or (now - parse_iso(r["tried_at"])).total_seconds() >= CONTACT_EVERY_MIN * CAL_TICK:
            with GATE.bg():
                contacts_sync(c, r["id"])


def need_contact(c, sid):
    r = c.execute("SELECT * FROM contact_srcs WHERE id=? AND user_id=?", (sid, me())).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.get("/api/family/contacts")
def family_contacts():
    c, uid = db(), me()
    return jsonify(enabled=CAL_ON, sources=[contact_public(c, r) for r in c.execute("SELECT * FROM contact_srcs WHERE user_id=? ORDER BY id", (uid,))])


@app.post("/api/family/contacts")
def family_contacts_add():
    """{url, username, password, name?, list_id?, lead_days? (7)} -- an address book (CardDAV) whose birthdays and
    anniversaries become yearly tasks; read at once (a source that fails is not kept), then once a day."""
    need_cal()
    c, uid, b = db(), me(), body()
    url = cal_norm_url(b.get("url"))
    user, pw = b.get("username"), b.get("password")
    if not url or not isinstance(user, str) or not isinstance(pw, str) or not user.strip() or not pw or len(user) > 200 or len(pw) > 500:
        return err(tr("Server address, username and password are needed"))
    if c.execute("SELECT COUNT(*) FROM contact_srcs WHERE user_id=?", (uid,)).fetchone()[0] >= CONTACT_SRCS_MAX:
        return err(tr("At most {0} address books", CONTACT_SRCS_MAX), 409)
    lid = b.get("list_id")
    if lid not in (None, ""):
        lid = as_int(lid, "list_id", 1)
        need_list(c, lid)
    else:
        lid = fam_list(c, uid, "birthdays")
    lead = as_int(b.get("lead_days", 7), "lead_days", 0, FAM_LEAD_MAX)
    name = b.get("name") if isinstance(b.get("name"), str) and b["name"].strip() else (urllib.parse.urlsplit(url).hostname or "CardDAV")
    if not cal_rate(uid):
        return _cal_limited()
    sid = c.execute("""INSERT INTO contact_srcs(user_id,name,url,url_hint,username,password,list_id,lead,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""", (uid, name.strip()[:100], cal_seal(c, uid, url), cal_url_hint(url), user.strip(),
                                                     cal_seal(c, uid, pw), lid, lead, iso(now_utc()))).lastrowid
    c.commit()
    contacts_sync(c, sid)
    r = c.execute("SELECT * FROM contact_srcs WHERE id=?", (sid,)).fetchone()
    if r["status"] != "ok":
        e = contact_err_text(r["error"])
        c.execute("DELETE FROM contact_srcs WHERE id=?", (sid,))
        c.commit()
        return jsonify(error=e, code=r["error"].split(":", 1)[0]), 400
    return jsonify(contact_public(c, r)), 201


@app.patch("/api/family/contacts/<int:sid>")
def family_contacts_edit(sid):
    """{name?, list_id?, lead_days?, username?, password?}"""
    c, b = db(), body()
    r = need_contact(c, sid)
    upd = {}
    if "name" in b:
        if not isinstance(b["name"], str) or not b["name"].strip():
            return err(tr("Name missing"))
        upd["name"] = b["name"].strip()[:100]
    if "list_id" in b:
        lid = as_int(b["list_id"], "list_id", 1) if b["list_id"] not in (None, "") else None
        if lid:
            need_list(c, lid)
        upd["list_id"] = lid
    if "lead_days" in b:
        upd["lead"] = as_int(b["lead_days"], "lead_days", 0, FAM_LEAD_MAX)
    if "username" in b:
        if not isinstance(b["username"], str) or not b["username"].strip() or len(b["username"]) > 200:
            return err(tr("Invalid value: {0}", "username"))
        upd["username"] = b["username"].strip()
    if b.get("password"):
        if not isinstance(b["password"], str) or len(b["password"]) > 500:
            return err(tr("Invalid value: {0}", "password"))
        upd["password"] = cal_seal(c, r["user_id"], b["password"])
    if upd:
        c.execute(f"UPDATE contact_srcs SET {', '.join(k + '=?' for k in upd)} WHERE id=?", (*upd.values(), sid))
        c.commit()
    return jsonify(contact_public(c, need_contact(c, sid)))


@app.delete("/api/family/contacts/<int:sid>")
def family_contacts_delete(sid):
    """Removes the address book; the birthdays it created stay (they are your tasks now)."""
    c = db()
    need_contact(c, sid)
    c.execute("DELETE FROM contact_srcs WHERE id=?", (sid,))
    c.commit()
    return jsonify(ok=True)


@app.post("/api/family/contacts/<int:sid>/sync")
def family_contacts_sync(sid):
    need_cal()
    c = db()
    need_contact(c, sid)
    if not cal_rate(me(), ("contacts", sid)):
        return _cal_limited()
    contacts_sync(c, sid)
    return jsonify(contact_public(c, need_contact(c, sid)))
