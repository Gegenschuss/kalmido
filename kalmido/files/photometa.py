"""2.61.0 (#1819): photo metadata (GPS, camera) removed on upload.

Every upload of the shared path (files/upsafe.py) comes here with its bytes. The type comes from the content (magic bytes),
never from the name. A photo loses its EXIF, XMP and IPTC data (place, camera, serial number, capture time) before it is
stored; the picture itself stays as it is wherever possible:

  JPEG  the APP1 (EXIF / XMP), APP13 (IPTC), comment and vendor segments are cut out without touching the image data; the
        ICC profile (APP2), JFIF (APP0) and Adobe (APP14) stay. Extra pictures behind the main one (MPF: gain map, depth)
        go with their index. A photo stored turned (EXIF orientation 2-8) is turned upright first and encoded again.
  PNG   the chunks eXIf, tEXt, iTXt, zTXt and tIME go (orientation in eXIf: turned upright and encoded again)
  WebP  the RIFF chunks EXIF and "XMP " go, VP8X flags and RIFF size follow (orientation: as JPEG)
  HEIC  (also HEIF / AVIF) no library: the meta box's Exif and XMP (mime) items are overwritten in place (an empty EXIF /
        an empty XMP packet, the rest zeros), so the file keeps its structure. The turn lives in irot / imir, not in EXIF.
        2.209.0 D (#1856): also items stored inside another item's data (iloc construction method 2).
  TIFF  2.190.0 D (#2496): the GPS directory of every image directory is emptied in place (its values zeroed) and an XMP
        packet (tag 700) becomes an empty one; the rest of the file stays byte for byte. 2.209.0 D (#1856): the EXIF directory
        (tag 0x8769: camera, serial number, times) is emptied the same way and IPTC (tag 33723) zeroed. Camera RAW files that
        are TIFF inside (DNG, CR2, NEF, ARW) take this path; other RAW formats stay as they came.
  GIF   2.209.0 D (#1856): comment blocks and application blocks other than the loop setting (NETSCAPE2.0 / ANIMEXTS1.0, e.g.
        XMP) go; the image blocks are copied unchanged. Videos (MOV / MP4) stay as they are.

The capture date (EXIF DateTimeOriginal, else DateTime) is read before -- also when the setting keeps the metadata -- and
handed on as meta["taken_at"] (documents keep it, files/store.py fs_put up=...). GPS is never stored anywhere.
The setting: an organisation's file follows orgs.photo_meta_strip, any other the uploader's user setting photo_meta_strip
(both default on). Anything unknown, broken or too big stays exactly as it came: the upload never fails here."""
import io
import os
import re
import struct
import threading
import zlib
from datetime import datetime

# the re-encode of a turned photo (memory); bigger: an orientation-only EXIF instead. 2.81.0 (#1856): KALMIDO_PHOTO_MAX_PIXELS
_pm_px = os.environ.get("KALMIDO_PHOTO_MAX_PIXELS", "").strip()
PM_MAX_PIXELS = max(1_000_000, int(_pm_px)) if _pm_px.isdigit() else 40_000_000
PM_JPEG_QUALITY = 92
_PM_ENC = threading.BoundedSemaphore(2)  # at most two re-encodes at once (memory)
_PM_ENC_WAIT = 20                   # s; a busy server writes the orientation-only EXIF instead

_JPEG_KEEP_APP = {0xE0, 0xE2, 0xEE}  # APP0 JFIF / JFXX, APP2 (ICC; MPF is cut), APP14 Adobe (colour transform)
_PNG_DROP = {b"eXIf", b"tEXt", b"iTXt", b"zTXt", b"tIME"}
_HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1", b"heif", b"avif", b"avis", b"mif2"}


# ---- the setting ------------------------------------------------------------------------------------------------------------
def pm_on(c, uid, org_id):
    """Whether metadata is removed: an organisation's file follows the organisation, any other the uploader's setting."""
    try:
        if org_id:
            r = c.execute("SELECT photo_meta_strip FROM orgs WHERE id=?", (org_id,)).fetchone()
            return not r or r[0] is None or int(r[0]) != 0
        if uid:
            from ..core.db import usettings
            return str(usettings(c, uid).get("photo_meta_strip", "1")) != "0"
    except Exception as e:  # noqa: BLE001 -- an unreadable setting = the safe default (remove)
        print("photometa: setting", type(e).__name__, flush=True)
    return True


