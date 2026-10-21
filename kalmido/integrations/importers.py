"""Importers: TickTick, Todoist, Trello, Asana, Microsoft To Do, ICS / VTODO (preview, dry run, undo)."""
import contextlib
import csv
import hashlib
import io
import json
import math
import os
import re
import zipfile
import icalendar
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr
from flask import has_request_context, jsonify, request

from ..core.config import app, TZ
from ..core.pg import insert_id
from ..core.schema import MAX_DEPTH, USER_DEFAULTS
from ..core.i18n import lang, N_, tr
from ..core.db import bump, db, err, iso, iso_ms, local_now, now_utc, parse_iso, usettings
from ..accounts.session import me
from ..lists.lists import list_created
from ..core.access import collab_all, Denied, list_people, list_role, my_inbox, my_max_sort, need_list, WRITE_ROLES, token_lists
from ..core.serializers import unlink_files
from ..core.pages import valid_url
from ..lists.lists import FOLDER_MAX, folder_seg, LIST_NAME_MAX
from ..tasks.validation import (
    ancestors, as_int, clean_reminders, clean_task, CONTENT_MAX, depth, descendants, DURATION_MAX, PRIORITIES,
    REM_COUNT, REM_MAX, REM_MIN, rr_feasible, rr_norm, rr_problem, TITLE_MAX, valid_date, valid_hm,
)
from ..tasks.tasks import set_tags
from ..core.errors import BadInput, UnknownFields
from ..lists.projects import list_purge_files, list_row_purge
from ..api.common import act_via, hit_limit  # 2.149.0 G (#2517): pulled up from functions


# ---------------------------------------------------------------- TickTick import

def tt_date(s, all_day):
    """TickTick '2026-10-14T22:00:00+0000' -> (local date, local HH:MM | None)."""
    if not s:
        return None, None
    dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").astimezone(TZ)
    if all_day:
        return dt.date().isoformat(), None
    return dt.date().isoformat(), dt.strftime("%H:%M")


def tt_reminders(s):
    """'-PT0S,-PT15M,-P1D' / 'TRIGGER:-PT30M' -> '0,15,1440'."""
    out = []
    for part in (s or "").replace("TRIGGER:", "").split(","):
        p = part.strip().lstrip("-")
        if not p.startswith("P"):
            continue
        mins, num, in_time = 0, "", False
        for ch in p[1:]:
            if ch == "T":
                in_time = True
            elif ch.isdigit():
                num += ch
            else:
                n = int(num or 0)
                num = ""
                mins += {"W": 10080, "D": 1440}.get(ch, 0) * n if not in_time else \
                    {"H": 60, "M": 1, "S": 0}.get(ch, 0) * n
        out.append(str(mins))
    return ",".join(dict.fromkeys(out))


def import_ticktick(c, text, uid):
    """Imports into the lists of user uid (matched by name among the lists they own)."""
    text = text.lstrip("﻿")
    i = text.find('"Folder Name"')
    if i < 0:
        raise ValueError(tr("Not a TickTick CSV (header 'Folder Name' missing)", lg=lang(c, uid)))
    rows = list(csv.DictReader(io.StringIO(text[i:])))
    if len(rows) > IMPORT_MAX_TASKS:  # 2.148.1 E (#2496)
        raise ValueError(tr("Too many rows (more than {0} tasks)", IMPORT_MAX_TASKS, lg=lang(c, uid)))
    lists = {r["name"]: r["id"] for r in c.execute("SELECT id, name FROM lists WHERE owner_id=? AND is_inbox=0 AND e2e IS NULL", (uid,))}
    inbox = my_inbox(c, uid)
    sections = {}
    stats = dict(tasks=0, skipped=0, lists=0)
    idmap = {}
    ts = iso(now_utc())
    now = local_now()
    # list order = first appearance; task order = TickTick "Order" within list
    rows.sort(key=lambda r: int(r.get("Order") or 0))
    for r in rows:
        name = (r.get("List Name") or "").strip()
        if name.lower() == "inbox" or not name:
            lid = inbox
        elif name in lists:
            lid = lists[name]
        else:
            srt = my_max_sort(c, uid) + 1
            lid = insert_id(c, "INSERT INTO lists(name,folder,sort,view,created_at,owner_id) VALUES(?,?,?,?,?,?)",
                            (name[:LIST_NAME_MAX], folder_seg(r.get("Folder Name") or ""), srt,
                             "kanban" if r.get("View Mode") == "kanban" else "list", ts, uid))
            from ..accounts.orgs import ws_apply_default
            ws_apply_default(c, uid, lid)  # 2.28.0 (#935): the default workspace
            list_created(c, uid, lid)  # 2.25.0 (#931): agents, groups and people of a shared folder
            lists[name] = lid
            stats["lists"] += 1
        tt = r.get("taskId") or None
        old = c.execute("SELECT id FROM tasks WHERE tt_id=? AND created_by=?", (tt, uid)).fetchone() if tt else None
        if old:
            idmap[tt] = old[0]
            stats["skipped"] += 1
            continue
        sec = None
        col = (r.get("Column Name") or "").strip()
        if col:
            key = (lid, col)
            if key not in sections:
                row = c.execute("SELECT id FROM sections WHERE list_id=? AND name=?", key).fetchone()
                sections[key] = row[0] if row else insert_id(c, "INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)",
                    (lid, col, float(r.get("Column Order") or 0)))
            sec = sections[key]
        all_day = (r.get("Is All Day") or "").lower() == "true"
        due, due_time = tt_date(r.get("Due Date") or r.get("Start Date"), all_day)
        start = None
        if r.get("Start Date") and r.get("Due Date"):
            sd, _ = tt_date(r["Start Date"], all_day)
            start = sd if sd and due and sd < due else None
        content = (r.get("Content") or "").replace("\\!", "!").replace("\r", "")
        if (r.get("Is Check list") or "N") == "Y":  # checklist lines -> content bullets
            content = "\n".join("- " + ln.lstrip("▫▪ ").strip() for ln in content.split("\n") if ln.strip())
        status = int(r.get("Status") or 0)
        status = 2 if status == 2 else (-1 if status == -1 else 0)
        completed = None
        if status and r.get("Completed Time"):
            completed = iso(datetime.strptime(r["Completed Time"], "%Y-%m-%dT%H:%M:%S%z"))
        created = r.get("Created Time")
        created = iso(datetime.strptime(created, "%Y-%m-%dT%H:%M:%S%z")) if created else ts
        rems = tt_reminders(r.get("Reminder"))
        # don't fire reminders that are already in the past at import time
        reminded = []
        if due and rems:
            base = datetime.fromisoformat(f"{due}T{due_time or '09:00'}").replace(tzinfo=TZ)
            for off in rems.split(","):
                if base - timedelta(minutes=int(off)) <= now:
                    reminded.append(f"{due} {due_time or ''}|{off}")
        repeat = rr_norm(r.get("Repeat") or "")
        if repeat and (rr_problem(repeat) or (due and not rr_feasible(repeat, due))):
            repeat = ""  # ERULE / custom date lists / sub-daily or never matching rules are not supported
        try:
            rems = clean_reminders(rems)
        except BadInput:
            rems = ""
        if due and not valid_date(due):
            due, due_time, start = None, None, None
        cur_id = insert_id(c, 
            """INSERT INTO tasks(list_id,section_id,title,content,priority,status,due,due_time,reminders,
               reminded,repeat,sort,created_at,updated_at,completed_at,tt_id,start,created_by,completed_by)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lid, sec, (r.get("Title") or tr("(untitled)", lg=lang(c, uid))).strip(), content, int(r.get("Priority") or 0),
             status, due, due_time, rems, json.dumps(reminded), repeat, stats["tasks"], created, ts, completed, tt,
             start, uid, uid if completed else None))
        idmap[tt] = cur_id
        tags = [t.strip() for t in (r.get("Tags") or "").split(",") if t.strip()]
        if tags:
            set_tags(c, cur_id, tags, uid)
        stats["tasks"] += 1
        r["_id"] = cur_id
    for r in rows:  # second pass: parents (same list only, never a cycle: see check_parent)
        p = r.get("parentId")
        if p and r.get("_id") and p in idmap and idmap[p] != r["_id"]:
            pl = c.execute("SELECT list_id FROM tasks WHERE id=?", (idmap[p],)).fetchone()
            me_l = c.execute("SELECT list_id FROM tasks WHERE id=?", (r["_id"],)).fetchone()
            if not pl or not me_l or pl[0] != me_l[0] or r["_id"] in ancestors(c, idmap[p]) \
                    or idmap[p] in descendants(c, r["_id"]):
                stats.setdefault("parents_skipped", 0)
                stats["parents_skipped"] += 1
                continue
            c.execute("UPDATE tasks SET parent_id=? WHERE id=?", (idmap[p], r["_id"]))
    bump(c)
    c.commit()
    return stats


@app.post("/api/import/ticktick")
def import_api():
    f = request.files.get("file")
    if not f:
        return err(tr("File missing"))
    raw = f.read(IMPORT_MAX_MB * 1048576 + 1)  # 2.148.1 E (#2496): the limits of the other importers
    if len(raw) > IMPORT_MAX_MB * 1048576:
        return err(tr("The file is too large (at most {0} MB)", IMPORT_MAX_MB), 413)
    try:
        stats = import_ticktick(db(), raw.decode("utf-8-sig"), me())
    except (ValueError, KeyError) as e:
        return err(str(e))
    return jsonify(stats)


# ---------------------------------------------------------------- package C: importers
# Todoist (CSV per project, the backup ZIP of those CSVs, Sync API JSON), Trello (board JSON), Asana (CSV), Microsoft To Do
# (Outlook / export tool CSV, or ICS) and ICS / VTODO (Apple Reminders exports, Nextcloud Tasks, Thunderbird, any CalDAV
# client). Every source is parsed into one neutral plan (lists > tasks, warnings for what cannot be mapped); imp_run then
# writes the plan for one user in ONE transaction: a dry run executes exactly the same code and rolls back, so the preview
# shows the real numbers. Nothing inside a file is ever fetched (attachment links become text in the notes), formula
# cells stay plain text, everything is validated like the app's own input (clean_task) and escaped by the client.
# Idempotent: every task gets tasks.tt_id = "<source>:<id>" (the source's own id, or a hash of list / section / parent
# chain / title / occurrence for formats without ids), unique per user -> importing the same file again skips it.
# Undo: the ids an import created are kept in the imports table; POST /api/imports/<id>/undo removes them again
# (IMPORT_UNDO_HOURS). Limits: IMPORT_MAX_MB per file, IMPORT_MAX_TASKS per import, ZIP / JSON bomb guards, rate limit.
def _imp_env(name, dflt):
    try:
        return max(1, int(os.environ.get(name, "") or dflt))
    except ValueError:
        return dflt


IMPORT_MAX_MB = _imp_env("KALMIDO_IMPORT_MAX_MB", 20)
IMPORT_MAX_TASKS = _imp_env("KALMIDO_IMPORT_MAX_TASKS", 20000)
IMPORT_ZIP_MEMBERS = 300                  # files in a ZIP
IMPORT_ZIP_RATIO = 200                    # max. uncompressed / compressed per member (bigger = zip bomb)
IMPORT_JSON_DEPTH = 40                    # nesting of a JSON file (Trello: ~6)
IMPORT_UNDO_HOURS = 24
IMPORT_RATE = _imp_env("KALMIDO_IMPORT_RATE", 30)  # imports + previews per user and 10 minutes
IMPORT_KEEP = 20                          # import records (undo) kept per user
IMPORT_SOURCES = {"todoist": "Todoist", "trello": "Trello", "asana": "Asana", "mstodo": "Microsoft To Do", "ics": "ICS",
                  # 2.142.0 B (#2147): file imports only (no API / OAuth connection, nothing fetched from the files)
                  "notion": "Notion", "gtasks": "Google Tasks", "clickup": "ClickUp", "jira": "Jira", "csv": "CSV", "markdown": "Markdown"}
IMPORT_OPTS = ("dry_run", "target", "mode", "archived", "completed", "list_name", "priority_scale", "space")
IMPORT_SAMPLES = 8
csv.field_size_limit(max(csv.field_size_limit(), 4 * CONTENT_MAX))
_IMP_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def imp_fail(key, *a):
    raise BadInput(tr(key, *a))


def imp_decode(data):
    """Bytes of a text file -> str: UTF-8 (with / without BOM), UTF-16 (BOM or detected), else Windows-1252."""
    try:
        if data.startswith(b"\xef\xbb\xbf"):
            s = data[3:].decode("utf-8")
        elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
            s = data.decode("utf-16")
        else:
            head = data[:4000]
            if len(head) >= 4 and head.count(b"\x00") > len(head) // 4:
                s = data.decode("utf-16-le" if head[1::2].count(0) > head[0::2].count(0) else "utf-16-be")
            else:
                if b"\x00" in data:
                    imp_fail(N_("This is not a text file"))
                try:
                    s = data.decode("utf-8")
                except UnicodeDecodeError:
                    s = data.decode("cp1252")
    except UnicodeDecodeError:
        imp_fail(N_("The text encoding of the file could not be read (UTF-8, UTF-16 or Windows-1252 expected)"))
    if "\x00" in s:
        imp_fail(N_("This is not a text file"))
    return s.lstrip("﻿")


def imp_line(v, n=TITLE_MAX):
    """One line of text from a file: no control / bidi characters, whitespace collapsed, cut to n."""
    return re.sub(r"\s+", " ", _IMP_CTRL.sub("", str(v or ""))).strip()[:n]


def imp_textblock(v, n=CONTENT_MAX):
    s = _IMP_CTRL.sub("", str(v or "").replace("\r\n", "\n").replace("\r", "\n"))
    return s.strip()[:n]


def imp_csv(text):
    """CSV text -> (lower-case header list, rows as dicts). Delimiter: , ; or tab (whatever the header uses most)."""
    first = text.split("\n", 1)[0]
    delim = max((",", ";", "\t"), key=first.count)
    try:
        rd = csv.reader(io.StringIO(text), delimiter=delim)
        head = next(rd, None)
        if not head:
            imp_fail(N_("The file is empty"))
        orig = [imp_line(h, 100) for h in head]
        keys = [h.lower() for h in orig]
        rows = []
        for r in rd:
            if not any(x.strip() for x in r):
                continue
            rows.append({k: (r[i] if i < len(r) else "") for i, k in enumerate(keys) if k})
            if len(rows) > IMPORT_MAX_TASKS * 3:
                imp_fail(N_("Too many rows (more than {0} tasks)"), IMPORT_MAX_TASKS)
    except csv.Error:
        imp_fail(N_("The CSV file could not be read"))
    return keys, rows, dict(zip(keys, orig))


def imp_json(text):
    """JSON with a nesting limit checked BEFORE parsing (a deeply nested file cannot exhaust the parser)."""
    depth = 0
    instr = esc_ = False
    for ch in text:
        if instr:
            if esc_:
                esc_ = False
            elif ch == "\\":
                esc_ = True
            elif ch == '"':
                instr = False
        elif ch == '"':
            instr = True
        elif ch in "[{":
            depth += 1
            if depth > IMPORT_JSON_DEPTH:
                imp_fail(N_("The JSON file is nested too deeply"))
        elif ch in "]}":
            depth -= 1
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        imp_fail(N_("The JSON file could not be read"))


def imp_zip(data, exts, full=False):
    """Members of a ZIP (read in memory, never extracted to disk) with the given extensions: [(name, bytes)].
    Guards: member count, total and per-member size (declared AND actually read), compression ratio."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        imp_fail(N_("The ZIP file could not be read"))
    if len(infos) > IMPORT_ZIP_MEMBERS:
        imp_fail(N_("The ZIP file contains too many files"))
    budget, out = IMPORT_MAX_MB * 1048576 * 3, []
    for i in infos:
        base = i.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if i.is_dir() or not base or i.filename.startswith("__MACOSX/") or base.startswith("._") \
                or not base.lower().endswith(exts):
            continue
        if i.file_size > budget or (i.file_size > 1048576 and i.file_size > max(1, i.compress_size) * IMPORT_ZIP_RATIO):
            imp_fail(N_("The ZIP file unpacks to too much data"))
        try:
            with zf.open(i) as f:
                b = f.read(min(budget, i.file_size) + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError):
            imp_fail(N_("The ZIP file could not be read"))
        if len(b) > i.file_size or len(b) > budget:
            imp_fail(N_("The ZIP file unpacks to too much data"))
        budget -= len(b)
        out.append((i.filename.replace("\\", "/") if full else base, b))  # 2.142.0 B (#2147): full = the path inside the ZIP
    return out


def imp_stem(name):
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"\.(csv|json|ics|ical|ifb|txt|zip|md|markdown)$", "", base, flags=re.I)
    return imp_line(re.sub(r"\s*\[\d+\]$", "", base), LIST_NAME_MAX)  # Todoist backup: "Name [2203306141].csv"


