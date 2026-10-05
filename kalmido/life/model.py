"""Home & life (#663): contracts, devices + upkeep, staying in touch, health, the review + journal, trips (the model)."""
import json
import re
from datetime import date, datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta

from ..core.config import TZ
from ..core.i18n import lang, N_, tr
from ..core.db import iso, local_now, now_utc, usettings
from ..core.access import Denied, health_hidden, my_max_sort, need_list, vis_sql, wr_sql
from ..core.serializers import load_tasks
from ..core.state import visible_lists
from ..lists.lists import agent_autoshare, clean_folder, LIST_NAME_MAX
from ..lists.groups import grp_touch
from ..tasks.validation import as_int, log_act, rr_problem, TITLE_MAX, valid_date
from ..personal.timetrack import BadInput
from ..family.family import PACKING


# ---------------------------------------------------------------- 2.22.0 (#663): "Home & life"
# Kalmido connects and reminds instead of rebuilding special tools. Seven modules, each OFF by default and switched on
# one by one (Settings > Modules > At home). Everything is made of the usual objects (lists, repeating tasks, reminders,
# deadlines, Paperless links, contacts), so calendar, pushes, CalDAV, sharing and the API keep working:
#   contracts  = a task per contract: tasks.fam {kind: contract, name, provider, cost, per, notice, nu, start?, account?};
#                due = the last day to cancel (end of the term minus the notice period), the repeat = the renewal
#                (completing it = extended: the next term), the end of the term is due + notice; cost per month / year
#   home       = devices (fam {kind: device, name, model?, bought?, warranty?}: a task due when the warranty ends, the
#                receipt linked from Paperless) and upkeep (fam {kind: upkeep, item?}: a repeating task: heating, smoke
#                detectors, tyres ...)
#   care       = "stay in touch" per person and contact (table contact_care: every N days, the last time, a note); one
#                push a day lists who is due (needs the module Contacts)
#   health     = a private list (lists.life 'health') with appointments, check-ups, vaccinations and medication
#                (fam {kind: health, type, who}); never visible to an agent, an API token needs the scope "private"
#   review     = the day / week in review (done, still open, moved, coming up) and a private journal (table journal)
#   travel     = a trip is a list (lists.life 'travel', lists.trip {from, to, where}) with bookings, things to do before
#                leaving and a packing list from the Family templates; optionally an all-day event
#   reading    = "Read later": a list (lists.life 'reading') filled from Karakeep (kalmido/life/karakeep.py)
LIFE_MODS = ("contracts", "home", "care", "health", "review", "travel", "reading")
LIFE_LIST_KINDS = ("", "contracts", "home", "health", "travel", "reading")
LIFE_FAM = ("contract", "device", "upkeep", "health", "bookmark")
LIFE_LIST_NAMES = {"contracts": N_("Contracts"), "home": N_("Home & devices"), "health": N_("Health"), "reading": N_("Read later")}
LIFE_LIST_COLORS = {"contracts": "#0ea5e9", "home": "#f59e0b", "health": "#ef4444", "travel": "#14b8a6", "reading": "#8b5cf6"}
LIFE_FEAT = {"contracts": "contracts", "home": "home", "health": "health", "travel": "travel", "reading": "reading"}
NAME_MAX, NOTE_MAX = 100, 500
COST_MAX = 10_000_000
LEAD_MAX = 365
PERIODS = ("month", "quarter", "year")
PER_MONTHS = {"month": 1, "quarter": 3, "year": 12}
NOTICE_UNITS = ("d", "w", "m")
HEALTH_TYPES = ("appointment", "checkup", "vaccination", "medication")
HEALTH_TIMES_MAX = 6
CARE_MAX_DAYS = 3 * 365
JOURNAL_MAX = 20000
TRIP_SPAN_MAX = 366


def feat_on(c, uid, f):
    return f in (usettings(c, uid).get("features") or "").split(",")


def need_life(c, uid, f):
    from ..core.access import FEAT_OFF
    if not feat_on(c, uid, f):
        raise Denied(409, tr(FEAT_OFF[f]))


def _name(v, what="name", need=False, n=NAME_MAX):
    if v in (None, "") and not need:
        return ""
    if not isinstance(v, str) or (need and not v.strip()):
        raise BadInput(tr("Please enter a name") if need else tr("Invalid value: {0}", what))
    return re.sub(r"\s+", " ", v).strip()[:n]


