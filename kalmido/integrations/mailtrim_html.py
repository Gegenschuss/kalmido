"""2.352.0 D (#2754): the shortened HTML view of a filed mail. A pure function (no database, no request): md_trim_html(src) -> src
with the forwarding header of a forwarded mail (Apple "Begin forwarded message", Gmail "---------- Forwarded message", Outlook
divRplyFwdMsg / "-----Original Message-----") replaced by ONE line "From <sender>, <date>", older quoted replies (blockquote,
gmail_quote, yahoo_quoted, moz-cite-prefix, the reply header of Outlook with everything below it) and signatures (gmail_signature,
a "-- " line with everything below it) taken out. The result is HTML text that still goes through the cleaner (mailview.mh_clean):
this function only decides what is left out and never lets anything through the cleaner would stop. Display only."""
import html as _h
import re
from html.parser import HTMLParser

from .mailtrim import DATE_KEYS, FROM_KEYS, HDR_RE, MARKER_RE, _hdr_block, _sender, md_trim_view  # noqa: F401 -- md_trim_view: for the hub

_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_RAW = frozenset(("script", "style"))
_BLOCK = frozenset("address article aside blockquote body dd div dl dt fieldset figure footer h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section table tr ul".split())
_QUOTE_CLS = re.compile(r"gmail_quote|yahoo_quoted|moz-cite-prefix|OutlookMessageHeader|protonmail_quote|zmail_extra|AppleOriginalContents", re.I)
_SIG_CLS = re.compile(r"gmail_signature|moz-signature|protonmail_signature", re.I)
_SIG_ID = re.compile(r"^(?:x_)?(?:signature|Signature)$|^x_x_?signature$", re.I)
_RPLY_ID = re.compile(r"divRplyFwdMsg|appendonsend", re.I)
MAX_NODES = 20000
MAX_DEPTH = 200    # 2.352.0 G (#2754): deeper markup -> the whole mail is shown (review M3)
TEXT_CAP = 4000    # 2.352.0 G (#2754): characters of a node's text looked at (header lines are short; review M3)


class _N:
    __slots__ = ("tag", "attrs", "raw", "kids", "txt", "tc")

    def __init__(self, tag=None, attrs=(), raw="", txt=None):
        self.tag, self.attrs, self.raw, self.kids, self.txt = tag, dict((k, v or "") for k, v in attrs), raw, [], txt
        self.tc = None  # 2.352.0 G (#2754): (text, cut) once per node, see _text


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _N("#root")
        self.stack = [self.root]
        self.n = 0

    def _add(self, node):
        self.n += 1
        if self.n > MAX_NODES:
            raise ValueError("too many nodes")
        self.stack[-1].kids.append(node)

    def handle_starttag(self, tag, attrs):
        node = _N(tag, attrs, self.get_starttag_text() or "")
        self._add(node)
        if tag not in _VOID:
            self.stack.append(node)
            if len(self.stack) > MAX_DEPTH:
                raise ValueError("too deep")

    def handle_startendtag(self, tag, attrs):
        self._add(_N(tag, attrs, self.get_starttag_text() or ""))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self._add(_N(txt=data, raw="raw" if self.stack[-1].tag in _RAW else ""))


def _ser(n, out):
    if n.txt is not None:
        out.append(n.txt if n.raw else _h.escape(n.txt, quote=False))
        return
    if n.tag == "#root":
        for k in n.kids:
            _ser(k, out)
        return
    out.append(n.raw)
    if n.tag in _VOID:
        return
    for k in n.kids:
        _ser(k, out)
    out.append(f"</{n.tag}>")


def _text(n):
    """(plain text of a node with a line break at <br> and block borders (so header lines stay separate lines), cut): at most
    TEXT_CAP characters, cut = there was more. 2.352.0 G (#2754, review M3): computed once per node from the children's capped
    texts, so a deeply nested large mail costs linear time, not depth x size."""
    if n.tc is not None:
        return n.tc
    if n.txt is not None:
        t = "" if n.raw else n.txt
        n.tc = (t[:TEXT_CAP], len(t) > TEXT_CAP)
        return n.tc
    if n.tag in _RAW or n.tag == "br":
        n.tc = ("" if n.tag in _RAW else "\n", False)
        return n.tc
    blk = n.tag in _BLOCK
    out, size, cut = (["\n"] if blk else []), (1 if blk else 0), False
    for k in n.kids:
        t, c = _text(k)
        out.append(t)
        size += len(t)
        if c or size > TEXT_CAP:
            cut = True
            break
    if blk and not cut:
        out.append("\n")
    s = "".join(out)
    n.tc = (s[:TEXT_CAP], cut or len(s) > TEXT_CAP)
    return n.tc


def _lines(n):
    """The non-empty lines of a node's text; when the text was cut, the last (partial) line is left out and None ends the list."""
    t, cut = _text(n)
    ls = t.replace("\xa0", " ").split("\n")
    if cut:
        ls = ls[:-1]
    out = [re.sub(r"\s+", " ", x).strip() for x in ls if x.strip()]
    return out + [None] if cut else out


