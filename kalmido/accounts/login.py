"""Password login, first setup, logout and two-factor authentication (TOTP, recovery codes, passkeys)."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import segno
import webauthn
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from webauthn.helpers import structs as wa_structs
from flask import g, jsonify, request
from werkzeug.security import check_password_hash

from ..core.config import app, APP_NAME, COOKIE, MIN_PASSWORD, NTFY_TOPIC, PUBLIC_URL, USERNAME_RE
from ..core.i18n import lang, languages, N_, tr
from ..core.db import adopt_orphans, body, bump, create_user, db, ensure_inbox, err, gset, gsetting, iso, now_utc
from ..accounts.session import (
    _accept_lang, _DUMMY_HASH, _peer_trusted, _rate_blocked, _rate_fail, _rate_keys, _rate_reset, _token_hash,
    client_ip, FAIL_WINDOW, proxy_login_value, set_cookie, start_session, user_public,
)


@app.get("/api/auth/info")
def auth_info():
    """What the login screen needs (open): setup needed?, language, why a proxy login failed, the extra
    login buttons (OIDC provider, passkey)."""
    from ..accounts.oidc import oidc_cfg, OIDC_ERRORS
    c = db()
    setup = not c.execute("SELECT 1 FROM users").fetchone()
    # 2.11.0 (#439): before login the browser's language wins (first setup: else English; login: else the admin's)
    return jsonify(setup=setup, lang=lang() if g.user else _accept_lang("en" if setup else lang()),
                   languages=languages(), user=user_public(g.user) if g.user else None,
                   auth_error=g.auth_error, login=g.proxy_login or proxy_login_value(),
                   oidc={"label": oidc_cfg(c)["label"]} if oidc_cfg(c)["on"] else None, passkey_login=gsetting(c, "passkey_login") != "0",
                   login_errors={k: tr(v) for k, v in OIDC_ERRORS.items()} if oidc_cfg(c)["on"] else {},
                   org=_org_label(c),  # 2.22.0 (#752): the instance's organisation (only when there is exactly one)
                   signup=_signup_info(c))  # 2.23.0 (#711): registration on the login page (None = off)


def _signup_info(c):
    from ..accounts.signup import signup_info
    return signup_info(c)


def _org_label(c):
    from ..accounts.orgs import org_label
    return org_label(c)


def finish_login(c, u, remember, via, extra=None):
    """Last step of every login: ends the session this browser brought along (if any), starts a new one, resets
    the failure counter of the user name."""
    old = request.cookies.get(COOKIE)
    if old:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(old),))
    _rate_reset(u["username"])
    tok, age = start_session(c, u["id"], remember, via)
    c.commit()
    resp = set_cookie(jsonify(ok=True, user=user_public(u), **(extra or {})), tok, age)
    resp.delete_cookie(PEND_COOKIE, path="/api/auth")
    return resp


@app.post("/api/auth/login")
def auth_login():
    from ..notify.alerts import aa_count, aa_now
    from ..agents.core import is_agent
    b = body()
    username = (b.get("username") or "").strip().lower()
    keys = _rate_keys(username)
    if _rate_blocked(keys):
        return err(tr("Too many failed logins, please wait a few minutes"), 429)
    c = db()
    u = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    pw = b.get("password") if isinstance(b.get("password"), str) else ""
    # exactly one hash check on every path (unknown user / no password: a real hash of the same kind)
    pw_ok = check_password_hash(u["password_hash"] if u and u["password_hash"] else _DUMMY_HASH, pw)
    ok = bool(u and u["password_hash"] and not u["disabled"] and pw_ok and not is_agent(u))
    if not ok and u and pw_ok and u["password_hash"] and u["disabled"] and u["signup"] == "pending":
        # 2.23.0 (#711): the right password of a registration that waits for an admin (says nothing to anyone else)
        return err(tr("Your account waits for an admin to approve it.", lg=_accept_lang(lang())), 403)
    if not ok:
        # admin alerts: only real usernames are named (a typo in the name field could be a password)
        for k in _rate_fail(keys):
            if k.startswith("ip:"):
                aa_now("security", "ratelimit:" + k, N_("Login rate limit reached for IP {0} (logins refused for {1} min)."),
                       [client_ip(), FAIL_WINDOW // 60])
            elif u:
                aa_now("security", "ratelimit:" + k, N_("Login rate limit reached for user {0} (logins refused for {1} min)."),
                       [username, FAIL_WINDOW // 60])
            else:
                aa_now("security", "ratelimit:u:?",
                       N_("Login rate limit reached for an unknown user name (logins refused for {0} min)."), [FAIL_WINDOW // 60])
        aa_count("security", "logins", client_ip(), user=username if u else "?")
        print("login failed for", repr(username), "from", client_ip(), flush=True)
        return err(tr("Wrong username or password", lg=_accept_lang(lang())), 401)  # 2.13.0 (#453 P7): the page's language
    remember = bool(b.get("remember", True))
    methods = twofa_methods(c, u)
    if methods:  # second step: a code, a passkey or a recovery code (POST /api/auth/2fa...)
        tok = pend_new("2fa", u["id"], remember=remember)
        return pend_cookie(jsonify(ok=False, twofa=True, methods=methods), tok)
    if gsetting(c, "twofa_required") == "1":  # admin policy: enrol now, the session starts afterwards
        tok = pend_new("enrol", u["id"], remember=remember)
        return pend_cookie(jsonify(ok=False, enrol=True, methods=["totp", "passkey"]), tok)
    return finish_login(c, u, remember, "password")


@app.post("/api/auth/setup")
def auth_setup():
    """First start without users: creates the first admin. With a trusted proxy header the account is
    bound to that login and the password is optional."""
    b = body()
    c = db()
    c.execute("BEGIN IMMEDIATE")
    if c.execute("SELECT 1 FROM users").fetchone():
        c.rollback()
        return err(tr("Setup is already done"), 409)
    username = (b.get("username") or "").strip().lower()
    pw = b.get("password") or ""
    proxy = proxy_login_value() or None
    if not USERNAME_RE.fullmatch(username):
        c.rollback()
        return err(tr("Username: 1-32 characters a-z, 0-9, dot, dash, underscore"))
    if (pw or not proxy) and len(pw) < MIN_PASSWORD:
        c.rollback()
        return err(tr("Password: at least {0} characters", MIN_PASSWORD))
    uid = create_user(c, username, (b.get("display_name") or "").strip()[:60] or username, pw or None, proxy, True,
                      ntfy_topic=NTFY_TOPIC or None, seed_global=True,
                      drop_token=os.environ.get("TASKS_DROP_TOKEN") or None,
                      onboard=not c.execute("SELECT 1 FROM tasks LIMIT 1").fetchone())
    adopt_orphans(c, uid)
    ensure_inbox(c, uid)
    if b.get("wizard") is True:  # 2.13.0 (#453 A16): the setup page's step 2 comes back after a reload until it is finished
        gset(c, "setup_step2", "pending")
    bump(c)
    tok, age = start_session(c, uid, True) if pw else (None, None)
    c.commit()
    resp = jsonify(ok=True)
    return set_cookie(resp, tok, age) if tok else resp


@app.post("/api/auth/logout")
def auth_logout():
    c = db()
    tok = request.cookies.get(COOKIE)
    if tok:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(tok),))
        c.commit()
    resp = jsonify(ok=True, proxy=g.auth_via == "proxy")
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ---------------------------------------------------------------- two-factor (built-in login): TOTP, recovery codes, passkeys
# Only for accounts with a password (the built-in login). Proxy-header SSO and OIDC logins leave the second factor
# to the proxy / identity provider. After a correct password a user with a second factor gets a short-lived ticket
# (HttpOnly cookie, path /api/auth, 5 min, 5 tries) instead of a session; the session starts after the code, a
# passkey or a recovery code. With the admin policy "Require 2FA" a user without one gets an enrolment ticket and
# must set up TOTP or a passkey first. Every failed code counts against the same limits as a wrong password.
# TOTP: RFC 6238 (SHA-1, 6 digits, 30 s, ±1 step), the secret is stored encrypted (AES-GCM, key from the server
# secret), a used time step is never accepted again. Recovery codes: 10 random one-time codes, SHA-256 at rest.
# Passkeys: WebAuthn via py_webauthn (attestation "none", the credential id, COSE public key and sign counter are
# stored); RP ID = KALMIDO_WEBAUTHN_RP_ID or the host of the page (only origins from PUBLIC_URL /
# KALMIDO_WEBAUTHN_ORIGINS or localhost), so a passkey only ever works on the address it was created on.
PEND_COOKIE = "kalmido_2fa"
PEND_TTL = 300           # s a login ticket / an enrolment secret / a WebAuthn challenge lives
PEND_TRIES = 5           # wrong codes per ticket
PEND_MAX = 5000
TOTP_STEP, TOTP_DIGITS = 30, 6
RC_COUNT = 10
RC_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PASSKEY_NAME_MAX = 60
PASSKEY_MAX = 20         # per user
WA_TRANSPORTS = {"usb", "nfc", "ble", "internal", "hybrid", "smart-card", "cable"}
WA_RP_ID_ENV = os.environ.get("KALMIDO_WEBAUTHN_RP_ID", "").strip().lower().rstrip(".")
WA_ORIGINS_ENV = [o.strip().rstrip("/") for o in os.environ.get("KALMIDO_WEBAUTHN_ORIGINS", "").split(",") if o.strip()]
_PEND, _PEND_LOCK = {}, threading.Lock()
_AUTH_KEY = {}


def auth_key(c):
    if "k" not in _AUTH_KEY:
        _AUTH_KEY["k"] = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"kalmido-auth",
                              info=b"sign-in secrets v1").derive(bytes.fromhex(gsetting(c, "auth_secret")))
    return _AUTH_KEY["k"]


def seal(c, purpose, s):
    """AES-GCM with the server key; purpose (e.g. 'totp:5') is bound as associated data."""
    from ..notify.push import _b64u
    if not s:
        return ""
    n = os.urandom(12)
    return "v1." + _b64u(n + AESGCM(auth_key(c)).encrypt(n, s.encode(), f"kalmido-auth:{purpose}".encode()))


def unseal(c, purpose, s):
    from ..notify.push import _b64u_dec
    if not s:
        return ""
    raw = _b64u_dec(s[3:])
    return AESGCM(auth_key(c)).decrypt(raw[:12], raw[12:], f"kalmido-auth:{purpose}".encode()).decode()


# ---- tickets / challenges (in memory: a restart simply asks for the password again)
def _pend_gc():
    now = time.time()
    for k in [k for k, v in _PEND.items() if v["exp"] < now]:
        del _PEND[k]
    if len(_PEND) > PEND_MAX:
        for k in sorted(_PEND, key=lambda k: _PEND[k]["exp"])[:len(_PEND) - PEND_MAX]:
            del _PEND[k]


def pend_new(kind, uid, **data):
    tok = secrets.token_urlsafe(32)
    with _PEND_LOCK:
        _pend_gc()
        _PEND["t:" + _token_hash(tok)] = {"kind": kind, "uid": uid, "exp": time.time() + PEND_TTL, "tries": 0, **data}
    return tok


def pend_cookie(resp, tok):
    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"
    resp.set_cookie(PEND_COOKIE, tok, max_age=PEND_TTL, httponly=True, samesite="Strict", secure=secure, path="/api/auth")
    return resp


def pend_get(kinds):
    """The ticket of this browser (dict, shared: changes stick) if it is one of `kinds`, else None."""
    tok = request.cookies.get(PEND_COOKIE) or ""
    if not tok:
        return None
    with _PEND_LOCK:
        _pend_gc()
        p = _PEND.get("t:" + _token_hash(tok))
    return p if p and p["kind"] in kinds else None


def pend_drop():
    tok = request.cookies.get(PEND_COOKIE) or ""
    with _PEND_LOCK:
        _PEND.pop("t:" + _token_hash(tok), None)


def pend_set(key, **data):
    """Per-user state of a logged-in user (TOTP enrolment secret, WebAuthn registration challenge)."""
    with _PEND_LOCK:
        _pend_gc()
        _PEND[key] = {"exp": time.time() + PEND_TTL, **data}


def pend_take(key):
    with _PEND_LOCK:
        _pend_gc()
        return _PEND.pop(key, None)


# ---- TOTP (RFC 6238 / RFC 4226)
def totp_code(key, step):
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()  # HOTP is defined with HMAC-SHA-1
    o = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** TOTP_DIGITS).zfill(TOTP_DIGITS)


def totp_match(secret_b32, code, last_step=0):
    """The matching time step (now ±1, newer than last_step) or None."""
    code = re.sub(r"\s", "", str(code or ""))
    if not re.fullmatch(r"\d{%d}" % TOTP_DIGITS, code):
        return None
    try:
        key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    except (ValueError, TypeError):
        return None
    now = int(time.time() // TOTP_STEP)
    for st in (now - 1, now, now + 1):
        if st > (last_step or 0) and hmac.compare_digest(totp_code(key, st), code):
            return st
    return None


def totp_new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_uri(secret, username):
    label = urllib.parse.quote(f"{APP_NAME}:{username}", safe=":@")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(APP_NAME)}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP}"


def totp_payload(secret, username):
    """What the client shows for the enrolment: secret (grouped), otpauth link and a QR code (SVG data URI, made here:
    no external request)."""
    uri = totp_uri(secret, username)
    return {"secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)), "uri": uri,
            "qr": segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#000", light="#fff")}


# ---- recovery codes
def rc_norm(code):
    return re.sub(r"[\s-]", "", str(code or "")).lower()


def rc_hash(code):
    return hashlib.sha256(("kalmido-recovery:" + rc_norm(code)).encode()).hexdigest()


def rc_new(c, uid):
    """10 new codes (the old ones stop working); returns them once, only the hashes are stored."""
    c.execute("DELETE FROM recovery_codes WHERE user_id=?", (uid,))
    codes = []
    for _ in range(RC_COUNT):
        raw = "".join(secrets.choice(RC_ALPHABET) for _ in range(10))
        codes.append(raw[:5] + "-" + raw[5:])
        c.execute("INSERT INTO recovery_codes(user_id,code_hash,created_at) VALUES(?,?,?)", (uid, rc_hash(raw), iso(now_utc())))
    return codes


def rc_use(c, uid, code):
    if len(rc_norm(code)) != 10:
        return False
    r = c.execute("SELECT id FROM recovery_codes WHERE user_id=? AND code_hash=? AND used_at IS NULL", (uid, rc_hash(code))).fetchone()
    if not r:
        return False
    return c.execute("UPDATE recovery_codes SET used_at=? WHERE id=? AND used_at IS NULL", (iso(now_utc()), r[0])).rowcount == 1


def rc_left(c, uid):
    return c.execute("SELECT COUNT(*) FROM recovery_codes WHERE user_id=? AND used_at IS NULL", (uid,)).fetchone()[0]


def twofa_methods(c, u):
    """Second factors of an account with a password: [] = none."""
    if not u["password_hash"]:
        return []
    out = []
    if u["totp_secret"]:
        out.append("totp")
    if c.execute("SELECT 1 FROM webauthn_creds WHERE user_id=?", (u["id"],)).fetchone():
        out.append("passkey")
    if out and rc_left(c, u["id"]):
        out.append("recovery")
    return out


def twofa_clear(c, uid):
    c.execute("UPDATE users SET totp_secret=NULL, totp_step=0 WHERE id=?", (uid,))
    c.execute("DELETE FROM webauthn_creds WHERE user_id=?", (uid,))
    c.execute("DELETE FROM recovery_codes WHERE user_id=?", (uid,))


def _user(c, uid):
    return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def _code_fail(u, p=None):
    """A wrong second factor: counts like a wrong password; the ticket dies after PEND_TRIES."""
    from ..notify.alerts import aa_count
    keys = _rate_keys(u["username"])
    _rate_fail(keys)
    aa_count("security", "logins", client_ip(), user=u["username"])
    print("second factor failed for", repr(u["username"]), "from", client_ip(), flush=True)
    if p is not None:
        p["tries"] += 1
        if p["tries"] >= PEND_TRIES:
            pend_drop()


def _ticket(kinds):
    """(ticket, user) of this browser or an error response."""
    p = pend_get(kinds)
    if not p:
        return None, None, (jsonify(error=tr("The login has expired, please log in again"), expired=True), 401)
    u = _user(db(), p["uid"])
    if not u or u["disabled"] or not u["password_hash"]:
        pend_drop()
        return None, None, (jsonify(error=tr("The login has expired, please log in again"), expired=True), 401)
    if _rate_blocked(_rate_keys(u["username"])):
        return None, None, err(tr("Too many failed logins, please wait a few minutes"), 429)
    return p, u, None


# ---- WebAuthn (passkeys)
def _req_origin():
    o = (request.headers.get("Origin") or "").strip().rstrip("/")
    if o and o != "null":
        return o
    proto = request.headers.get("X-Forwarded-Proto", "") if _peer_trusted() else ""
    return f"{proto or request.scheme}://{request.host}"


def _origin_host(o):
    try:
        return (urllib.parse.urlsplit(o).hostname or "").lower()
    except ValueError:
        return ""


def wa_context():
    """(rp_id, [expected origins]) for this request. The page's origin counts when it is PUBLIC_URL, one of
    KALMIDO_WEBAUTHN_ORIGINS or localhost; otherwise PUBLIC_URL's host is the RP ID."""
    public = PUBLIC_URL.rstrip("/")
    allowed = [public] + WA_ORIGINS_ENV
    o = _req_origin()
    host = _origin_host(o)
    if o not in allowed and not (host == "localhost" or host.endswith(".localhost")):
        o = public
    rp = WA_RP_ID_ENV or _origin_host(o)
    origins = [x for x in dict.fromkeys(allowed + [o]) if _origin_host(x) == rp or _origin_host(x).endswith("." + rp)]
    return rp, origins


