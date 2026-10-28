"""2.137.0 A (#2344): organisation import -- the clients and the office (admin/orgimport.py OiT; the archive entries of
admin/orgexport.py OX_AREAS "clients.json" and "office/*.json", the files below "files/office/").

Into an organisation every office row gets the organisation's id; into the private space the office rows go into the
person's own office (private="office": the hidden orgs row of office/model.py pb_personal) and the clients with their
contact persons into the private space (org_id NULL, created_by = the person: model.py pb_cl_sql), like the app keeps a
personal office. Numbers stay as they are (finalised invoices, closed cash days, the number ranges): a document or
archive number the target office already has skips that row with a warning, a number range the target already has
stays the target's. Ids inside texts (settings, master sets, contract rates, shoot sheets, the documents' references, the
legacy import runs) are mapped, unknown ones dropped. The office files are written anew under the app's own names
(sealed like the app seals them, the logos plain); approval links get a new secret (the old link ends)."""
import json
import os
import re
import uuid

from ..core.config import OFFICE_DIR
from ..core.i18n import N_
from .orgimport import OiFix, OiT, _txt  # noqa: F401
from ..core.orgcrypt import oc_item_store, oc_json_store, oc_log_detail  # 2.149.0 G (#2517): pulled up from functions
from ..core.orgcrypt import oc_dec_fields  # 2.188.0 A (#2498)
from ..office.calc import dec  # 2.188.0 A (#2498)
from ..core.db import insert_id, iso, now_utc  # 2.149.0 G (#2517): pulled up from functions

# ids inside JSON texts: key -> map kind (unknown -> None)
OI_JSON_IDS = {"service_id": "office_services", "producing_service_id": "office_services", "role_id": "office_roles",
               "equipment_id": "office_equipment", "intro_text_id": "office_texts", "closing_text_id": "office_texts",
               "time_id": "office_texts", "territory_id": "office_texts", "media_id": "office_texts", "set_id": "office_sets",
               "book_id": "office_cashbooks", "vehicle_id": "office_vehicles", "agreement_id": "office_agreements",
               "template_id": "office_doc_templates", "client_id": "clients"}
OI_RIGHTS_DIMS = ("time", "territory", "media")


def _oi_id(run, kind, v):
    return run.m(kind, v) if v is not None else None


def _oi_ids(run, v):
    """A parsed JSON value with the ids of OI_JSON_IDS mapped (in place for dicts and lists)."""
    if isinstance(v, list):
        return [_oi_ids(run, x) for x in v]
    if not isinstance(v, dict):
        return v
    out = {}
    for k, x in v.items():
        kind = OI_JSON_IDS.get(k)
        if kind and isinstance(x, dict):  # {"de": id, "en": id}
            out[k] = {lg: _oi_id(run, kind, i) if not isinstance(i, (dict, list)) else None for lg, i in x.items()}
        elif kind and not isinstance(x, list):
            out[k] = _oi_id(run, kind, x)
        elif k in OI_RIGHTS_DIMS and isinstance(x, dict) and "id" in x:  # the rights snapshot {time: {id, text}}
            out[k] = {**x, "id": _oi_id(run, "office_texts", x.get("id"))}
        else:
            out[k] = _oi_ids(run, x)
    return out


def _oi_json(s, dflt):
    if not isinstance(s, str) or not s:
        return dflt
    try:
        return json.loads(s)
    except (ValueError, RecursionError):
        return dflt


def _oi_dir(space):
    return os.path.join(OFFICE_DIR, str(int(space)))


def _oi_name(name):
    from .orgexport import _safe_part
    return "files/office/" + _safe_part(name)


def _oi_put(ctx, old, new, seal=True, mime="", keep=False):
    """Archive file `old` (a bare name below the source's office folder) -> `new` below the target's office folder. keep:
    a content-addressed name (logo / letterhead snapshots): an existing file of that name stays. -> new or None."""
    if not old or not new or os.path.basename(old) != old or os.path.basename(new) != new:
        return None
    full = os.path.join(_oi_dir(ctx.space), new)
    if os.path.exists(full):
        return new if keep else None
    done = ctx.run.__dict__.setdefault("oi_office_files", set())
    if (ctx.space, new) in done:
        return new
    r = ctx.file(_oi_name(old), None, new, base=_oi_dir(ctx.space), mime=mime, seal=seal)
    if not r:
        return None
    done.add((ctx.space, new))
    return new


def _oi_logo_ok(ctx, name):
    """2.137.0 review L4: a content-addressed logo copy only under the name of its own content (never a file that a
    later logo of the target would be taken for)."""
    import hashlib
    from .acctimport import _file_bytes
    raw = _file_bytes(ctx.zf, ctx.files, _oi_name(name))
    return raw is not None and hashlib.sha256(raw).hexdigest()[:16] == name[5:21]


