"""2.70.0 B (#1357): tidy up contacts -- an agent finds duplicates, the person merges them.

A person asks an agent (POST /api/proposals {agent_id, kind: "merge", book_id}) for one address book they may change. The
job input is only the name, company, e-mail addresses and phone numbers (+ id) of that book's contacts (at most
DUP_MAX_CONTACTS), nothing else (no notes, addresses, birthdays). The agent answers with groups {target_id, ids, reason};
the review dialog shows every group with the contacts as they are NOW (loaded fresh, never from the proposal), the target
can be switched, every group has its own tick. Applying runs ctm_merge (contacts/merge.py, 2.66) per ticked group as the
person and with their rights; contacts that are gone, changed since the request or no longer writable are skipped. Undo
takes every merge of the proposal back with ctm_undo (one step, within MG_UNDO_DAYS); redo merges again. The agent never
reads the contact routes (they stay refused for agents) and never applies anything itself."""
import json
import re

from ..core.i18n import N_, tr
from ..core.db import db
from ..core.access import Denied
from ..accounts.session import me
from ..core.errors import BadInput
from ..contacts.model import _jl, contacts_on, need_book, book_role
from ..contacts.merge import ctm_merge, ctm_undo
from ..core.merges import mg_dumps, mg_run, MG_MAX

DUP_KIND = "merge"
DUP_MAX_CONTACTS = 2000      # contacts of one address book sent in one request
DUP_GROUPS_MAX = 200         # groups in one proposal
DUP_GROUP_MAX = MG_MAX       # contacts in one group (target included), as one merge allows
DUP_REASON_MAX = 300
DUP_ITEMS_MAX, DUP_VALUE_MAX, DUP_NAME_MAX = 10, 200, 200   # e-mails / phones per contact, their length, name fields
DUP_TITLE = N_("Tidy up contacts: {0}")
DUP_FIELDS = ("fn", "given", "family", "org")
DUP_LIMITS = {"contacts_max": DUP_MAX_CONTACTS, "groups_max": DUP_GROUPS_MAX, "group_min": 2, "group_max": DUP_GROUP_MAX,
              "reason_max": DUP_REASON_MAX}


def dup_values(v):
    """The values of a contact's e-mail / phone list (JSON) as plain strings, cut to the limits."""
    out = []
    for it in _jl(v):
        s = (it.get("value") if isinstance(it, dict) else it) or ""
        s = str(s).strip()[:DUP_VALUE_MAX]
        if s and s not in out:
            out.append(s)
    return out[:DUP_ITEMS_MAX]


def dup_brief(r):
    """The fields of one contact the agent gets (and the review compares): id, name parts, company, e-mails, phones."""
    d = {"id": r["id"]}
    for k in DUP_FIELDS:
        d[k] = (r[k] or "")[:DUP_NAME_MAX]
    d["emails"], d["phones"] = dup_values(r["emails"]), dup_values(r["phones"])
    return d


def dup_agent_ok(c, aid, book):
    """The agent may get this book's contacts: never one of another organisation (a private book is the person's own
    choice), never an agent limited to selected lists (contacts are in no list)."""
    a = c.execute("SELECT org_id, list_ids FROM agents WHERE user_id=?", (aid,)).fetchone()
    if not a:
        raise Denied(404)
    if book["org_id"] and book["org_id"] != a["org_id"]:
        raise Denied(403, tr("This address book belongs to another organisation than the agent"))
    if (a["list_ids"] or "").strip():
        raise Denied(403, tr("This agent is limited to selected projects and cannot get contacts"))