def pm_kind(data):
    """'jpeg' | 'png' | 'webp' | 'heif' | 'tiff' | 'gif' | '' from the first bytes."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):  # 2.190.0 D (#2496)
        return "tiff"
    if data[:6] in (b"GIF87a", b"GIF89a"):  # 2.209.0 D (#1856)
        return "gif"
    if data[4:8] == b"ftyp" and len(data) >= 16:
        n = struct.unpack(">I", data[:4])[0]
        brands = {data[8:12]} | {data[i:i + 4] for i in range(16, min(n, 64, len(data)) - 3, 4)}
        if brands & _HEIF_BRANDS:
            return "heif"
    return ""


def pm_strip(c, data, mime, uid=None, org_id=None):
    """Returns (data, meta): data without metadata (orientation applied first) when the setting is on, meta a dict
    (e.g. {"taken_at": "2026-10-16T12:00:00"}) read before the removal."""
    try:
        kind = pm_kind(data or b"")
        if not kind:
            return data, {}
        fn = {"jpeg": _pm_jpeg, "png": _pm_png, "webp": _pm_webp, "heif": _pm_heif, "tiff": _pm_tiff, "gif": _pm_gif}[kind]
        out, taken = fn(data, pm_on(c, uid, org_id))
        meta = {"taken_at": taken} if taken else {}
        if out is None or not out:
            return data, meta
        return out, meta
    except Exception as e:  # noqa: BLE001 -- a broken file is stored as it came, the upload goes on
        print("photometa:", type(e).__name__, flush=True)
        return data, {}


# ---- EXIF (TIFF) reading ----------------------------------------------------------------------------------------------------
def pm_exif(t):
    """(taken_at ISO | "", orientation 1-8) from EXIF bytes (a TIFF block, maybe with the "Exif\\0\\0" prefix)."""
    if t[:6] == b"Exif\x00\x00":
        t = t[6:]
    if t[:4] == b"II*\x00":
        e = "<"
    elif t[:4] == b"MM\x00*":
        e = ">"
    else:
        return "", 1

    def ifd(off):
        if off < 8 or off + 2 > len(t):
            return {}
        n = struct.unpack(e + "H", t[off:off + 2])[0]
        out = {}
        for i in range(min(n, 500)):
            p = off + 2 + 12 * i
            if p + 12 > len(t):
                break
            tag, typ, cnt = struct.unpack(e + "HHI", t[p:p + 8])
            out[tag] = (typ, cnt, t[p + 8:p + 12])
        return out

    def ascii_(ent):
        typ, cnt, raw = ent
        if typ != 2 or cnt > 64:
            return ""
        if cnt <= 4:
            b = raw[:cnt]
        else:
            o = struct.unpack(e + "I", raw)[0]
            b = t[o:o + cnt]
        return b.split(b"\x00")[0].decode("ascii", "replace").strip()

    ifd0 = ifd(struct.unpack(e + "I", t[4:8])[0])
    orient = 1
    if 0x0112 in ifd0 and ifd0[0x0112][0] == 3:
        orient = struct.unpack(e + "H", ifd0[0x0112][2][:2])[0]
    sub = {}
    if 0x8769 in ifd0 and ifd0[0x8769][0] in (4, 13):
        sub = ifd(struct.unpack(e + "I", ifd0[0x8769][2])[0])
    raw, tz = "", ""
    if 0x9003 in sub:
        raw, tz = ascii_(sub[0x9003]), ascii_(sub[0x9011]) if 0x9011 in sub else ""
    if not _pm_iso(raw) and 0x0132 in ifd0:
        raw, tz = ascii_(ifd0[0x0132]), ascii_(sub[0x9010]) if 0x9010 in sub else ""
    taken = _pm_iso(raw)
    if taken and re.fullmatch(r"[+-]\d{2}:\d{2}", tz or ""):
        taken += tz
    return taken, orient if 1 <= orient <= 8 else 1


def _pm_iso(raw):
    m = re.fullmatch(r"(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", raw or "")
    if not m:
        return ""
    try:
        d = datetime(*map(int, m.groups()))
    except ValueError:
        return ""
    return d.isoformat() if 1900 < d.year < 2200 else ""


# a TIFF block with nothing but the orientation (photos too big / a busy server: the turn stays without the rest)
def _pm_orient_exif(orient):
    return b"Exif\x00\x00MM\x00*\x00\x00\x00\x08" + struct.pack(">HHHIHH", 1, 0x0112, 3, 1, orient, 0) + b"\x00\x00\x00\x00"


# ---- JPEG -------------------------------------------------------------------------------------------------------------------
def _pm_jpeg_segments(data):
    """[(marker, start, end)] of the JPEG's segments up to its end (EOI); the entropy-coded data after a SOS belongs to that
    SOS. None when the structure is broken."""
    segs, p, n = [], 2, len(data)
    while p < n:
        if data[p] != 0xFF:
            return None
        while p < n and data[p] == 0xFF:  # fill bytes
            p += 1
        if p >= n:
            return None
        mk = data[p]
        s = p - 1
        p += 1
        if mk == 0xD9:  # EOI
            segs.append((mk, s, p))
            return segs
        if 0xD0 <= mk <= 0xD7 or mk == 0x01:
            segs.append((mk, s, p))
            continue
        if p + 2 > n:
            return None
        ln = struct.unpack(">H", data[p:p + 2])[0]
        if ln < 2 or p + ln > n:
            return None
        p += ln
        if mk == 0xDA:  # SOS: the scan's data runs to the next marker that is no stuffing / restart
            while True:
                q = data.find(b"\xff", p)
                if q < 0 or q + 1 >= n:
                    return None
                b = data[q + 1]
                if b == 0x00 or 0xD0 <= b <= 0xD7 or b == 0xFF:
                    p = q + 1 if b == 0xFF else q + 2
                    continue
                p = q
                break
        segs.append((mk, s, p))
    return None


def _pm_jpeg_clean(data, segs):
    out = [data[:2]]
    for mk, s, e in segs:
        if (0xE0 <= mk <= 0xEF and mk not in _JPEG_KEEP_APP) or mk == 0xFE:
            continue  # APP1 EXIF / XMP, APP13 IPTC, other vendor segments, comments
        if mk == 0xE2 and data[s + 4:s + 8] == b"MPF\x00":
            continue  # the index of the extra pictures (they are cut too)
        out.append(data[s:e])
    return b"".join(out)  # ends with the EOI: what came after the main picture is gone


def _pm_jpeg(data, on):
    segs = _pm_jpeg_segments(data)
    if not segs:
        return None, ""
    taken, orient = "", 1
    for mk, s, e in segs:
        if mk == 0xE1 and data[s + 4:s + 10] == b"Exif\x00\x00":
            taken, orient = pm_exif(data[s + 4:e])
            break
        if mk == 0xDA:
            break
    if not on:
        return None, taken
    clean = _pm_jpeg_clean(data, segs)
    if orient != 1:
        turned = _pm_turn(clean, "JPEG", orient)
        if turned:
            return turned, taken
        segs2 = _pm_jpeg_segments(clean)  # too big / busy: the orientation alone survives (the picture stays upright)
        app = _pm_orient_exif(orient)
        k = 1 if segs2 and segs2[0][0] == 0xE0 else 0
        hdr = b"\xff\xe1" + struct.pack(">H", len(app) + 2) + app
        return (clean[:2] + b"".join(clean[s:e] for _, s, e in segs2[:k]) + hdr
                + b"".join(clean[s:e] for _, s, e in segs2[k:])) if segs2 else clean, taken
    return clean, taken


def _pm_turn(data, fmt, orient):
    """The picture turned upright and encoded again (no metadata, ICC kept); None when it cannot be done (no Pillow, too
    big, broken, animated, busy)."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    if not _PM_ENC.acquire(timeout=_PM_ENC_WAIT):
        return None
    try:
        im = Image.open(io.BytesIO(data))  # the header only
        if im.width * im.height > PM_MAX_PIXELS or getattr(im, "n_frames", 1) > 1:
            return None
        icc = im.info.get("icc_profile")
        kw = {}
        if fmt == "JPEG":
            from PIL import JpegImagePlugin
            sub = JpegImagePlugin.get_sampling(im)
            kw = {"quality": PM_JPEG_QUALITY, "optimize": True, **({"subsampling": sub} if sub in (0, 1, 2) else {}),
                  **({"dpi": im.info["dpi"]} if im.info.get("dpi") else {})}
            if im.mode not in ("RGB", "L", "CMYK"):
                return None
        elif fmt == "WEBP":
            kw = {"lossless": True} if any(t == b"VP8L" for t, _, _ in _pm_webp_chunks(data) or []) else {"quality": PM_JPEG_QUALITY}
        im.load()
        im.getexif()[0x0112] = orient  # the orientation of the original (the cleaned bytes have none left)
        up = ImageOps.exif_transpose(im)
        up.info = {k: up.info[k] for k in ("transparency", "dpi") if k in up.info}  # nothing else of the original is written again
        if icc:
            kw["icc_profile"] = icc
        out = io.BytesIO()
        up.save(out, fmt, **kw)
        b = out.getvalue()
    except Exception as e:  # noqa: BLE001 -- Pillow errors, decompression bombs, memory
        print("photometa: turn", type(e).__name__, flush=True)
        return None
    finally:
        _PM_ENC.release()
    # whatever the encoder wrote on its own goes too (the stripped result never carries metadata)
    k = pm_kind(b)
    if k == "jpeg":
        s = _pm_jpeg_segments(b)
        return _pm_jpeg_clean(b, s) if s else None
    if k == "png":
        return _pm_png_clean(b)
    if k == "webp":
        return _pm_webp_clean(b)
    return None


