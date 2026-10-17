"""2.75.0 (#1411): the routes of the built-in assistant (assistant/core.py explains the rules; docs/API.md "Built-in assistant").

Session only (the web app), never agents or children; every route answers 404 while the assistant is not configured.
What may be sent is checked on every call: a task must be visible to the person AND lie in a list they shared with the
assistant (re-checked against the current visibility, never a health list, never archived) or in their own basket; free
text they type always goes. Proposal results are ready proposal jobs of the person themself (agent_id = user_id = the
person, input.assistant = true) applied / discarded / undone over the existing /api/proposals routes; no agent event is
ever sent for them. Every call (also refused or failed ones) leaves one row in assistant_log -- numbers and a status,
never a prompt or an answer."""
import json
import re
import time
from datetime import timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import insert_id
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc, usettings
from ..core.access import Denied, list_people, list_role, my_inbox, need_task, vis_sql, WRITE_ROLES
from ..accounts.session import me
from ..personal.timetrack import BadInput
from . import core as A

ASST_OFF_MSG = N_("Switch the assistant on in Settings first")
ASST_SHARE_MSG = N_("Share this list with the assistant first")
ASST_ERR_MSG = {"network": N_("The assistant is not reachable right now"), "auth": N_("The assistant is not reachable right now"),
                "bad": N_("The assistant gave no usable answer"), "timeout": N_("The assistant took too long")}
ASST_ERR_CODE = {"network": 502, "auth": 502, "bad": 502, "timeout": 504}
ASST_KIND_NAMES = {"summary": N_("Summary"), "draft": N_("Draft"), "extract": N_("Tasks from notes"),
                   "tags": N_("Tags and due date"), "triage": N_("Sort tasks"), "dayplan": N_("Day plan")}
_ASST_CLEAN = {"at": 0.0}


def _asst_gate():
    """404 while off and for agents; 403 for children (they never use it)."""
    from ..agents.core import is_agent
    if not A.asst_on() or not getattr(g, "user", None) or is_agent(g.user):
        raise Denied(404)
    if g.user["kid"]:
        raise Denied(403)


