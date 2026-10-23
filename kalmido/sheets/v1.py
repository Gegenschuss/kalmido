"""2.89.0 C (#1916): tables for agents and scripts (API v1; scopes sheets:read / sheets:write).

What a token sees is what its account sees (sheets/core.py sh_may): a person their private sheets, the sheets of their
organisations and those attached to a list they see. An AGENT sees only what is shared with it: sheets attached to a list it
sees (its list limit applies, never a list with the lock) and the sheets it created itself in its own workspace (a personal
agent's private sheets belong to its owner, who sees them in the app). Every formula is evaluated with the visibility of the
token's account -- an agent gets "denied" (no value, no name) for a project / list / client it does not see.

Every change of an agent is one batch (one call = one batch, its id in the answer): the cells carry the agent and the batch,
the people see "changed by <agent>" and can take the whole call back (the app, or the agent itself with the undo route); a
sheet the call created goes to the trash then. A person's own token writes without a batch, like the app."""
import secrets

from flask import g, jsonify

from ..core.config import app
from ..core.access import Denied, need_feat
from ..core.db import db
from ..core.i18n import tr
from ..accounts.session import me
from ..api.v1 import BadInput, UnknownFields
from ..api.common import v1_args, v1_json, v1_view
from ..files.fsref import fs_ref_rename  # 2.199.0 C (#2742)
from .core import (SH_KINDS, sh_add_col, sh_add_rows, sh_brief, sh_check_list, sh_clean_title, sh_create, sh_dict, sh_index,
                   sh_may_rebind, sh_need, sh_reload, sh_set_cells, sh_touch, sh_undo_batch, sh_vars)

SHX_CREATE_FIELDS = ("title", "space", "list_id", "columns", "rows")


def _agent():
    from ..agents.core import is_agent
    return bool(getattr(g, "user", None) is not None and is_agent(g.user))


def _write_ctx():
    """(agent id, batch) of a change: an agent's call is one new batch; a person's token: none (and the module must be on)."""
    if _agent():
        return me(), "a" + secrets.token_hex(8)
    need_feat("sheets")
    return None, None


def _v1_sheet(c, r, batch=None):
    d = sh_dict(c, r)
    d.pop("presence", None)  # people's cursors are for the app
    d["url"] = f"/api/v1/sheets/{r['id']}"
    if batch:
        d["batch"] = batch
    return d


def _check_fields(b, allowed):
    extra = sorted(k for k in b if k not in allowed)
    if extra:
        raise UnknownFields(extra)


def _int_or_none(v, what):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 2 ** 62:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


@app.get("/api/v1/sheets")
@v1_view
def v1_sheets_list():
    """The tables you may read: ?space=private|org:<id>|shared|all (default all; 2.124.0 C #2113: shared = only the tables
    shared with you one by one) or ?list_id= (attached to that list)."""
    a = v1_args(("space", "list_id"))
    c = db()
    lid = a.get("list_id")
    if lid is not None:
        try:
            lid = int(lid)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "list_id")) from None
    rows = sh_index(c, me(), a.get("space"), lid)
    return jsonify(data=sh_brief(c, rows, me()))


@app.post("/api/v1/sheets")
@v1_view
def v1_sheets_create():
    """A new table in one step: {title, space, list_id?, columns?: [{title, kind, options?, color_mode?, width?}],
    rows?: [[input, ...], ...]} (inputs in the order of the columns; formulas start with "=")."""
    b = v1_json()
    _check_fields(b, SHX_CREATE_FIELDS)
    agent_id, batch = _write_ctx()
    c = db()
    cols, rows = b.get("columns"), b.get("rows")
    if cols is not None and not isinstance(cols, list):
        raise BadInput(tr("Invalid value: {0}", "columns"))
    if rows is not None and not isinstance(rows, list):
        raise BadInput(tr("Invalid value: {0}", "rows"))
    space = b.get("space")
    if agent_id:  # an agent: its workspace by default; a team agent has no private space (nobody would see the table)
        ag = c.execute("SELECT owner_id, org_id FROM agents WHERE user_id=?", (agent_id,)).fetchone()
        if space in (None, ""):
            space = f"org:{ag['org_id']}" if ag and ag["org_id"] and not ag["owner_id"] else "private"
        elif space in ("private", 0, "0") and not (ag and ag["owner_id"]):
            raise BadInput(tr("A team agent creates tables in its workspace (space org:<id>)"))
    sid = sh_create(c, me(), space, b.get("title"), _int_or_none(b.get("list_id"), "list_id"), columns=cols, rows=rows,
                    agent_id=agent_id, batch=batch)
    c.commit()
    return jsonify(_v1_sheet(c, sh_reload(c, sid), batch)), 201


