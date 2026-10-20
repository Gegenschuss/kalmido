"""2.138.0 C (#1907): the personal upload token (POST /drop) and the calendar feed secret (GET /ical/<uid>.<secret>.ics)
are kept only as a SHA-256 hash (users.drop_token_hash / users.ical_token_hash). The plain value is shown once, when it
is created; afterwards nobody can read it back. Both are long random values (token_urlsafe 24 / 32 bytes), so a plain
hash is enough (no password hash). The old plain columns stay (always NULL) so the version before runs on."""
import hashlib
import hmac
import secrets

from .db import iso, now_utc

TKH_DROP_BYTES, TKH_ICAL_BYTES = 24, 32


def tkh_hash(tok):
    """Hex SHA-256 of a token ('' / None -> None)."""
    return hashlib.sha256(tok.encode()).hexdigest() if tok else None


def tkh_match(tok, stored):
    """Constant-time check of a presented token against a stored hash."""
    return bool(tok and stored) and hmac.compare_digest(tkh_hash(tok), stored)


def tkh_set_drop(c, uid, tok=None):
    """A new upload token for uid (or the given one, e.g. TASKS_DROP_TOKEN); the old one stops working. Returns it."""
    tok = tok or secrets.token_urlsafe(TKH_DROP_BYTES)
    c.execute("UPDATE users SET drop_token=NULL, drop_token_hash=?, drop_token_at=? WHERE id=?", (tkh_hash(tok), iso(now_utc()), uid))
    return tok


def tkh_set_ical(c, uid):
    """A new calendar feed secret for uid; the old address stops working. Returns the secret."""
    tok = secrets.token_urlsafe(TKH_ICAL_BYTES)
    c.execute("UPDATE users SET ical_token=NULL, ical_token_hash=?, ical_token_at=? WHERE id=?", (tkh_hash(tok), iso(now_utc()), uid))
    return tok


def tkh_migrate(c):
    """At every start (idempotent): plain tokens left in users (from before 2.138, or written by an older version after a
    roll-back) become hashes and the plain value is removed. Existing shortcuts and calendar subscriptions keep working."""
    n = 0
    for r in c.execute("SELECT id, drop_token, ical_token FROM users WHERE drop_token IS NOT NULL OR ical_token IS NOT NULL").fetchall():
        sets, args = ["drop_token=NULL", "ical_token=NULL"], []
        if r["drop_token"]:
            sets.append("drop_token_hash=?")
            args.append(tkh_hash(r["drop_token"]))
        if r["ical_token"]:
            sets.append("ical_token_hash=?")
            args.append(tkh_hash(r["ical_token"]))
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*args, r["id"]))
        n += 1
    if n:
        print("tokens: stored", n, "accounts' upload / calendar tokens as hashes", flush=True)
    return n
