"""2.143.0 B (#2152): an off-site target for the backups (instance admins): S3-compatible storage, WebDAV or SFTP.

ONE target per server. Only encrypted backups leave the server (the target cannot be switched on without the backup
passphrase; an unencrypted backup is never uploaded). After a successful backup the backup thread's next tick uploads the
newest backup (automatic or manual, never the safety copies of a restore), checks its size on the target (S3 also checks
Content-MD5 and the signed SHA-256 of the body), keeps the newest N backups there and deletes older ones of this app's own
name pattern (nothing else in the folder is touched). A failed upload is tried again a few times with a growing pause,
then the admin gets an alert; the next backup or "Upload now" starts again.

No new library: S3 with Signature V4 over http.client + hmac, WebDAV with PUT / PROPFIND / DELETE, SFTP through the sftp
program (openssh-client) with a key pair this app makes (ed25519; the admin puts the public key on the target). The SFTP
server's host key is recorded at the first test and from then on required (a changed key stops the upload).
Credentials (S3 keys, WebDAV password, the SFTP private key) are sealed with the server key (login.seal) and never leave
the server: the API says only whether they are set (2.223.2 C, #2871: a new address of the target drops them unless new ones
come with it, so they never follow the address to another host). Error texts carry status codes, the target's error code or the kind
of network error -- never a credential. Restoring from the target is not built in: download the file there and upload it
under Backups > Restore from a file.
2.223.2 C (#2871): a hosted server (hosting.hosted()) reaches only public addresses over https (SFTP: a public host), checked
when saving and again when connecting (the guard of the calendar subscriptions and webhooks); changing / testing / using
the target needs the step-up (orgcrypt.stepup_need), switching the upload on / off and the count kept do not.
"""
import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import g, jsonify, request

from ..core.access import Denied
from ..core.config import app, COOKIE
from ..core.i18n import N_, tr
from ..core.db import body, connect, db, err, gset, gsetting, iso, now_utc
from ..accounts.login import pend_set, pend_take, seal, unseal, wa_auth_options
from ..accounts.session import _token_hash
from ..accounts.bgjobs import bgj_add, bgj_fn, bgj_pending
from ..calendars.subscriptions import _cal_connector, CalError, cal_ip_public
from ..core.orgcrypt import RCK_FRESH_MIN, rck_step, rck_stepup
from .hosting import hosted
from ..notify.alerts import _env_int, aa_now
from .backup import BK_DIR, BK_NAME_RE, bk_list, bk_passphrase, need_backups

BKO_TYPES = ("s3", "webdav", "sftp")
BKO_TIMEOUT = _env_int("KALMIDO_OFFSITE_TIMEOUT", 120)    # s per network step (connect / read); SFTP: per run x 30
BKO_TRIES = 4                                             # failed uploads of one backup before the alert (5, 10, 20 min apart)
BKO_PAUSE = _env_int("KALMIDO_OFFSITE_RETRY_S", 300)
BKO_SEAL = "backup-offsite"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
BKO_ERR = {"conn": N_("The target could not be reached ({0})."),
           "auth": N_("The target refused the sign-in ({0})."),
           "http": N_("The target answered with an error ({0})."),
           "size": N_("The upload could not be confirmed: the target holds {0} bytes instead of {1}."),
           "tool": N_("The program sftp is missing on this server (package openssh-client)."),
           "hostkey": N_("The SFTP server's fingerprint has changed. If that is expected, forget the saved fingerprint and test again."),
           "not_encrypted": N_("Only encrypted backups are uploaded: switch on “Encrypt backups” with a passphrase."),
           "incomplete": N_("The target is not set up completely."),
           "sftp": N_("SFTP failed ({0})."),
           "blocked": N_("This server may only reach public addresses over https.")}  # 2.223.2 C (#2871): hosted
_BKO = {"running": "", "for": "", "tries": 0, "next": 0.0}
_BKO_LOCK = threading.Lock()


class OffsiteError(Exception):
    def __init__(self, code, *args):
        super().__init__(code)
        self.code, self.args_ = code, args

    def text(self, lg=None):
        return tr(BKO_ERR.get(self.code, BKO_ERR["http"]), *self.args_, lg=lg)


# ---- settings: the plain part (JSON) + the sealed credentials
def bko_conf(c):
    try:
        x = json.loads(gsetting(c, "bko_conf") or "{}")
    except ValueError:
        x = {}
    x = x if isinstance(x, dict) else {}
    for k in BKO_TYPES:
        x[k] = x.get(k) if isinstance(x.get(k), dict) else {}
    x["type"] = x.get("type") if x.get("type") in BKO_TYPES else ""
    x["on"] = x.get("on") is True
    x["keep"] = x["keep"] if isinstance(x.get("keep"), int) and 1 <= x["keep"] <= 365 else _keep_default(c)
    return x


def _keep_default(c):
    try:
        return max(1, min(365, int(gsetting(c, "bk_keep_daily") or 14)))
    except ValueError:
        return 14