def dup_input(c, uid, b):
    """POST /api/proposals {agent_id, kind: merge, book_id} -> (input, title, task_id, list_id) like prop_input."""
    from .proposals import _p_keys, _p_int
    _p_keys(b, "", ("agent_id", "kind", "book_id"))
    if not contacts_on(c, uid):
        raise Denied(404)
    bid = _p_int(b.get("book_id"), "book_id")
    book, _ = need_book(c, bid, write=True, uid=uid)
    if book["src_id"]:
        raise BadInput(tr("Contacts of a synced external address book cannot be merged (they would come back with the next sync)"))
    dup_agent_ok(c, int(b.get("agent_id") or 0), book)
    rows = c.execute("SELECT id, fn, given, family, org, emails, phones FROM contacts WHERE book_id=? AND kind!='group' "
                     "ORDER BY id LIMIT ?", (bid, DUP_MAX_CONTACTS + 1)).fetchall()
    if len(rows) > DUP_MAX_CONTACTS:
        raise BadInput(tr("This address book has more than {0} contacts: split it into smaller address books first", DUP_MAX_CONTACTS))
    if len(rows) < 2:
        raise BadInput(tr("This address book has fewer than two contacts"))
    inp = {"book": {"id": bid, "name": book["name"]}, "contacts": [dup_brief(r) for r in rows], "limits": DUP_LIMITS}
    return inp, tr(DUP_TITLE, (book["name"] or "")[:80]), None, None


def dup_validate(b, inp):
    """prop_validate for kind merge: {summary?, groups: [{target_id, ids, reason?}]} -> {groups: [{target_id, ids (target
    first), reason}]}. Every id from the input, the target in its group, an id in at most one group."""
    from .proposals import _p_keys, _p_list, _p_int, _p_str
    _p_keys(b, "", ("kind", "summary", "groups"))
    known = {x["id"] for x in inp.get("contacts", [])}
    if b.get("groups") is None:
        raise BadInput(tr("Missing field: {0}", "groups"))
    raw = _p_list(b.get("groups"), "groups", DUP_GROUPS_MAX)  # empty = no duplicates found (the person just closes it)
    seen, groups = set(), []
    for i, g in enumerate(raw):
        w = f"groups[{i}]"
        _p_keys(g, w, ("target_id", "ids", "reason"))
        ids = [_p_int(x, w + ".ids") for x in _p_list(g.get("ids"), w + ".ids", DUP_GROUP_MAX)]
        if len(ids) < 2 or len(set(ids)) != len(ids):
            raise BadInput(tr("Invalid value: {0}", w + ".ids"))
        if any(x not in known or x in seen for x in ids):
            raise BadInput(tr("Invalid value: {0}", w + ".ids"))
        t = _p_int(g.get("target_id"), w + ".target_id")
        if t not in ids:
            raise BadInput(tr("Invalid value: {0}", w + ".target_id"))
        seen.update(ids)
        groups.append({"target_id": t, "ids": [t] + [x for x in ids if x != t],
                       "reason": _p_str(g.get("reason"), w + ".reason", DUP_REASON_MAX)})
    return {"groups": groups}


def dup_now(c, uid, inp, ids):
    """The contacts of one group as they are now for person uid: [{id, fn, org, emails, phones, state}] with state ''
    (fine) | gone (deleted, moved, no longer writable) | changed (name, company, e-mails or phones differ from the request)."""
    was = {x["id"]: x for x in inp.get("contacts", [])}
    bid = (inp.get("book") or {}).get("id")
    out = []
    for cid in ids:
        r = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        role = None
        if r is not None and r["book_id"] == bid and r["kind"] != "group":
            role = book_role(c, uid, c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone())
        if r is None or role not in ("owner", "edit"):
            out.append({"id": cid, "fn": "", "org": "", "emails": [], "phones": [], "state": "gone"})
            continue
        d = dup_brief(r)
        d["state"] = "" if d == {**was.get(cid, {}), "id": cid} else "changed"
        out.append({k: d[k] for k in ("id", "fn", "org", "emails", "phones", "state")})
    return out


def dup_groups_now(c, uid, j):
    p, inp = json.loads(j["proposal"] or "null") or {}, json.loads(j["input"] or "{}")
    if not contacts_on(c, uid):
        return [], inp
    return [{"key": str(i), "target_id": g["target_id"], "reason": g.get("reason") or "", "contacts": dup_now(c, uid, inp, g["ids"]),
             } for i, g in enumerate(p.get("groups") or [])], inp


