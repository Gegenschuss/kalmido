"""The module "Family": family fields of tasks, kid stars, occasions, shopping, packing lists, setup purpose, overview."""
import json
import re
from datetime import date, datetime, timedelta
from flask import g, has_request_context

from ..core.config import PUBLIC_URL
from ..core.i18n import lang, LANGS, N_, tr
from ..core.db import iso, local_now, now_utc, uset, usettings
from ..accounts.session import me, user_public
from ..core.access import collab_all, Denied, list_people, my_max_sort, need_list, vis_sql, wr_sql
from ..core.serializers import load_tasks
from ..core.state import visible_lists
from ..lists.lists import list_created, clean_folder, LIST_NAME_MAX
from ..tasks.validation import as_int, DATE_MIN_Y, log_act, rr_problem, rr_rule, TITLE_MAX, valid_date
from ..collab.comments import lang_of, user_names
from ..personal.timetrack import BadInput
from ..accounts.onboarding import sample_create, sample_state
from ..lists.templates import ptype_create, PTYPE_NAMES
from ..notify.push import push_prio, push_reachable
from ..agents.core import agent_ids, is_agent


# ---------------------------------------------------------------- 2.19.0 (#653): the module "Family"
# A module like Habits (features key "family", off by default; the setup question "What do you use Kalmido for?" turns it
# on for "Family"). Everything is made of the usual objects, so calendar, reminders, pushes, sharing, the API and CalDAV
# keep working:
#   birthdays / anniversaries = yearly tasks with tasks.fam {kind, name, year, lead, src?}; the age ("turns 80") is the
#     due year minus the year; gift ideas are the subtasks (kept ticked when the year rolls on: what was given stays);
#     optional import from CardDAV contacts (BDAY / ANNIVERSARY, contact_srcs: address + login, password sealed like a
#     calendar subscription, synced by hand and once a day)
#   household rotation = tasks.rotation {who: [user ids], mode: done | week, i, wk}: the assignee moves on to the next
#     person when the task is completed (mode done) or every Monday (mode week)
#   kids = users.kid: an account that only takes part (participant role in every list, enforced), a simple view in the
#     app, stars for completed tasks (tasks.stars, default 1; ledger kid_stars) and rewards the parents (kid_parents,
#     admins) approve; rewards: kid_rewards
#   family events = task_people: who comes along; they see the task (also as participants) and get its reminders
#   shopping = a list with lists.family 'shopping': its sections are the shop areas (defaults on creation), a new item
#     goes to the area it had last time (shop_memory), the app has a shopping mode with big ticks
#   household deadlines = tasks with fam {kind: deadline, type, who, expires, notice, lead} from built-in types (passport,
#     ID card, car inspection, insurance, contract, other); files are attached like on any task
#   meal plan = tasks of a list with family 'meals' (due = the day, notes = the ingredients); one tap puts the
#     ingredients on a shopping list (POST /api/tasks/<id>/to-shopping, open items are not doubled)
#   packing lists = built-in templates (holiday, pool, daycare, camping, business trip) -> a list with "done at the
#     bottom" (reusable)
# Rights: the usual list roles; rewards / stars of a kid only its parents (and admins); a kid requests rewards.
from dateutil.relativedelta import relativedelta  # noqa: E402

FAM_LIST_KINDS = ("", "shopping", "meals", "birthdays", "household", "packing")
FAM_OCC = ("birthday", "anniversary")
FAM_NAME_MAX, FAM_NOTE_MAX = 100, 200
FAM_LEAD_MAX = 365
STARS_MAX = 50
ROT_MAX = 20
KID_REWARDS_MAX, REWARD_COST_MAX = 50, 1000
CONTACT_SRCS_MAX, CONTACT_CARDS_MAX = 5, 3000
CONTACT_EVERY_MIN = 24 * 60  # minutes between automatic syncs of an address book (CAL_TICK seconds per minute)
SHOP_AREAS = (N_("Fruit & vegetables"), N_("Bread & bakery"), N_("Dairy & eggs"), N_("Meat & fish"), N_("Frozen"),
              N_("Pantry"), N_("Drinks"), N_("Household & drugstore"))
# deadline types: name, title template ({0} = who / what), lead days, repeat, notice months (0 = the date itself is due)
FAM_DL = {
    "passport": (N_("Passport"), N_("Renew the passport: {0}"), 90, "", 0),
    "id_card": (N_("ID card"), N_("Renew the ID card: {0}"), 60, "", 0),
    "car": (N_("Car inspection"), N_("Car inspection: {0}"), 30, "FREQ=YEARLY;INTERVAL=2", 0),
    "insurance": (N_("Insurance"), N_("Cancel or renew the insurance: {0}"), 21, "FREQ=YEARLY", 3),
    "contract": (N_("Contract"), N_("Cancel or renew the contract: {0}"), 14, "FREQ=YEARLY", 1),
    "other": (N_("Other deadline"), "{0}", 14, "", 0),
}
# packing list templates: name, [(section, [items])]
PACKING = {
    "holiday": (N_("Holiday"), [
        (N_("Documents"), (N_("Passports or ID cards"), N_("Tickets and bookings"), N_("Health insurance cards"), N_("Cash and cards"))),
        (N_("Clothes"), (N_("Underwear and socks"), N_("T-shirts"), N_("Trousers"), N_("Jumper"), N_("Rain jacket"), N_("Pyjamas"), N_("Swimwear"))),
        (N_("Toiletries"), (N_("Toothbrush and toothpaste"), N_("Sun cream"), N_("Medicines"), N_("Plasters"))),
        (N_("Electronics"), (N_("Phone chargers"), N_("Power bank"), N_("Headphones"), N_("Travel adapter"))),
        (N_("For the kids"), (N_("Cuddly toy"), N_("Snacks for the journey"), N_("Books and games")))]),
    "pool": (N_("Swimming pool"), [
        ("", (N_("Swimwear"), N_("Towels"), N_("Shower gel and shampoo"), N_("Flip-flops"), N_("Swimming goggles"),
              N_("Sun cream"), N_("Water bottle"), N_("Snacks"), N_("Coin for the locker"), N_("Hairbrush")))]),
    "daycare": (N_("Daycare"), [
        ("", (N_("Change of clothes"), N_("Nappies and wipes"), N_("Indoor shoes"), N_("Rain gear"), N_("Sun hat"),
              N_("Water bottle"), N_("Lunch box"), N_("Cuddly toy"), N_("Sun cream")))]),
    "camping": (N_("Camping"), [
        (N_("Sleeping"), (N_("Tent"), N_("Sleeping bags"), N_("Sleeping mats"), N_("Pillows"))),
        (N_("Kitchen"), (N_("Camping stove and gas"), N_("Lighter"), N_("Pots and cutlery"), N_("Washing-up bowl"), N_("Bin bags"))),
        (N_("Other"), (N_("Torch or head torch"), N_("First aid kit"), N_("Insect repellent"), N_("Rope and pegs")))]),
    "business": (N_("Business trip"), [
        ("", (N_("Laptop and charger"), N_("Phone chargers"), N_("Business clothes"), N_("Documents for the meeting"),
              N_("Tickets and bookings"), N_("Toiletries"), N_("Headphones")))]),
}
# what each answer of "What do you use Kalmido for?" switches on / off (agents stay as they are)
PURPOSES = ("me", "home", "family", "team", "software")  # 2.22.0 (#741): "home"
_LIFE = ("contracts", "home", "care", "health", "review", "travel", "reading")  # 2.22.0 (#663): Home & life
PURPOSE_MODS = ("cal", "timeline", "matrix", "kanban", "habits", "pomo", "stats", "comments", "collab", "time", "progress",
                "deps", "fields", "family", "events", "contacts") + _LIFE