def _oi_number_taken(c, space, number):
    if not number:
        return False
    return bool(c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND number=? UNION ALL SELECT 1 FROM office_archive WHERE org_id=? AND number=? LIMIT 1",
                          (space, number, space, number)).fetchone())


def _oi_has(c, table, space):
    return bool(c.execute(f"SELECT 1 FROM {table} WHERE org_id=? LIMIT 1", (space,)).fetchone())


# ---------------------------------------------------------------- prep / after hooks
def _p_client(c, run, src, d, ctx):
    if not run.org:  # a private client: the person's own (model.py pb_cl_sql)
        d["created_by"] = ctx.uid
    return d


def _p_once(table, text):
    """A table with one row per office (company data, cash flow start): kept when the target office has it already."""
    def prep(c, run, src, d, ctx):
        if _oi_has(c, table, ctx.space):
            run.warning(text)
            return None
        return d
    return prep


def _p_settings(c, run, src, d, ctx):
    if _oi_has(c, "office_settings", ctx.space):
        run.warning(N_("The target office already has its own office settings; they were kept."))
        return None
    j = _oi_json(d.get("data"), {})
    if not isinstance(j, dict):
        return None
    j = _oi_ids(run, j)
    from ..office.pdfweb import LOGO_FILE
    if j.get("logo"):
        j["logo"] = _oi_put(ctx, os.path.basename(str(j["logo"])), LOGO_FILE, seal=False, mime="image/png") or ""
    lh = j.get("letterhead")
    if isinstance(lh, dict) and lh.get("file"):
        from ..office.letterhead import BP_FILE_RE
        f = str(lh["file"])
        lh["file"] = (_oi_put(ctx, f, f"letterhead-{uuid.uuid4().hex[:16]}.pdf", mime="application/pdf") or "") if BP_FILE_RE.fullmatch(f) else ""
    d["data"] = json.dumps(oc_json_store(c, ctx.space, "office_settings", "data", j), ensure_ascii=False)
    return d


def _p_numbers(c, run, src, d, ctx):
    if c.execute("SELECT 1 FROM office_numbers WHERE org_id=? AND kind=? AND period=?", (ctx.space, d.get("kind"), d.get("period") or "")).fetchone():
        if isinstance(d.get("last"), int):  # 2.137.0 review M2: the kept counter continues after the imported numbers (never one twice)
            c.execute("UPDATE office_numbers SET last=GREATEST(last, ?) WHERE org_id=? AND kind=? AND period=?",
                      (d["last"], ctx.space, d.get("kind"), d.get("period") or ""))
        run.warning(N_("A number range of the target office was kept: {0}"), f"{d.get('kind')} {d.get('period') or ''}".strip())
        return None
    return d


def _p_sets(c, run, src, d, ctx):
    items = _oi_json(d.get("items"), [])
    d["items"] = json.dumps([it for it in _oi_ids(run, items) if isinstance(it, dict) and it.get("equipment_id")] if isinstance(items, list) else [])
    return d


def _p_contract(c, run, src, d, ctx):
    rates = _oi_json(src.get("rates"), {})
    out = {}
    if isinstance(rates, dict):  # {service id: rate}
        for k, v in rates.items():
            new = run.m("office_services", k)
            if new:
                out[str(new)] = v
    d["rates"] = json.dumps(out)
    return d


def _p_contract_file(c, run, src, d, ctx):
    cid = d.get("contract_id")
    d["file"] = ""
    if not src.get("file"):
        return d
    new = _oi_put(ctx, src["file"], f"contract{int(cid)}-{uuid.uuid4().hex[:16]}.pdf", mime="application/pdf")
    if not new:
        return None
    d["file"] = new
    return d


def _p_doc(c, run, src, d, ctx):
    if _oi_number_taken(c, ctx.space, d.get("number")):
        run.warning(N_("A document number already exists in the target office, the document was skipped: {0}"), d.get("number"))
        return None
    for col in ("ref_doc_ids", "abs_refs"):  # set by the finish pass (other documents)
        if col in d and d[col] is not None:  # an empty value stays empty (the round trip compares them)
            d[col] = "[]"
    if "rights" in d:
        d["rights"] = json.dumps(_oi_ids(run, _oi_json(src.get("rights"), {})), ensure_ascii=False)
    for col in ("totals",):
        j = _oi_json(d.get(col), None)
        if isinstance(j, dict):
            d[col] = json.dumps(oc_json_store(c, ctx.space, "office_docs", col, j), ensure_ascii=False)
    return d


def _oi_mark(c, run, ctx, target, doc_id=None, detail=None):
    """2.237.0 D (#2870): an office log entry "imported" by the importing person: what the file says (finalised, number,
    an approval, a day closing, locked months) came from the file, not from this office. Removed again by the undo."""
    if not isinstance(ctx.space, int):
        return
    det = {"source": "file", **{k: v for k, v in (detail or {}).items() if v not in (None, "")}}
    lid = insert_id(c, "INSERT INTO office_doc_log(org_id, doc_id, user_id, at, action, target, detail) VALUES(?,?,?,?,?,?,?)",
                    (ctx.space, doc_id, ctx.uid, iso(now_utc()), "import", target, oc_log_detail(c, ctx.space, json.dumps(det, ensure_ascii=False))))
    run.created["oi"].append(["office_doc_log", lid, ctx.space])


