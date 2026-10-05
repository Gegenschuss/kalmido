"""Family: the web API."""
import re
from datetime import date, timedelta
from flask import jsonify, request

from ..core.config import app
from ..core.i18n import lang, tr, trn
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_list, need_task
from ..tasks.validation import as_int, TITLE_MAX, valid_date
from ..tasks.tasks import one_task
from ..collab.comments import user_names
from ..personal.timetrack import BadInput
from ..family.family import (
    deadline_create, FAM_DL, FAM_NOTE_MAX, family_overview, ingredient_lines, kid_balance, kid_dict, kid_parents,
    kid_push, KID_REWARDS_MAX, kids_for, need_kid, occ_create, packing_create, packing_templates, purpose_apply,
    REWARD_COST_MAX, reward_dict, shop_areas_add, to_shopping,
)


# ---- web API
@app.get("/api/family")
def family_get():
    """The Family view's data (also GET /api/v1/family). ?week=YYYY-MM-DD: the meal plan of the week of that day."""
    c, uid = db(), me()
    wk = request.args.get("week")
    start = None
    if wk:
        if not valid_date(wk):
            return err(tr("Invalid value: {0}", "week"))
        d = date.fromisoformat(wk)
        start = d - timedelta(days=d.weekday())
    return jsonify(family_overview(c, uid, start))


@app.post("/api/family/occasions")
def family_occasion_new():
    """{name, kind? (birthday | anniversary), date (YYYY-MM-DD or --MM-DD), year?, lead_days? (7), list_id?, gifts?: [..]}
    -> a yearly task (in the list, else the first "Birthdays" list, created when missing)."""
    c, uid = db(), me()
    tid = occ_create(c, uid, body())
    bump(c)
    c.commit()
    return jsonify(one_task(c, tid)), 201


@app.get("/api/family/deadline-types")
def family_dl_types():
    lg = lang(db(), me())
    return jsonify(types=[{"key": k, "name": tr(n, lg=lg), "lead_days": ld, "repeat": rp, "notice_months": nm}
                          for k, (n, _t, ld, rp, nm) in FAM_DL.items()])


@app.post("/api/family/deadlines")
def family_deadline_new():
    """{type, expires, who?, notice_months?, lead_days?, title?, list_id?} -> a deadline task (due = expires minus the notice
    period, reminders lead days before and on the day; in the list, else the first "Household" list)."""
    c, uid = db(), me()
    tid = deadline_create(c, uid, body())
    bump(c)
    c.commit()
    return jsonify(one_task(c, tid)), 201


@app.post("/api/tasks/<int:tid>/to-shopping")
def task_to_shopping(tid):
    """{list_id?, items?: [..]} -- the ingredients of a meal (its notes; or the given items) onto a shopping list."""
    c, uid = db(), me()
    need_task(c, tid, write=False, full=True)
    b = body()
    items = b.get("items")
    if items is None:
        items = ingredient_lines(c.execute("SELECT content FROM tasks WHERE id=?", (tid,)).fetchone()[0])
    elif not isinstance(items, list) or len(items) > 100 or not all(isinstance(x, str) for x in items):
        return err(tr("Invalid value: {0}", "items"))
    items = [x.strip()[:TITLE_MAX] for x in items if x.strip()]
    if not items:
        return err(tr("No ingredients found: write them as a list in the notes"))
    lid = b.get("list_id")
    out = to_shopping(c, uid, items, as_int(lid, "list_id", 1) if lid not in (None, "") else None, source=tid)
    bump(c)
    c.commit()
    return jsonify(out)


@app.post("/api/lists/<int:lid>/shop-areas")
def list_shop_areas(lid):
    """The default shop areas as sections (only the missing ones); the list becomes a shopping list."""
    c = db()
    need_list(c, lid)
    c.execute("UPDATE lists SET family='shopping' WHERE id=? AND owner_id=?", (lid, me()))
    n = shop_areas_add(c, lid, lang(c, me()))
    # 2.22.0 (#747): areas are switched on by hand now ("Sort by shop area"): the open items without an area go to theirs
    from ..family.family import shop_area_of
    k = 0
    for t in c.execute("SELECT id, title FROM tasks WHERE list_id=? AND parent_id IS NULL AND section_id IS NULL AND status=0 AND deleted_at IS NULL",
                       (lid,)).fetchall():
        sid = shop_area_of(c, lid, t["title"])
        if sid:
            c.execute("UPDATE tasks SET section_id=? WHERE id=?", (sid, t["id"]))
            k += 1
    bump(c)
    c.commit()
    return jsonify(ok=True, added=n, sorted=k)


