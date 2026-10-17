"""Office & finance (2.36.1, #1021): the web routes of the module's settings, country packs and master data.
Every route: office_gate (no agents, no kids, feature on) + office_org (the organisation one works in; 400 without one).
Writes to settings / master data / import need the organisation's admin; members read. No /api/v1 and no MCP tool in
stage 1 (before the security audit): agents never reach this module."""
import json

from flask import jsonify, request, Response

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .packs import office_pack, office_pack_codes, office_pack_validate
from .model import (
    MD_KINDS, office_create, office_delete, office_export, office_gate, office_import, office_org, office_role, office_row,
    office_rows, office_seed_texts, office_settings, office_settings_clean, office_settings_save, office_update, office_number_format,
    office_number_next, office_scheme_clean, office_scheme_period, sr_public, pb_info,
)
from .ledger import ofx_company, ofx_company_clean, ofx_company_save, ofx_diff, ofx_log

IMPORT_MAX = 4 * 1024 * 1024


def _ctx(admin=False):
    """-> (c, uid, oid) after the gate; admin=True needs the organisation's admin."""
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=admin)
    return c, uid, oid


@app.get("/api/office/settings")
def office_settings_get():
    """The module's settings of my organisation + my role + the pack's tax rates. First call seeds the text blocks."""
    c, uid, oid = _ctx()
    if office_seed_texts(c, oid):
        c.commit()
    s = office_settings(c, oid)
    pack = office_pack(s["pack"]) or office_pack("DE")
    return jsonify(settings=s, company_fields=ofx_company(c, oid), org_id=oid, role=office_role(c, uid, oid), pack={"code": pack["code"], "name": pack["name"], "tax": pack["tax"],
                                                                               "formats": pack["formats"], "currency": pack["currency"]},
                   number_preview=office_number_next(c, oid, "offer", s["offer_scheme"], peek=True)[0],
                   industry=_industry(s), **pb_info(c, uid, oid))


def _industry(s):
    """2.47.0 (#1216): the industry packs switched on (labels, defaults, suggested crew functions) for the client."""
    from .sheet import dk_pack, dk_pack_public, dk_packs_on
    return [dk_pack_public(dk_pack(x)) for x in dk_packs_on(s)]


@app.put("/api/office/settings")
def office_settings_put():
    """Org admin. Partial body with the keys of office_settings.data (logo: see POST /api/office/logo); 2.36.2:
    company_fields = the structured company data (office_company, partial)."""
    c, uid, oid = _ctx(admin=True)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    cur = office_settings(c, oid)
    new = office_settings_clean(c, oid, b, cur)
    if "company_fields" in b:
        cf = ofx_company(c, oid)
        ncf = ofx_company_clean(b["company_fields"], cf)
        diff = ofx_diff(cf, ncf)
        if diff["after"]:
            ofx_company_save(c, oid, ncf)
            ofx_log(c, oid, "update", target="company", detail=diff)
    office_settings_save(c, oid, new)
    diff = ofx_diff(cur, new)
    if diff["after"]:
        ofx_log(c, oid, "update", target="settings", detail=diff)
    c.commit()
    return jsonify(settings=office_settings(c, oid), company_fields=ofx_company(c, oid), number_preview=office_number_next(c, oid, "offer", new["offer_scheme"], peek=True)[0])


@app.get("/api/office/number-preview")
def office_number_preview():
    """?scheme=…&kind=offer|invoice|credit|reminder -> {preview, valid, error, yearly} (the settings page shows the next
    number while typing; 2.40.0 (#1382): every scheme with its own counter, example values for project / client / initials,
    yearly = the counter starts again every year)."""
    c, uid, oid = _ctx()
    kind = request.args.get("kind") or "offer"
    if kind not in ("offer", "invoice", "credit", "reminder"):
        kind = "offer"
    try:
        scheme = office_scheme_clean(request.args.get("scheme") or "")
    except BadInput as e:
        return jsonify(preview="", valid=False, error=str(e))
    pv = office_number_next(c, oid, kind, scheme, peek=True, project=tr("Project"), client=tr("Client"), initials="AB")[0]
    return jsonify(preview=pv, valid=True, yearly=bool(office_scheme_period(scheme)))


