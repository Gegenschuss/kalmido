"""2.61.0 (#1818): virus scan of uploads (ClamAV clamd) and the file type from the content.

The scanner: KALMIDO_CLAMD = host:port (TCP, e.g. clamav:3310) or the path of clamd's unix socket; empty / not set = off (small
instances: no scan, no "unchecked" mark, the state is "off"). The bytes go to clamd with zINSTREAM (no new dependency).
A find refuses the upload (UploadRefused). When clamd cannot be reached (or the file is larger than it accepts, KALMIDO_CLAMD_MAX_MB,
like clamd's StreamMaxLength) the upload is taken and remembered as "unchecked" (table upload_scan); after a failed connect the
scanner counts as down for SC_DOWN_S seconds, so not every upload waits for the connect timeout. The watchdog (sc_tick) scans the
unchecked files again as soon as clamd answers: clean = the mark goes; a find = "infected": the file stays stored (a person
decides about deleting it), every way to read it answers 403 (sc_guard) and the uploader gets a News item.

The type from the content (sc_sniff_mime): an executable / HTML / SVG / unknown content with a harmless ending or browser type is
never served inline as an image or PDF (-> application/octet-stream); a picture with the wrong ending gets its real type.
kind / ref_id as in files/upsafe.py; ver = the version of a file of the Ablage (fs_versions.no), 0 for the other kinds."""
import json
import os
import socket
import struct
import time
from datetime import timedelta

from flask import jsonify

from ..core.config import app, ATT_DIR, INLINE_TYPES, OFFICE_DIR
from ..core.i18n import tr
from ..core.db import db, gset, gsetting, iso, iso_ms, now_utc, bump
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions
from ..core.access import Denied  # 2.149.0 G (#2517): pulled up from functions
from ..core.orgcrypt import oc_read_file  # 2.149.0 G (#2517): pulled up from functions
from ..core.env import env_bool

SC_CHUNK = 64 * 1024      # bytes per INSTREAM chunk
SC_CONNECT_S = 3          # connect timeout
SC_DOWN_S = 30            # after a failed connect: "unchecked" without trying, for this long (KALMIDO_CLAMD_DOWN_S)
SC_BATCH = 20             # files per watchdog run (sc_tick)
SC_BUDGET_S = 20          # seconds per watchdog run at most
SC_TICK_S = 60            # at most one run per minute (KALMIDO_CLAMD_TICK_S; the tests use 1)
_SC = {"down_until": 0.0, "tick_at": 0.0, "last_ok": "", "last_err": "", "gc_at": 0.0, "gc_id": 0}


def _env_int(name, default, lo, hi):
    try:
        return max(lo, min(hi, int(os.environ.get(name, "") or default)))
    except ValueError:
        return default


def sc_target():
    """None (off) | ("unix", path) | ("tcp", host, port) from KALMIDO_CLAMD."""
    v = (os.environ.get("KALMIDO_CLAMD") or "").strip()
    if not v or v.lower() in ("0", "off", "no", "false"):
        return None
    if v.startswith("/"):
        return ("unix", v)
    host, _, port = v.rpartition(":")
    if not host:
        host, port = v, "3310"
    try:
        return ("tcp", host.strip("[]"), int(port))
    except ValueError:
        return ("tcp", host.strip("[]"), 3310)


def sc_max_bytes():
    return _env_int("KALMIDO_CLAMD_MAX_MB", 100, 1, 4096) * 1024 * 1024


def _sc_scan_s():
    return _env_int("KALMIDO_CLAMD_TIMEOUT", 60, 5, 600)


def _sc_conn(t):
    if t[0] == "unix":
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(SC_CONNECT_S)
        try:
            s.connect(t[1])
        except OSError:
            s.close()
            raise
        return s
    return socket.create_connection((t[1], t[2]), timeout=SC_CONNECT_S)


def _sc_reply(s):
    buf = b""
    while b"\0" not in buf and len(buf) < 4096:
        part = s.recv(4096)
        if not part:
            break
        buf += part
    return buf.split(b"\0")[0].decode("utf-8", "replace").strip()


