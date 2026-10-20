"""2.126.1 B (#2125): table rows -> tasks, proposed by an agent, applied by the person.

Step 2 of the tables (sheets/step2.py, POST /api/sheets/<id>/to-tasks) stays for people only. An agent that sees a table
(shared with it, sheets/shshare.py; attached to a list it sees; or its own) proposes rows instead:
POST /api/v1/agent/proposals/sheet-tasks {sheet_id, rows, list_id, title_col, due_col?, notes_col?, summary?, for_user_id?}
(MCP propose_sheet_tasks). The target list must be shared with the agent too (never a health / budget list, never one with
the lock, inside the agent's list limit and organisation) and lie in the table's space. Rows already carried over are
skipped (none left = 409). The proposal (kind sheet_tasks, ready at once) goes to the person who works with the agent here:
for_user_id, else the person who shared the table with the agent, else the table's owner / creator -- always someone who
may write the table through its space (a share is not enough) and write the list. Nothing changes until they apply it.

The card shows the rows as the PERSON sees them now (evaluated with their visibility): title (editable, the agent may
suggest one), due date (editable), notes; rows gone, carried over or without a title are greyed out. "Apply" runs the
existing to-tasks core (sh2_to_tasks) as the person -- the same checks (table writable through its space, list writable,
same space, no lock, not archived) -- the history says "from a proposal by <agent>". Undo = the batch undo of step 2
(sh2_undo: the tasks go to the trash, the rows lose their mark); redo brings them back."""
import json
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.pg import insert_id
from ..core.access import Denied, WRITE_ROLES, list_role
from ..core.db import bump, db, iso, now_utc, usettings
from ..core.i18n import N_, tr
from ..accounts.session import me
from ..personal.timetrack import BadInput
from ..api.v1 import v1_args, v1_err, v1_json, v1_view

SHT_KIND = "sheet_tasks"
SHT_ROWS_MAX = 200            # rows per proposal (PROP_MAX_ITEMS: what one apply may select; step 2 allows 500 per press)
SHT_DAY_MAX = 50              # sheet_tasks proposals of one agent per 24 hours
SHT_TITLE = N_("Tasks from the table {0}")
SHT_NO_PERSON = N_("Nobody who works with you here may carry rows of this table over into this list (for_user_id)")
SHT_FIELDS = ("sheet_id", "rows", "list_id", "title_col", "due_col", "notes_col", "summary", "for_user_id", "user_id")


def _int(v, what, required=True):
    if v in (None, "", 0) and not required:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 2 ** 62:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def ast2_sheet(c, sid):
    """The live sheet row (a further sheet of a table too) or None."""
    from ..sheets.shbook import shb_deleted
    r = c.execute("SELECT * FROM sheets WHERE id=?", (sid,)).fetchone() if isinstance(sid, int) and 0 < sid < 2 ** 62 else None
    return None if not r or shb_deleted(c, r) else r


def ast2_list_ok(c, aid, sheet, lid):
    """The target list for agent aid: shared with it (list_role: never outside its organisation), inside its list limit, never
    a health / budget list or one with the lock, not archived, in the table's space. 404 / 409 otherwise."""
    from ..agents.core import agent_row
    from ..agents.safety import ids_parse
    a = agent_row(c, aid)
    l = c.execute("SELECT id, name, org_id, life, e2e, archived FROM lists WHERE id=?", (lid,)).fetchone()
    if not a or not l or not list_role(c, lid, aid) or (l["life"] or "") in ("health", "budget") or l["e2e"] is not None:
        raise Denied(404)
    if a["list_ids"] and lid not in ids_parse(a["list_ids"]):
        raise Denied(404)
    if (a["org_id"] and l["org_id"] and l["org_id"] != a["org_id"]) or l["org_id"] != sheet["org_id"]:
        raise Denied(409, tr("The list must be in the same space as the table"))
    if l["archived"]:
        raise Denied(409, tr("This list is archived"))
    return l


def ast2_person_ok(c, pid, sheet, lid):
    """May person pid apply it: a person (no agent, not disabled) with tables on, who may write the table through its space
    or list (a share is not enough, as step 2) and write the list."""
    from ..sheets.core import sh_may
    u = c.execute("SELECT kind, disabled FROM users WHERE id=?", (pid,)).fetchone() if pid else None
    if not u or (u["kind"] or "user") != "user" or u["disabled"]:
        return False
    if "sheets" not in (usettings(c, pid).get("features") or "").split(","):
        return False
    return sh_may(c, pid, sheet, write=True, share=False) and list_role(c, lid, pid) in WRITE_ROLES


