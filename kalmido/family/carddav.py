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
from ..core.pg import insert_id
from ..core.i18n import lang, N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc, parse_iso
from ..accounts.session import GATE, me
from ..core.access import Denied, list_role, need_list, WRITE_ROLES
from ..tasks.validation import as_int, DATE_MIN_Y
from ..calendars.subscriptions import (
    _cal_limited, _CAL_LOCK, _dav_href, _dav_responses, _dav_xml, cal_allow, CAL_ERR, cal_err_text, cal_href_ok,
    cal_http, cal_norm_url, CAL_ON, cal_rate, cal_seal, CAL_TICK, cal_unseal, cal_url_hint, CalError, DAV_NS, need_cal, pgb_heal,
)
from ..family.family import (
    _jparse, CONTACT_CARDS_MAX, CONTACT_EVERY_MIN, CONTACT_SRCS_MAX, FAM_LEAD_MAX, FAM_NAME_MAX, FAM_OCC, occ_create, pm_fam_target,
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


def carddav_cards(book, auth, allow, refs=False):
    """address-data of every card of an address book (REPORT addressbook-query); refs: [(href, etag, address-data)]."""
    body = ('<?xml version="1.0" encoding="utf-8"?><card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">'
            '<d:prop><d:getetag/><card:address-data/></d:prop></card:addressbook-query>')
    st, _, data, _ = cal_http(book, "REPORT", body.encode(), {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}, auth, allow)
    if st != 207:
        raise CalError("not_book")
    if refs:  # 2.140.0 D (#2137): where every card lives, for writing a date back
        out = []
        for href, props in _dav_responses(_dav_xml(data), book):
            el = props.get(f"{{{CARDDAV_NS}}}address-data")
            if el is not None and el.text and el.text.strip():
                out.append((href, (props.get(f"{{{DAV_NS}}}getetag").text or "").strip() if props.get(f"{{{DAV_NS}}}getetag") is not None else "",
                            el.text))
        return out[:CONTACT_CARDS_MAX]
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


# ---- 2.140.0 D (#2137): write a changed birthday / anniversary back into its vCard (per source "writeback", off by default).
# Only what the owner set in the family section of the task (the date field, the year) is noted (contact_links.want) and
# written by the next sync: GET the card (the bytes as they are), change only the value of that one date property in the
# style it had (basic / extended, a year-less --MMDD, Apple's 1604 + X-APPLE-OMIT-YEAR), check that every other date of the
# card reads the same as before, PUT it with If-Match (the ETag of that GET). 412 / a card changed since the last read =
# changed elsewhere: nothing is overwritten, the task takes the address book's date. A book whose privilege set has no
# write right or that answers 403 (a mirror, e.g. Kalmido's own copied books, #2378) is never written (wb_ro). Snoozing
# or moving the task, deleting it and removing a year write nothing; a contact without that date gets none.
CONTACT_WB_MAX = 50  # writes per source and sync (the rest waits for the next one)
_VDATE_RE = re.compile(r"^(\d{4}|--)(-?)(\d{2})(-?)(\d{2})")
_VLINE_RE = re.compile(r"^(?:([\w-]+)\.)?([\w-]+)((?:;[^:]*)?):(.*)$")


def _occ_kind(grp, name, labels):
    return "birthday" if name == "BDAY" else "anniversary" if name in ("ANNIVERSARY", "X-ANNIVERSARY") else \
        "anniversary" if name == "X-ABDATE" and "anniversary" in labels.get(grp, "").lower() else None


def _vdate_value(old, params, mo, dy, y):
    """The new date value in the style of the old one -> (value, params); y None keeps the old year part as it is."""
    m = _VDATE_RE.match(old)
    yr, s1, _m, s2, _d = m.groups()
    if y is not None and not (yr.isdigit() and int(yr) == y):
        if yr == "--":
            s1 = s2  # --MM-DD -> YYYY-MM-DD, --MMDD -> YYYYMMDD
        yr = f"{y:04d}"
        params = re.sub(r";X-APPLE-OMIT-YEAR=[^;:]*", "", params, flags=re.I)
    return f"{yr}{s1}{mo:02d}{s2}{dy:02d}{old[m.end():]}", params


def _fold(line):
    """A content line folded at 75 octets (RFC 6350 3.2): [first, ' rest', ...]."""
    out, cur, n = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if n + b > 75:
            out.append(cur)
            cur, n = " ", 1
        cur, n = cur + ch, n + b
    return out + [cur]


def vcard_set_date(text, uid, kind, mo, dy, y=None):
    """text with the date of (uid, kind) set to month / day (and year y, None = keep); every other byte stays (line ends,
    folding, other properties). None when the card or the date is not found, or the result would read differently."""
    parts = re.split(r"(\r\n|\n)", text)
    phys = [[parts[i], parts[i + 1] if i + 1 < len(parts) else ""] for i in range(0, len(parts), 2)]
    logical = []
    for i, (ln, _e) in enumerate(phys):
        if ln[:1] in (" ", "\t") and logical:
            logical[-1][1] = i + 1
        else:
            logical.append([i, i + 1])
    unf = lambda a, b: "".join(phys[k][0] if k == a else phys[k][0][1:] for k in range(a, b))  # noqa: E731
    blk = None
    for a, b in logical:
        word = unf(a, b).strip().upper()
        if word == "BEGIN:VCARD":
            blk = []
        elif word == "END:VCARD" and blk is not None:
            if any(o[0] == uid and o[1] == kind for o in vcard_occasions("BEGIN:VCARD\n" + "\n".join(unf(x, y_) for x, y_ in blk) + "\nEND:VCARD")):
                break
            blk = None
        elif blk is not None:
            blk.append((a, b))
    else:
        return None
    if blk is None:
        return None
    props, labels = [], {}
    for a, b in blk:
        m = _VLINE_RE.match(unf(a, b).strip())
        if m:
            props.append((a, b, (m.group(1) or "").lower(), m.group(2).upper(), m.group(3) or "", m.group(4)))
            if m.group(2).upper() == "X-ABLABEL":
                labels[(m.group(1) or "").lower()] = m.group(4)
    for a, b, grp, name, params, val in props:
        if _occ_kind(grp, name, labels) == kind and _vdate(val, params):
            break
    else:
        return None
    line = unf(a, b)
    cut = line.index(":")
    head, val = line[:cut], line[cut + 1:]
    lead = len(val) - len(val.lstrip())
    new_val, new_params = _vdate_value(val[lead:], params, mo, dy, y)
    if params != new_params:
        head = head[:len(head) - len(params)] + new_params if head.endswith(params) else head
    nl = f"{head}:{val[:lead]}{new_val}"
    eol, last = phys[a][1], phys[b - 1][1]
    lines = [nl] if b - a == 1 else _fold(nl)
    phys[a:b] = [[x, eol] for x in lines[:-1]] + [[lines[-1], last]]
    out = "".join(x + e for x, e in phys)
    before, after = vcard_occasions(text), vcard_occasions(out)
    want = [o if (o[0], o[1]) != (uid, kind) else (*o[:3], mo, dy, y if y is not None else o[5]) for o in before]
    return out if after == want else None


def _wb_ro(book, auth, allow):
    """True when the address book's privilege set grants no write right (Kalmido's mirrored books: read only), False with
    one; None when the server does not tell (it is tried, a 403 then marks it and that mark stays)."""
    _, rs = _card_propfind(book, 0, "<d:current-user-privilege-set/>", auth, allow)
    ps = rs[0][1].get(f"{{{DAV_NS}}}current-user-privilege-set") if rs else None
    if ps is None:
        return None
    names = {el.tag.rsplit("}", 1)[-1] for p in ps.findall(f"{{{DAV_NS}}}privilege") for el in p}
    return not names & {"all", "write", "write-content"}


def _bhash(book):
    return hashlib.sha256(book.encode()).hexdigest()[:16]


class WbConflict(Exception):
    pass


def _wb_write(href, book, auth, allow, uid, kind, mo, dy, y, dig_was):
    """One write: -> the new card text. WbConflict when the card reads differently from the last sync or the server
    answers 412; CalError on everything else ('weak_etag', 'parse', HTTP)."""
    from ..calendars.davwrite import cdw_inside
    if not cdw_inside(book, href):
        raise CalError("redirect")
    st, hd, data, final = cal_http(href, "GET", None, {"Accept": "text/vcard, text/x-vcard, */*;q=0.5"}, auth, allow)
    if st != 200 or final != href:
        raise CalError("http", st)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise CalError("parse") from None
    cur = next((o for o in vcard_occasions(text) if (o[0], o[1]) == (uid, kind)), None)
    if not cur or f"{cur[2]}|{cur[3]}|{cur[4]}|{cur[5]}" != dig_was:
        raise WbConflict(text)
    etag = (hd.get("ETag") or "").strip() if hd else ""
    if not etag or etag.startswith("W/"):
        raise CalError("weak_etag")
    new = vcard_set_date(text, uid, kind, mo, dy, y)
    if new is None:
        raise CalError("parse")
    if new == text:
        return text
    try:
        st, _, _, _ = cal_http(href, "PUT", new.encode("utf-8"), {"Content-Type": "text/vcard; charset=utf-8", "If-Match": etag}, auth, allow)
    except CalError as e:
        if e.code == "http" and e.detail == "412":  # changed meanwhile: read it again, the task takes its date
            try:
                st, _, data, _ = cal_http(href, "GET", None, {"Accept": "text/vcard, text/x-vcard, */*;q=0.5"}, auth, allow)
                raise WbConflict(data.decode("utf-8") if st == 200 else None) from None
            except (CalError, UnicodeDecodeError):
                raise WbConflict(None) from None
        raise
    if st not in (200, 201, 204):
        raise CalError("http", st)
    return new


def _occ_to_task(c, t, sid, uid_, kind, name, mo, dy, y, lg):
    """The task takes a date / name of the address book (the title only while it is still the generated one)."""
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


WB_ERR = {"conflict": N_("A date was changed in the address book at the same time: Kalmido took the date of the address book"),
          "read_only": N_("This address book cannot be changed (read only or a mirror): changes stay in Kalmido"),
          "weak_etag": N_("This address book server sends no reliable version tags: Kalmido does not write there"),
          "parse": N_("A contact could not be changed safely: nothing was written"),
          "failed": N_("Writing back failed: {0}")}


def wb_err_text(stored):
    code = (stored or "").partition(":")[0]
    if code in ("conflict", "read_only", "weak_etag", "parse"):
        return tr(WB_ERR[code])
    return tr(WB_ERR["failed"], contact_err_text(stored))


def contacts_writeback(c, s, auth, allow, todo, ro, lg):
    """contacts_sync, outside a transaction: todo = [(link row, task row, href, book, (name, mo, dy, y) of the card)].
    -> {href: new card text} of the cards written (for the mirror)."""
    done, err_ = {}, ""
    for ln, t, href, book, (name, mo, dy, y) in todo[:CONTACT_WB_MAX]:
        w = _jparse(ln["want"]) or {}
        nmo, ndy = (w["mo"], w["dy"]) if w.get("mo") and w.get("dy") else (mo, dy)
        ny = w.get("y") or y
        keep = False
        try:
            if _bhash(book) in ro:
                raise CalError("auth", 403)
            if (nmo, ndy, ny) == (mo, dy, y):
                new = None
            else:
                new = _wb_write(href, book, auth, allow, ln["uid"], ln["kind"], nmo, ndy, ny if ny != y else None, f"{name}|{mo}|{dy}|{y}")
                done[href] = new
                o = next(o for o in vcard_occasions(new) if (o[0], o[1]) == (ln["uid"], ln["kind"]))
                c.execute("UPDATE contact_links SET digest=? WHERE src_id=? AND uid=? AND kind=?", (f"{o[2]}|{o[3]}|{o[4]}|{o[5]}", s["id"], ln["uid"], ln["kind"]))
        except WbConflict as e:
            err_ = "conflict"
            fresh = next((o for o in vcard_occasions(e.args[0]) if (o[0], o[1]) == (ln["uid"], ln["kind"])), None) if e.args[0] else None
            tt = c.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (t["id"],)).fetchone()
            if fresh and tt:
                _occ_to_task(c, tt, s["id"], ln["uid"], ln["kind"], *fresh[2:6], lg)
                c.execute("UPDATE contact_links SET digest=? WHERE src_id=? AND uid=? AND kind=?",
                          (f"{fresh[2]}|{fresh[3]}|{fresh[4]}|{fresh[5]}", s["id"], ln["uid"], ln["kind"]))
            else:  # the next sync gives the task the address book's date
                c.execute("UPDATE contact_links SET digest='' WHERE src_id=? AND uid=? AND kind=?", (s["id"], ln["uid"], ln["kind"]))
        except CalError as e:
            if e.code in ("network", "timeout") or (e.code == "http" and e.detail[:1] == "5"):
                keep = True  # tried again at the next sync
                err_ = err_ or e.stored()
            elif e.code == "auth" and e.detail == "403":
                ro.add(_bhash(book))
                err_ = "read_only"
            else:
                err_ = e.code if e.code in ("weak_etag", "parse") else e.stored()
        except Exception as e:  # noqa: BLE001  (one card never stops the sync)
            print("contacts write-back: source", s["id"], "failed:", type(e).__name__, flush=True)
            err_ = "parse"
        if not keep:
            c.execute("UPDATE contact_links SET want='' WHERE src_id=? AND uid=? AND kind=?", (s["id"], ln["uid"], ln["kind"]))
        c.commit()
    c.execute("UPDATE contact_srcs SET wb_err=?, wb_ro=? WHERE id=?", (err_, json.dumps(sorted(ro)), s["id"]))
    c.commit()
    return done