def imp_hash(*parts):
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:24]


# ---- the neutral plan
def imp_plan(source):
    return {"source": source, "lists": [], "warn": {}}


def imp_list(plan, name, folder="", inbox=False):
    L = {"name": imp_line(name, LIST_NAME_MAX), "folder": folder_seg(imp_line(folder, FOLDER_MAX)), "view": "list", "inbox": inbox,
         "tasks": [], "sections": []}
    plan["lists"].append(L)
    return L


def imp_warn(plan, key, title=None, *a):
    """Collected per text (key + args): count + up to 3 example task titles."""
    k = (key,) + tuple(str(x) for x in a)
    w = plan["warn"].setdefault(k, {"n": 0, "ex": []})
    w["n"] += 1
    if title and len(w["ex"]) < 3:
        w["ex"].append(imp_line(title, 80))


def imp_task(L, ext, title, **k):
    t = {"ext": str(ext)[:200], "title": imp_line(title), "notes": "", "priority": 0, "status": 0, "due": None, "due_time": None,
         "start": None, "repeat": "", "repeat_from": "due", "reminders": [], "tags": [], "section": None, "parent": None,
         "completed_at": None, "created_at": None, "url": None, "duration": None, "assignee": None}
    t.update(k)
    if t["section"]:
        t["section"] = imp_line(t["section"], LIST_NAME_MAX) or None
        if t["section"] and t["section"] not in L["sections"]:
            L["sections"].append(t["section"])
    L["tasks"].append(t)
    return t


def imp_addnote(t, text):
    text = imp_textblock(text)
    if text:
        t["notes"] = (t["notes"] + "\n\n" + text) if t["notes"] else text


# ---- dates
def imp_local(v):
    """date / datetime (aware -> server time zone, naive = local) -> (YYYY-MM-DD, HH:MM | None)."""
    if isinstance(v, datetime):
        if v.tzinfo:
            v = v.astimezone(TZ)
        return v.date().isoformat(), v.strftime("%H:%M")
    if isinstance(v, date):
        return v.isoformat(), None
    return None, None


def imp_iso(s, tzname=None):
    """'2025-01-15', '2025-01-15T10:00[:00][.000][Z|+01:00]', '2025-01-15 10:00' -> (date, time | None); None, None if not ISO."""
    s = str(s or "").strip()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?\s*(Z|[+-]\d{2}:?\d{2})?)?", s)
    if not m:
        return None, None
    if not m.group(2):
        return (m.group(1), None) if valid_date(m.group(1)) else (None, None)
    try:
        dt = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4) or '00'}")
    except ValueError:
        return None, None
    z = m.group(5)
    if z:
        dt = dt.replace(tzinfo=timezone.utc) if z == "Z" else \
            dt.replace(tzinfo=timezone(timedelta(hours=int(z[1:3]), minutes=int(z[-2:])) * (1 if z[0] == "+" else -1)))
    elif tzname:
        with contextlib.suppress(Exception):
            dt = dt.replace(tzinfo=ZoneInfo(str(tzname)))
    return imp_local(dt)


def imp_ts(s):
    """A creation / completion timestamp from a file -> UTC ISO (None if unreadable)."""
    if isinstance(s, datetime):
        return iso(s if s.tzinfo else s.replace(tzinfo=TZ))
    if isinstance(s, date):
        return iso(datetime(s.year, s.month, s.day, 12, tzinfo=TZ))
    s = str(s or "").strip()
    if not s:
        return None
    with contextlib.suppress(ValueError, OverflowError):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return iso(dt if dt.tzinfo else dt.replace(tzinfo=TZ))
    d, t = imp_numdate(s)
    if d:
        return iso(datetime.fromisoformat(f"{d}T{t or '12:00'}").replace(tzinfo=TZ))
    return None


def imp_numdate(s, dmy=None):
    """Numeric dates of CSV exports: 15.01.2025, 1/15/2025 (US; 15/1/2025 when the day is > 12 or dmy), 2025-01-15,
    optionally with a time (10:00[:00] [AM|PM]). -> (date, time | None)."""
    s = str(s or "").strip()
    d, t = imp_iso(s)
    if d:
        return d, t
    m = re.fullmatch(r"(\d{1,2})([./-])(\d{1,2})\2(\d{2,4})(?:,?\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?)?", s)
    if not m:
        return None, None
    a, b, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
    y += 2000 if y < 100 else 0
    if m.group(2) == ".":
        day, mon = a, b
    elif dmy or a > 12:
        day, mon = a, b
    else:
        mon, day = a, b
    try:
        dd = date(y, mon, day).isoformat()
    except ValueError:
        return None, None
    if not valid_date(dd):
        return None, None
    tm = None
    if m.group(5):
        h, mi = int(m.group(5)), int(m.group(6))
        ap = (m.group(7) or "").lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        tm = f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None
    return dd, tm


# natural-language dates of Todoist exports (DATE column = what the user typed, e.g. "every monday", "Jan 15", "15 Okt"),
# English and German -- the grammar of the quick-add parser (static/js/quickadd.js parseQuick) plus absolute dates
IMP_MONTHS = {"jan": 1, "january": 1, "januar": 1, "jän": 1, "jänner": 1, "feb": 2, "february": 2, "februar": 2, "mar": 3,
              "march": 3, "mär": 3, "märz": 3, "maerz": 3, "apr": 4, "april": 4, "may": 5, "mai": 5, "jun": 6, "june": 6,
              "juni": 6, "jul": 7, "july": 7, "juli": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
              "oct": 10, "october": 10, "okt": 10, "oktober": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
              "dez": 12, "dezember": 12}
IMP_WDAYS = {"mon": 0, "monday": 0, "montag": 0, "tue": 1, "tues": 1, "tuesday": 1, "dienstag": 1, "wed": 2, "wednesday": 2,
             "mittwoch": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "donnerstag": 3, "fri": 4, "friday": 4, "freitag": 4,
             "sat": 5, "saturday": 5, "samstag": 5, "sonnabend": 5, "sun": 6, "sunday": 6, "sonntag": 6,
             "mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6}
IMP_RRWD = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_MON_RE = "|".join(sorted(IMP_MONTHS, key=len, reverse=True))
_WD_RE = "|".join(sorted(IMP_WDAYS, key=len, reverse=True))


def _imp_today():
    return local_now().date()


def _imp_md(mon, day, year):
    """Month + day (+ optional year) -> date; without a year: this year, or next year if it is long past."""
    t = _imp_today()
    try:
        d = date(int(year) if year else t.year, mon, int(day))
    except ValueError:
        return None
    if not year and (t - d).days > 60:
        with contextlib.suppress(ValueError):
            d = d.replace(year=d.year + 1)
    return d


def _imp_single(s):
    """One date expression (no time, no repetition) -> date or None."""
    t = _imp_today()
    s = re.sub(r"^(on|am|the|den|dem)\s+", "", s.strip()).strip()
    rel = {"today": 0, "heute": 0, "tod": 0, "tomorrow": 1, "morgen": 1, "tom": 1, "übermorgen": 2,
           "day after tomorrow": 2, "the day after tomorrow": 2, "yesterday": -1, "gestern": -1}
    if s in rel:
        return t + timedelta(days=rel[s])
    m = re.fullmatch(rf"(?:(next|nächsten|nächste|kommenden|this|diesen)\s+)?({_WD_RE})", s)
    if m:
        wd = IMP_WDAYS[m.group(2)]
        n = (wd - t.weekday()) % 7 or 7
        if m.group(1) in ("next", "nächsten", "nächste", "kommenden") and n < 7:
            n = 7 - t.weekday() + wd  # next week's day
        return t + timedelta(days=n)
    if s in ("next week", "nächste woche"):
        return t + timedelta(days=7 - t.weekday())
    if s in ("next month", "nächsten monat"):
        return (t.replace(day=1) + timedelta(days=32)).replace(day=1)
    if s in ("weekend", "this weekend", "wochenende", "am wochenende"):
        return t + timedelta(days=(5 - t.weekday()) % 7)
    m = re.fullmatch(r"in\s+(\d+|a|an|one|einem|einer|eine)\s+(days?|weeks?|months?|years?|tagen?|wochen?|monaten?|monat|jahren?|jahr)", s)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else 1
        u = m.group(2)
        if u.startswith(("day", "tag")):
            return t + timedelta(days=n)
        if u.startswith(("week", "woche")):
            return t + timedelta(days=7 * n)
        mo = t.month - 1 + (n * 12 if u.startswith(("year", "jahr")) else n)
        y, mo = t.year + mo // 12, mo % 12 + 1
        return _imp_md(mo, min(t.day, 28), y)
    d, _ = imp_numdate(s)
    if d:
        return date.fromisoformat(d)
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.?", s)  # 15.01. / 15.1
    if m:
        return _imp_md(int(m.group(2)), m.group(1), None)
    m = re.fullmatch(rf"({_MON_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th|\.)?(?:,?\s+(\d{{4}}))?", s)
    if m:
        return _imp_md(IMP_MONTHS[m.group(1)], m.group(2), m.group(3))
    m = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th|\.)?\s+(?:of\s+)?({_MON_RE})\.?(?:,?\s+(\d{{4}}))?", s)
    if m:
        return _imp_md(IMP_MONTHS[m.group(2)], m.group(1), m.group(3))
    return None


def _imp_time(s):
    """Pulls a time out of s -> (rest, HH:MM | None)."""
    pats = [r"(?:\s|^)(?:at|um|@)?\s*(\d{1,2}):(\d{2})\s*(am|pm|uhr|h)?(?=\s|$)",
            r"(?:\s|^)(?:at|um|@)?\s*(\d{1,2})()\s*(am|pm|uhr|h)(?=\s|$)"]
    for p in pats:
        m = re.search(p, s)
        if m:
            h, mi = int(m.group(1)), int(m.group(2) or 0)
            ap = m.group(3) or ""
            if ap == "pm" and h < 12:
                h += 12
            if ap == "am" and h == 12:
                h = 0
            if h > 23 or mi > 59:
                return s, None
            return (s[:m.start()] + " " + s[m.end():]).strip(), f"{h:02d}:{mi:02d}"
    for w, hm in (("morning", "09:00"), ("morgens", "09:00"), ("afternoon", "14:00"), ("nachmittags", "14:00"),
                  ("evening", "19:00"), ("abends", "19:00"), ("noon", "12:00"), ("mittags", "12:00")):
        if re.search(rf"(?:^|\s){w}$", s):
            return re.sub(rf"(?:^|\s)(?:in the\s+)?{w}$", "", s).strip(), hm
    return s, None


def _imp_rrule(body):
    """What follows "every" / "jeden" -> RRULE body or None."""
    b = re.sub(r"\s+", " ", body.replace(" and ", ", ").replace(" und ", ", ")).strip(" ,")
    if b in ("day", "tag", "days", "tage"):
        return "FREQ=DAILY"
    if b in ("other day", "zweiten tag"):
        return "FREQ=DAILY;INTERVAL=2"
    if b in ("week", "woche"):
        return "FREQ=WEEKLY"
    if b in ("other week", "zweite woche"):
        return "FREQ=WEEKLY;INTERVAL=2"
    if b in ("month", "monat"):
        return "FREQ=MONTHLY"
    if b in ("other month", "zweiten monat"):
        return "FREQ=MONTHLY;INTERVAL=2"
    if b in ("year", "jahr"):
        return "FREQ=YEARLY"
    if b in ("workday", "weekday", "work day", "werktag", "arbeitstag"):
        return "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    if b in ("weekend", "wochenende"):
        return "FREQ=WEEKLY;BYDAY=SA,SU"
    m = re.fullmatch(r"(\d{1,3}) (days?|weeks?|months?|years?|tage|wochen|monate|jahre)", b)
    if m:
        u = m.group(2)
        f = "DAILY" if u.startswith(("day", "tag")) else "WEEKLY" if u.startswith(("week", "woche")) else \
            "MONTHLY" if u.startswith(("month", "monat")) else "YEARLY"
        n = int(m.group(1))
        return f"FREQ={f}" + (f";INTERVAL={n}" if n > 1 else "") if n else None
    days = [x.strip() for x in b.split(",")]
    if days and all(x in IMP_WDAYS for x in days):
        return "FREQ=WEEKLY;BYDAY=" + ",".join(dict.fromkeys(IMP_RRWD[IMP_WDAYS[x]] for x in days))
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th|\.)?", b)
    if m and 1 <= int(m.group(1)) <= 31:
        return f"FREQ=MONTHLY;BYMONTHDAY={int(m.group(1))}"
    if b in ("last day", "letzten tag", "last day of the month", "letzten tag im monat"):
        return "FREQ=MONTHLY;BYMONTHDAY=-1"
    m = re.fullmatch(rf"({_MON_RE})\.? (\d{{1,2}})(?:st|nd|rd|th|\.)?|(\d{{1,2}})(?:st|nd|rd|th|\.)? ({_MON_RE})\.?", b)
    if m:
        mon, day = (IMP_MONTHS[m.group(1)], m.group(2)) if m.group(1) else (IMP_MONTHS[m.group(4)], m.group(3))
        return f"FREQ=YEARLY;BYMONTH={mon};BYMONTHDAY={int(day)}"
    return None


