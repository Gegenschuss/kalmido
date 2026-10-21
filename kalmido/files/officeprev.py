"""2.92.0 C (#1926): the preview and the text of Word (.docx) and Excel (.xlsx) files -- task / comment attachments,
project files and Ablage files.

The file is never parsed in the server process: like the PDF text (tasks/attachtext.py) it goes on stdin into a short-lived
Python process (python -I -c DPV_WORKER, standard library only: zipfile + xml.etree) with a time limit, a memory limit
(RLIMIT_AS), no new processes and no file writes. Before anything is unpacked the worker checks the archive: at most
DPV_ENTRIES entries and DPV_UNZIPPED bytes unpacked in total (the sizes the archive states, and every read is cut at that
budget too -- a zip bomb only ends in "too large"); an XML part with a DOCTYPE / ENTITY is refused (no entity tricks, no
external entities). The worker returns a small JSON model -- never the file's HTML / XML:
  docx: {"type": "docx", "blocks": [{"t": "h", "l": 1-6, "r": runs} | {"t": "p", "r": runs} | {"t": "li", "l": depth,
         "o": 0|1, "r": runs} | {"t": "tbl", "rows": [[cell text, ...], ...]}], "text", "truncated"}
         runs = [{"x": text, "b": 1?, "i": 1?}, ...]
  xlsx: {"type": "xlsx", "sheets": [{"name", "rows": [{"n": row number, "c": [cell text, ...]}], "cols", "truncated"}],
         "sheets_total", "text", "truncated"} (numbers / dates / percent as text, formulas: their stored result)
The client (static/js/docpreview.js) builds its HTML from this model through esc() only. The result is cached per content
(sha256) in the text cache, sealed like the PDF texts. Older .doc / .xls (binary formats) get no preview, only a hint."""
import hashlib
import json
import os
import subprocess
import sys
import time

from flask import jsonify

from ..core.config import app, ATT_DIR
from ..core.i18n import N_, tr
from ..core.db import db, err
from ..core.access import Denied
from ..accounts.session import me
from ..tasks import attachtext as AT

DPV_VER = "1"                 # bump when the model changes (cache key)
DPV_FILE_MB = 20              # larger files get no preview (the download stays)
DPV_UNZIPPED = 60 * 1024 * 1024   # bytes unpacked at most (all parts together)
DPV_ENTRIES = 3000            # archive entries at most
DPV_CHARS = AT.TEXT_CAP       # characters of text at most (the model is cut there too)
DPV_BLOCKS = 4000             # paragraphs / tables of a document at most
DPV_SHEETS, DPV_ROWS, DPV_COLS = 5, 500, 50  # spreadsheet: sheets, rows per sheet, columns per row
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OLD_EXT = {"doc": "doc", "xls": "xls", "ppt": "ppt"}

