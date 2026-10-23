"""Office & finance (2.50.0, #1196, part B): the sales pipeline -- deals from the first inquiry to the order: stage inquiry |
offer (quotation sent) | won (order) | lost, a net value in the office currency, a probability (preset per stage, changeable
per deal) and an expected date. A deal can get a quotation (made with the office's own quotation code, the client taken
over) and a project (a list of the client); a quotation set to accepted -- by hand or by the client's sign-off -- moves its
deal to won (pl2_offer_status, called from docs.odoc_status and part C's signoff). A declined quotation leaves the deal
where it is (the view shows a note; the admin sets "lost").
2.94.0 A (#1930): a stage lead before inquiry (office/leads.py: convert, CSV import, agents) with source, next step,
follow-up day and the lead's contact data; leads are never counted in the sums or the forecast.
Every route: office_gate + office_org with the admin of the office area (a personal office: its owner). Agents: none (the
office is for people only). value / contact / note / lost_reason (+ next_step / email / phone / company) encrypted at rest (orgcrypt)."""
import re
from datetime import date

from flask import jsonify, request

from ..core.config import app
from ..core.pg import insert_id
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, local_now, now_utc
from ..core.access import Denied
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .model import office_gate, office_org, office_settings, pb_cl_sql, pb_owner

PL2_STAGES = ("lead", "inquiry", "offer", "won", "lost")  # 2.94.0 A (#1930): + lead before inquiry (office/leads.py)
PL2_PROB = {"lead": 10, "inquiry": 20, "offer": 50, "won": 100, "lost": 0}  # the preset probability of a stage (%)
PL2_OPEN = ("inquiry", "offer")  # the sums and the forecast; leads are open too but never counted there (2.94.0 A, #1930)
# 2.94.0 A (#1930): where a lead came from (a key, the client translates it; "" = not given)
LEAD_SOURCES = ("website", "referral", "event", "social", "booking", "import", "agent", "other")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_DEALS = 2000
PL2_FIELDS = ("id", "title", "client_id", "contact", "value", "stage", "probability", "expected_date", "offer_id", "list_id",
              "lost_reason", "note", "sort", "created_at", "updated_at",
              "source", "next_step", "follow_up", "email", "phone", "company")  # 2.94.0 A (#1930): the lead fields


from .rights import ofr_need_area  # noqa: E402  2.187.0 (#2476)
from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def _txt(v, name, n):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", name))
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", v).strip()[:n]


