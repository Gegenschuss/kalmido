"""2.981.0 (#5278, stage Q6a of the cross-cutting core, analysis #3563, decided 08.11.2026): one search index for the open texts
of every area, `obj_search` (core/migrations.d/5278_a.py). It replaced the side tables task_fts / cmt_fts (tasks/ftsearch.py),
the trigram indexes on the message tables and on tasks (collab/msgsearch.py, schema.py), the column contacts.search and the
plain ILIKE of the task, note and contact searches.

One row per object (kind, ref_id): org_ref / owner_id / node_id (the container: a task's or note's project, a contact's address
book, a team chat message's room, an agent chat's agent), pkind / pid (a comment's object), title, names (folded names and
numbers for the part-of-a-word match) and tsv (the 'simple' configuration over kalmido_fold: title weight A, text B, more C).
Kinds (OSR_SOURCES): task, comment (obj_comments of every kind but a document's sealed note, #5278), note, contact, wiki_page (the page's name only: its text is
sealed and keeps its HMAC word index, wiki/wksearch.py), tchat (team chat messages without end-to-end text), agent_chat.

Filled by triggers on the source tables (every write path, also the old ones and rows written straight into the tables), and
at every start for the rows written while the triggers were missing (a restore, an older image); a new OSR_VERSION or fold
function builds it again. Derived data: no export, no import (the import's rows fill it through the triggers).

The rules (decisions of 08.11.2026):
- Umlauts the same everywhere (question 13): kalmido_fold (unaccent + lower case; a text with ä / ö / ü / ß once more with
  ae / oe / ue / ss) and every query word in its variants (osr_variants): "Müller" finds "Mueller" and back.
- Word start everywhere, part of a word only in names and numbers (question 14): every query word is a prefix ("word:*") of a
  word of the text; osr_cond(..., names=True) also takes it anywhere inside `names` (a contact's names and phone numbers, a
  task's ticket key, a knowledge page's name).
- Rights are NOT in the index: every reader joins the source row and applies the area's own visibility (a task's
  _task_cond, a note's notes_visible_sql, a contact's books, a page's wiki_may_read, a message's room) or, for comments of other
  kinds, obj_role >= view of the object per hit (OSR_KINDS: a kind without a registered check gives no hits). Kinds with a cap
  hook (calendars, address books, team chat) are never listed through obj_visible_sql (docs/dev/kern.md). obj_search itself
  has no org_id column on purpose (org_ref): row-level security would stop its GIN index (@@ is not leakproof, like ILIKE in
  #5116) -- so no reader may hand out a row of it without joining its source row (which stands under its policy) and the
  area's check; the helpers here return ids for such a join only.
"""
import re
import unicodedata

from .access import live_sql
from .db import gset, gsetting, trigger_ensure
from .kernretire import kern_retire_floor
from .objhooks import MOVE
from .pg import like_escape, qi, system_ctx, table_columns, table_exists

OSR_VERSION = "1"        # a new version empties the index and builds it again at the next start
OSR_FOLD_VERSION = "2"   # the fold function (was collab/msgsearch.py INDEX_VERSION, settings key msg_fts_v)
OSR_CAP = 100000         # characters of a text that the index reads (the tsvector size limit never makes a write fail)
OSR_TERMS = 8            # words of a query
OSR_NAMES_CAP = 4000

# ---- the fold (unaccent + lower case, a text with umlauts once more with ae / oe / ue / ss) -- moved from collab/msgsearch.py
_FOLD = "{x}"
for _a, _b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
    _FOLD = f"replace({_FOLD},'{_a}','{_b}')"


def osr_fold_fn(c):
    """SQL: CREATE OR REPLACE FUNCTION kalmido_fold(text) -- unaccent schema-qualified (an index expression must not depend on
    the search path)."""
    sch = c.execute("SELECT extnamespace::regnamespace::text FROM pg_extension WHERE extname='unaccent'").fetchone()[0]
    ua = f"{sch}.unaccent('{sch}.unaccent'::regdictionary, %s)"
    return ("CREATE OR REPLACE FUNCTION kalmido_fold(t text) RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $fold$\n"
            f"DECLARE x text := lower({ua % 't'}); y text := lower({ua % _FOLD.format(x='t')});\n"
            "BEGIN RETURN CASE WHEN x = y THEN x ELSE x || chr(10) || y END; END $fold$")


