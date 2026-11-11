"""2.152.0 (#2165 #2171 #2172 #2173 #2175): deletion periods and the switch of the retention runs.

Every background run that deletes data for good because a period ran out (trash periods, old logs, old safety backups,
orphan files, the agent chat's day limit) asks ret_on(kind) first and reports what it did -- or, while the switch is off,
what it WOULD have deleted -- with ret_report(). Default: off = count only ("dry run"), so an update never deletes
anything by surprise; the admin reads the counts (GET /api/admin/retention) and switches the runs on with
KALMIDO_RETENTION_PURGE=1 (all kinds) or KALMIDO_PURGE_<KIND>=1 / =0 (one kind, wins over the general switch).

Periods (days) per kind: RET_DAYS, each overridable by its env variable (RET_ENV). Legal retention (receipts, books,
the logbook: RET_LEGAL_YEARS) is never a purge: those rows are locked, not deleted (#2168 #2169).
2.545.0 (#4595): every lock keeps ret_keep_years(kind) = the law + the operator's buffer (KALMIDO_RETENTION_BUFFER_YEARS,
default 1 year, never below the law); the one source for olock.olk_until, orgretain, signoff and bookarch.

Expired credentials (sessions, tokens, codes past their end) are no data of a person any more and go without the switch.

2.272.0 A (#3026): the runs that delete for good (watchdog notify/push.py, backup loop). Trash periods all use ret_trash_cut()
(ret_days("trash"), floor 1 day). "kept" = lists.retain_until / legal locks are honoured. run = ret_report slot.
  run (module)                          kind     period            what goes / note
  obj_trash (core/writes.py)            trash    trash             the core's kinds with trash_prune; 2.936.0 (#5364): + task
                                                                    (tasks/tasktrash.py: + attachments, lists kept by law stay:
                                                                    task_kept) and list (lists/listtrash.py: with tasks + files,
                                                                    retain_until waits: list_kept) -- the runs tasks / lists went
  obj_trash (core/writes.py)            trash    trash             2.773.0 (#5292): the core kinds with trash_prune; 2.809.0 (#5365):
                                                                    + fs nodes (fs_entry, receipts locked: fs_entry_locked), knowledge
                                                                    pages with their files (wiki_page), tables (sheet_table)
                                                                    2.947.0 (#5367): + calendars with their events (evcal), address
                                                                    books (address_book), bookmarks with their pictures
                                                                    (bookmark_link), feeds (rss_feed), video sign-offs (video_review)
  - (files/trashpurge.py tp_tick)       trash    trash             hub mails, deleted table rows / columns, deals, series, tombstones
                                                                    2.223.3 A (#2879): + absences, dispo bookings, polls with votes,
                                                                    appointment types, file requests
  wiki_files (wiki/wikiatt.py)          trash    trash             files trashed on their own
  wiki_e2e_held (wiki/wkhist.py)        trash    trash             2.528.0 D (#4306): versions held when a space's lock went on
  sheet_files (sheets/shkinds.py)       trash    trash             table files no cell holds any more
  videos (videos/review.py)             trash    trash             comments trashed on their own (2.947.0 #5367: reviews = obj_trash)
  events (events/model.py)              trash    trash             events trashed on their own (2.947.0 #5367: calendars = obj_trash)
  (feeds: fetched articles are a cache, 30 days, no switch; 2.947.0 #5367: bookmarks and feeds = obj_trash)
  contract_files (office/contractfiles) trash    trash             trashed contract PDFs
  meals (office/meals.py)               trash    trash             trashed entertainment receipts (approved ones stay: legal)
  retired_orgs (accounts/orgretain.py)  trash    orgs.retain_until retired organisations after their legal period
  agreements (office/agreements.py)     trash    trash             deleted agreements (on reading the list, per organisation)
  suppliers (office/datevimp.py)        trash    trash             deleted DATEV suppliers (on reading / importing, per organisation)
  bookarch (office/bookarch.py)         trash    10 years (book)   2.414.0 (#3502): archived DATEV years after their legal period,
                                                                    with receipt images and original files (daily, the watchdog)
  webhooks_in (integrations/hookin.py)  trash    trash             deleted incoming webhooks (on reading a list's webhooks)
    2.272.0 F (#3026, review M4): these three run inside a request; they report only when they deleted something
  fs_orphans (files/fsmove.py)          files    files             stored versions no row names
  chat_files / tchat_files              files    files             chat / team chat files no row names
  terms_files (office/terms.py)         files    30 days fixed     replaced terms PDFs nobody names
  - (admin/dataretention.py lgc_tick)   logs     logs              activity / list / file / sheet logs (expired credentials always)
  - (admin/dataretention.py lgc_tick)   logs     backups kept      journal of deleted accounts once no backup can hold them (2.312.0 B)
  - (admin/dataretention.py orf_tick)   files    files             orphan files, old file versions
  - (admin/dataretention.py ckd_tick)   chat     chat              agent chat days
  - (admin/backup.py bk_prune)          backups  backups           old safety backups (the daily / weekly rotation always)
No switch, on purpose (technical, no content a person keeps): news feed rows (derived, TASKS_NEWS_DAYS), office read log
(GoBD keeps the writes), agent usage / audit / proposals (agent bookkeeping), merge undo snapshots (blanked after 30 days),
office editor undo copies (24 h), org / account export archives and import uploads (24 h copies), push / tidy / rule / mail
queues, scan rows of deleted files, embeddings, removed server link tokens (credentials).
"""
import json
import os
import time
from datetime import timedelta

