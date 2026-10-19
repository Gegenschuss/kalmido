"""2.98.0 A (#1953): scheduling polls -- several proposed times, people vote through a public link (yes / maybe / no),
the winning time becomes an event with one click. Built by part A.

A poll belongs to one person (sched_polls.user_id) in the private space (org_id NULL) or in one of their organisations:
every member of that organisation reads it, only its owner or an admin of the organisation changes it (like bookmarks);
the voters' e-mail addresses only those who may change it. People only (module "events"): agents and API tokens get 403
(no agent API in 2.98, parity_test SESSION_ONLY). The link /s/v/<token> (below the public links' prefix /s/, so a login
proxy that lets the public links through lets it through; 144 random bits, stored sealed so it can be copied again, looked
up by its SHA-256 like forms) works without an account: a name, yes / maybe / no per time, optionally an
address; the own vote can be changed with the edit key (a cookie on the device + the link on the thank-you page, stored as
SHA-256 only). The page shows only the poll, its times and -- unless the owner turned it off -- the voters' names with their
answers; never addresses, never other events or calendars of the owner. Expired, revoked, deleted or unknown = the same 404
page. Spam without an outside service: the signed page stamp of the forms (frm_stamp, once only), a honeypot, limits per
address / poll / hour, a cap of votes per poll and per address. "Choose this time" makes ONE event in a calendar the person
may write (a Kalmido calendar of the same workspace or a private one -- served over CalDAV to the phones -- or a CalDAV
subscription with "Allow writing", calendars/davwrite.py; never Google, #1128); the voters without an account are named in
its description; an invitation mail goes to the voters with an address only when the person ticks it (off by default). The
poll is then closed and its link shows only the chosen time. Undo: delete -> restore, choose -> reopen (the event goes to
the trash). Later: the time logic (zones, wall clock) could be shared with the booking page (#1929, calendars/apptbook.py).
"""
import hashlib
import hmac
import html
import json
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone

from flask import g, has_request_context, jsonify, make_response, request

from ..core.config import app, APP_NAME, PUBLIC_URL, TZ
from ..core.pg import insert_id, system_ctx
from ..core.i18n import LANGS, N_, lang, short_day, tr
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc
from ..accounts.session import _accept_lang, _token_hash, me, rate_ip
from ..accounts.login import auth_key, seal, unseal
from ..core.access import Denied, acx_anon_bind, acx_org_ok, need_feat
from ..personal.timetrack import BadInput
from ..api.v1 import hit_limit
from ..lists.public import HERON_ERROR, PUB_CSP, pub_html, public_links_on
from ..events.model import ev_zone, tz_ok, wall, wall_s

TPO_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
TPO_EDIT_RE = re.compile(r"(\d{1,18})\.([A-Za-z0-9_-]{20,64})")
TPO_TITLE_MAX, TPO_DESC_MAX, TPO_LOC_MAX = 200, 4000, 500
TPO_OPT_MIN, TPO_OPT_MAX = 2, 20
TPO_DUR_MAX = 24 * 60            # minutes of one proposed time
TPO_NAME_MAX, TPO_EMAIL_MAX = 80, 200
TPO_PER_USER = 300               # polls per person (not deleted)
TPO_VOTES_MAX = 300              # votes per poll
TPO_VOTES_IP = 20                # new votes of one address per poll
TPO_VIEW_RATE, TPO_VOTE_RATE, TPO_VOTE_HOUR = 60, 10, 200  # per address / minute, per address / minute, per poll / hour
TPO_MAIL_MAX = 50                # invitation mails per "Choose this time"
TPO_ANSWERS = ("y", "m", "n")
TPO_ONLY = N_("Only who created this poll or an admin of the organisation can change it")
TPO_GONE = N_("Poll not available")


# ---------------------------------------------------------------- rights
def tpo_gate():
    """People only, module "events" (agents and API tokens: 403)."""
    from ..agents.core import is_agent
    if has_request_context() and (is_agent(getattr(g, "user", None)) or g.get("auth_via") == "token"):
        raise Denied(403, tr("Scheduling polls are only available in the app"))
    need_feat("events")


def tpo_may(c, uid, r, write=False):
    """May uid read (write: change) poll r? Private: its owner; an organisation's: members read, owner / admins change."""
    if r["org_id"] is None:
        return r["user_id"] == uid
    from ..accounts.orgs import is_org_admin, user_orgs
    if r["org_id"] not in user_orgs(c, uid) or not acx_org_ok(c, uid, r["org_id"]):
        return False
    return not write or r["user_id"] == uid or is_org_admin(c, uid, r["org_id"])


def tpo_need(c, pid, write=False, deleted=False):
    r = c.execute("SELECT * FROM sched_polls WHERE id=?", (pid,)).fetchone() if 0 < pid < 2 ** 62 else None
    uid = me()
    if not r or bool(r["deleted_at"]) != deleted or not tpo_may(c, uid, r):
        raise Denied(404)
    if write and not tpo_may(c, uid, r, write=True):
        raise Denied(403, tr(TPO_ONLY))
    return r


def tpo_space(c, uid, v):
    """org id (None = private) of a space value "private" | "org:<id>"; 404 for an organisation uid is not in."""
    if v in (None, "", "private", 0, "0"):
        return None
    s = str(v)
    if s.startswith("org:"):
        s = s[4:]
    try:
        oid = int(s)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "space")) from None
    from ..accounts.orgs import user_orgs
    if oid not in user_orgs(c, uid):
        raise Denied(404)
    return oid


