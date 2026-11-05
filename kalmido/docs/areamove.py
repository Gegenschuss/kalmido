"""2.547.0 (#4434): the old receipts of the private file store into the office -- once, with a preview, one undo for 30 days.

Since #4433 (docs/area.py) the office and the private file store are apart, but what lay in the person's own documents before
stays there; nothing moves by itself with the update. Office > Receipts shows once "N receipts are still in your documents"
(GET /api/docs/office-move?count=1); the preview lists them (GET /api/docs/office-move): a document of the person's own space
that is a receipt (a row in rc_receipts), an e-invoice or a recognised invoice, each preset to "move" or "stays" -- the
tag "Tax" (Steuer) and every doubt (only one sign of an invoice) stay, and what the file move would refuse (a receipt booked
or of a locked month in the personal office's books, the cash book, the equipment list: files/fsmove.py fsm_plan) stays
with its reason and cannot be chosen. Only the person's click moves (POST /api/docs/office-move {ids}), in groups of
AMV_GROUP documents per transaction (one document that cannot go stays, the rest goes); one undo takes the whole move back
within AMV_UNDO_DAYS days (POST /api/docs/office-move/<id>/undo): the folder and the name in the own space, the shares the move
ended, the receipt's project, the area as it was. A document changed since (recorded as a receipt in the personal office,
booked in the organisation, deleted) stays where it is and is counted as "stays".

Where to (docs/area.py ar_office): the personal office (a person without an organisation or with "private" chosen) keeps its
documents in the own space, so only doc_meta.area becomes 'office'; an organisation's office gets the files in its documents
folder (fsm_plan / fsm_apply, the person's rights). Tenant boundary: in an organisation only its admin moves (review 2.522 (1)
of #4433: out of an organisation only its admin moves a file again, org_out_ok, so a member's undo could not work); a member
gets no hint and keeps "Move to office" per document. Agents never (403); another person's documents are never listed (only
the person's own space)."""
import json
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.db import body, bump, db, iso, now_utc, parse_iso, usettings, uset
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..core.pg import insert_id, system_ctx
from ..accounts.session import me
from ..accounts.orgs import is_org_admin
from ..accounts.spacemove import smv_refuse_agent
from ..files.store import fs_log_add
from ..files.fsmove import _rm, fsm_apply, fsm_list_ok, fsm_plan, fsm_share_gone
from ..notify.push import WD_TICKS
from . import store as S
from .area import ar_office
from .split import sp_view

AMV_UNDO_DAYS = 30
AMV_GROUP = 25        # documents per transaction
AMV_SCAN = 2000       # documents of the own space looked at (newest first)
AMV_LIST = 300        # rows of the preview (the rest after this move)
AMV_TAX = ("steuer", "steuern", "tax", "taxes")  # the tag that keeps a document in the private file store
AMV_HIDE = "amv_hide"  # user setting: the hint was closed (or the move done)
AMV_WHY = {"receipt": N_("Receipt"), "einvoice": N_("E-invoice"), "invoice": N_("Recognised invoice")}


def amv_office(c, uid):
    """(office of ar_office, None) or (None, why): why = 'none' (no office) | 'admin' (an organisation's office, not its admin)."""
    off = ar_office(c, uid)
    if not off:
        return None, "none"
    if off[0] == "org" and not is_org_admin(c, uid, off[2]):
        return None, "admin"
    return off, None


def amv_kind(c, m, rc):
    """('receipt' | 'einvoice' | 'invoice', sure) of document meta m, or None (no receipt: a letter, a stack, not read)."""
    if rc:
        return "receipt", True
    if m["state"] != "done" or (sp_view(m) or {}).get("stack"):
        return None
    det = S.meta_json(c, m, "extracted", {})
    if not isinstance(det, dict):
        return None
    if isinstance(det.get("_einv"), dict):
        return "einvoice", True
    signs = sum(1 for k in ("invoice_no", "net", "vat_pct") if det.get(k))
    if not signs:
        return None
    return "invoice", bool(det.get("invoice_no")) and signs >= 2  # one sign alone is a doubt: it stays