@app.get("/api/v1/sheets/<int:sid>")
@v1_view
def v1_sheet_get(sid):
    """A table: columns, rows, cells with input (formulas with names) and value, the sources of Kalmido variables, the batches."""
    v1_args(())
    c = db()
    r = sh_need(c, sid)
    d = _v1_sheet(c, r)
    c.commit()  # the viewer's last values
    return jsonify(d)


@app.patch("/api/v1/sheets/<int:sid>")
@v1_view
def v1_sheet_patch(sid):
    """{title?, list_id? (null = detach)}"""
    b = v1_json()
    _check_fields(b, ("title", "list_id"))
    agent_id, batch = _write_ctx()
    c = db()
    r = sh_need(c, sid, write=True)
    f = {}
    if "title" in b:
        f["title"] = sh_clean_title(b["title"]) or r["title"]
    if "list_id" in b:
        lid = _int_or_none(b["list_id"], "list_id")
        if lid != r["list_id"]:
            from .shshare import shs_need_own
            shs_need_own(c, r)  # 2.124.0 C (#2113): never through a share
            if not sh_may_rebind(c, me(), r):
                raise Denied(403)  # 2.89.0 (#1916): review 2, the rule of the web route; agents only on their own sheets
            f["list_id"] = sh_check_list(c, r["org_id"], lid, me())
    from .shbook import shb_patch, shb_sync
    f = shb_patch(c, r, f)  # 2.124.0 E (#2116): the list on the first sheet only; a further sheet's title = its name in the bar
    if f:
        c.execute(f"UPDATE sheets SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), sid])
        if "list_id" in f:
            shb_sync(c, sid)  # 2.124.0 E (#2116)
        if "title" in f and not r["book_id"]:
            fs_ref_rename(c, "sheet", sid, f["title"])  # 2.199.0 C (#2742): the table's name in its folder
        sh_touch(c, sid, me())
    c.commit()
    return jsonify(_v1_sheet(c, sh_reload(c, sid)))


@app.put("/api/v1/sheets/<int:sid>/cells")
@v1_view
def v1_sheet_cells(sid):
    """{cells: [{cell: "B4" | name, raw} | {row_id, col_id, raw}]} -> {cells: changed + depending cells, rev, batch}"""
    b = v1_json()
    _check_fields(b, ("cells",))
    agent_id, batch = _write_ctx()
    c = db()
    r = sh_need(c, sid, write=True)
    if not isinstance(b.get("cells"), list) or not b["cells"]:
        raise BadInput(tr("Invalid value: {0}", "cells"))
    out = sh_set_cells(c, r, b["cells"], me(), agent_id=agent_id, batch=batch)
    c.commit()
    return jsonify(cells=out, rev=sh_reload(c, sid)["rev"], batch=batch)


@app.post("/api/v1/sheets/<int:sid>/rows")
@v1_view
def v1_sheet_rows(sid):
    """{rows: [[input, ...], ...] | count, after_row_id?} -> {row_ids, rev, batch} (at the end unless after_row_id)."""
    b = v1_json()
    _check_fields(b, ("rows", "after_row_id"))
    agent_id, batch = _write_ctx()
    c = db()
    r = sh_need(c, sid, write=True)
    rows = b.get("rows", 1)
    if isinstance(rows, int) and not isinstance(rows, bool) and not 1 <= rows <= 500:
        raise BadInput(tr("Invalid value: {0}", "rows"))
    ids = sh_add_rows(c, r, rows, me(), after_row_id=_int_or_none(b.get("after_row_id"), "after_row_id"), agent_id=agent_id, batch=batch)
    if ids:
        sh_touch(c, sid, me())
    c.commit()
    return jsonify(row_ids=ids, rev=sh_reload(c, sid)["rev"], batch=batch), 201


@app.post("/api/v1/sheets/<int:sid>/columns")
@v1_view
def v1_sheet_column(sid):
    """{title, kind, options?, color_mode?, width?, after_col_id?} -> {col_id, rev, batch}"""
    b = v1_json()
    _check_fields(b, ("title", "kind", "options", "color_mode", "width", "after_col_id"))
    agent_id, batch = _write_ctx()
    c = db()
    r = sh_need(c, sid, write=True)
    if b.get("kind") not in (None, *SH_KINDS):
        raise BadInput(tr("Invalid value: {0}", "kind"))
    col = sh_add_col(c, r, b, me(), after_col_id=_int_or_none(b.get("after_col_id"), "after_col_id"), agent_id=agent_id, batch=batch)
    sh_touch(c, sid, me())
    c.commit()
    return jsonify(col_id=col, rev=sh_reload(c, sid)["rev"], batch=batch), 201


@app.get("/api/v1/sheets/<int:sid>/vars")
@v1_view
def v1_sheet_vars(sid):
    """?q= -- what a formula of this table may use: cell and column names, projects / lists / clients (with their fields and
    the current value), hier.<field>, the functions."""
    a = v1_args(("q",))
    c = db()
    r = sh_need(c, sid)
    out = sh_vars(c, r, me(), a.get("q") or "")
    c.commit()
    return jsonify(data=out)


@app.post("/api/v1/sheets/<int:sid>/batches/<batch>/undo")
@v1_view
def v1_sheet_undo(sid, batch):
    """Takes back one call's changes (an agent: only its own calls; a person's token: any agent call of the table)."""
    v1_args(())
    c = db()
    r = sh_need(c, sid, write=True)
    batch = batch[:80]
    q = "SELECT 1 FROM sheet_changes WHERE sheet_id=? AND batch=?" + (" AND agent_id=?" if _agent() else "") + " LIMIT 1"
    if not c.execute(q, (sid, batch, me()) if _agent() else (sid, batch)).fetchone():
        raise Denied(404)
    if not _agent():
        need_feat("sheets")
    n = sh_undo_batch(c, r, batch, me())
    c.commit()
    return jsonify(ok=True, undone=n, rev=sh_reload(c, sid)["rev"])


def sheets_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the tables (called from api/openapi.py)."""
    col_in = {"type": "object", "required": ["title"], "properties": {
        "title": {"type": "string", "maxLength": 80, "description": "Also the column's name in formulas (lower case, spaces -> _)"},
        "kind": {"type": "string", "enum": list(SH_KINDS), "description": "default text"},
        "options": {"type": "array", "description": "select: the choices [{label, color?: #rrggbb, id?}]",
                    "items": {"type": "object", "properties": {"label": {"type": "string"}, "color": {"type": "string"}, "id": {"type": "string"}}}},
        "color_mode": {"type": "string", "enum": ["cell", "row"], "description": "select: colour the cell (default) or the whole row"},
        "width": {"type": ["integer", "null"], "minimum": 30, "maximum": 2000}}}
    inputs = {"type": "array", "items": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}},
              "description": "Rows of inputs in the order of the columns. Numbers 1,5 or 1.5, dates DD.MM.YYYY or ISO, a select cell its "
                             "label (a new label becomes a new choice), formulas start with = (A1, B2:B9, cell / column names, "
                             "SUMME/SUM, MITTELWERT/AVERAGE, MIN, MAX, ANZAHL/COUNT, WENN/IF, RUNDEN/ROUND, HEUTE/TODAY, TAGE/DAYS, "
                             "SUMMEWENN/SUMIF, ZÄHLENWENN/COUNTIF, SVERWEIS/VLOOKUP, XVERWEIS/XLOOKUP, LINKS/LEFT, RECHTS/RIGHT, "
                             "TEIL/MID, LÄNGE/LEN, VERKETTEN/CONCAT, GLÄTTEN/TRIM, GROSS/UPPER, KLEIN/LOWER, DATUM/DATE, "
                             "JAHR/YEAR, MONAT/MONTH, TAG/DAY, EDATUM/EDATE, "
                             "projekt.<name>.<field>, liste.<name>.<field>, kunde.<name>.<field>, hier.<field>; arguments with ;)"}
    schemas["SheetBrief"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "title": {"type": "string"}, "space": {"type": "string", "description": "private | org:<id>"},
        "list_id": {"type": ["integer", "null"]}, "list_title": {"type": ["string", "null"]}, "updated_at": {"type": "string"},
        "updated_by_name": {"type": "string"}, "agent": {"type": ["object", "null"], "description": "The agent that created it"},
        # 2.124.0 C (#2113): single shares
        "shared": {"type": "integer", "description": "Number of people / agents this one table is shared with"},
        "shared_in": {"type": "boolean", "description": "You see it only because it is shared with you"},
        "share_role": {"type": "string", "description": "read | write (only with shared_in)"},
        "sheets": {"type": "integer", "description": "2.124.0: the number of sheets of the table"}}}
    schemas["SheetCell"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "row_id": {"type": "integer"}, "col_id": {"type": "integer"}, "addr": {"type": "string", "description": "B4"},
        "raw": {"type": "string", "description": "The input; a formula with the current names"}, "name": {"type": ["string", "null"]},
        "value": {"description": "number | text | ISO date | boolean | null"}, "vtype": {"type": "string"}, "display": {"type": "string"},
        "origin": {"type": "string", "enum": ["own", "formula", "kalmido", "frozen"]},
        "error": {"type": ["string", "null"], "enum": [None, "deleted", "denied", "cycle", "syntax", "div0", "ref", "type", "na"],
                  "description": "denied = a Kalmido variable you may not see (no value, no name); na = not found (VLOOKUP / XLOOKUP)"},
        "error_text": {"type": ["string", "null"]}, "option": {"type": ["string", "null"], "description": "select: the choice's id"},
        "agent": {"type": ["object", "null"], "description": "{id, name, batch} when an agent wrote it last"},
        "sources": {"type": "array", "items": {"type": "object"}}, "refs": {"type": "array", "items": {"type": "integer"}}}}
    schemas["Sheet"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "title": {"type": "string"}, "space": {"type": "string"}, "org_id": {"type": ["integer", "null"]},
        "list_id": {"type": ["integer", "null"]}, "list_title": {"type": ["string", "null"]}, "can_write": {"type": "boolean"},
        "currency": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "object", "description": "{id, pos, title, kind, options, color_mode, width, letter}"}},
        "rows": {"type": "array", "items": {"type": "object", "description": "{id, pos}"}},
        "chart": {"type": ["object", "null"], "description": "2.124.0: the table's chart set in the app, {type: bar | line, x: column id of "
                                                            "the labels | null, y: [column ids of the numbers]}; read only here"},
        "cells": {"type": "array", "items": ref("SheetCell")}, "names": {"type": "object"},
        "sources": {"type": "array", "items": {"type": "object"}, "description": "The Kalmido variables used: {type p|l|k, id, label, fields, denied, deleted}"},
        "batches": {"type": "array", "items": {"type": "object"}, "description": "Agent calls on this table: {batch, agent_id, agent_name, created_at, count, undone}"},
        "rev": {"type": "integer"}, "batch": {"type": "string", "description": "The batch of this call (agents)"},
        # 2.124.0 E (#2116): several sheets in one table
        "book_id": {"type": "integer", "description": "2.124.0: the table this sheet belongs to (the id of its first sheet)"},
        "book_title": {"type": "string"}, "tab_name": {"type": "string", "description": "The sheet's name (Name!A1 in formulas)"},
        "tabs": {"type": "array", "items": {"type": "object"}, "description": "The table's sheets {id, name, pos, first}"}}}
    T = "Tables"
    sid = pid("id", "Table id")
    write = "An agent's call is one batch (its id comes back as batch): people see the change and can take it back."
    paths["/sheets"] = {
        "get": op("Tables you may read (2.89.0)", T, ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("SheetBrief")}}})
                  | errs("400", "404"), [q("space", "private, org:<id>, shared (2.124.0: only tables shared with you) or all (default)"), q("list_id", "Tables attached to this list", {"type": "integer"})],
                  scope="sheets:read",
                  desc="An agent sees tables attached to a list shared with it and the tables it created itself."),
        "post": op("Create a table in one step: columns (with choices and colours), rows, formulas (2.89.0)", T,
                   ok(ref("Sheet"), "Created", "201") | errs("400", "403", "404", "409"), [],
                   body={"type": "object", "required": ["title"], "properties": {
                       "title": {"type": "string", "maxLength": 200}, "space": {"type": "string", "description": "private (default) or org:<id>"},
                       "list_id": {"type": ["integer", "null"], "description": "Attach to a project / list you may change (same space)"},
                       "columns": {"type": "array", "items": col_in, "maxItems": 200}, "rows": inputs}},
                   scope="sheets:write", desc=write + " Taking back the creating call moves the whole table to the trash.")}
    paths["/sheets/{id}"] = {
        "get": op("A table with its cells, values and formulas (2.89.0)", T, ok(ref("Sheet")) | errs("403", "404"), [sid], scope="sheets:read",
                  desc="Values are evaluated with your visibility: a project / list / client you do not see gives error denied."),
        "patch": op("Rename a table or attach it to a list (2.89.0)", T, ok(ref("Sheet")) | errs("400", "403", "404", "409"), [sid],
                    body={"type": "object", "properties": {"title": {"type": "string"}, "list_id": {"type": ["integer", "null"]}}},
                    scope="sheets:write")}
    paths["/sheets/{id}/cells"] = {"put": op(
        "Set cells (2.89.0)", T, ok({"type": "object", "properties": {"cells": {"type": "array", "items": ref("SheetCell")}, "rev": {"type": "integer"},
                                                                        "batch": {"type": ["string", "null"]}}}) | errs("400", "403", "404", "409"),
        [sid], body={"type": "object", "required": ["cells"], "properties": {"cells": {"type": "array", "maxItems": 5000, "items": {
            "type": "object", "description": "{cell: \"B4\" or a cell name, raw} or {row_id, col_id, raw}; raw \"\" empties the cell",
            "properties": {"cell": {"type": "string"}, "row_id": {"type": "integer"}, "col_id": {"type": "integer"},
                           "raw": {"type": ["string", "number", "boolean", "null"]}}}}}},
        scope="sheets:write", desc=write + " A wrong formula changes nothing (400 with the reason).")}
    paths["/sheets/{id}/rows"] = {"post": op(
        "Append rows (2.89.0)", T, ok({"type": "object", "properties": {"row_ids": {"type": "array", "items": {"type": "integer"}}, "rev": {"type": "integer"},
                                                                          "batch": {"type": ["string", "null"]}}}, "Created", "201") | errs("400", "403", "404", "409"),
        [sid], body={"type": "object", "properties": {"rows": {"oneOf": [inputs, {"type": "integer", "minimum": 1, "maximum": 500}]},
                                                      "after_row_id": {"type": "integer"}}},
        scope="sheets:write", desc=write)}
    paths["/sheets/{id}/columns"] = {"post": op(
        "Add a column (2.89.0)", T, ok({"type": "object", "properties": {"col_id": {"type": "integer"}, "rev": {"type": "integer"},
                                                                         "batch": {"type": ["string", "null"]}}}, "Created", "201") | errs("400", "403", "404", "409"),
        [sid], body={**col_in, "properties": {**col_in["properties"], "after_col_id": {"type": "integer"}}}, scope="sheets:write", desc=write)}
    paths["/sheets/{id}/vars"] = {"get": op(
        "What formulas of a table may use (2.89.0)", T, ok({"type": "object", "properties": {"data": {"type": "array", "items": {
            "type": "object", "description": "{token, label, kind cell|column|project|list|client|here|function, value_display, help}"}}}})
        | errs("403", "404"), [sid, q("q", "Filter")], scope="sheets:read",
        desc="Only projects / lists / clients you see and that lie in the table's space.")}
    paths["/sheets/{id}/batches/{batch}/undo"] = {"post": op(
        "Take back one call's changes (2.89.0)", T, ok({"type": "object", "properties": {"undone": {"type": "integer"}, "rev": {"type": "integer"}}})
        | errs("403", "404", "409"), [sid, {"name": "batch", "in": "path", "required": True, "description": "The batch of the call", "schema": {"type": "string"}}],
        scope="sheets:write",
        desc="Cells get their former input unless someone changed them since; added rows / columns go to the trash, a table the call "
             "created too. An agent may take back only its own calls.")}
    from .shbook import shb_spec
    shb_spec(paths, schemas, op, ok, errs, ref, pid, q, inputs, col_in, write)  # 2.124.0 E (#2116): the sheets of a table

