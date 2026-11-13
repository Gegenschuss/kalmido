"""2.1064.0 (#5818): a sent quotation without an answer rings the bell before and after its "valid until".

Decided 12.11.2026 (the product owner): a quotation in the status "sent" (no answer: not accepted, not declined, not superseded) with
a date "valid until" tells, in the bell under "For you", at most twice per validity:
  - "soon"  from offer_exp_days days before that date on (office setting, default 3, 1 to 30): "expires in N days"
  - "gone"  from the day after that date on: "has expired" (never for a date more than OFE_LATE days back: a quotation that
            ran out long before this existed does not ring once the feature arrives)
Who hears of it: the person who marked it sent (the office log's status entry, by hand or by the mail), while still a person
of the office; else the office admins (a personal office: its owner) -- the people of a customer's decision on an approval
link (signoff.sig_people). News only, no push (row "office" of the notification settings, like an overdue invoice); one
entry per quotation, so the bell counts 1 per quotation. The office setting offer_exp_notice (default on) switches it off.
Nothing changes by itself: no status change, the quotation stays "sent" until a person answers it.

The entry shows (news_items, ofe_news_live) while the person is still in that office, the quotation is still "sent", not in the
trash and its date is still the one it rang for: accepted / declined / superseded / extended = gone from the bell.
"Extend validity" (POST /api/office/docs/<id>/valid-until): a new date on a sent quotation without a new version; the
database holds a finalised row (core/migrations.d/4598.py), so the one column is written inside ledger.ofx_release, logged
in the office log (action valid_until, before / after). The stored PDF of a finalised quotation (pdfweb.epdf_store,
the file the app serves and mails) is stored anew with the new date (the office log keeps the old checksum); an open
approval link of the quotation no longer fits what it was made for (its hash covers the date, signoff.sig_check) - the
answer counts those links (links_void) so the app can say a new one is needed. The marks of the old date go: the new date
rings again.
The marks "told already" are rows of office_dunning_marks with the levels OFE_SOON / OFE_GONE (the invoices' marks use 0
and up; a document id is one document, so the two never meet), with their unique (doc_id, level): two runs at once ring once."""
import json
import time
from datetime import date, timedelta

from flask import g, jsonify

from ..core.config import app, WATCHDOG_INTERVAL
from ..core.db import body, bump, err, iso, iso_ms, local_now, now_utc, test_seconds
from ..core.i18n import tr
from ..core.pg import system_ctx, write_lock
from ..core.access import Denied, live_sql
from ..accounts.orgroles import OFFICE_READ
from ..tasks.validation import valid_date
from ..collab.news import news_add
from .model import office_ctx as _ctx, office_role, office_settings, ofx_release
from .docs import doc_public, doc_row
from .pdfweb import epdf_store
from .signoff import sig_people
from .fixedimport import fci_people
from .ledger import ofx_locked, ofx_log
from .dunning import dun_priv_hidden

OFE_SOON, OFE_GONE = -1, -2   # office_dunning_marks.level: "the bell told that it expires soon / has expired"
OFE_DAYS = 3                  # default of the office setting offer_exp_days
OFE_DAYS_MAX = 30
OFE_LATE = 14                 # a date further back than this never rings "gone" (see the module text)
OFE_EVERY_TICKS = 10          # whole days matter, like the overdue invoices
OFE_EVERY_TICKS = test_seconds("KALMIDO_TEST_DUN_TICKS", OFE_EVERY_TICKS)
_OFE_LAST = {"at": 0.0}


def _j(s, default):
    try:
        v = json.loads(s) if s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


def ofe_days(s):
    """The office settings s -> how many days ahead "soon" starts (0 = the notice is off)."""
    if not int(s.get("offer_exp_notice", 1) or 0):
        return 0
    try:
        return max(1, min(OFE_DAYS_MAX, int(s.get("offer_exp_days", OFE_DAYS) or OFE_DAYS)))
    except (TypeError, ValueError):
        return OFE_DAYS


def ofe_state(r, today, days):
    """'soon' | 'gone' | None of quotation row r on day today (ISO) with the notice days (0 = off: only 'gone' for the mark
    in the list and the editor's note, see ofe_doc_state)."""
    vu = r["valid_until"] or ""
    if r["kind"] != "offer" or r["status"] != "sent" or not valid_date(vu):
        return None
    if vu < today:
        return "gone"
    if days and vu <= (date.fromisoformat(today) + timedelta(days=days)).isoformat():
        return "soon"
    return None


