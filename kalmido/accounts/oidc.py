"""Login with a generic OpenID Connect provider (authorization code flow with PKCE)."""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import g, jsonify, redirect, request

from ..core.config import app, APP_NAME, APP_VERSION, COOKIE, PUBLIC_URL, SECRET_KEY, USERNAME_RE
from ..core.i18n import N_, tr
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gset, gsetting, iso, now_utc
from ..accounts.session import _rate_blocked, _rate_fail, _token_hash, client_ip, set_cookie, start_session
from ..accounts.login import _user


# ---------------------------------------------------------------- OIDC login (generic OpenID Connect provider)
# Authorization Code flow with PKCE (S256), state (bound to this browser by an HttpOnly cookie, one-time, 10 min) and
# nonce. Discovery from KALMIDO_OIDC_ISSUER/.well-known/openid-configuration; the ID token is checked here: signature
# with the provider's JWKS (RSA, RSA-PSS, ECDSA, Ed25519; never "none" or HMAC; keys cached for an hour, fetched again
# for an unknown key id), iss, aud, azp, exp, iat, nbf, nonce. Extra claims come from the userinfo endpoint (same sub).
# Every request to the provider goes through the SSRF guard of the calendar subscriptions (cal_http): public
# addresses only, unless the host is allow-listed (KALMIDO_OIDC_ALLOW_HOSTS or Settings > Users > Whole server).
# Accounts: a user linked to the subject (issuer|sub) logs in; otherwise the first login links the user whose
# username equals the username claim or whose e-mail equals the (verified) e-mail claim. Without a match: "no
# account", unless the admin turned on "Create accounts on first login". Optional required group; optional admin group
# (the admin flag then follows the group, the last active admin is never demoted). Secrets are never logged.
# 2.9.0 (#438): the provider can also be set up in Settings > Administration > Sign-in (stored in settings.oidc_*, the
# client secret sealed with KALMIDO_SECRET_KEY like the Paperless tokens). Every KALMIDO_OIDC_* variable that is set wins
# over the stored value of that field (the settings show it locked). Optional: admins by verified e-mail domain
# (KALMIDO_OIDC_ADMIN_DOMAINS / the setting), next to the admin group.
OIDC_FIELDS = (("issuer", "KALMIDO_OIDC_ISSUER"), ("client_id", "KALMIDO_OIDC_CLIENT_ID"),
               ("client_secret", "KALMIDO_OIDC_CLIENT_SECRET"), ("scopes", "KALMIDO_OIDC_SCOPES"),
               ("username_claim", "KALMIDO_OIDC_USERNAME_CLAIM"), ("groups_claim", "KALMIDO_OIDC_GROUPS_CLAIM"),
               ("required_group", "KALMIDO_OIDC_REQUIRED_GROUP"), ("admin_group", "KALMIDO_OIDC_ADMIN_GROUP"),
               ("admin_domains", "KALMIDO_OIDC_ADMIN_DOMAINS"), ("label", "KALMIDO_OIDC_BUTTON_LABEL"))
OIDC_FIELD_MAX = {"issuer": 500, "client_id": 300, "client_secret": 1000, "scopes": 300, "username_claim": 100,
                  "groups_claim": 100, "required_group": 200, "admin_group": 200, "admin_domains": 500, "label": 40}
_OIDC_CFG = {}
OIDC_ALLOW_ENV = os.environ.get("KALMIDO_OIDC_ALLOW_HOSTS", "")
OIDC_REDIRECT = PUBLIC_URL.rstrip("/") + "/api/auth/oidc/callback"
OIDC_COOKIE = "kalmido_oidc"
OIDC_STATE_TTL = 600
OIDC_CACHE = 3600
OIDC_LEEWAY = 60
OIDC_ALGS = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
_OIDC = {"doc": None, "doc_at": 0.0, "jwks": None, "jwks_at": 0.0, "err": "", "err_at": ""}
_OIDC_STATES, _OIDC_LOCK = {}, threading.Lock()
OIDC_ERRORS = {"no_account": N_("There is no account for this login yet. Please ask the admin to create one."),
               "disabled": N_("This account is disabled."),
               "group": N_("Your account at the login provider is not allowed to use this app."),
               "state": N_("The login took too long or was started in another browser. Please try again."),
               "denied": N_("The login was cancelled at the login provider."),
               "taken": N_("The user name from the login provider is already used by another account."),
               "failed": N_("The login with the provider failed. Please try again or ask the admin.")}