def bko_secrets(c):
    try:
        x = json.loads(unseal(c, BKO_SEAL, gsetting(c, "bko_sec")) or "{}")
    except (InvalidTag, ValueError):
        x = {}
    return x if isinstance(x, dict) else {}


def _save(c, conf, sec=None):
    gset(c, "bko_conf", json.dumps(conf, sort_keys=True))
    if sec is not None:
        gset(c, "bko_sec", seal(c, BKO_SEAL, json.dumps(sec, sort_keys=True)) if sec else "")


def bko_fingerprint(line):
    """'host type base64' (a known_hosts line) -> 'type SHA256:…' as ssh-keygen -l shows it."""
    try:
        _, kt, b64 = (line or "").split()[:3]
        fp = base64.b64encode(hashlib.sha256(base64.b64decode(b64)).digest()).decode().rstrip("=")
        return f"{kt} SHA256:{fp}"
    except (ValueError, TypeError):
        return ""


def bko_missing(conf, sec):
    """What the chosen target still lacks (field names; empty = complete)."""
    t, m = conf["type"], []
    if not t:
        return ["type"]
    x = conf[t]
    need = {"s3": ("endpoint", "bucket"), "webdav": ("url", "user"), "sftp": ("host", "user")}[t]
    m += [k for k in need if not x.get(k)]
    m += [k for k in {"s3": ("s3_key", "s3_secret"), "webdav": ("dav_pass",), "sftp": ("sftp_key",)}[t] if not sec.get(k)]
    if t == "sftp" and not x.get("hostkey"):
        m.append("hostkey")
    return m


def bko_state(c):
    conf, sec = bko_conf(c), bko_secrets(c)
    s3, dav, sf = conf["s3"], conf["webdav"], conf["sftp"]
    return {"type": conf["type"], "on": conf["on"], "keep": conf["keep"],
            "encrypt_ready": gsetting(c, "bk_encrypt") == "1" and len(bk_passphrase(c)) >= 10,
            "s3": {"endpoint": s3.get("endpoint", ""), "region": s3.get("region", ""), "bucket": s3.get("bucket", ""),
                   "prefix": s3.get("prefix", ""), "path_style": s3.get("path_style", True) is not False,
                   "key_set": bool(sec.get("s3_key")), "secret_set": bool(sec.get("s3_secret"))},
            "webdav": {"url": dav.get("url", ""), "user": dav.get("user", ""), "password_set": bool(sec.get("dav_pass"))},
            "sftp": {"host": sf.get("host", ""), "port": sf.get("port", 22), "user": sf.get("user", ""), "path": sf.get("path", ""),
                     "public_key": sf.get("pubkey", ""), "fingerprint": bko_fingerprint(sf.get("hostkey", ""))},
            "missing": bko_missing(conf, sec) if conf["type"] else [],
            "last_ok": gsetting(c, "bko_last_ok"), "last_name": gsetting(c, "bko_last_name"),
            "last_size": int(gsetting(c, "bko_last_size") or 0), "last_error": gsetting(c, "bko_last_error"),
            "last_error_at": gsetting(c, "bko_last_error_at"),
            "running": _BKO["running"] or ("queued" if bgj_pending(c, "offsite") else "")}  # 2.193.0 D (#2220): also queued / in the worker


# ---- validation of the form
_URL_OK = re.compile(r"[^\s\x00-\x1f\x7f]{1,500}")
_TXT_OK = re.compile(r"[^\x00-\x1f\x7f]{0,200}")


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _url(v, tls=False):
    """A http(s) address; tls: only https (a password in Basic auth), plain http only to this machine."""
    if not isinstance(v, str) or not _URL_OK.fullmatch(v.strip()):
        return None
    u = urlsplit(v.strip())
    if u.scheme not in ("http", "https") or not u.hostname or "@" in u.netloc or u.query or u.fragment:
        return None
    try:
        u.port  # noqa: B018 -- raises on a bad port
    except ValueError:
        return None
    if tls and u.scheme != "https" and u.hostname not in _LOCAL_HOSTS:
        return None
    return v.strip().rstrip("/")


def _host_public(host):
    """2.223.2 C (#2871): hosted: no localhost, no address of a private network (a DNS name is checked when connecting)."""
    h = str(host or "").strip("[]").lower().rstrip(".")
    if h in ("localhost", "localhost.localdomain") or h.endswith(".localhost"):
        return False
    try:
        ipaddress.ip_address(h.split("%", 1)[0])
    except ValueError:
        return True
    return cal_ip_public(h)


def _hosted_refused(kind, v):
    """2.223.2 C (#2871): a valid address a hosted server may not use (only public https; SFTP: a public host)."""
    if not hosted() or not v or kind not in ("url", "url_tls", "host"):
        return False
    if kind == "host":
        return not _host_public(v)
    u = urlsplit(v)
    return u.scheme != "https" or not _host_public(u.hostname)


