"""2.49.0 (#1106): finding people by e-mail like in a messenger -- opt-in, address book check, connection requests.

- "Findable by e-mail" (Settings > Account > People) is off by default and per account. It needs the account's own address
  (users.email, set by an admin, the registration or OIDC) confirmed through a link mailed when the person turns it on; the
  confirmed address is kept normalised in disc_profiles. When the account's address changes later, the profile stops
  matching (confirm again). Agents, kid accounts, disabled and waiting accounts are never findable.
- "Find a person": one full address, exact match only (normalised: NFC, trimmed, lower case) -- no prefix, no list. A hit
  shows name + picture + "Connect"; everything else (no account, not findable, disabled, agent, kid, myself) gets the very
  same answer, built by the same queries. Limits: DISC_DAY searches and DISC_CHECK_DAY checked addresses per account and
  day (table disc_quota), plus a brake per client address (in memory, like the login).
- Address book check: the e-mail addresses of the contacts the person may see (own + shared address books) are matched on
  the server; the addresses never leave it, only findable hits come back, every checked address counts.
- A hit carries a ref (HMAC of searcher + person), the only way to send a request: user ids cannot be probed.
- Requests: the other person accepts (both see each other from then on: accounts/orgs.py _connections reads conn_links) or
  declines -- the sender keeps seeing "sent" either way. Withdraw, disconnect, block (blocked: further requests are hidden
  from me, the sender still sees "sent"). News + push "share" row (switchable like sharing).
- Not for agents: no /api/v1 route, no MCP tool (agents must not look accounts up).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import unicodedata
from datetime import timedelta

from flask import g, jsonify

from ..core.config import app, APP_NAME, EMAIL_RE, PUBLIC_URL
from ..core.i18n import lang, N_, tr
from ..core.db import body, bump, db, err, gset, gsetting, iso, now_utc, write_lock
from ..core.access import Denied, collab_all
from ..core.pg import insert_id, system_ctx
from ..core.mailframe import mail_html
from ..accounts.session import _rate_blocked, _rate_fail, _token_hash, client_ip, me, rate_ip

DISC_DAY = 30            # searches per account and day
DISC_CHECK_DAY = 300     # addresses of the address book check per account and day
DISC_IP = (int(os.environ.get("KALMIDO_DISC_PER_IP", "60") or 60), "dip:")  # searches + checks per client address in 15 min
DISC_TOKEN_DAYS = 3
DISC_LINK_UNDO_H = 24    # a disconnect can be undone by the one who disconnected for this long
DISC_LIMIT = N_("That is enough searching for today. Try again tomorrow.")


def disc_norm(v):
    """The normalised form of an address, or '' when it is no valid address (no prefixes, no spaces, no control chars)."""
    if not isinstance(v, str):
        return ""
    v = unicodedata.normalize("NFC", v).strip().lower()
    if len(v) > 200 or any(ord(ch) < 33 or ch in "​‌‍⁠﻿" for ch in v) or not EMAIL_RE.fullmatch(v):
        return ""
    return v


def _need_person():
    """Only people use this (not agents, not kid accounts); collaboration must be on."""
    u = g.user
    if u["kind"] != "user" or u["kid"] or not collab_all():
        raise Denied(404)
    return u


def _key(c):
    k = gsetting(c, "disc_ref_key")
    if not k:
        k = secrets.token_hex(32)
        gset(c, "disc_ref_key", k)
    return k.encode()


def disc_ref(c, uid, other):
    return hmac.new(_key(c), f"conn|{int(uid)}|{int(other)}".encode(), hashlib.sha256).hexdigest()[:40]


def _findable_sql():
    return ("SELECT u.id, u.display_name, u.username, u.avatar, u.email FROM disc_profiles p JOIN users u ON u.id=p.user_id "
            "WHERE p.email=? AND p.confirmed_at IS NOT NULL AND u.disabled=0 AND u.kind='user' AND u.kid=0 AND u.signup=''")


def _findable(c, email):
    """The findable account of a normalised address or None. The same query for every input (also invalid ones)."""
    with system_ctx(c):  # other people's accounts, matched by one exact address only
        r = c.execute(_findable_sql(), (email or "-",)).fetchone()
    return r if r and disc_norm(r["email"] or "") == email else None


def _avatar(c, u):
    """A picture for someone I may not see yet: a preset, or the uploaded photo inline (the photo route is for list people)."""
    from ..accounts.pictures import avatar_url, avatar_path
    a = u["avatar"] or ""
    if a.startswith("u:"):
        try:
            with open(avatar_path(u["id"], a[2:]), "rb") as f:
                return "data:image/jpeg;base64," + base64.b64encode(f.read(400_000)).decode()
        except OSError:
            return ""
    return avatar_url(u)


def _person(c, u, uid):
    return {"id": u["id"], "name": u["display_name"] or u["username"], "avatar": _avatar(c, u), "ref": disc_ref(c, uid, u["id"])}


def _pair(a, b):
    return (a, b) if a < b else (b, a)


def _state(c, uid, other):
    """none | sent | incoming | connected -- what the person sees about other (always the same queries)."""
    a, b = _pair(uid, other or 0)
    lk = c.execute("SELECT 1 FROM conn_links WHERE a_id=? AND b_id=? AND deleted_at IS NULL", (a, b)).fetchone()
    out = c.execute("SELECT 1 FROM conn_requests WHERE from_id=? AND to_id=? AND status NOT IN ('wd_open','wd_declined','wd_hidden')", (uid, other or 0)).fetchone()
    inc = c.execute("SELECT 1 FROM conn_requests WHERE from_id=? AND to_id=? AND status='open'", (other or 0, uid)).fetchone()
    from ..accounts.orgs import may_see
    seen = may_see(c, uid, other or 0)
    return "connected" if lk or seen else "sent" if out else "incoming" if inc else "none"


def _quota(c, uid, searches=0, checked=0):
    """(searches left, addresses left) after counting this use; negative = over the limit (nothing is done then)."""
    day = now_utc().strftime("%Y-%m-%d")
    c.execute("DELETE FROM disc_quota WHERE day<?", (day,))
    r = c.execute("""INSERT INTO disc_quota(user_id, day, searches, checked) VALUES(?,?,?,?)
                     ON CONFLICT (user_id, day) DO UPDATE SET searches=disc_quota.searches+excluded.searches,
                     checked=disc_quota.checked+excluded.checked RETURNING searches, checked""", (uid, day, searches, checked)).fetchone()
    return DISC_DAY - r[0], DISC_CHECK_DAY - r[1]


def _ip_brake():
    keys = [(DISC_IP[1] + rate_ip(), DISC_IP[0])]
    if _rate_blocked(keys):
        return True
    _rate_fail(keys)
    return False


# ---------------------------------------------------------------- my own profile: findable or not
def disc_profile(c, u):
    """{on, confirmed, pending, email, mail} -- my setting as the settings show it."""
    from ..integrations.mail import MAIL_OUT_ON
    p = c.execute("SELECT email, confirmed_at FROM disc_profiles WHERE user_id=?", (u["id"],)).fetchone()
    cur = disc_norm(u["email"] or "")
    pend = c.execute("SELECT 1 FROM disc_tokens WHERE user_id=? AND expires_at>?", (u["id"], iso(now_utc()))).fetchone()
    return {"on": bool(p), "confirmed": bool(p and p["confirmed_at"] and cur and p["email"] == cur), "pending": bool(p and pend),
            "email": u["email"] or "", "mail": MAIL_OUT_ON}


def _confirm_mail(c, u, email, tok):
    lg = lang(c, u["id"])
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    link = f"{PUBLIC_URL}/#dsc-confirm/{tok}"
    subject = t(N_("Confirm your address to be findable at {0}"), APP_NAME)
    intro = t(N_("You switched on that people at {0} can find you by this e-mail address. Confirm it with the button; the link works for {1} days. Not you? Ignore this mail and nothing changes."), APP_NAME, DISC_TOKEN_DAYS)
    button = t(N_("Confirm my address"))
    text = f"{t(N_('Hello {0},'), u['display_name'] or u['username'])}\n\n{intro}\n\n{button}: {link}\n"
    # 2.420.0 B (#3499): the shared mail frame (was its own 520 px card)
    body_html = mail_html(subject, [intro], button, link, email, t(N_('Hello {0},'), u['display_name'] or u['username']), lang=lg)
    return subject, text, body_html


@app.get("/api/disc")
def disc_get():
    """Everything of the People pane: my setting, requests in / out, my connections, the people I blocked."""
    u = _need_person()
    c = db()
    uid = u["id"]
    with system_ctx(c):  # the accounts of my own requests / connections / blocks (rows that name me)
        ppl = lambda sql, *a: c.execute(sql, a).fetchall()  # noqa: E731
        inc = ppl("""SELECT r.id, r.created_at, u.id AS uid, u.display_name, u.username, u.avatar FROM conn_requests r
                     JOIN users u ON u.id=r.from_id WHERE r.to_id=? AND r.status='open' AND u.disabled=0 ORDER BY r.id DESC""", uid)
        # 2.58.0 (#1792): a disabled target stays in "sent" (L4) -- dropping the row would tell the sender about the deactivation
        out = ppl("""SELECT r.id, r.created_at, u.id AS uid, u.display_name, u.username, u.avatar FROM conn_requests r
                     JOIN users u ON u.id=r.to_id WHERE r.from_id=? AND r.status NOT IN ('wd_open','wd_declined','wd_hidden')
                     AND NOT EXISTS (SELECT 1 FROM conn_links l WHERE l.deleted_at IS NULL AND
                                     ((l.a_id=r.from_id AND l.b_id=r.to_id) OR (l.b_id=r.from_id AND l.a_id=r.to_id)))
                     ORDER BY r.id DESC""", uid)
        lk = ppl("""SELECT l.created_at, u.id AS uid, u.display_name, u.username, u.avatar FROM conn_links l
                    JOIN users u ON u.id=CASE WHEN l.a_id=? THEN l.b_id ELSE l.a_id END
                    WHERE (l.a_id=? OR l.b_id=?) AND l.deleted_at IS NULL AND u.disabled=0 ORDER BY u.display_name""", uid, uid, uid)
        bl = ppl("""SELECT b.created_at, u.id AS uid, u.display_name, u.username, u.avatar FROM conn_blocks b
                    JOIN users u ON u.id=b.blocked_id WHERE b.user_id=? ORDER BY b.created_at DESC""", uid)
    pp = lambda r: {"id": r["uid"], "name": r["display_name"] or r["username"], "avatar": _avatar(c, {**dict(r), "id": r["uid"]}),  # noqa: E731
                    "ref": disc_ref(c, uid, r["uid"])}
    res = jsonify(profile=disc_profile(c, u), incoming=[{"id": r["id"], "at": r["created_at"], "person": pp(r)} for r in inc],
                  outgoing=[{"id": r["id"], "at": r["created_at"], "person": pp(r)} for r in out],
                  connections=[{"at": r["created_at"], "person": pp(r)} for r in lk],
                  blocked=[{"at": r["created_at"], "person": pp(r)} for r in bl],
                  limits={"day": DISC_DAY, "check_day": DISC_CHECK_DAY})
    c.commit()  # the ref key may just have been created
    return res


@app.put("/api/disc")
def disc_set():
    """{on: bool} -- on: a confirmation link goes to the account's address (already confirmed for it: on at once)."""
    u = _need_person()
    b = body()
    on = b.get("on")
    if not isinstance(on, bool):
        return err(tr("Invalid value: {0}", "on"))
    c = db()
    write_lock(c, "disc:" + str(u["id"]))
    uid = u["id"]
    if not on:
        c.execute("DELETE FROM disc_profiles WHERE user_id=?", (uid,))
        c.execute("DELETE FROM disc_tokens WHERE user_id=?", (uid,))
        c.commit()
        return jsonify(profile=disc_profile(c, u))
    email = disc_norm(u["email"] or "")
    if not email:
        c.rollback()
        return err(tr("Your account has no e-mail address yet. An admin can add it under Settings > Organisation > People."))
    p = c.execute("SELECT email, confirmed_at FROM disc_profiles WHERE user_id=?", (uid,)).fetchone()
    if p and p["confirmed_at"] and p["email"] == email:
        c.commit()
        return jsonify(profile=disc_profile(c, u))
    from ..integrations.mail import MAIL_OUT_ON, mail_send
    if not MAIL_OUT_ON:
        c.rollback()
        return err(tr("This server cannot send e-mails, so your address cannot be confirmed. Ask an admin to set up e-mail."))
    from ..admin.hosting import mail_budget
    if not mail_budget(c, uid, email):
        c.rollback()
        return err(tr("Today's e-mail limit is reached. Try again tomorrow."), 429)
    now = now_utc()
    c.execute("""INSERT INTO disc_profiles(user_id, email, confirmed_at, created_at) VALUES(?,?,NULL,?)
                 ON CONFLICT (user_id) DO UPDATE SET email=excluded.email, confirmed_at=NULL""", (uid, email, iso(now)))
    c.execute("DELETE FROM disc_tokens WHERE user_id=? OR expires_at<?", (uid, iso(now)))
    tok = secrets.token_urlsafe(32)
    c.execute("INSERT INTO disc_tokens(token_hash, user_id, email, expires_at) VALUES(?,?,?,?)",
              (_token_hash(tok), uid, email, iso(now + timedelta(days=DISC_TOKEN_DAYS))))
    subject, text, body_html = _confirm_mail(c, u, email, tok)
    c.commit()  # no open transaction while the mail server is asked
    try:
        mail_send(u["email"], subject, text, body_html, from_name=APP_NAME)
    except Exception as e:  # noqa: BLE001
        print("findable: confirmation mail failed:", type(e).__name__, flush=True)
        return err(tr("The e-mail could not be sent. Try again later."), 502)
    return jsonify(profile=disc_profile(c, u), sent=True)


