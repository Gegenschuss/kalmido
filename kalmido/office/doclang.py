"""Office & finance 2.40.0 (#1381, #1363, #1368 point 3): switching the language (or the reminder level) of a DRAFT swaps
the standard texts. Intro, closing (settings / pack / framework contract), the rights texts (duration / territory / media),
the rights note and the titles of catalogue positions are set anew in the new language -- but only where the field still
holds the standard text of the old language. Texts changed by hand stay and come back as a note; a text block without
an English text keeps its German text with the note "no English text stored". Finalised documents never get here
(odoc_update refuses them first)."""
import json

from ..core.i18n import LANGS, N_, tr
from .model import office_settings

FIELD_TXT = {"intro": N_("Introduction"), "closing": N_("Closing text"), "time": N_("Duration of use"), "territory": N_("Territory"),
             "media": N_("Media"), "note": N_("Rights note")}
# the standard invoice closing up to 2.39 (it still counts as a standard text in older drafts)
LEGACY = {"invoice_closing": {
    "de": "Der Gesamtbetrag wird mit Erhalt dieser Rechnung zur Zahlung fällig. Es gelten unsere allgemeinen Geschäftsbedingungen.",
    "en": "Please remit the invoice amount to the account specified above. Our general terms and conditions apply."},
    # 2.357.0 D (#3183): the German standard closing up to 2.356 ("allgemeinen" small)
    "invoice_closing_2": {"de": "Bitte überweisen Sie den Gesamtbetrag unter Angabe der Rechnungsnummer auf unser angegebenes Bankkonto. "
                                "Es gelten unsere allgemeinen Geschäftsbedingungen."}}


def doc_lg(lang):
    """2.149.0 A (#2520): the language a document's own words are printed in (tr(..., lg=)): its language when Kalmido has
    it, else German (as before for an empty one). 2.185.0 C (#2520): "en-…" counts as English (as the old de/en checks)."""
    s = str(lang or "").strip().lower()
    return "en" if s.startswith("en") else s if s in LANGS else "de"


# 2.185.0 C (#2520): the languages a document can be written in (every app language; de / en as before)
DOC_LANGS = tuple(sorted(LANGS, key=lambda k: (k not in ("de", "en"), k != "de", k)))


def doc_txt(de, en, lang):
    """2.185.0 C (#2520): a free text kept only in German / English (text blocks, terms, catalogue names) for a document in
    lang: its own language, the English text for any other one (the German text without an English one)."""
    return de if lang == "de" else (en or de)


