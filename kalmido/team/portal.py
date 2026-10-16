"""2.63.0 (#1513): customer reports and the customer portal (module "portal").

A form with "status link" on (forms.portal, team/forms.py) turns a sent report into a ticket: the task (type from forms.ttype,
e.g. 'bug') plus one portal_tickets row. The reporter gets a status link /p/<token> (192 random bits, stored sealed so it can
be sent again, looked up by its SHA-256) on the thank-you page and by mail. The status page shows only that ticket: title,
state, the public answers and the reporter's own comments (comments.portal = 1); internal comments (portal = 0) never leave
the app. From there (or the form) the reporter can ask for a sign-in link by mail and then sees all their tickets of the same
space (org_id, or owner_id for a list without organisation) -- never another space's, never another person's.

The space and the e-mail are the whole identity of a reporter: there is no account. The e-mail is stored sealed (server key)
and as a keyed hash (pt_email_hash) for the sign-in lookup, so the table does not hold readable addresses.

Shared helpers (leader, 2.63.0): part A (the form) calls pt_create; part B (status page, portal, answers, mails, office
client) fills the rest of this module. Keep the signatures; a changed contract goes into iface.txt."""
import hashlib
import hmac
import re
import secrets

from ..core.config import PUBLIC_URL
from ..core.db import iso, now_utc
from ..core.pg import insert_id
from ..accounts.session import _token_hash
from ..accounts.login import auth_key, seal, unseal

PT_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
PT_EMAIL_MAX = 200


def pt_email_norm(email):
    """The form of an address that identifies a reporter ('' when it is no address)."""
    e = (email or "").strip().lower()[:PT_EMAIL_MAX]
    return e if re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", e) else ""


def pt_email_hash(c, email):
    """Keyed hash of an address (server key): the portal finds a reporter's tickets without readable addresses."""
    e = pt_email_norm(email)
    return hmac.new(auth_key(c), b"kalmido-portal-email|" + e.encode(), hashlib.sha256).hexdigest() if e else ""


def pt_status_url(token):
    return f"{PUBLIC_URL}/p/{token}"


def pt_create(c, task_id, list_row, form_id=None, name="", email="", client_id=None):
    """A reported task becomes a ticket: one portal_tickets row in the list's space. list_row needs id, org_id, owner_id.
    Returns (ticket id, token); the token is only in the status link. The caller commits."""
    tok = secrets.token_urlsafe(24)
    e = pt_email_norm(email)
    ts = iso(now_utc())
    tid = insert_id(c, """INSERT INTO portal_tickets(task_id,list_id,org_id,owner_id,form_id,client_id,name,email,email_hash,token,token_hash,
                          notify,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id, list_row["id"], list_row["org_id"], None if list_row["org_id"] else list_row["owner_id"], form_id, client_id,
                     (name or "")[:120], seal(c, "portal-email", e) if e else "", pt_email_hash(c, e) if e else "",
                     seal(c, "portal-token", tok), _token_hash(tok), 1 if e else 0, ts))
    return tid, tok


def pt_email(c, row):
    """The reporter's address of a portal_tickets row ('' when none was given)."""
    return unseal(c, "portal-email", row["email"]) if row["email"] else ""


def pt_token(c, row):
    """The status-link token of a portal_tickets row (to send the link again)."""
    return unseal(c, "portal-token", row["token"])