@app.post("/api/disc/confirm")
def disc_confirm():
    """{token} from the mailed link, used while signed in as the same account."""
    u = _need_person()
    tok = body().get("token")
    if _ip_brake() or not isinstance(tok, str) or not 20 <= len(tok) <= 100:
        return err(tr("This link is invalid or has expired."), 404)
    c = db()
    write_lock(c, "disc-confirm")
    r = c.execute("SELECT user_id, email FROM disc_tokens WHERE token_hash=? AND expires_at>?", (_token_hash(tok), iso(now_utc()))).fetchone()
    if not r or r["user_id"] != u["id"] or r["email"] != disc_norm(u["email"] or ""):
        c.rollback()
        return err(tr("This link is invalid or has expired."), 404)
    c.execute("DELETE FROM disc_tokens WHERE user_id=?", (u["id"],))
    with system_ctx(c):  # the address belongs to the account that confirmed it last
        c.execute("UPDATE disc_profiles SET confirmed_at=NULL WHERE email=? AND user_id!=?", (r["email"], u["id"]))
    c.execute("""INSERT INTO disc_profiles(user_id, email, confirmed_at, created_at) VALUES(?,?,?,?)
                 ON CONFLICT (user_id) DO UPDATE SET email=excluded.email, confirmed_at=excluded.confirmed_at""",
              (u["id"], r["email"], iso(now_utc()), iso(now_utc())))
    c.commit()
    return jsonify(profile=disc_profile(c, u))