def wa_handle(c, u):
    from ..notify.push import _b64u, _b64u_dec
    if u["webauthn_handle"]:
        return _b64u_dec(u["webauthn_handle"])
    h = secrets.token_bytes(32)
    c.execute("UPDATE users SET webauthn_handle=? WHERE id=?", (_b64u(h), u["id"]))
    c.commit()
    return h


def wa_json(opts):
    return json.loads(webauthn.options_to_json(opts))


def wa_reg_options(c, u):
    from ..notify.push import _b64u_dec
    rp, _ = wa_context()
    creds = c.execute("SELECT cred_id, transports FROM webauthn_creds WHERE user_id=?", (u["id"],)).fetchall()
    opts = webauthn.generate_registration_options(
        rp_id=rp, rp_name=APP_NAME, user_id=wa_handle(c, u), user_name=u["username"],
        user_display_name=u["display_name"] or u["username"],
        exclude_credentials=[wa_structs.PublicKeyCredentialDescriptor(id=_b64u_dec(r["cred_id"])) for r in creds],
        authenticator_selection=wa_structs.AuthenticatorSelectionCriteria(
            resident_key=wa_structs.ResidentKeyRequirement.PREFERRED,
            user_verification=wa_structs.UserVerificationRequirement.PREFERRED),
        attestation=wa_structs.AttestationConveyancePreference.NONE)
    return opts.challenge, rp, wa_json(opts)


