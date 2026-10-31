#!/usr/bin/env python3
"""2.442.0 (#2808): the Docker image sends JS / CSS packed ahead of time (tools/pack_static.py), by Accept-Encoding.
 - gzip and br: Content-Encoding, the same bytes as the plain answer once unpacked, about a third of the size at most
 - Vary: Accept-Encoding on both, an own ETag per encoding, 304 on each
 - no Accept-Encoding and a Range request: the plain file as before; an unknown file 404
No login needed (static files), so nothing differs for a person without an organisation.
usage: p2442_b_static_pack_test.py <datadir>"""
import gzip
import re
import sys

import requests
from kt import B, check, done, fresh

fresh(prefix="P2442B")
html = requests.get(B + "/").text
src = re.search(r'src="(/static/js/render\.js\?v=\w+)"', html).group(1)
css = re.search(r'href="(/static/[\w./-]+\.css\?v=\w+)"', html).group(1)
RAW = {"stream": True}


def get(path, enc, **kw):
    return requests.get(B + path, headers={"Accept-Encoding": enc, **kw}, **RAW)


for path in (src, css):
    plain = get(path, "identity")
    body = plain.raw.read()
    check(plain.status_code == 200 and "Content-Encoding" not in plain.headers and "Accept-Encoding" in plain.headers.get("Vary", ""), f"{path}: plain with Vary")
    z = get(path, "gzip")
    data = z.raw.read()
    check(z.headers.get("Content-Encoding") == "gzip" and "Accept-Encoding" in z.headers.get("Vary", ""), f"{path}: gzip answer {dict(z.headers)}")
    check(gzip.decompress(data) == body, f"{path}: unpacks to the plain bytes")
    check(len(data) * 2 < len(body), f"{path}: packed {len(data)} of {len(body)}")
    br = get(path, "br")
    check(br.headers.get("Content-Encoding") == "br", f"{path}: br when the browser takes it")
    check(len({plain.headers["ETag"], z.headers["ETag"], br.headers["ETag"]}) == 3, f"{path}: an ETag per encoding")
    r = get(path, "gzip", **{"If-None-Match": z.headers["ETag"]})
    check(r.status_code == 304, f"{path}: 304 on the packed ETag")
    r = get(path, "gzip", Range="bytes=0-9")
    check(r.status_code == 206 and "Content-Encoding" not in r.headers and r.raw.read() == body[:10], f"{path}: a Range goes to the plain file")
check(get("/static/js/none.js", "gzip").status_code == 404, "unknown file: 404")
sys.exit(done("p2442_b_static_pack"))
