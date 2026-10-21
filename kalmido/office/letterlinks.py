"""2.153.0 (#2028): letters <-> documents of the documents space (office_letter_links), the history ("Vorgang") per contact
and subject, the deadline found in an incoming document -> a task, the follow-up when no answer comes, the DIN 5008
reference line made from the answered document. Rules: the decisions of 18.10.2026."""
import re
import time
from datetime import date, timedelta

from flask import jsonify, request

from ..core.config import PUBLIC_URL, app
from ..core.pg import insert_id, system_ctx
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.access import Denied
from ..core.i18n import N_, lang, tr
from ..core.orgcrypt import oc_dec_fields
from ..personal.timetrack import BadInput
from .model import pb_owner

LTL_KINDS = ("answers", "reply")  # answers = the letter answers the document; reply = the document answers the letter


def ltl_link(c, oid, letter_id, node_id, kind, uid=None, agent_id=None):
    """Links letter letter_id (of area oid) and document node_id (kind answers | reply); idempotent -> the link id.
    The caller has checked that the person / agent may see both. No commit."""
    if kind not in LTL_KINDS:
        raise ValueError(kind)
    r = c.execute("SELECT id FROM office_letter_links WHERE letter_id=? AND node_id=? AND kind=?", (letter_id, node_id, kind)).fetchone()
    if r:
        return r[0]
    return insert_id(c, "INSERT INTO office_letter_links(org_id, letter_id, node_id, kind, created_by, agent_id, created_at) VALUES(?,?,?,?,?,?,?)",
                     (oid, letter_id, node_id, kind, uid, agent_id, iso(now_utc())))




# ---------------------------------------------------------------- recognising references and deadlines (plain rules, no model)
# the reference labels of an incoming letter -> what they are in the answer: theirs = the sender's reference ("Ihr Zeichen"
# in the answer), ours = our own reference the sender quoted ("Unser Zeichen" in the answer), policy / customer / tax = numbers
# the answer names again
LTL_REF_LABELS = (
    ("theirs", r"unsere?\s+zeichen|aktenzeichen|az\.|gesch(?:ä|ae)ftszeichen|vorgangs(?:nummer|-?nr\.?)|our\s+ref(?:erence)?\.?|"
               r"reference(?:\s+(?:no\.?|number))?|ref\.\s*(?:no\.?)?"),
    ("ours", r"ihre?\s+zeichen|your\s+ref(?:erence)?\.?"),
    ("policy", r"versicherungs(?:nummer|schein(?:nummer|-?nr\.?)|-?nr\.?)|vers\.\s*-?\s*nr\.?|policy\s+(?:no\.?|number)"),
    ("customer", r"kunden(?:nummer|-?nr\.?)|customer\s+(?:no\.?|number)"),
    ("tax", r"steuer(?:nummer|-?nr\.?)|tax\s+(?:no\.?|number)"),
)
LTL_REF_RE = re.compile(r"(?<![\w.-])(" + "|".join(f"(?P<{k}>{rx})" for k, rx in LTL_REF_LABELS) + r")[ \t]*[:.#]?[ \t]*(?:\n[ \t]*)?"
                        r"(?=([^\n]{1,60}))", re.I)  # the value as a look-ahead: a label right after it is found as well
LTL_TEXT_CAP = 60_000


def ltl_ref_value(raw):
    """The reference itself from the text after a label: tokens while they look like parts of a number (digits, short or
    upper-case parts: "12 K 345/26", "VN-2026-77"); the first ordinary word ends it. '' without any digit."""
    out = []
    for t in re.split(r"[ \t]+", raw.strip()):
        t2 = t.strip(",;:()")
        if not t2:
            break
        if out and re.fullmatch(r"[^\W\d_]{4,}", t2) and not t2.isupper():
            break
        if not out and re.fullmatch(r"[^\W\d_]{4,}", t2) and not t2.isupper():
            return ""  # "Reference to your letter": a word, no number
        out.append(t2)
        if len(" ".join(out)) > 40:
            out.pop()
            break
    v = " ".join(out).rstrip(".,;:-/")
    return v if re.search(r"\d", v) else ""


