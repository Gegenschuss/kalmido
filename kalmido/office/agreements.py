"""2.92.0 A (#1925): business contracts and insurances of an office area (insurance, rent, leasing, service provider, other).

One row per contract (office_agreements): provider, number, contribution (cost per month | quarter | year, net when a VAT
rate is set), the current term (ends) with notice period and automatic renewal (renew_months, 0 = it simply ends), the
contract document (a document of the office's documents space: 'o<org>' or, for a personal office, its owner's 'u<id>'),
a note. Cost, number and note are encrypted at rest (orgcrypt FIELDS).

The deadline logic is the one of the family contracts (life/model.py, imported): the last day to cancel = end of the term
minus the notice period; when it has passed and the contract renews, the term rolls on. "Deadline as a task" (default on)
keeps ONE task in a list the admin may write (default: their inbox) with the same fam as a family contract (kind contract,
plus office_agreement: <id>), so the agent "contracts in view" (agents/contractprop.py, #1359) reminds of it with the event
contract_notice -- only agents that may see that list. The task follows changes; archiving / deleting the contract ends it
(repeat removed, done; never deleted).

Contributions with cashflow=1 count in the cash flow (office/cashflow.py rk_cashflow, kind "agreement") like a fixed cost,
and show as read-only rows "from contracts" in the fixed costs list (no copy, no double booking).

Every route: office_gate + office_org(admin=True): only the admins of the office area (a personal office: its person);
agents and kids 403, ids of another office area 404. Deleting is soft (archived=2) so the undo can restore it."""
import json
import re
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from flask import jsonify, request

from ..core.config import PUBLIC_URL, app
from ..core.db import body, bump, db, iso, local_now, now_utc, write_lock
from ..core.retention import ret_on, ret_report, ret_trash_cut  # 2.272.0 F (#3026, review M4)
from ..core.i18n import N_, lang, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import insert_id
from ..core.access import Denied, my_inbox, need_list, wr_sql
from ..core.errors import BadInput
from ..files.fsref import fs_ref_rename
from .calc import dec, dstr, money
from .model import office_gate, office_org, pb_owner

AGR_KINDS = ("insurance", "rent", "leasing", "service", "other")
AGR_PERS = ("month", "quarter", "year")
AGR_PER_MONTHS = {"month": 1, "quarter": 3, "year": 12}
AGR_REPEAT = {"month": "monthly", "quarter": "quarterly", "year": "yearly"}  # cashflow.rk_fixed_days
AGR_UNITS = ("d", "w", "m")
AGR_VATS = ("19", "7", "0")
AGR_DELETED = 2  # archived=2: deleted (restorable through the undo; purged after AGR_PURGE_DAYS)
AGR_PURGE_DAYS = 30
MAX_AGR = 500
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AGR_TASK_TITLE = N_("Cancel or renew the contract: {0}")
AGR_COLS = ("kind", "name", "provider", "number", "cost", "per", "vat_pct", "start", "ends", "notice", "notice_unit", "renew_months",
            "lead_days", "doc_node_id", "cashflow", "note")


from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def _txt(v, what, n, need=False):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", what))
    v = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", v).strip()
    if need and not v:
        raise BadInput(tr("Please enter a name"))
    return v[:n]


def _int(v, what, lo, hi):
    from ..tasks.validation import as_int
    return as_int(v, what, lo, hi)


def _day(v, what):
    if v in (None, ""):
        return ""
    if isinstance(v, str) and DATE_RE.match(v.strip()):
        try:
            d = date.fromisoformat(v.strip())
            if 1900 <= d.year <= 2200:  # 2.92.0 review: bounded, the term / cash flow loops step through the years
                return d.isoformat()
        except ValueError:
            pass
    raise BadInput(tr("Invalid value: {0}", what))


def bk_doc(c, oid, uid, nid):
    """The document nid of the office's documents space uid can see -> {id, name} or None."""
    from ..files.store import fs_visible_sql
    if not nid:
        return None
    r = c.execute(f"SELECT n.id, n.name, n.org_id, n.owner_id FROM fs_nodes n JOIN doc_meta d ON d.node_id=n.id "
                  f"WHERE n.id=? AND n.deleted_at IS NULL AND n.id IN {fs_visible_sql(uid, c)}", (nid,)).fetchone()
    if not r:
        return None
    owner = pb_owner(c, oid)
    ok = (r["org_id"] is None and r["owner_id"] == owner) if owner is not None else r["org_id"] == oid
    return {"id": r["id"], "name": r["name"]} if ok else None