def oidc_seal(secret):
    from ..personal.timetrack import BadInput
    from ..notify.push import _b64u
    if not SECRET_KEY:
        raise BadInput(tr("Set KALMIDO_SECRET_KEY on the server to store the client secret (32 random bytes, base64)"))
    n = os.urandom(12)
    return "v1." + _b64u(n + AESGCM(SECRET_KEY).encrypt(n, secret.encode(), b"kalmido-oidc:client_secret"))


def oidc_unseal(s):
    from ..notify.push import _b64u_dec
    if not SECRET_KEY or not s or not s.startswith("v1."):
        return ""
    try:
        raw = _b64u_dec(s[3:])
        return AESGCM(SECRET_KEY).decrypt(raw[:12], raw[12:], b"kalmido-oidc:client_secret").decode()
    except (InvalidTag, ValueError, TypeError):
        return ""


def oidc_cfg(c=None):
    """The provider settings in effect: per field the environment variable if set, else the stored setting."""
    cfg = _OIDC_CFG.get("cfg")
    if cfg is not None:
        return cfg
    c = c or db()
    v, src = {}, {}
    for k, env in OIDC_FIELDS:
        e = os.environ.get(env, "").strip()
        if e:
            v[k], src[k] = e, "env"
            continue
        stored = gsetting(c, "oidc_" + k)
        if k == "client_secret":
            src[k] = "db" if stored else ""
            stored = oidc_unseal(stored)
            if src[k] and not stored:
                src[k] = "lost"  # sealed with another / no KALMIDO_SECRET_KEY: enter it again
        else:
            stored = (stored or "").strip()
            src[k] = "db" if stored else ""
        v[k] = stored
    sc = " ".join((v["scopes"] or "openid profile email").replace(",", " ").split())
    if "openid" not in sc.split():
        sc = "openid " + sc
    cfg = {**v, "scopes": sc, "username_claim": v["username_claim"] or "preferred_username",
           "groups_claim": v["groups_claim"] or "groups", "label": (v["label"] or "OpenID Connect")[:40],
           "domains": sorted({d.strip().lower().lstrip("@") for d in v["admin_domains"].replace(";", ",").split(",") if d.strip()}),
           "on": bool(v["issuer"] and v["client_id"]), "src": src}
    _OIDC_CFG["cfg"] = cfg
    return cfg


def oidc_reset():
    _OIDC_CFG.clear()
    _OIDC.update(doc=None, doc_at=0.0, jwks=None, jwks_at=0.0, err="", err_at="")


class OidcError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, str(detail)[:80]


def oidc_allow(c):
    from ..calendars.subscriptions import cal_allow, cal_allow_parse
    return frozenset(cal_allow(c) | set(cal_allow_parse(OIDC_ALLOW_ENV)[0]))


def _oidc_url_ok(u, allow):
    """https, or http for an allow-listed (internal) host."""
    from ..calendars.subscriptions import cal_host_allowed
    p = urllib.parse.urlsplit(u or "")
    if not p.hostname or p.username or p.password:
        return False
    try:
        port = p.port
    except ValueError:
        return False
    return p.scheme == "https" or (p.scheme == "http" and cal_host_allowed(allow, p.hostname, port or 80))


def oidc_http_json(c, url, method="GET", data=None, headers=None, auth=None):
    from ..calendars.subscriptions import cal_http, CalError
    allow = oidc_allow(c)
    if not _oidc_url_ok(url, allow):
        raise OidcError("config", "not https and not an allowed internal host")
    hd = {"User-Agent": f"{APP_NAME}/{APP_VERSION} (OpenID Connect)", "Accept": "application/json", **(headers or {})}
    try:
        st, h, raw, _ = cal_http(url, method=method, body=data, headers=hd, auth=auth, allow=allow)
    except CalError as e:
        if e.code in ("http", "auth", "not_found"):  # an HTTP error status: the body is not read (never logged)
            raise OidcError("http", e.detail or e.code) from None
        raise OidcError("network", e.code) from None
    try:
        j = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise OidcError("json") from None
    if not isinstance(j, dict):
        raise OidcError("json")
    return j