def ltl_refs(text):
    """[{kind: theirs|ours|policy|customer|tax, label (as written), value}] of the references in text (at most one per
    kind and value, at most 8, reading order)."""
    out, seen = [], set()
    for m in LTL_REF_RE.finditer(unicodedata_nfc(text)[:LTL_TEXT_CAP]):
        kind = next(k for k, _ in LTL_REF_LABELS if m.group(k))
        v = ltl_ref_value(m.group(len(LTL_REF_LABELS) + 2))
        if not v or (kind, v.casefold()) in seen:
            continue
        seen.add((kind, v.casefold()))
        out.append({"kind": kind, "label": re.sub(r"\s+", " ", m.group(1)).strip(), "value": v})
        if len(out) >= 8:
            break
    return out


def unicodedata_nfc(s):
    import unicodedata
    return unicodedata.normalize("NFC", s or "")


# a date right after these words is a deadline ("bis zum 31.10.2026", "spätestens am …", "Frist: …", "no later than …")
LTL_DL_WORDS = re.compile(r"(?<![\w])(?:bis\s+(?:zum|sp(?:ä|ae)testens(?:\s+(?:zum|am))?)|sp(?:ä|ae)testens(?:\s+(?:am|zum|bis(?:\s+zum)?))?|"
                          r"frist\w*(?:\s+(?:endet|l(?:ä|ae)uft\s+ab|l(?:ä|ae)uft))?(?:\s+(?:am|bis|zum))?(?:\s+(?:zum|am))?|"
                          r"deadline(?:\s+(?:is|of|on))?|(?:no|not)\s+later\s+than|by)\s*[:\-]?\s*(?:den\s+|dem\s+|the\s+)?", re.I)
LTL_NUM = {"ein": 1, "eine": 1, "einer": 1, "einem": 1, "one": 1, "a": 1, "zwei": 2, "two": 2, "drei": 3, "three": 3, "vier": 4,
           "four": 4, "fünf": 5, "fuenf": 5, "five": 5, "sechs": 6, "six": 6, "sieben": 7, "seven": 7, "acht": 8, "eight": 8,
           "zehn": 10, "ten": 10, "vierzehn": 14, "fourteen": 14}
LTL_DL_REL = re.compile(r"(?<![\w])(?:innerhalb|binnen|within|frist\s+von)\s+(?:von\s+|einer\s+frist\s+von\s+|of\s+|a\s+period\s+of\s+)?"
                        r"(\d{1,3}|" + "|".join(sorted(LTL_NUM, key=len, reverse=True)) + r")\s+"
                        r"((?:werk|arbeits|kalender)?tag(?:e|en)?|woche(?:n)?|monat(?:e|en)?|(?:working\s+|business\s+|calendar\s+)?days?|weeks?|months?)(?![\w])", re.I)
# relative terms near these words are payment terms ("zahlbar innerhalb von 14 Tagen"): the documents area has them as due date
LTL_PAY_RE = re.compile(r"zahl|(?:ü|ue)berweis|rechnungsbetrag|netto|skonto|payment|payable|invoice|\bpay\b|\bnet\b", re.I)


def ltl_snippet(text, s, e):
    """The words around text[s:e] on one line (at most ~140 characters)."""
    a = max(text.rfind("\n\n", 0, s), text.rfind(". ", 0, s) + 1, s - 80, 0)
    if a == s - 80 and a > 0:
        a = max(text.find(" ", a, s) + 1, a)  # not in the middle of a word
    b = min([x for x in (text.find("\n\n", e), text.find(". ", e)) if x >= 0] + [e + 50, len(text)])
    return re.sub(r"\s+", " ", text[a:b + (1 if text[b:b + 1] == "." else 0)]).strip()[:140]


def ltl_add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return d


