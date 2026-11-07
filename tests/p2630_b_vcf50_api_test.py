#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.630.0 (#4593): the vCard import takes files up to 50 MB (was 20 MB). A file just above 20 MB is not refused for its
size, a file above 50 MB is (400 with the limit named). The files are made in the test, nothing checked in."""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, done  # noqa: E402

kt.fresh(env={"TASKS_MAX_FILE_MB": "50"})  # the test container runs with 1 MB otherwise
A = kt.setup(lang="en")
BK = A.post(B + "/api/books", json={"name": "Big"}).json()["id"]
MB = 1024 * 1024


def vcf(size):
    head = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:big-1\r\nFN:Anna Muster\r\nN:Muster;Anna;;;\r\nEND:VCARD\r\n"
    return (head + "#" * max(0, size - len(head))).encode()


r = A.post(B + f"/api/books/{BK}/import", files={"file": ("a.vcf", vcf(21 * MB), "text/vcard")})
check("too large" not in r.text, f"#4593: 21 MB is not refused for its size {r.status_code} {r.text[:150]}")
r = A.post(B + f"/api/books/{BK}/import", files={"file": ("b.vcf", vcf(51 * MB), "text/vcard")})
check(r.status_code in (400, 413) and "at most 50 MB" in r.text, f"#4593: 51 MB is refused, limit 50 MB named {r.status_code} {r.text[:150]}")
sys.exit(done("p2630_b_vcf50"))