def amv_rows(c, uid, off):
    """The candidates of uid's own space for office off: [{id, name, kind, pick: move | stay, tax, sure}] (newest first)."""
    ws = S.doc_ws(None, uid)
    rows = c.execute("""SELECT d.*, n.name AS node_name, EXISTS (SELECT 1 FROM rc_receipts r WHERE r.node_id=d.node_id) AS rc
                        FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                        WHERE d.ws=? AND n.org_id IS NULL AND n.owner_id=? AND n.kind='file' AND n.deleted_at IS NULL
                        AND d.area_sort NOT IN ('pending', 'sorting') ORDER BY d.node_id DESC LIMIT ?""", (ws, uid, AMV_SCAN)).fetchall()
    out = []
    for m in rows:
        rc = bool(m["rc"])
        if off[0] == "own" and (rc or m["area"] == "office"):
            continue  # the personal office counts it as office already (docs/area.py ar_of)
        if m["area_sort"] == "person" and not rc:
            continue  # the person chose its area (Wrong area, Move to office)
        k = amv_kind(c, m, rc)
        if not k:
            continue
        tax = any((t["name"] or "").strip().casefold() in AMV_TAX for t in S.node_tags(c, m["node_id"]))
        out.append({"id": m["node_id"], "name": m["node_name"], "kind": k[0], "why": tr(AMV_WHY[k[0]]), "sure": k[1], "tax": tax,
                    "pick": "move" if k[1] and not tax else "stay"})
    return out


def amv_plan(c, uid, off, nid, dry):
    """fsm_plan of one document into the organisation's documents folder -> (plan, None) | (None, reason it stays)."""
    try:
        plan = fsm_plan(c, uid, {"ids": [nid], "parent": "docs"}, off[2], dry)
    except Denied as e:
        return None, e.text()
    if plan["block"]:
        return None, plan["block"]
    return plan, None


def amv_last(c, uid):
    """The person's last move that can still be undone: {id, n, at, until} or None."""
    r = c.execute("SELECT id, n, created_at FROM doc_office_moves WHERE user_id=? AND undone_at IS NULL ORDER BY id DESC LIMIT 1",
                  (uid,)).fetchone()
    if not r:
        return None
    until = parse_iso(r["created_at"]) + timedelta(days=AMV_UNDO_DAYS)
    return {"id": r["id"], "n": r["n"], "at": r["created_at"], "until": iso(until)} if until > now_utc() else None


@app.get("/api/docs/office-move")
def amv_get():
    """?count=1: only the number for the hint. -> {n, hidden, undo, office, items?: [...], more}."""
    smv_refuse_agent()
    c = db()
    uid = me()
    off, why = amv_office(c, uid)
    hidden = usettings(c, uid).get(AMV_HIDE) == "1"
    undo = amv_last(c, uid)
    if not off:
        return jsonify(n=0, hidden=hidden, undo=undo, office=None, why=why, items=[])
    rows = amv_rows(c, uid, off)
    out = {"n": len(rows), "hidden": hidden, "undo": undo, "office": off[0]}
    if request.args.get("count") == "1":
        return jsonify(out)
    items = rows[:AMV_LIST]
    if off[0] == "org":
        for x in items:
            _, block = amv_plan(c, uid, off, x["id"], True)
            if block:
                x.update(pick="stay", block=block)
    c.rollback()  # the plans write nothing; nothing of a preview stays
    return jsonify(**out, items=items, more=max(0, len(rows) - AMV_LIST))


@app.post("/api/docs/office-move/hide")
def amv_hide():
    """The hint closed: it does not come back (the preview stays reachable through the undo line while it lasts)."""
    smv_refuse_agent()
    c = db()
    uset(c, me(), AMV_HIDE, "1")
    c.commit()
    return jsonify(ok=True)


