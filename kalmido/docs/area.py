"""2.522.0 (#4433): the office and the private file store apart -- receipts only in the office, the private documents in the
file store, ONE general input sorts.

The office (decision 04.11.2026) = the documents space of the office a person works in (office/model.py office_where): an
organisation's office -> that organisation's documents space; the personal office of a person without one (pb_personal)
keeps its documents in the person's own space (office/books.py bk_ws), so there doc_meta.area tells the two apart
('office' | 'private' | '' = never sorted: a receipt row counts as office, everything else as private). Whoever has no office
(no feature "office", an agent, a kid, several organisations without a chosen one) keeps everything as before: no sorting,
no "Move to office", no filter.

The general input (an upload without a target in the own space, the share target, a mail to the person's own document
address) marks a new document area_sort = 'pending'; after its first recognition (docs/ingest.py doc_after, outside the
recognition's transaction) ar_sort_queued puts it: a recognised invoice / receipt (an e-invoice, an invoice number, a net
amount or a VAT rate -- a gross amount alone is no sign, like static/js/receipts.js rc_isReceipt) into the office, anything
else and every doubt (a stack waiting to be split) into the private space. It never becomes a receipt by that (a person
records it, #2865). area_sort = 'auto' then offers "Wrong area" (one click, undo) in both areas; a person's choice is
'person'. A bound input (a scan inbox with place / folder docs/scankeys.py, the receipt fetcher docs/fetcher.py, an
organisation's document address, an upload into a chosen workspace, the office's own uploads) lands exactly where it
was sent and is never sorted.

Tenant boundary: the server sorts, only into the office of the person who brought the document in (created_by), with that
person's rights (files/fsmove.py fsm_plan in a request context of their own: write on the document, the right to add to the
office's documents folder); an agent never sorts and never moves (403), so nothing lands in a foreign workspace.

POST /api/docs/<id>/area {to: office | private, undo?: true} -- a person moves a document into the office / back into the
private space ("Move to office" of the private sheet, "Wrong area" of a sorted one; undo = the same call back)."""
import re

from flask import g, jsonify

from ..core.config import app
from ..core.db import body, bump, db, err, usettings
from ..core.i18n import tr
from ..core.access import Denied
from ..core.pg import system_ctx
from ..accounts.session import me
from ..accounts.orgs import user_orgs
from ..accounts.orgroles import org_role_key
from ..accounts.spacemove import smv_refuse_agent
from ..files.store import fs_log_add, need_node
from ..files.fsmove import _rm, fsm_apply, fsm_plan
from ..office.model import OFFICE_FEAT
from . import store as S
from .ingest import doc_after
from .split import sp_view

AR_AREAS = ("office", "private")
AR_NO_WRITE = ("guest", "readonly")  # roles that add nothing to an organisation's documents folder (docs/store.py root_add_ok)


def ar_office(c, uid):
    """The office of person uid as ('own', 'u<uid>', None) | ('org', 'o<oid>', oid), or None (no office: nothing is sorted).
    Like office/model.py office_where, without making the personal office (no write, no commit: also in the queue)."""
    if not uid:
        return None
    with system_ctx(c):  # the person's own account row (kind, kid, settings): the queue has no request
        u = c.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
    if not u or (u["kind"] or "user") == "agent" or ("kid" in u.keys() and u["kid"]) or u["disabled"]:
        return None
    st = usettings(c, uid)
    if OFFICE_FEAT not in (st.get("features") or "").split(","):
        return None
    orgs = user_orgs(c, uid)
    ws = (st.get("workspace") or "").strip()
    m = re.fullmatch(r"org:(\d{1,9})", ws)
    if m and int(m.group(1)) in orgs:
        oid = int(m.group(1))
    elif ws == "private" or not orgs:
        return ("own", S.doc_ws(None, uid), None)
    elif len(orgs) == 1:
        oid = orgs[0]
    else:
        return None  # several organisations, none chosen: office_where asks; nothing is sorted
    if org_role_key(c, uid, oid) in (None, *AR_NO_WRITE):
        return None
    return ("org", S.doc_ws(oid, None), oid)


def ar_is_receipt(c, nid):
    return bool(c.execute("SELECT 1 FROM rc_receipts WHERE node_id=?", (nid,)).fetchone())


def ar_of(c, m, off, uid):
    """The area of document meta m for person uid with the office off (ar_office): 'office' | 'private' | None (another
    workspace: an organisation that is not the office, somebody else's private space)."""
    if not off or not m:
        return None
    if m["ws"] == off[1]:
        if off[0] == "org":
            return "office"
        return "office" if m["area"] == "office" or ar_is_receipt(c, m["node_id"]) else "private"
    if off[0] == "org" and m["ws"] == S.doc_ws(None, uid):
        return "office" if ar_is_receipt(c, m["node_id"]) else "private"  # an old receipt of the personal office (#4434 moves them)
    return None


def ar_guess(c, nid):
    """'office' for a recognised invoice / receipt, else 'private' (also every doubt)."""
    m = S.meta_row(c, nid)
    if not m or m["state"] != "done" or (sp_view(m) or {}).get("stack"):
        return "private"  # not read (failed) or a stack waiting to be split (#4468): in doubt private
    det = S.meta_json(c, m, "extracted", {})
    if not isinstance(det, dict):
        return "private"
    if det.get("_einv") or det.get("invoice_no") or det.get("net") or det.get("vat_pct"):
        return "office"
    return "private"


