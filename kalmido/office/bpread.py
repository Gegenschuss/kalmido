"""2.120.0 E (#2091): a small PDF reader for the own letterhead (office.letterhead), written without any PDF library.

It reads just what is needed to put the pages of an uploaded letterhead PDF behind the pages of an office document:
the cross-reference (classic tables, xref streams with PNG predictors, incremental updates through /Prev, hybrid files
with /XRefStm, a rebuild by scanning "n g obj" when the table is broken), object streams, the page tree with inherited
/Resources and /MediaBox, and the content streams (FlateDecode, ASCIIHex, ASCII85 or none). bp_emit_form copies one page
as a form XObject into the objects of office.pdf.pdf_write: the content decoded and compressed again, every object
reachable from its /Resources (fonts with their programs, images, graphics states, colour spaces, patterns, nested
forms) renumbered and copied byte for byte (streams keep their own filters). Strings, names and numbers are written back
as they were read (raw tokens), so nothing is re-encoded.

Everything that cannot be read safely raises BpError: an encrypted file, an unknown filter of a content stream, a
broken object, too many objects, no page. The upload route turns that into a 400; a document PDF is never written from
a half read letterhead. Nothing here reads the database."""
import base64
import re
import time
import zlib

BP_MAX_OBJECTS = 20000       # objects copied for one letterhead (fonts, images, ...)
BP_MAX_DEPTH = 64            # nesting of arrays / dictionaries in one object
BP_MAX_DECODED = 16 * 1024 * 1024  # one decoded stream (2.120.0 review H1: was 64 MB)
BP_MAX_DOC_DECODED = 48 * 1024 * 1024  # 2.120.0 review H1: all decoded streams of one document together (zlib bombs)
BP_MAX_PREDICTED = 4 * 1024 * 1024  # PNG predictors (xref / object streams only) run in pure Python: small
BP_MAX_CONTENTS = 64  # content streams of one page
BP_MAX_REF_DEPTH = 32  # 2.148.1 D (#2485): references resolved inside each other (object streams, lengths)
BP_MAX_SECONDS = 10  # 2.148.1 D (#2485): reading one document's objects

_WS = b"\x00\t\n\x0c\r "
_DELIM = b"()<>[]{}/%"
_REG_END = set(_WS + _DELIM)
_NUM_RE = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
_INT_RE = re.compile(rb"\d+")


class BpError(ValueError):
    """The PDF cannot be used as a letterhead (the text is for the log, the user sees one plain sentence)."""


class BpName(bytes):
    """A name without its slash, raw (with #xx escapes as in the file)."""


class BpStr(bytes):
    """A string token as in the file, with its delimiters: (literal) or <hex>."""


class BpNum:
    """A number with its raw token (written back unchanged) and its value."""
    __slots__ = ("raw", "v")

    def __init__(self, raw):
        self.raw = raw
        self.v = float(raw) if (b"." in raw) else int(raw)


class BpRef:
    __slots__ = ("num", "gen")

    def __init__(self, num, gen=0):
        self.num = num
        self.gen = gen


class BpStream:
    """A stream: its dictionary and the raw (still filtered) data."""
    __slots__ = ("d", "data")

    def __init__(self, d, data):
        self.d = d
        self.data = data


def bp_num(v, default=0.0):
    return v.v if isinstance(v, BpNum) else default


