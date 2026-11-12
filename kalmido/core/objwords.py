"""2.1002.0 (#5279, stage Q6b of the cross-cutting core, analysis #3563, decided 08.11.2026): one keyed word index for the
sealed texts of every area, `obj_search_words` (core/migrations.d/5279_a.py). It replaced the four indexes of their own:
doc_words (documents, docs/store.py), file_words (recognised text of files, files/textscan.py), wiki_words (knowledge
pages, wiki/wksearch.py) and hub_words (filed mails, hub/hubmail.py), and their four look-ups (search_ids, ts_match, the
mail hub's _search, the body part of wks_search). The open texts stay in obj_search (core/objsearch.py): one place says
"open -> tsvector, sealed -> HMAC, end-to-end -> nothing (the browser)".

One row per (kind, ref_id, h). Kinds (OSW_TABLES): doc (ref_id = the document's fs_nodes id), file_text (a file_text row),
wiki_page, hub_mail. h = HMAC-SHA256 (keyed per workspace with the workspace's key, docs/store.py _index_key; 20 hex
characters) of "p<n>:" + the first n characters of a folded word for n in OSW_PREFIXES, or a mark of the area (a knowledge
page's 'u:<updated_at>' / 'x:...' / tag hashes 't:...'). OSW_MARK ('v:2') = indexed by this version's rules; an object
without it is indexed again in the background (osw_tick, the watchdog; knowledge pages: their own catch-up, wksearch.py).

The rules of 08.11.2026, the same as the open index (core/objsearch.py):
- Umlauts the same everywhere (question 13): a word with ä / ö / ü is indexed folded (ä -> a) and once more with ae / oe /
  ue; a query word is looked up in its variants (osr_variants): "Müller" finds "Mueller" and back.
- Word start everywhere (question 14): every query word of 2+ characters is the start of a word of the text. A word of 2, 3,
  4, 6 or 8 characters is found by its prefix hash alone; a longer or odd one by its longest stored prefix and then checked
  against the opened text (the area's `opened`). Part of a word only in names (the areas match their names themselves).
- Rights are NOT in the index (no org_id: nothing to leak through row-level security either): every caller hands in the ids
  it may read ({workspace: ids}), the index only narrows them. A row never leaves on its own.

Derived data: no export, no import (rebuilt from the imported rows), no foreign key (the delete triggers kalmido_osw_gone on
the source tables take the rows along). The move (osw_move, core/objhooks.py MOVE, one-way): the hashes of the four old
tables are copied first (same key, same hashes: the search works at once after an update, also after a jump over several
releases), the fragment 5279_a drops them after, the back limit rises.
"""
import hashlib
import hmac
import re
import time
import unicodedata

from .db import trigger_ensure
from .kernretire import kern_retire_floor
from .objhooks import MOVE, START
from .objsearch import osr_variants
from .pg import qi, system_ctx, table_exists

OSW_PREFIXES = (2, 3, 4, 6, 8)  # prefix lengths kept per word (4 / 6 / 8 as the old indexes: their copied hashes stay valid)
OSW_WORDS_MAX = 4000  # distinct folded words of one object
OSW_TERMS = 8  # words of a query
OSW_MARK = "v:2"  # the rules of this version (umlaut variants, prefixes of 2 and 3); without it: indexed again
OSW_TICK = 100  # objects read per look-up of the catch-up (2.1028.0, #5783: no longer the limit of a tick, OSW_TICK_S is)
OSW_TICK_S = 2.0  # 2.1028.0 (#5783): seconds of catch-up per watchdog tick, over all kinds (a big document costs more than a mail)
OSW_OLD_SHORT = 4  # 2.1028.0 (#5783): words shorter than this had only their whole-word hash 'w:' in the old indexes
# kind -> its source table (the delete trigger) and the old table the move copies (old table, its id column)
OSW_TABLES = {"doc": "fs_nodes", "file_text": "file_text", "wiki_page": "wiki_pages", "hub_mail": "hub_mails"}
OSW_OLD = {"doc": ("doc_words", "node_id"), "file_text": ("file_words", "ft_id"), "wiki_page": ("wiki_words", "page_id"),
           "hub_mail": ("hub_words", "mail_id")}