# 2.185.0 C (#2520): the words and standard texts of the built-in packs (labels / texts in English, the pack's own word as
# the key): a document in a language the pack has no words for (nl, fr, es, it) gets them translated; a pack's own
# (other) English word stays English
DPK_WORDS = (N_("Quotation|pack"), N_("Quotation No.|pack"), N_("Invoice|pack"), N_("Invoice No.|pack"), N_("Project|pack"), N_("Ref./PO No.|pack"),
             N_("Client|pack"), N_("Date|pack"), N_("Valid until|pack"), N_("No.|pack"), N_("Title|pack"), N_("Qty|pack"), N_("Unit Price|pack"),
             N_("VAT|pack"), N_("Total|pack"), N_("Net Total|pack"), N_("Gross Total|pack"), N_("Net total with option raw data|pack"),
             N_("excluding raw data|pack"), N_("Optional: delivery of raw data|pack"), N_("Delivery of raw data|pack"), N_("Producing|pack"),
             N_("Discount|pack"), N_("Transfer of rights|pack"), N_("Duration of License|pack"), N_("Territorial Rights|pack"),
             N_("Rights by Medium|pack"), N_("Exceptions|pack"), N_("Exclusive|pack"), N_("Page {x} of {y}|pack"), N_("Kind regards|pack"),
             N_("Order confirmation|pack"), N_("Place, date, signature|pack"), N_("days|pack"), N_("hrs|pack"), N_("pcs|pack"), N_("min|pack"),
             N_("flat|pack"), N_("day|pack"), N_("hr|pack"), N_("pc|pack"), N_("Credit note|pack"), N_("Credit note No.|pack"),
             N_("Payment reminder|pack"), N_("Reminder|pack"), N_("Final reminder|pack"), N_("Reminder No.|pack"),
             N_("Credit note for invoice No.|pack"), N_("Re quotation No.|pack"), N_("Customer No.|pack"), N_("Service period|pack"),
             N_("Due on|pack"), N_("Exchange rate €1|pack"), N_("Subtotal|pack"), N_("Total amount due|pack"), N_("Credit total|pack"),
             N_("Already paid|pack"), N_("Amount outstanding|pack"), N_("Reminder fee|pack"), N_("Amount|pack"), N_("Payment|pack"), N_("Due|pack"),
             N_("Thank you for your enquiry. We are pleased to submit the following quotation:|pack"), N_("Dear Sir or Madam,|pack"),
             N_("We look forward to working with you and are happy to answer any questions.|pack"), N_("All prices plus 7 % or 19 % VAT.|pack"),
             N_("All prices net, without VAT.|pack"), N_("Our general terms and conditions apply.|pack"),
             N_("This quotation is valid until {date}.|pack"),
             N_("Regarding the project referenced above, we are pleased to submit the following charges for our services:|pack"),
             N_("Please transfer the total amount, quoting the invoice number, to our bank account stated on this invoice. Our general terms and conditions apply.|pack"),
             N_("The following goods or services have been delivered:|pack"), N_("Goods or services received in full and in good condition.|pack"),  # 2.296.0 D (#3167)
             N_("Regarding the invoice referenced below we issue the following credit note:|pack"),
             N_("We will refund the credited amount to you or offset it against open invoices. Please do not hesitate to contact us with any questions.|pack"),
             N_("It may have escaped your attention that the following invoices are still outstanding:|pack"),
             N_("Please transfer the outstanding amount within {days} days to the bank account above.|pack"),
             N_("Despite our payment reminder, we have not yet received payment for the following invoices:|pack"),
             N_("Please transfer the total amount outstanding within {days} days to the bank account above. If you have already arranged payment, please disregard this letter.|pack"),
             N_("Despite our payment reminder and our reminder notice, the following invoices remain unpaid:|pack"),
             N_("This is our final request to transfer the total amount outstanding within {days} days to the bank account above. If payment is not received by then, we will take legal action without further notice; any costs arising from this will be charged to you.|pack"),
             N_("Payable by {date} without deduction.|pack"), N_("Tax amount equals EUR {tax}, rate EUR 1 = USD {rate}|pack"),
             N_("VAT to be accounted for by the recipient (reverse charge, Art. 196 Directive 2006/112/EC).|pack"),
             N_("Not taxable in Germany.|pack"), N_("No VAT is charged (small business, section 19 German VAT Act).|pack"),
             N_("All prices plus statutory VAT.|pack"), N_("Reverse charge: VAT to be accounted for by the recipient.|pack"),
             N_("Not taxable in the supplier's country.|pack"), N_("Small business: no VAT is charged.|pack"),
             N_("Not taxable in Germany - reverse-charge procedure (VAT to be accounted for by the recipient).|pack"), N_("in perpetuity|pack"),
             N_("1 year from first publication|pack"), N_("2 years from first publication|pack"), N_("worldwide|pack"),
             N_("Germany, Austria, Switzerland|pack"), N_("Germany|pack"), N_("worldwide except music on trade shows / live events (DE)|pack"),
             N_("internal use|pack"), N_("internal use, web, unpaid media|pack"), N_("all media|pack"), N_("web, social media, paid media|pack"),
             N_("the client's country|pack"), N_("the client's region|pack"),
             # 2.296.0 B (#3168, #3175): invoice correction, client VAT id, buyer reference, the two reverse charge texts
             N_("Invoice correction|pack"), N_("Invoice correction No.|pack"), N_("Correction of invoice No.|pack"), N_("Correction total|pack"),
             N_("Regarding the invoice referenced above we issue the following invoice correction:|pack"), N_("Client VAT ID|pack"),
             N_("Leitweg ID|pack"), N_("Buyer reference|pack"),
             N_("Reverse charge: VAT to be accounted for by the recipient (section 13b German VAT Act).|pack"),
             # 2.357.0 D (#3183): sentence case, "Description" for the service column, the service date of one day
             N_("Description|pack"), N_("Unit price|pack"), N_("Net total|pack"), N_("Gross total|pack"), N_("Duration of licence|pack"),
             N_("Territorial rights|pack"), N_("Rights by medium|pack"), N_("Service date|pack"),
             N_("Regarding the invoice referenced above we issue the following credit note:|pack"))

