"""Office & finance, 2.138.0 D (#2256): the number ranges -- the next running number of every series (quotation, invoice,
credit note, reminder, delivery note) set by the office admin. The counter only moves up (never to or below the last number given);
a jump in the invoice / credit note series needs a reason (GoBD), every change goes into the office log. A scheme with
a year ({yyyy}/{yy}) has one counter per year: the setting applies to the current year. office_numbers.last = next - 1,
no new table or column. Session routes only (office_gate: no agents), like the rest of the settings."""
from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, err
from ..core.i18n import tr
from ..core.pg import write_lock
from .invoices import INV_SKIP_REASON_MIN, inv_scheme
from .ledger import ofx_log
from .model import office_gate, office_number_format, office_org, office_role, office_scheme_period, office_settings

ONUM_KINDS = ("offer", "invoice", "credit", "reminder", "delivery")  # delivery notes since 2.120.0 D (#2089)
ONUM_REASON_KINDS = ("invoice", "credit")  # a jump in these series needs a reason (GoBD)
ONUM_MAX = 999_999_999


def onum_kinds(s):
    """The series with one counter; quotations counted per client / project (2.118.0 A, #2265) have no single one."""
    return tuple(k for k in ONUM_KINDS if k != "offer" or (s.get("offer_counter") or "org") == "org")


def onum_scheme(s, kind):
    return s.get("offer_scheme") if kind == "offer" else inv_scheme(s, kind)


def onum_range(c, oid, s, kind):
    """The state of one series: scheme, counter period, last value, the next number (formatted with example values)."""
    scheme = onum_scheme(s, kind) or ""
    period = office_scheme_period(scheme)
    r = c.execute("SELECT last FROM office_numbers WHERE org_id=? AND kind=? AND period=?", (oid, kind, period)).fetchone()
    last = int(r["last"]) if r else 0
    return {"kind": kind, "scheme": scheme, "period": period, "yearly": bool(period), "last": last, "next": last + 1, "min_next": last + 1,
            "preview": office_number_format(scheme, last + 1, project=tr("Project"), client=tr("Client"), initials="AB"),
            "reason_needed": kind in ONUM_REASON_KINDS}


@app.get("/api/office/number-ranges")
def onum_list():
    """Every series of the office area I work in; members read (the settings page is the admins'), admin = may change."""
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid)
    s = office_settings(c, oid)
    return jsonify(ranges=[onum_range(c, oid, s, k) for k in onum_kinds(s)], admin=office_role(c, uid, oid) == "admin")


@app.post("/api/office/number-ranges/<kind>")
def onum_set(kind):
    """Org admin. {next, reason?}: the next running number of a series (current year with a yearly scheme). Only up;
    the invoice / credit note series need a reason when numbers are skipped. -> the series' new state."""
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=True)
    if kind not in onum_kinds(office_settings(c, oid)):
        return err(tr("Invalid value: {0}", "kind"))
    b = body()
    b = b if isinstance(b, dict) else {}
    try:
        nxt = int(str(b.get("next", "")).strip())
    except ValueError:
        return err(tr("Invalid value: {0}", "next"))
    reason = b.get("reason") if isinstance(b.get("reason"), str) else ""
    reason = reason.strip()[:300]
    write_lock(c, f"office_num_{int(oid)}")  # the same lock as the number of a new document (docs._assign_number)
    s = office_settings(c, oid)
    cur = onum_range(c, oid, s, kind)
    if nxt < cur["min_next"] or nxt > ONUM_MAX:
        return err(tr("The next number must be at least {0}", cur["min_next"]))
    if nxt == cur["next"]:
        return jsonify(onum_range(c, oid, s, kind))
    if kind in ONUM_REASON_KINDS and len(reason) < INV_SKIP_REASON_MIN:
        return err(tr("The number skips {0} numbers of the series; give a reason (GoBD)", nxt - cur["next"]))
    # never down, also against a document numbered in parallel (the lock above + the condition on the row)
    row = c.execute("INSERT INTO office_numbers(org_id, kind, period, last) VALUES(?,?,?,?) ON CONFLICT(org_id, kind, period) "
                    "DO UPDATE SET last=excluded.last WHERE office_numbers.last < excluded.last RETURNING last",
                    (oid, kind, cur["period"], nxt - 1)).fetchone()
    if row is None:
        c.rollback()
        return err(tr("The next number must be at least {0}", cur["min_next"]))
    ofx_log(c, oid, "number", target="number_range", detail={"before": {"kind": kind, "period": cur["period"], "next": cur["next"]},
                                                             "after": {"next": nxt, **({"reason": reason} if reason else {})}})
    bump(c)
    c.commit()
    return jsonify(onum_range(c, oid, s, kind))
