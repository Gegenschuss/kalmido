# Fake push service for webpush_test.py / webpush_ui.js, runs INSIDE the test container on 127.0.0.1:9997
# (allowed via KALMIDO_WEBPUSH_HOSTS=http://127.0.0.1:9997). Logs every request (headers + raw encrypted body,
# base64) to /data/webpush.log. The answer depends on the path: /gone -> 410, /nf -> 404, /rate -> 429
# (Retry-After 120), /bad -> 403, /big -> 413, anything else -> 201.
import base64, http.server, json
CODES = {"gone": 410, "nf": 404, "rate": 429, "bad": 403, "big": 413}
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n)
        code = CODES.get(self.path.strip("/").split("/")[-1].split("-")[0], 201)
        rec = {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
               "body": base64.b64encode(body).decode(), "code": code}
        with open("/data/webpush.log", "a") as f:
            f.write(json.dumps(rec) + "\n")
        self.send_response(code)
        if code == 429:
            self.send_header("Retry-After", "120")
        self.send_header("Content-Length", "0"); self.end_headers()
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", 9997), H).serve_forever()
