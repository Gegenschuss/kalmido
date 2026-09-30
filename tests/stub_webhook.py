# fake webhook receiver for webhooks_test.py: runs INSIDE the test container (docker exec -d python /data/stub_webhook.py) on
# 127.0.0.1:8097 and logs every request (path, headers, body) to /data/wh.log.
#   /ok /anything -> 200   /fail -> 500   /redirect -> 302 to /ok   /slow -> answers after 12 s   /big -> 200 with 2 MB
#   /code/<n> -> status n
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open('/data/wh.log', 'a', buffering=1)


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n).decode('utf-8', 'replace')
        LOG.write(json.dumps({'path': self.path, 'at': time.time(), 'body': body,
                              'headers': {k: v for k, v in self.headers.items()}}) + '\n')
        code, extra, out = 200, {}, b'{"ok": true}'
        if self.path.startswith('/fail'):
            code = 500
        elif self.path.startswith('/redirect'):
            code, extra = 302, {'Location': '/ok-after-redirect'}
        elif self.path.startswith('/slow'):
            time.sleep(12)
        elif self.path.startswith('/big'):
            out = b'x' * (2 * 1024 * 1024)
        elif self.path.startswith('/code/'):
            code = int(self.path.split('/')[2])
        self.send_response(code)
        for k, v in extra.items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        try:
            self.wfile.write(out)
        except OSError:
            pass


ThreadingHTTPServer(('127.0.0.1', 8097), H).serve_forever()
