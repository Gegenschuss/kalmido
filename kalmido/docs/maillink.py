"""2.424.0 B (#3450): invoice mails without a PDF, only a link "Download invoice" (Stripe, Paddle, Apple, Google, ...): the
documents mail input (docs/ingest.py docs_mail_import) follows such a link once and files the PDF it gets as a document.

 - Links: the <a href> of the HTML part (with the link text) and the bare URLs of the text part, at most ML_SCAN looked at.
   Taken (at most ML_LINKS per mail): a link to a known invoice host (ML_HOSTS, exactly that host) whose text or URL
   speaks of an invoice / receipt / PDF, or any link whose text or URL says invoice / Rechnung / receipt / Beleg ... and
   that points to a PDF (the path ends in .pdf or the text says PDF).
 - Fetch (ml_get): https only, through the SSRF guard of the calendar subscriptions (cal_http): every address the host
   resolves to must be public -- no loopback, private, link-local (cloud metadata 169.254.169.254), ULA, CGNAT, multicast,
   reserved, also inside IPv4-mapped / NAT64 / 6to4 IPv6 -- checked at connect time on every hop and the socket connects
   to exactly the checked address; the admin allow-list of internal calendar hosts does NOT apply (allow is empty). At most
   5 redirects, never https -> http, a redirect to another host only over https; no proxy, no cookies, no credentials,
   ML_MAX_BYTES, ML_TIMEOUT per socket operation, ML_DEADLINE for the whole download and ML_MAIL_DEADLINE for all the
   downloads of one mail (2.424.0 B2: also the connect and header phase). Only a 200 answer whose bytes
   start with %PDF- (and whose Content-Type is a PDF / binary one, or missing) counts.
 - No login, no form, no JavaScript, no second page followed (no scraping): an HTML page, a 401 / 403 or anything else is
   "needs a login" -- the mail itself then becomes the document, tagged ML_TAG (docs_mail_import).
2.424.0 B2 (#3450, review): the downloads run before the mail's database transaction (docs/ingest.py docs_mail_prefetch),
at most ML_HOUR_LINKS downloads and ML_HOUR_EML mails filed without a file per document address and hour (ml_budget).
Kalmido calls no language model here."""
import html.parser
import re
import secrets
import time
import urllib.parse

from ..core.config import APP_NAME, APP_VERSION, MAX_FILE_MB
from ..core.db import now_iso
from ..core.i18n import N_
from ..calendars.subscriptions import CalError, cal_http

ML_LINKS = 3          # links followed per mail
ML_SCAN = 200         # links of one mail looked at
ML_MAX_BYTES = min(MAX_FILE_MB, 20) * 1024 * 1024
ML_TIMEOUT, ML_DEADLINE = 10, 25  # s per socket operation / for one download
ML_MAIL_DEADLINE = 40  # 2.424.0 B2 (#3450): s for all the downloads of one mail
ML_HOUR_LINKS, ML_HOUR_EML = 30, 60  # 2.424.0 B2 (#3450): per document address and hour: downloads / mails filed without a file
ML_TAG = N_("Receipt link needs a login")
ML_UA = f"{APP_NAME}/{APP_VERSION} (receipt link)"
# invoice / receipt hosts whose mails carry a download link instead of the PDF (exactly these hosts). 2.424.0 B2 (#3450,
# review): only the hosts that serve the invoice itself -- no whole provider domains (google.com, apple.com, paypal.com
# with every subdomain: any spam with "Invoice" could make the server fetch from them); others need words + PDF
ML_HOSTS = ("invoice.stripe.com", "pay.stripe.com", "my.paddle.com", "app.lemonsqueezy.com", "app.gumroad.com",
            "invoice.zoho.eu", "invoice.zoho.com")
ML_KW = re.compile(r"invoice|rechnung|receipt|quittung|beleg|facture|fattura|factura|factuur|faktura", re.I)
_PDF_TYPES = ("application/pdf", "application/x-pdf", "application/octet-stream", "binary/octet-stream", "application/download",
              "application/force-download", "")
_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]{3,2000}", re.I)


