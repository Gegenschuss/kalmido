"""kalmido-embed (2.59.0, #1375): a small local text embedding service for "Related tasks".

It turns texts into vectors (numbers) with a multilingual embedding model that runs on the CPU inside this container. It
writes no text, holds no data and needs no network at run time: the model is part of the image (Dockerfile). Kalmido calls
it over the internal network (KALMIDO_EMBED_URL); without it Kalmido works as before and hides the related tasks.

  GET  /health  -> {"ok": true, "model": "...", "dim": 384}
  POST /embed   {"texts": ["..."], "kind": "passage" | "query"} -> {"model": "...", "dim": 384, "vectors": [[...], ...]}

The vectors are L2-normalised (cosine = dot product). At most MAX_TEXTS texts per call, each cut to MAX_CHARS characters
and to the model's token limit. EMBED_STUB=1 answers with deterministic pseudo-vectors from word hashes (tests, CI: no model).
Only the Python standard library besides onnxruntime, tokenizers and numpy.
"""
import hashlib
import json
import math
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("EMBED_PORT", "8090"))
MODEL_DIR = os.environ.get("EMBED_MODEL_DIR", "/model")
MODEL_NAME = os.environ.get("EMBED_MODEL", "intfloat/multilingual-e5-small")
DIM = int(os.environ.get("EMBED_DIM", "384"))
POOLING = os.environ.get("EMBED_POOLING", "mean")  # mean | cls
PREFIX = {"query": os.environ.get("EMBED_PREFIX_QUERY", "query: "), "passage": os.environ.get("EMBED_PREFIX_PASSAGE", "passage: ")}
MAX_TEXTS = 64
MAX_CHARS = 4000
MAX_TOKENS = int(os.environ.get("EMBED_MAX_TOKENS", "512"))
MAX_BODY = 2 * 1024 * 1024
THREADS = int(os.environ.get("EMBED_THREADS", "0"))  # 0 = onnxruntime decides
STUB = os.environ.get("EMBED_STUB", "") == "1"
LOCK_WAIT = float(os.environ.get("EMBED_LOCK_WAIT", "5"))  # seconds a request waits for the model, then 503 (no endless queue)


class Busy(Exception):
    """The model did not come free within LOCK_WAIT."""


class Stub:
    """Deterministic vectors without a model: every word (lower case, accents kept) adds a fixed pseudo-random direction,
    so texts sharing words point the same way (enough to test ranking, thresholds and the boundaries)."""
    name = "stub"

    def embed(self, texts, kind):
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in re.findall(r"\w+", t.lower()):
                h = hashlib.sha256(w.encode()).digest()
                for i in range(0, 32, 2):
                    v[(h[i] * 256 + h[i + 1]) % DIM] += 1.0 if h[i] & 1 else -1.0
            out.append(_norm(v))
        return out


class Model:
    def __init__(self):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np = np
        self.name = MODEL_NAME
        self.tok = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.no_padding()  # one text per run
        so = ort.SessionOptions()
        if THREADS:
            so.intra_op_num_threads = THREADS
        self.sess = ort.InferenceSession(os.path.join(MODEL_DIR, "model.onnx"), so, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}
        self.lock = threading.Lock()  # one batch at a time: the CPU is shared with Kalmido and its database

    def embed(self, texts, kind):
        # one text per run: on a small CPU batches are not faster, but need far more memory (16 x 512 tokens)
        return [self._one(PREFIX.get(kind, "") + t) for t in texts]

    def _one(self, text):
        np = self.np
        enc = [self.tok.encode(text)]
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        if not self.lock.acquire(timeout=LOCK_WAIT):
            raise Busy
        try:
            hidden = self.sess.run(None, feed)[0]  # (batch, tokens, dim)
        finally:
            self.lock.release()
        if POOLING == "cls":
            pooled = hidden[:, 0]
        else:
            m = mask[..., None].astype(hidden.dtype)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        pooled = pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
        return [round(float(x), 6) for x in pooled[0]]


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [round(x / n, 6) for x in v]


ENGINE = None


class Handler(BaseHTTPRequestHandler):
    server_version = "kalmido-embed"
    sys_version = ""

    def log_message(self, fmt, *args):  # no request log: the texts are never logged, the paths say nothing
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True, "model": ENGINE.name, "dim": DIM})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/embed":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > MAX_BODY:
            return self._send(413 if n > MAX_BODY else 400, {"error": "body"})
        try:
            b = json.loads(self.rfile.read(n))
            texts, kind = b.get("texts"), b.get("kind", "passage")
            if not isinstance(texts, list) or not texts or len(texts) > MAX_TEXTS or kind not in PREFIX:
                raise ValueError
            texts = [str(t if t is not None else "")[:MAX_CHARS] for t in texts]
        except (ValueError, AttributeError, UnicodeDecodeError):
            return self._send(400, {"error": "expected {texts: [1..%d strings], kind: passage|query}" % MAX_TEXTS})
        try:
            vecs = ENGINE.embed(texts, kind)
        except Busy:
            return self._send(503, {"error": "busy"})
        except Exception as e:  # noqa: BLE001 -- the reason in the log, never the texts
            print("embed: failed:", type(e).__name__, flush=True)
            return self._send(500, {"error": "embedding failed"})
        self._send(200, {"model": ENGINE.name, "dim": DIM, "vectors": vecs})


def main():
    global ENGINE
    ENGINE = Stub() if STUB else Model()
    print(f"kalmido-embed: {ENGINE.name}, dim {DIM}, port {PORT}" + (" (stub)" if STUB else ""), flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
