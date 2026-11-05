"""Events as iCalendar (VEVENT): rendering for CalDAV + export, reading what clients send, importing an ICS file."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone

import icalendar
from flask import jsonify, request

from ..core.config import app, APP_NAME, APP_VERSION, TZ
from ..core.i18n import tr
from ..core.db import bump, db, err, now_utc, parse_iso
from ..accounts.session import me
from ..core.access import collab_all, need_feat
from ..core.pages import valid_url
from ..tasks.validation import REM_COUNT, REM_MAX, REM_MIN, rr_feasible, rr_norm, rr_problem, valid_date
from ..calendars.icalfeed import ics_dur, ics_fold, ics_text, ics_utc, ics_vtimezone
from ..core.errors import BadInput
from ..core.dlock import dl_of, dl_tasks_locked  # 2.560.0 (#4699)
from ..events.model import (
    _span, att_rows, ev_att_ok, ev_store, ev_zone, is_occ, one_line, rule_local, EV_DESC_MAX, EV_LOC_MAX, EV_TITLE_MAX, need_evcal, ov_list, tz_ok, wall, wall_s,
)
from ..accounts.orgs import may_see  # 2.369.5 (#2517): pulled up from functions

OV_KEYS = ("title", "location", "description", "all_day", "start", "end", "status", "delete")
# properties of a VEVENT that map to event fields (everything else is kept as it came and sent back)
EV_MAPPED = {"UID", "DTSTAMP", "CREATED", "LAST-MODIFIED", "SEQUENCE", "SUMMARY", "LOCATION", "DESCRIPTION", "DTSTART", "DTEND",
             "DURATION", "RRULE", "EXDATE", "STATUS", "TRANSP", "URL", "ATTENDEE", "ORGANIZER", "RECURRENCE-ID",
             "X-KALMIDO-GUESTS-VISIBLE"}  # 2.380 H (#3392)
EV_SINGLE = {"UID", "DTSTAMP", "CREATED", "LAST-MODIFIED", "SEQUENCE", "SUMMARY", "LOCATION", "DESCRIPTION", "DTSTART", "DTEND",
             "DURATION", "STATUS", "TRANSP", "URL", "RRULE", "ORGANIZER", "RECURRENCE-ID"}
EXTRA_MAX = 16000
IMPORT_MAX_BYTES = 10 * 1024 * 1024
IMPORT_MAX_EVENTS = 5000
_VTZ = {}
PS_ICS = {"needs-action": "NEEDS-ACTION", "accepted": "ACCEPTED", "declined": "DECLINED", "tentative": "TENTATIVE"}
PS_IN = {v: k for k, v in PS_ICS.items()}


class EvError(Exception):
    """Calendar data that cannot be stored: status, text, CalDAV precondition."""
    def __init__(self, code, text, cond=None):
        super().__init__(text)
        self.code, self.text, self.cond = code, text, cond


def vtz(name, year):
    k = (name, year)
    if k not in _VTZ:
        _VTZ[k] = ics_vtimezone(ev_zone(name), year)
    return _VTZ[k]


def _prop_name(line):
    return re.split(r"[;:]", line, maxsplit=1)[0].strip().upper()


def _params(line):
    head = line.split(":", 1)[0]
    out = {}
    for p in head.split(";")[1:]:
        k, _, v = p.partition("=")
        out[k.strip().upper()] = v.strip().strip('"')
    return out


def _dt_line(name, key, all_day, tzname):
    """DTSTART / DTEND / RECURRENCE-ID / EXDATE line of a key (date or local wall time of the event's zone)."""
    if all_day:
        return f"{name};VALUE=DATE:{key[:10].replace('-', '')}"
    w = wall(key) or datetime.fromisoformat(key[:10])
    return f"{name};TZID={tzname}:{w:%Y%m%dT%H%M%S}"


def cal_addr(c, uid):
    r = c.execute("SELECT email, display_name, username FROM users WHERE id=?", (uid,)).fetchone()
    if not r:
        return None, ""
    return f"urn:kalmido:user:{uid}", (r["display_name"] or r["username"])  # never the account's e-mail (private)


def ev_lines(c, r, atts=None):
    """The VEVENT lines of an event (the series + its changed occurrences), unfolded, and the time zones they use."""
    tzname = r["tz"] or getattr(TZ, "key", "UTC")
    ad = bool(r["all_day"])
    stamp = ics_utc(parse_iso(r["updated_at"]))
    atts = atts if atts is not None else att_rows(c, [r["id"]]).get(r["id"], [])
    L = ["BEGIN:VEVENT", f"UID:{ics_text(r['uid'])}", f"DTSTAMP:{stamp}", f"CREATED:{ics_utc(parse_iso(r['created_at']))}",
         f"LAST-MODIFIED:{stamp}", f"SEQUENCE:{r['seq'] or 0}", f"SUMMARY:{ics_text(r['title'])}",
         _dt_line("DTSTART", r["start"], ad, tzname), _dt_line("DTEND", r["end"], ad, tzname)]
    if r["location"]:
        L.append(f"LOCATION:{ics_text(r['location'])}")
    if r["description"]:
        L.append(f"DESCRIPTION:{ics_text(r['description'])}")
    own_rule = bool(r["rrule"])
    if own_rule:
        L.append("RRULE:" + rule_out(r["rrule"], ad, ev_zone(r["tz"])))
        for x in [x for x in (r["exdates"] or "").split(",") if x]:
            L.append(_dt_line("EXDATE", x, ad, tzname))
    L.append(f"STATUS:{r['status'].upper()}")
    L.append("TRANSP:" + ("OPAQUE" if r["busy"] else "TRANSPARENT"))
    if r["url"]:
        L.append(f"URL:{r['url']}")
    if r["guests_visible"]:  # 2.380 H (#3392): only when on (an event without it keeps its ETag)
        L.append("X-KALMIDO-GUESTS-VISIBLE:TRUE")
    extra = (r["extra"] or "").split("\n") if r["extra"] else []
    if atts:
        if not any(_prop_name(x) == "ORGANIZER" for x in extra):
            addr, name = cal_addr(c, r["created_by"]) if r["created_by"] else (None, "")
            if addr:
                L.append(f"ORGANIZER;CN={_pq(name)}:{addr}")
        L += _att_lines(atts)
    for off in [x for x in (r["reminders"] or "").split(",") if x.strip()]:
        L += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_text(r['title'])}", f"TRIGGER:{ics_dur(-int(off))}", "END:VALARM"]
    L += _extra_merge(L, extra, own_rule)
    L.append("END:VEVENT")
    tzs = {tzname} if not ad else set()
    # 2.383.0 (#2587): answers to single dates. Only when someone answered one: the changed occurrences then carry the
    # attendees with their answer for that date, and an answered date that is no changed occurrence gets its own VEVENT
    # (RECURRENCE-ID, times of the series), so the phone keeps showing it. Without such answers nothing changes (same ETag).
    occ_rids = sorted({k for a in atts for k in (a.get("occ_partstat") or {})}) if atts and r["rrule"] else []
    ovs = [o for o in ov_list(r) if isinstance(o, dict) and o.get("rid")]
    if occ_rids:
        have = {o["rid"] for o in ovs}
        ex = set(x for x in (r["exdates"] or "").split(",") if x)
        for k in occ_rids:
            if k in have or k in ex or not is_occ(r, k):
                continue
            e_ = _span(r, k)[1]
            ovs.append({"rid": k, "start": k, "end": e_.isoformat() if ad else wall_s(e_.replace(tzinfo=None)), "_answer": True})
    org_line = [x for x in L if _prop_name(x) == "ORGANIZER"][:1]
    for o in ovs:
        oad = bool(o.get("all_day", ad))
        X = ["BEGIN:VEVENT", f"UID:{ics_text(r['uid'])}", f"DTSTAMP:{stamp}", _dt_line("RECURRENCE-ID", o["rid"], ad, tzname),
             f"SEQUENCE:{r['seq'] or 0}", f"SUMMARY:{ics_text(o.get('title') or r['title'])}",
             _dt_line("DTSTART", o.get("start") or o["rid"], oad, tzname), _dt_line("DTEND", o.get("end") or o.get("start") or o["rid"], oad, tzname)]
        if o.get("location", r["location"]):
            X.append(f"LOCATION:{ics_text(o.get('location', r['location']))}")
        if o.get("description", r["description"]):
            X.append(f"DESCRIPTION:{ics_text(o.get('description', r['description']))}")
        X.append(f"STATUS:{(o.get('status') or r['status']).upper()}")
        if o.get("_answer"):  # 2.383.0 (#2587): a date that only has its own answer: busy / transparent like the series
            X.append("TRANSP:" + ("OPAQUE" if r["busy"] else "TRANSPARENT"))
        if occ_rids:
            X += org_line + _att_lines(atts, o["rid"])
        oex = (o.get("extra") or "").split("\n") if o.get("extra") else []
        X += _extra_merge(X, oex, False)
        X.append("END:VEVENT")
        L += X
        if not oad:
            tzs.add(tzname)
    return L, tzs