PURPOSE_ON = {"me": ("cal", "events", "contacts"),
              "home": ("cal", "events", "contacts", "habits") + _LIFE,
              "family": ("cal", "habits", "comments", "collab", "family", "events", "contacts", "contracts", "home", "travel"),
              # 2.25.0 (UX-25): a package holds only what its name promises (no habits, focus timer, matrix, statistics)
              "team": ("cal", "timeline", "kanban", "comments", "collab", "time", "progress", "deps", "fields", "events", "contacts"),
              "software": ("cal", "timeline", "kanban", "comments", "collab", "time", "progress", "deps", "fields", "events", "contacts")}


# 2.19.0: what a child account may change: tick / untick (and undo) the tasks it sees, ask for a reward, its own
# account (name, password, picture, sign-in, push, settings), the news it has read. Everything else is read-only.
KID_WRITE = re.compile(r"^/api/(auth/.+|me|me/(avatar|2fa/.+|passkeys(/.*)?)|push/.+|news/(read|dismiss)|settings"
                       r"|tasks/\d+/(complete|reopen|undo)|family/rewards/\d+/request)$")


def is_kid(c, uid):
    r = c.execute("SELECT kid FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return bool(r and r[0])


def kid_parents(c, kid):
    return [r[0] for r in c.execute("""SELECT p.parent_id FROM kid_parents p JOIN users u ON u.id=p.parent_id
                                       WHERE p.kid_id=? AND u.disabled=0 ORDER BY p.parent_id""", (kid,))]


def parent_of(c, uid, kid):
    """uid may look after kid: a parent of it, or an admin."""
    if not is_kid(c, kid) or uid == kid:
        return False
    u = c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    return bool(u and u[0]) or uid in kid_parents(c, kid)


def need_kid(c, kid, parent=True):
    """404 unless kid is a kid account the current user looks after (parent) or is (parent=False also lets the kid in)."""
    if not is_kid(c, kid) or not (parent_of(c, me(), kid) or (not parent and kid == me())):
        raise Denied(404)


def kid_set(c, uid, on, parents=None):
    """Admins: make uid a kid account (or an ordinary one again) and set who looks after it. Error text or None."""
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if on:
        if u["is_admin"]:
            return tr("A child account cannot be an admin")
        if is_agent(u):
            return tr("An agent cannot be a child account")
    if parents is not None:
        if not isinstance(parents, list) or len(parents) > 20 or any(isinstance(x, bool) or not isinstance(x, int) for x in parents):
            return tr("Invalid value: {0}", "parents")
        for p in parents:
            r = c.execute("SELECT kind, kid, disabled FROM users WHERE id=?", (p,)).fetchone()
            if not r or p == uid or r["kind"] == "agent" or r["kid"] or r["disabled"]:
                return tr("Parents must be active people without a child account")
    c.execute("UPDATE users SET kid=? WHERE id=?", (1 if on else 0, uid))
    if on:
        kid_force_participant(c, uid)
        if parents is None and not kid_parents(c, uid) and has_request_context():
            parents = [me()]
    if parents is not None:
        c.execute("DELETE FROM kid_parents WHERE kid_id=?", (uid,))
        for p in dict.fromkeys(parents):
            c.execute("INSERT INTO kid_parents(kid_id,parent_id) VALUES(?,?)", (uid, p))
    return None


def kid_balance(c, kid):
    return c.execute("SELECT COALESCE(SUM(delta),0) FROM kid_stars WHERE kid_id=?", (kid,)).fetchone()[0]


def kid_force_participant(c, kid):
    """A kid takes part in shared lists only as a participant (sees only what is assigned to it or where it comes along)."""
    c.execute("""UPDATE list_members SET role='participant',
                 own_role=CASE WHEN own_role IS NULL THEN NULL ELSE 'participant' END,
                 grole=CASE WHEN grole IS NULL THEN NULL ELSE 'participant' END WHERE user_id=?""", (kid,))


def _jparse(v):
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v) if v else None
    except ValueError:
        return None


