"""2.266.0 (#2963): security mails to the person whose account changed - so a taken-over account does not stay unnoticed.
Until 2.266 only the instance admins heard of such events (admin alerts); the person got nothing. Now a short mail goes
to the account's address (the old AND the new one when the address changes), in the person's language, without a way to
unsubscribe (like the password reset), with a link to Settings > Account (password, two-factor sign-in):
  password        the person changed their password             password_admin  an admin set / removed it
  password_reset  a password was set through a reset link        email           the address was changed (old + new)
  2fa_off         two-factor sign-in (app codes) was turned off   2fa_reset       an admin reset two-factor sign-in
  passkey         a passkey was removed                          codes           new recovery codes were made
  code_used       a recovery code was used to sign in            login           a sign-in from a new device / browser
  disabled        an admin deactivated the account               approved        an admin approved the registration
Nothing without outgoing e-mail (MAIL_OUT_ON), for agents or without an address. The mail goes out in the background
(bgjobs kind "mail:security", one try: never twice; integrations/mail.py registers it) after the request. A new device = a browser (User-Agent) that is not among the last
SEC_DEVICES of the account (setting sec_devices, hashes only); the first sign-in after the update only stores it."""
import hashlib
import ipaddress
import json

from ..core.config import APP_NAME, PUBLIC_URL
from ..core.db import uset, usettings
from ..core.db import db_log_err  # 2.239.0 B (#2888): no values of database errors in the log
from ..core.i18n import N_, lang, tr
from ..core.mailframe import mail_html
from .bgjobs import BGJ_FNS, bgj_add

SEC_DEVICES = 10
SEC_EVENTS = {
    "password": (N_("Your password was changed"), N_("The password of your account {0} was changed.")),
    "password_admin": (N_("Your password was changed"), N_("An admin changed the password of your account {0}.")),
    "password_reset": (N_("Your password was reset"), N_("A new password was set for your account {0} through a reset link.")),
    "email": (N_("Your e-mail address was changed"), N_("The e-mail address of your account {0} was changed from {1} to {2}.")),
    "2fa_off": (N_("Two-factor sign-in was turned off"), N_("Sign-in codes from an authenticator app were turned off for your account {0}.")),
    "2fa_reset": (N_("Two-factor sign-in was reset"), N_("An admin reset the two-factor sign-in of your account {0}: app codes, passkeys and recovery codes are gone.")),
    "passkey": (N_("A passkey was removed"), N_("The passkey “{1}” was removed from your account {0}.")),
    "codes": (N_("New recovery codes"), N_("New recovery codes were made for your account {0}; the old ones no longer work.")),
    "code_used": (N_("A recovery code was used"), N_("Someone signed in to your account {0} with a recovery code ({1} left).")),
    "login": (N_("New sign-in to your account"), N_("Your account {0} was signed in from a new device: {1}, address {2}.")),
    "disabled": (N_("Your account was deactivated"), N_("An admin deactivated your account {0}. You can no longer sign in.")),
    "approved": (N_("Your account is approved"), N_("An admin approved your registration: you can sign in with your account {0} now.")),
}
SEC_NOT_ME = N_("If that was not you: change your password right away and tell an admin.")


def sec_ua_label(ua, lg=None):
    """'Firefox on Android' from a User-Agent (rough: browser + system), '' when unknown."""
    ua = ua or ""
    osn = next((n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                                ("Mac OS X", "macOS"), ("Macintosh", "macOS"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if k in ua), "")
    br = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("FxiOS", "Firefox"),
                               ("CriOS", "Chrome"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if k in ua), "")
    return tr("{0} on {1}", br, osn, lg=lg) if br and osn else br or osn or (ua[:60] if ua else "?")


def sec_content(c, uid, ev, args, lg):
    """(subject, text, html) of event ev for uid in language lg."""
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    subj, msg = SEC_EVENTS[ev]
    u = c.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    line = t(msg, (u["username"] if u else "?"), *args)
    link = f"{PUBLIC_URL}/" if ev == "approved" else f"{PUBLIC_URL}/#settings/account"
    lines = [line] + ([] if ev == "approved" else [t(SEC_NOT_ME)])
    subject = f"{APP_NAME}: {t(subj)}"
    text = "\n\n".join(lines) + f"\n\n{link}\n"
    button = t(N_("Open {0}"), APP_NAME) if ev == "approved" else t(N_("Security settings"))
    return subject, text, mail_html(subject, lines, button, link, lang=lg)  # 2.420.0 B (#3499): the shared mail frame


def sec_mask_ip(ip):
    """An address as the mail shows it (like the admin alerts): IPv4 without its last octet, IPv6 its first 48 bits."""
    try:
        a = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return "?"
    a = a.ipv4_mapped or a if a.version == 6 else a
    if a.version == 4:
        return str(a).rsplit(".", 1)[0] + ".x"
    return f"{ipaddress.ip_network(f'{a}/48', strict=False).network_address}/48"


def sec_mail(c, uid, ev, *args, to=None, also=None):
    """Queue the security mail ev to uid's address (to: another one, also: one more, e.g. the new address). Never raises."""
    try:
        if "mail:security" not in BGJ_FNS or ev not in SEC_EVENTS:  # registered by integrations/mail.py with outgoing mail only
            return False
        u = c.execute("SELECT email, kind FROM users WHERE id=?", (uid,)).fetchone()
        if not u or (u["kind"] or "user") == "agent":
            return False
        addrs = []
        for a in (to if to is not None else u["email"], also):
            a = (a or "").strip()
            if a and a.lower() not in [x.lower() for x in addrs]:
                addrs.append(a)
        if not addrs:
            return False
        m = sec_content(c, uid, ev, [str(x) for x in args], lang(c, uid))
        for a in addrs:
            bgj_add("mail:security", a, *m, user_id=uid, delay=1.0)
        return True
    except Exception as e:  # noqa: BLE001 - a security mail never breaks the action itself
        print("security mail not queued:", ev, db_log_err(e), flush=True)
        return False


def sec_login(c, uid, via, ua, ip):
    """start_session: a sign-in from a browser not among the account's last SEC_DEVICES -> mail "login". Never raises."""
    try:
        if via == "restore" or not ua:
            return
        h = hashlib.sha256(ua.encode("utf-8", "replace")).hexdigest()[:20]
        try:
            known = json.loads(usettings(c, uid).get("sec_devices") or "[]")
            known = [x for x in known if isinstance(x, str)] if isinstance(known, list) else []
        except ValueError:
            known = []
        if known and known[0] == h:
            return
        with c.savepoint():  # a database error here never aborts the sign-in
            uset(c, uid, "sec_devices", json.dumps(([h] + [x for x in known if x != h])[:SEC_DEVICES]))
        if known and h not in known:
            sec_mail(c, uid, "login", sec_ua_label(ua, lang(c, uid)), sec_mask_ip(ip) if ip else "?")  # review: the person's language
    except Exception as e:  # noqa: BLE001
        print("new device check skipped:", db_log_err(e), flush=True)