def ofe_doc_state(c, oid, r):
    """The editor's note for quotation row r: {state, until, days} or None (the notice days of the office's settings)."""
    today = local_now().date().isoformat()
    st = ofe_state(r, today, ofe_days(office_settings(c, oid)) or OFE_DAYS)
    if not st:
        return None
    return {"state": st, "until": r["valid_until"], "days": (date.fromisoformat(r["valid_until"]) - date.fromisoformat(today)).days}


def ofe_expired(r, today):
    """A list row: the quotation is sent, unanswered and past its date (the mark "expired")."""
    return ofe_state(r, today, 0) == "gone"


def _client(c, r):
    """The client's name: the quotation's recipient, else its client (a draft marked sent keeps no snapshot)."""
    name = str(_j(r["recipient"], {}).get("name") or "")
    if not name and r["client_id"]:
        x = c.execute("SELECT name FROM clients WHERE id=?", (r["client_id"],)).fetchone()
        name = str(x["name"] or "") if x else ""
    return name[:200]


def ofe_sender(c, oid, did):
    """Who marked quotation did sent (the office log's last status entry to 'sent'), None when the log does not know."""
    for x in c.execute("SELECT user_id, detail FROM office_doc_log WHERE org_id=? AND doc_id=? AND action='status' ORDER BY id DESC LIMIT 20",
                       (oid, did)):
        if x["user_id"] and (_j(x["detail"], {}).get("after") or {}).get("status") == "sent":
            return x["user_id"]
    return None


# ---------------------------------------------------------------- the watchdog
def ofe_tick(c, now=None):
    """Every office area with a sent quotation near or just past its date: ofe_area (see the module text)."""
    if time.monotonic() - _OFE_LAST["at"] < OFE_EVERY_TICKS * WATCHDOG_INTERVAL:
        return
    _OFE_LAST["at"] = time.monotonic()
    day = (now or local_now()).date()
    with system_ctx(c):  # which areas have a candidate at all; each is then handled in its admin's own context
        oids = [r[0] for r in c.execute(
            "SELECT DISTINCT org_id FROM office_docs WHERE kind='offer' AND status='sent' AND trial=0 AND valid_until IS NOT NULL "
            f"AND valid_until<=? AND valid_until>=? AND {live_sql()} ORDER BY org_id LIMIT 2000",
            ((day + timedelta(days=OFE_DAYS_MAX)).isoformat(), (day - timedelta(days=OFE_LATE)).isoformat())).fetchall()]
    c.commit()
    for oid in oids:
        try:
            ofe_area(c, oid, day.isoformat())
        except Exception as e:  # noqa: BLE001 -- one broken area never stops the others
            c.rollback()
            print("quotation expiry notice", oid, "failed:", e, flush=True)


def ofe_area(c, oid, today):
    """The notices of office area oid on day today (ISO); returns how many quotations rang."""
    with system_ctx(c):
        people = [p["id"] for p in fci_people(c, oid)]
    c.commit()
    if not people:
        return 0
    prev = c.ctx
    try:
        with app.test_request_context("/api/office/docs"):
            g.user = c.execute("SELECT * FROM users WHERE id=?", (people[0],)).fetchone()  # the area's admin: its context (RLS)
            if g.user is None:
                return 0
            return _ofe_as(c, oid, today)
    finally:
        c.rollback()  # whatever is left open; then the watchdog's own context again
        c.set_ctx(*prev)


