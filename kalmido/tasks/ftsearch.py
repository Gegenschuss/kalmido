"""2.116.0 B (#2065): full-text search on the server -- tasks (title, notes) and their comments, ranked.

Index: since 2.981.0 (#5278, stage Q6a) the shared search index obj_search (core/objsearch.py): kind 'task' (title weight
A, notes B, link and code snippets C) and kind 'comment' (the comments of tasks, pkind 'task'), the 'simple' configuration
over kalmido_fold() (unaccent + lower case, a text with umlauts once more with ä -> ae ...), so "Ärger", "arger" and
"aerger" find the same tasks as in the message search. No language stemmer on purpose: the lists are written in several
languages and a German stemmer would cut English or Italian words wrongly; the prefix match (every query word is "word:*")
covers plurals and typing while searching. Until 2.981 the side tables task_fts / cmt_fts (2.281.0 C, #3113) held the
vectors; they went with the stage.

Visibility is exactly the one of search_tasks (tasks) and of the message search (comments): lists the person may see
(vis_sql: list roles, organisation boundary, health / budget lists, a token limited to lists, agents never locked lists),
participants only their own tasks (tvis write=True), lists with the lock (e2e) never -- the server only holds ciphertexts
there, the browser searches those lists itself. Trash (deleted tasks / comments) never; completed tasks yes (status).
Custom fields and the recognised text of files come from the existing helpers (search_field_ids, ts_task_hits) as weaker
hits. Snippets are plain text with hit ranges (marks), never HTML."""
import re

from flask import g, has_request_context, jsonify, request

from ..core.i18n import tr
from ..core.db import db
from ..core.pg import st_ids
from ..core.access import access_note, live_sql, tvis, vis_sql
from ..core.serializers import load_tasks
from ..accounts.session import me
from ..collab.msgsearch import find_marks, snippet
from ..collab.comments import comment_plain, user_names
from ..core.objcomments import OCM_MENTION_RE  # 2.972.0 (#5272)
from ..core.objsearch import OSR_KINDS, osr_comment_hits, osr_query, osr_terms  # 2.981.0 (#5278)
from ..collab.teamchat import md_brief
from ..tasks.validation import as_int
from ..core.errors import BadInput
from ..core.srchreg import srch_q, srch_register  # 2.1026.0 (#5280)
from ..api.common import cursor_dec, cursor_enc  # 2.149.0 G (#2517): pulled up from functions
from ..lists.fields import search_field_ids  # 2.369.5 (#2517): pulled up from functions

FTS_CAND = 500           # ranked candidates per source before the merge
FTS_CAND_SHORT = 200     # 2.281.0 C (#3113): ... when a word has only 1-2 letters (a prefix that hits much; the best stay)
FTS_LIMIT = 50
WHERE_ORDER = ("title", "notes", "comment", "field", "file")


def fts_terms(q):
    """The words of a query (core/objsearch.py osr_terms)."""
    return osr_terms(q)


def fts_query(terms):
    """to_tsquery text of the words (core/objsearch.py osr_query): every word a prefix in each of its variants, all required."""
    return osr_query(terms)


def _plain(text):
    return re.sub(r"\s+", " ", md_brief(text or "")).strip()


def _marks(text, terms):
    """Hit ranges of the words that are in text (find_marks wants all of them; a hit may spread over title and notes)."""
    out = []
    for t in terms:
        out += find_marks(text, [t]) or []
    out.sort()
    merged = []
    for s, e in out:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def _snip(text, terms):
    t, m = snippet(text, _marks(text, terms))
    return {"text": t, "marks": m}


def _task_cond(c, uid, a=""):
    """The visibility of search_tasks (core/state.py): visible lists, no locked list, not in the trash, participants only
    their own tasks. Two ? = uid."""
    return (f"{a}list_id IN {vis_sql()} AND {a}list_id NOT IN (SELECT id FROM lists WHERE e2e IS NOT NULL) "
            f"AND {a}deleted_at IS NULL AND {tvis(c, uid, a, write=True)}")


