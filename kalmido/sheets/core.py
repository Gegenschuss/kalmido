"""2.89.0 (#1916): tables ("Excel in simple") -- sheets, columns, rows, cells, rights, evaluation, agent batches (no routes).

A sheet lives in a space like a knowledge page (wiki/pages.py): an organisation (every member reads and writes) or the private
space of one person (org_id NULL, owner_id). Attached to a project / list (list_id) the LIST decides: reading needs the list
visible, writing the right to change it; the list must be of the sheet's space (else the attachment is ignored and the space
rule applies: accounts/tenancy.py counts it). Agents see a sheet only when it is shared with them: attached to a list they see
(write: may change), or created by themselves in their own workspace. Columns and rows go to the trash (deleted_at), so Undo
can bring them back; formulas pointing at them show "ref" meanwhile.

The public functions (sh_*) are the interface of the web routes (sheets/web.py) and of the other parts (import / export,
agent API, MCP, tasks / quotations from a sheet). Every result is evaluated for one viewer (Kalmido variables: sheets/vars.py).
"""
import bisect
import json
import os
import re
import threading
import time

from flask import g, has_request_context

from ..core.access import MANAGE_ROLES, Denied, WRITE_ROLES, acx_org_ok, list_role
from ..core.db import bump, iso_ms, now_utc
from ..core.i18n import N_, lang, tr
from ..core.pg import insert_id
from ..accounts.session import me
from ..collab.comments import user_names
from ..personal.timetrack import BadInput
from .formula import (SH_FUNCS, SH_RAW_MAX, SH_TEXT_BUDGET, ShErr, ShEval, sh_col_index, sh_col_letter, sh_fmt, sh_freeze_dump, sh_freeze_load,
                      sh_fn_key, sh_json_value, sh_name_ok, sh_parse, sh_parse_date, sh_plain_value, sh_slug, sh_today, sh_tokens, sh_vtype)
from .shfuncs import SHF_HELP
from .vars import SH_VAR_WORD, sh_fields_of, sh_here_value, sh_slug_of, sh_id_of, sh_source, sh_var_value
from .shkinds import SHK_KINDS, shk_plain, shk_raw  # 2.124.0 B (#2110): checkbox, person, link, file
from .shbook import (shb_counts, shb_deleted, shb_dict, shb_display, shb_internal, shb_only_books, shb_pairs, shb_rights_row,
                     shb_check, shb_touch)  # 2.124.0 E (#2116): several sheets in one table

SH_KINDS = ("text", "number", "currency", "percent", "date", "select") + SHK_KINDS  # 2.124.0 B (#2110): + checkbox, person, link, file
SH_COLOR_MODES = ("cell", "row")
# 2.148.1 D (#2485): range cells read per evaluation of a sheet (chain of sheets included); stored cells over all sheets of
# one table. The environment values are for the tests only
SH_RANGE_BUDGET = int(os.environ.get("KALMIDO_SHEET_RANGE_BUDGET") or 15_000_000)
SH_BOOK_CELLS_MAX = int(os.environ.get("KALMIDO_SHEET_CELLS_MAX") or 1_000_000)
SH_TITLE_MAX, SH_COL_TITLE_MAX, SH_COLS_MAX, SH_ROWS_MAX, SH_CELLS_MAX, SH_OPTIONS_MAX = 200, 80, 200, 5000, 5000, 100
SH_START_COLS, SH_START_ROWS = 3, 10
SH_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")
SH_OPT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,24}")
SH_ERR_TEXT = {"deleted": N_("Source deleted"), "denied": N_("No access"), "cycle": N_("Circular reference"),
               "syntax": N_("Formula error"), "div0": N_("Division by zero"), "ref": N_("Reference not found"),
               "type": N_("Wrong type of value"), "na": N_("Not found")}  # 2.124.0 A (#2109): + na (SVERWEIS / XVERWEIS)
SH_PRESENCE_S = 15
_PRES, _PRES_LOCK = {}, threading.Lock()


def _clean_text(v, n):
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", v if isinstance(v, str) else "")).strip()[:n]


def sh_is_agent(c, uid):
    r = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r[0] == "agent")


def sh_space_key(oid):
    return f"org:{oid}" if oid else "private"


def sh_space(c, uid, v):
    """org id (None = private) of a space value "private" | "org:<id>" | <id>; 404 for an organisation uid is not in.
    An agent: only its own workspace (agents.org_id); its private space = a private agent."""
    if v in (None, "", "private", 0, "0"):
        return None
    if isinstance(v, str) and v.startswith("org:"):
        v = v[4:]
    try:
        oid = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "space")) from None
    if sh_is_agent(c, uid):
        a = c.execute("SELECT org_id FROM agents WHERE user_id=?", (uid,)).fetchone()
        if not a or a[0] != oid:
            raise Denied(404)
        return oid
    from ..accounts.orgs import user_orgs
    if oid not in user_orgs(c, uid):
        raise Denied(404)
    from ..accounts.orgroles import need_org_area
    need_org_area(c, uid, oid)  # 2.143.0 A (#2151): guests / accounting 404, read-only only reads
    return oid


def sh_list_bound(c, r):
    """The attached list's row when it exists and lies in the sheet's space, else None (the space rule applies)."""
    if not r["list_id"]:
        return None
    l = c.execute("SELECT id, name, org_id, e2e FROM lists WHERE id=?", (r["list_id"],)).fetchone()
    if not l or l["org_id"] != r["org_id"]:
        return None
    return l


def sh_may(c, uid, r, write=False, share=True):
    """May uid read (write: change) sheet r? share=False: through the space / list only."""
    if not uid:
        return False
    r = shb_rights_row(c, r)  # 2.124.0 E (#2116): a further sheet has the rights of its table's first sheet
    if r is None:
        return False
    if write and r["org_id"] and not sh_is_agent(c, uid):
        from ..accounts.orgroles import org_readonly
        if org_readonly(c, uid, r["org_id"]):
            return False  # 2.143.0 A (#2151): read-only changes nothing of the organisation (also with a share)
    if share:  # 2.124.0 C (#2113): a share of this one table adds to the rights below (sheets/shshare.py)
        from .shshare import shs_may
        if shs_may(c, uid, r, write):
            return True
    l = sh_list_bound(c, r)
    if sh_is_agent(c, uid):
        if l is not None:
            role = list_role(c, l["id"], uid)
            if not role or l["e2e"] is not None:
                return False
            from .vars import _agent_cap
            cap = _agent_cap(c, uid)
            if cap is not None and l["id"] not in cap:
                return False
            return not write or role in WRITE_ROLES
        if r["created_by"] != uid:
            return False
        return (r["owner_id"] == sh_agent_owner(c, uid)) if r["org_id"] is None else acx_org_ok(c, uid, r["org_id"])
    if l is not None:
        role = list_role(c, l["id"], uid)
        return bool(role) and (not write or role in WRITE_ROLES)
    if r["org_id"] is None:
        return r["owner_id"] == uid
    from ..accounts.orgroles import org_sees_all
    return org_sees_all(c, uid, r["org_id"]) and acx_org_ok(c, uid, r["org_id"])  # 2.143.0 A (#2151): not guests / accounting


def sh_may_rebind(c, uid, r):
    """May uid change (or remove) the list sheet r is attached to? Detaching opens the table to the whole space: a person
    needs to be its creator or the list's owner / admin; an agent may rebind only the sheets it created itself.
    2.89.0 (#1916): review 2 (the web and the v1 route share this rule)"""
    if sh_is_agent(c, uid):
        return r["created_by"] == uid
    return sh_list_bound(c, r) is None or r["created_by"] == uid or list_role(c, r["list_id"], uid) in MANAGE_ROLES


def sh_agent_owner(c, uid):
    """The person a private sheet of agent uid belongs to: a personal agent's owner (they see what it creates for them),
    else the agent itself. 2.89.0 C (#1916)"""
    a = c.execute("SELECT owner_id FROM agents WHERE user_id=?", (uid,)).fetchone()
    return a["owner_id"] if a and a["owner_id"] else uid


def sh_need(c, sid, write=False, deleted=False):
    """The sheet row for the current principal; 404 when they may not see it (or it is (not) in the trash), 403 read-only."""
    r = c.execute("SELECT * FROM sheets WHERE id=?", (sid,)).fetchone() if isinstance(sid, int) and 0 < sid < 2 ** 62 else None
    uid = me()
    if not r or shb_deleted(c, r) != deleted or not sh_may(c, uid, r):  # 2.124.0 E (#2116): + the table's first sheet in the trash
        raise Denied(404)
    if write and not sh_may(c, uid, r, write=True):
        raise Denied(403)
    return r


def sh_reload(c, sid):
    return c.execute("SELECT * FROM sheets WHERE id=?", (sid,)).fetchone()


