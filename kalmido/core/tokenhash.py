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
    return n + tkh_migrate_evfeeds(c)


def tkh_set_evfeed(c, fid=None, cal_id=None, uid=None):
    """2.577.0 (#4708 6): a new secret for an event calendar's subscription link: row fid gets it (the old address stops at
    once), else a new row for (cal_id, uid). Only its hash is stored. Returns the secret (shown once)."""
    tok = secrets.token_urlsafe(TKH_ICAL_BYTES)
    if fid:
        c.execute("UPDATE ev_cal_feeds SET secret='', secret_hash=?, created_at=? WHERE id=?", (tkh_hash(tok), iso(now_utc()), fid))
    else:
        c.execute("INSERT INTO ev_cal_feeds(cal_id, user_id, secret, secret_hash, created_at) VALUES(?,?,'',?,?)",
                  (cal_id, uid, tkh_hash(tok), iso(now_utc())))
    return tok


def tkh_evfeed_match(c, r, tok):
    """2.577.0 (#4708 6): does tok open the event calendar link row r? Against the stored hash; a plain secret still in the
    row (written after this start, e.g. by an older version after a roll-back) is compared in constant time and stored as
    a hash at once, so the link keeps working and the plain value goes."""
    if tkh_match(tok, r["secret_hash"]):
        return True
    plain = r["secret"] or ""
    if not (tok and plain) or not hmac.compare_digest(plain.encode(), tok.encode()):
        return False
    try:  # storing the hash is a tidy-up: the link opens even if this write fails (the next start hashes it)
        c.execute("UPDATE ev_cal_feeds SET secret='', secret_hash=? WHERE id=? AND secret=?", (tkh_hash(plain), r["id"], plain))
        c.commit()
    except Exception:  # noqa: BLE001
        c.rollback()
    return True


def tkh_migrate_evfeeds(c):
    """2.577.0 (#4708 6), at every start (idempotent): the plain secrets of the event calendars' links (from before 2.577, or
    written by an older version after a roll-back) become hashes, the plain value goes. The links keep working. A one-way
    step: a version before 2.577 no longer opens these links (they answer 404 there until a new link is made)."""
    n = c.execute("UPDATE ev_cal_feeds SET secret_hash=encode(sha256(convert_to(secret, 'UTF8')), 'hex'), secret='' "
                  "WHERE secret<>''").rowcount
    if n:
        print("tokens: stored", n, "event calendar links as hashes", flush=True)
    return n
