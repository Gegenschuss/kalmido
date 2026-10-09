"""2.33.0 (#1045): the usage ring -- how much of its plan's quota an agent has used (e.g. Claude's 5-hour and weekly windows).

Kalmido cannot see an agent's plan, so the agent (its host) reports it: PUT /api/v1/agent/quota with one or more WINDOWS
{label, percent, resets_at?, main?} or, for Claude Code, the status line's rate_limits object as it is ({five_hour:
{used_percentage, resets_at}, seven_day: {...}, spend_limit: {...}}), plus an optional own LIMIT in percent (e.g. 90: the
host pauses there). Stored per agent in agents.quota (json {windows, main, limit, at}); a new report replaces the old one,
an empty one / DELETE removes it (no ring). This is not the token log of agents.usage (#326): numbers only, no tokens.

Shown to the people who may chat with the agent (agent_public: everyone it shares a list with) as a ring right of its name in
the chat header: filled with the MAIN window (rate_limits: the week), accent colour, from QUOTA_WARN % yellow, from the limit
(no limit: 100 %) red with "paused until <reset of the main window>"; a report older than QUOTA_STALE_H hours is greyed out.
A tap / hover lists every window with its percentage and reset time. A window whose reset time has passed counts as 0 %."""
import json
import re
from datetime import datetime, timedelta, timezone

from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import bump, db, iso, now_utc, parse_iso
from ..personal.timetrack import BadInput, UnknownFields
from ..api.v1 import v1_args, v1_json, v1_view
from ..agents.core import agent_row, need_agent

QUOTA_WINDOWS_MAX = 6
QUOTA_LABEL_MAX = 40
QUOTA_PCT_MAX = 1000          # above 100 % happens (a spend limit that is exceeded)
QUOTA_STALE_H = 24
QUOTA_WARN = 75
# Claude Code status line (rate_limits): key -> label (the client translates the known keys); the week is the main window
CC_WINDOWS = (("seven_day", "Week"), ("five_hour", "5 hours"), ("spend_limit", "Spend limit"))
_BAD = re.compile(r"[<>\x00-\x1f\x7f]")
CC_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")  # 2.35.0 (#1098): further rate_limits windows


def _pct(v, k):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0 or v > QUOTA_PCT_MAX:
        raise BadInput(tr("Invalid value: {0}", k))
    return round(float(v), 1)


def _when(v, k):
    """resets_at: ISO 8601 with a time zone or Unix epoch seconds (Claude Code) -> ISO UTC; None stays None."""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, bool):
            raise ValueError
        if isinstance(v, (int, float)):
            d = datetime.fromtimestamp(float(v), tz=timezone.utc)
        elif isinstance(v, str) and len(v) <= 40:
            d = parse_iso(v.strip())
            if d.tzinfo is None:
                raise ValueError
        else:
            raise ValueError
    except (ValueError, TypeError, OverflowError, OSError):
        raise BadInput(tr("Invalid value: {0}", k))
    if not datetime(2000, 1, 1, tzinfo=timezone.utc) < d < datetime(2200, 1, 1, tzinfo=timezone.utc):
        raise BadInput(tr("Invalid value: {0}", k))
    return iso(d.astimezone(timezone.utc))


def quota_in(b):
    """The body of PUT /agent/quota -> {windows, main, limit} (windows [] = remove). 400 on anything odd."""
    unknown = sorted(k for k in b if k not in ("windows", "rate_limits", "limit", "measured_at"))
    if unknown:
        raise UnknownFields(unknown)
    if "windows" in b and "rate_limits" in b:
        raise BadInput(tr("Send either windows or rate_limits, not both"))
    out, main = [], None
    if "rate_limits" in b:
        rl = b["rate_limits"]
        if rl is not None and not isinstance(rl, dict):
            raise BadInput(tr("Invalid value: {0}", "rate_limits"))
        for key, label in CC_WINDOWS:
            w = (rl or {}).get(key)
            if w is None:
                continue
            if not isinstance(w, dict) or w.get("used_percentage") is None:
                raise BadInput(tr("Invalid value: {0}", "rate_limits." + key))
            out.append({"key": key, "label": label, "percent": _pct(w["used_percentage"], f"rate_limits.{key}.used_percentage"),
                        "resets_at": _when(w.get("resets_at"), f"rate_limits.{key}.resets_at")})
        # 2.35.0 (#1098): every further window Claude Code reports (e.g. a weekly one per model) passes through, labelled
        # by its key; odd entries are skipped, never an error (a newer host must not lose its ring)
        known = {k for k, _ in CC_WINDOWS}
        for key, w in sorted((rl or {}).items()):
            if key in known or len(out) >= QUOTA_WINDOWS_MAX or not isinstance(key, str) or not CC_KEY_RE.fullmatch(key):
                continue
            if not isinstance(w, dict) or w.get("used_percentage") is None:
                continue
            try:
                out.append({"key": key, "label": key.replace("_", " ").capitalize()[:QUOTA_LABEL_MAX],
                            "percent": _pct(w["used_percentage"], key), "resets_at": _when(w.get("resets_at"), key)})
            except BadInput:
                continue
        main = 0 if out else None
    else:
        ws = b.get("windows") or []
        if not isinstance(ws, list) or len(ws) > QUOTA_WINDOWS_MAX:
            raise BadInput(tr("Invalid value: {0}", "windows"))
        for i, w in enumerate(ws):
            if not isinstance(w, dict):
                raise BadInput(tr("Invalid value: {0}", "windows"))
            bad = sorted(k for k in w if k not in ("label", "percent", "resets_at", "main"))
            if bad:
                raise UnknownFields([f"windows.{k}" for k in bad])
            lb = w.get("label")
            if not isinstance(lb, str) or not lb.strip() or len(lb.strip()) > QUOTA_LABEL_MAX or _BAD.search(lb):
                raise BadInput(tr("Invalid value: {0}", "windows.label"))
            if "percent" not in w:
                raise BadInput(tr("Missing field: {0}", "windows.percent"))
            if "main" in w and not isinstance(w["main"], bool):
                raise BadInput(tr("Invalid value: {0}", "windows.main"))
            if w.get("main"):
                if main is not None:
                    raise BadInput(tr("Only one window can be the main one"))
                main = i
            out.append({"key": "", "label": lb.strip(), "percent": _pct(w["percent"], "windows.percent"),
                        "resets_at": _when(w.get("resets_at"), "windows.resets_at")})
        if out and main is None:
            main = 0
    lim = b.get("limit")
    if lim is not None and (isinstance(lim, bool) or not isinstance(lim, (int, float)) or lim != lim or not 1 <= lim <= 100):
        raise BadInput(tr("Invalid value: {0}", "limit"))
    # measured_at: when the host read the values (e.g. a file a status line wrote earlier) -> the ring greys out by THAT age
    ma = _when(b.get("measured_at"), "measured_at")
    return {"windows": out, "main": main, "limit": None if lim is None else round(float(lim), 1), "measured_at": ma}