def sh_touch(c, sid, uid):
    """The sheet changed: its counter + time (the app reloads it), and the area counter of /api/version."""
    ts = iso_ms(now_utc())
    c.execute("UPDATE sheets SET rev=rev+1, updated_at=?, updated_by=? WHERE id=?", (ts, uid, sid))
    shb_touch(c, sid, ts, uid)  # 2.124.0 E (#2116): the other sheets of the table
    bump(c)


# ---------------------------------------------------------------- the loaded sheet
class ShBook:
    """A sheet's live columns / rows in order and all its cells (also those of trashed rows / columns)."""

    def __init__(self, c, sheet):
        self.c, self.sheet = c, sheet
        sid = sheet["id"]
        self.cols = c.execute("SELECT * FROM sheet_columns WHERE sheet_id=? AND deleted_at IS NULL ORDER BY pos, id", (sid,)).fetchall()
        self.rows = c.execute("SELECT * FROM sheet_rows WHERE sheet_id=? AND deleted_at IS NULL ORDER BY pos, id", (sid,)).fetchall()
        self.all_cols = {r["id"] for r in c.execute("SELECT id FROM sheet_columns WHERE sheet_id=?", (sid,))}
        self.col_idx = {r["id"]: i for i, r in enumerate(self.cols)}
        self.row_idx = {r["id"]: i for i, r in enumerate(self.rows)}
        self.col_by = {r["id"]: r for r in self.cols}
        self.cells, self.at = {}, {}
        self._grid, self._rng, self._colc = None, {}, {}
        for x in c.execute("SELECT * FROM sheet_cells WHERE sheet_id=?", (sid,)).fetchall():
            self._add(dict(x))
        self.col_slug, self.slug_col = {}, {}
        for r in self.cols:
            s = sh_slug(r["title"])
            if not s or not re.match(r"[^\W\d]", s) or s in self.slug_col or s.lower() in SH_FUNCS:
                continue
            self.col_slug[r["id"]], self.slug_col[s] = s, r["id"]
        self.opts = {r["id"]: sh_options(r["options"]) for r in self.cols}

    def _add(self, x):
        self.cells[x["id"]] = x
        self.at[(x["row_id"], x["col_id"])] = x
        self._grid, self._rng, self._colc = None, {}, {}

    def rect(self, r1, r2, c1, c2):
        """The live cells inside rows r1..r2 / columns c1..c2 (indexes), row by row: only the cells that exist are visited,
        never every position of the rectangle (A1:GR5000 = 1 million). 2.89.0 (#1916): review 3"""
        key = (r1, r2, c1, c2)
        if key in self._rng:
            return self._rng[key]
        if self._grid is None:
            rows = {}
            for x in self.cells.values():
                if self.live(x):
                    rows.setdefault(self.row_idx[x["row_id"]], []).append((self.col_idx[x["col_id"]], x["id"], x))
            for v in rows.values():
                v.sort(key=lambda t: t[:2])
            self._grid = (sorted(rows), rows)
        keys, rows = self._grid
        out = []
        for ri in keys[bisect.bisect_left(keys, r1):bisect.bisect_right(keys, r2)]:
            line = rows[ri]
            lo = bisect.bisect_left(line, c1, key=lambda t: t[0])
            hi = bisect.bisect_right(line, c2, key=lambda t: t[0])
            out.extend(t[2] for t in line[lo:hi])
        self._rng[key] = out
        return out

    def col_cells(self, col_id):
        """The cells of a live column in row order (cached; review 3)."""
        out = self._colc.get(col_id)
        if out is None:
            out = [x for x in (self.at.get((r["id"], col_id)) for r in self.rows) if x] if col_id in self.col_idx else []
            self._colc[col_id] = out
        return out

    def live(self, x):
        return x is not None and x["row_id"] in self.row_idx and x["col_id"] in self.col_idx

    def names(self):
        return {x["name"].lower(): x for x in self.cells.values() if x.get("name") and self.live(x)}

    def addr(self, x):
        return sh_col_letter(self.col_idx[x["col_id"]]) + str(self.row_idx[x["row_id"]] + 1)

    def pos_of(self, letters, num):
        ci, ri = sh_col_index(letters), num - 1
        if not (0 <= ci < len(self.cols) and 0 <= ri < len(self.rows)):
            return None
        return self.rows[ri]["id"], self.cols[ci]["id"]

    def ensure(self, row_id, col_id, uid):
        """The cell at (row, column), created empty when missing (a formula may point at an empty cell)."""
        x = self.at.get((row_id, col_id))
        if x:
            return x
        ts = iso_ms(now_utc())
        cid = insert_id(self.c, "INSERT INTO sheet_cells(sheet_id,row_id,col_id,raw,updated_by,updated_at) VALUES(?,?,?,'',?,?) "
                                "ON CONFLICT (row_id, col_id) DO NOTHING", (self.sheet["id"], row_id, col_id, uid, ts))
        if not cid:
            cid = self.c.execute("SELECT id FROM sheet_cells WHERE row_id=? AND col_id=?", (row_id, col_id)).fetchone()[0]
        x = dict(self.c.execute("SELECT * FROM sheet_cells WHERE id=?", (cid,)).fetchone())
        self._add(x)
        return x


def sh_options(raw):
    try:
        v = json.loads(raw or "[]")
    except ValueError:
        return []
    return [o for o in v if isinstance(o, dict)] if isinstance(v, list) else []


def sh_clean_options(v):
    """[{id, label, color}] of a select column (ids kept, new ones o1, o2 ...); BadInput when wrong."""
    if not isinstance(v, list) or len(v) > SH_OPTIONS_MAX:
        raise BadInput(tr("Invalid value: {0}", "options"))
    out, ids = [], set()
    for o in v:
        if not isinstance(o, dict):
            raise BadInput(tr("Invalid value: {0}", "options"))
        label = _clean_text(o.get("label"), 80)
        if not label:
            raise BadInput(tr("Invalid value: {0}", "options"))
        color = o.get("color") or ""
        if color and (not isinstance(color, str) or not SH_COLOR_RE.fullmatch(color)):
            raise BadInput(tr("Invalid value: {0}", "color"))
        oid = o.get("id")
        if not isinstance(oid, str) or not SH_OPT_ID_RE.fullmatch(oid) or oid in ids:
            oid = None
        out.append({"id": oid, "label": label, "color": color.lower()})
        if oid:
            ids.add(oid)
    n = 1
    for o in out:
        if not o["id"]:
            while f"o{n}" in ids:
                n += 1
            o["id"] = f"o{n}"
            ids.add(o["id"])
    return out


# ---------------------------------------------------------------- names <-> ids
def _bad_formula(detail):
    if detail == "deep":  # 2.89.0 (#1916): review 4
        return BadInput(tr("The formula is nested too deeply"))
    return BadInput(tr("Formula error: {0}", detail) if detail else tr("Formula error"))


def sh_to_internal(c, sheet_row, text, uid, book=None, keep=""):
    """The stored form of an input: a formula's addresses / names become ids ({c:..}, {col:..}, {p:..}.field ...), everything
    else stays as typed; plain text is returned unchanged. A Kalmido variable must be one uid may use in this sheet's space
    (a bare id already in the cell's previous input `keep` may stay: it was chosen by someone who could). BadInput."""
    if not isinstance(text, str) or not text.startswith("="):
        return text
    if len(text) > SH_RAW_MAX:
        raise BadInput(tr("The text is too long (at most {0} characters)", SH_RAW_MAX))
    book = book or ShBook(c, sheet_row)
    body = text[1:]
    try:
        toks = sh_tokens(body)
    except ShErr as e:
        raise _bad_formula(e.detail) from None
    names = book.names()
    kept = set()
    if isinstance(keep, str) and keep.startswith("="):
        try:
            kept = {t[1] for t in sh_tokens(keep[1:]) if t[0] == "idref"}
        except ShErr:
            kept = set()
    out, last = [], 0
    for kind, val, a, b in toks:
        rep = None
        if kind == "a1":
            pos = book.pos_of(*val)
            if not pos:
                raise BadInput(tr("There is no cell {0}", f"{val[0]}{val[1]}"))
            rep = "{c:%d}" % book.ensure(pos[0], pos[1], uid)["id"]
        elif kind == "ident" and val.lower() not in ("wahr", "true", "falsch", "false"):
            rep = _ident_internal(c, sheet_row, book, names, val, uid)
        elif kind == "xref":  # 2.124.0 E (#2116): Blatt2!A1
            rep = shb_internal(c, sheet_row, book, val, uid)
        elif kind == "idref":
            typ, xid, field = val
            if typ == "x":  # 2.124.0 E (#2116)
                tab = shb_check(c, sheet_row, xid)
                if tab is None:
                    raise BadInput(tr("Unknown name: {0}", body[a:b]))
                if tab["id"] == sheet_row["id"]:  # review: a cell of this very sheet is a plain cell reference (its dependency)
                    rep = "{c:%d}" % xid
            elif typ == "c":
                if xid not in book.cells:
                    raise BadInput(tr("Unknown name: {0}", body[a:b]))
            elif typ == "col":
                if xid not in book.all_cols:
                    raise BadInput(tr("Unknown name: {0}", body[a:b]))
            else:
                if field not in sh_fields_of(typ):
                    raise BadInput(tr("Unknown field: {0}", field or "?"))
                if val not in kept and sh_source(c, sheet_row, uid, typ, xid) in (None, "deleted"):
                    raise BadInput(tr("Unknown name: {0}", body[a:b]))
        elif kind == "fn" and sh_fn_key(val) is None:  # 2.124.0 A (#2109): + shfuncs
            raise BadInput(tr("Unknown function: {0}", val))
        if rep is not None:
            out.append(body[last:a])
            out.append(rep)
            last = b
    out.append(body[last:])
    raw = "=" + "".join(out)
    try:
        sh_parse(raw[1:], lambda t: _node(t, book, sheet_row))
    except ShErr as e:
        raise _bad_formula(e.detail) from None
    except RecursionError:  # review 4: never a 500, whatever the nesting
        raise _bad_formula("deep") from None
    return raw