def _check(kind, v):
    """-> cleaned value or None (invalid)."""
    if kind == "url":
        return _url(v)
    if kind == "url_tls":
        return _url(v, tls=True)
    if not isinstance(v, str):
        return None
    v = v.strip()
    if kind == "region":
        return v if re.fullmatch(r"[a-z0-9-]{0,40}", v) else None
    if kind == "bucket":
        return v if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,61}[A-Za-z0-9]", v) else None
    if kind == "prefix":
        v = v.strip("/")
        return v if re.fullmatch(r"[\w .@+=,-]{1,100}(?:/[\w .@+=,-]{1,100}){0,9}", v) and ".." not in v.split("/") else (None if v else "")
    if kind == "host":
        return v if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,252}|\[[0-9A-Fa-f:.]{2,45}\]|[0-9A-Fa-f:]{2,45}", v) else None
    if kind == "user":
        return v if _TXT_OK.fullmatch(v) and v and not v.startswith("-") and len(v) <= 100 else None
    if kind == "sftp_user":
        return v if re.fullmatch(r"[A-Za-z0-9._][A-Za-z0-9._@-]{0,63}", v) else None
    if kind == "path":
        return v if re.fullmatch(r"[^\x00-\x1f\x7f\"\\*?\[\]{}]{0,300}", v) else None
    if kind == "secret":
        return v if 1 <= len(v) <= 500 and "\n" not in v else None
    return None


FIELDS = {"s3": {"endpoint": "url", "region": "region", "bucket": "bucket", "prefix": "prefix"},
          "webdav": {"url": "url_tls", "user": "user"},
          "sftp": {"host": "host", "user": "sftp_user", "path": "path"}}
SECRETS = {"s3": {"key": "s3_key", "secret": "s3_secret"}, "webdav": {"password": "dav_pass"}}


def _addr(t, x):
    """2.223.2 C (#2871): where a target's credentials go (S3: the endpoint, with virtual-host style also the bucket, which
    is then part of the host name; WebDAV: the address; SFTP: host + port -- the key pair is this server's own, it stays)."""
    if t == "s3":
        vh = x.get("path_style", True) is False
        return x.get("endpoint") or "", vh, (x.get("bucket") or "") if vh else ""
    if t == "webdav":
        return x.get("url") or ""
    return x.get("host") or "", x.get("port") or 22


def bko_keypair():
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    return priv, pub + " kalmido-backup"


# ---- transports: put(name, path, size) -> size on the target; names() -> [file names]; delete(name); probe()
def _http(scheme, netloc, method, target, headers, data=None):
    if hosted() and scheme != "https":  # 2.223.2 C (#2871): also a target saved before the server became hosted
        raise OffsiteError("blocked")
    cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    kw = {"context": ssl.create_default_context()} if scheme == "https" else {}
    conn = cls(netloc, timeout=BKO_TIMEOUT, **kw)
    if hosted():  # 2.223.2 C (#2871): every address the host resolves to is checked, the connection goes to a checked one
        conn._create_connection = _cal_connector(frozenset())
    try:
        conn.request(method, target, body=data, headers=headers)
        r = conn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read(8 * 1024 * 1024)
    except CalError as e:
        raise OffsiteError("blocked" if e.code == "blocked" else "conn", "network") from None
    except (OSError, http.client.HTTPException) as e:
        raise OffsiteError("conn", "network" if hosted() else type(e).__name__) from None  # 2.223.2 C (#2871): hosted: one kind
    finally:
        conn.close()


def _status_err(st, raw=b""):
    code = re.search(rb"<Code>([A-Za-z]{1,60})</Code>", raw or b"")
    what = f"{st}" + (f" {code.group(1).decode()}" if code else "")
    return OffsiteError("auth" if st in (401, 403) else "http", what)


def _hashes(path):
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)  # Content-MD5: the integrity check S3 asks for
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(b)
            md5.update(b)
    return sha.hexdigest(), base64.b64encode(md5.digest()).decode()