def bk_clean(c, oid, uid, b, cur=None):
    """The columns of a contract from body b (partial when cur is given)."""
    cur = cur or {}
    out = {}
    new = not cur
    if "kind" in b or new:
        k = b.get("kind") or "insurance"
        if k not in AGR_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        out["kind"] = k
    if "name" in b or new:
        out["name"] = _txt(b.get("name"), "name", 200, need=True)
    for f, n in (("provider", 200), ("number", 100), ("note", 2000)):
        if f in b or new:
            out[f] = _txt(b.get(f), f, n)
    if "cost" in b or new:
        v = b.get("cost")
        if v in (None, ""):
            out["cost"] = ""
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                raise BadInput(tr("Invalid value: {0}", "cost"))
            a = dec(str(v).strip().replace(",", ".") if isinstance(v, str) else v, "NaN")
            if a.is_nan() or not a.is_finite() or a < 0 or a > 10 ** 9:
                raise BadInput(tr("Invalid value: {0}", "cost"))
            out["cost"] = dstr(money(a))
    if "per" in b or new:
        p = b.get("per") or "month"
        if p not in AGR_PERS:
            raise BadInput(tr("Invalid value: {0}", "per"))
        out["per"] = p
    if "vat_pct" in b or new:
        v = b.get("vat_pct")
        v = None if v in (None, "") or isinstance(v, bool) else str(v)
        if v is not None and v not in AGR_VATS:
            raise BadInput(tr("Invalid value: {0}", "vat_pct"))
        out["vat_pct"] = v
    for f in ("start", "ends"):
        if f in b or new:
            out[f] = _day(b.get(f), f)
    if "notice" in b or new:
        out["notice"] = _int(b.get("notice") or 0, "notice", 0, 365)
    if "notice_unit" in b or new:
        u = b.get("notice_unit") or "m"
        if u not in AGR_UNITS:
            raise BadInput(tr("Invalid value: {0}", "notice_unit"))
        out["notice_unit"] = u
    if "renew_months" in b or new:
        v = b.get("renew_months", 12)
        out["renew_months"] = _int(12 if v in (None, "") else v, "renew_months", 0, 120)
    if "lead_days" in b or new:
        v = b.get("lead_days", 30)
        out["lead_days"] = _int(30 if v in (None, "") else v, "lead_days", 0, 365)
    if "cashflow" in b or new:
        v = b.get("cashflow", 1)
        if v not in (0, 1, True, False, "0", "1"):
            raise BadInput(tr("Invalid value: {0}", "cashflow"))
        out["cashflow"] = 1 if v in (1, True, "1") else 0
    if "doc_node_id" in b:
        v = b.get("doc_node_id")
        if v in (None, "", 0):
            out["doc_node_id"] = None
        else:
            v = _int(v, "doc_node_id", 1, None)
            if v != cur.get("doc_node_id") and not bk_doc(c, oid, uid, v):
                raise Denied(404)
            out["doc_node_id"] = v
    st, en = out.get("start", cur.get("start")), out.get("ends", cur.get("ends"))
    if st and en and en < st:
        raise BadInput(tr("The end is before the start"))
    return out


# ---------------------------------------------------------------- deadline (the family contracts' logic)
def bk_deadline(r, today=None, floor=None):
    """{cancel_by, ends, days, warn, over} of contract r (decrypted dict) or None without an end of term. When the last day
    to cancel has passed and the contract renews, the term rolls on (like life/model.py contract_create); floor (ISO, the
    open deadline task's due after "renewed" there) rolls it on up to that day."""
    from ..life.model import notice_delta
    if not r.get("ends"):
        return None
    today = today or local_now().date()
    end = date.fromisoformat(r["ends"])
    nd = notice_delta(int(r.get("notice") or 0), r.get("notice_unit") or "m")
    renew = int(r.get("renew_months") or 0)
    due = end - nd
    lim = date.fromisoformat(floor) if floor else today
    lim = max(lim, today)
    n = 0
    while renew and due < lim and n < 2400:
        end += relativedelta(months=renew)
        due = end - nd
        n += 1
    days = (due - today).days
    return {"cancel_by": due.isoformat(), "ends": end.isoformat(), "days": days, "warn": 0 <= days <= int(r.get("lead_days") or 0),
            "over": days < 0}