def asst_user_on(c, uid):
    """The person switched the assistant on (children and agents: never)."""
    u = c.execute("SELECT kid, kind FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["kid"] or u["kind"] == "agent":
        return False
    return usettings(c, uid).get("assistant_on") == "1"


def asst_lists(c, uid):
    """The shared lists of uid that may still be used: visible right now, not the basket, no health list, not archived.
    -> [{id, name}] in the order of the sidebar."""
    rows = c.execute(f"""SELECT l.id, l.name FROM assistant_access a JOIN lists l ON l.id=a.list_id
                         WHERE a.user_id=? AND l.id IN {vis_sql()} AND l.is_inbox=0 AND COALESCE(l.life, '')<>'health'
                         AND COALESCE(l.archived, 0)=0 ORDER BY l.sort, l.id""", (uid, uid, uid)).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def asst_state(c, uid):
    """The field "assistant" of /api/state ({} while off: the client then shows nothing)."""
    from ..agents.core import is_agent
    if not A.asst_on() or is_agent(g.user):
        return {}
    on = asst_user_on(c, uid)
    return {"assistant": {"enabled": True, **A.asst_info(), "on": on, "list_ids": [x["id"] for x in asst_lists(c, uid)] if on else []}}


def _asst_view(c, uid):
    on = asst_user_on(c, uid)
    from ..agents.proposals import PROP_OPEN_MAX
    return {"enabled": True, **A.asst_info(), "on": on, "lists": asst_lists(c, uid),
            "limits": {"max_chars": A.ASST_MAX_CHARS, "max_items": A.ASST_ITEMS_MAX, "open_max": PROP_OPEN_MAX}}


def asst_log(c, uid, kind, status, ms=0, chars_in=0, chars_out=0, task_id=None, list_id=None, job_id=None):
    """One row of the person's assistant log (numbers and a status only) + one line in the server log, no texts.
    Rows older than KALMIDO_AUDIT_DAYS days go (checked at most hourly; 0 = only today's rows stay)."""
    from ..agents.usage import AUDIT_DAYS
    at = now_utc()
    insert_id(c, """INSERT INTO assistant_log(user_id,kind,task_id,list_id,job_id,status,ms,chars_in,chars_out,model,at,day)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (uid, kind[:20], task_id, list_id, job_id, status, int(ms), int(chars_in), int(chars_out), A.ASST_MODEL[:120], iso(at),
               local_now().date().isoformat()))
    print("assistant", kind, status, int(ms), flush=True)
    if time.time() - _ASST_CLEAN["at"] > 3600:
        _ASST_CLEAN["at"] = time.time()
        first = (local_now().date() - timedelta(days=max(AUDIT_DAYS, 0))).isoformat()
        c.execute("DELETE FROM assistant_log WHERE day<?", (first,))


@app.get("/api/assistant")
def asst_get():
    _asst_gate()
    c = db()
    uid = me()
    keep = [x["id"] for x in asst_lists(c, uid)]  # shares of lists the person no longer sees (or archived / health) go
    q = f" AND list_id NOT IN ({','.join('?' * len(keep))})" if keep else ""
    if c.execute("DELETE FROM assistant_access WHERE user_id=?" + q, (uid, *keep)).rowcount:
        c.commit()
    return jsonify(_asst_view(c, uid))


@app.put("/api/assistant/lists")
def asst_put_lists():
    """{list_ids: [..]} -> the lists shared with the assistant. Only lists the person sees, never the basket, a health list
    or an archived list (silently left out). Replaces the earlier choice; one log row."""
    _asst_gate()
    c = db()
    uid = me()
    b = body()
    raw = b.get("list_ids")
    if not isinstance(raw, list) or len(raw) > 500 or not all(isinstance(x, int) and not isinstance(x, bool) for x in raw):
        raise BadInput(tr("Invalid value: {0}", "list_ids"))
    want = sorted({x for x in raw if 0 < x < 2 ** 53})
    ok = set()
    if want:
        ok = {r[0] for r in c.execute(f"""SELECT l.id FROM lists l WHERE l.id IN ({','.join('?' * len(want))}) AND l.id IN {vis_sql()}
                                         AND l.is_inbox=0 AND COALESCE(l.life, '')<>'health' AND COALESCE(l.archived, 0)=0""",
                                      (*want, uid, uid))}
    c.execute("DELETE FROM assistant_access WHERE user_id=?", (uid,))
    ts = iso(now_utc())
    for lid in sorted(ok):
        c.execute("INSERT INTO assistant_access(user_id,list_id,created_at) VALUES(?,?,?)", (uid, lid, ts))
    asst_log(c, uid, "lists", "ok", chars_in=len(ok))
    bump(c)
    c.commit()
    return jsonify(_asst_view(c, uid))


@app.get("/api/assistant/log")
def asst_get_log():
    _asst_gate()
    c = db()
    try:
        n = max(1, min(500, int(request.args.get("limit") or 50)))
    except ValueError:
        n = 50
    rows = c.execute("SELECT * FROM assistant_log WHERE user_id=? ORDER BY id DESC LIMIT ?", (me(), n)).fetchall()
    return jsonify(items=[{k: r[k] for k in ("id", "kind", "task_id", "list_id", "job_id", "status", "ms", "chars_in", "chars_out", "at")}
                          for r in rows])


@app.get("/api/admin/assistant")
def asst_admin():
    """Admins: the configuration (never the key) and the calls of the last 30 days (counts only, no people, no texts)."""
    from ..accounts.users import need_admin
    _asst_gate()
    need_admin()
    c = db()
    today = local_now().date()
    first = (today - timedelta(days=29)).isoformat()
    rows = c.execute("""SELECT day, COUNT(*) AS calls, SUM(CASE WHEN status IN ('error','timeout') THEN 1 ELSE 0 END) AS errors,
                        SUM(chars_in) AS cin, SUM(chars_out) AS cout FROM assistant_log WHERE day>=? AND kind<>'lists'
                        GROUP BY day ORDER BY day DESC""", (first,)).fetchall()
    days = [{"day": r["day"], "calls": int(r["calls"] or 0), "errors": int(r["errors"] or 0), "chars_in": int(r["cin"] or 0),
             "chars_out": int(r["cout"] or 0)} for r in rows]
    t = next((d for d in days if d["day"] == today.isoformat()), {"calls": 0, "errors": 0})
    return jsonify(**A.asst_info(), timeout_s=A.ASST_TIMEOUT_S, max_chars=A.ASST_MAX_CHARS,
                   today={"calls": t["calls"], "errors": t["errors"]}, days=days)


# ---- what goes to the model
def _asst_mentions(text):
    from ..collab.comments import MENTION_RE
    return re.sub(r"\s+", " ", MENTION_RE.sub("@(person)", text or "")).strip()


def asst_task_ok(c, uid, tid, shared):
    """The task row when uid may send it: visible (full, not only as a participant's context) AND in a shared list or in
    the person's own basket. Denied otherwise (404 for invisible tasks: no probing)."""
    try:
        need_task(c, tid, write=False, full=True)
    except Denied:
        raise Denied(404) from None
    t = c.execute("SELECT t.*, l.is_inbox AS l_inbox, l.owner_id AS l_owner, l.life AS l_life, l.name AS l_name "
                  "FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    if not t or t["deleted_at"]:
        raise Denied(404)
    if t["l_life"] == "health":
        raise Denied(403, tr(ASST_SHARE_MSG))
    if t["l_inbox"] and t["l_owner"] == uid:
        return t
    if t["list_id"] in shared:
        return t
    raise Denied(403, tr(ASST_SHARE_MSG))


def asst_task_text(c, t, comments=True):
    """Title, list, due, tags, note (never a locked one) and comments (mentions without names) of a task as plain text."""
    from ..collab.notelock import ln_is_locked
    from ..tasks.tasks import my_tags
    out = [f"Task {t['id']}: {t['title']}", f"List: {tr('Basket') if t['l_inbox'] else t['l_name']}"]
    if t["due"]:
        out.append(f"Due: {t['due']}")
    tags = my_tags(c, t["id"])
    if tags:
        out.append("Tags: " + ", ".join(tags))
    if not ln_is_locked(c, t["id"]) and (t["content"] or "").strip():
        out.append("Notes:\n" + t["content"].strip())
    if comments:
        rows = c.execute("SELECT body, created_at FROM comments WHERE task_id=? AND deleted_at IS NULL ORDER BY id LIMIT 200",
                         (t["id"],)).fetchall()
        if rows:
            out.append("Comments:")
            out += [f"- [{(r['created_at'] or '')[:10]}] {_asst_mentions(r['body'])}" for r in rows if (r["body"] or "").strip()]
    return "\n".join(out)


def _asst_str(v, mx):
    if not isinstance(v, str):
        return ""
    v = re.sub(r"[\x00-\x08\x0b-\x1f]", "", v.replace("\r\n", "\n")).strip()
    return v[:mx]


def _asst_date(v):
    from ..tasks.validation import valid_date
    return v if isinstance(v, str) and valid_date(v) else None


def _asst_prio(v):
    from ..api.v1 import PRIO_VALUES
    return v if isinstance(v, str) and v in PRIO_VALUES else None


def _asst_id(v):
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v.strip())
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 2 ** 53 else None


def _asst_tags(v):
    from ..agents.proposals import PROP_TAGS_MAX, PROP_TAG_MAX
    out = []
    for x in v if isinstance(v, list) else []:
        x = _asst_str(x, PROP_TAG_MAX).lstrip("#").strip()
        if x and "\n" not in x and x.casefold() not in (y.casefold() for y in out):
            out.append(x)
    return out[:PROP_TAGS_MAX]


def asst_clean(kind, raw, inp):
    """The model's JSON -> a proposal body that only holds known fields and ids of the input (everything else dropped,
    never an error for one bad entry); prop_validate checks it afterwards like an agent's proposal."""
    from ..agents.proposals import PROP_MAX_ITEMS, PROP_NOTES_MAX, PROP_SUMMARY_MAX, PROP_TITLE_MAX
    out = {"summary": _asst_str(raw.get("summary"), PROP_SUMMARY_MAX)}
    if kind == "extract":
        members = {m["id"] for m in inp.get("members", [])}
        secs = {s.casefold(): s for s in inp.get("list", {}).get("sections", [])}
        tasks = []
        for t in raw.get("tasks") if isinstance(raw.get("tasks"), list) else []:
            if not isinstance(t, dict):
                continue
            title = re.sub(r"\s*\n\s*", " ", _asst_str(t.get("title"), PROP_TITLE_MAX))
            if not title:
                continue
            aid = _asst_id(t.get("assignee_id"))
            sec = _asst_str(t.get("section"), 100)
            tasks.append({"title": title, "notes": _asst_str(t.get("notes"), PROP_NOTES_MAX),
                          "assignee_id": aid if aid in members else None, "due": _asst_date(t.get("due")),
                          "section": secs.get(sec.casefold()) if sec else None})
        out["tasks"] = tasks[:PROP_MAX_ITEMS]
    elif kind == "triage":
        ids = {x["task_id"] for x in inp.get("items", [])}
        lists = {x["id"]: {s["id"] for s in x.get("sections", [])} for x in inp.get("lists", [])}
        items, seen = [], set()
        for t in raw.get("items") if isinstance(raw.get("items"), list) else []:
            if not isinstance(t, dict):
                continue
            tid = _asst_id(t.get("task_id"))
            if tid not in ids or tid in seen:
                continue
            seen.add(tid)
            lid = _asst_id(t.get("list_id"))
            lid = lid if lid in lists else None
            sid = _asst_id(t.get("section_id"))
            sid = sid if lid is not None and sid in lists[lid] else None
            rt = re.sub(r"\s*\n\s*", " ", _asst_str(t.get("rewrite_title"), PROP_TITLE_MAX)) or None
            items.append({"task_id": tid, "list_id": lid, "section_id": sid, "tags": _asst_tags(t.get("tags")),
                          "priority": _asst_prio(t.get("priority")), "due": _asst_date(t.get("due")), "rewrite_title": rt})
        out["items"] = items
    elif kind == "dayplan":
        from ..tasks.validation import valid_hm
        ids = {t["task_id"] for t in inp.get("tasks", [])}
        seen, items, nofit = set(), [], []
        for t in raw.get("items") if isinstance(raw.get("items"), list) else []:
            if not isinstance(t, dict):
                continue
            tid, st = _asst_id(t.get("task_id")), t.get("start")
            if tid not in ids or tid in seen or not isinstance(st, str) or not valid_hm(st):
                continue
            seen.add(tid)
            dur = _asst_id(t.get("duration"))
            items.append({"task_id": tid, "start": st, "duration": dur if dur and 5 <= dur <= 720 else None,
                          "note": re.sub(r"\s*\n\s*", " ", _asst_str(t.get("note"), 300))})
        for t in raw.get("nofit") if isinstance(raw.get("nofit"), list) else []:
            tid = _asst_id(t.get("task_id")) if isinstance(t, dict) else None
            if tid in ids and tid not in seen:
                seen.add(tid)
                nofit.append({"task_id": tid, "note": re.sub(r"\s*\n\s*", " ", _asst_str(t.get("note"), 300))})
        out["items"], out["nofit"] = items, nofit
    return out


# ---- the inputs per kind (the same structure the agents' proposals use: the proposal card shows them unchanged)
def _asst_inp(inp):
    return {**inp, "assistant": True, "provider": A.ASST_NAME}


def asst_extract_input(c, uid, lid, text):
    from ..agents.core import agent_ids, list_sections
    from ..collab.comments import user_names
    lst = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    ag = agent_ids(c)
    ppl = [p for p in sorted(list_people(c, lid)) if p not in ag]
    names = user_names(c, ppl)
    return _asst_inp({"list": {"id": lid, "name": lst["name"], "sections": [s["name"] for s in list_sections(c, uid, lid)]},
                      "members": [{"id": p, "name": names.get(p, "")} for p in ppl], "text": text})


def asst_triage_lists(c, uid, shared):
    """The target lists of a triage: shared lists the person may change as a whole, with their sections."""
    from ..core.state import visible_lists, visible_sections
    mine = [d for d in visible_lists(c, uid) if d["id"] in shared and not d["is_inbox"] and not d["archived"]
            and d.get("role", "owner") in WRITE_ROLES]
    secs = {}
    for s in visible_sections(c, uid):
        secs.setdefault(s["list_id"], []).append({"id": s["id"], "name": s["name"]})
    return [{"id": d["id"], "name": d["name"], "folder": d["folder"] or None, "sections": secs.get(d["id"], [])} for d in mine]


def asst_dayplan_input(c, uid, day, shared):
    """The day plan input (tasks/dayplan.py dayplan_input) reduced to the shared lists; events only as busy times (no
    titles: they come from calendars, not from shared lists); locked notes left out."""
    from ..collab.notelock import ln_locked_ids
    from ..tasks.dayplan import dayplan_input
    inp = dayplan_input(c, uid, day, "day")
    inp["tasks"] = [t for t in inp["tasks"] if t["list_id"] in shared]
    inp["fixed"] = [t for t in inp["fixed"] if t.get("list_id") in shared]
    locked = ln_locked_ids(c, [t["task_id"] for t in inp["tasks"]])
    for t in inp["tasks"]:
        if t["task_id"] in locked:
            t["notes"] = ""
    ids = {t["task_id"] for t in inp["tasks"]}
    inp["builtin"] = {"plan": [x for x in inp["builtin"]["plan"] if x["task_id"] in ids],
                      "nofit": [x for x in inp["builtin"]["nofit"] if x in ids]}
    inp["events"] = [{**e, "title": tr("Busy")} for e in inp["events"]]
    return _asst_inp(inp)


def asst_job(c, uid, kind, pkind, inp, prop, task_id=None, list_id=None):
    """A ready proposal job of the person themself + the News card (no push: the person just asked and sees it)."""
    from ..agents.core import JOB_TITLE_MAX, job_dict
    from ..collab.comments import collab_user
    from ..collab.news import notif_ok
    ts = iso(now_utc())
    title = tr("Assistant: {0}", tr(ASST_KIND_NAMES[kind]))
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,?,?,?,'waiting','',?,?,?,?,'ready',?,?)""",
                    (uid, task_id, uid, title[:JOB_TITLE_MAX], ts, ts, pkind, json.dumps(inp, ensure_ascii=False), list_id,
                     json.dumps(prop, ensure_ascii=False)))
    s = collab_user(c, uid, None)
    if s and notif_ok(c, uid, s, "proposal", "news"):
        c.execute("INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (uid, "proposal", None, None, None, None, json.dumps({"job": jid, "title": title[:200], "kind": pkind, "assistant": True},
                                                                       ensure_ascii=False), iso(now_utc())))
    return jid, job_dict(c, c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone())


def _asst_int_arg(b, k):
    v = b.get(k)
    if v in (None, ""):
        return None
    v = _asst_id(v)
    if v is None:
        raise BadInput(tr("Invalid value: {0}", k))
    return v


@app.post("/api/assistant/run")
def asst_run():
    """{kind, task_id?, task_ids?, text?, instruction?, list_id?, day?} -> a text (summary, draft) or a ready proposal
    (extract, tags, triage, dayplan). One synchronous model call with the time limit; one log row whatever happens."""
    from ..agents.proposals import PROP_OPEN_MAX, PROP_TEXT_MAX, prop_validate
    _asst_gate()
    c = db()
    uid = me()
    b = body()
    kind = b.get("kind")
    if kind not in A.ASST_KINDS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    unknown = set(b) - {"kind", "task_id", "task_ids", "text", "instruction", "list_id", "day"}
    if unknown:
        raise BadInput(tr("Invalid value: {0}", sorted(unknown)[0]))
    t0 = time.monotonic()
    rec = {"task_id": None, "list_id": None, "job_id": None, "chars_in": 0}

    def fail(status, code, msg):
        c.rollback()
        asst_log(c, uid, kind, status, (time.monotonic() - t0) * 1000, rec["chars_in"], 0, rec["task_id"], rec["list_id"])
        c.commit()
        return err(msg, code)

    try:
        if not asst_user_on(c, uid):
            raise Denied(403, tr(ASST_OFF_MSG))
        shared = {x["id"] for x in asst_lists(c, uid)}
        tid = _asst_int_arg(b, "task_id")
        rec["task_id"] = tid
        text = b.get("text")
        if text is not None and not isinstance(text, str):
            raise BadInput(tr("Invalid value: {0}", "text"))
        text = (text or "").strip()[:PROP_TEXT_MAX]
        instr = b.get("instruction")
        if instr is not None and not isinstance(instr, str):
            raise BadInput(tr("Invalid value: {0}", "instruction"))
        instr = re.sub(r"\s+", " ", instr or "").strip()[:A.ASST_INSTR_MAX]
        task = asst_task_ok(c, uid, tid, shared) if tid else None
        if kind in ("extract", "tags", "triage", "dayplan") and c.execute(
                "SELECT COUNT(*) FROM agent_jobs WHERE user_id=? AND kind IS NOT NULL AND state IN ('running','waiting')",
                (uid,)).fetchone()[0] >= PROP_OPEN_MAX:
            asst_log(c, uid, kind, "denied", 0, 0, 0, tid)
            c.commit()
            return jsonify(error=tr("You have {0} open proposal requests: apply or discard some first", PROP_OPEN_MAX)), 429
        system = A.asst_system(c, uid, kind)
        inp, pkind, lid, jtask = None, None, None, None
        if kind in ("summary", "draft"):
            parts = []
            if task is not None:
                parts.append(asst_task_text(c, task))
            if text:
                parts.append(text)
            if not parts and not (kind == "draft" and instr):
                raise BadInput(tr("Missing field: {0}", "task_id / text"))
            if kind == "draft" and not instr:
                instr = "A short, friendly reply."
            data = "\n\n".join(parts)
        elif kind == "extract":
            lid = _asst_int_arg(b, "list_id")
            rec["list_id"] = lid
            if not lid:
                raise BadInput(tr("Missing field: {0}", "list_id"))
            if lid not in shared:
                raise Denied(403, tr(ASST_SHARE_MSG))
            if list_role(c, lid) not in WRITE_ROLES:  # the tasks would be created there: no model call for a read-only list
                raise Denied(403)
            src = text or (asst_task_text(c, task) if task is not None else "")
            if not src:
                raise BadInput(tr("Missing field: {0}", "text"))
            inp, pkind, jtask = asst_extract_input(c, uid, lid, src[:A.ASST_MAX_CHARS]), "extract", tid
            data = json.dumps({"list": inp["list"], "members": inp["members"], "today": local_now().date().isoformat()},
                              ensure_ascii=False) + "\n\nContent:\n" + src
            system = A.asst_system(c, uid, kind, n=50)
        elif kind == "tags":
            if task is None:
                raise BadInput(tr("Missing field: {0}", "task_id"))
            from ..collab.notelock import ln_is_locked
            from ..tasks.tasks import my_tags
            notes = "" if ln_is_locked(c, tid) else (task["content"] or "")[:4000]
            inp = _asst_inp({"items": [{"task_id": tid, "title": task["title"], "notes": notes}], "lists": []})
            pkind, jtask, lid = "triage", tid, task["list_id"]
            own = [r[0] for r in c.execute("SELECT DISTINCT tag FROM task_tags WHERE user_id=? ORDER BY tag LIMIT 200", (uid,))]
            data = asst_task_text(c, task) + "\n\n" + json.dumps({"task_id": tid, "existing_tags": own, "current_tags": my_tags(c, tid),
                                                                 "today": local_now().date().isoformat()}, ensure_ascii=False)
        elif kind == "triage":
            raw = b.get("task_ids")
            if not isinstance(raw, list) or not raw:
                raise BadInput(tr("Missing field: {0}", "task_ids"))
            if len(raw) > A.ASST_ITEMS_MAX:
                raise BadInput(tr("Too many entries: {0} (at most {1})", "task_ids", A.ASST_ITEMS_MAX))
            ids = []
            for x in raw:
                x = _asst_id(x)
                if x is None:
                    raise BadInput(tr("Invalid value: {0}", "task_ids"))
                if x not in ids:
                    ids.append(x)
            from ..collab.notelock import ln_locked_ids
            rows = [asst_task_ok(c, uid, x, shared) for x in ids]
            rows = [r for r in rows if r["status"] == 0 and r["parent_id"] is None]
            if not rows:
                raise BadInput(tr("Only open tasks can be sorted"))
            locked = ln_locked_ids(c, [r["id"] for r in rows])
            inp = _asst_inp({"items": [{"task_id": r["id"], "title": r["title"],
                                        "notes": "" if r["id"] in locked else (r["content"] or "")[:4000]} for r in rows],
                             "lists": asst_triage_lists(c, uid, shared)})
            pkind, lid = "triage", my_inbox(c, uid)
            data = json.dumps({"today": local_now().date().isoformat(), "lists": inp["lists"], "tasks": inp["items"]}, ensure_ascii=False)
        else:  # dayplan
            from ..tasks.dayplan import dayplan_day
            day = dayplan_day(b.get("day"))
            inp = asst_dayplan_input(c, uid, day, shared)
            if not inp["tasks"]:
                raise BadInput(tr("There are no open tasks to plan"))
            pkind = "dayplan"
            data = json.dumps({k: inp[k] for k in ("date", "now", "work", "from", "default_duration", "events", "fixed", "tasks")},
                              ensure_ascii=False)
        msg, rec["chars_in"], cut = A.asst_frame(data, instr if kind == "draft" else None)
        c.commit()  # no open transaction while the model works (up to KALMIDO_AI_TIMEOUT_S); nothing is written before
        answer = A.asst_chat(system, msg)
        if kind in ("summary", "draft"):
            out = A.asst_cap(answer)
            if not out:
                raise A.AsstError("bad")
            asst_log(c, uid, kind, "truncated" if cut else "ok", (time.monotonic() - t0) * 1000, rec["chars_in"], len(out), tid)
            c.commit()
            return jsonify(kind=kind, text=out, truncated=cut, log_id=c.execute(
                "SELECT MAX(id) FROM assistant_log WHERE user_id=?", (uid,)).fetchone()[0])
        clean = asst_clean(pkind, A.asst_json(answer), inp)
        if pkind == "triage" and kind == "tags":
            clean["items"] = [{**x, "list_id": None, "section_id": None, "rewrite_title": None} for x in clean["items"]]
        try:
            prop = prop_validate(pkind, clean, inp)
        except BadInput:
            raise A.AsstError("bad") from None
        jid, job = asst_job(c, uid, kind, pkind, inp, prop, jtask, lid)
        asst_log(c, uid, kind, "truncated" if cut else "ok", (time.monotonic() - t0) * 1000, rec["chars_in"], len(answer), tid, lid, jid)
        bump(c)
        c.commit()
        print("assistant proposal", jid, pkind, "by user", uid, flush=True)
        return jsonify(kind=kind, job_id=jid, job=job, proposal=prop, truncated=cut)
    except Denied as e:
        return fail("denied", e.code, e.text())
    except BadInput as e:
        return fail("error", 400, str(e))
    except A.AsstError as e:
        return fail("timeout" if e.code == "timeout" else "error", ASST_ERR_CODE[e.code], tr(ASST_ERR_MSG[e.code]))