def osr_fold_char(ch):
    """One character folded like kalmido_fold (in Python: the snippets' marks, the query words)."""
    if ch == "ß":
        return "ss"
    d = unicodedata.normalize("NFKD", ch)
    return "".join(x for x in d if not unicodedata.combining(x)).lower() or ch.lower()


def osr_variants(term):
    """Folded forms of a query word: as typed (ä -> a), with ä -> ae (the text says "ae") and ae -> a (the text says "ä")."""
    f = "".join(osr_fold_char(ch) for ch in term)
    ex = "".join(osr_fold_char(ch) for ch in re.sub("[äöüÄÖÜ]", lambda m: m.group(0) + "e", term))
    return {f, ex, f.replace("ae", "a").replace("oe", "o").replace("ue", "u")}


def osr_terms(q):
    """The words of a query (letters and digits only, max OSR_TERMS, each max 64 characters)."""
    return [w[:64] for w in re.findall(r"[^\W_]+", q or "")][:OSR_TERMS]


def _alnum_variants(t):
    return sorted({"".join(ch for ch in v if ch.isalnum()) for v in osr_variants(t)} - {""})


def osr_word_query(t):
    """to_tsquery text of one word: a prefix in each of its folded variants (OR). The lexemes hold letters / digits only, so
    nothing in them can be read as a tsquery operator."""
    vs = _alnum_variants(t)
    return "(" + " | ".join(f"'{v}':*" for v in vs) + ")" if vs else ""


def osr_query(terms):
    """to_tsquery text: every word as a prefix in each of its variants, all words required (AND); '' = nothing to search."""
    return " & ".join(p for p in (osr_word_query(t) for t in terms) if p)


def osr_cond(raw, alias="s", names=False):
    """(SQL condition on the obj_search row alias, its parameters) for the query raw, or (None, []) when it has no word.
    names=True: a word may also stand anywhere in alias.names (part of a name or a number; question 14)."""
    terms = osr_terms(raw)
    tsq = osr_query(terms)
    if not tsq:
        return None, []
    if not names:
        return f"{alias}.tsv @@ to_tsquery('simple'::regconfig, ?)", [tsq]
    parts, args = [], []
    for t in terms:
        wq = osr_word_query(t)
        if not wq:
            continue
        parts.append(f"({alias}.tsv @@ to_tsquery('simple'::regconfig, ?) OR {alias}.names LIKE ANY(CAST(? AS TEXT[])))")
        args += [wq, ["%" + like_escape(v) + "%" for v in _alnum_variants(t)]]
    return " AND ".join(parts), args


def osr_ids_sql(kind, raw, names=False):
    """(SQL "ref_id IN (...)" sub-select of the objects of kind matching raw, its parameters), or (None, [])."""
    cond, args = osr_cond(raw, "s", names)
    if cond is None:
        return None, []
    return f"(SELECT s.ref_id FROM obj_search s WHERE s.kind='{kind}' AND {cond})", args


# ---- the sources: what each kind indexes (SQL over the row {r}: NEW in the triggers, the table's alias when filling)
def _vec(expr, w):
    """Punctuation becomes a space before the parser reads the text: a word of a link, a path or an e-mail address
    ("https://example.com/needle", "src/zauber.py", "anna@firma.de") is a word of its own, so its start is found like any
    other word (the parser would keep "/needle" or the whole address as one token)."""
    return (f"setweight(to_tsvector('simple'::regconfig, regexp_replace(kalmido_fold(left(COALESCE({expr}, ''), {OSR_CAP})), "
            f"'[[:punct:]]+', ' ', 'g')), '{w}')")


