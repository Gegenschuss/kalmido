"""2.1033.0 (#5790): a person proves the own e-mail address (Settings > Account > E-mail address, "Confirm address").

Since 2.1021.0 (#5775) an organisation's invitation by address, "E-mails from my own address" and replies by mail count only
for a proved address (users.email_proved). It was proved by an invitation / reset link that went out by mail, a confirmed
registration or a verified OIDC claim - an account the admin typed in (the first admin's, too) had no way to prove it. Here:

 - GET /api/me/email -> {email, proved, mail_out}: the own address and whether it is proved
 - POST /api/me/email/proof: a mail with a one-time link (/#mailproof/<token>, EPF_HOURS) to the address the account has now.
   The token is short-lived state (core/ephem.py, ns "eproof": only its HMAC is stored, the address sealed), one per account
   (a new mail replaces the older link), at most EPF_PER_HOUR mails an hour plus the daily mail budget.
 - POST /api/me/email/proof/confirm {token}: proves the address - only signed in as the account the link was made for
   (eph_take with uid: a link opened by somebody else, signed in as somebody else, changes nothing for either account) and
   only while the account still has the address the mail went to. Then the silent organisation invitations of exactly this
   address (org_joins.silent with org_joins.email, #5775 / #4922) wake up as ordinary ones (orginvite.ojn_proved): the person
   hears of them now, unless the rule of a company of its own (#3570) keeps one silent.
Never for an agent (its address is its owner's business); a person without an organisation proves the address the same way."""
from flask import jsonify

from ..core.config import app, APP_NAME, PUBLIC_URL
from ..core.db import body, bump, db, err
from ..core.ephem import eph_put, eph_take
from ..core.i18n import lang, N_, tr
from ..accounts.login import seal, unseal
from ..accounts.session import me
from ..api.common import hit_limit
from ..agents.core import need_person

EPF_NS = "eproof"
EPF_HOURS = 48  # the link works this long (and once)
EPF_PER_HOUR = 3  # proof mails per account and hour (each counts in the daily mail budget, too)
EPF_TRIES = 10  # wrong / old links per account and hour


def _addr(u):
    return (u["email"] or "").strip().lower()


@app.get("/api/me/email")
def eproof_get():
    from ..integrations.mail import MAIL_OUT_ON
    need_person(403)
    c = db()
    u = c.execute("SELECT email, email_proved FROM users WHERE id=?", (me(),)).fetchone()
    em = _addr(u)
    return jsonify(email=u["email"] or "", proved=bool(em) and (u["email_proved"] or "") == em, mail_out=bool(MAIL_OUT_ON))


def eproof_mail(c, u, link):
    """(subject, text, html) of the proof mail in the person's language (the shared mail frame)."""
    from ..core.mailframe import mail_html
    lg = lang(c, u["id"])
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    subject = t(N_("Confirm your e-mail address for {0}"), APP_NAME)
    head = t(N_("Hello {0},"), u["display_name"] or u["username"])
    intro = t(N_("please confirm that {0} is your address: open the link while you are signed in to {1} as {2}."), u["email"], APP_NAME, u["username"])
    why = t(N_("Then invitations of organisations to this address reach you, and e-mails you send from it can become tasks for you."))
    button = t(N_("Confirm my address"))
    valid = t(N_("The link works once and for {0} days."), EPF_HOURS // 24)
    foot = t(N_("Did you not ask for this? Then ignore this e-mail: nothing changes."))
    body_html = mail_html(subject, [intro, why], button, link, foot, head, lang=lg, note=valid)
    text = "\n".join([head, "", intro, why, "", f"{button}: {link}", valid, "", foot, ""])
    return subject, text, body_html


@app.post("/api/me/email/proof")
def eproof_send():
    """A mail with a one-time link to the account's address (not when it is proved already: {ok, proved: true})."""
    import secrets
    from ..admin.hosting import mail_budget
    from ..integrations.mail import MAIL_OUT_ON, mail_send
    need_person(403)
    c = db()
    u = c.execute("SELECT id, username, display_name, email, email_proved FROM users WHERE id=?", (me(),)).fetchone()
    em = _addr(u)
    if not em:
        return err(tr("No e-mail address is stored for you: an admin adds it (Settings > Organisation > People)"), 409)
    if (u["email_proved"] or "") == em:
        return jsonify(ok=True, proved=True, email=u["email"])
    if not MAIL_OUT_ON:
        return err(tr("E-mail sending is not set up on this server"), 409)
    if hit_limit(f"eproof:{me()}", EPF_PER_HOUR, 3600):
        return err(tr("Too many attempts, please wait a few minutes"), 429)
    if not mail_budget(c, me(), em):
        c.rollback()
        return err(tr("Today's e-mail limit is reached. Try again tomorrow."), 429)
    tok = secrets.token_urlsafe(32)
    if not eph_put(EPF_NS, tok, seal(c, f"eproof:{me()}", em), EPF_HOURS * 3600, uid=me(), caps={"uid": 1}):  # one link per account
        c.rollback()
        return err(tr("The e-mail could not be sent. Try again later."), 503)
    c.commit()  # the mail count; no transaction stays open while the mail server is asked
    subject, text, body_html = eproof_mail(c, u, f"{PUBLIC_URL}/#mailproof/{tok}")
    try:
        mail_send(u["email"], subject, text, body_html, from_name=APP_NAME)
    except Exception as e:  # noqa: BLE001 -- the mail server said no: the link is of no use, the person may try again
        print("address proof mail failed:", type(e).__name__, flush=True)
        return err(tr("The e-mail could not be sent. Try again later."), 502)
    print("address proof mail sent to account", me(), flush=True)
    return jsonify(ok=True, sent=True, email=u["email"])


@app.post("/api/me/email/proof/confirm")
def eproof_confirm():
    """{token}: the link of the proof mail, opened signed in as its account -> {ok, proved, invitations: n woken}."""
    from ..accounts.orginvite import ojn_proved
    need_person(403)
    tok = body().get("token")
    bad = err(tr("This link is invalid or has expired. Ask for a new one."), 404)
    if hit_limit(f"eproof-try:{me()}", EPF_TRIES, 3600):
        return err(tr("Too many attempts, please wait a few minutes"), 429)
    if not isinstance(tok, str) or not 20 <= len(tok) <= 100:
        return bad
    v = eph_take(EPF_NS, tok, uid=me())  # another account's request leaves the link alone
    if v is None:
        return bad
    c = db()
    try:
        sent_to = unseal(c, f"eproof:{me()}", v)
    except Exception:  # noqa: BLE001 -- another server key / damaged value: like an old link
        return bad
    u = c.execute("SELECT email, email_proved FROM users WHERE id=?", (me(),)).fetchone()
    em = _addr(u)
    if not em or em != sent_to:  # the address changed after the mail: it proves the old one, not this
        return err(tr("Your e-mail address changed after this link was sent. Ask for a new one."), 409)
    n = 0
    if (u["email_proved"] or "") != em:
        c.execute("UPDATE users SET email_proved=? WHERE id=?", (em, me()))
        n = ojn_proved(c, me(), em)
        bump(c)
        c.commit()
        print("address proved by mail: account", me(), "woke", n, "invitation(s)", flush=True)
    return jsonify(ok=True, proved=True, email=u["email"], invitations=n)