def wa_reg_verify(c, u, cred, chal, rp, name):
    """Stores the new passkey; returns its row id or raises ValueError (message is safe to show)."""
    from ..notify.push import _b64u
    _, origins = wa_context()
    if not isinstance(cred, dict):
        raise ValueError(tr("The passkey could not be registered"))
    try:
        v = webauthn.verify_registration_response(credential=cred, expected_challenge=chal, expected_rp_id=rp,
                                                  expected_origin=origins, require_user_verification=False)
    except Exception as e:  # noqa: BLE001  (every parse / verification error of the library)
        print("passkey registration refused:", type(e).__name__, str(e)[:120], flush=True)
        raise ValueError(tr("The passkey could not be registered")) from None
    cid = _b64u(v.credential_id)
    if c.execute("SELECT 1 FROM webauthn_creds WHERE cred_id=?", (cid,)).fetchone():
        raise ValueError(tr("This passkey is already registered"))
    if c.execute("SELECT COUNT(*) FROM webauthn_creds WHERE user_id=?", (u["id"],)).fetchone()[0] >= PASSKEY_MAX:
        raise ValueError(tr("At most {0} passkeys", PASSKEY_MAX))
    resp = cred.get("response") if isinstance(cred.get("response"), dict) else {}
    tr_ = [t for t in (resp.get("transports") or []) if isinstance(t, str) and t in WA_TRANSPORTS] \
        if isinstance(resp.get("transports"), list) else []
    ext = cred.get("clientExtensionResults") if isinstance(cred.get("clientExtensionResults"), dict) else {}
    rk = (ext.get("credProps") or {}).get("rk") if isinstance(ext.get("credProps"), dict) else None
    name = (str(name or "").strip() or tr("Passkey"))[:PASSKEY_NAME_MAX]
    return c.execute("""INSERT INTO webauthn_creds(user_id,cred_id,public_key,sign_count,transports,name,rp_id,aaguid,backed_up,
                                                   discoverable,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                     (u["id"], cid, v.credential_public_key, v.sign_count, ",".join(tr_), name, rp, str(v.aaguid or ""),
                      1 if v.credential_backed_up else 0, None if rk is None else (1 if rk else 0), iso(now_utc()))).lastrowid


def wa_auth_options(c, uid=None, uv=False):
    from ..notify.push import _b64u_dec
    rp, _ = wa_context()
    allow = []
    if uid is not None:
        allow = [wa_structs.PublicKeyCredentialDescriptor(
            id=_b64u_dec(r["cred_id"]),
            transports=[wa_structs.AuthenticatorTransport(t) for t in r["transports"].split(",") if t in WA_TRANSPORTS - {"cable"}] or None)
            for r in c.execute("SELECT cred_id, transports FROM webauthn_creds WHERE user_id=?", (uid,))]
    opts = webauthn.generate_authentication_options(
        rp_id=rp, allow_credentials=allow,
        user_verification=wa_structs.UserVerificationRequirement.REQUIRED if uv else wa_structs.UserVerificationRequirement.PREFERRED)
    return opts.challenge, rp, wa_json(opts)


def wa_auth_verify(c, cred, chal, rp, uid=None, uv=False):
    """The user id the passkey belongs to (uid given: it must be that user's) or None."""
    from ..notify.push import _b64u_dec
    if not isinstance(cred, dict) or not isinstance(cred.get("rawId") or cred.get("id"), str):
        return None
    cid = cred.get("rawId") or cred.get("id")
    row = c.execute("SELECT * FROM webauthn_creds WHERE cred_id=?", (cid[:1400],)).fetchone()
    if not row or (uid is not None and row["user_id"] != uid):
        return None
    u = _user(c, row["user_id"])
    if not u or u["disabled"]:
        return None
    resp = cred.get("response") if isinstance(cred.get("response"), dict) else {}
    try:
        uh = _b64u_dec(resp["userHandle"]) if resp.get("userHandle") else b""
        mine = _b64u_dec(u["webauthn_handle"]) if u["webauthn_handle"] else b""
    except (ValueError, TypeError):
        return None
    if uid is None and (not uh or not mine or not hmac.compare_digest(uh, mine)):
        return None  # passwordless: the discoverable credential must name this account
    _, origins = wa_context()
    try:
        v = webauthn.verify_authentication_response(credential=cred, expected_challenge=chal, expected_rp_id=rp,
                                                    expected_origin=origins, credential_public_key=row["public_key"],
                                                    credential_current_sign_count=row["sign_count"], require_user_verification=uv)
    except Exception as e:  # noqa: BLE001
        print("passkey assertion refused:", type(e).__name__, str(e)[:120], flush=True)
        return None
    c.execute("UPDATE webauthn_creds SET sign_count=?, last_used_at=?, backed_up=? WHERE id=?",
              (v.new_sign_count, iso(now_utc()), 1 if v.credential_backed_up else 0, row["id"]))
    return row["user_id"]


def passkey_public(r):
    return {"id": r["id"], "name": r["name"], "created_at": r["created_at"], "last_used_at": r["last_used_at"],
            "synced": bool(r["backed_up"]), "discoverable": r["discoverable"], "rp_id": r["rp_id"]}


# ---- login: second step
@app.post("/api/auth/2fa")
def auth_2fa():
    """{code} (authenticator app) or {recovery} after a correct password."""
    from ..notify.alerts import aa_now
    p, u, e = _ticket(("2fa",))
    if e:
        return e
    c, b = db(), body()
    ok, via = False, "totp"
    if b.get("recovery"):
        ok = rc_use(c, u["id"], b.get("recovery"))
        via = "recovery"
    elif u["totp_secret"]:
        try:
            secret = unseal(c, f"totp:{u['id']}", u["totp_secret"])
        except (InvalidTag, ValueError):
            secret = ""
        st = totp_match(secret, b.get("code"), u["totp_step"]) if secret else None
        if st:
            ok = c.execute("UPDATE users SET totp_step=? WHERE id=? AND totp_step<?", (st, u["id"], st)).rowcount == 1
    if not ok:
        _code_fail(u, p)
        c.rollback()
        return err(tr("Wrong code"), 401)
    pend_drop()
    left = rc_left(c, u["id"])
    if via == "recovery":
        aa_now("security", f"recovery:{u['username']}:{int(time.time())}",
               N_("{0} logged in with a recovery code ({1} left)."), [u["username"], left])
    return finish_login(c, u, p.get("remember", True), "2fa", {"recovery_left": left} if via == "recovery" else None)


@app.post("/api/auth/2fa/passkey/options")
def auth_2fa_pk_options():
    p, u, e = _ticket(("2fa",))
    if e:
        return e
    chal, rp, opts = wa_auth_options(db(), u["id"])
    p.update(chal=chal, rp=rp)
    return jsonify(opts)


@app.post("/api/auth/2fa/passkey")
def auth_2fa_pk():
    p, u, e = _ticket(("2fa",))
    if e:
        return e
    c = db()
    chal, rp = p.pop("chal", None), p.get("rp")
    uid = wa_auth_verify(c, body().get("credential"), chal, rp, uid=u["id"]) if chal else None
    if uid != u["id"]:
        _code_fail(u, p)
        c.rollback()
        return err(tr("The passkey was not accepted"), 401)
    pend_drop()
    return finish_login(c, u, p.get("remember", True), "2fa")


# ---- login: enrolment forced by the admin policy (ticket kind "enrol")
@app.post("/api/auth/enrol/totp")
def auth_enrol_totp():
    p, u, e = _ticket(("enrol",))
    if e:
        return e
    p["totp"] = p.get("totp") or totp_new_secret()
    return jsonify(totp_payload(p["totp"], u["username"]))


@app.post("/api/auth/enrol/totp/confirm")
def auth_enrol_totp_confirm():
    p, u, e = _ticket(("enrol",))
    if e:
        return e
    c = db()
    st = totp_match(p.get("totp") or "", body().get("code")) if p.get("totp") else None
    if not st:
        _code_fail(u, p)
        return err(tr("Wrong code"), 401)
    c.execute("UPDATE users SET totp_secret=?, totp_step=? WHERE id=?", (seal(c, f"totp:{u['id']}", p["totp"]), st, u["id"]))
    codes = rc_new(c, u["id"])
    pend_drop()
    return finish_login(c, u, p.get("remember", True), "2fa", {"recovery_codes": codes})


@app.post("/api/auth/enrol/passkey/options")
def auth_enrol_pk_options():
    p, u, e = _ticket(("enrol",))
    if e:
        return e
    chal, rp, opts = wa_reg_options(db(), u)
    p.update(chal=chal, rp=rp)
    return jsonify(opts)


@app.post("/api/auth/enrol/passkey")
def auth_enrol_pk():
    p, u, e = _ticket(("enrol",))
    if e:
        return e
    c, b = db(), body()
    chal = p.pop("chal", None)
    try:
        if not chal:
            raise ValueError(tr("The passkey could not be registered"))
        wa_reg_verify(c, u, b.get("credential"), chal, p.get("rp"), b.get("name"))
    except ValueError as x:
        _code_fail(u, p)
        c.rollback()
        return err(str(x), 400)
    codes = rc_new(c, u["id"])
    pend_drop()
    return finish_login(c, u, p.get("remember", True), "2fa", {"recovery_codes": codes})


# ---- passwordless login with a passkey (user verification required)
@app.post("/api/auth/passkey/options")
def auth_pk_options():
    c = db()
    if gsetting(c, "passkey_login") == "0":
        return err(tr("Logging in with a passkey is turned off on this server"), 403)
    if _rate_blocked([("ip:" + client_ip(), 20)]):
        return err(tr("Too many failed logins, please wait a few minutes"), 429)
    chal, rp, opts = wa_auth_options(c, None, uv=True)
    tok = pend_new("pk", None, chal=chal, rp=rp, remember=bool(body().get("remember", True)))
    return pend_cookie(jsonify(opts), tok)


@app.post("/api/auth/passkey")
def auth_pk():
    from ..notify.alerts import aa_count
    c = db()
    keys = [("ip:" + client_ip(), 20)]
    if gsetting(c, "passkey_login") == "0":
        return err(tr("Logging in with a passkey is turned off on this server"), 403)
    if _rate_blocked(keys):
        return err(tr("Too many failed logins, please wait a few minutes"), 429)
    p = pend_get(("pk",))
    chal = p.pop("chal", None) if p else None
    uid = wa_auth_verify(c, body().get("credential"), chal, p.get("rp"), uv=True) if chal else None
    u = _user(c, uid) if uid else None
    if not u or u["disabled"]:
        _rate_fail(keys)
        aa_count("security", "logins", client_ip(), user="?")
        c.rollback()
        return err(tr("The passkey was not accepted"), 401)
    pend_drop()
    return finish_login(c, u, p.get("remember", True), "passkey")


# ---- account: Settings > Account > Two-factor authentication
def _reauth(u, b):
    """Current password for security-relevant changes (rate-limited like a login); an error response or None."""
    keys = _rate_keys(u["username"])
    if _rate_blocked(keys):
        return err(tr("Too many failed logins, please wait a few minutes"), 429)
    if not u["password_hash"]:
        return err(tr("Two-factor authentication is only for logins with a password"), 409)
    pw = b.get("password") if isinstance(b.get("password"), str) else ""
    if not check_password_hash(u["password_hash"], pw):
        _rate_fail(keys)
        return err(tr("Current password is wrong"), 403)
    return None


def twofa_state(c, u):
    rp, _ = wa_context()
    return {"available": bool(u["password_hash"]), "totp": bool(u["totp_secret"]), "recovery_left": rc_left(c, u["id"]),
            "passkeys": [passkey_public(r) for r in c.execute("SELECT * FROM webauthn_creds WHERE user_id=? ORDER BY id", (u["id"],))],
            "required": gsetting(c, "twofa_required") == "1", "passkey_login": gsetting(c, "passkey_login") != "0",
            "rp_id": rp, "via": g.auth_via if g.auth_via == "proxy" else session_via(c)}


def session_via(c):
    tok = request.cookies.get(COOKIE)
    r = c.execute("SELECT via FROM sessions WHERE token_hash=?", (_token_hash(tok),)).fetchone() if tok else None
    return r[0] if r else ""


def _last_factor_guard(c, u, removing):
    """With the admin policy on, the last second factor cannot be removed."""
    if gsetting(c, "twofa_required") != "1":
        return None
    left = twofa_methods(c, u)
    left = [m for m in left if m != "recovery" and m != removing]
    if removing == "passkey" and c.execute("SELECT COUNT(*) FROM webauthn_creds WHERE user_id=?", (u["id"],)).fetchone()[0] > 1:
        return None
    return None if left else err(tr("Two-factor authentication is required on this server; set up another method first"), 409)


def _end_other_sessions(c, uid):
    """A second factor was just turned on: sessions elsewhere (possibly opened with a leaked password) end."""
    tok = request.cookies.get(COOKIE)
    c.execute("DELETE FROM sessions WHERE user_id=? AND token_hash IS NOT ?", (uid, _token_hash(tok) if tok else None))


@app.get("/api/me/2fa")
def me_2fa():
    return jsonify(twofa_state(db(), g.user))


@app.post("/api/me/2fa/totp")
def me_totp_begin():
    u, b = g.user, body()
    e = _reauth(u, b)
    if e:
        return e
    if u["totp_secret"]:
        return err(tr("The authenticator app is already set up"), 409)
    secret = totp_new_secret()
    pend_set(f"totp:{u['id']}", secret=secret)
    return jsonify(totp_payload(secret, u["username"]))


@app.post("/api/me/2fa/totp/confirm")
def me_totp_confirm():
    from ..notify.alerts import aa_now
    u, c = g.user, db()
    keys = _rate_keys(u["username"])
    if _rate_blocked(keys):
        return err(tr("Too many failed logins, please wait a few minutes"), 429)
    with _PEND_LOCK:
        p = _PEND.get(f"totp:{u['id']}")
    if not p or p["exp"] < time.time():
        return err(tr("The setup has expired, please start again"), 409)
    st = totp_match(p["secret"], body().get("code"))
    if not st:
        _rate_fail(keys)
        return err(tr("Wrong code"), 400)
    pend_take(f"totp:{u['id']}")
    first = not twofa_methods(c, u)
    c.execute("UPDATE users SET totp_secret=?, totp_step=? WHERE id=?", (seal(c, f"totp:{u['id']}", p["secret"]), st, u["id"]))
    codes = rc_new(c, u["id"]) if not rc_left(c, u["id"]) else None
    if first:
        _end_other_sessions(c, u["id"])
    c.commit()
    aa_now("security", f"2fa:{u['username']}:{int(time.time())}", N_("{0} turned on two-factor authentication ({1})."),
           [u["username"], {"t": N_("authenticator app")}])
    return jsonify(recovery_codes=codes, **twofa_state(c, _user(c, u["id"])))


@app.post("/api/me/2fa/totp/disable")
def me_totp_disable():
    """Needs the password and a current code (or a recovery code)."""
    from ..notify.alerts import aa_now
    u, c, b = g.user, db(), body()
    e = _reauth(u, b)
    if e:
        return e
    if not u["totp_secret"]:
        return err(tr("The authenticator app is not set up"), 409)
    try:
        secret = unseal(c, f"totp:{u['id']}", u["totp_secret"])
    except (InvalidTag, ValueError):
        secret = ""
    ok = bool(secret and totp_match(secret, b.get("code"), u["totp_step"])) or rc_use(c, u["id"], b.get("code"))
    if not ok:
        _rate_fail(_rate_keys(u["username"]))
        c.rollback()
        return err(tr("Wrong code"), 400)
    e = _last_factor_guard(c, u, "totp")
    if e:
        c.rollback()
        return e
    c.execute("UPDATE users SET totp_secret=NULL, totp_step=0 WHERE id=?", (u["id"],))
    if not c.execute("SELECT 1 FROM webauthn_creds WHERE user_id=?", (u["id"],)).fetchone():
        c.execute("DELETE FROM recovery_codes WHERE user_id=?", (u["id"],))
    c.commit()
    aa_now("security", f"2faoff:{u['username']}:{int(time.time())}", N_("{0} turned off two-factor authentication ({1})."),
           [u["username"], {"t": N_("authenticator app")}])
    return jsonify(twofa_state(c, _user(c, u["id"])))


@app.post("/api/me/2fa/recovery")
def me_recovery_new():
    u, c, b = g.user, db(), body()
    e = _reauth(u, b)
    if e:
        return e
    if not twofa_methods(c, u):
        return err(tr("Set up an authenticator app or a passkey first"), 409)
    codes = rc_new(c, u["id"])
    c.commit()
    return jsonify(recovery_codes=codes, **twofa_state(c, u))


@app.post("/api/me/passkeys/options")
def me_pk_options():
    u, c, b = g.user, db(), body()
    e = _reauth(u, b)
    if e:
        return e
    chal, rp, opts = wa_reg_options(c, u)
    pend_set(f"wareg:{u['id']}", chal=chal, rp=rp)
    return jsonify(opts)


@app.post("/api/me/passkeys")
def me_pk_add():
    from ..notify.alerts import aa_now
    u, c, b = g.user, db(), body()
    p = pend_take(f"wareg:{u['id']}")
    if not p:
        return err(tr("The setup has expired, please start again"), 409)
    first = not twofa_methods(c, u)
    try:
        wa_reg_verify(c, u, b.get("credential"), p["chal"], p["rp"], b.get("name"))
    except ValueError as x:
        c.rollback()
        return err(str(x), 400)
    codes = rc_new(c, u["id"]) if not rc_left(c, u["id"]) else None
    if first:
        _end_other_sessions(c, u["id"])
    c.commit()
    aa_now("security", f"2fa:{u['username']}:{int(time.time())}", N_("{0} turned on two-factor authentication ({1})."),
           [u["username"], {"t": N_("passkey")}])
    return jsonify(recovery_codes=codes, **twofa_state(c, _user(c, u["id"])))


@app.patch("/api/me/passkeys/<int:pid>")
def me_pk_rename(pid):
    u, c = g.user, db()
    name = str(body().get("name") or "").strip()[:PASSKEY_NAME_MAX]
    if not name:
        return err(tr("Name missing"))
    if not c.execute("UPDATE webauthn_creds SET name=? WHERE id=? AND user_id=?", (name, pid, u["id"])).rowcount:
        return err(tr("unknown"), 404)
    c.commit()
    return jsonify(twofa_state(c, u))


@app.delete("/api/me/passkeys/<int:pid>")
def me_pk_delete(pid):
    u, c, b = g.user, db(), body()
    e = _reauth(u, b)
    if e:
        return e
    if not c.execute("SELECT 1 FROM webauthn_creds WHERE id=? AND user_id=?", (pid, u["id"])).fetchone():
        return err(tr("unknown"), 404)
    e = _last_factor_guard(c, u, "passkey")
    if e:
        return e
    c.execute("DELETE FROM webauthn_creds WHERE id=? AND user_id=?", (pid, u["id"]))
    if not u["totp_secret"] and not c.execute("SELECT 1 FROM webauthn_creds WHERE user_id=?", (u["id"],)).fetchone():
        c.execute("DELETE FROM recovery_codes WHERE user_id=?", (u["id"],))
    c.commit()
    return jsonify(twofa_state(c, _user(c, u["id"])))