# ---------------------------------------------------------------- finding
@app.post("/api/disc/find")
def disc_find():
    """{email} -> {person: {id, name, avatar, ref, state} | null}. The same answer for every address that is not findable."""
    u = _need_person()
    c = db()
    uid = u["id"]
    em = disc_norm(body().get("email"))
    if _ip_brake():
        return err(tr(DISC_LIMIT), 429)
    left, _ = _quota(c, uid, searches=1)
    if left < 0:
        c.commit()
        return err(tr(DISC_LIMIT), 429)
    hit = _findable(c, em)  # also for an invalid address: the same work
    other = hit["id"] if hit and hit["id"] != uid else 0
    st = _state(c, uid, other)
    person = {**_person(c, hit, uid), "state": st} if other else None
    c.commit()
    return jsonify(person=person)


@app.post("/api/disc/check")
def disc_check():
    """The address book check: the findable people among the e-mail addresses of my contacts (own and shared books).
    -> {people: [...], checked, skipped (over today's limit)}."""
    u = _need_person()
    c = db()
    uid = u["id"]
    if _ip_brake():
        return err(tr(DISC_LIMIT), 429)
    from ..contacts.model import contacts_on, my_book_ids
    ems = []
    ids = my_book_ids(c, uid) if contacts_on(c, uid) else {}
    if ids:
        q = ",".join("?" * len(ids))
        seen = set()
        for r in c.execute(f"SELECT emails FROM contacts WHERE book_id IN ({q}) AND deleted_at IS NULL", list(ids)):
            try:
                items = json.loads(r[0] or "[]")
            except ValueError:
                continue
            for it in items if isinstance(items, list) else []:
                v = disc_norm(it.get("value") if isinstance(it, dict) else it)
                if v and v not in seen:
                    seen.add(v)
                    ems.append(v)
    _, room = _quota(c, uid)
    room = max(0, room)
    todo, skipped = ems[:room], max(0, len(ems) - room)
    _quota(c, uid, checked=len(todo))
    found = {}
    if todo:
        with system_ctx(c):  # the findable accounts among my own contacts' addresses (exact matches only)
            q = ",".join("?" * len(todo))
            for r in c.execute(_findable_sql().replace("p.email=?", f"p.email IN ({q})"), todo):
                if r["id"] != uid and disc_norm(r["email"] or "") in todo:
                    found[r["id"]] = r
    people = [{**_person(c, r, uid), "state": _state(c, uid, r["id"])} for r in found.values()]
    people.sort(key=lambda p: p["name"].lower())
    c.commit()
    return jsonify(people=people, checked=len(todo), skipped=skipped, books=bool(ids))


