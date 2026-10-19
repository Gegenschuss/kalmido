"""2.122.0 B (#2294): the documents search, combinable like an archive's: several tags (every one / one of them / none of
these), several senders and types, the document date and the date of arrival, folder, file type, "without tag / sender /
type", and a search syntax in the search field (German and English keys):

    tag:Steuer  absender:Telekom  sender:"Muster GmbH"  typ:Rechnung  type:invoice  datum:2025  date:2025-03..2025-06
    eingang:>2025-01-01  added:2025-03  "genauer Text"  -wort  -tag:Privat  -"ganzer Satz"

Several tag: = every one of them, several absender: / typ: = one of them. Names match without regard to case (the whole
name first, else a part of it), only names of the workspaces whose documents the person sees (sender names are sealed:
they are opened per workspace as in the filters). A name nobody has = no hit. The rest of the words go to the word index
(docs/store.py search_ids); exact phrases and excluded words / phrases are checked against the opened text and the name.
Nothing here reads a document the caller does not already filter by visibility (docs/web.py doc_query)."""
import re
from datetime import date, timedelta

from . import rules as RU
from . import store as S

DSR_KEYS = {"tag": "tag", "tags": "tag", "absender": "sender", "sender": "sender", "von": "sender", "from": "sender",
            "typ": "type", "type": "type", "art": "type", "datum": "date", "date": "date", "eingang": "added", "added": "added"}
DSR_FTYPES = ("pdf", "image", "office", "text", "other")
DSR_TOKEN = re.compile(r'(-?)(?:([A-Za-zÄÖÜäöü]+):(?:"([^"]*)"|(\S+))|"([^"]*)"|(\S+))')
DSR_TEXT_MAX = 3000   # documents whose text is opened for a phrase / an exclusion
_ISO = r"\d{4}-\d{2}-\d{2}"


def dsr_parse(q):
    """The search field -> {words: "rest", phrases, not_words, not_phrases, tag, not_tag, sender, not_sender, type, not_type,
    date: [(from, to)], added: [(from, to)]}. Unknown keys stay words (a time "10:30", "http://x")."""
    out = {"words": [], "phrases": [], "not_words": [], "not_phrases": [], "tag": [], "not_tag": [], "sender": [], "not_sender": [],
           "type": [], "not_type": [], "date": [], "added": []}
    for m in DSR_TOKEN.finditer(str(q or "")[:500]):
        neg, key, kq, kv, phrase, word = m.groups()
        if key is not None:
            k = DSR_KEYS.get(key.lower())
            val = (kq if kq is not None else kv or "").strip()
            if not k:
                (out["not_words"] if neg else out["words"]).append(f"{key}:{val}")
                continue
            if not val:
                continue
            if k in ("date", "added"):
                rng = dsr_range(val)
                if rng:
                    out[k].append(rng)
                continue
            out[("not_" if neg else "") + k].append(val[:S.NAME_MAX])
        elif phrase is not None:
            if phrase.strip():
                out["not_phrases" if neg else "phrases"].append(phrase.strip()[:200])
        elif word:
            out["not_words" if neg else "words"].append(word.lstrip("-") if neg else word)
    out["words"] = " ".join(out["words"])
    return out


def _day(s, end):
    """'2025' | '2025-03' | '03.2025' | '2025-03-14' | '14.03.2025' -> the first (end: the last) day as ISO, else None."""
    s = s.strip()
    try:
        if re.fullmatch(r"\d{4}", s):
            return f"{s}-12-31" if end else f"{s}-01-01"
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", s) or re.fullmatch(r"(\d{1,2})\.(\d{4})", s)
        if m:
            y, mo = (int(m.group(1)), int(m.group(2))) if len(m.group(1)) == 4 else (int(m.group(2)), int(m.group(1)))
            first = date(y, mo, 1)
            if not end:
                return first.isoformat()
            return (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)).isoformat()
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None
    return None