def amv_one(c, uid, off, nid):
    """Moves document nid into the office -> (item for the undo, old sealed files) or (None, reason it stays). In a savepoint."""
    m = S.meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    item = {"id": nid, "parent": node["parent_id"], "name": node["name"], "area": m["area"], "sort": m["area_sort"]}
    if off[0] == "own":
        c.execute("UPDATE doc_meta SET area='office', area_sort='person' WHERE node_id=?", (nid,))
        fs_log_add(c, nid, "area", "move:office")
        return item, []
    plan, block = amv_plan(c, uid, off, nid, False)
    if block:
        return None, block
    ends = set(plan.get("ends") or [])
    item["shares"] = [{k: s[k] for k in s.keys() if k != "id"} for s in c.execute("SELECT * FROM fs_shares WHERE node_id=?", (nid,)).fetchall()
                      if s["id"] in ends]
    rc = c.execute("SELECT list_id FROM rc_receipts WHERE node_id=?", (nid,)).fetchone()
    item["list"] = rc["list_id"] if rc else None
    item["rc"] = bool(rc)
    new_paths, old_paths = [], []
    try:
        with c.savepoint():
            fsm_apply(c, uid, plan, off[2], new_paths, old_paths)
            c.execute("UPDATE doc_meta SET area='office', area_sort='person' WHERE node_id=?", (nid,))
            fs_log_add(c, nid, "area", "move:office")
    except Denied as e:
        _rm(new_paths)
        return None, e.text()
    except BaseException:
        _rm(new_paths)
        raise
    return item, old_paths


@app.post("/api/docs/office-move")
def amv_post():
    """{ids: [document ids to move]} -> {id (the move, for the undo), moved, stayed: [{id, reason}], undo_until}."""
    smv_refuse_agent()
    c = db()
    uid = me()
    off, why = amv_office(c, uid)
    if not off:
        raise Denied(403 if why == "admin" else 409, tr("Only an admin of the organisation moves documents into its office")
                     if why == "admin" else tr("You have no office"))
    ids = body().get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
        raise Denied(400, tr("Invalid value: {0}", "ids"))
    allowed = {x["id"] for x in amv_rows(c, uid, off)}  # only the person's own candidates, never a foreign id
    want = [i for i in dict.fromkeys(ids) if i in allowed]
    stayed = [{"id": i, "reason": tr("This document is not in your office or your own documents")} for i in ids if i not in allowed]
    if not want:
        raise Denied(409, tr("Nothing to move"))
    rid = insert_id(c, "INSERT INTO doc_office_moves(user_id,target,items,n,created_at) VALUES(?,?,'[]',0,?)", (uid, off[1], iso(now_utc())))
    uset(c, uid, AMV_HIDE, "1")  # the hint has done its work; the undo line follows
    c.commit()
    items = []
    for g0 in range(0, len(want), AMV_GROUP):
        old = []
        for nid in want[g0:g0 + AMV_GROUP]:
            item, res = amv_one(c, uid, off, nid)
            if item:
                items.append(item)
                old += res
            else:
                stayed.append({"id": nid, "reason": res})
        c.execute("UPDATE doc_office_moves SET items=?, n=? WHERE id=?", (json.dumps(items, separators=(",", ":"), default=str), len(items), rid))
        bump(c)
        c.commit()
        _rm(old)
    if not items:
        c.execute("DELETE FROM doc_office_moves WHERE id=?", (rid,))
        c.commit()
    return jsonify(id=rid if items else None, moved=len(items), stayed=stayed,
                   undo_until=iso(now_utc() + timedelta(days=AMV_UNDO_DAYS)) if items else None)


