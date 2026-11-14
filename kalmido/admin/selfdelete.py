"""2.553.0 (#1413): a person deletes their own account (GDPR Art. 17) - Settings > Account > Delete account.

Decided (13.10.2026): a fixed waiting time of SDL_DAYS days. Asking for it (POST /api/account/delete, confirmed with the
password - and the app code when one is set - or, without a password, a sign-in of the last few minutes) locks the account
at once: users.disabled = 1 (every way in checks it: sessions, the sign-in proxy, API tokens, app passwords, the upload
token), every session ends, the own agents are paused (agents.enabled = 0, the ones that ran are noted to come back), and
users.delete_at says when. Projects shared with others stay usable for them meanwhile. The sign-in with the right password
offers only "Cancel the deletion"; the mail sent at once (and the reminder one day before) carries a cancel link
(/#delete-cancel=<uid>.<secret>, only hashes stored). Cancelling lifts all of it. After the waiting time the watchdog
(sdl_tick) carries out what was chosen per own project (hand over to a member or delete along; nobody is left to take a
project over: one nobody else uses goes, else the first other member gets it) and deletes the account through
accounts/users.user_delete_run (the same path as the admin's deletion: retention gate, user_purge, files after the commit,
security log), then a last mail confirms it. Refused: agents, child accounts, the last active server admin, the last
admin of an organisation, an account whose organisation things nobody could take over (orgretain.upg_heirless).
An admin who enables the account again ends the deletion as well (the next tick lifts it)."""
import json
import secrets
from datetime import timedelta

from flask import g, jsonify, request
from werkzeug.security import check_password_hash

from ..core.config import APP_NAME, COOKIE, OPEN_PATHS, PUBLIC_URL, app
from ..core.db import body, bump, db, db_log_err, err, gsetting, iso, local_now, now_utc, parse_iso
from ..core.i18n import N_, lang, short_day, tr
from ..core.mailframe import mail_html
from ..core.pg import system_ctx
from ..core.tokenhash import tkh_hash, tkh_match
from ..accounts.bgjobs import BGJ_FNS, bgj_add
from ..accounts.login import _reauth, rc_use, totp_match, unseal
from ..accounts.session import _DUMMY_HASH, _rate_fail, _rate_keys, _token_hash, login_wait, rate_ip
from ..accounts.sessions import ses_end
from ..notify.push import WD_TICKS
from ..notify.alerts import aa_now
from ..core.access import my_inbox
from ..lists.lists import list_purge
from ..accounts.orglists import _ol_people  # 2.1151.0 D (#4562)
from ..collab.news import KIND_ROW
from ..core.objnotify import obj_notify
from ..lists.ownership import owner_candidates, owner_transfer
from ..accounts.users import _active_admins, user_delete_run
from ..accounts.useradmin import ua8_foreign, ua8_list_info, ua8_owned
from ..accounts.orgretain import UPG_NO_HEIR, upg_heirless, upg_info
from .backup import BK_ON_ENV, _clamp_int, bk_weekly_max
from .hosting import hosted
from .retexport import rx_counts, rx_gate, rx_subject, rx_user_info

SDL_DAYS = 7  # fixed (decided 13.10.2026)
SDL_REMIND = timedelta(days=1)  # the reminder mail one day before
SDL_RETRY = timedelta(hours=1)  # a final run that failed is tried again after this long (an admin alert says why)
SDL_FRESH = 600  # s: an account without a password confirms with a sign-in at most this long ago (as users.FIRST_PW_FRESH)
SDL_CANCEL = "/api/auth/delete-cancel"
OPEN_PATHS.add(SDL_CANCEL)  # reachable without a session: the account is locked (the cancel link / the password is the credential)
SDL_LAST_ADMIN = N_("You are the only active server admin. Make somebody else a server admin first, then delete your account.")
SDL_LAST_ORG = N_("You are the last admin of the organisation {0}. Make somebody else an admin there first (or delete the organisation), then delete your account.")


def sdl_plan(u):
    try:
        p = json.loads(u["delete_plan"] or "{}")
    except (TypeError, ValueError):
        p = {}
    return p if isinstance(p, dict) else {}


def _when(at, lg):
    """The day the deletion runs, in the server's time zone, as the mails / the sign-in say it."""
    try:
        d = parse_iso(at).astimezone(local_now().tzinfo).date()
    except (TypeError, ValueError):
        return str(at or "")[:10]
    return short_day(d, lg, year=True)


