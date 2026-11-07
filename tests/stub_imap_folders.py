"""2.581.0 (#4804) test stub, run INSIDE the test container: an IMAP server with folders and flags (127.0.0.1:1145, no TLS,
login kalmido / secret) for the document rules of a workspace mailbox (tests/p2581_d_mailrules_test.py).
/data/mbr/<folder>/<uid>.eml are the mails of a folder (the suite drops them there); the flags of every mail stand in
/data/mbr/flags.json ({"<folder>/<uid>": ["\\Seen", ...]}); /data/mbr/caps = the capabilities (default IMAP4rev1 UIDPLUS
MOVE); every command goes to /data/mbr/imap.log. Only the commands imaplib sends for Kalmido (SELECT, UID SEARCH / FETCH /
STORE / COPY / MOVE / EXPUNGE, EXPUNGE). SEARCH UNSEEN = the mails without \\Seen; any other search = the mails without
\\Deleted (SINCE is the client's own filter).
2.638.0 (#4852): a folder name is read like a real server does - a quoted string (with \\" and \\\\) or a plain atom; an
unquoted name with atom-specials ('{5}' = a literal, '%' / '*' = wildcards, a space, brackets) gets BAD."""
import json
import os
import re
import socketserver
import threading

D = "/data/mbr"
LOCK = threading.Lock()
os.makedirs(os.path.join(D, "INBOX"), exist_ok=True)


def flags():
    try:
        return json.load(open(os.path.join(D, "flags.json")))
    except (FileNotFoundError, ValueError):
        return {}


def save(f):
    tmp = os.path.join(D, "flags.json.tmp")
    json.dump(f, open(tmp, "w"))
    os.replace(tmp, os.path.join(D, "flags.json"))


def uids(folder):
    p = os.path.join(D, folder)
    if not os.path.isdir(p):
        return []
    return sorted(int(m.group(1)) for m in (re.fullmatch(r"(\d+)\.eml", x) for x in os.listdir(p)) if m)


def uidset(s, folder):
    have = uids(folder)
    out = []
    for part in s.split(","):
        if ":" in part:
            a, b = part.split(":")
            lo, hi = int(a), (max(have) if b == "*" and have else int(b))
            out += [u for u in have if lo <= u <= hi]
        elif part.isdigit() and int(part) in have:
            out.append(int(part))
    return out


def mbox(s):
    """The folder name of a command argument (RFC 3501 astring); None = what a real server would not read as that name."""
    s = s.strip()
    if s.startswith('"'):
        m = re.fullmatch(r'"((?:[^"\\]|\\["\\])*)"', s)
        return re.sub(r'\\(["\\])', r"\1", m.group(1)) if m else None
    return None if not s or re.search(r'[(){ %*"\\]', s) else s


def log(line):
    with open(os.path.join(D, "imap.log"), "a") as lg:
        lg.write(line + "\n")


