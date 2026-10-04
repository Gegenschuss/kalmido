# 2.2.0: fake GitHub (Enterprise layout, /api/v3 on 127.0.0.1:8090) and fake Gitea / Forgejo (/api/v1 on 127.0.0.1:8091)
# for p220_api_test.py / p220_ui.js. Runs INSIDE the test container (docker exec -d python /data/fake_git.py); no real
# GitHub is ever called. The suite writes the repositories into /data/git.json (re-read on every request):
#   {"<port>": {"owner/repo": {"token": "...", "default_branch": "main", "pulls": [...], "commits": {"main": [...]},
#                              "compare": {"<head ref>": [...]}, "status": {"<sha>": {...}}, "checks": {"<sha>": [...]}}},
#    "remaining": 4999, "rate_block": false, "slow": 0}
# Every request is logged to /data/git.log (port, path, Authorization, If-None-Match, status).
# 2.18.0 (#408): + fake GitLab (/api/v4 on 127.0.0.1:8092: projects by URL-encoded path incl. nested groups, PRIVATE-TOKEN or
# Bearer, RateLimit-* headers) and fake Bitbucket Cloud (/2.0 on 127.0.0.1:8093: {values: [...]} pages, Bearer or Basic
# user:app-password). Their repositories in git.json use the providers' own shapes: "pulls" = merge requests / pull
# requests, "commits" {branch: [...]}, "compare" {ref: [...]}, "status" {sha: [...]}, "tags" [...] (also GitHub / Gitea).
import base64
import hashlib
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open('/data/git.log', 'a', buffering=1)
PREFIX = {8090: '/api/v3', 8091: '/api/v1', 8092: '/api/v4', 8093: '/2.0'}


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
                              'ptok': self.headers.get('PRIVATE-TOKEN'),
                              'status': code, 'ua': self.headers.get('User-Agent')}) + '\n')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        if port == 8092:
            self.send_header('RateLimit-Remaining', str(st.get('gl_remaining', 1999)))
            self.send_header('RateLimit-Reset', str(int(time.time()) + int(st.get('reset_in', 120))))
        if port == 8090:
            self.send_header('X-RateLimit-Remaining', str(st.get('remaining', 4999)))
            self.send_header('X-RateLimit-Reset', str(int(time.time()) + int(st.get('reset_in', 120))))
        if code == 429:
            self.send_header('Retry-After', '120')
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
        if port == 8092:
            return self.gitlab(p, q, st)
        if port == 8093:
            return self.bitbucket(p, q, st)
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
        if rest == ['tags']:
            return self._send(200, r.get('tags', []), st)
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


    def _authed(self, r, st):
        want = r.get('token')
        if not want:
            return True
        got = self.headers.get('Authorization') or ''
        ok = got == 'Bearer ' + want or self.headers.get('PRIVATE-TOKEN') == want or \
            (':' in want and got == 'Basic ' + base64.b64encode(want.encode()).decode())
        if not ok:
            self._send(401, {'message': '401 Unauthorized'}, st)
        return ok

    def gitlab(self, p, q, st):
        pre = '/api/v4/projects/'
        if not p.path.startswith(pre):
            return self._send(404, {'message': '404 Not Found'}, st)
        if st.get('gl_block'):
            return self._send(429, {'message': 'Retry later'}, st, etag=False)
        parts = p.path[len(pre):].split('/')
        key, rest = urllib.parse.unquote(parts[0]), parts[1:]
        r = st.get('8092', {}).get(key)
        if r is None:
            return self._send(404, {'message': '404 Project Not Found'}, st)
        if not self._authed(r, st):
            return
        if not rest:
            return self._send(200, {'path': key.rsplit('/', 1)[-1], 'path_with_namespace': key,
                                    'default_branch': r.get('default_branch', 'main')}, st)
        if rest == ['merge_requests']:
            return self._send(200, r.get('pulls', []), st)
        if rest == ['repository', 'commits']:
            return self._send(200, r.get('commits', {}).get((q.get('ref_name') or ['main'])[0], []), st)
        if rest == ['repository', 'compare']:
            return self._send(200, {'commits': r.get('compare', {}).get((q.get('to') or [''])[0], [])}, st)
        if rest[:2] == ['repository', 'commits'] and len(rest) == 4 and rest[3] == 'statuses':
            return self._send(200, r.get('status', {}).get(urllib.parse.unquote(rest[2]), []), st)
        if rest == ['repository', 'tags']:
            return self._send(200, r.get('tags', []), st)
        return self._send(404, {'message': '404 Not Found'}, st)

    def bitbucket(self, p, q, st):
        pre = '/2.0/repositories/'
        if not p.path.startswith(pre):
            return self._send(404, {'type': 'error'}, st)
        parts = p.path[len(pre):].split('/')
        if len(parts) < 2:
            return self._send(404, {'type': 'error'}, st)
        key, rest = parts[0] + '/' + parts[1], parts[2:]
        r = st.get('8093', {}).get(key)
        if r is None:
            return self._send(404, {'type': 'error', 'error': {'message': 'Repository not found'}}, st)
        if not self._authed(r, st):
            return
        if not rest:
            return self._send(200, {'slug': parts[1], 'full_name': key, 'mainbranch': {'name': r.get('default_branch', 'main')}}, st)
        if rest == ['pullrequests']:
            return self._send(200, {'values': r.get('pulls', []), 'pagelen': 30}, st)
        if rest[0] == 'commits' and len(rest) == 2:
            ref = urllib.parse.unquote(rest[1])
            if q.get('exclude'):
                return self._send(200, {'values': r.get('compare', {}).get(ref, [])}, st)
            return self._send(200, {'values': r.get('commits', {}).get(ref, [])}, st)
        if rest[0] == 'commit' and len(rest) == 3 and rest[2] == 'statuses':
            return self._send(200, {'values': r.get('status', {}).get(rest[1], [])}, st)
        if rest == ['refs', 'tags']:
            return self._send(200, {'values': r.get('tags', [])}, st)
        return self._send(404, {'type': 'error'}, st)


for port in (8090, 8091, 8092, 8093):
    threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever, daemon=True).start()
while True:
    time.sleep(3600)