# ---------------------------------------------------------------- what stands in the way, the projects
def sdl_refusal(c, u):
    """The reason why this account cannot delete itself (translated), or None."""
    if (u["kind"] or "user") == "agent":
        return tr("Not allowed")
    if u["kid"]:
        return tr("Not possible with a child account")
    if u["is_admin"] and not _active_admins(c, u["id"]):
        return tr(SDL_LAST_ADMIN)
    with system_ctx(c):  # organisations the person administers, whether another active admin is left (names of their own orgs)
        r = c.execute("""SELECT o.name FROM org_members m JOIN orgs o ON o.id=m.org_id
                         WHERE m.user_id=? AND m.role='admin' AND o.personal_of IS NULL AND o.retired_at IS NULL
                           AND NOT EXISTS (SELECT 1 FROM org_members m2 JOIN users x ON x.id=m2.user_id
                                           WHERE m2.org_id=m.org_id AND m2.role='admin' AND m2.user_id<>m.user_id
                                             AND NOT x.disabled AND COALESCE(x.kind, 'user')<>'agent')
                         ORDER BY o.id LIMIT 1""", (u["id"],)).fetchone()
    if r:
        return tr(SDL_LAST_ORG, r[0])
    if upg_heirless(c, u["id"]):
        return tr(UPG_NO_HEIR)
    return None


def _heirs(c, lid, uid):
    """The other members of project lid who may become its owner (lists.ownership.owner_candidates, members only)."""
    with system_ctx(c):  # a project of an organisation: its members are checked against the organisation inside
        return [{"id": x["id"], "name": x["name"]} for x in owner_candidates(c, lid, uid) if x["role"] is not None]


def _receipts(c, lid):
    with system_ctx(c):
        return bool(c.execute("SELECT 1 FROM budget_files WHERE list_id=? LIMIT 1", (lid,)).fetchone())


def _may_delete_along(c, lr, how):
    """A project with receipts goes along only on the hosted instance after the retention export (as useradmin.ua8_lists_settle);
    a project of an organisation the person no longer belongs to is only handed over."""
    if ua8_foreign(c, lr):
        return tr("Projects of an organisation you do not belong to cannot be deleted along: hand them over instead.")
    if _receipts(c, lr["id"]) and not (hosted() and how == "exported"):
        return tr("Projects with receipts cannot be deleted along (receipts are kept): hand them over instead.")
    return None