def cdv_wb_note(c, tid, cur, b):
    """apply_update after a change of a task: a birthday / anniversary from an address book with write-back on, changed by
    the source's owner in the family section (the date field sends _act occ_date, the year field the fam) -> noted for the
    next sync, which is asked for at once. Snoozing or moving the task (only its due date) writes nothing."""
    f_old = _jparse(cur["fam"]) or {}
    if f_old.get("kind") not in FAM_OCC:
        return
    t = c.execute("SELECT due, fam FROM tasks WHERE id=?", (tid,)).fetchone()
    f_new = _jparse(t["fam"]) if t else None
    if not f_new or f_new.get("kind") != f_old.get("kind"):
        return
    want = {}
    if b.get("_act") == "occ_date" and t["due"] and t["due"] != cur["due"]:
        d = date.fromisoformat(t["due"])
        want.update(mo=d.month, dy=d.day)
        c.execute("UPDATE tasks SET due=?, repeat=?, reminded='[]' WHERE id=?", (occ_next(d.month, d.day).isoformat(), occ_rule(d.month, d.day), tid))
    if f_new.get("year") and f_new.get("year") != f_old.get("year"):
        want["y"] = f_new["year"]
    if not want:
        return
    try:
        uid = me()
    except Exception:  # noqa: BLE001  (no request: a rule / background change writes nothing)
        return
    for r in c.execute("""SELECT l.src_id, l.uid, l.kind, l.want FROM contact_links l JOIN contact_srcs s ON s.id=l.src_id
                          WHERE l.task_id=? AND s.writeback=1 AND s.user_id=?""", (tid, uid)).fetchall():
        w = {**(_jparse(r["want"]) or {}), **want}
        c.execute("UPDATE contact_links SET want=? WHERE src_id=? AND uid=? AND kind=?", (json.dumps(w), r["src_id"], r["uid"], r["kind"]))
        c.execute("UPDATE contact_srcs SET tried_at=NULL WHERE id=?", (r["src_id"],))


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
            "synced_at": r["synced_at"], "count": r["count"], **wb_public(r)}


