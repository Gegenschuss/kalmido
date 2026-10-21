"""Clients (#463, module "clients"): customers of an organisation above the lists, hours + budget, estimate vs. actual, the timesheet per client."""
import math
import re
from datetime import date

from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import insert_id
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc, usettings
from ..accounts.session import me
from ..core.access import Denied, MANAGE_ROLES, list_role, need_feat, tvis, vis_sql
from ..personal.timetrack import BadInput


# ---------------------------------------------------------------- 2.23.0 (#463): clients
# A client (customer) belongs to an organisation (#752): only the people of that organisation see it (and the admins);
# a client without an organisation (an instance without organisations) only its creator and the admins. Kids and agents
# never manage clients (an agent's token reads the clients of the lists it shares, see client_public). Lists belong to at
# most one client (lists.client_id, set by whoever manages the list and sees the client). Everything a client shows --
# its lists, hours, amounts, the estimate -- is computed for the person asking: only the lists (and time entries) they
# see, so two people of one organisation may see different sums. The amount uses the list's hourly rate, else the
# client's. Budget: hours and / or an amount; 80 % turns the bar amber, 100 % red. The timesheet is the time report
# filtered to the client's lists (CSV, printable page).
CLIENT_FIELDS = ("name", "name_extra", "display_name", "icon", "color", "contact", "email", "phone", "address", "note", "rate", "budget_h", "budget_amount",
                 "org_id", "archived")
CLIENT_TEXT_MAX = {"name": 80, "name_extra": 120, "display_name": 80, "icon": 8, "color": 20, "contact": 120, "email": 200, "phone": 60, "address": 500, "note": 4000}
# 2.36.2 (#1021, E): structured billing fields (office & finance; people only, never in agent answers)
CLIENT_BILLING = ("street", "address_extra", "zip", "city", "country", "vat_id", "customer_no", "buyer_reference", "email_invoice", "payment_terms_days")
CLIENT_BILLING_MAX = {"street": 200, "address_extra": 200, "zip": 20, "city": 120, "country": 2, "vat_id": 20, "customer_no": 40, "buyer_reference": 60,
                      "email_invoice": 200}
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def clients_on(c, uid):
    s = usettings(c, uid)
    return "clients" in (s.get("features") or "").split(",")


def _user(c, uid):
    return c.execute("SELECT id, is_admin, kid, kind FROM users WHERE id=?", (uid,)).fetchone()


def _org_boundary(c):
    """2.39.0 (#1209 audit M3): organisations are separate (modes workspaces / multi, unset mode: more than one org) -- then
    the instance admin sees and moves only the clients of their own organisations, like everybody else."""
    from ..accounts.orgs import INSTANCE_ENV
    return INSTANCE_ENV != "shared"  # 2.46.0 (#1592, review fix): always, as core/access.py _boundary_on


def client_rows(c, uid, archived=True):
    """The clients uid may see (rows), sorted by name."""
    u = _user(c, uid)
    if not u or u["kid"] or (u["kind"] or "user") == "agent":
        return []
    q = "SELECT * FROM clients" + ("" if archived else " WHERE archived=0")
    rows = c.execute(q + " ORDER BY archived, lower(name), id").fetchall()
    if u["is_admin"] and not _org_boundary(c):
        return rows
    from ..accounts.orgs import user_orgs
    from ..accounts.orgroles import user_orgs_full
    orgs = set(user_orgs(c, uid)) & set(user_orgs_full(c, uid))  # 2.143.0 A (#2151): not guests / accounting
    return [r for r in rows if (r["org_id"] in orgs) or (r["org_id"] is None and r["created_by"] == uid)]


def need_client(c, cid, uid=None):
    uid = uid or me()
    r = next((x for x in client_rows(c, uid) if x["id"] == cid), None)
    if not r:
        raise Denied(404)
    from ..accounts.orgroles import is_write_request, need_org_write
    if r["org_id"] and is_write_request():
        need_org_write(c, uid, r["org_id"])  # 2.143.0 A (#2151): read-only changes no client of the organisation
    return r