# ---------------------------------------------------------------- confirming who asks
def _confirm(c, u, b):
    """The same step as the other security changes of the account (login._reauth: the password, rate-limited) plus the code
    of the authenticator app when one is set (as turning it off); without a password a sign-in of the last SDL_FRESH s
    (as the first password, users.h6a_first_password_check). An error response or None."""
    if u["password_hash"]:
        e = _reauth(u, b)
        if e:
            return e
        if u["totp_secret"]:
            try:
                secret = unseal(c, f"totp:{u['id']}", u["totp_secret"])
            except Exception:  # noqa: BLE001 - an unreadable secret: only a recovery code helps
                secret = ""
            code = b.get("code")
            if not code:
                return jsonify(error=tr("Enter the code from your authenticator app"), code_needed=True), 403
            st = totp_match(secret, code, u["totp_step"]) if secret else None
            # review N2: like the login, a code counts once (its step is written; a second use in the window fails)
            ok = bool(st) and c.execute("UPDATE users SET totp_step=? WHERE id=? AND totp_step<?", (st, u["id"], st)).rowcount == 1
            if not (ok or rc_use(c, u["id"], code)):
                _rate_fail(_rate_keys(u["username"]))
                return err(tr("Wrong code"), 403)
        return None
    if g.auth_via != "session":
        return err(tr("An admin can delete this account."), 403)
    tok = request.cookies.get(COOKIE)
    r = c.execute("SELECT created_at FROM sessions WHERE token_hash=?", (_token_hash(tok),)).fetchone() if tok else None
    if not r or r[0] < iso(now_utc() - timedelta(seconds=SDL_FRESH)):
        return jsonify(error=tr("To delete your account, please sign out and sign in again (at most {0} minutes ago).", SDL_FRESH // 60),
                       fresh_needed=True), 403
    return None


def _person():
    if not g.user or (g.user["kind"] or "user") == "agent" or g.auth_via not in ("session", "proxy"):
        return err(tr("Not allowed"), 403)
    return None


# ---------------------------------------------------------------- routes
@app.get("/api/account/delete")
def sdl_info():
    """For the dialog: whether it may go (reason), the own projects (useradmin.ua8_list_info: name, shared with, lock,
    receipts) each with the members who may take it over, what else happens (orgretain.upg_info, the same numbers as the
    admin's dialog incl. purge.shared), the retention step (retexport.rx_user_info) and how to confirm."""
    e = _person()
    if e:
        return e
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    reason = sdl_refusal(c, u)
    lists = ua8_owned(c, u["id"])
    info = ua8_list_info(c, lists, "instance")
    for x in info:
        x["heirs"] = _heirs(c, x["id"], u["id"])
    ret = rx_user_info(c, u["id"], along=False)
    ret["needed_along"] = rx_user_info(c, u["id"], along=True)["needed"]
    c.rollback()
    return jsonify(can=reason is None, reason=reason or "", days=SDL_DAYS, lists=info, purge=upg_info(c, u["id"]) if reason is None else {},
                   retention=ret, confirm="password" if u["password_hash"] else ("fresh" if g.auth_via == "session" else "admin"),
                   code=bool(u["password_hash"] and u["totp_secret"]), fresh_minutes=SDL_FRESH // 60,
                   username=u["username"], email=bool(u["email"]))


@app.post("/api/account/delete")
def sdl_request():
    """{password, code?, lists: {"<project id>": {"to": <member id>} | {"delete": true}}, retention?: exported | waived}:
    locks the account for SDL_DAYS days and sends the mail with the cancel link. Every own project needs its choice; a
    choice is checked here and carried out by the final run (sdl_tick)."""
    e = _person()
    if e:
        return e
    c = db()
    b = body()
    u = c.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    uid = u["id"]
    e = _confirm(c, u, b)
    c.commit()  # a used recovery code stays used; review N2: a used app code too (also when a later check refuses)
    if e:
        return e
    reason = sdl_refusal(c, u)
    if reason:
        return err(reason, 409)
    how = b.get("retention") if b.get("retention") in ("exported", "waived") else ""
    want = b.get("lists") if isinstance(b.get("lists"), dict) else {}
    choice, along = {}, False
    for lr in ua8_owned(c, uid):
        ch = want.get(str(lr["id"])) if isinstance(want.get(str(lr["id"])), dict) else {}
        if ch.get("delete") is True:
            bad = _may_delete_along(c, lr, how)
            if bad:
                return jsonify(error=bad, lists=[lr["id"]]), 409
            choice[str(lr["id"])] = {"delete": True}
            along = True
            continue
        try:
            to = int(ch.get("to") or 0)
        except (TypeError, ValueError):
            to = 0
        if not to or to not in {x["id"] for x in _heirs(c, lr["id"], uid)}:
            return jsonify(error=tr("Choose for every project: hand it over to a member or delete it along."), lists=[lr["id"]]), 409
        choice[str(lr["id"])] = {"to": to}
    keep, _retained = rx_gate(c, rx_subject(c, "user", uid), along=along, how=how)  # records to keep: the export or its waiver now
    if keep:
        c.rollback()
        return keep
    tok = secrets.token_urlsafe(24)
    at = iso(now_utc() + timedelta(days=SDL_DAYS))
    with system_ctx(c):  # the own agents, also those working in an organisation: their tokens are refused meanwhile
        paused = [r[0] for r in c.execute("SELECT user_id FROM agents WHERE owner_id=? AND enabled ORDER BY user_id", (uid,)).fetchall()]
        if paused:
            c.execute("UPDATE agents SET enabled=false WHERE owner_id=? AND enabled", (uid,))
    plan = {"lists": choice, "how": how, "along": along, "agents": paused, "toks": [tkh_hash(tok)], "asked": iso(now_utc()),
            "rx": rx_counts(c, rx_subject(c, "user", uid), along)}  # review M2: the records to keep the gate saw when it was asked for
    sdl_notify(c, uid, choice, at)  # 2.1151.0 D (#4562): before the lock (the projects' roles as they are now)
    c.execute("UPDATE users SET disabled=true, delete_at=?, delete_plan=? WHERE id=?", (at, json.dumps(plan), uid))
    ses_end(c, uid)  # every session, this one too
    bump(c)
    c.commit()
    aa_now("security", f"selfdel:{uid}", N_("The account {0} asked for its deletion; it is locked and goes on {1}."), [f"#{uid}", at[:10]])
    sdl_mail(c, uid, "asked", f"{uid}.{tok}")
    resp = jsonify(ok=True, delete_at=at, mail=bool(u["email"]))
    resp.delete_cookie(COOKIE, path="/")
    return resp


def sdl_notify(c, uid, choice, at):
    """2.1151.0 D (#4562): the person asked for the deletion -- everybody who still reads one of their projects that goes along
    (choice "delete") hears it in the bell: a News entry of the existing kind orglist (action acctdel: the project's name, the
    day, nothing of its content), switched with the row "share" of the notification settings like the other project notices.
    Through the core's send decision (obj_notify, kind list): only people with a role on the project, never agents. A project
    handed over says nothing (it stays); taking the request back sends no second notice (decision of the build, #4562)."""
    day = parse_iso(at).astimezone(local_now().tzinfo).date().isoformat()
    for k, ch in sorted(choice.items()):
        if not ch.get("delete"):
            continue
        with system_ctx(c):  # the members of the own project (structure)
            lr = c.execute("SELECT id, name, owner_id FROM lists WHERE id=?", (int(k),)).fetchone()
            people = [x for x in _ol_people(c, lr) if x != uid] if lr else []
        if people:
            obj_notify(c, "list", lr["id"], people, row=KIND_ROW["orglist"], lid=lr["id"], push=False,
                       news={"kind": "orglist", "list_id": lr["id"], "actor": uid,
                             "data": {"action": "acctdel", "name": lr["name"], "day": day, "member": 1}})


def _lift(c, u):
    """Cancels the deletion of u (the caller commits): unlocked, the paused agents run again."""
    p = sdl_plan(u)
    with system_ctx(c):  # the agents may work in an organisation; the cancel link comes without a session
        for aid in p.get("agents") or []:
            c.execute("UPDATE agents SET enabled=true WHERE user_id=? AND owner_id=?", (int(aid), u["id"]))
        c.execute("UPDATE users SET disabled=false, delete_at=NULL, delete_plan='' WHERE id=?", (u["id"],))


@app.post("/api/auth/delete-cancel")  # SDL_CANCEL (a plain string: the route guards read it)
def sdl_cancel():
    """{token: "<uid>.<secret>"} (the link of the mail) or {username, password} (the sign-in): the deletion is off, the
    account can sign in again (with its second factor as always). Rate-limited like a sign-in."""
    c = db()
    b = body()
    tok = str(b.get("token") or "")
    if tok:
        keys = [("ip:" + rate_ip(), 20)]
        e = login_wait(keys, "")
        if e:
            return e
        uid, _, secret = tok.partition(".")
        u = c.execute("SELECT * FROM users WHERE id=? AND delete_at IS NOT NULL", (int(uid),)).fetchone() if uid.isdigit() and len(uid) <= 18 else None  # review N1: no BIGINT overflow
        ok = bool(u and secret and any(tkh_match(secret, h) for h in sdl_plan(u).get("toks") or []))
    else:
        username = str(b.get("username") or "").strip().lower()
        keys = _rate_keys(username)
        e = login_wait(keys, username)
        if e:
            return e
        u = c.execute("SELECT * FROM users WHERE username=? AND delete_at IS NOT NULL", (username,)).fetchone()
        pw = b.get("password") if isinstance(b.get("password"), str) else ""
        pw_ok = check_password_hash(u["password_hash"] if u and u["password_hash"] else _DUMMY_HASH, pw)  # one hash check on every path
        ok = bool(u and u["password_hash"] and pw_ok)
    if not ok:
        _rate_fail(keys)
        c.rollback()
        return err(tr("This link is no longer valid") if tok else tr("Wrong username or password"), 403 if tok else 401)
    _lift(c, u)
    bump(c)
    c.commit()
    sdl_mail(c, u["id"], "cancelled")
    return jsonify(ok=True, username=u["username"])


# ---------------------------------------------------------------- mails
def _backup_line(c, lg):
    """What the mails say about the backups: their own keeping times on this server (Settings > Backups), never invented ones."""
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    again = t(N_("If an older backup is restored, your account is deleted again."))
    if not BK_ON_ENV or gsetting(c, "bk_on") != "1":
        return again
    daily = _clamp_int(gsetting(c, "bk_keep_daily"), 1, 365, 14)
    weekly = _clamp_int(gsetting(c, "bk_keep_weekly"), 0, bk_weekly_max(), 8)
    return t(N_("Copies of your data stay in the server’s backups until newer ones replace them (on this server: daily backups for {0} days, weekly ones for {1} weeks)."),
             daily, weekly) + " " + again


SDL_MAILS = {
    "asked": N_("Your account will be deleted"),
    "remind": N_("Your account will be deleted tomorrow"),
    "cancelled": N_("The deletion of your account was cancelled"),
    "done": N_("Your account was deleted"),
}


def sdl_content(c, kind, username, lg, at=None, tok=None):
    """(subject, text, html) of mail kind ("asked", "remind", "cancelled", "done") in language lg."""
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    link, button = (f"{PUBLIC_URL}/#delete-cancel={tok}", t(N_("Cancel the deletion"))) if tok else (None, None)
    if kind == "asked":
        lines = [t(N_("You asked to delete your account {0}. It is locked now and will be deleted permanently on {1}."), username, _when(at, lg)),
                 t(N_("Changed your mind? Until then, the button below cancels the deletion (or sign in with your password)."))]
    elif kind == "remind":
        lines = [t(N_("Your account {0} will be deleted permanently tomorrow ({1})."), username, _when(at, lg)),
                 t(N_("Changed your mind? Until then, the button below cancels the deletion (or sign in with your password)."))]
    elif kind == "cancelled":
        lines = [t(N_("The deletion of your account {0} was cancelled. You can sign in again."), username)]
        link, button = f"{PUBLIC_URL}/", t(N_("Open {0}"), APP_NAME)
    else:
        lines = [t(N_("Your account {0} and its data were deleted permanently."), username)]
    if kind in ("asked", "done"):
        lines.append(_backup_line(c, lg))
    if kind in ("asked", "remind", "cancelled"):
        lines.append(t(N_("If that was not you: cancel the deletion and change your password right away.")) if kind != "cancelled"
                     else t(N_("If that was not you: change your password right away and tell an admin.")))
    subject = f"{APP_NAME}: {t(SDL_MAILS[kind])}"
    text = "\n\n".join(lines) + (f"\n\n{link}\n" if link else "\n")
    return subject, text, mail_html(subject, lines, button, link, lang=lg)


def sdl_mail(c, uid, kind, tok=None, addr=None, username=None, lg=None):
    """Queues mail kind to the account's address (addr / username / lg: given for "done", the account is gone). Never raises."""
    try:
        if "mail:security" not in BGJ_FNS:  # registered by integrations/mail.py with outgoing mail only
            return False
        at = None
        if addr is None:
            with system_ctx(c):
                u = c.execute("SELECT username, email, delete_at FROM users WHERE id=?", (uid,)).fetchone()
            if not u:
                return False
            addr, username, at, lg = u["email"], u["username"], u["delete_at"], lang(c, uid)
        if not (addr or "").strip():
            return False
        bgj_add("mail:security", addr.strip(), *sdl_content(c, kind, username, lg or "en", at, tok),
                user_id=uid if kind != "done" else None, delay=1.0)
        return True
    except Exception as e:  # noqa: BLE001 - a mail never breaks the step itself
        print("account deletion mail not queued:", kind, db_log_err(e), flush=True)
        return False


# ---------------------------------------------------------------- the background run
def _settle(c, uid, plan):
    """user_delete_run's settle: the choices per own project, carried out now -> (None, (icons, files, audit text, args)) or
    (an error response, None). A project without a (still possible) choice goes to its first other member; nobody is left:
    it goes (nobody else uses it), unless it keeps receipts (then the run waits, an admin alert says why)."""
    choice = plan.get("lists") or {}
    icons, files, moved, gone = [], [], 0, 0
    inbox = my_inbox(c, uid)
    for lr in ua8_owned(c, uid):
        ch = choice.get(str(lr["id"])) or {}
        heirs = [x["id"] for x in _heirs(c, lr["id"], uid)]
        if not ch.get("delete"):
            to = ch.get("to") if ch.get("to") in heirs else (heirs[0] if heirs else None)
            if to:
                with system_ctx(c):  # a project of an organisation (checked: the member may own it there)
                    owner_transfer(c, lr, to, force=True)
                    c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lr["id"], uid))
                moved += 1
                continue
        bad = _may_delete_along(c, lr, plan.get("how") or "")
        if bad:
            return err(bad, 409), None
        with system_ctx(c):  # the watchdog deletes the person's own project along, as chosen when it was asked for
            icon, lf = list_purge(c, lr["id"], inbox)
        icons.append((lr["id"], icon))
        files += lf
        gone += 1
    return None, (icons, files, N_("{0} deleted the account {1}: {2} projects handed over, {3} deleted along."), [moved, gone])


