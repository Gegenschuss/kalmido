# 2.19.0 (#653): a tiny CardDAV server for p2190_family_api_test.py; runs INSIDE the test container
# (docker exec -d python /data/fake_carddav.py), port 8096, Basic auth u / pw. Discovery: / -> current-user-principal
# /principals/u/ -> addressbook-home-set /books/u/ -> the address book /books/u/family/; REPORT answers the vCards of
# /data/cards.vcf (one file, several cards). Logs every request to /data/carddav.log (method, path, auth ok).
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open('/data/carddav.log', 'a', buffering=1)
AUTH = 'Basic ' + base64.b64encode(b'u:pw').decode()
MS = ('<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">{}</d:multistatus>')


def resp(href, props):
    return f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>{props}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, body=b'', ctype='application/xml; charset=utf-8'):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _auth(self):
        ok = self.headers.get('Authorization') == AUTH
        LOG.write(json.dumps({'method': self.command, 'path': self.path, 'auth': ok}) + '\n')
        if not ok:
            self._send(401, 'no')
        return ok

    def do_PROPFIND(self):
        n = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(n)
        if not self._auth():
            return
        p, depth = self.path, self.headers.get('Depth', '0')
        if p in ('/', '/.well-known/carddav'):
            return self._send(207, MS.format(resp(p, '<d:resourcetype><d:collection/></d:resourcetype>'
                                                   '<d:current-user-principal><d:href>/principals/u/</d:href></d:current-user-principal>')))
        if p == '/principals/u/':
            return self._send(207, MS.format(resp(p, '<card:addressbook-home-set><d:href>/books/u/</d:href></card:addressbook-home-set>')))
        if p == '/books/u/':
            out = resp(p, '<d:resourcetype><d:collection/></d:resourcetype>')
            if depth == '1':
                out += resp('/books/u/family/', '<d:resourcetype><d:collection/><card:addressbook/></d:resourcetype>')
            return self._send(207, MS.format(out))
        if p == '/books/u/family/':
            return self._send(207, MS.format(resp(p, '<d:resourcetype><d:collection/><card:addressbook/></d:resourcetype>')))
        self._send(404, 'not found')

    def do_REPORT(self):
        n = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(n)
        if not self._auth():
            return
        if self.path != '/books/u/family/':
            return self._send(404, 'not found')
        try:
            raw = open('/data/cards.vcf', encoding='utf-8').read()
        except OSError:
            raw = ''
        cards = ['BEGIN:VCARD' + c for c in raw.split('BEGIN:VCARD')[1:]]
        esc = lambda s: s.replace('&', '&amp;').replace('<', '&lt;')  # noqa: E731
        self._send(207, MS.format(''.join(resp(f'/books/u/family/{i}.vcf', f'<d:getetag>"{i}"</d:getetag><card:address-data>{esc(c)}</card:address-data>')
                                          for i, c in enumerate(cards))))


ThreadingHTTPServer(('127.0.0.1', 8096), H).serve_forever()