def _att_lines(atts, rid=None):
    """The ATTENDEE lines of an event's attendees; rid = for this date of a series (its own answer where one was given,
    2.383.0 #2587)."""
    out = []
    for a in atts:
        addr = f"urn:kalmido:user:{a['user_id']}" if a["user_id"] else (f"mailto:{a['email']}" if a["email"] else None)
        if not addr:
            continue
        ps = (a.get("occ_partstat") or {}).get(rid, a["partstat"]) if rid else a["partstat"]
        p = [f"CN={_pq(a['name'])}"] if a["name"] else []
        p += [f"PARTSTAT={PS_ICS.get(ps, 'NEEDS-ACTION')}", "ROLE=" + ("OPT-PARTICIPANT" if a["role"] == "opt" else "REQ-PARTICIPANT")]
        if a["user_id"]:
            p.append(f"X-KALMIDO-USER={a['user_id']}")
        out.append(f"ATTENDEE;{';'.join(p)}:{addr}")
    return out


def _pq(s):
    s = re.sub(r'[\x00-\x1f\x7f"]', " ", str(s or ""))
    return f'"{s}"' if re.search(r"[;:,]", s) else s


def _extra_merge(have_lines, extra, own_rule):
    have, out, depth = {_prop_name(x) for x in have_lines if not x.startswith(("BEGIN:", "END:"))}, [], 0
    for x in extra:
        if not x:
            continue
        up = x[:6].upper()
        if depth == 0 and up != "BEGIN:":
            n = _prop_name(x)
            if (n in EV_SINGLE and n in have) or (own_rule and n == "EXDATE"):  # 2.126.0 C (#1985): RDATE / EXRULE stay
                continue
        depth += 1 if up == "BEGIN:" else -1 if x[:4].upper() == "END:" else 0
        out.append(x)
    return out


