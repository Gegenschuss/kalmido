# 2.85.0 (#1162): a tiny feed server for p285_b_api_test.py / p285_b_ui.js; runs INSIDE the test container (docker exec -d
# python /data/fake_feeds.py), port 8098. GET /<name> serves /data/feeds/<name> (written by the test, re-read on every
# request; an ETag = the file's size + mtime, If-None-Match -> 304). Special paths: /redir-private (302 to a port the
# admin did not allow), /redir-meta (302 to the cloud metadata address), /redir-js (302 to javascript:), /big.xml (3 MB),
# /status-401 + /status-403 (2.172.0 B, #2678).
# Every request is logged to /data/feeds.log (method, path, If-None-Match).
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = '/data/feeds'
LOG = open('/data/feeds.log', 'a', buffering=1)
REDIR = {'/redir-private': 'http://127.0.0.1:8099/rss.xml', '/redir-meta': 'http://169.254.169.254/latest/meta-data/',
         '/redir-js': 'javascript:alert(1)', '/redir-ok': '/rss.xml'}


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def do_GET(self):
        LOG.write(json.dumps({'m': self.command, 'p': self.path, 'inm': self.headers.get('If-None-Match') or '',
                              'ua': self.headers.get('User-Agent') or ''}) + '\n')
        p = self.path.split('?', 1)[0]
        if p in ('/status-401', '/status-403'):  # 2.172.0 B (#2678): a login wall / a site refusing server fetches
            self._send(int(p[-3:]), b'denied', 'text/plain')
            return
        if p in REDIR:
            self.send_response(302)
            self.send_header('Location', REDIR[p])
            self.end_headers()
            return
        if p == '/slow.xml':  # 2.85.0 (#1162 review): headers at once, then one byte every 2 s for 60 s (a trickling server)
            self.send_response(200)
            self.send_header('Content-Type', 'application/rss+xml')
            self.end_headers()
            try:
                for _ in range(30):
                    self.wfile.write(b' ')
                    self.wfile.flush()
                    time.sleep(2)
            except OSError:
                pass
            return
        if p == '/big.xml':
            b = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Big</title>' + b'<!-- padding -->' * 200000 + b'</channel></rss>'
            self._send(200, b)
            return
        f = os.path.join(DIR, os.path.basename(p))
        if not os.path.isfile(f):
            self._send(404, b'not found', 'text/plain')
            return
        st = os.stat(f)
        etag = f'"{st.st_size}-{int(st.st_mtime)}"'
        if self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.end_headers()
            return
        self._send(200, open(f, 'rb').read(), 'text/html' if f.endswith('.html') else 'application/rss+xml', etag)

    def _send(self, code, b, ctype='application/rss+xml', etag=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        if etag:
            self.send_header('ETag', etag)
        self.end_headers()
        self.wfile.write(b)


ThreadingHTTPServer(('127.0.0.1', 8098), H).serve_forever()