def s3_sign(method, cpath, qs, h, sha, kid, sk, region, amz):
    """AWS Signature Version 4 (service s3): the Authorization header over every header in h (lower-case names)."""
    signed = ";".join(sorted(h))
    canon = "\n".join([method, cpath, qs, "".join(f"{k}:{str(h[k]).strip()}\n" for k in sorted(h)), signed, sha])
    scope = f"{amz[:8]}/{region}/s3/aws4_request"
    sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canon.encode()).hexdigest()])
    k = ("AWS4" + sk).encode()
    for part in (amz[:8], region, "s3", "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={kid}/{scope}, SignedHeaders={signed}, Signature={sig}"


class S3:
    def __init__(self, conf, sec):
        self.x, self.kid, self.sk = conf, sec.get("s3_key", ""), sec.get("s3_secret", "")
        self.region = conf.get("region") or "us-east-1"
        self.pre = (conf.get("prefix") or "").strip("/")

    def key(self, name):
        return f"{self.pre}/{name}" if self.pre else name

    def call(self, method, key="", query=(), data=None, length=None, sha=EMPTY_SHA, extra=None):
        u = urlsplit(self.x["endpoint"])
        base = u.path.rstrip("/")
        if self.x.get("path_style", True) is not False:
            host, path = u.netloc, f"{base}/{self.x['bucket']}" + (f"/{key}" if key else "")
        else:
            host, path = f"{self.x['bucket']}.{u.netloc}", f"{base}/{key}"
        cpath = quote(path or "/", safe="/-_.~")
        qs = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query))
        amz = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        h = {"host": host, "x-amz-content-sha256": sha, "x-amz-date": amz, **(extra or {})}
        h["authorization"] = s3_sign(method, cpath, qs, h, sha, self.kid, self.sk, self.region, amz)
        if length is not None:
            h["content-length"] = str(length)
        return _http(u.scheme, host, method, cpath + ("?" + qs if qs else ""), h, data)

    def put(self, name, path, size):
        sha, md5 = _hashes(path)
        with open(path, "rb") as f:
            st, _, raw = self.call("PUT", self.key(name), data=f, length=size, sha=sha,
                                   extra={"content-md5": md5, "content-type": "application/octet-stream"})
        if st not in (200, 201):
            raise _status_err(st, raw)
        st, hd, raw = self.call("HEAD", self.key(name))
        if st != 200:
            raise _status_err(st, raw)
        return int(hd.get("content-length") or -1)

    def names(self):
        out, token = [], None
        for _ in range(50):
            q = [("delimiter", "/"), ("list-type", "2"), ("prefix", self.key(""))] + ([("continuation-token", token)] if token else [])
            st, _, raw = self.call("GET", "", query=q)
            if st != 200:
                raise _status_err(st, raw)
            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                raise OffsiteError("http", "ListObjectsV2") from None
            pre = self.key("")
            for el in root.iter():
                if el.tag.endswith("}Key") or el.tag == "Key":
                    k = el.text or ""
                    out.append(k[len(pre):] if k.startswith(pre) and "/" not in k[len(pre):] else "")  # keys in sub-folders are not ours
            trunc = next((el.text for el in root.iter() if el.tag.split("}")[-1] == "IsTruncated"), "false")
            token = next((el.text for el in root.iter() if el.tag.split("}")[-1] == "NextContinuationToken"), None)
            if trunc != "true" or not token:
                break
        return [n for n in out if n]

    def delete(self, name):
        st, _, raw = self.call("DELETE", self.key(name))
        if st not in (200, 204):
            raise _status_err(st, raw)


class WebDAV:
    PROP = b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/><d:resourcetype/></d:prop></d:propfind>'

    def __init__(self, conf, sec):
        self.u = urlsplit(conf["url"])
        self.base = self.u.path.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{conf.get('user', '')}:{sec.get('dav_pass', '')}".encode()).decode()

    def call(self, method, name="", data=None, length=None, extra=None):
        target = quote(f"{self.base}/{name}" if name else self.base + "/", safe="/-_.~")
        h = {"authorization": self.auth, **(extra or {})}
        if length is not None:
            h["content-length"] = str(length)
        return _http(self.u.scheme, self.u.netloc, method, target, h, data)

    def _props(self, name, depth):
        st, _, raw = self.call("PROPFIND", name, data=self.PROP, length=len(self.PROP),
                               extra={"depth": depth, "content-type": "application/xml"})
        if st != 207:
            raise _status_err(st)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            raise OffsiteError("http", "PROPFIND") from None
        out = {}
        for r in root.iter("{DAV:}response"):
            href = r.findtext("{DAV:}href") or ""
            n = unquote(urlsplit(href).path.rstrip("/").rsplit("/", 1)[-1])
            ln = r.findtext(".//{DAV:}getcontentlength")
            if r.find(".//{DAV:}resourcetype/{DAV:}collection") is not None:
                ln = "dir"  # a folder: never one of the backups (a DELETE would remove it with its content)
            out[n] = int(ln) if ln and ln.strip().isdigit() else (None if ln == "dir" else -1)
        return out

    def put(self, name, path, size):
        with open(path, "rb") as f:
            st, _, _ = self.call("PUT", name, data=f, length=size, extra={"content-type": "application/octet-stream"})
        if st not in (200, 201, 204):
            raise _status_err(st)
        got = self._props(name, "0").get(name)
        return got if isinstance(got, int) else -1

    def names(self):
        return [n for n, ln in self._props("", "1").items() if n and ln is not None]

    def delete(self, name):
        st, _, _ = self.call("DELETE", name)
        if st not in (200, 204, 404):
            raise _status_err(st)