def _a_doc(c, run, src, nid, ctx):
    """The stored files of a finalised document (PDF / XML under the new id) and the snapshots its sender names."""
    from ..office.pdfweb import epdf_name
    _oi_mark(c, run, ctx, "doc", nid, {k: src.get(k) for k in ("number", "status", "locked_at")})  # 2.237.0 D (#2870)
    old = src.get("id")
    if not isinstance(old, int) or not src.get("kind"):
        return
    r_old, r_new = {**src}, {**src, "id": nid}
    for ext, mime in (("pdf", "application/pdf"), ("xml", "application/xml")):
        if src.get(ext + "_sha256"):
            _oi_put(ctx, f"doc{old}-{epdf_name(r_old)}.{ext}", f"doc{int(nid)}-{epdf_name(r_new)}.{ext}", mime=mime)
    snd = _oi_json(src.get("sender"), {})
    if isinstance(snd, dict):
        if isinstance(snd.get("logo"), str) and re.fullmatch(r"logo-[0-9a-f]{16}\.png", snd["logo"]) and _oi_logo_ok(ctx, snd["logo"]):
            _oi_put(ctx, snd["logo"], snd["logo"], seal=False, mime="image/png", keep=True)
        lh = snd.get("letterhead")
        if isinstance(lh, dict) and isinstance(lh.get("file"), str) and re.fullmatch(r"lhs-[0-9a-f]{16}\.pdf", lh["file"]):
            _oi_put(ctx, lh["file"], lh["file"], mime="application/pdf", keep=True)


def _p_part(c, run, src, d, ctx):
    if "sheet" in d:
        d["sheet"] = json.dumps(_oi_ids(run, _oi_json(src.get("sheet"), {})), ensure_ascii=False)
    if "settings" in d:
        d["settings"] = json.dumps(_oi_ids(run, _oi_json(src.get("settings"), {})), ensure_ascii=False)
    j = _oi_json(d.get("totals"), None)
    if isinstance(j, dict):
        d["totals"] = json.dumps(oc_json_store(c, ctx.space, "office_doc_parts", "totals", j), ensure_ascii=False)
    return d


def _p_item(c, run, src, d, ctx):
    return oc_item_store(c, ctx.space, d)


def _p_purchase(c, run, src, d, ctx):
    kind = "office_doc_items" if src.get("source") == "item" else "office_doc_parts"
    d["ref"] = run.m(kind, src.get("ref"))
    return d


def _p_signoff(c, run, src, d, ctx):
    from ..office.signoff import sig_purpose, sig_token_new
    _tok, h, sealed = sig_token_new(c, sig_purpose({k: d.get(k) for k in ("kind", "doc_id", "list_id", "gen_doc_id", "video_id")}))
    d["token_hash"], d["token"] = h, sealed  # a new secret nobody knows: the link of the old server ends here
    if (d.get("state") or "open") == "open" and not d.get("revoked_at"):
        d["revoked_at"] = iso(now_utc())
        run.warning(N_("Open approval links of the export were ended; create a new link where it is still needed."))
    return d


def _a_signoff(c, run, src, nid, ctx):
    """The accepted version of a quotation (its own PDF, named by document and approval)."""
    from ..office.pdfweb import epdf_name
    if (src.get("state") or "open") != "open":  # 2.237.0 D (#2870): an answer of the file is noted as imported, not as given here
        _oi_mark(c, run, ctx, "gen_doc" if src.get("gen_doc_id") else "doc", run.m("office_docs", src.get("doc_id")),
                 {"signoff": nid, "state": _txt(src.get("state"), 20), "signed_at": _txt(src.get("signed_at"), 40)})
    if src.get("kind") != "offer" or src.get("state") != "accepted":
        return
    dsrc = next((x for x in (ctx.data.get("oi") or {}).get("office/documents.json") or [] if x.get("id") == src.get("doc_id")), None)
    new_doc = run.m("office_docs", src.get("doc_id"))
    if not dsrc or not new_doc or not isinstance(src.get("id"), int):
        return
    _oi_put(ctx, f"doc{int(dsrc['id'])}-{epdf_name(dsrc)}.accepted-{int(src['id'])}.pdf",
            f"doc{int(new_doc)}-{epdf_name({**dsrc, 'id': new_doc})}.accepted-{int(nid)}.pdf", mime="application/pdf")


