"""2.140.0 B (#2136): a private device <-> a piece of office equipment -- take one over as the other and keep a link.

A device of "Home & life" is a task (fam kind device: name, model, bought, warranty, serial, price; the task's text = the
note); office equipment is a row of office_equipment (office/model.py MD "equipment": name, serial_no, purchase_date,
purchase_net ... admins only). Taking over COPIES the matching fields once and stores a link (life_device_links, the
person's own row): no live mirror; "update from there" copies them again on request. Both sides show "linked with ..."
with a jump there, and the link can be removed.
Rights like the normal way: a device needs the module "home" and the right to change its list; office equipment is made
only in an office area where the person is admin (the own personal office, or an organisation as its admin) and never by an
agent or a kid (office_gate). The link never binds anything to an organisation: when the person leaves it, loses the role
or the other side is deleted, the link is reported as broken (state noaccess / gone, without any name of the other side)
and can be removed; nothing fails. Another person's side is never shown: a link is only ever read by its own person.
Copied fields:  device -> equipment: name (+ model), serial, bought -> purchase day; the price only as the net price the
person confirms in the dialog (the device's price is what was paid). equipment -> device: name, serial, purchase day,
net price -> price, vendor -> the note."""
import json

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, iso, now_utc
from ..core.i18n import tr
from ..core.access import Denied, need_task
from ..accounts.session import me
from ..personal.timetrack import BadInput
from ..tasks.tasks import one_task
from ..tasks.validation import as_int, log_act
from .model import _cost, _dump, _name, device_create, life_clean_fam, need_life

DL_ORIGINS = ("device", "equipment")


def _ts():
    return iso(now_utc())


def _done(c, out, code=200):
    bump(c)
    c.commit()
    return jsonify(out), code


def _fam(t):
    try:
        f = json.loads(t["fam"] or "{}")
    except ValueError:
        f = {}
    return f if isinstance(f, dict) else {}


def _device(c, uid, tid, write=True):
    """The device task tid (visible to uid, changeable when write) and its fam; 404 for anything else."""
    need_life(c, uid, "home")
    need_task(c, tid, write)
    t = c.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
    f = _fam(t) if t else {}
    if not t or f.get("kind") != "device":
        raise Denied(404)
    return t, f


def _office_ws(c, oid):
    """The workspace setting that shows office area oid ("private" for the personal office, else org:<id>)."""
    from ..office.model import pb_owner
    return "private" if pb_owner(c, oid) else f"org:{oid}"


def _office_name(c, oid):
    from ..office.model import pb_owner
    if pb_owner(c, oid):
        return tr("My own office")
    r = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()
    return r[0] if r else ""


def dl_offices(c, uid):
    """The office areas uid may make equipment in: [{id, name, ws, personal}] -- the own personal office (id 0 while it does
    not exist yet) and every organisation where uid is admin. Empty without the module "office"."""
    from ..office.model import office_on, pb_personal
    from ..accounts.orgs import org_role, user_orgs
    if not office_on(c, uid):
        return []
    out = [{"id": pb_personal(c, uid, create=False) or 0, "name": tr("My own office"), "ws": "private", "personal": True}]
    for oid in user_orgs(c, uid):
        if org_role(c, uid, oid) == "admin":
            out.append({"id": oid, "name": _office_name(c, oid), "ws": f"org:{oid}", "personal": False})
    return out


def _equip(c, uid, oid, eid):
    """(row, role) of equipment eid in office oid when uid still has a role there, else (None, None) / (None, role)."""
    from ..office.model import office_role, office_row
    if not oid or not eid:
        return None, None
    role = office_role(c, uid, oid)
    if not role:
        return None, None
    try:
        return office_row(c, oid, "equipment", eid), role
    except Denied:
        return None, role


