"""2.66.0 B (#1835): merging duplicate clients by hand (Office > Clients, the selection mode), reversible for 30 days.

clm_merge keeps one client (the target) and moves everything of the others to it: every foreign key to clients (quotations
/ invoices, contracts, archive entries, contact persons, trips, deals and whatever a later version adds, core/merges.py
mg_fk_refs) plus lists.client_id (no foreign key; together with the documents, so billed time stays billed). A finalised
document keeps its printed address (recipient_snapshot); only its client changes. Drafts read the target's address
afterwards (the overview says so). Per field that differs, pick names the client whose value stays. Who may merge: the
people who see every client and may delete the others (their creator or an admin, like DELETE); all in one scope (the
same organisation, or the private clients of one person). The route is a thin wrapper: #1357 (an agent tidying up
duplicates) will call clm_merge / clm_undo directly."""
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr, trn
from ..core.db import body, bump, db, iso, now_utc
from ..core.pg import system_ctx, table_columns, write_lock
from ..core.access import Denied
from ..core.merges import (MG_MAX, mg_cascade_rows, mg_fk_refs, mg_history, mg_mark_undone, mg_repoint, mg_reinsert, mg_run,
                           mg_run_create, mg_undo_cascade, mg_undo_refs, mg_undoable)
from ..accounts.session import me
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput, UnknownFields
from .clients import CLIENT_BILLING, _gate, _org_boundary, _user, client_rows, need_client

def Nn_(one, other):  # a plural pair for trn (marked for tools/i18n_check.py, like notify/alerts.py)
    return one, other


CLM_FIELDS = ("name", "icon", "color", "contact", "email", "phone", "address", "note", "rate", "budget_h", "budget_amount",
              *CLIENT_BILLING)
# the overview's line per known table (one, other); a table not named here shows as "N more links"
CLM_LINES = {
    "office_contracts": Nn_("{0} contract", "{0} contracts"),
    "office_archive": Nn_("{0} archive entry", "{0} archive entries"),
    "office_client_contacts": Nn_("{0} contact person", "{0} contact persons"),
    "office_trips": Nn_("{0} trip", "{0} trips"),
    "office_deals": Nn_("{0} sales opportunity", "{0} sales opportunities"),
}


def _empty(v):
    return v is None or (isinstance(v, str) and not v.strip())


def clm_ids(target, ids):
    """(target, [target, others...]) validated: 2 to MG_MAX distinct clients."""
    target = as_int(target, "target", 1)
    if not isinstance(ids, list):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    if len(ids) > MG_MAX * 4:
        raise BadInput(tr("At most {0} entries can be merged at once", MG_MAX))
    out = list(dict.fromkeys([target, *(as_int(x, "ids", 1) for x in ids)]))
    if len(out) < 2:
        raise BadInput(tr("Choose at least two entries to merge"))
    if len(out) > MG_MAX:
        raise BadInput(tr("At most {0} entries can be merged at once", MG_MAX))
    return target, out


def clm_scope(r):
    """(org_id, owner) of a client: an organisation's clients share org_id, private ones (org_id NULL) their creator."""
    return (r["org_id"], None) if r["org_id"] is not None else (None, r["created_by"])


def clm_may_delete(uid, r):
    u = getattr(g, "user", None)
    return bool((u is not None and u["is_admin"]) or r["created_by"] == uid)


def clm_check(c, uid, target, ids):
    """The rows {id: row} after the checks: every client visible (else 404), the others deletable by uid (else 403), all
    in one scope (else 400)."""
    rows = {i: need_client(c, i, uid) for i in ids}
    if any(not clm_may_delete(uid, rows[i]) for i in ids if i != target):
        raise Denied(403, tr("Only the person who created the client or an admin can delete it"))
    if len({clm_scope(r) for r in rows.values()}) != 1:
        raise BadInput(tr("Only clients of the same workspace can be merged"))
    return rows


def clm_values(rows, target, ids, pick, cols):
    """{column: value} the target gets (only the columns that change). pick = {field: id of the client whose value stays};
    a field missing in pick keeps the target's value, or (target empty) the first non-empty one."""
    if pick is None:
        pick = {}
    if not isinstance(pick, dict):
        raise BadInput(tr("Invalid value: {0}", "pick"))
    bad = sorted(k for k in pick if k not in CLM_FIELDS)
    if bad:
        raise UnknownFields(bad)
    t = rows[target]
    out = {}
    for k in CLM_FIELDS:
        if k not in cols or k == "contact":  # contact = the default contact person's name (see clm_merge)
            continue
        if k in pick:
            src = as_int(pick[k], "pick", 1)
            if src not in ids:
                raise BadInput(tr("Invalid value: {0}", "pick"))
            v = rows[src][k]
        elif not _empty(t[k]):
            continue
        else:
            v = next((rows[i][k] for i in ids if not _empty(rows[i][k])), t[k])
        if v != t[k]:
            out[k] = v
    return out