class SdlWait(Exception):
    """review M2: the final deletion waits (the reason is the text)."""

    def text(self):
        return str(self.args[0]) if self.args else ""


def sdl_run(c, uid):
    """The final deletion of uid (its delete_at passed). True when it went; else the plan notes the try (SDL_RETRY)."""
    with system_ctx(c):
        u = c.execute("SELECT * FROM users WHERE id=? AND disabled AND delete_at IS NOT NULL", (uid,)).fetchone()
    if not u:
        c.rollback()
        return False
    plan = sdl_plan(u)
    addr, username, lg = u["email"], u["username"], lang(c, uid)
    why = ""
    with app.test_request_context("/api/account/delete/run"):
        g.db, g.pushes, g.user, g.auth_via = c, [], u, None  # the person's own step (me() = the account, as when it asked)
        try:
            # review M2: records to keep that came after the request (e.g. receipts others filed in a project deleted along)
            # passed no export or waiver - then it waits and the admins are told (tried again every hour)
            now_rx = rx_counts(c, rx_subject(c, "user", uid), bool(plan.get("along")))
            old_rx = plan.get("rx") or {}
            if any(n > int(old_rx.get(k) or 0) for k, n in now_rx.items()):
                raise SdlWait("retention: records to keep came after the request")
            with system_ctx(c):  # across organisations, like the hosting operator's deletion (admin/operator.py)
                code, answer, _n = user_delete_run(c, uid, {"t": N_("the account holder")}, along=bool(plan.get("along")),
                                                   settle=lambda: _settle(c, uid, plan), how="requested")
            if code:
                c.rollback()
                why = code if not isinstance(answer, tuple) else (answer[0].get_json() or {}).get("error") or code
        except Exception as e:  # noqa: BLE001 - one account never stops the tick; tried again later
            c.rollback()
            why = e.text() if callable(getattr(e, "text", None)) else type(e).__name__
        finally:
            g.pop("db", None)  # the watchdog's connection stays open
    c.set_ctx(role="system")  # the watchdog's own context again
    if not why:
        sdl_mail(c, None, "done", addr=addr, username=username, lg=lg)
        return True
    plan["tried"] = iso(now_utc())
    with system_ctx(c):
        c.execute("UPDATE users SET delete_plan=? WHERE id=?", (json.dumps(plan), uid))
    c.commit()
    aa_now("security", f"selfdel-fail:{uid}", N_("The deletion the account {0} asked for could not run yet ({1}); it is tried again every hour."),
           [f"#{uid}", str(why)[:200]])
    print("account deletion", uid, "waits:", str(why)[:200], flush=True)
    return False