DPV_WORKER = r"""
import io, json, re, resource, sys, zipfile, zlib
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
def lim(k, v):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
KIND = sys.argv[1]
MEM, CPU, CAP, UNZ, ENTRIES, BLOCKS, SHEETS, ROWS, COLS = (int(x) for x in sys.argv[2:11])
lim(resource.RLIMIT_AS, MEM)
lim(resource.RLIMIT_CPU, CPU)
lim(resource.RLIMIT_FSIZE, 0)
lim(resource.RLIMIT_CORE, 0)
if hasattr(resource, "RLIMIT_NPROC"):
    lim(resource.RLIMIT_NPROC, 0)
data = sys.stdin.buffer.read()

class Stop(Exception):
    pass

def out(o):
    print(json.dumps(o, ensure_ascii=False))
    sys.exit(0)

try:
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
except Exception:
    out({"error": "unreadable"})
if len(infos) > ENTRIES or sum(max(i.file_size, 0) for i in infos) > UNZ:
    out({"error": "too_large"})
NAMES = {i.filename for i in infos}
BUDGET = [0]
DTD = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)

def part(name):
    if name not in NAMES:
        return None
    with z.open(name) as f:
        b = f.read(UNZ - BUDGET[0] + 1)  # the stated size may lie: the read itself is cut at the budget
    BUDGET[0] += len(b)
    if BUDGET[0] > UNZ:
        raise Stop("too_large")
    if DTD.search(b) or b[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in b[:4]:  # 2.148.1 E (#2496): UTF-16 / UTF-32 hide the DOCTYPE from the check
        raise Stop("unsafe")
    return ET.fromstring(b)

def loc(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

def attr(el, name):
    for k, v in el.attrib.items():
        if loc(k) == name:
            return v
    return None

def on(el):  # <w:b/> or <w:b w:val="1|true|on"> = on, "0|false|off|none" = off
    v = attr(el, "val")
    return v is None or v.lower() not in ("0", "false", "off", "none")

class Text:
    def __init__(self):
        self.parts, self.n, self.cut = [], 0, False
    def add(self, s):
        if self.cut:
            return False
        if self.n + len(s) + 1 > CAP:
            self.parts.append(s[:max(CAP - self.n, 0)])
            self.n, self.cut = CAP, True
            return False
        self.parts.append(s)
        self.n += len(s) + 1
        return True
    def text(self):
        return "\n".join(self.parts)

def rels(path):
    d, f = path.rsplit("/", 1) if "/" in path else ("", path)
    root = part(f"{d}/_rels/{f}.rels" if d else f"_rels/{f}.rels")
    res = {}
    for el in (root if root is not None else []):
        t = el.get("Target") or ""
        if el.get("TargetMode") == "External":
            continue
        if t.startswith("/"):
            t = t[1:]
        else:
            segs = (d.split("/") if d else []) + t.split("/")
            st = []
            for s in segs:
                if s == "..":
                    if st:
                        st.pop()
                elif s and s != ".":
                    st.append(s)
            t = "/".join(st)
        res[el.get("Id")] = t
    return res

# ---------------------------------------------------------------- Word
def docx():
    doc = part("word/document.xml")
    if doc is None:
        raise Stop("unreadable")
    levels = {}  # styleId -> heading level (style names stay English in the file: "heading 1", "Title")
    st = part("word/styles.xml")
    for s in (st.iter() if st is not None else []):
        if loc(s.tag) != "style":
            continue
        sid, lv = attr(s, "styleId"), None
        for ch in s.iter():
            if loc(ch.tag) == "name":
                m = re.fullmatch(r"heading\s*(\d)", (attr(ch, "val") or "").strip().lower())
                lv = int(m.group(1)) if m else (1 if (attr(ch, "val") or "").strip().lower() == "title" else lv)
            elif loc(ch.tag) == "outlineLvl" and lv is None and (attr(ch, "val") or "").isdigit() and int(attr(ch, "val")) < 9:
                lv = int(attr(ch, "val")) + 1
        if sid and lv:
            levels[sid] = min(lv, 6)
    ordered = {}  # (numId, ilvl) -> numbered (not bullets)
    nb = part("word/numbering.xml")
    if nb is not None:
        absf = {}
        for a in nb:
            if loc(a.tag) == "abstractNum":
                fm = {}
                for lvl in a:
                    if loc(lvl.tag) == "lvl":
                        f = next((attr(x, "val") for x in lvl if loc(x.tag) == "numFmt"), "bullet")
                        fm[attr(lvl, "ilvl") or "0"] = (f or "bullet") not in ("bullet", "none")
                absf[attr(a, "abstractNumId")] = fm
        for n in nb:
            if loc(n.tag) == "num":
                ref = next((attr(x, "val") for x in n if loc(x.tag) == "abstractNumId"), None)
                for k, v in absf.get(ref, {}).items():
                    ordered[(attr(n, "numId"), k)] = v
    T, blocks = Text(), []

    def runs_of(p):
        rs = []
        def walk(el):
            for ch in el:
                t = loc(ch.tag)
                if t == "r":
                    b = i = False
                    s = []
                    for x in ch:
                        tx = loc(x.tag)
                        if tx == "rPr":
                            for y in x:
                                if loc(y.tag) == "b":
                                    b = on(y)
                                elif loc(y.tag) == "i":
                                    i = on(y)
                        elif tx == "t":
                            s.append(x.text or "")
                        elif tx == "tab":
                            s.append("\t")
                        elif tx in ("br", "cr"):
                            s.append("\n")
                    s = "".join(s)
                    if s:
                        if rs and rs[-1].get("b", 0) == int(b) and rs[-1].get("i", 0) == int(i):
                            rs[-1]["x"] += s
                        else:
                            r = {"x": s}
                            if b:
                                r["b"] = 1
                            if i:
                                r["i"] = 1
                            rs.append(r)
                elif t in ("hyperlink", "ins", "smartTag", "fldSimple", "sdt", "sdtContent", "customXml", "moveTo"):
                    walk(ch)
        walk(p)
        return rs

    def ptext(p):
        return "".join(r["x"] for r in runs_of(p))

    def para(p):
        sid = num = lvl = None
        olv = None
        for x in p:
            if loc(x.tag) == "pPr":
                for y in x:
                    ty = loc(y.tag)
                    if ty == "pStyle":
                        sid = attr(y, "val")
                    elif ty == "outlineLvl" and (attr(y, "val") or "").isdigit() and int(attr(y, "val")) < 9:
                        olv = int(attr(y, "val")) + 1
                    elif ty == "numPr":
                        for w in y:
                            if loc(w.tag) == "numId":
                                num = attr(w, "val")
                            elif loc(w.tag) == "ilvl":
                                lvl = attr(w, "val")
        rs = runs_of(p)
        s = "".join(r["x"] for r in rs)
        if not s.strip():
            return
        hl = levels.get(sid) or (min(olv, 6) if olv else None)
        if hl:
            blocks.append({"t": "h", "l": hl, "r": rs})
            T.add("#" * hl + " " + s)
        elif num and num != "0":
            d = min(int(lvl) if (lvl or "").isdigit() else 0, 8)
            o = ordered.get((num, lvl or "0"), False)
            blocks.append({"t": "li", "l": d, "o": int(o), "r": rs})
            T.add("  " * d + ("1. " if o else "- ") + s)
        else:
            blocks.append({"t": "p", "r": rs})
            T.add(s)

    def table(tb):
        rows = []
        for tr in tb:
            if loc(tr.tag) != "tr":
                continue
            cells = []
            for tc in tr:
                if loc(tc.tag) != "tc":
                    continue
                ps = [ptext(p) for p in tc.iter() if loc(p.tag) == "p"]
                cells.append("\n".join(x for x in ps if x)[:2000])
                if len(cells) >= COLS:
                    break
            rows.append(cells)
            if len(rows) >= ROWS:
                break
        if rows and any(any(x.strip() for x in r) for r in rows):
            blocks.append({"t": "tbl", "rows": rows})
            for r in rows:
                T.add(" | ".join(x.replace("\n", " ") for x in r))

    def body(el):
        for ch in el:
            if T.cut or len(blocks) >= BLOCKS:
                return
            t = loc(ch.tag)
            if t == "p":
                para(ch)
            elif t == "tbl":
                table(ch)
            elif t in ("sdt", "sdtContent", "customXml", "ins", "body"):
                body(ch)
    root = next((x for x in doc if loc(x.tag) == "body"), None)
    if root is not None:
        body(root)
    return {"type": "docx", "blocks": blocks, "text": T.text(), "truncated": T.cut or len(blocks) >= BLOCKS}

# ---------------------------------------------------------------- Excel
DATE_IDS = set(range(14, 23)) | {45, 46, 47}
PCT_IDS = {9, 10}

def is_date_fmt(code):
    s = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", code or "")
    return bool(re.search(r"[dmyhs]", s, re.I)) and not re.search(r"[0#?]", s.split(";")[0] if s else "")

def colno(ref):
    n = 0
    for ch in re.match(r"[A-Z]*", ref or "").group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1

def num_text(v):
    try:
        f = float(v)
    except ValueError:
        return v
    if f != f or f in (float("inf"), float("-inf")):
        return v
    if f.is_integer() and abs(f) < 1e15:
        return str(int(f))
    return format(f, ".15g")

def xlsx():
    wb = part("xl/workbook.xml")
    if wb is None:
        raise Stop("unreadable")
    d1904 = any(loc(x.tag) == "workbookPr" and (attr(x, "date1904") or "").lower() in ("1", "true") for x in wb.iter())
    strings = []
    ss = part("xl/sharedStrings.xml")
    for si in (ss if ss is not None else []):
        if loc(si.tag) == "si":
            skip = {id(t) for r in si if loc(r.tag) == "rPh" for t in r.iter()}
            strings.append("".join(t.text or "" for t in si.iter() if loc(t.tag) == "t" and id(t) not in skip)[:5000])
    kinds = []  # cellXfs index -> "date" | "pct" | ""
    sty = part("xl/styles.xml")
    if sty is not None:
        custom = {}
        for x in sty.iter():
            if loc(x.tag) == "numFmt":
                custom[attr(x, "numFmtId")] = attr(x, "formatCode") or ""
        for x in sty:
            if loc(x.tag) == "cellXfs":
                for xf in x:
                    fid = attr(xf, "numFmtId") or "0"
                    n = int(fid) if fid.isdigit() else 0
                    code = custom.get(fid)
                    if n in DATE_IDS or (code is not None and is_date_fmt(code)):
                        kinds.append("date")
                    elif n in PCT_IDS or (code is not None and "%" in code):
                        kinds.append("pct")
                    else:
                        kinds.append("")
    base = datetime(1904, 1, 1) if d1904 else datetime(1899, 12, 30)

    def date_text(v):
        try:
            f = float(v)
            dt = base + timedelta(days=f)
        except (ValueError, OverflowError):
            return v
        if abs(f - int(f)) < 1e-9:
            return dt.strftime("%Y-%m-%d")
        if f < 1:
            return dt.strftime("%H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")

    wrels = rels("xl/workbook.xml")
    T, sheets, total = Text(), [], 0
    for sh in wb.iter():
        if loc(sh.tag) != "sheet":
            continue
        total += 1
        if len(sheets) >= SHEETS or T.cut:
            continue
        path = wrels.get(attr(sh, "id"))
        if not path or path not in NAMES:
            continue
        name = (sh.get("name") or "")[:100]
        root = part(path)
        rows, cut, width = [], False, 0
        for r in root.iter():
            if loc(r.tag) != "row":
                continue
            if len(rows) >= ROWS:
                cut = True
                break
            n = int(attr(r, "r")) if (attr(r, "r") or "").isdigit() else (rows[-1]["n"] + 1 if rows else 1)
            cells, nxt = [], 0
            for c in r:
                if loc(c.tag) != "c":
                    continue
                ci = colno(c.get("r")) if c.get("r") else nxt
                nxt = ci + 1
                if ci < 0:
                    continue
                if ci >= COLS:
                    cut = True
                    continue
                t, v = c.get("t") or "n", None
                for x in c:
                    if loc(x.tag) == "v":
                        v = x.text or ""
                    elif loc(x.tag) == "is" and t == "inlineStr":
                        v = "".join(y.text or "" for y in x.iter() if loc(y.tag) == "t")
                if v is None:
                    continue
                if t == "s":
                    v = strings[int(v)] if v.isdigit() and int(v) < len(strings) else ""
                elif t == "b":
                    v = "TRUE" if v == "1" else "FALSE"
                elif t == "n":
                    s = c.get("s")
                    k = kinds[int(s)] if s and s.isdigit() and int(s) < len(kinds) else ""
                    if k == "date":
                        v = date_text(v)
                    elif k == "pct":
                        try:
                            v = num_text(repr(round(float(v) * 100, 10))) + " %"
                        except ValueError:
                            pass
                    else:
                        v = num_text(v)
                v = v[:2000]
                while len(cells) < ci:
                    cells.append("")
                cells.append(v)
            while cells and not cells[-1].strip():
                cells.pop()
            if not cells:
                continue
            width = max(width, len(cells))
            rows.append({"n": n, "c": cells})
            if not T.add(" | ".join(x.replace("\n", " ") for x in cells)):
                cut = True
                break
        if rows:
            T.parts.insert(len(T.parts) - len(rows), "## " + name)
        sheets.append({"name": name, "rows": rows, "cols": width, "truncated": cut})
    return {"type": "xlsx", "sheets": sheets, "sheets_total": total, "text": T.text(),
            "truncated": T.cut or total > len(sheets) or any(s["truncated"] for s in sheets)}

try:
    res = docx() if KIND == "docx" else xlsx()
except Stop as e:
    out({"error": str(e)})
except MemoryError:
    out({"error": "too_large"})
except (ET.ParseError, KeyError, ValueError, IndexError, zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError):
    out({"error": "unreadable"})
out(res)
"""

