#!/usr/bin/env python3
"""2.143.0 B (#2152): tiny stand-ins for an S3-compatible store and a WebDAV server for p2143_b_api_test.py (they run INSIDE
the test container: docker exec -d python /data/fake_offsite.py <mode> <port> <user/key id> <password/secret>).

Files go to /data/fake-remote/<mode>/<path>. Every request is logged to /data/fake-remote/<mode>.log (one JSON line: method,
path, status, sig = the Signature V4 was checked and matched). S3 checks the signature with its own implementation (path
style), the signed body hash and Content-MD5; WebDAV checks Basic auth. /data/fake-remote/<mode>.fail holding a number N:
the next N uploads answer 500 (the number counts down)."""
import base64
import hashlib
import hmac
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, quote, unquote, urlsplit
from xml.sax.saxutils import escape

MODE, PORT, USER, SECRET = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
ROOT = os.path.join("/data/fake-remote", MODE)
os.makedirs(ROOT, exist_ok=True)


def log(**kw):
    with open(ROOT + ".log", "a") as f:
        f.write(json.dumps(kw) + "\n")


def fail_once():
    p = ROOT + ".fail"
    try:
        n = int(open(p).read().strip() or 0)
    except (OSError, ValueError):
        return False
    if n <= 0:
        return False
    with open(p, "w") as f:
        f.write(str(n - 1))
    return True


def s3_check(h, method, path, query, payload_sha):
    """Our own Signature V4 check (independent of the app's code)."""
    m = re.fullmatch(r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/s3/aws4_request, SignedHeaders=([a-z0-9;-]+), "
                     r"Signature=([0-9a-f]{64})", h.get("Authorization", ""))
    if not m or m.group(1) != USER:
        return False
    kid, day, region, signed, sig = m.groups()
    names = signed.split(";")
    if not {"host", "x-amz-date", "x-amz-content-sha256"} <= set(names):
        return False
    canon_h = "".join(f"{n}:{(h.get(n) or '').strip()}\n" for n in names)
    qs = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query))
    canon = "\n".join([method, quote(path, safe="/-_.~"), qs, canon_h, signed, payload_sha])
    amz = h.get("x-amz-date", "")
    sts = "\n".join(["AWS4-HMAC-SHA256", amz, f"{day}/{region}/s3/aws4_request", hashlib.sha256(canon.encode()).hexdigest()])
    k = ("AWS4" + SECRET).encode()
    for part in (day, region, "s3", "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    return hmac.compare_digest(hmac.new(k, sts.encode(), hashlib.sha256).hexdigest(), sig)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, st, body=b"", ctype="application/xml", extra=None):
        self.send_response(st)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        log(method=self.command, path=self.path, status=st, sig=getattr(self, "sig", None))

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def local(self, path):
        p = os.path.normpath(os.path.join(ROOT, unquote(path).lstrip("/")))
        assert p.startswith(ROOT)
        return p

    def handle_any(self):
        u = urlsplit(self.path)
        data = self.body() if self.command in ("PUT", "PROPFIND") else b""
        if MODE == "s3":
            sha = self.headers.get("x-amz-content-sha256", "")
            self.sig = s3_check(self.headers, self.command, unquote(u.path), parse_qsl(u.query, keep_blank_values=True), sha)
            if not self.sig:
                return self.reply(403, b"<Error><Code>SignatureDoesNotMatch</Code></Error>")
            if self.command == "PUT":
                if hashlib.sha256(data).hexdigest() != sha:
                    return self.reply(400, b"<Error><Code>XAmzContentSHA256Mismatch</Code></Error>")
                if base64.b64encode(hashlib.md5(data).digest()).decode() != self.headers.get("Content-MD5"):  # noqa: S324
                    return self.reply(400, b"<Error><Code>BadDigest</Code></Error>")
                if fail_once():
                    return self.reply(500, b"<Error><Code>InternalError</Code></Error>")
                p = self.local(u.path)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(data)
                return self.reply(200, extra={"ETag": '"' + hashlib.md5(data).hexdigest() + '"'})  # noqa: S324
            if self.command == "HEAD":
                p = self.local(u.path)
                if not os.path.isfile(p):
                    return self.reply(404)
                self.send_response(200)
                self.send_header("Content-Length", str(os.path.getsize(p)))
                self.end_headers()
                return log(method="HEAD", path=self.path, status=200, sig=True)
            if self.command == "DELETE":
                p = self.local(u.path)
                if os.path.isfile(p):
                    os.remove(p)
                return self.reply(204)
            if self.command == "GET":
                q = dict(parse_qsl(u.query))
                bucket = self.local(u.path)
                pre = q.get("prefix", "")
                keys = []
                for r, _, fs in os.walk(bucket):
                    for fn in fs:
                        k = os.path.relpath(os.path.join(r, fn), bucket).replace(os.sep, "/")
                        if k.startswith(pre):
                            keys.append(k)
                xml = ('<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                       + "".join(f"<Contents><Key>{escape(k)}</Key></Contents>" for k in sorted(keys))
                       + "<IsTruncated>false</IsTruncated></ListBucketResult>")
                return self.reply(200, xml.encode())
            return self.reply(405)
        # WebDAV
        want = "Basic " + base64.b64encode(f"{USER}:{SECRET}".encode()).decode()
        self.sig = self.headers.get("Authorization") == want
        if not self.sig:
            return self.reply(401, extra={"WWW-Authenticate": 'Basic realm="fake"'})
        p = self.local(u.path)
        if self.command == "PUT":
            if fail_once():
                return self.reply(500)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
            return self.reply(201)
        if self.command == "DELETE":
            if not os.path.exists(p):
                return self.reply(404)
            os.remove(p)
            return self.reply(204)
        if self.command == "PROPFIND":
            if not os.path.exists(p):
                return self.reply(404)
            items = [(u.path, p)]
            if os.path.isdir(p) and self.headers.get("Depth") == "1":
                items += [(u.path.rstrip("/") + "/" + quote(n), os.path.join(p, n)) for n in sorted(os.listdir(p))]
            rs = "".join(f"<d:response><d:href>{escape(h)}</d:href><d:propstat><d:prop>"
                         + (f"<d:getcontentlength>{os.path.getsize(f)}</d:getcontentlength>" if os.path.isfile(f) else "")
                         + "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" for h, f in items)
            return self.reply(207, f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">{rs}</d:multistatus>'.encode())
        return self.reply(405)

    do_GET = do_PUT = do_HEAD = do_DELETE = do_PROPFIND = handle_any


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
