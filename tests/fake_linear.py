# 2.394.0 A (#3377): fake Linear GraphQL API for p2394_a_import_test.py. Runs INSIDE the test container (docker exec -d python
# /data/fake_linear.py) on 127.0.0.1:8085, the server reaches it through KALMIDO_LINEAR_API=http://127.0.0.1:8085/graphql.
# No real Linear is ever called. The suite writes /data/linear.json (re-read on every request):
#   {"key": "<the valid API key>", "issues": [<issue nodes in Linear's shape>], "page": 2, "mode": "" | "ratelimit" | "ratelimit_gql"
#    | "auth_gql" | "broken" | "big"}
# Pages: "page" issues per answer, the cursor is the index of the next issue as text. Every request is logged to /data/linear.log
# (path, whether an Authorization header came, whether it was the valid key, the cursor, the status) -- never the key itself.
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open('/data/linear.log', 'a', buffering=1)


def state():
    try:
        return json.load(open('/data/linear.json'))
    except (OSError, ValueError):
        return {}


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, obj, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        st = state()
        n = int(self.headers.get('Content-Length') or 0)
        try:
            req = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            req = {}
        auth = self.headers.get('Authorization')
        good = bool(auth) and auth == st.get('key')
        after = (req.get('variables') or {}).get('after')
        mode = st.get('mode') or ''
        code, out, raw = 200, None, None
        if self.path != '/graphql' or 'issues' not in str(req.get('query') or ''):
            code, out = 404, {'errors': [{'message': 'not found'}]}
        elif mode == 'ratelimit':
            code, out = 429, {'errors': [{'message': 'Rate limit exceeded', 'extensions': {'code': 'RATELIMITED'}}]}
        elif mode == 'ratelimit_gql':
            code, out = 400, {'errors': [{'message': 'Rate limit exceeded', 'extensions': {'code': 'RATELIMITED'}}]}
        elif not good and mode == 'auth_gql':
            code, out = 200, {'errors': [{'message': 'Authentication required, not authenticated: ' + str(auth),
                                          'extensions': {'type': 'authentication error', 'code': 'AUTHENTICATION_ERROR'}}]}
        elif not good:
            code, out = 401, {'errors': [{'message': 'Authentication required: ' + str(auth), 'extensions': {'code': 'AUTHENTICATION_ERROR'}}]}
        elif mode == 'broken':
            raw = b'<html>gateway</html>'
        elif mode == 'big':
            raw = b'{"data": {"issues": {"nodes": [' + b'{"title": "x"},' * 900000 + b'{}]}}}'
        else:
            issues, page = st.get('issues') or [], int(st.get('page') or 50)
            i = int(after or 0)
            nxt = i + page
            out = {'data': {'issues': {'nodes': issues[i:nxt],
                                       'pageInfo': {'hasNextPage': nxt < len(issues), 'endCursor': str(nxt) if nxt < len(issues) else None}}}}
        LOG.write(json.dumps({'path': self.path, 'auth': bool(auth), 'good': good, 'after': after, 'status': code,
                              'ua': self.headers.get('User-Agent')}) + '\n')
        self._send(code, out, raw)


ThreadingHTTPServer(('127.0.0.1', 8085), H).serve_forever()