def fts_search(c, uid, raw, files=True):
    """Every visible hit for raw, best first: [(task id, where, snippet dict | None, comment id | None)], one per task."""
    terms = fts_terms(raw)
    tsq = fts_query(terms)
    if not tsq:
        return []
    cand = FTS_CAND_SHORT if min(len(t) for t in terms) < 3 else FTS_CAND
    # 2.281.0 C (#3113): no list_role per candidate list any more -- _task_cond is the same list scope (vis_sql) in SQL;
    # only the agents' access log that list_role kept is noted here
    seen = set()

    def note(lid):
        if lid not in seen and has_request_context() and g.get("audit_aid") == uid:
            seen.add(lid)
            access_note(lid)

    best = {}  # task id -> (tier, -rank, payload)

    def put(tid, where, rank, snip, cid=None):
        k = (WHERE_ORDER.index(where), -rank)
        if tid not in best or k < best[tid][0]:
            best[tid] = (k, where, snip, cid)

    # 2.281.0 C (#3113): rank on the stored vector; title / notes only for the FTS_CAND best (in_title: the weight A part)
    # 2.981.0 (#5278): the vector of the shared index (obj_search kind 'task'); a hit only in the link / code snippets
    # (weight C) counts as notes
    rows = c.execute(f"""SELECT t.id, t.list_id, t.title, t.content, x.r, x.in_title FROM (
        SELECT f.ref_id AS task_id, ts_rank(f.tsv, q) AS r, (ts_filter(f.tsv, '{{a}}') @@ q) AS in_title
        FROM obj_search f JOIN tasks t ON t.id=f.ref_id, to_tsquery('simple'::regconfig, ?) q
        WHERE f.kind='task' AND f.tsv @@ q AND {_task_cond(c, uid, 't.')} ORDER BY r DESC, f.ref_id DESC LIMIT {cand}) x
        JOIN tasks t ON t.id=x.task_id ORDER BY x.r DESC, t.id DESC""", (tsq, uid, uid)).fetchall()
    for r in rows:
        note(r["list_id"])
        if r["in_title"]:
            put(r["id"], "title", r["r"], _snip(r["title"] or "", terms))
        else:
            put(r["id"], "notes", r["r"], _snip(_plain(r["content"]), terms))
    # comments: the same visibility as the message search (who may read the task's comments)
    # 2.972.0 (#5272): the comments of tasks in the comments' core (obj_comments kind 'task'); 2.981.0 (#5278): obj_search kind 'comment'
    rows = c.execute(f"""SELECT x.*, m.body FROM (SELECT * FROM (SELECT DISTINCT ON (m.ref_id) m.id, m.ref_id AS task_id, t.list_id, ts_rank(f.tsv, q) AS r
        FROM obj_search f JOIN obj_comments m ON m.id=f.ref_id AND m.kind='task' JOIN tasks t ON t.id=m.ref_id, to_tsquery('simple'::regconfig, ?) q
        WHERE f.kind='comment' AND f.pkind='task' AND f.tsv @@ q AND {live_sql('m')} AND {_task_cond(c, uid, 't.')}
        ORDER BY m.ref_id, r DESC, m.id DESC) y ORDER BY r DESC, id DESC LIMIT {cand}) x
        JOIN obj_comments m ON m.id=x.id ORDER BY x.r DESC, x.id DESC""", (tsq, uid, uid)).fetchall()
    names = user_names(c, {int(x) for r in rows for x in OCM_MENTION_RE.findall(r["body"] or "")}) if rows else {}
    for r in rows:
        if r["task_id"] in best:
            continue
        note(r["list_id"])
        text = comment_plain(c, md_brief(r["body"] or ""), names)
        if not _marks(text, terms):  # only in a mention id or a Markdown marker
            continue
        put(r["task_id"], "comment", r["r"], _snip(text, terms), r["id"])
    # weaker: custom field values and the recognised text of files (the existing helpers, substring like search_tasks)
    from ..files.textscan import ts_task_hits
    extra = {tid: ("field", None) for tid in search_field_ids(c, uid, raw)}
    if files:
        for tid, name in ts_task_hits(c, uid, raw).items():
            extra.setdefault(tid, ("file", {"text": name, "marks": []}))
    extra = {k: v for k, v in extra.items() if k not in best}
    if extra:
        ids = sorted(extra)[:2000]
        ok = {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id = ANY(CAST(? AS BIGINT[])) AND {_task_cond(c, uid)}",
                                       (st_ids(ids), uid, uid))}
        for tid in ids:
            if tid in ok:
                put(tid, extra[tid][0], 0, extra[tid][1])
    return [(tid, v[1], v[2], v[3]) for tid, v in sorted(best.items(), key=lambda x: (x[1][0], -x[0]))]