def dsr_range(v):
    """A date value of the syntax -> (from or None, to or None), None when it is no date: 2025, 2025-03, 14.03.2025,
    a..b, >a, >=a, <b, <=b."""
    v = v.strip()
    if ".." in v:
        a, b = v.split("..", 1)
        f, t = (_day(a, False) if a else None), (_day(b, True) if b else None)
        return (f, t) if (f or t) and (not a or f) and (not b or t) else None
    m = re.fullmatch(r"([<>]=?)(.+)", v)
    if m:
        op, d = m.groups()
        if op[0] == ">":
            x = _day(d, op == ">")
            if x and op == ">":
                x = (date.fromisoformat(x) + timedelta(days=1)).isoformat()
            return (x, None) if x else None
        x = _day(d, op == "<=")
        if x and op == "<":
            x = (date.fromisoformat(_day(d, False)) - timedelta(days=1)).isoformat()
        return (None, x) if x else None
    f, t = _day(v, False), _day(v, True)
    return (f, t) if f and t else None


def dsr_ids(args, key):
    """Repeated ?key=1,7 values (or "1,7;3") -> [[1, 7], [3]]: one group per chosen name (its ids in several workspaces)."""
    vals = args.getlist(key) if hasattr(args, "getlist") else ([args.get(key)] if not isinstance(args.get(key), list) else args.get(key))
    out = []
    for v in vals:
        for grp in str(v or "").split(";"):  # "1,7;3" = two names in one value (the API v1 takes each key once)
            ids = [int(x) for x in grp.split(",") if x.strip().isdigit()][:50]
            if ids:
                out.append(ids)
    return out[:30]


def dsr_label_ids(c, wss, kind, name):
    """The ids of label `name` in the workspaces wss: the whole name (case-insensitive) where a workspace has it, else the
    labels containing it."""
    low = name.strip().lower()
    out = []
    for ws in wss:
        names = S.labels(c, ws, kind)
        hit = [x["id"] for x in names if (x["name"] or "").lower() == low]
        out += hit or [x["id"] for x in names if low and low in (x["name"] or "").lower()]
    return out


def _in(col, ids, params):
    params += ids
    return f"{col} IN ({','.join('?' * len(ids))})"