def oidc_doc(c, force=False):
    from ..notify.alerts import aa_fail
    now = time.time()
    if _OIDC["doc"] and not force and now - _OIDC["doc_at"] < OIDC_CACHE:
        return _OIDC["doc"]
    try:
        iss = oidc_cfg(c)["issuer"].rstrip("/")
        d = oidc_http_json(c, iss + "/.well-known/openid-configuration")
        if str(d.get("issuer") or "").rstrip("/") != iss:
            raise OidcError("config", "issuer mismatch")
        allow = oidc_allow(c)
        for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not isinstance(d.get(k), str) or not _oidc_url_ok(d[k], allow):
                raise OidcError("config", k)
        if d.get("userinfo_endpoint") and not _oidc_url_ok(str(d["userinfo_endpoint"]), allow):
            d["userinfo_endpoint"] = None
        _OIDC.update(doc=d, doc_at=now, err="")
        return d
    except OidcError as e:
        _OIDC.update(err=e.code + (":" + e.detail if e.detail else ""), err_at=iso(now_utc()))
        aa_fail("oidc", e.code)
        raise


def oidc_jwks(c, doc, force=False):
    now = time.time()
    if _OIDC["jwks"] is not None and not force and now - _OIDC["jwks_at"] < OIDC_CACHE:
        return _OIDC["jwks"]
    if force and now - _OIDC["jwks_at"] < 10:  # an unknown key id asks again at most every 10 s
        return _OIDC["jwks"] or []
    j = oidc_http_json(c, doc["jwks_uri"])
    keys = [k for k in (j.get("keys") or []) if isinstance(k, dict)] if isinstance(j.get("keys"), list) else []
    _OIDC.update(jwks=keys, jwks_at=now)
    return keys


def _b64u_int(s):
    from ..notify.push import _b64u_dec
    return int.from_bytes(_b64u_dec(s), "big")


_EC = {"ES256": (ec.SECP256R1, "P-256", hashes.SHA256, 32), "ES384": (ec.SECP384R1, "P-384", hashes.SHA384, 48),
       "ES512": (ec.SECP521R1, "P-521", hashes.SHA512, 66)}
_SHA = {"256": hashes.SHA256, "384": hashes.SHA384, "512": hashes.SHA512}


def jwk_verify(k, alg, data, sig):
    """True when sig is a valid signature of data by the JWK k with alg (the key type must fit the algorithm)."""
    from ..notify.push import _b64u_dec
    try:
        if k.get("use") not in (None, "sig") or (k.get("alg") and k["alg"] != alg):
            return False
        if alg[:2] in ("RS", "PS"):
            if k.get("kty") != "RSA":
                return False
            pub = rsa.RSAPublicNumbers(_b64u_int(k["e"]), _b64u_int(k["n"])).public_key()
            if pub.key_size < 2048:
                return False
            h = _SHA[alg[2:]]()
            pad = padding.PKCS1v15() if alg[:2] == "RS" else padding.PSS(mgf=padding.MGF1(h), salt_length=h.digest_size)
            pub.verify(sig, data, pad, h)
            return True
        if alg in _EC:
            curve, crv, h, n = _EC[alg]
            if k.get("kty") != "EC" or k.get("crv") != crv or len(sig) != 2 * n:
                return False
            pub = ec.EllipticCurvePublicNumbers(_b64u_int(k["x"]), _b64u_int(k["y"]), curve()).public_key()
            pub.verify(encode_dss_signature(int.from_bytes(sig[:n], "big"), int.from_bytes(sig[n:], "big")), data, ec.ECDSA(h()))
            return True
        if alg == "EdDSA":
            if k.get("kty") != "OKP" or k.get("crv") != "Ed25519":
                return False
            ed25519.Ed25519PublicKey.from_public_bytes(_b64u_dec(k["x"])).verify(sig, data)
            return True
    except (InvalidSignature, KeyError, ValueError, TypeError):
        return False
    return False


