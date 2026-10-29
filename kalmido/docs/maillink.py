"""2.424.0 B (#3450): invoice mails without a PDF, only a link "Download invoice" (Stripe, Paddle, Apple, Google, ...): the
documents mail input (docs/ingest.py docs_mail_import) follows such a link once and files the PDF it gets as a document.

 - Links: the <a href> of the HTML part (with the link text) and the bare URLs of the text part, at most ML_SCAN looked at.
   Taken (at most ML_LINKS per mail): a link to a known invoice host (ML_HOSTS, the host or a subdomain) whose text or URL
   speaks of an invoice / receipt / PDF, or any link whose text or URL says invoice / Rechnung / receipt / Beleg ... and
   that points to a PDF (the path ends in .pdf or the text says PDF).
 - Fetch (ml_get): https only, through the SSRF guard of the calendar subscriptions (cal_http): every address the host
   resolves to must be public -- no loopback, private, link-local (cloud metadata 169.254.169.254), ULA, CGNAT, multicast,
   reserved, also inside IPv4-mapped / NAT64 / 6to4 IPv6 -- checked at connect time on every hop and the socket connects
   to exactly the checked address; the admin allow-list of internal calendar hosts does NOT apply (allow is empty). At most
   5 redirects, never https -> http, a redirect to another host only over https; no proxy, no cookies, no credentials,
   ML_MAX_BYTES, ML_TIMEOUT per socket operation and ML_DEADLINE for the whole download. Only a 200 answer whose bytes
   start with %PDF- (and whose Content-Type is a PDF / binary one, or missing) counts.
 - No login, no form, no JavaScript, no second page followed (no scraping): an HTML page, a 401 / 403 or anything else is
   "needs a login" -- the mail itself then becomes the document, tagged ML_TAG (docs_mail_import).
Kalmido calls no language model here."""
import html.parser
import re
import secrets
import urllib.parse

from ..core.config import APP_NAME, APP_VERSION, MAX_FILE_MB
from ..core.db import now_iso
from ..core.i18n import N_
from ..calendars.subscriptions import CalError, cal_http

ML_LINKS = 3          # links followed per mail
ML_SCAN = 200         # links of one mail looked at
ML_MAX_BYTES = min(MAX_FILE_MB, 20) * 1024 * 1024
ML_TIMEOUT, ML_DEADLINE = 10, 25  # s per socket operation / for one download
ML_TAG = N_("Receipt link needs a login")
ML_UA = f"{APP_NAME}/{APP_VERSION} (receipt link)"
# invoice / receipt senders whose mails carry a download link instead of the PDF (the host or any subdomain of it)
ML_HOSTS = ("stripe.com", "paddle.com", "paddle.net", "apple.com", "google.com", "paypal.com", "gumroad.com",
            "lemonsqueezy.com", "fastspring.com", "chargebee.com", "recurly.com", "invoice.zoho.eu", "invoice.zoho.com",
            "sevdesk.de", "lexoffice.de", "debitoor.com", "billomat.net", "fastbill.com", "easybill.de")
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
    return any(h == k or h.endswith("." + k) for k in ML_HOSTS)


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


def ml_get(url, allow=frozenset()):
    """One download through the SSRF guard -> (status, headers, body, final url). The mail import never passes allow
    (public addresses only); the tests let their stub server on 127.0.0.1 through with it."""
    return cal_http(url, headers={"User-Agent": ML_UA, "Accept": "application/pdf, */*;q=0.1"}, allow=allow,
                    cross_redirects=True, max_bytes=ML_MAX_BYTES, timeout=ML_TIMEOUT, deadline=ML_DEADLINE)


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


def ml_collect(msg, get=None):
    """(links, [(index of the link, name, PDF bytes)]) of a mail: the invoice links found and what could be downloaded."""
    links, got = ml_links(msg), []
    for i, u in enumerate(links):
        try:
            got.append((i, *ml_fetch(u, get=get)))
        except CalError as e:
            print("docs: receipt link not taken", e.code, flush=True)  # the code only, never the link (it may carry a token)
    return links, got


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
