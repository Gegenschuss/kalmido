# fake ntfy inbox (8081), the former Paperless port (8082, 2.36.0: only a sink that logs; nothing may reach it) and an
# "attacker / internal service" sink (8084) for security_test.py; runs INSIDE the test container (docker exec -d python /data/fake_services.py), logs to /data/fake.log
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open('/data/fake.log', 'a', buffering=1)
SENT = set()


def log(**kw):
    LOG.write(json.dumps(kw) + '\n')


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json', extra=None):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        port = self.server.server_address[1]
        log(port=port, method='GET', path=self.path, auth=self.headers.get('Authorization'))
        if port == 8081 and '/json' in self.path:  # inbox stream: every message of /data/inbox.json once
            try:
                msgs = json.load(open('/data/inbox.json'))
            except (OSError, ValueError):
                msgs = []
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson')
            self.end_headers()
            for m in msgs:
                if m['id'] in SENT:
                    continue
                SENT.add(m['id'])
                m.setdefault('event', 'message')
                m.setdefault('time', int(time.time()))
                m.setdefault('topic', 'inbox')
                self.wfile.write((json.dumps(m) + '\n').encode())
                self.wfile.flush()
            return
        if port == 8081 and self.path.startswith('/file/redir'):
            return self._send(302, b'', 'text/plain', {'Location': 'http://127.0.0.1:8084/steal-redirect'})
        if port == 8081 and self.path.startswith('/file/'):
            return self._send(200, b'good file from ntfy', 'text/plain')
        if port == 8084:
            return self._send(200, b'secret-internal-data', 'text/plain')
        self._send(404, '{}')

    def do_POST(self):
        port = self.server.server_address[1]
        n = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(n)
        log(port=port, method='POST', path=self.path, auth=self.headers.get('Authorization'))
        self._send(200, '"task-uuid-1"')


for p in (8081, 8082, 8084):
    threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', p), H).serve_forever, daemon=True).start()
while True:
    time.sleep(3600)