# ---------------------------------------------------------------- requests
def _push(c, to, kind, actor_name):
    """News item + push (row "share": News on, push off by default, both switchable in the notification settings)."""
    from ..collab.news import news_add, list_push
    news_add(c, to, kind, data={"name": actor_name}, row="share")
    title = {"connreq": N_("Connection request"), "connok": N_("Connection accepted")}[kind]
    msg = {"connreq": N_("{0} wants to connect with you"), "connok": N_("{0} accepted your connection request")}[kind]
    list_push(c, to, "share", None, lambda lg: tr(title, lg=lg), lambda lg: tr(msg, actor_name, lg=lg), click=f"{PUBLIC_URL}/#news")


def _link(c, a, b):
    a, b = _pair(a, b)
    c.execute("""INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?,?,?)
                 ON CONFLICT (a_id, b_id) DO UPDATE SET deleted_at=NULL, deleted_by=NULL""", (a, b, iso(now_utc())))


def _accept(c, rid, me_):
    r = c.execute("SELECT * FROM conn_requests WHERE id=? AND to_id=? AND status IN ('open','declined')", (rid, me_)).fetchone()
    if not r:
        raise Denied(404)
    with system_ctx(c):  # the sender's account (they asked me)
        s = c.execute("SELECT id FROM users WHERE id=? AND disabled=0 AND kind='user' AND kid=0", (r["from_id"],)).fetchone()
    if not s:
        raise Denied(404)
    c.execute("UPDATE conn_requests SET status='accepted', decided_at=? WHERE id=?", (iso(now_utc()), rid))
    _link(c, me_, r["from_id"])
    return r