def fts_page(c, uid, raw, off, lim, files=True):
    """(page of (hit, full task row), more?) -- the rows loaded again with the same visibility (a task gone meanwhile drops)."""
    hits = fts_search(c, uid, raw, files)
    part = hits[off:off + lim]
    ids = [h[0] for h in part]
    rows = {t["id"]: t for t in load_tasks(c, f"id = ANY(CAST(? AS BIGINT[])) AND {_task_cond(c, uid)}", (st_ids(ids), uid, uid))} if ids else {}
    return [(h, rows[h[0]]) for h in part if h[0] in rows], len(hits) > off + lim


def _brief(t):
    return {k: t.get(k) for k in ("id", "title", "list_id", "parent_id", "status", "completed_at", "due", "priority")}


def fts_args(a, lim_default=20):
    q = (a.get("q") or "").strip()
    if not q or len(q) > 200:
        raise BadInput(tr("Invalid value: {0}", "q"))
    return q, as_int(a.get("limit", lim_default), "limit", 1, FTS_LIMIT)


def fts_obj_comments(c, uid, raw, limit=10):
    """2.981.0 (#5278): comments of objects other than tasks (obj_comments of the kinds registered with core/objsearch.py
    osr_kind; none today, the video / picture reviews and document notes join with Q4b) that uid may read: [{id, kind, ref_id,
    snippet: {text, marks}}]. Tasks' comments stay in the hits (fts_search)."""
    kinds = [k for k in OSR_KINDS if k != "task"]
    terms = fts_terms(raw)
    out = []
    for r in osr_comment_hits(c, uid, raw, kinds, limit) if kinds else []:
        text = _plain(r["body"])
        if _marks(text, terms):
            out.append({"id": r["id"], "kind": r["kind"], "ref_id": r["ref_id"], "snippet": _snip(text, terms)})
    return out


def fts_web():
    """GET /api/search (kind tasks, core/srchreg.py): ?q, limit (1-50), cursor -- {hits: [{task, where, snippet: {text, marks},
    comment_id?}], next}. 2.1026.0 (#5280): the other kinds (office, knowledge pages, comments of other objects, contacts,
    notes, files, events, messages) come as `groups` of the first page from the registry (were the keys office / wiki /
    comments here)."""
    a = request.args
    q, lim = fts_args(a)
    off = cursor_dec("fs", a.get("cursor"))
    page, more = fts_page(db(), me(), q, off, lim)
    hits = []
    for (tid, where, snip, cid), t in page:
        h = {"task": _brief(t), "where": where, "snippet": snip}
        if cid:
            h["comment_id"] = cid
        hits.append(h)
    return {"hits": hits, "next": cursor_enc("fs", off + lim) if more else None}


def fts_comments_web():
    """GET /api/search?kind=comments: {comments: [{id, kind, ref_id, snippet}]} (comments of other objects than tasks)."""
    return {"comments": fts_obj_comments(db(), me(), srch_q(request.args), 20)}


srch_register("tasks", web=fts_web, order=0)  # the API side: api/v1.py
srch_register("comments", web=fts_comments_web, group=lambda c, uid, q, n: fts_obj_comments(c, uid, q, n), order=80)


def fts_v1(a, v1_task):
    """GET /api/v1/search?fulltext=1: the same ranked hits as tasks (v1 shape) + match {where, snippet, comment_id}."""
    from ..api.v1 import API_PAGE_MAX
    q, _ = fts_args({"q": a.get("q")})
    lim = min(as_int(a.get("limit", FTS_LIMIT), "limit", 1, API_PAGE_MAX), FTS_LIMIT)  # a bigger page asked for: 50
    off = cursor_dec("fs", a.get("cursor"))
    # audit G4 (as search_tasks): the recognised text of files only for a token that may read the files
    files = g.get("auth_via") != "token" or "attachments:read" in (g.get("scopes") or set())
    page, more = fts_page(db(), me(), q, off, lim, files)
    data = [{**v1_task(t), "match": {"where": where, "snippet": snip, **({"comment_id": cid} if cid else {})}}
            for (tid, where, snip, cid), t in page]
    return jsonify(data=data, next_cursor=cursor_enc("fs", off + lim) if more else None)
