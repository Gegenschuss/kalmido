"""2.432.0 (#3584): the shared file store of the backups -- every larger attachment / office file is kept ONCE (by its
content), however many backups hold it. Standalone (standard library + cryptography only), so the assembler at the end
also runs outside the app (a copy of the store from the off-site target or the Pi):

    python3 -I kalmido/admin/bkstore.py assemble BACKUP STORE OUT [--passphrase-file FILE]

(-I: the folder of the script must not come first on the module path, it holds a module named operator.py.)

Layout below BK_DIR/.store:
  plain/<ab>/<sha256>          the files of unencrypted backups, as they are
  k-<kid>/key.json             the store key of a passphrase: scrypt salt + parameters, a check value (no secret)
  k-<kid>/<ab>/<name>          the files of encrypted backups: name = HMAC(name key, SHA-256 of the content), so the
                               store shows no content hash; content AES-256-GCM in 1 MiB chunks with a key of its own
                               (HMAC(content key, name)), chunk counter, "last chunk" flag and the name authenticated
  refs/<backup name>           one store path per line: what that backup refers to (the clean-up needs no passphrase)
A backup of format 3 (backup.py) holds the database, the manifest and the small files; its manifest lists the shared
files ("shared": [path, size, sha256]) and the store ("store": "plain" or the kid with its salt). Download and restore
take them out of the store again (the download is a complete format-2 file, see assemble()).
Off-site target / Pi copy: the same files flat as kalmido-blob-<kid>-<name> (only encrypted ones leave the server)."""
import base64
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import struct
import sys
import tempfile
import time
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

CHUNK = 1024 * 1024
MAGIC = b"KALMIDO-BACKUP-ENC\x00"     # = backup.BK_MAGIC (the encrypted backup file)
BLOB_MAGIC = b"KALMIDO-BLOB-ENC\x00"  # one encrypted file of the store
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
SHA_RE = re.compile(r"[0-9a-f]{64}")
KID_RE = re.compile(r"[0-9a-f]{16}")
PATH_RE = re.compile(r"(plain|k-[0-9a-f]{16})/([0-9a-f]{2})/([0-9a-f]{64})")
REMOTE_RE = re.compile(r"kalmido-blob-([0-9a-f]{16})-([0-9a-f]{64})")
REFS = "refs"


class StoreError(Exception):
    """code: missing (a shared file is not in the store), hash (damaged), passphrase, format."""

    def __init__(self, code, what=""):
        super().__init__(code)
        self.code, self.what = code, what


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _scrypt(pw, desc):
    return Scrypt(salt=b64u_dec(desc["salt"]), length=32, n=int(desc["n"]), r=int(desc["r"]), p=int(desc["p"])).derive(pw.encode())


def _mac(k, msg):
    return hmac.new(k, msg, hashlib.sha256).digest()


class Key:
    """The store key of one passphrase (kid = its folder)."""

    def __init__(self, desc, master):
        self.kid, self.desc = desc["kid"], {k: desc[k] for k in ("kid", "salt", "n", "r", "p")}
        self._enc, self._name = _mac(master, b"kalmido-store-content"), _mac(master, b"kalmido-store-name")
        self.check = _mac(master, b"kalmido-store-check").hex()

    def name(self, sha):
        return _mac(self._name, bytes.fromhex(sha)).hex()

    def aes(self, name):
        return AESGCM(_mac(self._enc, name.encode()))


def desc_ok(d):
    try:
        return (isinstance(d, dict) and KID_RE.fullmatch(str(d["kid"])) is not None and 2 ** 10 <= int(d["n"]) <= 2 ** 20
                and 1 <= int(d["r"]) <= 16 and 1 <= int(d["p"]) <= 4 and len(b64u_dec(str(d["salt"]))) == 16)
    except (KeyError, ValueError, TypeError):
        return False


def key_from_desc(pw, desc):
    """The key of a backup's manifest entry "store" (restore, download, assembler)."""
    if not desc_ok(desc):
        raise StoreError("format")
    return Key(desc, _scrypt(pw, desc))