@app.post("/api/disc/requests")
def conn_request():
    """{ref} of a find / check hit -> a request (or, when that person already asked me, the connection at once).
    -> {state}. A blocked sender gets "sent" too; nothing reaches the person who blocked them."""
    u = _need_person()
    ref = body().get("ref")
    c = db()
    uid = u["id"]
    write_lock(c, "conn")
    if not isinstance(ref, str) or not 20 <= len(ref) <= 64:
        c.rollback()
        return err(tr("Search for the person again."), 404)
    other = _ref_target(c, uid, ref)
    if not other:
        c.rollback()
        return err(tr("Search for the person again."), 404)
    st = _state(c, uid, other)
    if st == "connected":
        c.rollback()
        return jsonify(state="connected")
    inc = c.execute("SELECT id FROM conn_requests WHERE from_id=? AND to_id=? AND status='open'", (other, uid)).fetchone()
    if inc:  # we asked each other: connected
        _accept(c, inc["id"], uid)
        _push(c, other, "connok", u["display_name"] or u["username"])
        bump(c)
        c.commit()
        return jsonify(state="connected")
    blocked = c.execute("SELECT 1 FROM conn_blocks WHERE user_id=? AND blocked_id=?", (other, uid)).fetchone()
    old = c.execute("SELECT id, status FROM conn_requests WHERE from_id=? AND to_id=?", (uid, other)).fetchone()
    if old:  # asking again changes nothing for the other person (a declined request stays declined: no nagging)
        if old["status"].startswith("wd_"):  # 2.49.0 review S1: asking again after a withdrawal brings the old state back, no new push
            st0 = old["status"][3:]
            c.execute("UPDATE conn_requests SET status=? WHERE id=?", ("hidden" if blocked and st0 == "open" else st0, old["id"]))
            c.commit()
        else:
            c.rollback()
        return jsonify(state="sent", id=old["id"])
    rid = insert_id(c, "INSERT INTO conn_requests(from_id, to_id, status, created_at) VALUES(?,?,?,?)",
                    (uid, other, "hidden" if blocked else "open", iso(now_utc())))
    if not blocked:
        _push(c, other, "connreq", u["display_name"] or u["username"])
    c.commit()
    return jsonify(state="sent", id=rid)


