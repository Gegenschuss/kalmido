"""2.111.0 B (#2056): invitations to an event by e-mail for attendees outside the server (iMIP, RFC 6047).
An attendee without an account (an address or a contact with an address) learns about an event only by mail: saving an event
in the editor with "Send the invitation by e-mail" ticked (body key send_invites, default off for every other caller, agents
included) mails the new external attendees -- and every external one when the time, place, title, repeat rule or status
changed -- a short text in the inviting person's language plus the event as an .ics file (METHOD:REQUEST, the series with its
rule, left-out and changed dates like the CalDAV export, SEQUENCE = the event's). Reply-To and ORGANIZER = the inviting
person's own address, so the answers land in their mailbox (Kalmido reads no replies). Removing an invited attendee or
deleting the event sends METHOD:CANCEL to those who got an invitation before (event_attendees.invited_seq), restoring it
invites them again. Only who may change the event triggers mails (the routes check the write right first); at most
EV_ATT_MAX recipients per event and EVI_DAY_MAX mails per person and day (ev_invite_day, then 429). Without mail sending
(KALMIDO_SMTP_*) nothing is sent and the editor says so. People of this server keep their News + push (events/model.py)."""
import re
from datetime import date, timedelta

from flask import jsonify, request

from ..core.config import app, APP_NAME
from ..core.i18n import short_day, tr
from ..core.db import db, iso, local_now, now_utc, usettings
from ..core.env import env_int
from ..accounts.session import me
from ..accounts.bgjobs import bgj_add, bgj_fn
from ..core.access import Denied
from ..core.errors import BadInput
from ..events.model import EV_ATT_MAX, need_event, wall

EVI_DAY_MAX = 200  # invitation mails per person and day
EVI_SERVER_DAY = env_int("KALMIDO_INVITE_MAIL_DAY", 2000, lo=0)  # 2.360.0 D (#2496): invitation mails of the whole server and day
# (mail_counts key EVI_SERVER_KEY); 2.360.0 R (#2496, review): set by KALMIDO_INVITE_MAIL_DAY
EVI_SERVER_KEY = "i:evinvite"
# what makes an invitation outdated: the external attendees get the new version (a change of the notes alone does not)
EVI_KEYS = ("title", "location", "all_day", "start", "end", "tz", "rrule", "exdates", "overrides", "status")


def evi_mail_on():
    from ..integrations.mail import MAIL_OUT_ON
    return MAIL_OUT_ON


def evi_flag(b):
    """Takes send_invites out of a request body (True / False; missing = False)."""
    if not isinstance(b, dict) or "send_invites" not in b:
        return False
    v = b.pop("send_invites")
    if not isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", "send_invites"))
    # 2.111.0 review: agents never mail invitations (prompt injection would send mail in the owner's name); people send them
    from flask import g
    from ..agents.core import is_agent
    if v and is_agent(getattr(g, "user", None)):
        raise Denied(403, tr("Agents cannot send invitations by e-mail; the person sends them in the app."))
    return v


def _key(a):
    return ("c", a["contact_id"]) if a["contact_id"] else ("e", (a["email"] or "").strip().lower())


_ADDR = re.compile(r"[^@\s<>\"(),;:\[\]\\]+@[^@\s<>\"(),;:\[\]\\]+\.[^@\s<>\"(),;:\[\]\\.]+")  # one plain address (no list, no comment)


def evi_ext(c, eid):
    """The external attendees of an event that have an address (no account of this server); an address that is no single
    plain address (a comma would make a second recipient) is never mailed."""
    return [dict(a) for a in c.execute("SELECT * FROM event_attendees WHERE event_id=? AND user_id IS NULL AND email<>'' ORDER BY id",
                                       (eid,)) if _ADDR.fullmatch(a["email"] or "")]