@app.get("/api/office/packs")
def office_packs_get():
    c, uid, oid = _ctx()
    out = []
    for code in office_pack_codes():
        p = office_pack(code)
        if p:
            out.append({"code": p["code"], "name": p["name"], "name_en": p.get("name_en", p["name"]), "currency": p["currency"],
                        "version": p["version"], "community": p.get("community", False), "tax": p["tax"]})
    return jsonify(packs=out)


@app.get("/api/office/packs/<code>")
def office_pack_get(code):
    c, uid, oid = _ctx()
    p = office_pack(code)
    if not p:
        raise Denied(404)
    return jsonify(pack=p)


@app.post("/api/office/packs/validate")
def office_pack_check():
    """Org admin: {pack: {...}} -> {problems: [...]} (a dry run for community packs; nothing is installed in stage 1)."""
    c, uid, oid = _ctx(admin=True)
    b = body()
    return jsonify(problems=office_pack_validate(b.get("pack") if isinstance(b, dict) else None))


# ---- master data: one set of routes per kind (services, equipment, sets, texts, contracts; 2.47.0: roles, crew)
def _kind(kind):
    if kind not in MD_KINDS:
        raise Denied(404)
    return kind


@app.get("/api/office/<kind>")
def office_rows_get(kind):
    """?q=search &archived=1 (else only live rows)."""
    _kind(kind)
    c, uid, oid = _ctx()
    a = request.args
    adm = office_role(c, uid, oid) == "admin"  # 2.47.0 (#1649): members never get purchase prices / markups
    return jsonify(items=[sr_public(kind, r, adm) for r in office_rows(c, oid, kind, archived=a.get("archived") == "1", q=a.get("q") or "")])


@app.post("/api/office/<kind>")
def office_row_post(kind):
    _kind(kind)
    c, uid, oid = _ctx(admin=True)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    r = office_create(c, oid, kind, b)
    ofx_log(c, oid, "create", target=kind, detail={"id": r["id"], "after": r})
    c.commit()
    return jsonify(r), 201


@app.get("/api/office/<kind>/<int:rid>")
def office_row_get(kind, rid):
    _kind(kind)
    c, uid, oid = _ctx()
    return jsonify(sr_public(kind, office_row(c, oid, kind, rid), office_role(c, uid, oid) == "admin"))  # 2.47.0 (#1649)


@app.patch("/api/office/<kind>/<int:rid>")
def office_row_patch(kind, rid):
    _kind(kind)
    c, uid, oid = _ctx(admin=True)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    old = office_row(c, oid, kind, rid)
    r = office_update(c, oid, kind, rid, b)
    diff = ofx_diff(old, r)
    diff["after"].pop("updated_at", None)
    diff["before"].pop("updated_at", None)
    if diff["after"]:
        ofx_log(c, oid, "update", target=kind, detail={"id": r["id"], **diff})
    c.commit()
    return jsonify(r)


@app.delete("/api/office/<kind>/<int:rid>")
def office_row_delete(kind, rid):
    """Deletes; a row used in documents / contracts / sets is archived instead -> {ok, result: deleted|archived}."""
    _kind(kind)
    c, uid, oid = _ctx(admin=True)
    old = office_row(c, oid, kind, rid)
    res = office_delete(c, oid, kind, rid)
    ofx_log(c, oid, "delete" if res == "deleted" else "archive", target=kind, detail={"id": old["id"], "before": old})
    c.commit()
    return jsonify(ok=True, result=res)


# ---- import / export of the master data (JSON file)
@app.get("/api/office/export")
def office_export_get():
    c, uid, oid = _ctx()
    d = office_export(c, oid, office_role(c, uid, oid) == "admin")  # 2.47.0 (#1649)
    ofx_log(c, oid, "export", target="master_data")
    c.commit()
    data = json.dumps(d, ensure_ascii=False, indent=1)
    return Response(data, mimetype="application/json", headers={"Content-Disposition": "attachment; filename=\"office-master-data.json\""})


