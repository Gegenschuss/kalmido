"""2.66.0 A (#1835): merging duplicate contacts by hand (reversible, core/merges.py).

ctm_merge keeps one contact (the target): per single field the value picked (else the target's, else the first one that
is set), the lists (e-mails, phones, web links, addresses, groups) joined without doubles. Every reference of the other
contacts moves to the target (task links, event attendances, contact person at a client, "stay in touch", the
disposition's bookings, every table a later version points at contacts); a link the target has already is dropped. The
birthday / anniversary tasks of the others go to the trash (like deleting them), then the others are deleted: their
address books' sync state lists them as gone, so a phone removes them on its next CardDAV sync. ctm_undo puts all of it
back (same ids, uid and href) within MG_UNDO_DAYS. The functions take the connection + person (no request) so that an
agent can use them later (#1357); the routes are thin wrappers."""
import json
import re

from flask import jsonify

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, bump, db
from ..core.merges import (mg_cascade_rows, mg_fk_refs, mg_history, mg_mark_undone, mg_reinsert, mg_repoint, mg_run,
                           mg_run_create, mg_undo_cascade, mg_undo_refs, mg_undoable, MG_MAX)
from ..accounts.session import me
from ..core.access import Denied, need_feat
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput
from ..contacts.model import _jl, book_touch, contact_store, contacts_on, need_book, need_contact, ITEMS_MAX

CTM_SINGLE = ("kind", "fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "bday", "anniversary",
              "note", "photo")
CTM_LISTS = ("emails", "phones", "urls", "addresses", "groups")
CTM_NL = ("nl_status", "nl_at", "nl_source")  # the newsletter consent: the target's, else the first contact's that has one
# references without a foreign key: (table, column, where)
CTM_SOFT = (("hub_bookings", "resource_id", "resource_kind='contact'"),)


class _Dry(Exception):
    pass


def ctm_key(k, it):
    """The comparison key of a list entry (doubles are dropped)."""
    if k == "groups":
        return str(it).strip().lower()
    if k == "emails":
        return (it.get("value") or "").strip().lower()
    if k == "phones":
        return re.sub(r"[^\d+]", "", it.get("value") or "")
    if k == "addresses":
        return "|".join(re.sub(r"\s+", " ", str(it.get(f) or "")).strip().lower() for f in ("street", "code", "city", "country"))
    return (it.get("value") or "").strip()


def ctm_join(k, rows):
    """The list k of rows (target first) joined: first occurrence wins, only the first preferred entry keeps pref."""
    out, seen, pref = [], set(), False
    for r in rows:
        for it in _jl(r[k]):
            key = ctm_key(k, it)
            if not key or key in seen:
                continue
            seen.add(key)
            if isinstance(it, dict):
                it = dict(it)
                if it.get("pref"):
                    it["pref"] = not pref
                    pref = True
            out.append(it)
    return out[:ITEMS_MAX]


def ctm_ids(target, ids):
    t = as_int(target, "target", 1)
    if ids is not None and not isinstance(ids, list):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    out = [t]
    for x in (ids or [])[:MG_MAX * 4]:
        x = as_int(x, "ids", 1)
        if x not in out:
            out.append(x)
    if len(out) < 2:
        raise BadInput(tr("Choose at least two contacts"))
    if len(out) > MG_MAX:
        raise BadInput(tr("At most {0} contacts at once", MG_MAX))
    return out


def ctm_load(c, uid, all_ids):
    """The rows of the contacts (all writable for uid, target first) and their address books; refuses mirrors, groups and
    mixing scopes (an organisation's contacts never merge with private ones or another organisation's)."""
    if not contacts_on(c, uid):
        raise Denied(404)
    rows = [need_contact(c, i, write=True, uid=uid)[0] for i in all_ids]
    books = {}
    for r in rows:
        if r["book_id"] not in books:
            books[r["book_id"]] = c.execute("SELECT * FROM books WHERE id=?", (r["book_id"],)).fetchone()
    if any(b["src_id"] for b in books.values()):
        raise BadInput(tr("Contacts of a synced external address book cannot be merged (they would come back with the next sync)"))
    if any(r["kind"] == "group" for r in rows):
        raise BadInput(tr("Groups cannot be merged"))
    if len({books[r["book_id"]]["org_id"] for r in rows}) > 1:
        raise Denied(409, tr("Only contacts of the same organisation (or all of your own address books) can be merged"))
    return rows, books