OSR_SOURCES = {
    # a task: title A, notes B, its link and code snippets (path + code) C; names = its ticket key "APP-12"
    "task": {"table": "tasks", "org": "{r}.org_id", "owner": "{r}.created_by", "node": "{r}.list_id",
             "title": "{r}.title", "body": "{r}.content",
             "more": "concat_ws(' ', {r}.url, (SELECT string_agg(concat_ws(' ', j->>'path', left(j->>'code', 20000)), ' ') "
                     "FROM jsonb_array_elements(CASE WHEN jsonb_typeof({r}.snippets)='array' THEN {r}.snippets ELSE '[]'::jsonb END) j))",
             "names": "CASE WHEN {r}.ticket_no IS NOT NULL THEN (SELECT l.ticket_key || '-' || {r}.ticket_no FROM lists l "
                      "WHERE l.id={r}.list_id AND l.ticket_key IS NOT NULL) END",
             "cols": ("title", "content", "url", "snippets", "ticket_no", "list_id", "org_id", "created_by")},
    # a comment of any kind (obj_comments): its text; pkind / pid = its object. 2.981.0 (#5278 x #5273): not a document's note
    # (kind doc_note): its text is sealed with the workspace key (a ciphertext in a word index finds nothing and its rights
    # are the document's) -- the notes are found by the documents' own word index (docs/store.py doc_index). skip = the rows
    # of the table that get no index row (the trigger deletes theirs, the start clears what an earlier build left)
    "comment": {"table": "obj_comments", "org": "{r}.org_id", "owner": "{r}.user_id", "node": "NULL::bigint",
                "pkind": "{r}.kind", "pid": "{r}.ref_id", "title": "NULL::text", "body": "{r}.body",
                "skip": "{r}.kind = 'doc_note'", "cols": ("body", "org_id", "kind", "ref_id")},
    # a note of a project: title A, text B, tags C
    "note": {"table": "notes", "org": "(SELECT l.org_id FROM lists l WHERE l.id={r}.list_id)", "owner": "{r}.created_by",
             "node": "{r}.list_id", "title": "{r}.title", "body": "{r}.body", "more": "{r}.tags",
             "cols": ("title", "body", "tags", "list_id")},
    # a contact: its name A; names, company, function, note, e-mails, phones, addresses, groups B; names = the names, the
    # company and the phone numbers (digits) for the part-of-a-word match
    "contact": {"table": "contacts", "org": "{r}.org_id", "owner": "{r}.created_by", "node": "{r}.book_id",
                "title": "COALESCE(NULLIF({r}.fn, ''), {r}.org)",
                "body": "concat_ws(' ', {r}.given, {r}.middle, {r}.family, {r}.nickname, {r}.org, {r}.dept, {r}.title, left({r}.note, 500), "
                        "kalmido_osr_vals({r}.emails, ARRAY['value']), kalmido_osr_vals({r}.phones, ARRAY['value']), "
                        "kalmido_osr_vals({r}.addresses, ARRAY['street', 'city', 'code', 'country']), kalmido_osr_vals({r}.groups, NULL))",
                "names": "concat_ws(' ', {r}.fn, {r}.given, {r}.family, {r}.nickname, {r}.org, "
                         "kalmido_osr_vals({r}.phones, ARRAY['value'], true))",
                "cols": ("fn", "given", "middle", "family", "nickname", "org", "dept", "title", "note", "emails", "phones",
                         "addresses", "groups", "book_id", "org_id", "created_by")},
    # a knowledge page: its name only (the text is sealed, wiki/wksearch.py); names = the name (part of a word)
    "wiki_page": {"table": "wiki_pages", "org": "{r}.org_id", "owner": "{r}.owner_id", "node": "NULL::bigint",
                  "title": "regexp_replace({r}.path, '^.*/', '')", "body": "{r}.path", "names": "{r}.path",
                  "cols": ("path", "org_id", "owner_id")},
    # a team chat message without end-to-end text; node = its room
    "tchat": {"table": "tchat_msgs", "org": "NULL::bigint", "owner": "{r}.user_id", "node": "{r}.room_id",
              "title": "NULL::text", "body": "CASE WHEN {r}.enc IS NULL THEN {r}.body END", "cols": ("body", "enc")},
    # a message of the chat with an agent; node = the agent, owner = the person
    "agent_chat": {"table": "agent_chat", "org": "NULL::bigint", "owner": "{r}.user_id", "node": "{r}.agent_id",
                   "title": "NULL::text", "body": "{r}.body", "cols": ("body",)},
}

