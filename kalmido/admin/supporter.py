"""2.74.0 (#338): the supporter licence (like Immich): voluntary, once, unlocks NOTHING -- it only shows a small badge.

Self-hosted servers only: with KALMIDO_HOSTED=1 every route answers 404 and /api/about carries none of the fields.
Two kinds: "server" (the instance; admins enter / remove it, stored in the instance settings) and "person" (the own
account, every person for themself, stored in the user settings). A key is checked offline against the Ed25519 public
key(s) below (no network): KSUP1.<base64url JSON>.<base64url signature>, JSON {"t": "server"|"person", "d": "YYYY-MM-DD",
"id": "<label>"}; tools/supporter_key.py makes the keys. The raw key never leaves the server (no logs, no error text, no
answer): clients get the kind, the date and the label only.
Removing keeps the key one step back (sup_*_prev) so "Undo" can bring it back without the client ever holding the key:
POST .../swap exchanges the current and the previous key (undo / redo of entering and removing alike).
The quiet hint: at most once a year, admins only, not in the first 30 days of the instance, only while neither a server
licence nor an own licence exists, switchable off (user setting sup_nudge = 0; sup_nudge_at = the day it was shown)."""
import base64
import json
import os
import re
from datetime import date, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from flask import g, jsonify

from ..core.config import app
from ..core.access import Denied
from ..core.db import body, db, err, gset, gsetting, uset, usettings
from ..core.i18n import tr
from ..accounts.session import me

SUP_PREFIX = "KSUP1"
SUP_MAX_LEN = 600  # a real key is about 200 characters
SUP_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
SUP_KINDS = ("server", "person")
# The public key of the Kalmido supporter licences (the private key never is in this repository).
SUP_PUBKEYS = ("o/j0qVKWZYnOjU010nb8J5dzohrOzQ2xU2brex/7Dh4=",)
# Further trusted public keys (comma separated, base64) -- the test suites sign their own keys with it. Harmless: a
# licence unlocks nothing, it only shows the badge.
SUP_EXTRA_ENV = os.environ.get("KALMIDO_SUPPORTER_EXTRA_PUBKEYS", "")
SUP_URL_ENV = os.environ.get("KALMIDO_SUPPORT_URL", "").strip()
# 2.144.0 D (#2158): the purchase page on the website. Used only when KALMIDO_SUPPORT_URL=default (or once SUP_SHOP_LIVE is
# switched on in a release, when the payment provider's account exists): until then no buy button points anywhere.
SUP_SHOP_URL = "https://kalmido.com/support.html"
SUP_SHOP_LIVE = False
# 2.144.0 D (#2158): the prices (once, VAT included, voluntary); shown in the dialog. Whole euros.
SUP_PRICES = {"person": 25, "server": 100}
SUP_CURRENCY = "EUR"
SUP_NUDGE_DAYS = 365
SUP_QUIET_DAYS = 30  # no hint in the first days after the instance was set up


def sup_url():
    """KALMIDO_SUPPORT_URL if it is a plain https:// address ('' otherwise: then only the explanation is shown);
    "default" = the purchase page on the website (2.144.0 D, #2158)."""
    u = SUP_URL_ENV
    if u.lower() == "default" or (not u and SUP_SHOP_LIVE):  # 2.144.0 D (#2158)
        u = SUP_SHOP_URL
    if len(u) > 500 or not re.fullmatch(r"https://[^\s\"'<>\\]+", u):
        return ""
    return u


def sup_pubkeys():
    out = []
    for k in SUP_PUBKEYS + tuple(x.strip() for x in SUP_EXTRA_ENV.split(",") if x.strip()):
        try:
            out.append(Ed25519PublicKey.from_public_bytes(base64.b64decode(k, validate=True)))
        except (ValueError, TypeError):
            print("supporter: ignored a public key that is not 32 bytes base64", flush=True)
    return out


SUP_KEYS = sup_pubkeys()


def _unb64u(s):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", s or ""):
        raise ValueError("base64url")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sup_parse(raw):
    """A licence key -> {t, d, id}; None if it is not a valid, correctly signed key (never says why: no oracle needed)."""
    if not isinstance(raw, str) or len(raw) > SUP_MAX_LEN * 2:
        return None
    key = "".join(raw.split())  # pasted with line breaks / spaces
    if not key or len(key) > SUP_MAX_LEN:
        return None
    parts = key.split(".")
    if len(parts) != 3 or parts[0] != SUP_PREFIX:
        return None
    try:
        sig, payload = _unb64u(parts[2]), _unb64u(parts[1])
    except ValueError:
        return None
    signed = (parts[0] + "." + parts[1]).encode()
    ok = False
    for pk in SUP_KEYS:
        try:
            pk.verify(sig, signed)
            ok = True
            break
        except InvalidSignature:
            continue
    if not ok:
        return None
    try:
        j = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(j, dict) or j.get("t") not in SUP_KINDS or not isinstance(j.get("d"), str) or not isinstance(j.get("id"), str):
        return None
    try:
        date.fromisoformat(j["d"])
    except ValueError:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", j["d"]) or not SUP_ID_RE.fullmatch(j["id"]):
        return None
    return {"t": j["t"], "d": j["d"], "id": j["id"]}