def ctm_fields(rows, pick):
    """The target's new columns from rows (target first) and pick {field: contact id}."""
    by = {r["id"]: r for r in rows}
    t = rows[0]
    f = {}
    for k in CTM_SINGLE:
        src = by.get(pick.get(k)) if pick.get(k) is not None else None
        if src is not None and not str(src[k] or "").strip():
            src = None
        if src is None:
            src = t if str(t[k] or "").strip() else next((r for r in rows if str(r[k] or "").strip()), t)
        f[k] = src[k]
    for k in CTM_LISTS:
        f[k] = json.dumps(ctm_join(k, rows), ensure_ascii=False)
    if "nl_status" in t.keys() and not t["nl_status"]:
        src = next((r for r in rows if r["nl_status"]), None)
        if src is not None:
            for k in CTM_NL:
                f[k] = src[k]
    return {k: v for k, v in f.items() if v != t[k]}


def ctm_pick(pick, all_ids):
    if pick in (None, ""):
        return {}
    if not isinstance(pick, dict):
        raise BadInput(tr("Invalid value: {0}", "pick"))
    out = {}
    for k, v in pick.items():
        if k not in CTM_SINGLE:
            raise BadInput(tr("Invalid value: {0}", "pick"))
        v = as_int(v, "pick", 1)
        if v not in all_ids:
            raise BadInput(tr("Invalid value: {0}", "pick"))
        out[k] = v
    return out


def ctm_lines(rows, f, refs, occ_names, unfit=0):
    """The overview of a merge (the dialog's step 2) in the person's language."""
    t = rows[0]
    n = {}
    for rec in refs:
        if not rec.get("dup"):  # the doubles a move made are counted with the move already
            n[rec["t"]] = n.get(rec["t"], 0) + len(rec["moved"]) + len(rec["dropped"])
    lines = []
    names = {"contact_tasks": N_("Task links: {0}"), "event_attendees": N_("Event attendances: {0}"),
             "office_client_contacts": N_("Contact person at clients: {0}"), "contact_care": N_("Stay in touch: {0}"),
             "hub_bookings": N_("Bookings in the disposition: {0}")}
    other = 0
    for tb, k in n.items():
        if not k:
            continue
        if tb in names:
            lines.append(tr(names[tb], k))
        else:
            other += k
    if other:
        lines.append(tr("Other references: {0}", other))
    if not lines:
        lines.append(tr("No links"))
    for k, label in (("phones", N_("Phone numbers added: {0}")), ("emails", N_("E-mail addresses added: {0}")),
                     ("addresses", N_("Addresses added: {0}")), ("urls", N_("Web links added: {0}")), ("groups", N_("Groups added: {0}"))):
        if k in f:
            d = len(_jl(f[k])) - len(_jl(t[k]))
            if d > 0:
                lines.append(tr(label, d))
    if unfit:
        lines.append(tr("Contact person links dropped (the address book does not fit the client): {0}", unfit))
    for nm in occ_names:
        lines.append(tr("The birthday or anniversary task of {0} goes to the trash", nm))
    return lines