def quota_raw(a):
    try:
        d = json.loads(a["quota"] or "null") if a is not None and "quota" in a.keys() else None
    except (ValueError, TypeError):
        d = None
    return d if isinstance(d, dict) and d.get("windows") else None


def quota_public(a, now=None):
    """What people see (agent_public "quota"): None = no report (no ring). Windows with a passed reset count as 0 %."""
    d = quota_raw(a)
    if not d:
        return None
    now = now or now_utc()
    ws = []
    for w in d["windows"]:
        r = w.get("resets_at")
        past = bool(r) and parse_iso(r) <= now
        ws.append({"key": w.get("key") or "", "label": w.get("label") or "", "percent": 0.0 if past else w.get("percent", 0.0),
                   "resets_at": None if past else r, "reset_passed": past})
    main = d.get("main") or 0
    main = main if 0 <= main < len(ws) else 0
    lim = d.get("limit")
    at = d.get("at")
    stale = not at or (now - parse_iso(at)) > timedelta(hours=QUOTA_STALE_H)
    over = ws[main]["percent"] >= (lim if lim is not None else 100)
    level = "over" if over else "warn" if ws[main]["percent"] >= QUOTA_WARN else "ok"
    return {"windows": ws, "main": main, "limit": lim, "at": at, "stale": stale, "level": level,
            "percent": ws[main]["percent"], "paused_until": ws[main]["resets_at"] if over else None}


def _visible(d):
    if not d:
        return None
    return json.dumps({"w": [(w["key"], w["label"], round(w["percent"]), w["resets_at"]) for w in d["windows"]],
                       "m": d["main"], "l": d["limit"]}, sort_keys=True)


@app.put("/api/v1/agent/quota")
@v1_view
def v1_agent_quota_put():
    """{windows: [{label, percent, resets_at?, main?}] | rate_limits: {five_hour, seven_day, spend_limit} (Claude Code's status
    line), limit?, measured_at?} -- the agent's plan usage, shown as the ring in its chat header. Replaces the last report; no windows = remove."""
    v1_args(())
    aid = need_agent()
    q = quota_in(v1_json())
    c = db()
    old = agent_row(c, aid)
    od = quota_raw(old)
    ma = q.pop("measured_at", None)
    nd = {**q, "at": min(ma, iso(now_utc())) if ma else iso(now_utc())} if q["windows"] else None
    c.execute("UPDATE agents SET quota=? WHERE user_id=?", (json.dumps(nd, ensure_ascii=False) if nd else "", aid))
    # clients reload only when something visible changed or the old report had gone grey (hosts may report after every run)
    if _visible(od) != _visible(nd) or (od and (now_utc() - parse_iso(od.get("at") or iso(now_utc()))) > timedelta(hours=QUOTA_STALE_H - 1)):
        bump(c)
    c.commit()
    return jsonify(quota=quota_public(agent_row(c, aid)))


@app.get("/api/v1/agent/quota")
@v1_view
def v1_agent_quota_get():
    """The agent's own last plan usage report as people see it (null = none)."""
    v1_args(())
    aid = need_agent()
    return jsonify(quota=quota_public(agent_row(db(), aid)))


@app.delete("/api/v1/agent/quota")
@v1_view
def v1_agent_quota_delete():
    """Removes the report: the ring disappears."""
    v1_args(())
    aid = need_agent()
    c = db()
    if quota_raw(agent_row(c, aid)):
        c.execute("UPDATE agents SET quota='' WHERE user_id=?", (aid,))
        bump(c)
        c.commit()
    return jsonify(quota=None)