def _ident_internal(c, sheet_row, book, names, val, uid):
    low = val.lower()
    if low in names:
        return "{c:%d}" % names[low]["id"]
    if low in book.slug_col:
        return "{col:%d}" % book.slug_col[low]
    parts = low.split(".")
    if parts[0] in ("projekt", "liste", "kunde", "aufgabe"):  # 2.89.0 (#1916, D): + aufgabe.<id>.<field>
        typ = {"projekt": "p", "liste": "l", "kunde": "k", "aufgabe": "t"}[parts[0]]
        if len(parts) != 3:
            raise BadInput(tr("Unknown name: {0}", val))
        if parts[2] not in sh_fields_of(typ):
            raise BadInput(tr("Unknown field: {0}", parts[2]))
        sid = sh_id_of(c, sheet_row, uid, typ, parts[1])
        if not sid:
            raise BadInput(tr("Unknown name: {0}", val))
        return "{%s:%d}.%s" % (typ, sid, parts[2])
    if parts[0] == "hier":
        if len(parts) != 2 or parts[1] not in sh_fields_of("l"):
            raise BadInput(tr("Unknown field: {0}", parts[-1]))
        if not sheet_row["list_id"]:
            raise BadInput(tr("This table is not attached to a project or list"))
        return low
    raise BadInput(tr("Unknown name: {0}", val))


def _node(tok, book, sheet_row):
    """The reference node of a token of a STORED formula (ids); names that are not ids any more are errors."""
    kind, val = tok[0], tok[1]
    if kind == "idref":
        typ, xid, field = val
        if typ == "c":
            return ("cell", xid)
        if typ == "col":
            return ("col", xid)
        if typ == "x":  # 2.124.0 E (#2116): a cell of another sheet of the table
            return ("xcell", xid)
        return ("var", typ, xid, field)
    if kind == "ident":
        parts = val.lower().split(".")
        if parts[0] == "hier" and len(parts) == 2:
            return ("here", parts[1])
        raise ShErr("ref")
    if kind == "a1":
        pos = book.pos_of(*val)
        if not pos or pos not in book.at:
            raise ShErr("ref")
        return ("cell", book.at[pos]["id"])
    raise ShErr("syntax", str(val))


def sh_to_display(c, sheet_row, raw, book=None, uid=None):
    """A stored formula with the current names / addresses for viewer uid (default: the current principal). Ids the viewer
    may not use (or that are gone) stay bare ids: never a name they may not see."""
    if not isinstance(raw, str) or not raw.startswith("="):
        return raw
    book = book or ShBook(c, sheet_row)
    uid = uid or me()
    body = raw[1:]
    try:
        toks = sh_tokens(body)
    except ShErr:
        return raw
    names_of = {x["id"]: x["name"] for x in book.cells.values() if x.get("name") and book.live(x)}
    out, last = [], 0
    for kind, val, a, b in toks:
        if kind != "idref":
            continue
        typ, xid, field = val
        rep = None
        if typ == "c":
            x = book.cells.get(xid)
            if book.live(x):
                rep = names_of.get(xid) or book.addr(x)
        elif typ == "col":
            if xid in book.col_slug:
                rep = book.col_slug[xid]
        elif typ == "x":  # 2.124.0 E (#2116)
            rep = shb_display(c, sheet_row, xid, book.__dict__.setdefault("shb_cache", {}))
        else:
            s = sh_slug_of(c, sheet_row, uid, typ, xid)
            if s:
                rep = f"{SH_VAR_WORD[typ]}.{s}.{field}"
        if rep is not None:
            out.append(body[last:a])
            out.append(rep)
            last = b
    out.append(body[last:])
    return "=" + shb_pairs("".join(out))  # 2.124.0 E (#2116): Blatt2!A1:B5


# ---------------------------------------------------------------- evaluation
def _err_res(kind, detail=""):
    t = tr(SH_ERR_TEXT[kind])
    if kind == "type" and detail == "long":  # 2.89.0 (#1916): review 1
        t = tr("The text is too long (at most {0} characters)", SH_RAW_MAX)
    elif kind == "type" and detail == "big":  # 2.124.0 A (#2109): the cell budget of SUMMEWENN / SVERWEIS ...
        t = tr("Too much to compute: use smaller ranges")
    elif kind == "syntax" and detail == "deep":
        t = tr("The formula is nested too deeply")
    elif kind == "syntax" and detail and detail not in ("empty", "end"):
        t = tr("Formula error: {0}", detail)
    return {"value": None, "vtype": "empty", "display": tr(SH_ERR_TEXT[kind]), "error": kind, "error_text": t}


def _tree_refs(node, book, self_id, out_cells, out_vars):
    """The cell ids and Kalmido variables a tree reads (static: both branches of IF)."""
    if not isinstance(node, tuple):
        return
    k = node[0]
    if k == "cell":
        out_cells.add(node[1])
    elif k == "range":
        for x in _range_cells(book, node[1], node[2]):
            out_cells.add(x["id"])
    elif k == "col":
        for x in book.col_cells(node[1]):
            if x["id"] != self_id:
                out_cells.add(x["id"])
    elif k == "var":
        out_vars.append(("v", node[1], node[2], node[3]))
    elif k == "here":
        out_vars.append(("h", None, None, node[1]))
    elif k == "fn":
        for a in node[2]:
            _tree_refs(a, book, self_id, out_cells, out_vars)
    elif k == "cmp":
        _tree_refs(node[2], book, self_id, out_cells, out_vars)
        _tree_refs(node[3], book, self_id, out_cells, out_vars)
    else:
        for a in node[1:]:
            _tree_refs(a, book, self_id, out_cells, out_vars)


def _range_cells(book, a, b):
    xa, xb = book.cells.get(a), book.cells.get(b)
    if not book.live(xa) or not book.live(xb):
        return []
    r1, r2 = sorted((book.row_idx[xa["row_id"]], book.row_idx[xb["row_id"]]))
    c1, c2 = sorted((book.col_idx[xa["col_id"]], book.col_idx[xb["col_id"]]))
    return book.rect(r1, r2, c1, c2)


class _Env:
    def __init__(self, ev, cell):
        self.ev, self.cell_row, self.lg = ev, cell, ev.lg

    def cell(self, cid):
        return self.ev.value_of(cid)

    def rng(self, a, b):
        book = self.ev.book
        if not book.live(book.cells.get(a)) or not book.live(book.cells.get(b)):
            raise ShErr("ref")
        cells = _range_cells(book, a, b)
        self.work(len(cells), (a, b))
        return [self.ev.value_of(x["id"]) for x in cells]

    def col(self, col_id):
        book = self.ev.book
        if col_id not in book.col_idx:
            raise ShErr("ref")
        cells = book.col_cells(col_id)
        self.work(len(cells), col_id)
        return [self.ev.value_of(x["id"]) for x in cells if x["id"] != self.cell_row["id"]]

    def work(self, n, key=None):
        """2.148.1 D (#2485): cells the ranges / columns of one evaluation may read (running totals over 5,000 rows fit).
        2.148.1 G (#2485): each column / range counts once per evaluation (a column total in every row is no square)."""
        seen = self.ev.__dict__.setdefault("rng_seen", set())
        if key is not None:
            if key in seen:
                return
            seen.add(key)
        self.ev.rng_work = getattr(self.ev, "rng_work", SH_RANGE_BUDGET) - n
        if self.ev.rng_work < 0:
            raise ShErr("type", "big")

    def spend(self, n):
        """Text "&" built: over the budget of this evaluation = an error instead of filling the memory (review 1)."""
        self.ev.text_left -= n
        if self.ev.text_left < 0:
            raise ShErr("type", "long")

    def var(self, typ, xid, field):
        return sh_var_value(self.ev.c, self.ev.book.sheet, self.ev.uid, typ, xid, field)

    def here(self, field):
        return sh_here_value(self.ev.c, self.ev.book.sheet, self.ev.uid, field)

    def today(self):
        return sh_today()

    def xcell(self, cid):  # 2.124.0 E (#2116): a cell / range of another sheet of the table (sheets/shbook.py)
        from .shbook import shb_value
        return shb_value(self.ev, cid)

    def xrange(self, a, b):
        from .shbook import shb_range
        out = shb_range(self.ev, a, b)
        self.work(len(out))  # 2.148.1 D (#2485)
        return out


