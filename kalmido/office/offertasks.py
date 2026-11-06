"""2.537.0 C (#3433): tasks in the project from a quotation, with a time budget per position (decisions of 27.10. and 04.11.2026).

GET  /api/office/docs/<did>/tasks: the preview -- every position of the quotation as a row with its hours and its state
     against the tasks the chain (the quotation and its versions, version_of) already made in the project:
     new | same | changed (the quotation's hours changed, the field was not changed by hand) | manual (changed, but the
     field was changed by hand: kept) | gone (a task whose position is no longer there).
POST /api/office/docs/<did>/tasks {pick: [keys], hours: {key: h|null}, create?: {name}}: applies the ticked rows -- a new row
     becomes a task, a changed one gets the new budget, a gone one is only marked (history, the task stays); never deletes.
     A quotation without a project gets a new one first (like "Create project", office/docproject.py dpj_create).

Mapping: a position of the title page = a task without a section; a part (Teilangebot) = a section named after it, its
positions = its tasks; a shoot part: one task per crew function with its days. Rabatt-, Zwischensummen- and text lines
(kinds text / heading, the computed lines are no rows at all) never become tasks. Title = the position's title, text = its
description; never a price, only hours.
Budget: unit hour = qty, minute = qty / 60, day = qty x the project's hours per day (lists.day_hours, else the instance's,
default 8); a part used n times on the title page counts n times; piece / flat rate: no budget (the preview takes a value).
It is written into the project's number field "Budget h" (the agency project type's field, summed per project by
personal/timetrack.py time_list_totals -- the head bar "tracked / budget"); a project without it gets the field.
Rights: the office's (office_ctx + the area "offers" through the route's segment) and, for applying, the right to change
the project (need_list write); a list with the lock (end-to-end encryption) takes no plain texts (409)."""
import json
import math
from decimal import Decimal

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, iso, now_utc
from ..core.i18n import LANGS, tr
from ..core.access import WRITE_ROLES, Denied, list_role, need_list
from ..core.errors import BadInput
from ..core.pg import insert_id, write_lock
from ..collab.liste2eguard import le2b_list_locked, le2b_off
from ..lists.fields import FIELD_MAX, field_act, field_value, fields_pinned_ok, tb_fields_module_on
from ..lists.lists import COL_MAX, columns_out
from ..personal.timetrack import BUDGET_FIELD_NAMES, time_day_h
from ..tasks.dependencies import newtask_events
from ..tasks.validation import TITLE_MAX, log_act
from .calc import calc_lang, fmt_money, fmt_qty
from .docs import doc_items, doc_row
from .docproject import dpj_create, dpj_name
from .ledger import ofx_log
from .model import office_ctx
from .offerdispo import odp_apply, odp_dates_in, odp_preview  # 2.589.0 (#4571): shoot days into the disposition
from .parts import tp_parts
from .sheet import dk_staff_days

OTK_MAX_ROWS = 300  # rows of one preview (a quotation holds at most 300 positions per page)
OTK_MAX_H = 100000  # hours a row may take by hand
OTK_TIME_UNITS = {"hour": Decimal(1), "minute": Decimal(1) / Decimal(60)}  # + day = the project's hours per day


def otk_root(r):
    """The chain of quotation row r: its first quotation (version_of, 2.88.0 #1915) or itself."""
    return (r["version_of"] if "version_of" in r.keys() else None) or r["id"]


def otk_chain_ids(c, oid, root):
    return [x[0] for x in c.execute("SELECT id FROM office_docs WHERE org_id=? AND kind='offer' AND (id=? OR version_of=?)", (oid, root, root))]


def otk_links(c, oid, r, lid):
    """{item_key: link row} of the tasks this quotation's chain made in project lid (the chain's documents or its root)."""
    root = otk_root(r)
    ids = otk_chain_ids(c, oid, root) or [r["id"]]
    q = ",".join("?" * len(ids))
    rows = c.execute(f"""SELECT k.*, t.title, t.deleted_at FROM task_offer_links k JOIN tasks t ON t.id=k.task_id
                         WHERE k.list_id=? AND (k.root_id=? OR k.doc_id IN ({q})) ORDER BY k.task_id""", (lid, root, *ids)).fetchall()
    out = {}
    for x in rows:
        if x["item_key"] not in out or out[x["item_key"]]["deleted_at"] and not x["deleted_at"]:  # a living task wins
            out[x["item_key"]] = x
    return out


