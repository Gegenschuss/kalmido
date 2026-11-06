"""2.111.0 C (#2057): a reminder at a fixed time ("remind me Tue 9:00"), with or without a due date.

tasks.remind_at = the local date + time "YYYY-MM-DDTHH:MM" (the clock of the person it goes to, like due / due_time, 2.368.3
#2985; NULL = none). The watchdog
fires it once (key "at|<remind_at>" in tasks.reminded, like the offsets), to the same people, over the same channels and
with the same switches as the reminders before the due time; missed by more than 6 hours = skipped. A recurring task
moves it along with its due date when it is ticked or skipped (and back on undo)."""
import json
from datetime import date, datetime, timedelta

from ..core.config import PUBLIC_URL
from ..core.i18n import short_day, tr
from ..core.db import inbox_default
from ..tasks.validation import valid_plan_start
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from ..core.schema import USER_DEFAULTS  # 2.149.0 G (#2517): pulled up from functions
from ..core.usertz import hm_text, tz_gap, tz_of_s, user_now
from ..notify.push import _wd_fail  # 2.369.5 (#2517): pulled up from functions
from ..collab.news import notif_ok  # 2.369.5 (#2517): pulled up from functions

RAT_MISS_H = 6  # the same grace as the offset reminders


def rat_clean(v):
    """Client value -> column value: None / '' = none, else a valid local "YYYY-MM-DDTHH:MM" (BadInput otherwise)."""
    if v in (None, ""):
        return None
    if not valid_plan_start(v):
        raise BadInput(tr("Invalid value: {0}", tr("Reminder")))
    return v


def rat_key(v):
    return f"at|{v}"


def rat_shift(c, tid, old_due, new_due):
    """A recurring task moved from old_due to new_due: its fixed reminder moves by the same number of days."""
    row = c.execute("SELECT remind_at FROM tasks WHERE id=?", (tid,)).fetchone()
    if not row or not row["remind_at"] or not old_due or not new_due:
        return
    try:
        at = datetime.fromisoformat(row["remind_at"]) + (date.fromisoformat(new_due) - date.fromisoformat(old_due))
    except (ValueError, TypeError):
        return
    c.execute("UPDATE tasks SET remind_at=? WHERE id=?", (at.strftime("%Y-%m-%dT%H:%M"), tid))


def rat_tick(c, users, S, LG, now):
    """Watchdog section: the fixed-time reminders that are due now."""
    gap = tz_gap(S, now) + timedelta(hours=2)  # 2.368.3 (#2985): a first look wide enough for everybody's clock, rat_fire decides
    cut, old = (now + gap).strftime("%Y-%m-%dT%H:%M"), (now - timedelta(hours=RAT_MISS_H) - gap).strftime("%Y-%m-%dT%H:%M")
    rows = c.execute("""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox, l.owner_id AS list_owner, l.nag AS list_nag
                        FROM tasks t JOIN lists l ON l.id=t.list_id
                        WHERE t.status=0 AND t.deleted_at IS NULL AND t.remind_at IS NOT NULL AND t.remind_at<=? AND t.remind_at>=?
                          AND l.archived=0""", (cut, old)).fetchall()  # older than the grace: never sent (like a missed offset)
    for t in rows:
        try:
            rat_fire(c, t, users, S, LG, now)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "fixed reminder of task", t["id"], e)


def rat_fire(c, t, users, S, LG, now):
    from ..family.v1 import reminder_people
    from ..notify.push import notify, push_prio, reminder_recipient
    fired = json.loads(t["reminded"] or "[]")
    key = rat_key(t["remind_at"])
    if key in fired:
        return
    rcpt = reminder_recipient(c, t, users)
    at = datetime.fromisoformat(t["remind_at"]).replace(tzinfo=tz_of_s(S.get(rcpt)))
    if at > now:
        return
    fired.append(key)
    c.execute("UPDATE tasks SET reminded=? WHERE id=?", (json.dumps(fired[-20:]), t["id"]))
    c.commit()  # marked before sending: a failing channel never sends it twice
    if now - at > timedelta(hours=RAT_MISS_H):
        return
    for who in ([rcpt] if rcpt else []) + reminder_people(c, t, users, rcpt):
        sw, lgw = S.get(who, USER_DEFAULTS), LG.get(who, "en")
        if not notif_ok(c, who, sw, "reminder", "push", t["list_id"], own=who == rcpt):  # 2.266.0 (#2962)
            continue  # the same switch as the reminders before the due time
        lname = tr("Basket", lg=lgw) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
        if t["due"]:
            when = tr("all day", lg=lgw) if not t["due_time"] else tr("at {0}", hm_text(t["due_time"], sw), lg=lgw)
            day = tr("today", lg=lgw) if t["due"] == user_now(sw, now).date().isoformat() else short_day(date.fromisoformat(t["due"]), lgw)
            msg = tr("Due {0} {1} · {2}", day, when, lname, lg=lgw)
        else:
            msg = lname
        notify(who, t["title"], msg, push_prio(sw, 4 if t["priority"] >= 5 else None), f"{PUBLIC_URL}/#t/{t['id']}", s=sw,
               actions=([(tr("Snooze", lg=lgw), f"{PUBLIC_URL}/#snooze/{t['id']}")] if t["due"] else [])  # snoozing moves the due date
               + [(tr("Done|action", lg=lgw), f"{PUBLIC_URL}/#done/{t['id']}")],
               task=t["id"], due=t["due"] if t["repeat"] else None)