def oidc_verify_id_token(c, doc, tok, nonce):
    from ..notify.push import _b64u_dec
    parts = tok.split(".") if isinstance(tok, str) and len(tok) < 20000 else []
    if len(parts) != 3:
        raise OidcError("token", "format")
    try:
        head = json.loads(_b64u_dec(parts[0]))
        claims = json.loads(_b64u_dec(parts[1]))
        sig = _b64u_dec(parts[2])
    except (ValueError, TypeError):
        raise OidcError("token", "format") from None
    if not isinstance(head, dict) or not isinstance(claims, dict):
        raise OidcError("token", "format")
    alg = head.get("alg")
    offered = doc.get("id_token_signing_alg_values_supported")
    if alg not in OIDC_ALGS or (isinstance(offered, list) and alg not in offered):
        raise OidcError("token", "alg")
    if head.get("crit"):
        raise OidcError("token", "crit")
    data = (parts[0] + "." + parts[1]).encode()
    kid = head.get("kid")

    def pick(keys):
        return [k for k in keys if not kid or k.get("kid") == kid]
    keys = pick(oidc_jwks(c, doc))
    if not keys and kid:
        keys = pick(oidc_jwks(c, doc, force=True))
    if not any(jwk_verify(k, alg, data, sig) for k in keys):
        raise OidcError("token", "signature")
    now = time.time()
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if str(claims.get("iss") or "") != str(doc["issuer"]):
        raise OidcError("token", "iss")
    cid = oidc_cfg(c)["client_id"]
    if cid not in auds:
        raise OidcError("token", "aud")
    if (len(auds) > 1 or "azp" in claims) and claims.get("azp") != cid:
        raise OidcError("token", "azp")
    for k in ("exp", "iat"):
        if isinstance(claims.get(k), bool) or not isinstance(claims.get(k), (int, float)):
            raise OidcError("token", k)
    if claims["exp"] < now - OIDC_LEEWAY:
        raise OidcError("token", "exp")
    if claims["iat"] > now + OIDC_LEEWAY * 5:
        raise OidcError("token", "iat")
    if isinstance(claims.get("nbf"), (int, float)) and claims["nbf"] > now + OIDC_LEEWAY:
        raise OidcError("token", "nbf")
    if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce):
        raise OidcError("token", "nonce")
    if not isinstance(claims.get("sub"), str) or not 0 < len(claims["sub"]) <= 255:
        raise OidcError("token", "sub")
    return claims


def _oidc_groups(v):
    if isinstance(v, str):
        return {x.strip() for x in v.split(",") if x.strip()}
    if isinstance(v, list):
        return {str(x) for x in v if isinstance(x, (str, int))}
    return set()


def _truthy(v):
    return v is True or (isinstance(v, str) and v.lower() == "true")