# ---- PNG --------------------------------------------------------------------------------------------------------------------
def _pm_png_chunks(data):
    p, n, out = 8, len(data), []
    while p + 12 <= n:
        ln = struct.unpack(">I", data[p:p + 4])[0]
        typ = data[p + 4:p + 8]
        e = p + 12 + ln
        if e > n:
            return None
        out.append((typ, p, e))
        p = e
        if typ == b"IEND":
            return out
    return None


def _pm_png_clean(data):
    ch = _pm_png_chunks(data)
    if not ch:
        return None
    return data[:8] + b"".join(data[s:e] for t, s, e in ch if t not in _PNG_DROP)


def _pm_png(data, on):
    ch = _pm_png_chunks(data)
    if not ch:
        return None, ""
    taken, orient = "", 1
    for t, s, e in ch:
        if t == b"eXIf":
            taken, orient = pm_exif(data[s + 8:e - 4])
            break
    if not on:
        return None, taken
    clean = data[:8] + b"".join(data[s:e] for t, s, e in ch if t not in _PNG_DROP)
    if orient != 1:
        turned = None if any(t == b"acTL" for t, _, _ in ch) else _pm_turn(clean, "PNG", orient)
        if turned:
            return turned, taken
        i = next(s for t, s, e in ch if t == b"IDAT") if any(t == b"IDAT" for t, _, _ in ch) else None
        if i is not None:  # not turned: the orientation alone stays (before the first IDAT, as the PNG spec wants it)
            tiff = _pm_orient_exif(orient)[6:]
            exif_chunk = struct.pack(">I", len(tiff)) + b"eXIf" + tiff + struct.pack(">I", zlib.crc32(b"eXIf" + tiff) & 0xffffffff)
            k = len(data[:8] + b"".join(data[s:e] for t, s, e in ch if t not in _PNG_DROP and s < i))
            return clean[:k] + exif_chunk + clean[k:], taken
    return clean, taken