def store_key(root, pw):
    """The key of the current passphrase: an existing k-<kid> whose check value matches, else a new one."""
    os.makedirs(root, mode=0o700, exist_ok=True)
    for n in sorted(os.listdir(root)):
        p = os.path.join(root, n, "key.json")
        if not n.startswith("k-") or not os.path.isfile(p):
            continue
        try:
            with open(p) as f:
                d = json.load(f)
            if not desc_ok(d) or "k-" + d["kid"] != n:
                continue
            k = Key(d, _scrypt(pw, d))
        except (OSError, ValueError, KeyError):
            continue
        if hmac.compare_digest(k.check, str(d.get("check") or "")):
            return k
    d = {"v": 1, "kdf": "scrypt", **SCRYPT, "kid": secrets.token_hex(8), "salt": b64u(os.urandom(16))}
    k = Key(d, _scrypt(pw, d))
    os.makedirs(os.path.join(root, "k-" + k.kid), mode=0o700)
    _write_atomic(os.path.join(root, "k-" + k.kid, "key.json"), json.dumps({**d, "check": k.check}).encode())
    return k


def _write_atomic(p, data):
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(p))
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def rel(key, sha):
    """Store path of a file with this SHA-256 (key None = plain)."""
    if key is None:
        return f"plain/{sha[:2]}/{sha}"
    nm = key.name(sha)
    return f"k-{key.kid}/{nm[:2]}/{nm}"


def remote_name(path):
    """Flat name on an off-site target / in a Pi copy (encrypted files only), or None."""
    m = PATH_RE.fullmatch(path or "")
    return f"kalmido-blob-{m.group(1)[2:]}-{m.group(3)}" if m and m.group(1) != "plain" else None


