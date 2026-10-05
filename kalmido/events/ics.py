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
from ..personal.timetrack import BadInput
from ..events.model import (
    att_rows, ev_store, ev_zone, one_line, rule_local, EV_DESC_MAX, EV_LOC_MAX, EV_TITLE_MAX, need_evcal, ov_list, tz_ok, wall, wall_s,
)

OV_KEYS = ("title", "location", "description", "all_day", "start", "end", "status", "delete")
# properties of a VEVENT that map to event fields (everything else is kept as it came and sent back)
EV_MAPPED = {"UID", "DTSTAMP", "CREATED", "LAST-MODIFIED", "SEQUENCE", "SUMMARY", "LOCATION", "DESCRIPTION", "DTSTART", "DTEND",
             "DURATION", "RRULE", "EXDATE", "STATUS", "TRANSP", "URL", "ATTENDEE", "ORGANIZER", "RECURRENCE-ID"}
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
    extra = (r["extra"] or "").split("\n") if r["extra"] else []
    if atts:
        if not any(_prop_name(x) == "ORGANIZER" for x in extra):
            addr, name = cal_addr(c, r["created_by"]) if r["created_by"] else (None, "")
            if addr:
                L.append(f"ORGANIZER;CN={_pq(name)}:{addr}")
        for a in atts:
            addr = f"urn:kalmido:user:{a['user_id']}" if a["user_id"] else (f"mailto:{a['email']}" if a["email"] else None)
            if not addr:
                continue
            p = [f"CN={_pq(a['name'])}"] if a["name"] else []
            p += [f"PARTSTAT={PS_ICS.get(a['partstat'], 'NEEDS-ACTION')}", "ROLE=" + ("OPT-PARTICIPANT" if a["role"] == "opt" else "REQ-PARTICIPANT")]
            if a["user_id"]:
                p.append(f"X-KALMIDO-USER={a['user_id']}")
            L.append(f"ATTENDEE;{';'.join(p)}:{addr}")
    for off in [x for x in (r["reminders"] or "").split(",") if x.strip()]:
        L += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_text(r['title'])}", f"TRIGGER:{ics_dur(-int(off))}", "END:VALARM"]
    L += _extra_merge(L, extra, own_rule)
    L.append("END:VEVENT")
    tzs = {tzname} if not ad else set()
    for o in ov_list(r):
        if not isinstance(o, dict) or not o.get("rid"):
            continue
        oad = bool(o.get("all_day", ad))
        X = ["BEGIN:VEVENT", f"UID:{ics_text(r['uid'])}", f"DTSTAMP:{stamp}", _dt_line("RECURRENCE-ID", o["rid"], ad, tzname),
             f"SEQUENCE:{r['seq'] or 0}", f"SUMMARY:{ics_text(o.get('title') or r['title'])}",
             _dt_line("DTSTART", o.get("start") or o["rid"], oad, tzname), _dt_line("DTEND", o.get("end") or o.get("start") or o["rid"], oad, tzname)]
        if o.get("location", r["location"]):
            X.append(f"LOCATION:{ics_text(o.get('location', r['location']))}")
        if o.get("description", r["description"]):
            X.append(f"DESCRIPTION:{ics_text(o.get('description', r['description']))}")
        X.append(f"STATUS:{(o.get('status') or r['status']).upper()}")
        oex = (o.get("extra") or "").split("\n") if o.get("extra") else []
        X += _extra_merge(X, oex, False)
        X.append("END:VEVENT")
        L += X
        if not oad:
            tzs.add(tzname)
    return L, tzs


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
            if (n in EV_SINGLE and n in have) or (own_rule and n in ("EXRULE", "RDATE", "EXDATE")):
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
def _unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")).split("\r\n")


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
    v = {"uid": uid_, "title": (str(first.get("SUMMARY") or "").strip() or tr("(no title)"))[:EV_TITLE_MAX],
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
        elif name == "ATTENDEE":
            p = _params(line)
            addr = val.strip()
            a = {"addr": addr, "name": p.get("CN", "")[:200], "partstat": PS_IN.get(p.get("PARTSTAT", "").upper(), "needs-action"),
                 "role": "opt" if p.get("ROLE", "").upper() == "OPT-PARTICIPANT" else "req", "kuser": p.get("X-KALMIDO-USER")}
            atts.append(a)
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
    ovs = []
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
        ost_s = str(comp.get("STATUS") or "").strip().upper()
        okeep = [x for x in r2["lines"] if _prop_name(x) not in EV_MAPPED]
        for b in r2["alarms"] + r2["blocks"]:
            okeep += b
        ovs.append({"rid": rkey, "title": (str(comp.get("SUMMARY") or "").strip() or v["title"])[:EV_TITLE_MAX],
                    "location": one_line(comp.get("LOCATION") or "")[:EV_LOC_MAX],
                    "description": str(comp.get("DESCRIPTION") or "")[:EV_DESC_MAX], "all_day": oad, "start": okeys[0], "end": okeys[1],
                    "status": {"TENTATIVE": "tentative", "CANCELLED": "cancelled"}.get(ost_s, "confirmed"), "extra": _cap("\n".join(okeep))})
    if mi is None:  # only occurrences arrived (an invitation to one date of a series): it is a single event
        v["rrule"] = ""
        ovs = []
    v["overrides"] = json.dumps(ovs[:500], ensure_ascii=False) if ovs else ""
    return v


def _cap(s):
    if len(s) > EXTRA_MAX:
        s = s[:EXTRA_MAX].rsplit("\n", 1)[0]
    return s


def atts_resolve(c, uid, raw):
    """The ATTENDEE lines of a client -> attendee rows: a person of this server (by X-KALMIDO-USER / urn / e-mail),
    a contact the writer sees (by e-mail) or the address."""
    from ..contacts.model import contact_by_email
    out, seen = [], set()
    for a in raw[:100]:
        addr = a["addr"]
        row = {"user_id": None, "contact_id": None, "email": "", "name": a["name"], "partstat": a["partstat"], "role": a["role"]}
        m = re.fullmatch(r"(?i)urn:kalmido:user:(\d{1,9})", addr)
        ku = int(a["kuser"]) if a.get("kuser") and str(a["kuser"]).isdigit() else (int(m.group(1)) if m else None)
        em = addr[7:].strip() if addr.lower().startswith("mailto:") else ""
        if collab_all() and ku and c.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (ku,)).fetchone():
            row["user_id"] = ku  # by its Kalmido id only: an e-mail address never reveals or picks an account
            row["partstat"] = "needs-action"  # a person's reply is their own (att_set keeps it)
        if em and not row["user_id"] and c.execute("SELECT 1 FROM users WHERE id=? AND lower(email)=lower(?)", (uid, em)).fetchone():
            continue  # the writer's own address: the organiser
        if row["user_id"] == uid:
            continue  # the writer is the organiser
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