class ShEvaluator:
    """Evaluates every live cell of a book for viewer uid in dependency order (no recursion: a long chain of cells is fine);
    the cells of a cycle (and what depends on them) get "cycle"."""

    def __init__(self, c, book, uid):
        self.c, self.book, self.uid, self.lg = c, book, uid, lang()
        self.currency = sh_currency(c, book.sheet)
        self.res, self.trees, self.deps, self.vars = {}, {}, {}, {}
        self.text_left = SH_TEXT_BUDGET

    def value_of(self, cid):
        x = self.book.cells.get(cid)
        if not self.book.live(x):
            raise ShErr("ref")
        r = self.res.get(cid)
        if r is None:
            if cid in self.trees:  # a formula not evaluated yet = part of a cycle
                raise ShErr("cycle")
            r = self.plain(x)
            self.res[cid] = r
        if r.get("error"):
            raise ShErr(r["error"])
        return r["_v"]

    def kind_of(self, x):
        col = self.book.col_by.get(x["col_id"])
        return (col["kind"] if col else "text"), self.book.opts.get(x["col_id"], [])

    def plain(self, x):
        kind, opts = self.kind_of(x)
        raw = x["raw"] or ""
        if x["frozen"]:
            v, _ = sh_freeze_load(x["frozen_value"])
            return self.out(v, kind, "frozen")
        if kind in SHK_KINDS:  # 2.124.0 B (#2110)
            return shk_plain(self, x, kind)
        v = sh_plain_value(raw, kind, opts)
        if kind == "text" or (kind != "select" and isinstance(v, str)):
            d = raw if kind != "select" else (v or "")
            r = self.out(v, kind, "own")
            r["display"] = d
            return r
        return self.out(v, kind, "own")

    def out(self, v, kind, origin):
        yes, no = tr("Yes"), tr("No")
        return {"_v": v, "value": sh_json_value(v), "vtype": sh_vtype(v), "display": sh_fmt(v, kind, self.lg, self.currency, yes, no),
                "origin": origin, "error": None, "error_text": None}

    def run(self):
        book, formulas = self.book, []
        for x in book.cells.values():
            if not book.live(x):
                continue
            raw = x["raw"] or ""
            if raw.startswith("=") and not x["frozen"]:
                formulas.append(x)
        for x in formulas:
            cells, vs = set(), []
            try:
                tree = sh_parse(x["raw"][1:], lambda t, _b=book: _node(t, _b, _b.sheet))
                _tree_refs(tree, book, x["id"], cells, vs)
            except ShErr as e:
                self.res[x["id"]] = dict(_err_res(e.kind, e.detail), origin="formula", _v=None)
                continue
            except RecursionError:  # review 4: a stored formula from before the depth limit
                self.res[x["id"]] = dict(_err_res("syntax", "deep"), origin="formula", _v=None)
                continue
            self.trees[x["id"]], self.deps[x["id"]], self.vars[x["id"]] = tree, cells, vs
        # Kahn: formulas whose formula inputs are all done go first; what is left belongs to (or hangs on) a cycle
        indeg, users = {}, {}
        for cid, ds in self.deps.items():
            n = 0
            for d in ds:
                if d in self.trees:
                    n += 1
                    users.setdefault(d, []).append(cid)
            indeg[cid] = n
        queue = [cid for cid, n in indeg.items() if n == 0]
        while queue:
            cid = queue.pop()
            self.eval_one(cid)
            for u in users.get(cid, ()):
                indeg[u] -= 1
                if indeg[u] == 0:
                    queue.append(u)
        for cid in self.trees:
            if cid not in self.res:
                self.res[cid] = dict(_err_res("cycle"), origin="formula", _v=None)
        for x in book.cells.values():
            if book.live(x) and x["id"] not in self.res:
                self.res[x["id"]] = self.plain(x)
        return self.res

    def eval_one(self, cid):
        x = self.book.cells[cid]
        kind, _ = self.kind_of(x)
        origin = "kalmido" if self.vars[cid] else "formula"
        try:
            v = ShEval(_Env(self, x)).run(self.trees[cid])
            r = self.out(v, kind, origin)
        except ShErr as e:
            r = dict(_err_res(e.kind, e.detail), origin=origin, _v=None)
        except (OverflowError, ValueError, ZeroDivisionError):
            r = dict(_err_res("type"), origin=origin, _v=None)
        except RecursionError:  # review 4
            r = dict(_err_res("syntax", "deep"), origin=origin, _v=None)
        self.res[cid] = r


def sh_currency(c, sheet):
    """The currency of amounts: the office's of the sheet's organisation, of a private sheet the owner's personal office."""
    if has_request_context():
        cache = g.setdefault("sh_currency", {})
        if sheet["id"] in cache:
            return cache[sheet["id"]]
    cur = "EUR"
    try:
        oid = sheet["org_id"]
        if oid is None and sheet["owner_id"]:
            r = c.execute("SELECT id FROM orgs WHERE personal_of=?", (sheet["owner_id"],)).fetchone()
            oid = r[0] if r else None
        if oid is not None:
            r = c.execute("SELECT data FROM office_settings WHERE org_id=?", (oid,)).fetchone()
            d = json.loads(r[0]) if r and r[0] else {}
            if isinstance(d, dict) and isinstance(d.get("currency"), str) and re.fullmatch(r"[A-Z]{3}", d["currency"]):
                cur = d["currency"]
    except (ValueError, TypeError):
        cur = "EUR"
    if has_request_context():
        g.sh_currency[sheet["id"]] = cur
    return cur


def sh_eval(c, sheet_row, book=None, uid=None):
    """{cell_id: result} of every live cell for viewer uid (default: the current principal): value, vtype, display, origin,
    error, error_text, last_value, refs, sources. Writes only sheet_lastvals (the viewer's last value of a cell with a
    Kalmido variable; shown when the source is deleted, never anyone else's)."""
    book = book or ShBook(c, sheet_row)
    uid = uid or me()
    ev = ShEvaluator(c, book, uid)
    res = ev.run()
    last = {r[0]: r[1] for r in c.execute("SELECT l.cell_id, l.value FROM sheet_lastvals l JOIN sheet_cells x ON x.id=l.cell_id "
                                          "WHERE x.sheet_id=? AND l.user_id=?", (sheet_row["id"], uid))}
    ts = None
    for cid, r in res.items():
        r.pop("_v", None)
        r["refs"] = sorted(ev.deps.get(cid, ()))
        r["sources"] = _sources_of(c, sheet_row, uid, ev.vars.get(cid, ()))
        r["last_value"] = None
        if r["origin"] == "kalmido":
            if r["error"] is None:
                if last.get(cid) != r["display"]:
                    ts = ts or iso_ms(now_utc())
                    c.execute("INSERT INTO sheet_lastvals(cell_id,user_id,value,at) VALUES(?,?,?,?) ON CONFLICT (cell_id, user_id) "
                              "DO UPDATE SET value=excluded.value, at=excluded.at", (cid, uid, r["display"], ts))
            elif r["error"] == "deleted":
                r["last_value"] = last.get(cid)
    _hide_unknown_deleted(res, ev.deps, last)
    return res


