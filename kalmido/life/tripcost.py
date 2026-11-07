"""2.173.0 A (#2680): from a trip (a project of Home & life, lists.life 'travel') to its travel expenses in the office.
The trip planning keeps no costs of its own: "Travel expenses" makes ONE trip of the office (office_trips) filled from
the trip (period, destination, the trip's name as note, the person as participant) and remembers it (life_trip_costs),
so the next click opens the same one. The office area is the trip's organisation, for a private trip the person's own
office (a person without an organisation: the personal office). Only who may make travel expenses there (the admins of
the office area, like the tab "Travel expenses"; 2.620.0 (#4642): also a member on the level "own", for the own office trip
only); never an agent or an API token."""
import json

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import bump, db, iso, now_utc
from ..core.pg import insert_id, write_lock
from ..core.access import Denied, vis_sql
from ..accounts.session import me
from ..accounts.orgroles import office_allowed
from ..core.orgcrypt import oc_enc_fields
from ..life.model import need_life
from ..office.model import OFFICE_ADMIN_ONLY, office_gate, office_role, pb_owner, pb_personal
from ..office.periodlock import period_need_open
from ..office.travel import rk_trip_clean


def ltc_trip_list(c, uid, lid):
    """The trip project lid uid sees (id, name, org_id, trip dict), else 404."""
    r = c.execute(f"""SELECT id, name, org_id, trip FROM lists WHERE id=? AND life='travel' AND deleted_at IS NULL
                      AND id IN {vis_sql()}""", (lid, uid, uid)).fetchone()
    try:
        trip = json.loads(r["trip"]) if r and r["trip"] else None
    except ValueError:
        trip = None
    if not r or not isinstance(trip, dict) or not trip.get("from"):
        raise Denied(404)
    return r, trip


def ltc_office(c, uid, oid_list):
    """The office area of a trip for uid (the trip's organisation, else the personal office) -> (oid, own): 403 unless uid is
    its admin, has travel expenses on "edit" through office groups or -- 2.620.0 (#4642) -- works there on the level "own"
    (an org member in "Previous access" like #4592, or a group like "Staff"): own=True, only the person's own office trip."""
    office_gate(c)  # agents, kid accounts, the module office off: 403
    if g.get("auth_via") == "token":
        raise Denied(403, tr("Agents cannot use this endpoint"))
    oid = oid_list or pb_personal(c, uid)
    from ..office.rights import office_can, ofr_level, ofr_rights
    if office_role(c, uid, oid) == "admin":
        return oid, False
    if not office_allowed(c, uid, oid, write=True):  # read-only, accounting, guests: never (they enter no trips)
        if ofr_rights(c, uid, oid) is not None and office_can(c, uid, oid, "travel", "edit"):
            return oid, False  # 2.187.0 C (#2476): or office groups with travel expenses
        if pb_owner(c, oid) is None and ofr_level(c, uid, oid, "travel") == "own":
            return oid, True  # 2.620.0 (#4642): ofr_level = the group's level or "Previous access" (office/rights.py LEGACY_OWN)
    raise Denied(403, tr(OFFICE_ADMIN_ONLY))


def ltc_own_trip(c, oid, tid, uid):
    """2.620.0 (#4642): on the level "own" the linked office trip must be one uid entered (created_by), else 403 -- the
    trip of a shared trip project somebody else made the travel expenses of stays theirs (no id, no second one)."""
    r = c.execute("SELECT created_by FROM office_trips WHERE id=? AND org_id=?", (tid, oid)).fetchone()
    if r is None or r[0] != uid:
        raise Denied(403, tr("The travel expenses of this trip were entered by somebody else"))


def ltc_open(c, uid, lid):
    """-> {trip_id, created, office_id}: the office trip made from trip project lid (the one made before when it still exists)."""
    need_life(c, uid, "travel")
    lr, trip = ltc_trip_list(c, uid, lid)
    oid, own = ltc_office(c, uid, lr["org_id"])
    write_lock(c, f"ltc:{lid}:{oid}")  # a second click at the same time finds the first one's trip
    old = c.execute("""SELECT k.trip_id, t.org_id FROM life_trip_costs k JOIN office_trips t ON t.id=k.trip_id
                       WHERE k.list_id=? AND k.org_id=?""", (lid, oid)).fetchone()
    if old and old[1] != oid:  # 2.173.0 review (#2680): moved to another office area -- no second one
        raise Denied(409, tr("The travel expenses of this trip were moved to another office area"))
    if old:
        if own:
            ltc_own_trip(c, oid, old[0], uid)
        return {"trip_id": old[0], "created": False, "office_id": oid}
    a, z = trip["from"], trip.get("to") or trip["from"]
    row = rk_trip_clean(c, oid, uid, {"date_from": a, "date_to": z, "dest": (trip.get("where") or lr["name"] or "")[:300],
                                      "overnight": z > a, "people": [{"id": uid}], "purpose": "job", "note": lr["name"] or ""})
    period_need_open(c, oid, row.get("date_from"), row.get("date_to"))
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_trips", row)
    tid = insert_id(c, f"INSERT INTO office_trips({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    c.execute("""INSERT INTO life_trip_costs(list_id,org_id,trip_id,created_by,created_at) VALUES(?,?,?,?,?)
                 ON CONFLICT (list_id, org_id) DO UPDATE SET trip_id=excluded.trip_id, created_by=excluded.created_by,
                 created_at=excluded.created_at""", (lid, oid, tid, uid, ts))
    return {"trip_id": tid, "created": True, "office_id": oid}


@app.post("/api/life/trips/<int:lid>/expenses")
def life_trip_expenses(lid):
    """The travel expenses of trip project lid: makes the office trip on the first call (201), later the same one (200)
    -> {trip_id, created, office_id}."""
    c, uid = db(), me()
    out = ltc_open(c, uid, lid)
    if out["created"]:
        bump(c)
    c.commit()
    return jsonify(out), 201 if out["created"] else 200


@app.get("/api/life/trips/<int:lid>/expenses")
def life_trip_expenses_get(lid):
    """2.173.1 A (#2714): the travel expenses already linked to trip project lid in uid's office area -> {trip_id|null}
    (the button then reads "Open travel expenses"). Same gate as the POST: the admins of the office area (2.620.0, #4642: + a member on "own", the own trip only)."""
    c, uid = db(), me()
    need_life(c, uid, "travel")
    lr, _trip = ltc_trip_list(c, uid, lid)
    oid, own = ltc_office(c, uid, lr["org_id"])
    r = c.execute("""SELECT k.trip_id FROM life_trip_costs k JOIN office_trips t ON t.id=k.trip_id AND t.org_id=k.org_id
                     WHERE k.list_id=? AND k.org_id=?""", (lid, oid)).fetchone()
    if r and own:
        ltc_own_trip(c, oid, r[0], uid)  # 2.620.0 (#4642): somebody else's travel expenses: 403 like the POST
    return jsonify({"trip_id": r[0] if r else None})
