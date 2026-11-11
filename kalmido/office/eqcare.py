"""2.558.0 C (#4591): warranty end and maintenance of office equipment -- what a private device of Home & life can
(life/model.py device_create / upkeep_create), in the office inventory (office_equipment, model.py MD "equipment").

Columns (migrations.d/4591.py): warranty_until (YYYY-MM-DD, '' = none), warranty_task_id, maint = JSON
[{id, kind (inspection | service | calibration | other), label, every_months (1..120), next (YYYY-MM-DD), lead_days, task_id}].
Like a business contract's deadline (agreements.py bk_task_sync) every date keeps ONE task: the warranty end a task due on
that day (reminder 30 days before, a deadline), a maintenance a repeating task (every N months from "next", reminder 7
days before). A new task goes into the inbox of the admin who saves (an own private list, as a private device goes into
the own "Home & devices" list); it is a normal task: moved to another list it stays there and still follows the device.
Nobody is assigned. The tasks follow every save of the device (name, date, interval); a date taken away, the device
archived or deleted ends its tasks (repeat removed, done; never deleted). A done task stays done until its date changes.
fam {kind: "equipment", office_equipment: <id>, part: "warranty" | "maint:<id>"} marks the task: a stored id never
reaches another task. Saving stays the office's master data way (model.py office_update, expect_updated_at)."""
import json
from datetime import date

from ..core.config import PUBLIC_URL
from ..core.db import iso, local_now, now_utc
from ..core.i18n import N_, lang, tr
from ..core.access import live_sql, my_inbox, wr_sql
from ..core.errors import BadInput
from ..accounts.session import me
from ..tasks.validation import log_act, log_changes, rr_problem
from ..life.model import _insert, _reminders, renew_rule

EQC_KINDS = {"inspection": N_("Inspection: {0}"), "service": N_("Service: {0}"), "calibration": N_("Calibration: {0}"),
             "other": N_("Maintenance: {0}")}
EQC_MAX = 20
EQC_WARRANTY_LEAD = 30  # days, as a private device (life/model.py device_create)
EQC_MAINT_LEAD = 7  # days, as upkeep (life/model.py upkeep_create)
EQC_LABEL_MAX = 80
EQC_SYNC_KEYS = ("warranty_until", "maint", "archived", "name")


def _date(v, k):
    if v in (None, ""):
        return ""
    try:
        if not isinstance(v, str) or len(v) != 10:
            raise ValueError
        date.fromisoformat(v)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", k)) from None
    return v


def eqc_clean_maint(v):
    """The maintenance list of a client -> the stored JSON text (ids and task ids are set by eqc_sync)."""
    if v in (None, ""):
        return "[]"
    if not isinstance(v, list) or len(v) > EQC_MAX:
        raise BadInput(tr("Invalid value: {0}", "maint"))
    out = []
    for it in v:
        if not isinstance(it, dict) or it.get("kind") not in EQC_KINDS:
            raise BadInput(tr("Invalid value: {0}", "maint"))
        try:
            every = int(it.get("every_months"))
            lead = int(it.get("lead_days", EQC_MAINT_LEAD) if it.get("lead_days") not in (None, "") else EQC_MAINT_LEAD)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "every_months")) from None
        if not 1 <= every <= 120 or not 0 <= lead <= 365:
            raise BadInput(tr("Invalid value: {0}", "every_months"))
        label = it.get("label") or ""
        if not isinstance(label, str):
            raise BadInput(tr("Invalid value: {0}", "label"))
        nxt = _date(it.get("next"), "next") or local_now().date().isoformat()
        x = {"kind": it["kind"], "label": " ".join(label.split())[:EQC_LABEL_MAX], "every_months": every, "next": nxt, "lead_days": lead}
        if isinstance(it.get("id"), int) and it["id"] > 0:
            x["id"] = it["id"]
        out.append(x)
    return json.dumps(out, ensure_ascii=False)


def _maint(v):
    if isinstance(v, list):
        return v
    try:
        j = json.loads(v or "[]")
    except (TypeError, ValueError):
        return []
    return j if isinstance(j, list) else []


def eqc_task(c, eid, tid, part):
    """The task tid made for part of device eid (its fam says so), else None."""
    if not tid:
        return None
    return _ours(c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone(), eid, part)


