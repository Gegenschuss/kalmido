"""2.49.0 (#971): shorten a forwarded mail. A pure text function (no database, no request) so every path that takes in mails
can use it (tasks by e-mail now; filing mails with a customer / project later).

md_trim_forward(text) -> text: the forwarding header (marker line + From / Sent / To / Subject lines, German and English,
Gmail / Outlook / Apple Mail / Thunderbird) becomes ONE line "From <sender>, <date>"; the person's own words above it stay on
top; below it signatures, disclaimers and older quoted replies are cut. Text without a forwarding header is returned as it is."""
import re

# marker lines that open a forwarded message
MARKER_RE = re.compile(
    r"^\s*(?:[-_=*]{2,}\s*)?(?:forwarded message|begin forwarded message|original message|weitergeleitete nachricht|"
    r"anfang der weitergeleiteten nachricht|urspr(?:ü|ue)ngliche nachricht|message transf(?:é|e)r(?:é|e)|"
    r"mensaje reenviado|messaggio inoltrato|doorgestuurd bericht)\s*:?\s*(?:[-_=*]{2,})?\s*$", re.I)
HDR_RE = re.compile(r"^\s*\**(from|von|sent|gesendet|date|datum|to|an|cc|bcc|subject|betreff|reply-to|antwort an|de|envoy(?:é|e)|à|objet)\**\s*:\s*(.*)$", re.I)
FROM_KEYS, DATE_KEYS = ("from", "von", "de"), ("sent", "gesendet", "date", "datum", "envoyé", "envoye")
SUBJ_KEYS = ("subject", "betreff", "objet")
SEP_RE = re.compile(r"^\s*[_\-=*]{5,}\s*$")
# "On <date>, <name> wrote:" and friends (may wrap onto a second line)
QUOTE_RE = re.compile(r"^\s*(?:on .{5,300}wrote|am .{5,300}schrieb.{0,120}|le .{5,300}a (?:é|e)crit|el .{5,300}escribi(?:ó|o)|il .{5,300}ha scritto|op .{5,300}schreef.{0,100})\s*:\s*$", re.I)
QUOTE_HEAD_RE = re.compile(r"^\s*(?:on|am|le|el|il|op)\s.{3,300}$", re.I)
QUOTE_TAIL_RE = re.compile(r"^\s*.{0,120}(?:wrote|schrieb.{0,60}|a (?:é|e)crit|escribi(?:ó|o)|ha scritto|schreef.{0,60})\s*:\s*$", re.I)
SIGN_RE = re.compile(
    r"^\s*(?:--\s?|mit freundlichen gr(?:ü|ue)(?:ß|ss)en|freundliche gr(?:ü|ue)(?:ß|ss)e|viele gr(?:ü|ue)(?:ß|ss)e|beste gr(?:ü|ue)(?:ß|ss)e|"
    r"herzliche gr(?:ü|ue)(?:ß|ss)e|liebe gr(?:ü|ue)(?:ß|ss)e|gr(?:ü|ue)(?:ß|ss)e|best regards|kind regards|warm regards|regards|"
    r"sincerely|yours sincerely|cheers|many thanks|thanks and regards|sent from my .*|gesendet von meinem .*|von meinem .* gesendet|"
    r"get outlook for .*)\s*[,!.]?\s*$", re.I)
DISCLAIMER_RE = re.compile(
    r"confidential|intended recipient|privileged|disclaimer|this (?:e-?mail|message) (?:and any|may contain|is intended)|"
    r"vertraulich|haftungsausschluss|irrt(?:ü|ue)mlich|nicht f(?:ü|ue)r sie bestimmt|gesch(?:ü|ue)tzte informationen|"
    r"if you have received this|falls sie nicht der (?:richtige )?adressat", re.I)
MAX_HDR = 14


def _is_hdr(line):
    return HDR_RE.match(line) is not None