def dsr_filters(c, args, where, params, base_where, base_params):
    """Adds the conditions of the filters and of the search syntax (args: the request's) to where / params (doc_meta d,
    fs_nodes n) -> (rest of the words for the word index, {phrases, not_words, not_phrases})."""
    flat = lambda key: [i for g in dsr_ids(args, key) for i in g]  # noqa: E731
    for key, col in (("sender", "d.sender_id"), ("type", "d.type_id")):
        ids = flat(key)
        if ids:
            where.append(_in(col, ids, params))
    tags = dsr_ids(args, "tag")
    if tags:
        parts = [_in("d.node_id IN (SELECT node_id FROM doc_node_tags WHERE tag_id", g, params) + ")" for g in tags]
        where.append("(" + (" AND " if str(args.get("tag_mode") or "") == "all" else " OR ").join(parts) + ")")
    nt = flat("not_tag")
    if nt:
        where.append("NOT " + _in("d.node_id IN (SELECT node_id FROM doc_node_tags WHERE tag_id", nt, params) + ")")
    for key, expr, op in (("from", "COALESCE(d.doc_date, substr(n.created_at, 1, 10))", ">="), ("to", "COALESCE(d.doc_date, substr(n.created_at, 1, 10))", "<="),
                          ("added_from", "substr(n.created_at, 1, 10)", ">="), ("added_to", "substr(n.created_at, 1, 10)", "<=")):
        v = str(args.get(key) or "")[:10]
        if re.fullmatch(_ISO, v):
            where.append(f"{expr} {op} ?")
            params.append(v)
    if str(args.get("review") or "") in ("1", "true"):
        where.append("d.review = 1")
    st = str(args.get("state") or "")
    if st in S.STATES:
        where.append("d.state = ?")
        params.append(st)
    for key, cond in (("no_tag", "NOT EXISTS (SELECT 1 FROM doc_node_tags x WHERE x.node_id=d.node_id)"),
                      ("no_sender", "d.sender_id IS NULL"), ("no_type", "d.type_id IS NULL")):
        if str(args.get(key) or "") in ("1", "true"):
            where.append(cond)
    fol = flat("folder")
    if fol:
        where.append(_in("n.parent_id", fol, params))
    ft = [x for x in str(args.get("ftype") or "").split(",") if x in DSR_FTYPES]
    if ft:
        kinds = {"pdf": "n.mime = 'application/pdf'", "image": "n.mime ILIKE 'image/%'", "text": "n.mime ILIKE 'text/%'",
                 "office": "(n.mime ILIKE 'application/vnd.%' OR n.mime ILIKE 'application/msword%')"}
        other = "NOT (" + " OR ".join(f"COALESCE({v}, FALSE)" for v in kinds.values()) + ")"
        where.append("(" + " OR ".join(kinds.get(x, other) for x in ft) + ")")
    p = dsr_parse(args.get("q"))
    if any(p[k] for k in ("tag", "not_tag", "sender", "not_sender", "type", "not_type")):
        wss = [r[0] for r in c.execute(f"SELECT DISTINCT d.ws FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE {' AND '.join(base_where)}",
                                       base_params)]
        for name in p["tag"]:  # every tag:
            ids = dsr_label_ids(c, wss, "tag", name)
            where.append(_in("d.node_id IN (SELECT node_id FROM doc_node_tags WHERE tag_id", ids, params) + ")" if ids else "FALSE")
        nt = [i for name in p["not_tag"] for i in dsr_label_ids(c, wss, "tag", name)]
        if nt:
            where.append("NOT " + _in("d.node_id IN (SELECT node_id FROM doc_node_tags WHERE tag_id", nt, params) + ")")
        for kind, col in (("sender", "d.sender_id"), ("type", "d.type_id")):
            if p[kind]:  # one of them
                ids = [i for name in p[kind] for i in dsr_label_ids(c, wss, kind, name)]
                where.append(_in(col, ids, params) if ids else "FALSE")
            no = [i for name in p["not_" + kind] for i in dsr_label_ids(c, wss, kind, name)]
            if no:
                where.append(f"({col} IS NULL OR NOT " + _in(col, no, params) + ")")
    for key, expr in (("date", "COALESCE(d.doc_date, substr(n.created_at, 1, 10))"), ("added", "substr(n.created_at, 1, 10)")):
        for f, t in p[key]:
            if f:
                where.append(f"{expr} >= ?")
                params.append(f)
            if t:
                where.append(f"{expr} <= ?")
                params.append(t)
    return p["words"].strip()[:200], {"phrases": p["phrases"], "not_words": p["not_words"], "not_phrases": p["not_phrases"]}


def dsr_text(c, by_ws, hit, text):
    """hit (a set of node ids, None = every one of by_ws) narrowed by the exact phrases and the excluded words / phrases
    of text -> a set (None when there is nothing to narrow)."""
    if not any(text.values()):
        return hit
    for ph in text["phrases"]:  # the words of a phrase via the index first, then the phrase itself in the text
        got = S.search_ids(c, by_ws, ph)
        if got is not None:
            hit = got if hit is None else hit & got
    for w in text["not_words"]:
        got = S.search_ids(c, by_ws, w)
        if got:
            hit = (set(i for ids in by_ws.values() for i in ids) if hit is None else hit) - got
    if hit is None:
        hit = set(i for ids in by_ws.values() for i in ids)
    if text["phrases"] or text["not_phrases"]:
        need = [" ".join(RU.fold(x).split()) for x in text["phrases"]]
        avoid = [" ".join(RU.fold(x).split()) for x in text["not_phrases"]]
        ok = set()
        for i in sorted(hit)[:DSR_TEXT_MAX]:
            m = S.meta_row(c, i)
            name = c.execute("SELECT name FROM fs_nodes WHERE id=?", (i,)).fetchone()
            t = " ".join(RU.fold(f"{name[0] if name else ''}\n{S.meta_text(c, m) if m else ''}").split())
            if all(x in t for x in need) and not any(x in t for x in avoid if x):
                ok.add(i)
        hit = ok
    return hit