@app.get("/api/family/packing")
def family_packing_list():
    return jsonify(templates=packing_templates(lang(db(), me())))


@app.post("/api/family/packing")
def family_packing_new():
    """{template, name?} -> a new packing list from a built-in template (done items stay at the bottom, reusable)."""
    c, uid = db(), me()
    b = body()
    lid = packing_create(c, uid, b.get("template"), b.get("name"))
    bump(c)
    c.commit()
    return jsonify(ok=True, list_id=lid), 201


@app.post("/api/me/purpose")
def me_purpose():
    """{purpose: me | family | team | software, examples?: true} -- "What do you use Kalmido for?": switches my modules and
    creates the starter lists of that purpose once."""
    c, uid = db(), me()
    b = body()
    out = purpose_apply(c, uid, b.get("purpose"), b.get("examples", True) is not False)
    bump(c)
    c.commit()
    return jsonify(out)


# kids: stars + rewards
@app.get("/api/family/kids")
def family_kids():
    return jsonify(kids=kids_for(db(), me()))


@app.post("/api/family/kids/<int:kid>/stars")
def family_kid_stars(kid):
    """{delta (-100..100, not 0), note?} -- a parent gives (or corrects) stars by hand."""
    c = db()
    need_kid(c, kid)
    b = body()
    d = as_int(b.get("delta"), "delta", -100, 100)
    if not d:
        return err(tr("Invalid value: {0}", "delta"))
    note = b.get("note") or ""
    if not isinstance(note, str):
        return err(tr("Invalid value: {0}", "note"))
    if d < 0 and kid_balance(c, kid) + d < 0:
        return err(tr("Not that many stars"), 409)
    ts = iso(now_utc())
    c.execute("INSERT INTO kid_stars(kid_id,delta,kind,title,by_id,at,created_at) VALUES(?,?,?,?,?,?,?)",
              (kid, d, "bonus", note.strip()[:FAM_NOTE_MAX], me(), ts, ts))
    if d > 0:
        who = user_names(c, [me()]).get(me(), "?")
        kid_push(c, kid, lambda lg: trn("{0} gave you a star", "{0} gave you {1} stars", d, who, d, lg=lg), lambda lg: note.strip()[:FAM_NOTE_MAX] or "★")
    bump(c)
    c.commit()
    return jsonify(kid_dict(c, kid))


def _reward_fields(b, partial=False):
    out = {}
    if "title" in b or not partial:
        t = b.get("title")
        if not isinstance(t, str) or not t.strip():
            raise BadInput(tr("Please enter a name"))
        out["title"] = re.sub(r"\s+", " ", t).strip()[:FAM_NOTE_MAX]
    if "cost" in b or not partial:
        out["cost"] = as_int(b.get("cost"), "cost", 1, REWARD_COST_MAX)
    if "emoji" in b:
        e = b.get("emoji") or ""
        if not isinstance(e, str) or len(e) > 16:
            raise BadInput(tr("Invalid value: {0}", "emoji"))
        out["emoji"] = e.strip()
    if "once" in b:
        if not isinstance(b["once"], bool):
            raise BadInput(tr("Invalid value: {0}", "once"))
        out["once"] = 1 if b["once"] else 0
    return out