class BpDoc:
    """A parsed PDF: objects are read lazily by number (bp_obj), the pages through the page tree (pages)."""

    def __init__(self, data):
        if not isinstance(data, (bytes, bytearray)) or b"%PDF-" not in bytes(data[:1024]):
            raise BpError("not a PDF")
        self.b = bytes(data)
        self.xref = {}       # num -> ("o", offset) | ("s", objstm num, index)
        self.trailer = {}
        self._cache = {}
        self._objstm = {}
        self.decoded = 0  # 2.120.0 review H1: bytes decoded so far (bp_decode, budget BP_MAX_DOC_DECODED)
        self._end, self._depth = time.monotonic() + BP_MAX_SECONDS, 0  # 2.148.1 D (#2485)
        try:
            self._read_xref()
        except BpError:
            raise
        except Exception as e:  # noqa: BLE001 (any parsing trouble: rebuild from the objects)
            self.xref, self.trailer = {}, {}
            self._rebuild(str(e))
        if not self.trailer.get(b"Root"):
            self._rebuild("no root")
        if self.trailer.get(b"Encrypt") is not None:
            raise BpError("encrypted")
        self.pages = self._pages()
        if not self.pages:
            raise BpError("no pages")

    # ---------------------------------------------------------------- lexer
    def _skip(self, i):
        b, n = self.b, len(self.b)
        while i < n:
            c = b[i]
            if c in _WS:
                i += 1
            elif c == 0x25:  # % comment
                while i < n and b[i] not in (10, 13):
                    i += 1
            else:
                break
        return i

    def _token(self, i):
        """The regular token at i -> (bytes, end)."""
        b, n, j = self.b, len(self.b), i
        while j < n and b[j] not in _REG_END:
            j += 1
        return b[i:j], j

    def _parse(self, i, depth=0):
        """The object at i -> (value, end)."""
        if depth > BP_MAX_DEPTH:
            raise BpError("nested too deep")
        b = self.b
        i = self._skip(i)
        if i >= len(b):
            raise BpError("unexpected end")
        c = b[i]
        if c == 0x2F:  # /name
            t, j = self._token(i + 1)
            return BpName(t), j
        if c == 0x3C:  # < : dict or hex string
            if b[i + 1:i + 2] == b"<":
                d, j = {}, i + 2
                while True:
                    j = self._skip(j)
                    if b[j:j + 2] == b">>":
                        return d, j + 2
                    k, j = self._parse(j, depth + 1)
                    if not isinstance(k, BpName):
                        raise BpError("bad dictionary key")
                    v, j = self._parse(j, depth + 1)
                    d[bytes(k)] = v
            j = b.find(b">", i)
            if j < 0:
                raise BpError("open hex string")
            return BpStr(b[i:j + 1]), j + 1
        if c == 0x28:  # ( literal string )
            j, lvl, n = i + 1, 1, len(b)
            while j < n and lvl:
                ch = b[j]
                if ch == 0x5C:
                    j += 2
                    continue
                if ch == 0x28:
                    lvl += 1
                elif ch == 0x29:
                    lvl -= 1
                j += 1
            if lvl:
                raise BpError("open string")
            return BpStr(b[i:j]), j
        if c == 0x5B:  # [ array ]
            a, j = [], i + 1
            while True:
                j = self._skip(j)
                if j >= len(b):
                    raise BpError("open array")
                if b[j] == 0x5D:
                    return a, j + 1
                v, j = self._parse(j, depth + 1)
                a.append(v)
        t, j = self._token(i)
        if not t:
            raise BpError(f"unexpected byte {c}")
        if t == b"true":
            return True, j
        if t == b"false":
            return False, j
        if t == b"null":
            return None, j
        if _NUM_RE.fullmatch(t):
            if _INT_RE.fullmatch(t):  # maybe "n g R"
                k = self._skip(j)
                t2, k2 = self._token(k)
                if _INT_RE.fullmatch(t2 or b"-"):
                    k3 = self._skip(k2)
                    if b[k3:k3 + 1] == b"R" and (k3 + 1 >= len(b) or b[k3 + 1] in _REG_END):
                        return BpRef(int(t), int(t2)), k3 + 1
            return BpNum(t), j
        raise BpError("unknown token")

    # ---------------------------------------------------------------- objects
    def _indirect_at(self, off, num=None):
        """The object "n g obj ... endobj" at off -> value (a BpStream for streams)."""
        i = self._skip(off)
        t1, i = self._token(i)
        i = self._skip(i)
        t2, i = self._token(i)
        i = self._skip(i)
        t3, i = self._token(i)
        if t3 != b"obj" or not _INT_RE.fullmatch(t1 or b"-") or (num is not None and int(t1) != num):
            raise BpError("object not where the table says")
        v, i = self._parse(i)
        j = self._skip(i)
        if isinstance(v, dict) and self.b[j:j + 6] == b"stream":
            j += 6
            if self.b[j:j + 2] == b"\r\n":
                j += 2
            elif self.b[j:j + 1] in (b"\n", b"\r"):
                j += 1
            ln = v.get(b"Length")
            if isinstance(ln, BpRef):
                ln = self.obj(ln)
            ln = int(bp_num(ln, -1))
            end = j + ln
            if ln < 0 or end > len(self.b) or b"endstream" not in self.b[end:end + 32]:
                e = self.b.find(b"endstream", j)
                if e < 0:
                    raise BpError("open stream")
                end = e
                while end > j and self.b[end - 1] in (10, 13):
                    end -= 1
            return BpStream(v, self.b[j:end])
        return v

    def obj(self, ref):
        """The value of a reference (other values pass through); a missing object is null."""
        if not isinstance(ref, BpRef):
            return ref
        num = ref.num
        if num in self._cache:
            return self._cache[num]
        self._cache[num] = None  # a reference cycle reads null instead of recursing
        # 2.148.1 D (#2485): bounded nesting and time (sub documents of object streams share the counters via _lim)
        lim = getattr(self, "_lim", self)
        if time.monotonic() > lim._end:
            raise BpError("too slow")
        if lim._depth >= BP_MAX_REF_DEPTH:
            raise BpError("nested too deeply")
        lim._depth += 1
        try:
            e = self.xref.get(num)
            v = None
            if e and e[0] == "o":
                v = self._indirect_at(e[1], num)
            elif e and e[0] == "s":
                v = self._from_objstm(e[1], e[2], num)
        finally:
            lim._depth -= 1
        self._cache[num] = v
        return v

    def _from_objstm(self, snum, idx, num):
        if snum not in self._objstm:
            s = self.obj(BpRef(snum))
            if not isinstance(s, BpStream):
                raise BpError("object stream missing")
            data = bp_decode(s, self)
            n, first = int(bp_num(s.d.get(b"N"))), int(bp_num(s.d.get(b"First")))
            head = data[:first].split()
            offs = {}
            for k in range(min(n, len(head) // 2)):
                offs[int(head[2 * k])] = first + int(head[2 * k + 1])
            self._objstm[snum] = (data, offs)
        data, offs = self._objstm[snum]
        if num not in offs:
            return None
        sub = BpDoc.__new__(BpDoc)
        sub.b, sub.xref, sub._cache, sub._objstm = data, self.xref, self._cache, self._objstm
        sub._lim = getattr(self, "_lim", self)  # 2.148.1 D (#2485)
        return sub._parse(offs[num])[0]

    # ---------------------------------------------------------------- cross-reference
    def _read_xref(self):
        tail = self.b[-2048:]
        k = tail.rfind(b"startxref")
        if k < 0:
            raise ValueError("no startxref")
        off = int(tail[k + 9:].split()[0])
        seen = set()
        while off is not None and off not in seen and len(seen) < 64:
            seen.add(off)
            i = self._skip(off)
            if self.b[i:i + 4] == b"xref":
                trailer = self._xref_table(i + 4)
                stm = trailer.get(b"XRefStm")
                if isinstance(stm, BpNum):
                    self._xref_stream(int(stm.v))
            else:
                trailer = self._xref_stream(i)
            for k2, v in trailer.items():
                self.trailer.setdefault(k2, v)
            prev = trailer.get(b"Prev")
            off = int(prev.v) if isinstance(prev, BpNum) else None

    def _xref_table(self, i):
        b = self.b
        while True:
            i = self._skip(i)
            if b[i:i + 7] == b"trailer":
                return self._parse(i + 7)[0]
            t1, i = self._token(i)
            i = self._skip(i)
            t2, i = self._token(i)
            start, count = int(t1), int(t2)
            for n in range(count):
                i = self._skip(i)
                ent = b[i:i + 20].split()
                if len(ent) < 3:
                    raise ValueError("short xref entry")
                i += len(b" ".join(ent[:3]))
                if ent[2][:1] == b"n" and (start + n) not in self.xref:
                    self.xref[start + n] = ("o", int(ent[0]))
                elif (start + n) not in self.xref:
                    self.xref[start + n] = ("f",)

    def _xref_stream(self, off):
        s = self._indirect_at(off)
        if not isinstance(s, BpStream) or s.d.get(b"Type") != b"XRef":
            raise ValueError("no xref stream")
        data = bp_decode(s, self)
        w = [int(bp_num(x)) for x in s.d.get(b"W") or []]
        if len(w) != 3 or sum(w) <= 0:
            raise ValueError("bad W")
        idx = [int(bp_num(x)) for x in s.d.get(b"Index") or [BpNum(b"0"), s.d.get(b"Size")]]
        rec, pos = sum(w), 0
        for a in range(0, len(idx) - 1, 2):
            for n in range(idx[a], idx[a] + idx[a + 1]):
                if pos + rec > len(data):
                    break
                f = []
                q = pos
                for wl in w:
                    f.append(int.from_bytes(data[q:q + wl], "big") if wl else None)
                    q += wl
                pos += rec
                typ = 1 if f[0] is None else f[0]
                if n in self.xref:
                    continue
                if typ == 1:
                    self.xref[n] = ("o", f[1])
                elif typ == 2:
                    self.xref[n] = ("s", f[1], f[2] or 0)
                else:
                    self.xref[n] = ("f",)
        return s.d

    def _rebuild(self, why):
        """No usable table: every "n g obj" of the file (the last one of a number wins), the trailer from the last
        "trailer" dictionary or the last xref stream, else the catalog found by its /Type."""
        self.xref, self._cache = {}, {}
        for m in re.finditer(rb"(?<![0-9])(\d{1,7})\s+(\d{1,5})\s+obj\b", self.b):
            self.xref[int(m.group(1))] = ("o", m.start())
        self.trailer = {}
        k = self.b.rfind(b"trailer")
        if k >= 0:
            try:
                self.trailer = self._parse(k + 7)[0]
            except Exception:  # noqa: BLE001
                self.trailer = {}
        for num in list(self.xref):
            if self.trailer.get(b"Root"):
                break
            try:
                v = self.obj(BpRef(num))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(v, BpStream) and v.d.get(b"Type") == b"ObjStm":
                n, first = int(bp_num(v.d.get(b"N"))), int(bp_num(v.d.get(b"First")))
                head = bp_decode(v, self)[:first].split()
                for q in range(min(n, len(head) // 2)):
                    self.xref.setdefault(int(head[2 * q]), ("s", num, q))
            if isinstance(v, BpStream) and v.d.get(b"Type") == b"XRef":
                self.trailer = dict(v.d)
        if not self.trailer.get(b"Root"):
            for num in list(self.xref):
                v = self.obj(BpRef(num))
                if isinstance(v, dict) and v.get(b"Type") == b"Catalog":
                    self.trailer = {b"Root": BpRef(num)}
                    break
        if not self.trailer.get(b"Root"):
            raise BpError(f"no catalog ({why})")

    # ---------------------------------------------------------------- pages
    def _pages(self):
        root = self.obj(self.trailer.get(b"Root"))
        if not isinstance(root, dict):
            raise BpError("no catalog")
        out, seen = [], set()

        def walk(ref, inh, depth):
            if depth > 32 or len(out) >= 2:
                return
            if isinstance(ref, BpRef):
                if ref.num in seen:
                    return
                seen.add(ref.num)
            node = self.obj(ref)
            if not isinstance(node, dict):
                return
            inh = dict(inh)
            for k in (b"Resources", b"MediaBox", b"CropBox", b"Rotate"):
                if k in node:
                    inh[k] = node[k]
            if node.get(b"Type") == b"Pages" or (b"Kids" in node and node.get(b"Type") != b"Page"):
                for kid in self.obj(node.get(b"Kids")) or []:
                    walk(kid, inh, depth + 1)
            else:
                out.append((node, inh))
        walk(root.get(b"Pages"), {}, 0)
        return out

    def page_box(self, i):
        """(llx, lly, urx, ury) of page i (the CropBox inside the MediaBox when there is one)."""
        node, inh = self.pages[i]
        box = self.obj(inh.get(b"CropBox") or inh.get(b"MediaBox"))
        try:
            vals = [bp_num(self.obj(x), None) for x in box]
            if len(vals) != 4 or None in vals:
                raise TypeError
        except TypeError:
            vals = [0, 0, 595.28, 841.89]
        x0, y0, x1, y1 = vals
        if x1 - x0 < 1 or y1 - y0 < 1:
            raise BpError("empty page")
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def page_content(self, i):
        """The decoded content of page i (all its streams joined)."""
        node, inh = self.pages[i]
        c = node.get(b"Contents")
        c = self.obj(c)
        parts = c if isinstance(c, list) else [c] if c is not None else []
        seen = set()  # 2.120.0 review H1: the same stream once, at most BP_MAX_CONTENTS
        parts = [p for p in parts if not (isinstance(p, BpRef) and (p.num in seen or seen.add(p.num)))]
        if len(parts) > BP_MAX_CONTENTS:
            raise BpError("too many content streams")
        out = []
        for p in parts:
            s = self.obj(p)
            if s is None:
                continue
            if not isinstance(s, BpStream):
                raise BpError("content is no stream")
            out.append(bp_decode(s, self))
        return b"\n".join(out)

    def page_rotate(self, i):
        return int(bp_num(self.obj(self.pages[i][1].get(b"Rotate")), 0)) % 360


# ---------------------------------------------------------------- filters
def _png_unpredict(data, cols, colors=1, bpc=8):
    if len(data) > BP_MAX_PREDICTED or not (1 <= cols <= 1 << 14) or not (1 <= colors <= 4) or bpc not in (1, 2, 4, 8, 16):
        raise BpError("unsupported predictor data")  # 2.120.0 review H1: pure Python loop, bounded
    bpp = max(1, colors * bpc // 8)
    row = (cols * colors * bpc + 7) // 8
    out, prev, i = bytearray(), bytearray(row), 0
    while i + 1 + row <= len(data):
        ft, cur = data[i], bytearray(data[i + 1:i + 1 + row])
        i += 1 + row
        for x in range(row):
            a = cur[x - bpp] if x >= bpp else 0
            up = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ft == 1:
                cur[x] = (cur[x] + a) & 0xFF
            elif ft == 2:
                cur[x] = (cur[x] + up) & 0xFF
            elif ft == 3:
                cur[x] = (cur[x] + ((a + up) >> 1)) & 0xFF
            elif ft == 4:
                pa, pb, pc = abs(up - c), abs(a - c), abs(a + up - 2 * c)
                cur[x] = (cur[x] + (a if pa <= pb and pa <= pc else up if pb <= pc else c)) & 0xFF
        out += cur
        prev = cur
    return bytes(out)


def bp_decode(s, doc=None):
    """The decoded data of stream s (FlateDecode with predictors, ASCIIHex, ASCII85, no filter); BpError for others."""
    get = (doc.obj if doc else (lambda x: x))
    flt = get(s.d.get(b"Filter"))
    parms = get(s.d.get(b"DecodeParms"))
    flts = flt if isinstance(flt, list) else [flt] if flt is not None else []
    parms = parms if isinstance(parms, list) else [parms] * len(flts)
    data = s.data
    for k, f in enumerate(flts):
        f = bytes(get(f) or b"")
        p = get(parms[k]) if k < len(parms) else None
        if f in (b"FlateDecode", b"Fl"):
            try:
                d = zlib.decompressobj()
                lim = BP_MAX_DECODED if doc is None else min(BP_MAX_DECODED, BP_MAX_DOC_DECODED - doc.decoded)
                data = d.decompress(data, max(0, lim) + 1)
            except zlib.error:
                raise BpError("broken compressed stream") from None
            if len(data) > lim:
                raise BpError("stream too large")
            if doc is not None:
                doc.decoded += len(data)
            pred = int(bp_num(get((p or {}).get(b"Predictor")), 1)) if isinstance(p, dict) else 1
            if pred >= 10:
                data = _png_unpredict(data, int(bp_num(get(p.get(b"Columns")), 1)), int(bp_num(get(p.get(b"Colors")), 1)),
                                      int(bp_num(get(p.get(b"BitsPerComponent")), 8)))
            elif pred != 1:
                raise BpError("unknown predictor")
        elif f in (b"ASCIIHexDecode", b"AHx"):
            h = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
            data = bytes.fromhex((h + b"0" if len(h) % 2 else h).decode())
        elif f in (b"ASCII85Decode", b"A85"):
            t = re.sub(rb"\s", b"", data)
            t = t[2:] if t.startswith(b"<~") else t
            t = t.split(b"~>")[0]
            try:
                data = base64.a85decode(t)
            except ValueError:
                raise BpError("broken ASCII85") from None
        else:
            raise BpError("unsupported filter")
    return data


# ---------------------------------------------------------------- writing back
def bp_ser(v):
    """A value -> its bytes (raw tokens unchanged; streams are written by the caller)."""
    if v is None:
        return b"null"
    if v is True:
        return b"true"
    if v is False:
        return b"false"
    if isinstance(v, BpNum):
        return v.raw
    if isinstance(v, (int, float)):
        return (f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)).encode()
    if isinstance(v, BpName):
        return b"/" + bytes(v)
    if isinstance(v, BpStr):
        return bytes(v)
    if isinstance(v, BpRef):
        return f"{v.num} {v.gen} R".encode()
    if isinstance(v, list):
        return b"[" + b" ".join(bp_ser(x) for x in v) + b"]"
    if isinstance(v, dict):
        return b"<<" + b"".join(b"/" + k + b" " + bp_ser(x) for k, x in v.items()) + b" >>"
    raise BpError("cannot write value")


BP_DROP_KEYS = (b"PieceInfo", b"StructParent", b"StructParents", b"Metadata", b"Parent")


class BpCopier:
    """Copies objects of one BpDoc into the object list of pdf_write (object number = index + 1); shared objects (a
    font used on page 1 and on the following pages) are written once."""

    def __init__(self, doc, objs):
        self.doc, self.objs, self.memo, self.todo = doc, objs, {}, []

    def ref(self, num):
        if num not in self.memo:
            if len(self.memo) >= BP_MAX_OBJECTS:
                raise BpError("too many objects")
            self.objs.append(b"null")
            self.memo[num] = len(self.objs)
            self.todo.append(num)
        return self.memo[num]

    def val(self, v, depth=0):
        if depth > BP_MAX_DEPTH:
            raise BpError("nested too deep")
        if isinstance(v, BpRef):
            return BpRef(self.ref(v.num))
        if isinstance(v, list):
            return [self.val(x, depth + 1) for x in v]
        if isinstance(v, dict):
            return {k: self.val(x, depth + 1) for k, x in v.items() if k not in BP_DROP_KEYS}
        return v

    def body(self, v):
        if isinstance(v, BpStream):
            d = self.val(v.d)
            d.pop(b"Length", None)
            return bp_ser(d)[:-2] + f"/Length {len(v.data)} >>\nstream\n".encode() + v.data + b"\nendstream"
        return bp_ser(self.val(v))

    def flush(self):
        while self.todo:
            num = self.todo.pop()
            self.objs[self.memo[num] - 1] = self.body(self.doc.obj(BpRef(num)))

    def form(self, i, matrix):
        """Page i as a form XObject -> its object number. matrix: the six numbers placing the page on the document page."""
        node, inh = self.doc.pages[i]
        x0, y0, x1, y1 = self.doc.page_box(i)
        res = self.val(self.doc.obj(inh.get(b"Resources")) or {})
        if not isinstance(res, dict):
            res = {}
        content = zlib.compress(self.doc.page_content(i), 6)
        head = (f"<< /Type /XObject /Subtype /Form /FormType 1 /BBox [{x0:.4f} {y0:.4f} {x1:.4f} {y1:.4f}] "
                f"/Matrix [{' '.join(f'{m:.5f}' for m in matrix)}] /Resources ").encode()
        self.objs.append(head + bp_ser(res) + f" /Filter /FlateDecode /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        fid = len(self.objs)
        self.flush()
        return fid


def bp_check(data):
    """Reads data as a letterhead -> (number of pages used (1 or 2), [(width pt, height pt)]); BpError when it cannot be
    used. Every object a page needs is resolved here once, so a document PDF later never meets a broken one."""
    doc = BpDoc(data)
    sizes = []
    for i in range(min(2, len(doc.pages))):
        if doc.page_rotate(i):
            raise BpError("rotated page")
        x0, y0, x1, y1 = doc.page_box(i)
        sizes.append((x1 - x0, y1 - y0))
        objs = []
        BpCopier(doc, objs).form(i, (1, 0, 0, 1, 0, 0))
    return len(sizes), sizes