OSR_VALS_FN = """CREATE OR REPLACE FUNCTION kalmido_osr_vals(t text, keys text[], digits boolean DEFAULT false) RETURNS text
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $f$
DECLARE j jsonb; o text;
BEGIN  -- the text values of a JSON list kept as TEXT (contacts' e-mails, phones ...); '' for anything else, never an error;
       -- digits: each value only with its digits and + (a phone number as one word: "+49 171 1234" -> "+491711234")
  IF t IS NULL OR t = '' OR left(ltrim(t), 1) <> '[' THEN RETURN ''; END IF;
  BEGIN j := t::jsonb; EXCEPTION WHEN others THEN RETURN ''; END;
  IF jsonb_typeof(j) <> 'array' THEN RETURN ''; END IF;
  IF keys IS NULL THEN
    SELECT string_agg(e #>> '{}', ' ') INTO o FROM jsonb_array_elements(j) e WHERE jsonb_typeof(e) IN ('string', 'number');
  ELSE
    SELECT string_agg(CASE WHEN digits THEN regexp_replace(e ->> k, '[^0-9+]', '', 'g') ELSE e ->> k END, ' ') INTO o
      FROM jsonb_array_elements(j) e, unnest(keys) k WHERE jsonb_typeof(e) = 'object' AND e ->> k <> '';
  END IF;
  RETURN COALESCE(o, '');
END $f$"""


def _x(src, key, r, default="NULL"):
    return src.get(key, default).replace("{r}", r)


def _values(kind, r):
    """The column values of obj_search for one row of kind's table (alias / NEW r) -- one definition for trigger and fill."""
    s = OSR_SOURCES[kind]
    names = f"left(kalmido_fold(COALESCE({_x(s, 'names', r)}, '')), {OSR_NAMES_CAP})" if "names" in s else "''"
    tsv = " || ".join(_vec(_x(s, k, r), w) for k, w in (("title", "A"), ("body", "B"), ("more", "C")) if k in s)
    return (f"'{kind}', {r}.id, {_x(s, 'org', r)}, {_x(s, 'owner', r)}, {_x(s, 'node', r)}, {_x(s, 'pkind', r, 'NULL::text')}, "
            f"{_x(s, 'pid', r, 'NULL::bigint')}, left(COALESCE({_x(s, 'title', r)}, ''), 500), {names}, {tsv}")


OSR_COLS = "kind, ref_id, org_ref, owner_id, node_id, pkind, pid, title, names, tsv"
OSR_INSERT = "INSERT INTO obj_search(" + OSR_COLS + ")"
OSR_TABLES = {s["table"] for s in OSR_SOURCES.values()}
OSR_SET = ", ".join(f"{x}=EXCLUDED.{x}" for x in OSR_COLS.split(", ")[2:]) + ", updated_at=CURRENT_TIMESTAMP"
OSR_UPSERT = "ON CONFLICT (kind, ref_id) DO UPDATE SET " + OSR_SET


def _skip(kind, r):
    """2.981.0 (#5278): the SQL of the rows of kind's table that get no index row (OSR_SOURCES skip), FALSE without."""
    return _x(OSR_SOURCES[kind], "skip", r, "FALSE")


def _skip_branch(kind):
    if "skip" not in OSR_SOURCES[kind]:
        return ""
    return f"\n  ELSIF {_skip(kind, 'NEW')} THEN\n    DELETE FROM obj_search WHERE kind = '{kind}' AND ref_id = NEW.id;"


def _fn(kind):
    """The trigger function of kind: the row as system (row-level security: the index row follows its source, whoever wrote it)."""
    return f"""CREATE OR REPLACE FUNCTION kalmido_osr_{kind}() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE prev text := current_setting('app.role', true);
BEGIN
  PERFORM set_config('app.role', 'system', true);
  IF TG_OP = 'DELETE' THEN
    DELETE FROM obj_search WHERE kind = '{kind}' AND ref_id = OLD.id;{_skip_branch(kind)}
  ELSIF to_regprocedure('kalmido_fold(text)') IS NULL THEN  -- the fold function missing (until the next start): the write goes on,
    DELETE FROM obj_search WHERE kind = '{kind}' AND ref_id = NEW.id;  -- the start fills the row (an IF: no subtransaction per row)
  ELSE
    {OSR_INSERT} VALUES ({_values(kind, 'NEW')})
      {OSR_UPSERT};
  END IF;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $fn$"""