def _p_meal_file(c, run, src, d, ctx):
    d["file"] = ""
    m = re.fullmatch(r"meal\d{1,12}-[0-9a-f]{16}(\.[a-z]{2,4})", str(src.get("file") or ""))
    if not m:
        return None
    new = _oi_put(ctx, src["file"], f"meal{int(d['meal_id'])}-{uuid.uuid4().hex[:16]}{m.group(1)}", mime=d.get("mime") or "")
    if not new:
        return None
    d["file"] = new
    return d


def _a_archive(c, run, src, nid, ctx):
    """The PDF of an archived document: archive-<new id>-<sha16>.pdf like the legacy import names it."""
    f = str(src.get("file") or "")
    if not re.fullmatch(r"archive-\d{1,12}-[0-9a-f]{16}\.pdf", f):
        c.execute("UPDATE office_archive SET file='' WHERE id=?", (nid,))
        return
    sha = str(src.get("sha256") or "")
    new = _oi_put(ctx, f, f"archive-{int(nid)}-{sha[:16] if re.fullmatch(r'[0-9a-f]{16,64}', sha) else uuid.uuid4().hex[:16]}.pdf",
                  mime="application/pdf")
    c.execute("UPDATE office_archive SET file=? WHERE id=?", (new or "", nid))


def _p_archive(c, run, src, d, ctx):
    if _oi_number_taken(c, ctx.space, d.get("number")):
        run.warning(N_("A document number already exists in the target office, the document was skipped: {0}"), d.get("number"))
        return None
    d["file"] = ""  # written by _a_archive under the new id
    return d


def _oi_before(c, run, name, space, sql):
    """2.188.0 A (#2498): the target's rows of a table as they were before this run (read once, on its first row)."""
    key = ("oi_before", name, space)
    if key not in run.__dict__:
        run.__dict__[key] = c.execute(sql, (space,)).fetchall()
    return run.__dict__[key]


def _oi_jsonv(v):
    try:
        return json.loads(v) if isinstance(v, str) else v
    except ValueError:
        return v


def _p_procdoc(c, run, src, d, ctx):
    """2.148.0 C (#2472): versions of the procedure documentation follow the ones the area already has (rows come by id).
    2.188.0 A (#2498): a target office that had its own before keeps only those (a second import adds nothing twice)."""
    had = _oi_before(c, run, "procdocs", ctx.space, "SELECT * FROM office_procdocs WHERE org_id=?")
    if had:
        want = _oi_jsonv(src.get("data"))
        if not any(_oi_jsonv(oc_dec_fields(c, ctx.space, "office_procdocs", r).get("data")) == want for r in had):
            run.warning(N_("The target office already has its own procedure documentation; it was kept."))
        return False
    r = c.execute("SELECT MAX(version) FROM office_procdocs WHERE org_id=?", (d.get("org_id"),)).fetchone()
    d["version"] = int((r[0] if r else 0) or 0) + 1
    return d


def _p_opening(c, run, src, d, ctx):
    """2.188.0 A (#2498): an opening balance of a year + account the target office has already is not added again; one that
    differs keeps the target's (warning)."""
    had = _oi_before(c, run, "opening", ctx.space, "SELECT year, account, side, amount FROM office_opening_balances WHERE org_id=?")
    same = [r for r in had if int(r["year"]) == int(d.get("year") or 0) and str(r["account"]) == str(d.get("account") or "")]
    if not same:
        return d
    if not any(str(r["side"]) == str(d.get("side") or "S") and dec(r["amount"], "0") == dec(d.get("amount"), "0") for r in same):
        run.warning(N_("An opening balance differs from the one in the target office; the target's was kept: {0}"),
                    f"{d.get('year')} {d.get('account')}")
    return False


def _p_datev_guid(c, run, src, d, ctx):
    """2.188.0 A (#2498): the kept GUID of a document that came along (receipt files: node_id late, _f_datev_guids)."""
    if src.get("doc_id") is not None and not d.get("doc_id"):
        return False  # its document stayed out: the GUID has nothing to name
    if src.get("doc_id") is None and src.get("node_id") is None:
        return False
    return d


def _f_datev_guids(c, run, uid, data, who):
    """2.188.0 A (#2498): the GUID of a receipt file that did not come along names nothing: gone again."""
    ids = [e[1] for e in run.created.get("oi") or [] if e and e[0] == "office_datev_guids" and isinstance(e[1], int)]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        c.execute(f"DELETE FROM office_datev_guids WHERE id IN ({','.join('?' * len(part))}) AND doc_id IS NULL AND node_id IS NULL", part)


def _p_bank_balance(c, run, src, d, ctx):
    """Balances hang on their statement import; without it (an older export) on one import row of this run."""
    if d.get("import_id"):
        return d
    key = ("oi_bank_import", ctx.space)
    bid = run.__dict__.get(key)
    if not bid:
        bid = insert_id(c, "INSERT INTO office_bank_imports(org_id, filename, fmt, count, dup_count, created_by, created_at) VALUES(?,?,?,?,?,?,?)",
                        (ctx.space, "import", "import", 0, 0, ctx.uid, iso(now_utc())))
        run.__dict__[key] = bid
        run.created["oi"].append(["office_bank_imports", bid, ctx.space])
    d["import_id"] = bid
    return d