def ast2_person(c, aid, sheet, lid, want):
    """Whose card: want (for_user_id) or the person who shared the table with the agent, else its owner, else its creator."""
    from ..sheets.shbook import shb_rights_row
    if want is not None:
        pid = _int(want, "for_user_id")
        if not ast2_person_ok(c, pid, sheet, lid):
            raise BadInput(tr(SHT_NO_PERSON))
        return pid
    rr = shb_rights_row(c, sheet) or sheet
    cands = [r[0] for r in c.execute("SELECT created_by FROM sheet_shares WHERE sheet_id=? AND user_id=? AND revoked_at IS NULL "
                                     "ORDER BY id DESC", (rr["id"], aid)).fetchall()]
    for pid in cands + [rr["owner_id"], rr["created_by"]]:
        if pid and pid != aid and ast2_person_ok(c, pid, sheet, lid):
            return pid
    raise BadInput(tr(SHT_NO_PERSON))


def _cols(book, b):
    from ..sheets.step2 import _col
    return {"title_col": _col(book, b.get("title_col"), "title_col", required=True),
            "due_col": _col(book, b.get("due_col"), "due_col"), "notes_col": _col(book, b.get("notes_col"), "notes_col")}


def sht_validate(b, inp):
    """prop_validate for kind sheet_tasks: {summary?, rows: [row id | {row_id, title?}]} -> {rows: [{row_id, title}]}. Every
    row a live row of the sheet, at most once, at most SHT_ROWS_MAX; title = the agent's suggestion (empty = the cell)."""
    from ..agents.proposals import _p_keys, _p_list, _p_str, PROP_TITLE_MAX
    from ..sheets.core import ShBook
    _p_keys(b, "", ("kind", "summary", "rows"))
    c = db()
    sheet = ast2_sheet(c, inp.get("sheet_id"))
    if not sheet:
        raise Denied(404)
    live = set(ShBook(c, sheet).row_idx)
    raw = _p_list(b.get("rows"), "rows", SHT_ROWS_MAX)
    if not raw:
        raise BadInput(tr("Missing field: {0}", "rows"))
    seen, out = set(), []
    for i, x in enumerate(raw):
        if isinstance(x, dict):
            _p_keys(x, f"rows[{i}]", ("row_id", "title"))
            rid, title = _int(x.get("row_id"), f"rows[{i}].row_id"), _p_str(x.get("title"), f"rows[{i}].title", PROP_TITLE_MAX)
        else:
            rid, title = _int(x, f"rows[{i}]"), ""
        if rid not in live or rid in seen:
            raise BadInput(tr("Invalid value: {0}", f"rows[{i}]"))
        seen.add(rid)
        out.append({"row_id": rid, "title": title})
    return {"rows": out}


# ---------------------------------------------------------------- the agent proposes
def _check(c, aid, b):
    """The sheet (seen by the agent), the target list (shared with it), the columns; -> (sheet, list, cols)."""
    from ..sheets.core import ShBook, sh_need
    sheet = sh_need(c, _int(b.get("sheet_id"), "sheet_id"))  # the agent: shared with it / its list / its own, else 404
    l = ast2_list_ok(c, aid, sheet, _int(b.get("list_id"), "list_id"))
    return sheet, l, _cols(ShBook(c, sheet), b)