def ltl_deadline(text, doc_date=None):
    """The deadline in an incoming document: a date after a deadline word, or "innerhalb von 14 Tagen" / "within two weeks"
    counted from the document date (doc_date: date or 'YYYY-MM-DD'; without it relative terms are skipped). Payment terms
    are left out (the documents area shows them as due date). -> {date: 'YYYY-MM-DD', text: the words around it} or None;
    the first one in reading order."""
    from ..docs.extract import find_dates
    if isinstance(doc_date, str):
        try:
            doc_date = date.fromisoformat(doc_date[:10])
        except ValueError:
            doc_date = None
    text = unicodedata_nfc(text)[:LTL_TEXT_CAP]
    lo = doc_date or date(1990, 1, 1)
    hi = (doc_date or local_now().date()) + timedelta(days=731)
    found = []
    dates = find_dates(text)
    for m in LTL_DL_WORDS.finditer(text):
        if m.group(0).strip().lower() == "by" and not re.search(r"\b(?:reply|respond|answer|submit|send|return|pay|by)\s*$", text[max(0, m.start() - 30):m.start()], re.I):
            continue  # "by" alone only after a verb of answering ("please reply by 31 October 2026")
        if re.search(r"\d\s*$", text[max(0, m.start() - 4):m.start()]):
            continue  # "01.10. bis zum 31.10.": a period, no deadline
        for s, e, d in dates:
            if m.end() <= s <= m.end() + 12:
                if lo <= d <= hi:
                    found.append((m.start(), d, ltl_snippet(text, m.start(), e)))
                break
    if doc_date:
        for m in LTL_DL_REL.finditer(text):
            if LTL_PAY_RE.search(text[max(0, m.start() - 80):m.end() + 40]):
                continue
            raw = m.group(1).lower()
            n = int(raw) if raw.isdigit() else LTL_NUM.get(raw, 0)
            unit = m.group(2).lower()
            if not 0 < n <= 365:
                continue
            if unit.startswith(("woche", "week")):
                d = doc_date + timedelta(weeks=n)
            elif unit.startswith(("monat", "month")):
                d = ltl_add_months(doc_date, n)
            else:
                d = doc_date + timedelta(days=n)
            if d <= hi:
                found.append((m.start(), d, ltl_snippet(text, m.start(), m.end())))
    if not found:
        return None
    _s, d, snip = min(found, key=lambda x: x[0])
    return {"date": d.isoformat(), "text": snip}


# ---------------------------------------------------------------- the reference line (DIN 5008) and the prefill
def ltl_day(day, lg):
    """'YYYY-MM-DD' -> the date as written in a letter of language lg (German and default: 31.10.2026)."""
    try:
        d = date.fromisoformat(str(day)[:10])
    except ValueError:
        return str(day or "")
    if lg == "en":
        return f"{d.day} {('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')[d.month - 1]} {d.year}"
    return f"{d.day:02d}-{d.month:02d}-{d.year}" if lg == "nl" else f"{d.day:02d}.{d.month:02d}.{d.year}" if lg in ("de", "", None) \
        else f"{d.day:02d}/{d.month:02d}/{d.year}"


LTL_REF_PARTS = (("theirs", N_("Your reference: {0}")), ("ours", N_("Our reference: {0}")), ("policy", N_("Policy number: {0}")),
                 ("customer", N_("Customer number: {0}")), ("tax", N_("Tax number: {0}")))


def ltl_ref_line(refs, doc_date=None, lg=None):
    """The reference line of an answer (DIN 5008: "Ihr Zeichen: …, Ihre Nachricht vom …, Unser Zeichen: …") from the
    references found in the answered document (ltl_refs) and its date; '' when there is nothing. One per kind."""
    lg = lg or lang()
    by = {}
    for r in refs or []:
        by.setdefault(r["kind"], r["value"])
    parts = []
    if by.get("theirs"):
        parts.append(tr("Your reference: {0}", by["theirs"], lg=lg))
    if doc_date:
        parts.append(tr("Your message of {0}", ltl_day(doc_date, lg), lg=lg))
    for k, key in LTL_REF_PARTS[1:]:
        if by.get(k):
            parts.append(tr(key, by[k], lg=lg))
    return ", ".join(parts)[:300]


def ltl_doc(c, oid, nid, write=False):
    """(meta, node) of document nid when it lies in the documents space of office area oid (an organisation's space; a
    personal office: its owner's private space) and the signed-in account may see it (write: change it); else 404. A
    document in the bin is not there."""
    from ..docs import store as S
    from ..files.store import need_node
    try:
        nid = int(nid)
    except (TypeError, ValueError):
        raise Denied(404) from None
    n = need_node(c, nid, write=write)
    m = S.meta_row(c, nid)
    owner = pb_owner(c, oid)
    if not m or n["kind"] != "file" or m["ws"] != (S.doc_ws(None, owner) if owner is not None else S.doc_ws(oid, None)):
        raise Denied(404)
    if (n["org_id"] or None) != (None if owner is not None else oid):
        raise Denied(404)
    return m, n


def ltl_doc_title(n):
    name = n["name"] or ""
    return re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name) or name


