"""Office & finance (2.36.1, #1021): the web routes of the module's settings, country packs and master data.
Every route: office_gate (no agents, no kids, feature on) + office_org (the organisation one works in; 400 without one).
Writes to settings / master data / import need the organisation's admin; members read. No /api/v1 and no MCP tool in
stage 1 (before the security audit): agents never reach this module."""
import json

from flask import g, jsonify, request, Response

from ..core.config import app
from ..core.i18n import tr, lg_base
from ..core.db import body, bump, db, err, uset
from ..core.access import Denied, acx_drop
from ..core.errors import BadInput
from .packs import office_features, office_pack, office_pack_codes, office_pack_for, office_pack_validate, pack_features, pack_retention
from .model import (
    MD_KINDS, office_create, office_delete, office_export, office_gate, office_import, office_org, office_role, office_row,
    office_rows, office_seed_texts, office_settings, office_settings_clean, office_settings_lock, office_settings_save, office_update, office_number_format,
    office_number_next, office_scheme_clean, office_scheme_period, sr_public, pb_info, onc_preview, OFFER_COUNTERS,
)
from .ledger import ofx_company, ofx_company_clean, ofx_company_save, ofx_diff, ofx_log
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions
from .rights import AREA_LEGACY, ofr_area_of, ofr_mine, ofr_rights, office_can  # 2.187.0 A (#2476)

IMPORT_MAX = 4 * 1024 * 1024


from .homecur import HC_CODES, hc_bookings, hc_pack_editable  # noqa: E402  2.189.0 (#2475)
from .model import office_ctx as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


@app.get("/api/office/settings")
def office_settings_get():
    """The module's settings of my organisation + my role + the pack's tax rates. First call seeds the text blocks."""
    c, uid, oid = _ctx()
    if office_seed_texts(c, oid):
        c.commit()
    s = office_settings(c, oid)
    pack = office_pack_for(s)
    feats = office_features(s, pack)  # 2.147.0 (#2459, #2460): before the member view strips anything
    role = office_role(c, uid, oid)
    cf = ofx_company(c, oid)
    rights = ofr_mine(c, uid, oid)  # 2.187.0 A (#2476): menu, tabs and buttons follow the office rights
    if role != "admin" and not (not rights["legacy"] and office_can(c, uid, oid, "settings", "manage")):  # 2.86.0 (N15): members never get the bank lines and the DATEV master data (admins only); 2.187.0 A (#2476): + a group that manages the settings
        s, cf = h6c_member_settings(s), {k: ("" if k in H6C_BANK_COLS else v) for k, v in cf.items()}
    return jsonify(settings=s, company_fields=cf, org_id=oid, role=role, pack=office_pack_info(pack, s),
                   rights={**{k: rights[k] for k in ("levels", "specials", "manager", "legacy")},
                           "adm": [k for k, v in AREA_LEGACY.items() if v == "admin"]},  # the areas that were the admins' before
                   features=feats,  # 2.147.0 (#2459, #2460): {key: on} -- menus, tabs and buttons follow it, the routes check it too
                   number_preview=onc_preview(c, oid, s, s["offer_scheme"]),  # 2.118.0 A (#2265): onc_preview
                   industry=_industry(s), home_locked=of_home_locked(c, oid, pack),  # 2.189.0 (#2475)
                   **of_pack_choice(c, oid, role, cf), **pb_info(c, uid, oid))


def of_pack_choice(c, oid, role, cf):
    """2.147.0 (#2462): {pack_choose, pack_suggest}: a NEW office area (no saved settings, no documents) asks its admin once for
    its country; the suggestion: the company's country when a pack exists for it, else the neutral base pack -- without a
    company country the language (German -> DE). Offices from before never see the question (they stay DE as they were)."""
    if role != "admin" or c.execute("SELECT 1 FROM office_settings WHERE org_id=?", (oid,)).fetchone() \
            or c.execute("SELECT 1 FROM office_docs WHERE org_id=? LIMIT 1", (oid,)).fetchone() \
            or c.execute("SELECT 1 FROM office_doc_log WHERE org_id=? LIMIT 1", (oid,)).fetchone():  # (review: an office in use is never "new")
        return {"pack_choose": False, "pack_suggest": None}
    codes = office_pack_codes()
    cc = str((cf or {}).get("country") or "").upper()
    sug = (cc if cc in codes else "XX") if cc else ("DE" if lg_base() == "de" else "XX")
    return {"pack_choose": True, "pack_suggest": sug if sug in codes else "DE"}