class SFTP:
    def __init__(self, conf, sec, c=None):
        self.x, self.key, self.c = conf, sec.get("sftp_key", ""), c
        self.dir = (conf.get("path") or "").rstrip("/")

    def rp(self, name):
        return f"{self.dir}/{name}" if self.dir else name

    def pin(self):
        """2.223.2 C (#2871): hosted: ssh options for a checked public address of the host (sftp connects exactly there; the
        host key stays filed under the name, as known_hosts writes it)."""
        h, port = str(self.x["host"]).strip("[]"), int(self.x.get("port") or 22)
        try:
            infos = socket.getaddrinfo(h, port, 0, socket.SOCK_STREAM)
        except (socket.gaierror, UnicodeError):
            raise OffsiteError("conn", "network") from None
        ip = next((sa[0] for *_, sa in infos if cal_ip_public(sa[0])), None)
        if not ip:
            raise OffsiteError("blocked")
        return ["-o", f"HostName={ip}", "-o", "HostKeyAlias=" + (h if port == 22 else f"[{h}]:{port}")]

    def command(self, keyfile, khfile, accept_new=False, pin=()):
        """The sftp command line (no shell; batch commands on stdin)."""
        return ["sftp", "-b", "-", "-F", "/dev/null", "-i", keyfile, "-P", str(int(self.x.get("port") or 22)),
                "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", f"UserKnownHostsFile={khfile}",
                "-o", "GlobalKnownHostsFile=/dev/null", "-o", "HashKnownHosts=no", "-o", "LogLevel=ERROR",
                "-o", "StrictHostKeyChecking=" + ("accept-new" if accept_new else "yes"),
                "-o", f"ConnectTimeout={min(BKO_TIMEOUT, 60)}", "-o", "ServerAliveInterval=15", *pin,
                "--", f"{self.x['user']}@{self.x['host']}"]

    def run(self, lines, accept_new=False):
        """-> (stdout, the known_hosts text after the run). OffsiteError on failure."""
        pin = self.pin() if hosted() else ()  # 2.223.2 C (#2871)
        if not shutil.which("sftp"):
            raise OffsiteError("tool")
        tmp = tempfile.mkdtemp(prefix="kalmido-sftp-")
        try:
            kf, kh = os.path.join(tmp, "id"), os.path.join(tmp, "known_hosts")
            fd = os.open(kf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(self.key if self.key.endswith("\n") else self.key + "\n")
            with open(kh, "w") as f:
                f.write((self.x.get("hostkey") or "") + "\n")
            try:
                r = subprocess.run(self.command(kf, kh, accept_new, pin), input="\n".join(lines) + "\n", capture_output=True, text=True,
                                   timeout=BKO_TIMEOUT * 30, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp})
            except subprocess.TimeoutExpired:
                raise OffsiteError("conn", "network" if hosted() else "timeout") from None
            with open(kh) as f:
                known = f.read().strip()
            if r.returncode != 0:
                raise sftp_error(r.stderr.replace(tmp, "…"), known)
            return r.stdout, known
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _size(out, name):
        for ln in out.splitlines():
            p = ln.split()
            if len(p) >= 9 and not ln.startswith("sftp>") and p[-1].endswith(name) and p[4].isdigit():
                return int(p[4])
        return -1

    def put(self, name, path, size):
        """Upload as .part, then rename over the old file (OpenSSH servers replace it in one step). A server that refuses
        to rename onto an existing file: the old file goes only once the complete .part is confirmed there."""
        rp = self.rp(name)
        try:
            out, _ = self.run([f'-rm "{rp}.part"', f'put "{path}" "{rp}.part"', f'rename "{rp}.part" "{rp}"', f'ls -l "{rp}"'])
        except OffsiteError as e:
            if e.code != "sftp":
                raise
            out, _ = self.run([f'ls -l "{rp}.part"'])
            if self._size(out, name + ".part") != size:
                raise
            out, _ = self.run([f'-rm "{rp}"', f'rename "{rp}.part" "{rp}"', f'ls -l "{rp}"'])
        return self._size(out, name)

    def names(self):
        out, _ = self.run([f'ls -1 "{self.dir or "."}"'])
        return [ln.strip().rsplit("/", 1)[-1] for ln in out.splitlines() if ln.strip() and not ln.startswith("sftp>")]

    def delete(self, name):
        self.run([f'rm "{self.rp(name)}"'])


def sftp_error(stderr, known=""):
    """A failed sftp run -> OffsiteError with a short reason (never the key; the temp folder is cut out)."""
    e = OffsiteError("sftp", "")
    low = stderr.lower()
    if "host key verification failed" in low or "remote host identification has changed" in low:
        e = OffsiteError("hostkey")
    elif "permission denied" in low:
        e = OffsiteError("auth", "publickey")
    elif any(x in low for x in ("connection refused", "timed out", "could not resolve", "no route to host", "network is unreachable")):
        e = OffsiteError("conn", next(x for x in ("connection refused", "timed out", "could not resolve", "no route to host",
                                                    "network is unreachable") if x in low))
        if hosted():  # 2.223.2 C (#2871): no telling a closed port from a silent one (no port scan of the hoster's network)
            e = OffsiteError("conn", "network")
    else:
        last = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
        e = OffsiteError("sftp", (last[-1] if last else "exit")[:160])
    e.known = known
    return e


def bko_target(c, conf=None, sec=None):
    conf, sec = conf or bko_conf(c), sec if sec is not None else bko_secrets(c)
    if [m for m in bko_missing(conf, sec) if m != "hostkey"]:  # SFTP without a host key: a test records it, an upload refuses
        raise OffsiteError("incomplete")
    x = conf[conf["type"]]
    return {"s3": S3, "webdav": WebDAV, "sftp": SFTP}[conf["type"]](x, sec)