def _date(v, what, need=False):
    if v in (None, "") and not need:
        return ""
    if not valid_date(v):
        raise BadInput(tr("Please enter the date") if need else tr("Invalid value: {0}", what))
    return v


def _cost(v):
    if v in (None, ""):
        return None
    if isinstance(v, str):
        v = v.strip().replace(",", ".")
        if not re.fullmatch(r"\d{1,8}(\.\d{1,2})?", v):
            raise BadInput(tr("Invalid value: {0}", tr("Cost")))
        v = float(v)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= COST_MAX:
        raise BadInput(tr("Invalid value: {0}", tr("Cost")))
    return round(float(v), 2)


def _dump(d):
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


# ---- tasks.fam: the kinds of this package (family.clean_fam hands them over)
def life_clean_fam(v):
    """{kind: contract | device | upkeep | health | bookmark, ...} from a client -> the stored JSON text."""
    k = v.get("kind")
    bad = BadInput(tr("Invalid value: {0}", "family"))
    allowed = {"contract": {"kind", "name", "provider", "cost", "per", "notice", "nu", "start", "account", "lead"},
               "device": {"kind", "name", "model", "bought", "warranty", "lead"},
               "upkeep": {"kind", "item", "lead"},
               "health": {"kind", "type", "who", "lead"},
               "bookmark": {"kind", "src", "bid", "arch"}}[k]
    if set(v) - allowed:
        raise bad
    out = {"kind": k}
    if k == "contract":
        out["name"] = _name(v.get("name"))
        out["provider"] = _name(v.get("provider"), "provider")
        cost = _cost(v.get("cost"))
        if cost is not None:
            out["cost"] = cost
        per = v.get("per") or "month"
        if per not in PERIODS:
            raise bad
        out["per"] = per
        out["notice"] = as_int(v.get("notice", 0) or 0, "notice", 0, 365)
        nu = v.get("nu") or "m"
        if nu not in NOTICE_UNITS:
            raise bad
        out["nu"] = nu
        if v.get("start"):
            out["start"] = _date(v["start"], "start")
        if v.get("account"):
            out["account"] = _name(v["account"], "account")
    elif k == "device":
        out["name"] = _name(v.get("name"))
        for f in ("model",):
            if v.get(f):
                out[f] = _name(v[f], f)
        for f in ("bought", "warranty"):
            if v.get(f):
                out[f] = _date(v[f], f)
    elif k == "upkeep":
        if v.get("item"):
            out["item"] = _name(v["item"], "item")
    elif k == "health":
        if v.get("type", "appointment") not in HEALTH_TYPES:
            raise bad
        out["type"] = v.get("type", "appointment")
        out["who"] = _name(v.get("who"), "who")
    elif k == "bookmark":
        if not isinstance(v.get("bid"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", v["bid"]) or v.get("src") != "karakeep":
            raise bad
        out.update(src="karakeep", bid=v["bid"])
        if v.get("arch"):
            out["arch"] = 1
    if v.get("lead") not in (None, ""):
        out["lead"] = as_int(v["lead"], "lead", 0, LEAD_MAX)
    return _dump(out)


def notice_delta(n, nu):
    return relativedelta(days=n) if nu == "d" else relativedelta(weeks=n) if nu == "w" else relativedelta(months=n)


def contract_end(due, f):
    """The end of the current term: the last day to cancel (the task's due) plus the notice period."""
    return (date.fromisoformat(due) + notice_delta(f.get("notice") or 0, f.get("nu") or "m")).isoformat() if due else None


def renew_months(rep):
    m = re.fullmatch(r"FREQ=MONTHLY(?:;INTERVAL=(\d+))?", rep or "")
    if m:
        return int(m.group(1) or 1)
    m = re.fullmatch(r"FREQ=YEARLY(?:;INTERVAL=(\d+))?", rep or "")
    return int(m.group(1) or 1) * 12 if m else 0


def renew_rule(months):
    return "" if not months else "FREQ=YEARLY" if months == 12 else f"FREQ=YEARLY;INTERVAL={months // 12}" if months % 12 == 0 \
        else "FREQ=MONTHLY" if months == 1 else f"FREQ=MONTHLY;INTERVAL={months}"


def _reminders(lead):
    return ",".join(dict.fromkeys(str(x) for x in ([lead * 1440] if lead else []) + [0]))


# ---- the lists of the package
def life_list(c, uid, kind, create=True):
    """The first not archived list of life kind `kind` the user may write (own first), created when missing (create)."""
    r = c.execute(f"""SELECT id FROM lists WHERE life=? AND archived=0 AND id IN {wr_sql()}
                      ORDER BY owner_id!=?, id LIMIT 1""", (kind, uid, uid, uid)).fetchone()
    if r:
        return r[0]
    return life_list_create(c, uid, kind) if create else None


def life_list_create(c, uid, kind, name=None, folder="", trip=None):
    lg = lang(c, uid)
    lid = c.execute("""INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind,life,trip)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    ((name or tr(LIFE_LIST_NAMES[kind], lg=lg))[:LIST_NAME_MAX], LIFE_LIST_COLORS.get(kind, ""), folder,
                     my_max_sort(c, uid) + 1, "list", iso(now_utc()), uid, 1 if kind == "travel" else 0, "list", kind,
                     _dump(trip) if trip else "")).lastrowid
    if kind != "health":  # health lists are never shared with an agent automatically
        agent_autoshare(c, uid, lid)
    grp_touch(c, uid)
    return lid


def _target_list(c, uid, b, kind):
    lid = b.get("list_id")
    if lid not in (None, ""):
        lid = as_int(lid, "list_id", 1)
        need_list(c, lid)
        return lid
    return life_list(c, uid, kind)


def _insert(c, uid, lid, title, due=None, due_time=None, rem="", rep="", fam=None, deadline=0, prio=0, url=None, content=""):
    ts = iso(now_utc())
    tid = c.execute("""INSERT INTO tasks(list_id,title,content,due,due_time,reminders,repeat,deadline,priority,sort,created_at,updated_at,
                                         created_by,fam,url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (lid, title.strip()[:TITLE_MAX], content, due, due_time, rem, rep, deadline, prio,
                     c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0],
                     ts, ts, uid, _dump(fam) if fam else "", url)).lastrowid
    log_act(c, tid, "created", uid=uid)
    return tid


# ---- contracts
def contract_create(c, uid, b):
    """{name, ends (YYYY-MM-DD: end of the current term), provider?, cost?, per? (month), notice? (0), notice_unit? (m),
    renew_months? (12; 0 = it simply ends), lead_days? (14), start?, account?, list_id?} -> the new task id."""
    need_life(c, uid, "contracts")
    name = _name(b.get("name"), need=True)
    ends = _date(b.get("ends"), "ends", need=True)
    f = json.loads(life_clean_fam({"kind": "contract", "name": name, "provider": b.get("provider"), "cost": b.get("cost"),
                                   "per": b.get("per") or "month", "notice": b.get("notice", 0), "nu": b.get("notice_unit") or "m",
                                   "start": b.get("start"), "account": b.get("account")}))
    renew = as_int(b.get("renew_months", 12), "renew_months", 0, 120)
    lead = as_int(b.get("lead_days", 14), "lead_days", 0, LEAD_MAX)
    f["lead"] = lead
    end = date.fromisoformat(ends)
    nd = notice_delta(f["notice"], f["nu"])
    due = end - nd
    today = local_now().date()
    while renew and due < today:  # the last chance of this term is gone: the next term
        end += relativedelta(months=renew)
        due = end - nd
    rep = renew_rule(renew)
    if rep and rr_problem(rep):
        rep = ""
    lid = _target_list(c, uid, b, "contracts")
    title = tr("Cancel or renew the contract: {0}", name, lg=lang(c, uid))
    return _insert(c, uid, lid, title, due.isoformat(), rem=_reminders(lead), rep=rep, fam=f, deadline=2, prio=3)


def contract_out(t, today):
    f = t.get("fam") or {}
    cost, per = f.get("cost"), f.get("per") or "month"
    monthly = round(cost / PER_MONTHS[per], 2) if cost is not None else None
    return {"task_id": t["id"], "list_id": t["list_id"], "title": t["title"], "name": f.get("name") or t["title"],
            "provider": f.get("provider") or "", "cost": cost, "per": per, "monthly": monthly,
            "yearly": round(monthly * 12, 2) if monthly is not None else None, "notice": f.get("notice") or 0, "notice_unit": f.get("nu") or "m",
            "due": t["due"], "ends": contract_end(t["due"], f), "renew_months": renew_months(t["repeat"]),
            "days": (date.fromisoformat(t["due"]) - today).days if t["due"] else None, "account": f.get("account") or "",
            "start": f.get("start") or None, "documents": len(t.get("paperless") or [])}


# ---- home: devices + upkeep
UPKEEP_PRESETS = (("heating", N_("Service the heating"), 12), ("smoke", N_("Test the smoke detectors"), 12),
                  ("tyres", N_("Change the tyres"), 6), ("descale", N_("Descale the coffee machine"), 3),
                  ("hood", N_("Clean the cooker hood filter"), 3), ("chimney", N_("Chimney sweep"), 12),
                  ("bike", N_("Service the bike"), 12), ("gutter", N_("Clean the gutters"), 12))


def device_create(c, uid, b):
    """{name, model?, bought?, warranty? (YYYY-MM-DD), lead_days? (30), list_id?} -> the new task id (due when the
    warranty ends, without a warranty date a plain entry)."""
    need_life(c, uid, "home")
    name = _name(b.get("name"), need=True)
    f = json.loads(life_clean_fam({"kind": "device", "name": name, "model": b.get("model"), "bought": b.get("bought"),
                                   "warranty": b.get("warranty")}))
    lead = as_int(b.get("lead_days", 30), "lead_days", 0, LEAD_MAX)
    f["lead"] = lead
    if f.get("bought") and f.get("warranty") and f["warranty"] < f["bought"]:
        raise BadInput(tr("The warranty must end after the purchase"))
    lid = _target_list(c, uid, b, "home")
    lg = lang(c, uid)
    if f.get("warranty"):
        return _insert(c, uid, lid, tr("Warranty ends: {0}", name, lg=lg), f["warranty"], rem=_reminders(lead), fam=f, deadline=2)
    return _insert(c, uid, lid, name, fam=f)


def upkeep_create(c, uid, b):
    """{title, every_months (1..120), next? (YYYY-MM-DD, default today), item?, lead_days? (7), list_id?} -> a repeating task."""
    need_life(c, uid, "home")
    title = _name(b.get("title"), need=True, n=TITLE_MAX)
    every = as_int(b.get("every_months"), "every_months", 1, 120)
    nxt = _date(b.get("next"), "next") or local_now().date().isoformat()
    lead = as_int(b.get("lead_days", 7), "lead_days", 0, LEAD_MAX)
    f = json.loads(life_clean_fam({"kind": "upkeep", "item": b.get("item")}))
    f["lead"] = lead
    lid = _target_list(c, uid, b, "home")
    return _insert(c, uid, lid, title, nxt, rem=_reminders(lead), rep=renew_rule(every), fam=f)


def upkeep_presets(lg):
    return [{"key": k, "title": tr(t, lg=lg), "every_months": m} for k, t, m in UPKEEP_PRESETS]


# ---- health (private)
def health_create(c, uid, b):
    """{type (appointment | checkup | vaccination | medication), title, who?, date? (YYYY-MM-DD), time? (HH:MM),
    every_months? (check-ups / vaccinations: repeat), times? ([HH:MM]: medication, one daily task per time),
    lead_days?, list_id? (a health list)} -> [the new task ids]."""
    need_life(c, uid, "health")
    typ = b.get("type", "appointment")
    if typ not in HEALTH_TYPES:
        raise BadInput(tr("Invalid value: {0}", "type"))
    title = _name(b.get("title"), need=True, n=TITLE_MAX)
    who = _name(b.get("who"), "who")
    day = _date(b.get("date"), "date") or (local_now().date().isoformat() if typ == "medication" else "")
    if typ != "medication" and not day:
        raise BadInput(tr("Please enter the date"))
    tm = b.get("time") or None
    if tm is not None and (not isinstance(tm, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", tm)):
        raise BadInput(tr("Invalid value: {0}", "time"))
    every = as_int(b.get("every_months", 0) or 0, "every_months", 0, 240)
    lead = as_int(b.get("lead_days", 1 if typ == "appointment" else 14 if typ in ("checkup", "vaccination") else 0), "lead_days", 0, LEAD_MAX)
    lid = b.get("list_id")
    if lid not in (None, ""):
        lid = as_int(lid, "list_id", 1)
        need_list(c, lid)
        if c.execute("SELECT life FROM lists WHERE id=?", (lid,)).fetchone()[0] != "health":
            raise BadInput(tr("Health entries belong in a health list"))
    else:
        lid = life_list(c, uid, "health")
    f = {"kind": "health", "type": typ, "who": who, "lead": lead}
    if typ == "medication":
        times = b.get("times") or ([tm] if tm else [])
        if not isinstance(times, list) or not 1 <= len(times) <= HEALTH_TIMES_MAX or \
                not all(isinstance(x, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x) for x in times):
            raise BadInput(tr("Please enter at least one time"))
        return [_insert(c, uid, lid, title, day, x, rem="0", rep="FREQ=DAILY", fam=f) for x in sorted(set(times))]
    rem = ",".join(dict.fromkeys(str(x) for x in ([lead * 1440] if lead else []) + ([60] if tm and typ == "appointment" else []) + [0]))
    return [_insert(c, uid, lid, title, day, tm, rem=rem, rep=renew_rule(every) if typ != "appointment" else "", fam=f)]


# ---- travel
TRIP_TODO = ((N_("Check passports and ID cards"), 30), (N_("Arrange care for plants and pets"), 7), (N_("Pack"), 1))


def clean_trip(v):
    """{from, to, where?} -> dict (validated) or None for null / {}."""
    if v in (None, "", {}):
        return None
    if not isinstance(v, dict) or set(v) - {"from", "to", "where"}:
        raise BadInput(tr("Invalid value: {0}", "trip"))
    a, z = _date(v.get("from"), "from", need=True), _date(v.get("to"), "to", need=True)
    if z < a or (date.fromisoformat(z) - date.fromisoformat(a)).days > TRIP_SPAN_MAX:
        raise BadInput(tr("The end must be after the start"))
    out = {"from": a, "to": z}
    if v.get("where"):
        out["where"] = _name(v["where"], "where")
    return out


def trip_create(c, uid, b):
    """{name, from, to, where?, packing? (a packing template key or ''), event? (bool: an all-day event, module Events),
    folder?} -> {list_id, event_id}."""
    from ..family.family import packing_templates
    need_life(c, uid, "travel")
    name = _name(b.get("name"), need=True, n=LIST_NAME_MAX)
    trip = clean_trip({k: b[k] for k in ("from", "to", "where") if k in b})
    if not trip:
        raise BadInput(tr("Please enter the date"))
    pk = b.get("packing", "holiday")
    if pk not in ("", None) and pk not in PACKING:
        raise BadInput(tr("Invalid value: {0}", "packing"))
    lg = lang(c, uid)
    folder = clean_folder(b.get("folder") or "") if b.get("folder") else ""
    lid = life_list_create(c, uid, "travel", name, folder, trip)
    ts, srt = iso(now_utc()), 0
    start = date.fromisoformat(trip["from"])
    secs = [(tr("Bookings", lg=lg), []), (tr("Before you leave", lg=lg), [(tr(t, lg=lg), (start - timedelta(days=d)).isoformat()) for t, d in TRIP_TODO])]
    if pk:
        tpl = next(x for x in packing_templates(lg) if x["key"] == pk)
        for s in tpl["sections"]:
            secs.append((tr("Packing: {0}", s["name"], lg=lg) if s["name"] else tr("Packing", lg=lg), [(i, None) for i in s["items"]]))
    today = local_now().date().isoformat()
    for _sn, items in secs:  # 2.22.0 (#747): new lists start without sections: the things to do first, then the packing list
        sid = None
        for title, due in items:
            srt += 1
            c.execute("INSERT INTO tasks(list_id,section_id,title,due,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                      (lid, sid, title, max(due, today) if due else None, srt, ts, ts, uid))
    eid = None
    if b.get("event") and feat_on(c, uid, "events"):
        from ..events.model import default_cal, ev_fields, ev_store
        f = ev_fields(c, uid, {"title": name, "all_day": True, "start": trip["from"],
                               "end": (date.fromisoformat(trip["to"]) + timedelta(days=1)).isoformat(), "location": trip.get("where") or ""})
        eid = ev_store(c, uid, default_cal(c, uid), f)
    return {"list_id": lid, "event_id": eid}


# ---- the overview (view "Home & life", API)
def life_overview(c, uid):
    """What the view "Home & life" shows, per switched-on module."""
    from ..contacts.model import contacts_on
    on = set((usettings(c, uid).get("features") or "").split(","))
    today = local_now().date()
    out = {"modules": [m for m in LIFE_MODS if m in on]}
    rows = load_tasks(c, f"list_id IN {vis_sql()} AND deleted_at IS NULL AND status=0 AND fam!=''", (uid, uid))
    lists = {d["id"]: d for d in visible_lists(c, uid)}
    by = {}
    for t in rows:
        k = (t.get("fam") or {}).get("kind")
        if k in LIFE_FAM:
            by.setdefault(k, []).append(t)
    if "contracts" in on:
        cs = sorted((contract_out(t, today) for t in by.get("contract", [])), key=lambda x: (x["due"] or "9999", x["task_id"]))
        out["contracts"] = {"items": cs, "monthly": round(sum(x["monthly"] or 0 for x in cs), 2),
                            "yearly": round(sum(x["yearly"] or 0 for x in cs), 2)}
    if "home" in on:
        devs = [{"task_id": t["id"], "list_id": t["list_id"], "title": t["title"], "name": t["fam"].get("name") or t["title"],
                 "model": t["fam"].get("model") or "", "bought": t["fam"].get("bought"), "warranty": t["fam"].get("warranty"),
                 "days": (date.fromisoformat(t["fam"]["warranty"]) - today).days if t["fam"].get("warranty") else None}
                for t in by.get("device", [])]
        devs.sort(key=lambda x: (x["warranty"] or "9999", x["name"].casefold()))
        ups = [{"task_id": t["id"], "list_id": t["list_id"], "title": t["title"], "item": t["fam"].get("item") or "", "due": t["due"],
                "every_months": renew_months(t["repeat"]), "days": (date.fromisoformat(t["due"]) - today).days if t["due"] else None}
               for t in by.get("upkeep", [])]
        ups.sort(key=lambda x: (x["due"] or "9999", x["task_id"]))
        out["home"] = {"devices": devs, "upkeep": ups}
    if "health" in on and not health_hidden(c, uid):
        hs = [{"task_id": t["id"], "list_id": t["list_id"], "title": t["title"], "type": t["fam"].get("type"), "who": t["fam"].get("who") or "",
               "due": t["due"], "time": t["due_time"], "repeat": t["repeat"],
               "days": (date.fromisoformat(t["due"]) - today).days if t["due"] else None}
              for t in by.get("health", []) if lists.get(t["list_id"], {}).get("life") == "health"]
        hs.sort(key=lambda x: (x["due"] or "9999", x["time"] or "", x["task_id"]))
        out["health"] = {"items": hs}
    if "care" in on:
        out["care"] = {"contacts": contacts_on(c, uid), "items": care_list(c, uid) if contacts_on(c, uid) else []}
    if "travel" in on:
        trips = []
        for l in lists.values():
            tr_ = l.get("trip")
            if l.get("life") != "travel" or l["archived"] or not tr_:
                continue
            state = "past" if tr_["to"] < today.isoformat() else "now" if tr_["from"] <= today.isoformat() else "upcoming"
            trips.append({"list_id": l["id"], "name": l["name"], "where": tr_.get("where") or "", "from": tr_["from"], "to": tr_["to"],
                          "days": (date.fromisoformat(tr_["from"]) - today).days, "state": state,
                          "open": l["progress"]["total"] - l["progress"]["done"], "total": l["progress"]["total"]})
        trips.sort(key=lambda x: (x["state"] == "past", x["from"] if x["state"] != "past" else "", x["list_id"]))
        out["travel"] = {"trips": trips}
    if "reading" in on:
        from ..life.karakeep import kk_public
        rl = [l for l in lists.values() if l.get("life") == "reading" and not l["archived"]]
        items = [{"task_id": t["id"], "list_id": t["list_id"], "title": t["title"], "url": t.get("url") or ""}
                 for t in load_tasks(c, f"list_id IN {vis_sql()} AND deleted_at IS NULL AND status=0 AND parent_id IS NULL AND "
                                        "list_id IN (SELECT id FROM lists WHERE life='reading' AND archived=0)", (uid, uid))]
        out["reading"] = {"lists": [l["id"] for l in rl], "items": items[:100], "count": len(items), "karakeep": kk_public(c, uid)}
    return out


# ---- care: staying in touch (per person and contact)
def care_get(c, uid, cid):
    r = c.execute("SELECT * FROM contact_care WHERE user_id=? AND contact_id=?", (uid, cid)).fetchone()
    return care_dict(r) if r else {"every_days": 0, "last": None, "note": "", "due": None}


def care_dict(r):
    last, every = r["last"] or None, r["every_days"]
    due = None
    if every:
        due = (date.fromisoformat(last) + timedelta(days=every)).isoformat() if last else local_now().date().isoformat()
    return {"every_days": every, "last": last, "note": r["note"], "due": due}


def care_set(c, uid, cid, b):
    """{every_days? (0 = off), last? (YYYY-MM-DD; "today"), note?} for contact cid (which uid must see)."""
    from ..contacts.model import need_contact
    need_life(c, uid, "care")
    need_contact(c, cid, uid=uid)
    cur = care_get(c, uid, cid)
    every, last, note = cur["every_days"], cur["last"] or "", cur["note"]
    if "every_days" in b:
        every = as_int(b["every_days"] or 0, "every_days", 0, CARE_MAX_DAYS)
    if "last" in b:
        v = b["last"]
        last = local_now().date().isoformat() if v == "today" else (_date(v, "last") if v else "")
        if last and last > local_now().date().isoformat():
            raise BadInput(tr("The date cannot be in the future"))
    if "note" in b:
        if not isinstance(b["note"], str):
            raise BadInput(tr("Invalid value: {0}", "note"))
        note = b["note"].strip()[:NOTE_MAX]
    c.execute("""INSERT INTO contact_care(user_id,contact_id,every_days,last,note,updated_at) VALUES(?,?,?,?,?,?)
                 ON CONFLICT(user_id,contact_id) DO UPDATE SET every_days=excluded.every_days, last=excluded.last, note=excluded.note,
                 updated_at=excluded.updated_at""", (uid, cid, every, last, note, iso(now_utc())))
    return care_get(c, uid, cid)


def care_list(c, uid, due_only=False):
    """The contacts uid wants to stay in touch with (and may still see), the most overdue first."""
    from ..contacts.model import contact_visible
    today = local_now().date()
    out = []
    for r in c.execute("SELECT * FROM contact_care WHERE user_id=? AND every_days>0", (uid,)).fetchall():
        k = contact_visible(c, r["contact_id"], uid)
        if not k:
            continue
        d = care_dict(r)
        days = (date.fromisoformat(d["due"]) - today).days
        if due_only and days > 0:
            continue
        out.append({"contact_id": r["contact_id"], "fn": k["fn"] or k["org"] or "?", "photo": bool(k["photo"]), **d, "days": days})
    out.sort(key=lambda x: (x["days"], x["fn"].casefold()))
    return out


def _wd_care(c, users, S, LG, now):
    """Watchdog: once a day (from the person's all-day reminder time on) one push with the contacts that are due."""
    from ..core.config import PUBLIC_URL
    from ..notify.push import notify, push_prio
    today = now.date().isoformat()
    for uid in users:
        s = S[uid]
        if "care" not in (s.get("features") or "").split(",") or "contacts" not in (s.get("features") or "").split(","):
            continue
        if now.strftime("%H:%M") < (s.get("allday_time") or "09:00") or s.get("care_sent") == today:
            continue
        due = care_list(c, uid, due_only=True)
        if not due:
            continue  # nothing due yet: asked again later today (cheap: only people with the module)
        from ..core.db import uset
        uset(c, uid, "care_sent", today)
        c.commit()
        lg = LG[uid]
        names = ", ".join(x["fn"] for x in due[:5]) + (" …" if len(due) > 5 else "")
        notify(uid, tr("Time to get in touch", lg=lg), names, push_prio(s), f"{PUBLIC_URL}/#life", s=s, tag="care", ttl=20 * 3600)


# ---- review + journal
def journal_get(c, uid, lo, hi):
    return [{"day": r["day"], "text": r["text"], "mood": r["mood"]} for r in
            c.execute("SELECT * FROM journal WHERE user_id=? AND day>=? AND day<=? ORDER BY day", (uid, lo, hi))]


def journal_set(c, uid, day, b):
    """{text, mood? (1..5 or null)}: the entry of `day` (an empty text without a mood deletes it)."""
    need_life(c, uid, "review")
    if not valid_date(day) or day > (local_now().date() + timedelta(days=1)).isoformat():
        raise BadInput(tr("Invalid value: {0}", tr("Date")))
    text = b.get("text", "")
    if not isinstance(text, str):
        raise BadInput(tr("Invalid value: {0}", "text"))
    text = text.strip()[:JOURNAL_MAX]
    mood = b.get("mood")
    if mood not in (None, ""):
        mood = as_int(mood, "mood", 1, 5)
    else:
        mood = None
    if not text and mood is None:
        c.execute("DELETE FROM journal WHERE user_id=? AND day=?", (uid, day))
        return {"day": day, "text": "", "mood": None}
    c.execute("""INSERT INTO journal(user_id,day,text,mood,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,day) DO UPDATE SET
                 text=excluded.text, mood=excluded.mood, updated_at=excluded.updated_at""", (uid, day, text, mood, iso(now_utc())))
    return {"day": day, "text": text, "mood": mood}


def review(c, uid, period, day, journal=True):
    """{period, from, to, done, open, moved, next, journal}: what uid completed in the day / week (Monday to Sunday) of
    `day`, what is still open from it (due on or before its end), what they moved away, what comes in the next 7 days."""
    from ..tasks.dayplan import dayplan_mine_sql
    lo_d = day - timedelta(days=day.weekday()) if period == "week" else day
    hi_d = lo_d + timedelta(days=6 if period == "week" else 0)
    a = datetime(lo_d.year, lo_d.month, lo_d.day, tzinfo=TZ).astimezone(timezone.utc)
    b = datetime(hi_d.year, hi_d.month, hi_d.day, tzinfo=TZ).astimezone(timezone.utc) + timedelta(days=1)
    lo, hi, lo_s, hi_s = iso(a), iso(b), lo_d.isoformat(), hi_d.isoformat()
    done = [{"task_id": r["id"], "title": r["title"], "list_id": r["list_id"], "at": r["completed_at"]} for r in c.execute(
        f"""SELECT id, title, list_id, completed_at FROM tasks WHERE completed_by=? AND status=2 AND deleted_at IS NULL
            AND completed_at>=? AND completed_at<? AND list_id IN {vis_sql()} ORDER BY completed_at LIMIT 200""", (uid, lo, hi, uid, uid))]
    mine = dayplan_mine_sql(uid)
    still = [{"task_id": r["id"], "title": r["title"], "list_id": r["list_id"], "due": r["due"], "overdue": r["due"] < lo_s}
             for r in c.execute(f"""SELECT t.id, t.title, t.list_id, t.due FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.status=0
                                    AND t.deleted_at IS NULL AND t.parent_id IS NULL AND l.archived=0 AND t.due IS NOT NULL AND t.due<=?
                                    AND t.list_id IN {vis_sql()} AND {mine} ORDER BY t.due, t.id LIMIT 200""",
                                 (hi_s, uid, uid))]
    moved = [{"task_id": r["task_id"], "title": r["title"], "list_id": r["list_id"], "due": r["due"]} for r in c.execute(
        f"""SELECT DISTINCT a.task_id, t.title, t.list_id, t.due FROM activity a JOIN tasks t ON t.id=a.task_id
            WHERE a.user_id=? AND a.kind IN ('due', 'snooze') AND a.created_at>=? AND a.created_at<?
              AND t.status=0 AND t.deleted_at IS NULL AND t.due>? AND t.list_id IN {vis_sql()} LIMIT 100""", (uid, lo, hi, hi_s, uid, uid))]
    n0, n1 = (hi_d + timedelta(days=1)).isoformat(), (hi_d + timedelta(days=7)).isoformat()
    nxt = [{"task_id": r["id"], "title": r["title"], "list_id": r["list_id"], "due": r["due"], "time": r["due_time"]}
           for r in c.execute(f"""SELECT t.id, t.title, t.list_id, t.due, t.due_time FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.status=0
                                  AND t.deleted_at IS NULL AND t.parent_id IS NULL AND l.archived=0 AND t.due>=? AND t.due<=?
                                  AND t.list_id IN {vis_sql()} AND {mine} ORDER BY t.due, t.due_time IS NULL, t.due_time, t.id LIMIT 100""",
                                (n0, n1, uid, uid))]
    out = {"period": period, "from": lo_s, "to": hi_s, "done": done, "open": still, "moved": moved, "next": nxt}
    if journal:
        out["journal"] = journal_get(c, uid, lo_s, hi_s)
    return out
