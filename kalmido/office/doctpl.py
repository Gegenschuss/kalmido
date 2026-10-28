"""2.93.0 A (#1927): document templates with variables, documents as PDF filed with client / project, signature by customer link.

Templates (office_doc_templates): kind contract | confirmation | nda | other, name, language, text with {{variables}} and
"can be signed". Three samples (service contract, order confirmation, non-disclosure agreement) in German and English live
in the code (DT_STARTERS) and become an own template with "Use sample". Documents (office_gen_docs) are made from a template
for a client (required), optionally a project list and a quotation of the same client. A draft keeps the text WITH its
variables (the preview fills them from the current client / project / quotation / company, unknown or empty ones are
marked); "Finish" fills them for good (unknown / empty -> empty), freezes the text (body_hash = SHA-256 of it), writes the
PDF with the office PDF writer's parts (office/pdf.py) and files it sealed into the office documents space (a folder per
client, docs_ingest). After that the text never changes: a new version is a new document ("Edit a copy").
A finished document whose template allowed it can be signed by the customer through a link (office/signoff.py, kind
document): afterwards the signed PDF (the original + a signature block: name, time UTC, SHA-256 of the text, "simple
electronic signature") is filed next to the original (signed_node_id) -- by the next read of an admin, in their own
context (the public page never writes into the documents space).

Every route: office_gate + office_org with the admin of the office area (like the travel expenses; members 403, agents
and kids 403, objects of another area 404). Texts (template / document body) encrypted at rest (orgcrypt). Kalmido never
calls a language model here; the variables are replaced by a plain regular expression, never evaluated."""
import hashlib
import re
import urllib.parse

from flask import Response, g, jsonify, request

from ..core.config import app, APP_VERSION, OFFICE_DIR
from ..core.pg import insert_id, system_ctx, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc
from ..core.access import Denied, need_list, vis_sql
from ..core.errors import BadInput
from .model import office_gate, office_org, office_settings, pb_cl_sql, pb_owner, trial_flag
from .doctpl_samples import DMA_SAMPLES  # 2.117.0 B (#2283)
from .doclang import DOC_LANGS, doc_lg  # 2.185.0 C (#2520)
from .oftref import GD_KIND, oft_renamed  # 2.351.0 A (#2823)

DT_KINDS = (("contract", N_("Contract")), ("confirmation", N_("Order confirmation")), ("nda", N_("Non-disclosure agreement")),
            ("other", N_("Other")), ("letter", N_("Letter")))  # 2.153.0 (#2028): letter templates (office/letters.py)
DT_KIND_KEYS = tuple(k for k, _ in DT_KINDS)
DT_STATUS = ("draft", "final", "signed", "declined")
DT_NOTE = N_("Sample text, no legal advice.")
# the variables (one source: the editor's buttons, the preview and the finishing use this list)
DT_VARS = (("client.name", N_("Client name")), ("client.address", N_("Client address")), ("client.contact", N_("Contact person")),
           ("project.title", N_("Project")), ("offer.number", N_("Quotation number")), ("offer.date", N_("Quotation date")),
           ("offer.total", N_("Quotation total (gross, incl. VAT)")), ("company.name", N_("Company name")), ("company.address", N_("Company address")),
           ("today", N_("Today")),
           # 2.296.0 C (#3165): net / gross named (offer.total stays the gross alias), the payment term of the office settings
           ("offer.net", N_("Quotation net (excl. VAT)")), ("offer.gross", N_("Quotation gross (incl. VAT)")),
           ("payment.days", N_("Payment term in days")))
DT_VAR_KEYS = tuple(k for k, _ in DT_VARS)
DT_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]{1,40})\s*\}\}")
# 2.296.0 C (#3165): [[ ... ]] = an optional part of a line, left out as a whole when a variable in it has no value
DT_OPT_RE = re.compile(r"\[\[(.*?)\]\]")
DT_GAP = "\x00"  # where an empty variable was taken out (closing up the spaces / punctuation around it)
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
NAME_MAX, TITLE_MAX, BODY_MAX = 200, 300, 60000
LIST_MAX = 500

# ---------------------------------------------------------------- the samples (German and English, kept short)
DT_STARTERS = {
    "contract": {
        "de": ("Vertrag über Leistungen", """# Vertrag über Leistungen

Zwischen {{company.name}}[[, {{company.address}}]] (Auftragnehmer)
und {{client.name}}[[, {{client.address}}]] (Auftraggeber)

## 1. Gegenstand
Der Auftragnehmer erbringt für den Auftraggeber Leistungen[[ im Projekt {{project.title}}]][[ nach dem Angebot {{offer.number}}]][[ vom {{offer.date}}]].

## 2. Vergütung
Die Vergütung richtet sich nach dem Angebot[[ und beträgt {{offer.net}} zzgl. USt]]. Rechnungen sind innerhalb von {{payment.days}} Tagen ohne Abzug zahlbar.

## 3. Mitwirkung
Der Auftraggeber stellt die nötigen Unterlagen und Informationen rechtzeitig bereit.[[ Ansprechpartner beim Auftraggeber: {{client.contact}}.]]

## 4. Nutzungsrechte
Die Nutzungsrechte gehen im vereinbarten Umfang mit der vollständigen Zahlung über.

## 5. Schlussbestimmungen
Änderungen und Ergänzungen bedürfen der Textform. Ist eine Bestimmung unwirksam, bleibt der Vertrag im Übrigen wirksam.

Datum: {{today}}"""),
        "en": ("Service agreement", """# Service agreement

Between {{company.name}}[[, {{company.address}}]] (contractor)
and {{client.name}}[[, {{client.address}}]] (client)

## 1. Subject
The contractor provides services to the client[[ in the project {{project.title}}]][[ according to quotation {{offer.number}}]][[ of {{offer.date}}]].

## 2. Fee
The fee follows the quotation[[ and amounts to {{offer.net}} plus VAT]]. Invoices are payable within {{payment.days}} days without deduction.

## 3. Cooperation
The client provides the documents and information needed in good time.[[ Contact person at the client: {{client.contact}}.]]

## 4. Rights of use
The rights of use pass in the agreed scope upon full payment.

## 5. Final provisions
Changes and additions must be made in text form. Should a provision be invalid, the rest of the agreement remains valid.

Date: {{today}}"""),
    },
    "confirmation": {
        "de": ("Auftragsbestätigung", """# Auftragsbestätigung

Sehr geehrte Damen und Herren,

vielen Dank für Ihren Auftrag. Wir bestätigen den Auftrag[[ nach unserem Angebot {{offer.number}}]][[ vom {{offer.date}}]][[ für das Projekt {{project.title}}]].

- Auftraggeber: {{client.name}}
- Ansprechpartner: {{client.contact}}
- Auftragssumme: {{offer.net}} zzgl. USt

Es gelten die Bedingungen des Angebots. Bitte prüfen Sie die Angaben und melden Sie sich, wenn etwas nicht stimmt.

Mit freundlichen Grüßen
{{company.name}}"""),
        "en": ("Order confirmation", """# Order confirmation

Dear Sir or Madam,

thank you for your order. We confirm the order[[ according to our quotation {{offer.number}}]][[ of {{offer.date}}]][[ for the project {{project.title}}]].

- Client: {{client.name}}
- Contact person: {{client.contact}}
- Order total: {{offer.net}} plus VAT

The terms of the quotation apply. Please check the details and let us know if anything is not right.

Kind regards
{{company.name}}"""),
    },
    "nda": {
        "de": ("Geheimhaltungsvereinbarung", """# Geheimhaltungsvereinbarung

Zwischen {{company.name}}[[, {{company.address}}]]
und {{client.name}}[[, {{client.address}}]]

## 1. Vertrauliche Informationen
Vertraulich sind alle Informationen, die eine Partei der anderen im Rahmen der Zusammenarbeit[[ im Projekt {{project.title}}]] mitteilt und die als vertraulich bezeichnet oder erkennbar vertraulich sind.

## 2. Pflichten
Die Parteien nutzen vertrauliche Informationen nur für das Projekt, geben sie nicht an Dritte weiter und schützen sie mit angemessener Sorgfalt.

## 3. Ausnahmen
Die Pflichten gelten nicht für Informationen, die öffentlich bekannt sind, die eine Partei schon vorher rechtmäßig kannte oder die sie aufgrund einer gesetzlichen Pflicht offenlegen muss.

## 4. Dauer
Die Vereinbarung gilt ab {{today}} und endet drei Jahre nach dem Ende der Zusammenarbeit."""),
        "en": ("Non-disclosure agreement", """# Non-disclosure agreement

Between {{company.name}}[[, {{company.address}}]]
and {{client.name}}[[, {{client.address}}]]

## 1. Confidential information
Confidential information means all information that one party shares with the other in the cooperation[[ in the project {{project.title}}]] and that is marked as confidential or is recognisably confidential.

## 2. Obligations
The parties use confidential information only for the project, do not pass it on to third parties and protect it with reasonable care.

## 3. Exceptions
The obligations do not apply to information that is public, that a party already knew lawfully or that it must disclose by law.

## 4. Term
This agreement applies from {{today}} and ends three years after the end of the cooperation."""),
    },
}