def bko_prune(tgt, keep):
    """The newest `keep` backups on the target stay; older ones of this app's name pattern go. -> deleted names."""
    try:
        names = tgt.names()
    except OffsiteError:
        return []  # the upload itself went through; the clean-up is tried again after the next one
    mine = sorted((n for n in names if BK_NAME_RE.fullmatch(n) and n.endswith(".enc") and "-safety." not in n), reverse=True)
    gone = []
    for n in mine[keep:]:
        try:
            tgt.delete(n)
            gone.append(n)
        except OffsiteError:
            pass  # tried again after the next upload
    return gone


@bgj_fn("offsite")  # 2.193.0 D (#2220): "Upload now" through the queue (the worker runs it)
def bko_upload(force=False):
    """Uploads the newest backup when it is not on the target yet (own connection; any thread). Never raises.
    -> the uploaded name or None."""
    if not _BKO_LOCK.acquire(blocking=False):
        return None
    c = None
    try:
        c = connect()
        conf = bko_conf(c)
        if not conf["on"] or not conf["type"]:
            return None
        items = [x for x in bk_list() if x["kind"] != "safety"]
        if not items:
            return None
        x = items[0]
        if not force and x["name"] == gsetting(c, "bko_last_name"):
            return None
        if _BKO["for"] != x["name"]:
            _BKO.update({"for": x["name"], "tries": 0, "next": 0.0})
        if not force and (_BKO["tries"] >= BKO_TRIES or time.time() < _BKO["next"]):
            return None
        _BKO["running"] = x["name"]
        try:
            if not x["encrypted"] or len(bk_passphrase(c)) < 10:
                raise OffsiteError("not_encrypted")
            tgt = bko_target(c, conf)
            c.rollback()  # no open transaction while the (long) upload runs: a restore must not wait for it
            got = tgt.put(x["name"], os.path.join(BK_DIR, x["name"]), x["size"])
            if got != x["size"]:
                raise OffsiteError("size", got, x["size"])
            bko_prune(tgt, conf["keep"])
        except OffsiteError as e:
            _BKO["tries"] += 1
            _BKO["next"] = time.time() + BKO_PAUSE * 2 ** (_BKO["tries"] - 1)
            c.rollback()
            gset(c, "bko_last_error", e.text("en"))
            gset(c, "bko_last_error_at", iso(now_utc()))
            c.commit()
            print("off-site upload FAILED:", e.text("en"), flush=True)
            if _BKO["tries"] >= BKO_TRIES or force:
                aa_now("storage", f"offsite:{e.code}", N_("Off-site backup failed: {0}"), [e.text("en")])
            return None
        for k, v in (("bko_last_ok", iso(now_utc())), ("bko_last_name", x["name"]), ("bko_last_size", str(x["size"])),
                     ("bko_last_error", ""), ("bko_last_error_at", "")):
            gset(c, k, v)
        c.commit()
        _BKO.update({"for": "", "tries": 0, "next": 0.0})
        print("off-site upload done:", x["name"], flush=True)
        return x["name"]
    except Exception as e:  # noqa: BLE001 -- no database / disk: tried again on the next tick
        print("off-site upload error:", type(e).__name__, flush=True)
        return None
    finally:
        _BKO["running"] = ""
        if c is not None:
            c.close()
        _BKO_LOCK.release()


def bko_tick(c):
    """backup_tick (the backup thread): the upload of a new backup, or the next try of a failed one. The upload runs in
    its own thread, so a slow target never holds the backup thread (nor its gate: restore / maintenance wait for that)."""
    if not gsetting(c, "bko_conf") or not bko_conf(c)["on"] or _BKO_LOCK.locked():
        return
    items = [x for x in bk_list() if x["kind"] != "safety"]
    if not items or items[0]["name"] == gsetting(c, "bko_last_name"):
        return
    if _BKO["for"] == items[0]["name"] and (_BKO["tries"] >= BKO_TRIES or time.time() < _BKO["next"]):
        return
    threading.Thread(target=bko_upload, daemon=True, name="kalmido-offsite").start()


# ---- 2.223.2 C (#2871): the step-up (also for the export downloads of retexport.py / orgexport.py)
def stepup_need(c, b):
    """2.223.2 C (#2871): the step-up of orgcrypt.rck_stepup before the off-site target is changed / tested / used and before an
    export download; an error response or None. A login-provider account: its step-up sign-in there for the own office
    (oidc.py knows no other purpose yet); signed in by the login proxy without a password: refused. A confirmed step-up
    holds for this session RCK_FRESH_MIN minutes (sessions.stepup_for "su", never a recovery key's purpose), so filling in
    the target field by field asks once."""
    u = c.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    step = rck_step(c, u)
    if step == "proxy":
        return jsonify(error=tr("You are signed in through the server’s login proxy. This step needs a sign-in with a password."),
                       need="proxy"), 403
    tok = request.cookies.get(COOKIE) if g.auth_via == "session" else None
    if tok and step != "fresh":
        r = c.execute("SELECT stepup_at, stepup_for FROM sessions WHERE token_hash=?", (_token_hash(tok),)).fetchone()
        if r and r[1] == "su" and str(r[0] or "") >= iso(now_utc() - timedelta(minutes=RCK_FRESH_MIN)):
            return None
    if step != "fresh" and not (isinstance(b.get("password"), str) and b["password"]):  # the client asks, then sends it again
        return jsonify(error=tr("Confirm with your password"), need=step), 403
    # 2.223.2 (#2871, review): a login-provider account confirms with its own purpose "0:su" (oidc.py ?stepup=su), also
    # without a personal office, and never with a recovery key's step-up
    e = rck_stepup(c, u, b, "0:su")
    if e is None:
        if tok and step != "fresh":
            c.execute("UPDATE sessions SET stepup_at=?, stepup_for='su' WHERE token_hash=? AND user_id=?",
                      (iso(now_utc()), _token_hash(tok), u["id"]))
        c.commit()  # also the used code's step (totp_step), whatever the route does next
    return e