def imp_nl_date(text, lg="en"):
    """Todoist DATE text -> {due, time, repeat, repeat_from} or None (not understood). lg: DATE_LANG (en / de only)."""
    s = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not s:
        return None
    iso_d, iso_t = imp_iso(s)
    if iso_d:
        return {"due": iso_d, "time": iso_t, "repeat": "", "repeat_from": "due"}
    if lg not in ("en", "de", ""):
        d, t = imp_numdate(s)
        return {"due": d, "time": t, "repeat": "", "repeat_from": "due"} if d else None
    s, tm = _imp_time(s)
    m = re.match(r"^(every!|ev!|every|ev|each|jeden!|jede!|jedes!|alle!|jeden|jede|jedes|alle)\s+(.+)$", s)
    words = {"daily": "day", "täglich": "tag", "weekly": "week", "wöchentlich": "woche", "monthly": "month", "monatlich": "monat",
             "yearly": "year", "annually": "year", "jährlich": "jahr", "weekdays": "workday", "werktags": "werktag"}
    if m or s in words:
        after = m.group(1).endswith("!") if m else False
        body = m.group(2) if m else words[s]
        until = None
        m2 = re.search(r"\s(?:starting|from|ab|beginnend|until|bis|ending|for)\s.*$", " " + body)
        if m2:
            tail = (" " + body)[m2.start():].strip()
            body = (" " + body)[:m2.start()].strip()
            mu = re.match(r"(?:until|bis|ending)\s+(.+)$", tail)
            if mu:
                ud = _imp_single(mu.group(1))
                until = ud.strftime("%Y%m%d") if ud else None
        rr = _imp_rrule(body)
        if not rr:
            return None
        if until:
            rr += ";UNTIL=" + until
        t0 = _imp_today()
        try:
            nxt = rrulestr(rr.split(";UNTIL=")[0], dtstart=datetime(t0.year, t0.month, t0.day)).after(
                datetime(t0.year, t0.month, t0.day), inc=True)
        except (ValueError, TypeError, OverflowError):
            return None
        return {"due": (nxt.date() if nxt else t0).isoformat(), "time": tm, "repeat": rr, "repeat_from": "done" if after else "due"}
    if not s and tm:
        return {"due": _imp_today().isoformat(), "time": tm, "repeat": "", "repeat_from": "due"}
    d = _imp_single(s)
    if not d or not valid_date(d.isoformat()):
        return None
    return {"due": d.isoformat(), "time": tm, "repeat": "", "repeat_from": "due"}


def imp_prio_word(v):
    v = str(v or "").strip().lower()
    return {"high": 5, "hoch": 5, "urgent": 5, "dringend": 5, "wichtig": 5, "important": 5, "medium": 3, "mittel": 3,
            "normal": 0, "low": 1, "niedrig": 1, "gering": 1}.get(v, 0)


def imp_tags(v, sep=r"[,;]"):
    return [x for x in (imp_line(t, 100).lstrip("#") for t in re.split(sep, str(v or ""))) if x][:50]


# ---- Todoist
def parse_todoist(data, fname, opts, plan):
    if data[:4] == b"PK\x03\x04":  # the backup ZIP: one CSV per project
        members = imp_zip(data, (".csv",))
        if not members:
            imp_fail(N_("No CSV files found in the ZIP file"))
        for name, b in members:
            _todoist_csv(imp_decode(b), name, opts, plan)
        return
    text = imp_decode(data)
    if text.lstrip()[:1] in ("{", "["):
        return _todoist_json(imp_json(text), plan)
    _todoist_csv(text, fname, opts, plan)


_TD_FILE = re.compile(r"\[\[file\s+(\{.*?\})\]\]", re.S)


def _todoist_files(s):
    """'[[file {"file_name": .., "file_url": ..}]]' -> 'Attachment: name (url)' lines (links only, never fetched)."""
    def one(m):
        try:
            j = json.loads(m.group(1))
            return "\n" + tr("Attachment: {0}", imp_line(j.get("file_name") or j.get("name") or "file", 200)) + \
                (f" ({imp_line(j.get('file_url') or j.get('url'), 2000)})" if j.get("file_url") or j.get("url") else "")
        except (ValueError, AttributeError):
            return ""
    return _TD_FILE.sub(one, s)


def _todoist_labels(content):
    tags = re.findall(r"(?:(?<=\s)|^)@([\w\-/.:&]+)", content)
    title = re.sub(r"(?:(?<=\s)|^)@[\w\-/.:&]+", " ", content)
    return imp_line(title), [imp_line(x, 100) for x in tags if imp_line(x, 100)]


def _todoist_date(t, text, lg, tzname, plan, what="DATE"):
    r = imp_nl_date(text, (lg or "en").lower()[:2])
    if not r:
        imp_warn(plan, N_("Date not understood, kept in the notes: {0}"), t["title"], imp_line(text, 60))
        imp_addnote(t, tr("Due (Todoist): {0}", imp_line(text, 200)))
        return
    d, tm = r["due"], r["time"]
    if tm and tzname and str(tzname) != str(TZ.key):  # a time in the task's own time zone -> the server's
        with contextlib.suppress(Exception):
            dt = datetime.fromisoformat(f"{d}T{tm}").replace(tzinfo=ZoneInfo(str(tzname))).astimezone(TZ)
            d, tm = dt.date().isoformat(), dt.strftime("%H:%M")
    t.update(due=d, due_time=tm)
    if r["repeat"]:
        t.update(repeat=r["repeat"], repeat_from=r["repeat_from"])


def _todoist_csv(text, fname, opts, plan):
    keys, rows, _ = imp_csv(text)
    if "type" not in keys or "content" not in keys:
        imp_fail(N_("This is not a Todoist CSV export (columns TYPE and CONTENT missing)"))
    name = imp_stem(fname) or "Todoist"
    L = imp_list(plan, name, inbox=name.lower() in ("inbox", "eingang"))
    raw = [(r.get("priority") or "").strip() for r in rows if (r.get("type") or "").strip().lower() == "task"]
    scale = opts.get("priority_scale") or "auto"
    if scale == "auto":
        n1, n4 = raw.count("1"), raw.count("4")
        scale = "4" if n1 > n4 else "1"  # most tasks carry the lowest priority: that end tells the direction
        if any(x and x not in ("1", "4") for x in raw) or (n1 and n4):
            imp_warn(plan, N_("Todoist priorities read as {0} = p1 (highest); if that is wrong, choose the other scale"), None, scale)
    pmap = {"1": 5, "2": 3, "3": 1, "4": 0} if scale == "1" else {"4": 5, "3": 3, "2": 1, "1": 0}
    section, stack, last, seen = None, [], None, {}
    for r in rows:
        typ = (r.get("type") or "").strip().lower()
        content = r.get("content") or ""
        if typ == "meta":
            if "view_style=board" in content:
                L["view"] = "kanban"
            continue
        if typ == "section":
            section, stack = imp_line(content, LIST_NAME_MAX) or None, []
            if section and section not in L["sections"]:
                L["sections"].append(section)
            continue
        if typ == "note":
            if last is not None:
                who = imp_line(re.sub(r"\s*\(\d+\)$", "", r.get("author") or ""), 100)
                body = _todoist_files(content)
                last.setdefault("_comments", []).append(f"**{who}**: {body.strip()}" if who else body.strip())
            continue
        if typ != "task":
            continue
        uncompletable = content.lstrip().startswith("* ")
        title, tags = _todoist_labels(content.lstrip()[2:] if uncompletable else content)
        try:
            indent = max(1, min(9, int((r.get("indent") or "1").strip() or 1)))
        except ValueError:
            indent = 1
        stack = stack[:indent - 1]
        parent = stack[-1] if stack else None
        chain = "/".join(x["title"] for x in stack)
        key = (section, chain, title)
        seen[key] = seen.get(key, 0) + 1
        t = imp_task(L, imp_hash(name, section, chain, title, seen[key]), title or tr("(untitled)"), tags=tags, section=section,
                     parent=parent["ext"] if parent else None, priority=pmap.get((r.get("priority") or "").strip(), 0))
        stack.append(t)
        last = t
        imp_addnote(t, r.get("description"))
        if uncompletable:
            imp_warn(plan, N_("Headings without a checkbox (* ...) became normal tasks"), t["title"])
        resp = imp_line(re.sub(r"\s*\(\d+\)$", "", r.get("responsible") or ""), 100)
        if resp:
            t["assignee"] = {"name": resp}
        if (r.get("date") or "").strip():
            _todoist_date(t, r["date"], r.get("date_lang"), (r.get("timezone") or "").strip(), plan)
        dl = (r.get("deadline") or "").strip()
        if dl:
            if not t["due"]:
                _todoist_date(t, dl, r.get("deadline_lang") or r.get("date_lang"), None, plan)
            else:
                imp_addnote(t, tr("Deadline (Todoist): {0}", imp_line(dl, 100)))
        dur = (r.get("duration") or "").strip()
        unit = (r.get("duration_unit") or "").strip().lower()
        if dur.isdigit() and int(dur) > 0 and unit in ("minute", "day"):
            mins = int(dur) * (1440 if unit == "day" else 1)
            t["duration"] = mins if mins <= DURATION_MAX else None
    for t in L["tasks"]:
        if t.get("_comments"):
            imp_addnote(t, tr("Comments (Todoist):") + "\n" + "\n\n".join(t.pop("_comments")))


def _todoist_json(j, plan):
    """Sync API / full export JSON: {projects, sections, items | tasks, notes | comments, collaborators}."""
    if not isinstance(j, dict) or not isinstance(j.get("projects"), list) \
            or not isinstance(j.get("items", j.get("tasks")), list):
        imp_fail(N_("This is not a Todoist export (projects and items missing)"))
    projects = {str(p.get("id")): p for p in j["projects"] if isinstance(p, dict)}
    secs = {str(s.get("id")): imp_line(s.get("name"), LIST_NAME_MAX) for s in j.get("sections") or [] if isinstance(s, dict)}
    people = {str(p.get("id")): p for p in j.get("collaborators") or [] if isinstance(p, dict)}
    notes = {}
    for n in (j.get("notes") or j.get("comments") or []):
        if isinstance(n, dict) and n.get("item_id") is not None:
            notes.setdefault(str(n["item_id"]), []).append(n)
    lists = {}
    for pid, p in projects.items():
        if p.get("is_deleted") or p.get("is_archived"):
            continue
        par = projects.get(str(p.get("parent_id"))) if p.get("parent_id") else None
        lists[pid] = imp_list(plan, p.get("name") or "Todoist", folder=(par or {}).get("name") or "",
                              inbox=bool(p.get("inbox_project")))
        if p.get("view_style") == "board":
            lists[pid]["view"] = "kanban"
    items = [x for x in j.get("items", j.get("tasks")) if isinstance(x, dict)]
    items.sort(key=lambda x: (x.get("child_order") or x.get("order") or 0) if isinstance(x.get("child_order") or x.get("order") or 0, int) else 0)
    for it in items:
        L = lists.get(str(it.get("project_id")))
        if L is None or it.get("is_deleted"):
            continue
        title, tags = _todoist_labels(str(it.get("content") or ""))
        tags += [imp_line(x, 100) for x in it.get("labels") or [] if isinstance(x, str) and imp_line(x, 100)]
        pr = it.get("priority")
        t = imp_task(L, it.get("id") or imp_hash(title), title or tr("(untitled)"), tags=list(dict.fromkeys(tags)),
                     section=secs.get(str(it.get("section_id"))) if it.get("section_id") else None,
                     parent=str(it["parent_id"]) if it.get("parent_id") else None,
                     priority={4: 5, 3: 3, 2: 1}.get(pr if isinstance(pr, int) else 0, 0),
                     created_at=imp_ts(it.get("added_at") or it.get("created_at")))
        imp_addnote(t, it.get("description"))
        if it.get("checked") or it.get("is_completed"):
            t.update(status=2, completed_at=imp_ts(it.get("completed_at")) or iso(now_utc()))
        due = it.get("due") if isinstance(it.get("due"), dict) else None
        if due:
            d, tm = imp_iso(due.get("date"), due.get("timezone"))
            if d:
                t.update(due=d, due_time=tm)
            if due.get("is_recurring") and due.get("string"):
                r = imp_nl_date(due["string"], str(due.get("lang") or "en")[:2])
                if r and r["repeat"]:
                    t.update(repeat=r["repeat"], repeat_from=r["repeat_from"])
                else:
                    imp_warn(plan, N_("Repetition not understood, kept in the notes: {0}"), t["title"], imp_line(due["string"], 60))
                    imp_addnote(t, tr("Repeats (Todoist): {0}", imp_line(due["string"], 200)))
            elif not d and due.get("string"):
                _todoist_date(t, due["string"], due.get("lang"), None, plan)
        dur = it.get("duration") if isinstance(it.get("duration"), dict) else None
        if dur and isinstance(dur.get("amount"), int) and dur["amount"] > 0:
            mins = dur["amount"] * (1440 if dur.get("unit") == "day" else 1)
            t["duration"] = mins if mins <= DURATION_MAX else None
        rp = people.get(str(it.get("responsible_uid"))) if it.get("responsible_uid") else None
        if rp:
            t["assignee"] = {"name": imp_line(rp.get("full_name"), 100), "email": imp_line(rp.get("email"), 200)}
        cm = []
        for n in notes.get(str(it.get("id")), []):
            body = imp_textblock(n.get("content"), 20000)
            fa = n.get("file_attachment") if isinstance(n.get("file_attachment"), dict) else None
            if fa:
                body += "\n" + tr("Attachment: {0}", imp_line(fa.get("file_name") or "file", 200)) + \
                    (f" ({imp_line(fa.get('file_url'), 2000)})" if fa.get("file_url") else "")
            who = people.get(str(n.get("posted_uid")), {}).get("full_name")
            cm.append((f"**{imp_line(who, 100)}**: " if who else "") + body.strip())
        if cm:
            imp_addnote(t, tr("Comments (Todoist):") + "\n" + "\n\n".join(cm))


