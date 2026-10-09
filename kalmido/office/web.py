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
    office_number_next, office_scheme_clean,
)

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
    return jsonify(settings=s, org_id=oid, role=office_role(c, uid, oid), pack={"code": pack["code"], "name": pack["name"], "tax": pack["tax"],
                                                                               "formats": pack["formats"], "currency": pack["currency"]},
                   number_preview=office_number_next(c, oid, "offer", s["offer_scheme"], peek=True)[0])


@app.put("/api/office/settings")
def office_settings_put():
    """Org admin. Partial body with the keys of office_settings.data (logo: see POST /api/office/logo)."""
    c, uid, oid = _ctx(admin=True)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    cur = office_settings(c, oid)
    new = office_settings_clean(c, oid, b, cur)
    office_settings_save(c, oid, new)
    c.commit()
    return jsonify(settings=office_settings(c, oid), number_preview=office_number_next(c, oid, "offer", new["offer_scheme"], peek=True)[0])


@app.get("/api/office/number-preview")
def office_number_preview():
    """?scheme=… -> {preview, valid} (the settings page shows the next number while typing)."""
    c, uid, oid = _ctx()
    try:
        scheme = office_scheme_clean(request.args.get("scheme") or "")
    except BadInput as e:
        return jsonify(preview="", valid=False, error=str(e))
    return jsonify(preview=office_number_next(c, oid, "offer", scheme, peek=True)[0], valid=True)


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


# ---- master data: one set of routes per kind (services, equipment, sets, texts, contracts)
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
    return jsonify(items=office_rows(c, oid, kind, archived=a.get("archived") == "1", q=a.get("q") or ""))


@app.post("/api/office/<kind>")
def office_row_post(kind):
    _kind(kind)
    c, uid, oid = _ctx(admin=True)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    r = office_create(c, oid, kind, b)
    c.commit()
    return jsonify(r), 201


@app.get("/api/office/<kind>/<int:rid>")
def office_row_get(kind, rid):
    _kind(kind)
    c, uid, oid = _ctx()
    return jsonify(office_row(c, oid, kind, rid))


@app.patch("/api/office/<kind>/<int:rid>")
def office_row_patch(kind, rid):
    _kind(kind)
    c, uid, oid = _ctx(admin=True)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    r = office_update(c, oid, kind, rid, b)
    c.commit()
    return jsonify(r)


@app.delete("/api/office/<kind>/<int:rid>")
def office_row_delete(kind, rid):
    """Deletes; a row used in documents / contracts / sets is archived instead -> {ok, result: deleted|archived}."""
    _kind(kind)
    c, uid, oid = _ctx(admin=True)
    res = office_delete(c, oid, kind, rid)
    c.commit()
    return jsonify(ok=True, result=res)


# ---- import / export of the master data (JSON file)
@app.get("/api/office/export")
def office_export_get():
    c, uid, oid = _ctx()
    d = office_export(c, oid)
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
    c.commit()
    return jsonify(ok=True, counts=counts)