def _cls(n):
    return n.attrs.get("class", "")


def _is_quote(n):
    return n.tag == "blockquote" or bool(_QUOTE_CLS.search(_cls(n))) or bool(_RPLY_ID.search(n.attrs.get("id", "")))


def _is_sig(n):
    return bool(_SIG_CLS.search(_cls(n))) or bool(_SIG_ID.match(n.attrs.get("id", ""))) or n.attrs.get("data-smartmail") == "gmail_signature"


def _head_line(lines):
    """"From <sender>, <date>" from the header lines of a forwarded mail, or ""."""
    f, _ = _hdr_block([x for x in lines if not MARKER_RE.match(x)], 0)
    if not f:
        return ""
    de = any(k in f for k in ("von", "gesendet", "datum", "betreff", "an"))
    who = _sender(next((f[k] for k in FROM_KEYS if k in f), ""))
    when = next((f[k] for k in DATE_KEYS if k in f), "").strip()
    return (("Von " if de else "From ") + who + (", " + when if when else "")) if who else when


def _hdr_only(lines):
    return None not in lines and all(MARKER_RE.match(x) or HDR_RE.match(x) or re.fullmatch(r"[-_=*\s]*", x) for x in lines)


def _starts_marker(n):
    ls = _lines(n)
    return bool(ls) and ls[0] is not None and bool(MARKER_RE.match(ls[0]))


def _find_head(kids):
    """Index of the first child that opens a forwarding header (marker line, Outlook reply header, header lines), or -1."""
    for i, k in enumerate(kids):
        if k.txt is not None:
            continue
        if _RPLY_ID.search(k.attrs.get("id", "")) or (k.tag != "br" and _starts_marker(k)):
            return i
        ls = _lines(k)
        if k.tag != "br" and len(ls) >= 3 and _hdr_only(ls[:3]) and HDR_RE.match(ls[0]) and ls[0].split(":")[0].strip("* ").lower() in FROM_KEYS:
            return i
    return -1


def _forward(kids):
    """(kids after the forwarding header was folded into one line, found): the header run (marker / header children,
    separators, empty ones) becomes a paragraph; a wrapper that opens with the marker is unwrapped first."""
    i = _find_head(kids)
    if i < 0:
        return kids, False
    k = kids[i]
    if k.tag in ("blockquote", "div", "section") and not _RPLY_ID.search(k.attrs.get("id", "")) and _starts_marker(k) and len(_lines(k)) > 1:
        # a wrapper (Apple blockquote, Gmail quote div) that opens with the marker: its children are the header + the content
        inner, found = _forward(k.kids)
        if found:
            return kids[:i] + inner + kids[i + 1:], True
    j, head = i, []
    while j < len(kids):
        c = kids[j]
        if c.txt is not None:
            if c.txt.strip() and not _hdr_only([x.strip() for x in c.txt.split("\n") if x.strip()]):
                break
            head += [x.strip() for x in c.txt.split("\n") if x.strip()]
        elif c.tag in ("br", "hr", "meta"):
            pass
        else:
            ls = _lines(c)
            if ls and not _hdr_only(ls):
                break
            head += ls
        j += 1
    line = _head_line(head)
    p = _N("p", (("class", "hbmfwd"),), "<p class=\"hbmfwd\">")
    p.kids.append(_N(txt=line))
    return kids[:i] + ([p] if line else []) + kids[j:], True


def _clean(n, fwd):
    """Takes quotes and signatures out below n (a forwarding wrapper has been unwrapped before)."""
    kids, found = (_forward(n.kids) if not fwd else (n.kids, True))
    fwd = fwd or found
    out, cut = [], False
    for k in kids:
        if cut:
            break
        if k.txt is not None:
            if re.match(r"^\s*--\s*$", k.txt) or re.match(r"^\s*-- ?\n", k.txt):
                cut = True  # a "-- " signature line: it and everything below goes
                continue
            out.append(k)
            continue
        if _is_sig(k):
            continue
        if _is_quote(k):
            if _RPLY_ID.search(k.attrs.get("id", "")):
                break  # the Outlook reply header opens the older mails: everything below goes
            continue
        _clean(k, fwd)
        out.append(k)
    n.kids, n.tc = out, None


def md_trim_html(src):
    """The shortened HTML text of src, or src itself when nothing could be left out (or it could not be read)."""
    if not src or not src.strip():
        return src
    try:
        t = _Tree()
        t.feed(src)
        t.close()
        _clean(t.root, False)
        out = []
        _ser(t.root, out)
    except Exception:  # noqa: BLE001 -- strange markup or too big: the whole mail is shown
        return src
    res = "".join(out)
    return res if re.sub(r"<[^>]*>", "", res).strip() or "<img" in res.lower() else src