DPV_ERR = {
    "too_large": N_("The file is too large for the preview. Download it to open it."),
    "unsafe": N_("This file contains parts that are not shown for safety. Download it to open it."),
    "unreadable": N_("The file is damaged or not a Word / Excel file and cannot be shown."),
    "too_complex": N_("The file took too long or too much memory to read."),
    "busy": N_("Several files are being read right now, try again in a moment."),
    "encrypted": N_("The file is password-protected and cannot be shown."),
    "old": N_("No preview for the older Office format (.doc / .xls). Download the file to open it."),
    "type": N_("No preview for this kind of file."),
}


def dpv_kind(name, mime, head):
    """'docx' | 'xlsx' (an Office Open XML archive), 'old' (.doc / .xls / .ppt or a password-protected Office file -- an
    OLE container), else None."""
    n, m = (name or "").lower(), (mime or "").lower()
    ole = head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if head[:4] == b"PK\x03\x04":
        if n.endswith((".docx", ".docm")) or m == DOCX_MIME:
            return "docx"
        if n.endswith((".xlsx", ".xlsm")) or m == XLSX_MIME:
            return "xlsx"
        return None
    if ole and (n.endswith((".docx", ".xlsx")) or m in (DOCX_MIME, XLSX_MIME)):
        return "encrypted"  # Office stores a password-protected .docx / .xlsx as an OLE container
    if ole or n.rsplit(".", 1)[-1] in OLD_EXT:
        return "old"
    return None