# ---- the marks survive att_set (it replaces every attendee row): kept before, put back after
def evi_keep(c, eid):
    return {_key(a): (a["invited_seq"], a["invited_at"]) for a in evi_ext(c, eid) if a["invited_seq"] is not None}


def evi_restore(c, eid, keep):
    if not keep:
        return
    for a in evi_ext(c, eid):
        k = keep.get(_key(a))
        if k:
            c.execute("UPDATE event_attendees SET invited_seq=?, invited_at=? WHERE id=?", (k[0], k[1], a["id"]))


def evi_snap(c, eid):
    """Before a change: the fields that matter for an invitation + the external attendees (to find who was removed)."""
    r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if not r:
        return None
    return {"ev": {k: r[k] for k in EVI_KEYS}, "ext": {_key(a): a for a in evi_ext(c, eid)}}


def evi_precheck(c, uid, n):
    """429 before anything changes when n more mails would pass the person's daily limit."""
    if n and _sent_today(c, uid) + n > EVI_DAY_MAX:
        raise Denied(429, tr("At most {0} invitation e-mails a day. Try again tomorrow.", EVI_DAY_MAX))
    if n and _server_today(c) + n > EVI_SERVER_DAY:  # 2.360.0 D (#2496): the server's limit, then the same answer
        raise Denied(429, tr("The server sends no more invitation e-mails today. Try again tomorrow."))


def evi_estimate(c, b, eid=None):
    """Upper bound of the mails a save sends: the external addresses given (or stored), plus the stored invited ones."""
    if isinstance(b.get("attendees"), list):
        n = sum(1 for a in b["attendees"] if isinstance(a, dict) and not a.get("user_id") and (a.get("email") or a.get("contact_id")))
    else:
        n = len(evi_ext(c, eid)) if eid else 0
    if eid:
        n += sum(1 for a in evi_ext(c, eid) if a["invited_seq"] is not None)
    return min(n, 2 * EV_ATT_MAX)


def _today():
    return local_now().date().isoformat()


def _sent_today(c, uid):
    r = c.execute("SELECT n FROM ev_invite_day WHERE user_id=? AND day=?", (uid, _today())).fetchone()
    return r[0] if r else 0


def _server_today(c):
    """2.360.0 D (#2496): the invitation mails of the whole server today (one mail_counts row). 2.360.0 R (#2496, review):
    the same day as the person's counter (_today, local), not the UTC day."""
    r = c.execute("SELECT n, day FROM mail_counts WHERE k=?", (EVI_SERVER_KEY,)).fetchone()
    return r[0] if r and r[1] == _today() else 0


def _count(c, uid, n):
    """Books n mails on today's counters (the person's and the server's); returns how many may go (the rest is dropped at
    the limit)."""
    have = _sent_today(c, uid)
    n = max(0, min(n, EVI_DAY_MAX - have, EVI_SERVER_DAY - _server_today(c)))
    if n:
        c.execute("INSERT INTO mail_counts(k,day,n) VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET "
                  "n=CASE WHEN mail_counts.day=excluded.day THEN mail_counts.n+excluded.n ELSE excluded.n END, day=excluded.day",
                  (EVI_SERVER_KEY, _today(), n))
        c.execute("INSERT INTO ev_invite_day(user_id, day, n) VALUES(?,?,?) ON CONFLICT (user_id, day) DO UPDATE SET n=ev_invite_day.n+?",
                  (uid, _today(), n, n))
        c.execute("DELETE FROM ev_invite_day WHERE day<?", ((local_now().date() - timedelta(days=7)).isoformat(),))
    return n