def dup_view_extra(c, j):
    """For the review dialog: every group with its contacts loaded fresh (ok = all of them unchanged and writable). The
    input itself is not sent back (it can be large); the book and the count are enough."""
    if j["user_id"] != me():
        return {}
    groups, inp = dup_groups_now(c, me(), j) if j["proposal"] else ([], json.loads(j["input"] or "{}"))
    for g in groups:
        g["ok"] = all(not x["state"] for x in g["contacts"])
    return {"input": {"book": inp.get("book"), "count": len(inp.get("contacts") or [])}, "dup_groups": groups}


def dup_targets(prop, ed):
    """The edited targets {key: target id} of the apply request (a target must be a contact of its group)."""
    from .proposals import _p_keys, _p_int
    out, groups = {}, prop.get("groups") or []
    for k, e in (ed or {}).items():
        if not re.fullmatch(r"\d{1,3}", str(k)) or int(k) >= len(groups):
            raise BadInput(tr("Invalid value: {0}", "edits"))
        _p_keys(e, f"edits.{k}", ("target_id",))
        if "target_id" in e:
            t = _p_int(e["target_id"], "target_id")
            if t not in groups[int(k)]["ids"]:
                raise BadInput(tr("Invalid value: {0}", "target_id"))
            out[k] = t
    return out


def dup_run(c, j, sel, ed, extra, rec):
    """Applies the ticked groups as the person: one ctm_merge each (their rights, need_contact write); a group with a
    contact gone / changed / not writable, or one the merge refuses, is skipped. rec = the undo record."""
    uid = me()
    prop, inp = json.loads(j["proposal"]), json.loads(j["input"] or "{}")
    groups = prop.get("groups") or []
    targets = dup_targets(prop, ed)
    agent = c.execute("SELECT display_name, username FROM users WHERE id=?", (j["agent_id"],)).fetchone()
    via = {"job": j["id"], "agent_id": j["agent_id"], "agent": (agent["display_name"] or agent["username"]) if agent else ""}
    rec.update(merges=[], skipped=[], edits=ed)
    for k in sorted({k for k in sel if re.fullmatch(r"\d{1,3}", k) and int(k) < len(groups)}, key=int):
        g = groups[int(k)]
        t = targets.get(k, g["target_id"])
        now = dup_now(c, uid, inp, g["ids"])
        name = next((x["fn"] or x["org"] for x in inp.get("contacts", []) if x["id"] == t), "") or "?"  # as the agent knows it
        if any(x["state"] for x in now):
            rec["skipped"].append(name)
            continue
        try:
            with c.savepoint():
                res = ctm_merge(c, uid, t, [x for x in g["ids"] if x != t])
                d = mg_run(c, res["run_id"], "contact")  # the history line of the contact names the agent
                c.execute("UPDATE merge_runs SET summary=? WHERE id=?", (mg_dumps({**(d["summary"] or {}), "proposal": via}), res["run_id"]))
        except (BadInput, Denied):
            rec["skipped"].append(name)
            continue
        rec["merges"].append({"key": k, "run_id": res["run_id"], "target_id": t, "name": name})
    if not rec["merges"]:
        raise Denied(409, tr("Nothing could be merged: the contacts changed since the request or you can no longer change them"))
    return rec


def dup_result(rec):
    return {"merged": len(rec.get("merges") or []), "skipped": len(rec.get("skipped") or []), "skipped_names": (rec.get("skipped") or [])[:8]}


def dup_undo(c, j, rec, back=True):
    """Undo: every merge of the proposal goes back (ctm_undo, newest first; one that cannot is skipped with its reason).
    Redo: the same groups (and targets) are merged again."""
    uid = me()
    if not back:
        r = dup_run(c, j, rec.get("sel") or [], rec.get("edits") or {}, rec.get("extra") or {}, dict(rec, undone=False))
        rec.clear()
        rec.update(r)
        return len(rec["merges"]), rec["skipped"][:8]
    n, skipped = 0, []
    for m in reversed(rec.get("merges") or []):
        try:
            with c.savepoint():
                ctm_undo(c, uid, m["run_id"])
            n += 1
        except (BadInput, Denied) as e:
            skipped.append(f"{m.get('name') or '?'}: {e.text() if isinstance(e, Denied) else e}")
    return n, skipped