OSW_FLOOR_HOW = ("the shared word index obj_search_words replaced doc_words, file_words, wiki_words and hub_words (#5279) - an "
                 "older version would make them again empty and search nothing; go back only with a backup from before")
# kind -> {"table", "id", "where", "reindex": f(c, ids)}: the areas whose objects the watchdog indexes again (osw_register)
OSW_REINDEX = {}

_UML = re.compile("[äöüÄÖÜ]")


def osw_fold(s):
    """Lower case without accents, ß -> ss (the fold of the old indexes, docs/rules.py fold: their hashes stay valid)."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch)).replace("ß", "ss")


def _ae(s):
    return _UML.sub(lambda m: m.group(0) + "e", s)


def osw_words(text, cap=OSW_WORDS_MAX):
    """The distinct folded words of a text (2..40 characters), a word with an umlaut once more in its ae / oe / ue form."""
    out, seen = [], set()
    for tok in re.findall(r"\w+", unicodedata.normalize("NFC", str(text or ""))):
        forms = re.findall(r"\w+", osw_fold(tok)) + (re.findall(r"\w+", osw_fold(_ae(tok))) if _UML.search(tok) else [])
        for w in forms:
            if len(w) < 2 or len(w) > 40 or w in seen:
                continue
            seen.add(w)
            out.append(w)
            if len(out) >= cap:
                return out
    return out


def osw_terms(raw):
    """The words of a query, each as the list of its folded variants (osr_variants: as typed, ä -> ae, ae -> a) of 2+
    characters; a word without such a variant is left out. At most OSW_TERMS."""
    out = []
    for t in re.findall(r"\w+", unicodedata.normalize("NFC", str(raw or ""))):
        vs = sorted({w for v in osr_variants(t[:40]) for w in re.findall(r"\w+", v) if len(w) >= 2})
        if vs:
            out.append(vs)
        if len(out) >= OSW_TERMS:
            break
    return out


OSW_KEY = []  # f(c, ws) -> the workspace's index key: docs/store.py registers _index_key (a later module, no import upward)


def _key(c, ws, create=True):
    return OSW_KEY[0](c, ws, create=create)


def _h(key, s):
    return hmac.new(key, s.encode(), hashlib.sha256).hexdigest()[:20]


def osw_hashes(c, ws, words):
    """The hashes of words (folded, osw_words) in workspace ws."""
    key = _key(c, ws)
    return {_h(key, f"p{n}:" + w[:n]) for w in words for n in OSW_PREFIXES if len(w) >= n}


def osw_hash(c, ws, s):
    """One mark of an area as a hash of ws (a knowledge page's tag 't:...')."""
    return _h(_key(c, ws), s)


def _qhash(key, v):
    """(hash, exact) of a query variant: its longest stored prefix; exact = the prefix is the whole variant."""
    n = max(p for p in OSW_PREFIXES if p <= len(v))
    return _h(key, f"p{n}:" + v[:n]), n == len(v)


def osw_put(c, kind, ref_id, ws=None, text=None, more=(), mark=True):
    """Replace the words of object (kind, ref_id): the hashes of text in ws (None = no words), the area's marks more, and
    OSW_MARK unless mark=False (a page not read yet keeps being late)."""
    c.execute("DELETE FROM obj_search_words WHERE kind=? AND ref_id=?", (kind, int(ref_id)))
    hs = set(more)
    if text and ws:
        hs |= osw_hashes(c, ws, osw_words(text))
    if mark:
        hs.add(OSW_MARK)
    hs = sorted(hs)
    for i in range(0, len(hs), 500):
        part = hs[i:i + 500]
        c.execute("INSERT INTO obj_search_words(kind, ref_id, h) VALUES " + ",".join(["(?,?,?)"] * len(part))
                  + " ON CONFLICT DO NOTHING", [x for h in part for x in (kind, int(ref_id), h)])


def osw_drop(c, kind, ids):
    """The words of these objects go (a new version waits for its text, a page's space goes)."""
    ids = [int(i) for i in ids]
    if ids:
        c.execute("DELETE FROM obj_search_words WHERE kind=? AND ref_id = ANY(CAST(? AS BIGINT[]))", (kind, ids))


def osw_drop_sql(c, kind, sub, args=()):
    """The words of the objects of the sub-select sub (one id column) go."""
    c.execute(f"DELETE FROM obj_search_words WHERE kind=? AND ref_id IN ({sub})", (kind, *args))


def osw_copy(c, kind, src, dst):
    """Object dst takes the words of src (the same content in the same workspace)."""
    c.execute("DELETE FROM obj_search_words WHERE kind=? AND ref_id=?", (kind, int(dst)))
    c.execute("INSERT INTO obj_search_words(kind, ref_id, h) SELECT kind, ?, h FROM obj_search_words WHERE kind=? AND ref_id=? "
              "ON CONFLICT DO NOTHING", (int(dst), kind, int(src)))


def osw_has(c, kind, ref_id, h):
    return c.execute("SELECT 1 FROM obj_search_words WHERE kind=? AND ref_id=? AND h=?", (kind, int(ref_id), h)).fetchone() is not None


def _with(c, kind, h, ids):
    if not ids:
        return set()
    return {r[0] for r in c.execute("SELECT ref_id FROM obj_search_words WHERE kind=? AND h=? AND ref_id = ANY(CAST(? AS BIGINT[]))",
                                    (kind, h, sorted(ids)))}


def osw_term_hits(c, kind, ws, ids, terms, opened, late=None):
    """[set of ids per term]: the objects among ids (workspace ws, all readable by the caller) whose text has the term at a word
    start. opened(c, ws, ids) -> {id: text} reads the texts of the hits that need the check (a longer word found by its
    prefix). late = {id: set of words} of objects read just now (not indexed yet): matched on their words, not on the index."""
    late = late or {}
    ids = set(ids) - set(late)
    key = _key(c, ws, create=False) if ids else None  # a search never makes a key
    out, need, old = [], {}, None
    for ti, vs in enumerate(terms):
        sure, maybe = set(), {}
        for v in vs:
            if not ids:
                break
            h, exact = _qhash(key, v)
            got = _with(c, kind, h, ids)
            if len(v) < OSW_OLD_SHORT:  # 2.1028.0 (#5783): an object not indexed again yet has a short word only whole
                old = _unmarked(c, kind, ids) if old is None else old
                sure |= _with(c, kind, _h(key, "w:" + v), old)
            if exact:
                sure |= got
            else:
                for i in got:
                    maybe.setdefault(i, []).append(v)
        for i, vv in maybe.items():
            if i not in sure:
                need.setdefault(i, {})[ti] = vv
        sure |= {i for i, ws_ in late.items() if any(w.startswith(v) for w in ws_ for v in vs)}
        out.append(sure | set(maybe))
    if need:
        texts = opened(c, ws, sorted(need))
        for i, per in need.items():
            have = set(osw_words(texts.get(i) or ""))
            for ti, vv in per.items():
                if not any(w.startswith(v) for w in have for v in vv):
                    out[ti].discard(i)
    return out


def _unmarked(c, kind, ids):
    """2.1028.0 (#5783): the ids among ids without OSW_MARK (their words are still the copied ones of the old indexes)."""
    return set(ids) - _with(c, kind, OSW_MARK, ids)


def osw_prefilter(c, kind, ws, raw, col):
    """2.1028.0 (#5783): (sql, args) that keeps only the objects (id column col of the caller's query, workspace ws) with a
    stored hash for every word of raw -- the caller narrows its rows in SQL before osw_match decides on them (a superset:
    the longest stored prefix, for a short word also the old whole-word hash). ('', ()) without a word or without a key."""
    terms = osw_terms(raw)
    key = _key(c, ws, create=False) if terms else None  # a search never makes a key
    if not terms or not key:
        return "", ()
    sql, args = [], []
    for vs in terms:
        hs = sorted({_qhash(key, v)[0] for v in vs} | {_h(key, "w:" + v) for v in vs if len(v) < OSW_OLD_SHORT})
        sql.append(f" AND EXISTS (SELECT 1 FROM obj_search_words w WHERE w.kind=? AND w.ref_id={col} "
                   "AND w.h = ANY(CAST(? AS TEXT[])))")
        args += [kind, hs]
    return "".join(sql), tuple(args)


def osw_match(c, kind, cand, raw, opened):
    """The ids among cand ({workspace: ids the caller may read}) whose text has every word of raw at a word start; None for a
    query without a word (2+ characters)."""
    terms = osw_terms(raw)
    if not terms:
        return None
    hits = set()
    for ws, ids in cand.items():
        if ids:
            per = osw_term_hits(c, kind, ws, ids, terms, opened)
            hits |= set.intersection(*per) if per else set()
    return hits


# ---- the start: the delete triggers, the move ---------------------------------------------------------------------------
OSW_GONE_FN = """CREATE OR REPLACE FUNCTION kalmido_osw_gone() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  DELETE FROM obj_search_words WHERE kind = TG_ARGV[0] AND ref_id = OLD.id;
  RETURN NULL;
END $fn$"""


def osw_init(c):
    """Every start (core/objhooks.py START, run by init_db inside its transaction after the fragments): the delete trigger on
    every source table."""
    c.execute(OSW_GONE_FN)
    for kind, t in OSW_TABLES.items():
        if table_exists(c, t):
            trigger_ensure(c, f"kalmido_osw_{kind}_del", t, f"CREATE OR REPLACE TRIGGER kalmido_osw_{kind}_del AFTER DELETE ON "
                           f"{qi(t, set(OSW_TABLES.values()))} FOR EACH ROW EXECUTE FUNCTION kalmido_osw_gone('{kind}')")


def osw_move(c):
    """2.1002.0 (#5279): before the fragment 5279_a drops the old word tables (core/objhooks.py MOVE, before the fragments'
    AFTER): their hashes into obj_search_words (the same keys and hashes; rows whose object is gone stay behind), the back
    limit raised once. The objects lack OSW_MARK and are indexed again by the new rules in the background."""
    moved = False
    with system_ctx(c):
        for kind, (old, col) in OSW_OLD.items():
            if not table_exists(c, old):
                continue
            t = OSW_TABLES[kind]
            c.execute(f"INSERT INTO obj_search_words(kind, ref_id, h) SELECT '{kind}', w.{qi(col, {col})}, w.h "
                      f"FROM {qi(old, {old})} w WHERE EXISTS (SELECT 1 FROM {qi(t, {t})} r WHERE r.id=w.{qi(col, {col})}) "
                      "AND w.h <> 'tv:1' ON CONFLICT DO NOTHING")
            moved = True
    if moved:
        kern_retire_floor(c, how=OSW_FLOOR_HOW)
    return moved


MOVE.append(osw_move)
START.append(("osw_init", False, osw_init))


# ---- the catch-up: objects without OSW_MARK ------------------------------------------------------------------------------
def osw_register(kind, table, id_col, where, reindex):
    """An area whose objects the watchdog indexes again: rows of table (id_col = the object's id, where = the rows that
    have an index) without OSW_MARK; reindex(c, ids) writes their words with osw_put (mark included)."""
    OSW_REINDEX[kind] = {"table": table, "id": id_col, "where": where, "reindex": reindex}


def osw_late(c, kind, limit=OSW_TICK):
    """The ids of kind's objects without OSW_MARK (at most limit); not the ones whose catch-up failed in this process
    (_BAD: a key that cannot open them -- they keep their copied words and wait for the next start)."""
    r = OSW_REINDEX[kind]
    t, col = r["table"], r["id"]
    return [x[0] for x in c.execute(
        f"SELECT x.{qi(col, {col})} FROM {qi(t, {t})} x WHERE {r['where']} AND NOT EXISTS (SELECT 1 FROM obj_search_words w "
        f"WHERE w.kind=? AND w.ref_id=x.{qi(col, {col})} AND w.h=?) AND NOT (x.{qi(col, {col})} = ANY(CAST(? AS BIGINT[]))) "
        f"ORDER BY x.{qi(col, {col})} DESC LIMIT {int(limit)}",
        (kind, OSW_MARK, sorted(_BAD.get(kind, ())))).fetchall()]


_BAD = {}  # 2.1002.0 (#5279, review): kind -> ids whose catch-up failed in this process (skipped until the next start)
_IDLE = {}  # kind -> time.monotonic() when its catch-up last found nothing (this process)
OSW_IDLE_S = 600  # a kind without late objects is asked again after so many seconds (every write sets the mark itself)


_TURN = [0]  # 2.1028.0 (#5783): the kind the next tick starts with (a kind with many late objects holds no other one back)


def _late_locked(c, kind, rid):
    """2.1028.0 (#5783): the source row of the object locked (FOR UPDATE) and still without OSW_MARK? A save that came first
    wrote its words and the mark (nothing to do); one that comes later waits for this transaction and writes after it -- the
    catch-up never overwrites a fresher save with an older text."""
    r = OSW_REINDEX[kind]
    t, col = r["table"], r["id"]
    if c.execute(f"SELECT 1 FROM {qi(t, {t})} WHERE {qi(col, {col})}=? FOR UPDATE", (int(rid),)).fetchone() is None:
        return False
    return not osw_has(c, kind, rid, OSW_MARK)


def osw_tick(c, limit=OSW_TICK, force=False, budget=None):
    """The watchdog (notify/push.py): objects indexed again by this version's rules. {kind: n}. A kind that had none is
    skipped for OSW_IDLE_S (late objects come only from the move, a restore or an older image).
    2.1028.0 (#5783): a time budget per tick (budget seconds, default OSW_TICK_S, over all kinds, starting with the next kind
    in turn) instead of a fixed number per kind; limit = objects per look-up. Each object under the lock of its source row
    (_late_locked) and committed on its own (the lock is held for one object only)."""
    done = {}
    end = time.monotonic() + (OSW_TICK_S if budget is None else budget)
    kinds = list(OSW_REINDEX)
    if kinds:
        _TURN[0] %= len(kinds)
        kinds = kinds[_TURN[0]:] + kinds[:_TURN[0]]
        _TURN[0] += 1
    with system_ctx(c):  # every workspace's objects; nobody gets a text, only the hashes are written
        for kind in kinds:
            r = OSW_REINDEX[kind]
            if time.monotonic() >= end:
                break
            if not force and time.monotonic() - _IDLE.get(kind, -1e9) < OSW_IDLE_S:
                continue
            ids = osw_late(c, kind, limit)
            if not ids:
                _IDLE[kind] = time.monotonic()
                continue
            _IDLE.pop(kind, None)
            n, tried = 0, set()
            while ids and time.monotonic() < end:
                tried |= set(ids)
                for i in ids:  # 2.1002.0 (#5279, review): one object a key cannot open holds only itself, not the run
                    if time.monotonic() >= end:
                        break
                    try:
                        with c.savepoint():
                            if _late_locked(c, kind, i):
                                r["reindex"](c, [i])
                                n += 1
                    except Exception:  # noqa: BLE001 -- OrgCryptError and the like: its copied words stay, no mark
                        _BAD.setdefault(kind, set()).add(int(i))
                    c.commit()  # each object's work stays and its row lock goes at once
                # the next ones; one an area's reindex left without its mark is not taken twice in a tick
                ids = [i for i in osw_late(c, kind, limit) if i not in tried] if time.monotonic() < end else []
            done[kind] = n
    return done