def clm_ref_tables(c):
    """[(table, column)] of every reference to clients: the foreign keys plus lists.client_id (no foreign key)."""
    refs = [(t, col) for t, col, _ in mg_fk_refs(c, "clients")]
    return refs + [("lists", "client_id")] if ("lists", "client_id") not in refs else refs


def clm_counts(c, others):
    """{key: n} of what moves (keys: table names; office_docs split into docs_locked / docs_open)."""
    qs = ",".join("?" * len(others))
    out = {}
    for t, col in clm_ref_tables(c):
        if t == "office_docs":
            r = c.execute(f"SELECT COUNT(*) FILTER (WHERE locked_at IS NOT NULL), COUNT(*) FILTER (WHERE locked_at IS NULL) "
                          f"FROM office_docs WHERE client_id IN ({qs})", others).fetchone()
            out["docs_locked"], out["docs_open"] = int(r[0] or 0), int(r[1] or 0)
            continue
        n = c.execute(f"SELECT COUNT(*) FROM {t} WHERE {col} IN ({qs})", others).fetchone()[0]
        out[t] = out.get(t, 0) + int(n or 0)
    return {k: v for k, v in out.items() if v}


def clm_lines(counts, target_name):
    """The overview's lines (the person's language) from clm_counts."""
    lines = []
    if counts.get("docs_locked"):
        lines.append(trn("{0} issued quotation or invoice (keeps its printed address)", "{0} issued quotations or invoices (keep their printed address)",
                         counts["docs_locked"]))
    if counts.get("docs_open"):
        lines.append(trn("{0} draft or open quotation shows the address of {1} afterwards", "{0} drafts or open quotations show the address of {1} afterwards",
                         counts["docs_open"], target_name))
    if counts.get("datev"):
        lines.append(trn("{0} issued invoice is exported to DATEV under the customer number of {1} afterwards",
                         "{0} issued invoices are exported to DATEV under the customer number of {1} afterwards", counts["datev"], target_name))
    if counts.get("lists"):
        lines.append(trn("{0} project", "{0} projects", counts["lists"]))
    for t, (one, other) in CLM_LINES.items():
        if counts.get(t):
            lines.append(trn(one, other, counts[t]))
    more = sum(n for k, n in counts.items() if k not in CLM_LINES and k not in ("docs_locked", "docs_open", "lists", "datev"))
    if more:
        lines.append(trn("{0} more link", "{0} more links", more))
    if not lines:
        lines.append(tr("Nothing else is linked to the other clients."))
    return lines


def clm_office(c, scope):
    """The office area of a scope (organisation, or the owner's personal office; None when there is none)."""
    oid, owner = scope
    if oid is not None:
        return oid
    from ..office.model import pb_personal
    return pb_personal(c, owner, create=False) if owner == me() else None


def clm_log(c, scope, action, detail):
    oid = clm_office(c, scope)
    if oid:
        from ..office.ledger import ofx_log
        ofx_log(c, oid, action, target="client", detail=detail)