# ---- Trello
def parse_trello(data, fname, opts, plan):
    j = imp_json(imp_decode(data))
    if not isinstance(j, dict) or not isinstance(j.get("cards"), list) or not isinstance(j.get("lists"), list):
        imp_fail(N_("This is not a Trello board export (JSON with lists and cards expected)"))
    board = imp_line(j.get("name"), LIST_NAME_MAX) or imp_stem(fname) or "Trello"
    archived = opts.get("archived") or "skip"
    as_lists = opts.get("mode") == "lists"
    labels = {str(x.get("id")): imp_line(x.get("name") or x.get("color"), 100) for x in j.get("labels") or [] if isinstance(x, dict)}
    members = {str(m.get("id")): m for m in j.get("members") or [] if isinstance(m, dict)}
    checklists = {}
    for cl in j.get("checklists") or []:
        if isinstance(cl, dict):
            checklists.setdefault(str(cl.get("idCard")), []).append(cl)
    comments = {}
    for a in j.get("actions") or []:
        if isinstance(a, dict) and a.get("type") == "commentCard" and isinstance(a.get("data"), dict):
            cid = str((a["data"].get("card") or {}).get("id"))
            comments.setdefault(cid, []).append(a)
    tl = sorted((x for x in j["lists"] if isinstance(x, dict)), key=lambda x: _imp_num(x.get("pos")))
    closed_lists = {str(x.get("id")) for x in tl if x.get("closed")}
    dest, one = {}, None
    for x in tl:
        if x.get("closed") and archived == "skip":
            continue
        nm = imp_line(x.get("name"), LIST_NAME_MAX) or "Trello"
        if as_lists:
            dest[str(x.get("id"))] = (imp_list(plan, nm, folder=board), None)
        else:
            one = one or imp_list(plan, board)
            dest[str(x.get("id"))] = (one, nm)
            if nm not in one["sections"]:
                one["sections"].append(nm)
    if not as_lists and one is None:
        one = imp_list(plan, board)
    skipped = 0
    for cd in sorted((x for x in j["cards"] if isinstance(x, dict)), key=lambda x: _imp_num(x.get("pos"))):
        lid = str(cd.get("idList"))
        closed = bool(cd.get("closed")) or lid in closed_lists
        if closed and archived == "skip":
            skipped += 1
            continue
        if lid not in dest:
            continue
        L, sec = dest[lid]
        cid = str(cd.get("id") or "")
        created = None
        if re.fullmatch(r"[0-9a-f]{24}", cid):  # a Trello id starts with its creation time
            created = iso(datetime.fromtimestamp(int(cid[:8], 16), timezone.utc))
        tags = [labels.get(str(i)) or "" for i in cd.get("idLabels") or []]
        tags += [imp_line(x.get("name") or x.get("color"), 100) for x in cd.get("labels") or [] if isinstance(x, dict)]
        t = imp_task(L, (cid or imp_hash(cd.get("name"))), cd.get("name") or tr("(untitled)"), section=sec,
                     tags=list(dict.fromkeys(x for x in tags if x)), created_at=created)
        imp_addnote(t, cd.get("desc"))
        if cd.get("due"):
            d, tm = imp_iso(cd["due"])
            t.update(due=d, due_time=tm)
            rem = cd.get("dueReminder")
            if isinstance(rem, int) and not isinstance(rem, bool) and rem >= 0 and tm:
                t["reminders"] = [rem]
        if cd.get("start") and t["due"]:
            t["start"] = imp_iso(cd["start"])[0]
        if cd.get("dueComplete") or closed:
            t.update(status=2, completed_at=imp_ts(cd.get("dateLastActivity")) or iso(now_utc()))
        mem = [members.get(str(m)) for m in cd.get("idMembers") or [] if members.get(str(m))]
        if mem:
            t["assignee"] = {"name": imp_line(mem[0].get("fullName"), 100), "username": imp_line(mem[0].get("username"), 100)}
            if len(mem) > 1:
                imp_addnote(t, tr("Members (Trello): {0}", ", ".join(imp_line(m.get("fullName"), 100) for m in mem)))
        att = [a for a in cd.get("attachments") or [] if isinstance(a, dict)]
        if att:
            imp_addnote(t, tr("Attachments (links, not downloaded):") + "\n" + "\n".join(
                f"- {imp_line(a.get('name') or 'file', 200)}: {imp_line(a.get('url'), 2000)}" for a in att))
        if cd.get("customFieldItems"):
            imp_warn(plan, N_("Trello custom fields are not imported"), t["title"])
        cm = sorted(comments.get(cid, []), key=lambda a: str(a.get("date") or ""))
        if cm:
            imp_addnote(t, tr("Comments (Trello):") + "\n" + "\n\n".join(
                f"**{imp_line((a.get('memberCreator') or {}).get('fullName'), 100)}**, {str(a.get('date') or '')[:10]}: "
                f"{imp_textblock(a['data'].get('text'), 20000)}" for a in cm))
        cls = sorted(checklists.get(cid, []), key=lambda x: _imp_num(x.get("pos")))
        for cl in cls:
            par = t
            if len(cls) > 1:  # several checklists: one subtask per checklist, its items below
                par = imp_task(L, "cl:" + str(cl.get("id")), cl.get("name") or tr("Checklist"), section=sec, parent=t["ext"])
            for it in sorted((x for x in cl.get("checkItems") or [] if isinstance(x, dict)), key=lambda x: _imp_num(x.get("pos"))):
                s = imp_task(L, "ci:" + str(it.get("id")), it.get("name") or tr("(untitled)"), section=sec, parent=par["ext"])
                if it.get("state") == "complete":
                    s.update(status=2, completed_at=t["completed_at"] or iso(now_utc()))
                if it.get("due"):
                    s["due"], s["due_time"] = imp_iso(it["due"])
    if skipped:
        imp_warn(plan, N_("Archived cards and cards in archived lists were skipped"), None)
        plan["warn"][(N_("Archived cards and cards in archived lists were skipped"),)]["n"] = skipped


def _imp_num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else 0


# ---- Asana
ASANA_STD = {"task id", "created at", "completed at", "last modified", "name", "section/column", "assignee", "assignee email",
             "start date", "due date", "tags", "notes", "projects", "parent task", "priority"}


def parse_asana(data, fname, opts, plan):
    keys, rows, head = imp_csv(imp_decode(data))
    if "task id" not in keys or "name" not in keys:
        imp_fail(N_("This is not an Asana CSV export (columns Task ID and Name missing)"))
    lists, by_name, extra = {}, {}, [k for k in keys if k and k not in ASANA_STD]
    for r in rows:
        tid = imp_line(r.get("task id"), 100)
        title = imp_line(r.get("name"))
        if not tid and not title:
            continue
        proj = imp_line((r.get("projects") or "").split(",")[0], LIST_NAME_MAX) or imp_stem(fname) or "Asana"
        L = lists.get(proj) or lists.setdefault(proj, imp_list(plan, proj))
        pname = imp_line(r.get("parent task"))
        parent = by_name.get((proj, pname)) or by_name.get((None, pname)) if pname else None
        if pname and not parent:
            imp_warn(plan, N_("Parent task not found, imported as a main task"), title)
        t = imp_task(L, (tid or imp_hash(proj, title)), title or tr("(untitled)"),
                     section=None if parent else (imp_line(r.get("section/column"), LIST_NAME_MAX) or None),
                     parent=parent, tags=imp_tags(r.get("tags"), r","), created_at=imp_ts(r.get("created at")),
                     priority=imp_prio_word(r.get("priority")))
        by_name[(proj, title)] = by_name[(None, title)] = t["ext"]
        imp_addnote(t, r.get("notes"))
        if (r.get("completed at") or "").strip():
            t.update(status=2, completed_at=imp_ts(r["completed at"]) or iso(now_utc()))
        d, tm = imp_numdate(r.get("due date"))
        if (r.get("due date") or "").strip() and not d:
            imp_warn(plan, N_("Date not understood, kept in the notes: {0}"), title, imp_line(r["due date"], 60))
            imp_addnote(t, tr("Due: {0}", imp_line(r["due date"], 100)))
        t.update(due=d, due_time=tm)
        sd, _ = imp_numdate(r.get("start date"))
        if sd and d and sd <= d:
            t["start"] = sd
        who, mail = imp_line(r.get("assignee"), 100), imp_line(r.get("assignee email"), 200)
        if who or mail:
            t["assignee"] = {"name": who, "email": mail}
        lines = []
        for k in extra:
            v = imp_line(r.get(k), 500)
            if v:
                lines.append(f"{head.get(k, k)}: {v}")
        if lines:
            imp_addnote(t, "\n".join(lines))


