"""Clients: several at once (2.47.3, #1733). One request deletes, archives, restores or changes a selection of clients
(Office > Clients, the selection mode). Every id is checked first (one the person does not see -> 404, nothing changes).
delete: a client that is in use (quotations / invoices, framework contracts, archived legacy documents) is archived
instead, like the master data of the office (office_delete); the others are deleted like a single DELETE (their lists
lose the client) -- only by their creator or an admin, the rest is skipped and counted. set: hourly rate, budget (hours /
amount), colour, a note appended; restore: puts back the values set / archive answered with (the client's undo step)."""
from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput, UnknownFields
from .clients import CLIENT_TEXT_MAX, _gate, clean_client, client_rows, cl_may_delete

MS_CL_MAX = 1000  # clients in one request
MS_CL_SET = ("rate", "budget_h", "budget_amount", "color", "note_append")
MS_CL_RESTORE = ("rate", "budget_h", "budget_amount", "color", "note", "archived")


def ms_client_in_use(c, cid):
    """A client quotations / invoices, framework contracts or archived documents point to (they would lose it)."""
    from ..core.pg import system_ctx
    # system: only a yes / no across the workspaces (a document of another workspace may point to it), no content
    with system_ctx(c):
        return any(c.execute(f"SELECT 1 FROM {t} WHERE client_id=? LIMIT 1", (cid,)).fetchone()
                   for t in ("office_docs", "office_contracts", "office_archive"))


def ms_cl_ids(b, k="ids"):
    ids = b.get(k)
    if not isinstance(ids, list) or not ids:
        raise BadInput(tr("Choose at least one client"))
    if len(ids) > MS_CL_MAX:
        raise BadInput(tr("At most {0} clients at once", MS_CL_MAX))
    return list(dict.fromkeys(as_int(x, k, 1) for x in ids))


def ms_cl_set(c, uid, b):
    """The validated columns of action set (only the keys given; null / "" clears rate, budget and colour)."""
    f = clean_client(c, uid, {k: b[k] for k in ("rate", "budget_h", "budget_amount", "color") if k in b})
    if b.get("note_append") is not None:
        if not isinstance(b["note_append"], str):
            raise BadInput(tr("Invalid value: {0}", "note_append"))
        v = b["note_append"].replace("\x00", "").strip()
        if v:
            f["note_append"] = v
    if not f:
        raise BadInput(tr("Nothing to change"))
    return f


def ms_clients_bulk(c, uid, b):
    """{ids, action: delete | archive | unarchive | set | restore, ...} -> {action, deleted, archived, changed, unchanged,
    skipped, undo: [{id, <old values>}]} (the counts of the action)."""
    bad = sorted(k for k in b if k not in ("ids", "action", "items", *MS_CL_SET))
    if bad:
        raise UnknownFields(bad)
    action = b.get("action")
    if action not in ("delete", "archive", "unarchive", "set", "restore"):
        raise BadInput(tr("Invalid value: {0}", "action"))
    if action == "restore":
        items = b.get("items")
        if not isinstance(items, list) or not items or len(items) > MS_CL_MAX or any(not isinstance(x, dict) for x in items):
            raise BadInput(tr("Invalid value: {0}", "items"))
        ids = ms_cl_ids({"ids": [x.get("id") for x in items]})
        if len(ids) != len(items) or any(k not in ("id", *MS_CL_RESTORE) for x in items for k in x):
            raise BadInput(tr("Invalid value: {0}", "items"))
    else:
        ids = ms_cl_ids(b)
    seen = {r["id"]: r for r in client_rows(c, uid)}
    if any(i not in seen for i in ids):
        raise Denied(404)
    ts = iso(now_utc())
    out = {"action": action}
    if action == "delete":
        dl, ar, sk = [], [], 0
        for i in ids:
            r = seen[i]
            if not cl_may_delete(c, uid, r):  # 2.148.1 B (#2484): the creator or an admin of its organisation
                sk += 1
            elif ms_client_in_use(c, i):
                if not r["archived"]:
                    c.execute("UPDATE clients SET archived=1, updated_at=? WHERE id=?", (ts, i))
                ar.append(i)
            else:
                c.execute("UPDATE lists SET client_id=NULL WHERE client_id=?", (i,))
                c.execute("DELETE FROM clients WHERE id=?", (i,))
                dl.append(i)
        out.update(deleted=len(dl), archived=len(ar), skipped=sk, undo=[{"id": i, "archived": bool(seen[i]["archived"])} for i in ar])
    elif action in ("archive", "unarchive"):
        v = 1 if action == "archive" else 0
        ch = [i for i in ids if seen[i]["archived"] != v]
        for i in ch:
            c.execute("UPDATE clients SET archived=?, updated_at=? WHERE id=?", (v, ts, i))
        out.update(changed=len(ch), unchanged=len(ids) - len(ch), undo=[{"id": i, "archived": not v} for i in ch])
    elif action == "set":
        f = ms_cl_set(c, uid, b)
        undo = []
        for i in ids:
            r = seen[i]
            new = {k: v for k, v in f.items() if k != "note_append" and r[k] != v}
            if "note_append" in f:
                n = ((r["note"].rstrip() + "\n\n" if (r["note"] or "").strip() else "") + f["note_append"])[:CLIENT_TEXT_MAX["note"]]
                if n != r["note"]:
                    new["note"] = n
            if new:
                undo.append({"id": i, **{k: r[k] for k in new}})
                c.execute(f"UPDATE clients SET {','.join(k + '=?' for k in new)}, updated_at=? WHERE id=?", [*new.values(), ts, i])
        out.update(changed=len(undo), unchanged=len(ids) - len(undo), undo=undo)
    else:
        n = 0
        for x in items:
            f = clean_client(c, uid, {k: v for k, v in x.items() if k != "id"})
            if f:
                c.execute(f"UPDATE clients SET {','.join(k + '=?' for k in f)}, updated_at=? WHERE id=?", [*f.values(), ts, as_int(x["id"], "id", 1)])
                n += 1
        out.update(changed=n)
    bump(c)
    c.commit()
    return out


@app.post("/api/clients/bulk")
def clients_bulk():
    c = db()
    _gate(c)
    return jsonify(ms_clients_bulk(c, me(), body()))