from .errors import Denied
from .db import gset, iso, now_utc
from .env import env_int
from .i18n import N_, short_day, tr
from .pg import system_ctx

RET_KINDS = ("trash", "logs", "backups", "files", "chat")
RET_DAYS = {
    "trash": 30,     # #2165: files, wiki, hub mails, sheets, pipeline, invoice series, chat tombstones
    "logs": 400,     # #2171: activity, list_activity, fs_log, org_list_log, sheet_changes, sheet_hist (#5283) (office logs stay: GoBD)
    "backups": 30,   # #2172: safety backups (kind=safety) older than this
    "files": 1,      # #2173: an orphan file must be older than this before the sweep removes it
    "chat": 0,       # #2175: agent chat messages older than this (0 = no day limit, only the count limit)
}
RET_ENV = {"trash": "KALMIDO_TRASH_DAYS", "logs": "KALMIDO_LOG_DAYS", "backups": "KALMIDO_SAFETY_BACKUP_DAYS",
           "files": "KALMIDO_ORPHAN_DAYS", "chat": "KALMIDO_CHAT_KEEP_DAYS"}
# Legal retention in Germany (section 147 AO, section 257 HGB, section 14b UStG): receipts 8 years (since 2025), books 10
RET_LEGAL_YEARS = {"receipt": 8, "book": 10, "logbook": 8, "letter": 6}  # 2.184.0 A (#2628): sent business letters (section 257 HGB)
# 2.545.0 (#4595, decision of 04.11.2026): the periods kept are the law plus a buffer the operator sets (never below the law)
RET_BUFFER_ENV = "KALMIDO_RETENTION_BUFFER_YEARS"
RET_BUFFER_YEARS = 1
RET_BUFFER_MAX = 30
RET_ON_VALUES = ("1", "on", "true", "yes")
RET_OFF_VALUES = ("0", "off", "false", "no")


def ret_days(kind):
    """The period of a kind in days (env first, then RET_DAYS); a broken env value keeps the default."""
    raw = os.environ.get(RET_ENV.get(kind, ""), "").strip()
    try:
        return max(0, int(raw)) if raw else RET_DAYS[kind]
    except ValueError:
        return RET_DAYS[kind]


def ret_buffer_years():
    """2.545.0 (#4595): the years the operator adds to every legal period (env, default 1); below 0 = 0 (never under the law)."""
    return env_int(RET_BUFFER_ENV, RET_BUFFER_YEARS, 0, RET_BUFFER_MAX)


def ret_keep_years(kind):
    """2.545.0 (#4595): how many years after the end of its calendar year a row of kind (receipt, book, logbook, letter) is kept:
    the law (RET_LEGAL_YEARS) plus the operator's buffer. Every retention lock asks this one."""
    return RET_LEGAL_YEARS[kind] + ret_buffer_years()


# 2.545.0 (#4595): the switch "Extend the lock" of an office (orgs.ret_hold_at, office/rethold.py): a tax audit is open, nothing
# kept by law is deleted, also after its period (office/olock.py, accounts/orgretain.py, accounts/orgs.py ask it)
RET_HELD = N_("Deleting is paused: the retention lock of this office is extended (since {0}). Switch it off in the office settings first.")
RET_HELD_ANY = N_("Deleting is paused: the retention lock of this office is extended. Switch it off in the office settings first.")