def _hdr_block(lines, i):
    """(fields, next index) of the header lines from i on (continuation lines are indented); fields = {key: value}."""
    f, n = {}, len(lines)
    last = None
    while i < n and len(f) < MAX_HDR:
        m = HDR_RE.match(lines[i])
        if m:
            last = m.group(1).lower()
            f.setdefault(last, m.group(2).strip())
        elif last and lines[i][:1] in (" ", "\t") and lines[i].strip():
            f[last] = (f[last] + " " + lines[i].strip()).strip()
        else:
            break
        i += 1
    return f, i


def _starts_block(lines, i):
    """A header block (without marker) starts at i: a From / Von line with at least two more header lines and a date or subject."""
    m = HDR_RE.match(lines[i])
    if not m or m.group(1).lower() not in FROM_KEYS:
        return False
    f, _ = _hdr_block(lines, i)
    return len(f) >= 3 and any(k in f for k in DATE_KEYS + SUBJ_KEYS)


def _sender(v):
    v = re.sub(r"\[mailto:[^\]]*\]|mailto:", "", v or "").replace("*", "").strip()
    m = re.match(r"^(.*?)\s*<([^>]*)>\s*$", v)
    if m:
        v = m.group(1).strip().strip('"\'').strip() or m.group(2).strip()
    return v.strip().strip('"\'').strip()


def _cut_quoted(lines):
    """Drops quoted older replies: lines with '>', 'On … wrote:', a second header block, 'Original Message'."""
    out = []
    n = len(lines)
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith(">"):
            continue
        if MARKER_RE.match(ln) or (_starts_block(lines, i) and any(x.strip() for x in out)):
            break
        if QUOTE_RE.match(ln) or (QUOTE_HEAD_RE.match(ln) and i + 1 < n and QUOTE_TAIL_RE.match(lines[i + 1]) and not QUOTE_TAIL_RE.match(ln)):
            break
        out.append(ln)
    while out and (not out[-1].strip() or SEP_RE.match(out[-1])):  # a separator line that opened the cut part
        out.pop()
    return out


def _cut_signature(lines):
    for i, ln in enumerate(lines):
        if SIGN_RE.match(ln):  # the pattern needs the whole line, so a greeting inside a sentence stays
            return lines[:i]
    return lines


def _drop_disclaimers(lines):
    paras, cur = [], []
    for ln in lines + [""]:
        if ln.strip():
            cur.append(ln)
        else:
            if cur:
                paras.append(cur)
            cur = []
            paras.append(None)
    out = []
    for p in paras:
        if p is None:
            out.append("")
        elif not (DISCLAIMER_RE.search(" ".join(p)) and len(" ".join(p)) < 2500):
            out.extend(p)
    return out


def md_trim_forward(text):
    """The shortened text, or text itself when it holds no forwarding header."""
    if not text:
        return text
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    n, start, hdr_at, f, end = len(lines), None, None, None, None
    for i in range(n):
        if MARKER_RE.match(lines[i]):
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and _is_hdr(lines[j]):
                start, hdr_at = i, j
                break
        elif _starts_block(lines, i):
            start, hdr_at = i, i
            if i and SEP_RE.match(lines[i - 1]):
                start = i - 1
            break
    if start is None:
        return text
    f, end = _hdr_block(lines, hdr_at)
    de = any(k in f for k in ("von", "gesendet", "datum", "betreff", "an"))
    before = lines[:start]
    while before and not before[-1].strip():
        before.pop()
    body = lines[end:]
    body = _cut_quoted(body)
    body = _cut_signature(body)
    body = _drop_disclaimers(body)
    body = "\n".join(body).strip("\n")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    who = _sender(next((f[k] for k in FROM_KEYS if k in f), ""))
    when = next((f[k] for k in DATE_KEYS if k in f), "").strip()
    head = (("Von " if de else "From ") + who + (", " + when if when else "")) if who else when
    parts = ["\n".join(before).strip("\n"), head, body]
    return "\n\n".join(p for p in parts if p).strip()