def enc_size(size):
    return len(BLOB_MAGIC) + max(1, -(-size // CHUNK)) * 20 + size


def stored_size(key, size):
    return size if key is None else enc_size(size)


def _aad(name, i, last):
    return hashlib.sha256(BLOB_MAGIC + name.encode()).digest() + struct.pack(">QB", i, 1 if last else 0)


def put(root, key, src, sha, size):
    """Puts the file src (SHA-256 sha, as hashed before) into the store. -> (store path, bytes newly written), or None
    when the file changed meanwhile (the caller hashes it again). An existing store file of the right size stays."""
    p = rel(key, sha)
    full = os.path.join(root, p)
    try:
        if os.path.getsize(full) == stored_size(key, size):  # (its time stays: the Pi copy takes the files of the last days)
            return p, 0
    except OSError:
        pass
    os.makedirs(os.path.dirname(full), mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=root)
    h, n = hashlib.sha256(), 0
    try:
        with open(src, "rb") as f, os.fdopen(fd, "wb") as o:
            if key is None:
                for b in iter(lambda: f.read(CHUNK), b""):
                    h.update(b)
                    n += len(b)
                    o.write(b)
            else:
                nm, i = p.rsplit("/", 1)[1], 0
                aes = key.aes(nm)
                o.write(BLOB_MAGIC)
                cur = f.read(CHUNK)
                while True:
                    nxt = f.read(CHUNK) if cur else b""
                    last = not nxt
                    h.update(cur)
                    n += len(cur)
                    ct = aes.encrypt(struct.pack(">IQ", 0, i), cur, _aad(nm, i, last))
                    o.write(struct.pack(">I", len(ct)) + ct)
                    if last:
                        break
                    i, cur = i + 1, nxt
            o.flush()
            os.fsync(o.fileno())
        if n != size or h.hexdigest() != sha:
            os.remove(tmp)
            return None
        os.chmod(tmp, 0o600)
        os.replace(tmp, full)
        return p, stored_size(key, size)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def find(root, path):
    """Full path of a store file: the store layout, or (a copy from the off-site target / the Pi) the flat name."""
    full = os.path.join(root, path)
    if os.path.isfile(full) and not os.path.islink(full):
        return full
    flat = remote_name(path)
    for cand in ([os.path.join(root, flat)] if flat else []) + [os.path.join(root, path.rsplit("/", 1)[1])]:
        if os.path.isfile(cand) and not os.path.islink(cand):
            return cand
    raise StoreError("missing", path)


def chunks(root, key, sha, size):
    """The plain content of a shared file in chunks; size and SHA-256 are checked (StoreError hash at the end)."""
    p = rel(key, sha)
    full = find(root, p)
    h, n = hashlib.sha256(), 0
    with open(full, "rb") as f:
        if key is None:
            for b in iter(lambda: f.read(CHUNK), b""):
                n += len(b)
                if n > size:
                    raise StoreError("hash", p)
                h.update(b)
                yield b
        else:
            nm = p.rsplit("/", 1)[1]
            aes, i = key.aes(nm), 0
            if f.read(len(BLOB_MAGIC)) != BLOB_MAGIC:
                raise StoreError("hash", p)
            while True:
                ln = f.read(4)
                if len(ln) != 4:
                    raise StoreError("hash", p)  # truncated: the last chunk never came
                ln = struct.unpack(">I", ln)[0]
                if ln > CHUNK + 16:
                    raise StoreError("hash", p)
                ct = f.read(ln)
                pt, last = None, 0
                for last in (0, 1):
                    try:
                        pt = aes.decrypt(struct.pack(">IQ", 0, i), ct, _aad(nm, i, last))
                        break
                    except InvalidTag:
                        continue
                if pt is None:
                    raise StoreError("hash", p)
                n += len(pt)
                if n > size:
                    raise StoreError("hash", p)
                h.update(pt)
                yield pt
                if last:
                    if f.read(1):
                        raise StoreError("hash", p)
                    break
                i += 1
    if n != size or not hmac.compare_digest(h.hexdigest(), sha):
        raise StoreError("hash", p)


# ---- references + clean-up
def lock(root, wait=True):
    """The store's lock across processes (a worker process writes backups, the web process deletes them): a backup holds
    it from its first store file until its reference file is written, the clean-up only runs when it gets it at once.
    -> a handle for unlock(), or None (wait=False and taken)."""
    os.makedirs(root, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(root, ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def unlock(fd):
    if fd is not None:
        os.close(fd)  # (closing releases the flock)


def refs_write(root, backup, paths):
    os.makedirs(os.path.join(root, REFS), mode=0o700, exist_ok=True)
    _write_atomic(os.path.join(root, REFS, backup), ("\n".join(sorted(set(paths))) + "\n").encode())


def refs_read(root, backup):
    """The store paths of a backup, or None (no reference file)."""
    try:
        with open(os.path.join(root, REFS, backup)) as f:
            return {ln for ln in f.read().split() if PATH_RE.fullmatch(ln)}
    except (OSError, ValueError):
        return None


def refs_names(root):
    return {n for n in _ls(os.path.join(root, REFS)) if not n.startswith(".")}


def files(root):
    """{store path: size} of every file in the store."""
    out = {}
    try:
        tops = os.listdir(root)
    except OSError:
        return out
    for top in tops:
        if top != "plain" and not (top.startswith("k-") and KID_RE.fullmatch(top[2:])):
            continue
        for sub in _ls(os.path.join(root, top)):
            d = os.path.join(root, top, sub)
            if len(sub) != 2 or not os.path.isdir(d) or os.path.islink(d):
                continue
            for fn in _ls(d):
                p = f"{top}/{sub}/{fn}"
                if PATH_RE.fullmatch(p):
                    try:
                        out[p] = os.lstat(os.path.join(d, fn)).st_size
                    except OSError:
                        pass
    return out


def _ls(d):
    try:
        return os.listdir(d)
    except OSError:
        return []


def gc(root, needed, keep_refs):
    """Removes every store file not in `needed`, every reference file not in `keep_refs`, emptied folders and
    leftovers of an interrupted write (older than 6 h). -> (files removed, bytes freed)."""
    n = freed = 0
    for p, size in files(root).items():
        if p not in needed:
            try:
                os.remove(os.path.join(root, p))
                n, freed = n + 1, freed + size
            except OSError:
                pass
    for b in refs_names(root) - set(keep_refs):
        try:
            os.remove(os.path.join(root, REFS, b))
        except OSError:
            pass
    for top in _ls(root):
        d = os.path.join(root, top)
        if top.startswith(".tmp-") and os.path.isfile(d) and time.time() - os.path.getmtime(d) > 6 * 3600:
            try:
                os.remove(d)
            except OSError:
                pass
        if top == "plain" or top.startswith("k-"):  # (the key.json of a passphrase stays: cheap, no secret)
            for sub in _ls(d):
                sd = os.path.join(d, sub)
                if len(sub) == 2 and os.path.isdir(sd) and not _ls(sd):
                    try:
                        os.rmdir(sd)
                    except OSError:
                        pass
    return n, freed


def usage(root):
    """(files, bytes) of the store."""
    f = files(root)
    return len(f), sum(f.values())


# ---- writing an archive: plain or encrypted (the format of backup.bk_encrypt), straight into the target
class EncWriter:
    """A file-like object (write / flush / close): the encrypted backup format of backup.bk_encrypt, streamed. The zip
    is written straight into it, so no plain zip lands on the disk first. No tell(): zipfile writes as into a stream."""

    def __init__(self, out, pw, meta, scrypt=None):
        p = scrypt or SCRYPT
        salt = os.urandom(16)
        head = json.dumps({"v": 1, "kdf": "scrypt", **p, "salt": b64u(salt), "chunk": CHUNK, "meta": meta},
                          separators=(",", ":")).encode()
        self.aes = AESGCM(Scrypt(salt=salt, length=32, n=p["n"], r=p["r"], p=p["p"]).derive(pw.encode()))
        self.hh = hashlib.sha256(MAGIC + head).digest()
        self.out, self.buf, self.i, self.closed = out, bytearray(), 0, False
        out.write(MAGIC + struct.pack(">I", len(head)) + head)

    def _emit(self, data, last):
        ct = self.aes.encrypt(struct.pack(">IQ", 0, self.i), bytes(data), self.hh + struct.pack(">QB", self.i, 1 if last else 0))
        self.out.write(struct.pack(">I", len(ct)) + ct)
        self.i += 1

    def write(self, b):
        self.buf += b
        while len(self.buf) > CHUNK:  # the tail stays: the last chunk is only known at close()
            self._emit(self.buf[:CHUNK], False)
            del self.buf[:CHUNK]
        return len(b)

    def flush(self):
        pass

    def close(self):
        if not self.closed:
            self.closed = True
            self._emit(self.buf, True)
            self.buf = bytearray()


class Pipe:
    """A file-like sink whose bytes the download generator takes out (drain) after every step."""

    def __init__(self):
        self.parts = []

    def write(self, b):
        self.parts.append(bytes(b))
        return len(b)

    def flush(self):
        pass

    def drain(self):
        out, self.parts = b"".join(self.parts), []
        return out


def _info(name, size):
    zi = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    zi.compress_type, zi.file_size, zi.external_attr = zipfile.ZIP_STORED, size, 0o600 << 16
    return zi


def assemble(src_zip, man, out, opener):
    """Writes a complete format-2 archive (every file inside, as before 2.432) into the file-like out: the members of the
    format-3 zip src_zip (an open ZipFile) and every shared file of the manifest man from opener(sha, size) (chunks).
    A generator: it yields after every chunk, so a download can pass the bytes on at once."""
    want = {f[0]: f for f in man["files"]}
    z = zipfile.ZipFile(out, "w", allowZip64=True)
    listed = []
    for zi in src_zip.infolist():
        if zi.filename == "manifest.json":
            continue
        with src_zip.open(zi) as f, z.open(_info(zi.filename, zi.file_size), "w", force_zip64=zi.file_size > 2 ** 31) as o:
            for b in iter(lambda: f.read(CHUNK), b""):
                o.write(b)
                yield
        listed.append(want[zi.filename])
    for name, size, sha in man.get("shared") or []:
        with z.open(_info(name, size), "w", force_zip64=size > 2 ** 31) as o:
            for b in opener(sha, size):
                o.write(b)
                yield
        listed.append([name, size, sha])
    m = {k: v for k, v in man.items() if not k.startswith("_") and k not in ("shared", "store", "files")}
    m.update(format_version=2, files=listed, assembled_from=3)
    z.writestr(_info("manifest.json", 0), json.dumps(m, ensure_ascii=False))
    z.close()
    yield


# ---- the assembler outside the app (restore from an off-site / Pi copy)
def decrypt_file(src, dst, pw):
    """An encrypted backup file -> the plain zip (the format of backup.bk_encrypt). -> its header."""
    with open(src, "rb") as f, open(dst, "wb") as o:
        if f.read(len(MAGIC)) != MAGIC:
            raise StoreError("format")
        n = struct.unpack(">I", f.read(4))[0]
        if not 0 < n <= 65536:
            raise StoreError("format")
        raw = f.read(n)
        h = json.loads(raw)
        if h.get("v") != 1 or h.get("kdf") != "scrypt":
            raise StoreError("format")
        aes = AESGCM(_scrypt(pw, h))
        hh, i = hashlib.sha256(MAGIC + raw).digest(), 0
        while True:
            ln = f.read(4)
            if len(ln) != 4:
                raise StoreError("passphrase")
            ct = f.read(struct.unpack(">I", ln)[0])
            pt = last = None
            for last in (0, 1):
                try:
                    pt = aes.decrypt(struct.pack(">IQ", 0, i), ct, hh + struct.pack(">QB", i, last))
                    break
                except InvalidTag:
                    continue
            if pt is None:
                raise StoreError("passphrase")
            o.write(pt)
            if last:
                return h
            i += 1


def main(argv):
    """assemble BACKUP STORE OUT [--passphrase-file FILE]: a complete archive (format 2) for "Restore from a file"."""
    args, pwfile = list(argv), None
    if "--passphrase-file" in args:
        i = args.index("--passphrase-file")
        pwfile = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if len(args) != 4 or args[0] != "assemble" or ("--passphrase-file" in argv and not pwfile):
        print(__doc__.split("\n\n")[1] if "\n\n" in __doc__ else __doc__, file=sys.stderr)
        return 2
    _, src, store, out = args
    pw = ""
    if pwfile:
        with open(pwfile) as f:
            pw = f.read().strip()
    with open(src, "rb") as f:
        enc = f.read(len(MAGIC)) == MAGIC
    work = tempfile.mkdtemp(prefix="kalmido-assemble-")
    try:
        zp, head = src, None
        if enc:
            if not pw:
                print("encrypted backup: --passphrase-file FILE is needed", file=sys.stderr)
                return 2
            zp = os.path.join(work, "archive.zip")
            head = decrypt_file(src, zp, pw)
        with zipfile.ZipFile(zp) as z:
            man = json.loads(z.read("manifest.json"))
            if man.get("format_version") != 3:
                print("not an archive with shared files (format 3): it is complete already", file=sys.stderr)
                return 2
            key = None if man.get("store") == "plain" else key_from_desc(pw, man.get("store"))
            with open(out, "xb") as o:
                sink = EncWriter(o, pw, {**head["meta"], "format_version": 2}) if enc else o
                for _ in assemble(z, man, sink, lambda sha, size: chunks(store, key, sha, size)):
                    pass
                if enc:
                    sink.close()
        print(f"written: {out} ({len(man.get('shared') or [])} shared files taken from the store)")
        return 0
    except StoreError as e:
        print(f"failed: {e.code} {e.what}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