def _p_log(c, run, src, d, ctx):
    if d.get("detail"):
        d["detail"] = oc_log_detail(c, ctx.space, d["detail"])  # like the app: only entries with protected keys sealed
    return d


def _oi_gref(run, ref):
    """2.187.1 A (#2735): a group ref of the rights log on the target: 'g:<new id>', 'g:0' for a group that did not come
    along (the rights page shows "Deleted group"), templates as they are."""
    if not isinstance(ref, str) or not ref.startswith("g:"):
        return ref
    try:
        new = _oi_id(run, "office_rgroups", int(ref[2:]))
    except ValueError:
        new = None
    return f"g:{new}" if new else "g:0"


def _p_rights_log(c, run, src, d, ctx):
    """2.187.1 A (#2735): the rights log names the target's group numbers (before: the source's, i.e. a wrong or no group)
    and the target's people in a deleted group's member list."""
    if d.get("group_ref"):
        d["group_ref"] = _oi_gref(run, d["group_ref"])
    for k in ("before", "after"):
        v = _oi_json(d.get(k), None)
        if isinstance(v, list):
            d[k] = json.dumps([_oi_gref(run, x) for x in v], ensure_ascii=False)
        elif isinstance(v, dict) and isinstance(v.get("members"), list):
            v["members"] = [m for m in (ctx.who(x) for x in v["members"] if x is not None) if m]
            d[k] = json.dumps(v, ensure_ascii=False)
    return d


def _p_tx(c, run, src, d, ctx):
    for k in ("match_kind", "matched_at", "rule_id"):  # set again by the finish pass once the match is known (2.299.0 B (#3191): + rule_id)
        d.pop(k, None)
    return d


def _p_rule_no(c, run, src, d, ctx):
    """2.299.0 B (#3191): a declined rule suggestion is keyed by its office area (bankrules.br_key) -- it does not carry over."""
    return False


def _p_letter(c, run, src, d, ctx):
    """2.184.0 A (#2579): a follow-up task that did not come along stays done (0, like the claim of office/letterlinks.py), never
    made twice by the watchdog."""
    if src.get("followup_task_id") is not None and d.get("followup_task_id") is None:
        d["followup_task_id"] = 0
    return d


def _p_drive_closed(c, run, src, d, ctx):
    """2.362.0 (#3096): a closed month of the logbook (a vehicle that did not come along: nothing to close)."""
    if src.get("vehicle_id") and not d.get("vehicle_id"):
        return False
    if c.execute("SELECT 1 FROM office_drive_closed WHERE org_id=? AND COALESCE(vehicle_id, 0)=? AND month=?",
                 (ctx.space, d.get("vehicle_id") or 0, d.get("month"))).fetchone():
        return False
    return d


def _p_letter_profile(c, run, src, d, ctx):
    """2.184.0 A (#2579): the signature of a person in the target office stays theirs (one per person and office)."""
    if c.execute("SELECT 1 FROM office_letter_profiles WHERE org_id=? AND user_id=?", (ctx.space, d["user_id"])).fetchone():
        return False
    return d