def client_lists(c, uid, cid):
    """Ids of the lists of client cid that uid sees."""
    return [r[0] for r in c.execute(f"SELECT id FROM lists WHERE client_id=? AND id IN {vis_sql()} ORDER BY id", (cid, uid, uid))]


def _num(v, what, lo=0.0, hi=1e9):
    if v in (None, ""):
        return None
    try:
        x = float(str(v).replace(",", "."))
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", what)) from None
    if not math.isfinite(x) or not lo <= x <= hi:
        raise BadInput(tr("Invalid value: {0}", what))
    return round(x, 2)


def clean_client(c, uid, b, new=False):
    """The columns to store from body b (validated); BadInput when something is wrong."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    out = {}
    for k in CLIENT_FIELDS:
        if k not in b:
            continue
        v = b[k]
        if k in CLIENT_TEXT_MAX:
            if v is not None and not isinstance(v, str):
                raise BadInput(tr("Invalid value: {0}", k))
            v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v or "").strip()  # 2.39.0 (#1209 audit M2): no control characters (invoice XML)
            if k != "address" and k != "note":
                v = re.sub(r"\s+", " ", v)
            v = v[:CLIENT_TEXT_MAX[k]]
            if k == "color" and v and not COLOR_RE.fullmatch(v):
                raise BadInput(tr("Invalid value: {0}", k))
            if k == "email" and v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
                raise BadInput(tr("Invalid value: {0}", k))
        elif k == "rate":
            v = _num(v, k, 0, 1e6)
        elif k in ("budget_h", "budget_amount"):
            v = _num(v, k, 0, 1e9)
            v = v or None
        elif k == "archived":
            if not isinstance(v, bool):
                raise BadInput(tr("Invalid value: {0}", k))
            v = 1 if v else 0
        elif k == "org_id":
            if v is not None and (not isinstance(v, int) or isinstance(v, bool)):
                raise BadInput(tr("Invalid value: {0}", k))
            u = _user(c, uid)
            from ..accounts.orgs import user_orgs
            mine = set(user_orgs(c, uid))
            if v is not None and not c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL AND retired_at IS NULL", (v,)).fetchone():  # 2.47.3 (#1360)
                raise BadInput(tr("Invalid value: {0}", k))
            if v is not None and v in mine:
                from ..accounts.orgroles import need_org_write
                need_org_write(c, uid, v)  # 2.143.0 A (#2151)
            if v is not None and v not in mine and not (u["is_admin"] and not _org_boundary(c)):
                raise BadInput(tr("You can only add clients to your own organisations"))
        out[k] = v
    for k in CLIENT_BILLING:
        if k not in b:
            continue
        v = b[k]
        if k == "payment_terms_days":
            if v in (None, ""):
                out[k] = None
                continue
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise BadInput(tr("Invalid value: {0}", k)) from None
            if isinstance(b[k], bool) or not 0 <= v <= 365:
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
            continue
        if v is not None and not isinstance(v, str):
            raise BadInput(tr("Invalid value: {0}", k))
        v = re.sub(r"\s+", " ", (v or "").strip())
        if k == "country":  # 2.40.0 (#1372): ISO 3166-1 alpha-2 only (UK -> GB, EL -> GR)
            from ..office.countries import fk_country
            v = fk_country(v)
        if k == "vat_id":
            v = v.replace(" ", "").upper()
        if len(v) > CLIENT_BILLING_MAX[k]:
            raise BadInput(tr("Invalid value: {0}", k))
        if k == "email_invoice" and v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise BadInput(tr("Invalid value: {0}", k))
        out[k] = v
    if new or "name" in out:
        if not out.get("name"):
            raise BadInput(tr("Name missing"))
    return out


def client_stats(c, uid, cid, lids, month=None):
    """Hours, amounts, estimate of client cid as uid sees it: total and in the month (YYYY-MM, default: this one)."""
    from ..personal.timetrack import time_report
    if not lids:
        # 2.46.2 (#1472): the month is part of the answer also for a client without lists
        m0 = month or local_now().date().strftime("%Y-%m")
        try:
            date.fromisoformat(m0 + "-01")
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "month")) from None
        return {"seconds": 0, "rounded": 0, "amount": 0.0, "month": m0, "month_seconds": 0, "month_amount": 0.0, "estimate_min": 0,
                "estimated": 0, "open": 0, "done": 0}
    q = ",".join("?" * len(lids))
    csv = ",".join(str(x) for x in lids)
    tot = time_report(c, uid, {"scope": "all", "lists": csv})["total"]
    today = local_now().date()
    m = month or today.strftime("%Y-%m")
    try:
        d1 = date.fromisoformat(m + "-01")
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "month")) from None
    d2 = date(d1.year + (d1.month == 12), d1.month % 12 + 1, 1).toordinal() - 1
    mon = time_report(c, uid, {"scope": "all", "lists": csv, "from": d1.isoformat(), "to": date.fromordinal(d2).isoformat()})["total"]
    est = c.execute(f"""SELECT COALESCE(SUM(duration),0), COUNT(duration), SUM(CASE WHEN status=0 THEN 1 ELSE 0 END), SUM(CASE WHEN status!=0 THEN 1 ELSE 0 END) FROM tasks
                        WHERE list_id IN ({q}) AND deleted_at IS NULL AND ms=0 AND {tvis(c, uid)}""", lids).fetchone()
    return {"seconds": tot["seconds"], "rounded": tot["rounded"], "amount": tot["amount"], "month": m,
            "month_seconds": mon["seconds"], "month_amount": mon["amount"], "estimate_min": est[0] or 0, "estimated": est[1] or 0,
            "open": est[2] or 0, "done": est[3] or 0}


def budget_state(st, cl):
    """{pct_h, pct_amount, level: ok | warn | over | none} of a client's budget (80 % warn, 100 % over)."""
    ph = round(st["rounded"] / 3600 / cl["budget_h"] * 100) if cl["budget_h"] else None
    pa = round(st["amount"] / cl["budget_amount"] * 100) if cl["budget_amount"] else None
    top = max([x for x in (ph, pa) if x is not None], default=None)
    return {"pct_h": ph, "pct_amount": pa, "level": "none" if top is None else "over" if top >= 100 else "warn" if top >= 80 else "ok"}


