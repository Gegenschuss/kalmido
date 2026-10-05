"""Configuration from the environment, the outbound-HTTP guard, proxy and login settings, the Flask app object.

Every other module imports from here (directly or through core/db.py); this module imports no other module of the package."""
import base64
import contextlib
import csv
import email.message
import email.policy
import email.utils
import errno
import functools
import glob
import hashlib
import hmac
import html
import http.client
import imaplib
import io
import ipaddress
import json
import math
import mimetypes
mimetypes.add_type("font/woff2", ".woff2")  # slim images have no /etc/mime.types (bundled Geist fonts)
import os
import re
import uuid
import secrets
import shutil
import smtplib
import socket
import sqlite3
import ssl
import struct
import tempfile
import threading
import unicodedata
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
import icalendar
import recurring_ical_events
from dateutil.rrule import rrulestr
import segno
import webauthn
from webauthn.helpers import structs as wa_structs
from flask import Flask, Response, g, has_request_context, jsonify, redirect, request, send_file, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

DB = os.environ.get("TASKS_DB", "/data/tasks.db")
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")  # topic of the first admin (seed); other users: settings
NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")  # optional ntfy access token (write access to NTFY_TOPIC)
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:3040")
# 1.9.0: link to a signed, generic iOS shortcut ("Share to Kalmido", asks for address + upload token on import),
# shown in Settings > Integrations > Share from your phone. Empty = the link is hidden.
IOS_SHORTCUT_URL = os.environ.get("KALMIDO_IOS_SHORTCUT_URL", "").strip()
APP_NAME = "Kalmido"
APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the folder of app.py (+ VERSION, static/)


def _read_version():
    """VERSION file next to app.py (x.y.z); 0.0.0 when missing or malformed."""
    try:
        with open(os.path.join(APP_DIR, "VERSION"), encoding="utf-8") as f:
            v = f.read().strip()
    except OSError:
        return "0.0.0"
    return v if re.fullmatch(r"\d+\.\d+\.\d+", v) else "0.0.0"


APP_VERSION = _read_version()
# Update check (admins only, server side, never updates anything): once a day the latest GitHub release
# is compared with VERSION. KALMIDO_UPDATE_CHECK=0 turns it off for good; admins can also switch it off.
UPDATE_CHECK_ENV = os.environ.get("KALMIDO_UPDATE_CHECK", "1").strip().lower() not in ("0", "false", "no", "off")
# v1.1: new users get a "Getting started" sample list and the welcome tour (existing users never do).
# KALMIDO_ONBOARDING=0 turns both off (new users start empty, as before; the test suites use this).
ONBOARDING_ENV = os.environ.get("KALMIDO_ONBOARDING", "1").strip().lower() not in ("0", "false", "no", "off")
UPDATE_URL = os.environ.get("KALMIDO_UPDATE_URL", "https://api.github.com/repos/Gegenschuss/kalmido/releases/latest")
UPDATE_EVERY = 6 * 3600  # s (1.9.0: was a day; releases come more often)
UPDATE_RETRY = 3600      # s: after a failed check (e.g. GitHub's rate limit for anonymous requests, HTTP 403 / 429)
UPDATE_MAX_BYTES = 256 * 1024
WATCHDOG_INTERVAL = int(os.environ.get("TASKS_WATCHDOG_INTERVAL", "30"))

ATT_DIR = os.environ.get("TASKS_ATTACHMENTS", os.path.join(os.path.dirname(DB), "attachments"))
MAX_FILE_MB = int(os.environ.get("TASKS_MAX_FILE_MB", "50"))
# shown in the browser; everything else is served as a download (svg/html could carry script)
INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp",
                "image/heic", "image/heif", "application/pdf"}

# Paperless-ngx integration (link documents, send attachments). Empty token = feature off.
PL_TOKEN = os.environ.get("PAPERLESS_TOKEN", "")
PL_API = os.environ.get("PAPERLESS_API", "").rstrip("/")
PL_PUBLIC = os.environ.get("PAPERLESS_PUBLIC_URL", "").rstrip("/")


