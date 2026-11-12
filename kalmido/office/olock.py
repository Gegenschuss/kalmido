"""2.152.0 C (#2168 #2169): legal retention locks of the office -- what is booked is kept, not deleted.

Section 147 AO / section 257 HGB / section 14b UStG / GoBD: booked receipts (8 years), the books (10) and the logbook (8) are
kept from the end of the calendar year they belong to. Kalmido locks such rows (409 with the reason) instead of deleting
them: travel receipts ticked "in DATEV" or billed on a finalised document, booked receipts of the document store
(receipts/suggest.py olk_fs_locked), logbook drives (office/logbook.py). Corrections stay possible where the law wants
them traceable (a reversal payment, a correcting drive). The periods: core/retention.py RET_LEGAL_YEARS.
2.545.0 (#4595): the periods are core/retention.py ret_keep_years (the law + the operator's buffer); the switch "Extend the
lock" of an office (orgs.ret_hold_at, olk_held) keeps everything kept by law of it beyond its period while it is on (a tax
audit is open): the deleting runs and routes ask olk_held / olk_need_unheld, olk_fs_locked(hold=True) answers OLK_HOLD_DAY.
"""
import contextvars
import re
from datetime import date

from ..core.access import Denied, live_sql
from ..core.db import now_utc
from ..core.i18n import N_, short_day, tr
from ..core.retention import RET_HELD_ANY, ret_held, ret_held_text, ret_keep_years, ret_need_unheld, ret_person_office

OLK_DATEV = N_("This receipt is in DATEV and has to be kept: it can no longer be deleted.")
OLK_BILLED = N_("This receipt was billed on a finalised document and has to be kept: it can no longer be deleted.")
OLK_KEPT = N_("Kept by law until {0}: this can no longer be deleted.")
OLK_HOLD_DAY = date(9999, 12, 31)  # what olk_fs_locked(hold=True) answers for a lock that only the switch keeps
# 2.152.0 (#2164 #2167, review A2): set while the hosted instance deletes an organisation / account after the retention
# export or waiver (admin/retexport.py rx_gate): it keeps nothing for others, so the purge hook of booked receipts stands
# aside (self-hosting keeps the lock: there the booked rows were retired / moved first)
OLK_BYPASS = contextvars.ContextVar("olk_bypass", default=False)


def olk_until(day, kind):
    """The last day of the legal period of a row dated day (ISO text, at least YYYY): 31 Dec of year + N, else None.
    2.545.0 (#4595): N = ret_keep_years(kind), the law + the operator's buffer."""
    m = re.match(r"(\d{4})", str(day or ""))
    if not m:
        return None
    return date(int(m.group(1)) + ret_keep_years(kind), 12, 31)


def olk_active(until):
    """Is the period ending at until (a date) still running today?"""
    return until is not None and until >= now_utc().date()


def olk_kept_text(until):
    if until == OLK_HOLD_DAY:  # 2.545.0 (#4595): only the switch "Extend the lock" keeps it
        return tr(RET_HELD_ANY)
    return tr(OLK_KEPT, short_day(until, year=True))


# 2.545.0 (#4595): the switch itself lives in core/retention.py (accounts/ asks it too); the names of this module stay
olk_held, olk_held_text, olk_need_unheld, olk_person_office = ret_held, ret_held_text, ret_need_unheld, ret_person_office


# 2.545.0 (#4595): a deleting run over many offices leaves out the rows of the offices whose lock is extended
OLK_NOT_HELD = "org_id NOT IN (SELECT id FROM orgs WHERE ret_hold_at IS NOT NULL)"


def olk_trip_item_reason(c, oid, r):
    """Why travel receipt row r may not be deleted (a translated text) or None. 2.152.0 C (#2168): ticked "in DATEV", or billed
    on a document of the office that is finalised (locked_at) or sent."""
    if r["datev"]:
        return tr(OLK_DATEV)
    if r["billed_doc_id"]:
        d = c.execute(f"SELECT locked_at, status FROM office_docs WHERE id=? AND org_id=? AND {live_sql()}", (r["billed_doc_id"], oid)).fetchone()
        if d and (d["locked_at"] or d["status"] == "sent"):
            return tr(OLK_BILLED)
    return None


def olk_need_trip_items(c, oid, rows):
    """409 when one of the travel receipt rows is locked (delete of a receipt or of its trip)."""
    for r in rows:
        why = olk_trip_item_reason(c, oid, r)
        if why:
            raise Denied(409, why)