def client_public(c, uid, r, stats=False, month=None):
    lids = client_lists(c, uid, r["id"])
    org = c.execute("SELECT name FROM orgs WHERE id=?", (r["org_id"],)).fetchone() if r["org_id"] else None
    u = _user(c, uid)
    d = {k: r[k] for k in ("id", "name", "name_extra", "display_name", "icon", "color", "contact", "email", "phone", "address", "note", "rate", "budget_h",
                           "budget_amount", "org_id", "created_by", "created_at", "updated_at")}
    d.update(archived=bool(r["archived"]), org_name=org[0] if org else "", lists=lids,
             can_delete=bool(u and (u["is_admin"] or r["created_by"] == uid)), label=cdn_label(c, uid, r))
    from ..office.contacts_cl import fk_contacts
    d["contacts"] = fk_contacts(c, r["id"])  # 2.40.0 (#1380): the contact persons, the default first ("contact" = its name)
    if u and (u["kind"] or "user") == "agent":  # 2.81.0 (#1466): agents get name / role only per contact person, no mail / phone / link
        d["contacts"] = [{k: x[k] for k in ("id", "name", "role", "is_default")} for x in d["contacts"]]
    if u and (u["kind"] or "user") != "agent":  # 2.36.2: billing fields for people only
        d["billing"] = {k: (r[k] if k in r.keys() else None) for k in CLIENT_BILLING}
    if stats:
        st = client_stats(c, uid, r["id"], lids, month)
        d["stats"] = st
        d["budget"] = budget_state(st, r)
    return d


def clients_brief(c, uid):
    """/api/state: [{id, name, icon, color, org_id, archived, lists}] of the clients uid sees (module on).
    2.56.3 (#1842): org_id too - the office's client picker keeps only the clients of the office's org (null = private)."""
    if not clients_on(c, uid):
        return []
    rows = client_rows(c, uid)
    labels = cdn_labels(rows)  # 2.97.0 B (#1951): the name pickers show
    return [{"id": r["id"], "name": r["name"], "name_extra": r["name_extra"], "display_name": r["display_name"], "label": labels[r["id"]], "icon": r["icon"],
             "color": r["color"], "org_id": r["org_id"], "archived": bool(r["archived"]), "lists": client_lists(c, uid, r["id"])}
            for r in rows]