def _ref_target(c, uid, ref):
    """The account a ref of mine points to: a findable person, or one I already have a request / connection with."""
    with system_ctx(c):  # candidates: findable accounts and the people of my own request / connection rows (ids only)
        ids = [r[0] for r in c.execute(
            """SELECT p.user_id FROM disc_profiles p JOIN users u ON u.id=p.user_id WHERE p.confirmed_at IS NOT NULL
               AND u.disabled=0 AND u.kind='user' AND u.kid=0 AND u.signup=''
               UNION SELECT to_id FROM conn_requests WHERE from_id=? UNION SELECT from_id FROM conn_requests WHERE to_id=?""",
            (uid, uid))]
    hit = 0
    for i in ids:  # compare every candidate (no early exit)
        if hmac.compare_digest(disc_ref(c, uid, i), ref) and i != uid:
            hit = i
    if not hit:
        return 0
    with system_ctx(c):
        r = c.execute("SELECT id, email FROM users WHERE id=? AND disabled=0 AND kind='user' AND kid=0", (hit,)).fetchone()
        p = c.execute("SELECT email FROM disc_profiles WHERE user_id=? AND confirmed_at IS NOT NULL", (hit,)).fetchone()
    if not r:
        return 0
    known = c.execute("SELECT 1 FROM conn_requests WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)", (uid, hit, hit, uid)).fetchone()
    if known or (p and p["email"] == disc_norm(r["email"] or "")):
        return hit
    return 0


@app.post("/api/disc/requests/<int:rid>/<action>")
def conn_answer(rid, action):
    """The person asked: accept | decline | reopen (undo of decline / accept, back to open)."""
    u = _need_person()
    if action not in ("accept", "decline", "reopen"):
        raise Denied(404)
    c = db()
    uid = u["id"]
    write_lock(c, "conn")
    if action == "accept":
        r = _accept(c, rid, uid)
        _push(c, r["from_id"], "connok", u["display_name"] or u["username"])
        bump(c)
        c.commit()
        return jsonify(ok=True, user_id=r["from_id"])
    r = c.execute("SELECT * FROM conn_requests WHERE id=? AND to_id=? AND status IN ('open','declined','accepted')", (rid, uid)).fetchone()
    if not r:
        c.rollback()
        raise Denied(404)
    if action == "decline":
        c.execute("UPDATE conn_requests SET status='declined', decided_at=? WHERE id=?", (iso(now_utc()), rid))
    else:
        if r["status"] == "accepted":  # undo of accept: the connection goes again
            a, b = _pair(uid, r["from_id"])
            c.execute("DELETE FROM conn_links WHERE a_id=? AND b_id=?", (a, b))
            bump(c)
        c.execute("UPDATE conn_requests SET status='open', decided_at=NULL WHERE id=?", (rid,))
    c.commit()
    return jsonify(ok=True)