def clm_merge(c, uid, target, ids, pick=None, dry=False):
    """Merges the clients ids into target (see the module text). dry: {lines, counts} without a change; else {run_id}."""
    from ..office.contacts_cl import FK_LIMIT, fk_sync
    target, ids = clm_ids(target, ids)
    rows = clm_check(c, uid, target, ids)
    others = [i for i in ids if i != target]
    cols = table_columns(c, "clients")
    new = clm_values(rows, target, ids, pick, cols)
    t = rows[target]
    # system: the references are counted / moved in every workspace (a document of another workspace may point to a
    # client, see clients_bulk.ms_client_in_use); only numbers come out, no content
    with system_ctx(c):
        counts = clm_counts(c, others)
        # review: DATEV reads the debtor (customer number) from the live client -- issued invoices of a client with another
        # number are exported under the target's number afterwards; the overview says so
        if "customer_no" in cols and counts.get("docs_locked"):
            cn = (new.get("customer_no", t["customer_no"]) or "").strip()
            dif = [i for i in others if (rows[i]["customer_no"] or "").strip() != cn]
            if dif:
                # 2.81.0 (#1867): an invoice locked with a customer number keeps it (datev.r81b_customer_no); only the others move
                from ..office.datev import r81b_customer_no
                n = sum(1 for r in c.execute("SELECT locked_at, recipient_snapshot, '' AS dx_customer_no FROM office_docs WHERE locked_at "
                                             f"IS NOT NULL AND client_id IN ({','.join('?' * len(dif))})", dif) if not r81b_customer_no(r))
                if n:
                    counts["datev"] = int(n)
        nk = c.execute(f"SELECT COUNT(*) FROM office_client_contacts WHERE client_id IN ({','.join('?' * len(ids))})", ids).fetchone()[0]
    if nk > FK_LIMIT:
        raise BadInput(tr("Together these clients have more than {0} contact persons", FK_LIMIT))
    if dry:
        return {"lines": clm_lines(counts, t["name"]), "counts": counts, "fields": new}
    scope = clm_scope(t)
    write_lock(c, f"client_merge_{scope[0]}_{scope[1]}")
    with system_ctx(c):  # review: a client deleted / merged meanwhile (between the check and the lock)
        alive = c.execute(f"SELECT COUNT(*) FROM clients WHERE id IN ({','.join('?' * len(ids))})", ids).fetchone()[0]
    if alive != len(ids):
        raise Denied(409, tr("One of the clients was changed meanwhile, please try again"))
    before = {k: t[k] for k in t.keys()}
    with system_ctx(c):  # system: see above (moving every reference; the deleted rows go into the snapshot)
        kdef = [dict(r) for r in c.execute(f"SELECT id, client_id, is_default FROM office_client_contacts WHERE client_id IN "
                                           f"({','.join('?' * len(ids))})", ids)]
        refs = [mg_repoint(c, tb, col, others, target) for tb, col in clm_ref_tables(c)]
        cascade = mg_cascade_rows(c, "clients", others)
        # contact persons: the target's default stays; pick "contact" = the default of the chosen client
        src = pick.get("contact") if isinstance(pick, dict) else None
        src = as_int(src, "pick", 1) if src is not None else None
        want = next((k["id"] for k in kdef if k["client_id"] == src and k["is_default"]), None) if src in ids else None
        if want is None:
            want = next((k["id"] for k in kdef if k["client_id"] == target and k["is_default"]), None)
        if want is not None:
            c.execute("UPDATE office_client_contacts SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END WHERE client_id=?", (want, target))
        c.execute(f"DELETE FROM clients WHERE id IN ({','.join('?' * len(others))})", others)
    if any(rows[i]["import_run_id"] for i in ids if "import_run_id" in cols):
        new["import_run_id"] = None  # an undo of the legacy import must not delete the merged target
    ts = iso(now_utc())
    if new:
        c.execute(f"UPDATE clients SET {','.join(k + '=?' for k in new)}, updated_at=? WHERE id=?", [*new.values(), ts, target])
    fk_sync(c, target)
    after = {k: v for k, v in dict(c.execute("SELECT * FROM clients WHERE id=?", (target,)).fetchone()).items() if k != "updated_at"}
    snap = {"target": before, "after": after, "clients": [dict(rows[i]) for i in others], "refs": refs, "cascade": cascade,
            "kdef": kdef}
    summary = {"target_name": t["name"], "merged": [{"id": i, "name": rows[i]["name"]} for i in others], "counts": counts}
    rid = mg_run_create(c, "client", target, others, uid, snap, summary, org_id=scope[0])
    clm_log(c, scope, "client_merge", {"id": target, "merged": [{"id": i, "name": rows[i]["name"]} for i in others], "run": rid})
    bump(c)
    c.commit()
    return {"run_id": rid}


def clm_run_scope_ok(c, uid, d):
    """May uid see the scope of merge d? Its organisation (a member, or an admin where organisations are not separate),
    or private: the person who merged."""
    u = _user(c, uid)
    if d["org_id"] is not None:
        from ..accounts.orgs import user_orgs
        return d["org_id"] in user_orgs(c, uid) or bool(u and u["is_admin"] and not _org_boundary(c))
    return d["user_id"] == uid


def clm_may_undo(c, uid, d):
    """Undo: whoever may see the scope and merged it, or may delete every merged client again (creator / admin)."""
    if not clm_run_scope_ok(c, uid, d):
        return False
    cl = (d.get("snapshot") or {}).get("clients") or []
    u = _user(c, uid)
    return bool(d["user_id"] == uid or (u and u["is_admin"]) or (cl and all(x.get("created_by") == uid for x in cl)))