def _imp_hm(v):
    """'9:00:00 AM', '08:00:00', '08:00' -> 'HH:MM' | None."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?", str(v or "").strip())
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    h += 12 if ap == "pm" and h < 12 else 0
    h = 0 if ap == "am" and h == 12 else h
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


# ---- Microsoft To Do (Outlook tasks CSV, CSVs of export tools; ICS goes to parse_ics)
MS_COLS = {
    "title": ("subject", "betreff", "title", "task", "task name", "name", "aufgabe", "titel"),
    "list": ("list", "list name", "listname", "liste", "folder", "ordner"),
    "due": ("due date", "fällig am", "fälligkeitsdatum", "duedatetime", "due", "fällig"),
    "start": ("start date", "beginnt am", "startdatetime", "start", "startdatum"),
    "done": ("date completed", "erledigt am", "completeddatetime", "completed", "completed date"),
    "status": ("status",),
    "pct": ("% complete", "% erledigt"),
    "prio": ("priority", "priorität", "importance", "wichtigkeit"),
    "notes": ("notes", "notizen", "body", "description", "beschreibung", "note"),
    "cats": ("categories", "kategorien", "category", "kategorie"),
    "rem_on": ("reminder on/off", "erinnerung ein/aus", "isreminderon"),
    "rem_date": ("reminder date", "erinnerungsdatum", "reminderdatetime", "reminder"),
    "rem_time": ("reminder time", "erinnerungszeit"),
    "created": ("createddatetime", "created", "created date", "erstellt"),
    "steps": ("steps", "checklistitems", "checklist", "schritte"),
    "flag": ("flagged", "is flagged"),
}


def parse_mstodo(data, fname, opts, plan):
    head = data[:3000].lstrip(b"\xef\xbb\xbf").lstrip()
    if head[:15].upper().startswith(b"BEGIN:VCALENDAR") or b"BEGIN:VCALENDAR" in head.upper()[:200]:
        return parse_ics(data, fname, opts, plan)
    keys, rows, _ = imp_csv(imp_decode(data))
    col = {f: next((k for k in names if k in keys), None) for f, names in MS_COLS.items()}
    if not col["title"]:
        imp_fail(N_("This is not an Outlook / Microsoft To Do CSV (column Subject or Title missing)"))
    german = "betreff" in keys
    s = usettings(db(), me()) if has_request_context() else USER_DEFAULTS
    base_t = s.get("allday_time") or "09:00"
    lists, seen = {}, {}
    g_ = lambda r, f: r.get(col[f]) if col[f] else ""  # noqa: E731
    for r in rows:
        title = imp_line(g_(r, "title"))
        if not title:
            continue
        ln = imp_line(g_(r, "list"), LIST_NAME_MAX) or imp_stem(fname) or "To Do"
        L = lists.get(ln) or lists.setdefault(ln, imp_list(plan, ln))
        d, tm = imp_numdate(g_(r, "due"), dmy=german)
        if tm == "00:00":  # To Do / Outlook store dates as midnight: no time of day
            tm = None
        key = (ln, title, d)
        seen[key] = seen.get(key, 0) + 1
        st = str(g_(r, "status") or "").strip().lower()
        done_d = imp_numdate(g_(r, "done"), dmy=german)[0]
        is_done = st in ("completed", "complete", "erledigt", "abgeschlossen", "done") or \
            str(g_(r, "pct") or "").strip().rstrip("%") in ("100", "100.0") or (bool(done_d) and not st)
        t = imp_task(L, imp_hash(ln, title, d, g_(r, "created"), seen[key]), title, due=d, due_time=tm,
                     priority=imp_prio_word(g_(r, "prio")), tags=imp_tags(g_(r, "cats")), created_at=imp_ts(g_(r, "created")))
        if (g_(r, "due") or "").strip() and not d:
            imp_warn(plan, N_("Date not understood, kept in the notes: {0}"), title, imp_line(g_(r, "due"), 60))
            imp_addnote(t, tr("Due: {0}", imp_line(g_(r, "due"), 100)))
        sd = imp_numdate(g_(r, "start"), dmy=german)[0]
        if sd and d and sd <= d:
            t["start"] = sd
        if is_done:
            t.update(status=2, completed_at=imp_ts(done_d) or iso(now_utc()))
        if str(g_(r, "flag") or "").strip().lower() in ("true", "1", "yes", "wahr", "ja") and not t["priority"]:
            t["priority"] = 3
        imp_addnote(t, g_(r, "notes"))
        steps = str(g_(r, "steps") or "").strip()
        if steps:
            for i, stp in enumerate(x for x in re.split(r"\n|;|\|", steps) if x.strip()):
                done_s = bool(re.match(r"^\s*(\[x\]|✓|✔)", stp, re.I))
                s2 = imp_task(L, t["ext"] + f":s{i}", re.sub(r"^\s*(\[[ xX]?\]|✓|✔|-)\s*", "", stp), parent=t["ext"])
                if done_s:
                    s2.update(status=2, completed_at=t["completed_at"] or iso(now_utc()))
        on = str(g_(r, "rem_on") or "").strip().lower()
        rd = g_(r, "rem_date")
        if rd and on not in ("false", "0", "no", "aus", "falsch", "nein"):
            rdd, rtm = imp_numdate(rd, dmy=german)
            rtm = _imp_hm(g_(r, "rem_time")) or rtm
            if rdd and d and rtm:
                due_dt = datetime.fromisoformat(f"{d}T{tm or base_t}")
                off = int((due_dt - datetime.fromisoformat(f"{rdd}T{rtm}")).total_seconds() // 60)
                if REM_MIN <= off <= REM_MAX:
                    t["reminders"] = [off]
                else:
                    imp_warn(plan, N_("Reminder too far from the due date, not imported"), title)
            elif rdd and not d:
                imp_warn(plan, N_("Reminder without a due date, not imported"), title)


# ---- ICS / VTODO
def parse_ics(data, fname, opts, plan):
    text = imp_decode(data)
    if "BEGIN:VCALENDAR" not in text[:5000].upper():
        imp_fail(N_("This is not an iCalendar file (BEGIN:VCALENDAR missing)"))
    try:
        cals = icalendar.Calendar.from_ical(text, multiple=True)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        imp_fail(N_("The iCalendar file could not be read"))
    s = usettings(db(), me()) if has_request_context() else USER_DEFAULTS
    base_t = s.get("allday_time") or "09:00"
    for n, cal in enumerate(cals):
        name = imp_line(cal.get("X-WR-CALNAME"), LIST_NAME_MAX) or imp_stem(fname) or "Tasks"
        L = next((x for x in plan["lists"] if x["name"] == name), None) or imp_list(plan, name)
        ev = sum(1 for _ in cal.walk("VEVENT"))
        if ev:
            imp_warn(plan, N_("Calendar events are not tasks and were skipped ({0})"), None, ev)
        for td in cal.walk("VTODO"):
            try:
                _ics_todo(td, L, plan, base_t, n)
            except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                imp_warn(plan, N_("A task could not be read and was skipped"), imp_line(td.get("SUMMARY"), 80))


def _ics_val(p):
    return getattr(p, "dt", None) if p is not None else None


def _ics_todo(td, L, plan, base_t, n):
    uid = imp_line(td.get("UID"), 190)
    title = imp_line(td.get("SUMMARY")) or tr("(untitled)")
    if td.get("RECURRENCE-ID") is not None:
        imp_warn(plan, N_("Changed single occurrences of recurring tasks were skipped"), title)
        return
    parent = None
    rel = td.get("RELATED-TO")
    for r in (rel if isinstance(rel, list) else [rel] if rel is not None else []):
        if str(r.params.get("RELTYPE", "PARENT")).upper() == "PARENT" and str(r).strip():
            parent = imp_line(r, 190)
    cats = td.get("CATEGORIES")
    tags = []
    for cv in (cats if isinstance(cats, list) else [cats] if cats is not None else []):
        tags += [imp_line(x, 100) for x in getattr(cv, "cats", []) if imp_line(x, 100)]
    pr = td.get("PRIORITY")
    try:
        pr = int(pr) if pr is not None else 0
    except (TypeError, ValueError):
        pr = 0
    t = imp_task(L, (uid or imp_hash(L["name"], title, n, len(L["tasks"]))), title, tags=list(dict.fromkeys(tags)),
                 parent=parent, priority=5 if 1 <= pr <= 4 else 3 if pr == 5 else 1 if 6 <= pr <= 9 else 0,
                 created_at=imp_ts(_ics_val(td.get("CREATED"))))
    imp_addnote(t, td.get("DESCRIPTION"))
    u = str(td.get("URL") or "").strip()
    if u and valid_url(u):
        t["url"] = u
    due, start = _ics_val(td.get("DUE")), _ics_val(td.get("DTSTART"))
    t["due"], t["due_time"] = imp_local(due)
    if start is not None:
        sd, stm = imp_local(start)
        if t["due"] and sd and sd <= t["due"]:
            t["start"] = sd
        elif not t["due"] and sd:
            imp_addnote(t, tr("Start: {0}", sd + (" " + stm if stm else "")))
    st = str(td.get("STATUS") or "").upper()
    comp = _ics_val(td.get("COMPLETED"))
    if st == "CANCELLED":
        t.update(status=-1, completed_at=imp_ts(comp) or iso(now_utc()))
    elif st == "COMPLETED" or comp is not None:
        t.update(status=2, completed_at=imp_ts(comp) or iso(now_utc()))
    rr = td.get("RRULE")
    if rr is not None:
        rule = rr_norm((rr[0] if isinstance(rr, list) else rr).to_ical().decode("utf-8", "replace"))
        if rule and not rr_problem(rule) and (not t["due"] or rr_feasible(rule, t["due"])):
            t["repeat"] = rule
        elif rule:
            imp_warn(plan, N_("Repetition not supported (only daily, weekly, monthly or yearly), kept in the notes"), title)
            imp_addnote(t, tr("Repeats: {0}", imp_line(rule, 300)))
    rems = []
    for al in td.walk("VALARM"):
        trig = al.get("TRIGGER")
        v = _ics_val(trig)
        if not t["due"]:
            imp_warn(plan, N_("Reminder without a due date, not imported"), title)
            break
        due_dt = datetime.fromisoformat(f"{t['due']}T{t['due_time'] or base_t}").replace(tzinfo=TZ)
        if isinstance(v, timedelta):
            ref = due_dt
            if str(trig.params.get("RELATED", "START")).upper() == "START" and start is not None:
                sd, stm = imp_local(start)
                ref = datetime.fromisoformat(f"{sd}T{stm or base_t}").replace(tzinfo=TZ)
            at = ref + v
        elif isinstance(v, datetime):
            at = v if v.tzinfo else v.replace(tzinfo=TZ)
        else:
            continue
        off = int((due_dt - at).total_seconds() // 60)
        if REM_MIN <= off <= REM_MAX:
            rems.append(off)
        else:
            imp_warn(plan, N_("Reminder too far from the due date, not imported"), title)
    if rems:
        rems = list(dict.fromkeys(rems))
        if len(rems) > REM_COUNT:
            imp_warn(plan, N_("More than {0} reminders, the rest was dropped"), title, REM_COUNT)
        t["reminders"] = rems[:REM_COUNT]


# ---- 2.142.0 B (#2147): Notion, Google Tasks, ClickUp, Jira, any CSV, Markdown checklists. File imports only: nothing in a
# file is fetched (links stay text), people are never matched to accounts (their names go into the notes as text).
def imp_csv_multi(text):
    """Like imp_csv, but a header that repeats (Jira: Labels, Sprint, Components) keeps every value: rows = {key: [values]}."""
    first = text.split("\n", 1)[0]
    delim = max((",", ";", "\t"), key=first.count)
    try:
        rd = csv.reader(io.StringIO(text), delimiter=delim)
        head = next(rd, None)
        if not head:
            imp_fail(N_("The file is empty"))
        keys = [imp_line(h, 100).lower() for h in head]
        rows = []
        for r in rd:
            if not any(x.strip() for x in r):
                continue
            row = {}
            for i, k in enumerate(keys):
                if k and i < len(r) and r[i].strip():
                    row.setdefault(k, []).append(r[i])
            rows.append(row)
            if len(rows) > IMPORT_MAX_TASKS * 3:
                imp_fail(N_("Too many rows (more than {0} tasks)"), IMPORT_MAX_TASKS)
    except csv.Error:
        imp_fail(N_("The CSV file could not be read"))
    return keys, rows


def imp_anydate(s, dmy=None):
    """imp_numdate + dates with month names: 'January 15, 2025', 'Wednesday, January 15th 2025', '15 Jan 2025',
    '15. Januar 2025', '15/Jan/25 10:00 AM' (Jira), optionally a time (10:00 [AM|PM]) and a time zone after it. -> (date, time | None)."""
    s = str(s or "").strip()
    d, t = imp_numdate(s, dmy)
    if d:
        return d, t
    x = re.sub(r"\([^)]*\)", " ", s.lower())
    x = re.sub(r"[\s,]+", " ", x).strip()
    tm = None
    m = re.search(r"(?:^|\s)(?:at\s|um\s)?(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?)(?:\s+\S+)?$", x)
    if m:
        tm = _imp_hm(m.group(1))
        x = x[:m.start()].strip()
    x = re.sub(rf"^(?:{_WD_RE})\.?\s+", "", x)
    m = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th|\.)?[\s/.-]*({_MON_RE})\.?[\s/.-]*(\d{{2}}|\d{{4}})", x) or \
        re.fullmatch(rf"({_MON_RE})\.?[\s/.-]*(\d{{1,2}})(?:st|nd|rd|th|\.)?[\s/.-]+(\d{{4}})", x)
    if not m:
        return None, None
    a, b, y = m.groups()
    day, mon = (int(a), IMP_MONTHS[b]) if a.isdigit() else (int(b), IMP_MONTHS[a])
    y = int(y) + (2000 if len(y) == 2 else 0)
    try:
        dd = date(y, mon, day).isoformat()
    except ValueError:
        return None, None
    return (dd, tm) if valid_date(dd) else (None, None)


def _imp_epoch(v):
    """A Unix time in seconds or milliseconds (ClickUp) -> (date, time | None in local time; midnight = no time)."""
    v = str(v or "").strip()
    if not re.fullmatch(r"\d{9,13}", v):
        return None, None
    n = int(v) / (1000 if len(v) > 11 else 1)
    with contextlib.suppress(ValueError, OverflowError, OSError):
        d, t = imp_local(datetime.fromtimestamp(n, timezone.utc))
        return (d, None if t == "00:00" else t) if valid_date(d) else (None, None)
    return None, None


IMP_DONE = {"done", "complete", "completed", "closed", "resolved", "finished", "erledigt", "fertig", "abgeschlossen", "geschlossen",
            "x", "yes", "y", "true", "ja", "wahr", "1", "✓", "✔", "✅", "checked", "gelöst"}
IMP_CANCEL = {"cancelled", "canceled", "won't do", "wont do", "won't fix", "abgebrochen", "verworfen", "abgesagt", "declined", "rejected",
              "duplicate", "storniert"}


def imp_done(v):
    """A status / checkbox value -> 2 (done), -1 (cancelled, won't do) or 0."""
    v = re.sub(r"\s+", " ", str(v or "").strip().lower())
    return 2 if v in IMP_DONE else -1 if v in IMP_CANCEL else 0


def imp_prio_any(v):
    """Priority words of Jira / ClickUp / other apps -> 0, 1, 3, 5 (None = not understood). The two top levels are high."""
    v = re.sub(r"\s+", " ", str(v or "").strip().lower())
    if not v or v in ("none", "keine", "-", "no priority", "ohne"):
        return 0
    for words, p in ((("highest", "blocker", "critical", "urgent", "dringend", "kritisch", "high", "hoch", "höchste", "wichtig",
                       "important", "p1", "!!!"), 5),
                     (("medium", "mittel", "normal", "major", "p2", "!!"), 3),
                     (("low", "lowest", "niedrig", "gering", "minor", "trivial", "p3", "p4", "!"), 1)):
        if v in words:
            return p
    return None


def imp_who(t, src, v):
    """People of a file never become accounts: their names go into the notes as text."""
    v = imp_line(re.sub(r"^\[|\]$", "", str(v or "").strip()), 300)
    if v:
        imp_addnote(t, tr("Assignee ({0}): {1}", IMPORT_SOURCES[src], v))


IMP_OPEN = {"", "no", "n", "nein", "false", "falsch", "0", "open", "offen", "todo", "to do", "to-do", "not started", "nicht begonnen",
            "new", "neu"}


def _imp_status_note(t, st, v, label):
    """A status that is neither done nor plainly open ("In progress", "Waiting") goes into the notes."""
    v = imp_line(v, 100)
    if not st and v.lower() not in IMP_OPEN:
        imp_addnote(t, f"{label}: {v}")


def _imp_strip_br(v):
    return re.sub(r"^\[|\]$", "", str(v or "").strip())


# the column names any CSV can carry (lower case); the first match per field wins, the rest goes into the notes
IMP_COLS = {
    "title": ("title", "name", "task", "task name", "taskname", "summary", "subject", "aufgabe", "titel", "betreff", "todo", "to-do",
              "item", "aufgabenname", "bezeichnung"),
    "id": ("id", "task id", "key", "issue key", "uid", "nummer", "nr"),
    "parent": ("parent", "parent id", "parent task", "parent task id", "übergeordnet", "übergeordnete aufgabe", "eltern"),
    "list": ("list", "list name", "project", "project name", "liste", "projekt", "board", "folder", "ordner"),
    "section": ("section", "section/column", "column", "group", "abschnitt", "spalte", "gruppe", "bereich", "phase"),
    "due": ("due", "due date", "duedate", "due_date", "date", "deadline", "fällig", "fällig am", "fälligkeit", "fälligkeitsdatum",
            "datum", "termin", "frist", "bis", "end date", "enddatum"),
    "due_time": ("due time", "time", "uhrzeit", "zeit"),
    "start": ("start", "start date", "start_date", "startdatum", "beginn", "begin", "von"),
    "notes": ("notes", "note", "description", "beschreibung", "notiz", "notizen", "details", "body", "content", "inhalt", "text",
              "kommentar", "comment", "comments"),
    "priority": ("priority", "priorität", "prio", "importance", "wichtigkeit", "dringlichkeit"),
    "tags": ("tags", "tag", "labels", "label", "schlagwörter", "schlagworte", "stichwörter", "categories", "category", "kategorien",
             "kategorie", "keywords"),
    "done": ("done", "completed", "complete", "erledigt", "is done", "is completed", "checked", "status", "state", "zustand",
             "fertig", "check"),
    "done_at": ("completed at", "completed date", "date completed", "completion date", "done at", "erledigt am", "abgeschlossen am"),
    "created": ("created", "created time", "created at", "created date", "date created", "erstellt", "erstellt am", "angelegt"),
    "assignee": ("assignee", "assignees", "assigned to", "zuständig", "verantwortlich", "owner", "responsible", "person", "bearbeiter"),
    "url": ("url", "link", "website", "webseite"),
}


def imp_colmap(keys, title_fallback=True):
    """CSV header (lower case) -> {field: column}; the title falls back to the first column."""
    col = {}
    for f, names in IMP_COLS.items():
        col[f] = next((k for k in names if k in keys and k not in col.values()), None)
    if not col["title"] and title_fallback:  # the first column that is no other field (a column read as notes is taken back)
        taken = {v for f, v in col.items() if v and f != "notes"}
        col["title"] = next((k for k in keys if k and k not in taken), None)
        if col["title"] and col["title"] == col["notes"]:
            col["notes"] = None
    return col


def _imp_dmy(values):
    """Slash dates of a column: day first (True), month first (False) or not to tell (None)."""
    for v in values:
        m = re.match(r"\s*(\d{1,2})/(\d{1,2})/\d{2,4}", str(v or ""))
        if m:
            if int(m.group(1)) > 12:
                return True
            if int(m.group(2)) > 12:
                return False
    return None


def _imp_extra(t, row, keys, head, skip):
    lines = [f"{head.get(k, k)}: {imp_line(row.get(k), 500)}" for k in keys if k and k not in skip and imp_line(row.get(k), 500)]
    if lines:
        imp_addnote(t, "\n".join(lines))


# ---- any CSV
IMP_FIELD_NAMES = ("title", "id", "parent", "list", "section", "due", "due_time", "start", "notes", "priority", "tags", "done",
                   "done_at", "created", "assignee", "url")


def parse_csv(data, fname, opts, plan):
    keys, rows, head = imp_csv(imp_decode(data))
    col = imp_colmap(keys)
    if not col["title"]:
        imp_fail(N_("No column with a task title found"))
    g_ = lambda r, f: (r.get(col[f]) or "") if col[f] else ""  # noqa: E731
    used = {v: f for f, v in col.items() if v}
    plan["columns"] = [{"column": head.get(k, k), "field": used.get(k, "notes")} for k in keys if k]
    dmy = _imp_dmy([g_(r, "due") for r in rows] + [g_(r, "start") for r in rows])
    if dmy is None and any(re.match(r"\s*\d{1,2}/\d{1,2}/", g_(r, "due") + " " + g_(r, "start")) for r in rows):
        imp_warn(plan, N_("Dates like 01/02/2025 were read as month/day/year"), None)
    lists, seen, by_id, by_title, rows_t = {}, {}, {}, {}, []
    for r in rows:
        title = imp_line(g_(r, "title"))
        if not title:
            continue
        ln = imp_line(g_(r, "list"), LIST_NAME_MAX) or imp_stem(fname) or "CSV"
        L = lists.get(ln) or lists.setdefault(ln, imp_list(plan, ln))
        rid = imp_line(g_(r, "id"), 100)
        d, tm = imp_anydate(g_(r, "due"), dmy)
        key = (ln, title, d)
        seen[key] = seen.get(key, 0) + 1
        t = imp_task(L, ("id:" + rid) if rid else imp_hash(ln, title, d, seen[key]), title, due=d,
                     due_time=_imp_hm(g_(r, "due_time")) or tm, section=imp_line(g_(r, "section"), LIST_NAME_MAX) or None,
                     tags=imp_tags(_imp_strip_br(g_(r, "tags"))), created_at=imp_ts(g_(r, "created")) if g_(r, "created") else None)
        if g_(r, "due").strip() and not d:
            imp_warn(plan, N_("Date not understood, kept in the notes: {0}"), title, imp_line(g_(r, "due"), 60))
            imp_addnote(t, tr("Due: {0}", imp_line(g_(r, "due"), 100)))
        sd = imp_anydate(g_(r, "start"), dmy)[0]
        if sd and d and sd <= d:
            t["start"] = sd
        pr = imp_prio_any(g_(r, "priority"))
        if pr is None:
            imp_warn(plan, N_("Priority not understood, kept in the notes"), title)
            imp_addnote(t, tr("Priority: {0}", imp_line(g_(r, "priority"), 100)))
        t["priority"] = pr or 0
        st = imp_done(g_(r, "done"))
        _imp_status_note(t, st, g_(r, "done"), head.get(col["done"], col["done"]))
        da = g_(r, "done_at").strip()
        if st or (da and not col["done"]):
            t.update(status=st or 2, completed_at=(imp_ts(da) if da else None) or iso(now_utc()))
        url = imp_line(g_(r, "url"), 2000)
        if url:
            t["url"] = url
        imp_addnote(t, g_(r, "notes"))
        imp_who(t, "csv", g_(r, "assignee"))
        _imp_extra(t, r, keys, head, set(used))
        if rid:
            by_id[rid] = t["ext"]
        by_title.setdefault((ln, title), t["ext"])
        rows_t.append((t, ln, imp_line(g_(r, "parent"), 300)))
    for t, ln, p in rows_t:
        if p:
            t["parent"] = by_id.get(p) or by_title.get((ln, p))
            if not t["parent"]:
                imp_warn(plan, N_("Parent task not found, imported as a main task"), t["title"])


# ---- Markdown checklists
_MD_HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_BOX = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+\[([ xX/\-])\]\s+(.*)$")
_MD_ANYBOX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\[[ xX/\-]\]\s", re.M)
_MD_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
_MD_DATE = re.compile(r"(?:(📅|⏳|🛫|✅|due:?|fällig:?|start:?|@due\(|@start\()\s*)?(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})"
                      r"(?:[ T](\d{1,2}:\d{2}))?\)?", re.I)
_MD_TAG = re.compile(r"(?:^|\s)#([^\W\d_][\w/-]{0,99})", re.U)


def _md_title(text):
    """Title of a Markdown task -> (title, {due, due_time, start, done_at, priority, tags}). Only clear dates (2025-01-15,
    15.01.2025, with a due / start marker or the Obsidian Tasks symbols); priorities ⏫ 🔼 🔽, #tags."""
    out = {"due": None, "due_time": None, "start": None, "done_at": None, "priority": 0, "tags": []}

    def dt(m):
        mark = (m.group(1) or "").lower().rstrip(":(")
        d = m.group(2)
        if "." in d:
            d = imp_numdate(d)[0]
        if not d or not valid_date(d):
            return m.group(0)
        if mark in ("🛫", "⏳", "start", "@start"):
            out["start"] = out["start"] or d
        elif mark == "✅":
            out["done_at"] = d
        elif not out["due"]:
            tm = (m.group(3) or "").zfill(5)
            out["due"], out["due_time"] = d, tm if m.group(3) and valid_hm(tm) else None
        return " "
    text = _MD_DATE.sub(dt, text)
    for sym, p in (("⏫", 5), ("🔺", 5), ("🔼", 3), ("🔽", 1), ("⏬", 1)):
        if sym in text:
            out["priority"] = out["priority"] or p
            text = text.replace(sym, " ")
    out["tags"] = list(dict.fromkeys(imp_line(m.group(1), 100) for m in _MD_TAG.finditer(text)))[:50]
    text = _MD_TAG.sub(" ", text)
    return imp_line(text), out


def _md_parse(text, plan, name, ext0, heads_as_lists=True, src="markdown"):
    """Markdown -> tasks: the top heading level = lists (heads_as_lists), deeper headings = sections; - [ ] / - [x] / * [ ] / 1. [ ]
    = tasks (plain bullets only in a file without any checkbox), indentation = subtask, text below a task = its notes.
    -> the number of tasks."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[0].strip() == "---":  # front matter
        end = next((i for i, x in enumerate(lines[1:60], 1) if x.strip() in ("---", "...")), None)
        if end:
            lines = lines[end + 1:]
    fence, heads, boxes = False, [], False
    for x in lines:
        if x.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence:
            h = _MD_HEAD.match(x)
            if h:
                heads.append(len(h.group(1)))
            elif _MD_BOX.match(x):
                boxes = True
    top = min(heads) if heads and heads_as_lists else None
    state = {"list": None, "name": name}
    section, stack, last, seen, n, fence = None, [], None, {}, 0, False

    def cur():
        if state["list"] is None:
            state["list"] = imp_list(plan, state["name"] or name)
        return state["list"]
    for x in lines:
        if x.lstrip().startswith(("```", "~~~")):
            fence = not fence
            if last is not None:
                last["_md"].append(x.strip())
            continue
        h = None if fence else _MD_HEAD.match(x)
        if h:
            txt = imp_line(re.sub(r"[*_`]", "", h.group(2)), LIST_NAME_MAX)
            if top and len(h.group(1)) == top:
                state.update(list=None, name=txt or name)
                section = None
            else:
                section = txt or None
            stack, last = [], None
            continue
        m = None if fence else (_MD_BOX.match(x) or (None if boxes else _MD_ITEM.match(x)))
        if m:
            ind = len(m.group(1).expandtabs(4))
            mark = m.group(2) if boxes else " "
            body = m.group(3) if boxes else m.group(2)
            while stack and stack[-1][0] >= ind:
                stack.pop()
            parent = stack[-1][1] if stack else None
            title, ex = _md_title(body)
            L = cur()
            chain = "/".join(p[1]["title"] for p in stack)
            k = (L["name"], section, chain, title)
            seen[k] = seen.get(k, 0) + 1
            t = imp_task(L, imp_hash(ext0, L["name"], section, chain, title, seen[k]), title or tr("(untitled)"), section=section,
                         parent=parent["ext"] if parent else None, due=ex["due"], due_time=ex["due_time"], start=ex["start"],
                         priority=ex["priority"], tags=ex["tags"])
            t["_md"] = []
            if mark in "xX":
                t.update(status=2, completed_at=imp_ts(ex["done_at"]) or iso(now_utc()))
            elif mark == "-":
                t.update(status=-1, completed_at=iso(now_utc()))
            stack.append((ind, t))
            last, n = t, n + 1
            continue
        if last is not None and (x.strip() or last["_md"]):
            base = (stack[-1][0] if stack else 0) + 2
            last["_md"].append(x[base:] if x[:base].strip() == "" else x.strip())
    for L in plan["lists"]:
        for t in L["tasks"]:
            if "_md" in t:
                imp_addnote(t, "\n".join(t.pop("_md")))
    return n


def parse_markdown(data, fname, opts, plan):
    text = imp_decode(data)
    if not _md_parse(text, plan, imp_stem(fname) or "Markdown", "md"):
        imp_fail(N_("No tasks found in the file"))


# ---- Notion (export "Markdown & CSV": a ZIP, often with ZIPs inside, page and database names carry an id at the end)
_NOTION_ID = re.compile(r"\s+[0-9a-f]{32}$|\s+[0-9a-f]{8}(?:-?[0-9a-f]{4}){3}-?[0-9a-f]{12}$", re.I)
IMPORT_NEST_ZIPS = 20  # ZIPs inside a ZIP (Notion splits big exports into parts), one level deep


def _notion_name(path):
    base = str(path or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    base = re.sub(r"\.(csv|md|markdown|zip)$", "", base, flags=re.I)
    base = re.sub(r"_all$", "", base)
    return imp_line(_NOTION_ID.sub("", base), LIST_NAME_MAX)


def _notion_files(data):
    """(path, bytes) of every CSV / Markdown file of a Notion export ZIP, also inside ZIPs in it (one level, IMPORT_NEST_ZIPS,
    one budget for everything)."""
    out, budget, nested = [], IMPORT_MAX_MB * 1048576 * 3, 0
    for path, b in imp_zip(data, (".csv", ".md", ".markdown", ".zip"), full=True):
        if path.lower().endswith(".zip"):
            nested += 1
            if nested > IMPORT_NEST_ZIPS:
                imp_fail(N_("The ZIP file contains too many files"))
            for p2, b2 in imp_zip(b, (".csv", ".md", ".markdown", ".zip"), full=True):
                if p2.lower().endswith(".zip"):
                    imp_fail(N_("The ZIP file is nested too deeply"))
                budget -= len(b2)
                out.append((path[:-4] + "/" + p2, b2))
        else:
            budget -= len(b)
            out.append((path, b))
        if budget < 0:
            imp_fail(N_("The ZIP file unpacks to too much data"))
    return out


def _notion_date(v):
    """'January 15, 2025', 'January 15, 2025 10:00 AM (GMT+1)', '2025-01-15', ranges 'A → B' -> (start, due, time)."""
    parts = [x.strip() for x in re.split(r"\s+(?:→|->)\s+", str(v or "").strip()) if x.strip()]
    if not parts:
        return None, None, None
    d1, t1 = imp_anydate(parts[0])
    if len(parts) > 1:
        d2, t2 = imp_anydate(parts[1])
        if d1 and d2 and d1 <= d2:
            return d1, d2, t2
    return None, d1, t1


def _notion_db(text, path, plan, opts):
    keys, rows, head = imp_csv(text)
    if not keys or not rows:
        return {}
    col = imp_colmap(keys)
    # Notion: the title is the first column; a checkbox column may be named anything ("Done", "Erledigt", "Checkbox")
    col["title"] = next((k for k in ("name", "title", "task", "task name", "aufgabe", "titel") if k in keys), keys[0])
    if col["done"] == col["title"]:
        col["done"] = None
    if not col["done"]:
        col["done"] = next((k for k in keys if k not in col.values() and rows and
                            all(str(r.get(k) or "").strip().lower() in ("yes", "no", "ja", "nein", "") for r in rows)
                            and any(str(r.get(k) or "").strip() for r in rows)), None)
    g_ = lambda r, f: (r.get(col[f]) or "") if col[f] else ""  # noqa: E731
    name = _notion_name(path) or "Notion"
    L = imp_list(plan, name)
    used = {v for v in col.values() if v} | {"last edited time", "last edited by", "created by"}
    seen, idx = {}, {}
    for r in rows:
        title = imp_line(g_(r, "title"))
        if not title:
            continue
        seen[title] = seen.get(title, 0) + 1
        sd, d, tm = _notion_date(g_(r, "due"))
        t = imp_task(L, imp_hash("notion", name, title, seen[title]), title, due=d, due_time=None if tm == "00:00" else tm, start=sd,
                     tags=imp_tags(g_(r, "tags"), r","), section=imp_line(g_(r, "section"), LIST_NAME_MAX) or None,
                     created_at=imp_ts(imp_anydate(g_(r, "created"))[0]) if g_(r, "created") else None)
        if g_(r, "due").strip() and not d:
            imp_warn(plan, N_("Date not understood, kept in the notes: {0}"), title, imp_line(g_(r, "due"), 60))
            imp_addnote(t, tr("Due: {0}", imp_line(g_(r, "due"), 100)))
        pr = imp_prio_any(g_(r, "priority"))
        t["priority"] = pr or 0
        if pr is None:
            used.discard(col["priority"])  # not understood: the column goes into the notes
        st = imp_done(g_(r, "done"))
        _imp_status_note(t, st, g_(r, "done"), head.get(col["done"], col["done"]))
        if st:
            t.update(status=st, completed_at=iso(now_utc()))
        url = imp_line(g_(r, "url"), 2000)
        if url and valid_url(url):
            t["url"] = url
        imp_addnote(t, g_(r, "notes"))
        imp_who(t, "notion", g_(r, "assignee"))
        _imp_extra(t, r, keys, head, used)
        used.add(col["priority"])
        idx.setdefault(title.lower(), t)
    return {"list": L, "rows": idx}


def _notion_page_body(text):
    """A database row's own page: drop the title heading and the property lines below it."""
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines) and re.match(r"^[^\s:#\-*][^:]{0,80}:\s", lines[i]):
        i += 1
    return "\n".join(lines[i:]).strip()