def _triggers(c, kind):
    s = OSR_SOURCES[kind]
    t = s["table"]
    cols = [x for x in s["cols"] if x in table_columns(c, t)]
    changed = " OR ".join(f"OLD.{x} IS DISTINCT FROM NEW.{x}" for x in cols)
    trigger_ensure(c, f"kalmido_osr_{kind}_ins", t, f"CREATE OR REPLACE TRIGGER kalmido_osr_{kind}_ins AFTER INSERT ON {t} "
                   f"FOR EACH ROW EXECUTE FUNCTION kalmido_osr_{kind}()")
    trigger_ensure(c, f"kalmido_osr_{kind}_upd", t, f"CREATE OR REPLACE TRIGGER kalmido_osr_{kind}_upd AFTER UPDATE OF {', '.join(cols)} "
                   f"ON {t} FOR EACH ROW WHEN ({changed}) EXECUTE FUNCTION kalmido_osr_{kind}()")
    trigger_ensure(c, f"kalmido_osr_{kind}_del", t, f"CREATE OR REPLACE TRIGGER kalmido_osr_{kind}_del AFTER DELETE ON {t} "
                   f"FOR EACH ROW EXECUTE FUNCTION kalmido_osr_{kind}()")


def osr_fill(c, kind):
    """The rows of kind's table without an index row get one; index rows whose source is gone go. Returns the rows added."""
    t = OSR_SOURCES[kind]["table"]
    # 2.981.0 (#5278): a row of the skipped ones (a document's note) loses its index row too
    c.execute(f"DELETE FROM obj_search s WHERE s.kind='{kind}' AND NOT EXISTS (SELECT 1 FROM {qi(t, OSR_TABLES)} r WHERE r.id=s.ref_id "
              f"AND NOT ({_skip(kind, 'r')}))")
    return c.execute(f"{OSR_INSERT} SELECT {_values(kind, 'r')} FROM {qi(t, OSR_TABLES)} r "
                     f"WHERE NOT ({_skip(kind, 'r')}) AND NOT EXISTS (SELECT 1 FROM obj_search s WHERE s.kind='{kind}' AND s.ref_id=r.id) "
                     "ON CONFLICT (kind, ref_id) DO NOTHING").rowcount


def osr_init(c):
    """Called by init_db inside its transaction (an error must surface there), after the fragments: the fold function (a new
    OSR_FOLD_VERSION replaces it), the triggers of every source, and the rows missing in the index (a new OSR_VERSION or fold
    empties it first, so every row is built again)."""
    have = c.execute("SELECT 1 FROM pg_proc WHERE proname='kalmido_fold' AND pronamespace=current_schema()::regnamespace").fetchone()
    fold_new = not have or gsetting(c, "msg_fts_v") != OSR_FOLD_VERSION
    if fold_new:
        c.execute(osr_fold_fn(c))
        gset(c, "msg_fts_v", OSR_FOLD_VERSION)
    c.execute(OSR_VALS_FN)
    ver = f"{OSR_VERSION}.{OSR_FOLD_VERSION}"
    new = fold_new or gsetting(c, "osr_v") != ver
    with system_ctx(c):  # every organisation's rows
        for kind in OSR_SOURCES:
            if new:  # the trigger's WHEN may have changed
                t = OSR_SOURCES[kind]["table"]
                for x in ("ins", "upd", "del"):
                    c.execute(f"DROP TRIGGER IF EXISTS kalmido_osr_{kind}_{x} ON {t}")
            c.execute(_fn(kind))
            _triggers(c, kind)
        if new:
            c.execute("TRUNCATE obj_search")
        n = {k: osr_fill(c, k) for k in OSR_SOURCES}
    if new:
        gset(c, "osr_v", ver)
        print("search index: (re)built", {k: v for k, v in n.items() if v}, flush=True)
    return n