def wb_public(r):
    """2.140.0 D (#2137): writeback = on / off; writeback_avail = yes | some (a few books are mirrors) | no (every book read
    only: no switch, a hint) | unknown (not read yet); writeback_error = the last problem of writing back."""
    ro = len(_jparse(r["wb_ro"]) or [])
    avail = "unknown" if not r["wb_books"] else "no" if ro >= r["wb_books"] else "some" if ro else "yes"
    return {"writeback": bool(r["writeback"]), "writeback_avail": avail,
            "writeback_error": wb_err_text(r["wb_err"]) if r["wb_err"] and r["writeback"] else ""}


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
            c.commit()  # 2.37.0 (#1150): no open transaction while the address book server is asked (snapshot, pool)
            occs, cards, hrefs, ro = [], [], [], set(_jparse(s["wb_ro"]) or [])
            books = carddav_books(url, auth, allow)
            for b in books:
                try:  # 2.140.0 D (#2137): a book without write right (a mirror) is never written
                    w = _wb_ro(b, auth, allow)
                    if w is not None:
                        (ro.add if w else ro.discard)(_bhash(b))
                except CalError:
                    pass
                for href, _etag, card in carddav_cards(b, auth, allow, refs=True):
                    occs += [(*o, b, href) for o in vcard_occasions(card)]
                    cards.append(card)
                    hrefs.append(href)
            c.execute("UPDATE contact_srcs SET wb_ro=?, wb_books=? WHERE id=?", (json.dumps(sorted(ro & {_bhash(b) for b in books})), len(books), sid))
            lid = s["list_id"]
            if not lid or list_role(c, lid, s["user_id"]) not in WRITE_ROLES:
                lid = pm_fam_target(c, s["user_id"], "birthdays", create=False)[0]  # 2.46.1 (#1615): or the list "Family"
                if not lid:
                    raise CalError("no_list")
                c.execute("UPDATE contact_srcs SET list_id=? WHERE id=?", (lid, sid))
            from ..collab.liste2e import le2a_gen_locked
            if le2a_gen_locked(c, lid):  # 2.64.1 review (M3): no plain birthday titles in a list with the lock
                raise CalError("no_list")
            lg = lang(c, s["user_id"])
            n, todo = 0, []
            for uid_, kind, name, mo, dy, y, book, href in occs[:CONTACT_CARDS_MAX]:
                book_s = cal_seal(c, s["user_id"], book)
                dig = f"{name}|{mo}|{dy}|{y}"
                ln = c.execute("SELECT * FROM contact_links WHERE src_id=? AND uid=? AND kind=?", (sid, uid_, kind)).fetchone()
                t = c.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (ln["task_id"],)).fetchone() if ln and ln["task_id"] else None
                n += 1
                if t:
                    if ln["digest"] == dig:
                        if ln["want"] and s["writeback"]:  # 2.140.0 D (#2137): set in Kalmido, the card unchanged since
                            todo.append((ln, t, href, book, (name, mo, dy, y)))
                        continue
                    _occ_to_task(c, t, sid, uid_, kind, name, mo, dy, y, lg)
                    # 2.140.0 D (#2137): changed in the address book meanwhile = its date wins over one set in Kalmido
                    c.execute("UPDATE contact_links SET digest=?, book=?, want='' WHERE src_id=? AND uid=? AND kind=?", (dig, book_s, sid, uid_, kind))
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
                c.execute("INSERT INTO contact_links(src_id,uid,kind,task_id,digest,book) VALUES(?,?,?,?,?,?) ON CONFLICT (src_id,uid,kind) DO UPDATE SET task_id=excluded.task_id, digest=excluded.digest, book=excluded.book", (sid, uid_, kind, tid, dig, book_s))
            if todo:  # 2.140.0 D (#2137): the dates set in Kalmido go into the vCards (no transaction open meanwhile)
                c.commit()
                done = contacts_writeback(c, s, auth, allow, todo, ro, lg)
                if done:
                    cards = [done.get(h, x) for h, x in zip(hrefs, cards)]
            try:  # 2.21.0 (#658): the cards also land in an address book of their own (module Contacts on)
                from ..contacts.model import mirror_source
                with c.savepoint():  # 2.37.0 (#1150): a failing statement here leaves the birthdays above intact
                    mirror_source(c, sid, cards[:CONTACT_CARDS_MAX])
            except Exception as e:  # noqa: BLE001  (the birthdays above stay, whatever happens here)
                print("contacts sync: mirroring source", sid, "failed:", type(e).__name__, e, flush=True)
            upd.update(status="ok", error="", fails=0, count=n, synced_at=iso(now_utc()))
            bump(c)
        except Exception as e:  # noqa: BLE001
            ce = e if isinstance(e, CalError) else CalError("error", type(e).__name__)
            if not isinstance(e, CalError):
                print("contacts sync: source", sid, "failed:", type(e).__name__, e, flush=True)
            pgb_heal(c)
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
        from ..collab.liste2e import le2a_gen_refuse
        le2a_gen_refuse(c, lid)  # 2.64.1 review (M3)
    else:
        lid = pm_fam_target(c, uid, "birthdays")[0]  # 2.46.1 (#1615): an old list Birthdays, else the list "Family"
    lead = as_int(b.get("lead_days", 7), "lead_days", 0, FAM_LEAD_MAX)
    name = b.get("name") if isinstance(b.get("name"), str) and b["name"].strip() else (urllib.parse.urlsplit(url).hostname or "CardDAV")
    if not cal_rate(uid):
        return _cal_limited()
    sid = insert_id(c, """INSERT INTO contact_srcs(user_id,name,url,url_hint,username,password,list_id,lead,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""", (uid, name.strip()[:100], cal_seal(c, uid, url), cal_url_hint(url), user.strip(),
                                                     cal_seal(c, uid, pw), lid, lead, iso(now_utc())))
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
    """{name?, list_id?, lead_days?, username?, password?, writeback?}"""
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
            from ..collab.liste2e import le2a_gen_refuse
            le2a_gen_refuse(c, lid)  # 2.64.1 review (M3)
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
    if "writeback" in b:  # 2.140.0 D (#2137): changed dates back into the address book (never into a read-only mirror)
        if not isinstance(b["writeback"], bool):
            return err(tr("Invalid value: {0}", "writeback"))
        if b["writeback"] and wb_public(r)["writeback_avail"] == "no":
            return err(tr(WB_ERR["read_only"]), 409)
        upd.update(writeback=int(b["writeback"]), wb_err="")
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