def ltl_doc_info(c, m, n):
    """Date, sender, references and deadline of a document (its text decrypted like docs/web.py)."""
    from ..docs import store as S
    text = S.meta_text(c, m)
    refs = ltl_refs(text)
    dl = ltl_deadline(text, m["doc_date"])
    if not dl and m["due_date"]:
        dl = {"date": m["due_date"], "text": ""}  # the due date the documents area found (payment): clear enough as a deadline
    return {"date": m["doc_date"], "sender": S.label_name(c, m["ws"], "sender", m["sender_id"]) if m["sender_id"] else None,
            "refs": refs, "deadline": dl, "title": ltl_doc_title(n)}


def ltl_client_match(c, oid, name, text=""):
    """The client of office area oid whose name is the sender's name (or whose e-mail address is in the text) or None."""
    from .model import pb_cl_sql
    rows = c.execute(f"SELECT * FROM clients WHERE archived=0 AND {pb_cl_sql(c, oid)} ORDER BY id").fetchall()
    key = (name or "").strip().casefold()
    for r in rows:
        if key and (r["name"] or "").strip().casefold() == key:
            return r
    low = (text or "")[:LTL_TEXT_CAP].casefold()
    for r in rows:
        if r["email"] and re.search(r"(?<![\w.+-])" + re.escape(r["email"].strip().casefold()) + r"(?![\w.-])", low):
            return r
    return None


LTL_CONTACTS_MAX = 5000  # address book contacts compared with a document's sender at most


def ltl_contact_match(c, oid, uid, name, text=""):
    """2.153.0 (#2229): the address book contact (row) whose name (full name, given + family name or organisation) is the
    sender's name, else whose e-mail address is in the text, or None. Only the books uid sees in the office's space
    (letters.py lt_book_ids: never across the boundary)."""
    from .letters import lt_book_ids, lt_jl
    books = lt_book_ids(c, oid, uid)
    if not books:
        return None
    rows = c.execute(f"SELECT * FROM contacts WHERE book_id IN ({','.join('?' * len(books))}) AND kind!='group' ORDER BY id LIMIT ?",
                     list(books) + [LTL_CONTACTS_MAX]).fetchall()
    key = (name or "").strip().casefold()
    if key:
        hits = [r for r in rows if any((x or "").strip().casefold() == key
                                       for x in (r["fn"], " ".join(x for x in (r["given"], r["family"]) if x), r["org"]))]
        if hits:  # review A6: a company name -> the organisation's own card before a person working there, then the oldest
            return min(hits, key=lambda r: (0 if r["kind"] == "org" else 1 if not (r["given"] or r["family"]) else 2, r["id"]))
    low = (text or "")[:LTL_TEXT_CAP].casefold()
    if not low:
        return None
    for r in rows:
        for e in lt_jl(r["emails"]):
            v = (e.get("value") or "").strip().casefold() if isinstance(e, dict) else ""
            if v and re.search(r"(?<![\w.+-])" + re.escape(v) + r"(?![\w.-])", low):
                return r
    return None


def ltl_client_addr(cl):
    """The address lines of a client for the address field: street, extra line, zip + city, country (not DE); the fixed
    fields only (2.97.0 B #1951), like office/doctpl.py _addr."""
    cl = dict(cl)
    lines = [(cl.get("street") or "").strip(), (cl.get("address_extra") or "").strip(),
             " ".join(y for y in ((cl.get("zip") or "").strip(), (cl.get("city") or "").strip()) if y)]
    if (cl.get("country") or "").strip() and (cl.get("country") or "").strip().upper() != "DE":
        lines.append(cl["country"].strip())
    return "\n".join(x for x in lines if x)


def ltl_prefill(c, oid, uid, node_id, agent_id=None):
    """A new letter that answers document node_id: {client_id?, contact_id?, rcpt_name?, rcpt_address?, rcpt_email?, subject?,
    ref_line?} taken from the document (sender, date, reference from the text recognition). 404 when the person / agent
    may not see the document in the documents space of office area oid (agents: the share is checked by part D, the
    signed-in account here is the agent's)."""
    from ..docs import store as S
    m, n = ltl_doc(c, oid, node_id)
    info = ltl_doc_info(c, m, n)
    out = {}
    cl = ltl_client_match(c, oid, info["sender"], S.meta_text(c, m))
    # 2.153.0 (#2229): a client first; agents get no address book contact (the books are not shared with them)
    ct = None if cl or agent_id else ltl_contact_match(c, oid, uid, info["sender"], S.meta_text(c, m))
    if cl:
        out.update(client_id=cl["id"], rcpt_name=cl["name"] or "", rcpt_address=ltl_client_addr(cl), rcpt_email=cl["email"] or "")
    elif ct:
        from .letters import lt_contact_rcpt
        out.update(lt_contact_rcpt(ct))
    elif info["sender"]:
        out["rcpt_name"] = info["sender"]
    from .letters import lt_lang
    lg = lt_lang(c, oid)  # the language of the new letter (the office's document language), not the reader's
    out["lang"] = lg
    out["subject"] = tr("Your letter of {0}", ltl_day(info["date"], lg), lg=lg) if info["date"] else \
        tr("Re: {0}", info["title"], lg=lg)[:300]
    line = ltl_ref_line(info["refs"], info["date"], lg)
    if line:
        out["ref_line"] = line
    return out