# ---------------------------------------------------------------- the tables, in the order they are created
_P = {"created_by": "null"}
SPECS = [
    OiT("office/import_runs.json", "office_import_runs", people={**_P, "undone_by": "null"}, private="office"),
    OiT("clients.json", "clients", refs={"import_run_id": "office_import_runs"}, people=_P, label=N_("Clients"), prep=_p_client),
    OiT("office/client_contacts.json", "office_client_contacts", refs={"client_id": "clients", "contact_id": "contacts",
        "import_run_id": "office_import_runs"}, need=("client_id",)),
    OiT("office/company.json", "office_company", private="office", rid=False, key=("org_id",), label=N_("Office"),
        prep=_p_once("office_company", N_("The target office already has its own company data; they were kept."))),
    OiT("office/texts.json", "office_texts", private="office"),
    OiT("office/roles.json", "office_roles", refs={"import_run_id": "office_import_runs"}, private="office"),
    OiT("office/services.json", "office_services", refs={"role_id": "office_roles", "import_run_id": "office_import_runs"}, private="office"),
    OiT("office/agreements.json", "office_agreements", refs={"task_id": "tasks"}, late={"doc_node_id": "fs_nodes"}, people=_P, private="office"),
    OiT("office/equipment.json", "office_equipment", refs={"agreement_id": "office_agreements", "import_run_id": "office_import_runs"},
        late={"receipt_node_id": "fs_nodes"}, private="office"),
    OiT("office/packages.json", "office_sets", private="office", prep=_p_sets),
    OiT("office/doc_templates.json", "office_doc_templates", people=_P, private="office"),
    OiT("office/settings.json", "office_settings", private="office", rid=False, key=("org_id",), prep=_p_settings),
    OiT("office/numbers.json", "office_numbers", private="office", rid=False, key=("org_id", "kind", "period"), prep=_p_numbers),
    OiT("office/contracts.json", "office_contracts", refs={"client_id": "clients", "rights_time_id": "office_texts",
        "rights_territory_id": "office_texts", "rights_media_id": "office_texts"}, private="office", prep=_p_contract),
    OiT("office/contract_files.json", "office_contract_files", refs={"contract_id": "office_contracts"}, need=("contract_id",),
        people=_P, private="office", prep=_p_contract_file),
    OiT("office/documents.json", "office_docs", refs={"client_id": "clients", "contract_id": "office_contracts", "contact_id": "office_client_contacts",
        "list_id": "lists"}, late={"version_of": "office_docs", "cancels_id": "office_docs", "source_doc_id": "office_docs",
        "series_id": "office_inv_series"}, people={**_P, "locked_by": "null", "agent_id": "null"}, private="office", prep=_p_doc, after=_a_doc),
    OiT("office/document_parts.json", "office_doc_parts", refs={"doc_id": "office_docs"}, need=("doc_id",), private="office", prep=_p_part),
    OiT("office/document_items.json", "office_doc_items", refs={"doc_id": "office_docs", "service_id": "office_services",
        "part_id": "office_doc_parts", "ref_part_id": "office_doc_parts", "list_id": "lists"}, need=("doc_id",), private="office", prep=_p_item),
    OiT("office/purchases.json", "office_purchases", refs={"doc_id": "office_docs"}, need=("doc_id",), private="office", prep=_p_purchase),
    OiT("office/invoice_series.json", "office_inv_series", refs={"template_id": "office_docs"}, need=("template_id",), people=_P, private="office"),
    OiT("office/payments.json", "office_payments", refs={"doc_id": "office_docs"}, need=("doc_id",), people=_P, private="office"),
    OiT("office/pay-props.json", "office_pay_props", refs={"doc_id": "office_docs", "payment_id": "office_payments"}, need=("doc_id",),
        people={"agent_id": "null", "requested_by": "null", "decided_by": "null"}, private="office"),
    OiT("office/gen_docs.json", "office_gen_docs", refs={"template_id": "office_doc_templates", "client_id": "clients", "list_id": "lists",
        "doc_id": "office_docs"}, late={"node_id": "fs_nodes", "signed_node_id": "fs_nodes"}, people={**_P, "sign_uid": "null"}, private="office"),  # 2.357.0 C (#3158)
    OiT("office/signoffs.json", "office_signoffs", refs={"doc_id": "office_docs", "list_id": "lists", "section_id": "sections", "task_id": "tasks",
        "gen_doc_id": "office_gen_docs"}, late={"video_id": "video_reviews"}, people=_P, private="office", prep=_p_signoff, after=_a_signoff),
    OiT("office/privacy_sheets.json", "office_privacy_sheets", refs={"client_id": "clients", "gen_doc_id": "office_gen_docs"},
        late={"signed_node_id": "fs_nodes"}, people=_P, private="office"),  # 2.154.0 C (#2192): the mail code is new on the target (code_hash dropped)
    # 2.184.0 A (#2579): the correspondence: letters (the filed PDF set once the file store is in), text blocks, signatures;
    # the links to documents come with the documents (oi_store.py)
    OiT("office/letters.json", "office_letters", refs={"client_id": "clients", "contact_id": "contacts", "template_id": "office_doc_templates",
        "followup_task_id": "tasks"}, late={"node_id": "fs_nodes"}, people={**_P, "agent_id": "null"}, private="office", label=N_("Letters"),
        prep=_p_letter),
    OiT("office/letter_blocks.json", "office_letter_blocks", people=_P, private="office", label=N_("Letters")),
    OiT("office/letter_profiles.json", "office_letter_profiles", people={"user_id": "need"}, private="office", label=N_("Letters"),
        prep=_p_letter_profile),
    OiT("office/trip_purposes.json", "office_trip_purposes", people=_P, private="office"),
    OiT("office/trips.json", "office_trips", refs={"client_id": "clients"}, people=_P, private="office"),
    OiT("office/trip_items.json", "office_trip_items", refs={"trip_id": "office_trips", "billed_doc_id": "office_docs"}, need=("trip_id",),
        private="office"),
    OiT("office/vehicles.json", "office_vehicles", people=_P, private="office"),
    OiT("office/drives.json", "office_drives", refs={"vehicle_id": "office_vehicles", "client_id": "clients", "trip_id": "office_trips"},
        people={**_P, "user_id": "null"}, private="office"),
    OiT("office/drive_log.json", "office_drive_log", refs={"drive_id": "office_drives"}, need=("drive_id",), people={"by_user": "null"},
        private="office"),
    # 2.362.0 (#3096): the closed months of the logbook stay closed (one already closed in the target is left as it is)
    OiT("office/drive_closed.json", "office_drive_closed", refs={"vehicle_id": "office_vehicles"}, people={"closed_by": "null"},
        private="office", label=N_("Logbook"), prep=_p_drive_closed),
    OiT("office/cashbooks.json", "office_cashbooks", people=_P, private="office"),
    OiT("office/cash_entries.json", "office_cash_entries", refs={"book_id": "office_cashbooks", "invoice_id": "office_docs"}, need=("book_id",),
        late={"storno_of": "office_cash_entries", "node_id": "fs_nodes"}, people=_P, private="office"),
    OiT("office/cash_closings.json", "office_cash_closings", refs={"book_id": "office_cashbooks"}, need=("book_id",),
        people={"closed_by": "null"}, private="office",
        after=lambda c, run, src, nid, ctx: _oi_mark(c, run, ctx, "cashbook", None, {"closing": nid, "day": _txt(src.get("day"), 10)})),  # 2.237.0 D (#2870)
    OiT("office/cash_log.json", "office_cash_log", refs={"book_id": "office_cashbooks", "entry_id": "office_cash_entries"}, need=("book_id",),
        people={"by_user": "null"}, private="office"),
    OiT("office/period_locks.json", "office_period_locks", people={"locked_by": "null"}, private="office", rid=False,
        key=("org_id", "period"),  # 2.148.0 A (#2471): locked accounting periods
        after=lambda c, run, src, nid, ctx: _oi_mark(c, run, ctx, "period", None, {"period": _txt(src.get("period"), 7)})),  # 2.237.0 D (#2870)
    OiT("office/procdocs.json", "office_procdocs", people=_P, private="office", prep=_p_procdoc,
        label=N_("Procedure documentation")),  # 2.148.0 C (#2472): procedure documentation
    OiT("office/suppliers.json", "office_suppliers", refs={"import_run_id": "office_import_runs"}, private="office"),  # 2.148.0 D (#2458)
    OiT("office/opening_balances.json", "office_opening_balances", refs={"import_run_id": "office_import_runs"}, private="office",
        prep=_p_opening),  # 2.188.0 A (#2498): no double on a second import
    OiT("office/datev_guids.json", "office_datev_guids", refs={"doc_id": "office_docs"}, late={"node_id": "fs_nodes"}, private="office",
        prep=_p_datev_guid),  # 2.188.0 A (#2498): the receipt images keep their GUID in DATEV (no double after a move)
    # 2.187.0 C (#2476): the office rights' own groups and their log come along (an organisation only: the private space has
    # no groups of an organisation); the memberships never -- the target's admins assign its people themselves (until
    # then the members have the previous access and the agents none)
    OiT("office/rights_groups.json", "office_rgroups", people=_P, private=False),
    OiT("office/rights_log.json", "office_rights_log", people={"by_user": "null", "target_user": "null"}, private=False,
        prep=_p_rights_log),  # 2.187.1 A (#2735)
    OiT("office/meal_choices.json", "office_meal_choices", people=_P, private="office"),
    OiT("office/meals.json", "office_meals", people={**_P, "approved_by": "null"}, private="office"),
    OiT("office/meal_files.json", "office_meal_files", refs={"meal_id": "office_meals"}, need=("meal_id",), people=_P, private="office",
        prep=_p_meal_file),
    OiT("office/meal_log.json", "office_meal_log", refs={"meal_id": "office_meals"}, need=("meal_id",), people={"user_id": "null"},
        private="office"),
    OiT("office/fixed_costs.json", "office_fixed_costs", people={**_P, "remind_user": "null"}, private="office"),
    OiT("office/sub_reminders.json", "office_sub_reminders", refs={"fixed_id": "office_fixed_costs", "task_id": "tasks"}, need=("fixed_id",),
        people={"user_id": "null"}, private="office"),
    OiT("office/dunning_marks.json", "office_dunning_marks", refs={"doc_id": "office_docs", "reminder_id": "office_docs"}, need=("doc_id",),
        private="office"),  # 2.147.1 (#2054, review): a suggested reminder deleted by hand stays not suggested after an import
    OiT("office/peppol_sends.json", "office_peppol_sends", refs={"doc_id": "office_docs"}, need=("doc_id",), people=_P,
        private="office"),  # 2.154.0 B (#1960): the history of sends over Peppol (the connection itself is set up again)
    OiT("office/cashflow_start.json", "office_cf_start", people={"updated_by": "null"}, private="office", rid=False, key=("org_id",),
        prep=_p_once("office_cf_start", N_("The target office already has its own cash flow start balance; it was kept."))),
    OiT("office/cashflow_adjust.json", "office_cf_adjust", people=_P, private="office"),
    OiT("office/cashflow_actual.json", "office_cf_actual", people={"updated_by": "null"}, private="office"),
    OiT("office/bank_imports.json", "office_bank_imports", people=_P, private="office"),
    OiT("office/bank_rules.json", "office_bank_rules", people={"created_by": "null"}, private="office"),  # 2.299.0 B (#3191)
    OiT("office/bank_rule_nos.json", "office_bank_rule_nos", people={"created_by": "null"}, private="office", prep=_p_rule_no),
    OiT("office/bank_tx.json", "office_bank_tx", refs={"import_id": "office_bank_imports", "payment_id": "office_payments"},
        people={"matched_by": "null"}, private="office", prep=_p_tx),
    OiT("office/bank_balances.json", "office_bank_balances", refs={"import_id": "office_bank_imports"}, private="office", prep=_p_bank_balance),
    OiT("office/deals.json", "office_deals", refs={"client_id": "clients", "offer_id": "office_docs", "list_id": "lists",
        "lead_client_id": "clients"}, people=_P, private="office"),
    OiT("office/archive.json", "office_archive", refs={"run_id": "office_import_runs", "client_id": "clients"}, people=_P, private="office",
        prep=_p_archive, after=_a_archive),
    OiT("office/archive-log.json", "office_archive_log", refs={"archive_id": "office_archive"}, need=("archive_id",),
        people={"user_id": "null"}, private="office"),
    OiT("office/pack-installs.json", "office_pack_installs", people={"installed_by": "null"}, private="office"),
    OiT("office/log.json", "office_doc_log", refs={"doc_id": "office_docs"}, people={"user_id": "null"}, private="office", enc=False,
        prep=_p_log),
]
for _s in SPECS:  # what the preview and the warnings name
    _s.label = _s.label or (N_("Clients") if _s.table in ("clients", "office_client_contacts") else N_("Office"))