def bk_monthly(r):
    """The contribution per month (as entered, net when a VAT rate is set) or None."""
    if r.get("cost") in (None, ""):
        return None
    return money(dec(r["cost"]) / AGR_PER_MONTHS.get(r.get("per") or "month", 1))


def bk_gross(r):
    return money(dec(r.get("cost") or 0) * (100 + int(r.get("vat_pct") or 0)) / 100)


# ---------------------------------------------------------------- the deadline task
def bk_task_row(c, aid, tid):
    """The task tid made for contract aid (its fam says so), else None: a stored id never reaches another task."""
    if not tid:
        return None
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t:
        return None
    try:
        f = json.loads(t["fam"] or "{}")
    except ValueError:
        return None
    return t if isinstance(f, dict) and f.get("kind") == "contract" and f.get("office_agreement") == aid else None


def bk_task_end(c, aid, tid):
    """Ends the deadline task: the repeat removed and done (never deleted)."""
    from ..tasks.validation import log_act
    t = bk_task_row(c, aid, tid)
    if not t or t["status"] != 0 or t["deleted_at"]:
        return
    ts = iso(now_utc())
    c.execute("UPDATE tasks SET repeat='', status=2, completed_at=?, updated_at=? WHERE id=? AND status=0", (ts, ts, tid))
    log_act(c, tid, "complete")


def bk_task_fields(c, uid, r, dl):
    from ..life.model import _reminders, renew_rule
    from ..tasks.validation import rr_problem
    lead = int(r.get("lead_days") or 0)
    rep = renew_rule(int(r.get("renew_months") or 0))
    if rep and rr_problem(rep):
        rep = ""
    fam = {"kind": "contract", "name": (r.get("name") or "")[:100], "provider": (r.get("provider") or "")[:100], "per": r.get("per") or "month",
           "notice": int(r.get("notice") or 0), "nu": r.get("notice_unit") or "m", "lead": lead, "office_agreement": r["id"]}
    if r.get("cost") not in (None, ""):
        fam["cost"] = round(float(bk_gross(r)), 2)
    if r.get("start"):
        fam["start"] = r["start"]
    return {"title": tr(AGR_TASK_TITLE, r.get("name") or "", lg=lang(c, uid)), "due": dl["cancel_by"], "reminders": _reminders(lead),
            "repeat": rep, "fam": fam}


def bk_task_list(c, uid, lid, oid=None):
    """The list for a new deadline task: lid (one the person may write, never a locked one) or their inbox. 2.92.0 review:
    only a private list or one of the office's own organisation (the contract never goes into another organisation)."""
    if lid in (None, "", 0):
        return my_inbox(c, uid)
    lid = _int(lid, "list_id", 1, None)
    need_list(c, lid)
    if oid is not None and c.execute("SELECT 1 FROM lists WHERE id=? AND org_id IS NOT NULL AND org_id<>?", (lid, oid)).fetchone():
        raise BadInput(tr("Invalid value: {0}", "list_id"))
    from ..collab.liste2e import le2a_gen_refuse
    le2a_gen_refuse(c, lid)
    if c.execute("SELECT 1 FROM lists WHERE id=? AND life IN ('health', 'budget')", (lid,)).fetchone():
        raise BadInput(tr("Invalid value: {0}", "list_id"))
    return lid