class Imap(socketserver.StreamRequestHandler):
    def w(self, s):
        self.wfile.write(s if isinstance(s, bytes) else s.encode())

    def handle(self):
        try:
            caps = open(os.path.join(D, "caps")).read().strip()
        except FileNotFoundError:
            caps = "IMAP4rev1 UIDPLUS MOVE"
        folder = None
        self.w(f"* OK [CAPABILITY {caps}] stub ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode(errors="replace").strip()
            parts = text.split(" ")
            tag, cmd, args = parts[0], (parts[1].upper() if len(parts) > 1 else ""), parts[2:]
            log(" ".join(([cmd] + args) if cmd != "LOGIN" else [cmd]))
            with LOCK:
                self.one(tag, cmd, args, text, caps, folder)
                if cmd == "SELECT":
                    name = mbox((text.split(" ", 2) + ["", ""])[2])
                    folder = name if name and os.path.isdir(os.path.join(D, name)) else None
                if cmd == "LOGOUT":
                    return

    def one(self, tag, cmd, args, text, caps, folder):
        if cmd == "CAPABILITY":
            self.w(f"* CAPABILITY {caps}\r\n{tag} OK CAPABILITY done\r\n")
        elif cmd == "LOGIN":
            ok = [a.strip('"') for a in args[:2]] == ["kalmido", "secret"]
            self.w(f"{tag} OK LOGIN done\r\n" if ok else f"{tag} NO wrong login\r\n")
        elif cmd == "SELECT":
            name = mbox((text.split(" ", 2) + ["", ""])[2])
            if name is None:
                self.w(f"{tag} BAD not a folder name\r\n")
                return
            if not os.path.isdir(os.path.join(D, name)):
                self.w(f"{tag} NO no such folder\r\n")
                return
            self.w(f"* {len(uids(name))} EXISTS\r\n* 0 RECENT\r\n* FLAGS (\\Seen \\Flagged \\Deleted)\r\n{tag} OK [READ-WRITE] SELECT done\r\n")
        elif cmd == "UID" and folder is None:
            self.w(f"{tag} NO no folder selected\r\n")
        elif cmd == "UID" and args and args[0].upper() == "SEARCH":
            f = flags()
            crit = " ".join(args[1:]).upper()
            ids = [u for u in uids(folder) if ("\\Seen" not in f.get(f"{folder}/{u}", []) if "UNSEEN" in crit
                                               else "\\Deleted" not in f.get(f"{folder}/{u}", []))]
            self.w((f"* SEARCH {' '.join(map(str, ids))}".rstrip() + f"\r\n{tag} OK SEARCH done\r\n"))
        elif cmd == "UID" and args and args[0].upper() == "FETCH":
            what = " ".join(args[2:]).upper()
            out = b""
            for u in uidset(args[1], folder):
                data = open(os.path.join(D, folder, f"{u}.eml"), "rb").read()
                seq = uids(folder).index(u) + 1
                if "HEADER.FIELDS" in what:
                    head = re.split(rb"\r?\n\r?\n", data, maxsplit=1)[0]
                    keep = b"".join(m.group(0) for m in re.finditer(rb"(?im)^(message-id|from|subject|date):[^\n]*\n(?:[ \t][^\n]*\n)*", head + b"\n"))
                    keep += b"\r\n"
                    try:  # /data/mbr/nosize: "<folder>/<uid>" lines whose answer leaves RFC822.SIZE out (a broken server)
                        nos = open(os.path.join(D, "nosize")).read().split()
                    except FileNotFoundError:
                        nos = []
                    size = "" if f"{folder}/{u}" in nos else f" RFC822.SIZE {len(data)}"
                    out += f"* {seq} FETCH (UID {u}{size} BODY[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)] {{{len(keep)}}}\r\n".encode() + keep + b")\r\n"
                elif "RFC822.SIZE" in what:
                    out += f"* {seq} FETCH (UID {u} RFC822.SIZE {len(data)})\r\n".encode()
                else:
                    key = "BODY[]" if "BODY.PEEK[]" in what or "BODY[]" in what else "RFC822"
                    out += f"* {seq} FETCH (UID {u} {key} {{{len(data)}}}\r\n".encode() + data + b")\r\n"
                    if key == "RFC822":  # a plain RFC822 fetch sets \Seen like a real server; BODY.PEEK[] does not
                        f = flags()
                        f.setdefault(f"{folder}/{u}", [])
                        if "\\Seen" not in f[f"{folder}/{u}"]:
                            f[f"{folder}/{u}"].append("\\Seen")
                        save(f)
            self.w(out + f"{tag} OK FETCH done\r\n".encode())
        elif cmd == "UID" and args and args[0].upper() == "STORE":
            f = flags()
            add = re.findall(r"\\\w+", " ".join(args[3:]))
            for u in uidset(args[1], folder):
                cur = f.setdefault(f"{folder}/{u}", [])
                for x in add:
                    if x not in cur:
                        cur.append(x)
                self.w(f"* {uids(folder).index(u) + 1} FETCH (UID {u} FLAGS ({' '.join(cur)}))\r\n")
            save(f)
            self.w(f"{tag} OK STORE done\r\n")
        elif cmd == "UID" and args and args[0].upper() in ("COPY", "MOVE"):
            if args[0].upper() == "MOVE" and "MOVE" not in caps.split():
                self.w(f"{tag} BAD unknown\r\n")
                return
            dest = mbox((text.split(" ", 4) + [""] * 4)[4])
            if dest is None:
                self.w(f"{tag} BAD not a folder name\r\n")
                return
            if not os.path.isdir(os.path.join(D, dest)):
                self.w(f"{tag} NO [TRYCREATE] no such folder\r\n")
                return
            f = flags()
            for u in uidset(args[1], folder):
                nu = (max(uids(dest)) + 1) if uids(dest) else 1
                data = open(os.path.join(D, folder, f"{u}.eml"), "rb").read()
                open(os.path.join(D, dest, f"{nu}.eml"), "wb").write(data)
                f[f"{dest}/{nu}"] = [x for x in f.get(f"{folder}/{u}", []) if x != "\\Deleted"]
                if args[0].upper() == "MOVE":
                    os.remove(os.path.join(D, folder, f"{u}.eml"))
                    f.pop(f"{folder}/{u}", None)
            save(f)
            self.w(f"{tag} OK {args[0].upper()} done\r\n")
        elif cmd == "UID" and args and args[0].upper() == "EXPUNGE":
            f = flags()
            for u in uidset(args[1], folder):
                if "\\Deleted" in f.get(f"{folder}/{u}", []):
                    os.remove(os.path.join(D, folder, f"{u}.eml"))
                    f.pop(f"{folder}/{u}", None)
            save(f)
            self.w(f"{tag} OK EXPUNGE done\r\n")
        elif cmd == "EXPUNGE":
            f = flags()
            for u in uids(folder or ""):
                if "\\Deleted" in f.get(f"{folder}/{u}", []):
                    os.remove(os.path.join(D, folder, f"{u}.eml"))
                    f.pop(f"{folder}/{u}", None)
            save(f)
            self.w(f"{tag} OK EXPUNGE done\r\n")
        elif cmd == "LOGOUT":
            self.w(f"* BYE\r\n{tag} OK LOGOUT done\r\n")
        elif cmd == "NOOP":
            self.w(f"{tag} OK NOOP\r\n")
        else:
            self.w(f"{tag} BAD unknown\r\n")


class TS(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


TS(("127.0.0.1", 1145), Imap).serve_forever()