def otk_count(c, r):
    """doc_public: how many living tasks the chain of quotation r made in its project (0 without a project)."""
    if r["kind"] != "offer" or not r["list_id"]:
        return 0
    return len([x for x in otk_links(c, r["org_id"], r, r["list_id"]).values() if not x["deleted_at"]])


def otk_day_hours(c, lid):
    if lid:
        x = c.execute("SELECT day_hours FROM lists WHERE id=?", (lid,)).fetchone()
        if x and x[0]:
            return float(x[0])
    return float(time_day_h(c))


def _h(unit, qty, dh, mult=Decimal(1)):
    """The budget of a position in hours (2 places) or None (piece, flat rate, percent: no time)."""
    q = Decimal(str(qty or 0)) * mult
    if unit == "day":
        v = q * Decimal(str(dh))
    elif unit in OTK_TIME_UNITS:
        v = q * OTK_TIME_UNITS[unit]
    else:
        return None
    return float(round(v, 2)) if v > 0 else None


def otk_rows(c, oid, r, dh):
    """The rows of quotation r: [{key, section, part, title, text, unit, qty, qty_text, hours}] in the print order."""
    lg = calc_lang(r["lang"])
    parts = {p["id"]: p for p in tp_parts(c, oid, r["id"])}
    out, seen = [], set()

    def add(key, sec, pkey, title, text, unit, qty, hours):
        if key in seen or len(out) >= OTK_MAX_ROWS or not (title or "").strip():
            return
        seen.add(key)
        out.append({"key": key, "section": sec, "part": pkey, "title": " ".join(str(title).split())[:TITLE_MAX], "text": (text or "").strip(),
                    "unit": unit, "qty": float(qty), "qty_text": fmt_qty(qty, lg), "hours": hours})

    for it in doc_items(c, r["id"], oid):
        if it["kind"] == "service":
            add(f"i:{it['origin_id'] or it['id']}", "", "", it["title"], it["detail"], it["unit"], it["qty"], _h(it["unit"], it["qty"], dh))
        elif it["kind"] == "part" and it["ref_part_id"] in parts:
            p = parts[it["ref_part_id"]]
            mult = Decimal(str(it["qty"] or 1)) if (it["qty"] or 0) > 0 else Decimal(1)
            pk = str(p.get("origin_id") or p["id"])
            sec = " ".join((p["title"] or "").split())[:100] or tr("Part {0}", len({x["part"] for x in out if x["part"]}) + 1)
            if p["kind"] == "shoot":
                for s in dk_staff_days(p["sheet"], lg):
                    days = s["people"] * s["days"] * mult
                    add(f"s:{pk}:{s['uid']}", sec, pk, s["name"], "", "day", days, _h("day", days, dh))
            else:
                for pit in doc_items(c, r["id"], oid, part=p["id"]):
                    if pit["kind"] == "service":
                        add(f"i:{pit['origin_id'] or pit['id']}", sec, pk, pit["title"], pit["detail"], pit["unit"], pit["qty"],
                            _h(pit["unit"], pit["qty"], dh, mult))
    return out