def bk_task_sync(c, oid, uid, r, want=None, lid=None, revive=False, new_end=False):
    """Keeps the deadline task of contract r (decrypted dict with id) in step. want: True (on) / False (off) / None (as
    it is: on when it has a task). revive: a task ended by archiving / deleting comes back (restore, unarchive). new_end:
    the end of term was just entered (the task's due is no floor then). Returns the task id to store (None = no task)."""
    from ..life.model import _insert
    tid = r.get("task_id")
    t = bk_task_row(c, r["id"], tid)
    on = bool(tid) if want is None else bool(want)
    if not on or r.get("archived"):
        if t:
            bk_task_end(c, r["id"], tid)
        return tid if on and t else None
    floor = t["due"] if t and t["status"] == 0 and not t["deleted_at"] and t["due"] and not new_end else None
    dl = bk_deadline(r, floor=floor)
    if not dl or (dl["over"] and not t):
        return tid if t else None  # no end of term / its last chance is gone: nothing to remind of
    f = bk_task_fields(c, uid, r, dl)
    if t and not t["deleted_at"] and (t["status"] == 0 or not revive):
        from ..core.access import wr_sql
        from ..tasks.validation import log_changes
        if not c.execute(f"SELECT 1 FROM lists WHERE id=? AND id IN {wr_sql()}", (t["list_id"], uid, uid)).fetchone():
            return t["id"]  # 2.92.0 review: another admin's list this one may not change - the task stays as it is
        sets = {"title": f["title"][:500], "due": f["due"], "reminders": f["reminders"], "fam": json.dumps(f["fam"], ensure_ascii=False, separators=(",", ":"))}
        if t["status"] == 0:
            sets["repeat"] = f["repeat"]
        if lid not in (None, "", 0) and int(lid) != t["list_id"]:
            sets["list_id"] = bk_task_list(c, uid, lid, oid)
        if any(str(t[k] or "") != str(v or "") for k, v in sets.items()):
            sets["updated_at"] = iso(now_utc())
            c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in sets)} WHERE id=?", list(sets.values()) + [t["id"]])
            log_changes(c, t["id"], t)
        return t["id"]
    target = bk_task_list(c, uid, lid, oid)
    content = PUBLIC_URL.rstrip("/") + f"/#office/agreements/{r['id']}"
    return _insert(c, uid, target, f["title"], f["due"], rem=f["reminders"], rep=f["repeat"], fam=f["fam"], deadline=2, prio=3, content=content)


# ---------------------------------------------------------------- read
def bk_dec(c, oid, row):
    d = oc_dec_fields(c, oid, "office_agreements", row)
    return {k: d.get(k) for k in row.keys()}


def bk_public(c, oid, uid, row, today=None):
    r = bk_dec(c, oid, row)
    out = {k: r.get(k) for k in ("id",) + AGR_COLS + ("task_id", "archived", "created_at", "updated_at")}
    out["cashflow"] = int(out["cashflow"] or 0)
    out["archived"] = int(out["archived"] or 0)
    t = bk_task_row(c, r["id"], r.get("task_id"))
    task = None
    if t and not t["deleted_at"]:
        ln = c.execute("SELECT name FROM lists WHERE id=?", (t["list_id"],)).fetchone()
        task = {"id": t["id"], "list_id": t["list_id"], "list": ln[0] if ln else "", "due": t["due"], "done": t["status"] != 0}
    out["task"] = task
    floor = t["due"] if task and not task["done"] else None
    out["deadline"] = bk_deadline(r, today=today, floor=floor)
    m = bk_monthly(r)
    out["monthly"] = dstr(m) if m is not None else None
    out["gross"] = dstr(bk_gross(r)) if r.get("cost") not in (None, "") else None
    out["doc"] = bk_doc(c, oid, uid, r.get("doc_node_id"))
    try:
        from . import assets
        cov = getattr(assets, "ast_covered", None)
        out["covered"] = cov(c, oid, r["id"]) if cov else None
    except Exception:  # part B not there / failing: nothing shown
        out["covered"] = None
    return out


def _row(c, oid, aid, deleted=False):
    r = c.execute("SELECT * FROM office_agreements WHERE id=? AND org_id=?", (aid, oid)).fetchone()
    if not r or (not deleted and r["archived"] == AGR_DELETED):
        raise Denied(404)
    return r


def agr_list(c, oid, kind=None):
    """For part B (#1931, the policy of a device): [{id, kind, name, provider, number, archived}] without amounts."""
    q, args = "SELECT * FROM office_agreements WHERE org_id=? AND archived<>?", [oid, AGR_DELETED]
    if kind:
        q += " AND kind=?"
        args.append(kind)
    out = []
    for row in c.execute(q + " ORDER BY lower(name), id", args).fetchall():
        r = oc_dec_fields(c, oid, "office_agreements", row)
        out.append({"id": row["id"], "kind": row["kind"], "name": row["name"], "provider": row["provider"], "number": r.get("number") or "",
                    "archived": int(row["archived"] or 0)})
    return out