def amv_back(c, uid, run, x):
    """One document of move run back -> (True, old sealed files) | (False, []) when it changed since and stays."""
    nid = x["id"]
    m = S.meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not m or not node or node["deleted_at"]:
        return False, []
    if run["target"] == S.doc_ws(None, uid):  # the personal office: the area only, unless it is a receipt now
        if m["ws"] != run["target"] or m["area"] != "office" or m["area_sort"] != "person" \
                or c.execute("SELECT 1 FROM rc_receipts WHERE node_id=?", (nid,)).fetchone():
            return False, []
        c.execute("UPDATE doc_meta SET area=?, area_sort=? WHERE node_id=?", (x["area"], x["sort"], nid))
        fs_log_add(c, nid, "area", "move:undo")
        return True, []
    if m["ws"] != run["target"]:
        return False, []  # moved on since (another workspace): it stays there
    p = c.execute("SELECT org_id, owner_id, deleted_at, kind FROM fs_nodes WHERE id=?", (x["parent"],)).fetchone() if x.get("parent") else None
    parent = x["parent"] if p and p["kind"] == "folder" and not p["deleted_at"] and p["org_id"] is None and p["owner_id"] == uid else None
    try:
        plan = fsm_plan(c, uid, {"items": [{"id": nid, "parent": parent, "name": x["name"]}]}, None, False)
    except Denied:
        return False, []
    if plan["block"]:
        return False, []
    new_paths, old_paths = [], []
    try:
        with c.savepoint():
            fsm_apply(c, uid, plan, None, new_paths, old_paths)
            for s in x.get("shares") or []:  # the shares the move ended (still possible: the person / group / agent is there)
                s = {**s, "node_id": nid}
                if fsm_share_gone(c, s):
                    continue
                cols = [k for k in s if k in ("node_id", "user_id", "group_id", "agent_id", "role", "expires_at", "created_by",
                                              "created_at", "list_role")]
                c.execute(f"INSERT INTO fs_shares({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [s[k] for k in cols])
            if x.get("list") and fsm_list_ok(c, x["list"], None, uid):
                c.execute("UPDATE rc_receipts SET list_id=? WHERE node_id=? AND list_id IS NULL", (x["list"], nid))
            c.execute("UPDATE doc_meta SET area=?, area_sort=? WHERE node_id=?", (x["area"], x["sort"], nid))
            fs_log_add(c, nid, "area", "move:undo")
    except Denied:
        _rm(new_paths)
        return False, []
    except BaseException:
        _rm(new_paths)
        raise
    return True, old_paths


@app.post("/api/docs/office-move/<int:rid>/undo")
def amv_undo(rid):
    """The whole move back (within AMV_UNDO_DAYS) -> {back, stayed}."""
    smv_refuse_agent()
    c = db()
    uid = me()
    run = c.execute("SELECT * FROM doc_office_moves WHERE id=? AND user_id=? FOR UPDATE", (rid, uid)).fetchone()
    if not run:
        raise Denied(404)
    if run["undone_at"]:
        raise Denied(409, tr("This move was undone already"))
    if parse_iso(run["created_at"]) + timedelta(days=AMV_UNDO_DAYS) <= now_utc():
        raise Denied(409, tr("The undo of this move has expired"))
    try:
        items = json.loads(run["items"] or "[]")
    except ValueError:
        items = []
    c.execute("UPDATE doc_office_moves SET undone_at=? WHERE id=?", (iso(now_utc()), rid))  # once, even if two clicks race
    c.commit()
    back, stayed = 0, []
    for g0 in range(0, len(items), AMV_GROUP):
        old = []
        for x in items[g0:g0 + AMV_GROUP]:
            ok, res = amv_back(c, uid, run, x)
            if ok:
                back += 1
                old += res
            else:
                stayed.append(x["id"])
        bump(c)
        c.commit()
        _rm(old)
    return jsonify(back=back, stayed=stayed)


def amv_prune(c, *_):
    """Watchdog: the moves older than AMV_UNDO_DAYS are deleted (their undo has expired)."""
    with system_ctx(c):  # watchdog: the expired undo rows of every person (ids, names, folder ids; no content)
        c.execute("DELETE FROM doc_office_moves WHERE created_at<?", (iso(now_utc() - timedelta(days=AMV_UNDO_DAYS)),))
    c.commit()


WD_TICKS.append(("receipt move undo", amv_prune))