def _dpk(w, lang):
    # 2.185.0 (#2520): looked up directly, not via tr(): an own text with a "|" must come back whole
    v = LANGS.get(lang, {}).get(w + "|pack") if isinstance(w, str) and w else None
    return v if isinstance(v, str) else w


def doc_word(en, lang):
    """2.185.0 C (#2520): the English text of a de / en text (a text block, a catalogue entry) for a document in lang:
    nl / fr / es / it get it translated when it is still the standard text of a built-in pack (copied text blocks), any
    other text stays English."""
    return _dpk(en, lang) if doc_lg(lang) not in ("de", "en") else en


def doc_pack(pack, lang):
    """2.185.0 C (#2520): the country pack for a document in lang. A language the pack labels (de, en) returns the pack as it
    is; any other gets labels[lang] (the English words, translated where they are the built-in pack's) and texts[k][lang]
    (the English text, the German one without it; translated where it is a built-in standard text) -- so every place that
    reads pack["labels"][lang] / pack["texts"][k][lang] works unchanged."""
    lb = (pack or {}).get("labels") or {}
    if not pack or not lang or isinstance(lb.get(lang), dict):
        return pack
    p = dict(pack)
    base = lb.get("en") if isinstance(lb.get("en"), dict) else (lb.get("de") or {})
    L = {}
    for k, v in base.items():
        L[k] = _dpk(v, lang) if isinstance(v, str) else {u: _dpk(w, lang) for u, w in v.items()} if isinstance(v, dict) else v
    p["labels"] = {**lb, lang: L}
    tx = {}
    for k, v in (pack.get("texts") or {}).items():
        tx[k] = {**v, lang: _dpk(v.get("en") or v.get("de") or "", lang)} if isinstance(v, dict) and not isinstance(v.get(lang), str) else v
    p["texts"] = tx
    ex = (pack.get("tax") or {}).get("exempt_note")
    if isinstance(ex, dict) and not isinstance(ex.get(lang), str):
        p["tax"] = {**pack["tax"], "exempt_note": {**ex, lang: _dpk(ex.get("en") or ex.get("de") or "", lang)}}
    return p


def _norm(t):
    return " ".join(str(t or "").split())


def _j(s, default):
    try:
        v = json.loads(s) if isinstance(s, str) else s
    except (TypeError, ValueError):
        return default
    return v if v is not None else default


def _en(lang):
    """2.185.0 C (#2520): whether a document in lang takes the English one of a de / en free text (en, nl, fr, es, it)."""
    return doc_lg(lang) != "de"


def _block(c, oid, tid, lang):
    """(text, missing) of text block tid in lang; missing: English asked, but the block has only German (2.185.0 C: the
    English text also stands for nl / fr / es / it)."""
    from .docs import _iid
    if not tid:
        return None, False
    r = c.execute("SELECT text_de, text_en FROM office_texts WHERE id=? AND org_id=?", (_iid(tid), oid)).fetchone()
    if not r:
        return None, False
    if _en(lang) and not (r["text_en"] or "").strip():
        return r["text_de"] or "", True
    return (doc_word(r["text_en"], lang) if _en(lang) else r["text_de"]) or r["text_de"] or "", False


def _offer_block_missing(c, oid, s, kind, lang):
    """Whether the default intro / closing block of an offer (see docs._default_text) lacks the English text."""
    if not _en(lang):
        return False
    ids = s.get(kind + "_text_id") or {}
    tid = ids.get("en") if isinstance(ids, dict) else ids
    if tid:
        t, miss = _block(c, oid, tid, lang)
        if t is not None:
            return miss
    r = c.execute("SELECT text_en FROM office_texts WHERE org_id=? AND archived=0 AND kind=? ORDER BY sort, id LIMIT 1", (oid, kind)).fetchone()
    return bool(r) and not (r["text_en"] or "").strip()