class _Links(html.parser.HTMLParser):
    """(href, text) of every <a> of an HTML body."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self._cur = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "a" and len(self.out) < ML_SCAN:
            href = next((v for k, v in attrs if k == "href" and v), None)
            self._cur = [href.strip(), []] if href else None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._cur is not None:
            self.out.append((self._cur[0], " ".join(" ".join(self._cur[1]).split())[:200]))
            self._cur = None


def _host_known(host):
    h = (host or "").lower().rstrip(".")
    return h in ML_HOSTS


def ml_pick(url, text=""):
    """True when (url, link text) looks like the download of an invoice PDF (see the module text)."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if p.scheme.lower() != "https" or not p.hostname or p.username or p.password:
        return False
    path = urllib.parse.unquote(p.path or "").lower()
    kw = bool(ML_KW.search(text or "") or ML_KW.search(urllib.parse.unquote(url)))
    pdf = path.endswith(".pdf") or path.endswith("/pdf") or "pdf" in (text or "").lower()
    if _host_known(p.hostname):
        return kw or pdf
    return kw and pdf


def ml_links(msg):
    """The invoice download links of an email.message.EmailMessage (in the order of the mail, each once), at most ML_LINKS."""
    cands = []
    for part in msg.walk():
        if part.is_multipart() or (part.get_content_disposition() or "").lower() == "attachment":
            continue
        ct = part.get_content_type()
        if ct not in ("text/html", "text/plain"):
            continue
        try:
            txt = part.get_content()
        except Exception:  # noqa: BLE001 -- a broken part has no links
            continue
        if not isinstance(txt, str):
            continue
        if ct == "text/html":
            lp = _Links()
            try:
                lp.feed(txt[:2_000_000])
                lp.close()
            except Exception:  # noqa: BLE001
                pass
            cands += lp.out
        else:
            for m in _URL_RE.finditer(txt[:2_000_000]):
                if len(cands) >= 2 * ML_SCAN:
                    break
                line = txt[max(0, txt.rfind("\n", 0, m.start())):m.start()]  # the words before the URL on its line
                cands.append((m.group(0).rstrip(".,;:!?"), line.strip()[-200:]))
    out, seen = [], set()
    for href, text in cands[:2 * ML_SCAN]:
        href = href.replace("&amp;", "&")
        if href in seen or len(href) > 2000 or any(ch.isspace() or ord(ch) < 32 for ch in href):
            continue
        seen.add(href)
        if ml_pick(href, text):
            out.append(href)
            if len(out) >= ML_LINKS:
                break
    return out


def ml_get(url, allow=frozenset(), until=None):
    """One download through the SSRF guard -> (status, headers, body, final url). The mail import never passes allow
    (public addresses only); the tests let their stub server on 127.0.0.1 through with it. until: the time.monotonic()
    point all the downloads of the mail end at (cal_http until: also the connect and header phase)."""
    return cal_http(url, headers={"User-Agent": ML_UA, "Accept": "application/pdf, */*;q=0.1"}, allow=allow,
                    cross_redirects=True, max_bytes=ML_MAX_BYTES, timeout=ML_TIMEOUT, deadline=ML_DEADLINE, until=until)


def _name(hdrs, final, url):
    cd = (hdrs.get("Content-Disposition") if hdrs else "") or ""
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)|filename=\"?([^\";]+)", cd, re.I)
    raw = urllib.parse.unquote((m.group(1) or m.group(2)) if m else "").strip()
    if not raw:
        for u in (final, url):
            last = urllib.parse.unquote(urllib.parse.urlsplit(u or "").path.rsplit("/", 1)[-1])
            if last.lower().endswith(".pdf"):
                raw = last
                break
    raw = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", raw).strip(" .-")[:120]
    if not raw:
        raw = "invoice"
    return raw if raw.lower().endswith(".pdf") else raw + ".pdf"