def stepup_download(c):
    """2.223.2 C (#2871): a download behind the step-up (the caller checked the right first): POST with the step-up ->
    {ticket}; GET ?t=<ticket> (once, PEND_TTL, this person + this address) -> None = send the file; else the response."""
    if request.method == "POST":
        e = stepup_need(c, body())
        if e is not None:
            return e
        tok = secrets.token_urlsafe(32)
        pend_set("sudl:" + hashlib.sha256(tok.encode()).hexdigest(), uid=g.user["id"], path=request.path)
        return jsonify(ticket=tok)
    p = pend_take("sudl:" + hashlib.sha256((request.args.get("t") or "").encode()).hexdigest())
    if p and p.get("uid") == g.user["id"] and p.get("path") == request.path:
        return None
    u = c.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    return jsonify(error=tr("Confirm the download again."), need=rck_step(c, u)), 403


@app.post("/api/stepup/passkey")
def stepup_passkey():
    """2.223.2 C (#2871): the passkey challenge of stepup_need (the same one rck_stepup takes)."""
    if g.user is None:
        raise Denied(401)
    c = db()
    if not c.execute("SELECT 1 FROM webauthn_creds WHERE user_id=?", (g.user["id"],)).fetchone():
        return err(tr("No passkey is set up"), 409)
    chal, rp, opts = wa_auth_options(c, g.user["id"], uv=True)
    pend_set(f"rck:{g.user['id']}", chal=chal, rp=rp)
    return jsonify(opts)


# ---- routes (instance admins; the backups switch KALMIDO_BACKUPS as for the backups themselves)
@app.get("/api/admin/backups/offsite")
def offsite_get():
    need_backups()
    return jsonify(bko_state(db()))


@app.patch("/api/admin/backups/offsite")
def offsite_set():
    """{type?, on?, keep?, s3?: {endpoint, region, bucket, prefix, path_style, key, secret}, webdav?: {url, user, password},
    sftp?: {host, port, user, path, new_key, forget_host}} -- credentials: a non-empty value replaces the saved one, an empty
    or missing one keeps it (2.223.2 C, #2871: unless the address changes: then they go, see _addr). The target (type, s3,
    webdav, sftp) needs the step-up (password / code / credential in the body); on, keep and remove do not (they send
    nothing anywhere new: the upload goes only to a target set up and tested with the step-up)."""
    need_backups()
    c, b = db(), body()
    if any(k in b for k in ("type", *BKO_TYPES)):  # 2.223.2 C (#2871)
        e = stepup_need(c, b)
        if e is not None:
            return e
    conf, sec = bko_conf(c), bko_secrets(c)
    if b.get("remove") is True:  # "Remove target": the addresses, the sealed credentials and the SFTP key pair go
        _save(c, {}, {})
        c.commit()
        _BKO.update({"for": "", "tries": 0, "next": 0.0})
        return jsonify(bko_state(c))
    if "type" in b:
        if b["type"] not in ("", *BKO_TYPES):
            return err(tr("Invalid value: {0}", "type"))
        conf["type"] = b["type"]
    if "keep" in b:
        if isinstance(b["keep"], bool) or not isinstance(b["keep"], int) or not 1 <= b["keep"] <= 365:
            return err(tr("Invalid value: {0}", "keep"))
        conf["keep"] = b["keep"]
    for t in BKO_TYPES:
        x = b.get(t)
        if x is None:
            continue
        if not isinstance(x, dict):
            return err(tr("Invalid value: {0}", t))
        cur = conf[t]
        old_addr = (cur.get("host"), cur.get("port"))
        was = _addr(t, cur)  # 2.223.2 C (#2871)
        for k, kind in FIELDS[t].items():
            if k in x:
                v = "" if x[k] in ("", None) else _check(kind, x[k])
                if v is None:
                    return err(tr("Invalid value: {0}", f"{t}.{k}"))
                if _hosted_refused(kind, v):  # 2.223.2 C (#2871)
                    return err(BKO_ERR_TEXT("blocked"))
                cur[k] = v
        if t == "s3" and "path_style" in x:
            if not isinstance(x["path_style"], bool):
                return err(tr("Invalid value: {0}", "s3.path_style"))
            cur["path_style"] = x["path_style"]
        for k, sk in SECRETS.get(t, {}).items():
            if x.get(k) not in (None, ""):
                v = _check("secret", x[k])
                if v is None:
                    return err(tr("Invalid value: {0}", f"{t}.{k}"))
                sec[sk] = v
        if _addr(t, cur) != was:  # 2.223.2 C (#2871): another host: the saved credentials do not follow it
            for k, sk in SECRETS.get(t, {}).items():
                if x.get(k) in (None, ""):
                    sec.pop(sk, None)
        if t == "sftp":
            if "port" in x:
                if isinstance(x["port"], bool) or not isinstance(x["port"], int) or not 1 <= x["port"] <= 65535:
                    return err(tr("Invalid value: {0}", "sftp.port"))
                cur["port"] = x["port"]
            if x.get("new_key") is True or not sec.get("sftp_key"):
                sec["sftp_key"], cur["pubkey"] = bko_keypair()
            if x.get("forget_host") is True or (cur.get("host"), cur.get("port")) != old_addr:
                cur.pop("hostkey", None)  # another server (or the admin said so): the next test records its key
    if conf["type"] == "sftp" and not sec.get("sftp_key"):
        sec["sftp_key"], conf["sftp"]["pubkey"] = bko_keypair()
    if "on" in b and not isinstance(b["on"], bool):
        return err(tr("Invalid value: {0}", "on"))
    if "on" in b:
        conf["on"] = b["on"]
    elif conf["on"] and (not conf["type"] or bko_missing(conf, sec)):
        conf["on"] = False  # the target changed into an incomplete one (another server, a forgotten host key): off until tested
    if b.get("on"):
        if gsetting(c, "bk_encrypt") != "1" or len(bk_passphrase(c)) < 10:
            c.rollback()
            return err(BKO_ERR_TEXT("not_encrypted"))
        if not conf["type"] or bko_missing(conf, sec):
            c.rollback()
            return err(tr("Fill in the target completely and test the connection first ({0}).", ", ".join(bko_missing(conf, sec))))
    _save(c, conf, sec)
    c.commit()
    return jsonify(bko_state(c))


