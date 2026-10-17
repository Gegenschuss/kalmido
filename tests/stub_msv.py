# 2.73.0 A (#661): a misbehaving "other Kalmido server" for p273_a_api_test.py; runs INSIDE the test container (docker exec -d
# python /data/stub_msv.py), port 8099. The first path segment chooses the misbehaviour of every /<kind>/api/v1/... request:
#   deep   200 JSON nested 100000 levels deep       big    200 JSON of 9 MB
#   redir  302 to the real app                       html   200 text/html
#   rate   429 with Retry-After: 7                   e500   500
#   evil   a well-formed Kalmido answer with odd values (HTML in titles, wrong types, extra fields) for /me, /lists, /tasks
# Every request goes to /data/msv.log (method, path, whether a bearer token came along -- never the token itself).
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open('/data/msv.log', 'a', buffering=1)


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, raw=b'', ctype='application/json', extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _any(self):
        auth = (self.headers.get('Authorization') or '').startswith('Bearer ')
        LOG.write(f"{self.command} {self.path} bearer={auth}\n")
        kind, _, rest = self.path.lstrip('/').partition('/')
        rest = re.sub(r'^/n\d+(?=/)', '', '/' + rest.split('?')[0])  # /evil/n3/... = another address of the same server
        if kind == 'deep':
            return self._send(200, b'[' * 100000 + b']' * 100000)
        if kind == 'big':
            return self._send(200, b'{"x":"' + b'a' * (9 * 1024 * 1024) + b'"}')
        if kind == 'redir':
            return self._send(302, extra={'Location': 'http://127.0.0.1:3040/api/v1/me'})
        if kind == 'html':
            return self._send(200, b'<html><body>hello</body></html>', 'text/html')
        if kind == 'rate':
            return self._send(429, b'{"error":{"code":"rate_limited","message":"slow down"}}', extra={'Retry-After': '7'})
        if kind == 'e500':
            return self._send(500, b'{}')
        if kind == 'evil':
            if rest == '/api/v1/me':
                return self._send(200, json.dumps({"id": 7, "username": "<b>x</b>", "display_name": "<script>alert(1)</script>", "kind": "user",
                                                   "token": {"effective_scopes": ["read"]}}).encode())
            if rest == '/api/v1/lists':
                return self._send(200, json.dumps({"data": [{"id": 3, "name": "<img src=x onerror=alert(1)>", "color": "red;background:url(x)",
                                                             "role": "owner", "is_inbox": "yes", "secret": "s"}, {"id": "4", "name": "bad id"},
                                                            "junk"], "next_cursor": None}).encode())
            if rest == '/api/v1/tasks':
                return self._send(200, json.dumps({"data": [{"id": 9, "title": "<img src=x onerror=alert(1)>", "list_id": 3, "due": "tomorrow",
                                                             "due_time": "25:99:00", "priority": "urgent", "status": {"x": 1},
                                                             "tags": ["a", 5, {"b": 1}], "notes": "hidden", "password": "p"},
                                                            {"id": True, "title": "bool id"}], "next_cursor": {"x": 1}}).encode())
        return self._send(404, b'{"error":{"code":"not_found","message":"Not found"}}')

    do_GET = do_POST = do_PATCH = do_DELETE = _any


ThreadingHTTPServer(('127.0.0.1', 8099), H).serve_forever()