def sup_info(raw, kind):
    """The public part of a stored key ({kind, date, id}) or None (empty, broken, or of the other kind)."""
    p = sup_parse(raw) if raw else None
    if not p or p["t"] != kind:
        return None
    return {"kind": kind, "date": p["d"], "id": p["id"]}


def sup_server(c):
    return sup_info(gsetting(c, "sup_server_key"), "server")


def sup_person(c, uid):
    return sup_info(usettings(c, uid).get("sup_key") or "", "person")


def _instance_age_days(c):
    r = c.execute("SELECT MIN(created_at) FROM users").fetchone()
    try:
        return (date.today() - date.fromisoformat(str(r[0])[:10])).days if r and r[0] else 0
    except ValueError:
        return 0


def sup_nudge_due(c, u, s=None):
    """The quiet yearly hint is due for this person now (admins only, never on a hosted server)."""
    from .hosting import hosted
    if hosted() or not u or not u["is_admin"]:
        return False
    s = s or usettings(c, u["id"])
    if s.get("sup_nudge") == "0" or sup_server(c) or sup_info(s.get("sup_key") or "", "person"):
        return False
    if _instance_age_days(c) < SUP_QUIET_DAYS:
        return False
    try:
        last = date.fromisoformat((s.get("sup_nudge_at") or "")[:10])
    except ValueError:
        return True
    return date.today() - last >= timedelta(days=SUP_NUDGE_DAYS)


def sup_about(c, u):
    """The fields /api/about adds on a self-hosted server ({} on a hosted one: the fields are missing entirely)."""
    from .hosting import hosted
    if hosted():
        return {}
    d = {"supporter": sup_server(c), "support_url": sup_url(),
         "support_prices": {"currency": SUP_CURRENCY, **SUP_PRICES}}  # 2.144.0 D (#2158)
    if u:
        s = usettings(c, u["id"])
        d["supporter_me"] = sup_info(s.get("sup_key") or "", "person")
        if u["is_admin"]:
            d.update(sup_nudge_on=s.get("sup_nudge") != "0", sup_nudge=sup_nudge_due(c, u, s))
    return d


def _gate(kind=None):
    from .hosting import hosted
    from ..agents.core import is_agent
    if hosted():
        raise Denied(404)
    if is_agent(g.user):
        raise Denied(403)
    if kind not in (None, *SUP_KINDS):
        raise Denied(404)
    if kind == "server":
        from ..accounts.users import need_admin
        need_admin()


def _out(c):
    return jsonify(sup_about(c, g.user))


def _get(c, kind, slot=""):
    return gsetting(c, "sup_server_key" + slot) if kind == "server" else (usettings(c, me()).get("sup_key" + slot) or "")


def _put(c, kind, slot, v):
    if kind == "server":
        gset(c, "sup_server_key" + slot, v)
    else:
        uset(c, me(), "sup_key" + slot, v)


@app.get("/api/supporter")
def sup_get():
    _gate()
    return _out(db())


@app.put("/api/supporter/<kind>")
def sup_set(kind):
    """{key}: enter a licence of this kind (server: admins). A wrong / broken / other-kind key: 400, nothing stored."""
    _gate(kind)
    raw = body().get("key")
    p = sup_parse(raw) if isinstance(raw, str) else None
    if not p:
        return err(tr("This is not a valid supporter key."))
    if p["t"] != kind:
        return err(tr("This is a personal licence: enter it under your own licence.") if p["t"] == "person"
                   else tr("This is a server licence: an admin enters it for the whole server."))
    c = db()
    cur = _get(c, kind)
    _put(c, kind, "_prev", cur)
    _put(c, kind, "", "".join(raw.split()))
    c.commit()
    return _out(c)


@app.delete("/api/supporter/<kind>")
def sup_del(kind):
    _gate(kind)
    c = db()
    cur = _get(c, kind)
    if cur:
        _put(c, kind, "_prev", cur)
        _put(c, kind, "", "")
        c.commit()
    return _out(c)


@app.post("/api/supporter/<kind>/swap")
def sup_swap(kind):
    """Undo / redo: the current and the previous key change places (the previous one is checked again)."""
    _gate(kind)
    c = db()
    cur, prev = _get(c, kind), _get(c, kind, "_prev")
    if prev and not sup_info(prev, kind):
        prev = ""
    _put(c, kind, "", prev)
    _put(c, kind, "_prev", cur)
    c.commit()
    return _out(c)


@app.patch("/api/supporter/nudge")
def sup_nudge():
    """{on?: bool} the yearly hint on / off (admins; a person setting); {seen: true} it was shown now."""
    _gate()
    from ..accounts.users import need_admin
    need_admin()
    b, c = body(), db()
    if "on" in b:
        if not isinstance(b["on"], bool):
            return err(tr("Invalid value: {0}", "on"))
        uset(c, me(), "sup_nudge", "1" if b["on"] else "0")
    if b.get("seen") is True:
        uset(c, me(), "sup_nudge_at", date.today().isoformat())
    c.commit()
    return _out(c)