def parse_notion(data, fname, opts, plan):
    if data[:4] == b"PK\x03\x04":
        files = _notion_files(data)
    else:
        files = [(fname or "Notion.md", data)]
    csvs = [(p, b) for p, b in files if p.lower().endswith(".csv")]
    have_all = {p[:-8].lower() for p, _ in csvs if p.lower().endswith("_all.csv")}
    dbs, n = {}, 0
    for p, b in csvs:  # newer exports carry "<db>.csv" (the view) next to "<db>_all.csv" (every row): the full one wins
        if not p.lower().endswith("_all.csv") and p[:-4].lower() in have_all:
            continue
        r = _notion_db(imp_decode(b), p, plan, opts)
        if r:
            dbs.setdefault(_notion_name(p).lower(), []).append(r)
            n += len(r["list"]["tasks"])
    skipped = 0
    for p, b in sorted((x for x in files if not x[0].lower().endswith(".csv")), key=lambda x: x[0].count("/")):
        text = imp_decode(b)
        segs = p.split("/")
        owner = _notion_name(segs[-2]).lower() if len(segs) > 1 else ""
        row = None
        for db_ in dbs.get(owner, []):
            row = db_["rows"].get(_notion_name(p).lower())
            if row:
                L = db_["list"]
                break
        if row:  # the page of a database row: its text into the task's notes, its checkboxes become subtasks
            body = _notion_page_body(text)
            sub = imp_plan("notion")
            if _md_parse(body, sub, row["title"], "notion:" + row["ext"], heads_as_lists=False):
                for t in sub["lists"][0]["tasks"]:
                    t["section"] = row["section"]
                    t["parent"] = t["parent"] or row["ext"]
                    L["tasks"].append(t)
                    n += 1
                body = "\n".join(x for x in body.split("\n") if not _MD_BOX.match(x))
            imp_addnote(row, body)
            continue
        if not _MD_ANYBOX.search(text):
            skipped += 1
            continue
        text = re.sub(r"\A\s*# [^\n]*\n", "", text)  # the page title (the list is named after the page)
        got = _md_parse(text, plan, _notion_name(p) or "Notion", "notion:" + p, heads_as_lists=False)
        if not got:
            skipped += 1
        n += got
    if not n:
        imp_fail(N_("No Notion database (CSV) or checklist found in the file"))
    if skipped:
        imp_warn(plan, N_("Pages without a checklist were skipped"), None)
        plan["warn"][(N_("Pages without a checklist were skipped"),)]["n"] = skipped


# ---- Google Tasks (Takeout: a ZIP with Tasks/Tasks.json, or the JSON itself)
def parse_gtasks(data, fname, opts, plan):
    if data[:4] == b"PK\x03\x04":
        members = imp_zip(data, (".json",), full=True)
        pick = [b for p, b in members if p.lower().rsplit("/", 1)[-1] == "tasks.json"] or [b for _, b in members]
        if not pick:
            imp_fail(N_("No Tasks.json found in the ZIP file"))
        js = [imp_json(imp_decode(b)) for b in pick[:5]]
    else:
        js = [imp_json(imp_decode(data))]
    ok = False
    for j in js:
        if not isinstance(j, dict) or not isinstance(j.get("items"), list):
            continue
        items = [x for x in j["items"] if isinstance(x, dict)]
        if j.get("kind") == "tasks#taskLists" or any(isinstance(x.get("items"), list) or x.get("kind") == "tasks#taskList" for x in items):
            for tl in items:
                _gtasks_list(tl.get("title") or "Google Tasks", [x for x in tl.get("items") or [] if isinstance(x, dict)], plan)
            ok = True
        elif j.get("kind") == "tasks#tasks" or any(x.get("kind") == "tasks#task" for x in items):
            _gtasks_list(imp_stem(fname) or "Google Tasks", items, plan)
            ok = True
    if not ok:
        imp_fail(N_("This is not a Google Tasks export (Tasks.json from Google Takeout expected)"))


def _gtasks_list(name, items, plan):
    L = imp_list(plan, name)
    items = [x for x in items if not x.get("deleted")]
    items.sort(key=lambda x: (str(x.get("parent") or ""), str(x.get("position") or "")))
    for it in items:
        tid = str(it.get("id") or "") or imp_hash(name, it.get("title"), it.get("updated"))
        t = imp_task(L, tid, it.get("title") or tr("(untitled)"), parent=str(it["parent"]) if it.get("parent") else None,
                     created_at=imp_ts(it.get("created")) if it.get("created") else None)
        due = str(it.get("due") or "")[:10]  # Google keeps the day only (midnight UTC): never shifted by a time zone
        if valid_date(due):
            t["due"] = due
        imp_addnote(t, it.get("notes"))
        if it.get("status") == "completed":
            t.update(status=2, completed_at=imp_ts(it.get("completed")) or iso(now_utc()))
        links = [x for x in it.get("links") or [] if isinstance(x, dict) and x.get("link")]
        if links:
            imp_addnote(t, tr("Links (not opened):") + "\n" + "\n".join(
                f"- {imp_line(x.get('description') or x.get('type') or 'link', 200)}: {imp_line(x.get('link'), 2000)}" for x in links))


# ---- ClickUp (CSV export of a list / space)
CU_STD = {"task id", "task custom id", "task name", "task content", "status", "date created", "date created text", "due date",
          "due date text", "start date", "start date text", "parent id", "attachments", "assignees", "tags", "priority", "list name",
          "folder name", "space name", "time estimated", "time estimated text", "checklists", "comments", "assigned comments",
          "time spent", "time spent text", "rolled up time", "rolled up time text", "date updated", "date updated text",
          "date closed", "date closed text", "date done", "date done text", "lists", "latest comment", "task url", "points",
          "watchers", "creator", "sprint points", "dependencies", "linked tasks"}