def BKO_ERR_TEXT(code, *a):
    return tr(BKO_ERR[code], *a)


@app.post("/api/admin/backups/offsite/test")
def offsite_test():
    """Writes a small file to the target and deletes it again. SFTP: the first test records the server's host key (its
    fingerprint is in the answer); later tests require that key. -> {ok, error?, fingerprint?}"""
    need_backups()
    c = db()
    e = stepup_need(c, body())  # 2.223.2 C (#2871)
    if e is not None:
        return e
    conf, sec = bko_conf(c), bko_secrets(c)
    if not conf["type"]:
        return err(BKO_ERR_TEXT("incomplete"))
    name = f"kalmido-probe-{secrets.token_hex(6)}.txt"
    fd, tmp = tempfile.mkstemp(prefix=".probe-")
    os.write(fd, b"Kalmido backup target test\n")
    os.close(fd)
    out = {"ok": False}
    try:
        tgt = bko_target(c, conf, sec)
        if conf["type"] == "sftp":
            new = not conf["sftp"].get("hostkey")
            try:
                _, known = tgt.run([f'put "{tmp}" "{tgt.rp(name)}"', f'rm "{tgt.rp(name)}"'], accept_new=new)
            except OffsiteError as e:
                known = getattr(e, "known", "")
                if new and known.strip():  # the key was seen before the sign-in failed: keep it, show it
                    conf["sftp"]["hostkey"] = known.strip().splitlines()[0]
                    _save(c, conf)
                    c.commit()
                raise
            if new and known.strip():
                conf["sftp"]["hostkey"] = known.strip().splitlines()[0]
                _save(c, conf)
                c.commit()
            out["fingerprint"] = bko_fingerprint(conf["sftp"].get("hostkey", ""))
        else:
            got = tgt.put(name, tmp, os.path.getsize(tmp))
            tgt.delete(name)
            if got != os.path.getsize(tmp):
                raise OffsiteError("size", got, os.path.getsize(tmp))
        out["ok"] = True
    except OffsiteError as e:
        out.update(error=e.text(), code=e.code)
        if conf["type"] == "sftp":
            out["fingerprint"] = bko_fingerprint(conf["sftp"].get("hostkey", ""))
    finally:
        os.remove(tmp)
    return jsonify(**out, **{"state": bko_state(c)})


@app.post("/api/admin/backups/offsite/upload")
def offsite_upload_now():
    """Uploads the newest backup now (in the background; GET shows the result)."""
    need_backups()
    c = db()
    e = stepup_need(c, body())  # 2.223.2 C (#2871)
    if e is not None:
        return e
    if not bko_conf(c)["on"]:
        return err(BKO_ERR_TEXT("incomplete"))
    if _BKO_LOCK.locked() or bgj_pending(c, "offsite"):  # an upload runs already: nothing new starts
        return jsonify(error=tr("An upload is running already."), **bko_state(c)), 409
    bgj_add("offsite", True, once=True)  # 2.193.0 D (#2220): the queue in the database (the worker runs it)
    time.sleep(0.05)
    return jsonify(ok=True, **bko_state(c)), 202