# ---- tasks: the family fields (fam, rotation, stars, people)
def clean_fam(v):
    """tasks.fam from a client: {kind: birthday | anniversary, name, year?, lead?} or {kind: deadline, type, who?, expires?,
    notice?, lead?}; null / '' / {} = none. Returns the stored JSON text."""
    if v in (None, "", {}):
        return ""
    if isinstance(v, str):
        v = _jparse(v)
    bad = BadInput(tr("Invalid value: {0}", "family"))
    if not isinstance(v, dict):
        raise bad
    k = v.get("kind")
    out = {"kind": k}
    from ..life.model import LIFE_FAM, life_clean_fam  # 2.22.0 (#663): the kinds of "Home & life"
    if k in LIFE_FAM:
        return life_clean_fam(v)
    if k in FAM_OCC:
        allowed = {"kind", "name", "year", "lead", "src", "card"}
        name = v.get("name", "")
        if not isinstance(name, str):
            raise bad
        out["name"] = re.sub(r"\s+", " ", name).strip()[:FAM_NAME_MAX]
        y = v.get("year")
        if y not in (None, ""):
            y = as_int(y, "year", DATE_MIN_Y, local_now().year)
            out["year"] = y
        if isinstance(v.get("src"), str) and v["src"]:
            out["src"] = v["src"][:200]
        if isinstance(v.get("card"), str) and v["card"]:
            out["card"] = v["card"][:200]  # the vCard UID of an imported contact (kept for a later contacts module)
    elif k == "deadline":
        allowed = {"kind", "type", "who", "expires", "notice", "lead"}
        if v.get("type", "other") not in FAM_DL:
            raise bad
        out["type"] = v.get("type", "other")
        who = v.get("who", "")
        if not isinstance(who, str):
            raise bad
        out["who"] = re.sub(r"\s+", " ", who).strip()[:FAM_NAME_MAX]
        if v.get("expires") not in (None, ""):
            if not valid_date(v["expires"]):
                raise bad
            out["expires"] = v["expires"]
        if v.get("notice") not in (None, ""):
            out["notice"] = as_int(v["notice"], "notice", 0, 24)
    else:
        raise bad
    if set(v) - allowed:
        raise bad
    if v.get("lead") not in (None, ""):
        out["lead"] = as_int(v["lead"], "lead", 0, FAM_LEAD_MAX)
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def clean_rotation(v):
    """The shape of tasks.rotation from a client ({who: [ids], mode, i?}); the people are checked against the list later
    (rot_apply). null / '' = no rotation."""
    if v in (None, "", {}):
        return ""
    if isinstance(v, str):
        v = _jparse(v)
    bad = BadInput(tr("Invalid value: {0}", "rotation"))
    if not isinstance(v, dict) or set(v) - {"who", "mode", "i", "wk"}:
        raise bad
    who = v.get("who")
    if not isinstance(who, list) or not 2 <= len(who) <= ROT_MAX or any(isinstance(x, bool) or not isinstance(x, int) or x < 1 for x in who) \
            or len(set(who)) != len(who):
        raise BadInput(tr("Taking turns needs at least two people"))
    mode = v.get("mode", "done")
    if mode not in ("done", "week"):
        raise bad
    i = v.get("i")  # null = keep the turn where it is (or with the current assignee)
    if i is not None and (isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(who)):
        raise bad
    return json.dumps({"who": who, "mode": mode, "i": i}, separators=(",", ":"))


def iso_week(d=None):
    d = d or local_now().date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def rot_apply(c, f, cur, lid):
    """apply_update / task_create: a new rotation (f["rotation"]) is checked against the people of list lid and sets the
    assignee to the person whose turn it is (the current assignee keeps it when they are in the new order). Error text."""
    if "rotation" not in f:
        if cur is not None and cur["rotation"] and lid != cur["list_id"]:  # moved: only people of the new list stay in
            r = _jparse(cur["rotation"]) or {}
            ppl = list_people(c, lid)
            who = [x for x in r.get("who", []) if x in ppl]
            f["rotation"] = json.dumps({**r, "who": who, "i": 0}, separators=(",", ":")) if len(who) >= 2 else ""
        return None
    if not f["rotation"]:
        return None
    r = json.loads(f["rotation"])
    if not collab_all():
        return tr("Collaboration is turned off on this server (an admin can turn it on)")
    ppl = list_people(c, lid)
    agents = agent_ids(c)
    if any(x not in ppl or x in agents for x in r["who"]):
        return tr("Only people who share this list can take turns")
    if any(c.execute("SELECT disabled FROM users WHERE id=?", (x,)).fetchone()[0] for x in r["who"]):
        return tr("Only people who share this list can take turns")
    old = _jparse(cur["rotation"]) if cur is not None and cur["rotation"] else None
    have = f.get("assignee_id", cur["assignee_id"] if cur is not None else None)
    if r["i"] is None:
        if old and old.get("who") == r["who"] and 0 <= (old.get("i") or 0) < len(r["who"]):
            r["i"] = old.get("i") or 0
        else:
            r["i"] = r["who"].index(have) if have in r["who"] else 0
    if r["mode"] == "week":
        r["wk"] = old.get("wk") if old and old.get("mode") == "week" and old.get("wk") else iso_week()
    f["rotation"] = json.dumps(r, separators=(",", ":"))
    f["assignee_id"] = r["who"][r["i"]]
    f["assignee_group_id"] = None
    return None


def rot_next(c, t):
    """(next assignee, new rotation JSON) after one turn of task row t, skipping people who lost the list; None = no change."""
    r = _jparse(t["rotation"])
    if not r or not r.get("who"):
        return None
    ppl = list_people(c, t["list_id"])
    who, n = r["who"], len(r["who"])
    for step in range(1, n + 1):
        j = (r.get("i", 0) + step) % n
        u = c.execute("SELECT disabled FROM users WHERE id=?", (who[j],)).fetchone()
        if who[j] in ppl and u and not u[0]:
            r["i"] = j
            return who[j], json.dumps(r, separators=(",", ":"))
    return None


def people_set(c, tid, lid, v):
    """task_people of task tid (list lid): [user ids] of people who share the list (who comes along). Error text or None."""
    if v in (None, ""):
        v = []
    if not isinstance(v, list) or len(v) > 50 or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        return tr("Invalid value: {0}", "people")
    ppl = list_people(c, lid)
    agents = agent_ids(c)
    if any(x not in ppl or x in agents for x in v):
        return tr("Only people who share this list can come along")
    c.execute("DELETE FROM task_people WHERE task_id=?", (tid,))
    for x in dict.fromkeys(v):
        c.execute("INSERT OR IGNORE INTO task_people(task_id,user_id) VALUES(?,?)", (tid, x))
    return None