def rule_out(rule, all_day, zone):
    """UNTIL as iCalendar wants it next to DTSTART: a date (all day) or a UTC date-time (timed)."""
    parts = []
    for p in rule.split(";"):
        k, _, v = p.partition("=")
        if k == "UNTIL":
            if all_day:
                v = v[:8]
            elif len(v) == 8:
                v = ics_utc(datetime(int(v[:4]), int(v[4:6]), int(v[6:8]), 23, 59, 59, tzinfo=zone))
            elif not v.endswith("Z"):
                try:
                    v = ics_utc(datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone))
                except ValueError:
                    pass
        parts.append(f"{k}={v}")
    return ";".join(parts)


def wrap(lines, tzs, year=None):
    y = year or now_utc().year
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{APP_NAME}//CalDAV {APP_VERSION}//EN", "CALSCALE:GREGORIAN"]
    for t in sorted(tzs):
        out += vtz(t, y)
    out += lines + ["END:VCALENDAR"]
    return "\r\n".join(ics_fold(x) for x in out) + "\r\n"


def etag(lines, tzs):
    return '"' + hashlib.sha1(("\n".join(lines) + "|" + ",".join(sorted(tzs))).encode("utf-8"), usedforsecurity=False).hexdigest()[:24] + '"'


# ---- reading
from ..calendars.icalfeed import ics_unfold as _unfold  # noqa: E402  2.149.0 G (#2517): was an own copy


def split_events(text):
    """Raw lines of every VEVENT (top level lines, VALARM blocks, other blocks) in order + the kinds of components."""
    evs, kinds, depth, cur, sub = [], set(), 0, None, None
    for line in _unfold(text):
        if not line.strip():
            continue
        up = line.upper()
        if up.startswith("BEGIN:"):
            depth += 1
            comp = up[6:].strip()
            if depth == 2:
                kinds.add(comp)
                if comp == "VEVENT":
                    cur = {"lines": [], "alarms": [], "blocks": []}
                continue
            if cur is not None:
                if depth == 3:
                    sub = [line]
                    (cur["alarms"] if comp == "VALARM" else cur["blocks"]).append(sub)
                elif sub is not None:
                    sub.append(line)
            continue
        if up.startswith("END:"):
            if depth == 2 and cur is not None:
                evs.append(cur)
                cur = None
            elif depth >= 3 and sub is not None:
                sub.append(line)
                if depth == 3:
                    sub = None
            depth = max(0, depth - 1)
            continue
        if cur is not None:
            if depth == 2:
                cur["lines"].append(line)
            elif sub is not None:
                sub.append(line)
    return evs, kinds


def _val(prop):
    if prop is None:
        return None
    try:
        return prop.dt if hasattr(prop, "dt") else prop
    except (AttributeError, ValueError):
        return None


def _zone_of(prop, raw_tzid):
    """(IANA name or '', aware datetime / date / naive) for a DTSTART-like property."""
    v = _val(prop)
    if isinstance(v, datetime) and v.tzinfo is not None:
        key = getattr(v.tzinfo, "key", None) or (raw_tzid if raw_tzid and tz_ok(raw_tzid) else None)
        return key or "", v
    return "", v


def _key(v, zone, all_day):
    """A date / datetime -> the stored key in the event's zone ('YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM')."""
    if all_day:
        return (v.date() if isinstance(v, datetime) else v).isoformat()
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return wall_s(v)
        return wall_s(v.astimezone(zone))
    return f"{v.isoformat()}T00:00"