def _num(v):
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def otk_budget_field(c, lid, create=False):
    """The project's number field "Budget h" (any language, like time_list_totals) -> its row; create: made when missing
    (like the agency type's field: pinned while there is room) -> (row, made)."""
    names = set(BUDGET_FIELD_NAMES) | {tr("Budget h", lg=x).lower() for x in LANGS}
    for f in c.execute("SELECT * FROM list_fields WHERE list_id=? AND type='number' ORDER BY sort, id", (lid,)).fetchall():
        if (f["name"] or "").strip().lower() in names:
            return f, False
    if not create:
        return None, False
    if c.execute("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0] >= FIELD_MAX:
        raise BadInput(tr("At most {0} fields per project", FIELD_MAX))
    srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0]
    fid = insert_id(c, "INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                    (lid, tr("Budget h"), "number", "{}", 1 if fields_pinned_ok(c, lid) else 0, srt, iso(now_utc())))
    cc = c.execute("SELECT col_cfg FROM lists WHERE id=?", (lid,)).fetchone()[0]
    if cc:  # like field_create: a list with its own columns shows the new field as its last column
        cols = columns_out(cc, {x[0] for x in c.execute("SELECT id FROM list_fields WHERE list_id=?", (lid,))})
        if cols is not None and len(cols) < COL_MAX:
            c.execute("UPDATE lists SET col_cfg=? WHERE id=?", (json.dumps([*cols, f"f:{fid}"]), lid))
    return c.execute("SELECT * FROM list_fields WHERE id=?", (fid,)).fetchone(), True


def otk_preview(c, oid, uid, r):
    """The preview of quotation r (see the module text)."""
    lid = r["list_id"]
    role = list_role(c, lid, uid) if lid else None
    dh = otk_day_hours(c, lid if role else None)
    rows = otk_rows(c, oid, r, dh)
    links = otk_links(c, oid, r, lid) if role else {}
    f = otk_budget_field(c, lid)[0] if role else None
    cur = {}
    if f is not None and links:
        ids = [x["task_id"] for x in links.values()]
        cur = {t: _num(v) for t, v in c.execute(f"SELECT task_id, value FROM task_field_values WHERE field_id=? AND task_id IN ({','.join('?' * len(ids))})",
                                                (f["id"], *ids))}
    for x in rows:
        k = links.get(x["key"])
        x.update(state="new", task_id=None, task_hours=None, pick=True)
        if k is None:
            continue
        if k["deleted_at"]:  # the person deleted the task: offered again, not ticked
            x.update(state="new", pick=False, deleted=True)
            continue
        th = cur.get(k["task_id"])
        x.update(task_id=k["task_id"], task_hours=th)
        same = (x["hours"] or None) == (k["auto_h"] or None)
        by_hand = (th or None) != (k["set_h"] or None)
        x.update(state="same" if same else "manual" if by_hand else "changed", pick=not same and not by_hand)
        if same and k["gone"]:
            x["state"], x["pick"] = "back", True  # a position that came back: the mark goes
    keys = {x["key"] for x in rows}
    gone = [{"key": k, "task_id": x["task_id"], "title": x["title"], "state": "gone", "pick": not x["gone"], "marked": bool(x["gone"]),
             "task_hours": cur.get(x["task_id"])} for k, x in links.items() if k not in keys and not x["deleted_at"]]
    t = json.loads(r["totals"] or "{}") if isinstance(r["totals"], str) else (r["totals"] or {})
    lg = calc_lang(r["lang"])
    return {"doc_id": r["id"], "list_id": lid if role else None, "list_known": bool(role) or not lid, "can": (role in WRITE_ROLES) if lid else True,
            "day_hours": dh, "linked": len([x for x in links.values() if not x["deleted_at"]]), "rows": rows, "gone": gone,
            "total_h": round(sum(x["hours"] or 0 for x in rows), 2), "net_text": fmt_money(t.get("net") or 0, lg, r["currency"]),
            "field": f["name"] if f is not None else None, "dispo": odp_preview(c, oid, uid, r, otk_root(r))}


def otk_offer(c, oid, did):
    r = doc_row(c, oid, did)
    if r["kind"] != "offer":
        raise BadInput(tr("Tasks are made from a quotation only"))
    return r


@app.get("/api/office/docs/<int:did>/tasks")
def otk_get(did):
    """The preview: {doc_id, list_id, can, day_hours, linked, rows: [...], gone: [...], total_h, net_text, field}."""
    c, uid, oid = office_ctx()
    return jsonify(otk_preview(c, oid, uid, otk_offer(c, oid, did)))


def _hours_in(v):
    if v is None or v == "":
        return None
    x = _num(v)
    if x is None or x < 0 or x > OTK_MAX_H:
        raise BadInput(tr("Invalid value: {0}", tr("Budget h")))
    return round(x, 2) or None


def _section(c, lid, name, cache):
    if not name:
        return None
    k = name.casefold()
    if k not in cache:
        x = c.execute("SELECT id FROM sections WHERE list_id=? AND lower(name)=lower(?) ORDER BY sort, id LIMIT 1", (lid, name)).fetchone()
        if x:
            cache[k] = x[0]
        else:
            srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM sections WHERE list_id=?", (lid,)).fetchone()[0]
            cache[k] = insert_id(c, "INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, name[:100], srt))
    return cache[k]


def _set_budget(c, f, tid, lid, h):
    v = field_value(c, f, h, lid) if h is not None else None
    old = c.execute("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (tid, f["id"])).fetchone()
    if (old[0] if old else None) == v:
        return
    if v is None:
        c.execute("DELETE FROM task_field_values WHERE task_id=? AND field_id=?", (tid, f["id"]))
    else:
        c.execute("INSERT INTO task_field_values(task_id,field_id,value) VALUES(?,?,?) ON CONFLICT(task_id,field_id) DO UPDATE SET value=excluded.value",
                  (tid, f["id"], v))
    log_act(c, tid, "field", field_act(c, f, v))


@app.post("/api/office/docs/<int:did>/tasks")
def otk_apply(did):
    """{pick: [keys], hours?: {key: h|null}, create?: {name}, dispo?: {pick: [day keys], dates: {key: YYYY-MM-DD}}} -> {list_id,
    created, updated, marked, made_project, field_made, modules_on, dispo: {booked, adapted, marked}}. 2.589.0 (#4571): + dispo
    (office/offerdispo.py); tasks or shoot days, at least one."""
    c, uid, oid = office_ctx()
    b = body()
    if not isinstance(b, dict) or not isinstance(b.get("pick", []), list) or not isinstance(b.get("hours") or {}, dict):
        raise BadInput(tr("Invalid data"))
    pick = {str(x) for x in b.get("pick") or [] if isinstance(x, (str, int))}
    dsp = b.get("dispo") if isinstance(b.get("dispo"), dict) else {}
    dpick = [str(x) for x in dsp.get("pick") or [] if isinstance(x, str)] if isinstance(dsp.get("pick"), list) else []
    ddates = odp_dates_in(dsp.get("dates"))
    if not pick and not dpick:
        raise BadInput(tr("Select at least one entry"))
    hin = {str(k): _hours_in(v) for k, v in (b.get("hours") or {}).items()}
    # 2.537.0 (#3433, review M1): the shared thing is the chain (two versions clicked at once made every task twice) and the
    # project; fixed order chain -> document -> project, so two chains with the same project wait instead of deadlocking
    write_lock(c, f"offer_tasks_{otk_root(otk_offer(c, oid, did))}")
    write_lock(c, f"office_doc_{int(did)}")  # like docproject: never in between two saves of the document
    r = otk_offer(c, oid, did)
    made, on = False, []
    lid = r["list_id"]
    if lid:
        write_lock(c, f"offer_tasks_list_{int(lid)}")
        need_list(c, lid, write=True)  # 404 unseen, 403 a viewer / participant: creating tasks needs the right to change the project
    else:
        cr = b.get("create") if isinstance(b.get("create"), dict) else {}
        lid, on = dpj_create(c, uid, oid, r, dpj_name(cr.get("name")))
        made = True
        ts = iso(now_utc())
        c.execute("UPDATE office_docs SET list_id=?, updated_at=? WHERE id=? AND org_id=?", (lid, ts, did, oid))
        c.execute("UPDATE office_deals SET list_id=?, updated_at=? WHERE org_id=? AND offer_id=? AND list_id IS NULL AND deleted_at IS NULL", (lid, ts, oid, did))
        ofx_log(c, oid, "project", doc_id=did, detail={"before": {"list_id": None}, "after": {"list_id": lid}, "created": True})
        r = otk_offer(c, oid, did)
    if le2b_list_locked(c, lid):
        raise Denied(409, le2b_off())
    pv = otk_preview(c, oid, uid, r)
    dres = odp_apply(c, oid, uid, r, otk_root(r), lid, dpick, ddates)  # 2.589.0 (#4571): before the tasks, its 400 / 409 changes nothing
    f, fmade = otk_budget_field(c, lid, create=True) if pick else (otk_budget_field(c, lid)[0], False)
    if fmade:
        on = list(dict.fromkeys(on + tb_fields_module_on(c, lid)))
    ts, root = iso(now_utc()), otk_root(r)
    secs, n_new, n_upd, n_gone = {}, 0, 0, 0
    srt = c.execute("SELECT COALESCE(MAX(sort),0) FROM tasks WHERE list_id=?", (lid,)).fetchone()[0] or 0
    for x in pv["rows"]:
        if x["key"] not in pick or x["state"] == "same":
            continue
        h = hin[x["key"]] if x["key"] in hin else x["hours"]
        if x["state"] == "new":
            srt += 1
            tid = insert_id(c, "INSERT INTO tasks(list_id,section_id,title,content,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                            (lid, _section(c, lid, x["section"], secs), x["title"], x["text"], srt, ts, ts, uid))
            log_act(c, tid, "created", {"offer": True})
            if h is not None:
                v = field_value(c, f, h, lid)
                c.execute("INSERT INTO task_field_values(task_id,field_id,value) VALUES(?,?,?)", (tid, f["id"], v))
            c.execute("INSERT INTO task_offer_links(task_id,list_id,doc_id,root_id,item_key,auto_h,set_h,gone,created_at,updated_at) VALUES(?,?,?,?,?,?,?,0,?,?)",
                      (tid, lid, r["id"], root, x["key"], x["hours"], h, ts, ts))
            newtask_events(c, tid)
            n_new += 1
        elif x["state"] == "back":  # the position is in the quotation again: the mark goes, the budget stays as it is
            log_act(c, x["task_id"], "offer_back")
            c.execute("UPDATE task_offer_links SET doc_id=?, root_id=?, gone=0, updated_at=? WHERE task_id=?", (r["id"], root, ts, x["task_id"]))
            n_upd += 1
        elif x["state"] in ("changed", "manual"):  # ticked: the quotation's hours (or the value typed in the preview)
            if h is None:  # 2.537.0 (#3433, review L1): no hours (a flat rate now, an empty field): the entered budget stays
                h = x["task_hours"]
            else:
                _set_budget(c, f, x["task_id"], lid, h)
            c.execute("UPDATE task_offer_links SET doc_id=?, root_id=?, auto_h=?, set_h=?, gone=0, updated_at=? WHERE task_id=?",
                      (r["id"], root, x["hours"], h, ts, x["task_id"]))
            n_upd += 1
    for x in pv["gone"]:
        if x["key"] in pick and not x["marked"]:
            c.execute("UPDATE task_offer_links SET gone=1, doc_id=?, updated_at=? WHERE task_id=?", (r["id"], ts, x["task_id"]))
            log_act(c, x["task_id"], "offer_gone")
            n_gone += 1
    # the rows left as they are follow the new version too (doc_id: the project's budget shows this quotation's net)
    c.execute("UPDATE task_offer_links SET doc_id=?, root_id=? WHERE list_id=? AND root_id=? AND (doc_id IS NULL OR doc_id<>?)", (r["id"], root, lid, root, r["id"]))  # 2.552.0 (#4647, review): a deleted version left NULL
    ofx_log(c, oid, "tasks", doc_id=did, detail={"list_id": lid, "created": n_new, "updated": n_upd, "marked": n_gone, **({"dispo": dres} if dpick else {})})
    bump(c)
    c.commit()
    return jsonify(list_id=lid, created=n_new, updated=n_upd, marked=n_gone, made_project=made, field_made=fmade, modules_on=on,
                   dispo=dres), 201 if n_new or made or dres["booked"] else 200


def otk_project_budget(c, oid, lid):
    """GET /api/lists/<lid>/office-docs (office people only): the project's budget from its quotation -- {doc_id, number,
    hours (the field values of the tasks it made, not gone), net_text (the quotation's net)} or None."""
    k = c.execute("SELECT doc_id FROM task_offer_links WHERE list_id=? AND gone=0 AND doc_id IS NOT NULL ORDER BY updated_at DESC, task_id DESC LIMIT 1", (lid,)).fetchone()
    if not k:
        return None
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=? AND kind='offer'", (k[0], oid)).fetchone()
    if r is None:
        return None
    links = [x for x in otk_links(c, oid, r, lid).values() if not x["deleted_at"] and not x["gone"]]
    f = otk_budget_field(c, lid)[0]
    hours = 0.0
    if f is not None and links:
        ids = [x["task_id"] for x in links]
        hours = sum(_num(v) or 0 for (v,) in c.execute(f"SELECT value FROM task_field_values WHERE field_id=? AND task_id IN ({','.join('?' * len(ids))})",
                                                      (f["id"], *ids)))
    t = json.loads(r["totals"] or "{}") if isinstance(r["totals"], str) else {}
    return {"doc_id": r["id"], "number": r["number"] or "", "hours": round(hours, 2), "net_text": fmt_money(t.get("net") or 0, calc_lang(r["lang"]), r["currency"])}