def _gate(c):
    u = g.user
    if u["kid"] or (u["kind"] or "user") == "agent":
        raise Denied(403, tr("Only people can manage clients"))
    need_feat("clients")


@app.get("/api/clients")
def clients_list():
    """The clients I see with their lists, hours, amounts and budget (?month=YYYY-MM for the month's sums; ?archived=1
    with the archived ones). Also GET /api/v1/clients."""
    c = db()
    uid = me()
    if (g.user["kind"] or "user") != "agent":
        need_feat("clients")
    arch = request.args.get("archived") in ("1", "true")
    return jsonify(clients=[client_public(c, uid, r, stats=True, month=request.args.get("month"))
                            for r in client_rows(c, uid, archived=arch)])


@app.get("/api/clients/<int:cid>")
def client_get(cid):
    c = db()
    uid = me()
    if (g.user["kind"] or "user") != "agent":
        need_feat("clients")
    r = need_client(c, cid, uid)
    d = client_public(c, uid, r, stats=True, month=request.args.get("month"))
    # estimate vs. actual per list (#330): the sum of the tasks' durations next to the tracked time
    per = []
    for lid in d["lists"]:
        l = c.execute("SELECT id, name, kind, rate, status FROM lists WHERE id=?", (lid,)).fetchone()
        st = client_stats(c, uid, cid, [lid], request.args.get("month"))
        per.append({"id": lid, "name": l["name"], "kind": l["kind"], "rate": l["rate"], "status": l["status"], **st})
    d["per_list"] = per
    from .clientmerge import clm_history
    if (g.user["kind"] or "user") != "agent":  # 2.63.0 B (#1513): the client's reports (customer portal) the person sees
        from .portal import pt_client_tickets
        d["tickets"] = pt_client_tickets(c, uid, cid)
        d["merges"] = clm_history(c, uid, r)  # 2.66.0 B (#1835): the merges into this client (people only)
    return jsonify(d)


