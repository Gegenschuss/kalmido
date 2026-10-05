# 2.22.0 (#663): a tiny Karakeep API for p2220_api_test.py; runs INSIDE the test container (docker exec -d python
# /data/fake_karakeep.py), port 8097, API key "kk-secret" (Bearer). GET /api/v1/bookmarks?archived=false&limit&cursor (two
# pages), GET /api/v1/lists, GET /api/v1/lists/<id>/bookmarks, PATCH /api/v1/bookmarks/<id> {archived}. The bookmarks are
# /data/kk.json (written by the test, re-read on every request); every request is logged to /data/kk.log (method, path, auth ok).
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

LOG = open('/data/kk.log', 'a', buffering=1)


def marks():
    try:
        return json.load(open('/data/kk.json'))
    except (OSError, ValueError):
        return []


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        b = json.dumps(obj if obj is not None else {}).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _auth(self):
        ok = self.headers.get('Authorization') == 'Bearer kk-secret'
        LOG.write(json.dumps({'m': self.command, 'p': self.path, 'auth': ok}) + '\n')
        if not ok:
            self._send(401, {'code': 'UNAUTHORIZED'})
        return ok

    def do_GET(self):
        if not self._auth():
            return
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        if u.path == '/api/v1/lists':
            return self._send(200, {'lists': [{'id': 'lst_1', 'name': 'Later', 'icon': '📚'}, {'id': 'bad id!', 'name': 'x'}]})
        ms = [m for m in marks() if not m.get('archived')]
        if u.path.startswith('/api/v1/lists/'):
            lid = u.path.split('/')[4]
            ms = [m for m in ms if lid in m.get('lists', [])]
        elif u.path != '/api/v1/bookmarks':
            return self._send(404, {'code': 'NOT_FOUND'})
        if q.get('archived', ['false'])[0] != 'false':
            return self._send(400, {'code': 'BAD'})
        start = int(q.get('cursor', ['0'])[0])
        size = 2  # small pages: the client has to follow nextCursor
        page = ms[start:start + size]
        return self._send(200, {'bookmarks': page, 'nextCursor': str(start + size) if start + size < len(ms) else None})

    def do_PATCH(self):
        if not self._auth():
            return
        n = int(self.headers.get('Content-Length') or 0)
        b = json.loads(self.rfile.read(n) or b'{}')
        bid = urlsplit(self.path).path.split('/')[-1]
        ms = marks()
        hit = [m for m in ms if m['id'] == bid]
        if not hit:
            return self._send(404, {'code': 'NOT_FOUND'})
        hit[0]['archived'] = bool(b.get('archived'))
        json.dump(ms, open('/data/kk.json', 'w'))
        return self._send(200, hit[0])


ThreadingHTTPServer(('127.0.0.1', 8097), H).serve_forever()