def read_vevent(text, uid_hint=None):
    """Calendar data with ONE event (series + changed occurrences, all with one UID) -> the event's columns and attendees.
    EvError when it cannot be stored."""
    if "BEGIN:VCALENDAR" not in text[:4000].upper():
        raise EvError(415, "Expected text/calendar", "<C:supported-calendar-data/>")
    raws, kinds = split_events(text)
    if kinds - {"VEVENT", "VTIMEZONE"}:
        raise EvError(403, "Only events (VEVENT) in this calendar", "<C:supported-calendar-component/>")
    try:
        cal = icalendar.Calendar.from_ical(text)
        comps = list(cal.walk("VEVENT"))
    except Exception:  # noqa: BLE001  (icalendar raises many kinds of errors on bad input)
        raise EvError(400, "The calendar data could not be read", "<C:valid-calendar-data/>") from None
    if not comps or len(comps) != len(raws):
        raise EvError(400, "No event in the calendar data", "<C:valid-calendar-data/>")
    uids = {str(x.get("UID") or "").strip()[:250] for x in comps}
    if len(uids) != 1 or not next(iter(uids)):
        raise EvError(400, "One UID per resource", "<C:valid-calendar-object-resource/>")
    masters = [i for i, x in enumerate(comps) if x.get("RECURRENCE-ID") is None]
    if len(masters) > 1:
        raise EvError(400, "Exactly one event per resource", "<C:valid-calendar-object-resource/>")
    return _read_group(comps, raws, masters[0] if masters else None)


def _att_in(line):
    """One ATTENDEE line of a client -> {addr, name, partstat (app value), role, kuser}."""
    p = _params(line)
    val = line.split(":", 1)[1] if ":" in line else ""
    return {"addr": val.strip(), "name": p.get("CN", "")[:200], "partstat": PS_IN.get(p.get("PARTSTAT", "").upper(), "needs-action"),
            "role": "opt" if p.get("ROLE", "").upper() == "OPT-PARTICIPANT" else "req", "kuser": p.get("X-KALMIDO-USER")}