def of_reseed_texts(c, oid, old_code):
    """2.147.0 (#2462): a new office opened before its country was chosen got the text blocks of DE (seeded on the first
    look); the first choice of another country swaps the ones still unchanged for the new pack's (own texts stay)."""
    old = office_pack_for({"pack": old_code}) or {}
    tx = old.get("texts") or {}
    want = {(k, t["key"]): (t["de"], t["en"]) for k in ("rights_time", "rights_territory", "rights_media") for t in tx.get(k) or []}
    want.update({(k, "default"): (tx[k]["de"], tx[k]["en"]) for k in ("intro", "closing") if tx.get(k)})
    if tx.get("rights_note"):
        want[("note", "rights_note")] = (tx["rights_note"]["de"], tx["rights_note"]["en"])
    rows = office_rows(c, oid, "texts")
    gone = [r["id"] for r in rows if want.get((r.get("kind"), r.get("key"))) == (r.get("text_de"), r.get("text_en"))]
    if not gone or len(gone) != len(rows):
        return 0  # own texts (or none seeded): left as they are
    for rid in gone:
        c.execute("DELETE FROM office_texts WHERE id=? AND org_id=?", (rid, oid))
    return office_seed_texts(c, oid)


def of_pack_switch(c, oid, s, code):
    """2.147.0 (#2462): what a change of the country pack to code does -- shown before it is saved: functions hidden / shown,
    open documents recalculated with the new rates and texts, finalised documents that keep their state. Nothing is deleted."""
    new = office_pack_for(dict(s, pack=code))
    if not new or new.get("code") != code:
        raise Denied(404)
    before, after = office_features(s), office_features(dict(s, pack=code), new)
    n_open = c.execute("SELECT COUNT(*) FROM office_docs WHERE org_id=? AND locked_at IS NULL AND kind IN ('offer','invoice','credit','reminder')",
                       (oid,)).fetchone()[0]
    n_locked = c.execute("SELECT COUNT(*) FROM office_docs WHERE org_id=? AND locked_at IS NOT NULL", (oid,)).fetchone()[0]
    return {"from": s.get("pack") or "DE", "to": code, "name": new.get("name"), "name_en": new.get("name_en", new.get("name")),
            "hidden": sorted(k for k, on in before.items() if on and not after.get(k)),
            "shown": sorted(k for k, on in after.items() if on and not before.get(k)),
            "open_docs": n_open, "locked_docs": n_locked, "tax": new.get("tax"), "tax_editable": bool((new.get("tax") or {}).get("editable"))}


def office_pack_info(pack, s):
    """2.147.0 (#2459, #2461): what the office client needs of its country pack: tax (the office's own rates in a pack that allows
    them), formats, currency, the functions it offers (ready / planned), the retention and whether it is the neutral base pack."""
    tax = pack.get("tax") or {}
    return {"code": pack["code"], "name": pack["name"], "name_en": pack.get("name_en", pack["name"]), "tax": tax, "formats": pack["formats"],
            "currency": pack["currency"], "neutral": bool(pack.get("neutral")), "tax_editable": bool(tax.get("editable")),
            "offers": pack_features(pack), "retention": pack_retention(pack, s),
            "einvoice_formats": [f for f in ((pack.get("einvoice") or {}).get("formats") or []) if f in ("zugferd", "xrechnung")],
            "currency_editable": hc_pack_editable(pack), "currencies": list(HC_CODES)}  # 2.189.0 (#2475)


def of_home_locked(c, oid, pack):
    """2.189.0 (#2475): True when the home currency may no longer change (only asked in a pack with currency choice)."""
    return bool(hc_pack_editable(pack) and hc_bookings(c, oid))


H6C_BANK_COLS = ("iban", "bic", "bank_name")


def h6c_member_settings(s):
    """2.86.0 (N15): the office settings as a member sees them: no bank lines, no DATEV booking export data (advisor / client
    number, accounts). The documents still print them (rendered on the server); the settings page is the admins' anyway."""
    s = dict(s)
    s["company"] = {**(s.get("company") or {}), "bank_lines": []}
    s["datev_extf"] = {}
    return s