from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def _iid(v, name):
    if isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", name))
    try:
        return int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name)) from None


def _text(v, name, mx):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", name))
    return CTRL_RE.sub("", re.sub(r"[\r\n\t]+", " ", v)).strip()[:mx]  # one line (a title also names files)


def dt_body(v):
    """A template / document text: line breaks kept (\\r dropped), control characters out, at most BODY_MAX."""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "body"))
    v = CTRL_RE.sub("", v.replace("\r\n", "\n").replace("\r", "\n"))
    if len(v) > BODY_MAX:
        raise BadInput(tr("The text is too long"))
    return v.strip("\n")


def dt_lang(c, oid, v=None):
    """'de' | 'en': the given one, else the office's document language (office/doclang.py: settings lang).
    2.185.0 C (#2520): every app language (doclang.DOC_LANGS)."""
    if v in DOC_LANGS:
        return v
    if v not in (None, ""):
        raise BadInput(tr("Invalid value: {0}", "lang"))
    return doc_lg(office_settings(c, oid).get("lang"))


def dt_kind_label(k, lg=None):
    return tr(dict(DT_KINDS).get(k, "Other"), lg=lg)


# ---------------------------------------------------------------- the variables
def _pack(c, oid):
    from .packs import office_pack_for
    s = office_settings(c, oid)
    return office_pack_for(s) or {}


def dt_company(c, oid, lang):
    """The printed company of the office area (like a quotation's print model): name, lines, contact / register / bank
    lines, logo path, accent colour."""
    import os
    from .ledger import ofx_company, ofx_company_print
    s = office_settings(c, oid)
    co = ofx_company_print(ofx_company(c, oid), s.get("company") or {}, lang, _pack(c, oid))
    logo = None
    if s.get("logo"):
        p = os.path.join(OFFICE_DIR, str(int(oid)), os.path.basename(s["logo"]))
        logo = p if os.path.isfile(p) else None
    color = s.get("color") or ""
    co["logo_path"] = logo
    co["logo_size"], co["logo_pos"] = s.get("logo_size") or "m", s.get("logo_pos") or "r"  # 2.406.0 (#3501)
    co["color"] = color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#2f5d8a"
    return co


def dt_client(c, oid, cid):
    """Client cid of the office area (dict) or 404."""
    r = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (_iid(cid, "client_id"),)).fetchone()
    if not r:
        raise Denied(404)
    return dict(r)