def _secret_key_env():
    """2.1.0 (#180): KALMIDO_SECRET_KEY = 32 random bytes, base64 (standard or URL-safe). Encrypts the users' Paperless
    tokens. It never lives in the database or the data directory (so a backup alone never reveals a token); without it
    no token can be stored. Losing it means everyone enters their tokens again. Returns (key or None, problem)."""
    raw = os.environ.get("KALMIDO_SECRET_KEY", "").strip()
    if not raw:
        return None, "unset"
    try:
        k = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_" if ("-" in raw or "_" in raw) else None, validate=True)
    except (ValueError, TypeError):
        return None, "invalid"
    return (k, "") if len(k) == 32 else (None, "invalid")


SECRET_KEY, SECRET_KEY_PROBLEM = _secret_key_env()

# Optional share inbox: every message on an ntfy topic becomes an inbox task (files as attachments).
# Needs a token with read access to that topic (NTFY_INBOX_TOKEN).
NTFY_IN = {"token": os.environ.get("NTFY_INBOX_TOKEN", ""), "url": os.environ.get("NTFY_INBOX_URL", "").rstrip("/"),
           "public": os.environ.get("NTFY_INBOX_PUBLIC", "").rstrip("/"), "topic": os.environ.get("NTFY_INBOX_TOPIC", "inbox"),
           "user": os.environ.get("NTFY_INBOX_USER", "").strip().lower()}  # username; empty = first admin


# ---- outbound HTTP (ntfy publish, ntfy inbox, Paperless). Only http/https (no file://, ftp://, data:),
# no proxy from the environment, redirects only within the same origin (a redirect never carries a token
# to another host). User-supplied URLs (task links, shared text) are NEVER fetched server-side.
class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        a, b = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (a.scheme, a.netloc.lower()) != (b.scheme, b.netloc.lower()):
            return None  # -> HTTPError with the 3xx code
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.OpenerDirector()
for _h in (urllib.request.UnknownHandler(), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
           urllib.request.HTTPDefaultErrorHandler(), _SameOriginRedirect(), urllib.request.HTTPErrorProcessor()):
    _OPENER.add_handler(_h)


def safe_urlopen(req, timeout):
    """urlopen for server-side requests: http(s) only, same-origin redirects only."""
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise urllib.error.URLError(f"scheme not allowed: {urllib.parse.urlsplit(url).scheme or '?'}")
    return _OPENER.open(req, timeout=timeout)


def _origin(u):
    p = urllib.parse.urlsplit(u)
    try:
        port = p.port or {"http": 80, "https": 443}.get(p.scheme)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        return None
    return p.scheme, p.hostname.lower(), port


def ntfy_attachment_url(u):
    """Internal fetch URL of an inbox attachment, or None when the URL is not on the configured ntfy
    server (NTFY_INBOX_PUBLIC or NTFY_INBOX_URL, same origin + path below the base). The inbox token is
    only ever sent to that server."""
    if not isinstance(u, str) or not u or len(u) > 2000:
        return None
    o = _origin(u)
    if not o:
        return None
    path = urllib.parse.urlsplit(u).path
    for base in (NTFY_IN["public"], NTFY_IN["url"]):
        if not base or _origin(base) != o:
            continue
        bpath = urllib.parse.urlsplit(base).path.rstrip("/")
        if not path.startswith(bpath + "/") or "/../" in path + "/" or "/./" in path + "/":
            continue
        rest = u.split("://", 1)[1]
        rest = rest[rest.find("/"):] if "/" in rest else "/"
        bp = bpath or ""
        return NTFY_IN["url"] + rest[len(bp):]
    return None


def ntfy_inbox_allowed():
    """The share inbox imports whatever is published to the topic: refuse a guessable topic on the
    public ntfy.sh (anyone could publish there)."""
    host = (urllib.parse.urlsplit(NTFY_IN["url"]).hostname or "").lower()
    if host in ("ntfy.sh", "www.ntfy.sh") and (len(NTFY_IN["topic"]) < 16 or NTFY_IN["topic"].lower() == "inbox"):
        return False
    return True


