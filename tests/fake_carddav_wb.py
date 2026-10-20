# 2.140.0 D (#2137): a tiny CardDAV server that can be written to, for p2140_d_api_test.py / p2140_d_ui.js; runs INSIDE the
# test container (docker exec -d python /data/fake_carddav_wb.py), port 8097, Basic auth with the password "wb-secret-2140".
# Accounts (each sees one address book, discovery like fake_carddav.py: / -> principal -> home -> book):
#   u: /books/u/family/  writable (privilege set: read, write-content)
#   m: /books/m/mirror/  read only (privilege set: read; a PUT answers 403), like a mirrored book of Kalmido's own server
#   x: /books/x/locked/  tells no privileges, but a PUT answers 403
# The cards are files /data/wb/<account>/<name>.vcf (bytes as they are); ETag = "sha1 of the bytes" (strong). GET answers
# the bytes, PUT needs If-Match with the current ETag (else 412). /data/wb/force412 = the next PUT answers 412 (the file
# is removed then). Every request goes to /data/wb.log (method, path, If-Match, never the password).
import base64
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = '/data/wb'
LOG = open('/data/wb.log', 'a', buffering=1)
PW = 'wb-secret-2140'
BOOKS = {'u': 'family', 'm': 'mirror', 'x': 'locked'}
MS = ('<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">{}</d:multistatus>')


def resp(href, props):
    return f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>{props}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'


def etag(b):
    return '"' + hashlib.sha1(b).hexdigest() + '"'


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, body=b'', ctype='application/xml; charset=utf-8', hdrs=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        for k, v in (hdrs or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _user(self):
        a = self.headers.get('Authorization') or ''
        user = None
        try:
            u, _, p = base64.b64decode(a[6:]).decode().partition(':')
            user = u if a.startswith('Basic ') and p == PW and u in BOOKS else None
        except ValueError:
            pass
        LOG.write(json.dumps({'method': self.command, 'path': self.path, 'user': user, 'if_match': self.headers.get('If-Match')}) + '\n')
        if not user:
            self._send(401, 'no')
        return user

    def _body(self):
        return self.rfile.read(int(self.headers.get('Content-Length') or 0))

    def _book(self, u):
        return f'/books/{u}/{BOOKS[u]}/'

    def _cards(self, u):
        d = os.path.join(ROOT, u)
        return sorted(f for f in (os.listdir(d) if os.path.isdir(d) else []) if f.endswith('.vcf'))

    def do_PROPFIND(self):
        body = self._body()
        u = self._user()
        if not u:
            return
        p, book = self.path, self._book(u)
        if p in ('/', '/.well-known/carddav'):
            return self._send(207, MS.format(resp(p, '<d:resourcetype><d:collection/></d:resourcetype>'
                                                   f'<d:current-user-principal><d:href>/principals/{u}/</d:href></d:current-user-principal>')))
        if p == f'/principals/{u}/':
            return self._send(207, MS.format(resp(p, f'<card:addressbook-home-set><d:href>/books/{u}/</d:href></card:addressbook-home-set>')))
        if p == f'/books/{u}/':
            out = resp(p, '<d:resourcetype><d:collection/></d:resourcetype>')
            if self.headers.get('Depth') == '1':
                out += resp(book, '<d:resourcetype><d:collection/><card:addressbook/></d:resourcetype>')
            return self._send(207, MS.format(out))
        if p == book:
            props = '<d:resourcetype><d:collection/><card:addressbook/></d:resourcetype>'
            if b'current-user-privilege-set' in body and u != 'x':
                pv = ['read'] + (['write-content'] if u == 'u' else [])
                props = '<d:current-user-privilege-set>' + ''.join(f'<d:privilege><d:{x}/></d:privilege>' for x in pv) + '</d:current-user-privilege-set>'
            return self._send(207, MS.format(resp(p, props)))
        self._send(404, 'not found')

    def do_REPORT(self):
        self._body()
        u = self._user()
        if not u:
            return
        if self.path != self._book(u):
            return self._send(404, 'not found')
        esc = lambda s: s.replace('&', '&amp;').replace('<', '&lt;').replace('\r', '&#13;')  # noqa: E731
        out = ''
        for f in self._cards(u):
            b = open(os.path.join(ROOT, u, f), 'rb').read()
            out += resp(self.path + f, f'<d:getetag>{etag(b)}</d:getetag><card:address-data>{esc(b.decode())}</card:address-data>')
        self._send(207, MS.format(out))

    def _file(self, u):
        book = self._book(u)
        if not self.path.startswith(book) or '/' in self.path[len(book):]:
            return None
        f = os.path.join(ROOT, u, self.path[len(book):])
        return f if os.path.isfile(f) else None

    def do_GET(self):
        u = self._user()
        if not u:
            return
        f = self._file(u)
        if not f:
            return self._send(404, 'not found')
        b = open(f, 'rb').read()
        self._send(200, b, 'text/vcard; charset=utf-8', {'ETag': etag(b)})

    def do_PUT(self):
        body = self._body()
        u = self._user()
        if not u:
            return
        if u in ('m', 'x'):
            return self._send(403, 'read only')
        f = self._file(u)
        if not f:
            return self._send(404, 'not found')
        force = os.path.join(ROOT, 'force412')
        if os.path.exists(force):
            os.remove(force)
            return self._send(412, 'precondition failed')
        if self.headers.get('If-Match') != etag(open(f, 'rb').read()):
            return self._send(412, 'precondition failed')
        open(f, 'wb').write(body)
        self._send(204, b'', hdrs={'ETag': etag(body)})


ThreadingHTTPServer(('127.0.0.1', 8097), H).serve_forever()