def _client_ok(c, oid, cid):
    """A client of office area oid (an organisation's, or the owner's private ones in a personal office)."""
    return bool(c.execute(f"SELECT 1 FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (cid,)).fetchone())


def _list_ok(c, oid, lid):
    """A list of office area oid (a personal office: the owner's private lists)."""
    return bool(c.execute(f"SELECT 1 FROM lists WHERE id=? AND {pb_cl_sql(c, oid, 'org_id', 'owner_id')}",
                          (lid,)).fetchone())


def _ref(c, oid, b, k, ok):
    v = b.get(k)
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or not ok(c, oid, v):
        raise BadInput(tr("Invalid value: {0}", k))
    return v


def _day(v, name):
    v = v or ""
    if v:
        if not isinstance(v, str) or not DATE_RE.match(v):
            raise BadInput(tr("Invalid value: {0}", name))
        try:
            date.fromisoformat(v)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", name)) from None
    return v


def pl2_clean(c, oid, b, cur=None):
    """The checked columns of body b (a new deal: cur None; else only the keys given)."""
    new = cur is None
    cur = cur or {}
    out = {}
    if "title" in b or new:
        out["title"] = _txt(b.get("title"), "title", 200)
        if not out["title"]:
            raise BadInput(tr("Please enter a name"))
    for k, n in (("contact", 200), ("note", 4000), ("lost_reason", 500), ("next_step", 300), ("company", 200), ("phone", 60)):
        if k in b:
            out[k] = _txt(b.get(k), k, n)
    if "email" in b:  # 2.94.0 A (#1930): the lead's contact data
        out["email"] = _txt(b.get("email"), "email", 200)
        if out["email"] and not EMAIL_RE.match(out["email"]):
            raise BadInput(tr("Invalid value: {0}", "email"))
    if "source" in b:
        v = b.get("source") or ""
        if v not in LEAD_SOURCES + ("",):
            raise BadInput(tr("Invalid value: {0}", "source"))
        out["source"] = v
    if "follow_up" in b:
        out["follow_up"] = _day(b.get("follow_up"), "follow_up")
    if "client_id" in b:
        out["client_id"] = _ref(c, oid, b, "client_id", _client_ok)
    if "list_id" in b:
        out["list_id"] = _ref(c, oid, b, "list_id", _list_ok)
    if "value" in b or new:
        v = b.get("value")
        if v in (None, ""):
            v = 0
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise BadInput(tr("Invalid value: {0}", "value"))
        a = dec(v, "NaN")
        if a.is_nan() or not a.is_finite() or a < 0 or a > 10 ** 10:
            raise BadInput(tr("Invalid value: {0}", "value"))
        out["value"] = dstr(money(a))
    if "stage" in b or new:
        st = b.get("stage") or "inquiry"
        if st not in PL2_STAGES:
            raise BadInput(tr("Invalid value: {0}", "stage"))
        out["stage"] = st
    if "probability" in b:
        p = b.get("probability")
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 100:
            raise BadInput(tr("Invalid value: {0}", "probability"))
        out["probability"] = int(round(p))
    elif "stage" in out and out["stage"] != cur.get("stage"):
        # a new stage: its preset, unless the deal's own value was changed by hand (won / lost always 100 / 0)
        old = cur.get("probability")
        if new or out["stage"] in ("won", "lost") or old == PL2_PROB.get(cur.get("stage")):
            out["probability"] = PL2_PROB[out["stage"]]
    if "expected_date" in b:
        out["expected_date"] = _day(b.get("expected_date"), "expected_date")
    if "sort" in b:
        s = b.get("sort")
        if isinstance(s, bool) or not isinstance(s, (int, float)) or abs(s) > 1e12:
            raise BadInput(tr("Invalid value: {0}", "sort"))
        out["sort"] = float(s)
    return out


def _offer_state(c, oid, ids):
    """{offer id: (number, status)} of the quotations of the deals (the view shows them on the card)."""
    ids = [i for i in ids if i]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r["id"]: (r["number"], r["status"]) for r in c.execute(
        f"SELECT id, number, status FROM office_docs WHERE org_id=? AND kind='offer' AND id IN ({q})", [oid] + ids)}


def pl2_public(c, oid, r, offers=None, names=None):
    d = oc_dec_fields(c, oid, "office_deals", r)
    out = {k: d.get(k) for k in PL2_FIELDS}
    out["weighted"] = dstr(money(dec(out["value"] or 0) * dec(out["probability"] or 0) / 100))
    o = (offers or {}).get(out["offer_id"]) if out["offer_id"] else None
    out["offer_number"], out["offer_status"] = (o[0], o[1]) if o else ("", "")
    out["client_name"] = (names or {}).get(out["client_id"], "") if out["client_id"] else ""
    return out


def _client_names(c, oid):
    return {r["id"]: r["name"] for r in c.execute(f"SELECT id, name FROM clients WHERE {pb_cl_sql(c, oid)}")}


def _add_months(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def pl2_summary(items, today=None, months=6):
    """{open, weighted, count_open, won, forecast: [{month, weighted, next}], undated}: open = inquiries + quotations (net);
    weighted = their value x probability; the forecast puts the weighted value of every open deal in the month of its
    expected date (a past date = this month), from this month on; deals without a date are counted apart."""
    today = today or local_now().date().isoformat()
    cur = today[:7]
    ms = [_add_months(cur, i) for i in range(months)]
    fc = {m: dec(0) for m in ms}
    tot, wt, won, undated, n = dec(0), dec(0), dec(0), dec(0), 0
    leads = due = 0  # 2.94.0 A (#1930): leads only counted (never in the sums / the forecast)
    for d in items:
        if d["stage"] == "lead":
            leads += 1
            due += bool(d.get("follow_up")) and d["follow_up"] <= today
        if d["stage"] == "won":
            won += dec(d["value"] or 0)
        if d["stage"] not in PL2_OPEN:
            continue
        n += 1
        tot += dec(d["value"] or 0)
        w = dec(d["weighted"])
        wt += w
        ed = d.get("expected_date") or ""
        if not ed:
            undated += w
            continue
        mo = max(ed[:7], cur)
        if mo in fc:
            fc[mo] += w
    nxt = _add_months(cur, 1)
    return {"open": dstr(money(tot)), "weighted": dstr(money(wt)), "count_open": n, "won": dstr(money(won)), "undated": dstr(money(undated)),
            "leads": leads, "leads_due": due, "forecast": [{"month": m, "weighted": dstr(money(fc[m])), "next": m == nxt, "current": m == cur} for m in ms]}


def pl2_list(c, oid, deleted=False):
    rows = c.execute(f"SELECT * FROM office_deals WHERE org_id=? AND deleted_at IS {'NOT ' if deleted else ''}NULL "
                     "ORDER BY sort, expected_date, id", (oid,)).fetchall()
    offers = _offer_state(c, oid, [r["offer_id"] for r in rows])
    names = _client_names(c, oid)
    return [pl2_public(c, oid, r, offers, names) for r in rows]


def pl2_weighted(c, oid):
    """The weighted value of the open deals of office area oid (the figures of #1197)."""
    return pl2_summary(pl2_list(c, oid))


def _row(c, oid, did, deleted=False):
    r = c.execute(f"SELECT * FROM office_deals WHERE id=? AND org_id=? AND deleted_at IS {'NOT ' if deleted else ''}NULL", (did, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def _one(c, oid, did):
    r = _row(c, oid, did)
    return pl2_public(c, oid, r, _offer_state(c, oid, [r["offer_id"]]), _client_names(c, oid))


def _update(c, oid, did, row):
    if not row:
        return
    row["updated_at"] = iso(now_utc())
    row = oc_enc_fields(c, oid, "office_deals", row)
    c.execute(f"UPDATE office_deals SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [did, oid])


# ---------------------------------------------------------------- the hook of the quotation status
def pl2_offer_status(c, oid, doc_id, status):
    """A quotation of office area oid got status: accepted moves the deals bound to it to won (probability 100). Called
    after the status change by docs.odoc_status and by part C's sign-off over the client link (the caller commits).
    Declined / others: nothing (the view shows the quotation's state). Returns the ids of the deals moved."""
    if status != "accepted":
        return []
    if c.execute("SELECT 1 FROM office_docs WHERE id=? AND org_id=? AND trial<>0", (doc_id, oid)).fetchone():
        return []  # 2.144.10 B (#2576): a trial quotation never wins a deal
    ids = [r[0] for r in c.execute("SELECT id FROM office_deals WHERE org_id=? AND offer_id=? AND deleted_at IS NULL AND stage!='won'",
                                   (oid, doc_id)).fetchall()]
    for did in ids:
        _update(c, oid, did, {"stage": "won", "probability": 100})
    return ids


# ---------------------------------------------------------------- routes
@app.get("/api/office/deals")
def pl2_get():
    """{items: [...], summary: pl2_summary, stages: [...], probabilities: {stage: %}, sources: [...], currency}."""
    c, uid, oid = _ctx()
    items = pl2_list(c, oid)
    return jsonify(items=items, summary=pl2_summary(items), stages=list(PL2_STAGES), probabilities=PL2_PROB,
                   sources=list(LEAD_SOURCES), currency=(office_settings(c, oid).get("currency") or "EUR").upper())


@app.post("/api/office/deals")
def pl2_post():
    """{title, client_id?, contact?, value?, stage?, probability?, expected_date?, list_id?, note?} -> 201 the deal."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if c.execute("SELECT COUNT(*) FROM office_deals WHERE org_id=? AND deleted_at IS NULL", (oid,)).fetchone()[0] >= MAX_DEALS:
        raise BadInput(tr("Too many entries"))
    row = pl2_clean(c, oid, b)
    if "sort" not in row:
        row["sort"] = float(c.execute("SELECT COALESCE(MIN(sort), 0) - 1 FROM office_deals WHERE org_id=?", (oid,)).fetchone()[0])
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_deals", row)
    did = insert_id(c, f"INSERT INTO office_deals({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, did)), 201


@app.patch("/api/office/deals/<int:did>")
def pl2_patch(did):
    """Partial: the fields of POST + sort, offer_id (a quotation of the office area, null = unbound). Answers the deal and
    "before" = the old values of the keys changed (the client's undo patches them back)."""
    c, uid, oid = _ctx()
    cur = pl2_public(c, oid, _row(c, oid, did))
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = pl2_clean(c, oid, b, cur)
    if "offer_id" in b:
        v = b.get("offer_id")
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not c.execute(
                "SELECT 1 FROM office_docs WHERE id=? AND org_id=? AND kind='offer' AND trial=0", (v, oid)).fetchone()):  # 2.144.10 B (#2576)
            raise BadInput(tr("Invalid value: {0}", "offer_id"))
        row["offer_id"] = v
    before = {k: cur.get(k) for k in row}
    _update(c, oid, did, row)
    bump(c)
    c.commit()
    return jsonify({**_one(c, oid, did), "before": before})


@app.delete("/api/office/deals/<int:did>")
def pl2_delete(did):
    """Into the bin (deleted_at); POST .../restore brings it back (the client's undo)."""
    c, uid, oid = _ctx()
    _row(c, oid, did)
    c.execute("UPDATE office_deals SET deleted_at=? WHERE id=? AND org_id=?", (iso(now_utc()), did, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, id=did)


@app.post("/api/office/deals/<int:did>/restore")
def pl2_restore(did):
    c, uid, oid = _ctx()
    _row(c, oid, did, deleted=True)
    c.execute("UPDATE office_deals SET deleted_at=NULL WHERE id=? AND org_id=?", (did, oid))
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, did))


@app.post("/api/office/deals/<int:did>/offer")
def pl2_make_offer(did):
    """A new quotation for the deal (the office's quotation code: settings, number; the deal's client and title taken over),
    bound to it (offer_id); an inquiry moves to "offer". 201 {deal, doc_id}. The quotation is a draft until it is sent."""
    from .docs import doc_create, doc_row
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    ofr_need_area(c, uid, oid, "offers", "edit")  # 2.187.0 (#2476, review): it reads / writes quotations and invoices too
    cur = pl2_public(c, oid, _row(c, oid, did))
    if cur["offer_id"] and c.execute("SELECT 1 FROM office_docs WHERE id=? AND org_id=?", (cur["offer_id"], oid)).fetchone():
        raise Denied(409, tr("This deal already has a quotation"))
    b = {"kind": "offer", "project_title": cur["title"]}
    if cur["client_id"] and _client_ok(c, oid, cur["client_id"]):
        b["client_id"] = cur["client_id"]
    nid = doc_create(c, oid, uid, b, True)
    if cur["list_id"] and _list_ok(c, oid, cur["list_id"]):  # 2.168.0 A (#2665): the quotation belongs to the deal's project
        c.execute("UPDATE office_docs SET list_id=? WHERE id=? AND org_id=?", (cur["list_id"], nid, oid))
    r = doc_row(c, oid, nid)
    ofx_log(c, oid, "create", doc_id=nid, detail={"number": r["number"], "items": 0, "deal_id": did})
    row = {"offer_id": nid}
    if cur["stage"] in ("lead", "inquiry"):  # 2.94.0 A (#1930): a lead with a quotation moves on too
        row.update(pl2_clean(c, oid, {"stage": "offer"}, cur))
    _update(c, oid, did, row)
    bump(c)
    c.commit()
    return jsonify(deal=_one(c, oid, did), doc_id=nid), 201


@app.post("/api/office/deals/<int:did>/project")
def pl2_make_project(did):
    """A new project (list of the project type "agency": time tracking + fields) named like the deal, in the office's
    workspace (a personal office: private), with the deal's client; bound to the deal (list_id). 201 {deal, list_id}.
    The client's undo deletes the list and unbinds it."""
    from ..lists.templates import ptype_create
    from ..team.clients import list_client_set
    c, uid, oid = _ctx()
    cur = pl2_public(c, oid, _row(c, oid, did))
    if cur["list_id"] and _list_ok(c, oid, cur["list_id"]):
        raise Denied(409, tr("This deal already has a project"))
    lid, on = ptype_create(c, uid, "agency", cur["title"], org_id=None if pb_owner(c, oid) is not None else oid)
    if cur["client_id"] and _client_ok(c, oid, cur["client_id"]):
        list_client_set(c, lid, cur["client_id"])
    _update(c, oid, did, {"list_id": lid})
    bump(c)
    c.commit()
    return jsonify(deal=_one(c, oid, did), list_id=lid, modules_on=on), 201


@app.get("/api/office/deals/summary")
def pl2_summary_get():
    """Only the sums (the figures tab and a tile): pl2_summary + currency."""
    c, uid, oid = _ctx()
    months = request.args.get("months") or "6"
    n = int(months) if months.isdigit() and 1 <= int(months) <= 12 else 6
    return jsonify(summary=pl2_summary(pl2_list(c, oid), months=n), currency=(office_settings(c, oid).get("currency") or "EUR").upper())
