import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0)); body = self.rfile.read(n).decode()
        t = self.headers.get('Title') or ''
        try: t = t.encode('latin-1').decode('utf-8')
        except Exception: pass
        rec = {'topic': self.path.strip('/'), 'title': t, 'msg': body, 'click': self.headers.get('Click'), 'prio': self.headers.get('Priority')}
        with open('/data/ntfy.log', 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        if rec['topic'].startswith('fail-'):  # admin_alerts_test.py: a topic whose publishes fail
            self.send_response(500); self.end_headers(); return
        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(('127.0.0.1', 9999), H).serve_forever()