def _link(c, uid, lid):
    r = c.execute("SELECT * FROM life_device_links WHERE id=? AND user_id=?", (lid, uid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def _device_side(c, uid, l):
    """The device of link l as the equipment side shows it: {state ok | gone, task_id?, name?}."""
    if not l["task_id"]:
        return {"state": "gone"}
    t = c.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (l["task_id"],)).fetchone()
    try:
        if not t:
            raise Denied(404)
        need_task(c, t["id"], False)
    except Denied:
        return {"state": "gone"}
    f = _fam(t)
    return {"state": "ok", "task_id": t["id"], "list_id": t["list_id"], "name": f.get("name") or t["title"]}


def _equip_side(c, uid, l):
    """The equipment of link l as the device side shows it: {state ok | noaccess | gone, ...}; without a role in the office
    nothing of it is shown (not even the office's name)."""
    if not l["office_id"] or not l["equipment_id"]:
        return {"state": "gone"}
    r, role = _equip(c, uid, l["office_id"], l["equipment_id"])
    if role is None:
        return {"state": "noaccess"}
    if r is None:
        return {"state": "gone"}
    return {"state": "ok", "office_id": l["office_id"], "office_name": _office_name(c, l["office_id"]), "ws": _office_ws(c, l["office_id"]),
            "equipment_id": r["id"], "name": r["name"], "archived": bool(r.get("archived")), "can_write": role == "admin"}


def dl_public(c, uid, l, side):
    out = {"id": l["id"], "origin": l["origin"], "created_at": l["created_at"], "updated_at": l["updated_at"]}
    out["other"] = _equip_side(c, uid, l) if side == "device" else _device_side(c, uid, l)
    return out


def _insert_link(c, uid, tid, oid, eid, origin):
    """The callers checked that neither side carries a link of the person yet (unique indexes as the floor)."""
    ts = _ts()
    c.execute("INSERT INTO life_device_links(user_id, task_id, office_id, equipment_id, origin, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
              (uid, tid, oid, eid, origin, ts, ts))
    return c.execute("SELECT * FROM life_device_links WHERE user_id=? AND task_id=?", (uid, tid)).fetchone()


def _from_device(f, b=None):
    """The equipment fields of a device fam (b: what the person confirmed in the dialog: name, purchase_net)."""
    b = b or {}
    name = b.get("name") if isinstance(b.get("name"), str) and b.get("name").strip() else \
        " ".join(x for x in (f.get("name") or "", f.get("model") or "") if x)
    out = {"name": name.strip(), "serial_no": f.get("serial") or "", "purchase_date": f.get("bought") or ""}
    if "purchase_net" in b:
        out["purchase_net"] = b.get("purchase_net")
    return out


def _from_equip(r):
    """The device fields of an equipment row."""
    price = None
    if r.get("purchase_net") not in (None, ""):
        try:
            price = _cost(str(r["purchase_net"]))
        except BadInput:
            price = None
    return {"name": (r.get("name") or "")[:100], "serial": (r.get("serial_no") or "")[:100], "bought": r.get("purchase_date") or "",
            "price": price, "vendor": r.get("vendor") or ""}


# ---------------------------------------------------------------- the device side (Home & life)
@app.get("/api/life/devices/<int:tid>/link")
def dl_device_get(tid):
    """{link: null | {id, origin, other: {state ok | noaccess | gone, office_name?, ws?, equipment_id?, name?, ...}},
    offices: the office areas the device can go to (the own office, organisations as admin)}."""
    c, uid = db(), me()
    _device(c, uid, tid, write=False)
    l = c.execute("SELECT * FROM life_device_links WHERE task_id=? AND user_id=?", (tid, uid)).fetchone()
    taken = l is None and c.execute("SELECT 1 FROM life_device_links WHERE task_id=?", (tid,)).fetchone()  # another person's link
    return jsonify(link=dl_public(c, uid, l, "device") if l else None, offices=[] if l or taken else dl_offices(c, uid))


@app.post("/api/life/devices/<int:tid>/to-office")
def dl_device_to_office(tid):
    """{office_id (0 = the own office, made on first use), name?, purchase_net?} -> 201 {link, equipment_id}: a new piece of
    equipment in that office area from the device's fields, linked with it. Admins of the area only (403 otherwise)."""
    from ..office.model import office_create, office_gate, office_role, pb_personal
    from ..office.ledger import ofx_log
    c, uid = db(), me()
    office_gate(c)
    _t, f = _device(c, uid, tid)
    if c.execute("SELECT 1 FROM life_device_links WHERE task_id=?", (tid,)).fetchone():  # also by another person of a shared list
        raise BadInput(tr("This device is linked already"))
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    oid = as_int(b.get("office_id", 0), "office_id", 0)
    if oid == 0:
        oid = pb_personal(c, uid)
    if office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only admins of this office can add equipment"))
    vals = _from_device(f, b)
    vals["name"] = _name(vals["name"], need=True, n=200)
    r = office_create(c, oid, "equipment", vals)
    ofx_log(c, oid, "create", target="equipment", detail={"id": r["id"], "after": r})
    l = _insert_link(c, uid, tid, oid, r["id"], "device")
    log_act(c, tid, "updated", uid=uid)
    return _done(c, {"link": dl_public(c, uid, l, "device"), "equipment_id": r["id"]}, 201)


# ---------------------------------------------------------------- the equipment side (office)
def _ectx():
    from ..office.model import office_gate, office_org
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid)


@app.get("/api/office/equipment/<int:rid>/link")
def dl_equip_get(rid):
    """The own link of equipment rid of the current office area: {link: null | {id, origin, other: {state ok | gone,
    task_id?, name?}}, can_take: the module "home" is on and the person is admin here}. Links of other people never show."""
    from ..office.model import office_role, office_row
    from .model import feat_on
    c, uid, oid = _ectx()
    office_row(c, oid, "equipment", rid)  # 404 outside the area
    l = c.execute("SELECT * FROM life_device_links WHERE office_id=? AND equipment_id=? AND user_id=?", (oid, rid, uid)).fetchone()
    return jsonify(link=dl_public(c, uid, l, "equipment") if l else None,
                   can_take=bool(feat_on(c, uid, "home") and office_role(c, uid, oid) == "admin"))