def agr_exists(c, oid, aid):
    return bool(aid) and c.execute("SELECT 1 FROM office_agreements WHERE id=? AND org_id=? AND archived<>?", (aid, oid, AGR_DELETED)).fetchone() is not None


def agr_cashflow_items(c, oid, today=None):
    """The contributions in the cash flow, as fixed costs for cashflow.rk_fixed_days: [{id, label, kind, amount (net or as
    entered), gross, vat_rate, repeat, start, until}]. Active contracts with cashflow on and a cost above 0; from the start
    (else the start of the current term, else today) every period; until the end of the term only when it does not renew."""
    today = today or local_now().date().isoformat()
    out = []
    for row in c.execute("SELECT * FROM office_agreements WHERE org_id=? AND archived=0 AND cashflow=1 ORDER BY lower(name), id", (oid,)).fetchall():
        r = bk_dec(c, oid, row)
        if r.get("cost") in (None, "") or dec(r["cost"]) <= 0:
            continue
        renew = int(r.get("renew_months") or 0)
        st = r.get("start") or ""
        if not st and r.get("ends"):
            d = date.fromisoformat(r["ends"]) + timedelta(days=1)
            step = relativedelta(months=renew or 12)
            while d.isoformat() > today:
                d -= step
            st = d.isoformat()
        out.append({"id": r["id"], "label": r.get("name") or "", "kind": r.get("kind"), "amount": dstr(money(dec(r["cost"]))), "gross": dstr(bk_gross(r)),
                    "vat_rate": int(r.get("vat_pct") or 0), "repeat": AGR_REPEAT.get(r.get("per") or "month", "monthly"), "start": st or today,
                    "until": r.get("ends") if not renew else "", "category": ""})
    return out


def _lists(c, uid, oid=None):
    """The lists a deadline task can go to (the person may write them; never health / budget / locked lists)."""
    inbox = my_inbox(c, uid)
    rows = c.execute(f"SELECT id, name FROM lists WHERE archived=0 AND e2e IS NULL AND COALESCE(life, '') NOT IN ('health', 'budget') "
                     f"AND (org_id IS NULL OR org_id=?) AND id IN {wr_sql()} ORDER BY id<>?, lower(name), id", (oid or 0, uid, uid, inbox)).fetchall()
    return [{"id": r["id"], "name": r["name"], "inbox": r["id"] == inbox} for r in rows]


@app.get("/api/office/agreements")
def agr_get_all():
    """Office admin. ?archived=1 also the archived ones -> {items, doc_ws (the documents space for the picker / upload:
    private | org:<id>), lists (where the deadline task can go), currency}."""
    c, uid, oid = _ctx()
    n = c.execute("DELETE FROM office_agreements WHERE org_id=? AND archived=? AND updated_at<?",
                  (oid, AGR_DELETED, ret_trash_cut())).rowcount if ret_on("trash") else 0
    if n:
        ret_report(c, "trash", {"agreements": n}, True, run="agreements")
        c.commit()
    arch = request.args.get("archived") == "1"
    rows = c.execute("SELECT * FROM office_agreements WHERE org_id=? AND archived<>? AND (archived=0 OR ?=1) ORDER BY lower(name), id",
                     (oid, AGR_DELETED, 1 if arch else 0)).fetchall()
    today = local_now().date()
    from .model import office_settings
    return jsonify(items=[bk_public(c, oid, uid, r, today) for r in rows], doc_ws="private" if pb_owner(c, oid) is not None else f"org:{oid}",
                   lists=_lists(c, uid, oid), currency=(office_settings(c, oid).get("currency") or "EUR").upper())


@app.get("/api/office/agreements/<int:aid>")
def agr_get(aid):
    c, uid, oid = _ctx()
    return jsonify(bk_public(c, oid, uid, _row(c, oid, aid)))


def _save_task(c, oid, uid, aid, b, revive=False, new_end=False):
    want = None
    if "task" in b:
        v = b.get("task")
        if v not in (0, 1, True, False, "0", "1"):
            raise BadInput(tr("Invalid value: {0}", "task"))
        want = v in (1, True, "1")
    r = bk_dec(c, oid, _row(c, oid, aid))
    tid = bk_task_sync(c, oid, uid, r, want=want, lid=b.get("list_id"), revive=revive, new_end=new_end)
    if tid != r.get("task_id"):
        c.execute("UPDATE office_agreements SET task_id=? WHERE id=? AND org_id=?", (tid, aid, oid))