def sdl_tick(c, *_):
    """Watchdog: accounts whose deletion was asked for -- enabled again by an admin (the deletion is off), one day before
    (the reminder with a new cancel link), due (sdl_run). Idempotent: every step leaves a mark (gone, reminded, tried)."""
    with system_ctx(c):
        rows = c.execute("SELECT * FROM users WHERE delete_at IS NOT NULL ORDER BY delete_at, id LIMIT 50").fetchall()
    c.commit()
    now = now_utc()
    for u in rows:
        try:
            at = parse_iso(u["delete_at"])
        except (TypeError, ValueError):
            at = now
        plan = sdl_plan(u)
        if not u["disabled"]:  # an admin enabled the account again: the deletion is off
            with system_ctx(c):
                _lift(c, u)
            c.commit()
            continue
        if at <= now:
            tried = plan.get("tried")
            if tried and parse_iso(tried) + SDL_RETRY > now:
                continue
            sdl_run(c, u["id"])
            continue
        if at - SDL_REMIND <= now and not plan.get("reminded"):
            tok = secrets.token_urlsafe(24)
            plan["toks"] = (plan.get("toks") or [])[-3:] + [tkh_hash(tok)]
            plan["reminded"] = iso(now)
            with system_ctx(c):  # the watchdog notes the reminder in the person's own row (no request, nobody signed in)
                c.execute("UPDATE users SET delete_plan=? WHERE id=?", (json.dumps(plan), u["id"]))
            c.commit()
            sdl_mail(c, u["id"], "remind", f"{u['id']}.{tok}")


WD_TICKS.append(("own account deletions", sdl_tick))
