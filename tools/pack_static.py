#!/usr/bin/env python3
"""2.442.0 (#2808): packs the client's JavaScript and CSS ahead of time for the Docker image, so a server without a compressing
proxy still sends about a third of the bytes and nothing is packed at run time.

Every .js / .css under <static dir> as it goes out (without comments, core/strip.py) is written to <out dir> as
<content hash>.gz and, with the package brotli, <content hash>.br. The hash is the one of core/pages.py st_asset, so a file
changed after the build simply finds no packed copy and goes out plain: never a stale one. Small files are left out.
usage: pack_static.py <static dir> <out dir>"""
import gzip
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "kalmido", "core")]
from strip import strip_asset  # noqa: E402  (a file of its own without imports from the app)

try:
    import brotli
except ImportError:
    brotli = None

PACK_MIN = 1024  # bytes: as in core/compress.py


def pack(root, out):
    n = 0
    for base, _, names in os.walk(root):
        for name in names:
            if not name.endswith((".js", ".css")):
                continue
            path = os.path.join(base, name)
            with open(path, "rb") as f:
                data = f.read()
            served = strip_asset(os.path.relpath(path, root).replace(os.sep, "/"), data)
            data = data if served is None else served
            if len(data) < PACK_MIN:
                continue
            h = hashlib.sha256(data).hexdigest()[:12]
            with open(os.path.join(out, h + ".gz"), "wb") as f:
                f.write(gzip.compress(data, 9, mtime=0))
            if brotli:
                with open(os.path.join(out, h + ".br"), "wb") as f:
                    f.write(brotli.compress(data, quality=11))
            n += 1
    return n


if __name__ == "__main__":
    os.makedirs(sys.argv[2], exist_ok=True)
    print("packed", pack(sys.argv[1], sys.argv[2]), "files", "with brotli" if brotli else "gzip only")