# ---- the move (stage Q6a, one-way): the old search structures go
OSR_OLD_TRIGGERS = (("kalmido_fts_task_ins", "tasks"), ("kalmido_fts_task_upd", "tasks"),
                    ("kalmido_fts_cmt_ins", "obj_comments"), ("kalmido_fts_cmt_upd", "obj_comments"))
OSR_OLD_INDEXES = ("msg_trgm_obj_comments", "msg_trgm_tchat_msgs", "msg_trgm_agent_chat", "msg_trgm_comments", "msg_trgm_chat",
                   "tasks_trgm_title", "tasks_trgm_content", "tasks_trgm_url", "fts_tasks", "fts_comments")
OSR_FLOOR_HOW = ("the shared search index obj_search replaced the search side tables task_fts / cmt_fts and the column "
                 "contacts.search (#5278) - an older version would write contacts into the dropped column; go back only with a "
                 "backup from before")


def osr_move(c):
    """2.981.0 (#5278): before the fragment 5278_a drops task_fts / cmt_fts and contacts.search (core/objhooks.py MOVE, before
    the fragments' AFTER): the old triggers that write into the side tables, their functions and the trigram indexes go; the
    database's back limit is raised to the minor of this image the first time (an older image writes contacts.search)."""
    old = table_exists(c, "task_fts") or table_exists(c, "cmt_fts") or (
        table_exists(c, "contacts") and "search" in table_columns(c, "contacts"))
    for name, t in OSR_OLD_TRIGGERS:
        if table_exists(c, t):
            c.execute(f"DROP TRIGGER IF EXISTS {name} ON {t}")
    for fn in ("kalmido_fts_task", "kalmido_fts_cmt"):
        c.execute(f"DROP FUNCTION IF EXISTS {fn}()")
    for ix in OSR_OLD_INDEXES:
        c.execute(f"DROP INDEX IF EXISTS {ix}")
    if old:
        kern_retire_floor(c, how=OSR_FLOOR_HOW)
    return old


MOVE.append(osr_move)


# ---- reading: comments of other kinds (the object's rights per hit)
OSR_KINDS = {}  # kind of a commented object -> f(c, uid, ref_id) -> True when uid may read its comments (None = obj_role >= view)


def osr_kind(kind, may_read=None):
    """Register a kind whose comments the search may show: its comment hits are checked per hit with may_read, by default
    obj_role(c, uid, kind, ref_id) >= 'view' of the shared core. A kind not registered gives no comment hits."""
    OSR_KINDS[kind] = may_read


def osr_may_read(c, uid, kind, ref_id):
    if kind not in OSR_KINDS:
        return False
    f = OSR_KINDS[kind]
    if f is not None:
        return bool(f(c, uid, ref_id))
    from .objects import obj_role  # a higher layer: at call time
    return obj_role(c, uid, kind, ref_id) is not None


def osr_comment_hits(c, uid, raw, kinds=None, limit=20, cand=200):
    """Comments (obj_comments, not in the trash) of the registered kinds (or of kinds) matching raw, newest first, each checked
    with osr_may_read of its object: [{id, kind, ref_id, body}]."""
    ks = sorted(k for k in (kinds or OSR_KINDS) if k in OSR_KINDS)
    cond, args = osr_cond(raw, "s")
    if not ks or cond is None:
        return []
    rows = c.execute(f"""SELECT m.id, m.kind, m.ref_id, m.body FROM obj_search s JOIN obj_comments m ON m.id=s.ref_id
        WHERE s.kind='comment' AND s.pkind = ANY(CAST(? AS TEXT[])) AND {cond} AND {live_sql('m')}
        ORDER BY m.id DESC LIMIT {int(cand)}""", [ks] + args).fetchall()
    out, seen = [], {}
    for r in rows:
        k = (r["kind"], r["ref_id"])
        if k not in seen:
            seen[k] = osr_may_read(c, uid, *k)
        if seen[k]:
            out.append(dict(r))
            if len(out) >= limit:
                break
    return out