def ret_held(c, oid):
    """2.545.0 (#4595): since when (ISO time) the switch "Extend the lock" of office oid (an organisation or a personal office)
    is on, else None. Structure only, read as system (the deleting run or person need not be a member)."""
    if not oid:
        return None
    with system_ctx(c):
        r = c.execute("SELECT ret_hold_at FROM orgs WHERE id=?", (int(oid),)).fetchone()
    return (r[0] or None) if r else None


def ret_held_text(at):
    from datetime import datetime  # noqa: PLC0415
    try:
        return tr(RET_HELD, short_day(datetime.fromisoformat(str(at)[:19]).date(), year=True))
    except ValueError:
        return tr(RET_HELD_ANY)


def ret_need_unheld(c, oid):
    """2.545.0 (#4595): 409 with the reason while the switch "Extend the lock" of office oid is on."""
    at = ret_held(c, oid)
    if at:
        raise Denied(409, ret_held_text(at))


def ret_person_office(c, uid):
    """2.545.0 (#4595): the personal office of person uid (orgs.personal_of), else None."""
    if not uid:
        return None
    with system_ctx(c):
        r = c.execute("SELECT id FROM orgs WHERE personal_of=?", (int(uid),)).fetchone()
    return r[0] if r else None


def ret_trash_days():
    """2.272.0 A (#3026): the trash period in days with the floor of 1 -- 0 (a typo, an empty template) never means "everything now"."""
    return max(1, ret_days("trash"))


def ret_trash_cut():
    """2.272.0 A (#3026): the ISO time before which a row in a trash is due (now - ret_trash_days()); every trash run uses it."""
    return iso(now_utc() - timedelta(days=ret_trash_days()))


RET_DUE = {}  # 2.272.0 A (#3026): run name -> time.time() of its last pass


def ret_due(run, every=3600, force=False):
    """2.272.0 A (#3026): True at most once per `every` seconds per run -- the watchdog ticks every 30 s, a run that counts
    (switch off) or deletes reports once an hour instead of writing its numbers every tick. force = tests."""
    t = time.time()
    if not force and t - RET_DUE.get(run, 0.0) < every:
        return False
    RET_DUE[run] = t
    return True


def ret_on(kind):
    """True = the run of this kind deletes; False = it only counts (the safe default)."""
    one = os.environ.get(f"KALMIDO_PURGE_{kind.upper()}", "").strip().lower()
    if one in RET_ON_VALUES:
        return True
    if one in RET_OFF_VALUES:
        return False
    return os.environ.get("KALMIDO_RETENTION_PURGE", "").strip().lower() in RET_ON_VALUES


def ret_report(c, kind, counts, purged, run=None):
    """Keep the last result of a run (numbers only, no content) for GET /api/admin/retention and the server log.
    counts: {"what": n}; purged: True when the rows / files are gone, False for a dry run; run: a name of its own when
    several runs share a kind (each keeps its own slot). The caller commits."""
    counts = {k: int(v) for k, v in (counts or {}).items() if v}
    key = f"ret_last_{kind}" + (f".{run}" if run else "")
    gset(c, key, json.dumps({"at": iso(now_utc()), "purged": bool(purged), "counts": counts}))
    if counts:
        print(f"retention: {kind}{'/' + run if run else ''} {'deleted' if purged else 'would delete (dry run)'}: "
              + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())), flush=True)


def ret_status(c):
    """Every kind: switch, period, env names and the last result."""
    out = {}
    for k in RET_KINDS:
        runs = {}
        for r in c.execute("SELECT key, value FROM settings WHERE key=? OR key LIKE ?", (f"ret_last_{k}", f"ret_last_{k}.%")):  # pg-ok: own lower-case setting keys, case-sensitive on purpose
            try:
                v = json.loads(r[1] or "null")
            except ValueError:
                continue
            if isinstance(v, dict):
                runs[r[0].partition(".")[2] or k] = v
        last = max(runs.values(), key=lambda v: v.get("at") or "", default=None)
        out[k] = {"on": ret_on(k), "days": ret_days(k), "env_days": RET_ENV[k], "env_switch": f"KALMIDO_PURGE_{k.upper()}",
                  "last": last, "runs": runs}
    return {"general_switch": "KALMIDO_RETENTION_PURGE", "kinds": out, "legal_years": RET_LEGAL_YEARS,
            # 2.545.0 (#4595): the periods really kept (law + buffer) and the variable of the buffer
            "buffer_years": ret_buffer_years(), "env_buffer": RET_BUFFER_ENV, "keep_years": {k: ret_keep_years(k) for k in RET_LEGAL_YEARS}}
