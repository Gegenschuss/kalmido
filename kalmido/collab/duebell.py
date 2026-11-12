"""2.1037.0 (#5801): deadlines in the bell. Two computed lines at the top of "For you": "{n} tasks due today" and "{n} tasks
overdue" -- no stored News item per task, no background run; the state is counted from the tasks when the bell's number is.

Counted: my open tasks (assigned to me, or nobody's in a list I own) of the lists I see (not archived, no sample items), due
today or before on my own clock (setting tz, core/usertz.py) -- the same set as the briefing's "today / overdue". Each of the
two lines counts 1 at the bell (not one per task, so the number stays small); news_unread_me (the bell, the app icon's
badge_count) adds them, the browser reads them with the News counts (key "due").

"Seen for today": a read mark of the shared core (obj_seen, kind 'due', ref_id 1 = today / 2 = overdue, core/objseen.py),
no table of its own. Its seen_id is day * DUE_DAY + the count seen (a high-water mark: a later day or more tasks on the
same day is always higher). A line counts again on the next day, or the same day once more tasks are due than were seen."""
from datetime import date

from flask import jsonify

from ..core.access import live_sql, tvis, vis_sql
from ..core.config import app
from ..core.db import body, db, err, usettings
from ..core.i18n import tr
from ..core.objseen import osn_mark
from ..core.usertz import user_now
from ..accounts.session import me
from .comments import collab_on
from .news import news_counts

DUE_LINES = {"today": 1, "overdue": 2}  # the line -> ref_id of its mark (obj_seen kind 'due')
DUE_DAY = 1_000_000  # seen_id = day ordinal * DUE_DAY + the count seen then


def due_counts(c, uid, s=None):
    """(today, overdue, day): my open tasks due today / before today on my clock (the briefing's set) and that day (ISO)."""
    s = s or usettings(c, uid)
    day = user_now(s).date().isoformat()
    mine = "((l.owner_id=? AND t.assignee_id IS NULL AND t.assignee_group_id IS NULL) OR t.assignee_id=?)"
    r = c.execute(f"""SELECT COUNT(*) FILTER (WHERE substr(t.due,1,10)=?), COUNT(*) FILTER (WHERE substr(t.due,1,10)<?)
                      FROM tasks t JOIN lists l ON l.id=t.list_id
                      WHERE t.status=0 AND {live_sql('t')} AND t.due IS NOT NULL AND substr(t.due,1,10)<=?
                        AND l.archived=0 AND t.list_id IN {vis_sql(ov=False)} AND {tvis(c, uid, 't.')}
                        AND t.id NOT IN (SELECT item_id FROM sample_items WHERE kind='task') AND {mine}""",
                  (day, day, day, uid, uid, uid, uid)).fetchone()
    return int(r[0] or 0), int(r[1] or 0), day


def _day_ord(day):
    return date.fromisoformat(day).toordinal()


def due_state(c, uid, s=None):
    """{day, today, overdue, seen_today, seen_overdue, n}: the counts, the count seen today per line (-1 = not seen today) and
    n = how many of the two lines count at the bell now. {} without the News (module collab off)."""
    s = s or usettings(c, uid)
    if not collab_on(s):
        return {}
    today, over, day = due_counts(c, uid, s)
    d0 = _day_ord(day)
    marks = {r[0]: int(r[1]) for r in c.execute("SELECT ref_id, seen_id FROM obj_seen WHERE kind='due' AND user_id=?", (uid,))}
    out = {"day": day, "today": today, "overdue": over}
    for k, ref in DUE_LINES.items():
        m = marks.get(ref, 0)
        out["seen_" + k] = m % DUE_DAY if m // DUE_DAY == d0 else -1
    out["n"] = sum(1 for k in DUE_LINES if out[k] > max(0, out["seen_" + k]))
    return out


def due_lines(c, uid, s=None):
    """How many of the two lines count at the bell (0..2) -- news_unread_me adds it."""
    return due_state(c, uid, s).get("n", 0)


@app.post("/api/news/due-seen")
def due_seen():
    """{line: today | overdue}: the line is seen for today (with the count it shows now). Answers the News counts."""
    b = body()
    line = b.get("line")
    if line not in DUE_LINES:
        return err(tr("Invalid data"))
    c = db()
    uid = me()
    s = usettings(c, uid)
    st = due_state(c, uid, s)
    if st:
        osn_mark(c, "due", DUE_LINES[line], uid, _day_ord(st["day"]) * DUE_DAY + min(st[line], DUE_DAY - 1))
        c.commit()
    return jsonify(ok=True, **news_counts(c, uid))
