"""2.469.0 (#3459): a stand-in for the Stripe API in the online payment tests, run INSIDE the test container (port 8099; no real
provider and no real account is ever called). Bearer "sk_test_good" only, else 401. POST /v1/checkout/sessions -> {id: cs_<n>, url};
POST .../expire; GET /v1/balance; GET /v1/balance_transactions?payout=<id> -> two charges with fees (120 + 30) and the payout row.
/data/payonline_fail exists = 500 on every request. Every request is one line in /data/payonline.log."""
import http.server
import json
import os
import urllib.parse

LOG = "/data/payonline.log"
N = [0]


class H(http.server.BaseHTTPRequestHandler):
    def _go(self):
        n = int(self.headers.get("Content-Length") or 0)
        form = dict(urllib.parse.parse_qsl(self.rfile.read(n).decode())) if n else {}
        with open(LOG, "a") as f:
            f.write(json.dumps({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"),
                                "idem": self.headers.get("Idempotency-Key"), "form": form}) + "\n")
        if os.path.exists("/data/payonline_fail"):
            return self._send(500, {"error": {"message": "boom"}})
        if self.headers.get("Authorization") != "Bearer sk_test_good":
            return self._send(401, {"error": {"message": "bad key"}})
        p = urllib.parse.urlsplit(self.path).path
        if p == "/v1/balance":
            return self._send(200, {"object": "balance"})
        if p == "/v1/checkout/sessions":
            N[0] += 1
            sid = f"cs_{N[0]}"
            return self._send(200, {"id": sid, "url": f"https://checkout.stripe.com/c/pay/{sid}"})
        if p.endswith("/expire"):
            return self._send(200, {"status": "expired"})
        if p == "/v1/balance_transactions":
            return self._send(200, {"has_more": False, "data": [{"id": "txn_1", "type": "charge", "fee": 120}, {"id": "txn_2", "type": "payment", "fee": 30},
                                                                {"id": "txn_3", "type": "payout", "fee": 999}]})
        return self._send(404, {})

    do_GET = do_POST = _go

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", 8099), H).serve_forever()