def _sc_instream(t, data):
    """clamd's answer to the bytes (e.g. "stream: OK", "stream: Eicar-Signature FOUND", "INSTREAM size limit exceeded. ERROR").
    Raises OSError when clamd cannot be reached / does not answer."""
    end = time.monotonic() + _sc_scan_s()  # 2.61.0 review: one limit for the whole scan, not per socket step

    def left():
        r = end - time.monotonic()
        if r <= 0:
            raise socket.timeout("clamd scan time over")
        return r
    with _sc_conn(t) as s:
        s.settimeout(left())
        s.sendall(b"zINSTREAM\0")
        mv = memoryview(data)
        try:
            for i in range(0, len(mv), SC_CHUNK):
                ch = mv[i:i + SC_CHUNK]
                s.settimeout(left())
                s.sendall(struct.pack("!I", len(ch)) + bytes(ch))
            s.sendall(struct.pack("!I", 0))
        except OSError:  # clamd closes the stream when it is too long: its answer says so
            r = _sc_reply(s)
            if r:
                return r
            raise
        s.settimeout(left())
        return _sc_reply(s)


def sc_parse(reply):
    """("clean", "") | ("found", signature) | ("error", reply)."""
    r = (reply or "").strip()
    body = r.split(":", 1)[1].strip() if r.lower().startswith("stream:") else r
    if body == "OK":
        return "clean", ""
    if body.endswith(" FOUND"):
        return "found", body[:-6].strip()[:200] or "?"
    return "error", r[:200]


def _sc_down(e):
    _SC["down_until"] = time.time() + _env_int("KALMIDO_CLAMD_DOWN_S", SC_DOWN_S, 0, 3600)
    _SC["last_err"] = f"{iso(now_utc())} {type(e).__name__}: {e}"[:300]
    print("virus scanner not reachable:", _SC["last_err"], flush=True)


def sc_ping():
    """True when clamd answers PING (and resets the down mark)."""
    t = sc_target()
    if not t:
        return False
    try:
        with _sc_conn(t) as s:
            s.settimeout(SC_CONNECT_S)
            s.sendall(b"zPING\0")
            ok = _sc_reply(s) == "PONG"
    except OSError as e:
        _sc_down(e)
        return False
    if ok:
        _SC["down_until"] = 0.0
        _SC["last_ok"] = iso(now_utc())
    return ok


# ---------------------------------------------------------------- the type from the content
SC_EXEC = "application/x-executable"


