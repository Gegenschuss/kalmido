"""Fake OpenID Connect provider for oidc_test.py, started INSIDE the test container (127.0.0.1:9990).
Discovery, JWKS (every key in /data/oidc/signing/<kid>.pem), token endpoint (client_secret_basic, one-time codes,
PKCE S256, exact redirect_uri) and userinfo. The test plays the browser + the login page: it reads state / nonce /
code_challenge from the authorization redirect and writes the code it wants into /data/oidc/codes.json:
  {code: {"nonce", "challenge", "claims": {...}, "userinfo": {...} | null, "mode": "ok" | <broken token>, "kid": null}}
Every request is logged to /data/oidc/log.jsonl (the test checks PKCE, client auth, caching)."""
import base64
import glob
import hashlib
import hmac
import http.server
import json
import os
import time
import urllib.parse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

ISS, CLIENT, SECRET = "http://127.0.0.1:9990", "kalmido-test", "s3cret:/x+y"
REDIRECT = "https://kalmido.example/api/auth/oidc/callback"
D = "/data/oidc"


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def log(rec):
    with open(f"{D}/log.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")


def keys():
    out = {}
    for p in sorted(glob.glob(f"{D}/signing/*.pem")):
        out[os.path.basename(p)[:-4]] = serialization.load_pem_private_key(open(p, "rb").read(), None)
    return out


def jwk(kid, k):
    pub = k.public_key()
    if isinstance(pub, rsa.RSAPublicKey):
        n = pub.public_numbers()
        return {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256", "n": b64u(n.n.to_bytes((n.n.bit_length() + 7) // 8, "big")),
                "e": b64u(n.e.to_bytes(3, "big"))}
    n = pub.public_numbers()
    return {"kty": "EC", "kid": kid, "use": "sig", "alg": "ES256", "crv": "P-256", "x": b64u(n.x.to_bytes(32, "big")), "y": b64u(n.y.to_bytes(32, "big"))}


def sign(head, claims, k, alg):
    data = (b64u(json.dumps(head).encode()) + "." + b64u(json.dumps(claims).encode())).encode()
    if alg == "none":
        sig = b""
    elif alg == "HS256":
        sig = hmac.new(SECRET.encode(), data, hashlib.sha256).digest()
    elif alg == "RS256":
        sig = k.sign(data, padding.PKCS1v15(), hashes.SHA256())
    else:
        r, s = decode_dss_signature(k.sign(data, ec.ECDSA(hashes.SHA256())))
        sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return data.decode() + "." + b64u(sig)


class H(http.server.BaseHTTPRequestHandler):
    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urllib.parse.urlsplit(self.path)
        log({"m": "GET", "path": p.path, "auth": self.headers.get("Authorization", "")})
        if p.path == "/.well-known/openid-configuration":
            return self.send(200, {"issuer": ISS, "authorization_endpoint": ISS + "/authorize", "token_endpoint": ISS + "/token",
                                   "jwks_uri": ISS + "/jwks", "userinfo_endpoint": ISS + "/userinfo",
                                   "id_token_signing_alg_values_supported": ["RS256", "ES256"],
                                   "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                                   "code_challenge_methods_supported": ["S256"]})
        if p.path == "/jwks":
            return self.send(200, {"keys": [jwk(kid, k) for kid, k in keys().items()]})
        if p.path == "/userinfo":
            tok = self.headers.get("Authorization", "")[7:]
            codes = json.load(open(f"{D}/codes.json"))
            for c in codes.values():
                if c.get("at") == tok and c.get("userinfo") is not None:
                    return self.send(200, c["userinfo"])
            return self.send(401, {"error": "invalid_token"})
        self.send(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = dict(urllib.parse.parse_qsl(self.rfile.read(n).decode()))
        auth = self.headers.get("Authorization", "")
        log({"m": "POST", "path": self.path, "auth": auth, "form": form})
        if self.path != "/token":
            return self.send(404, {})
        try:
            cid, sec = base64.b64decode(auth[6:]).decode().split(":", 1)
            cid, sec = urllib.parse.unquote(cid), urllib.parse.unquote(sec)
        except Exception:  # noqa: BLE001
            cid = sec = ""
        if cid != CLIENT or sec != SECRET:
            return self.send(401, {"error": "invalid_client"})
        codes = json.load(open(f"{D}/codes.json"))
        c = codes.get(form.get("code", ""))
        if not c or c.get("used") or form.get("grant_type") != "authorization_code" or form.get("redirect_uri") != REDIRECT:
            return self.send(400, {"error": "invalid_grant"})
        if b64u(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) != c["challenge"]:
            return self.send(400, {"error": "invalid_grant", "error_description": "PKCE"})
        c["used"] = True
        c["at"] = "at-" + form["code"]
        json.dump(codes, open(f"{D}/codes.json", "w"))
        ks = keys()
        kid = c.get("kid") or next(iter(ks))
        k = ks[kid]
        alg = "RS256" if isinstance(k, rsa.RSAPrivateKey) else "ES256"
        now = int(time.time())
        cl = {"iss": ISS, "aud": CLIENT, "exp": now + 300, "iat": now, "nonce": c["nonce"], **c["claims"]}
        mode, head = c.get("mode", "ok"), {"alg": alg, "kid": kid, "typ": "JWT"}
        if mode == "bad_sig":
            k = serialization.load_pem_private_key(open(f"{D}/evil.pem", "rb").read(), None)
        elif mode == "wrong_aud":
            cl["aud"] = "someone-else"
        elif mode == "aud_list_no_azp":
            cl["aud"] = [CLIENT, "someone-else"]
        elif mode == "azp_bad":
            cl["aud"], cl["azp"] = [CLIENT, "someone-else"], "someone-else"
        elif mode == "expired":
            cl["exp"], cl["iat"] = now - 3600, now - 7200
        elif mode == "no_exp":
            del cl["exp"]
        elif mode == "wrong_nonce":
            cl["nonce"] = "not-the-nonce"
        elif mode == "wrong_iss":
            cl["iss"] = "http://evil.example"
        elif mode == "alg_none":
            head["alg"], alg = "none", "none"
        elif mode == "hs256":
            head["alg"], alg = "HS256", "HS256"
        elif mode == "tampered":
            tok = sign(head, cl, k, alg)
            h_, p_, s_ = tok.split(".")
            cl2 = dict(cl, sub="someone-else")
            return self.send(200, {"access_token": c["at"], "token_type": "Bearer",
                                   "id_token": h_ + "." + b64u(json.dumps(cl2).encode()) + "." + s_})
        tok = sign(head, cl, k, alg)
        self.send(200, {"access_token": c["at"], "token_type": "Bearer", "expires_in": 300, "id_token": tok})

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", 9990), H).serve_forever()
