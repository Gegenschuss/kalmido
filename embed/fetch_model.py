"""Build step of kalmido-embed: download the model files of one fixed revision and check their SHA-256 (no run-time network)."""
import hashlib
import os
import sys
import urllib.request


def fetch(base, src, dst, want):
    h = hashlib.sha256()
    with urllib.request.urlopen(base + src, timeout=600) as r, open(dst + ".part", "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            h.update(b)
            f.write(b)
    if h.hexdigest() != want:
        os.remove(dst + ".part")
        sys.exit(f"checksum mismatch: {src}")
    os.replace(dst + ".part", dst)


if __name__ == "__main__":
    e = os.environ
    base = f"https://huggingface.co/{e['EMBED_REPO']}/resolve/{e['EMBED_REV']}/"
    os.makedirs("/model", exist_ok=True)
    fetch(base, e["EMBED_ONNX"], "/model/model.onnx", e["EMBED_ONNX_SHA256"])
    fetch(base, e["EMBED_TOK"], "/model/tokenizer.json", e["EMBED_TOK_SHA256"])