# ---------------------------------------------------------------- links, history ("Vorgang")
LTL_GRAPH_MAX = 200  # letters + documents of one history at most


def ltl_doc_ok(c, oid, nid):
    """(meta, node) of a linked document the person may see in the area, or None (bin, no access, another space)."""
    try:
        return ltl_doc(c, oid, nid)
    except Denied:
        return None


def ltl_letter_item(c, oid, r):
    from .letters import lt_public
    d = lt_public(c, oid, oc_dec_fields(c, oid, "office_letters", r))
    return {"type": "letter", "id": d["id"], "date": d["letter_date"] or (d["sent_at"] or d["created_at"] or "")[:10], "dir": "out",
            "title": d["subject"] or "", "status": d["status"], "rcpt_name": d["rcpt_name"] or "", "client_id": d["client_id"],
            "href": f"#office/letters/{d['id']}"}


def ltl_node_item(c, m, n):
    from ..docs import store as S
    return {"type": "doc", "id": n["id"], "date": m["doc_date"] or (n["created_at"] or "")[:10], "dir": "in", "title": ltl_doc_title(n),
            "sender": S.label_name(c, m["ws"], "sender", m["sender_id"]) if m["sender_id"] else None, "href": f"#docs/{n['id']}"}


def ltl_links_of(c, oid, lid):
    """[{node_id, kind, title, date, sender, href}] of the documents linked to letter lid that the person sees."""
    out = []
    for r in c.execute("SELECT node_id, kind FROM office_letter_links WHERE letter_id=? AND org_id=? ORDER BY id", (lid, oid)).fetchall():
        ok = ltl_doc_ok(c, oid, r["node_id"])
        if ok:
            it = ltl_node_item(c, *ok)
            out.append({"node_id": r["node_id"], "kind": r["kind"], "title": it["title"], "date": it["date"], "sender": it["sender"],
                        "href": it["href"]})
    return out


def ltl_answered(c, oid, lid):
    """Has letter lid an answer: a reply link to a document that is not in the bin?"""
    return bool(c.execute("SELECT 1 FROM office_letter_links l JOIN fs_nodes n ON n.id=l.node_id WHERE l.letter_id=? AND l.org_id=? "
                          "AND l.kind='reply' AND n.deleted_at IS NULL LIMIT 1", (lid, oid)).fetchone())