def tpo_ref_ok(c, uid, kind, rid, org):
    """A task / client / list the poll is about: uid must see it and it must lie in the poll's workspace (None = fine)."""
    if rid is None:
        return True
    try:
        if kind == "task":
            from ..core.access import need_task
            need_task(c, rid, write=False)
            r = c.execute("SELECT l.org_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (rid,)).fetchone()
        elif kind == "client":
            from ..team.clients import need_client
            r = need_client(c, rid, uid)
        else:
            from ..core.access import need_list
            need_list(c, rid, write=False)
            r = c.execute("SELECT org_id FROM lists WHERE id=?", (rid,)).fetchone()
    except Denied:
        return False
    return bool(r) and (r["org_id"] or None) == (org or None)


# ---------------------------------------------------------------- values
def _txt(b, k, n, single=True):
    v = b.get(k)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", k))
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    return (" ".join(v.split()) if single else v.strip())[:n]


def _int(v, k, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise BadInput(tr("Invalid value: {0}", k))
    return v


def tpo_zone_name(r):
    return r["tz"] or getattr(TZ, "key", "UTC")


def tpo_options_clean(v, duration):
    """[{id?, start: 'YYYY-MM-DDTHH:MM', end?}] -> sorted [(id | None, start, end)] (wall clock of the poll's zone)."""
    if not isinstance(v, list) or not TPO_OPT_MIN <= len(v) <= TPO_OPT_MAX:
        raise BadInput(tr("Please propose between {0} and {1} times", TPO_OPT_MIN, TPO_OPT_MAX))
    out, seen = [], set()
    for o in v:
        if not isinstance(o, dict):
            raise BadInput(tr("Invalid value: {0}", "options"))
        s = wall(o.get("start"))
        e = wall(o.get("end")) if o.get("end") else (s + timedelta(minutes=duration) if s else None)
        if not s or not e or e <= s or e - s > timedelta(minutes=TPO_DUR_MAX):
            raise BadInput(tr("Invalid value: {0}", "options"))
        oid = o.get("id")
        if oid is not None and (isinstance(oid, bool) or not isinstance(oid, int)):
            raise BadInput(tr("Invalid value: {0}", "options"))
        if (s, e) in seen:
            continue
        seen.add((s, e))
        out.append((oid, wall_s(s), wall_s(e)))
    if len(out) < TPO_OPT_MIN:
        raise BadInput(tr("Please propose between {0} and {1} times", TPO_OPT_MIN, TPO_OPT_MAX))
    return sorted(out, key=lambda x: (x[1], x[2]))


def tpo_expires(v, zone_name):
    """'YYYY-MM-DD' (the end of that day in the poll's zone) | an ISO time | None -> ISO UTC or None."""
    if v in (None, ""):
        return None
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "expires_at"))
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            d = datetime.fromisoformat(v + "T23:59").replace(tzinfo=ev_zone(zone_name))
        else:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=ev_zone(zone_name))
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "expires_at")) from None
    return iso(d)


def tpo_fields(c, uid, b, old=None, org=None):
    """A request body -> the columns of a poll (all of them for a new one); the refs are checked against org."""
    allowed = {"title", "description", "duration", "location", "tz", "options", "expires_at", "show_votes", "task_id",
               "client_id", "list_id", "space", "link_on", "regenerate"}
    if not isinstance(b, dict) or set(b) - allowed:
        raise BadInput(tr("Invalid data"))
    f = {}
    if old is None or "title" in b:
        f["title"] = _txt(b, "title", TPO_TITLE_MAX)
        if not f["title"]:
            raise BadInput(tr("Title missing"))
    for k, n in (("description", TPO_DESC_MAX), ("location", TPO_LOC_MAX)):
        if k in b or old is None:
            f[k] = _txt(b, k, n, single=(k == "location"))
    if "duration" in b or old is None:
        f["duration"] = _int(b.get("duration", 60), "duration", 5, TPO_DUR_MAX)
    if "tz" in b or old is None:
        z = b.get("tz") or getattr(TZ, "key", "UTC")
        if not tz_ok(z) or not z:
            raise BadInput(tr("Invalid value: {0}", "tz"))
        f["tz"] = z
    zn = f.get("tz") or (old["tz"] if old is not None else "")
    if "expires_at" in b:
        f["expires_at"] = tpo_expires(b["expires_at"], zn)
    for k in ("show_votes", "link_on"):
        if k in b:
            if not isinstance(b[k], bool):
                raise BadInput(tr("Invalid value: {0}", k))
            f[k] = 1 if b[k] else 0
    for k, kind in (("task_id", "task"), ("client_id", "client"), ("list_id", "list")):
        if k in b:
            v = b[k]
            if v is not None:
                v = _int(v, k, 1, 2 ** 62)
                if not tpo_ref_ok(c, uid, kind, v, org):
                    raise BadInput(tr("Invalid value: {0}", k))
            f[k] = v
    return f


# ---------------------------------------------------------------- output
def tpo_url(c, r):
    return PUBLIC_URL.rstrip("/") + "/s/v/" + unseal(c, f"poll:{r['id']}", r["token"])


def tpo_options(c, pid):
    return c.execute('SELECT id, start, "end" FROM sched_poll_options WHERE poll_id=? ORDER BY pos, start, id', (pid,)).fetchall()


def tpo_votes(c, pid):
    return c.execute("SELECT * FROM sched_poll_votes WHERE poll_id=? ORDER BY id", (pid,)).fetchall()


def _answers(v):
    try:
        a = json.loads(v["answers"] or "{}")
    except ValueError:
        return {}
    return {str(k): x for k, x in a.items() if x in TPO_ANSWERS} if isinstance(a, dict) else {}


def tpo_tally(opts, votes):
    """{option id: {y, m, n}} and the best option id (most yes, then most maybe, then the earliest; None without a yes / maybe)."""
    t = {o["id"]: {"y": 0, "m": 0, "n": 0} for o in opts}
    for v in votes:
        for k, x in _answers(v).items():
            if k.isdigit() and int(k) in t:
                t[int(k)][x] += 1
    best = None
    for o in opts:  # opts come sorted by time: the first of equals wins
        s = t[o["id"]]
        if (s["y"] or s["m"]) and (best is None or (s["y"], s["m"]) > (t[best]["y"], t[best]["m"])):
            best = o["id"]
    return t, best


def tpo_live(c, r):
    """Is the link of poll r open right now (for the app's hint; the page checks the same in tpo_find)?"""
    return bool(r["link_on"]) and not r["deleted_at"] and (not r["expires_at"] or r["expires_at"] > iso(now_utc())) and public_links_on(c)


def tpo_space_key(oid):
    return f"org:{oid}" if oid else "private"