@app.post("/api/family/kids/<int:kid>/rewards")
def family_reward_new(kid):
    """{title, cost (stars), emoji?, once? (false: can be redeemed again and again)} -- a parent offers a reward."""
    c = db()
    need_kid(c, kid)
    f = _reward_fields(body())
    if c.execute("SELECT COUNT(*) FROM kid_rewards WHERE kid_id=?", (kid,)).fetchone()[0] >= KID_REWARDS_MAX:
        return err(tr("At most {0} rewards", KID_REWARDS_MAX), 409)
    rid = c.execute("INSERT INTO kid_rewards(kid_id,title,cost,emoji,once,state,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (kid, f["title"], f["cost"], f.get("emoji", ""), f.get("once", 0), "open", me(), iso(now_utc()))).lastrowid
    bump(c)
    c.commit()
    return jsonify(reward_dict(c.execute("SELECT * FROM kid_rewards WHERE id=?", (rid,)).fetchone())), 201


def need_reward(c, rid, parent=True):
    r = c.execute("SELECT * FROM kid_rewards WHERE id=?", (rid,)).fetchone()
    if not r:
        raise Denied(404)
    need_kid(c, r["kid_id"], parent)
    return r


@app.patch("/api/family/rewards/<int:rid>")
def family_reward_edit(rid):
    c = db()
    r = need_reward(c, rid)
    f = _reward_fields(body(), partial=True)
    if f:
        c.execute(f"UPDATE kid_rewards SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), rid])
        bump(c)
        c.commit()
    return jsonify(reward_dict(c.execute("SELECT * FROM kid_rewards WHERE id=?", (r["id"],)).fetchone()))


@app.delete("/api/family/rewards/<int:rid>")
def family_reward_delete(rid):
    c = db()
    need_reward(c, rid)
    c.execute("DELETE FROM kid_rewards WHERE id=?", (rid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/family/rewards/<int:rid>/request")
def family_reward_request(rid):
    """The kid asks for a reward it has the stars for; its parents get a push and decide."""
    c = db()
    r = need_reward(c, rid, parent=False)
    if r["kid_id"] != me():
        return err(tr("Only the child itself can ask for a reward"), 403)
    if r["state"] != "open":
        return err(tr("Already asked for"), 409)
    if kid_balance(c, me()) < r["cost"]:
        return err(tr("Not enough stars yet"), 409)
    c.execute("UPDATE kid_rewards SET state='requested', requested_at=? WHERE id=?", (iso(now_utc()), rid))
    who = user_names(c, [me()]).get(me(), "?")
    adm = [x[0] for x in c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0")]
    for p in dict.fromkeys(kid_parents(c, me()) or adm):
        kid_push(c, p, lambda lg: tr("{0} would like a reward", who, lg=lg), lambda lg: f"{r['emoji'] + ' ' if r['emoji'] else ''}{r['title']} · {r['cost']} ★")
    bump(c)
    c.commit()
    return jsonify(kid_dict(c, me()))


@app.post("/api/family/rewards/<int:rid>/decide")
def family_reward_decide(rid):
    """{approve: true | false} -- a parent redeems the reward (its stars are taken; a one-off reward is done, the others can
    be asked for again) or declines the request. Works on an open reward too (redeem right away)."""
    c = db()
    r = need_reward(c, rid)
    b = body()
    if not isinstance(b.get("approve"), bool):
        return err(tr("Invalid value: {0}", "approve"))
    if r["state"] == "redeemed":
        return err(tr("Already redeemed"), 409)
    ts = iso(now_utc())
    if b["approve"]:
        if kid_balance(c, r["kid_id"]) < r["cost"]:
            return err(tr("Not enough stars yet"), 409)
        c.execute("INSERT INTO kid_stars(kid_id,delta,kind,reward_id,title,by_id,at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (r["kid_id"], -r["cost"], "reward", rid, r["title"], me(), ts, ts))
        c.execute("UPDATE kid_rewards SET state=?, decided_by=?, decided_at=?, requested_at=NULL WHERE id=?",
                  ("redeemed" if r["once"] else "open", me(), ts, rid))
        kid_push(c, r["kid_id"], lambda lg: tr("Reward approved: {0}", r["title"], lg=lg), lambda lg: f"−{r['cost']} ★")
    else:
        if r["state"] != "requested":
            return err(tr("Nobody asked for it"), 409)
        c.execute("UPDATE kid_rewards SET state='open', decided_by=?, decided_at=?, requested_at=NULL WHERE id=?", (me(), ts, rid))
        kid_push(c, r["kid_id"], lambda lg: tr("Not this time: {0}", r["title"], lg=lg), lambda lg: tr("Ask again later", lg=lg))
    bump(c)
    c.commit()
    return jsonify(kid_dict(c, r["kid_id"]))