def store_parsed(c, uid, cal_id, v, eid=None, href=None):
    """Stores read_vevent() values as a new event (eid None) or into an existing one. Returns the id."""
    f = {k: v[k] for k in ("title", "location", "description", "all_day", "start", "end", "tz", "rrule", "exdates", "overrides",
                           "reminders", "status", "busy", "url", "extra")}
    me_ = c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    if me_ and me_[0]:  # the writer's own address as organiser: Kalmido writes its own (no account e-mail reaches others)
        f["extra"] = "\n".join(x for x in f["extra"].split("\n")
                               if not (_prop_name(x) == "ORGANIZER" and x.split(":", 1)[-1].strip().lower() == "mailto:" + me_[0].lower()))
    return ev_store(c, uid, cal_id, f, eid=eid, uid_=v["uid"], href=href, attendees=atts_resolve(c, uid, v["attendees_raw"]))


# ---- ICS import (a file, e.g. an export of another calendar) into one calendar
def import_ics(c, uid, cal_id, raw, dry=False):
    """-> {created, updated, skipped, errors}. The same UID in that calendar is updated (importing twice changes nothing)."""
    if len(raw) > IMPORT_MAX_BYTES:
        raise BadInput(tr("The file is too large (at most {0} MB)", IMPORT_MAX_BYTES // (1024 * 1024)))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if "BEGIN:VCALENDAR" not in text[:4000].upper():
        raise BadInput(tr("This is not a calendar file (ICS)"))
    raws, _ = split_events(text)
    try:
        cals = icalendar.Calendar.from_ical(text, multiple=True)
    except Exception:  # noqa: BLE001
        raise BadInput(tr("The calendar file could not be read")) from None
    comps = [x for cal in cals for x in cal.walk("VEVENT")]
    if len(comps) != len(raws):
        raise BadInput(tr("The calendar file could not be read"))
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
        old = c.execute("SELECT id FROM events WHERE cal_id=? AND uid=? AND deleted_at IS NULL", (cal_id, v["uid"])).fetchone()
        if dry:
            res["updated" if old else "created"] += 1
            continue
        store_parsed(c, uid, cal_id, v, eid=old[0] if old else None)
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


def ics_export(c, cal_id):
    rows = c.execute("SELECT * FROM events WHERE cal_id=? AND deleted_at IS NULL ORDER BY id", (cal_id,)).fetchall()
    atts = att_rows(c, [r["id"] for r in rows])
    lines, tzs = [], set()
    for r in rows:
        L, t = ev_lines(c, r, atts.get(r["id"], []))
        lines += L
        tzs |= t
    return wrap(lines, tzs)