def _cu_date(v, text):
    d, t = _imp_epoch(v)
    if not d:
        d, t = imp_anydate(v)
    if not d and text:
        d, t = imp_anydate(re.sub(r"\s+(?:gmt|utc)[+-]?\d*$", "", str(text).strip(), flags=re.I))
    return d, (None if t == "00:00" else t)


def _cu_checklists(v):
    """ClickUp checklists as JSON ({name: [items]} or [{name, items}]) -> [(name, [(text, done)])]; None = not JSON."""
    try:
        j = json.loads(v) if len(v) < 200000 else None
    except (ValueError, RecursionError):  # 2.142.0 review: a deeply nested cell is no 500
        return None
    if isinstance(j, dict):
        j = [{"name": k, "items": x} for k, x in j.items()]
    if not isinstance(j, list):
        return None
    out = []
    for cl in j[:50]:
        if not isinstance(cl, dict):
            continue
        its = []
        for it in (cl.get("items") or [])[:500]:
            if isinstance(it, str):
                its.append((it, False))
            elif isinstance(it, dict):
                its.append((str(it.get("name") or it.get("text") or ""), bool(it.get("resolved") or it.get("checked") or it.get("done"))))
        out.append((str(cl.get("name") or ""), [x for x in its if x[0].strip()]))
    return out