def rd2_manage(c, uid, oid):
    """2.187.0 A (#2476): a person ruled by office groups who manages the area of this request (purchase prices / markups of
    the master data like an admin); everybody else exactly as before (the admin role)."""
    area = ofr_area_of(request.path)
    return bool(area) and ofr_rights(c, uid, oid) is not None and office_can(c, uid, oid, area, "manage")


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
    if "pack" in b or "industry_packs" in b or "home_currency" in b:  # 2.76.0 review (N8): the pack choice and an uninstall never interleave; 2.189.0 (#2475): nor two home currency changes
        from ..core.pg import write_lock
        write_lock(c, f"office_packs_{int(oid)}")
    office_settings_lock(c, oid)  # 2.269.0 B (#3014): two saves with different keys both stay (after the packs lock)
    cur = office_settings(c, oid)
    fresh = "pack" in b and of_pack_choice(c, oid, "admin", None)["pack_choose"]  # 2.147.0 (#2462): the first choice of the country
    new = office_settings_clean(c, oid, b, cur)
    if "company_fields" in b:
        cf = ofx_company(c, oid)
        ncf = ofx_company_clean(b["company_fields"], cf)
        diff = ofx_diff(cf, ncf)
        if diff["after"]:
            ofx_company_save(c, oid, ncf)
            ofx_log(c, oid, "update", target="company", detail=diff)
    office_settings_save(c, oid, new)
    if fresh and new["pack"] != cur["pack"] and not any(v for k in ("intro_text_id", "closing_text_id", "rights_default") for v in (new.get(k) or {}).values()):
        of_reseed_texts(c, oid, cur["pack"])
    diff = ofx_diff(cur, new)
    if diff["after"]:
        ofx_log(c, oid, "update", target="settings", detail=diff)
    c.commit()
    s2 = office_settings(c, oid)
    return jsonify(settings=s2, company_fields=ofx_company(c, oid), number_preview=onc_preview(c, oid, new, new["offer_scheme"]),  # 2.118.0 A (#2265)
                   features=office_features(s2), pack=office_pack_info(office_pack_for(s2), s2),  # 2.147.0 (#2460)
                   home_locked=of_home_locked(c, oid, office_pack_for(s2)))  # 2.189.0 (#2475)


@app.get("/api/office/number-preview")
def office_number_preview():
    """?scheme=…&kind=offer|invoice|credit|reminder -> {preview, valid, error, yearly} (the settings page shows the next
    number while typing; 2.40.0 (#1382): every scheme with its own counter, example values for project / client / initials,
    yearly = the counter starts again every year)."""
    c, uid, oid = _ctx()
    kind = request.args.get("kind") or "offer"
    if kind not in ("offer", "invoice", "credit", "reminder", "delivery"):  # 2.120.0 D (#2089)
        kind = "offer"
    try:
        scheme = office_scheme_clean(request.args.get("scheme") or "", offer=kind == "offer")  # 2.118.0 A (#2265): {version} only here
    except BadInput as e:
        return jsonify(preview="", valid=False, error=str(e))
    if kind == "offer":  # 2.118.0 A (#2265): ?counter=org|client|project (the choice on the page), example client / project from 1
        cnt = request.args.get("counter")
        pv = onc_preview(c, oid, office_settings(c, oid), scheme, cnt if cnt in OFFER_COUNTERS else None, project=tr("Project"), client=tr("Client"), initials="AB")
    else:
        pv = office_number_next(c, oid, kind, scheme, peek=True, project=tr("Project"), client=tr("Client"), initials="AB")[0]
    return jsonify(preview=pv, valid=True, yearly=bool(office_scheme_period(scheme)))


@app.get("/api/office/packs")
def office_packs_get():
    c, uid, oid = _ctx()
    from .catalog import pkc_packs_extra
    src, industry = pkc_packs_extra(c, oid)  # 2.76.0 (#1023): + the packs installed in my office area, source / badge, industry packs
    out = []
    for code in office_pack_codes():
        p = office_pack_for({"pack": code})  # 2.147.0 (#2461): tax labels with {rate} filled in
        if p and p.get("code") == code:
            out.append({"code": p["code"], "name": p["name"], "name_en": p.get("name_en", p["name"]), "currency": p["currency"],
                        "neutral": bool(p.get("neutral")), "offers": pack_features(p),  # 2.147.0 (#2459, #2461)
                        "version": p["version"], "community": p.get("community", False), "tax": p["tax"],
                        "source": src.get(code, ("builtin", "verified"))[0], "badge": src.get(code, ("builtin", "verified"))[1]})
    return jsonify(packs=out, industry=industry)


