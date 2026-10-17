# 2.76.0 (#1023): a tiny pack catalogue for p276_a_packs_api_test.py; runs INSIDE the test container (docker exec -d
# python /data/fake_packs.py), port 8099. GET /<path> answers the file /data/packs/<path> (index.json and the pack files,
# written by the test, read on every request); GET /redirect-internal answers 302 to a link-local address (the app must
# not follow it). Every request goes to /data/packs.log (the test checks that nothing is fetched without a catalogue).
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = '/data/packs'
LOG = open('/data/packs.log', 'a', buffering=1)


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        LOG.write(f'GET {path}\n')
        if path == '/redirect-internal':
            self.send_response(302)
            self.send_header('Location', 'http://169.254.169.254/latest/meta-data')
            self.end_headers()
            return
        p = os.path.normpath(os.path.join(ROOT, path.lstrip('/')))
        if not p.startswith(ROOT + '/') or not os.path.isfile(p):
            self.send_response(404)
            self.end_headers()
            return
        data = open(p, 'rb').read()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


ThreadingHTTPServer(('127.0.0.1', 8099), H).serve_forever()