# ---- WebP -------------------------------------------------------------------------------------------------------------------
def _pm_webp_chunks(data):
    p, n, out = 12, len(data), []
    end = min(n, 8 + struct.unpack("<I", data[4:8])[0])
    while p + 8 <= end:
        typ = data[p:p + 4]
        ln = struct.unpack("<I", data[p + 4:p + 8])[0]
        e = p + 8 + ln + (ln & 1)
        if p + 8 + ln > end:
            return None
        out.append((typ, p, min(e, end)))
        p = e
    return out or None


def _pm_webp_clean(data):
    ch = _pm_webp_chunks(data)
    if not ch:
        return None
    parts = []
    for t, s, e in ch:
        if t in (b"EXIF", b"XMP "):
            continue
        b = data[s:e]
        if t == b"VP8X" and len(b) >= 9:
            b = b[:8] + bytes([b[8] & ~0x0C]) + b[9:]  # flags: no EXIF (0x08), no XMP (0x04)
        parts.append(b)
    body = b"WEBP" + b"".join(parts)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _pm_webp(data, on):
    ch = _pm_webp_chunks(data)
    if not ch:
        return None, ""
    taken, orient = "", 1
    for t, s, e in ch:
        if t == b"EXIF":
            ln = struct.unpack("<I", data[s + 4:s + 8])[0]
            taken, orient = pm_exif(data[s + 8:s + 8 + ln])
            break
    if not on:
        return None, taken
    clean = _pm_webp_clean(data)
    if clean and orient != 1:
        turned = None if any(t == b"ANIM" for t, _, _ in ch) else _pm_turn(clean, "WEBP", orient)
        if turned:
            return turned, taken
        if clean[12:16] == b"VP8X":  # not turned: the orientation alone stays (an EXIF chunk at the end, its flag set)
            tiff = _pm_orient_exif(orient)[6:]
            body = clean[12:20] + bytes([clean[20] | 0x08]) + clean[21:] + b"EXIF" + struct.pack("<I", len(tiff)) + tiff + b"\x00" * (len(tiff) & 1)
            return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body, taken
    return clean, taken