def ltl_followup(c, oid, d):
    """The follow-up state of letter d (decrypted row): {due, task_id, answered}."""
    tid = d.get("followup_task_id") or None
    if tid and not c.execute("SELECT 1 FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone():
        tid = None  # review 2.153.0: the task was deleted (the column stays set: the watchdog never makes a second one)
    return {"days": d.get("followup_days") or 0, "due": d.get("followup_due"), "task_id": tid,
            "answered": ltl_answered(c, oid, d["id"])}


def ltl_suggest_ref(c, oid, d):
    """The reference line made from the first document letter d answers ('' without one)."""
    r = c.execute("SELECT node_id FROM office_letter_links WHERE letter_id=? AND org_id=? AND kind='answers' ORDER BY id", (d["id"], oid)).fetchall()
    for x in r:
        ok = ltl_doc_ok(c, oid, x["node_id"])
        if ok:
            info = ltl_doc_info(c, *ok)
            return ltl_ref_line(info["refs"], info["date"], d.get("lang") or None)
    return ""


def ltl_graph(c, oid, start_letters=(), start_nodes=()):
    """The connected part of letters and documents (over the links of area oid) around the start ids -> (letter ids,
    node ids), at most LTL_GRAPH_MAX together. Documents the person may not see are left out and not walked through."""
    letters, nodes = set(), set()
    todo_l, todo_n = list(start_letters), list(start_nodes)
    while (todo_l or todo_n) and len(letters) + len(nodes) < LTL_GRAPH_MAX:
        if todo_l:
            lid = todo_l.pop()
            if lid in letters:
                continue
            letters.add(lid)
            for r in c.execute("SELECT node_id FROM office_letter_links WHERE letter_id=? AND org_id=?", (lid, oid)).fetchall():
                if r[0] not in nodes:
                    todo_n.append(r[0])
        else:
            nid = todo_n.pop()
            if nid in nodes or not ltl_doc_ok(c, oid, nid):
                continue
            nodes.add(nid)
            for r in c.execute("SELECT l.letter_id FROM office_letter_links l JOIN office_letters t ON t.id=l.letter_id "
                               "WHERE l.node_id=? AND l.org_id=? AND t.org_id=? AND t.archived=0", (nid, oid, oid)).fetchall():
                if r[0] not in letters:
                    todo_l.append(r[0])
    return letters, nodes


def ltl_items(c, oid, letters, nodes):
    """The history as a list in time order (letters and documents)."""
    out = []
    if letters:
        ids = sorted(letters)
        for r in c.execute(f"SELECT * FROM office_letters WHERE org_id=? AND archived=0 AND id IN ({','.join('?' * len(ids))})", (oid, *ids)).fetchall():
            out.append(ltl_letter_item(c, oid, r))
    for nid in sorted(nodes):
        ok = ltl_doc_ok(c, oid, nid)
        if ok:
            out.append(ltl_node_item(c, *ok))
    out.sort(key=lambda x: (x["date"] or "", 0 if x["type"] == "doc" else 1, x["id"]))
    return out


def ltl_ctx():
    from .letters import lt_ctx
    return lt_ctx()


def ltl_kind(v):
    if v not in LTL_KINDS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    return v


@app.get("/api/office/letters/<int:lid>/links")
def ltl_links_get(lid):
    """The documents of a letter (both directions), the follow-up state and the reference line from the answered document."""
    from .letters import lt_row
    c, uid, oid = ltl_ctx()
    d = lt_row(c, oid, lid)
    return jsonify(links=ltl_links_of(c, oid, d["id"]), followup=ltl_followup(c, oid, d), ref_line=ltl_suggest_ref(c, oid, d),
                   docs_ws="private" if pb_owner(c, oid) is not None else f"org:{oid}")  # the ?ws= of GET /api/docs for the picker


@app.post("/api/office/letters/<int:lid>/links")
def ltl_links_post(lid):
    """Links a document {node_id, kind: answers|reply} (also at a sent letter). answers at a draft without a reference line:
    the line is filled from the document."""
    from .letters import lt_row, lt_update
    c, uid, oid = ltl_ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    kind = ltl_kind(b.get("kind") or "answers")
    d = lt_row(c, oid, lid)
    m, n = ltl_doc(c, oid, b.get("node_id"))
    ltl_link(c, oid, d["id"], n["id"], kind, uid=uid)
    if kind == "answers" and d["status"] == "draft" and not (d.get("ref_line") or "").strip():
        info = ltl_doc_info(c, m, n)
        line = ltl_ref_line(info["refs"], info["date"], d.get("lang") or None)
        if line:
            d = lt_update(c, oid, d["id"], {"ref_line": line})
    bump(c)
    c.commit()
    return jsonify(links=ltl_links_of(c, oid, d["id"]), followup=ltl_followup(c, oid, d), ref_line=d.get("ref_line") or ""), 201


@app.delete("/api/office/letters/<int:lid>/links/<int:nid>")
def ltl_links_del(lid, nid):
    """Removes the link (?kind=answers|reply; without: both). Undo = POST it again."""
    from .letters import lt_row
    c, uid, oid = ltl_ctx()
    d = lt_row(c, oid, lid)
    kind = request.args.get("kind") or ""
    if kind:
        ltl_kind(kind)
    n = c.execute("DELETE FROM office_letter_links WHERE letter_id=? AND org_id=? AND node_id=?" + (" AND kind=?" if kind else ""),
                  (d["id"], oid, nid, *((kind,) if kind else ()))).rowcount
    if not n:
        raise Denied(404)
    bump(c)
    c.commit()
    return jsonify(ok=True, links=ltl_links_of(c, oid, d["id"]), followup=ltl_followup(c, oid, d))


@app.get("/api/office/letters/<int:lid>/thread")
def ltl_thread_get(lid):
    """The history of a letter: every letter and document connected with it over links, in time order."""
    from .letters import lt_row
    c, uid, oid = ltl_ctx()
    d = lt_row(c, oid, lid)
    letters, nodes = ltl_graph(c, oid, [d["id"]])
    return jsonify(items=ltl_items(c, oid, letters, nodes))


@app.get("/api/office/letters/threads")
def ltl_threads_get():
    """The histories with a client (?client_id=) or an address book contact (?contact=): one per connected part, topic = the
    subject / title of its first item, newest first."""
    c, uid, oid = ltl_ctx()
    col = "client_id" if request.args.get("client_id") else "contact_id" if request.args.get("contact") else None
    raw = request.args.get("client_id") or request.args.get("contact") or ""
    if not col or not raw.isdigit():
        raise BadInput(tr("Invalid data"))
    rows = c.execute(f"SELECT id FROM office_letters WHERE org_id=? AND archived=0 AND {col}=? ORDER BY id DESC LIMIT 500", (oid, int(raw))).fetchall()
    done, out = set(), []
    for r in rows:
        if r[0] in done:
            continue
        letters, nodes = ltl_graph(c, oid, [r[0]])
        done |= letters
        items = ltl_items(c, oid, letters, nodes)
        if not items:
            continue
        out.append({"topic": items[0]["title"], "first": items[0]["date"], "last": items[-1]["date"], "count": len(items),
                    "letter_id": r[0], "items": items})
        if len(out) >= 100:
            break
    out.sort(key=lambda t: t["last"] or "", reverse=True)
    return jsonify(threads=out)


# ---------------------------------------------------------------- the document side: links, deadline -> task
@app.get("/api/office/letters/doc/<int:nid>")
def ltl_doc_get(nid):
    """For the document detail: the letters linked with the document (both directions), the deadline and references found,
    the deadline task. {available: false} (no error) when there is no office, the person is no admin of it or the
    document is not in the office's documents space."""
    from .model import office_gate
    from .letters import lt_org
    from ..core.db import db
    c = db()
    try:
        uid = office_gate(c)
        oid = lt_org(c, uid)
        m, n = ltl_doc(c, oid, nid)
    except (Denied, BadInput):
        return jsonify(available=False)
    info = ltl_doc_info(c, m, n)
    letters = []
    for r in c.execute("SELECT t.*, l.kind AS link_kind FROM office_letter_links l JOIN office_letters t ON t.id=l.letter_id "
                       "WHERE l.node_id=? AND l.org_id=? AND t.org_id=? AND t.archived=0 ORDER BY t.letter_date, t.id", (n["id"], oid, oid)).fetchall():
        it = ltl_letter_item(c, oid, r)
        letters.append({"id": it["id"], "subject": it["title"], "date": it["date"], "status": it["status"], "kind": r["link_kind"],
                        "href": it["href"]})
    tid = m["task_id"]
    task = None
    if tid:
        t = c.execute("SELECT id, due, status FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
        if t:  # review 2.153.0: only a task the person may see (another admin's inbox task stays hidden)
            from ..core.access import need_task
            try:
                need_task(c, t["id"], write=False)
            except Denied:
                t = None
        task = {"id": t["id"], "due": t["due"], "status": t["status"]} if t else None
    return jsonify(available=True, letters=letters, deadline=info["deadline"], refs=info["refs"], date=info["date"],
                   sender=info["sender"], task=task, can_write=n["role"] != "view")


@app.post("/api/office/letters/doc/<int:nid>/deadline-task")
def ltl_deadline_task(nid):
    """A task "Deadline: <document>" due on the deadline found (or {due}) in my inbox, the document linked in its text (the
    pattern of POST /api/docs/<nid>/task, the same column doc_meta.task_id). A task already linked: its due date is set
    and it is returned (old_due for the undo). Undo of a new task: DELETE the task + DELETE /api/docs/<nid>/task."""
    from ..core.pages import new_inbox_task
    c, uid, oid = ltl_ctx()
    b = body() or {}
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    m, n = ltl_doc(c, oid, nid, write=True)
    due = b.get("due")
    if due not in (None, ""):
        if not isinstance(due, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
            raise BadInput(tr("Invalid value: {0}", "due"))
        try:
            date.fromisoformat(due)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "due")) from None
    else:
        dl = ltl_doc_info(c, m, n)["deadline"]
        due = dl["date"] if dl else None
    if not due:
        raise BadInput(tr("No deadline found"))
    if m["task_id"]:
        t = c.execute("SELECT id, due FROM tasks WHERE id=? AND deleted_at IS NULL", (m["task_id"],)).fetchone()
        if t:  # review 2.153.0: a task the person cannot change (another admin's) -> a new one of the person's own
            from ..core.access import need_task
            try:
                need_task(c, t["id"], write=True)
            except Denied:
                t = None
        if t:
            c.execute("UPDATE tasks SET due=?, updated_at=? WHERE id=?", (due, iso(now_utc()), t["id"]))
            bump(c)
            c.commit()
            return jsonify(task_id=t["id"], due=due, old_due=t["due"], existing=True)
    title = tr("Deadline: {0}", ltl_doc_title(n))[:300]
    tid = new_inbox_task(c, uid, title, f"[{n['name']}](#docs/{n['id']})", None, None)
    c.execute("UPDATE tasks SET due=? WHERE id=?", (due, tid))
    c.execute("UPDATE doc_meta SET task_id=?, updated_at=? WHERE node_id=?", (tid, iso(now_utc()), n["id"]))
    bump(c)
    c.commit()
    return jsonify(task_id=tid, due=due, title=title, existing=False), 201


# ---------------------------------------------------------------- the follow-up (watchdog)
LTL_FOLLOWUP_EVERY = 3600  # seconds between two runs
_LTL_LAST = {"at": 0.0}


def ltl_followup_tick(c, force=False):
    """Watchdog: a sent letter whose follow-up day (followup_due) has come, without a task yet and without an answer (no
    reply link to a document outside the bin) -> a task "Follow-up: <subject>" due today in the inbox of the person who
    wrote it (else the first admin of the area; nobody when they are no admin any more / disabled / the office is off).
    An answer that comes later leaves the task alone. At most once an hour. -> the number of tasks made."""
    from .fixedimport import fci_people
    from ..core.access import my_inbox
    from ..tasks.validation import log_act
    if not force and time.monotonic() - _LTL_LAST["at"] < LTL_FOLLOWUP_EVERY:
        return 0
    _LTL_LAST["at"] = time.monotonic()
    today = local_now().date().isoformat()
    made = 0
    # the watchdog works for every office area at once (row-level security); every task goes to a person of that area only
    with system_ctx(c):
        rows = c.execute("SELECT * FROM office_letters t WHERE t.status IN ('sent', 'delivered') AND t.archived=0 AND t.followup_due IS NOT NULL "
                         "AND t.followup_due<=? AND t.followup_task_id IS NULL AND NOT EXISTS (SELECT 1 FROM office_letter_links l JOIN fs_nodes n "
                         "ON n.id=l.node_id WHERE l.letter_id=t.id AND l.kind='reply' AND n.deleted_at IS NULL) ORDER BY t.org_id, t.id LIMIT 500",
                         (today,)).fetchall()
        people = {}
        for r in rows:
            oid = r["org_id"]
            try:
                if oid not in people:
                    people[oid] = [p["id"] for p in fci_people(c, oid)]
                pid = r["created_by"] if r["created_by"] in people[oid] else (people[oid][0] if people[oid] else None)
                if pid is None:
                    continue
                if not c.execute("UPDATE office_letters SET followup_task_id=0 WHERE id=? AND followup_task_id IS NULL", (r["id"],)).rowcount:
                    continue
                try:
                    subject = oc_dec_fields(c, oid, "office_letters", r).get("subject") or ""
                except Exception:  # noqa: BLE001 (no key: a title without the subject)
                    subject = ""
                lg = lang(c, pid)
                inbox = my_inbox(c, pid)
                ts = iso(now_utc())
                srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (inbox,)).fetchone()[0]
                title = tr("Follow-up: {0}", subject[:150] or tr("Letter", lg=lg), lg=lg)
                text = tr("No answer to the letter yet.", lg=lg) + f"\n\n[{subject[:150] or tr('Letter', lg=lg)}](#office/letters/{r['id']})"
                tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,due,sort,created_at,updated_at,created_by,url,assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (inbox, title[:300], text, today, srt, ts, ts, pid, PUBLIC_URL.rstrip("/") + f"/#office/letters/{r['id']}", pid))
                log_act(c, tid, "created", uid=pid)
                c.execute("UPDATE office_letters SET followup_task_id=? WHERE id=?", (tid, r["id"]))
                bump(c)
                c.commit()
                made += 1
            except Exception as e:  # noqa: BLE001 (one letter that fails must not hold back the others)
                c.rollback()
                print("letter follow-up", r["id"], "failed:", e, flush=True)
    return made