@app.post("/api/office/equipment/<int:rid>/to-device")
def dl_equip_to_device(rid):
    """{list_id?} -> 201 {link, task}: a private device (Home & life) from equipment rid of the current office area, linked
    with it. Office admins only (they see the purchase fields); needs the module "home"."""
    from ..office.model import office_org, office_row
    c, uid, _oid = _ectx()
    oid = office_org(c, uid, admin=True)
    r = office_row(c, oid, "equipment", rid)
    if c.execute("SELECT 1 FROM life_device_links WHERE office_id=? AND equipment_id=? AND user_id=?", (oid, rid, uid)).fetchone():
        raise BadInput(tr("This device is linked already"))
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    v = _from_equip(r)
    note = tr("Bought from: {0}", v["vendor"]) if v["vendor"] else ""
    tid = device_create(c, uid, {"name": v["name"] or tr("Device"), "bought": v["bought"] or None, "serial": v["serial"] or None,
                                 "price": v["price"], "note": note, **({"list_id": b["list_id"]} if b.get("list_id") not in (None, "") else {})})
    l = _insert_link(c, uid, tid, oid, rid, "equipment")
    return _done(c, {"link": dl_public(c, uid, l, "equipment"), "task": one_task(c, tid)}, 201)


# ---------------------------------------------------------------- the link itself (its own person only)
@app.post("/api/life/device-links/<int:lid>/pull")
def dl_pull(lid):
    """{into: device | equipment} -> {link}: copies the fields of the other side into this one again (no mirror; the
    rights of the side written to as usual). 409 when the other side is gone / out of reach."""
    from ..office.model import office_gate, office_update
    from ..office.ledger import ofx_diff, ofx_log
    c, uid = db(), me()
    l = _link(c, uid, lid)
    b = body()
    into = b.get("into") if isinstance(b, dict) else None
    if into not in DL_ORIGINS:
        raise BadInput(tr("Invalid value: {0}", "into"))
    if not l["task_id"] or not l["equipment_id"] or not l["office_id"]:
        raise Denied(409, tr("The linked entry is gone"))
    office_gate(c)
    r, role = _equip(c, uid, l["office_id"], l["equipment_id"])
    if r is None:
        raise Denied(409, tr("The linked entry is gone") if role else tr("You have no access to the linked entry any more"))
    if into == "device":
        if role != "admin":  # 2.140.0 review (F1): purchase price / serial / vendor are admin columns; a demoted admin pulls none
            raise Denied(403, tr("Only admins of this office can change equipment"))
        from ..collab.liste2e import le2a_gen_refuse
        t, f = _device(c, uid, l["task_id"])
        le2a_gen_refuse(c, t["list_id"])  # 2.140.0 review (F2): no plain text into a list with the end-to-end lock
        v = _from_equip(r)
        nf = dict(f, name=v["name"] or f.get("name") or "")
        for k in ("serial", "bought"):
            if v[k]:
                nf[k] = v[k]
            else:
                nf.pop(k, None)
        if v["price"] is not None:
            nf["price"] = v["price"]
        nf = json.loads(life_clean_fam(nf))
        if f.get("lead") is not None:
            nf["lead"] = f["lead"]
        title = t["title"] if f.get("warranty") or t["title"] != (f.get("name") or "") else nf["name"]
        c.execute("UPDATE tasks SET fam=?, title=?, updated_at=? WHERE id=?", (_dump(nf), title, _ts(), t["id"]))
        log_act(c, t["id"], "updated", uid=uid)
    else:
        if role != "admin":
            raise Denied(403, tr("Only admins of this office can change equipment"))
        _t, f = _device(c, uid, l["task_id"], write=False)
        vals = _from_device(f)
        vals["name"] = _name(vals["name"], need=True, n=200)
        nr = office_update(c, l["office_id"], "equipment", r["id"], vals)
        diff = ofx_diff(r, nr)
        diff["after"].pop("updated_at", None)
        diff["before"].pop("updated_at", None)
        if diff["after"]:
            ofx_log(c, l["office_id"], "update", target="equipment", detail={"id": r["id"], **diff})
    c.execute("UPDATE life_device_links SET updated_at=? WHERE id=?", (_ts(), lid))
    l = _link(c, uid, lid)
    return _done(c, {"link": dl_public(c, uid, l, into)})


@app.delete("/api/life/device-links/<int:lid>")
def dl_delete(lid):
    """Removes the own link (both entries stay as they are) -- also when the other side is out of reach."""
    c, uid = db(), me()
    _link(c, uid, lid)
    c.execute("DELETE FROM life_device_links WHERE id=? AND user_id=?", (lid, uid))
    return _done(c, {"ok": True})