def clm_undo(c, uid, rid):
    """Undoes merge rid: the merged clients come back under their ids, their references move back (only those still at
    the target or emptied since), the target gets back the values the merge changed (unless edited since). -> {ok,
    target_gone}. 404 unknown / not in the person's scope, 403 no right, 409 already undone / too old."""
    from ..office.contacts_cl import fk_sync
    rid = as_int(rid, "id", 1)
    write_lock(c, f"client_merge_run_{rid}")
    d = mg_run(c, rid, "client")
    if not d or not clm_run_scope_ok(c, uid, d):
        raise Denied(404)
    if not clm_may_undo(c, uid, d):
        raise Denied(403, tr("Only the person who merged the clients, their creator or an admin can undo it"))
    why = mg_undoable(d)
    if why:
        raise Denied(409, tr("This merge has already been undone") if why == "undone" else tr("This merge is too old to be undone"))
    s = d["snapshot"]
    tid = d["target_id"]
    cl = s.get("clients") or []
    with system_ctx(c):  # system: the references go back in every workspace they came from (merge: see clm_merge)
        tgone = not c.execute("SELECT 1 FROM clients WHERE id=?", (tid,)).fetchone()
        for r in cl:
            mg_reinsert(c, "clients", r)
        mg_undo_cascade(c, s.get("cascade"))
        mg_undo_refs(c, s.get("refs"), target_gone=tgone)
        for k in s.get("kdef") or []:
            c.execute("UPDATE office_client_contacts SET is_default=? WHERE id=? AND client_id=?", (k["is_default"], k["id"], k["client_id"]))
        cur = c.execute("SELECT * FROM clients WHERE id=?", (tid,)).fetchone()
    gone = cur is None
    if not gone:
        b, a = s.get("target") or {}, s.get("after") or {}
        back = {k: b[k] for k in (*CLM_FIELDS, "import_run_id") if k in b and k in a and k in cur.keys() and k != "contact"
                and cur[k] == a[k] and b[k] != a[k]}
        if back:
            c.execute(f"UPDATE clients SET {','.join(k + '=?' for k in back)}, updated_at=? WHERE id=?", [*back.values(), iso(now_utc()), tid])
        fk_sync(c, tid)
    for r in cl:
        fk_sync(c, r["id"])
    mg_mark_undone(c, rid, uid)
    clm_log(c, (d["org_id"], None if d["org_id"] is not None else uid), "client_merge_undo",
            {"id": tid, "merged": [x["id"] for x in cl], "run": rid})
    bump(c)
    c.commit()
    return {"ok": True, "target_gone": gone, "restored": [x["id"] for x in cl]}


def clm_history(c, uid, r):
    """The merges into client r for its detail answer (people only; everyone who sees the client may edit it):
    [{id, at, by, by_name, merged: [{id, name}], counts, undo, undone_at, can_undo}]."""
    u = _user(c, uid)
    if not u or u["kid"] or (u["kind"] or "user") == "agent":
        return []
    out = []
    for h in mg_history(c, "client", r["id"]):
        if (h.get("summary") or {}).get("merged") is None:
            continue
        nm = c.execute("SELECT COALESCE(NULLIF(display_name, ''), username) FROM users WHERE id=?", (h["by"],)).fetchone() if h["by"] else None
        can = h["undo"] == ""
        if can:
            d = mg_run(c, h["id"], "client")
            can = bool(d and clm_may_undo(c, uid, d))
        out.append({"id": h["id"], "at": h["at"], "by": h["by"], "by_name": nm[0] if nm else "", "merged": h["summary"].get("merged") or [],
                    "counts": h["summary"].get("counts") or {}, "undo": h["undo"], "undone_at": h["undone_at"],
                    "can_undo": can})
    return out


def _detail(cid):
    from .clients import client_get
    return client_get(cid).get_json()  # the same record as GET /api/clients/<id>


@app.post("/api/clients/merge")
def clients_merge():
    """{target, ids, pick: {field: id}, dry} -> dry: {lines, counts, fields}; else {run_id, target: <GET /api/clients/<id>>}."""
    c = db()
    _gate(c)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    bad = sorted(k for k in b if k not in ("target", "ids", "pick", "dry"))
    if bad:
        raise UnknownFields(bad)
    out = clm_merge(c, me(), b.get("target"), b.get("ids"), b.get("pick"), dry=b.get("dry") is True)
    if "run_id" in out:
        out["target"] = _detail(as_int(b.get("target"), "target", 1))
    return jsonify(out)


@app.post("/api/clients/merges/<int:rid>/undo")
def clients_merge_undo(rid):
    c = db()
    _gate(c)
    out = clm_undo(c, me(), rid)
    d = mg_run(c, rid, "client")
    out["target"] = None if out["target_gone"] else _detail(d["target_id"])
    return jsonify(out)
