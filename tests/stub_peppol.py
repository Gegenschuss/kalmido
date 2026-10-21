"""2.154.0 B (#1960): a stand-in for the Peppol access point providers in the Peppol tests, run INSIDE the test container
(port 8098; no real provider is ever called). Two faces:
 - /sc/api/v2/...  like the Storecove API: GET /legal_entities/<id> (200 with the key "good-key", else 401),
   POST /discovery/receives ({"code": "OK"} for the identifiers in /data/peppol_reachable.json, default 0123456749),
   POST /document_submissions -> {"guid": "g-<n>"}, GET /document_submissions/<guid>/evidence/sending (404 until
   /data/peppol_delivered exists)
 - /own/...  the protocol of an own endpoint (docs/OFFICE.md): GET /check, GET /participants/<id> -> {reachable},
   POST /documents (500 for the receiver 9930:DE111111111) -> {id, status}, GET /documents/<id> -> {status: rejected}
Every request (method, path, Authorization, the other X- headers and the body) is one line in /data/peppol.log."""
import base64
import http.server
import json
import os

LOG = "/data/peppol.log"
N = [0]


class H(http.server.BaseHTTPRequestHandler):
    def _log(self, body=b""):
        with open(LOG, "a") as f:
            f.write(json.dumps({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"),
                                "sender": self.headers.get("X-Peppol-Sender"), "receiver": self.headers.get("X-Peppol-Receiver"),
                                "idem": self.headers.get("Idempotency-Key"), "test": self.headers.get("X-Peppol-Test"),
                                "body": base64.b64encode(body).decode()}) + "\n")

    def _send(self, code, obj=None):
        data = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _ok_key(self):
        return self.headers.get("Authorization") == "Bearer good-key"

    def do_GET(self):
        self._log()
        p = self.path
        if not self._ok_key():
            return self._send(401, {"error": "unauthorized"})
        if p.startswith("/sc/api/v2/legal_entities/"):
            return self._send(200, {"id": int(p.rsplit("/", 1)[1])})
        if p.startswith("/sc/api/v2/document_submissions/") and p.endswith("/evidence/sending"):
            return self._send(200, {"network": "peppol"}) if os.path.exists("/data/peppol_delivered") else self._send(404, {})
        if p == "/own/check":
            return self._send(200, {"ok": True})
        if p.startswith("/own/participants/"):
            ident = p.split("/own/participants/", 1)[1]
            return self._send(200, {"reachable": not ident.startswith("0088:")})
        if p.startswith("/own/documents/"):
            return self._send(200, {"status": "rejected", "message": "Buyer rejected: unknown order"})
        return self._send(404, {})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._log(body)
        if not self._ok_key():
            return self._send(401, {"error": "unauthorized"})
        if self.path == "/sc/api/v2/discovery/receives":
            try:
                ok = json.load(open("/data/peppol_reachable.json"))
            except (OSError, ValueError):
                ok = ["0123456749"]
            return self._send(200, {"code": "OK" if json.loads(body).get("identifier") in ok else "NOK", "email": False})
        if self.path == "/sc/api/v2/document_submissions":
            N[0] += 1
            return self._send(200, {"guid": f"g-{N[0]}"})
        if self.path == "/own/documents":
            if self.headers.get("X-Peppol-Receiver") == "9930:DE111111111":
                return self._send(500, {"error": "boom"})
            N[0] += 1
            return self._send(200, {"id": f"c-{N[0]}", "status": "sent"})
        return self._send(404, {})

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", 8098), H).serve_forever()