def _defaults(c, oid, s, cur, lang, level, ct):
    """{field: (standard text, candidates, missing)} of intro / closing for document row cur in lang."""
    from .docs import _default_text
    from .invoices import inv_default_texts
    kind = cur["kind"]
    out = {}
    if kind == "offer":
        intro = _default_text(c, oid, s, "intro", lang)
        out["intro"] = (intro, {intro}, _offer_block_missing(c, oid, s, "intro", lang))
        base = _default_text(c, oid, s, "closing", lang)
        cands = {base}
        closing, miss = base, _offer_block_missing(c, oid, s, "closing", lang)
        if ct:
            ctc = (ct.get("closing_en") if _en(lang) else ct.get("closing_de")) or ""
            if ctc:
                cands.add(ctc)
                closing, miss = ctc, False
            elif _en(lang) and ct.get("closing_de"):
                cands.add(ct["closing_de"])
                closing, miss = ct["closing_de"], True
        out["closing"] = (closing, cands, miss)
    else:
        intro, closing = inv_default_texts(c, oid, s, kind, lang, level)
        cands = {closing}
        legacy = LEGACY["invoice_closing"].get(lang)  # 2.185.0 C (#2520): de / en only
        if kind == "invoice" and legacy:
            cands.add(legacy)
        if kind == "credit":  # credit notes up to 2.39 took the invoice closing
            cands.add(inv_default_texts(c, oid, s, "invoice", lang)[1])
            if legacy:
                cands.add(legacy)
        if kind in ("invoice", "credit") and LEGACY["invoice_closing_2"].get(lang):
            cands.add(LEGACY["invoice_closing_2"][lang])
        if kind == "reminder":  # any level's standard text counts (the level may change together with the language)
            for lv in (1, 2, 3):
                cands.add(inv_default_texts(c, oid, s, kind, lang, lv)[1])
        icands = {intro}
        if kind == "reminder":
            icands |= {inv_default_texts(c, oid, s, kind, lang, lv)[0] for lv in (1, 2, 3)}
        out["intro"] = (intro, icands, False)
        out["closing"] = (closing, cands, False)
    if doc_lg(lang) != "de":  # 2.357.0 D (#3183): fr / es standard intros up to 2.356 began with a small letter; 2.390.0 A (#3349): en / it / nl up to 2.389
        i0, ic, im = out["intro"]
        out["intro"] = (i0, ic | {x[:1].lower() + x[1:] for x in ic if x}, im)
    return out


def _note_texts(c, oid, ct, lang):
    """The standard rights notes in lang (contract's, the first note block's) -> (first, candidates, missing)."""
    cands, first, miss = set(), None, False
    if ct:
        t = (ct.get("rights_note_en") if _en(lang) else ct.get("rights_note_de")) or ct.get("rights_note_de") or ""
        if t:
            cands.add(t)
            first = t
            miss = _en(lang) and not ct.get("rights_note_en")
    r = c.execute("SELECT text_de, text_en FROM office_texts WHERE org_id=? AND archived=0 AND kind='note' ORDER BY sort, id LIMIT 1", (oid,)).fetchone()
    if r:
        t = (doc_word(r["text_en"], lang) if _en(lang) else r["text_de"]) or r["text_de"] or ""
        cands.add(t)
        if first is None:
            first, miss = t, _en(lang) and not (r["text_en"] or "").strip()
    return first, cands, miss


