"""Onboarding and the sample project."""
import json
from datetime import datetime, timedelta, timezone
from flask import g, has_request_context, jsonify

from ..core.config import app, TZ
from ..core.i18n import lang, N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc, uset, usettings
from ..accounts.session import me
from ..accounts.pictures import list_icon_drop_file
from ..core.access import collab_all, list_role, my_max_sort, time_all, WRITE_ROLES
from ..core.serializers import attachment_files, unlink_files
from ..tasks.validation import log_act
from ..tasks.tasks import set_tags


# ---------------------------------------------------------------- onboarding (v1.1)
# "Getting started" sample list: created once on the first start of a NEW account (setting onboard=pending,
# set by the setup and the user admin; existing accounts have onboard=done). Server-side so it lands in the
# user's language and only mentions enabled modules; the client says which device it is on (touch / Mac),
# the gesture tasks follow that. The list is a normal list: rename, share or delete it like any other.

def onboarding_tasks(feats, touch, mac):
    """[(title, content, priority, due_today, subtasks)] in English (tr() by the caller)."""
    tt = [
        (N_("Tick me off"), N_("Tap the square on the left, or swipe the task to the right.") if touch
         else N_("Click the square on the left to complete a task."), 5, True, []),
        (N_("Tap me for details, notes and subtasks") if touch else N_("Click me for details, notes and subtasks"),
         N_("Everything about a task lives in this panel:\n\n- a description with **Markdown**\n- [ ] checklists like this one\n- files, links, dates and reminders"),
         3, True, [N_("Subtasks work like tasks"), N_("Tick this one off, too")]),
        (N_("Try quick add: Dentist tomorrow 3pm !high #private"),
         N_("Type it into the add bar (the + button on a phone): dates, times, !priority, #tags and ~list are recognized while you type."), 3, True, []),
        (N_("Swipe me left to reschedule") if touch else N_("Drag me onto Tomorrow in the sidebar"),
         N_("Swipe left for snooze, other dates and delete; long-press and drag to reorder.") if touch
         else N_("Drag tasks onto a day, a list or another place in the list. Right-click is not needed: the … menu has the rest."), 1, True, []),
    ]
    if not touch:
        tt.append((N_("Press {0} to search and run commands"), N_("Lists, tasks, views and actions in one box. Press ? for all keyboard shortcuts."), 0, False, []))
    mods = [("habits", N_("Create a habit under Habits"), N_("Daily or a few times a week, with streaks.")),
            ("pomo", N_("Start a focus timer on a task"), N_("Task menu (…) > Start focus, or the Focus module.")),
            ("collab", N_("Share this list with someone"), N_("List menu (…) > Sharing. Tasks in shared lists can be assigned and commented.")),
            ("time", N_("Start a timer on a task"), N_("Task menu (…) > Start timer; reports under Time tracking.")),
            ("timeline+deps", N_("Plan a project in the timeline"),
             N_("Edit list > Type: Project, View: Timeline. Drag the dot at the end of one bar onto another: the second task then waits on the first.")
             if not touch else
             N_("Edit list > Type: Project, View: Timeline. Long-press a bar and choose “Connect to…”, then tap the task that waits on it."))]
    for k, t, d in mods:
        if all(x in feats for x in k.split("+")):
            tt.append((t, d, 0, False, []))
    tt.append((N_("Delete this list when you are done"), N_("List menu (…) > Delete. Nothing else is affected."), 0, False, []))
    return tt