@app.post("/api/office/import")
def office_import_post():
    """Org admin. Body: the export's JSON (or multipart file 'file'); ?overwrite=1 updates rows that exist by name."""
    c, uid, oid = _ctx(admin=True)
    f = request.files.get("file")
    if f is not None:
        raw = f.read(IMPORT_MAX + 1)
        if len(raw) > IMPORT_MAX:
            return err(tr("File too large"), 413)
        try:
            d = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return err(tr("Invalid data"))
    else:
        d = body()
        if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict) and "kalmido_office" not in d:
            d = d["data"]
    if not isinstance(d, dict):
        return err(tr("Invalid data"))
    overwrite = (request.args.get("overwrite") or (d.get("overwrite") if isinstance(d.get("overwrite"), (bool, int, str)) else "")) in (1, True, "1", "true")
    counts = office_import(c, oid, d, overwrite=overwrite)
    ofx_log(c, oid, "import", target="master_data", detail={"overwrite": bool(overwrite), "counts": counts})
    c.commit()
    return jsonify(ok=True, counts=counts)


# ---- 2.47.3 (#1360): the personal office moves into a new organisation (one way)
@app.post("/api/office/move")
def pb_move_post():
    """Body {name, confirm: true}: the owner of the personal office shown turns it into a new organisation named name, with
    themselves as its admin -- the same area id, so numbers, keys, files and the log stay as they are (no duplicate
    numbers); the owner's private clients move with it. One way, no undo. Only where organisations can be created: the
    mode workspaces and an instance admin (the rule of POST /api/admin/orgs). Into an existing organisation: not yet."""
    from flask import g
    from ..accounts.orgs import ORG_NAME_MAX, instance_mode, org_member_add
    from ..core.access import acx_drop
    from ..core.db import uset
    from ..core.pg import system_ctx
    from .model import pb_owner
    c, uid, oid = _ctx(admin=True)
    b = body()
    if pb_owner(c, oid) != uid:
        return err(tr("Only a personal office can move into an organisation"), 409)
    if not isinstance(b, dict) or b.get("confirm") is not True:
        return err(tr("Please confirm the move"))
    if instance_mode(c) != "workspaces" or not g.user["is_admin"]:
        raise Denied(403, tr("Only an admin of this server can create an organisation"))
    name = " ".join(str(b.get("name") or "").split())[:ORG_NAME_MAX]
    if not name:
        return err(tr("Name missing"))
    with system_ctx(c):  # creating an organisation (instance structure) out of the caller's own area
        if c.execute("SELECT 1 FROM orgs WHERE lower(name)=lower(?) AND personal_of IS NULL", (name,)).fetchone():
            return err(tr("An organisation with this name exists"), 409)
        if c.execute("UPDATE orgs SET name=?, personal_of=NULL WHERE id=? AND personal_of=?", (name, oid, uid)).rowcount != 1:
            return err(tr("Only a personal office can move into an organisation"), 409)
        org_member_add(c, oid, uid, "admin")
        moved = [r[0] for r in c.execute("SELECT id FROM clients WHERE org_id IS NULL AND created_by=?", (uid,))]
        if moved:
            q = ",".join("?" * len(moved))
            c.execute(f"UPDATE clients SET org_id=? WHERE id IN ({q})", (oid, *moved))
            c.execute(f"UPDATE office_client_contacts SET org_id=? WHERE client_id IN ({q})", (oid, *moved))
            c.execute(f"UPDATE office_client_contacts SET contact_id=NULL WHERE client_id IN ({q})", moved)  # 2.59.0 (#1735): own books stay private
    g.pop("pb_owner", None)
    acx_drop()
    uset(c, uid, "workspace", f"org:{oid}")
    ofx_log(c, oid, "move", target="settings", detail={"name": name, "clients": len(moved)})
    bump(c)
    c.commit()
    print("organisation", name, "(id", oid, ") made from a personal office by", g.user["username"], flush=True)
    return jsonify(ok=True, org_id=oid, name=name, clients=len(moved))