def people_of(c, ids):
    out = {}
    if not ids:
        return out
    ids = list(ids)
    for i in range(0, len(ids), 900):
        part = ids[i:i + 900]
        for r in c.execute(f"SELECT task_id, user_id FROM task_people WHERE task_id IN ({','.join('?' * len(part))}) ORDER BY user_id", part):
            out.setdefault(r[0], []).append(r[1])
    return out


def fam_task_out(d):
    """load_tasks / task_dict: fam and rotation as objects (absent when empty), stars only when set."""
    for k in ("fam", "rotation"):
        if k in d:
            v = _jparse(d[k]) if d[k] else None
            if v:
                d[k] = v
            else:
                d.pop(k, None)
    if d.get("stars") is None:
        d.pop("stars", None)
    return d


# ---- stars of kids
def stars_earn(c, t, at):
    """do_complete: a kid completed task t (row before the change): stars (tasks.stars, default 1) into the ledger."""
    uid = me() if has_request_context() and getattr(g, "user", None) else None
    stars_add(c, uid, t, at)


def stars_add(c, kid, t, at):
    """The stars of task t for kid (a kid account) at the completion time at."""
    if not kid or not is_kid(c, kid):
        return
    n = t["stars"] if t["stars"] is not None else 1
    if n > 0:
        c.execute("INSERT INTO kid_stars(kid_id,delta,kind,task_id,title,by_id,at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (kid, n, "task", t["id"], (t["title"] or "")[:200], kid, at, iso(now_utc())))


def stars_revoke(c, tid, at=None, kid=None):
    """A completion taken back (reopen / undo): its stars leave the ledger again (the newest row of that task / moment)."""
    q, a = "SELECT id FROM kid_stars WHERE task_id=? AND kind='task'", [tid]
    if at:
        q += " AND at=?"
        a.append(at)
    if kid:
        q += " AND kid_id=?"
        a.append(kid)
    r = c.execute(q + " ORDER BY id DESC LIMIT 1", a).fetchone()
    if r:
        c.execute("DELETE FROM kid_stars WHERE id=?", (r[0],))


# ---- occasions (birthdays, anniversaries)
def occ_next(month, day, today=None):
    """The next date (today included) of a yearly day; 29 February falls on the 28th in other years."""
    today = today or local_now().date()
    for y in (today.year, today.year + 1, today.year + 2):
        try:
            d = date(y, month, day)
        except ValueError:
            d = date(y, month, 28)
        if d >= today:
            return d
    return date(today.year + 1, month, min(day, 28))


def occ_rule(month, day):
    return "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1" if (month, day) == (2, 29) else "FREQ=YEARLY"


def fam_list(c, uid, kind, create=True):
    """The first list of family kind `kind` the user may write (own first), created when missing (create)."""
    r = c.execute(f"""SELECT id FROM lists WHERE family=? AND archived=0 AND id IN {wr_sql()}
                      ORDER BY owner_id!=?, id LIMIT 1""", (kind, uid, uid, uid)).fetchone()
    if r:
        return r[0]
    if not create:
        return None
    return fam_list_create(c, uid, kind)


FAM_LIST_NAMES = {"shopping": N_("Shopping list"), "meals": N_("Meal plan"), "birthdays": N_("Birthdays"),
                  "household": N_("Household"), "packing": N_("Packing list")}
FAM_LIST_COLORS = {"shopping": "#22c55e", "meals": "#f59e0b", "birthdays": "#ec4899", "household": "#0ea5e9", "packing": "#8b5cf6"}


def fam_list_create(c, uid, kind, name=None, folder=""):
    lg = lang(c, uid)
    lid = c.execute("""INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind,family)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (name or tr(FAM_LIST_NAMES[kind], lg=lg), FAM_LIST_COLORS.get(kind, ""), folder, my_max_sort(c, uid) + 1, "list",
                     iso(now_utc()), uid, 1 if kind in ("shopping", "packing") else 0, "list", kind)).lastrowid
    list_created(c, uid, lid)  # 2.22.0 (#747): no shop areas by itself (the list bar's "Add shop areas" adds them); 2.25.0 (#931)
    return lid


def shop_areas_add(c, lid, lg):
    """The default shop areas as the sections of a shopping list (the ones it already has by name are skipped)."""
    have = {r[0].strip().casefold() for r in c.execute("SELECT name FROM sections WHERE list_id=?", (lid,))}
    n = c.execute("SELECT COALESCE(MAX(sort),0) FROM sections WHERE list_id=?", (lid,)).fetchone()[0]
    added = 0
    for a in SHOP_AREAS:
        t = tr(a, lg=lg)
        if t.casefold() in have:
            continue
        n += 1
        added += 1
        c.execute("INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, t, n))
    return added


def occ_create(c, uid, b, check=True):
    """{name, kind?, date (YYYY-MM-DD or --MM-DD), year?, lead_days?, list_id?, gifts?: [..]} -> the new task id.
    check=False: the caller checked the list (background sync of an address book, no request)."""
    name = b.get("name")
    if not isinstance(name, str) or not name.strip():
        raise BadInput(tr("Please enter a name"))
    kind = b.get("kind", "birthday")
    if kind not in FAM_OCC:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    d = b.get("date")
    m = re.fullmatch(r"(\d{4}|-{2})-?(\d{2})-?(\d{2})", d.strip()) if isinstance(d, str) else None
    if not m:
        raise BadInput(tr("Invalid value: {0}", tr("Date")))
    mo, dy = int(m.group(2)), int(m.group(3))
    try:
        date(2000, mo, dy)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", tr("Date"))) from None
    year = int(m.group(1)) if m.group(1).isdigit() else None
    if b.get("year") not in (None, ""):
        year = as_int(b["year"], "year", DATE_MIN_Y, local_now().year)
    if year is not None and not DATE_MIN_Y <= year <= local_now().year:
        raise BadInput(tr("Invalid value: {0}", "year"))
    lead = as_int(b.get("lead_days", 7), "lead_days", 0, FAM_LEAD_MAX)
    lid = b.get("list_id")
    if lid not in (None, ""):
        lid = as_int(lid, "list_id", 1)
        if check:
            need_list(c, lid)
    else:
        lid = fam_list(c, uid, "birthdays")
    name = re.sub(r"\s+", " ", name).strip()[:FAM_NAME_MAX]
    lg = lang(c, uid)
    fam = {"kind": kind, "name": name, "lead": lead, **({"year": year} if year else {})}
    if b.get("src"):
        fam["src"] = str(b["src"])[:200]
    due = occ_next(mo, dy)
    ts = iso(now_utc())
    rem = ",".join(dict.fromkeys(str(x) for x in ([lead * 1440] if lead else []) + [0]))
    title = tr("Birthday: {0}", name, lg=lg) if kind == "birthday" else tr("Anniversary: {0}", name, lg=lg)
    tid = c.execute("""INSERT INTO tasks(list_id,title,due,reminders,repeat,sort,created_at,updated_at,created_by,fam)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (lid, title[:TITLE_MAX], due.isoformat(), rem, occ_rule(mo, dy),
                     c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0],
                     ts, ts, uid, json.dumps(fam, ensure_ascii=False, separators=(",", ":")))).lastrowid
    log_act(c, tid, "created", uid=uid)
    gifts = b.get("gifts") or []
    if not isinstance(gifts, list) or len(gifts) > 50 or not all(isinstance(x, str) for x in gifts):
        raise BadInput(tr("Invalid value: {0}", "gifts"))
    for i, gft in enumerate(x.strip()[:TITLE_MAX] for x in gifts if x.strip()):
        c.execute("INSERT INTO tasks(list_id,parent_id,title,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?)",
                  (lid, tid, gft, i + 1, ts, ts, uid))
    return tid