@app.post("/api/office/agreements")
def agr_post():
    """Office admin. {kind, name, provider?, number?, cost?, per?, vat_pct?, start?, ends?, notice?, notice_unit?,
    renew_months? (12), lead_days? (30), cashflow? (1), doc_node_id?, note?, task? (1: the deadline task), list_id?} -> 201."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    write_lock(c, f"office_agr_{int(oid)}")
    if c.execute("SELECT COUNT(*) FROM office_agreements WHERE org_id=? AND archived<>?", (oid, AGR_DELETED)).fetchone()[0] >= MAX_AGR:
        raise BadInput(tr("Too many entries"))
    row = bk_clean(c, oid, uid, b)
    if row.get("ends") and row.get("renew_months"):
        dl = bk_deadline(row)
        row["ends"] = dl["ends"]  # a term whose last day to cancel has passed rolls on (stored as the current term)
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts, archived=0)
    row = oc_enc_fields(c, oid, "office_agreements", row)
    aid = insert_id(c, f"INSERT INTO office_agreements({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    _save_task(c, oid, uid, aid, {"task": b.get("task", 1), "list_id": b.get("list_id")})
    bump(c)
    c.commit()
    return jsonify(bk_public(c, oid, uid, _row(c, oid, aid))), 201


@app.patch("/api/office/agreements/<int:aid>")
def agr_patch(aid):
    """Office admin. Any field of POST, archived 0|1, task 0|1, list_id -> the contract. The deadline task follows."""
    c, uid, oid = _ctx()
    cur = bk_dec(c, oid, _row(c, oid, aid))
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = bk_clean(c, oid, uid, b, cur)
    revive = False
    if "archived" in b:
        v = b.get("archived")
        if v not in (0, 1, True, False, "0", "1"):
            raise BadInput(tr("Invalid value: {0}", "archived"))
        row["archived"] = 1 if v in (1, True, "1") else 0
        revive = cur.get("archived") and not row["archived"]
    if "ends" in row and row["ends"] and int(row.get("renew_months", cur.get("renew_months")) or 0):
        row["ends"] = bk_deadline({**cur, **row})["ends"]
    if row:
        row["updated_at"] = iso(now_utc())
        enc = oc_enc_fields(c, oid, "office_agreements", row)
        c.execute(f"UPDATE office_agreements SET {','.join(k + '=?' for k in enc)} WHERE id=? AND org_id=?", list(enc.values()) + [aid, oid])
        if row.get("name"):
            fs_ref_rename(c, "office_agreement", aid, row["name"])  # 2.351.0 B (#2749): the name on its folder node (office/agrref.py)
    _save_task(c, oid, uid, aid, b, revive=revive, new_end="ends" in row and row["ends"] != cur.get("ends"))
    bump(c)
    c.commit()
    return jsonify(bk_public(c, oid, uid, _row(c, oid, aid)))


@app.delete("/api/office/agreements/<int:aid>")
def agr_delete(aid):
    """Office admin. Deletes softly (restorable through POST .../restore, purged after 30 days); the deadline task ends."""
    c, uid, oid = _ctx()
    r = bk_dec(c, oid, _row(c, oid, aid))
    bk_task_end(c, aid, r.get("task_id"))
    c.execute("UPDATE office_agreements SET archived=?, updated_at=? WHERE id=? AND org_id=?", (AGR_DELETED, iso(now_utc()), aid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, id=aid, archived=int(r.get("archived") or 0))


@app.post("/api/office/agreements/<int:aid>/restore")
def agr_restore(aid):
    """Office admin. {archived?: 0|1 (as it was)} brings a deleted contract back; its deadline task comes back too."""
    c, uid, oid = _ctx()
    row = _row(c, oid, aid, deleted=True)
    if row["archived"] != AGR_DELETED:
        raise Denied(409)
    b = body()
    arch = 1 if isinstance(b, dict) and b.get("archived") in (1, True, "1") else 0
    c.execute("UPDATE office_agreements SET archived=?, updated_at=? WHERE id=? AND org_id=?", (arch, iso(now_utc()), aid, oid))
    _save_task(c, oid, uid, aid, {}, revive=True)
    bump(c)
    c.commit()
    return jsonify(bk_public(c, oid, uid, _row(c, oid, aid)))