# ---- HEIC / HEIF / AVIF (ISOBMFF) -------------------------------------------------------------------------------------------
def _pm_boxes(data, p, end):
    """[(type, payload start, box end)] of the boxes in data[p:end]."""
    out = []
    while p + 8 <= end:
        ln, typ = struct.unpack(">I", data[p:p + 4])[0], data[p + 4:p + 8]
        h = 8
        if ln == 1:
            if p + 16 > end:
                break
            ln, h = struct.unpack(">Q", data[p + 8:p + 16])[0], 16
        elif ln == 0:
            ln = end - p
        if ln < h or p + ln > end:
            break
        out.append((typ, p + h, p + ln))
        p += ln
        if len(out) > 10_000:
            break
    return out


def _pm_uint(data, p, size):
    return (int.from_bytes(data[p:p + size], "big") if size else 0), p + size


def _pm_heif_items(data):
    """{item id: (type, content type)} and {item id: [(file offset, length)]} of the top level meta box; None if broken."""
    top = _pm_boxes(data, 0, len(data))
    meta = next(((s, e) for t, s, e in top if t == b"meta"), None)
    if not meta:
        return None
    kids = _pm_boxes(data, meta[0] + 4, meta[1])  # meta is a full box (version + flags)
    get = lambda name: next(((s, e) for t, s, e in kids if t == name), None)  # noqa: E731
    iinf, iloc, idat = get(b"iinf"), get(b"iloc"), get(b"idat")
    if not iinf or not iloc:
        return None
    s, e = iinf
    ver = data[s]
    p = s + 4 + (4 if ver else 2)
    types = {}
    for t, bs, be in _pm_boxes(data, p, e):
        if t != b"infe" or be - bs < 8:
            continue
        v = data[bs]
        if v < 2:
            continue
        q = bs + 4
        iid, q = _pm_uint(data, q, 2 if v == 2 else 4)
        q += 2  # protection index
        ityp = data[q:q + 4]
        q += 4
        ctype = ""
        if ityp == b"mime":
            q = data.find(b"\x00", q, be) + 1  # item name
            if q > 0:
                z = data.find(b"\x00", q, be)
                ctype = data[q:z if z >= 0 else be].decode("ascii", "replace")
        types[iid] = (ityp, ctype)
    s, e = iloc
    ver = data[s]
    p = s + 4
    off_sz, len_sz = data[p] >> 4, data[p] & 15
    base_sz, idx_sz = data[p + 1] >> 4, (data[p + 1] & 15) if ver in (1, 2) else 0
    p += 2
    cnt, p = _pm_uint(data, p, 2 if ver < 2 else 4)
    locs, total, m2 = {}, 0, {}
    for _ in range(min(cnt, 100_000)):
        if p >= e:
            break
        iid, p = _pm_uint(data, p, 2 if ver < 2 else 4)
        method = 0
        if ver in (1, 2):
            m, p = _pm_uint(data, p, 2)
            method = m & 15
        p += 2  # data reference index
        base, p = _pm_uint(data, p, base_sz)
        ext_n, p = _pm_uint(data, p, 2)
        ext = []
        for _ in range(min(ext_n, 10_000)):
            total += 1
            if p > e or total > 100_000:  # a crafted box: zero-size fields would loop without reading
                return None
            xi, p = _pm_uint(data, p, idx_sz)
            eo, p = _pm_uint(data, p, off_sz)
            el, p = _pm_uint(data, p, len_sz)
            if method == 2:  # 2.209.0 D (#1856): bytes inside another item's data (iref 'iloc'), resolved below
                m2.setdefault(iid, []).append((xi, base + eo, el))
            elif method == 0:
                ext.append((base + eo, el))
            elif method == 1 and idat:
                ext.append((idat[0] + base + eo, el))
        if p > e:
            return None
        locs[iid] = ext
    if m2:
        _pm_heif_m2(data, get(b"iref"), locs, m2)
    return types, locs