def deadline_create(c, uid, b):
    """{type, who?, expires (YYYY-MM-DD), notice_months?, lead_days?, title?, list_id?} -> the new task id."""
    k = b.get("type", "other")
    if k not in FAM_DL:
        raise BadInput(tr("Invalid value: {0}", "type"))
    name, tpl, lead0, rep, notice0 = FAM_DL[k]
    exp = b.get("expires")
    if not valid_date(exp):
        raise BadInput(tr("Please enter the date"))
    who = b.get("who") or ""
    if not isinstance(who, str):
        raise BadInput(tr("Invalid value: {0}", "who"))
    who = re.sub(r"\s+", " ", who).strip()[:FAM_NAME_MAX]
    notice = as_int(b.get("notice_months", notice0), "notice_months", 0, 24)
    lead = as_int(b.get("lead_days", lead0), "lead_days", 0, FAM_LEAD_MAX)
    lid = b.get("list_id")
    if lid not in (None, ""):
        lid = as_int(lid, "list_id", 1)
        need_list(c, lid)
    else:
        lid = fam_list(c, uid, "household")
    lg = lang(c, uid)
    title = b.get("title")
    if not isinstance(title, str) or not title.strip():
        if k == "other" and not who:
            raise BadInput(tr("Please enter a name"))
        title = tr(tpl, who or tr(name, lg=lg), lg=lg) if tpl != "{0}" else who
    if rep and rr_problem(rep):
        rep = ""
    end = date.fromisoformat(exp)
    due = end - relativedelta(months=notice)
    step = {"FREQ=YEARLY": 1, "FREQ=YEARLY;INTERVAL=2": 2}.get(rep, 0)
    while step and due < local_now().date():  # a recurring contract whose last chance has passed: the next term
        end += relativedelta(years=step)
        due = end - relativedelta(months=notice)
        exp = end.isoformat()
    ts = iso(now_utc())
    fam = {"kind": "deadline", "type": k, "who": who, "expires": exp, "notice": notice, "lead": lead}
    rem = ",".join(dict.fromkeys(str(x) for x in ([lead * 1440] if lead else []) + [0]))
    tid = c.execute("""INSERT INTO tasks(list_id,title,due,reminders,repeat,deadline,priority,sort,created_at,updated_at,created_by,fam)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (lid, title.strip()[:TITLE_MAX], due.isoformat(), rem, rep, 2, 3,
                     c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0],
                     ts, ts, uid, json.dumps(fam, ensure_ascii=False, separators=(",", ":")))).lastrowid
    log_act(c, tid, "created", uid=uid)
    return tid


# ---- shopping
_QTY = re.compile(r"^\s*(?:ca\.?\s*)?[\d½¼¾⅓⅔]+(?:[.,/][\d]+)?\s*(?:x|×|kg|g|gr|mg|l|ml|cl|dl|liter|litre|liters|litres|stk\.?|stück|"
                  r"pck\.?|pack|packs|packung|packungen|dose|dosen|can|cans|bund|bunch|el|tl|tbsp|tsp|cups?|pcs|pieces?|"
                  r"becher|glas|gläser|flasche|flaschen|bottles?|scheiben|slices?|zehen|cloves?|prise|pinch)?\b\.?\s*", re.I)


def shop_key(title):
    """An item name without its amount, for the area memory and for not adding an item twice ("2 l Milch" = "milch")."""
    s = re.sub(r"\s*\([^)]*\)\s*$", "", str(title or "")).strip()
    s2 = _QTY.sub("", s, count=1)
    s = s2 if s2.strip() else s
    return re.sub(r"[\s.,;:!?]+", " ", s).strip().casefold()[:120]


def shop_remember(c, lid, title, sid):
    k = shop_key(title)
    if not k:
        return
    if sid:
        c.execute("INSERT INTO shop_memory(list_id,item,section_id,at) VALUES(?,?,?,?) ON CONFLICT(list_id,item) "
                  "DO UPDATE SET section_id=excluded.section_id, at=excluded.at", (lid, k, sid, iso(now_utc())))
    else:
        c.execute("DELETE FROM shop_memory WHERE list_id=? AND item=?", (lid, k))


# 2.19.0: a first guess for items the list has not seen yet (index into SHOP_AREAS -> word stems in the six languages).
# Words under 4 letters only count as a whole word; longer ones also as the start or (German compounds) the end of a word.
SHOP_GUESS = (
    "apple apfel äpfel pomme manzana mela appel banan plátano platano tomat pomodor onion zwiebel oignon cebolla cipoll "
    "potato kartoffel patata aardappel carrot karotte möhre carotte zanahoria carot wortel salad salat lettuce cucumber "
    "gurke concombre pepino cetriol komkommer paprika lemon zitrone citron limón limon limone citroen orange naranja "
    "arancia sinaasappel grape traube raisin uva druif berry beere fraise strawberr erdbeer fresa fragol aardbei garlic "
    "knoblauch ail ajo aglio knoflook mushroom pilz champignon avocado broccoli brokkoli spinach spinat épinard espinaca "
    "spinac spinazie zucchini courgette herbs kräuter basil basilikum parsley petersilie fruit obst frucht fruta frutta "
    "gemüse vegetable légume verdur groente pear birne poire pera peer kiwi melon ingwer ginger leek lauch porree celery "
    "sellerie cabbage kohl",
    "bread brot brötchen pain baguette pan pane brood croissant roll rolls semmel toast bagel cake kuchen gâteau torta "
    "taart bun buns",
    "milk milch lait leche latte melk cheese käse fromage queso formaggio kaas parmesan parmigiano mozzarella gouda feta "
    "butter beurre mantequilla burro boter yogh joghurt yaourt yogur cream sahne crème nata panna quark egg eggs eier ei "
    "œuf oeuf oeufs huevo uova uovo eieren skyr",
    "meat fleisch viande carne vlees chicken hähnchen huhn poulet pollo kip beef rind boeuf bœuf ternera manzo pork "
    "schwein porc cerdo maiale varken ham schinken jambon jamón prosciutto sausage wurst würstchen saucisse salchicha "
    "salsiccia worst bacon speck mince hack steak fish fisch poisson pescado pesce vis salmon lachs saumon salmón salmone "
    "zalm tuna thunfisch thon atún tonno tonijn shrimp garnele crevette gamba turkey pute salami",
    "frozen tiefkühl tk surgelé congelad surgelat diepvries eis glace helado gelato ijs fischstäbchen",
    "pasta nudel noodle spaghetti penne fusilli rice reis riz arroz riso rijst flour mehl farine harina farina meel sugar "
    "zucker sucre azúcar zucchero suiker salt salz sel sal sale zout oil öl huile aceite olio olie vinegar essig vinaigre "
    "vinagre aceto azijn sauce soße sugo saus ketchup mustard senf moutarde mostaza senape mosterd honey honig miel "
    "miele honing jam marmelade confiture mermelada marmellata cereal müsli muesli oats hafer cornflakes coffee kaffee "
    "café caffè koffie tea tee thé té tè thee chocolate schokolade chocolat cioccolat chocola beans bohnen lentil linsen "
    "crackers chips nuts nüsse noix spice gewürz pfeffer poivre pimienta",
    "water wasser eau agua acqua juice saft jus zumo succo sap beer bier bière cerveza birra wine wein vin vino wijn cola "
    "soda lemonade limo limonade sprudel tonic mineral",
    "toilet toiletten klopapier detergent waschmittel lessive detergente wasmiddel soap seife savon jabón sapone zeep "
    "shampoo shampoing champú toothpaste zahnpasta dentifrice dentífrico dentifricio tandpasta washing spülmittel "
    "vaisselle müllbeutel sponge schwamm éponge esponja spugna spons tissue taschentücher kitchen küchenrolle nappies "
    "windeln couches pañales pannolini luiers deo deodorant battery batterie batterien pile pila foil folie cleaner "
    "reiniger",
)


def shop_guess(title):
    """The SHOP_AREAS index a new item probably belongs to, or None. Whole words first, then word ends (German
    compounds: "Vollkornbrot"), then word starts ("tomatoes")."""
    toks = [t for t in re.split(r"[\s\-/,;&+]+", shop_key(title)) if t]
    areas = [w.casefold().split() for w in SHOP_GUESS]
    for test in (lambda t, w: t == w, lambda t, w: len(w) >= 4 and t.endswith(w), lambda t, w: len(w) >= 4 and t.startswith(w)):
        for t in toks:
            for i, ws in enumerate(areas):
                if any(test(t, w) for w in ws):
                    return i
    return None


def shop_area_of(c, lid, title):
    r = c.execute("SELECT m.section_id FROM shop_memory m JOIN sections s ON s.id=m.section_id AND s.list_id=m.list_id "
                  "WHERE m.list_id=? AND m.item=?", (lid, shop_key(title))).fetchone()
    if r:
        return r[0]
    i = shop_guess(title)
    if i is None:
        return None
    names = {tr(SHOP_AREAS[i], lg=lg).casefold() for lg in LANGS} | {SHOP_AREAS[i].casefold()}
    for sid, name in c.execute("SELECT id, name FROM sections WHERE list_id=? ORDER BY sort, id", (lid,)):
        if str(name or "").strip().casefold() in names:
            return sid
    return None


def is_shop(c, lid):
    r = c.execute("SELECT family FROM lists WHERE id=?", (lid,)).fetchone() if lid else None
    return bool(r) and r[0] == "shopping"


def ingredient_lines(text):
    """The ingredients in a meal's notes: checklist / bullet / numbered lines (open ones), else every plain line."""
    lines = [x.rstrip() for x in str(text or "").replace("\r", "").split("\n")]
    items, bul = [], False
    for ln in lines:
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(\[( |x|X)\]\s*)?(.*\S)\s*$", ln)
        if m:
            bul = True
            if m.group(2) in ("x", "X"):
                continue
            items.append(m.group(3))
    if not bul:
        items = [x.strip() for x in lines if x.strip() and not x.strip().startswith(("#", ">", "```"))]
    out = []
    for x in items:
        x = re.sub(r"[*_`]+", "", x).strip()[:TITLE_MAX]
        if x and shop_key(x) not in {shop_key(y) for y in out}:
            out.append(x)
    return out[:100]


def to_shopping(c, uid, items, lid=None, source=None):
    """Adds items to a shopping list (lid, else the first one the user may write, created when missing); open items with
    the same name are not added twice. -> {list_id, added: [{id, title}], skipped: [titles]}"""
    if lid:
        need_list(c, lid)
        if not is_shop(c, lid):
            raise BadInput(tr("This is not a shopping list"))
    else:
        lid = fam_list(c, uid, "shopping")
    have = {shop_key(r[0]) for r in c.execute("SELECT title FROM tasks WHERE list_id=? AND status=0 AND deleted_at IS NULL AND parent_id IS NULL", (lid,))}
    srt = c.execute("SELECT COALESCE(MAX(sort),0) FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    ts = iso(now_utc())
    added, skipped = [], []
    for x in items:
        k = shop_key(x)
        if not k or k in have:
            skipped.append(x)
            continue
        have.add(k)
        srt += 1
        tid = c.execute("INSERT INTO tasks(list_id,section_id,title,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?)",
                        (lid, shop_area_of(c, lid, x), x, srt, ts, ts, uid)).lastrowid
        log_act(c, tid, "created", {"from": source} if source else None, uid=uid)
        added.append({"id": tid, "title": x})
    return {"list_id": lid, "added": added, "skipped": skipped}


# ---- packing lists
def packing_templates(lg):
    return [{"key": k, "name": tr(n, lg=lg), "sections": [{"name": tr(s, lg=lg) if s else "", "items": [tr(i, lg=lg) for i in its]}
                                                         for s, its in secs]} for k, (n, secs) in PACKING.items()]


def packing_create(c, uid, key, name=None):
    if key not in PACKING:
        raise BadInput(tr("Invalid value: {0}", "template"))
    lg = lang(c, uid)
    n, secs = PACKING[key]
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise BadInput(tr("Name missing"))
    lid = fam_list_create(c, uid, "packing", (name or tr("Packing list: {0}", tr(n, lg=lg), lg=lg)).strip()[:LIST_NAME_MAX])
    ts, srt = iso(now_utc()), 0
    for si, (s, its) in enumerate(secs):
        sid = c.execute("INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, tr(s, lg=lg), si + 1)).lastrowid if s else None
        for it in its:
            srt += 1
            c.execute("INSERT INTO tasks(list_id,section_id,title,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?)",
                      (lid, sid, tr(it, lg=lg), srt, ts, ts, uid))
    return lid


# ---- "What do you use Kalmido for?" (setup, welcome tour, Settings > Modules)
def purpose_apply(c, uid, purpose, examples=True):
    """Switches the user's modules to the purpose and (examples) creates its starter lists once. -> {features, created}"""
    if purpose not in PURPOSES:
        raise BadInput(tr("Invalid value: {0}", "purpose"))
    fs = [x for x in (usettings(c, uid).get("features") or "").split(",") if x]
    on = set(PURPOSE_ON[purpose])
    fs = [x for x in fs if x not in PURPOSE_MODS or x in on] + [x for x in PURPOSE_MODS if x in on and x not in fs]
    uset(c, uid, "features", ",".join(fs))
    uset(c, uid, "purpose", purpose)
    created = []
    if examples:
        if purpose == "family":
            created = family_examples(c, uid)
        elif purpose == "software" and not c.execute("SELECT 1 FROM lists WHERE owner_id=? AND ptype='software' AND archived=0", (uid,)).fetchone():
            lid, _ = ptype_create(c, uid, "software", tr(PTYPE_NAMES["software"], lg=lang(c, uid)))
            created.append(lid)
        elif purpose == "team" and not sample_state(c, uid):
            created.append(sample_create(c, uid))
    return {"features": ",".join(fs), "created": created}


FAM_CHORES = ((N_("Take out the rubbish"), "FREQ=WEEKLY;BYDAY=MO"), (N_("Clean the bathroom"), "FREQ=WEEKLY;BYDAY=SA"),
              (N_("Water the plants"), "FREQ=DAILY;INTERVAL=3"), (N_("Vacuum"), "FREQ=WEEKLY;BYDAY=FR"))
FAM_SHOP_EXAMPLES = (N_("Apples"), N_("Bread"), N_("Milk"))


def family_examples(c, uid):
    """The starter lists of the family setup, in the folder "Family": shopping list (with areas), household chores,
    birthdays, meal plan. A kind the user already has a list of is skipped. Returns the new list ids."""
    lg = lang(c, uid)
    folder = clean_folder(tr("Family", lg=lg))
    made, ts, day = [], iso(now_utc()), local_now().date()
    for kind in ("shopping", "household", "birthdays", "meals"):
        if fam_list(c, uid, kind, create=False):
            continue
        lid = fam_list_create(c, uid, kind, folder=folder)
        made.append(lid)
        if kind == "shopping":
            secs = {r["name"]: r["id"] for r in c.execute("SELECT id, name FROM sections WHERE list_id=?", (lid,))}
            for i, (it, area) in enumerate(zip(FAM_SHOP_EXAMPLES, (SHOP_AREAS[0], SHOP_AREAS[1], SHOP_AREAS[2]))):
                sid = secs.get(tr(area, lg=lg))
                c.execute("INSERT INTO tasks(list_id,section_id,title,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?)",
                          (lid, sid, tr(it, lg=lg), i + 1, ts, ts, uid))
                shop_remember(c, lid, tr(it, lg=lg), sid)
        elif kind == "household":
            for i, (t, rep) in enumerate(FAM_CHORES):
                rule = rr_rule(rep, day.isoformat())
                nxt = rule.after(datetime(day.year, day.month, day.day), inc=True).date() if rule else day
                c.execute("INSERT INTO tasks(list_id,title,due,repeat,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                          (lid, tr(t, lg=lg), nxt.isoformat(), rep, i + 1, ts, ts, uid))
        elif kind == "meals":
            c.execute("INSERT INTO tasks(list_id,title,content,due,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                      (lid, tr("Spaghetti with tomato sauce", lg=lg),
                       "\n".join("- " + tr(x, lg=lg) for x in (N_("Spaghetti"), N_("Tomatoes"), N_("Onion"), N_("Parmesan"))),
                       day.isoformat(), 1, ts, ts, uid))
    if made:
        fl = json.loads(usettings(c, uid).get("folders") or "[]")
        if folder and folder not in fl:
            uset(c, uid, "folders", json.dumps(fl + [folder], ensure_ascii=False))
    return made


# ---- the overview (Family view, dashboard card, API)
def family_overview(c, uid, start=None):
    """What the Family view shows, for the API (the app computes the same from its state): upcoming birthdays and
    anniversaries (with the age), deadlines, who is next in the rotations, the meal plan of the week starting `start`
    (Monday of this week by default), the shopping lists with their open items and the kids I look after (or me)."""
    today = local_now().date()
    mon = start or (today - timedelta(days=today.weekday()))
    rows = load_tasks(c, f"list_id IN {vis_sql()} AND deleted_at IS NULL AND status=0 AND (fam!='' OR rotation!='' OR "
                         "list_id IN (SELECT id FROM lists WHERE family IN ('meals','shopping')))", (uid, uid))
    lists = {d["id"]: d for d in visible_lists(c, uid)}
    occ, dls, rots, meals = [], [], [], []
    names = user_names(c, {x for t in rows for x in ((t.get("rotation") or {}).get("who") or [])})
    for t in rows:
        f = t.get("fam") or {}
        if f.get("kind") in FAM_OCC and t["due"]:
            d = date.fromisoformat(t["due"])
            occ.append({"task_id": t["id"], "list_id": t["list_id"], "title": t["title"], "kind": f["kind"], "name": f.get("name") or t["title"],
                        "date": t["due"], "days": (d - today).days, "year": f.get("year"),
                        "age": d.year - f["year"] if f.get("year") else None,
                        "gifts": c.execute("SELECT COUNT(*) FROM tasks WHERE parent_id=? AND status=0 AND deleted_at IS NULL", (t["id"],)).fetchone()[0]})
        elif f.get("kind") == "deadline" and t["due"]:
            dls.append({"task_id": t["id"], "list_id": t["list_id"], "title": t["title"], "type": f.get("type"), "who": f.get("who") or "",
                        "expires": f.get("expires"), "due": t["due"], "days": (date.fromisoformat(t["due"]) - today).days})
        r = t.get("rotation")
        if r and r.get("who"):
            n = len(r["who"])
            i = r.get("i", 0) % n
            rots.append({"task_id": t["id"], "list_id": t["list_id"], "title": t["title"], "mode": r.get("mode", "done"),
                         "who": [{"user_id": x, "name": names.get(x, "?")} for x in r["who"]],
                         "current": t["assignee_id"], "next": r["who"][(i + 1) % n], "due": t["due"]})
        if lists.get(t["list_id"], {}).get("family") == "meals" and t["due"] and not t["parent_id"] and \
                mon.isoformat() <= t["due"] <= (mon + timedelta(days=6)).isoformat():
            meals.append({"task_id": t["id"], "list_id": t["list_id"], "title": t["title"], "day": t["due"], "time": t["due_time"],
                          "ingredients": ingredient_lines(t["content"])})
    occ.sort(key=lambda x: (x["days"], x["name"].casefold()))
    dls.sort(key=lambda x: (x["due"], x["task_id"]))
    meals.sort(key=lambda x: (x["day"], x["time"] or "", x["task_id"]))
    shop = [{"list_id": lid, "name": d["name"], "open": sum(1 for t in rows if t["list_id"] == lid and not t["parent_id"]),
             "role": d["role"]} for lid, d in lists.items() if d.get("family") == "shopping" and not d["archived"]]
    return {"occasions": occ, "deadlines": dls, "rotations": rots, "week": mon.isoformat(), "meals": meals, "shopping": shop,
            "kids": kids_for(c, uid), "kid": is_kid(c, uid)}


def kid_dict(c, kid, full=True):
    u = c.execute("SELECT * FROM users WHERE id=?", (kid,)).fetchone()
    d = {**user_public(u), "stars": kid_balance(c, kid), "parents": kid_parents(c, kid)}
    if full:
        d["rewards"] = [reward_dict(r) for r in c.execute("SELECT * FROM kid_rewards WHERE kid_id=? ORDER BY state!='requested', cost, id", (kid,))]
        d["history"] = [{"id": r["id"], "delta": r["delta"], "kind": r["kind"], "title": r["title"], "task_id": r["task_id"],
                         "by": r["by_id"], "at": r["created_at"]}
                        for r in c.execute("SELECT * FROM kid_stars WHERE kid_id=? ORDER BY id DESC LIMIT 30", (kid,))]
        d["requests"] = sum(1 for x in d["rewards"] if x["state"] == "requested")
    return d


def reward_dict(r):
    return {"id": r["id"], "kid_id": r["kid_id"], "title": r["title"], "emoji": r["emoji"], "cost": r["cost"], "once": bool(r["once"]),
            "state": r["state"], "requested_at": r["requested_at"], "decided_at": r["decided_at"], "decided_by": r["decided_by"]}


def kids_for(c, uid):
    """The kids uid looks after (admins: every kid), or [uid itself] for a kid."""
    if is_kid(c, uid):
        return [kid_dict(c, uid)]
    adm = c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    q = "SELECT id FROM users WHERE kid=1 AND disabled=0" + ("" if adm and adm[0] else " AND id IN (SELECT kid_id FROM kid_parents WHERE parent_id=?)")
    return [kid_dict(c, r[0]) for r in c.execute(q + " ORDER BY id", () if adm and adm[0] else (uid,))]


def kid_push(c, uid, title_fn, msg_fn, click="#family"):
    """A family push (rewards) to uid in their language, when they can get pushes."""
    if not uid or uid in agent_ids(c):
        return
    s = usettings(c, uid)
    if not push_reachable(c, uid, s):
        return
    lg = lang_of(s)
    g.pushes.append((uid, title_fn(lg), msg_fn(lg), f"{PUBLIC_URL}/{click}", push_prio(s)))