def _ours(t, eid, part):
    """t when its fam marks it as the task of part of device eid, else None."""
    if not t:
        return None
    try:
        f = json.loads(t["fam"] or "{}")
    except ValueError:
        return None
    return t if isinstance(f, dict) and f.get("kind") == "equipment" and f.get("office_equipment") == eid and f.get("part") == part else None


def _end(c, t):
    if not t or t["status"] != 0 or t["deleted_at"]:
        return
    ts = iso(now_utc())
    c.execute("UPDATE tasks SET repeat='', status=2, completed_at=?, updated_at=? WHERE id=? AND status=0", (ts, ts, t["id"]))
    log_act(c, t["id"], "complete")


def _live(t):
    return bool(t) and t["status"] == 0 and not t["deleted_at"]


def _slot(c, uid, eid, part, tid, spec, changed, t=False):
    """Keeps the task of one date in step. spec None = no task wanted. -> the task id to store (None = none).
    2.558.0 D (#4591, review F1): an open task keeps its due date unless the date (or interval) really changed -- a repeating
    task moves on in the same row when it is done, a save without that change never sets it back. t: the task already read."""
    t = eqc_task(c, eid, tid, part) if t is False else t
    if spec is None:
        _end(c, t)
        return None
    live = _live(t)
    if t and not live and not changed:
        return t["id"]  # done by a person (or ended): stays done until its date changes
    fam = {"kind": "equipment", "office_equipment": eid, "part": part}
    if live:
        if not c.execute(f"SELECT 1 FROM lists WHERE id=? AND id IN {wr_sql()}", (t["list_id"], uid, uid)).fetchone():
            return t["id"]  # another admin's list this one may not change: the task stays as it is
        sets = {"title": spec["title"][:500], "due": spec["due"], "reminders": spec["reminders"], "repeat": spec["repeat"]}
        if not changed:
            sets.pop("due")  # 2.558.0 D (#4591, review F1)
        if any(str(t[k] or "") != str(v or "") for k, v in sets.items()):
            sets["updated_at"] = iso(now_utc())
            c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), t["id"]])
            log_changes(c, t["id"], t)
        return t["id"]
    content = PUBLIC_URL.rstrip("/") + "/#office/equipment"
    return _insert(c, uid, my_inbox(c, uid), spec["title"], spec["due"], rem=spec["reminders"], rep=spec["repeat"], fam=fam,
                   deadline=spec["deadline"], content=content)