def tpo_event_cal(c, r):
    """The calendar of the poll's event (the app's redo of a reopen puts the event back there), or None."""
    if not r["event_id"]:
        return None
    x = c.execute("SELECT cal_id FROM events WHERE id=?", (r["event_id"],)).fetchone()
    return x[0] if x else None


def tpo_dict(c, r, uid, full=True):
    can = tpo_may(c, uid, r, write=True)
    opts = tpo_options(c, r["id"])
    votes = tpo_votes(c, r["id"])
    tally, best = tpo_tally(opts, votes)
    d = {"id": r["id"], "title": r["title"], "description": r["description"], "duration": r["duration"], "location": r["location"],
         "tz": tpo_zone_name(r), "space": tpo_space_key(r["org_id"]), "org_id": r["org_id"], "user_id": r["user_id"],
         "mine": r["user_id"] == uid, "can_edit": can, "link_on": bool(r["link_on"]), "show_votes": bool(r["show_votes"]),
         "expires_at": r["expires_at"], "closed_at": r["closed_at"], "chosen_id": r["chosen_id"], "event_id": r["event_id"],
         "event_ref": r["event_ref"] or "", "event_cal_id": tpo_event_cal(c, r), "task_id": r["task_id"], "client_id": r["client_id"], "list_id": r["list_id"],
         "created_at": r["created_at"], "updated_at": r["updated_at"], "deleted_at": r["deleted_at"], "votes_n": len(votes),
         "best_id": best, "live": tpo_live(c, r), "url": tpo_url(c, r) if can else None,
         "options": [{"id": o["id"], "start": o["start"], "end": o["end"], **tally[o["id"]]} for o in opts]}
    if full:
        d["votes"] = [{"id": v["id"], "name": v["name"], "answers": _answers(v), "at": v["updated_at"],
                       **({"email": v["email"]} if can else {})} for v in votes]
    return d


# ---------------------------------------------------------------- the API (people only)
@app.get("/api/polls")
def tpo_list():
    """?space=private|org:N|all (default all), ?task_id / client_id / list_id, ?deleted=1 (the trash) -> {items}."""
    tpo_gate()
    c, uid, a = db(), me(), request.args
    from ..accounts.orgs import user_orgs
    orgs = [o for o in user_orgs(c, uid) if acx_org_ok(c, uid, o)]
    sp = a.get("space") or "all"
    if sp == "private":
        orgs = []
    elif sp != "all":
        orgs = [tpo_space(c, uid, sp)]
    q = ("SELECT * FROM sched_polls WHERE deleted_at IS " + ("NOT NULL" if a.get("deleted") == "1" else "NULL")
         + " AND ((org_id IS NULL AND user_id=?)" + (f" OR org_id IN ({','.join('?' * len(orgs))})" if orgs else "") + ")")
    args = [uid if sp in ("all", "private") else 0, *orgs]
    for k in ("task_id", "client_id", "list_id"):
        if a.get(k):
            try:
                v = int(a[k])
            except ValueError:
                return err(tr("Invalid value: {0}", k))
            q += f" AND {k}=?"
            args.append(v)
    rows = c.execute(q + " ORDER BY closed_at IS NOT NULL, updated_at DESC, id DESC LIMIT 500", args).fetchall()
    return jsonify(items=[tpo_dict(c, r, uid, full=False) for r in rows if tpo_may(c, uid, r)], public_links=public_links_on(c))


def _store_options(c, pid, opts):
    """Replaces the options of poll pid: ids that exist keep their votes, new times get new rows, the rest goes."""
    have = {r["id"] for r in c.execute("SELECT id FROM sched_poll_options WHERE poll_id=?", (pid,))}
    keep = set()
    for i, (oid, s, e) in enumerate(opts):
        if oid in have and oid not in keep:
            c.execute('UPDATE sched_poll_options SET start=?, "end"=?, pos=? WHERE id=?', (s, e, i, oid))
            keep.add(oid)
        else:
            insert_id(c, 'INSERT INTO sched_poll_options(poll_id,start,"end",pos) VALUES(?,?,?,?)', (pid, s, e, i))
    gone = have - keep
    if gone:
        c.execute(f"DELETE FROM sched_poll_options WHERE poll_id=? AND id IN ({','.join('?' * len(gone))})", [pid, *sorted(gone)])