def oidc_account(c, claims):
    """The user for these claims (links / creates as configured) or OidcError(no_account|disabled|group|taken)."""
    from ..lists.groups import grp_oidc_sync
    from ..accounts.users import _active_admins
    from ..notify.alerts import aa_now
    subject = f"{claims['iss']}|{claims['sub']}"
    oc = oidc_cfg(c)
    groups = _oidc_groups(claims.get(oc["groups_claim"]))
    if oc["required_group"] and oc["required_group"] not in groups:
        raise OidcError("group")
    uname = str(claims.get(oc["username_claim"]) or "").strip().lower()
    # 2.9.0: Microsoft Entra marks a verified e-mail with xms_edov (optional claim) instead of email_verified
    verified = _truthy(claims.get("email_verified")) or (claims.get("email_verified") is None and _truthy(claims.get("xms_edov")))
    email = str(claims.get("email") or "").strip().lower() if verified else ""
    # admins: the admin group and / or a verified e-mail of an admin domain (2.9.0, #438); None = neither is set up
    admin_rule = bool(oc["admin_group"] or oc["domains"])
    admin_want = (bool(oc["admin_group"]) and oc["admin_group"] in groups) or \
        (bool(oc["domains"]) and "@" in email and email.rsplit("@", 1)[1] in oc["domains"])
    u = c.execute("SELECT * FROM users WHERE oidc_subject=?", (subject,)).fetchone()
    how = "subject"
    if not u and uname:
        u = c.execute("SELECT * FROM users WHERE username=? AND oidc_subject IS NULL", (uname,)).fetchone()
        how = "username"
    if not u and email:
        u = c.execute("SELECT * FROM users WHERE lower(email)=? AND oidc_subject IS NULL", (email,)).fetchone()
        how = "email"
    if not u:
        if gsetting(c, "oidc_autocreate") != "1":
            raise OidcError("no_account", uname or "?")
        if not USERNAME_RE.fullmatch(uname) and email:
            # 2.9.0: providers without a fitting user name (Google: none, Entra: anna@corp.example) -> a NEW account is named
            # after the verified e-mail's local part. Only for creating: existing accounts are never matched this way.
            uname = re.sub(r"[^a-z0-9._-]", "", email.split("@", 1)[0])[:32].lstrip("._-")
        if not USERNAME_RE.fullmatch(uname):
            raise OidcError("taken", "invalid username claim")
        if c.execute("SELECT 1 FROM users WHERE username=?", (uname,)).fetchone():
            raise OidcError("taken", uname)
        name = str(claims.get("name") or "").strip()[:60] or uname
        uid = create_user(c, uname, name, None, None, admin_want, onboard=True)
        ensure_inbox(c, uid)
        c.execute("UPDATE users SET oidc_subject=?, email=? WHERE id=?", (subject, email or None, uid))
        bump(c)
        aa_now("security", f"oidc:new:{uname}", N_("{0} was created by the first login with the OIDC provider."), [uname])
        grp_oidc_sync(c, uid, groups)  # 2.10.0 (#441)
        return _user(c, uid)
    if u["disabled"]:
        raise OidcError("disabled", u["username"])
    if how != "subject":
        c.execute("UPDATE users SET oidc_subject=? WHERE id=?", (subject, u["id"]))
        aa_now("security", f"oidc:link:{u['username']}", N_("{0} was linked to the OIDC provider (matched by {1})."),
               [u["username"], {"t": N_("user name") if how == "username" else N_("e-mail")}])
    if admin_rule:
        want = admin_want
        if want != bool(u["is_admin"]) and (want or _active_admins(c, u["id"])):
            c.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if want else 0, u["id"]))
            aa_now("security", f"oidc:admin:{u['username']}:{int(want)}",
                   N_("{0} is now an admin (set by {1}).") if want else N_("{0} is no longer an admin (OIDC group)."),
                   [u["username"], "OIDC"] if want else [u["username"]])
    grp_oidc_sync(c, u["id"], groups)  # 2.10.0 (#441): synced groups follow the provider's group claim
    return _user(c, u["id"])


def _oidc_fail_redirect(code):
    resp = redirect("/#login-error=" + code, 303)
    resp.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
    return resp


