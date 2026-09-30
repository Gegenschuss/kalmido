# 2.2.0: fake GitHub (Enterprise layout, /api/v3 on 127.0.0.1:8090) and fake Gitea / Forgejo (/api/v1 on 127.0.0.1:8091)
# for p220_api_test.py / p220_ui.js. Runs INSIDE the test container (docker exec -d python /data/fake_git.py); no real
# GitHub is ever called. The suite writes the repositories into /data/git.json (re-read on every request):
#   {"<port>": {"owner/repo": {"token": "...", "default_branch": "main", "pulls": [...], "commits": {"main": [...]},
#                              "compare": {"<head ref>": [...]}, "status": {"<sha>": {...}}, "checks": {"<sha>": [...]}}},
#    "remaining": 4999, "rate_block": false, "slow": 0}
# Every request is logged to /data/git.log (port, path, Authorization, If-None-Match, status).
import hashlib
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open('/data/git.log', 'a', buffering=1)
PREFIX = {8090: '/api/v3', 8091: '/api/v1'}


def state():
    try:
        return json.load(open('/data/git.json'))
    except (OSError, ValueError):
        return {}


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, obj, st, etag=True):
        port = self.server.server_address[1]
        body = json.dumps(obj).encode() if obj is not None else b''
        tag = '"' + hashlib.md5(body).hexdigest() + '"'
        inm = self.headers.get('If-None-Match')
        if code == 200 and etag and inm == tag:
            code, body = 304, b''
        LOG.write(json.dumps({'port': port, 'path': self.path, 'auth': self.headers.get('Authorization'), 'inm': inm,
                              'status': code, 'ua': self.headers.get('User-Agent')}) + '\n')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        if port == 8090:
            self.send_header('X-RateLimit-Remaining', str(st.get('remaining', 4999)))
            self.send_header('X-RateLimit-Reset', str(int(time.time()) + int(st.get('reset_in', 120))))
        if code in (200, 304):
            self.send_header('ETag', tag)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        port = self.server.server_address[1]
        st = state()
        if st.get('slow'):
            time.sleep(float(st['slow']))
        p = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(p.query)
        pre = PREFIX[port]
        if not p.path.startswith(pre + '/repos/'):
            return self._send(404, {'message': 'Not Found'}, st)
        parts = p.path[len(pre) + 7:].split('/')
        if len(parts) < 2:
            return self._send(404, {'message': 'Not Found'}, st)
        key, rest = parts[0] + '/' + parts[1], parts[2:]
        repos = st.get(str(port), {})
        r = repos.get(key)
        if port == 8090 and st.get('rate_block'):
            return self._send(403, {'message': 'API rate limit exceeded'}, {**st, 'remaining': 0}, etag=False)
        if r is None:
            return self._send(404, {'message': 'Not Found'}, st)
        want = r.get('token')
        if want:
            got = self.headers.get('Authorization') or ''
            if got not in ('Bearer ' + want, 'token ' + want):
                return self._send(401, {'message': 'Bad credentials'}, st)
        if not rest:
            return self._send(200, {'name': parts[1], 'owner': {'login': parts[0]}, 'default_branch': r.get('default_branch', 'main')}, st)
        if rest == ['pulls']:
            return self._send(200, r.get('pulls', []), st)
        if rest == ['commits']:
            return self._send(200, r.get('commits', {}).get((q.get('sha') or ['main'])[0], []), st)
        if rest[0] == 'compare' and len(rest) >= 2:
            head = urllib.parse.unquote('/'.join(rest[1:])).split('...', 1)[-1]
            return self._send(200, {'commits': r.get('compare', {}).get(head, [])}, st)
        if rest[0] == 'commits' and len(rest) == 3 and rest[2] == 'status':
            return self._send(200, r.get('status', {}).get(rest[1], {'state': 'pending', 'total_count': 0, 'statuses': []}), st)
        if rest[0] == 'commits' and len(rest) == 3 and rest[2] == 'check-runs':
            if port != 8090:
                return self._send(404, {'message': 'Not Found'}, st)
            return self._send(200, {'total_count': len(r.get('checks', {}).get(rest[1], [])), 'check_runs': r.get('checks', {}).get(rest[1], [])}, st)
        return self._send(404, {'message': 'Not Found'}, st)


for port in (8090, 8091):
    threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever, daemon=True).start()
while True:
    time.sleep(3600)