@app.post("/api/polls")
def tpo_create():
    """{title, description?, duration (min), location?, tz?, options: [{start, end?}] (2-20), space?, task_id? | client_id? |
    list_id?, expires_at?, show_votes?} -> 201 {poll}."""
    tpo_gate()
    c, uid, b = db(), me(), body()
    org = tpo_space(c, uid, b.get("space") if isinstance(b, dict) else None)
    f = tpo_fields(c, uid, b, org=org)
    opts = tpo_options_clean(b.get("options"), f["duration"])
    if c.execute("SELECT COUNT(*) FROM sched_polls WHERE user_id=? AND deleted_at IS NULL", (uid,)).fetchone()[0] >= TPO_PER_USER:
        return err(tr("At most {0} polls per person", TPO_PER_USER), 409)
    tok, ts = secrets.token_urlsafe(18), iso_ms(now_utc())
    f.update(user_id=uid, org_id=org, token="", token_hash=_token_hash(tok), created_at=ts, updated_at=ts)
    pid = insert_id(c, f"INSERT INTO sched_polls({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values()))
    c.execute("UPDATE sched_polls SET token=? WHERE id=?", (seal(c, f"poll:{pid}", tok), pid))  # bound to the poll's id
    _store_options(c, pid, [(None, s, e) for _i, s, e in opts])
    bump(c)
    c.commit()
    return jsonify(poll=tpo_dict(c, tpo_need(c, pid), uid)), 201


@app.get("/api/polls/<int:pid>")
def tpo_get(pid):
    tpo_gate()
    c = db()
    return jsonify(poll=tpo_dict(c, tpo_need(c, pid), me()))


@app.patch("/api/polls/<int:pid>")
def tpo_update(pid):
    """The fields of create (not space: move-space) + options (ids keep their votes; not after a time was chosen), link_on
    (false = the link is revoked, true = open again), regenerate: true (a new link; the old one stops)."""
    tpo_gate()
    c, uid, b = db(), me(), body()
    r = tpo_need(c, pid, write=True)
    if isinstance(b, dict) and "space" in b:
        return err(tr("Invalid value: {0}", "space"))
    f = tpo_fields(c, uid, b, old=r, org=r["org_id"])
    opts = None
    if "options" in b:
        if r["closed_at"]:
            return err(tr("The poll is closed: reopen it to change the times"), 409)
        opts = tpo_options_clean(b["options"], f.get("duration", r["duration"]))
    if b.get("regenerate") is True:
        tok = secrets.token_urlsafe(18)
        f.update(token=seal(c, f"poll:{pid}", tok), token_hash=_token_hash(tok))
    f["updated_at"] = iso_ms(now_utc())
    c.execute(f"UPDATE sched_polls SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), pid])
    if opts is not None:
        _store_options(c, pid, opts)
    bump(c)
    c.commit()
    return jsonify(poll=tpo_dict(c, tpo_need(c, pid), uid))


@app.delete("/api/polls/<int:pid>")
def tpo_delete(pid):
    """To the trash (the link stops at once); POST …/restore takes it back (one undo step in the app)."""
    tpo_gate()
    c = db()
    tpo_need(c, pid, write=True)
    c.execute("UPDATE sched_polls SET deleted_at=?, updated_at=? WHERE id=?", (iso(now_utc()), iso_ms(now_utc()), pid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/polls/<int:pid>/restore")
def tpo_restore(pid):
    tpo_gate()
    c = db()
    tpo_need(c, pid, write=True, deleted=True)
    c.execute("UPDATE sched_polls SET deleted_at=NULL, updated_at=? WHERE id=?", (iso_ms(now_utc()), pid))
    bump(c)
    c.commit()
    return jsonify(poll=tpo_dict(c, tpo_need(c, pid), me()))


# ---- "Choose this time": the event, the poll closes
def tpo_event_text(c, r, opt_id, lg):
    """The event's description: the poll's text + the voters who can come (yes, then maybe) by name."""
    yes, maybe = [], []
    for v in tpo_votes(c, r["id"]):
        x = _answers(v).get(str(opt_id))
        (yes if x == "y" else maybe if x == "m" else []).append(v["name"])
    parts = [r["description"]] if r["description"] else []
    if yes:
        parts.append(tr("Yes: {0}", ", ".join(yes), lg=lg))
    if maybe:
        parts.append(tr("Maybe: {0}", ", ".join(maybe), lg=lg))
    parts.append(tr("Chosen with the scheduling poll “{0}”", r["title"], lg=lg))
    return "\n\n".join(parts)[:20000]


def tpo_mail_rcpts(c, r, opt_id):
    """The voters with an address who did not say no to the chosen time (one each, at most TPO_MAIL_MAX)."""
    out, seen = [], set()
    for v in tpo_votes(c, r["id"]):
        e = (v["email"] or "").strip()
        if e and e.lower() not in seen and _answers(v).get(str(opt_id)) in ("y", "m"):
            seen.add(e.lower())
            out.append((v["name"], e))
    return out[:TPO_MAIL_MAX]


@app.post("/api/polls/<int:pid>/decide")
def tpo_decide(pid):
    """{option_id, cal_id? (a Kalmido calendar; default = the person's first) | sub_id? (a CalDAV subscription with "Allow
    writing"), mail?: bool (default false: an invitation to the voters with an address)} -> {poll, event_id | event_ref, mailed}."""
    tpo_gate()
    c, uid, b = db(), me(), body()
    r = tpo_need(c, pid, write=True)
    if r["closed_at"]:
        return err(tr("A time has already been chosen for this poll"), 409)
    oid = _int(b.get("option_id"), "option_id", 1, 2 ** 62)
    o = c.execute('SELECT id, start, "end" FROM sched_poll_options WHERE id=? AND poll_id=?', (oid, pid)).fetchone()
    if not o:
        return err(tr("Invalid value: {0}", "option_id"))
    mail = b.get("mail", False)
    if not isinstance(mail, bool):
        return err(tr("Invalid value: {0}", "mail"))
    olg = lang(c, uid)
    ev = {"title": r["title"], "location": r["location"], "description": tpo_event_text(c, r, oid, olg), "all_day": False,
          "start": o["start"], "end": o["end"], "tz": tpo_zone_name(r)}
    eid, ref = None, ""
    if b.get("sub_id") not in (None, ""):
        ref = tpo_dav_create(c, _int(b["sub_id"], "sub_id", 1, 2 ** 62), ev)
        if isinstance(ref, tuple):  # an error answer of the CalDAV write
            return ref
        r = tpo_need(c, pid, write=True)  # the write committed (no transaction is open while the calendar server is asked)
        if r["closed_at"]:
            return err(tr("A time has already been chosen for this poll"), 409)
    else:
        from ..events.model import ev_fields, ev_store, need_evcal
        cid = b.get("cal_id")
        cid = _int(cid, "cal_id", 1, 2 ** 62) if cid not in (None, "") else tpo_default_cal(c, uid, r["org_id"])
        if not cid:
            return err(tr("Please choose a calendar"), 409)
        cal, _role = need_evcal(c, cid, write=True)
        if cal["org_id"] and r["org_id"] and cal["org_id"] != r["org_id"]:  # never into another organisation's calendar
            return err(tr("This calendar belongs to another workspace"), 409)
        f = ev_fields(c, uid, ev)
        if r["task_id"] and tpo_ref_ok(c, uid, "task", r["task_id"], r["org_id"]):
            f["task_id"] = r["task_id"]
        eid = ev_store(c, uid, cid, f)
    ts = iso_ms(now_utc())
    c.execute("UPDATE sched_polls SET closed_at=?, chosen_id=?, event_id=?, event_ref=?, updated_at=? WHERE id=?",
              (ts, oid, eid, ref, ts, pid))
    rcpts = tpo_mail_rcpts(c, r, oid) if mail else []
    sent = []
    if rcpts:
        from ..integrations.mail import MAIL_OUT_ON
        from ..admin.hosting import mail_budget
        if MAIL_OUT_ON:
            sent = [x for x in rcpts if mail_budget(c, uid, x[1])]
    bump(c)
    c.commit()
    if sent:
        who = g.user["display_name"] or g.user["username"]
        threading.Thread(target=tpo_mail, args=(sent, {k: r[k] for k in r.keys()}, {k: o[k] for k in o.keys()}, who, olg), daemon=True).start()
    return jsonify(poll=tpo_dict(c, tpo_need(c, pid), uid), event_id=eid, event_ref=ref, mailed=len(sent))


def tpo_default_cal(c, uid, org):
    """The person's first own calendar of the poll's workspace, else a private one, else any they may write (an organisation's
    poll never goes into another organisation's calendar); a person with no calendar at all gets their first one."""
    from ..events.model import default_cal, my_cal_ids
    ids = my_cal_ids(c, uid)
    if not ids:
        return default_cal(c, uid)
    rows = c.execute(f"SELECT id, org_id FROM ev_cals WHERE id IN ({','.join('?' * len(ids))}) ORDER BY sort, id", list(ids)).fetchall()
    ok = [x for x in rows if ids[x["id"]] in ("owner", "edit") and (not org or not x["org_id"] or x["org_id"] == org)]
    rank = lambda x: ((x["org_id"] or None) != (org or None), bool(x["org_id"]), ids[x["id"]] != "owner")  # noqa: E731
    return min(ok, key=rank)["id"] if ok else None


def tpo_dav_create(c, sid, ev):
    """The event in a CalDAV subscription with "Allow writing" (the way of calendars/davwrite.py cdw_create) -> its UID, or
    an error answer (a tuple)."""
    import urllib.parse
    import uuid as uuidlib
    from .davwrite import (CdwConflict, _cal_fail, _cal_limited, _cdw_auth, _cdw_fields, _cdw_sub, _conflict, _put,
                           cdw_inside, cdw_new_ics, cdw_rate)
    from .subscriptions import CalError, cal_sync
    s = _cdw_sub(c, sid)
    try:
        f = _cdw_fields(ev, True)
    except ValueError as e:
        return err(tr("Invalid value: {0}", str(e)))
    if not cdw_rate(me()):
        return _cal_limited()
    url, auth, allow = _cdw_auth(c, s)
    c.commit()
    uid_ = str(uuidlib.uuid4())
    href = urllib.parse.urljoin(url if url.endswith("/") else url + "/", uid_ + ".ics")
    if not cdw_inside(url, href):
        return err(tr("Invalid value: {0}", "url"))
    try:
        _put(href, cdw_new_ics(f, uid_), auth, allow, new=True)
    except CdwConflict:
        return _conflict(c, sid)
    except CalError as e:
        return _cal_fail(e)
    cal_sync(c, sid, force=True)
    return f"s{sid}:{uid_}"


def tpo_when(start, end, zone_name, lg):
    """'Tue, 21.10.2026 10:00-11:00' in the poll's zone (the page's script shows the visitor's own zone)."""
    s, e = wall(start), wall(end)
    if not s or not e:
        return start
    wds = LANGS.get(lg, {}).get("_weekdays_short")
    wd = wds[(s.weekday() + 1) % 7] if isinstance(wds, list) and len(wds) == 7 else s.strftime("%a")
    same = s.date() == e.date()
    return (f"{wd}, {short_day(s.date(), lg, year=True)} {s:%H:%M}–" + (f"{e:%H:%M}" if same else f"{short_day(e.date(), lg, year=True)} {e:%H:%M}"))


def tpo_mail(rcpts, r, o, who, lg):
    """The background part: one invitation per voter with an address, the event attached as .ics."""
    from ..integrations.mail import mail_send
    from .davwrite import cdw_new_ics
    z = ev_zone(r["tz"])
    f = {"title": r["title"], "location": r["location"], "description": r["description"], "all_day": False,
         "start": wall(o["start"]).replace(tzinfo=z), "end": wall(o["end"]).replace(tzinfo=z), "tz": r["tz"] or getattr(TZ, "key", "UTC")}
    ics = cdw_new_ics(f, f"poll-{r['id']}-{o['id']}@kalmido").encode()
    when = tpo_when(o["start"], o["end"], r["tz"], lg) + f" ({f['tz']})"
    for name, addr in rcpts:
        text = "\n\n".join(x for x in (tr("Hello {0},", name, lg=lg),
                                       tr("{0} has chosen a time for “{1}”:", who, r["title"], lg=lg) + "\n" + when
                                       + (("\n" + r["location"]) if r["location"] else ""),
                                       tr("The event is attached: open it to add it to your calendar.", lg=lg),
                                       tr("You get this mail because you entered this address when you voted. If that was not you, you can ignore it.", lg=lg)) if x)
        try:
            mail_send(addr, tr("Date set: {0}", r["title"], lg=lg), text, from_name=APP_NAME,
                      attachments=[("invite.ics", ics, "text/calendar")])
        except Exception as x:  # noqa: BLE001  (nobody waits for this; the app showed the result)
            print("poll invitation mail failed:", type(x).__name__, flush=True)


@app.post("/api/polls/<int:pid>/reopen")
def tpo_reopen(pid):
    """The undo of "Choose this time": the poll is open again, its Kalmido event goes to the trash (restorable there); an
    event in a CalDAV subscription is deleted by the client through the calendar's own route (DELETE
    /api/calendars/<sid>/events, 2.98.0 review L1)."""
    tpo_gate()
    c = db()
    r = tpo_need(c, pid, write=True)
    if not r["closed_at"]:
        return jsonify(poll=tpo_dict(c, r, me()))
    if r["event_id"]:
        from ..events.model import ev_delete, need_event
        try:
            ev, _role = need_event(c, r["event_id"], write=True)
            ev_delete(c, ev)
        except Denied:
            pass  # the event moved where the person may no longer change it: it stays
    ts = iso_ms(now_utc())
    c.execute("UPDATE sched_polls SET closed_at=NULL, chosen_id=NULL, event_id=NULL, event_ref='', updated_at=? WHERE id=?", (ts, pid))
    bump(c)
    c.commit()
    return jsonify(poll=tpo_dict(c, tpo_need(c, pid), me()))


# ---- 2.96 pattern (P4): to the other workspace
@app.post("/api/polls/<int:pid>/move-space")
def tpo_move_space(pid):
    """{to, dry?} -- only the poll's owner moves it (into an organisation they are a member of, or back to private); a task /
    client / list it is about that does not lie in the target is taken off (named by the dry run)."""
    from ..accounts.spacemove import smv_answer, smv_refuse_agent, smv_same, smv_target
    smv_refuse_agent()
    tpo_gate()
    c, uid, b = db(), me(), body()
    r = tpo_need(c, pid, write=True)
    to = smv_target(c, uid, b.get("to"))
    smv_same(r["org_id"], to)
    if r["user_id"] != uid:
        raise Denied(403, tr("Only who created this poll can move it"))
    drop = [k for k, kind in (("task_id", "task"), ("client_id", "client"), ("list_id", "list"))
            if r[k] and not tpo_ref_ok(c, uid, kind, r[k], to)]
    names = {"task_id": tr("The poll is no longer linked to its task"), "client_id": tr("The poll is no longer linked to its client"),
             "list_id": tr("The poll is no longer linked to its list")}
    notes = [names[k] for k in drop] + ([tr("Every member of the organisation can then see the poll")] if to else [])
    if b.get("dry"):
        return jsonify(smv_answer(notes, None, count=1))
    ts = iso_ms(now_utc())
    sets = {"org_id": to, "updated_at": ts, **{k: None for k in drop}}
    c.execute(f"UPDATE sched_polls SET {','.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), pid])
    mid = insert_id(c, "INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('poll',?,?,?,?,?,?)",
                    (pid, r["org_id"], to, uid, ts, json.dumps({k: r[k] for k in drop})))
    bump(c)
    c.commit()
    return jsonify(smv_answer(notes, None, ok=True, move_id=mid, from_space=tpo_space_key(r["org_id"]), space=tpo_space_key(to),
                              poll=tpo_dict(c, tpo_need(c, pid), uid)))


# ---------------------------------------------------------------- the public page /s/v/<token>
def tpo_find(c, token):
    """The open poll of a link (its owner enabled, the link on, not deleted, not expired, public links on) or None."""
    if not TPO_TOKEN_RE.fullmatch(token or "") or not public_links_on(c):
        return None
    with system_ctx(c):  # resolve the token (one row) across organisations ...
        r = c.execute("""SELECT p.*, u.display_name AS u_name, u.username AS u_login FROM sched_polls p JOIN users u ON u.id=p.user_id
                         WHERE p.token_hash=? AND p.link_on=1 AND p.deleted_at IS NULL AND u.disabled=0 AND COALESCE(u.kind, 'user')!='agent'""",
                      (_token_hash(token),)).fetchone()
    from ..agents.core import is_agent
    if r is None or (r["expires_at"] and r["expires_at"] <= iso(now_utc())) or is_agent(getattr(g, "user", None)) \
            or request.headers.get("Authorization", "").lower().startswith("bearer "):
        return None  # agents (and API tokens) never vote through the link
    g.user = None  # everyone votes as a visitor here (a signed-in person of another organisation too)
    acx_anon_bind(c, r["org_id"])  # ... and the page reads inside exactly the poll's organisation
    return r


def tpo_lang(c, r):
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return lang(c, r["user_id"])


# the page's only script (served by GET /s/v/time.js; the public pages allow no inline script): the proposed times in the
# visitor's own zone. The page works without it (the server writes the times in the poll's zone and names that zone).
TPO_JS = """(function () {
  const lg = document.documentElement.lang || undefined;
  let own = '';
  try { own = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return; }
  const tzl = document.querySelector('.tpo-tz');
  const ptz = tzl ? tzl.getAttribute('data-ptz') : '';
  if (!own || !ptz || own === ptz) return;
  const day = new Intl.DateTimeFormat(lg, {weekday: 'short', day: 'numeric', month: 'short', year: 'numeric'});
  const hm = new Intl.DateTimeFormat(lg, {hour: '2-digit', minute: '2-digit'});
  let moved = false;
  document.querySelectorAll('time.tpo-when').forEach(t => {
    const s = new Date(t.getAttribute('datetime')), e = new Date(t.getAttribute('data-e'));
    if (isNaN(s) || isNaN(e)) return;
    const same = day.format(s) === day.format(e);
    t.textContent = `${day.format(s)} ${hm.format(s)}–${same ? hm.format(e) : day.format(e) + ' ' + hm.format(e)}`;
    moved = true;
  });
  if (moved && tzl) tzl.textContent = (tzl.getAttribute('data-own') || '').replace('{0}', own).replace('{1}', ptz);
})();
"""


@app.get("/s/v/time.js")
def tpo_js():
    from flask import Response
    r = Response("'use strict';\n" + TPO_JS, mimetype="application/javascript")
    r.headers["Cache-Control"] = "public, max-age=86400"
    return r


def tpo_headers(resp):
    """The public links' headers; plus this page's own small script (it only shows the times in the visitor's zone)."""
    resp.headers["Content-Security-Policy"] = PUB_CSP + "; script-src 'self'"
    return resp


def tpo_gone(lg=None):
    lg = lg or _accept_lang()
    return pub_html(tr(TPO_GONE, lg=lg), f'<div class="msg">{HERON_ERROR}<h1>{html.escape(tr(TPO_GONE, lg=lg))}</h1>'
                    f'<p>{html.escape(tr("This poll does not exist or is no longer open.", lg=lg))}</p></div>', lg, 404, foot=False)


def tpo_msg(title, text, lg, code=200, link=None):
    e = html.escape
    return pub_html(title, f'<div class="msg"><h1>{e(title)}</h1><p>{e(text)}</p>'
                    + (f'<a class="btn" href="{e(link[0])}">{e(link[1])}</a>' if link else "") + '</div>', lg, code, foot=False)


def tpo_cookie(pid):
    return f"kv{pid}"


def tpo_mine(c, r, key):
    """The voter's own vote of poll r for an edit key 'vote id.secret' (cookie or ?e=), else None."""
    m = TPO_EDIT_RE.fullmatch(key or "")
    if not m:
        return None
    v = c.execute("SELECT * FROM sched_poll_votes WHERE id=? AND poll_id=?", (int(m.group(1)), r["id"])).fetchone()
    if v is None or not hmac.compare_digest(v["edit_hash"], _token_hash(m.group(2))):
        return None
    return v


def _utc_attr(start, zone_name):
    s = wall(start)
    return s.replace(tzinfo=ev_zone(zone_name)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if s else ""


def tpo_page(c, r, token, lg, mine=None, vals=None, error="", note="", code=None):
    e = html.escape
    zn = tpo_zone_name(r)
    opts = tpo_options(c, r["id"])
    votes = tpo_votes(c, r["id"])
    tally, best = tpo_tally(opts, votes)
    v = vals or {}
    my = _answers(mine) if mine is not None else {}
    names = {o["id"]: {"y": [], "m": []} for o in opts}
    for x in votes:
        for k, a in _answers(x).items():
            if k.isdigit() and int(k) in names and a in ("y", "m"):
                names[int(k)][a].append(x["name"])
    closed = bool(r["closed_at"])
    owner = r["u_name"] or r["u_login"]
    head = (f'<header><h1>{e(r["title"])}</h1><p class="sub">{e(tr("A poll by {0}", owner, lg=lg))}'
            + (f' · {e(r["location"])}' if r["location"] else "") + '</p></header>'
            + (f'<div class="intro">{"".join(f"<p>{e(p)}</p>" for p in r["description"].split(chr(10)) if p.strip())}</div>' if r["description"] else ""))
    tzl = (f'<p class="sub tpo-tz" data-ptz="{e(zn)}" data-own="{e(tr("Times in your time zone ({0}); the poll uses {1}.", lg=lg))}">'
           f'{e(tr("Times in the time zone {0}", zn, lg=lg))}</p>')

    def when(o):
        return (f'<time class="tpo-when" datetime="{e(_utc_attr(o["start"], zn))}" data-e="{e(_utc_attr(o["end"], zn))}">'
                f'{e(tpo_when(o["start"], o["end"], zn, lg))}</time>')

    if closed:
        o = next((x for x in opts if x["id"] == r["chosen_id"]), None)
        main = (head + f'<div class="tpo-done"><p class="sub">{e(tr("The time has been chosen:", lg=lg))}</p>'
                + (f'<p class="tpo-chosen">{when(o)}</p>' if o else "") + '</div>' + tzl)
        return tpo_headers(pub_html(r["title"], main + '<script src="/s/v/time.js"></script>', lg, code or 200, foot=True))
    rows = []
    for o in opts:
        s = tally[o["id"]]
        cur = v.get(f"a{o['id']}") or my.get(str(o["id"])) or ""
        radios = "".join(f'<label class="tpo-a tpo-{k}"><input type="radio" name="a{o["id"]}" value="{k}"{" checked" if cur == k else ""}>'
                         f'<span>{e(lbl)}</span></label>' for k, lbl in (("y", tr("Yes", lg=lg)), ("m", tr("Maybe", lg=lg)), ("n", tr("No", lg=lg))))
        who = ""
        if r["show_votes"]:
            who = "".join(f'<p class="tpo-who"><b>{e(lbl)}:</b> {e(", ".join(names[o["id"]][k]))}</p>'
                          for k, lbl in (("y", tr("Yes", lg=lg)), ("m", tr("Maybe", lg=lg))) if names[o["id"]][k])
        rows.append(f'<fieldset class="tpo-opt{" tpo-best" if o["id"] == best else ""}"><legend>{when(o)}</legend>'
                    f'<p class="tpo-n">{e(tr("{0} yes · {1} maybe", s["y"], s["m"], lg=lg))}</p><div class="tpo-as">{radios}</div>{who}</fieldset>')
    nm = v.get("name", mine["name"] if mine is not None else "")
    em = v.get("email", mine["email"] if mine is not None else "")
    fields = (f'<label for="tv-name">{e(tr("Your name", lg=lg))}</label><input id="tv-name" name="name" required autocomplete="name" maxlength="{TPO_NAME_MAX}" value="{e(nm)}">'
              + "".join(rows)
              + f'<label for="tv-email">{e(tr("Your e-mail (optional, for the invitation)", lg=lg))}</label><input id="tv-email" name="email" type="email" autocomplete="email" maxlength="{TPO_EMAIL_MAX}" value="{e(em)}">'
              + f'<p class="sub">{e(tr("Only the organiser sees your e-mail address.", lg=lg))}' + (f' {e(tr("The others see your name and your answers.", lg=lg))}' if r["show_votes"] else "") + '</p>'
              + f'<input type="hidden" name="stamp" value="{e(_stamp(c, r))}">'
              + (f'<input type="hidden" name="edit" value="{e(v.get("edit") or "")}">' if v.get("edit") else ""))
    hp = '<div class="hp" aria-hidden="true"><label for="tv-web">Website</label><input id="tv-web" name="website" tabindex="-1" autocomplete="off"></div>'
    main = (head + tzl + (f'<p class="err" role="alert">{e(error)}</p>' if error else "") + (f'<p class="tpo-note" role="status">{e(note)}</p>' if note else "")
            + f'<form method="post" action="/s/v/{e(token)}" class="fform tpo-form">{fields}{hp}'
            + f'<button type="submit">{e(tr("Change my vote", lg=lg) if mine is not None else tr("Vote", lg=lg))}</button></form>')
    return tpo_headers(pub_html(r["title"], main + '<script src="/s/v/time.js"></script>', lg, code or (400 if error else 200), foot=True))


def _stamp(c, r):
    from ..team.forms import frm_stamp
    return frm_stamp(c, f"poll{r['id']}")


def _ip_hash(c):
    return hmac.new(auth_key(c), b"kalmido-poll-ip|" + rate_ip().encode(), hashlib.sha256).hexdigest()[:32]


@app.get("/s/v/<token>")
def tpo_page_get(token):
    c = db()
    if hit_limit("tpov:" + rate_ip(), TPO_VIEW_RATE):
        return tpo_msg(tr("Too many requests"), tr("Please wait a minute and try again."), _accept_lang(), 429)
    r = tpo_find(c, token)
    if not r:
        return tpo_gone()
    lg = tpo_lang(c, r)
    key = request.args.get("e") or request.cookies.get(tpo_cookie(r["id"])) or ""
    mine = tpo_mine(c, r, key)
    resp = make_response(tpo_page(c, r, token, lg, mine, {"edit": key} if mine is not None else None))
    if mine is not None and request.args.get("e"):
        _set_cookie(resp, r["id"], key)
    return resp


def _set_cookie(resp, pid, key):
    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"
    resp.set_cookie(tpo_cookie(pid), key, max_age=180 * 86400, path="/s/v/", httponly=True, samesite="Lax", secure=secure)


@app.post("/s/v/<token>")
def tpo_vote(token):
    from ..team.forms import FRM_MAX_S, FRM_MIN_S, frm_stamp_age, r81c_stamp_once
    c = db()
    r = tpo_find(c, token)
    if not r:
        return tpo_gone()
    lg = tpo_lang(c, r)
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return tpo_msg(tr("Not allowed", lg=lg), tr("Please vote from the poll's own page.", lg=lg), lg, 403)
    if hit_limit("tpos:" + rate_ip(), TPO_VOTE_RATE) or hit_limit(f"tpoh:{r['id']}", TPO_VOTE_HOUR, 3600):
        return tpo_msg(tr("Too many requests", lg=lg), tr("Please wait a minute and try again.", lg=lg), lg, 429)
    if (request.content_length or 0) > 64 * 1024:
        return tpo_msg(tr("Too many requests", lg=lg), tr("Please wait a minute and try again.", lg=lg), lg, 413)
    fv = request.form
    opts = tpo_options(c, r["id"])
    vals = {k: (fv.get(k) or "").strip() for k in ("name", "email", "edit")}
    vals.update({f"a{o['id']}": fv.get(f"a{o['id']}") or "" for o in opts})
    if fv.get("website"):  # the honeypot: a bot filled the hidden field -> pretend it worked
        return tpo_msg(tr("Thank you!", lg=lg), tr("Your vote has been saved.", lg=lg), lg)
    if r["closed_at"]:
        return tpo_page(c, r, token, lg, code=409)
    key = vals["edit"] or request.cookies.get(tpo_cookie(r["id"])) or ""
    mine = tpo_mine(c, r, key)
    if mine is None:
        vals["edit"] = ""
    age = frm_stamp_age(c, f"poll{r['id']}", fv.get("stamp"))
    if age is None or not FRM_MIN_S <= age <= FRM_MAX_S or not r81c_stamp_once(c, fv.get("stamp")):
        c.commit()
        return tpo_page(c, r, token, lg, mine, vals, tr("Please send your vote once more: it was sent very quickly or the page was open for a long time.", lg=lg))
    name = re.sub(r"\s+", " ", vals["name"])[:TPO_NAME_MAX]
    if not name:
        return tpo_page(c, r, token, lg, mine, vals, tr("Please enter your name.", lg=lg))
    email = vals["email"][:TPO_EMAIL_MAX]
    if email and (not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", email) or re.search(r"[,;\"'()\[\]\\]", email)):
        return tpo_page(c, r, token, lg, mine, vals, tr("Please check the e-mail address.", lg=lg))
    answers = {str(o["id"]): vals[f"a{o['id']}"] for o in opts if vals[f"a{o['id']}"] in TPO_ANSWERS}
    if not answers:
        return tpo_page(c, r, token, lg, mine, vals, tr("Please answer at least one time.", lg=lg))
    ts, iph = iso_ms(now_utc()), _ip_hash(c)
    if mine is not None:
        c.execute("UPDATE sched_poll_votes SET name=?, email=?, answers=?, updated_at=? WHERE id=?",
                  (name, email, json.dumps(answers), ts, mine["id"]))
        vid, key_out = mine["id"], key
    else:
        n_all = c.execute("SELECT COUNT(*) FROM sched_poll_votes WHERE poll_id=?", (r["id"],)).fetchone()[0]
        n_ip = c.execute("SELECT COUNT(*) FROM sched_poll_votes WHERE poll_id=? AND ip_hash=?", (r["id"], iph)).fetchone()[0]
        if n_all >= TPO_VOTES_MAX or n_ip >= TPO_VOTES_IP:
            c.commit()
            return tpo_msg(tr("Too many requests", lg=lg), tr("This poll takes no more votes.", lg=lg), lg, 429)
        sec = secrets.token_urlsafe(18)
        vid = insert_id(c, "INSERT INTO sched_poll_votes(poll_id,name,email,answers,edit_hash,ip_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (r["id"], name, email, json.dumps(answers), _token_hash(sec), iph, ts, ts))
        key_out = f"{vid}.{sec}"
    c.execute("UPDATE sched_polls SET updated_at=? WHERE id=?", (ts, r["id"]))  # the owner's app reloads it
    bump(c)
    c.commit()
    e = html.escape
    link = f"{PUBLIC_URL.rstrip('/')}/s/v/{token}?e={key_out}"
    resp = make_response(pub_html(tr("Thank you!", lg=lg), f'<div class="msg"><h1>{e(tr("Thank you!", lg=lg))}</h1><p>{e(tr("Your vote has been saved.", lg=lg))}</p>'
                                  f'<p>{e(tr("With this link you can change your vote later (also on another device):", lg=lg))}</p>'
                                  f'<input class="frm-link" readonly value="{e(link)}" aria-label="{e(tr("Link to change your vote", lg=lg))}">'
                                  f'<a class="btn" href="/s/v/{e(token)}">{e(tr("Back to the poll", lg=lg))}</a></div>', lg, 200, foot=False))
    _set_cookie(resp, r["id"], key_out)
    return resp