@app.post("/api/clients")
def client_create():
    """{name, icon?, color?, contact?, contacts?, email?, phone?, address?, note?, rate?, budget_h?, budget_amount?, org_id?} -> 201.
    org_id: one of my organisations (default: my first one). contacts (2.40.0): [{name, role?, email?, phone?, is_default?}]."""
    c = db()
    uid = me()
    _gate(c)
    f = clean_client(c, uid, body(), new=True)
    if "org_id" not in f:
        from ..accounts.orgroles import user_orgs_full
        mine = user_orgs_full(c, uid, write=True)  # 2.143.0 A (#2151): never into an organisation where uid only reads
        f["org_id"] = mine[0] if mine else None
    ts = iso(now_utc())
    f.update(created_by=uid, created_at=ts, updated_at=ts)
    cid = insert_id(c, f"INSERT INTO clients({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values()))
    _contacts_from_body(c, cid, f.get("org_id"), body(), f)
    if f.get("address"):
        cdn_fill_address(c, cid)
    bump(c)
    c.commit()
    return jsonify(client_public(c, uid, need_client(c, cid, uid), stats=True)), 201


def _contacts_from_body(c, cid, oid, b, f):
    """2.40.0 (#1380): {contacts: [...]} replaces the client's contact persons; else the old field contact names the default."""
    from ..office.contacts_cl import fk_contact_field, fk_put
    if isinstance(b, dict) and b.get("contacts") is not None:
        fk_put(c, cid, oid, b["contacts"])
    elif "contact" in f:
        fk_contact_field(c, cid, oid, f["contact"])


@app.patch("/api/clients/<int:cid>")
def client_update(cid):
    c = db()
    uid = me()
    _gate(c)
    old = need_client(c, cid, uid)
    from ..office.undo import oun_post, oun_pre
    oun_pre(c, uid, None, "client", cid)  # 2.111.0 A (#2233): the state before, for "Saved · Undo"
    f = clean_client(c, uid, body())
    if "org_id" in f and f["org_id"] == old["org_id"]:
        f.pop("org_id")  # unchanged (the dialog sends it with every save)
    if "org_id" in f:
        h6c_client_move_ok(c, uid, old)
        if old["org_id"] and c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND client_id=? AND locked_at IS NOT NULL LIMIT 1",
                                       (old["org_id"], cid)).fetchone():  # 2.126.0 A (#1979 F7): its finalised documents keep it
            raise Denied(409, tr("Finalised documents of this organisation refer to this client, so it stays here. “Move to another workspace…” in the office takes a copy along."))
    if f:
        f["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE clients SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), cid])
        if "org_id" in f:  # 2.40.0 (#1380, review): the contacts move with their client into the other workspace
            c.execute("UPDATE office_client_contacts SET org_id=? WHERE client_id=?", (f["org_id"], cid))
            from ..office.contacts_cl import ckl_unlink_client
            ckl_unlink_client(c, cid)  # 2.59.0 (#1735): the address books stay in the old workspace
            if _org_boundary(c):  # 2.86.0 (N11): the lists of the old workspace stay there and lose the client
                c.execute("UPDATE lists SET client_id=NULL WHERE client_id=? AND org_id IS DISTINCT FROM ?", (cid, f["org_id"]))
    _contacts_from_body(c, cid, need_client(c, cid, uid)["org_id"], body(), f)
    if f.get("address"):
        cdn_fill_address(c, cid)
    bump(c)
    oun_post(c)
    c.commit()
    return jsonify(client_public(c, uid, need_client(c, cid, uid), stats=True))


def h6c_client_move_ok(c, uid, r):
    """2.86.0 (N11): moving a client into another workspace takes its creator or an admin of the workspace it is in now
    (clean_client already allows only the mover's own organisations as the target)."""
    if r["created_by"] == uid or (g.user["is_admin"] and not _org_boundary(c)):
        return
    from ..accounts.orgs import is_org_admin
    if r["org_id"] and is_org_admin(c, uid, r["org_id"]):
        return
    raise Denied(403, tr("Only the person who created the client or an admin of its organisation can move it"))


@app.delete("/api/clients/<int:cid>")
def client_delete(cid):
    """Only its creator or an admin; the lists stay (they lose the client)."""
    c = db()
    uid = me()
    _gate(c)
    r = need_client(c, cid, uid)
    if not (g.user["is_admin"] or r["created_by"] == uid):
        return err(tr("Only the person who created the client or an admin can delete it"), 403)
    from .clients_bulk import ms_client_in_use
    if ms_client_in_use(c, cid):  # 2.152.0 C (#2168): documents / contracts keep their client (records) -> archived, like the bulk delete
        if not r["archived"]:
            c.execute("UPDATE clients SET archived=1, updated_at=? WHERE id=?", (iso(now_utc()), cid))
            bump(c)
            c.commit()
        return jsonify(ok=True, archived=True, message=tr("The client is used in quotations, invoices or contracts and was archived instead of deleted."))
    c.execute("UPDATE lists SET client_id=NULL WHERE client_id=?", (cid,))
    c.execute("DELETE FROM clients WHERE id=?", (cid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


def list_client_set(c, lid, cid):
    """lists.client_id of list lid (the owner / list admins; the client must be one the person sees). None = no client."""
    role = list_role(c, lid)
    if not role:
        raise Denied(404)
    if role not in MANAGE_ROLES:
        raise Denied(403, tr("Only the owner and list admins can change the client"))
    if cid is not None:
        if not isinstance(cid, int) or isinstance(cid, bool):
            raise BadInput(tr("Invalid value: {0}", "client_id"))
        cl = need_client(c, cid)
        # 2.86.0 (N11): a client only hangs on lists of its own workspace (organisation boundary)
        from ..accounts.orgs import list_org
        if _org_boundary(c) and (cl["org_id"] or None) != (list_org(c, lid) or None):
            raise Denied(409, tr("The client belongs to another workspace than this list"))
    c.execute("UPDATE lists SET client_id=? WHERE id=?", (cid, lid))



# ---------------------------------------------------------------- 2.97.0 B (#1951): display name, the address from fixed fields
# display_name is the name in pickers and lists only; documents, e-invoices and the letterhead always print "name". Without
# a display name, clients of one workspace with the same name get their city appended ("Foo (Basel)"), the country when
# the cities are the same too. The free address text left the client form: a client with it and no street / postcode /
# city gets those split from it once (start and every write of "address", which old API callers still send); the text
# itself stays in its column.
def cdn_labels(rows):
    """{client id: label} of the rows (the clients one person sees)."""
    out, groups = {}, {}
    for r in rows:
        dn = (r["display_name"] if "display_name" in r.keys() else "") or ""
        out[r["id"]] = dn or cdn_name1(r)
        if not dn:
            area = r["org_id"] if r["org_id"] is not None else ("p", r["created_by"])
            groups.setdefault((area, cdn_name1(r).strip().lower()), []).append(r)
    for rs in groups.values():
        if len(rs) < 2:
            continue
        cities = [((r["city"] if "city" in r.keys() else "") or "").strip() for r in rs]
        lows = [x.lower() for x in cities]
        for r, city in zip(rs, cities):
            country = ((r["country"] if "country" in r.keys() else "") or "").strip()
            twin = [rs[i] for i, x in enumerate(lows) if x == city.lower()]
            extra = city if city and len(twin) == 1 else country if country and \
                sum(1 for x in twin if (x["country"] or "").strip() == country) == 1 else city or country
            if extra:
                out[r["id"]] = f"{cdn_name1(r)} ({extra})"
    return out


def cdn_name1(r):
    """2.99.0 D (#2188): the client's name on one line: "name - name addition" (lists, search, the e-invoice buyer name BT-44)."""
    ex = ((r["name_extra"] if "name_extra" in r.keys() else "") or "").strip()
    return f"{r['name']} - {ex}" if ex else r["name"]


def cdn_label(c, uid, r):
    """The label of client row r for uid (the labels of all their clients, once per request)."""
    try:
        cache = g.setdefault("cdn_labels", {})
    except RuntimeError:  # outside a request
        cache = {}
    if uid not in cache:
        cache[uid] = cdn_labels(client_rows(c, uid))
    dn = (r["display_name"] if "display_name" in r.keys() else "") or ""
    return cache[uid].get(r["id"]) or dn or r["name"]


def cdn_split_free(r):
    """{street, zip, city, country?} split from the free address of client row r (the empty ones left out)."""
    from ..office.countries import fk_country_code
    from ..office.legacyimport import fi_split_address
    lines = [x.strip() for x in (r["address"] or "").replace("\r", "").split("\n") if x.strip()]
    if not lines:
        return {}
    name = (r["name"] or "").strip()
    if lines[0].lower() != name.lower():
        lines.insert(0, name)  # the parser reads a whole address block, the name on top
    sp = fi_split_address("\n".join(lines))
    f = {k: re.sub(r"\s+", " ", sp.get(k) or "").strip()[:CLIENT_BILLING_MAX[k]] for k in ("street", "zip", "city")}
    f = {k: v for k, v in f.items() if v}
    cc = fk_country_code(sp.get("country"))
    if f and cc and not (r["country"] or "").strip():
        f["country"] = cc
    return f


def cdn_fill_address(c, cid):
    """Client cid: street / postcode / city from its free address when all three are empty. -> True when filled."""
    r = c.execute("SELECT id, name, address, street, zip, city, country FROM clients WHERE id=?", (cid,)).fetchone()
    if not r or any((r[k] or "").strip() for k in ("street", "zip", "city")) or not (r["address"] or "").strip():
        return False
    f = cdn_split_free(r)
    if not f:
        return False
    c.execute(f"UPDATE clients SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), cid])
    return True


def cdn_backfill(c):
    """Start: every client with a free address and no street / postcode / city (idempotent; nothing filled is touched)."""
    ids = [r[0] for r in c.execute("SELECT id FROM clients WHERE address<>'' AND street='' AND zip='' AND city=''")]
    return sum(1 for cid in ids if cdn_fill_address(c, cid))