@app.delete("/api/disc/requests/<int:rid>")
def conn_withdraw(rid):
    """The sender takes a request back (any state but accepted). Undo = asking again with the ref. 2.49.0 review S1: the row
    stays, marked wd_<state>: asking again restores that state without a new push (no withdraw / ask loop of pushes, a
    declined request stays declined)."""
    u = _need_person()
    c = db()
    n = c.execute("UPDATE conn_requests SET status='wd_' || status WHERE id=? AND from_id=? AND status IN ('open','declined','hidden')",
                  (rid, u["id"])).rowcount
    c.commit()
    if not n:
        raise Denied(404)
    return jsonify(ok=True)


# ---------------------------------------------------------------- connections and blocks
@app.delete("/api/disc/connections/<int:other>")
def conn_drop(other):
    """Disconnect: the explicit connection ends (shared lists, organisations and kids keep connecting people as before)."""
    u = _need_person()
    c = db()
    a, b = _pair(u["id"], other)
    n = c.execute("UPDATE conn_links SET deleted_at=?, deleted_by=? WHERE a_id=? AND b_id=? AND deleted_at IS NULL",
                  (iso(now_utc()), u["id"], a, b)).rowcount
    # the old request rows go too, so asking again later works like the first time
    c.execute("DELETE FROM conn_requests WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)", (u["id"], other, other, u["id"]))
    if n:
        bump(c)
    c.commit()
    if not n:
        raise Denied(404)
    return jsonify(ok=True)


@app.post("/api/disc/connections/<int:other>/restore")
def conn_restore(other):
    """Undo of a disconnect / block: only the one who disconnected, within DISC_LINK_UNDO_H hours."""
    u = _need_person()
    c = db()
    a, b = _pair(u["id"], other)
    since = iso(now_utc() - timedelta(hours=DISC_LINK_UNDO_H))
    n = c.execute("UPDATE conn_links SET deleted_at=NULL, deleted_by=NULL WHERE a_id=? AND b_id=? AND deleted_by=? AND deleted_at>?",
                  (a, b, u["id"], since)).rowcount
    if n:
        bump(c)
    c.commit()
    if not n:
        raise Denied(404)
    return jsonify(ok=True)


@app.post("/api/disc/blocks/<int:other>")
def conn_block(other):
    """Block someone who asked me or is connected with me: their requests stay hidden from me, a connection ends.
    -> {unlinked} (the client's undo restores it)."""
    u = _need_person()
    c = db()
    uid = u["id"]
    write_lock(c, "conn")
    a, b = _pair(uid, other)
    known = c.execute("SELECT 1 FROM conn_requests WHERE from_id=? AND to_id=?", (other, uid)).fetchone() or \
        c.execute("SELECT 1 FROM conn_links WHERE a_id=? AND b_id=?", (a, b)).fetchone()
    if not known or other == uid:
        c.rollback()
        raise Denied(404)
    c.execute("INSERT INTO conn_blocks(user_id, blocked_id, created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (uid, other, iso(now_utc())))
    c.execute("UPDATE conn_requests SET status='hidden' WHERE from_id=? AND to_id=? AND status='open'", (other, uid))
    n = c.execute("UPDATE conn_links SET deleted_at=?, deleted_by=? WHERE a_id=? AND b_id=? AND deleted_at IS NULL",
                  (iso(now_utc()), uid, a, b)).rowcount
    if n:
        bump(c)
    c.commit()
    return jsonify(ok=True, unlinked=bool(n))


@app.delete("/api/disc/blocks/<int:other>")
def conn_unblock(other):
    """Unblock (also the undo of a block): a hidden request shows again."""
    u = _need_person()
    c = db()
    n = c.execute("DELETE FROM conn_blocks WHERE user_id=? AND blocked_id=?", (u["id"], other)).rowcount
    c.execute("UPDATE conn_requests SET status='open' WHERE from_id=? AND to_id=? AND status='hidden'", (other, u["id"]))
    c.commit()
    if not n:
        raise Denied(404)
    return jsonify(ok=True)


def disc_request_open(c, uid, actor):
    """News: a request item stays while the request from actor to uid is open."""
    return bool(c.execute("SELECT 1 FROM conn_requests WHERE from_id=? AND to_id=? AND status='open'", (actor, uid)).fetchone())

