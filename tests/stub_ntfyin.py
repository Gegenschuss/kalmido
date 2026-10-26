"""2.142.0 C (#2150): a tiny ntfy server for the share inbox tests, run INSIDE the test container (port 8099). GET /<topic>/json?poll=1&since=X
answers the messages of /data/ntfyin_msgs.json (a list of {topic, id, message, title?}) for that topic after id X (all when X is not an id),
and records every request (path + Authorization) in /data/ntfyin.log."""
import http.server
import json
import time
import urllib.parse


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        topic = u.path.strip("/").split("/")[0]
        with open("/data/ntfyin.log", "a") as f:
            f.write(json.dumps({"path": self.path, "auth": self.headers.get("Authorization"), "t": time.time()}) + "\n")
        try:
            msgs = [m for m in json.load(open("/data/ntfyin_msgs.json")) if m["topic"] == topic]
        except (OSError, ValueError):
            msgs = []
        since = (q.get("since") or [""])[0]
        ids = [m["id"] for m in msgs]
        if since in ids:
            msgs = msgs[ids.index(since) + 1:]
        if topic.startswith("slow-"):  # 2.312.0 C (#3265): a hanging server (answers late, logs the end)
            time.sleep(12)
            with open("/data/ntfyin.log", "a") as f:
                f.write(json.dumps({"path": self.path, "end": True, "t": time.time()}) + "\n")
        if topic.startswith("down-"):
            self.send_response(500)
            self.end_headers()
            return
        body = "".join(json.dumps({**m, "event": "message", "time": 1}) + "\n" for m in msgs).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", 8099), H).serve_forever()