@app.get("/api/office/pack-switch")
def office_pack_switch_get():
    """Office admin. ?code=XX -> of_pack_switch (the warning before the country pack changes; 2.147.0, #2462)."""
    c, uid, oid = _ctx(admin=True)
    s = office_settings(c, oid)
    return jsonify(of_pack_switch(c, oid, s, str(request.args.get("code") or "").strip().upper()))


@app.get("/api/office/packs/<code>")
def office_pack_get(code):
    c, uid, oid = _ctx()
    office_settings(c, oid)  # 2.76.0 (#1023): binds my office area (its installed packs)
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
    adm = office_role(c, uid, oid) == "admin" or rd2_manage(c, uid, oid)  # 2.47.0 (#1649): members never get purchase prices / markups
    rows = [sr_public(kind, r, adm) for r in office_rows(c, oid, kind, archived=a.get("archived") == "1", q=a.get("q") or "")]
    if kind == "equipment" and adm:  # 2.92.0 B (#1931): + depreciation, book / new / current value (admins only)
        from .assets import ast_enrich
        ast_enrich(c, oid, rows)
    if kind == "contracts":  # 2.117.0 B (#2285): files = the attached PDFs (the paper clip in the list)
        from .contractfiles import dma_counts
        dma_counts(c, oid, rows)
    return jsonify(items=rows)


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
    adm = office_role(c, uid, oid) == "admin" or rd2_manage(c, uid, oid)
    r = sr_public(kind, office_row(c, oid, kind, rid), adm)  # 2.47.0 (#1649)
    if kind == "equipment" and adm:  # 2.92.0 B (#1931)
        from .assets import ast_enrich
        ast_enrich(c, oid, [r])
    return jsonify(r)


@app.patch("/api/office/<kind>/<int:rid>")
def office_row_patch(kind, rid):
    _kind(kind)
    c, uid, oid = _ctx(admin=True)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    old = office_row(c, oid, kind, rid)
    from .undo import oun_post, oun_pre
    oun_pre(c, uid, oid, kind, rid)  # 2.111.0 A (#2233): the state before, for "Saved · Undo"
    r = office_update(c, oid, kind, rid, b)
    from .legacyimport import imr_restored
    imr_restored(c, oid, kind, old, r)  # 2.144.6 B (#2400 F4): restored on purpose -> "Archive leftover entries" skips it
    diff = ofx_diff(old, r)
    diff["after"].pop("updated_at", None)
    diff["before"].pop("updated_at", None)
    if diff["after"]:
        ofx_log(c, oid, "update", target=kind, detail={"id": r["id"], **diff})
    oun_post(c)
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
    return jsonify(ok=True, result=res, **({"trash_id": g.otb_id} if res == "deleted" and g.get("otb_id") else {}))  # 2.272.0 E2 (#3038)


# ---- import / export of the master data (JSON file)
@app.get("/api/office/export")
def office_export_get():
    c, uid, oid = _ctx()
    adm = office_role(c, uid, oid) == "admin"
    d = office_export(c, oid, adm)  # 2.47.0 (#1649)
    if not adm:  # 2.86.0 (N15)
        d["settings"] = h6c_member_settings(d["settings"])
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
    from .model import pb_owner
    from .pbtransfer import pb_letter_detach
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
    unlinked = pb_letter_detach(c, oid)  # review A2 (2.153.0): the owner's private documents and address books stay private
    g.pop("pb_owner", None)
    acx_drop()
    uset(c, uid, "workspace", f"org:{oid}")
    ofx_log(c, oid, "move", target="settings", detail={"name": name, "clients": len(moved), "letter_links": unlinked})
    bump(c)
    c.commit()
    print("organisation", name, "(id", oid, ") made from a personal office by", g.user["username"], flush=True)
    return jsonify(ok=True, org_id=oid, name=name, clients=len(moved))
