#!/usr/bin/env python3
"""2.61.0 (#1818): a tiny stand-in for ClamAV's clamd for the tests (runs INSIDE the test container, docker exec -d).
Speaks zPING / zINSTREAM on 127.0.0.1:3310 and reports the EICAR test string as FOUND, everything else as OK.
The file /data/clamd.off makes it stop (the scanner "goes away"); start it again with docker exec -d.
usage: python fake_clamd.py [port]"""
import os
import socket
import struct
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3310
OFF = "/data/clamd.off"
# the EICAR test string, assembled here so this file itself never carries it
EICAR = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*").encode()


def read_exact(c, n):
    b = b""
    while len(b) < n:
        p = c.recv(n - len(b))
        if not p:
            raise ConnectionError("closed")
        b += p
    return b


def serve(c):
    cmd = b""
    while not cmd.endswith(b"\0"):
        p = c.recv(1)
        if not p:
            return
        cmd += p
    cmd = cmd[:-1]
    if cmd in (b"zPING", b"nPING"):
        c.sendall(b"PONG\0")
        return
    if cmd not in (b"zINSTREAM", b"nINSTREAM"):
        c.sendall(b"UNKNOWN COMMAND\0")
        return
    data = b""
    while True:
        n = struct.unpack("!I", read_exact(c, 4))[0]
        if not n:
            break
        data += read_exact(c, n)
    c.sendall(b"stream: Eicar-Test-Signature FOUND\0" if EICAR in data else b"stream: OK\0")


s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", PORT))
s.listen(8)
s.settimeout(0.2)
while not os.path.exists(OFF):
    try:
        c, _ = s.accept()
    except socket.timeout:
        continue
    with c:
        c.settimeout(10)
        try:
            serve(c)
        except (OSError, ConnectionError, struct.error):
            pass
s.close()