def _nets(s):
    out = []
    for part in (s or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                print("trusted proxies (AUTH_TRUSTED_PROXIES / KALMIDO_TRUSTED_PROXIES): ignoring invalid entry", repr(part), flush=True)
    return out


# ---- login. Proxy mode: the header is trusted only from these peers (and only on AUTH_PROXY_PORT
# if set: a second listener, so other containers that share the docker gateway IP cannot spoof it).
AUTH_HEADER = os.environ.get("AUTH_PROXY_HEADER", "").strip()
AUTH_TRUSTED = _nets(os.environ.get("AUTH_TRUSTED_PROXIES", ""))
AUTH_PROXY_PORT = os.environ.get("AUTH_PROXY_PORT", "").strip()
# ---- 2.10.0 (#445): reverse proxies whose X-Forwarded-For / -Proto / -Host are believed (KALMIDO_TRUSTED_PROXIES:
# comma-separated addresses or networks; default loopback + the docker bridge gateway 172.17.0.1, "none" = trust nobody).
# The AUTH_TRUSTED_PROXIES peers (proxy login) are trusted proxies too. waitress' own trusted_proxy takes ONE address,
# so the app wraps itself in waitress' proxy-header parser per peer (proxy_mw below; waitress itself clears nothing).
# KALMIDO_TRUSTED_PROXY_COUNT: proxies in a row in front of the app (default 1: the rightmost X-Forwarded-For entry,
# the one the proxy appended, is the client; earlier ones were sent by the client and are ignored).
_TP_RAW = os.environ.get("KALMIDO_TRUSTED_PROXIES", "127.0.0.1,::1,172.17.0.1").strip()
TRUSTED_PROXIES = ([] if _TP_RAW.lower() in ("none", "off", "0") else _nets(_TP_RAW)) + AUTH_TRUSTED
try:
    TRUSTED_PROXY_COUNT = max(1, min(5, int(os.environ.get("KALMIDO_TRUSTED_PROXY_COUNT", "1"))))
except ValueError:
    TRUSTED_PROXY_COUNT = 1
TRUSTED_PROXY_HEADERS = {"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"}
BOOT_USER = (os.environ.get("AUTH_BOOTSTRAP_USER") or "admin").strip().lower()
BOOT_NAME = (os.environ.get("AUTH_BOOTSTRAP_NAME") or BOOT_USER.capitalize()).strip()
BOOT_PROXY = os.environ.get("AUTH_BOOTSTRAP_PROXY_LOGIN", "").strip() or None
SESSION_DAYS = int(os.environ.get("AUTH_SESSION_DAYS", "30"))
COOKIE = "kalmido_session"
CSRF_HEADER, CSRF_VALUE = "X-Requested-With", "kalmido"
# reachable without a user; the proxy header is never read on PROXY_IGNORE paths (they bypass the
# proxy login, so a client could send its own header there)
OPEN_PATHS = {"/", "/sw.js", "/manifest.json", "/api/health", "/drop", "/drop/drop",
              "/api/auth/info", "/api/auth/login", "/api/auth/setup", "/api/auth/logout",
              # second step of a built-in login (a short-lived ticket cookie, see "two-factor"), passkey login, OIDC
              "/api/auth/2fa", "/api/auth/2fa/passkey/options", "/api/auth/2fa/passkey",
              "/api/auth/enrol/totp", "/api/auth/enrol/totp/confirm", "/api/auth/enrol/passkey/options", "/api/auth/enrol/passkey",
              "/api/auth/passkey/options", "/api/auth/passkey", "/api/auth/oidc/start", "/api/auth/oidc/callback",
              "/api/auth/invite/check", "/api/auth/invite/accept"}  # 2.22.0 (#697): the "Set up your account" page
PROXY_IGNORE = {"/drop", "/drop/drop", "/manifest.json", "/sw.js", "/api/health"}
ICAL_PREFIX = "/ical/"  # calendar feed: the secret token in the path is the only credential (never the proxy header)
# package B: the REST API authenticates ONLY with a personal access token (Authorization: Bearer abk_...), never with
# the proxy header or a session cookie; a public list link (/s/<token>) has no user at all
API_PREFIX = "/api/v1/"
PUB_PREFIX = "/s/"
USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
EMAIL_RE = re.compile(r"[^@\s]{1,100}@[^@\s]{1,100}\.[^@\s]{1,60}")
MIN_PASSWORD = 8

# import name "app" + root_path: the same app name and static folder as when everything lived in app.py
app = Flask("app", root_path=APP_DIR, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_MB * 4 * 1024 * 1024  # one request may carry several files