@app.get("/api/auth/oidc/start")
def oidc_start():
    from ..notify.push import _b64u
    if not oidc_cfg()["on"]:
        return err(tr("OIDC login is not configured"), 404)
    ip_key = [("oidc:" + client_ip(), 60)]
    if _rate_blocked(ip_key):
        return err(tr("Too many failed logins, please wait a few minutes"), 429)
    _rate_fail(ip_key)  # every start counts (60 per 15 min and IP): the state table cannot be flooded
    c = db()
    try:
        doc = oidc_doc(c)
    except OidcError as e:
        print("OIDC discovery failed:", e.code, e.detail, flush=True)
        return _oidc_fail_redirect("failed")
    state, nonce, verifier, bind = (secrets.token_urlsafe(32) for _ in range(4))
    now = time.time()
    with _OIDC_LOCK:
        for k in [k for k, v in _OIDC_STATES.items() if v["exp"] < now]:
            del _OIDC_STATES[k]
        if len(_OIDC_STATES) >= 1000:
            del _OIDC_STATES[min(_OIDC_STATES, key=lambda k: _OIDC_STATES[k]["exp"])]
        _OIDC_STATES[state] = {"bind": _token_hash(bind), "nonce": nonce, "verifier": verifier, "exp": now + OIDC_STATE_TTL,
                               "remember": request.args.get("remember", "1") != "0"}
    q = {"response_type": "code", "client_id": oidc_cfg(c)["client_id"], "redirect_uri": OIDC_REDIRECT, "scope": oidc_cfg(c)["scopes"],
         "state": state, "nonce": nonce, "code_challenge_method": "S256",
         "code_challenge": _b64u(hashlib.sha256(verifier.encode()).digest())}
    ae = doc["authorization_endpoint"]
    resp = redirect(ae + ("&" if "?" in ae else "?") + urllib.parse.urlencode(q), 302)
    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"
    resp.set_cookie(OIDC_COOKIE, bind, max_age=OIDC_STATE_TTL, httponly=True, samesite="Lax", secure=secure, path="/api/auth/oidc")
    return resp


@app.get("/api/auth/oidc/callback")
def oidc_callback():
    from ..notify.alerts import aa_count, aa_fail, aa_ok
    if not oidc_cfg()["on"]:
        return err(tr("OIDC login is not configured"), 404)
    state = request.args.get("state") or ""
    with _OIDC_LOCK:
        st = _OIDC_STATES.pop(state, None) if state else None
    bind = request.cookies.get(OIDC_COOKIE) or ""
    if not st or st["exp"] < time.time() or not bind or not hmac.compare_digest(st["bind"], _token_hash(bind)):
        return _oidc_fail_redirect("state")
    if request.args.get("error"):
        return _oidc_fail_redirect("denied")
    code = request.args.get("code") or ""
    if not code or len(code) > 4000:
        return _oidc_fail_redirect("failed")
    c = db()
    try:
        doc = oidc_doc(c)
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": OIDC_REDIRECT, "code_verifier": st["verifier"]}
        methods = doc.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        auth = None
        oc = oidc_cfg(c)
        if oc["client_secret"] and "client_secret_basic" in methods:
            auth = (urllib.parse.quote(oc["client_id"], safe=""), urllib.parse.quote(oc["client_secret"], safe=""))
        else:
            form["client_id"] = oc["client_id"]
            if oc["client_secret"]:
                form["client_secret"] = oc["client_secret"]
        tokr = oidc_http_json(c, doc["token_endpoint"], "POST", urllib.parse.urlencode(form).encode(),
                              {"Content-Type": "application/x-www-form-urlencoded"}, auth)
        claims = oidc_verify_id_token(c, doc, tokr.get("id_token"), st["nonce"])
        at = tokr.get("access_token")
        if doc.get("userinfo_endpoint") and isinstance(at, str) and at and str(tokr.get("token_type", "")).lower() == "bearer":
            try:
                ui = oidc_http_json(c, doc["userinfo_endpoint"], headers={"Authorization": "Bearer " + at})
                if ui.get("sub") == claims["sub"]:
                    claims = {**{k: v for k, v in ui.items() if k not in ("iss", "aud", "exp", "iat", "nbf", "nonce", "azp")}, **claims}
            except OidcError as e:
                print("OIDC userinfo skipped:", e.code, e.detail, flush=True)
        u = oidc_account(c, claims)
    except OidcError as e:
        c.rollback()
        if e.code in ("no_account", "disabled", "group", "taken"):
            print("OIDC login refused:", e.code, e.detail, flush=True)
            aa_count("security", "logins", client_ip(), user="oidc:" + e.code)
            return _oidc_fail_redirect(e.code)
        print("OIDC login failed:", e.code, e.detail, flush=True)
        _OIDC.update(err=e.code + (":" + e.detail if e.detail else ""), err_at=iso(now_utc()))
        aa_fail("oidc", e.code)
        return _oidc_fail_redirect("failed")
    aa_ok("oidc")
    _OIDC["err"] = ""
    old = request.cookies.get(COOKIE)
    if old:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(old),))
    tok, age = start_session(c, u["id"], st["remember"], "oidc")
    c.commit()
    resp = set_cookie(redirect("/", 303), tok, age)
    resp.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
    return resp