def parse_clickup(data, fname, opts, plan):
    keys, rows, head = imp_csv(imp_decode(data))
    if "task name" not in keys:
        imp_fail(N_("This is not a ClickUp CSV export (column Task Name missing)"))
    lists, seen = {}, {}
    for r in rows:
        title = imp_line(r.get("task name"))
        if not title:
            continue
        ln = imp_line(r.get("list name"), LIST_NAME_MAX) or imp_stem(fname) or "ClickUp"
        fo = imp_line(r.get("folder name"), FOLDER_MAX)
        fo = "" if fo.lower() in ("hidden", "-", "none") else fo
        fo = fo or imp_line(r.get("space name"), FOLDER_MAX)
        L = lists.get((fo, ln)) or lists.setdefault((fo, ln), imp_list(plan, ln, folder=fo))
        tid = imp_line(r.get("task id"), 100)
        seen[(ln, title)] = seen.get((ln, title), 0) + 1
        d, tm = _cu_date(r.get("due date"), r.get("due date text"))
        t = imp_task(L, tid or imp_hash(ln, title, seen[(ln, title)]), title, due=d, due_time=tm,
                     parent=imp_line(r.get("parent id"), 100) or None, tags=imp_tags(_imp_strip_br(r.get("tags")), r","),
                     created_at=imp_ts(_imp_epoch(r.get("date created"))[0]) if _imp_epoch(r.get("date created"))[0] else None)
        if (r.get("due date") or "").strip() and not d:
            imp_warn(plan, N_("Date not understood, kept in the notes: {0}"), title, imp_line(r.get("due date text") or r["due date"], 60))
            imp_addnote(t, tr("Due: {0}", imp_line(r.get("due date text") or r["due date"], 100)))
        sd = _cu_date(r.get("start date"), r.get("start date text"))[0]
        if sd and d and sd <= d:
            t["start"] = sd
        pv = (r.get("priority") or "").strip().lower()
        t["priority"] = {"1": 5, "2": 5, "3": 3, "4": 1}.get(pv, imp_prio_any(pv) or 0)
        st = imp_done(r.get("status"))
        if st:
            done_at = _imp_epoch(r.get("date closed") or r.get("date done"))[0]
            t.update(status=st, completed_at=imp_ts(done_at) if done_at else iso(now_utc()))
        est = (r.get("time estimated") or "").strip()
        if est.isdigit() and int(est) >= 60000:
            t["duration"] = min(int(est) // 60000, DURATION_MAX)
        imp_addnote(t, r.get("task content"))
        if not st and imp_line(r.get("status"), 100).lower() not in IMP_OPEN:
            imp_addnote(t, tr("Status ({0}): {1}", "ClickUp", imp_line(r.get("status"), 100)))
        imp_who(t, "clickup", r.get("assignees"))
        att = _imp_strip_br(r.get("attachments")).strip()
        if att:
            imp_addnote(t, tr("Attachments (links, not downloaded):") + "\n" + imp_textblock(att, 4000))
        cm = imp_textblock(_imp_strip_br(r.get("comments")), 20000)
        if cm:
            imp_addnote(t, tr("Comments ({0}):", "ClickUp") + "\n" + cm)
        lines = [f"{head.get(k, k)}: {imp_line(r.get(k), 500)}" for k in keys if k and k not in CU_STD and imp_line(r.get(k), 500)]
        if lines:
            imp_addnote(t, "\n".join(lines))
        clv = (r.get("checklists") or "").strip()
        if clv and clv not in ("[]", "{}"):
            cls = _cu_checklists(clv)
            if cls is None:
                imp_addnote(t, tr("Checklists ({0}):", "ClickUp") + "\n" + imp_textblock(clv, 4000))
                continue
            for i, (cn, its) in enumerate(cls):
                par = t
                if len(cls) > 1:
                    par = imp_task(L, f"{t['ext']}:cl{i}", cn or tr("Checklist"), parent=t["ext"])
                for k2, (txt, dn) in enumerate(its):
                    s = imp_task(L, f"{par['ext']}:ci{k2}", txt, parent=par["ext"])
                    if dn:
                        s.update(status=2, completed_at=t["completed_at"] or iso(now_utc()))
    known = {t["ext"] for L in plan["lists"] for t in L["tasks"]}
    for L in plan["lists"]:
        for t in L["tasks"]:
            if t["parent"] and t["parent"] not in known:
                imp_warn(plan, N_("Parent task not found, imported as a main task"), t["title"])
                t["parent"] = None


# ---- Jira (CSV export of an issue search: "Export > CSV (all fields / current fields)")
JIRA_NOTE_COLS = (("sprint", N_("Sprint")), ("components", N_("Components")),
                  ("fix version/s", N_("Fix version")), ("affects version/s", N_("Affects version")), ("reporter", N_("Reporter")),
                  ("resolution", N_("Resolution")), ("custom field (story points)", N_("Story points")),
                  ("custom field (epic link)", N_("Epic")), ("custom field (epic name)", N_("Epic")))


def parse_jira(data, fname, opts, plan):
    keys, rows = imp_csv_multi(imp_decode(data))
    if "summary" not in keys or not ({"issue key", "issue id"} & set(keys)):
        imp_fail(N_("This is not a Jira CSV export (columns Summary and Issue key missing)"))
    one = lambda r, k: (r.get(k) or [""])[0]  # noqa: E731
    lists, idx, out = {}, {}, []
    for r in rows:
        title = imp_line(one(r, "summary"))
        key, iid = imp_line(one(r, "issue key"), 100), imp_line(one(r, "issue id"), 100)
        if not title or not (key or iid):
            continue
        ln = imp_line(one(r, "project name") or one(r, "project key"), LIST_NAME_MAX) or imp_stem(fname) or "Jira"
        L = lists.get(ln) or lists.setdefault(ln, imp_list(plan, ln))
        d, tm = imp_anydate(one(r, "due date"))
        tags = [imp_line(x, 100) for k in ("labels", "label") for v in r.get(k) or [] for x in str(v).split() if imp_line(x, 100)]
        t = imp_task(L, key or iid, title, due=d, due_time=None if tm == "00:00" else tm, tags=list(dict.fromkeys(tags))[:50],
                     created_at=imp_ts(" ".join(filter(None, imp_anydate(one(r, "created"))))) if one(r, "created") else None)
        if one(r, "due date").strip() and not d:
            imp_warn(plan, N_("Date not understood, kept in the notes: {0}"), title, imp_line(one(r, "due date"), 60))
            imp_addnote(t, tr("Due: {0}", imp_line(one(r, "due date"), 100)))
        sd = imp_anydate(one(r, "custom field (start date)"))[0]
        if sd and d and sd <= d:
            t["start"] = sd
        pr = imp_prio_any(one(r, "priority"))
        t["priority"] = pr or 0
        st = imp_done(one(r, "status"))
        res = one(r, "resolution").strip()
        if res and res.lower() not in ("unresolved", "ungelöst"):  # a resolution means closed; "Won't Do" etc. = cancelled
            st = -1 if imp_done(res) == -1 else (st or 2)
        if st:
            rv = one(r, "resolved")
            rd = imp_anydate(rv) if rv else (None, None)
            t.update(status=st, completed_at=imp_ts(f"{rd[0]} {rd[1] or '12:00'}") if rd[0] else iso(now_utc()))
        head = " · ".join(x for x in (key, imp_line(one(r, "issue type"), 100)) if x)
        imp_addnote(t, "Jira: " + head if head else "")
        imp_addnote(t, one(r, "description"))
        lines = []
        for k, label in JIRA_NOTE_COLS:
            vals = [imp_line(x, 200) for x in r.get(k) or [] if imp_line(x, 200)]
            if vals:
                lines.append(f"{tr(label)}: {', '.join(dict.fromkeys(vals))}")
        if pr is None:
            lines.append(f"{tr('Priority')}: {imp_line(one(r, 'priority'), 100)}")
        if lines:
            imp_addnote(t, "\n".join(lines))
        imp_who(t, "jira", one(r, "assignee"))
        for x in (key, iid):
            if x:
                idx.setdefault(x, t["ext"])
        out.append((t, imp_line(one(r, "parent") or one(r, "parent id") or one(r, "parent key"), 100)))
    for t, p in out:
        if p:
            t["parent"] = idx.get(p)
            if not t["parent"]:
                imp_warn(plan, N_("Parent task not found, imported as a main task"), t["title"])


IMPORT_PARSERS = {"todoist": parse_todoist, "trello": parse_trello, "asana": parse_asana, "mstodo": parse_mstodo, "ics": parse_ics,
                  # 2.142.0 B (#2147)
                  "notion": parse_notion, "gtasks": parse_gtasks, "clickup": parse_clickup, "jira": parse_jira, "csv": parse_csv,
                  "markdown": parse_markdown}


# ---- writing a plan
def imp_user_match(c, a, people):
    """An assignee of the file -> an Kalmido user id, only if e-mail / user name / display name match exactly one user who is
    in `people` (owner + members of the target list)."""
    if not a or not people:
        return None
    q = ",".join("?" * len(people))
    us = c.execute(f"SELECT id, username, display_name, email FROM users WHERE disabled=0 AND id IN ({q})", list(people)).fetchall()
    for key, col in (("email", "email"), ("username", "username"), ("name", "display_name"), ("name", "username")):
        v = (a.get(key) or "").strip().lower()
        if v:
            hit = [u["id"] for u in us if (u[col] or "").strip().lower() == v]
            if len(hit) == 1:
                return hit[0]
    return None


def imp_clean(plan, t):
    """Validates one task of a plan like the app's own input; drops what does not fit (with a warning)."""
    if t["due"] and not valid_date(t["due"]):
        imp_warn(plan, N_("Invalid date removed"), t["title"])
        t.update(due=None, due_time=None, start=None)
    if t["due_time"] and not valid_hm(t["due_time"]):
        t["due_time"] = None
    if t["start"] and (not valid_date(t["start"]) or not t["due"] or t["start"] > t["due"]):
        t["start"] = None
    if t["repeat"]:
        rep = rr_norm(t["repeat"])
        if rr_problem(rep) or (t["due"] and not rr_feasible(rep, t["due"])):
            imp_warn(plan, N_("Repetition not supported (only daily, weekly, monthly or yearly), kept in the notes"), t["title"])
            imp_addnote(t, tr("Repeats: {0}", imp_line(rep, 300)))
            rep = ""
        t["repeat"] = rep
        if rep and not t["due"]:
            t["due"] = local_now().date().isoformat()
    if t["url"] and not valid_url(t["url"]):
        t["url"] = None
    if t["duration"] is not None and not (isinstance(t["duration"], int) and 1 <= t["duration"] <= DURATION_MAX):
        t["duration"] = None
    try:
        rem = clean_reminders([x for x in t["reminders"]][:REM_COUNT]) if t["due"] else ""
    except BadInput:
        rem = ""
    b = {"title": t["title"] or tr("(untitled)"), "content": t["notes"], "priority": t["priority"] if t["priority"] in PRIORITIES else 0,
         "due": t["due"], "due_time": t["due_time"] if t["due"] else None, "start": t["start"], "reminders": rem,
         "repeat": t["repeat"], "repeat_from": t["repeat_from"], "duration": t["duration"]}
    try:
        return clean_task(b)
    except BadInput:  # never expected (everything is checked above); keep the text at least
        imp_warn(plan, N_("Some values were invalid and were removed"), t["title"])
        return clean_task({"title": b["title"], "content": b["content"]})


def imp_run(c, uid, plan, opts, dry):
    """Writes the plan for user uid in one transaction (dry: executes, then rolls back). -> report dict."""
    lg = lang(c, uid)
    total = sum(len(L["tasks"]) for L in plan["lists"])
    if not total:
        imp_fail(N_("No tasks found in the file"))
    if total > IMPORT_MAX_TASKS:
        imp_fail(N_("Too many tasks: {0} (at most {1} per import)"), total, IMPORT_MAX_TASKS)
    if opts.get("list_name") and len(plan["lists"]) == 1:
        plan["lists"][0]["name"] = imp_line(opts["list_name"], LIST_NAME_MAX) or plan["lists"][0]["name"]
    skip_done = opts.get("completed") == "skip"
    target = opts.get("target")
    from ..collab.liste2eguard import le2b_list_locked, le2b_off
    if target and le2b_list_locked(c, target):  # 2.64.1 B (#1817): the server cannot write texts into a list with the lock
        # 2.64.1 review (H1): raised, not returned -- import_any / the v1 route jsonify the result (a response tuple was a 500)
        raise Denied(409, le2b_off())
    c.commit()  # a clean transaction: nothing of this import is written before it is complete
    ts, now = iso(now_utc()), local_now()
    src = plan["source"]
    created = {"lists": [], "sections": [], "tasks": []}
    report_lists, idmap, rows = [], {}, []
    stats = {"tasks": 0, "subtasks": 0, "done": 0, "skipped": 0, "lists": 0, "sections": 0, "assigned": 0}
    s_all = usettings(c, uid)
    base_t = s_all.get("allday_time") or "09:00"
    own, space = {}, opts.get("space", False)
    for r in c.execute("SELECT id, name, org_id FROM lists WHERE owner_id=? AND is_inbox=0 AND archived=0 AND e2e IS NULL ORDER BY id", (uid,)):
        if space is False or r["org_id"] == space:  # 2.87.9 (#1940): a chosen workspace reuses only its own lists
            own.setdefault(r["name"], r["id"])  # 2.64.1 B (#1817): never into a list with the lock (a new list of that name instead)
    tl = token_lists()
    if tl is not None and not target:  # 2.86.0 (N19): a token limited to selected lists never creates lists, only fills allowed ones
        for L in plan["lists"]:
            lid = my_inbox(c, uid) if L["inbox"] else own.get(L["name"])
            if not lid or lid not in tl:
                raise Denied(403, tr("This token is limited to selected lists and cannot create new lists: choose one of them as the import target"))
    collab = collab_all()
    # a task's effective parent: same list, at most MAX_DEPTH levels (deeper ones hang below the deepest allowed level)
    where = {}
    for L in plan["lists"]:
        for t in L["tasks"]:
            where[t["ext"]] = (id(L), t)
    for L in plan["lists"]:
        for t in L["tasks"]:
            p, chain = t["parent"], []
            while p and p in where and len(chain) < 50:
                if where[p][0] != id(L) or p in chain or p == t["ext"]:
                    imp_warn(plan, N_("Subtask in another list or in a cycle, imported as a main task"), t["title"])
                    chain = []
                    break
                chain.append(p)
                p = where[p][1]["parent"]
            if t["parent"] and t["parent"] not in where:
                chain = []
            if len(chain) >= MAX_DEPTH:
                imp_warn(plan, N_("Nested deeper than {0} levels, moved up"), t["title"], MAX_DEPTH)
                chain = chain[len(chain) - (MAX_DEPTH - 1):]
            t["_parent"] = chain[0] if chain else None
    try:
        sort_l = my_max_sort(c, uid)
        for L in plan["lists"]:
            existing = True
            if target:
                lid = target
            elif L["inbox"]:
                lid = my_inbox(c, uid)
            elif L["name"] in own:
                lid = own[L["name"]]
            else:
                sort_l += 1
                lid = insert_id(c, "INSERT INTO lists(name,folder,sort,view,created_at,owner_id) VALUES(?,?,?,?,?,?)",
                                (L["name"] or tr("Import", lg=lg), L["folder"], sort_l, L["view"], ts, uid))
                from ..accounts.orgs import ws_apply_default
                if space is False:
                    ws_apply_default(c, uid, lid)  # 2.28.0 (#935): the default workspace
                elif space:  # 2.87.9 (#1940): the workspace the person confirmed (checked in imp_opts: an organisation of theirs)
                    c.execute("UPDATE lists SET org_id=? WHERE id=?", (space, lid))
                list_created(c, uid, lid)  # 2.25.0 (#931)
                if space is not False:  # 2.87.9 (#1940): a folder's default workspace never overrides the confirmed one
                    c.execute("UPDATE lists SET org_id=? WHERE id=?", (space, lid))
                own[L["name"]] = lid
                created["lists"].append(lid)
                stats["lists"] += 1
                existing = False
            people = list_people(c, lid) if collab else {uid}
            secs = {r["name"]: r["id"] for r in c.execute("SELECT id, name FROM sections WHERE list_id=?", (lid,))}
            sec_sort = c.execute("SELECT COALESCE(MAX(sort),0) FROM sections WHERE list_id=?", (lid,)).fetchone()[0]
            base_sort = c.execute("SELECT COALESCE(MAX(sort),0) FROM tasks WHERE list_id=?", (lid,)).fetchone()[0] + 1
            # into one existing list: several source lists without own sections become sections
            as_sec = L["name"] if target and len(plan["lists"]) > 1 and not L["sections"] else None
            rl = {"name": L["name"], "list_id": lid, "existing": existing, "tasks": 0, "skipped": 0, "sections": 0}
            for i, t in enumerate(L["tasks"]):
                key = f"{src}:{t['ext']}"
                old = c.execute("SELECT id FROM tasks WHERE created_by=? AND tt_id=?", (uid, key)).fetchone()
                if old:
                    idmap[t["ext"]] = old[0]
                    stats["skipped"] += 1
                    rl["skipped"] += 1
                    continue
                if skip_done and t["status"] != 0:
                    continue
                f = imp_clean(plan, t)
                sname = t["section"] or as_sec
                sid = None
                if sname:
                    if sname not in secs:
                        sec_sort += 1
                        secs[sname] = insert_id(c, "INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, sname, sec_sort))
                        created["sections"].append(secs[sname])
                        stats["sections"] += 1
                        rl["sections"] += 1
                    sid = secs[sname]
                reminded = []
                if f.get("due") and f.get("reminders"):
                    base = datetime.fromisoformat(f"{f['due']}T{f.get('due_time') or base_t}").replace(tzinfo=TZ)
                    reminded = [f"{f['due']} {f.get('due_time') or ''}|{o}" for o in f["reminders"].split(",")
                                if base - timedelta(minutes=int(o)) <= now]
                aid = imp_user_match(c, t["assignee"], people) if collab else None
                if t["assignee"] and not aid:
                    who = t["assignee"].get("name") or t["assignee"].get("email") or t["assignee"].get("username")
                    if who:
                        f["content"] = ((f.get("content") or "") + ("\n\n" if f.get("content") else "") +
                                        tr("Assignee ({0}): {1}", IMPORT_SOURCES[src], who, lg=lg))[:CONTENT_MAX]
                status = t["status"] if t["status"] in (0, 2, -1) else 0
                tid = insert_id(c, """INSERT INTO tasks(list_id,section_id,title,content,priority,status,due,due_time,reminders,reminded,repeat,
                       repeat_from,sort,created_at,updated_at,completed_at,tt_id,start,duration,created_by,completed_by,assignee_id,
                       assigned_by,url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (lid, sid, f["title"], f.get("content") or "", f.get("priority") or 0, status, f.get("due"), f.get("due_time"),
                     f.get("reminders") or "", json.dumps(reminded), f.get("repeat") or "", f.get("repeat_from") or "due",
                     base_sort + i, t["created_at"] or ts, ts, (t["completed_at"] or ts) if status else None, key, f.get("start"),
                     f.get("duration"), uid, uid if status else None, aid, uid if aid else None, t["url"]))
                idmap[t["ext"]] = tid
                created["tasks"].append(tid)
                rows.append((t, tid, lid))
                if t["tags"]:
                    set_tags(c, tid, [x[:100] for x in t["tags"]][:50], uid)
                c.execute("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
                          (tid, uid, "import", json.dumps({"source": IMPORT_SOURCES[src], **({"via": "api"} if act_via() == "api" else {})}),
                           iso_ms(now_utc())))
                stats["tasks"] += 1
                stats["done"] += 1 if status else 0
                stats["assigned"] += 1 if aid else 0
                rl["tasks"] += 1
            report_lists.append(rl)
        for t, tid, lid in rows:  # second pass: parents (the subtask follows its parent's section)
            p = t.get("_parent")
            if p and p in idmap and idmap[p] != tid:
                pr = c.execute("SELECT list_id, section_id FROM tasks WHERE id=?", (idmap[p],)).fetchone()
                if pr and pr["list_id"] == lid and depth(c, idmap[p]) + 1 < MAX_DEPTH:
                    c.execute("UPDATE tasks SET parent_id=?, section_id=? WHERE id=?", (idmap[p], pr["section_id"], tid))
                    stats["subtasks"] += 1
                else:
                    imp_warn(plan, N_("Subtask in another list or in a cycle, imported as a main task"), t["title"])
        rep = {"source": src, "source_name": IMPORT_SOURCES[src], "dry_run": bool(dry), "created": stats, "skipped": stats["skipped"],
               "lists": report_lists, "import_id": None, "undo_until": None,
               "samples": [{"list": L["name"], "title": t["title"], "section": t["section"], "due": t["due"], "due_time": t["due_time"],
                            "priority": t["priority"], "status": t["status"], "tags": t["tags"][:5], "repeat": t["repeat"],
                            "subtask": bool(t.get("_parent"))}
                           for L in plan["lists"] for t in L["tasks"][:IMPORT_SAMPLES]][:IMPORT_SAMPLES],
               "warnings": [{"text": tr(k[0], *k[1:], lg=lg), "count": w["n"], "examples": w["ex"]}
                            for k, w in plan["warn"].items()],
               # 2.142.0 B (#2147): any CSV: which column went into which field (unknown columns: the notes)
               **({"columns": plan["columns"]} if plan.get("columns") else {}),
               # compatibility with the TickTick import's answer
               "tasks": stats["tasks"], "new_lists": stats["lists"]}
        if dry:
            c.rollback()
            return rep
        if created["tasks"] or created["lists"] or created["sections"]:
            iid = insert_id(c, "INSERT INTO imports(user_id,source,file_name,created,report,created_at) VALUES(?,?,?,?,?,?)",
                            (uid, src, opts.get("_fname", "")[:200], json.dumps(created), json.dumps(stats), ts))
            c.execute("""DELETE FROM imports WHERE user_id=? AND id NOT IN
                         (SELECT id FROM imports WHERE user_id=? ORDER BY id DESC LIMIT ?)""", (uid, uid, IMPORT_KEEP))
            rep["import_id"] = iid
            rep["undo_until"] = iso(now_utc() + timedelta(hours=IMPORT_UNDO_HOURS))
        bump(c)
        c.commit()
    except BaseException:
        c.rollback()
        raise
    print("import", src, "user", uid, "tasks", stats["tasks"], "skipped", stats["skipped"], "lists", stats["lists"], flush=True)
    return rep


def imp_opts(form, uid):
    """Form fields of an import request -> options (BadInput for unknown fields / values)."""
    unknown = sorted(k for k in form if k not in IMPORT_OPTS)
    if unknown:
        raise UnknownFields(unknown)
    o = {"dry_run": str(form.get("dry_run", "")).lower() in ("1", "true", "yes", "on")}
    tg = str(form.get("target") or "new").strip()
    if tg != "new":
        o["target"] = as_int(tg, "target", 1)
        need_list(db(), o["target"])  # 404 / 403 (view only) like every other write
        from ..collab.liste2e import le2a_gen_refuse
        le2a_gen_refuse(db(), o["target"])  # 2.64.1 review (H1): 409 code list_e2e_plain before the file is even parsed
    for k, allowed in (("mode", ("sections", "lists")), ("archived", ("skip", "done")), ("completed", ("import", "skip")),
                       ("priority_scale", ("auto", "1", "4"))):
        v = str(form.get(k) or "").strip()
        if v:
            if v not in allowed:
                raise BadInput(tr("Invalid value: {0}", k))
            o[k] = v
    if form.get("list_name"):
        o["list_name"] = str(form["list_name"])[:LIST_NAME_MAX]
    # 2.87.9 (#1940): the workspace of the NEW lists ('private' | 'org:<id>' of an organisation of the person); without it the
    # default of a new list (ws_default_org) as before. A list of the same name is reused only inside that workspace.
    sp = str(form.get("space") or "").strip()
    if sp:
        if sp == "private":
            o["space"] = None
        else:
            from ..accounts.orgs import user_orgs
            m = re.fullmatch(r"org:(\d+)", sp)
            if not m or int(m.group(1)) not in user_orgs(db(), uid):
                raise BadInput(tr("Invalid value: {0}", "space"))
            from ..accounts.orgroles import need_org_write
            need_org_write(db(), uid, int(m.group(1)))  # 2.143.0 A (#2151)
            o["space"] = int(m.group(1))
    return o


def imp_request(source):
    """Shared by POST /api/import/<source> (app) and POST /api/v1/import/<source> (token, scope write)."""
    if source not in IMPORT_SOURCES:
        raise Denied(404)
    uid = me()
    opts = imp_opts(request.form, uid)
    f = request.files.get("file")
    if not f:
        raise BadInput(tr("File missing"))
    if hit_limit(f"import:{uid}", IMPORT_RATE, 600):
        raise Denied(429, tr("Too many imports, please wait a few minutes"))
    data = f.read(IMPORT_MAX_MB * 1048576 + 1)
    if len(data) > IMPORT_MAX_MB * 1048576:
        raise Denied(413, tr("The file is too large (at most {0} MB)", IMPORT_MAX_MB))
    if not data.strip():
        raise BadInput(tr("The file is empty"))
    opts["_fname"] = imp_line(f.filename, 200)
    plan = imp_plan(source)
    IMPORT_PARSERS[source](data, f.filename or "", opts, plan)
    return imp_run(db(), uid, plan, opts, opts["dry_run"])


@app.post("/api/import/<source>")
def import_any(source):
    if source == "ticktick":
        return import_api()
    return jsonify(imp_request(source))


def imp_undo(c, uid, iid):
    r = c.execute("SELECT * FROM imports WHERE id=? AND user_id=?", (iid, uid)).fetchone()
    if not r:
        raise Denied(404)
    if r["undone_at"]:
        raise Denied(409, tr("This import was already undone"))
    if (now_utc() - parse_iso(r["created_at"])).total_seconds() > IMPORT_UNDO_HOURS * 3600:
        raise Denied(409, tr("An import can only be undone within {0} hours", IMPORT_UNDO_HOURS))
    if r["source"] == "Kalmido":  # 2.73.0 B (#1473): an account import undoes everything it created
        from ..admin.acctimport import umz_undo
        return umz_undo(c, uid, r)
    cr = json.loads(r["created"] or "{}")
    ids = [int(x) for x in cr.get("tasks") or []]
    mine = []
    for i in range(0, len(ids), 500):  # only tasks that are still this import's (tt_id set, created by the user) and writable
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        for t in c.execute(f"SELECT id, list_id FROM tasks WHERE id IN ({q}) AND created_by=? AND tt_id IS NOT NULL", part + [uid]):
            if list_role(c, t["list_id"], uid) in WRITE_ROLES:
                mine.append(t["id"])
    files, kept = [], 0
    for i in range(0, len(mine), 500):
        part = mine[i:i + 500]
        q = ",".join("?" * len(part))
        # tasks someone added below an imported task later stay (as main tasks)
        kept += c.execute(f"UPDATE tasks SET parent_id=NULL WHERE parent_id IN ({q}) AND id NOT IN ({q})", part + part).rowcount
    for i in range(0, len(mine), 500):
        part = mine[i:i + 500]
        q = ",".join("?" * len(part))
        files += [x[0] for x in c.execute(f"SELECT path FROM attachments WHERE task_id IN ({q})", part)]
        c.execute(f"DELETE FROM tasks WHERE id IN ({q})", part)
    secs = lists = kept_lists = 0
    gone = []
    for sid in cr.get("sections") or []:
        if not c.execute("SELECT 1 FROM tasks WHERE section_id=?", (sid,)).fetchone():
            secs += c.execute("DELETE FROM sections WHERE id=?", (sid,)).rowcount
    for lid in cr.get("lists") or []:
        if c.execute("SELECT 1 FROM lists WHERE id=? AND owner_id=?", (lid, uid)).fetchone():
            if c.execute("SELECT 1 FROM tasks WHERE list_id=?", (lid,)).fetchone():
                kept_lists += 1
            else:
                lists += list_row_purge(c, lid, gone)  # 2.7.2: its project files leave the disk too
    c.execute("UPDATE imports SET undone_at=? WHERE id=?", (iso(now_utc()), iid))
    bump(c)
    c.commit()
    unlink_files(files)
    list_purge_files(gone)
    print("import undo", iid, "user", uid, "tasks", len(mine), flush=True)
    return {"tasks": len(mine), "lists": lists, "sections": secs, "kept_lists": kept_lists, "kept_tasks": kept}


@app.post("/api/imports/<int:iid>/undo")
def import_undo(iid):
    return jsonify(imp_undo(db(), me(), iid))


@app.get("/api/imports")
def imports_list():
    """The user's recent imports (Settings > Data): source, file, counts, undo possible until."""
    c, out = db(), []
    for r in c.execute("SELECT * FROM imports WHERE user_id=? ORDER BY id DESC LIMIT ?", (me(), IMPORT_KEEP)):
        until = parse_iso(r["created_at"]) + timedelta(hours=IMPORT_UNDO_HOURS)
        out.append({"id": r["id"], "source": r["source"], "source_name": IMPORT_SOURCES.get(r["source"], r["source"]),
                    "file_name": r["file_name"], "created_at": r["created_at"], "counts": json.loads(r["report"] or "{}"),
                    "undone_at": r["undone_at"], "can_undo": not r["undone_at"] and until > now_utc(), "undo_until": iso(until)})
    return jsonify(imports=out, max_mb=IMPORT_MAX_MB, max_tasks=IMPORT_MAX_TASKS)