# ---- the mail
def _sender(c, uid, r):
    """(address, name) of the inviting person; an account without an address (an agent) invites with the calendar owner's --
    2.360.0 D (#2496): only an agent of that owner (another one's answers would go to someone who did not send it: the
    server's sender with the agent's name)."""
    u = c.execute("SELECT email, display_name, username FROM users WHERE id=?", (uid,)).fetchone()
    if u and (u["email"] or "").strip():
        return u["email"].strip(), (u["display_name"] or u["username"])
    o = c.execute("SELECT u.email, u.display_name, u.username FROM ev_cals k JOIN users u ON u.id=k.owner_id WHERE k.id=? "
                  "AND EXISTS (SELECT 1 FROM agents a WHERE a.user_id=? AND a.owner_id=k.owner_id)", (r["cal_id"], uid)).fetchone()
    from ..integrations.mail import SMTP
    if o and (o["email"] or "").strip():
        return o["email"].strip(), (o["display_name"] or o["username"])
    return SMTP["from"], (u["display_name"] or u["username"]) if u else APP_NAME


def evi_ics(c, r, method, atts, org_addr, org_name):
    """The iMIP calendar: the event's VEVENTs (events/ics.py ev_lines) without alarms, with METHOD, ORGANIZER = mailto of the
    inviting person and the external attendees (RSVP); people of this server are left out (their address is private)."""
    from ..calendars.icalfeed import ics_utc
    from ..events.ics import _pq, ev_lines, wrap
    lines, tzs = ev_lines(c, r, [])
    out, alarm, stamp = [], 0, ics_utc(now_utc())
    for x in lines:
        if x == "BEGIN:VALARM":
            alarm += 1
            continue
        if alarm:
            alarm -= x == "END:VALARM"
            continue
        n = re.split(r"[;:]", x, maxsplit=1)[0].upper()
        if n in ("ORGANIZER", "ATTENDEE", "X-KALMIDO-GUESTS-VISIBLE"):  # 2.380 H (#3392): the switch is Kalmido's own
            continue
        if n == "DTSTAMP":
            x = f"DTSTAMP:{stamp}"
        elif n == "STATUS" and method == "CANCEL":
            x = "STATUS:CANCELLED"
        if x == "END:VEVENT":
            out.append(f"ORGANIZER;CN={_pq(org_name)}:mailto:{org_addr}")
            for a in atts:
                p = [f"CN={_pq(a['name'])}"] if a["name"] else []
                p += ["ROLE=" + ("OPT-PARTICIPANT" if a["role"] == "opt" else "REQ-PARTICIPANT"), "PARTSTAT=NEEDS-ACTION", "RSVP=TRUE"]
                out.append(f"ATTENDEE;{';'.join(p)}:mailto:{a['email']}")
        out.append(x)
    return wrap(out, tzs).replace("CALSCALE:GREGORIAN\r\n", f"CALSCALE:GREGORIAN\r\nMETHOD:{method}\r\n", 1)


def evi_when(r, lg):
    """The event's time as words in its own zone: "20.10. 14:00 - 15:00 (Europe/Berlin)", all day: "20.10." / "20.10. - 22.10."."""
    if r["all_day"]:
        s, e = date.fromisoformat(r["start"][:10]), date.fromisoformat(r["end"][:10]) - timedelta(days=1)
        return short_day(s, lg, year=True) + (f" - {short_day(e, lg, year=True)}" if e > s else "")
    s, e = wall(r["start"]), wall(r["end"])
    if not s or not e:
        return r["start"]
    tail = f" ({r['tz']})" if r["tz"] else ""
    if e.date() == s.date():
        return f"{short_day(s.date(), lg, year=True)} {s:%H:%M} - {e:%H:%M}{tail}"
    return f"{short_day(s.date(), lg, year=True)} {s:%H:%M} - {short_day(e.date(), lg, year=True)} {e:%H:%M}{tail}"