def ar_view(c, node, m, uid):
    """What the document sheet needs (GET /api/docs/<id> "area", docs/web.py doc_json), None without an office or in another workspace:
    {area, office: own | org, wrong: "Wrong area" offered, can_move}."""
    off = ar_office(c, uid)
    a = ar_of(c, m, off, uid)
    if not a:
        return None
    rc = ar_is_receipt(c, m["node_id"])
    return {"area": a, "office": off[0], "wrong": m["area_sort"] == "auto" and not rc,
            "can_move": node["role"] in ("owner", "edit") and not rc}


def ar_sql(c, uid, want):
    """(SQL condition on d = doc_meta, params) of the documents list ?area=office | private; None = no filter (no office)."""
    off = ar_office(c, uid) if want in AR_AREAS else None
    if not off:
        return None
    rc = "EXISTS (SELECT 1 FROM rc_receipts r WHERE r.node_id=d.node_id)"
    if off[0] == "org":
        office = f"(d.ws=? OR (d.ws=? AND {rc}))"
        params = [off[1], S.doc_ws(None, uid)]
    else:
        office = f"(d.ws=? AND (d.area='office' OR {rc}))"
        params = [off[1]]
    return (office, params) if want == "office" else (f"NOT {office}", params)


def _set(c, nid, area, how):
    c.execute("UPDATE doc_meta SET area=?, area_sort=? WHERE node_id=?", (area, how, nid))


def ar_move(c, uid, nid, to, how):
    """Document nid of person uid into the area to ('office' | 'private') of uid's office; how = the new area_sort. Returns
    the old sealed files to remove after the commit. Raises Denied (no office, not the person's, no right)."""
    off = ar_office(c, uid)
    m = S.meta_row(c, nid)
    cur = ar_of(c, m, off, uid)
    if not cur:
        raise Denied(409, tr("This document is not in your office or your own documents"))
    if ar_is_receipt(c, nid):
        raise Denied(409, tr("This document is a receipt already"))
    if cur == to:
        _set(c, nid, to, how)
        return []
    if off[0] == "own":
        _set(c, nid, to, how)
        return []
    target = off[2] if to == "office" else None
    plan = fsm_plan(c, uid, {"ids": [nid], "parent": "docs"}, target, False)
    if plan["block"]:
        raise Denied(plan["code"], plan["block"])
    new_paths, old_paths = [], []
    try:
        fsm_apply(c, uid, plan, target, new_paths, old_paths)
    except BaseException:
        _rm(new_paths)
        raise
    _set(c, nid, to, how)
    return old_paths


# ---- the general input, after the first recognition (docs/ingest.py doc_after) ------------------------------------------
def ar_sort_queued(c, nid):
    """A document of the general input (area_sort 'pending') goes to the office or stays private (commits itself)."""
    with system_ctx(c):  # docs queue: the sorting of a document, decided for the person who brought it in
        m = c.execute("SELECT node_id, ws, area_sort, created_by FROM doc_meta WHERE node_id=?", (nid,)).fetchone()
    if not m or m["area_sort"] != "pending":
        return
    uid = m["created_by"]
    with system_ctx(c):  # the person's office (their settings and memberships)
        off = ar_office(c, uid)
        to = ar_guess(c, nid)
    if not off or m["ws"] != S.doc_ws(None, uid or 0):
        with system_ctx(c):
            _set(c, nid, "", "")  # no office (any more): as before, nothing sorted
        c.commit()
        return
    if off[0] == "own" or to == "private":
        with system_ctx(c):
            _set(c, nid, to, "auto")
        c.commit()
        return
    old = []
    prev = c.ctx
    try:
        with app.test_request_context("/api/docs/area-sort"):
            g.db = c
            g.user = c.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
            try:
                old = ar_move(c, uid, nid, "office", "auto")
                c.commit()
            except Exception as e:  # noqa: BLE001 -- a refused move leaves it private (in doubt private)
                c.rollback()
                print("docs: area sort", nid, type(e).__name__, flush=True)
                with system_ctx(c):
                    _set(c, nid, "private", "")
                c.commit()
            finally:
                g.pop("db", None)  # the queue's connection: closed by the queue
    finally:
        c.set_ctx(*prev)  # the queue's own context again (the request context followed the person)
    _rm(old)


if ar_sort_queued not in doc_after:
    doc_after.append(ar_sort_queued)


# ---- people ---------------------------------------------------------------------------------------------------------
@app.post("/api/docs/<int:nid>/area")
def ar_post(nid):
    """{to: office | private, undo?: bool}: a person moves the document into the office / the private space."""
    smv_refuse_agent()  # agents never move a document between the areas (nor sort one)
    c = db()
    uid = me()
    b = body()
    to = b.get("to")
    if to not in AR_AREAS:
        return err(tr("Invalid value: {0}", "to"))
    need_node(c, nid, write=True)
    m = S.meta_row(c, nid)
    if not m:
        raise Denied(404)
    was = m["area_sort"]
    how = "auto" if b.get("undo") is True and was == "person" else ("person" if was in ("auto", "person") else "")
    try:
        old = ar_move(c, uid, nid, to, how)
        fs_log_add(c, nid, "area", to)
        bump(c)
        c.commit()
    except BaseException:
        c.rollback()
        raise
    _rm(old)
    n = c.execute("SELECT org_id FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    return jsonify(id=nid, area=to, area_sort=how, ws=S.meta_row(c, nid)["ws"], org_id=n["org_id"] if n else None)
