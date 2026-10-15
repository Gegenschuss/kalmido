"""Office & finance 2.40.0 (#1381, #1363, #1368 point 3): switching the language (or the reminder level) of a DRAFT swaps
the standard texts. Intro, closing (settings / pack / framework contract), the rights texts (duration / territory / media),
the rights note and the titles of catalogue positions are set anew in the new language -- but only where the field still
holds the standard text of the old language. Texts changed by hand stay and come back as a note; a text block without
an English text keeps its German text with the note "no English text stored". Finalised documents never get here
(odoc_update refuses them first)."""
import json

from ..core.i18n import N_, tr
from .model import office_settings

FIELD_TXT = {"intro": N_("Introduction"), "closing": N_("Closing text"), "time": N_("Duration of use"), "territory": N_("Territory"),
             "media": N_("Media"), "note": N_("Rights note")}
# the standard invoice closing up to 2.39 (it still counts as a standard text in older drafts)
LEGACY = {"invoice_closing": {
    "de": "Der Gesamtbetrag wird mit Erhalt dieser Rechnung zur Zahlung fällig. Es gelten unsere allgemeinen Geschäftsbedingungen.",
    "en": "Please remit the invoice amount to the account specified above. Our general terms and conditions apply."}}


def _norm(t):
    return " ".join(str(t or "").split())


def _j(s, default):
    try:
        v = json.loads(s) if isinstance(s, str) else s
    except (TypeError, ValueError):
        return default
    return v if v is not None else default


def _block(c, oid, tid, lang):
    """(text, missing) of text block tid in lang; missing: English asked, but the block has only German."""
    from .docs import _iid
    if not tid:
        return None, False
    r = c.execute("SELECT text_de, text_en FROM office_texts WHERE id=? AND org_id=?", (_iid(tid), oid)).fetchone()
    if not r:
        return None, False
    if lang == "en" and not (r["text_en"] or "").strip():
        return r["text_de"] or "", True
    return (r["text_en"] if lang == "en" else r["text_de"]) or r["text_de"] or "", False


def _offer_block_missing(c, oid, s, kind, lang):
    """Whether the default intro / closing block of an offer (see docs._default_text) lacks the English text."""
    if lang != "en":
        return False
    ids = s.get(kind + "_text_id") or {}
    tid = ids.get(lang) if isinstance(ids, dict) else ids
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
            ctc = (ct.get("closing_en") if lang == "en" else ct.get("closing_de")) or ""
            if ctc:
                cands.add(ctc)
                closing, miss = ctc, False
            elif lang == "en" and ct.get("closing_de"):
                cands.add(ct["closing_de"])
                closing, miss = ct["closing_de"], True
        out["closing"] = (closing, cands, miss)
    else:
        intro, closing = inv_default_texts(c, oid, s, kind, lang, level)
        cands = {closing}
        if kind == "invoice":
            cands.add(LEGACY["invoice_closing"][lang])
        if kind == "credit":  # credit notes up to 2.39 took the invoice closing
            cands.add(inv_default_texts(c, oid, s, "invoice", lang)[1])
            cands.add(LEGACY["invoice_closing"][lang])
        if kind == "reminder":  # any level's standard text counts (the level may change together with the language)
            for lv in (1, 2, 3):
                cands.add(inv_default_texts(c, oid, s, kind, lang, lv)[1])
        icands = {intro}
        if kind == "reminder":
            icands |= {inv_default_texts(c, oid, s, kind, lang, lv)[0] for lv in (1, 2, 3)}
        out["intro"] = (intro, icands, False)
        out["closing"] = (closing, cands, False)
    return out


def _note_texts(c, oid, ct, lang):
    """The standard rights notes in lang (contract's, the first note block's) -> (first, candidates, missing)."""
    cands, first, miss = set(), None, False
    if ct:
        t = (ct.get("rights_note_en") if lang == "en" else ct.get("rights_note_de")) or ct.get("rights_note_de") or ""
        if t:
            cands.add(t)
            first = t
            miss = lang == "en" and not ct.get("rights_note_en")
    r = c.execute("SELECT text_de, text_en FROM office_texts WHERE org_id=? AND archived=0 AND kind='note' ORDER BY sort, id LIMIT 1", (oid,)).fetchone()
    if r:
        t = (r["text_en"] if lang == "en" else r["text_de"]) or r["text_de"] or ""
        cands.add(t)
        if first is None:
            first, miss = t, lang == "en" and not (r["text_en"] or "").strip()
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
            on = (sv["name_en"] if old_lang == "en" else sv["name_de"]) or sv["name_de"]
            nn = (sv["name_en"] if new_lang == "en" else sv["name_de"]) or sv["name_de"]
            if _norm(it.get("title")) == _norm(on):
                if nn != it.get("title"):
                    titles[it["id"]] = nn
                if new_lang == "en" and not (sv["name_en"] or "").strip():
                    notes.append(tr("Position \"{0}\": no English name stored", sv["name_de"]))
            elif _norm(it.get("title")) != _norm(nn):
                hand += 1
        if hand:
            notes.append(tr("Position titles changed by hand, not translated: {0}", hand))
    return notes, titles


def fd_put_titles(c, oid, did, titles):
    for iid, t in (titles or {}).items():
        c.execute("UPDATE office_doc_items SET title=? WHERE id=? AND doc_id=? AND org_id=?", (t, iid, did, oid))

