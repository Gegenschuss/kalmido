"""2.593.0 (#4891): the years with data of an office list (travel, meals, logbook, cash book, books / VAT return).

Every list sends years = {"min": first year, "max": last year} of the rows the person may see (independent of ?year=), or
None without rows; the year picker (static/js/office.js ofcYearOpts) runs from min to this year without gaps and reaches
later years only when data lies there."""

import re

_Y = re.compile(r"^(\d{4})")


def ofc_years(days):
    """ISO days / years (str, None and junk skipped) -> {"min": int, "max": int} or None."""
    ys = [int(m.group(1)) for m in (_Y.match(str(d)) for d in days if d) if m]
    ys = [y for y in ys if y >= 1900]  # a typo like 0202-01-01 never stretches the picker over centuries
    return {"min": min(ys), "max": max(ys)} if ys else None


def ofc_years_sql(c, sql, args=()):
    """sql selects one row (lowest day, highest day) -> ofc_years of both."""
    r = c.execute(sql, args).fetchone()
    return ofc_years([r[0], r[1]]) if r else None


def ofc_years_join(*spans):
    """Several ofc_years (None skipped) -> the span over all of them, or None."""
    return ofc_years([str(v) for s in spans if s for v in (s["min"], s["max"])])