def ml_fetch(url, get=None, https_only=True):
    """(file name, PDF bytes) of an invoice link, or raises CalError (code: config, auth, not_found, http, too_large,
    timeout, network, tls, redirect, blocked, not_pdf). get: the download (default ml_get); https_only=False only for the
    tests (a plain-http stub server; the SSRF guard stays)."""
    p = urllib.parse.urlsplit(str(url or ""))
    if (https_only and p.scheme.lower() != "https") or p.scheme.lower() not in ("http", "https") or not p.hostname \
            or p.username or p.password:
        raise CalError("config")
    st, hdrs, data, final = (get or ml_get)(url)
    if https_only and urllib.parse.urlsplit(final or url).scheme.lower() != "https":
        raise CalError("redirect")
    if st != 200:
        raise CalError("http", st)
    ctype = ((hdrs.get("Content-Type") if hdrs else "") or "").split(";", 1)[0].strip().lower()
    if ctype not in _PDF_TYPES or not bytes(data or b"").lstrip()[:5] == b"%PDF-":
        raise CalError("not_pdf")
    return _name(hdrs, final, url), bytes(data)


def ml_collect(msg, get=None, limit=ML_LINKS, links=None):
    """(links, [(index of the link, name, PDF bytes)]) of a mail: the invoice links found and what could be downloaded
    (the first `limit` of them, all within ML_MAIL_DEADLINE). get: the download (default ml_get with the mail's deadline)."""
    links = ml_links(msg) if links is None else links
    until = time.monotonic() + ML_MAIL_DEADLINE
    fetch = get or (lambda u: ml_get(u, until=until))
    got = []
    for i, u in enumerate(links[:max(0, limit)]):
        if time.monotonic() >= until:
            print("docs: receipt link not taken timeout", flush=True)
            break
        try:
            got.append((i, *ml_fetch(u, get=fetch)))
        except CalError as e:
            print("docs: receipt link not taken", e.code, flush=True)  # the code only, never the link (it may carry a token)
    return links, got


def ml_budget(c, token, kind, n=1):
    """2.424.0 B2 (#3450): how many of n downloads (kind "links") / mails filed without a file (kind "eml") the document
    address `token` may still have this hour (ML_HOUR_LINKS / ML_HOUR_EML), taken from its budget at once. Counted on
    the doc_mail row (hits_hour = the hour, hits_links / hits_eml); call inside system_ctx, the caller commits."""
    col, cap = ("hits_links", ML_HOUR_LINKS) if kind == "links" else ("hits_eml", ML_HOUR_EML)
    r = c.execute(f"SELECT hits_hour, {col} AS used FROM doc_mail WHERE token=? FOR UPDATE", (token,)).fetchone()
    if not r or n <= 0:
        return 0
    hour = now_iso()[:13]
    used = int(r["used"] or 0) if r["hits_hour"] == hour else 0
    k = max(0, min(n, cap - used))
    if r["hits_hour"] != hour:
        c.execute("UPDATE doc_mail SET hits_hour=?, hits_links=0, hits_eml=0 WHERE token=?", (hour, token))
    if k:
        c.execute(f"UPDATE doc_mail SET {col}={col}+? WHERE token=?", (k, token))
    if k < n:
        print("docs: mail budget spent", kind, n - k, flush=True)  # a count only, never the address or a link
    return k


def ml_mail_name(msg):
    """The file name of the mail filed as a document: its subject (cleaned), .eml."""
    subj = re.sub(r"^\s*((fwd?|wg|aw|re)\s*:\s*)+", "", str(msg.get("Subject", "") or "").replace("\n", " "), flags=re.I)
    subj = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", subj).strip(" .-")[:80]
    return (subj or "mail") + ".eml"


def ml_token_new(c, uid, org):
    """A new forwarding address token of uid's documents space (org None = the private one); the old one stops working.
    Used by the documents settings (POST /api/docs/mail) and the office settings (POST /api/office/receipt-mail)."""
    tok = "d" + secrets.token_urlsafe(14).replace("-", "x").replace("_", "y")
    c.execute("DELETE FROM doc_mail WHERE user_id=? AND org_id IS NOT DISTINCT FROM ?", (uid, org))
    c.execute("INSERT INTO doc_mail(token, user_id, org_id, created_at) VALUES(?,?,?,?)", (tok, uid, org, now_iso()))
    return tok
