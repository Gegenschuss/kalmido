"""2.545.0 (#4595, decision of 04.11.2026): the switch "Extend the lock" of an office (an organisation, or the personal office
of a person without one). A tax audit is open: while it is on, nothing of the office kept by law is deleted, also after its
period ran out -- the trash purge of receipts (receipts/suggest.py olk_on_delete), old file versions (admin/dataretention.py),
the booking archive (office/bookarch.py), decided records (office/signoff.py), the deletion of the organisation or of the
account with the personal office (accounts/orgs.py, orgretain.py). It only keeps longer, never shortens a period, so it can
be switched off again at any time; both steps go into the office log. Office admins (the area "settings", manage), no agents."""
from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import tr
from ..core.pg import system_ctx
from ..core.retention import RET_LEGAL_YEARS, ret_buffer_years, ret_keep_years
from .ledger import ofx_log
from .model import office_ctx


def rth_state(c, oid):
    """{"on", "since", "by_name", "keep_years": {kind: years}, "buffer_years"} of office oid."""
    with system_ctx(c):  # structure: the switch of the own office and who set it
        r = c.execute("SELECT o.ret_hold_at, u.display_name, u.username FROM orgs o LEFT JOIN users u ON u.id=o.ret_hold_by "
                      "WHERE o.id=?", (int(oid),)).fetchone()
    since = (r["ret_hold_at"] or None) if r else None
    return {"on": bool(since), "since": since, "by_name": ((r["display_name"] or r["username"]) if r and since else "") or "",
            "keep_years": {k: ret_keep_years(k) for k in RET_LEGAL_YEARS}, "buffer_years": ret_buffer_years()}


@app.get("/api/office/settings/retention-hold")
def rth_get():
    """Office admin: the switch "Extend the lock" and the periods kept (law + the operator's buffer)."""
    c, uid, oid = office_ctx(admin=True)
    return jsonify(rth_state(c, oid))


@app.put("/api/office/settings/retention-hold")
def rth_put():
    """Office admin: {"on": true|false}. On keeps the first day (switching on again changes nothing)."""
    c, uid, oid = office_ctx(admin=True)
    b = body()
    on = b.get("on") if isinstance(b, dict) else None
    if not isinstance(on, bool):
        raise BadInput(tr("Invalid value: {0}", "on"))
    with system_ctx(c):  # the own office's row (orgs is structure)
        if on:
            n = c.execute("UPDATE orgs SET ret_hold_at=?, ret_hold_by=? WHERE id=? AND ret_hold_at IS NULL", (iso(now_utc()), uid, oid)).rowcount
        else:
            n = c.execute("UPDATE orgs SET ret_hold_at=NULL, ret_hold_by=NULL WHERE id=? AND ret_hold_at IS NOT NULL", (oid,)).rowcount
    if n:
        ofx_log(c, oid, "retention_hold", target="settings", detail={"on": on})
        bump(c)  # 2.566.0 (#4706): the area tick, other devices reload
    c.commit()
    return jsonify(rth_state(c, oid))