def _read_group(comps, raws, mi):
    """One series: master index mi (None = only changed occurrences arrived: the first one stands for the series)."""
    first = comps[mi if mi is not None else 0]
    rw = raws[mi if mi is not None else 0]
    uid_ = str(first.get("UID") or "").strip()[:250]
    tzid = _params(next((x for x in rw["lines"] if _prop_name(x) == "DTSTART"), "DTSTART:")).get("TZID")
    tzname, st = _zone_of(first.get("DTSTART"), tzid)
    if st is None:
        raise EvError(400, "DTSTART missing", "<C:valid-calendar-object-resource/>")
    all_day = not isinstance(st, datetime)
    zone = ev_zone(tzname)
    if not all_day and st.tzinfo is not None and not tzname:  # UTC or an unknown zone: the server's wall time
        st = st.astimezone(TZ)
    en = _val(first.get("DTEND"))
    if en is None and first.get("DURATION") is not None:
        d = _val(first.get("DURATION"))
        en = st + d if isinstance(d, timedelta) else None
    # 2.360.0 D (#2496): the title is one line (as in the app; a line break would break the subject of an invitation mail)
    v = {"uid": uid_, "title": (one_line(first.get("SUMMARY") or "") or tr("(no title)"))[:EV_TITLE_MAX],
         "location": one_line(first.get("LOCATION") or "")[:EV_LOC_MAX],
         "description": str(first.get("DESCRIPTION") or "")[:EV_DESC_MAX], "all_day": 1 if all_day else 0, "tz": tzname if tz_ok(tzname) else ""}
    if v["tz"] == getattr(TZ, "key", ""):
        v["tz"] = ""
    zone = ev_zone(v["tz"])
    v["start"] = _key(st, zone, all_day)
    if all_day:
        e = en.date() if isinstance(en, datetime) else en if isinstance(en, date) else None
        if not e or e <= st:
            e = st + timedelta(days=1)
        v["end"] = e.isoformat()
    else:
        e = en if isinstance(en, datetime) else st
        if e.tzinfo is None and st.tzinfo is not None:
            e = e.replace(tzinfo=st.tzinfo)
        if st.tzinfo is None and e.tzinfo is not None:
            e = e.astimezone(zone).replace(tzinfo=None)
        if e < st:
            e = st
        v["end"] = _key(e, zone, False)
    if not valid_date(v["start"][:10]) or not valid_date(v["end"][:10]):
        raise EvError(400, "Date out of range", "<C:valid-calendar-object-resource/>")
    stt = str(first.get("STATUS") or "").strip().upper()
    v["status"] = {"TENTATIVE": "tentative", "CANCELLED": "cancelled"}.get(stt, "confirmed")
    v["busy"] = 0 if str(first.get("TRANSP") or "").strip().upper() == "TRANSPARENT" else 1
    keep, v["rrule"], v["url"], ex, atts = [], "", None, [], []
    for line in rw["lines"]:
        name = _prop_name(line)
        val = line.split(":", 1)[1] if ":" in line else ""
        if name == "RRULE" and mi is not None:
            rule = rule_local(rr_norm(val), zone, all_day)
            parts = [p for p in rule.split(";") if not p.startswith("WKST=MO")]
            rule = ";".join(parts)
            if not v["rrule"] and rule and not rr_problem(rule) and rr_feasible(rule, v["start"][:10]):
                v["rrule"] = rule
            else:
                keep.append(line)
        elif name == "EXDATE":
            p = _params(line)
            for x in val.split(","):
                x = x.strip()
                try:
                    if p.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", x):
                        ex.append(date(int(x[:4]), int(x[4:6]), int(x[6:8])).isoformat() if all_day else f"{x[:4]}-{x[4:6]}-{x[6:8]}T{v['start'][11:]}")
                    else:
                        dt = datetime.strptime(x[:15], "%Y%m%dT%H%M%S")
                        if x.endswith("Z"):
                            dt = dt.replace(tzinfo=timezone.utc)
                        elif p.get("TZID") and tz_ok(p["TZID"]):
                            dt = dt.replace(tzinfo=ev_zone(p["TZID"]))
                        ex.append(_key(dt, zone, all_day) if dt.tzinfo else (dt.date().isoformat() if all_day else wall_s(dt)))
                except ValueError:
                    continue
        elif name == "URL":
            u = val.strip()
            if not v["url"] and valid_url(u):
                v["url"] = u
            else:
                keep.append(line)
        elif name == "X-KALMIDO-GUESTS-VISIBLE":  # 2.380 H (#3392): a client without the line leaves the switch as it is
            v["guests_visible"] = val.strip().upper() in ("TRUE", "1", "YES")
        elif name == "ATTENDEE":
            atts.append(_att_in(line))
        elif name == "ORGANIZER":
            if not (val.lower().startswith("urn:kalmido:user:")):
                keep.append(line)  # an outside organiser stays; Kalmido's own one is written again
        elif name not in EV_MAPPED:
            keep.append(line)
    if mi is None:
        keep = [x for x in keep if _prop_name(x) != "RECURRENCE-ID"]
    v["exdates"] = ",".join(sorted(set(ex)))
    rems = []
    alarms = list(first.walk("VALARM"))
    for i, block in enumerate(rw["alarms"]):
        al = alarms[i] if i < len(alarms) else None
        trig = al.get("TRIGGER") if al is not None else None
        tv = _val(trig)
        off = None
        if isinstance(tv, timedelta) and str(trig.params.get("RELATED", "START")).upper() == "START":
            off = -int(tv.total_seconds() // 60)
        elif isinstance(tv, datetime) and not v["rrule"]:
            s0 = datetime.fromisoformat(v["start"] if not all_day else v["start"] + "T00:00").replace(tzinfo=zone)
            off = int((s0 - (tv if tv.tzinfo else tv.replace(tzinfo=zone))).total_seconds() // 60)
        if off is not None and REM_MIN <= off <= REM_MAX and len(rems) < REM_COUNT and off not in rems:
            rems.append(off)
        else:
            keep += block
    v["reminders"] = ",".join(str(x) for x in rems)
    for b in rw["blocks"]:
        keep += b
    v["extra"] = _cap("\n".join(x for x in keep if x))
    v["attendees_raw"] = atts
    # changed occurrences
    ovs, ov_mod, ov_atts = [], {}, {}
    for i, comp in enumerate(comps):
        if i == mi or comp.get("RECURRENCE-ID") is None:
            continue
        r2 = raws[i]
        rid_line = next((x for x in r2["lines"] if _prop_name(x) == "RECURRENCE-ID"), "")
        rtz = _params(rid_line).get("TZID")
        _, rid = _zone_of(comp.get("RECURRENCE-ID"), rtz)
        if rid is None:
            continue
        if not all_day and isinstance(rid, datetime) and rid.tzinfo is None:
            rid = rid.replace(tzinfo=zone)
        rkey = _key(rid, zone, all_day) if not (all_day and isinstance(rid, datetime)) else rid.date().isoformat()
        otz, ost = _zone_of(comp.get("DTSTART"), _params(next((x for x in r2["lines"] if _prop_name(x) == "DTSTART"), "DTSTART:")).get("TZID"))
        if ost is None:
            ost = rid
        oad = not isinstance(ost, datetime)
        oen = _val(comp.get("DTEND"))
        if oen is None and comp.get("DURATION") is not None:
            d = _val(comp.get("DURATION"))
            oen = ost + d if isinstance(d, timedelta) else None
        if oad:
            oe = oen.date() if isinstance(oen, datetime) else oen if isinstance(oen, date) else None
            oe = oe if oe and oe > ost else ost + timedelta(days=1)
            okeys = (ost.isoformat(), oe.isoformat())
        else:
            if ost.tzinfo is None:
                ost = ost.replace(tzinfo=zone)
            oe = oen if isinstance(oen, datetime) else ost
            if oe.tzinfo is None:
                oe = oe.replace(tzinfo=ost.tzinfo)
            okeys = (_key(ost, zone, False), _key(max(oe, ost), zone, False))
        ov_atts[rkey] = [_att_in(x) for x in r2["lines"] if _prop_name(x) == "ATTENDEE"]  # 2.383.0 (#2587): answers per date
        ov_mod[rkey] = _ics_mod(comp)  # 2.363.3 (#3133): a changed occurrence has its own LAST-MODIFIED (import_ics)
        ost_s = str(comp.get("STATUS") or "").strip().upper()
        okeep = [x for x in r2["lines"] if _prop_name(x) not in EV_MAPPED]
        for b in r2["alarms"] + r2["blocks"]:
            okeep += b
        ovs.append({"rid": rkey, "title": (one_line(comp.get("SUMMARY") or "") or v["title"])[:EV_TITLE_MAX],
                    "location": one_line(comp.get("LOCATION") or "")[:EV_LOC_MAX],
                    "description": str(comp.get("DESCRIPTION") or "")[:EV_DESC_MAX], "all_day": oad, "start": okeys[0], "end": okeys[1],
                    "status": {"TENTATIVE": "tentative", "CANCELLED": "cancelled"}.get(ost_s, "confirmed"), "extra": _cap("\n".join(okeep))})
    if mi is None:  # only occurrences arrived (an invitation to one date of a series): it is a single event
        v["rrule"] = ""
        ovs = []
    # 2.383.0 (#2587): a date that differs from the series in nothing (ev_lines writes one for an answer to that date) is no
    # changed occurrence: kept as one, a later change of the series would no longer reach it
    ovs = [o for o in ovs if not _ov_plain(v, o)]
    v["overrides"] = json.dumps(ovs[:500], ensure_ascii=False) if ovs else ""
    v["ov_mod"] = ov_mod if ovs else {}
    v["ov_atts"] = ov_atts if mi is not None else {}  # 2.383.0 (#2587): {occurrence key: ATTENDEE lines of that date}
    return v


def _ov_plain(v, o):
    """2.383.0 (#2587): True when override o of read values v is the series' own date unchanged (same texts, status, times)."""
    if o["extra"] or o["title"] != v["title"] or o["location"] != v["location"] or o["description"] != v["description"] \
            or o["status"] != v["status"] or bool(o["all_day"]) != bool(v["all_day"]) or o["start"] != o["rid"]:
        return False
    try:
        if v["all_day"]:
            d = date.fromisoformat(v["end"][:10]) - date.fromisoformat(v["start"][:10])
            return o["end"] == (date.fromisoformat(o["rid"][:10]) + d).isoformat()
        return o["end"] == wall_s(wall(o["rid"]) + (wall(v["end"]) - wall(v["start"])))
    except (TypeError, ValueError):
        return False


def _cap(s):
    if len(s) > EXTRA_MAX:
        s = s[:EXTRA_MAX].rsplit("\n", 1)[0]
    return s


def atts_resolve(c, uid, raw, eid=None, cal_id=None):
    """The ATTENDEE lines of a client -> attendee rows: a person of this server (by X-KALMIDO-USER / urn / e-mail),
    a contact the writer sees (by e-mail) or the address. A person only when the writer may see them (like att_clean,
    #476 H1): an ICS file or a CalDAV client never invites accounts of other organisations; already invited ones stay."""
    from ..contacts.model import contact_by_email
    from ..agents.admin import personal_agent_foreign
    had_u = {r[0] for r in c.execute("SELECT user_id FROM event_attendees WHERE event_id=? AND user_id IS NOT NULL",
                                     (eid,))} if eid else set()
    # 2.87.0 (#1983): in an organisation's calendar only its people (like att_clean); anyone else stays an address
    cal_org = (c.execute("SELECT org_id FROM ev_cals WHERE id=?", (cal_id,)).fetchone() or [None])[0] if cal_id else None
    out, seen = [], set()
    for a in raw[:100]:
        addr = a["addr"]
        row = {"user_id": None, "contact_id": None, "email": "", "name": a["name"], "partstat": a["partstat"], "role": a["role"]}
        m = re.fullmatch(r"(?i)urn:kalmido:user:(\d{1,9})", addr)
        ku = int(a["kuser"]) if a.get("kuser") and str(a["kuser"]).isdigit() else (int(m.group(1)) if m else None)
        em = addr[7:].strip() if addr.lower().startswith("mailto:") else ""
        if collab_all() and ku and c.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (ku,)).fetchone() \
                and (ku == uid or ku in had_u or (may_see(c, uid, ku) and not personal_agent_foreign(c, ku, uid))) \
                and (not cal_org or ev_att_ok(c, ku, cal_org)):
            row["user_id"] = ku  # by its Kalmido id only: an e-mail address never reveals or picks an account
            row["partstat"] = "needs-action"  # a person's reply is their own (att_set keeps it)
        if em and not row["user_id"] and c.execute("SELECT 1 FROM users WHERE id=? AND lower(email)=lower(?)", (uid, em)).fetchone():
            continue  # the writer's own address: the organiser
        if row["user_id"] == uid:
            if uid not in had_u:
                continue  # the writer is the organiser
            # 2.383.0 (#2587): the writer is invited (a calendar they may edit): their own answer from the device counts,
            # like op_rsvp; before, the line was dropped and the PUT took them off the event
            row["partstat"] = a["partstat"]
        if not row["user_id"]:
            if not em or not re.fullmatch(r"[^@\s<>\"]+@[^@\s<>\"]+", em):
                continue
            row["email"] = em[:200]
            k = contact_by_email(c, uid, em)
            if k:
                row["contact_id"] = k
        key = ("u", row["user_id"]) if row["user_id"] else ("e", row["email"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _parsed_cols(c, uid, v):
    """The event columns of read_vevent() values (store_parsed; 2.273.0 C #3048: the import compares them first)."""
    f = {k: v[k] for k in ("title", "location", "description", "all_day", "start", "end", "tz", "rrule", "exdates", "overrides",
                           "reminders", "status", "busy", "url", "extra")}
    if v.get("guests_visible") is not None:  # 2.380 H (#3392): only a file with the line changes the switch
        f["guests_visible"] = 1 if v["guests_visible"] else 0
    me_ = c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    if me_ and me_[0]:  # the writer's own address as organiser: Kalmido writes its own (no account e-mail reaches others)
        f["extra"] = "\n".join(x for x in f["extra"].split("\n")
                               if not (_prop_name(x) == "ORGANIZER" and x.split(":", 1)[-1].strip().lower() == "mailto:" + me_[0].lower()))
    return f


def store_parsed(c, uid, cal_id, v, eid=None, href=None, keep_attendees=False):
    """Stores read_vevent() values as a new event (eid None) or into an existing one. Returns the id. keep_attendees: the
    existing event's attendees stay as they are (2.144.5 B, #2379: a CalDAV client that never writes ATTENDEE)."""
    f = _parsed_cols(c, uid, v)
    atts = None if keep_attendees and eid else atts_resolve(c, uid, v["attendees_raw"], eid, cal_id)
    return ev_store(c, uid, cal_id, f, eid=eid, uid_=v["uid"], href=href, attendees=atts)


def _ics_mod(comp):
    """2.273.0 C (#3048): LAST-MODIFIED of a VEVENT as 'YYYY-MM-DDTHH:MM:SS' (UTC) or ''."""
    p = comp.get("LAST-MODIFIED")
    dt = getattr(p, "dt", None)
    if not dt or not hasattr(dt, "hour"):
        return ""
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _ics_differs(c, uid, cal_id, v, old):
    """2.273.0 C (#3048): the file's event differs from the stored one (columns; attendees only when the file has some)."""
    f = _parsed_cols(c, uid, v)
    if any(str(f[k] if f[k] is not None else "") != str(old[k] if old[k] is not None else "") for k in f):
        return True
    if not v.get("attendees_raw"):
        return False
    key = lambda a: ("u", a["user_id"]) if a.get("user_id") else ("e", str(a.get("email") or "").lower())  # noqa: E731
    have = {key(dict(a)) for a in c.execute("SELECT user_id, email FROM event_attendees WHERE event_id=?", (old["id"],)).fetchall()}
    return {key(a) for a in atts_resolve(c, uid, v["attendees_raw"], old["id"], cal_id)} != have


def _ics_ovs(raw):
    """2.363.3 (#3133): the changed occurrences of an event's overrides column: {rid: override}."""
    try:
        v = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return {}
    return {o["rid"]: o for o in v if isinstance(o, dict) and o.get("rid")} if isinstance(v, list) else {}


def _ics_ov_merge(old, v, here_newer, master_kept):
    """2.363.3 (#3133): an occurrence with its own LAST-MODIFIED decides for itself. master_kept (the series here stays): the
    file's occurrences changed after the change here go into the stored ones -> (overrides, how many came from the file). Else
    (the file's series wins): an occurrence changed here after the file's stays as it is here -> (overrides, 0). A file
    occurrence without its own date goes with the series, as before."""
    have, mine, mods = _ics_ovs(old["overrides"]), _ics_ovs(v.get("overrides")), v.get("ov_mod") or {}
    out, took = dict(have) if master_kept else dict(mine), 0
    for rid, o in mine.items():
        mod = mods.get(rid)
        if not mod or rid not in have and not master_kept or have.get(rid) == o:
            continue
        if master_kept and not here_newer(mod):
            out[rid] = o
            took += 1
        elif not master_kept and here_newer(mod):
            out[rid] = have[rid]
    return (json.dumps(list(out.values())[:500], ensure_ascii=False) if out else ""), took


# ---- ICS import (a file, e.g. an export of another calendar) into one calendar
def import_ics(c, uid, cal_id, raw, dry=False):
    """-> {created, updated, skipped, errors}. The same UID in that calendar is updated (importing twice changes nothing).
    2.273.0 C (#3048): an event changed here after the file's LAST-MODIFIED stays as it is (counted in kept_newer, only when
    there is one); a file event without attendees leaves the stored attendees."""
    if len(raw) > IMPORT_MAX_BYTES:
        raise BadInput(tr("The file is too large (at most {0} MB)", IMPORT_MAX_BYTES // (1024 * 1024)))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if "BEGIN:VCALENDAR" not in text[:4000].upper():
        raise BadInput(tr("This is not a calendar file (ICS)"))
    # 2.363.2 (#3106): the messages tell the causes apart (cut off, a broken line, broken event blocks, nothing to import)
    if not re.search("END:VCALENDAR", text, re.I):
        raise BadInput(tr("The calendar file is incomplete, its end is missing"))
    raws, _ = split_events(text)
    try:
        cals = icalendar.Calendar.from_ical(text, multiple=True)
    except Exception:  # noqa: BLE001
        raise BadInput(tr("The calendar file contains a line that cannot be read")) from None
    comps = [x for cal in cals for x in cal.walk("VEVENT")]
    if len(comps) != len(raws):
        raise BadInput(tr("An event in the calendar file is not closed properly"))
    if not comps:
        raise BadInput(tr("The calendar file contains no events"))
    groups = {}
    for i, comp in enumerate(comps):
        groups.setdefault(str(comp.get("UID") or f"noid-{i}").strip()[:250], []).append(i)
    res = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}
    for n, (u_, idx) in enumerate(groups.items()):
        if n >= IMPORT_MAX_EVENTS:
            res["skipped"] += len(groups) - n
            break
        cs, rs = [comps[i] for i in idx], [raws[i] for i in idx]
        ms = [j for j, x in enumerate(cs) if x.get("RECURRENCE-ID") is None]
        try:
            if u_.startswith("noid-"):
                cs[0]["UID"] = icalendar.vText(f"import-{hashlib.sha1(str(cs[0].to_ical()).encode(), usedforsecurity=False).hexdigest()[:20]}")
            v = _read_group(cs, rs, ms[0] if len(ms) == 1 else None)
            if u_.startswith("noid-"):
                v["uid"] = str(cs[0]["UID"])
        except (EvError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            res["errors"] += 1
            continue
        old = c.execute("SELECT * FROM events WHERE cal_id=? AND uid=? AND deleted_at IS NULL", (cal_id, v["uid"])).fetchone()
        if old:
            lm = _ics_mod(cs[ms[0]] if len(ms) == 1 else cs[0])
            upd = str(old["updated_at"] or "")  # 2.273.0 F2 (#3048): the own last import write is no change here (imp_at / imp_rev)

            def here_newer(x, upd=upd, old=old):
                return x < upd[:19] if old["imp_at"] is None else \
                    bool(old["imp_rev"] and x < old["imp_rev"]) or (upd > old["imp_at"] and x < upd[:19])
            if lm and here_newer(lm) and _ics_differs(c, uid, cal_id, v, old):
                ovs, took = _ics_ov_merge(old, v, here_newer, True)  # 2.363.3 (#3133): a newer occurrence of the file still comes in
                if not took:
                    res["kept_newer"] = res.get("kept_newer", 0) + 1
                    continue
                if not dry:  # the series stays, so do the import marks: what was changed here still counts as changed here
                    f = {k: old[k] for k in _parsed_cols(c, uid, v)}
                    ev_store(c, uid, cal_id, {**f, "overrides": ovs}, eid=old["id"], uid_=old["uid"])
                res["updated"] += 1
                continue
            v["overrides"] = _ics_ov_merge(old, v, here_newer, False)[0]
        if dry:
            res["updated" if old else "created"] += 1
            continue
        eid = store_parsed(c, uid, cal_id, v, eid=old["id"] if old else None, keep_attendees=not v.get("attendees_raw"))
        c.execute("UPDATE events SET imp_at=updated_at, imp_rev=? WHERE id=?",
                  (_ics_mod(cs[ms[0]] if len(ms) == 1 else cs[0]), eid))  # 2.273.0 F2 (#3048): the import marker
        res["updated" if old else "created"] += 1
    return res


@app.post("/api/evcals/<int:cid>/import")
def evcal_import(cid):
    """multipart file=<.ics> (or a raw text/calendar body); ?dry=1 only counts."""
    need_feat("events")
    c = db()
    need_evcal(c, cid, write=True)
    f = request.files.get("file")
    raw = f.read(IMPORT_MAX_BYTES + 1) if f else request.get_data(cache=False)[:IMPORT_MAX_BYTES + 1]
    if not raw:
        return err(tr("No file"))
    try:
        res = import_ics(c, me(), cid, raw, dry=request.args.get("dry") == "1")
    except BadInput as e:
        return err(str(e))
    bump(c)
    c.commit()
    return jsonify(res)


def ev_dl_drop(c, uid, rows):
    """2.560.0 (#4699, Fable review F1/F2): rows without the events whose task agent uid's data lock covers (like ev_range),
    one query; people keep every row."""
    if not uid or not dl_of(c, uid):
        return rows
    gone = dl_tasks_locked(c, uid, [r["task_id"] for r in rows if r["task_id"]])
    return [r for r in rows if not (r["task_id"] and int(r["task_id"]) in gone)] if gone else rows


def ics_export(c, cal_id, uid=None):
    rows = c.execute("SELECT * FROM events WHERE cal_id=? AND deleted_at IS NULL ORDER BY id", (cal_id,)).fetchall()
    rows = ev_dl_drop(c, uid, rows)  # 2.560.0 (#4699): an agent's export leaves the events of its locked tasks out
    atts = att_rows(c, [r["id"] for r in rows])
    lines, tzs = [], set()
    for r in rows:
        L, t = ev_lines(c, r, atts.get(r["id"], []))
        lines += L
        tzs |= t
    return wrap(lines, tzs)