def ctm_merge(c, uid, target, ids, pick=None, dry=False):
    """Merges the contacts ids into target (see the module). dry: nothing changes, returns {lines, fields}; else
    {run_id, target_id}. The caller commits (the route does)."""
    all_ids = ctm_ids(target, ids)
    pick = ctm_pick(pick, all_ids)
    rows, books = ctm_load(c, uid, all_ids)
    t, others = rows[0], [r["id"] for r in rows[1:]]
    tb = books[t["book_id"]]
    f = ctm_fields(rows, pick)
    out = {}
    try:
        with c.savepoint():
            before = dict(t)
            t_occ = [r[0] for r in c.execute("SELECT kind FROM contact_occ WHERE contact_id=?", (t["id"],)).fetchall()]
            refs = [mg_repoint(c, tb_, col, others, t["id"]) for tb_, col, _ in mg_fk_refs(c, "contacts") if tb_ != "contact_occ"]
            refs += [mg_repoint(c, tb_, col, others, t["id"], where) for tb_, col, where in CTM_SOFT]
            refs = [r for r in refs if r["moved"] or r["dropped"]]
            refs.append(ctm_dedupe_attendees(c, t["id"]))
            unfit = ctm_unfit_clients(c, refs, tb)
            # the others' birthday / anniversary tasks go to the trash (like deleting them), their links come back on undo
            from ..contacts.bulk import bk_occ_drop
            occ = [dict(r) for r in c.execute(f"SELECT * FROM contact_occ WHERE contact_id IN ({','.join('?' * len(others))})",
                                               others).fetchall()]
            live = [r["task_id"] for r in occ if r["task_id"] and
                    c.execute("SELECT 1 FROM tasks WHERE id=? AND deleted_at IS NULL", (r["task_id"],)).fetchone()]
            bk_occ_drop(c, uid, others)
            trashed = [x for x in live if c.execute("SELECT 1 FROM tasks WHERE id=? AND deleted_at IS NOT NULL", (x,)).fetchone()]
            occ_names = [r["fn"] for r in rows[1:] if any(o["contact_id"] == r["id"] and o["task_id"] in trashed for o in occ)]
            cascade = mg_cascade_rows(c, "contacts", others)
            if dry:
                out = {"lines": ctm_lines(rows, f, refs, occ_names, unfit),
                       "fields": {k: (_jl(v) if k in CTM_LISTS else v) for k, v in f.items() if k not in CTM_NL and k != "photo"}}
                raise _Dry()
            c.execute(f"DELETE FROM contacts WHERE id IN ({','.join('?' * len(others))})", others)
            contact_store(c, uid, t["book_id"], f, cid=t["id"])  # search, birthday task of the target, book touched, bumped
            for bid in books:
                book_touch(c, bid)
            counts = {}
            for rec in refs:
                if (rec["moved"] or rec["dropped"]) and not rec.get("dup"):
                    counts[rec["t"]] = counts.get(rec["t"], 0) + len(rec["moved"]) + len(rec["dropped"])
            snap = {"target": before, "after": f, "rows": [dict(r) for r in rows[1:]], "refs": refs, "cascade": cascade, "occ": occ,
                    "trashed": trashed, "t_occ": t_occ}
            summary = {"target_fn": rows[0]["fn"], "merged": [{"id": r["id"], "fn": r["fn"]} for r in rows[1:]], "counts": counts}
            rid = mg_run_create(c, "contact", t["id"], others, uid, snap, summary, org_id=tb["org_id"], book_id=t["book_id"])
            bump(c)
            out = {"run_id": rid, "target_id": t["id"]}
    except _Dry:
        pass
    return out


def ctm_unfit_clients(c, refs, tb):
    """A client's contact person may only link to an address book that fits the client (contacts_cl.ckl_book_fits): a
    moved link that does not fit the target's book is dropped (name, e-mail, phone stay; undo puts it back). Returns the count."""
    from ..office.contacts_cl import ckl_book_fits
    n = 0
    for rec in refs:
        if rec["t"] != "office_client_contacts":
            continue
        for k in rec["moved"]:
            cl = c.execute("SELECT cl.* FROM office_client_contacts k JOIN clients cl ON cl.id=k.client_id WHERE k.id=?", (k["id"],)).fetchone()
            if cl is not None and not ckl_book_fits(cl, tb):
                c.execute("UPDATE office_client_contacts SET contact_id=NULL WHERE id=?", (k["id"],))
                n += 1
    return n


def ctm_dedupe_attendees(c, tid):
    """After the move an event may list the target twice: the extra attendee rows go (kept for undo)."""
    rec = {"t": "event_attendees", "col": "contact_id", "to": tid, "moved": [], "dropped": [], "dup": True}
    rows = [dict(r) for r in c.execute("SELECT * FROM event_attendees WHERE contact_id=? ORDER BY id", (tid,)).fetchall()]
    seen = set()
    for r in rows:
        if r["event_id"] in seen:
            c.execute("DELETE FROM event_attendees WHERE id=?", (r["id"],))
            rec["dropped"].append(r)
        seen.add(r["event_id"])
    return rec