def eqc_sync(c, oid, eid, before=None, revive=False, uid=None):
    """After a save of device eid of office oid (before = the row before, None for a new one): the stored maintenance
    list gets its ids, the tasks follow (made, changed, ended). revive: a restored device starts its tasks again.
    2.558.0 D (#4591, review F1): an unchanged maintenance takes "next" from its open task (done -> it moved on); a task made
    again for a revived device (archive, office trash) starts at the latest of next, the old task's date and today, never
    overdue. uid: whose inbox gets new tasks (default the person saving; the org import passes the importing admin)."""
    r = c.execute(f"SELECT id, name, archived, warranty_until, warranty_task_id, maint FROM office_equipment WHERE id=? AND org_id=? AND {live_sql()}",
                  (eid, oid)).fetchone()
    if not r:
        return
    uid = uid or me()
    lg = lang(c, uid)
    if revive and not before:  # restored from the office trash: its own stored list names the old tasks (ids kept)
        before = dict(r)
    before = before or {}
    off = bool(int(r["archived"] or 0))
    revive = revive or (bool(int(before.get("archived") or 0)) and not off)  # taken out of the archive: its tasks start again
    name = r["name"] or ""
    w = r["warranty_until"] or ""
    spec = None if off or not w else {"title": tr("Warranty ends: {0}", name, lg=lg), "due": w, "reminders": _reminders(EQC_WARRANTY_LEAD),
                                      "repeat": "", "deadline": 2}
    t = eqc_task(c, eid, r["warranty_task_id"], "warranty")
    if spec and revive and not _live(t) and w < local_now().date().isoformat():
        spec = None  # 2.558.0 D (#4591, review F1): revived with the warranty already over -- nothing left to remind of
    wt = _slot(c, uid, eid, "warranty", r["warranty_task_id"], spec, revive or w != (before.get("warranty_until") or ""), t)
    old = {x.get("id"): x for x in _maint(before.get("maint")) if isinstance(x, dict) and x.get("id")}
    items = _maint(r["maint"])
    top = max([x.get("id") or 0 for x in items if isinstance(x, dict) and isinstance(x.get("id"), int)] + list(old) + [0])
    out, keep = [], set()
    for x in items:
        if not isinstance(x, dict) or x.get("kind") not in EQC_KINDS:
            continue
        if not isinstance(x.get("id"), int) or x["id"] in keep or x["id"] not in old:
            top += 1
            x["id"] = top
        keep.add(x["id"])
        prev = old.get(x["id"]) or {}
        tid = prev.get("task_id")
        rep = renew_rule(int(x["every_months"]))
        if rep and rr_problem(rep):
            rep = ""
        what = tr(EQC_KINDS[x["kind"]], name, lg=lg) if not x.get("label") else f"{x['label']}: {name}"
        part = f"maint:{x['id']}"
        t = eqc_task(c, eid, tid, part)
        edited = any(str(prev.get(k)) != str(x.get(k)) for k in ("next", "every_months"))
        changed = revive or edited
        if _live(t) and not edited and t["due"]:
            x["next"] = str(t["due"])[:10]  # 2.558.0 D (#4591, review F1): done in the meantime, the task moved on
        elif revive and not off and not _live(t):
            x["next"] = max(x["next"], str(t["due"] or "")[:10] if t else "", local_now().date().isoformat())
        sp = None if off else {"title": what, "due": x["next"], "reminders": _reminders(int(x.get("lead_days") or 0)), "repeat": rep, "deadline": 0}
        x["task_id"] = _slot(c, uid, eid, part, tid, sp, changed, t)
        out.append(x)
    for mid, x in old.items():  # a maintenance taken out: its task ends
        if mid not in keep:
            _slot(c, uid, eid, f"maint:{mid}", x.get("task_id"), None, False)
    c.execute("UPDATE office_equipment SET warranty_task_id=?, maint=? WHERE id=? AND org_id=?",
              (wt, json.dumps(out, ensure_ascii=False), eid, oid))


def eqc_end(c, oid, eid):
    """The device goes (deleted / archived without a save): its tasks end."""
    r = c.execute("SELECT warranty_task_id, maint FROM office_equipment WHERE id=? AND org_id=?", (eid, oid)).fetchone()
    if not r:
        return
    _end(c, eqc_task(c, eid, r["warranty_task_id"], "warranty"))
    for x in _maint(r["maint"]):
        if isinstance(x, dict) and x.get("id"):
            _end(c, eqc_task(c, eid, x.get("task_id"), f"maint:{x['id']}"))


def eqc_enrich(c, rows):
    """Admin rows of GET /api/office/equipment[/<id>]: warranty_task / per maintenance task = {id, due, done} of its task
    (the next date of a repeating task moves on when it is done). 2.558.0 D (#4591, review F6): the tasks of the whole list in
    one query per 500 ids, not one per device and maintenance."""
    want = set()
    for r in rows:
        want.add(r.get("warranty_task_id"))
        want.update(x.get("task_id") for x in _maint(r.get("maint")) if isinstance(x, dict))
    ids = sorted(i for i in want if isinstance(i, int) and i > 0)
    got = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        got.update((t["id"], t) for t in c.execute(f"SELECT id, due, status, deleted_at, fam FROM tasks WHERE id IN ({','.join('?' * len(part))})",
                                                   part).fetchall())
    for r in rows:
        t = _ours(got.get(r.get("warranty_task_id")), r.get("id"), "warranty")
        r["warranty_task"] = {"id": t["id"], "due": t["due"], "done": t["status"] != 0 or bool(t["deleted_at"])} if t else None
        items = []
        for x in _maint(r.get("maint")):
            if not isinstance(x, dict):
                continue
            t = _ours(got.get(x.get("task_id")), r.get("id"), f"maint:{x.get('id')}")
            items.append({**x, "task": {"id": t["id"], "due": t["due"], "done": t["status"] != 0 or bool(t["deleted_at"])} if t else None})
        r["maint"] = items
    return rows