@app.post("/api/v1/agent/proposals/sheet-tasks")
@v1_view
def v1_sht_propose():
    """{sheet_id, rows, list_id, title_col, due_col?, notes_col?, summary?, for_user_id?} -> a ready proposal (kind sheet_tasks)
    for the person. Nothing is created until they apply it."""
    from ..agents.core import JOB_TITLE_MAX, job_dict, need_agent
    from ..agents.proposals import PROP_MAX_BYTES, prop_ready_notify, prop_validate
    from ..agents.usage import usage_block
    from ..sheets.step2 import _linked
    v1_args(())
    aid = need_agent()
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    b = v1_json()
    if not isinstance(b, dict):
        raise BadInput(tr("The body must be a JSON object"))
    unknown = sorted(k for k in b if k not in SHT_FIELDS)
    if unknown:
        from ..api.v1 import UnknownFields
        raise UnknownFields(unknown)
    if b.get("user_id") is not None and b.get("for_user_id") is not None and b["user_id"] != b["for_user_id"]:
        raise BadInput(tr("Invalid value: {0}", "for_user_id"))
    c = db()
    sheet, l, cols = _check(c, aid, b)
    pid = ast2_person(c, aid, sheet, l["id"], b.get("for_user_id", b.get("user_id")))
    if usage_block(c, aid):
        return v1_err(409, tr("You reached your usage limit"))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND kind=? AND created_at>=?",
                 (aid, SHT_KIND, iso(now_utc() - timedelta(days=1)))).fetchone()[0] >= SHT_DAY_MAX:
        return v1_err(429, tr("At most {0} table proposals per day", SHT_DAY_MAX))
    inp = {"sheet_id": sheet["id"], "list_id": l["id"], **cols, "user_id": pid}
    p = prop_validate(SHT_KIND, {k: b[k] for k in ("summary", "rows") if k in b}, inp)
    done = _linked(c, sheet["id"], "task", {x["row_id"] for x in p["rows"]})
    if len(done) == len(p["rows"]):
        return v1_err(409, tr("These rows were already carried over into tasks"))
    ts = iso(now_utc())
    title = tr(SHT_TITLE, (sheet["title"] or "")[:80])
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,NULL,?,?,'waiting','',?,?,?,?,'ready',?,?)""",
                    (aid, pid, title[:JOB_TITLE_MAX], ts, ts, SHT_KIND, json.dumps(inp, ensure_ascii=False), l["id"],
                     json.dumps(p, ensure_ascii=False)))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    prop_ready_notify(c, j)
    bump(c)
    c.commit()
    return jsonify({**job_dict(c, j), "proposal": p, "skipped": sorted(done)}), 201


def sht_replace_check(c, aid, j):
    """POST /api/v1/agent/jobs/<id>/proposal for kind sheet_tasks: the agent must still see the table and the list."""
    from ..api.scopes import need_scope
    need_scope("sheets:read")
    inp = json.loads(j["input"] or "{}")
    _check(c, aid, inp)


# ---------------------------------------------------------------- the card (the person)
def sht_rows_now(c, uid, j):
    """The proposal's rows as uid sees them now: [{key, row_id, n, title, cell_title, due, notes, state}] with state ''
    (fine) | done (carried over before) | gone (the row was deleted) | empty (no title)."""
    from ..sheets.core import ShBook, sh_eval, sh_may
    from ..sheets.formula import sh_parse_date
    from ..sheets.step2 import _cell, _linked
    p, inp = json.loads(j["proposal"] or "null") or {}, json.loads(j["input"] or "{}")
    sheet = ast2_sheet(c, inp.get("sheet_id"))
    if not sheet or not sh_may(c, uid, sheet):
        return None, []
    book = ShBook(c, sheet)
    res = sh_eval(c, sheet, book, uid)
    done = _linked(c, sheet["id"], "task")
    pos = {r["id"]: i + 1 for i, r in enumerate(book.rows)}
    out = []
    for i, x in enumerate(p.get("rows") or []):
        rid = x["row_id"]
        d = {"key": str(i), "row_id": rid, "n": pos.get(rid), "title": "", "cell_title": "", "due": None, "notes": "", "state": ""}
        if rid not in book.row_idx:
            d["state"] = "gone"
        else:
            d["cell_title"] = _cell(book, res, rid, inp.get("title_col"))[1][:300]
            d["title"] = x.get("title") or d["cell_title"]
            if inp.get("due_col"):
                v, _ = _cell(book, res, rid, inp["due_col"])
                dd = sh_parse_date(str(v)) if v not in (None, "") else None
                d["due"] = dd.isoformat() if dd else None
            if inp.get("notes_col"):
                d["notes"] = _cell(book, res, rid, inp["notes_col"])[1][:240]
            d["state"] = "done" if rid in done else "" if d["title"] else "empty"
        out.append(d)
    return sheet, out


def sht_view_extra(c, j):
    """For the card: the table, the target list and the rows as the person sees them now (only the person sees it)."""
    if j["user_id"] != me():
        return {}
    inp = json.loads(j["input"] or "{}")
    sheet, rows = sht_rows_now(c, me(), j)
    l = c.execute("SELECT id, name FROM lists WHERE id=?", (inp.get("list_id"),)).fetchone() if list_role(c, inp.get("list_id") or 0) else None
    return {"input": {"sheet_id": inp.get("sheet_id"), "list_id": inp.get("list_id")},
            "sheet": {"id": sheet["id"], "title": sheet["title"]} if sheet else None, "list": {"id": l["id"], "name": l["name"]} if l else None,
            "sheet_rows": rows}


def _edits(ed, rows):
    """The card's edits {key: {title?, due?}} -> ({row id: title}, {row id: due or None})."""
    from ..agents.proposals import _p_keys, _p_str, _p_date, PROP_TITLE_MAX
    titles, dues = {}, {}
    for k, e in (ed or {}).items():
        if not str(k).isdigit() or int(k) >= len(rows):
            raise BadInput(tr("Invalid value: {0}", "edits"))
        _p_keys(e, f"edits.{k}", ("title", "due"))
        rid = rows[int(k)]["row_id"]
        if e.get("title"):
            titles[rid] = _p_str(e["title"], "title", PROP_TITLE_MAX)
        if "due" in e:
            dues[rid] = _p_date(e["due"], "due") if e["due"] else None
    return titles, dues