def _hide_unknown_deleted(res, deps, last):
    """2.89.0 (#1916): review 7 - "Source deleted" only for a viewer who once saw the value (has a last value of a cell that
    read it, or reads such a cell); anyone else gets "No access", exactly as for a source that exists but is hidden, so the
    difference does not tell whether an id exists."""
    known = {cid for cid, r in res.items() if r["error"] == "deleted" and r["origin"] == "kalmido" and cid in last}
    todo = [cid for cid, r in res.items() if r["error"] == "deleted" and cid not in known]
    grew = True
    while grew and todo:
        grew = False
        for cid in list(todo):
            if deps.get(cid, set()) & known:
                known.add(cid)
                todo.remove(cid)
                grew = True
    seen_src = {(x["type"], x["id"]) for cid in known for x in res[cid]["sources"] if x["deleted"]}
    for cid in todo:
        r = res[cid]
        r.update({k: v for k, v in _err_res("denied").items() if k != "value"}, last_value=None)
    for r in res.values():
        for x in r["sources"]:
            if x["deleted"] and (x["type"], x["id"]) not in seen_src:
                x["deleted"], x["denied"] = False, True


def _sources_of(c, sheet, uid, vs):
    out, seen = [], set()
    for k, typ, xid, field in vs:
        if k == "h":
            typ, xid = "l", sheet["list_id"]
            if not xid:
                continue
        key = (typ, xid, field)
        if key in seen:
            continue
        seen.add(key)
        r = sh_source(c, sheet, uid, typ, xid)
        ok = r not in (None, "deleted")
        out.append({"type": typ, "id": xid, "label": r["name"] if ok else None, "field": field,
                    "denied": r is None, "deleted": r == "deleted", "here": k == "h"})
    return out


# ---------------------------------------------------------------- the answers
def sh_col_dict(r, i=None):
    return {"id": r["id"], "pos": r["pos"], "title": r["title"], "kind": r["kind"], "options": sh_options(r["options"]),
            "color_mode": r["color_mode"], "width": r["width"], "letter": sh_col_letter(i) if i is not None else None}


def sh_cell_dicts(c, sheet_row, book, res, ids=None, uid=None):
    """The cell dicts (raw in the display form) of the live cells with content (or only ids)."""
    uid = uid or me()
    cells = [x for x in book.cells.values() if book.live(x) and (ids is None or x["id"] in ids)
             and (ids is not None or x["raw"] or x.get("name") or x["frozen"])]
    names = user_names(c, {x["updated_by"] for x in cells} | {x["agent_id"] for x in cells if x.get("agent_id")})
    out = []
    for x in sorted(cells, key=lambda x: (book.row_idx[x["row_id"]], book.col_idx[x["col_id"]])):
        r = res.get(x["id"]) or {}
        kind = book.col_by[x["col_id"]]["kind"]
        d = {"id": x["id"], "row_id": x["row_id"], "col_id": x["col_id"], "addr": book.addr(x),
             "raw": sh_to_display(c, sheet_row, x["raw"], book, uid), "name": x.get("name"), "frozen": bool(x["frozen"]),
             "agent": ({"id": x["agent_id"], "name": names.get(x["agent_id"], ""), "batch": x.get("agent_batch")}
                       if x.get("agent_id") else None),
             "updated_by": x["updated_by"], "updated_by_name": names.get(x["updated_by"], ""), "updated_at": x["updated_at"],
             "option": (x["raw"] if kind == "select" and not (x["raw"] or "").startswith("=") and x["raw"] else None)}
        for k in ("value", "vtype", "display", "origin", "error", "error_text", "last_value", "refs", "sources"):
            d[k] = r.get(k)
        out.append(d)
    return out


def sh_presence(c, sid, uid):
    now = time.time()
    with _PRES_LOCK:
        for k in [k for k, v in _PRES.items() if v[1] <= now]:
            _PRES.pop(k, None)
        live = [(u, v[0]) for (s, u), v in _PRES.items() if s == sid and u != uid]
    names = user_names(c, {u for u, _ in live})
    return [{"user_id": u, "name": names.get(u, "?"), "cell_id": cid} for u, cid in live][:50]


def sh_presence_set(c, r, uid, cell_id):
    if cell_id is not None and not c.execute("SELECT 1 FROM sheet_cells WHERE id=? AND sheet_id=?", (cell_id, r["id"])).fetchone():
        raise BadInput(tr("Invalid value: {0}", "cell_id"))
    with _PRES_LOCK:
        if len(_PRES) < 5000 or (r["id"], uid) in _PRES:
            _PRES[(r["id"], uid)] = (cell_id, time.time() + SH_PRESENCE_S)
    return {"ok": True, "seconds": SH_PRESENCE_S}


def sh_batches(c, sid):
    rows = c.execute("SELECT batch, MIN(agent_id) AS agent_id, MIN(created_at) AS created_at, COUNT(*) AS n, COUNT(undone_at) AS u "
                     "FROM sheet_changes WHERE sheet_id=? GROUP BY batch ORDER BY MIN(id) DESC LIMIT 50", (sid,)).fetchall()
    names = user_names(c, {r["agent_id"] for r in rows})
    return [{"batch": r["batch"], "agent_id": r["agent_id"], "agent_name": names.get(r["agent_id"], ""), "created_at": r["created_at"],
             "count": r["n"], "undone": r["u"] >= r["n"]} for r in rows]


def sh_list_title(c, r, uid):
    """The attached list's name for uid (None when they may not see it or it is locked)."""
    if not r["list_id"]:
        return None
    l = c.execute("SELECT name, e2e FROM lists WHERE id=?", (r["list_id"],)).fetchone()
    if not l or not list_role(c, r["list_id"], uid):
        return None
    return l["name"] if l["e2e"] is None else ""


def sh_dict(c, sheet_row, uid=None, book=None):
    """The whole sheet as GET /api/sheets/<id> answers it, evaluated for the current principal."""
    uid = uid or me()
    book = book or ShBook(c, sheet_row)
    res = sh_eval(c, sheet_row, book, uid)
    cells = sh_cell_dicts(c, sheet_row, book, res, uid=uid)
    srcs = {}
    for d in cells:
        for s in d["sources"] or ():
            k = (s["type"], s["id"])
            e = srcs.setdefault(k, {"type": s["type"], "id": s["id"], "label": s["label"], "fields": [], "denied": s["denied"],
                                    "deleted": s["deleted"]})
            if s["field"] not in e["fields"]:
                e["fields"].append(s["field"])
    return {"id": sheet_row["id"], "title": sheet_row["title"], "space": sh_space_key(sheet_row["org_id"]), "org_id": sheet_row["org_id"],
            "list_id": sheet_row["list_id"], "list_title": sh_list_title(c, sheet_row, uid),
            "can_write": sh_may(c, uid, sheet_row, write=True), "currency": sh_currency(c, sheet_row),
            "columns": [sh_col_dict(r, i) for i, r in enumerate(book.cols)], "rows": [{"id": r["id"], "pos": r["pos"]} for r in book.rows],
            "cells": cells, "names": {x["name"]: x["id"] for x in book.cells.values() if x.get("name") and book.live(x)},
            "presence": sh_presence(c, sheet_row["id"], uid), "sources": list(srcs.values()), "batches": sh_batches(c, sheet_row["id"]),
            "rev": sheet_row["rev"], "deleted_at": sheet_row["deleted_at"], "updated_at": sheet_row["updated_at"],
            "freeze_rows": sheet_row["freeze_rows"], "freeze_cols": sheet_row["freeze_cols"],  # 2.124.0 B (#2111)
            "agent": ({"id": sheet_row["agent_id"], "batch": sheet_row["agent_batch"]} if sheet_row["agent_id"] else None),
            "chart": _chart_of(sheet_row), **shb_dict(c, sheet_row)}  # 2.124.0 A (#2115); E (#2116): book_id, book_title, tab_name, tabs


def _chart_of(sheet_row):
    from .shchart import shc_load  # 2.124.0 A (#2115): a later module (ORDER)
    return shc_load(sheet_row)


def sh_brief(c, rows, uid):
    """The entries of GET /api/sheets."""
    names = user_names(c, {r["updated_by"] for r in rows} | {r["agent_id"] for r in rows if r["agent_id"]})
    from .shshare import shs_marks  # 2.124.0 C (#2113): + shared / shared_in
    return shb_counts(c, rows, shs_marks(c, uid, rows, [{"id": r["id"], "title": r["title"], "space": sh_space_key(r["org_id"]), "list_id": r["list_id"],
             "list_title": sh_list_title(c, r, uid), "updated_at": r["updated_at"], "updated_by_name": names.get(r["updated_by"], ""),
             "agent": ({"id": r["agent_id"], "name": names.get(r["agent_id"], "")} if r["agent_id"] else None)} for r in rows]))  # 2.124.0 E (#2116): + sheets


# ---------------------------------------------------------------- changes
def sh_change(c, sid, batch, agent_id, kind, cell_id=None, row_id=None, col_id=None, old=None, new=None):
    if not batch:
        return
    c.execute("INSERT INTO sheet_changes(sheet_id,batch,agent_id,cell_id,row_id,col_id,kind,old_raw,new_raw,created_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?)", (sid, batch, agent_id, cell_id, row_id, col_id, kind, old, new, iso_ms(now_utc())))