def evi_mail(c, uid, r, method, a, ics_atts, update=False):
    """(to, subject, text, html, reply_to, from_name, attachments) of one invitation / cancellation mail to attendee a;
    ics_atts = the attendees the attached calendar lists."""
    import html as _h
    from ..collab.comments import lang_of
    lg = lang_of(usettings(c, uid))
    addr, name = _sender(c, uid, r)
    title = r["title"]
    if method == "CANCEL":
        subj = tr("Cancelled: {0}", title, lg=lg)
        head = tr("{0} cancelled the event: {1}", name, title, lg=lg)
    elif update:
        subj = tr("Updated invitation: {0}", title, lg=lg)
        head = tr("{0} changed the event: {1}", name, title, lg=lg)
    else:
        subj = tr("Invitation: {0}", title, lg=lg)
        head = tr("{0} invites you: {1}", name, title, lg=lg)
    lines = [head, f"{tr('Date and time', lg=lg)}: {evi_when(r, lg)}" + (f" · {tr('Repeats', lg=lg)}" if r["rrule"] else "")]
    if r["location"]:
        lines.append(f"{tr('Where', lg=lg)}: {r['location']}")
    if r["description"] and method != "CANCEL":
        lines.append(r["description"][:4000])
    foot = tr("The event is attached as a calendar file. Your answer goes to {0}.", name, lg=lg) if method != "CANCEL" else \
        tr("Your calendar app removes the event with the attached file.", lg=lg)
    text = "\n\n".join(lines + [foot]) + "\n"
    hb = ('<div style="font-family:system-ui,sans-serif;max-width:34rem;line-height:1.5">'
          + "".join(f"<p>{_h.escape(x).replace(chr(10), '<br>')}</p>" for x in lines)
          + f'<p style="color:#777;font-size:.85rem">{_h.escape(foot)}</p></div>')
    ics = evi_ics(c, r, method, ics_atts, addr, name).encode("utf-8")
    return a["email"], subj, text, hb, addr, name, [("invite.ics" if method == "REQUEST" else "cancel.ics", ics, "text/calendar")]


@bgj_fn("mail:evinvite", tries=1)
def evi_bg(mails):
    from ..integrations.mail import mail_send
    for to, subj, text, hb, rt, fn, att in mails:
        try:
            mail_send(to, subj, text, hb, from_name=fn, reply_to=rt or None, attachments=att)
        except Exception as ex:  # noqa: BLE001  (nobody waits for this; the person can send it again by saving)
            print("event invitation mail failed:", type(ex).__name__, flush=True)


def evi_send(mails):
    if mails:
        bgj_add("mail:evinvite", mails)  # 2.193.0 D (#2220): the queue in the database (the worker sends it)


def evi_after_save(c, uid, eid, snap, send, only_invited=False):
    """After a saved change (committed): the invitations / cancellations it calls for. Returns the number of mails."""
    if not send or not evi_mail_on():
        return 0
    r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if not r or r["deleted_at"]:
        return 0
    ext = evi_ext(c, eid)
    old = (snap or {}).get("ext", {})
    changed = snap is None or any(snap["ev"].get(k) != r[k] for k in EVI_KEYS)
    gone = [a for k, a in old.items() if a["invited_seq"] is not None and k not in {_key(x) for x in ext}]
    if r["status"] == "cancelled":  # called off (still in the calendar): one cancellation when it turns so
        req, cancel = [], ([a for a in ext if a["invited_seq"] is not None] if (snap or {}).get("ev", {}).get("status") != "cancelled" else []) + gone
    elif only_invited:
        req, cancel = ([a for a in ext if a["invited_seq"] is not None] if changed else []), gone
    else:
        req, cancel = [a for a in ext if changed or a["invited_seq"] is None], gone
    seen = set()
    req = [a for a in req if not (a["email"].lower() in seen or seen.add(a["email"].lower()))][:EV_ATT_MAX]  # a contact + its address: one mail
    cancel = [a for a in cancel if a["email"].lower() not in seen][:EV_ATT_MAX]
    n = _count(c, uid, len(req) + len(cancel))
    req, cancel = req[:n], cancel[:max(0, n - len(req))]
    if not req and not cancel:
        c.commit()
        return 0
    # 2.360.0 D (#2496): the attached calendar names the recipient only -- the other guests' addresses stay with the organiser;
    # 2.380 H (#3392): unless the event says so (guests_visible): then every external guest is named
    seen_all = set()
    every = [a for a in ext if not (a["email"].lower() in seen_all or seen_all.add(a["email"].lower()))][:EV_ATT_MAX]
    mails = [evi_mail(c, uid, r, "REQUEST", a, every if r["guests_visible"] else [a], update=a["invited_seq"] is not None) for a in req]
    ts = iso(now_utc())
    sent = {a["email"].lower() for a in req}
    for a in ext:
        if a["email"].lower() in sent:
            c.execute("UPDATE event_attendees SET invited_seq=?, invited_at=? WHERE id=?", (r["seq"] or 0, ts, a["id"]))
    mails += [evi_mail(c, uid, r, "CANCEL", a, [a]) for a in cancel]
    c.commit()
    evi_send(mails)
    return len(mails)


