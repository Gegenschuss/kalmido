"""2.152.0 (#2165 #2171 #2172 #2173 #2175): deletion periods and the switch of the retention runs.

Every background run that deletes data for good because a period ran out (trash periods, old logs, old safety backups,
orphan files, the agent chat's day limit) asks ret_on(kind) first and reports what it did -- or, while the switch is off,
what it WOULD have deleted -- with ret_report(). Default: off = count only ("dry run"), so an update never deletes
anything by surprise; the admin reads the counts (GET /api/admin/retention) and switches the runs on with
KALMIDO_RETENTION_PURGE=1 (all kinds) or KALMIDO_PURGE_<KIND>=1 / =0 (one kind, wins over the general switch).

Periods (days) per kind: RET_DAYS, each overridable by its env variable (RET_ENV). Legal retention (receipts, books,
the logbook: RET_LEGAL_YEARS) is never a purge: those rows are locked, not deleted (#2168 #2169).

Expired credentials (sessions, tokens, codes past their end) are no data of a person any more and go without the switch.

2.272.0 A (#3026): the runs that delete for good (watchdog notify/push.py, backup loop). Trash periods all use ret_trash_cut()
(ret_days("trash"), floor 1 day). "kept" = lists.retain_until / legal locks are honoured. run = ret_report slot.
  run (module)                          kind     period            what goes / note
  tasks (tasks/tasktrash.py)            trash    trash             trashed tasks + attachments; lists kept by law stay (tasks_kept)
  lists (lists/listtrash.py otr_prune)  trash    trash             trashed lists with tasks + files; retain_until waits
  - (files/trashpurge.py tp_tick)       trash    trash             fs nodes (receipts locked), hub mails, sheets, deals, series, tombstones
  wiki (wiki/pages.py)                  trash    trash             trashed pages with versions + their files
  wiki_files (wiki/wikiatt.py)          trash    trash             files trashed on their own
  sheet_files (sheets/shkinds.py)       trash    trash             table files no cell holds any more
  videos (videos/review.py)             trash    trash             trashed video reviews / comments
  events (events/model.py)              trash    trash             trashed events
  bookmarks (life/bookmarks.py)         trash    trash             trashed bookmarks + pictures
  feeds (life/rss.py)                   trash    trash             trashed feed subscriptions (fetched articles: cache, 30 days, no switch)
  contract_files (office/contractfiles) trash    trash             trashed contract PDFs
  meals (office/meals.py)               trash    trash             trashed entertainment receipts (approved ones stay: legal)
  retired_orgs (accounts/orgretain.py)  trash    orgs.retain_until retired organisations after their legal period
  agreements (office/agreements.py)     trash    trash             deleted agreements (on reading the list, per organisation)
  suppliers (office/datevimp.py)        trash    trash             deleted DATEV suppliers (on reading / importing, per organisation)
  webhooks_in (integrations/hookin.py)  trash    trash             deleted incoming webhooks (on reading a list's webhooks)
    2.272.0 F (#3026, review M4): these three run inside a request; they report only when they deleted something
  fs_orphans (files/fsmove.py)          files    files             stored versions no row names
  chat_files / tchat_files              files    files             chat / team chat files no row names
  terms_files (office/terms.py)         files    30 days fixed     replaced terms PDFs nobody names
  - (admin/dataretention.py lgc_tick)   logs     logs              activity / list / file / sheet logs (expired credentials always)
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

from .db import gset, iso, now_utc

RET_KINDS = ("trash", "logs", "backups", "files", "chat")
RET_DAYS = {
    "trash": 30,     # #2165: files, wiki, hub mails, sheets, pipeline, invoice series, chat tombstones
    "logs": 400,     # #2171: activity, list_activity, fs_log, org_list_log, sheet_changes (office logs stay: GoBD)
    "backups": 30,   # #2172: safety backups (kind=safety) older than this
    "files": 1,      # #2173: an orphan file must be older than this before the sweep removes it
    "chat": 0,       # #2175: agent chat messages older than this (0 = no day limit, only the count limit)
}
RET_ENV = {"trash": "KALMIDO_TRASH_DAYS", "logs": "KALMIDO_LOG_DAYS", "backups": "KALMIDO_SAFETY_BACKUP_DAYS",
           "files": "KALMIDO_ORPHAN_DAYS", "chat": "KALMIDO_CHAT_KEEP_DAYS"}
# Legal retention in Germany (section 147 AO, section 257 HGB, section 14b UStG): receipts 8 years (since 2025), books 10
RET_LEGAL_YEARS = {"receipt": 8, "book": 10, "logbook": 8, "letter": 6}  # 2.184.0 A (#2628): sent business letters (section 257 HGB)
RET_ON_VALUES = ("1", "on", "true", "yes")
RET_OFF_VALUES = ("0", "off", "false", "no")


def ret_days(kind):
    """The period of a kind in days (env first, then RET_DAYS); a broken env value keeps the default."""
    raw = os.environ.get(RET_ENV.get(kind, ""), "").strip()
    try:
        return max(0, int(raw)) if raw else RET_DAYS[kind]
    except ValueError:
        return RET_DAYS[kind]


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
    return {"general_switch": "KALMIDO_RETENTION_PURGE", "kinds": out, "legal_years": RET_LEGAL_YEARS}