def _pm_heif_m2(data, iref, locs, m2):
    """2.209.0 D (#1856): construction method 2 -- an extent is an offset into the data of the item its iref 'iloc' names
    (extent index, 1-based; else the first); mapped onto that item's file extents."""
    if not iref:
        return
    s, e = iref
    w = 4 if data[s] else 2
    refs = {}
    for t, bs, be in _pm_boxes(data, s + 4, e):
        if t != b"iloc" or be - bs < w + 2:
            continue
        frm, q = _pm_uint(data, bs, w)
        n, q = _pm_uint(data, q, 2)
        refs[frm] = [_pm_uint(data, q + w * i, w)[0] for i in range(min(n, (be - q) // w))]
    for iid, parts in m2.items():
        out = []
        for xi, off, ln in parts:
            to = refs.get(iid) or []
            src = locs.get(to[xi - 1] if 0 < xi <= len(to) else (to[0] if to else -1)) or []
            for so, sl in src:  # walk the source's extents to the logical offset
                if off >= sl:
                    off -= sl
                    continue
                k = min(sl - off, ln)
                out.append((so + off, k))
                ln, off = ln - k, 0
                if ln <= 0:
                    break
        locs[iid] = out


_PM_XMP_EMPTY = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'


def _pm_heif(data, on):
    items = _pm_heif_items(data)
    if not items:
        return None, ""
    types, locs = items
    n = len(data)
    taken = ""
    hits = []
    for iid, (ityp, ctype) in types.items():
        is_xmp = ityp == b"mime" and "xmp" in ctype.lower() or ctype.lower() == "application/rdf+xml"
        if ityp != b"Exif" and not is_xmp:
            continue
        ext = [(o, ln) for o, ln in locs.get(iid, []) if 0 <= o and ln > 0 and o + ln <= n]
        if not ext:
            continue
        if sum(ln for _, ln in ext) > n:  # overlapping extents: no repeated writes over the whole file
            continue
        hits.append((ityp, ext))
        if ityp == b"Exif" and not taken:
            raw = b"".join(data[o:o + ln] for o, ln in ext)[:1_000_000]
            if len(raw) > 4:
                skip = struct.unpack(">I", raw[:4])[0]
                taken = pm_exif(raw[4 + skip:] if 4 + skip < len(raw) else b"")[0]
    if not on or not hits:
        return None, taken
    buf = bytearray(data)
    for ityp, ext in hits:
        # an empty but valid block keeps strict readers happy: EXIF = offset 0 + TIFF with an empty IFD, XMP = an empty packet
        fill = (b"\x00\x00\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00") if ityp == b"Exif" else _PM_XMP_EMPTY
        total = sum(ln for _, ln in ext)
        blob = (fill if len(fill) <= total else b"") + (b"\x00" if ityp == b"Exif" else b" ") * total
        k = 0
        for o, ln in ext:
            buf[o:o + ln] = blob[k:k + ln]
            k += ln
    return bytes(buf), taken


# ---- TIFF (2.190.0 D, #2496) -----------------------------------------------------------------------------------------------
_PM_TIFF_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8, 17: 8, 18: 8}


def _pm_tiff(data, on):
    """A TIFF without its GPS data (in place, the offsets stay valid): every IFD's GPS directory (tag 0x8825) left with no
    entries and its values zeroed, an XMP packet (tag 700) replaced by an empty one. (None, taken) when nothing is found."""
    taken = pm_exif(data[:4_000_000] if len(data) > 4_000_000 else data)[0]
    if not on:
        return None, taken
    e = "<" if data[:2] == b"II" else ">"
    n = len(data)
    buf = bytearray(data)
    hit, seen = False, set()

    def entries(off):
        if off < 8 or off + 2 > n:
            return []
        cnt = struct.unpack(e + "H", data[off:off + 2])[0]
        return [(off + 2 + 12 * i,) + struct.unpack(e + "HHI", data[off + 2 + 12 * i:off + 10 + 12 * i])
                for i in range(min(cnt, 500)) if off + 14 + 12 * i <= n]

    def blank(p, typ, cnt, fill):
        size = _PM_TIFF_SIZES.get(typ, 1) * cnt
        if size > 4:
            o = struct.unpack(e + "I", data[p + 8:p + 12])[0]
            if 0 < o and o + size <= n:
                buf[o:o + size] = fill(size)
        else:
            buf[p + 8:p + 12] = b"\x00" * 4

    off = struct.unpack(e + "I", data[4:8])[0]
    while 8 <= off < n and off not in seen and len(seen) < 64:
        seen.add(off)
        for p, tag, typ, cnt in entries(off):
            if tag in (0x8825, 0x8769) and typ in (4, 13) and cnt == 1:  # 2.209.0 D (#1856): + the EXIF directory
                g = struct.unpack(e + "I", data[p + 8:p + 12])[0]
                ge = entries(g)
                for gp, _t, gtyp, gcnt in ge:
                    blank(gp, gtyp, gcnt, lambda k: b"\x00" * k)
                    buf[gp:gp + 12] = b"\x00" * 12
                if ge:
                    buf[g:g + 2] = b"\x00\x00"  # no entries; the next-IFD link after them reads as zero
                    buf[g + 2:g + 6] = b"\x00" * 4
                    hit = True
            elif tag == 33723 and cnt > 0:  # 2.209.0 D (#1856): IPTC
                blank(p, typ, cnt, lambda k: b"\x00" * k)
                hit = True
            elif tag == 700 and typ in (1, 7) and cnt > 0:
                size = cnt
                o = struct.unpack(e + "I", data[p + 8:p + 12])[0] if size > 4 else p + 8
                if 0 < o and o + size <= n:
                    fill = _PM_XMP_EMPTY if len(_PM_XMP_EMPTY) <= size else b""
                    buf[o:o + size] = fill + b" " * (size - len(fill))
                    hit = True
        cnt = struct.unpack(e + "H", data[off:off + 2])[0] if off + 2 <= n else 0
        nx = off + 2 + 12 * cnt
        off = struct.unpack(e + "I", data[nx:nx + 4])[0] if nx + 4 <= n else 0
    return (bytes(buf) if hit else None), taken


# ---- GIF (2.209.0 D, #1856) -------------------------------------------------------------------------------------------------
_PM_GIF_KEEP_APP = (b"NETSCAPE2.0", b"ANIMEXTS1.0")  # the loop setting of an animation


def _pm_gif_subs(data, p):
    """The end of the data sub-blocks starting at p (after the terminator); raises IndexError on a cut file."""
    while data[p]:
        p += data[p] + 1
    return p + 1


def _pm_gif(data, on):
    """A GIF without comment blocks and foreign application blocks (XMP); (None, "") when there is none or it is broken."""
    if not on:
        return None, ""
    try:
        p = 13 + (3 << ((data[10] & 7) + 1) if data[10] & 0x80 else 0)
        out, hit = bytearray(data[:p]), False
        while data[p] != 0x3B:
            if data[p] == 0x21:
                end = _pm_gif_subs(data, p + 2)
                drop = data[p + 1] == 0xFE or (data[p + 1] == 0xFF and data[p + 3:p + 14] not in _PM_GIF_KEEP_APP)
            elif data[p] == 0x2C:
                q = p + 10 + (3 << ((data[p + 9] & 7) + 1) if data[p + 9] & 0x80 else 0)
                end, drop = _pm_gif_subs(data, q + 1), False
            else:
                return None, ""
            if end > len(data):
                return None, ""
            if drop:
                hit = True
            else:
                out += data[p:end]
            p = end
        return (bytes(out) + data[p:] if hit else None), ""
    except IndexError:
        return None, ""
