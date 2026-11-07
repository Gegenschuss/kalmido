"""Kalmido: id reservations for records encrypted in the browser (2.640.0, #3388, AAD v2).

A v2 ciphertext binds the id of its record (a wiki page, a list channel message) in its associated data, so the browser
needs that id before it encrypts. The server hands out the next value of the table's id sequence with a mark: an HMAC with
the server's sign-in key over kind, scope (the space / the room), the person and the id, plus the time. The record is then
stored under exactly that id, only by that person in that scope, only within E2R_TTL seconds and only once (the id must
still be free). No table: the sequence never hands the same value out twice, unused ids are gaps.
Guessing an id or taking another person's reservation fails the mark; a reservation of another space / room fails it too."""
import hashlib
import hmac
import time

from ..accounts.login import auth_key

E2R_TTL = 900  # seconds a reservation stays valid (the browser encrypts and sends right after asking)
_E2R_TABLES = {"wiki": "wiki_pages", "chan": "tchat_msgs"}


def _e2r_mac(c, kind, scope, uid, rid, ts):
    msg = f"kalmido-e2eresv:v1:{kind}:{scope}:{uid}:{rid}:{ts}".encode()
    return hmac.new(auth_key(c), msg, hashlib.sha256).hexdigest()


def e2r_new(c, kind, scope, uid):
    """A new reservation -> {id, resv} (resv = "<unix time>.<mark>")."""
    t = _E2R_TABLES[kind]
    rid = int(c.execute(f"SELECT nextval(pg_get_serial_sequence('{t}', 'id'))").fetchone()[0])
    ts = int(time.time())
    return {"id": rid, "resv": f"{ts}.{_e2r_mac(c, kind, scope, uid, rid, ts)}"}


def e2r_ok(c, kind, scope, uid, rid, tok):
    """True when tok is a valid, unexpired reservation of id rid for (kind, scope, uid) and the id is still free."""
    if isinstance(rid, bool) or not isinstance(rid, int) or rid < 1 or not isinstance(tok, str) or len(tok) > 100:
        return False
    ts, _, mac = tok.partition(".")
    if not ts.isdigit() or not mac:
        return False
    age = time.time() - int(ts)
    if not -60 <= age <= E2R_TTL:
        return False
    if not hmac.compare_digest(mac, _e2r_mac(c, kind, scope, uid, rid, int(ts))):
        return False
    return c.execute(f"SELECT 1 FROM {_E2R_TABLES[kind]} WHERE id=?", (rid,)).fetchone() is None
