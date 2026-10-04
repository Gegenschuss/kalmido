"""2.17.0 (#443) test stubs, run INSIDE the test container: a tiny IMAP server (127.0.0.1:1143, no TLS) that serves the
files /data/mail/in/<uid>.eml as the INBOX (\\Seen remembered in /data/mail/seen), and an SMTP sink (127.0.0.1:1025)
that appends every mail to /data/mail/out.jsonl. Only the commands imaplib / smtplib use for Kalmido."""
import json, os, re, socketserver, threading

D = "/data/mail"
os.makedirs(os.path.join(D, "in"), exist_ok=True)


def msgs():
    out = []
    for f in os.listdir(os.path.join(D, "in")):
        m = re.fullmatch(r"(\d+)\.eml", f)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def seen():
    try:
        return {int(x) for x in open(os.path.join(D, "seen")).read().split()}
    except FileNotFoundError:
        return set()


class Imap(socketserver.StreamRequestHandler):
    def w(self, s):
        self.wfile.write(s if isinstance(s, bytes) else s.encode())

    def handle(self):
        with open(os.path.join(D, "imap.log"), "a") as lg:
            lg.write("connect\n")
        self.w("* OK IMAP4rev1 stub ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            parts = [x[1:-1] if len(x) > 1 and x[0] == x[-1] == '"' else x for x in line.decode(errors="replace").strip().split(" ")]
            tag, cmd, args = parts[0], (parts[1].upper() if len(parts) > 1 else ""), parts[2:]
            with open(os.path.join(D, "imap.log"), "a") as lg:
                lg.write(" ".join(parts[1:2] + args[:2]) + "\n")
            if cmd == "CAPABILITY":
                self.w(f"* CAPABILITY IMAP4rev1\r\n{tag} OK CAPABILITY done\r\n")
            elif cmd == "LOGIN":
                ok = args[:2] == ["kalmido", "secret"]
                self.w(f"{tag} OK LOGIN done\r\n" if ok else f"{tag} NO wrong login\r\n")
            elif cmd == "SELECT":
                self.w(f"* {len(msgs())} EXISTS\r\n* 0 RECENT\r\n* FLAGS (\\Seen)\r\n{tag} OK [READ-WRITE] SELECT done\r\n")
            elif cmd == "UID" and args and args[0].upper() == "SEARCH":
                ids = [u for u in msgs() if u not in seen()]
                self.w(f"* SEARCH {' '.join(map(str, ids))}\r\n{tag} OK SEARCH done\r\n".replace("SEARCH \r\n", "SEARCH\r\n"))
            elif cmd == "UID" and args and args[0].upper() == "FETCH":
                u = int(args[1])
                data = open(os.path.join(D, "in", f"{u}.eml"), "rb").read()
                seq = msgs().index(u) + 1
                self.w(f"* {seq} FETCH (UID {u} RFC822 {{{len(data)}}}\r\n".encode() + data + b")\r\n" + f"{tag} OK FETCH done\r\n".encode())
            elif cmd == "UID" and args and args[0].upper() == "STORE":
                u = int(args[1])
                with open(os.path.join(D, "seen"), "a") as f:
                    f.write(f"{u}\n")
                self.w(f"* {msgs().index(u) + 1} FETCH (UID {u} FLAGS (\\Seen))\r\n{tag} OK STORE done\r\n")
            elif cmd == "LOGOUT":
                self.w(f"* BYE\r\n{tag} OK LOGOUT done\r\n")
                return
            elif cmd == "NOOP":
                self.w(f"{tag} OK NOOP\r\n")
            else:
                self.w(f"{tag} BAD unknown\r\n")


class Smtp(socketserver.StreamRequestHandler):
    def w(self, s):
        self.wfile.write(s.encode())

    def handle(self):
        self.w("220 stub ESMTP\r\n")
        frm, to = "", []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            s = line.decode(errors="replace").strip()
            u = s.upper()
            if u.startswith(("EHLO", "HELO")):
                self.w("250-stub\r\n250 8BITMIME\r\n")
            elif u.startswith("MAIL FROM"):
                frm = s.split(":", 1)[1].strip(" <>")
                self.w("250 OK\r\n")
            elif u.startswith("RCPT TO"):
                to.append(s.split(":", 1)[1].strip(" <>"))
                self.w("250 OK\r\n")
            elif u == "DATA":
                self.w("354 go\r\n")
                buf = []
                while True:
                    ln = self.rfile.readline()
                    if not ln or ln in (b".\r\n", b".\n"):
                        break
                    buf.append(ln)
                with open(os.path.join(D, "out.jsonl"), "a") as f:
                    f.write(json.dumps({"from": frm, "to": to, "raw": b"".join(buf).decode(errors="replace")}) + "\n")
                frm, to = "", []
                self.w("250 queued\r\n")
            elif u == "QUIT":
                self.w("221 bye\r\n")
                return
            else:
                self.w("250 OK\r\n")


class TS(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


threading.Thread(target=TS(("127.0.0.1", 1025), Smtp).serve_forever, daemon=True).start()
TS(("127.0.0.1", 1143), Imap).serve_forever()