def fd_lang_swap(c, oid, cur, b, f):
    """Head fields f (from clean_doc for body b) of draft row cur: on a new language / reminder level, the standard texts
    in f (intro, closing, rights) are replaced and the positions' titles returned for the caller to store.
    -> (notes [text], item_titles {item id: title})"""
    from .docs import _contract, doc_items
    old_lang, new_lang = cur["lang"], f.get("lang", cur["lang"])
    keys = cur.keys()
    old_level = int(cur["reminder_level"] or 1) if "reminder_level" in keys and cur["reminder_level"] else 1
    new_level = int(f.get("reminder_level", old_level) or 1)
    if old_lang == new_lang and (cur["kind"] != "reminder" or old_level == new_level):
        return [], {}
    s = office_settings(c, oid)
    ct = _contract(c, oid, f.get("contract_id", cur["contract_id"])) if (f.get("contract_id", cur["contract_id"])) else None
    old_d = _defaults(c, oid, s, cur, old_lang, old_level, ct)
    new_d = _defaults(c, oid, s, cur, new_lang, new_level, ct)
    notes = []
    for k in ("intro", "closing"):
        if k in b:  # sent with the same change: the person's text wins
            continue
        now = f.get(k, cur[k])
        if not _norm(now):
            continue
        if _norm(now) in {_norm(x) for x in old_d[k][1]} or _norm(now) in {_norm(x) for x in new_d[k][1]}:
            f[k] = new_d[k][0]
            if new_d[k][2]:
                notes.append(tr("{0}: no English text stored", tr(FIELD_TXT[k])))
        else:
            notes.append(tr("{0} changed by hand, not translated", tr(FIELD_TXT[k])))
    if old_lang != new_lang:
        rights = _j(f.get("rights") or cur["rights"], {})
        changed = False
        if "rights" not in b:
            for dim in ("time", "territory", "media"):
                x = rights.get(dim) or {}
                if not x.get("id") or not _norm(x.get("text")):
                    continue
                ot, _ = _block(c, oid, x["id"], old_lang)
                nt, miss = _block(c, oid, x["id"], new_lang)
                if nt is None:
                    continue
                if _norm(x.get("text")) == _norm(ot):
                    x["text"] = nt
                    rights[dim] = x
                    changed = True
                    if miss:
                        notes.append(tr("{0}: no English text stored", tr(FIELD_TXT[dim])))
                elif _norm(x.get("text")) != _norm(nt):
                    notes.append(tr("{0} changed by hand, not translated", tr(FIELD_TXT[dim])))
            if _norm(rights.get("note")):
                _, oc, _ = _note_texts(c, oid, ct, old_lang)
                nf, nc, miss = _note_texts(c, oid, ct, new_lang)
                if _norm(rights["note"]) in {_norm(x) for x in oc} and nf is not None:
                    rights["note"] = nf
                    changed = True
                    if miss:
                        notes.append(tr("{0}: no English text stored", tr(FIELD_TXT["note"])))
                elif _norm(rights["note"]) not in {_norm(x) for x in nc}:
                    notes.append(tr("{0} changed by hand, not translated", tr(FIELD_TXT["note"])))
        if changed:
            f["rights"] = json.dumps(rights, ensure_ascii=False)
    titles = {}
    if old_lang != new_lang:
        hand = 0
        from .parts import tp_part_items_all  # 2.47.0 (#1215): the positions of the parts too
        for it in doc_items(c, cur["id"], oid) + tp_part_items_all(c, oid, cur["id"]):
            if not it.get("service_id") or it.get("kind") != "service":
                continue
            sv = c.execute("SELECT name_de, name_en FROM office_services WHERE id=? AND org_id=?", (it["service_id"], oid)).fetchone()
            if not sv:
                continue
            on = (sv["name_en"] if _en(old_lang) else sv["name_de"]) or sv["name_de"]
            nn = (sv["name_en"] if _en(new_lang) else sv["name_de"]) or sv["name_de"]
            if _norm(it.get("title")) == _norm(on):
                if nn != it.get("title"):
                    titles[it["id"]] = nn
                if _en(new_lang) and not (sv["name_en"] or "").strip():
                    notes.append(tr("Position \"{0}\": no English name stored", sv["name_de"]))
            elif _norm(it.get("title")) != _norm(nn):
                hand += 1
        if hand:
            notes.append(tr("Position titles changed by hand, not translated: {0}", hand))
    return notes, titles


def fd_put_titles(c, oid, did, titles):
    for iid, t in (titles or {}).items():
        c.execute("UPDATE office_doc_items SET title=? WHERE id=? AND doc_id=? AND org_id=?", (t, iid, did, oid))