def _ofe_as(c, oid, today):
    days = ofe_days(office_settings(c, oid))
    if not days:
        return 0
    write_lock(c, f"office_offer_exp_{int(oid)}")
    t0 = date.fromisoformat(today)
    rows = c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind='offer' AND status='sent' AND trial=0 AND valid_until IS NOT NULL "
                     f"AND valid_until<=? AND valid_until>=? AND {live_sql()} ORDER BY valid_until, id LIMIT 2000",
                     (oid, (t0 + timedelta(days=days)).isoformat(), (t0 - timedelta(days=OFE_LATE)).isoformat())).fetchall()
    ts, n = iso(now_utc()), 0
    for r in rows:
        st = ofe_state(r, today, days)
        if not st:
            continue
        level = OFE_GONE if st == "gone" else OFE_SOON
        # only the mark THIS run set counts (RETURNING is empty when another run was first): one entry per quotation and step
        if not c.execute("INSERT INTO office_dunning_marks(org_id, doc_id, level, created_at) VALUES(?,?,?,?) "
                         "ON CONFLICT(doc_id, level) DO NOTHING RETURNING doc_id", (oid, r["id"], level, ts)).fetchone():
            continue
        if st == "gone":  # a quotation that was not told "soon" (sent late, the notice switched on later) is not told so afterwards
            c.execute("INSERT INTO office_dunning_marks(org_id, doc_id, level, created_at) VALUES(?,?,?,?) ON CONFLICT(doc_id, level) DO NOTHING",
                      (oid, r["id"], OFE_SOON, ts))
        data = {"org_id": oid, "doc": r["id"], "number": r["number"] or "", "client": _client(c, r), "state": st, "until": r["valid_until"],
                "days": (date.fromisoformat(r["valid_until"]) - t0).days, "click": f"#office/offers/{int(r['id'])}"}
        for p in sig_people(c, oid, ofe_sender(c, oid, r["id"])):
            news_add(c, p, "offerexp", actor=0, row="office", data=data)
        n += 1
    c.commit()
    return n


def ofe_news_live(c, uid, data):
    """A News entry "offerexp" shows while uid is still a person of that office (its private office: while "Also private" is
    on) and the quotation is still sent, not in the trash and has the date the entry rang for."""
    d = _j(data, {})
    try:
        oid, did = int(d.get("org_id") or 0), int(d.get("doc") or 0)
    except (TypeError, ValueError):
        return False
    if not oid or not did or dun_priv_hidden(c, uid, oid) or office_role(c, uid, oid) not in OFFICE_READ:
        return False
    with system_ctx(c):  # the office role above is checked; the quotation is read across the request's organisations
        r = c.execute(f"SELECT status, valid_until FROM office_docs WHERE id=? AND org_id=? AND kind='offer' AND {live_sql()}", (did, oid)).fetchone()
    return bool(r) and r["status"] == "sent" and (r["valid_until"] or "") == str(d.get("until") or "")


# ---------------------------------------------------------------- "Extend validity"
@app.post("/api/office/docs/<int:did>/valid-until")
def ofe_extend(did):
    """{valid_until: YYYY-MM-DD (today or later)} -> the quotation with its new date, links_void = open approval links that no
    longer fit. Only a sent quotation without an answer (409 otherwise); no new version (see the module text)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_doc_{int(did)}")
    r = doc_row(c, oid, did)
    if r["kind"] != "offer":
        raise Denied(409, tr("Only a quotation has a validity date"))
    if r["status"] != "sent":
        raise Denied(409, tr("Only a sent quotation without an answer can be extended"))
    b = body()
    v = (b if isinstance(b, dict) else {}).get("valid_until")
    if not isinstance(v, str) or not valid_date(v) or v < local_now().date().isoformat():
        return err(tr("The date must be today or later"))
    old = r["valid_until"] or ""
    if v != old:
        with ofx_release(c):  # a finalised quotation: this one column, deliberately (core/migrations.d/4598.py)
            c.execute("UPDATE office_docs SET valid_until=?, updated_at=? WHERE id=? AND org_id=?", (v, iso_ms(now_utc()), did, oid))
            if ofx_locked(r) and (r["pdf_sha256"] if "pdf_sha256" in r.keys() else ""):
                # the stored PDF is what the app serves and mails: stored anew with the new date
                epdf_store(c, oid, did, log_extra={"valid_until": v})
        c.execute("DELETE FROM office_dunning_marks WHERE org_id=? AND doc_id=? AND level IN (?, ?)", (oid, did, OFE_SOON, OFE_GONE))
        ofx_log(c, oid, "valid_until", doc_id=did, detail={"before": {"valid_until": old}, "after": {"valid_until": v}})
    void = c.execute("SELECT COUNT(*) FROM office_signoffs WHERE org_id=? AND doc_id=? AND kind='offer' AND state='open' AND revoked_at IS NULL "
                     f"AND (expires_at IS NULL OR expires_at>?) AND {live_sql()}", (oid, did, iso(now_utc()))).fetchone()[0] if v != old else 0
    bump(c)
    c.commit()
    out = doc_public(c, oid, doc_row(c, oid, did), office_role(c, uid, oid) == "admin", items=False)
    out["links_void"] = int(void or 0)
    return jsonify(out)