def dt_list_ok(c, oid, lid):
    """A project list for a document: the admin must see it (need_list) and it belongs to the office area (an
    organisation's list; a personal office: the owner's private lists) -- else 404."""
    lid = _iid(lid, "list_id")
    need_list(c, lid, write=False)
    r = c.execute("SELECT id, name, org_id, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    owner = pb_owner(c, oid)
    if not r or (r["org_id"] != oid if owner is None else (r["org_id"] is not None or r["owner_id"] != owner)):
        raise Denied(404)
    return dict(r)


def dt_offer(c, oid, did, cid):
    """A quotation of the office area for client cid, or 404 (another client: 404 as well)."""
    from .docs import doc_row
    r = doc_row(c, oid, _iid(did, "doc_id"))
    if r["kind"] != "offer" or r["client_id"] != cid:
        raise Denied(404)
    return r


def _addr(cl, sep=", "):
    """The client's address in one line: street, extra line, zip city, country (2.97.0 B #1951: the fixed fields only; the
    old free address was split into them, see team/clients.cdn_backfill)."""
    parts = [x for x in ((cl.get("street") or "").strip(), (cl.get("address_extra") or "").strip(),
                         " ".join(y for y in ((cl.get("zip") or "").strip(), (cl.get("city") or "").strip()) if y)) if x]
    if parts and (cl.get("country") or "").strip() and (cl.get("country") or "").strip().upper() != "DE":
        parts.append(cl["country"].strip())
    return sep.join(parts)  # 2.114.4 C (#2280): sep="\n" for the document variable (own lines)


def dt_values(c, oid, lang, client_id=None, list_id=None, doc_id=None):
    """{variable: value} for a document of client / project list / quotation (missing objects -> '')."""
    from .calc import fmt_money
    from .contacts_cl import fk_contact
    from .docs import _fmt_date, odoc_render
    pack = _pack(c, oid)
    co = dt_company(c, oid, lang)
    v = {k: "" for k in DT_VAR_KEYS}
    v["company.name"] = co.get("name") or ""
    v["company.address"] = ", ".join(str(x) for x in co.get("lines") or [] if str(x).strip())
    v["today"] = _fmt_date(local_now().date().isoformat(), pack)
    v["payment.days"] = str(int(office_settings(c, oid).get("payment_days") or 14))  # 2.296.0 C (#3165): was a fixed 14 in the samples
    if client_id:
        cl = dt_client(c, oid, client_id)
        k = fk_contact(c, cl["id"])
        v["client.name"] = cl["name"] or ""
        v["client.address"] = _addr(cl, "\n")  # 2.114.4 C (#2280): street / zip city on own lines
        v["client.contact"] = (k["name"] if k else "") or cl.get("contact") or ""
        if cl.get("payment_terms_days"):  # 2.296.0 F (#3165): the client's own term, as its invoices use it
            v["payment.days"] = str(int(cl["payment_terms_days"]))
        if doc_id:
            r = dt_offer(c, oid, doc_id, cl["id"])
            m = odoc_render(c, r["id"], oid)
            t = m.get("totals") or {}
            tot = t.get("gross") if t.get("gross") is not None else t.get("net")
            v["offer.number"] = r["number"] or ""
            v["offer.date"] = _fmt_date(r["date"], pack) if r["date"] else ""
            v["offer.total"] = fmt_money(tot, lang, r["currency"] or "EUR") if tot is not None else ""
            v["offer.gross"] = v["offer.total"]  # 2.296.0 C (#3165)
            v["offer.net"] = fmt_money(t["net"], lang, r["currency"] or "EUR") if t.get("net") is not None else ""
            if not list_id:
                v["project.title"] = r["project_title"] or ""
    if list_id:
        v["project.title"] = dt_list_ok(c, oid, list_id)["name"] or ""
    # a value never brings variables of its own (no second round of replacing) nor markup: "# ", "- ", "* " at its start
    # get a non-breaking space (looks the same, dt_blocks reads no heading / list item)
    # 2.114.4 C (#2280): line breaks in a value stay (each line cleaned on its own, the markup guard applies per line)
    return {k: "\n".join(re.sub(r"^([#*-]+) ", "\\1\u00a0", " ".join(ln.split())) for ln in str(x).replace("{{", "{").replace("}}", "}").splitlines() if ln.strip())
            for k, x in v.items()}


def dt_fill(text, values, mark=False):
    """(text with the variables replaced, [keys unknown or empty]). mark=True (preview, draft PDF): an unknown / empty
    variable stays as {{key}} (marked there), else it is left out (the PDF).
    2.296.0 C (#3165): left out = the text closes up around it (no double space, no " ." / " ,"); a line that held only
    empty variables (or a list line all of whose variables are empty) goes as a whole; [[ ... ]] is an optional part that
    goes as a whole when one of its variables is empty (mark=True keeps it, without the brackets, the empty ones marked).
    A multi-line value (client.address) keeps its lines only alone on its line, in running text it becomes "a, b"."""
    miss, got = [], [0]

    def var(m, alone):
        k = m.group(1)
        val = values.get(k) if k in DT_VAR_KEYS else None
        if val:
            got[0] += 1
            return val if alone else ", ".join(x.strip() for x in str(val).split("\n") if x.strip())
        if k not in miss:
            miss.append(k)
        return "{{" + k + "}}" if mark else DT_GAP

    def opt(m):
        part = m.group(1)
        if not DT_VAR_RE.search(part):
            return m.group(0)  # 2.296.0 F (#3165): [[ ... ]] without a variable is the person's own text ([[1]], [[Name]])
        if mark or all(values.get(k) and k in DT_VAR_KEYS for k in DT_VAR_RE.findall(part)):
            return DT_VAR_RE.sub(lambda x: var(x, False), part)
        return DT_GAP  # an optional part without its values: its keys are no missing details (it is left out by design)

    out = []
    for ln in (text or "").split("\n"):
        got[0] = 0
        alone = bool(DT_VAR_RE.fullmatch(ln.strip()))
        filled = DT_VAR_RE.sub(lambda m: var(m, alone), DT_OPT_RE.sub(opt, ln))
        if DT_GAP not in filled:
            out.append(filled)
            continue
        s = filled.lstrip()
        if not s.replace(DT_GAP, "").strip() or (s[:2] in ("- ", "* ") and not got[0]):
            continue  # nothing but empty variables, or a list line none of whose variables has a value
        ind = filled[:len(filled) - len(s)]
        out.append(ind + _dt_close(s))
    return "\n".join(out), miss


_DT_GAP_RUN = re.compile(r"[ \t]*\x00(?:[ \t]*\x00)*[ \t]*")


def _dt_close(s):
    """2.357.0 D (#3220): closes up a line around each gap only (was the whole line: an own ", (" or double space
    elsewhere in the line went as well). Spaces at the gap become one (none at the line's ends or before a
    punctuation mark); a comma left before a punctuation mark, a doubled comma and an emptied (...) go too."""
    while True:
        m = _DT_GAP_RUN.search(s)
        if not m:
            return s.strip()
        pre, post = s[:m.start()], s[m.end():]
        p, n = pre[-1:], post[:1]
        if p and n and p in "([" and n in ")]":
            pre, post = pre[:-1].rstrip(" \t"), post[1:].lstrip(" \t")
            p, n = pre[-1:], post[:1]
        if not pre.strip():
            pre, post = "", post.lstrip(",;").lstrip(" \t")
        elif not n:
            pre = pre.rstrip(",;")
        elif n in ".,;:!?" and p in ",;:":
            pre = pre[:-1]
        elif n == "(" and p == ",":
            pre = pre[:-1] + " "
        elif p not in "([" and n not in ".,;:!?)]":
            pre += " "
        s = pre + post


def dt_miss_labels(miss):
    """2.296.0 C (#3165): the missing details by name ("Quotation date"), an unknown variable as {{key}}."""
    names = dict(DT_VARS)
    return [tr(names[k]) if k in names else "{{" + k + "}}" for k in miss]


def dt_blocks(text):
    """The light markup of a text -> [(kind, text)]: 'h1' (# ...), 'h2' (## ...), 'li' (- ...), 'p' (lines of a
    paragraph joined by line breaks). Nothing else is interpreted."""
    out, para = [], []

    def flush():
        if para:
            out.append(("p", "\n".join(para)))
            para.clear()
    for ln in (text or "").split("\n"):
        s = ln.strip()
        if not s:
            flush()
        elif s.startswith("## "):
            flush()
            out.append(("h2", s[3:].strip()))
        elif s.startswith("# "):
            flush()
            out.append(("h1", s[2:].strip()))
        elif s.startswith("- ") or s.startswith("* "):
            flush()
            out.append(("li", s[2:].strip()))
        else:
            para.append(s)
    flush()
    return out


def dt_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- the PDF (office/pdf.py's parts: fonts, page, writer)
DT_MISS_COLOR = "#c62828"  # 2.296.0 C (#3165)


def dt_pdf(c, oid, d, signed=None, client=None):
    """The PDF (bytes, PDF/A-3b) of document d (a decrypted office_gen_docs row of a finished document): letterhead,
    the client's address, title, the text, signature lines (signable documents); signed = {name, at, hash} adds the
    block of the simple electronic signature."""
    from . import pdf as P
    P = P.pdf_paper_ns(office_settings(c, oid).get("paper"))  # 2.357.0 A (#3156): the office's paper size
    lang = doc_lg(d.get("lang"))  # 2.185.0 C (#2520)
    co = dt_company(c, oid, lang)
    cl = client
    if cl is None and d.get("client_id"):
        try:
            cl = dt_client(c, oid, d["client_id"])
        except Denied:
            cl = None
    accent = co.get("color") or "#2f5d8a"
    logo = None
    images = {}
    if co.get("logo_path"):
        try:
            with open(co["logo_path"], "rb") as fh:
                logo = P.pdf_image_object(fh.read(16 * 1024 * 1024))
        except OSError:
            logo = None
        if logo:
            images["Logo"] = logo
    title = d.get("title") or dt_kind_label(d.get("kind"), lang)
    draft = tr("Draft", lg=lang).upper() if d.get("status") == "draft" else ""  # a preview of a draft says so on every page
    if d.get("trial"):  # 2.144.10 A (#2576): a trial document says SAMPLE / MUSTER instead (one mark) and carries it diagonally
        draft = tr("SAMPLE", lg=lang)  # the watermark word (de MUSTER)
    body_sz, lh = 9.6, 9.6 * 1.42
    mk = d.get("status") == "draft"  # 2.296.0 C (#3165): a draft shows the variables without a value in red
    # 2.357.0 C (#3158): the own signature picture of the person who finished the document (sign_uid, set only by that
    # person); a draft / trial document keeps its room free
    sig_uid = d.get("sign_uid")
    sig = None
    if sig_uid:
        from .letters import lt_sig_pic
        sig = lt_sig_pic(c, oid, sig_uid)
        if sig and not draft:  # also no picture on a trial document (SAMPLE)
            images["Sig"] = sig
    pages = []
    # 2.357.0 C (#3182): an own letterhead lies under the document as under letters and the other office PDFs (letters.lt_pdf)
    from .letterhead import bp_letter
    blh = bp_letter(c, oid)
    geo = P.bp_geometry(blh) if blh else None
    BPD = geo["bp"] if geo else None
    PL, PCW, PAT, PNT = (geo["l"], geo["cw"], geo["addr_top"], geo["next_top"]) if geo else (P.PDF_L, P.PDF_CW, P.PDF_ADDR_TOP, P.PDF_NEXT_TOP)
    hide_head = bool(BPD and BPD["hide_head"])
    foot = P.pdf_footer_cols(co)  # 2.114.4 A (#2284): the same columns as a quotation (address, contact, register, bank)
    foot_fit = P.p3f_fit(foot, PCW)  # 2.296.0 A (#3164): laid out once; the body ends above the real footer height
    foot_h = P.p3f_foot_h(foot_fit)
    PBX = P.pdf_body_bottom(foot_h)
    body_bottom = [(BPD["bottom"][i] if BPD["hide_footer"] else min(BPD["bottom"][i], PBX)) if BPD else PBX for i in (0, 1)]

    def dt_line(page, x, y, s, size, bold, mark):
        """2.296.0 C (#3165): one line of the text; mark=True (a draft) draws a left {{key}} in red (the final PDF leaves it out)."""
        if not mark or "{{" not in s:
            page.text(x, y, s, size, bold)
            return
        pos = 0
        for m in list(DT_VAR_RE.finditer(s)) + [None]:
            for seg, col in ((s[pos:m.start() if m else len(s)], P.C_INK), (m.group(0) if m else "", DT_MISS_COLOR)):
                if seg:
                    page.text(x, y, seg, size, bold, col)
                    x += P.pdf_text_width(seg, size, bold)
            pos = m.end() if m else pos

    def new_page(first):
        p = P._Page()
        if first:
            if hide_head:  # 2.357.0 C (#3182): the letterhead brings logo, name and fold marks
                pass
            elif logo:
                fw, fh, left = P.pdf_logo_frame(co)  # 2.406.0 (#3501): size and side from the office settings
                lw, lh_ = P.pdf_logo_fit(logo, fw, fh)  # 2.357.0 B (#3179): at most 200 dpi
                p.image("Logo", PL if left else PL + PCW - lw, P.PDF_TOP + 2 * P.MM, lw, lh_)
            else:
                nl = (co.get("name_lines") or [co.get("name") or ""])[:3]  # 2.99.0 D (#2188): the name lines one under the other
                for i, ln in enumerate(nl):
                    p.text(PL + PCW, P.PDF_TOP + 4 * P.MM + i * 18, ln, 15, True, P.C_INK, align="r", spacing=1.2)
                p.rect(PL + PCW - 12 * P.MM, P.PDF_TOP + 4 * P.MM + 24 + (len(nl) - 1) * 18, 12 * P.MM, 2.2, accent)
            for y in (() if hide_head else P.PDF_MARKS):  # 2.357.0 A (#3156): of the paper size
                p.line(5 * P.MM, y, 9 * P.MM, y, 0.4, P.C_RULE)
        else:  # 2.294.0 (#3155): the draft / sample word only as the diagonal watermark, no more in the head
            hy = PNT - 18 * P.MM if BPD else 12 * P.MM  # 2.357.0 C (#3182): above the letterhead's top margin (as letters.lt_pdf)
            if hy >= 4 * P.MM:
                p.text(PL, hy + 2, title, 8, False, P.C_INK2)
                if not hide_head:
                    p.text(PL + PCW, hy, co.get("name") or "", 9, True, P.C_INK, align="r", spacing=0.6)
                p.line(PL, hy + 12.5 * P.MM, PL + PCW, hy + 12.5 * P.MM, 0.5, accent)
        pages.append(p)
        return p

    page = new_page(True)
    # the address field (sender line + recipient) and the date on the right
    sender = " · ".join(dict.fromkeys(str(x) for x in [co.get("name") or ""] + list(co.get("lines") or []) if str(x).strip()))
    sender = P.pdf_sender_line(sender, co.get("name"), (co.get("name_lines") or [""])[0])  # 2.296.0 E (#3170): the address has priority
    y = PAT
    page.text(PL, y, sender, 7, False, P.C_INK2)
    page.line(PL, y + 11, PL + P.PDF_ADDR_W, y + 11, 0.5, P.C_RULE2)
    addr = []
    if cl:
        addr = [cl["name"]] + [x for x in _addr(cl).split(", ") if x]
    yy = y + 16
    for ln in [w for x in addr[:8] for w in P.pdf_wrap(x, body_sz, P.PDF_ADDR_W)]:  # 2.217.0 B (#2800): wraps within the address field
        page.text(PL, yy, ln, body_sz)
        yy += lh
    info_x = PL + P.PDF_ADDR_W + 8 * P.MM
    info_w = PCW - P.PDF_ADDR_W - 8 * P.MM
    when = (d.get("final_at") or d.get("updated_at") or iso(now_utc()))[:10]
    from .docs import _fmt_date
    page.text(info_x, y + 2, tr("Date", lg=lang), 8.6, False, P.C_INK2)
    page.text(info_x, y + 2, _fmt_date(when, _pack(c, oid)), 8.6, True, P.C_INK, align="r", width=info_w)
    y = max(PAT + P.PDF_ADDR_H, yy + 4)  # 2.217.0 B (#2800): a longer address pushes the body down

    def room(h):
        nonlocal page, y
        if y + h > body_bottom[len(pages) > 1]:
            page = new_page(False)
            y = PNT
    # 2.357.0 C (#3182): the room the end needs: the signature lines (16 + 30 to the line, two caption lines: 74 pt, was
    # reserved with 62 -> the lines ran into the footer), else the own signature picture with the name under it
    sig_h = 0.0
    if sig:
        sig_h = 14 * P.MM if d.get("sign") else 16 * P.MM
        sig_w = min(60 * P.MM, sig[0] * sig_h / sig[1])
        sig_h = sig_w * sig[1] / sig[0]
    end_h = (16 + max(30, sig_h + 4) + 28) if d.get("sign") else (sig_h + 6 + lh + 4 if sig else 0)
    blocks = dt_blocks(d.get("body") or "")
    if not blocks or blocks[0][0] != "h1":  # the title as heading when the text brings none
        blocks.insert(0, ("h1", title))
    for i, (k, t) in enumerate(blocks):
        last = i == len(blocks) - 1
        if k == "h1":
            hl = P.pb_wrap(t.upper(), 15, PCW, True, 0.8)  # 2.357.0 C (#3182): a long title wraps (ran out of the page)
            room(34 + (len(hl) - 1) * 19 + lh * 2)
            for j, s in enumerate(hl):
                page.text(PL, y + 6 + j * 19, s, 15, True, P.C_INK, spacing=0.8)
            y += (len(hl) - 1) * 19
            page.line(PL, y + 6 + 21, PL + 14 * P.MM, y + 6 + 21, 1.6, accent)
            y += 36
        elif k == "h2":
            room(22 + lh * 2)  # a heading never stays alone at the end of a page
            y += 6
            for s in P.pdf_wrap(t, 10.4, PCW, True):
                dt_line(page, PL, y, s, 10.4, True, mk)
                y += 10.4 * 1.42
            y += 2
        elif k == "li":
            ls = P.pdf_wrap(t, body_sz, PCW - 14)
            for j, s in enumerate(ls):
                room(lh)
                if j == 0:
                    page.text(PL + 3, y, "•", body_sz, False, P.pdf_text_color(accent))  # 2.296.0 D (#3172)
                dt_line(page, PL + 14, y, s, body_sz, False, mk)
                y += lh
            y += 2
        else:
            ls = P.pdf_wrap(t, body_sz, PCW)
            # 2.357.0 C (#3182): the last paragraph (the greeting) stays with the signature: the whole of a short one, else its
            # last two lines
            g0 = (0 if len(ls) <= 4 else len(ls) - 2) if last and end_h else -1
            for j, s in enumerate(ls):
                room(lh + ((len(ls) - j) * lh + lh * 0.6 + end_h - lh if j == g0 else 0))
                dt_line(page, PL, y, s, body_sz, False, mk)
                y += lh
            y += lh * 0.6
    if d.get("sign"):  # the lines for a signature on paper (both parties)
        room(end_h)
        half = (PCW - 28) / 2
        yl = y + 16 + max(30, sig_h + 4)
        if sig and not draft:  # 2.357.0 C (#3158): the own signature above the line of the own side
            page.image("Sig", PL, yl - 2 - sig_h, sig_w, sig_h)
        for x0, who in ((PL, co.get("name") or ""), (PL + half + 28, cl["name"] if cl else "")):
            page.line(x0, yl, x0 + half, yl, 0.6, P.C_INK)
            page.text(x0, yl + 3, tr("Place, date, signature", lg=lang), 7.6, False, P.C_INK2)
            if who:
                page.text(x0, yl + 13, who, 7.6, False, P.C_INK2)
        y = yl + 28
    elif sig:  # 2.357.0 C (#3158): no lines: the signature picture and the name of the person under the text
        from .letters import lt_sig_name
        room(end_h)
        if not draft:
            page.image("Sig", PL, y + 2, sig_w, sig_h)
        y += sig_h + 6
        page.text(PL, y, lt_sig_name(c, oid, sig_uid), body_sz)
        y += lh + 4
    if signed:
        rows = [(tr("Signed by", lg=lang), signed.get("name") or ""), (tr("Time (UTC)", lg=lang), (signed.get("at") or "")[:19].replace("T", " ")),
                (tr("SHA-256 of the text", lg=lang), signed.get("hash") or "")]
        bh = P.qac_sig_block_h(rows)
        room(bh + 8)
        y += 8
        P.qac_sig_block(page, y, rows, tr("Simple electronic signature", lg=lang), tr("Signed through a customer link of {0}.", co.get("name") or "", lg=lang), accent)  # 2.99.0 C (#2195): shared with accepted quotations
        y += bh
    total = len(pages)
    for n, p in enumerate(pages, 1):
        # 2.114.4 A (#2282): the page count only from two pages on
        pg_txt = tr("Page {0} of {1}", n, total, lg=lang) if total >= 2 else ""
        if BPD and BPD["hide_footer"]:  # 2.357.0 C (#3182): the letterhead has its own footer: only the page count under the body
            if pg_txt:
                p.text(PL + PCW, BPD["bottom"][n > 1] + 3 * P.MM, pg_txt, 6.8, False, P.C_INK2, align="r")
            continue
        P.pdf_draw_footer(p, foot, pg_txt, foot_fit, foot_h, PL, PCW)
    meta = {"when": now_utc(), "producer": f"Kalmido v{APP_VERSION}"}
    if draft:  # 2.294.0 (#3155): a draft too (was a head line), not only a trial document
        for p in pages:
            p.mark(draft)
    if BPD:
        P.bp_finish(pages, BPD)
    return P.pdf_write(pages, images, title=title, author=co.get("name") or "", meta=meta)


# ---------------------------------------------------------------- filing into the documents space
def dt_file(c, oid, uid, d, data, signed=False):
    """Files PDF data of document d into the office documents space (a folder per client; sealed like every upload,
    files/store.py fs_put) -> the node id. ext_id makes it idempotent (a second call returns the first file)."""
    from ..docs import store as S
    from ..docs.ingest import docs_ingest
    owner = pb_owner(c, oid)
    who, org = (owner, None) if owner is not None else (uid, oid)
    title = (d.get("title") or dt_kind_label(d.get("kind"))).replace("/", "-")[:150]
    name = f"{title} ({tr('signed')}).pdf" if signed else f"{title}.pdf"
    meta = {"ext_id": f"gendoc:{d['id']}:{'signed' if signed else 'final'}", "date": local_now().date().isoformat(),
            "type": dt_kind_label(d.get("kind")), "text": d.get("body") or ""}
    nid = docs_ingest(c, who, org, name, data, "application/pdf", "office", meta)
    if d.get("client_id"):
        try:
            cl = dt_client(c, oid, d["client_id"])
            node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
            fid = S.folder_by_name(c, node, who, cl["name"]) if node else None
            if fid and node["parent_id"] != fid:
                S.move_to_folder(c, node, fid)
        except Denied:
            pass
    return nid


def dt_kick():
    try:
        from ..docs.ingest import docs_kick
        docs_kick()
    except Exception:  # noqa: BLE001 -- the recognition starts with the next upload anyway
        pass


def dt_signed_sync(c, oid, uid, rows):
    """The signed PDF of signed documents not filed yet (the customer's page never writes into the documents space):
    rendered from the frozen text + the signature protocol and filed by this admin. -> True when something was filed."""
    from .signoff import sig_dec
    done = False
    for d in rows:
        if d["status"] != "signed" or d["signed_node_id"]:
            continue
        s = c.execute("SELECT * FROM office_signoffs WHERE gen_doc_id=? AND org_id=? AND state='accepted' ORDER BY id DESC LIMIT 1",
                      (d["id"], oid)).fetchone()
        if not s:
            continue
        s = sig_dec(c, s)
        x = oc_dec_fields(c, oid, "office_gen_docs", d)
        data = dt_pdf(c, oid, x, signed={"name": s["signer_name"], "at": s["signed_at"], "hash": s["doc_hash"]})
        nid = dt_file(c, oid, uid, x, data, signed=True)
        c.execute("UPDATE office_gen_docs SET signed_node_id=? WHERE id=? AND org_id=? AND signed_node_id IS NULL", (nid, d["id"], oid))
        done = True
    if done:
        c.commit()
        dt_kick()
    return done


# ---------------------------------------------------------------- templates
def dt_tpl_public(r):
    return {"id": r["id"], "kind": r["kind"], "kind_label": dt_kind_label(r["kind"]), "name": r["name"], "lang": r["lang"], "body": r["body"],
            "sign": int(r["sign"] or 0), "archived": int(r["archived"] or 0), "created_at": r["created_at"], "updated_at": r["updated_at"]}


def dt_tpl(c, oid, tid):
    r = c.execute("SELECT * FROM office_doc_templates WHERE id=? AND org_id=?", (_iid(tid, "id"), oid)).fetchone()
    if not r:
        raise Denied(404)
    return oc_dec_fields(c, oid, "office_doc_templates", r)


def dt_tpl_clean(c, oid, b, cur=None):
    out = {}
    if "kind" in b or cur is None:
        k = b.get("kind") or "other"
        if k not in DT_KIND_KEYS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        out["kind"] = k
    if "name" in b or cur is None:
        out["name"] = _text(b.get("name"), "name", NAME_MAX)
        if not out["name"]:
            raise BadInput(tr("Please enter a name"))
    if "lang" in b or cur is None:
        out["lang"] = dt_lang(c, oid, b.get("lang"))
    if "body" in b or cur is None:
        out["body"] = dt_body(b.get("body"))
    if "sign" in b or cur is None:
        out["sign"] = 1 if b.get("sign", 1) else 0
    if "archived" in b and cur is not None:
        out["archived"] = 1 if b.get("archived") else 0
    return out


@app.get("/api/office/doc-templates")
def dt_tpl_list():
    """?archived=1 also the archived ones -> {templates, kinds, vars, lang, note}."""
    c, uid, oid = _ctx()
    arch = request.args.get("archived") == "1"
    rows = c.execute("SELECT * FROM office_doc_templates WHERE org_id=?" + ("" if arch else " AND archived=0") + " ORDER BY lower(name), id LIMIT ?",
                     (oid, LIST_MAX)).fetchall()
    return jsonify(templates=[dt_tpl_public(oc_dec_fields(c, oid, "office_doc_templates", r)) for r in rows], **dt_meta(c, oid))


def dt_meta(c, oid):
    return {"kinds": [{"key": k, "label": tr(n)} for k, n in DT_KINDS], "vars": [{"key": k, "label": tr(n)} for k, n in DT_VARS],
            "lang": dt_lang(c, oid), "note": tr(DT_NOTE)}


# 2.357.0 D (#3219): a small business (section 19, no VAT) gets the samples with the total instead of "net plus VAT"; only
# when a sample is taken -- templates already saved stay as they are
DT_SMALL = (("{{offer.net}} zzgl. USt", "{{offer.gross}}"), ("{{offer.net}} plus VAT", "{{offer.gross}}"))


def dt_sample_body(c, oid, text):
    if not office_settings(c, oid).get("small_business"):
        return text
    for a, b in DT_SMALL:
        text = text.replace(a, b)
    return text


@app.get("/api/office/doc-templates/starters")
def dt_starters_get():
    """?lang=de|en (default: the office's document language) -> {starters: [{key, kind, name, lang, body}], note}."""
    c, uid, oid = _ctx()
    lg = dt_lang(c, oid, request.args.get("lang") or None)
    # 2.117.0 B (#2283): the letters of doctpl_samples after the contract samples; legal = the picker says to check it
    sl = "de" if lg == "de" else "en"  # 2.185.0 C (#2520): the samples are de / en; other languages take the English one
    return jsonify(starters=[{"key": k, "kind": k, "kind_label": dt_kind_label(k), "name": v[sl][0], "lang": lg, "body": dt_sample_body(c, oid, v[sl][1]),
                              "legal": int(k != "confirmation")}
                             for k, v in DT_STARTERS.items()] +
                   [{"key": k, "kind": v["kind"], "kind_label": dt_kind_label(v["kind"]), "name": v[sl][0], "lang": lg, "body": v[sl][1],
                     "legal": v["legal"]} for k, v in DMA_SAMPLES.items()], note=tr(DT_NOTE), lang=lg)


@app.post("/api/office/doc-templates")
def dt_tpl_post():
    """{kind, name, lang, body, sign} or {starter: contract|confirmation|nda|<a key of DMA_SAMPLES>, lang?} (a sample as own template) -> 201."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if b.get("starter") is not None:
        st = DT_STARTERS.get(b.get("starter")) if isinstance(b.get("starter"), str) else None
        sm = DMA_SAMPLES.get(b.get("starter")) if isinstance(b.get("starter"), str) and not st else None  # 2.117.0 B (#2283)
        if not st and not sm:
            raise BadInput(tr("Invalid value: {0}", "starter"))
        lg = dt_lang(c, oid, b.get("lang"))
        sl = "de" if lg == "de" else "en"  # 2.185.0 C (#2520): English sample for nl / fr / es / it
        if sm:
            b = {"kind": sm["kind"], "name": sm[sl][0], "lang": lg, "body": sm[sl][1], "sign": sm["sign"]}
        else:
            b = {"kind": b["starter"], "name": st[sl][0], "lang": lg, "body": dt_sample_body(c, oid, st[sl][1]), "sign": 0 if b["starter"] == "confirmation" else 1}
    row = dt_tpl_clean(c, oid, b)
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_doc_templates", row)
    tid = insert_id(c, f"INSERT INTO office_doc_templates({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)
    c.commit()
    return jsonify(dt_tpl_public(dt_tpl(c, oid, tid))), 201


@app.patch("/api/office/doc-templates/<int:tid>")
def dt_tpl_patch(tid):
    c, uid, oid = _ctx()
    cur = dt_tpl(c, oid, tid)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = dt_tpl_clean(c, oid, b, cur)
    if row:
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_doc_templates", row)
        c.execute(f"UPDATE office_doc_templates SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [tid, oid])
        bump(c)
        c.commit()
    return jsonify(dt_tpl_public(dt_tpl(c, oid, tid)))


@app.delete("/api/office/doc-templates/<int:tid>")
def dt_tpl_delete(tid):
    """Archives a template (its documents stay); POST .../restore takes it back (the client's undo)."""
    c, uid, oid = _ctx()
    dt_tpl(c, oid, tid)
    c.execute("UPDATE office_doc_templates SET archived=1, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), tid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/office/doc-templates/<int:tid>/restore")
def dt_tpl_restore(tid):
    c, uid, oid = _ctx()
    dt_tpl(c, oid, tid)
    c.execute("UPDATE office_doc_templates SET archived=0, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), tid, oid))
    bump(c)
    c.commit()
    return jsonify(dt_tpl_public(dt_tpl(c, oid, tid)))


# ---------------------------------------------------------------- documents
def dt_doc(c, oid, gid):
    r = c.execute("SELECT * FROM office_gen_docs WHERE id=? AND org_id=?", (_iid(gid, "id"), oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def dt_doc_public(c, oid, r, names=None, sigs=None):
    """A document for the app (decrypted; names = {clients, lists, offers} lookups; sigs = {gen_doc_id: newest link})."""
    from .signoff import sig_public
    d = oc_dec_fields(c, oid, "office_gen_docs", r)
    names = names or dt_names(c, oid, [d])
    s = (sigs or {}).get(d["id"]) if sigs is not None else c.execute(
        "SELECT * FROM office_signoffs WHERE gen_doc_id=? AND org_id=? ORDER BY id DESC LIMIT 1", (d["id"], oid)).fetchone()
    return {"id": d["id"], "template_id": d["template_id"], "kind": d["kind"], "kind_label": dt_kind_label(d["kind"]), "title": d["title"],
            "body": d["body"], "body_hash": d["body_hash"], "lang": d["lang"] if "lang" in d else "", "sign": int(d.get("sign") or 0),
            "client_id": d["client_id"], "client_name": names["clients"].get(d["client_id"], ""), "list_id": d["list_id"],
            "list_name": names["lists"].get(d["list_id"], ""), "doc_id": d["doc_id"], "offer_number": names["offers"].get(d["doc_id"], ""),
            "node_id": d["node_id"], "signed_node_id": d["signed_node_id"], "status": d["status"], "archived": int(d["archived"] or 0),
            "created_at": d["created_at"], "updated_at": d["updated_at"], "final_at": d.get("final_at"),
            "trial": bool(d.get("trial")),  # 2.144.10 A (#2576)
            # 2.357.0 C (#3158): with the own signature picture (sign_mine: of the person asking; only that person may keep it)
            "sign_image": bool(d.get("sign_uid")), "sign_mine": bool(d.get("sign_uid")) and d.get("sign_uid") == dt_me(),
            "signoff": sig_public(c, s) if s else None}


def dt_me():
    """2.357.0 C (#3158): the signed-in person (None outside a request)."""
    from .letters import lt_uid
    return lt_uid()


def dt_sign_uid(v, uid):
    """2.357.0 C (#3158): sign_image of a request -> the sign_uid to store: the asking person's own id or None (never
    someone else's signature: the column is only ever set to the person who sets it)."""
    return uid if v and uid else None


def dt_names(c, oid, rows):
    cids = sorted({r["client_id"] for r in rows if r["client_id"]})
    lids = sorted({r["list_id"] for r in rows if r["list_id"]})
    dids = sorted({r["doc_id"] for r in rows if r["doc_id"]})
    out = {"clients": {}, "lists": {}, "offers": {}}
    if cids:
        out["clients"] = {r["id"]: r["name"] for r in c.execute(f"SELECT id, name FROM clients WHERE id IN ({','.join('?' * len(cids))}) AND {pb_cl_sql(c, oid)}", cids)}
    if lids:  # only lists the admin (still) sees
        uid = g.user["id"]
        out["lists"] = {r["id"]: r["name"] for r in c.execute(f"SELECT id, name FROM lists WHERE id IN ({','.join('?' * len(lids))}) AND id IN {vis_sql()}",
                                                              lids + [uid, uid])}
    if dids:
        out["offers"] = {r["id"]: r["number"] or "" for r in c.execute(f"SELECT id, number FROM office_docs WHERE org_id=? AND id IN ({','.join('?' * len(dids))})", [oid] + dids)}
    return out


def dt_refs(c, oid, b, cur=None):
    """The client / list / quotation columns of body b (partial with cur): client required, list and quotation optional;
    a quotation must belong to the client (a client change drops the old one). Objects of another area 404."""
    out = {}
    cid = b.get("client_id") if "client_id" in b else (cur["client_id"] if cur else None)
    if cid in (None, "", 0):
        raise BadInput(tr("Choose a client"))
    cl = dt_client(c, oid, cid)
    out["client_id"] = cl["id"]
    if "list_id" in b or cur is None:
        lid = b.get("list_id")
        out["list_id"] = dt_list_ok(c, oid, lid)["id"] if lid not in (None, "", 0) else None
    # another client without a quotation named: the old quotation (of the old client) is dropped, not a 404
    did = b.get("doc_id") if "doc_id" in b else (cur["doc_id"] if cur and cur["client_id"] == cl["id"] else None)
    out["doc_id"] = dt_offer(c, oid, did, cl["id"])["id"] if did not in (None, "", 0) else None
    return out


@app.get("/api/office/gen-docs")
def dt_docs_list():
    """?client_id=&list_id=&status=&archived=1 -> {docs, clients, lists, offers, templates, kinds, vars, note}: the documents
    (newest first) and what the dialog offers (clients of the area, lists the admin sees in it, quotations)."""
    c, uid, oid = _ctx()
    sql, args = "SELECT * FROM office_gen_docs WHERE org_id=?", [oid]
    if request.args.get("archived") != "1":
        sql += " AND archived=0"
    for k in ("client_id", "list_id"):
        if request.args.get(k):
            sql += f" AND {k}=?"
            args.append(_iid(request.args.get(k), k))
    st = request.args.get("status") or ""
    if st:
        if st not in DT_STATUS:
            raise BadInput(tr("Invalid value: {0}", "status"))
        sql += " AND status=?"
        args.append(st)
    if request.args.get("trial") in ("0", "1"):  # 2.144.10 A (#2576): only trial / only real documents
        sql += " AND trial=?"
        args.append(int(request.args["trial"]))
    rows = c.execute(sql + " ORDER BY id DESC LIMIT ?", args + [LIST_MAX]).fetchall()
    if dt_signed_sync(c, oid, uid, rows):
        rows = c.execute(sql + " ORDER BY id DESC LIMIT ?", args + [LIST_MAX]).fetchall()
    names = dt_names(c, oid, rows)
    sigs = {}
    if rows:
        ids = [r["id"] for r in rows]
        for s in c.execute(f"SELECT * FROM office_signoffs WHERE org_id=? AND gen_doc_id IN ({','.join('?' * len(ids))}) ORDER BY id", [oid] + ids):
            sigs[s["gen_doc_id"]] = s  # the newest wins
    out = {"docs": [dt_doc_public(c, oid, r, names, sigs) for r in rows]}
    if request.args.get("brief") != "1":
        owner = pb_owner(c, oid)
        lsql = "l.org_id IS NULL AND l.owner_id=?" if owner is not None else "l.org_id=?"
        out["clients"] = [{"id": r["id"], "name": r["name"]} for r in
                          c.execute(f"SELECT id, name FROM clients WHERE {pb_cl_sql(c, oid)} AND archived=0 AND deleted_at IS NULL ORDER BY lower(name) LIMIT ?", (LIST_MAX,))]
        out["lists"] = [{"id": r["id"], "name": r["name"]} for r in
                        c.execute(f"SELECT l.id, l.name FROM lists l WHERE l.id IN {vis_sql()} AND {lsql} AND l.archived=0 AND l.is_inbox=0 "
                                  "ORDER BY lower(l.name) LIMIT ?", (uid, uid, owner if owner is not None else oid, LIST_MAX))]
        out["offers"] = [{"id": r["id"], "number": r["number"] or "", "client_id": r["client_id"], "project_title": r["project_title"] or "",
                          "status": r["status"], "trial": bool(r["trial"])} for r in  # 2.144.10 A (#2576)
                         c.execute("SELECT id, number, client_id, project_title, status, trial FROM office_docs WHERE org_id=? AND kind='offer' "
                                   "AND client_id IS NOT NULL ORDER BY id DESC LIMIT ?", (oid, LIST_MAX))]
        tpls = c.execute("SELECT * FROM office_doc_templates WHERE org_id=? AND archived=0 ORDER BY lower(name), id LIMIT ?", (oid, LIST_MAX)).fetchall()
        out["templates"] = [dt_tpl_public(oc_dec_fields(c, oid, "office_doc_templates", r)) for r in tpls]
        out.update(dt_meta(c, oid))
    return jsonify(out)


@app.get("/api/office/gen-docs/<int:gid>")
def dt_doc_get(gid):
    c, uid, oid = _ctx()
    r = dt_doc(c, oid, gid)
    if dt_signed_sync(c, oid, uid, [r]):
        r = dt_doc(c, oid, gid)
    return jsonify(dt_doc_public(c, oid, r))


@app.post("/api/office/gen-docs")
def dt_doc_post():
    """A new draft {template_id?, client_id, list_id?, doc_id?, title?, body?, sign?} (the body defaults to the template's
    text with its variables) or {copy_of: id} (a new draft with the frozen text of a finished document). 201."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if b.get("copy_of") not in (None, ""):
        src = oc_dec_fields(c, oid, "office_gen_docs", dt_doc(c, oid, b["copy_of"]))
        b = {"template_id": src["template_id"], "client_id": src["client_id"], "list_id": src["list_id"], "doc_id": src["doc_id"],
             "title": src["title"], "body": src["body"], "sign": src.get("sign"), "lang": src.get("lang"), "kind": src["kind"],
             "trial": src.get("trial"),  # 2.144.10 A (#2576): a copy of a trial document stays one
             "sign_image": bool(src.get("sign_uid")) and src.get("sign_uid") == uid}  # 2.357.0 C (#3158): only the own signature
    t = dt_tpl(c, oid, b["template_id"]) if b.get("template_id") not in (None, "") else None
    row = dt_refs(c, oid, b)
    row["template_id"] = t["id"] if t else None
    row["kind"] = t["kind"] if t else (b.get("kind") if b.get("kind") in DT_KIND_KEYS else "other")
    row["lang"] = dt_lang(c, oid, b.get("lang") or (t["lang"] if t else None))
    row["title"] = _text(b.get("title"), "title", TITLE_MAX) or (t["name"] if t else "") or dt_kind_label(row["kind"], row["lang"])
    row["body"] = dt_body(b["body"]) if b.get("body") is not None else (t["body"] if t else "")
    row["sign"] = (1 if b.get("sign") else 0) if "sign" in b and b.get("sign") is not None else (int(t["sign"] or 0) if t else 0)
    if b.get("sign_image"):  # 2.357.0 C (#3158)
        row["sign_uid"] = dt_sign_uid(b.get("sign_image"), uid)
    # 2.144.10 A (#2576): a trial document when asked for or when its quotation is one (set at creation only)
    row["trial"] = 1 if trial_flag(b.get("trial")) or (row["doc_id"] and c.execute(
        "SELECT trial FROM office_docs WHERE id=? AND org_id=?", (row["doc_id"], oid)).fetchone()["trial"]) else 0
    ts = iso(now_utc())
    row.update(org_id=oid, status="draft", created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_gen_docs", row)
    gid = insert_id(c, f"INSERT INTO office_gen_docs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)
    c.commit()
    return jsonify(dt_doc_public(c, oid, dt_doc(c, oid, gid))), 201


@app.patch("/api/office/gen-docs/<int:gid>")
def dt_doc_patch(gid):
    """A draft's {title, body, client_id, list_id, doc_id, sign}; a finished document: 409 (a new version = Edit a copy)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_gen_doc_{int(gid)}")
    cur = dt_doc(c, oid, gid)
    if cur["status"] != "draft":
        return err(tr("A finished document cannot be changed any more. Edit a copy instead."), 409)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = {}
    if any(k in b for k in ("client_id", "list_id", "doc_id")):
        row.update(dt_refs(c, oid, b, cur))
    if "title" in b:
        row["title"] = _text(b.get("title"), "title", TITLE_MAX) or dt_kind_label(cur["kind"])
    if "body" in b:
        row["body"] = dt_body(b.get("body"))
    if "sign" in b:
        row["sign"] = 1 if b.get("sign") else 0
    if "sign_image" in b:  # 2.357.0 C (#3158): the own signature on / off
        row["sign_uid"] = dt_sign_uid(b.get("sign_image"), uid)
    if "lang" in b:
        row["lang"] = dt_lang(c, oid, b.get("lang"))
    if row:
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_gen_docs", row)
        c.execute(f"UPDATE office_gen_docs SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [gid, oid])
        if "title" in row:  # 2.351.0 A (#2823): its node in a folder takes the new title
            oft_renamed(c, GD_KIND, gid, row["title"])
        bump(c)
        c.commit()
    return jsonify(dt_doc_public(c, oid, dt_doc(c, oid, gid)))


@app.delete("/api/office/gen-docs/<int:gid>")
def dt_doc_delete(gid):
    """Archives a document (the filed PDFs stay in the documents space; an open signature link stops); restore = undo."""
    c, uid, oid = _ctx()
    dt_doc(c, oid, gid)
    # the same lock as the customer's decision (signoff.py sig_decide) per open link: archive and sign never cross
    for s in c.execute("SELECT id FROM office_signoffs WHERE gen_doc_id=? AND org_id=? AND state='open' AND revoked_at IS NULL ORDER BY id",
                       (gid, oid)).fetchall():
        write_lock(c, f"office_signoff_{int(s['id'])}")
    ts = iso(now_utc())
    c.execute("UPDATE office_gen_docs SET archived=1, updated_at=? WHERE id=? AND org_id=?", (ts, gid, oid))
    c.execute("UPDATE office_signoffs SET revoked_at=? WHERE gen_doc_id=? AND org_id=? AND state='open' AND revoked_at IS NULL", (ts, gid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/office/gen-docs/<int:gid>/restore")
def dt_doc_restore(gid):
    c, uid, oid = _ctx()
    dt_doc(c, oid, gid)
    c.execute("UPDATE office_gen_docs SET archived=0, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), gid, oid))
    bump(c)
    c.commit()
    return jsonify(dt_doc_public(c, oid, dt_doc(c, oid, gid)))


@app.post("/api/office/gen-docs/preview")
def dt_preview():
    """{gen_doc_id? | template_id? | body?, client_id?, list_id?, doc_id?, lang?} -> {text (filled; unknown / empty
    variables stay as {{key}}), missing: [keys], blocks: [[kind, text]]}. Nothing is stored."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    src, lang = None, b.get("lang")
    if b.get("gen_doc_id") not in (None, ""):
        d = oc_dec_fields(c, oid, "office_gen_docs", dt_doc(c, oid, b["gen_doc_id"]))
        src, lang = d["body"], lang or d.get("lang")
        b = {"client_id": d["client_id"], "list_id": d["list_id"], "doc_id": d["doc_id"], **b}
    elif b.get("template_id") not in (None, ""):
        t = dt_tpl(c, oid, b["template_id"])
        src, lang = t["body"], lang or t["lang"]
    if b.get("body") is not None:
        src = dt_body(b.get("body"))
    lang = dt_lang(c, oid, lang or None)
    cid = b.get("client_id") if b.get("client_id") not in ("", 0) else None
    v = dt_values(c, oid, lang, cid, b.get("list_id") or None, (b.get("doc_id") or None) if cid else None)
    text, miss = dt_fill(src or "", v, mark=True)
    return jsonify(text=text, missing=miss, missing_labels=dt_miss_labels(miss), blocks=[list(x) for x in dt_blocks(text)], values=v)


@app.post("/api/office/gen-docs/<int:gid>/final")
def dt_final(gid):
    """Finish a draft: fill the variables for good (unknown / empty -> empty), freeze the text (SHA-256), write the PDF
    and file it into the documents space (folder of the client). 409 when it is not a draft."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    write_lock(c, f"office_gen_doc_{int(gid)}")
    r = dt_doc(c, oid, gid)
    if r["status"] != "draft":
        return err(tr("This document is already finished."), 409)
    d = dict(oc_dec_fields(c, oid, "office_gen_docs", r))
    lang = dt_lang(c, oid, d.get("lang") or None)
    v = dt_values(c, oid, lang, d["client_id"], d["list_id"], d["doc_id"] if d["client_id"] else None)
    text, _miss = dt_fill(d["body"], v, mark=False)
    text = "\n".join(ln.rstrip() for ln in text.split("\n")).strip("\n")
    if not text.strip():
        raise BadInput(tr("The document has no text."))
    ts = iso(now_utc())
    if d.get("sign_uid") and d["sign_uid"] != uid:  # 2.357.0 C (#3158): finished by someone else -> without the other's signature
        d["sign_uid"] = None
        c.execute("UPDATE office_gen_docs SET sign_uid=NULL WHERE id=? AND org_id=?", (gid, oid))
    d.update(body=text, body_hash=dt_hash(text), status="final", final_at=ts, lang=lang)
    data = dt_pdf(c, oid, d)
    nid = dt_file(c, oid, uid, d, data)
    vals = oc_enc_fields(c, oid, "office_gen_docs", {"body": text})
    c.execute("UPDATE office_gen_docs SET body=?, body_hash=?, status='final', node_id=?, final_at=?, lang=?, updated_at=? WHERE id=? AND org_id=?",
              (vals["body"], d["body_hash"], nid, ts, lang, ts, gid, oid))
    from .terms import agb_gen_freeze  # 2.113.2 (#2253): order confirmations / contracts keep the terms of their language
    c.execute("UPDATE office_gen_docs SET terms=? WHERE id=? AND org_id=?", (agb_gen_freeze(c, oid, r["kind"], lang), gid, oid))
    ofx_log(c, oid, "gen_doc_final", target="gen_doc", detail={"gen_doc": gid, "title": d["title"], "body_hash": d["body_hash"], "node_id": nid})
    bump(c)
    c.commit()
    dt_kick()
    return jsonify(dt_doc_public(c, oid, dt_doc(c, oid, gid)))


def dt_disposition(title, suffix=""):
    """The Content-Disposition of a document's PDF: the title without path / quote / control characters, UTF-8 encoded."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]+', "-", title or "document")[:120] + suffix + ".pdf"
    return "attachment; filename*=UTF-8''" + urllib.parse.quote(name)


@app.get("/api/office/gen-docs/<int:gid>/pdf")
def dt_pdf_get(gid):
    """?signed=1 the signed PDF. The filed file when the admin still reaches it, else written anew from the frozen text.
    A draft: a preview PDF with the variables filled (marked as draft)."""
    from ..files.store import fs_read, fs_role
    from .signoff import sig_dec
    c, uid, oid = _ctx()
    r = dt_doc(c, oid, gid)
    if dt_signed_sync(c, oid, uid, [r]):
        r = dt_doc(c, oid, gid)
    d = dict(oc_dec_fields(c, oid, "office_gen_docs", r))
    signed = request.args.get("signed") == "1"
    if signed and d["status"] != "signed":
        raise Denied(404)
    nid = d["signed_node_id"] if signed else d["node_id"]
    data = None
    if nid and d["status"] != "draft":
        n = c.execute("SELECT deleted_at FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        if n and not n["deleted_at"] and fs_role(c, nid, uid):
            try:
                data = fs_read(c, nid)
            except Denied:
                data = None
    if data is None:
        if d["status"] == "draft":
            lang = dt_lang(c, oid, d.get("lang") or None)
            # 2.296.0 C (#3165): the draft keeps a variable without a value as {{key}} (dt_pdf draws it red)
            d["body"] = dt_fill(d["body"], dt_values(c, oid, lang, d["client_id"], d["list_id"], d["doc_id"] if d["client_id"] else None), mark=True)[0]
        sg = None
        if signed:
            s = c.execute("SELECT * FROM office_signoffs WHERE gen_doc_id=? AND org_id=? AND state='accepted' ORDER BY id DESC LIMIT 1", (gid, oid)).fetchone()
            if s:
                s = sig_dec(c, s)
                sg = {"name": s["signer_name"], "at": s["signed_at"], "hash": s["doc_hash"]}
        data = dt_pdf(c, oid, d, signed=sg)
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = dt_disposition(d["title"], " (signed)" if signed else "")
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


# ---------------------------------------------------------------- signature links (office/signoff.py, kind document)
@app.post("/api/office/gen-docs/<int:gid>/signoff")
def dt_signoff_new(gid):
    """{expires: YYYY-MM-DD | null} -> a new signature link of a finished, signable document (an open one stops)."""
    from ..lists.public import public_links_on
    from .ledger import ofx_log
    from .signoff import sig_create, sig_expiry, sig_public
    c, uid, oid = _ctx()
    r = dt_doc(c, oid, gid)
    if r["status"] != "final" or r["archived"] or not r["sign"]:
        return err(tr("Signature links exist for finished documents that may be signed"), 409)
    if not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    b = body()
    try:
        exp = sig_expiry((b if isinstance(b, dict) else {}).get("expires"))
    except BadInput as x:
        return err(str(x), 400)
    write_lock(c, f"office_signoff_gendoc_{int(gid)}")
    row, _tok = sig_create(c, oid, "document", r["title"] or "", r["body_hash"], uid, exp, gen_doc_id=gid)
    ofx_log(c, oid, "signoff_link", target="gen_doc", detail={"signoff": row["id"], "gen_doc": gid, "expires_at": exp, "doc_hash": r["body_hash"]})
    c.commit()
    return jsonify(sig_public(c, row))


@app.get("/api/office/gen-docs/<int:gid>/signoffs")
def dt_signoff_list(gid):
    from .signoff import sig_public
    c, uid, oid = _ctx()
    dt_doc(c, oid, gid)
    rows = c.execute("SELECT * FROM office_signoffs WHERE gen_doc_id=? AND org_id=? ORDER BY id DESC LIMIT 50", (gid, oid)).fetchall()
    return jsonify(signoffs=[sig_public(c, s) for s in rows])


# ---------------------------------------------------------------- the customer's page (called by office/signoff.py)
def dt_sig_row(c, r):
    """The decrypted document of signoff r (the public page reads inside the link's organisation), or None."""
    d = c.execute("SELECT * FROM office_gen_docs WHERE id=? AND org_id=?", (r["gen_doc_id"], r["org_id"])).fetchone()
    return dict(oc_dec_fields(c, r["org_id"], "office_gen_docs", d)) if d else None


def dt_sig_valid(c, r):
    """An open document link still fits: the document is finished (not archived) and its text unchanged."""
    d = dt_sig_row(c, r) if r["gen_doc_id"] else None
    return bool(d) and d["status"] == "final" and not d["archived"] and d["body_hash"] == r["doc_hash"] and dt_hash(d["body"]) == r["doc_hash"]


def dt_sig_html(c, r, lg, token, prefix):
    """The document on the customer's page: company, title, the text (escaped, light markup only), the PDF link."""
    import html
    e = html.escape
    d = dt_sig_row(c, r) or {}
    co = dt_company(c, r["org_id"], doc_lg(d.get("lang"))).get("name") or ""
    parts, items = [], []
    for k, t in dt_blocks(d.get("body") or ""):
        if k != "li" and items:
            parts.append("<ul>" + "".join(items) + "</ul>")
            items = []
        if k == "h1":
            parts.append(f"<h2>{e(t)}</h2>")
        elif k == "h2":
            parts.append(f"<h3>{e(t)}</h3>")
        elif k == "li":
            items.append(f"<li>{e(t)}</li>")
        else:
            parts.append("<p>" + "<br>".join(e(x) for x in t.split("\n")) + "</p>")
    if items:
        parts.append("<ul>" + "".join(items) + "</ul>")
    return (f'<header>{f"<div class=brand><span>{e(co)}</span></div>" if co else ""}<h1>{e(d.get("title") or r["title"] or "")}</h1>'
            f'<p class="sub">{e(tr("Signature requested", lg=lg))}</p></header>'
            f'<article class="sigdoc">{"".join(parts)}</article>'
            f'<p class="sub">{e(tr("SHA-256 of the text", lg=lg))}: <code>{e(r["doc_hash"] or "")}</code></p>'
            f'<p><a class="pdf" href="{prefix}{e(token)}/pdf" download rel="nofollow">{e(tr("Download the document (PDF)", lg=lg))}</a></p>')


def dt_sig_pdf(c, r):
    """The PDF for the customer: the original while open, the signed one after signing (rendered from the frozen text)."""
    from .signoff import sig_dec
    d = dt_sig_row(c, r)
    if not d:
        return None
    sg = None
    if r["state"] == "accepted":
        s = sig_dec(c, r)
        sg = {"name": s["signer_name"], "at": s["signed_at"], "hash": s["doc_hash"]}
    cl = None
    if d.get("client_id"):
        with system_ctx(c):  # the recipient printed on the PDF: exactly the client the document names (a personal office's
            x = c.execute("SELECT * FROM clients WHERE id=?", (d["client_id"],)).fetchone()  # client is private, the page reads as "anon")
        cl = dict(x) if x else None
    return dt_pdf(c, r["org_id"], d, signed=sg, client=cl or {}), (d["title"] or "document")


def dt_sig_decided(c, r, st):
    """The customer decided (office/signoff.py sig_decide): the document's status signed | declined. False when the
    document is no longer a finished, not archived one (archived meanwhile): the caller rolls back."""
    return c.execute("UPDATE office_gen_docs SET status=?, updated_at=? WHERE id=? AND org_id=? AND status='final' AND archived=0",
                     ("signed" if st == "accepted" else "declined", iso(now_utc()), r["gen_doc_id"], r["org_id"])).rowcount == 1