@app.post("/api/onboarding")
def onboarding():
    b, c = body(), db()
    uid = me()
    c.execute("BEGIN IMMEDIATE")
    if usettings(c, uid).get("onboard") != "pending":
        c.rollback()
        return jsonify(ok=True, created=False)
    lg = lang(c, uid)
    feats = [f for f in usettings(c, uid)["features"].split(",") if f]
    feats = [f for f in feats if (f != "collab" or collab_all()) and (f != "time" or time_all())]
    touch, mac = b.get("touch") is True, b.get("mac") is True
    ts, day = iso(now_utc()), local_now().strftime("%Y-%m-%d")
    # time tracking / dependencies / custom fields on (e.g. "Projects & team"): the sample list is a project, so the
    # timer and dependency tips work right there
    kind = "project" if {"time", "deps", "fields"} & set(feats) else "list"
    lid = c.execute("INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                    (tr("Getting started", lg=lg), "#2dd4bf", "", my_max_sort(c, uid) + 1, "list", ts, uid, kind)).lastrowid
    for i, (title, content, prio, due, subs) in enumerate(onboarding_tasks(feats, touch, mac)):
        t = tr(title, "⌘K" if mac else "Ctrl+K", lg=lg) if "{0}" in title else tr(title, lg=lg)
        tid = c.execute("""INSERT INTO tasks(list_id,title,content,priority,due,sort,created_at,updated_at,created_by)
                           VALUES(?,?,?,?,?,?,?,?,?)""", (lid, t, tr(content, lg=lg), prio, day if due else None, i, ts, ts, uid)).lastrowid
        log_act(c, tid, "created", uid=uid)
        for j, st in enumerate(subs):
            c.execute("""INSERT INTO tasks(list_id,parent_id,title,sort,created_at,updated_at,created_by)
                         VALUES(?,?,?,?,?,?,?)""", (lid, tid, tr(st, lg=lg), j, ts, ts, uid))
    uset(c, uid, "onboard", "done")
    bump(c)
    c.commit()
    return jsonify(ok=True, created=True, list_id=lid)


# ---------------------------------------------------------------- sample project (1.8.0)
# "Example: Image film for client Muster": a realistic project list (sections, dates around today, start dates for the
# timeline, dependencies, all four matrix quadrants, subtasks, a Markdown checklist, tags, a repeating task, a comment,
# custom fields, a time entry, a project status) plus a checklist "Example: Shoot day packing list". Offered in the
# first-run setup and the welcome tour, created / removed under Settings > Data. Only uses the modules the user has
# on. Private (owner only), quiet: no reminders, no activity / webhooks / News, left out of the daily digest.
# Every row it creates is recorded in sample_items, so "Remove" deletes exactly that: sample tasks go even when the
# user edited them; tasks the user added (also below a sample task) stay, and with them their list and section.
SAMPLE_KINDS = ("list", "section", "task", "field", "time")


def _sample_tasks():
    """(key, section index | None, title, priority, start offset, due offset, extras) in English (tr() by the caller).
    Offsets are days from today; None = no date."""
    return [
        ("brief", 0, N_("Briefing with the client"), 3, -9, -8, {"done": -8, "tags": [N_("client")]}),
        ("concept", 0, N_("Write the concept and treatment"), 5, -5, -1, {
            "tags": [N_("concept")], "content": N_("**Goal:** a 90-second image film for the website and trade fairs.\n\n- [x] Read the briefing notes\n- [ ] First draft of the treatment\n- [ ] Internal review\n- [ ] Send it to the client\n\nInterviews: managing director and head of production."),
            "subs": [(N_("Define the target audience"), True), (N_("Phrase the key message"), False),
                     (N_("Collect reference films"), False)], "effort": "m"}),
        ("budget", 0, N_("Get the quote and budget approved"), 5, None, 0, {
            "tags": [N_("client")], "budget": 12500,
            "comment": N_("The client agreed to the budget on the phone, the written approval follows.")}),
        ("scout", 1, N_("Scout the locations"), 3, 1, 3, {}),
        ("board", 1, N_("Draw the storyboard"), 3, 0, 4, {"effort": "m"}),
        ("crew", 1, N_("Book crew and equipment"), 1, None, 5, {"tags": [N_("organisation")]}),
        ("permit", 1, N_("Apply for a filming permit"), 1, None, 2, {"tags": [N_("organisation")]}),
        ("day1", 2, N_("Shoot day 1: interviews"), 5, None, 8, {"time": "08:00", "dur": 540, "budget": 3200, "effort": "l"}),
        ("day2", 2, N_("Shoot day 2: B-roll at the plant"), 3, None, 9, {"time": "08:00", "dur": 480}),
        ("rough", 3, N_("Rough cut"), 3, 10, 14, {"budget": 1800, "effort": "l"}),
        ("music", 3, N_("License the music"), 0, None, None, {}),
        ("grade", 3, N_("Color grading and sound mix"), 1, 15, 17, {"effort": "m"}),
        ("feedback", 4, N_("Feedback round with the client"), 5, None, 19, {"tags": [N_("client")]}),
        ("deliver", 4, N_("Final delivery (4K and social formats)"), 3, None, 21, {}),
        ("call", None, N_("Weekly status call with the client"), 0, None, "tue", {"time": "10:00", "dur": 30,
                                                                                  "repeat": "FREQ=WEEKLY;BYDAY=TU"}),
    ]


SAMPLE_SECTIONS = (N_("Concept"), N_("Pre-production"), N_("Shoot"), N_("Edit|film production phase"), N_("Approval"))
SAMPLE_DEPS = (("budget", "concept"), ("scout", "budget"), ("day1", "scout"), ("rough", "day1"))  # (waits, on)
SAMPLE_PACKING = (N_("Camera and three batteries"), N_("Memory cards (formatted)"), N_("Tripod and slider"),
                  N_("Wireless lavalier microphones"), N_("LED lights and stands"), N_("Gaffer tape"),
                  N_("Shooting schedule and contact list"), N_("Release forms"), N_("Water and snacks"))


def sample_state(c, uid):
    """What the sample left behind, for the client (Settings > Data, the removal dialog), or None."""
    tasks = c.execute("""SELECT COUNT(*) FROM tasks WHERE id IN
                         (SELECT item_id FROM sample_items WHERE user_id=? AND kind='task')""", (uid,)).fetchone()[0]
    lists = [{"id": r["id"], "name": r["name"], "extra": r["extra"]} for r in c.execute(
        """SELECT l.id, l.name, (SELECT COUNT(*) FROM tasks t WHERE t.list_id=l.id AND t.id NOT IN
                                  (SELECT item_id FROM sample_items WHERE user_id=? AND kind='task')) AS extra
           FROM lists l WHERE l.owner_id=? AND l.id IN (SELECT item_id FROM sample_items WHERE user_id=? AND kind='list')
           ORDER BY l.id""", (uid, uid, uid))]
    return {"tasks": tasks, "lists": lists} if tasks or lists else None


def sample_create(c, uid):
    """Creates the sample for uid (caller commits). Returns the id of the project list."""
    from ..lists.fields import fmt_num
    c.execute("DELETE FROM sample_items WHERE user_id=?", (uid,))  # leftovers of a sample removed by hand
    lg = lang(c, uid)
    s = usettings(c, uid)
    feats = {f for f in s["features"].split(",") if f}
    feats = {f for f in feats if (f != "collab" or collab_all()) and (f != "time" or time_all())}
    project = bool({"time", "deps", "fields", "progress"} & feats)
    today = local_now().date()
    ts = iso(now_utc())
    day = lambda n: (today + timedelta(days=n)).isoformat() if n is not None else None  # noqa: E731
    track = lambda kind, iid: c.execute("INSERT OR IGNORE INTO sample_items(user_id,kind,item_id) VALUES(?,?,?)",  # noqa: E731
                                        (uid, kind, iid))
    srt = my_max_sort(c, uid)
    lid = c.execute("INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                    (tr("Example: Image film for client Muster", lg=lg), "#8b5cf6", "", srt + 1, "list", ts, uid, 0,
                     "project" if project else "list")).lastrowid
    track("list", lid)
    secs = []
    for i, n in enumerate(SAMPLE_SECTIONS):
        secs.append(c.execute("INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, tr(n, lg=lg), i + 1)).lastrowid)
        track("section", secs[-1])
    fields = {}
    if project and "fields" in feats:
        cur = s.get("time_currency") or "€"
        fields["budget"] = c.execute("INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                                     (lid, tr("Budget", lg=lg), "number", json.dumps({"unit": cur[:12]}), 1, 1, ts)).lastrowid
        opts = [{"id": k, "name": tr(n, lg=lg), "color": col} for k, n, col in
                (("s", N_("Small"), "#22c55e"), ("m", N_("Medium"), "#f59e0b"), ("l", N_("Large"), "#ef4444"))]
        fields["effort"] = c.execute("INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                                     (lid, tr("Effort", lg=lg), "select", json.dumps({"options": opts}, ensure_ascii=False), 1, 2, ts)).lastrowid
        for f in fields.values():
            track("field", f)
    ids = {}
    for i, (key, sec, title, prio, start, due, x) in enumerate(_sample_tasks()):
        if due == "tue":  # the next Tuesday (today, if it is one)
            due = (1 - today.weekday()) % 7
        done = x.get("done")
        tid = c.execute("""INSERT INTO tasks(list_id,section_id,title,content,priority,status,due,due_time,repeat,sort,created_at,
                           updated_at,completed_at,start,duration,created_by,completed_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (lid, secs[sec] if sec is not None else None, tr(title, lg=lg), tr(x["content"], lg=lg) if x.get("content") else "",
                         prio, 2 if done is not None else 0, day(due), x.get("time"), x.get("repeat") or "", i + 1, ts, ts,
                         iso(datetime.combine(today + timedelta(days=done), datetime.min.time().replace(hour=16), TZ).astimezone(timezone.utc))
                         if done is not None else None,
                         day(start), x.get("dur") if x.get("time") else None, uid, uid if done is not None else None)).lastrowid
        ids[key] = tid
        track("task", tid)
        if x.get("tags"):
            set_tags(c, tid, [tr(t, lg=lg) for t in x["tags"]], uid)
        for j, (st, sdone) in enumerate(x.get("subs") or []):
            sid = c.execute("""INSERT INTO tasks(list_id,section_id,parent_id,title,status,sort,created_at,updated_at,completed_at,
                               created_by,completed_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (lid, secs[sec] if sec is not None else None, tid, tr(st, lg=lg), 2 if sdone else 0, j + 1, ts, ts,
                             ts if sdone else None, uid, uid if sdone else None)).lastrowid
            track("task", sid)
        for fk in ("budget", "effort"):
            if fk in fields and x.get(fk) is not None:
                v = fmt_num(x[fk]) if fk == "budget" else x[fk]
                c.execute("INSERT INTO task_field_values(task_id,field_id,value) VALUES(?,?,?)", (tid, fields[fk], v))
        if x.get("comment") and "collab" in feats:
            c.execute("INSERT INTO comments(task_id,user_id,body,mentions,created_at) VALUES(?,?,?,?,?)",
                      (tid, uid, tr(x["comment"], lg=lg), "", iso(now_utc() - timedelta(hours=3))))
    if project and "deps" in feats:
        for a, b in SAMPLE_DEPS:
            c.execute("INSERT OR IGNORE INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,?,?)",
                      (ids[a], ids[b], uid, ts))
    if project and "time" in feats:  # 1.5 h on the treatment yesterday afternoon
        st = datetime.combine(today - timedelta(days=1), datetime.min.time().replace(hour=14), TZ).astimezone(timezone.utc)
        eid = c.execute("""INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,end,seconds,note,source,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (uid, ids["concept"], lid, tr("Write the concept and treatment", lg=lg), iso(st),
                         iso(st + timedelta(minutes=90)), 5400, tr("First draft of the treatment", lg=lg), "manual", ts, ts)).lastrowid
        track("time", eid)
    if project and "progress" in feats:
        note = tr("Shoot dates confirmed with the client", lg=lg)
        c.execute("UPDATE lists SET status='on_track', status_note=?, status_by=?, status_at=? WHERE id=?", (note, uid, ts, lid))
        c.execute("INSERT INTO list_status(list_id,user_id,status,note,created_at) VALUES(?,?,?,?,?)", (lid, uid, "on_track", note, ts))
    # the packing list: a plain list with "Show completed at the bottom" (2.7.2, #414; ticked items stay below and can be
    # reused for the next shoot)
    cl = c.execute("INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                   (tr("Example: Shoot day packing list", lg=lg), "#f59e0b", "", srt + 2, "list", ts, uid, 1, "list")).lastrowid
    track("list", cl)
    for i, n in enumerate(SAMPLE_PACKING):
        track("task", c.execute("INSERT INTO tasks(list_id,title,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?)",
                                (cl, tr(n, lg=lg), i + 1, ts, ts, uid)).lastrowid)
    uset(c, uid, "sample_ask", "0")
    return lid


def sample_remove(c, uid):
    """Removes what the sample created (caller commits; returns (counts, files to unlink))."""
    from ..lists.projects import list_row_purge
    rows = lambda kind: [r[0] for r in c.execute("SELECT item_id FROM sample_items WHERE user_id=? AND kind=?", (uid, kind))]  # noqa: E731
    mine = [t["id"] for t in c.execute(f"SELECT id, list_id FROM tasks WHERE id IN ({','.join('?' * len(rows('task'))) or 'NULL'})",
                                       rows("task")).fetchall()
            if list_role(c, t["list_id"], uid) in WRITE_ROLES]
    q = ",".join("?" * len(mine)) or "NULL"
    # tasks the user added below a sample task stay (as main tasks)
    kept = c.execute(f"UPDATE tasks SET parent_id=NULL WHERE parent_id IN ({q}) AND id NOT IN ({q})", mine + mine).rowcount
    files = attachment_files(c, mine)
    c.execute(f"DELETE FROM tasks WHERE id IN ({q})", mine)
    te = rows("time")
    c.execute(f"DELETE FROM time_entries WHERE user_id=? AND id IN ({','.join('?' * len(te)) or 'NULL'})", [uid] + te)
    for fid in rows("field"):  # a field stays while a task of the user still has a value in it
        c.execute("DELETE FROM list_fields WHERE id=? AND NOT EXISTS (SELECT 1 FROM task_field_values WHERE field_id=?)", (fid, fid))
    for sid in rows("section"):
        c.execute("DELETE FROM sections WHERE id=? AND NOT EXISTS (SELECT 1 FROM tasks WHERE section_id=?)", (sid, sid))
    lists = kept_lists = 0
    gone = []
    for lid in rows("list"):
        if c.execute("SELECT 1 FROM lists WHERE id=? AND owner_id=?", (lid, uid)).fetchone():
            if c.execute("SELECT 1 FROM tasks WHERE list_id=?", (lid,)).fetchone():
                kept_lists += 1
            else:
                lists += list_row_purge(c, lid, gone)  # 2.7.2: its project files leave the disk too
    c.execute("DELETE FROM sample_items WHERE user_id=?", (uid,))
    files += [p for _, _, ps in gone for p in ps]
    g.purge_icons = [(lid, icon) for lid, icon, _ in gone] if has_request_context() else []
    return {"tasks": len(mine), "lists": lists, "kept_lists": kept_lists, "kept_tasks": kept}, files


@app.post("/api/sample")
def sample_post():
    """Creates the sample project (idempotent: while one exists, {created: false, exists: true, list_id})."""
    c, uid = db(), me()
    c.execute("BEGIN IMMEDIATE")
    st = sample_state(c, uid)
    if st:
        c.rollback()
        return jsonify(ok=True, created=False, exists=True, list_id=st["lists"][0]["id"] if st["lists"] else None, sample=st)
    lid = sample_create(c, uid)
    bump(c)
    c.commit()
    print("sample created, user", uid, flush=True)
    return jsonify(ok=True, created=True, list_id=lid, sample=sample_state(c, uid))


@app.delete("/api/sample")
def sample_delete():
    c, uid = db(), me()
    c.execute("BEGIN IMMEDIATE")
    if not sample_state(c, uid):
        c.execute("DELETE FROM sample_items WHERE user_id=?", (uid,))
        c.commit()
        return err(tr("There is no sample project"), 404)
    counts, files = sample_remove(c, uid)
    bump(c)
    c.commit()
    unlink_files(files)
    for lid, icon in g.pop("purge_icons", []):
        list_icon_drop_file(lid, icon)
    print("sample removed, user", uid, "tasks", counts["tasks"], flush=True)
    return jsonify(ok=True, **counts)