def sh_clean_title(v, what="title", n=SH_TITLE_MAX):
    if v is not None and not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", what))
    return _clean_text(v or "", n)


def sh_check_list(c, oid, list_id, uid):
    """An attached list: uid may change it and it lies in the space (oid); BadInput / 404 otherwise. Returns its id or None."""
    if list_id in (None, "", 0):
        return None
    if isinstance(list_id, bool) or not isinstance(list_id, int):
        raise BadInput(tr("Invalid value: {0}", "list_id"))
    role = list_role(c, list_id, uid)
    l = c.execute("SELECT org_id, e2e FROM lists WHERE id=?", (list_id,)).fetchone()
    if not role or not l:
        raise Denied(404)
    if role not in WRITE_ROLES:
        raise Denied(403)
    if l["org_id"] != oid:
        raise BadInput(tr("The list belongs to another workspace"))
    if l["e2e"] is not None:
        raise BadInput(tr("Tables cannot be attached to a list with a lock"))
    if sh_is_agent(c, uid):
        from .vars import _agent_cap
        cap = _agent_cap(c, uid)
        if cap is not None and list_id not in cap:
            raise Denied(404)
    return list_id


def sh_clean_col(b, partial=False):
    """The column fields of a body (title, kind, options, color_mode, width)."""
    out = {}
    if "title" in b or not partial:
        out["title"] = sh_clean_title(b.get("title"), "title", SH_COL_TITLE_MAX)
    if "kind" in b or not partial:
        k = b.get("kind") or "text"
        if k not in SH_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        out["kind"] = k
    if "options" in b and b["options"] is not None:
        out["options"] = json.dumps(sh_clean_options(b["options"]), ensure_ascii=False)
    if "color_mode" in b or not partial:
        m = b.get("color_mode") or "cell"
        if m not in SH_COLOR_MODES:
            raise BadInput(tr("Invalid value: {0}", "color_mode"))
        out["color_mode"] = m
    if "width" in b:
        w = b["width"]
        if w is not None and (isinstance(w, bool) or not isinstance(w, int) or not 30 <= w <= 2000):
            raise BadInput(tr("Invalid value: {0}", "width"))
        out["width"] = w
    return out


def sh_add_col(c, sheet_row, b, uid, after_col_id=None, agent_id=None, batch=None):
    """A new column (after a column or at the end) -> its id."""
    sid = sheet_row["id"]
    f = sh_clean_col(b)
    n = c.execute("SELECT COUNT(*) FROM sheet_columns WHERE sheet_id=? AND deleted_at IS NULL", (sid,)).fetchone()[0]
    if n >= SH_COLS_MAX:
        raise BadInput(tr("Too many columns (at most {0})", SH_COLS_MAX))
    pos = _pos_after(c, "sheet_columns", sid, after_col_id)
    cid = insert_id(c, "INSERT INTO sheet_columns(sheet_id,pos,title,kind,options,color_mode,width) VALUES(?,?,?,?,?,?,?)",
                    (sid, pos, f["title"], f["kind"], f.get("options", "[]"), f["color_mode"], f.get("width")))
    sh_change(c, sid, batch, agent_id, "col", col_id=cid)
    return cid


def _pos_after(c, table, sid, after_id):
    rows = c.execute(f"SELECT id, pos FROM {table} WHERE sheet_id=? AND deleted_at IS NULL ORDER BY pos, id", (sid,)).fetchall()
    if after_id is None or not rows:
        return (rows[-1]["pos"] + 1) if rows else 1.0
    if isinstance(after_id, bool) or not isinstance(after_id, int):
        raise BadInput(tr("Invalid value: {0}", "after"))
    i = next((i for i, r in enumerate(rows) if r["id"] == after_id), None)
    if i is None:
        raise BadInput(tr("Invalid value: {0}", "after"))
    if i == len(rows) - 1:
        return rows[i]["pos"] + 1
    a, b = rows[i]["pos"], rows[i + 1]["pos"]
    if b - a < 1e-9:  # renumber when the gaps are used up
        for k, r in enumerate(rows):
            c.execute(f"UPDATE {table} SET pos=? WHERE id=?", (float(k + 1), r["id"]))
        return i + 1.5
    return (a + b) / 2


def sh_add_rows(c, sheet_row, rows, uid, after_row_id=None, agent_id=None, batch=None):
    """New rows (after a row or at the end): rows = a count of empty rows or a list of rows, each a list of inputs in the order
    of the columns (formulas in the display form). -> [row ids]"""
    sid = sheet_row["id"]
    data = None
    if isinstance(rows, bool) or not isinstance(rows, (int, list)):
        raise BadInput(tr("Invalid value: {0}", "rows"))
    if isinstance(rows, list):
        data, n = rows, len(rows)
        if any(not isinstance(r, list) for r in data):
            raise BadInput(tr("Invalid value: {0}", "rows"))
    else:
        n = rows
    have = c.execute("SELECT COUNT(*) FROM sheet_rows WHERE sheet_id=? AND deleted_at IS NULL", (sid,)).fetchone()[0]
    if n < 0 or have + n > SH_ROWS_MAX:
        raise BadInput(tr("Too many rows (at most {0})", SH_ROWS_MAX))
    ids = []
    pos = _pos_after(c, "sheet_rows", sid, after_row_id)
    nxt = None
    if after_row_id is not None:
        r = c.execute("SELECT MIN(pos) FROM sheet_rows WHERE sheet_id=? AND deleted_at IS NULL AND pos>?", (sid, pos)).fetchone()
        nxt = r[0] if r else None
    step = ((nxt - pos) / (n + 1)) if nxt is not None and n else 1.0
    for i in range(n):
        rid = insert_id(c, "INSERT INTO sheet_rows(sheet_id,pos) VALUES(?,?)", (sid, pos + i * step))
        ids.append(rid)
        sh_change(c, sid, batch, agent_id, "row", row_id=rid)
    if data:
        book = ShBook(c, sheet_row)
        cells = []
        for rid, vals in zip(ids, data):
            for col, v in zip(book.cols, vals):
                if v not in (None, ""):
                    cells.append({"row_id": rid, "col_id": col["id"], "raw": v if isinstance(v, str) else _num_raw(v)})
        if cells:
            _write_cells(c, sheet_row, cells, uid, agent_id, batch, book)
    return ids


def _num_raw(v):
    if isinstance(v, bool):
        return "WAHR" if v else "FALSCH"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    raise BadInput(tr("Invalid value: {0}", "raw"))


def _select_raw(c, book, col, raw):
    """A select column stores the option's id; a label is translated (an unknown label becomes a new option)."""
    if not raw or raw.startswith("="):
        return raw
    opts = book.opts.get(col["id"], [])
    if any(o.get("id") == raw for o in opts):
        return raw
    low = raw.strip().casefold()
    o = next((o for o in opts if (o.get("label") or "").casefold() == low), None)
    if o:
        return o["id"]
    if len(opts) >= SH_OPTIONS_MAX:
        raise BadInput(tr("Invalid value: {0}", "options"))
    new = sh_clean_options(opts + [{"label": raw}])
    c.execute("UPDATE sheet_columns SET options=? WHERE id=?", (json.dumps(new, ensure_ascii=False), col["id"]))
    book.opts[col["id"]] = new
    return new[-1]["id"]


def _resolve_target(book, d):
    """(row_id, col_id) of a cell entry {row_id, col_id} | {cell: "B4" | name}."""
    if "cell" in d:
        ref = d["cell"]
        if not isinstance(ref, str):
            raise BadInput(tr("Invalid value: {0}", "cell"))
        x = book.names().get(ref.lower())
        if x:
            return x["row_id"], x["col_id"]
        m = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d{1,6})", ref.strip())
        pos = book.pos_of(m.group(1), int(m.group(2))) if m else None
        if not pos:
            raise BadInput(tr("There is no cell {0}", ref[:20]))
        return pos
    rid, cid = d.get("row_id"), d.get("col_id")
    if rid not in book.row_idx or cid not in book.col_idx or isinstance(rid, bool) or isinstance(cid, bool):
        raise BadInput(tr("Invalid value: {0}", "cell"))
    return rid, cid


def _book_cells_check(c, sheet_row, book, cells):
    """2.148.1 D (#2485): a table holds at most SH_BOOK_CELLS_MAX stored cells over all its sheets (counted only when the
    call adds cells)."""
    new = 0
    for d in cells:
        if isinstance(d, dict) and d.get("raw") not in (None, ""):
            try:
                if _resolve_target(book, d) not in book.at:
                    new += 1
            except BadInput:
                pass  # reported by the write itself
    if not new:
        return
    bid = sheet_row["book_id"] or sheet_row["id"]
    have = c.execute("SELECT COUNT(*) FROM sheet_cells WHERE sheet_id IN (SELECT id FROM sheets WHERE id=? OR book_id=?)",
                     (bid, bid)).fetchone()[0]
    if have + new > SH_BOOK_CELLS_MAX:
        raise BadInput(tr("The table is full (at most {0} cells)", SH_BOOK_CELLS_MAX))