def ctm_undo(c, uid, rid):
    """Undoes the merge rid: the merged contacts come back with their old ids, uid and href, the references move back, the
    target gets its columns from before (each one only while it still has the merged value). The caller commits.
    Returns {ok, target_id (None when the target is gone), restored: [ids]}."""
    rid = as_int(rid, "run_id", 1)
    if not contacts_on(c, uid):
        raise Denied(404)
    d = mg_run(c, rid, "contact")
    if not d:
        raise Denied(404)
    snap = d["snapshot"] or {}
    t = c.execute("SELECT * FROM contacts WHERE id=?", (d["target_id"],)).fetchone()
    # rights: the target while it exists + every address book the merged contacts come back to; nothing checked = 404
    # (a run of someone else's address book looks like an unknown one)
    rbids = sorted({r["book_id"] for r in snap.get("rows") or []})
    bids, checked, missing = [], False, False
    if t is not None:
        need_contact(c, t["id"], write=True, uid=uid)
        checked = True
    for bid in rbids + ([d["book_id"]] if d["book_id"] and t is None and d["book_id"] not in rbids else []):
        if not c.execute("SELECT 1 FROM books WHERE id=?", (bid,)).fetchone():
            missing = missing or bid in rbids
            continue
        need_book(c, bid, write=True, uid=uid)
        bids.append(bid)
        checked = True
    if not checked:
        raise Denied(404)
    if missing:
        raise Denied(409, tr("The address book of a merged contact no longer exists"))
    why = mg_undoable(d)
    if why == "undone":
        raise Denied(409, tr("This merge was undone already"))
    if why:
        raise Denied(409, tr("This merge is older than {0} days and cannot be undone any more", 30))
    rows = snap.get("rows") or []
    for r in rows:
        if c.execute("SELECT 1 FROM contacts WHERE id=?", (r["id"],)).fetchone():
            raise Denied(409, tr("This merge was undone already"))
        if c.execute("SELECT 1 FROM contacts WHERE book_id=? AND (uid=? OR href=?)", (r["book_id"], r["uid"], r["href"])).fetchone():
            raise Denied(409, tr("The address book has this contact already"))
    for r in rows:
        mg_reinsert(c, "contacts", r)
    mg_undo_cascade(c, snap.get("cascade"))
    mg_undo_refs(c, snap.get("refs"))
    from ..tasks.lifecycle import restore_task, trash_task
    for o in snap.get("occ") or []:
        mg_reinsert(c, "contact_occ", o)
    for x in snap.get("trashed") or []:
        if c.execute("SELECT 1 FROM tasks WHERE id=? AND deleted_at IS NOT NULL", (x,)).fetchone():
            restore_task(c, x)
    if t is not None:
        before, after = snap.get("target") or {}, snap.get("after") or {}
        f = {k: before[k] for k, v in after.items() if k in before and t[k] == v}
        # a birthday / anniversary task the merge made for the target goes again when its date goes back to empty
        keep = set(snap.get("t_occ") or [])
        for o in c.execute("SELECT kind, task_id FROM contact_occ WHERE contact_id=?", (t["id"],)).fetchall():
            col = "bday" if o["kind"] == "birthday" else "anniversary"
            if o["kind"] in keep or col not in f or f[col]:
                continue
            if o["task_id"] and c.execute("SELECT 1 FROM tasks WHERE id=? AND deleted_at IS NULL", (o["task_id"],)).fetchone():
                trash_task(c, o["task_id"])
            c.execute("DELETE FROM contact_occ WHERE contact_id=? AND kind=?", (t["id"], o["kind"]))
        contact_store(c, uid, t["book_id"], f, cid=t["id"])
    for bid in bids:
        book_touch(c, bid)
    mg_mark_undone(c, rid, uid)
    bump(c)
    return {"ok": True, "target_id": t["id"] if t is not None else None, "restored": [r["id"] for r in rows]}


def ctm_history(c, cid):
    """The merges into contact cid for its card (the caller checked the right to change it)."""
    return mg_history(c, "contact", cid)


@app.post("/api/contacts/merge")
def contacts_merge():
    need_feat("contacts")
    from ..contacts.web import op_contact
    c, uid, b = db(), me(), body()
    res = ctm_merge(c, uid, b.get("target"), b.get("ids"), b.get("pick"), bool(b.get("dry")))
    if b.get("dry"):
        return jsonify(res)
    c.commit()
    return jsonify(run_id=res["run_id"], target=op_contact(c, uid, res["target_id"]))


@app.post("/api/contacts/merges/<int:rid>/undo")
def contacts_merge_undo(rid):
    need_feat("contacts")
    from ..contacts.web import op_contact
    c, uid = db(), me()
    res = ctm_undo(c, uid, rid)
    c.commit()
    return jsonify(ok=True, target=op_contact(c, uid, res["target_id"]) if res["target_id"] else None, restored=res["restored"],
                   note="" if res["target_id"] else tr("The contact the others were merged into no longer exists; the merged contacts are back"))