def dpv_wanted(name, mime):
    """Could this be a Word / Excel file (by name / type, before the bytes are read)?"""
    n, m = (name or "").lower(), (mime or "").lower()
    return n.endswith((".docx", ".docm", ".xlsx", ".xlsm")) or m in (DOCX_MIME, XLSX_MIME)


def dpv_model(data, kind, owner=None):
    """The JSON model of a .docx / .xlsx (bytes) or {error: too_large | unsafe | unreadable | too_complex | busy}. Runs in
    the limited worker (the PDF worker's slots: at most AT.PDF_PARALLEL files, one per account); cached per content."""
    if kind not in ("docx", "xlsx"):
        return {"error": kind if kind in ("old", "encrypted") else "type"}
    if len(data) > DPV_FILE_MB * 1024 * 1024:
        return {"error": "too_large"}
    key = hashlib.sha256(data).hexdigest() + "-dpv" + DPV_VER
    hit = AT._cache_get(key)
    if hit is not None:
        return hit
    if owner is not None:
        with AT._RUN_LOCK:
            if owner in AT._RUNNING:
                return {"error": "busy"}
            AT._RUNNING.add(owner)
    try:
        if not AT._SEM.acquire(timeout=AT.PDF_WAIT):
            return {"error": "busy"}
        clean = False  # only an answer of the worker itself is cached (no timeouts / fork errors)
        try:
            t0 = time.monotonic()
            args = [str(x) for x in (AT.PDF_MEM, AT.PDF_SECONDS, DPV_CHARS, DPV_UNZIPPED, DPV_ENTRIES, DPV_BLOCKS, DPV_SHEETS,
                                     DPV_ROWS, DPV_COLS)]
            try:
                p = subprocess.run([sys.executable, "-I", "-c", DPV_WORKER, kind, *args], input=data, capture_output=True,
                                   timeout=AT.PDF_SECONDS, close_fds=True,
                                   env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
                res = json.loads(p.stdout.decode("utf-8", "replace") or "null") if p.returncode == 0 else None
                clean = isinstance(res, dict)
            except subprocess.TimeoutExpired:
                res = {"error": "too_complex"}
            except (OSError, ValueError):
                res = None
            if not isinstance(res, dict):  # killed by a limit (memory: too large for its budget)
                res = {"error": "too_complex" if time.monotonic() - t0 >= AT.PDF_SECONDS - 1 else "too_large"}
        finally:
            AT._SEM.release()
    finally:
        if owner is not None:
            with AT._RUN_LOCK:
                AT._RUNNING.discard(owner)
    if clean:
        AT._cache_put(key, res)
    return res


def dpv_text(name, mime, data, owner=None):
    """(kind, model) for attachtext.text_of_bytes / the search: kind None when the file is no Word / Excel file."""
    kind = dpv_kind(name, mime, data[:16])
    if kind is None:
        return None, None
    return kind, dpv_model(data, kind, owner)


def _answer(c, name, mime, size, read):
    """The preview answer of one stored file (the caller checked the rights). read() -> plain bytes."""
    if (size or 0) > DPV_FILE_MB * 1024 * 1024:
        return err(tr(DPV_ERR["too_large"]), 413)
    try:
        data = read()
    except (OSError, ValueError):
        return err(tr("File damaged or missing"), 404)
    kind = dpv_kind(name, mime, data[:16])
    if kind is None and data[:5] == b"%PDF-":
        kind = "pdf"
    if kind in (None, "pdf"):
        return err(tr(DPV_ERR["type"]), 415)
    r = dpv_model(data, kind, owner=me())
    if r.get("error"):
        resp = jsonify(error=tr(DPV_ERR.get(r["error"], DPV_ERR["unreadable"])), code=r["error"])
        resp.headers["Cache-Control"] = "no-store"
        if r["error"] == "busy":
            resp.headers["Retry-After"] = "5"
        return resp, 503 if r["error"] == "busy" else 422
    resp = jsonify({"name": name, "size": size, **{k: v for k, v in r.items() if k != "text"}})
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


@app.get("/api/attachments/<int:aid>/preview")
def dpv_attachment_preview(aid):
    """The preview model of a task / comment file (.docx / .xlsx). Same rights as the download (need_attachment: sees the
    task, a live comment, not locked by the virus scan); a file encrypted in the browser has no preview (409)."""
    from ..tasks.attachments import need_attachment
    from ..core.orgcrypt import oc_read_file
    c = db()
    a = need_attachment(c, aid, False)
    if a["enc"]:
        return err(tr("This file is encrypted in the browser: no preview."), 409)
    return _answer(c, a["name"], a["mime"], a["size"], lambda: oc_read_file(c, os.path.join(ATT_DIR, a["path"])))


@app.get("/api/files/nodes/<int:nid>/preview")
def dpv_node_preview(nid):
    """The preview model of an Ablage file (the current version; a link: its original). Rights as the download."""
    from .store import fs_read, need_node
    c = db()
    n = need_node(c, nid)
    if n["kind"] not in ("file", "link"):
        raise Denied(409, tr("Not a file"))
    return _answer(c, n["name"], n["mime"], n["size"], lambda: fs_read(c, nid))


@app.get("/api/list-files/<int:fid>/preview")
def dpv_list_file_preview(fid):
    """The preview model of a project file. Rights as the download (need_list_file)."""
    from ..lists.projects import need_list_file
    from ..core.orgcrypt import oc_read_file
    c = db()
    f = need_list_file(c, fid, False)
    return _answer(c, f["name"], f["mime"], f["size"], lambda: oc_read_file(c, os.path.join(ATT_DIR, f["path"])))


def dpv_agents(c, a):
    """The agents that may summarise attachment row a (the caller checked my read right): active agents of the task's list
    that see the task with its comments and files (task_visible full: never a health / budget list, never outside the
    agent's organisation, within its list limit), that the mention keeps (task_people) -- and only with collaboration
    on, in a list without the browser lock and for a file the server can read. [] = no button."""
    from ..agents.core import agent_active, agent_row, list_agents
    from ..agents.safety import ids_parse
    from ..collab.comments import task_people
    from ..core.access import collab_all, task_visible
    if not collab_all() or a["enc"]:
        return []
    t = c.execute("""SELECT t.id, t.list_id, t.deleted_at, l.org_id, l.life, l.e2e FROM tasks t JOIN lists l ON l.id=t.list_id
                     WHERE t.id=?""", (a["task_id"],)).fetchone()
    if not t or t["deleted_at"] or t["e2e"] is not None or (t["life"] or "") in ("health", "budget"):
        return []
    people = {p["id"]: p["name"] for p in task_people(c, t["list_id"], t["id"])}
    out = []
    for aid in list_agents(c, t["list_id"]):
        ag = agent_row(c, aid)
        if not agent_active(ag) or aid not in people:
            continue
        if ag["list_ids"] and t["list_id"] not in ids_parse(ag["list_ids"]):
            continue
        if ag["org_id"] and t["org_id"] and ag["org_id"] != t["org_id"]:
            continue
        if not task_visible(c, t["id"], aid, full=True):
            continue
        out.append({"id": aid, "name": people[aid], "username": ag["username"]})
    return out


@app.get("/api/attachments/<int:aid>/agents")
def dpv_attachment_agents(aid):
    """2.92.0 C (#1926): who can summarise this file ("Summarise" in the preview): {agents: [{id, name, username}]}. The
    summary itself is a normal comment of the person that mentions the agent (POST /api/tasks/<tid>/comments) -- the
    mention event wakes the agent, it reads the file (GET /api/v1/attachments/<id>/text) and answers as a comment."""
    from ..tasks.attachments import need_attachment
    c = db()
    a = need_attachment(c, aid, False)
    return jsonify(agents=dpv_agents(c, a), task_id=a["task_id"])