def oidc_public(c):
    oc = oidc_cfg(c)
    stored = {k: ("" if k == "client_secret" else gsetting(c, "oidc_" + k)) for k, _ in OIDC_FIELDS}
    return {"configured": oc["on"], "issuer": oc["issuer"], "client_id": oc["client_id"], "secret_set": bool(oc["client_secret"]),
            "scopes": oc["scopes"], "username_claim": oc["username_claim"], "groups_claim": oc["groups_claim"],
            "required_group": oc["required_group"], "admin_group": oc["admin_group"], "label": oc["label"],
            "admin_domains": ", ".join(oc["domains"]), "env": sorted(k for k, s_ in oc["src"].items() if s_ == "env"),
            "stored": stored, "secret_lost": oc["src"].get("client_secret") == "lost", "secret_key": bool(SECRET_KEY),
            "redirect_uri": OIDC_REDIRECT, "autocreate": gsetting(c, "oidc_autocreate") == "1",
            "error": _OIDC["err"], "error_at": _OIDC["err_at"] if _OIDC["err"] else "",
            "linked": c.execute("SELECT COUNT(*) FROM users WHERE oidc_subject IS NOT NULL").fetchone()[0]}


@app.put("/api/admin/oidc")
def oidc_admin_set():
    """2.9.0 (#438): the stored provider settings (admins). Fields set by KALMIDO_OIDC_* cannot be changed here (409).
    client_secret: a new value is sealed with KALMIDO_SECRET_KEY; "" removes it; missing = unchanged."""
    from ..accounts.users import need_admin
    from ..notify.alerts import aa_now
    need_admin()
    b, c = body(), db()
    keys = dict(OIDC_FIELDS)
    unknown = [k for k in b if k not in keys]
    if unknown:
        return err(tr("Unknown field"), 400)
    env = [k for k in b if os.environ.get(keys[k], "").strip()]
    if env:
        return err(tr("Set by the server environment: {0}", ", ".join(sorted(env))), 409)
    vals = {}
    for k, v in b.items():
        if not isinstance(v, str) or len(v) > OIDC_FIELD_MAX[k]:
            return err(tr("Invalid value: {0}", k))
        v = v.strip()
        if k == "issuer" and v:
            pu = urllib.parse.urlsplit(v)
            if pu.scheme not in ("https", "http") or not pu.hostname or pu.query or pu.fragment or pu.username:
                return err(tr("Invalid value: {0}", tr("Provider")))
        if k == "admin_domains" and v and not all(re.fullmatch(r"@?[a-z0-9.-]+\.[a-z]{2,}", d.strip().lower())
                                                   for d in v.replace(";", ",").split(",") if d.strip()):
            return err(tr("Invalid value: {0}", tr("Admin e-mail domains")))
        vals[k] = v
    for k, v in vals.items():
        gset(c, "oidc_" + k, oidc_seal(v) if k == "client_secret" and v else v)
    oidc_reset()
    bump(c)
    c.commit()
    aa_now("security", f"oidc:cfg:{int(time.time())}", N_("{0} changed the OIDC login settings."), [g.user["username"]])
    return jsonify(oidc_public(c))


@app.post("/api/admin/oidc/check")
def oidc_admin_check():
    """Fetches the provider's discovery document now (admins): {ok, error, issuer, endpoints}."""
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    if not oidc_cfg(c)["on"]:
        return err(tr("OIDC login is not configured"), 409)
    try:
        d = oidc_doc(c, force=True)
        oidc_jwks(c, d, force=True)
    except OidcError as e:
        return jsonify(ok=False, error=e.code + (": " + e.detail if e.detail else ""))
    return jsonify(ok=True, error="", issuer=d.get("issuer"),
                   scopes=d.get("scopes_supported") or [], claims=d.get("claims_supported") or [])