def _write_cells(c, sheet_row, cells, uid, agent_id, batch, book):
    """Stores the inputs; returns the set of changed cell ids."""
    if not isinstance(cells, list) or len(cells) > SH_CELLS_MAX:
        raise BadInput(tr("Invalid value: {0}", "cells"))
    ts, changed, later = iso_ms(now_utc()), set(), []
    sid = sheet_row["id"]
    _book_cells_check(c, sheet_row, book, cells)  # 2.148.1 D (#2485)
    for d in cells:
        if not isinstance(d, dict):
            raise BadInput(tr("Invalid value: {0}", "cells"))
        rid, cid = _resolve_target(book, d)
        raw = d.get("raw")
        if raw is None:
            raw = ""
        if not isinstance(raw, str):
            raw = _num_raw(raw)
        raw = raw.replace("\x00", "")
        if len(raw) > SH_RAW_MAX:
            raise BadInput(tr("The text is too long (at most {0} characters)", SH_RAW_MAX))
        if raw.strip().startswith("="):
            later.append((rid, cid, raw.strip()))  # after the plain inputs: a formula may name a cell set in the same call
            continue
        raw = _select_raw(c, book, book.col_by[cid], raw) if book.col_by[cid]["kind"] == "select" else raw
        if book.col_by[cid]["kind"] in SHK_KINDS:  # 2.124.0 B (#2110): checked / translated (file: the old one to the trash)
            raw = shk_raw(c, book, book.col_by[cid], rid, raw)
        changed.add(_store(c, book, sid, rid, cid, raw, uid, ts, agent_id, batch))
    for rid, cid, raw in later:
        x = book.at.get((rid, cid))
        internal = sh_to_internal(c, sheet_row, raw, uid, book, keep=(x["raw"] if x else ""))
        changed.add(_store(c, book, sid, rid, cid, internal, uid, ts, agent_id, batch))
    return {x for x in changed if x}


def _store(c, book, sid, rid, cid, raw, uid, ts, agent_id, batch):
    x = book.at.get((rid, cid))
    if x and x["raw"] == raw and not x["frozen"]:
        return None
    old = x["raw"] if x else None
    if x:
        c.execute("UPDATE sheet_cells SET raw=?, frozen=0, frozen_value=NULL, updated_by=?, updated_at=?, agent_id=?, agent_batch=? "
                  "WHERE id=?", (raw, uid, ts, agent_id, batch, x["id"]))
        x.update(raw=raw, frozen=0, frozen_value=None, updated_by=uid, updated_at=ts, agent_id=agent_id, agent_batch=batch)
        xid = x["id"]
    else:
        xid = insert_id(c, "INSERT INTO sheet_cells(sheet_id,row_id,col_id,raw,updated_by,updated_at,agent_id,agent_batch) "
                           "VALUES(?,?,?,?,?,?,?,?)", (sid, rid, cid, raw, uid, ts, agent_id, batch))
        book._add(dict(c.execute("SELECT * FROM sheet_cells WHERE id=?", (xid,)).fetchone()))
    sh_change(c, sid, batch, agent_id, "cell", cell_id=xid, row_id=rid, col_id=cid, old=old, new=raw)
    from .shhist import shh_log  # 2.124.0 B (#2112)
    shh_log(c, book, xid, rid, cid, old, raw, uid, agent_id, ts)  # 2.124.0 B (#2112): people's changes too
    return xid


def sh_dependents(book, res_deps, ids):
    """ids plus every formula cell that reads them (transitively)."""
    users = {}
    for cid, ds in res_deps.items():
        for d in ds:
            users.setdefault(d, set()).add(cid)
    out, todo = set(ids), list(ids)
    while todo:
        for u in users.get(todo.pop(), ()):
            if u not in out:
                out.add(u)
                todo.append(u)
    return out


def sh_set_cells(c, sheet_row, cells, uid, agent_id=None, batch=None):
    """Stores inputs [{row_id, col_id, raw}] or [{cell: "B4" | name, raw}] (empty raw = empty cell) -> the cell dicts of the
    changed cells and of every cell that depends on them, evaluated for the current principal. BadInput on a wrong formula
    (nothing is stored then: the caller's transaction is rolled back)."""
    book = ShBook(c, sheet_row)
    changed = _write_cells(c, sheet_row, cells, uid, agent_id, batch, book)
    if changed:
        sh_touch(c, sheet_row["id"], uid)
    book = ShBook(c, sh_reload(c, sheet_row["id"]))
    ev_uid = me() if has_request_context() and getattr(g, "user", None) is not None else uid
    res = sh_eval(c, book.sheet, book, ev_uid)
    deps = {cid: r["refs"] for cid, r in res.items()}
    ids = sh_dependents(book, deps, changed)
    return sh_cell_dicts(c, book.sheet, book, res, ids=ids, uid=ev_uid)


def sh_create(c, uid, space, title, list_id=None, columns=None, rows=None, agent_id=None, batch=None):
    """A new sheet in a space ("private" | "org:N"), optionally attached to a list uid may change (of the same space) ->
    its id. columns: [{title, kind, options, color_mode, width}] (default A-C, text); rows: a list of rows of inputs (default
    10 empty rows)."""
    oid = sh_space(c, uid, space)
    lid = sh_check_list(c, oid, list_id, uid)
    t = sh_clean_title(title) or tr("Table")
    ts = iso_ms(now_utc())
    sid = insert_id(c, "INSERT INTO sheets(org_id,owner_id,title,list_id,created_by,created_at,updated_at,updated_by,agent_id,agent_batch) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)", (oid, None if oid else (sh_agent_owner(c, uid) if sh_is_agent(c, uid) else uid), t, lid, uid, ts, ts, uid, agent_id, batch))
    sh_change(c, sid, batch, agent_id, "create")
    cols = columns if columns is not None else [{"title": "", "kind": "text"} for _ in range(SH_START_COLS)]
    if not isinstance(cols, list) or len(cols) > SH_COLS_MAX:
        raise BadInput(tr("Too many columns (at most {0})", SH_COLS_MAX))
    for i, col in enumerate(cols):
        if not isinstance(col, dict):
            raise BadInput(tr("Invalid value: {0}", "columns"))
        f = sh_clean_col(col)
        c.execute("INSERT INTO sheet_columns(sheet_id,pos,title,kind,options,color_mode,width) VALUES(?,?,?,?,?,?,?)",
                  (sid, float(i + 1), f["title"], f["kind"], f.get("options", "[]"), f["color_mode"], f.get("width")))
    r = sh_reload(c, sid)
    if rows is None:
        sh_add_rows(c, r, SH_START_ROWS, uid)
    else:
        sh_add_rows(c, r, rows, uid, agent_id=None, batch=None)
        if agent_id and batch:  # the cells belong to the agent's call (Undo = the whole sheet to the trash)
            c.execute("UPDATE sheet_cells SET agent_id=?, agent_batch=? WHERE sheet_id=?", (agent_id, batch, sid))
    return sid


