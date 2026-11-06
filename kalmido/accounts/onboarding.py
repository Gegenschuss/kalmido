"""Onboarding, the sample project and the app's industry (2.578.0, #4573)."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from flask import g, has_request_context, jsonify, request

from ..core.config import app, TZ
from ..core.pg import insert_id, system_ctx
from ..core.i18n import lang, N_, tr
from ..core.db import body, bump, db, err, iso, iso_ms, local_now, now_utc, uset, usettings, write_lock
from ..accounts.session import me
from ..accounts.pictures import list_icon_drop_file
from ..core.access import acx_drop, collab_all, list_role, my_max_sort, time_all, WRITE_ROLES
from ..core.serializers import unlink_files
from ..core.errors import BadInput, Denied  # 2.578.0 (#4573)
from ..core.conflict import ccf_check  # 2.578.0 (#4573)
from ..core.orgcrypt import oc_json_store  # 2.578.0 (#4573)
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
         N_("Type it into the add bar (the + button on a phone): dates, times, !priority, #tags and ~project are recognised while you type."), 3, True, []),
        (N_("Swipe me left to reschedule") if touch else N_("Drag me onto Tomorrow in the sidebar"),
         N_("Swipe left for snooze, other dates and delete; long-press for the task’s menu, long-press and drag to reorder.") if touch
         else N_("Drag tasks onto a day, a project or another place in the list. Right-click is not needed: the … menu has the rest."), 1, True, []),
    ]
    if not touch:
        tt.append((N_("Press {0} to search and run commands"), N_("Projects, tasks, views and actions in one box. Press ? for all keyboard shortcuts."), 0, False, []))
    mods = [("habits", N_("Create a habit under Habits"), N_("Daily or a few times a week, with streaks.")),
            ("pomo", N_("Start a focus timer on a task"), N_("Task menu (…) > Start focus, or the Focus timer module.")),
            ("collab", N_("Share this project with someone"), N_("Project menu (…) > Sharing. Tasks in shared projects can be assigned and commented.")),
            ("time", N_("Start a timer on a task"), N_("Task menu (…) > Start timer; reports under Time tracking.")),
            ("timeline+deps", N_("Plan a project in the timeline"),
             N_("Edit project > View: Timeline. Drag the dot at the end of one bar onto another: the second task is then blocked by the first.")
             if not touch else
             N_("Edit project > View: Timeline. Long-press a bar and choose “Connect to…”, then tap the task it blocks."))]
    for k, t, d in mods:
        if all(x in feats for x in k.split("+")):
            tt.append((t, d, 0, False, []))
    tt.append((N_("Delete this project when you are done"), N_("Project menu (…) > Delete. Nothing else is affected."), 0, False, []))
    return tt


def _org_member(c, uid):
    """2.364.0 A (#3037): uid belongs to an organisation as a member (invited, placed in a team), not as its admin.
    2.453.0 (#3780): or is about to: a new account joins by accepting its invitation after the first start."""
    from ..accounts.orginvite import ojn_waiting
    if ojn_waiting(c, uid, plain=True):
        return True
    with system_ctx(c):  # memberships are structure (as accounts/orgs.py user_orgs / org_role)
        return bool(c.execute("SELECT 1 FROM org_members m JOIN orgs o ON o.id=m.org_id WHERE m.user_id=? AND o.retired_at IS NULL "
                              "AND COALESCE(m.role, 'member')<>'admin' LIMIT 1", (uid,)).fetchone())


@app.post("/api/onboarding")
def onboarding():
    b, c = body(), db()
    uid = me()
    write_lock(c, f"onboard:{uid}")  # 2.37.0 (#1150): was BEGIN IMMEDIATE
    again = b.get("again") is True and not g.user["kid"]  # 2.364.0 A (#3037): Settings > Help: the list on request, once more
    if usettings(c, uid).get("onboard") != "pending" and not again:
        c.rollback()
        return jsonify(ok=True, created=False)
    if g.user["kid"] or (_org_member(c, uid) and not again):  # 2.49.0 (#1537): a kid gets no "Getting started" list (its view shows none), only done
        uset(c, uid, "onboard", "done")
        if not g.user["kid"]:  # 2.364.0 A (#3037): an invited member neither (nor the sample project in the tour; Help still has both)
            uset(c, uid, "sample_ask", "0")
        bump(c)
        c.commit()
        return jsonify(ok=True, created=False)
    lg = lang(c, uid)
    feats = [f for f in usettings(c, uid)["features"].split(",") if f]
    feats = [f for f in feats if (f != "collab" or collab_all()) and (f != "time" or time_all())]
    touch, mac = b.get("touch") is True, b.get("mac") is True
    ts, day = iso(now_utc()), local_now().strftime("%Y-%m-%d")
    # time tracking / dependencies / custom fields on (e.g. "Projects & team"): the sample list is a project, so the
    # timer and dependency tips work right there
    kind = "project" if {"time", "deps", "fields"} & set(feats) else "list"
    lid = insert_id(c, "INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                    (tr("Getting started", lg=lg), "#2dd4bf", "", my_max_sort(c, uid) + 1, "list", ts, uid, kind))
    from ..accounts.orgs import ws_apply_default
    ws_apply_default(c, uid, lid)  # 2.28.0 (#935): the default workspace
    for i, (title, content, prio, due, subs) in enumerate(onboarding_tasks(feats, touch, mac)):
        t = tr(title, "⌘K" if mac else "Ctrl+K", lg=lg) if "{0}" in title else tr(title, lg=lg)
        tid = insert_id(c, """INSERT INTO tasks(list_id,title,content,priority,due,sort,created_at,updated_at,created_by)
                           VALUES(?,?,?,?,?,?,?,?,?)""", (lid, t, tr(content, lg=lg), prio, day if due else None, i, ts, ts, uid))
        log_act(c, tid, "created", uid=uid)
        for j, st in enumerate(subs):
            c.execute("""INSERT INTO tasks(list_id,parent_id,title,sort,created_at,updated_at,created_by)
                         VALUES(?,?,?,?,?,?,?)""", (lid, tid, tr(st, lg=lg), j, ts, ts, uid))
    uset(c, uid, "onboard", "done")
    bump(c)
    c.commit()
    return jsonify(ok=True, created=True, list_id=lid)


# ---------------------------------------------------------------- sample project (1.8.0)
# 2.578.0 (#4573): the variant follows the app's industry (SAMPLE_VARIANTS): "Example: Website relaunch for client Muster"
# without one, "Example: Image film for client Muster" with Film & Video. The film one: a realistic project list (sections, dates around today, start dates for the
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
        ("budget", 0, N_("Get the quotation and budget approved"), 5, None, 0, {
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
        ("grade", 3, N_("Colour grading and sound mix"), 1, 15, 17, {"effort": "m"}),
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


# 2.578.0 (#4573): the neutral sample (no industry chosen): "Example: Website relaunch for client Muster" with the same
# building blocks as the film one (sections, dependencies, subtasks, a checklist in the description, tags, budget, effort,
# a timed appointment, a repeating task, a comment, a time entry, a project status) plus a launch checklist. The image film
# with its shoot days and packing list is the sample of the industry Film & Video only (app_industry).
def _sample_tasks_neutral():
    """As _sample_tasks: the neutral client project."""
    return [
        ("brief", 0, N_("Kick-off with the client"), 3, -9, -8, {"done": -8, "tags": [N_("client")]}),
        ("concept", 0, N_("Write the concept and sitemap"), 5, -5, -1, {
            "tags": [N_("concept")], "content": N_("**Goal:** a clearer, faster website that brings more enquiries.\n\n- [x] Read the briefing notes\n- [ ] First draft of the sitemap\n- [ ] Internal review\n- [ ] Send it to the client\n\nPages: home, services, references and contact."),
            "subs": [(N_("Define the target audience"), True), (N_("Phrase the key message"), False),
                     (N_("Collect reference websites"), False)], "effort": "m"}),
        ("budget", 0, N_("Get the quotation and budget approved"), 5, None, 0, {
            "tags": [N_("client")], "budget": 9800,
            "comment": N_("The client agreed to the budget on the phone, the written approval follows.")}),
        ("content", 1, N_("Collect texts and pictures from the client"), 3, 1, 3, {"tags": [N_("client")]}),
        ("design", 1, N_("Design the page layouts"), 3, 0, 4, {"effort": "m"}),
        ("access", 1, N_("Get access to domain and hosting"), 1, None, 5, {"tags": [N_("organisation")]}),
        ("redirects", 1, N_("List the old pages for redirects"), 1, None, 2, {"tags": [N_("organisation")]}),
        ("workshop", 2, N_("Content workshop with the client"), 5, None, 8, {"time": "10:00", "dur": 180, "budget": 1200, "effort": "l"}),
        ("build", 2, N_("Build the pages"), 3, 9, 13, {"budget": 3600, "effort": "l"}),
        ("test", 3, N_("Test on phones and browsers"), 3, 14, 15, {"budget": 800, "effort": "m"}),
        ("legal", 3, N_("Check imprint and privacy policy"), 0, None, None, {}),
        ("speed", 3, N_("Optimise the loading speed"), 1, 15, 17, {"effort": "m"}),
        ("feedback", 4, N_("Feedback round with the client"), 5, None, 19, {"tags": [N_("client")]}),
        ("golive", 4, N_("Go live and switch the domain"), 3, None, 21, {}),
        ("call", None, N_("Weekly status call with the client"), 0, None, "tue", {"time": "10:00", "dur": 30,
                                                                                  "repeat": "FREQ=WEEKLY;BYDAY=TU"}),
    ]


SAMPLE_SECTIONS_NEUTRAL = (N_("Concept"), N_("Design|website project phase"), N_("Build|website project phase"),
                           N_("Test|website project phase"), N_("Approval"))
SAMPLE_DEPS_NEUTRAL = (("budget", "concept"), ("design", "budget"), ("build", "design"), ("test", "build"))
SAMPLE_CHECKLIST_NEUTRAL = (N_("Back up the old website"), N_("Set up the redirects"), N_("Send every form once"),
                            N_("Check phone, tablet and desktop"), N_("Check imprint and privacy policy"),
                            N_("Connect the visitor statistics"), N_("Submit the sitemap to search engines"),
                            N_("Tell the client's team"))
# per variant: project name, colour, tasks, sections, dependencies, checklist name + items, the time entry (task title,
# note), the project status note
SAMPLE_VARIANTS = {
    "film": {"name": N_("Example: Image film for client Muster"), "tasks": _sample_tasks, "sections": SAMPLE_SECTIONS,
             "deps": SAMPLE_DEPS, "check_name": N_("Example: Shoot day packing list"), "check": SAMPLE_PACKING,
             "time": (N_("Write the concept and treatment"), N_("First draft of the treatment")),
             "status": N_("Shoot dates confirmed with the client")},
    "": {"name": N_("Example: Website relaunch for client Muster"), "tasks": _sample_tasks_neutral,
         "sections": SAMPLE_SECTIONS_NEUTRAL, "deps": SAMPLE_DEPS_NEUTRAL, "check_name": N_("Example: Launch checklist"),
         "check": SAMPLE_CHECKLIST_NEUTRAL, "time": (N_("Write the concept and sitemap"), N_("First draft of the sitemap")),
         "status": N_("Launch date confirmed with the client")},
}


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
    """Creates the sample for uid (caller commits). Returns the id of the project list. 2.578.0 (#4573): the variant of the
    app's industry (app_industry): the image film only with Film & Video, else the neutral website relaunch."""
    from ..lists.fields import fmt_num
    var = SAMPLE_VARIANTS.get(app_industry(c, uid)) or SAMPLE_VARIANTS[""]
    c.execute("DELETE FROM sample_items WHERE user_id=?", (uid,))  # leftovers of a sample removed by hand
    lg = lang(c, uid)
    s = usettings(c, uid)
    feats = {f for f in s["features"].split(",") if f}
    feats = {f for f in feats if (f != "collab" or collab_all()) and (f != "time" or time_all())}
    project = bool({"time", "deps", "fields", "progress"} & feats)
    today = local_now().date()
    ts = iso(now_utc())
    day = lambda n: (today + timedelta(days=n)).isoformat() if n is not None else None  # noqa: E731
    track = lambda kind, iid: c.execute("INSERT INTO sample_items(user_id,kind,item_id) VALUES(?,?,?) ON CONFLICT DO NOTHING",  # noqa: E731
                                        (uid, kind, iid))
    srt = my_max_sort(c, uid)
    # 2.352.0 B (#2752): priority is every list's default sort now - the sample keeps Flow as its own sort (it shows the chain)
    lid = insert_id(c, "INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind,sort_mode) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (tr(var["name"], lg=lg), "#8b5cf6", "", srt + 1, "list", ts, uid, 0,
                     "project" if project else "list", "flow" if "deps" in feats else ""))
    from ..accounts.orgs import ws_apply_default
    ws_apply_default(c, uid, lid)  # 2.28.0 (#935): the default workspace
    track("list", lid)
    secs = []
    for i, n in enumerate(var["sections"]):
        secs.append(insert_id(c, "INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, tr(n, lg=lg), i + 1)))
        track("section", secs[-1])
    fields = {}
    if project and "fields" in feats:
        cur = s.get("time_currency") or "€"
        fields["budget"] = insert_id(c, "INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                                     (lid, tr("Budget", lg=lg), "number", json.dumps({"unit": cur[:12]}), 1, 1, ts))
        opts = [{"id": k, "name": tr(n, lg=lg), "color": col} for k, n, col in
                (("s", N_("Small"), "#22c55e"), ("m", N_("Medium"), "#f59e0b"), ("l", N_("Large"), "#ef4444"))]
        fields["effort"] = insert_id(c, "INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                                     (lid, tr("Effort", lg=lg), "select", json.dumps({"options": opts}, ensure_ascii=False), 1, 2, ts))
        for f in fields.values():
            track("field", f)
    ids = {}
    for i, (key, sec, title, prio, start, due, x) in enumerate(var["tasks"]()):
        if due == "tue":  # the next Tuesday (today, if it is one)
            due = (1 - today.weekday()) % 7
        done = x.get("done")
        tid = insert_id(c, """INSERT INTO tasks(list_id,section_id,title,content,priority,status,due,due_time,repeat,sort,created_at,
                           updated_at,completed_at,start,duration,created_by,completed_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (lid, secs[sec] if sec is not None else None, tr(title, lg=lg), tr(x["content"], lg=lg) if x.get("content") else "",
                         prio, 2 if done is not None else 0, day(due), x.get("time"), x.get("repeat") or "", i + 1, ts, ts,
                         iso(datetime.combine(today + timedelta(days=done), datetime.min.time().replace(hour=16), TZ).astimezone(timezone.utc))
                         if done is not None else None,
                         day(start), x.get("dur") if x.get("time") else None, uid, uid if done is not None else None))
        ids[key] = tid
        track("task", tid)
        if x.get("tags"):
            set_tags(c, tid, [tr(t, lg=lg) for t in x["tags"]], uid)
        for j, (st, sdone) in enumerate(x.get("subs") or []):
            sid = insert_id(c, """INSERT INTO tasks(list_id,section_id,parent_id,title,status,sort,created_at,updated_at,completed_at,
                               created_by,completed_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (lid, secs[sec] if sec is not None else None, tid, tr(st, lg=lg), 2 if sdone else 0, j + 1, ts, ts,
                             ts if sdone else None, uid, uid if sdone else None))
            track("task", sid)
        for fk in ("budget", "effort"):
            if fk in fields and x.get(fk) is not None:
                v = fmt_num(x[fk]) if fk == "budget" else x[fk]
                c.execute("INSERT INTO task_field_values(task_id,field_id,value) VALUES(?,?,?)", (tid, fields[fk], v))
        if x.get("comment") and "collab" in feats:
            c.execute("INSERT INTO comments(task_id,user_id,body,mentions,created_at) VALUES(?,?,?,?,?)",
                      (tid, uid, tr(x["comment"], lg=lg), "", iso(now_utc() - timedelta(hours=3))))
    if project and "deps" in feats:
        for a, b in var["deps"]:
            c.execute("INSERT INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                      (ids[a], ids[b], uid, ts))
    if project and "time" in feats:  # 1.5 h on the treatment yesterday afternoon
        st = datetime.combine(today - timedelta(days=1), datetime.min.time().replace(hour=14), TZ).astimezone(timezone.utc)
        eid = insert_id(c, """INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,"end",seconds,note,source,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (uid, ids["concept"], lid, tr(var["time"][0], lg=lg), iso(st),
                         iso(st + timedelta(minutes=90)), 5400, tr(var["time"][1], lg=lg), "manual", ts, ts))
        track("time", eid)
        c.execute("UPDATE lists SET time_tracking=1 WHERE id=?", (lid,))  # 2.41.0 (#1471): the sample tracks time
    if project and "progress" in feats:
        note = tr(var["status"], lg=lg)
        c.execute("UPDATE lists SET status='on_track', status_note=?, status_by=?, status_at=? WHERE id=?", (note, uid, ts, lid))
        c.execute("INSERT INTO list_status(list_id,user_id,status,note,created_at) VALUES(?,?,?,?,?)", (lid, uid, "on_track", note, ts))
    # the packing list (2.578.0 #4573: the neutral sample's launch checklist): a plain list with "Show completed at the bottom"
    # (2.7.2, #414; ticked items stay below and can be reused for the next shoot)
    cl = insert_id(c, "INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                   (tr(var["check_name"], lg=lg), "#f59e0b", "", srt + 2, "list", ts, uid, 1, "list"))
    from ..accounts.orgs import ws_apply_default
    ws_apply_default(c, uid, cl)  # 2.28.0 (#935): the default workspace
    track("list", cl)
    for i, n in enumerate(var["check"]):
        track("task", insert_id(c, "INSERT INTO tasks(list_id,title,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?)",
                                (cl, tr(n, lg=lg), i + 1, ts, ts, uid)))
    uset(c, uid, "sample_ask", "0")
    return lid


def sample_edited(c, ids):
    """2.530.0 B (#4315): the sample tasks of ids the person changed since: a later change (updated_at), a comment written
    after the task was made (the sample's own comment is older), a file."""
    if not ids:
        return set()
    q = ",".join("?" * len(ids))
    return {r[0] for r in c.execute(f"""SELECT t.id FROM tasks t WHERE t.id IN ({q}) AND (t.updated_at<>t.created_at
                                         OR EXISTS (SELECT 1 FROM comments m WHERE m.task_id=t.id AND m.created_at>t.created_at)
                                         OR EXISTS (SELECT 1 FROM attachments a WHERE a.task_id=t.id))""", ids)}


def sample_remove(c, uid):
    """Removes what the sample created (caller commits; returns (counts, files to unlink)).
    2.530.0 B (#4315): nothing goes for good at once any more -- the sample tasks go into the trash (trash_task, restorable
    there until the trash period ends), a sample project left without live tasks goes into the projects' trash with what the
    person added to it (files, notes, chat); the sample's time entry goes only while neither it nor its task was changed,
    else it stays. Fields and sections stay while a live task uses them (as before; a sample task restored from the trash
    comes back without a sample section / field that went)."""
    from ..tasks.lifecycle import otr_trash, trash_task  # one upward import (lists/listtrash.py otr_trash through lifecycle)
    rows = lambda kind: [r[0] for r in c.execute("SELECT item_id FROM sample_items WHERE user_id=? AND kind=?", (uid, kind))]  # noqa: E731
    mine = [t["id"] for t in c.execute(f"SELECT id, list_id, parent_id FROM tasks WHERE deleted_at IS NULL AND "
                                       f"id IN ({','.join('?' * len(rows('task'))) or 'NULL'})", rows("task")).fetchall()
            if list_role(c, t["list_id"], uid) in WRITE_ROLES]
    q = ",".join("?" * len(mine)) or "NULL"
    # tasks the user added below a sample task stay (as main tasks)
    kept = c.execute(f"UPDATE tasks SET parent_id=NULL WHERE parent_id IN ({q}) AND id NOT IN ({q})", mine + mine).rowcount
    edited = sample_edited(c, mine)
    te = rows("time")
    if te:  # unchanged entries of unchanged tasks only (updated_at = created_at: the sample's own)
        ex = f" AND (task_id IS NULL OR task_id NOT IN ({','.join('?' * len(edited))}))" if edited else ""  # NOT IN (NULL) holds never
        c.execute(f"DELETE FROM time_entries WHERE user_id=? AND id IN ({','.join('?' * len(te))}) AND updated_at=created_at{ex}",
                  [uid] + te + sorted(edited))
    mset = set(mine)
    for tid in [r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id IN ({q}) AND (parent_id IS NULL OR parent_id NOT IN ({q}))",
                                        mine + mine)]:
        trash_task(c, tid)  # its sample subtasks go along (do_delete)
    for tid in mset - {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id IN ({q}) AND deleted_at IS NOT NULL", mine)}:
        trash_task(c, tid)  # a sample subtask in another list the parent's trash left behind
    for fid in rows("field"):  # a field stays while a live task of the user still has a value in it
        c.execute("DELETE FROM list_fields WHERE id=? AND NOT EXISTS (SELECT 1 FROM task_field_values v JOIN tasks t ON t.id=v.task_id "
                  "WHERE v.field_id=? AND t.deleted_at IS NULL)", (fid, fid))
    for sid in rows("section"):
        c.execute("DELETE FROM sections WHERE id=? AND NOT EXISTS (SELECT 1 FROM tasks WHERE section_id=? AND deleted_at IS NULL)", (sid, sid))
    lists = kept_lists = 0
    for lid in rows("list"):
        if c.execute("SELECT 1 FROM lists WHERE id=? AND owner_id=? AND deleted_at IS NULL", (lid, uid)).fetchone():
            if c.execute("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NULL", (lid,)).fetchone():
                kept_lists += 1
            else:  # into the projects' trash (archived, as a delete in the app): it comes back there with its tasks
                c.execute("UPDATE lists SET archived=1 WHERE id=?", (lid,))
                ts = otr_trash(c, lid, uid)
                c.execute("UPDATE tasks SET deleted_at=? WHERE list_id=? AND id IN (" + q + ")", [ts, lid] + mine)  # restored with it
                lists += 1
    c.execute("DELETE FROM sample_items WHERE user_id=?", (uid,))
    if has_request_context():
        g.purge_icons = []
    return {"tasks": len(mine), "lists": lists, "kept_lists": kept_lists, "kept_tasks": kept}, []


@app.post("/api/sample")
def sample_post():
    """Creates the sample project (idempotent: while one exists, {created: false, exists: true, list_id})."""
    c, uid = db(), me()
    write_lock(c, f"sample:{uid}")
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
    write_lock(c, f"sample:{uid}")
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


# ---------------------------------------------------------------- the app's industry (2.578.0, #4573)
# Decided 04.11.2026: the industry is one switch for the whole app (default: none). Its one truth is the setting
# industry_packs of the office area (office/model.py office_settings, the same list the pack cards of Office > Settings
# switch): the industry = the first built-in pack in it ("film"); own packs of the data folder stay office extras. The area
# is the one office/model.py office_where picks (the workspace's organisation, else the person's own office), read here
# without creating anything. Only with Film & Video: the image film sample with its packing list and the shoot calculation
# (office/sheet.py dk_enabled reads the same list). Accounts and organisations that use the film pack today keep it: their
# list holds "film" already, so nothing is migrated; new ones start without.
IND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "office", "packs", "industry")
IND_NO_RIGHT = N_("Only an admin of the organisation chooses its industry")
IND_NO_AREA = N_("Choose a workspace first: the industry belongs to an organisation or to your own area")
_ind_cache = {}


def ind_codes():
    """The industries one can choose: the shipped industry packs (office/packs/industry/<code>.json), e.g. ("film",)."""
    if "codes" not in _ind_cache:
        try:
            _ind_cache["codes"] = tuple(sorted(f[:-5] for f in os.listdir(IND_DIR) if f.endswith(".json")))
        except OSError:
            _ind_cache["codes"] = ()
    return _ind_cache["codes"]


def ind_choices(lg):
    """[{code, name}] of the industries in language lg (the pack's own name; English when the language is missing)."""
    out = []
    for code in ind_codes():
        if code not in _ind_cache:
            try:
                with open(os.path.join(IND_DIR, code + ".json"), encoding="utf-8") as f:
                    _ind_cache[code] = json.load(f).get("name") or {}
            except (OSError, ValueError):
                _ind_cache[code] = {}
        nm = _ind_cache[code]
        out.append({"code": code, "name": nm.get(lg) or nm.get("en") or code})
    return out


def ind_area(c, uid):
    """(office area id | None, may choose) of uid's industry: the area office/model.py office_where picks; the person's own
    office may be None while it was never made (then it is made on the first choice). A kid or an agent never chooses."""
    from ..accounts.orgs import org_role, user_orgs  # orgs comes later in ORDER
    u = getattr(g, "user", None) if has_request_context() else None
    may = u is None or not (("kid" in u.keys() and u["kid"]) or (u["kind"] if "kind" in u.keys() else "user") == "agent")
    orgs = user_orgs(c, uid)
    ws = (usettings(c, uid).get("workspace") or "").strip()
    m = re.fullmatch(r"org:(\d{1,9})", ws)
    if m and int(m.group(1)) in orgs:
        oid = int(m.group(1))
    elif ws == "private" or not orgs:
        with system_ctx(c):  # the person's own hidden area (office/model.py pb_personal)
            r = c.execute("SELECT id FROM orgs WHERE personal_of=?", (uid,)).fetchone()
        return (r[0] if r else None), may
    elif len(orgs) == 1:
        oid = orgs[0]
    else:
        return None, False
    return oid, may and org_role(c, uid, oid) == "admin"


def _ind_data(c, oid):
    """(office_settings.data of area oid as stored, its updated_at); the encrypted keys stay as they are. Read as structure:
    oid is uid's own area (ind_area checked the membership), also an organisation the setup made in this transaction."""
    if not oid:
        return {}, None
    with system_ctx(c):
        r = c.execute("SELECT data, updated_at FROM office_settings WHERE org_id=?", (oid,)).fetchone()
    try:
        d = json.loads(r["data"]) if r and r["data"] else {}
    except ValueError:
        d = {}
    return (d if isinstance(d, dict) else {}), (r["updated_at"] if r else None)


def ind_of_area(c, oid):
    """The industry of office area oid: the first built-in pack switched on there, "" = none."""
    packs = _ind_data(c, oid)[0].get("industry_packs")
    return next((x for x in packs if x in ind_codes()), "") if isinstance(packs, list) else ""


def app_industry(c, uid):
    """THE read point of the app's industry for uid ("" = none, "film" = Film & Video): the industry of uid's area."""
    return ind_of_area(c, ind_area(c, uid)[0])


def ind_state(c, uid):
    """The field industry of /api/state and GET /api/industry."""
    oid, may = ind_area(c, uid)
    return {"code": ind_of_area(c, oid), "can_set": bool(may), "choices": ind_choices(lang(c, uid)),
            "updated_at": _ind_data(c, oid)[1]}


def ind_set(c, uid, code, b=None):
    """Sets uid's industry ("" = none; caller commits). Only the built-in packs change in industry_packs, own packs stay.
    b: the request body (expect_updated_at = the version read, 409 when the settings moved on). -> True when it changed."""
    code = (code or "").strip().lower() if isinstance(code, str) else code
    if code not in ("",) + ind_codes():
        raise BadInput(tr("Invalid value: {0}", "industry"))
    oid, may = ind_area(c, uid)
    if not may:
        raise Denied(403, tr(IND_NO_AREA if oid is None and _ind_orgs(c, uid) else IND_NO_RIGHT))
    if oid is None:  # the person's own office, made on the first choice (as office/model.py pb_personal)
        with system_ctx(c):
            c.execute("INSERT INTO orgs(name,icon,created_at,personal_of) VALUES(?,?,?,?) ON CONFLICT (personal_of) WHERE personal_of IS NOT NULL DO NOTHING",
                      (f"private-{int(uid)}", "", iso(now_utc()), uid))
            oid = c.execute("SELECT id FROM orgs WHERE personal_of=?", (uid,)).fetchone()[0]
        c.commit()  # the area exists before anything is written into it
        acx_drop()
    write_lock(c, f"office_packs_{int(oid)}")  # the locks of PUT /api/office/settings, in its order
    write_lock(c, f"office_settings_{int(oid)}")
    d, at = _ind_data(c, oid)
    ccf_check(b, at, "industry", lambda: ind_state(c, uid))
    cur = [x for x in d.get("industry_packs") or [] if isinstance(x, str)] if isinstance(d.get("industry_packs"), list) else []
    new = [x for x in cur if x not in ind_codes()] + ([code] if code else [])
    if new == cur:
        return False
    d["industry_packs"] = new
    with system_ctx(c):  # as _ind_data: the area is uid's own, the admin role was checked (ind_area)
        c.execute("INSERT INTO office_settings(org_id, data, updated_at) VALUES(?,?,?) ON CONFLICT(org_id) DO UPDATE SET data=excluded.data, "
                  "updated_at=excluded.updated_at", (oid, json.dumps(oc_json_store(c, oid, "office_settings", "data", d), ensure_ascii=False), iso_ms(now_utc())))
    return True


def _ind_orgs(c, uid):
    """True when uid has several organisations (the workspace "all" names no area)."""
    from ..accounts.orgs import user_orgs  # orgs comes later in ORDER
    return len(user_orgs(c, uid)) > 1


@app.get("/api/industry")
def industry_get():
    """{industry: {code, can_set, choices: [{code, name}], updated_at}} -- the app's industry of my area."""
    c = db()
    return jsonify(industry=ind_state(c, me()))


@app.put("/api/industry")
def industry_put():
    """{industry: "" | "film", expect_updated_at?} -- chooses the industry of my area (an organisation's admin, a person
    without organisation for her own area). 403 for members, kids and agents; 409 {industry: the current} when the
    settings changed since expect_updated_at."""
    c, uid, b = db(), me(), body()
    if not isinstance(b, dict) or "industry" not in b:
        return err(tr("Invalid value: {0}", "industry"))
    changed = ind_set(c, uid, b.get("industry"), b)
    if changed:
        bump(c)
    c.commit()
    return jsonify(ok=True, changed=changed, industry=ind_state(c, uid))
