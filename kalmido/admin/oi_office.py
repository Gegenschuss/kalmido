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
from .orgimport import OiFix, OiT  # noqa: F401

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
    from ..core.orgcrypt import oc_json_store
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
    from ..core.orgcrypt import oc_json_store
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


def _a_doc(c, run, src, nid, ctx):
    """The stored files of a finalised document (PDF / XML under the new id) and the snapshots its sender names."""
    from ..office.pdfweb import epdf_name
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
    from ..core.orgcrypt import oc_json_store
    if "sheet" in d:
        d["sheet"] = json.dumps(_oi_ids(run, _oi_json(src.get("sheet"), {})), ensure_ascii=False)
    if "settings" in d:
        d["settings"] = json.dumps(_oi_ids(run, _oi_json(src.get("settings"), {})), ensure_ascii=False)
    j = _oi_json(d.get("totals"), None)
    if isinstance(j, dict):
        d["totals"] = json.dumps(oc_json_store(c, ctx.space, "office_doc_parts", "totals", j), ensure_ascii=False)
    return d


def _p_item(c, run, src, d, ctx):
    from ..core.orgcrypt import oc_item_store
    return oc_item_store(c, ctx.space, d)


def _p_purchase(c, run, src, d, ctx):
    kind = "office_doc_items" if src.get("source") == "item" else "office_doc_parts"
    d["ref"] = run.m(kind, src.get("ref"))
    return d


def _p_signoff(c, run, src, d, ctx):
    from ..core.db import iso, now_utc
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


def _p_bank_balance(c, run, src, d, ctx):
    """Balances hang on their statement import; without it (an older export) on one import row of this run."""
    if d.get("import_id"):
        return d
    from ..core.db import insert_id, iso, now_utc
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
    from ..core.orgcrypt import oc_log_detail
    if d.get("detail"):
        d["detail"] = oc_log_detail(c, ctx.space, d["detail"])  # like the app: only entries with protected keys sealed
    return d


def _p_tx(c, run, src, d, ctx):
    for k in ("match_kind", "matched_at"):  # set again by the finish pass once the match is known
        d.pop(k, None)
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
        "part_id": "office_doc_parts", "ref_part_id": "office_doc_parts"}, need=("doc_id",), private="office", prep=_p_item),
    OiT("office/purchases.json", "office_purchases", refs={"doc_id": "office_docs"}, need=("doc_id",), private="office", prep=_p_purchase),
    OiT("office/invoice_series.json", "office_inv_series", refs={"template_id": "office_docs"}, need=("template_id",), people=_P, private="office"),
    OiT("office/payments.json", "office_payments", refs={"doc_id": "office_docs"}, need=("doc_id",), people=_P, private="office"),
    OiT("office/pay-props.json", "office_pay_props", refs={"doc_id": "office_docs", "payment_id": "office_payments"}, need=("doc_id",),
        people={"agent_id": "null", "requested_by": "null", "decided_by": "null"}, private="office"),
    OiT("office/gen_docs.json", "office_gen_docs", refs={"template_id": "office_doc_templates", "client_id": "clients", "list_id": "lists",
        "doc_id": "office_docs"}, late={"node_id": "fs_nodes", "signed_node_id": "fs_nodes"}, people=_P, private="office"),
    OiT("office/signoffs.json", "office_signoffs", refs={"doc_id": "office_docs", "list_id": "lists", "section_id": "sections", "task_id": "tasks",
        "gen_doc_id": "office_gen_docs"}, late={"video_id": "video_reviews"}, people=_P, private="office", prep=_p_signoff, after=_a_signoff),
    OiT("office/privacy_sheets.json", "office_privacy_sheets", refs={"client_id": "clients", "gen_doc_id": "office_gen_docs"},
        late={"signed_node_id": "fs_nodes"}, people=_P, private="office"),  # 2.154.0 C (#2192): the mail code is new on the target (code_hash dropped)
    OiT("office/trip_purposes.json", "office_trip_purposes", people=_P, private="office"),
    OiT("office/trips.json", "office_trips", refs={"client_id": "clients"}, people=_P, private="office"),
    OiT("office/trip_items.json", "office_trip_items", refs={"trip_id": "office_trips", "billed_doc_id": "office_docs"}, need=("trip_id",),
        private="office"),
    OiT("office/vehicles.json", "office_vehicles", people=_P, private="office"),
    OiT("office/drives.json", "office_drives", refs={"vehicle_id": "office_vehicles", "client_id": "clients", "trip_id": "office_trips"},
        people={**_P, "user_id": "null"}, private="office"),
    OiT("office/drive_log.json", "office_drive_log", refs={"drive_id": "office_drives"}, need=("drive_id",), people={"by_user": "null"},
        private="office"),
    OiT("office/cashbooks.json", "office_cashbooks", people=_P, private="office"),
    OiT("office/cash_entries.json", "office_cash_entries", refs={"book_id": "office_cashbooks", "invoice_id": "office_docs"}, need=("book_id",),
        late={"storno_of": "office_cash_entries", "node_id": "fs_nodes"}, people=_P, private="office"),
    OiT("office/cash_closings.json", "office_cash_closings", refs={"book_id": "office_cashbooks"}, need=("book_id",),
        people={"closed_by": "null"}, private="office"),
    OiT("office/cash_log.json", "office_cash_log", refs={"book_id": "office_cashbooks", "entry_id": "office_cash_entries"}, need=("book_id",),
        people={"by_user": "null"}, private="office"),
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
    OiT("office/cashflow_start.json", "office_cf_start", people={"updated_by": "null"}, private="office", rid=False, key=("org_id",),
        prep=_p_once("office_cf_start", N_("The target office already has its own cash flow start balance; it was kept."))),
    OiT("office/cashflow_adjust.json", "office_cf_adjust", people=_P, private="office"),
    OiT("office/cashflow_actual.json", "office_cf_actual", people={"updated_by": "null"}, private="office"),
    OiT("office/bank_imports.json", "office_bank_imports", people=_P, private="office"),
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


FINISH = [_f_docs, _f_runs, _f_bank]
