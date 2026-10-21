"""2.152.0 (#2165 #2171 #2172 #2173 #2175): deletion periods and the switch of the retention runs.

Every background run that deletes data for good because a period ran out (trash periods, old logs, old safety backups,
orphan files, the agent chat's day limit) asks ret_on(kind) first and reports what it did -- or, while the switch is off,
what it WOULD have deleted -- with ret_report(). Default: off = count only ("dry run"), so an update never deletes
anything by surprise; the admin reads the counts (GET /api/admin/retention) and switches the runs on with
KALMIDO_RETENTION_PURGE=1 (all kinds) or KALMIDO_PURGE_<KIND>=1 / =0 (one kind, wins over the general switch).

Periods (days) per kind: RET_DAYS, each overridable by its env variable (RET_ENV). Legal retention (receipts, books,
the logbook: RET_LEGAL_YEARS) is never a purge: those rows are locked, not deleted (#2168 #2169).

Expired credentials (sessions, tokens, codes past their end) are no data of a person any more and go without the switch.
"""
import json
import os

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
RET_LEGAL_YEARS = {"receipt": 8, "book": 10, "logbook": 8}
RET_ON_VALUES = ("1", "on", "true", "yes")
RET_OFF_VALUES = ("0", "off", "false", "no")


def ret_days(kind):
    """The period of a kind in days (env first, then RET_DAYS); a broken env value keeps the default."""
    raw = os.environ.get(RET_ENV.get(kind, ""), "").strip()
    try:
        return max(0, int(raw)) if raw else RET_DAYS[kind]
    except ValueError:
        return RET_DAYS[kind]


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
        for r in c.execute("SELECT key, value FROM settings WHERE key=? OR key LIKE ?", (f"ret_last_{k}", f"ret_last_{k}.%")):
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