def evi_after_delete(c, uid, eid):
    """The event went to the trash (committed): a cancellation to every external attendee who had an invitation."""
    if not evi_mail_on():
        return 0
    inv = [a for a in evi_ext(c, eid) if a["invited_seq"] is not None][:EV_ATT_MAX]
    if not inv:
        return 0
    c.execute("UPDATE events SET seq=seq+1 WHERE id=?", (eid,))  # the cancellation outranks the last invitation
    r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    n = _count(c, uid, len(inv))
    mails = [evi_mail(c, uid, r, "CANCEL", a, [a]) for a in inv[:n]]
    c.commit()
    evi_send(mails)
    return len(mails)


def evi_cal_cancel(c, uid, cid):
    """Before a calendar is deleted (its events go with it): the cancellation mails of its events' invited attendees,
    sent by the caller after the commit."""
    if not evi_mail_on():
        return []
    mails = []
    for r in c.execute("""SELECT DISTINCT e.* FROM events e JOIN event_attendees a ON a.event_id=e.id
                          WHERE e.cal_id=? AND e.deleted_at IS NULL AND a.user_id IS NULL AND a.invited_seq IS NOT NULL ORDER BY e.id""",
                       (cid,)).fetchall():
        inv = [a for a in evi_ext(c, r["id"]) if a["invited_seq"] is not None][:EV_ATT_MAX]
        r = {**dict(r), "seq": (r["seq"] or 0) + 1}
        mails += [evi_mail(c, uid, r, "CANCEL", a, [a]) for a in inv[:_count(c, uid, len(inv))]]
    return mails


def evi_after_restore(c, uid, eid):
    """Restored from the trash (committed, e.g. Undo right after deleting): the cancelled attendees are invited again."""
    if not evi_mail_on() or not any(a["invited_seq"] is not None for a in evi_ext(c, eid)):
        return 0
    c.execute("UPDATE events SET seq=seq+1 WHERE id=?", (eid,))
    c.commit()
    snap = evi_snap(c, eid)
    snap["ev"]["start"] = None  # = changed: everyone invited before gets the event again
    return evi_after_save(c, uid, eid, snap, True, only_invited=True)


@app.get("/api/evinvite")
def evinvite_info():
    """For the editor: may this server send mail, the person's mails left today, and (event_id) who got an invitation."""
    c = db()
    out = {"mail_ok": evi_mail_on(), "day_max": EVI_DAY_MAX, "left": max(0, EVI_DAY_MAX - _sent_today(c, me())), "invited": []}
    eid = request.args.get("event_id")
    if eid:
        if not eid.isdigit():
            raise BadInput(tr("Invalid value: {0}", "event_id"))
        r, role = need_event(c, int(eid), write=True)
        out["invited"] = [{"contact_id": a["contact_id"], "email": a["email"], "invited_at": a["invited_at"]}
                          for a in evi_ext(c, r["id"]) if a["invited_seq"] is not None]
    return jsonify(out)