def _sc_magic(data):
    """The type the first bytes show, None when unknown. Executables / scripts -> SC_EXEC, HTML -> text/html, SVG -> image/svg+xml."""
    h = bytes(data[:4096])
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if h.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "image/webp"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis"):
            return "image/heic"
        if brand in (b"mif1", b"msf1"):
            return "image/heif"
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand == b"qt  ":
            return "video/quicktime"
        return "video/mp4"
    i = h.find(b"%PDF-", 0, 1024)
    if i >= 0 and b"<" not in h[:i]:  # 2.61.0 review: "<html>...%PDF-" is a polyglot and no PDF (it stays text/html below)
        return "application/pdf"
    if h[:2] == b"BM" and len(h) >= 26 and h[6:10] == b"\0\0\0\0":
        return "image/bmp"
    if h[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "application/zip"
    if h[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "application/x-ole-storage"
    if h[:4] == b"\x7fELF":
        return SC_EXEC
    if h[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
        return SC_EXEC  # Mach-O (and fat binaries / Java classes)
    if h[:2] == b"MZ" and len(h) >= 64:
        off = struct.unpack("<I", h[60:64])[0]
        if h[off:off + 4] == b"PE\0\0" or b"\0" in h[2:64]:
            return SC_EXEC
    if h[:2] == b"#!":
        return SC_EXEC
    t = h[:1024].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if t.startswith((b"<!doctype html", b"<html", b"<head", b"<body", b"<script", b"<iframe", b"<meta", b"<a ", b"<div", b"<img")):
        return "text/html"
    if t.startswith(b"<svg") or (t.startswith((b"<?xml", b"<!doctype svg")) and b"<svg" in t):
        return "image/svg+xml"
    return None


_SC_SAME = {"image/heif": "image/heic", "image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "image/x-png": "image/png",
            "image/x-ms-bmp": "image/bmp"}


def sc_sniff_mime(name, data, mime):
    """The mime type from the content (magic bytes) when it differs from the declared one, else None. Only what the browser
    would show inline matters: a declared image / PDF must be one (another picture type -> its type, anything else ->
    application/octet-stream, so HTML / SVG / programs never run as a "picture"); an executable never passes as text or picture;
    an undeclared picture / PDF gets its type. Nothing is refused because of its type."""
    if not data:
        return None
    mime = (mime or "").split(";")[0].strip().lower()
    got = _sc_magic(data)
    want = _SC_SAME.get(mime, mime)
    if want in INLINE_TYPES:
        if got and _SC_SAME.get(got, got) == want:
            return None
        return got if got in INLINE_TYPES else "application/octet-stream"
    if got == SC_EXEC and (mime.startswith(("text/", "image/", "audio/", "video/")) or mime == "application/pdf"):
        return "application/octet-stream"
    if got in INLINE_TYPES and mime in ("", "application/octet-stream"):
        return got
    return None


# ---------------------------------------------------------------- the scan of an upload
def sc_scan(name, data):
    """'clean' | 'unchecked' (scanner not reachable / file too large for it) | 'off' (scanner switched off). Raises
    upsafe.UploadRefused on a find."""
    from .upsafe import UploadRefused
    t = sc_target()
    if not t:
        return "off"
    if len(data) > sc_max_bytes() or time.time() < _SC["down_until"]:
        return "unchecked"
    try:
        st, sig = sc_parse(_sc_instream(t, data))
    except OSError as e:
        _sc_down(e)
        return "unchecked"
    if st == "found":
        print(f"upload refused: {sig} found", flush=True)
        raise UploadRefused(tr("{0}: malware found ({1}), not uploaded", name, sig))
    if st == "error":
        print("virus scanner error:", sig, flush=True)
        return "unchecked"
    _SC["last_ok"] = iso(now_utc())
    return "clean"


def _sc_ver(c, kind, ref_id):
    if kind != "fs":
        return 0
    r = c.execute("SELECT cur_version FROM fs_nodes WHERE id=?", (ref_id,)).fetchone()
    return int(r[0] or 0) if r else 0


# 2.190.0 D (#2561): office uploads with their own table (contract files, restaurant bills): kind -> table
SC_OFFICE_KINDS = {"ocf": "office_contract_files", "omf": "office_meal_files"}


def _sc_file(c, kind, ref_id, ver):
    """(name, path relative to ATT_DIR, size) of the stored file, None when it is gone."""
    if kind == "fs":
        r = c.execute("""SELECT n.name, v.path, v.size FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id
                         WHERE v.node_id=? AND v.no=?""", (ref_id, ver)).fetchone()
    elif kind in SC_OFFICE_KINDS:  # 2.190.0 D (#2561): an office upload below its area's folder (absolute path)
        r = c.execute(f"SELECT name, file, size, org_id FROM {SC_OFFICE_KINDS[kind]} WHERE id=?", (ref_id,)).fetchone()
        if not r or not r[1] or os.path.basename(r[1]) != r[1]:
            return None
        return r[0], os.path.join(OFFICE_DIR, str(int(r[3])), r[1]), r[2] or 0
    elif kind == "oar":  # 2.209.0 D (#1856): an archived office PDF (legacy import), sealed below the organisation's folder
        r = c.execute("SELECT file_name, file, bytes, org_id FROM office_archive WHERE id=?", (ref_id,)).fetchone()
        if not r or not r[1] or os.path.basename(r[1]) != r[1]:
            return None
        return r[0] or r[1], os.path.join(OFFICE_DIR, str(int(r[3])), r[1]), r[2] or 0
    else:
        tbl = {"att": "attachments", "list": "list_files", "chat": "chat_files", "wiki": "wiki_files", "sheet": "sheet_files",  # 2.99.0 A (#2182); 2.124.0 B (#2110): + sheet
               "budget": "budget_files", "tchat": "tchat_files"}.get(kind)  # 2.126.0 A (#1979 L1): household receipts; 2.113.1 (#2059): team chat files
        if not tbl:
            return None
        r = c.execute(f"SELECT name, path, size FROM {tbl} WHERE id=?", (ref_id,)).fetchone()
    return (r[0], r[1], r[2] or 0) if r and r[1] else None


def sc_after_store(c, kind, ref_id, org_id, info):
    """Remember an unchecked file for the later scan (the caller commits)."""
    if (info or {}).get("scan") != "unchecked":
        return None
    with system_ctx(c):  # only the mark of the file this request just stored (mail / share intake runs without a person)
        ver = _sc_ver(c, kind, ref_id)
        f = _sc_file(c, kind, ref_id, ver)
        why = "size" if f and f[2] > sc_max_bytes() else ""
        c.execute("""INSERT INTO upload_scan(kind,ref_id,ver,org_id,state,why,created_at) VALUES(?,?,?,?,'unchecked',?,?)
                     ON CONFLICT(kind, ref_id, ver) DO UPDATE SET state='unchecked', why=excluded.why, sig='', tries=0, next_at=NULL""",
                  (kind, int(ref_id), ver, org_id or None, why, iso(now_utc())))
    return None


def sc_copy_mark(c, kind, old_id, new_id, org_id):
    """2.190.0 R (#2496): a stored file copied under a new id keeps the mark of the original (unchecked / infected)."""
    with system_ctx(c):
        c.execute("""INSERT INTO upload_scan(kind,ref_id,ver,org_id,state,sig,why,tries,next_at,created_at,checked_at)
                     SELECT kind, ?, ver, ?, state, sig, why, tries, next_at, created_at, checked_at FROM upload_scan
                     WHERE kind=? AND ref_id=? ON CONFLICT(kind, ref_id, ver) DO NOTHING""",
                  (int(new_id), org_id or None, kind, int(old_id)))


def _sc_rows(c, kind, ids, infected_only=False):
    ids = [int(i) for i in ids if i]
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    cur = "COALESCE((SELECT n.cur_version FROM fs_nodes n WHERE n.id=s.ref_id), 0)" if kind == "fs" else "0"
    st = "s.state='infected'" if infected_only else "s.state IN ('unchecked','infected')"
    # the caller already decided which files the asker sees (ids); the mark of a file is read across organisations so a
    # public link / an agent gets the same answer as the people of the file's organisation
    with system_ctx(c):
        return c.execute(f"SELECT s.ref_id, s.state, s.sig, s.why FROM upload_scan s WHERE s.kind=? AND s.ref_id IN ({q}) "
                         f"AND s.ver={cur} AND {st}", (kind, *ids)).fetchall()


def sc_locked_all(c, org_id=None):
    """2.209.0 D (#1856): {(kind, ref_id, ver): signature} of the locked (infected) files for the exports, which leave them
    out and list them; org_id: also {office file name: (kind, id, signature)} of that office's folder under key "office"."""
    out = {(r[0], int(r[1]), int(r[2])): r[3] or "" for r in c.execute("SELECT kind, ref_id, ver, sig FROM upload_scan WHERE state='infected'")}
    if org_id is not None:
        off, sig = {}, {}
        for k, v in out.items():  # 2.306.0 D3 (#2875): an office file has no versions -- any row of it counts (no KeyError)
            sig.setdefault(k[:2], v)
        for kind, tbl in (*SC_OFFICE_KINDS.items(), ("oar", "office_archive")):
            ids = sorted({k[1] for k in out if k[0] == kind})
            if ids:
                q = ",".join("?" * len(ids))
                for r in c.execute(f"SELECT id, file FROM {tbl} WHERE org_id=? AND id IN ({q})", (int(org_id), *ids)):
                    if r[1]:
                        off[r[1]] = (kind, int(r[0]), out.get((kind, int(r[0]), 0), sig[(kind, int(r[0]))]))
        out["office"] = off
    return out


def sc_marks(c, kind, ids):
    """{id: {"scan": "unchecked"|"infected", "sig"?: signature, "scan_why"?: "size"}} for the files of `kind` with such a state.
    Scanner off: only "infected" (unchecked is no fault then)."""
    out = {}
    for r in _sc_rows(c, kind, ids, infected_only=sc_target() is None):
        m = {"scan": r["state"]}
        if r["state"] == "infected":
            m["sig"] = r["sig"]
        elif r["why"]:
            m["scan_why"] = r["why"]
        out[r["ref_id"]] = m
    return out


def sc_up(c, kind, items, key="id"):
    """Adds the marks of files/upsafe.up_marks as `up` to the dicts in items (only where a file has one). Returns items."""
    from .upsafe import up_marks
    if not items:
        return items
    marks = up_marks(c, kind, [x.get(key) for x in items])
    if marks:
        for x in items:
            m = marks.get(x.get(key))
            if m:
                x["up"] = m
    return items


def sc_strict():
    """2.79.0 (#476 M7): strict mode = a file the scanner could not check yet (scanner down, error) is locked like an
    infected one until the later scan finds it clean (a file too large for the scanner keeps its mark only). KALMIDO_CLAMD_STRICT=1 / 0; not set = on whenever a
    scanner is configured (KALMIDO_CLAMD). Off = the behaviour of 2.61-2.78: unchecked files stay readable, with their mark."""
    v = (os.environ.get("KALMIDO_CLAMD_STRICT") or "").strip().lower()
    if v in ("0", "off", "no", "false"):
        return False
    return sc_target() is not None


def _sc_state_row(c, kind, ref_id, ver, state, more=""):
    if kind == "fs":
        cur, args = ("?", (int(ver),)) if ver else ("COALESCE((SELECT cur_version FROM fs_nodes WHERE id=?), 0)", (int(ref_id),))
    else:
        cur, args = "0", ()
    with system_ctx(c):  # a public link / an agent sees the lock like everyone (the caller checked the read right)
        return c.execute(f"SELECT sig FROM upload_scan WHERE kind=? AND ref_id=? AND state=? AND ver={cur} {more}",
                         (kind, int(ref_id), state, *args)).fetchone()


def sc_locked(c, kind, ref_id, ver=None):
    """The signature when the file (fs: version ver, default the current one) was found infected, else None."""
    if not ref_id:
        return None
    r = _sc_state_row(c, kind, ref_id, ver, "infected")
    return (r[0] or "?") if r else None


def sc_waiting(c, kind, ref_id, ver=None):
    """2.79.0 (#476 M7): True when strict mode holds this file back because it is not checked yet. A file too large for
    the scanner (why 'size') is never scanned later, so it stays readable with its mark (else it would be locked for good)."""
    if not ref_id or not sc_strict():
        return False
    r = _sc_state_row(c, kind, ref_id, ver, "unchecked", "AND why=''")
    return bool(r)


def sc_guard(c, kind, ref_id, ver=None):
    """Raises Denied(403) when the file was found infected (or, strict mode, is not checked yet): no download, no preview,
    no text. Deleting it stays possible (write paths do not call this)."""
    sig = sc_locked(c, kind, ref_id, ver)
    if sig:
        raise Denied(403, tr("Locked: malware was found in this file ({0})", sig))
    if sc_waiting(c, kind, ref_id, ver):
        raise Denied(403, tr("Not checked for malware yet: the file can be opened once the virus scanner has checked it"))


# ---------------------------------------------------------------- the later scan (watchdog)
def _sc_uploader(c, kind, ref_id, ver):
    """(person to tell, task_id, list_id) of a stored file; an agent's upload goes to the agent's owner."""
    if kind == "att":
        r = c.execute("SELECT user_id, task_id FROM attachments WHERE id=?", (ref_id,)).fetchone()
        uid, tid, lid = (r[0], r[1], None) if r else (None, None, None)
    elif kind == "list":
        r = c.execute("SELECT user_id, list_id FROM list_files WHERE id=?", (ref_id,)).fetchone()
        uid, tid, lid = (r[0], None, r[1]) if r else (None, None, None)
    elif kind == "fs":
        r = c.execute("""SELECT COALESCE(v.created_by, n.created_by) FROM fs_nodes n LEFT JOIN fs_versions v ON v.node_id=n.id AND v.no=?
                         WHERE n.id=?""", (ver, ref_id)).fetchone()
        uid, tid, lid = (r[0] if r else None), None, None
    elif kind == "budget":  # 2.126.0 A (#1979 L1): a household receipt -- who stored it, its list
        r = c.execute("SELECT user_id, list_id FROM budget_files WHERE id=?", (ref_id,)).fetchone()
        uid, tid, lid = (r[0], None, r[1]) if r else (None, None, None)
    elif kind in ("wiki", "sheet"):  # 2.99.0 A (#2182): a knowledge page's file -- who stored it; 2.124.0 B (#2110): a table's file
        r = c.execute(f"SELECT created_by FROM {'wiki_files' if kind == 'wiki' else 'sheet_files'} WHERE id=?", (ref_id,)).fetchone()
        uid, tid, lid = (r[0] if r else None), None, None
    elif kind in SC_OFFICE_KINDS or kind == "oar":  # 2.190.0 D (#2561): an office upload: who stored it; 2.209.0 D (#1856): + archive
        r = c.execute(f"SELECT created_by FROM {SC_OFFICE_KINDS.get(kind, 'office_archive')} WHERE id=?", (ref_id,)).fetchone()
        uid, tid, lid = (r[0] if r else None), None, None
    elif kind == "tchat":  # 2.113.1 (#2059): a team chat file: its uploader
        r = c.execute("SELECT user_id FROM tchat_files WHERE id=?", (ref_id,)).fetchone()
        uid, tid, lid = (r[0] if r else None), None, None
    else:  # chat: the person of the conversation
        r = c.execute("SELECT m.user_id FROM chat_files f JOIN agent_chat m ON m.id=f.message_id WHERE f.id=?", (ref_id,)).fetchone()
        uid, tid, lid = (r[0] if r else None), None, None
    if uid:
        a = c.execute("SELECT a.owner_id FROM agents a JOIN users u ON u.id=a.user_id WHERE a.user_id=? AND u.kind='agent'", (uid,)).fetchone()
        if a:
            uid = a[0]
    return uid, tid, lid


def _sc_tell(c, kind, ref_id, ver, name, sig):
    """The News item "malware found" for the uploader (no push: the News feed only)."""
    uid, tid, lid = _sc_uploader(c, kind, ref_id, ver)
    if not uid:
        return
    c.execute("INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (uid, "upscan", tid, lid, None, None,
               json.dumps({"name": name, "sig": sig, "where": kind, "ref": ref_id, "ver": ver}, ensure_ascii=False), iso_ms(now_utc())))


def sc_news_live(c, data):
    """2.61.0 (#1818): a News item "upscan" shows while its file is still locked."""
    try:
        d = json.loads(data or "{}")
        kind, ref, ver = d.get("where"), int(d.get("ref") or 0), int(d.get("ver") or 0)
    except (ValueError, TypeError, AttributeError):
        return False
    with system_ctx(c):  # the person's own upload (any organisation); only "is it still locked"
        return bool(c.execute("SELECT 1 FROM upload_scan WHERE kind=? AND ref_id=? AND ver=? AND state='infected'",
                              (kind, ref, ver)).fetchone())


def _sc_gc(c):
    """2.61.0 review: the rows of deleted files go (every state, also with the scanner off): 200 rows every 10 minutes,
    walking through the table by id."""
    if time.time() - _SC["gc_at"] < 600:
        return
    _SC["gc_at"] = time.time()
    with system_ctx(c):
        rows = c.execute("SELECT id, kind, ref_id, ver FROM upload_scan WHERE id>? ORDER BY id LIMIT 200",
                         (_SC["gc_id"],)).fetchall()
        for r in rows:
            if not _sc_file(c, r["kind"], r["ref_id"], r["ver"]):
                c.execute("DELETE FROM upload_scan WHERE id=?", (r["id"],))
    _SC["gc_id"] = rows[-1]["id"] if len(rows) == 200 else 0
    c.commit()


# 2.209.0 D (#1856): files stored before the type check (sc_sniff_mime) get the type their content shows, once, a few per
# minute, the newest first (KALMIDO_MIME_SWEEP=off = off). Only the type column changes; the file and its name stay.
SC_MIME_KEY = "sc_mime_sweep"  # settings: {kind: lowest id done, "done": [kinds]}
SC_MIME_SQL = {"att": ("attachments", "SELECT id, name, mime, path, size FROM attachments WHERE id < ? AND enc=0 ORDER BY id DESC LIMIT ?"),
               "list": ("list_files", "SELECT id, name, mime, path, size FROM list_files WHERE id < ? ORDER BY id DESC LIMIT ?"),
               "fs": ("fs_versions", "SELECT v.id, n.name, v.mime, v.path, v.size, v.node_id, v.no, n.cur_version FROM fs_versions v "
                      "JOIN fs_nodes n ON n.id=v.node_id WHERE v.id < ? ORDER BY v.id DESC LIMIT ?")}


SC_MIME_BYTES = 64 * 1024 * 1024  # 2.209.0 review (#1856): bytes one step of the type check reads at most


def sc_mime_sweep(c, n=20, force=False):
    """One step of the type check of older files; returns how many types were corrected (the caller's watchdog commits)."""
    if not env_bool("KALMIDO_MIME_SWEEP", True) or (not force and time.time() - _SC.get("mime_at", 0.0) < 60):
        return 0
    _SC["mime_at"] = time.time()
    try:
        st = json.loads(gsetting(c, SC_MIME_KEY) or "{}")
    except ValueError:
        st = {}
    done, fixed = set(st.get("done") or []), 0
    kind = next((k for k in SC_MIME_SQL if k not in done), None)
    if not kind:
        return 0
    tbl, sql = SC_MIME_SQL[kind]
    with system_ctx(c):  # older files of every workspace: only their type column, nothing handed to a person
        rows = c.execute(sql, (int(st.get(kind) or 2 ** 62), n)).fetchall()
        last, spent = None, 0
        for r in rows:
            if spent > SC_MIME_BYTES:  # a minute's step reads at most ~64 MB; the rest follows in the next step
                break
            last, data = r, None
            if r["path"] and (r["size"] or 0) <= sc_max_bytes():
                spent += r["size"] or 0
                try:
                    data = oc_read_file(c, os.path.join(ATT_DIR, r["path"]))
                except Exception:  # noqa: BLE001 - a missing / unreadable file keeps its type
                    data = None
            got = sc_sniff_mime(r["name"], data, r["mime"]) if data else None
            if got:
                c.execute(f"UPDATE {tbl} SET mime=? WHERE id=?", (got, r["id"]))
                if kind == "fs" and r["no"] == r["cur_version"]:
                    c.execute("UPDATE fs_nodes SET mime=? WHERE id=?", (got, r["node_id"]))
                print(f"type check: {kind} {r['id']} {r['mime'] or '-'} -> {got}", flush=True)
                fixed += 1
        if len(rows) < n and last is (rows[-1] if rows else None):
            done.add(kind)
        elif last is not None:
            st[kind] = last["id"]
        st["done"] = sorted(done)
        gset(c, SC_MIME_KEY, json.dumps(st, separators=(",", ":")))
    return fixed


def sc_tick(c, force=False):
    """Watchdog: scans up to SC_BATCH unchecked files (oldest first, at most SC_BUDGET_S seconds) while clamd answers.
    Returns the number of files checked."""
    _sc_gc(c)
    try:
        sc_mime_sweep(c)  # 2.209.0 D (#1856)
        c.commit()
    except Exception as e:  # noqa: BLE001 - the type check never stops the scan
        c.rollback()
        print("type check:", type(e).__name__, flush=True)
    t = sc_target()
    if not t or (not force and time.time() - _SC["tick_at"] < _env_int("KALMIDO_CLAMD_TICK_S", SC_TICK_S, 1, 3600)):
        return 0
    _SC["tick_at"] = time.time()
    now = iso(now_utc())
    with system_ctx(c):  # the unchecked files of every organisation (the scan reads them, nobody gets their content)
        rows = c.execute("""SELECT * FROM upload_scan WHERE state='unchecked' AND why='' AND (next_at IS NULL OR next_at<=?)
                            ORDER BY id LIMIT ?""", (now, SC_BATCH)).fetchall()
        gone = c.execute("SELECT id, kind, ref_id, ver FROM upload_scan WHERE state='infected' ORDER BY checked_at LIMIT 50").fetchall()
        n, changed, t0 = 0, False, time.time()
        for r in gone:  # a locked file somebody deleted: its row goes too
            if not _sc_file(c, r["kind"], r["ref_id"], r["ver"]):
                c.execute("DELETE FROM upload_scan WHERE id=?", (r["id"],))
        if rows and sc_ping():
            for r in rows:
                if time.time() - t0 > SC_BUDGET_S:
                    break
                f = _sc_file(c, r["kind"], r["ref_id"], r["ver"])
                if not f:
                    c.execute("DELETE FROM upload_scan WHERE id=?", (r["id"],))
                    continue
                if f[2] > sc_max_bytes():
                    c.execute("UPDATE upload_scan SET why='size' WHERE id=?", (r["id"],))
                    continue
                try:
                    data = oc_read_file(c, os.path.join(ATT_DIR, f[1]))  # sealed files decrypted
                except Exception as e:  # noqa: BLE001 - a missing / unreadable file: try again later
                    print("virus scan: file not readable", r["kind"], r["ref_id"], type(e).__name__, flush=True)
                    data = None
                try:
                    st, sig = sc_parse(_sc_instream(t, data)) if data is not None else ("error", "")
                except OSError as e:
                    _sc_down(e)
                    break
                n += 1
                if st == "clean":
                    c.execute("DELETE FROM upload_scan WHERE id=?", (r["id"],))
                    changed = True
                elif st == "found":
                    c.execute("UPDATE upload_scan SET state='infected', sig=?, checked_at=? WHERE id=?", (sig, iso(now_utc()), r["id"]))
                    _sc_tell(c, r["kind"], r["ref_id"], r["ver"], f[0], sig)
                    from .textscan import ts_forget  # the recognised text of a locked file is never searchable
                    ts_forget(c, r["kind"], r["ref_id"])
                    changed = True
                    print(f"virus scan: {sig} found in a stored file ({r['kind']} {r['ref_id']}), locked", flush=True)
                else:  # clamd could not scan it: again later, waiting longer each time (at most a day)
                    tries = (r["tries"] or 0) + 1
                    nxt = iso(now_utc() + timedelta(hours=min(24, 2 ** min(tries, 5))))
                    c.execute("UPDATE upload_scan SET tries=?, next_at=? WHERE id=?", (tries, nxt, r["id"]))
                if r["kind"] == "att" and st in ("clean", "found"):  # the task's files changed: the app reloads it (delta)
                    tk = c.execute("SELECT task_id FROM attachments WHERE id=?", (r["ref_id"],)).fetchone()
                    if tk:
                        c.execute("INSERT INTO dl_changes(task_id) VALUES(?)", (tk[0],))
        if changed:
            bump(c)
    c.commit()
    return n


# ---------------------------------------------------------------- Settings > Users > Whole server: the scanner's state
@app.get("/api/admin/upload-scan")
def sc_admin_state():
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    t = sc_target()
    with system_ctx(c):  # counts over every organisation for the server admin (no content)
        cnt = {r[0]: r[1] for r in c.execute("SELECT state, COUNT(*) FROM upload_scan GROUP BY state")}
    state = "off" if not t else ("ok" if sc_ping() else "down")
    return jsonify(state=state, unchecked=cnt.get("unchecked", 0) if t else 0, infected=cnt.get("infected", 0),
                   strict=bool(t) and sc_strict(),  # 2.79.0 (#476 M7)
                   max_mb=sc_max_bytes() // (1024 * 1024), last_ok=_SC["last_ok"], last_error=_SC["last_err"] if state == "down" else "")