def sht_run(c, j, sel, ed, extra, rec):
    """Apply as the person: the ticked rows through the to-tasks core (the same checks as the button). rec = the undo record."""
    from ..sheets.step2 import _bump_area, _gate, sh2_to_tasks
    p, inp = json.loads(j["proposal"]), json.loads(j["input"] or "{}")
    rows = p.get("rows") or []
    sheet, uid = _gate(c, inp["sheet_id"])  # write the table through its space, tables on (agents can never apply)
    keys = sorted({int(k) for k in sel if k.isdigit() and int(k) < len(rows)})
    if not keys:
        raise BadInput(tr("Select at least one entry"))
    titles, dues = _edits({k: v for k, v in (ed or {}).items() if str(k).isdigit() and int(k) in keys}, rows)
    for k in keys:  # the agent's suggested title, unless the person typed another one
        x = rows[k]
        if x.get("title") and x["row_id"] not in titles:
            titles[x["row_id"]] = x["title"]
    b = {"list_id": inp["list_id"], "title_col": inp["title_col"], "due_col": inp.get("due_col"), "notes_col": inp.get("notes_col"),
         "rows": [rows[k]["row_id"] for k in keys]}
    out = sh2_to_tasks(c, sheet, uid, b, titles=titles, dues=dues, via={"agent_id": j["agent_id"]})
    _bump_area(c, "tasks")
    _bump_area(c, "sheets")
    rec.update(tasks=[t["task_id"] for t in out["tasks"]], batch=out["batch"], sheet_id=sheet["id"], list=out["list_id"],
               skipped_rows=out["skipped"])
    return rec


def sht_result(rec):
    return {"skipped": rec.get("skipped_rows") or 0, "sheet_id": rec.get("sheet_id")}


def sht_undo(c, j, rec, back=True):
    """Undo / redo: the batch of step 2 (the tasks to the trash and back, the rows' marks with them)."""
    from ..sheets.step2 import _bump_area, _gate, sh2_undo
    sheet, uid = _gate(c, rec["sheet_id"])
    r = sh2_undo(c, sheet, uid, rec["batch"], redo=not back)
    _bump_area(c, "tasks")
    _bump_area(c, "sheets")
    return r["done"], []


# ---------------------------------------------------------------- OpenAPI
def sht_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of POST /agent/proposals/sheet-tasks (2.126.1 B, #2125)."""
    paths["/agent/proposals/sheet-tasks"] = {"post": op(
        "2.126.1 (#2125): propose rows of a table as tasks of a list -- the person checks the card and carries them over", "Agents",
        ok({"type": "object"}, "Created", "201") | errs("400", "403", "404", "409", "413", "429"),
        body={"type": "object", "required": ["sheet_id", "rows", "list_id", "title_col"], "properties": {
            "sheet_id": {"type": "integer", "description": "The table (or one sheet of it): shared with you, attached to a list you see, or your own"},
            "rows": {"type": "array", "maxItems": SHT_ROWS_MAX, "description": "Row ids from GET /sheets/{id} (rows[].id); an item may be "
                     "{row_id, title} with a better task title (empty = the cell of title_col)",
                     "items": {"oneOf": [{"type": "integer"}, {"type": "object", "required": ["row_id"], "properties": {
                         "row_id": {"type": "integer"}, "title": {"type": "string", "maxLength": 300}}}]}},
            "list_id": {"type": "integer", "description": "The list the tasks go to: shared with you and in the table's space"},
            "title_col": {"type": "integer", "description": "Column id of the task title"},
            "due_col": {"type": "integer", "description": "Column id of the due date (optional)"},
            "notes_col": {"type": "integer", "description": "Column id of the notes (optional)"},
            "summary": {"type": "string", "description": "Markdown: why these rows"},
            "for_user_id": {"type": "integer", "description": "The person who gets the card; default: who shared the table with you, else its owner"}}},
        scope="sheets:read",
        desc=f"Agents only. You create nothing yourself: a ready proposal (kind sheet_tasks) for a person who may write the table "
             f"through its space and the list, News + push per their settings. They see the rows as THEY see them, untick rows, edit "
             f"titles and dates and apply: the tasks are theirs, the history names you, the rows get the mark \"carried over\"; one "
             f"undo step. Rows carried over before are skipped (all of them = 409). At most {SHT_ROWS_MAX} rows, {SHT_DAY_MAX} "
             f"proposals a day. The direct route POST /api/sheets/{{id}}/to-tasks stays closed to agents (403).")}