def sh_undo_batch(c, sheet_row, batch, uid):
    """Takes back exactly the changes of one agent call (newest first): cells get their former input when nobody changed them
    since, added rows / columns go to the trash, a sheet the call created goes to the trash. -> number of changes undone."""
    rows = c.execute("SELECT * FROM sheet_changes WHERE sheet_id=? AND batch=? AND undone_at IS NULL ORDER BY id DESC",
                     (sheet_row["id"], batch)).fetchall()
    ts, n = iso_ms(now_utc()), 0
    for r in rows:
        if r["kind"] == "cell":
            x = c.execute("SELECT raw FROM sheet_cells WHERE id=?", (r["cell_id"],)).fetchone()
            if not x or x["raw"] != (r["new_raw"] or ""):
                continue  # changed again since: the newer input stays
            c.execute("UPDATE sheet_cells SET raw=?, frozen=0, frozen_value=NULL, updated_by=?, updated_at=?, agent_id=NULL, agent_batch=NULL "
                      "WHERE id=?", (r["old_raw"] or "", uid, ts, r["cell_id"]))
        elif r["kind"] == "row":
            c.execute("UPDATE sheet_rows SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (ts, r["row_id"]))
        elif r["kind"] == "col":
            c.execute("UPDATE sheet_columns SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (ts, r["col_id"]))
        elif r["kind"] == "create":
            c.execute("UPDATE sheets SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (ts, sheet_row["id"]))
        c.execute("UPDATE sheet_changes SET undone_at=? WHERE id=?", (ts, r["id"]))
        n += 1
    if n:
        sh_touch(c, sheet_row["id"], uid)
    return n


def sh_set_name(c, sheet_row, cell_row, name, uid):
    """Gives a cell a name (None / "" = no name); BadInput when invalid or taken (cells and column names)."""
    name = (name or "").strip() if isinstance(name, (str, type(None))) else None
    if name is None:
        raise BadInput(tr("Invalid value: {0}", "name"))
    if name:
        if not sh_name_ok(name):
            raise BadInput(tr("Use letters, digits and _ only, starting with a letter (not like a cell address)"))
        book = ShBook(c, sheet_row)
        other = book.names().get(name.lower())
        if other and other["id"] != cell_row["id"]:
            raise BadInput(tr("This name is already used in this table"))
        if name.lower() in book.slug_col:
            raise BadInput(tr("This name is already used in this table"))
    c.execute("UPDATE sheet_cells SET name=?, updated_by=?, updated_at=? WHERE id=?", (name or None, uid, iso_ms(now_utc()), cell_row["id"]))
    sh_touch(c, sheet_row["id"], uid)


def sh_freeze(c, sheet_row, cell_row, frozen, uid):
    """Freezes the cell's current value (evaluated for uid: a deliberate copy, like a typed number) or thaws it."""
    ts = iso_ms(now_utc())
    if frozen:
        book = ShBook(c, sheet_row)
        res = sh_eval(c, sheet_row, book, uid).get(cell_row["id"]) or {}
        if res.get("error"):
            raise BadInput(tr("Only a value can be frozen"))
        vt, jv = res.get("vtype"), res.get("value")
        v = sh_parse_date(jv) if vt == "date" else float(jv) if vt == "number" else jv
        c.execute("UPDATE sheet_cells SET frozen=1, frozen_value=?, updated_by=?, updated_at=? WHERE id=?",
                  (sh_freeze_dump(v, res.get("display") or ""), uid, ts, cell_row["id"]))
    else:
        c.execute("UPDATE sheet_cells SET frozen=0, frozen_value=NULL, updated_by=?, updated_at=? WHERE id=?", (uid, ts, cell_row["id"]))
    sh_touch(c, sheet_row["id"], uid)


def sh_need_cell(c, sheet_row, cid):
    x = c.execute("SELECT * FROM sheet_cells WHERE id=? AND sheet_id=?", (cid, sheet_row["id"])).fetchone()
    if not x:
        raise Denied(404)
    return x


def sh_vars(c, sheet_row, uid, q=""):
    """The completion after "=": the sheet's cell names and column names, the projects / lists / clients uid may use here
    (with their fields), hier.<field>, the functions -- filtered by q."""
    from .vars import SH_FIELD_HELP, sh_sources
    book = ShBook(c, sheet_row)
    res = sh_eval(c, sheet_row, book, uid)
    lg = lang()
    q = (q or "").strip().lower()[:80]
    out = []

    def add(token, label, kind, value_display="", help_=""):
        if q and q not in token.lower() and q not in (label or "").lower():
            return
        out.append({"token": token, "label": label, "kind": kind, "value_display": value_display, "help": help_})

    for x in sorted(book.names().values(), key=lambda x: x["name"].lower()):
        add(x["name"], book.addr(x), "cell", (res.get(x["id"]) or {}).get("display") or "")
    for col_id, s in book.col_slug.items():
        add(s, book.col_by[col_id]["title"], "column", "", tr("All cells of the column"))
    if sheet_row["list_id"] and sh_list_bound(c, sheet_row) is not None:
        for f in sh_fields_of("l"):
            try:
                v = sh_here_value(c, sheet_row, uid, f)
                vd = sh_fmt(v, "number", lg)
            except ShErr:
                continue
            add(f"hier.{f}", tr(SH_FIELD_HELP[f]), "here", vd, tr(SH_FIELD_HELP[f]))
    for typ, kind in (("p", "project"), ("l", "list"), ("k", "client")):
        for xid, slug, name in sh_sources(c, sheet_row, uid, typ):
            for f in sh_fields_of(typ):
                tok = f"{SH_VAR_WORD[typ]}.{slug}.{f}"
                if q and q not in tok and q not in (name or "").lower():
                    continue
                try:
                    v = sh_var_value(c, sheet_row, uid, typ, xid, f)
                    vd = sh_fmt(v, "currency" if f in ("satz", "budget_betrag") else "number", lg, sh_currency(c, sheet_row))
                except ShErr:
                    vd = ""
                add(tok, name, kind, vd, tr(SH_FIELD_HELP[f]))
                if len(out) >= 300:
                    break
    for fn in ("SUMME", "MITTELWERT", "MIN", "MAX", "ANZAHL", "WENN", "RUNDEN", "HEUTE", "TAGE"):
        add(fn, fn, "function", "", tr(SH_FN_HELP[fn]))
    for fn, help_ in SHF_HELP.items():  # 2.124.0 A (#2109)
        add(fn, fn, "function", "", tr(help_))
    return out[:300]


SH_FN_HELP = {"SUMME": N_("Sum of the values (SUM)"), "MITTELWERT": N_("Average of the values (AVERAGE)"),
              "MIN": N_("Smallest value"), "MAX": N_("Largest value"), "ANZAHL": N_("Number of values (COUNT)"),
              "WENN": N_("IF(condition; then; else)"), "RUNDEN": N_("ROUND(value; digits)"), "HEUTE": N_("Today's date (TODAY)"),
              "TAGE": N_("Days between two dates: DAYS(end; start)")}


def sh_index(c, uid, space=None, list_id=None):
    """The sheets uid may read: of a space ("private" | "org:N" | "all") or attached to a list."""
    agent = sh_is_agent(c, uid)
    owner = sh_agent_owner(c, uid) if agent else uid  # 2.89.0 C (#1916): a personal agent's private sheets belong to its owner
    if list_id is not None:
        if not list_role(c, list_id, uid):
            raise Denied(404)
        rows = c.execute("SELECT * FROM sheets WHERE deleted_at IS NULL AND list_id=? ORDER BY lower(title), id LIMIT 500",
                         (list_id,)).fetchall()
    elif space in (None, "", "all"):
        from ..accounts.orgs import user_orgs
        if agent:  # 2.89.0 C (#1916): an agent only in its own workspace
            a = c.execute("SELECT org_id FROM agents WHERE user_id=?", (uid,)).fetchone()
            orgs = str(int(a[0])) if a and a[0] else ""
        else:
            from ..accounts.orgroles import user_orgs_full
            orgs = ",".join(str(int(x)) for x in user_orgs(c, uid) if x in user_orgs_full(c, uid))  # 2.143.0 A (#2151)
        lids = [r[0] for r in c.execute("SELECT DISTINCT list_id FROM sheets WHERE deleted_at IS NULL AND list_id IS NOT NULL").fetchall()
                if list_role(c, r[0], uid)]
        cond = "(org_id IS NULL AND owner_id=?)" + (f" OR org_id IN ({orgs})" if orgs else "")
        if lids:
            cond += f" OR list_id IN ({','.join(str(int(x)) for x in lids)})"
        rows = c.execute(f"SELECT * FROM sheets WHERE deleted_at IS NULL AND ({cond}) ORDER BY updated_at DESC, id LIMIT 2000", (owner,)).fetchall()
    elif space == "shared":  # 2.124.0 C (#2113): only the sheets shared with uid (below)
        rows = []
    else:
        oid = sh_space(c, uid, space)
        if oid is None:
            lids = [r[0] for r in c.execute("SELECT DISTINCT list_id FROM sheets WHERE deleted_at IS NULL AND org_id IS NULL "
                                            "AND list_id IS NOT NULL").fetchall() if list_role(c, r[0], uid)]
            cond = "owner_id=?" + (f" OR list_id IN ({','.join(str(int(x)) for x in lids)})" if lids else "")
            rows = c.execute(f"SELECT * FROM sheets WHERE deleted_at IS NULL AND org_id IS NULL AND ({cond}) "
                             f"ORDER BY lower(title), id LIMIT 2000", (owner,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM sheets WHERE deleted_at IS NULL AND org_id=? ORDER BY lower(title), id LIMIT 2000",
                             (oid,)).fetchall()
    from .shshare import shs_index  # 2.124.0 C (#2113): space "shared" / the shared sheets in "all"
    rows = shb_only_books(c, rows)  # 2.124.0 E (#2116): a table once, never its further sheets
    return [r for r in (rows if list_id is not None else shs_index(c, uid, space, rows)) if sh_may(c, uid, r)]