FIXES = []


# ---------------------------------------------------------------- once every row is in
def _f_docs(c, run, uid, data, who):
    """The documents' lists of other documents (reminders: their invoices; final invoices: their progress invoices)."""
    for src in (data.get("oi") or {}).get("office/documents.json") or []:
        nid = run.m("office_docs", src.get("id"))
        if not nid:
            continue
        sets = {}
        for col in ("ref_doc_ids", "abs_refs"):
            ids = _oi_json(src.get(col), None)
            if isinstance(ids, list) and ids:
                sets[col] = json.dumps([n for n in (run.m("office_docs", i) for i in ids) if n])
        if sets:
            c.execute(f"UPDATE office_docs SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), nid))


def _f_runs(c, run, uid, data, who):
    """The legacy import runs: the ids their undo works on (merged clients, filled master data) mapped, unknown ones dropped."""
    kinds = {"clients": "clients", "services": "office_services", "equipment": "office_equipment", "roles": "office_roles",
             "crew": "office_roles"}
    for src in (data.get("oi") or {}).get("office/import_runs.json") or []:
        nid = run.m("office_import_runs", src.get("id"))
        det = _oi_json(src.get("detail"), {})
        if not nid or not isinstance(det, dict):
            continue
        if isinstance(det.get("merged"), dict):
            det["merged"] = {str(n): v for n, v in ((run.m("clients", k), v) for k, v in det["merged"].items()) if n}
        if isinstance(det.get("filled"), dict):
            det["filled"] = {a: {str(n): v for n, v in ((run.m(kinds[a], k), v) for k, v in m.items()) if n}
                             for a, m in det["filled"].items() if a in kinds and isinstance(m, dict)}
        for key, tbl in (("filled_clients", "clients"), ("filled_suppliers", "office_suppliers")):  # 2.148.0 D (#2458): DATEV runs
            if isinstance(det.get(key), dict):
                det[key] = {str(n): v for n, v in ((run.m(tbl, k), v) for k, v in det[key].items()) if n}
        if isinstance(det.get("replaced"), list):
            det["replaced"] = [dict(x, import_run_id=run.m("office_import_runs", x.get("import_run_id")) if x.get("import_run_id") else None)
                               for x in det["replaced"] if isinstance(x, dict)]
        c.execute("UPDATE office_import_runs SET detail=? WHERE id=?", (json.dumps(det, ensure_ascii=False), nid))


def _f_bank(c, run, uid, data, who):
    """The matches of the bank bookings: an invoice (document) or a receipt (file store); without its partner none."""
    for src in (data.get("oi") or {}).get("office/bank_tx.json") or []:
        nid, kind = run.m("office_bank_tx", src.get("id")), src.get("match_kind")
        if not nid or kind not in ("invoice", "receipt"):
            continue
        mid = run.m("office_docs" if kind == "invoice" else "fs_nodes", src.get("match_id"))
        if mid:
            c.execute("UPDATE office_bank_tx SET match_kind=?, match_id=?, matched_at=? WHERE id=?", (kind, mid, src.get("matched_at"), nid))
        else:
            c.execute("UPDATE office_bank_tx SET payment_id=NULL, matched_by=NULL WHERE id=?", (nid,))


FINISH = [_f_docs, _f_runs, _f_bank, _f_datev_guids]
