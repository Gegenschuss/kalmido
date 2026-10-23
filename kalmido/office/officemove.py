"""2.97.0 C (#2049): office data between the personal office and an organisation's office (customers, contacts, drafts,
travel-expense drafts, templates move; issued invoices, closed receipts, number ranges and the archive stay). Built by part C.

The mapping: the workspace "Private" (org_id NULL elsewhere) is the person's personal office -- a hidden orgs row
(orgs.personal_of = uid, model.py pb_personal) whose id is the org_id of every office_* row there; the private clients
and their contact persons keep org_id NULL (created_by = the owner, model.py pb_cl_sql). An organisation's office uses the
organisation's id for both. So per row: "area" tables (office_docs, items, parts, trips, receipts, templates) carry the
office area id, "workspace" tables (clients, office_client_contacts) the workspace org id (NULL = private).

POST /api/office/move-space {what: clients | drafts | travel | templates, ids, to, dry, copy_issued} -- the rules of
accounts/spacemove.py (agents 403, the target an organisation the person is a member of, else 409) plus the office roles:
a role in the source office (404 without), a role in the target office; travel expenses and templates need the admin of
both offices (like their routes); out of an organisation only the admin of its office or who created the thing (403).
What moves keeps its id (one UPDATE per row, the protected fields re-sealed with the target's key, core/orgcrypt.py):
- drafts (status draft, never finalised, no payment / sign-off link / purchase / billed receipt / series / credit or
  reminder reference): their number is emptied (the target numbers them when they are issued), the links into the old
  office end (framework contract, project, agent, the deal or template document pointing at them, the catalogue service
  of a position); the client and its contact person follow when they move along, else the draft keeps only the address;
- a client takes its contact persons and its drafts. A client that something else in the old workspace still points at
  (issued documents, archive entries, trips, deals, projects ...) stays there archived and is created anew in the target;
  otherwise it moves as a whole. The address-book links of its contact persons end (the address books stay);
- trips without a receipt ticked "in DATEV" or billed, with their receipts; templates (documents made from them keep
  their text and lose the link).
Issued documents never move (retention). copy_issued=1 files a read-only copy of each issued document of a moving client
(and of its archive entries) into the target's document archive (office_archive, copy_of = where it came from): view and
PDF only, no number (the target's number ranges stay untouched, legacyimport.py fi_number_taken), never edited
(archiveedit.py), and the archive is no source of the books, DATEV, VAT or cash flow (they read office_docs / receipts).
Every move is one space_moves row (kind office_<what>, from / to = workspace) whose detail holds the old values, and an
entry in both office logs. {undo: <that id>} (the same person) takes it back in one step: the rows go back (re-sealed),
the client copies and archive copies made by the move go again (a copied client the target has used since stays)."""
import hashlib
import json
import os
import uuid

from flask import jsonify

from ..core.config import OFFICE_DIR, app
from ..core.access import Denied
from ..core.db import body, bump, db, iso, now_utc
from ..core.i18n import N_, tr, trn
from ..core.merges import mg_fk_refs
from ..core.orgcrypt import FIELDS, JSON_KEYS, oc_dec_fields, oc_enc_fields, oc_item_store, oc_json_store, oc_read_file, oc_write_file
from ..core.pg import insert_id, table_columns, write_lock
from ..core.errors import BadInput
from ..accounts.spacemove import SMV_MAX, smv_answer, smv_refuse_agent, smv_same, smv_target
from .ledger import ofx_log
from .model import OFFICE_ADMIN_ONLY, office_gate, office_role, pb_owner, pb_personal
from .rights import NO_RIGHT, office_can, ofr_rights

OFM_WHAT = ("clients", "drafts", "travel", "templates", "meals")  # 2.119.0 A (#2288): + entertainment receipts (drafts)
OFM_TABLE = {"drafts": "office_docs", "travel": "office_trips", "templates": "office_doc_templates", "meals": "office_meals"}
OFM_ADMIN = ("travel", "templates", "meals")  # their routes are for the office's admins only (travel.py, doctpl.py, meals.py)
OFM_MAX = 200  # objects named in one move (a client's drafts and contact persons come on top, SMV_MAX in all)
OFM_ONLY = N_("Only who created it or an admin of the organisation can move it out of it")
OFM_RO = N_("This is a read-only copy of an issued document")
# rows that keep a document in its office (it is no longer only a draft there)
OFM_DOC_HOLD = ("office_payments", "office_purchases", "office_signoffs", "office_pay_props")
OFM_DOC_KIDS = ("office_doc_items", "office_doc_parts")  # move with their document
# the undo puts a link back only while what it points at still exists
OFM_FK = {"office_docs": {"client_id": "clients", "contract_id": "office_contracts", "list_id": "lists"},
          "office_doc_items": {"service_id": "office_services"}, "office_client_contacts": {"contact_id": "contacts"}}
# 2.119.1 C (#2298): framework contracts with their PDF files (office/contractfiles.py); their routes are for admins only
OFM_WHAT += ("contracts",)
OFM_TABLE["contracts"] = "office_contracts"
OFM_ADMIN += ("contracts",)
OFM_FK["office_contracts"] = {"client_id": "clients", "rights_time_id": "office_texts", "rights_territory_id": "office_texts",
                              "rights_media_id": "office_texts"}


def ofm_fk_refs(c, table):
    """mg_fk_refs cached per request (the catalogue does not change during one)."""
    from flask import g
    cache = g.setdefault("ofm_fk", {})
    if table not in cache:
        cache[table] = mg_fk_refs(c, table)
    return cache[table]


def ofm_ws(c, area):
    """The workspace (org id | None = private) of office area id area."""
    return None if pb_owner(c, area) is not None else area


def ofm_ws_key(ws):
    return f"org:{ws}" if ws else "private"


def ofm_ids(v):
    if not isinstance(v, list) or not v or len(v) > OFM_MAX:
        raise BadInput(tr("Invalid value: {0}", "ids"))
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, int) or x < 1:
            raise BadInput(tr("Invalid value: {0}", "ids"))
        if x not in out:
            out.append(x)
    return out


def ofm_reseal(c, table, row, src, dst):
    """{column: value} of row's protected columns (FIELDS, the protected keys of JSON columns, the purchase price of a
    position) opened with area src's key and sealed for area dst (plain where the target has no encryption)."""
    d = oc_dec_fields(c, src, table, row)
    if table == "office_doc_items":
        st = oc_item_store(c, dst, {"cost": d.get("cost")})
        return {"cost": st.get("cost"), "cost_enc": st.get("cost_enc")}
    out = oc_enc_fields(c, dst, table, {k: d[k] for k in FIELDS.get(table, ()) if k in d})
    for (t, col), _keys in JSON_KEYS.items():
        if t == table and isinstance(d.get(col), str):
            try:
                j = json.loads(d[col])
            except ValueError:
                continue
            if isinstance(j, dict):
                out[col] = json.dumps(oc_json_store(c, dst, table, col, j), ensure_ascii=False, default=str)
    return out


def ofm_set(c, table, rid, cols):
    if cols:
        c.execute(f"UPDATE {table} SET {', '.join(k + '=?' for k in cols)} WHERE id=?", [*cols.values(), rid])


def ofm_refs(c, table, rid, skip=(), skip_ids=None):
    """{table: n} of the rows of other tables pointing at row rid of table (foreign keys, + lists.client_id for clients),
    without the tables in skip and the rows in skip_ids ({table: set of ids})."""
    out = {}
    skip_ids = skip_ids or {}
    for t, col, _d in ofm_fk_refs(c, table):
        if t in skip or t == table and col == "id":
            continue
        ids = skip_ids.get(t)
        if ids:
            q = ",".join("?" * len(ids))
            n = c.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=? AND id NOT IN ({q})", (rid, *ids)).fetchone()[0]
        else:
            n = c.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (rid,)).fetchone()[0]
        if n:
            out[t] = out.get(t, 0) + n
    if table == "clients":
        n = c.execute("SELECT COUNT(*) FROM lists WHERE client_id=?", (rid,)).fetchone()[0]
        if n:
            out["lists"] = n
    return out


# ---------------------------------------------------------------- what may move
def ofm_doc_hold(c, r):
    """None when document row r may move, else why it stays: 'issued' | 'linked'."""
    if r["status"] != "draft" or r["locked_at"]:
        return "issued"
    if r["kind"] in ("invoice", "credit") and r["number"]:  # 2.126.0 A (#1966): its number belongs to this office's series
        return "issued"
    if r["series_id"] or r["cancels_id"] or (r["ref_doc_ids"] or "").strip() not in ("", "[]", "null"):
        return "linked"
    for t in OFM_DOC_HOLD:
        if c.execute(f"SELECT 1 FROM {t} WHERE doc_id=? LIMIT 1", (r["id"],)).fetchone():
            return "linked"
    if c.execute("SELECT 1 FROM office_trip_items WHERE billed_doc_id=? LIMIT 1", (r["id"],)).fetchone():
        return "linked"
    for t, col, d in ofm_fk_refs(c, "office_docs"):  # a later table holding the document in its office (not set-null)
        if t not in OFM_DOC_KIDS + OFM_DOC_HOLD and d != "n" and c.execute(f"SELECT 1 FROM {t} WHERE {col}=? LIMIT 1", (r["id"],)).fetchone():
            return "linked"
    return None


def ofm_trip_hold(c, r):
    """None when trip row r may move (no receipt in DATEV or billed), else 'issued'."""
    if c.execute("SELECT 1 FROM office_trip_items WHERE trip_id=? AND (datev=1 OR datev_no!='' OR billed_doc_id IS NOT NULL) LIMIT 1",
                 (r["id"],)).fetchone():
        return "issued"
    for t, col, d in ofm_fk_refs(c, "office_trips"):
        if t != "office_trip_items" and d != "n" and c.execute(f"SELECT 1 FROM {t} WHERE {col}=? LIMIT 1", (r["id"],)).fetchone():
            return "issued"
    return None


def ofm_meal_hold(c, r):
    """2.119.0 A (#2288): None when entertainment receipt r may move (a draft, not in the trash), else 'issued'."""
    return "issued" if r["status"] == "approved" or r["deleted_at"] else None


def ofm_meal_people(c, uid, r, src, dst):
    """2.119.0 A (#2288): host / guests of meal row r for office dst: a person of the old office who is no person of the new
    one stays as a free name (sealed for dst)."""
    from .travel import rk_people
    d = oc_dec_fields(c, src, "office_meals", r)
    known = {p["id"] for p in rk_people(c, dst, uid)}
    def keep(p):
        return p if not isinstance(p, dict) or not p.get("id") or p["id"] in known else {"name": p.get("name") or "", "extra": ""}
    try:
        host, guests = json.loads(d.get("host") or "{}"), json.loads(d.get("guests") or "[]")
    except ValueError:
        return {}
    return oc_enc_fields(c, dst, "office_meals", {"host": json.dumps(keep(host), ensure_ascii=False),
                                                  "guests": json.dumps([keep(g) for g in guests if isinstance(g, dict)], ensure_ascii=False)})


def ofm_need(c, uid, what, ids):
    """(source area, rows) of the objects to move: all visible to uid in ONE office (404 / 400)."""
    if what == "clients":
        from ..team.clients import need_client
        rows = [need_client(c, i, uid) for i in ids]
        ws = {r["org_id"] or None for r in rows}
        if len(ws) != 1:
            raise BadInput(tr("Choose items of one workspace"))
        w = ws.pop()
        if w is None and any(r["created_by"] != uid for r in rows):
            raise Denied(404)
        return (pb_personal(c, uid) if w is None else w), rows
    t = OFM_TABLE[what]
    q = ",".join("?" * len(ids))
    rows = c.execute(f"SELECT * FROM {t} WHERE id IN ({q}) ORDER BY id", ids).fetchall()
    if len(rows) != len(ids):
        raise Denied(404)
    areas = {r["org_id"] for r in rows}
    if len(areas) != 1:
        raise BadInput(tr("Choose items of one workspace"))
    area = areas.pop()
    if not office_role(c, uid, area) or office_role(c, uid, area) == "guest":
        raise Denied(404)
    return area, rows


def ofm_writer(c, uid, *areas):
    """2.143.0 A (#2151, review): moving changes both offices -- 403 for guest / read-only / accounting in either of them."""
    from ..accounts.orgroles import office_allowed
    for a in areas:
        no = office_allowed(c, uid, a, write=True)
        if no:
            raise Denied(403, tr(no))


# 2.187.0 C (#2476): the office area (office/rights.py) of each kind of object that moves
OFM_RIGHTS_AREA = {"clients": "offers", "drafts": "offers", "travel": "travel", "templates": "gendocs", "meals": "meals", "contracts": "contracts"}


def ofm_groups(c, uid, what, *areas):
    """2.187.0 C (#2476): a person ruled by office groups in one of the two offices needs the area of what to edit there."""
    for a in areas:
        if ofr_rights(c, uid, a) is not None and not office_can(c, uid, a, OFM_RIGHTS_AREA.get(what, "settings"), "edit"):
            raise Denied(403, tr(NO_RIGHT))


def ofm_rights(c, uid, what, src, dst, rows):
    """403 unless uid may take rows out of office src into office dst."""
    rs, rt = office_role(c, uid, src), office_role(c, uid, dst)
    if not rs:
        raise Denied(404)
    if not rt:
        raise Denied(409, tr("You are not a member of this organisation"))
    ofm_writer(c, uid, src, dst)
    ofm_groups(c, uid, what, src, dst)
    if what in OFM_ADMIN and (rs != "admin" or rt != "admin"):
        raise Denied(403, tr(OFFICE_ADMIN_ONLY))
    if pb_owner(c, src) is None and rs != "admin" and any(r["created_by"] != uid for r in rows):
        raise Denied(403, tr(OFM_ONLY))
    if what == "travel":  # 2.148.0 A (#2471): a trip leaves / enters no locked month
        from .travel import _trip_need_open
        for r in rows:
            _trip_need_open(c, src, r)
            _trip_need_open(c, dst, r)


# ---------------------------------------------------------------- the plan (dry run and move share it)
def ofm_plan(c, uid, what, src, rows, own=False):
    """{docs: [movable draft rows], keep: {why: n}, clients: [{row, mode: move | copy, refs, issued, contacts, docs}],
    trips, tpls} -- what would move and what stays. own: only uid's own drafts leave (a plain member out of an
    organisation: the drafts of the others stay with the client there)."""
    p = {"docs": [], "keep": {}, "clients": [], "trips": [], "tpls": [], "meals": [], "detach": 0, "unclient": 0}
    def keep(k, n=1):
        p["keep"][k] = p["keep"].get(k, 0) + n
    if what == "drafts":
        for r in rows:
            why = ofm_doc_hold(c, r)
            if why:
                keep(why)
            else:
                p["docs"].append(r)
                p["unclient"] += 1 if r["client_id"] else 0
    elif what == "travel":
        for r in rows:
            if ofm_trip_hold(c, r):
                keep("trip")
            else:
                p["trips"].append(r)
                p["unclient"] += 1 if r["client_id"] else 0
    elif what == "contracts":  # 2.119.1 C (#2298)
        rmv_plan(c, p, rows)
    elif what == "meals":  # 2.119.0 A (#2288)
        for r in rows:
            if ofm_meal_hold(c, r):
                keep("meal")
            else:
                p["meals"].append(r)
    elif what == "templates":
        p["tpls"] = list(rows)
        q = ",".join("?" * len(rows))
        p["detach"] = c.execute(f"SELECT COUNT(*) FROM office_gen_docs WHERE template_id IN ({q})", [r["id"] for r in rows]).fetchone()[0]
    else:
        for r in rows:
            docs, issued = [], []
            for d in c.execute("SELECT * FROM office_docs WHERE org_id=? AND client_id=? ORDER BY id", (src, r["id"])).fetchall():
                if d["trial"]:  # 2.144.10 (#2576, review): trial documents stay where they are (no archive copy, no TEST number clash)
                    continue
                why = ofm_doc_hold(c, d)
                if why == "issued":
                    issued.append(d)
                elif not why and own and d["created_by"] != uid:
                    keep("others")
                elif not why:
                    docs.append(d)
            refs = ofm_refs(c, "clients", r["id"], skip=("office_client_contacts",), skip_ids={"office_docs": [d["id"] for d in docs]})
            arch = c.execute("SELECT * FROM office_archive WHERE org_id=? AND client_id=? AND copy_of IS NULL ORDER BY id",
                             (src, r["id"])).fetchall()
            contacts = c.execute("SELECT * FROM office_client_contacts WHERE client_id=? ORDER BY sort, id", (r["id"],)).fetchall()
            p["clients"].append({"row": r, "mode": "copy" if refs else "move", "refs": refs, "issued": issued, "arch": arch,
                                 "contacts": contacts, "docs": docs})
            p["docs"].extend(docs)
    return p


def ofm_notes(c, what, p, copy):
    notes, block = [], None
    if what == "clients":
        cl = p["clients"]
        moved = sum(1 for x in cl if x["mode"] == "move")
        ks = sum(len(x["contacts"]) for x in cl)
        notes.append(trn("{0} client moves", "{0} clients move", moved) if moved else "")
        for x in [x for x in cl if x["mode"] == "copy"][:8]:
            n = len(x["issued"]) + len(x["arch"])
            notes.append(trn("“{1}” stays archived in the old workspace for {0} issued document and is created anew in the target",
                             "“{1}” stays archived in the old workspace for {0} issued documents and is created anew in the target", n, x["row"]["name"])
                         if n else tr("“{0}” is still used in the old workspace (projects, trips or deals): it stays there archived and is created anew in the target",
                                      x["row"]["name"]))
        notes.append(trn("{0} contact person moves along (links to the address book end)", "{0} contact persons move along (links to the address book end)", ks) if ks else "")
        issued = sum(len(x["issued"]) + len(x["arch"]) for x in cl)
        if issued:
            notes.append(trn("{0} issued document stays in the old workspace (retention)", "{0} issued documents stay in the old workspace (retention)", issued))
            notes.append(tr("Copied read-only into the archive of the target: view and PDF, no number, not in the books, DATEV or VAT there") if copy
                         else tr("Tick the box to take a read-only copy along"))
    if p["docs"]:
        notes.append(trn("{0} draft moves", "{0} drafts move", len(p["docs"])))
        notes.append(tr("Drafts get their number in the target when they are issued"))
    if what == "drafts" and p["unclient"]:
        notes.append(trn("{0} draft loses its client (the address stays in it)", "{0} drafts lose their client (the address stays in them)", p["unclient"]))
    if p["trips"]:
        notes.append(trn("{0} trip moves with its receipts", "{0} trips move with their receipts", len(p["trips"])))
        if p["unclient"]:
            notes.append(trn("{0} trip loses its client", "{0} trips lose their client", p["unclient"]))
    if p["meals"]:  # 2.119.0 A (#2288)
        notes.append(trn("{0} entertainment receipt moves with its bill", "{0} entertainment receipts move with their bills", len(p["meals"])))
    if p["tpls"]:
        notes.append(trn("{0} template moves", "{0} templates move", len(p["tpls"])))
        if p["detach"]:
            notes.append(trn("{0} document made from it keeps its text and stays", "{0} documents made from them keep their text and stay", p["detach"]))
    if p.get("ctr"):
        notes.extend(rmv_notes(p))  # 2.119.1 C (#2298)
    k = p["keep"]
    if k.get("issued"):
        notes.append(trn("{0} issued document stays in the old workspace (retention)", "{0} issued documents stay in the old workspace (retention)", k["issued"]))
    if k.get("others"):
        notes.append(trn("{0} draft of somebody else stays with the client in the organisation", "{0} drafts of other people stay with the client in the organisation", k["others"]))
    if k.get("linked"):
        notes.append(trn("{0} draft stays: it has payments, a sign-off link or billed receipts there", "{0} drafts stay: they have payments, sign-off links or billed receipts there", k["linked"]))
    if k.get("trip"):
        notes.append(trn("{0} trip stays: receipts of it are in DATEV or billed", "{0} trips stay: receipts of them are in DATEV or billed", k["trip"]))
    if k.get("meal"):  # 2.119.0 A (#2288)
        notes.append(trn("{0} entertainment receipt stays: it is approved (retention)", "{0} entertainment receipts stay: they are approved (retention)", k["meal"]))
    if not (p["clients"] or p["docs"] or p["trips"] or p["tpls"] or p["meals"] or p.get("ctr")):
        block = tr("Nothing here can move: issued documents and receipts stay where they were issued")
    return notes, block


# ---------------------------------------------------------------- moving
def ofm_move_row(c, rec, table, r, src, dst, new_org, extra=None):
    """Moves row r of an area table from office src to dst (re-sealed) + the extra column values; notes the old ones."""
    cols = {"org_id": new_org, **ofm_reseal(c, table, r, src, dst), **(extra or {})}
    rec.append({"t": table, "id": r["id"], "org": new_org, "area": 1, "old": {k: r[k] for k in cols if k in r.keys()
                                                                                 and k not in FIELDS.get(table, ()) and k != "cost_enc"
                                                                                 and (table, k) not in JSON_KEYS}})
    ofm_set(c, table, r["id"], cols)


def ofm_detach(c, rec, table, col, val, ref):
    """Ends the links of table.col to row val of table ref (set to NULL), noted for the undo."""
    if "id" not in table_columns(c, table):
        return
    for x in c.execute(f"SELECT id FROM {table} WHERE {col}=?", (val,)).fetchall():
        rec.append({"t": table, "id": x["id"], "old": {col: val}, "detach": col, "ref": ref})
        c.execute(f"UPDATE {table} SET {col}=NULL WHERE id=?", (x["id"],))


def ofm_move_doc(c, rec, r, src, dst, cmap, kmap, ts):
    ofm_move_row(c, rec, "office_docs", r, src, dst, dst, {
        "number": "", "client_id": cmap.get(r["client_id"]) if r["client_id"] else None,
        "contact_id": kmap.get(r["contact_id"]) if r["contact_id"] else None, "contract_id": None, "list_id": None,
        "agent_id": None, "source_doc_id": None, "version_of": None, "updated_at": ts})
    for it in c.execute("SELECT * FROM office_doc_items WHERE doc_id=? ORDER BY id", (r["id"],)).fetchall():
        # 2.144.5 A2 (#1523, review R10): the list a position came from belongs to the old office
        ofm_move_row(c, rec, "office_doc_items", it, src, dst, dst, {"service_id": None, "list_id": None})
    for pt in c.execute("SELECT * FROM office_doc_parts WHERE doc_id=? ORDER BY id", (r["id"],)).fetchall():
        ofm_move_row(c, rec, "office_doc_parts", pt, src, dst, dst)
    for t, col, d in ofm_fk_refs(c, "office_docs"):  # the deal / template document / other version pointing at it
        if d == "n" and t not in OFM_DOC_KIDS:
            ofm_detach(c, rec, t, col, r["id"], "office_docs")


def ofm_archive_copy(c, uid, made, files, src, dst, cid, r, frm, kind="doc"):
    """A read-only copy of an issued document (kind doc: office_docs row r) or of an archive entry (kind archive) of office
    src in office dst's archive: the PDF (stored or rendered from the snapshot) sealed for dst, no number."""
    if kind == "doc":
        from .pdfweb import _render, _stored, epdf_name
        p = _stored(src, r, "pdf")
        try:
            data = oc_read_file(c, p) if p else _render(c, src, r)[0]
        except (BadInput, Denied, OSError):
            return  # cannot be printed (e.g. an e-invoice without the buyer reference): no copy, the original stays

        try:
            gross = json.loads(r["totals"] or "{}").get("gross")
        except ValueError:
            gross = None
        try:
            rec_name = json.loads(r["recipient"] or "{}").get("name") or ""
        except ValueError:
            rec_name = ""
        f = {"kind": "offer" if r["kind"] == "offer" else "invoice", "project": (r["project_title"] or "")[:200], "client_name": str(rec_name)[:200],
             "date": r["date"] or "", "amount": None if gross is None else str(round(float(gross), 2)), "currency": r["currency"] or "EUR",
             "paid": 1 if r["status"] == "paid" else 0, "file_name": epdf_name(r) + ".pdf"}
        src_ref = {"doc": r["id"], "kind": r["kind"], "number": r["number"] or ""}
    else:
        from .legacyimport import fi_archive_path
        p = fi_archive_path(src, r["file"])
        if not p:
            return
        data = oc_read_file(c, p)
        f = {k: r[k] for k in ("kind", "project_no", "project", "client_name", "date", "amount", "currency", "paid", "file_name", "tax_lines")}
        src_ref = {"archive": r["id"], "kind": r["kind"], "number": r["number"] or ""}
    sha = hashlib.sha256(data).hexdigest()
    if c.execute("SELECT 1 FROM office_archive WHERE org_id=? AND sha256=?", (dst, sha)).fetchone():
        return  # already there
    row = dict(f, org_id=dst, run_id=None, number="", client_id=cid, file="", sha256=sha, bytes=len(data), created_by=uid,
               created_at=iso(now_utc()), copy_of=json.dumps(dict(src_ref, **frm), ensure_ascii=False))
    aid = insert_id(c, f"INSERT INTO office_archive({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    name = f"archive-{int(aid)}-{sha[:16]}.pdf"
    d = os.path.join(OFFICE_DIR, str(int(dst)))
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, name)
    files.append(path)
    oc_write_file(c, dst, path, data, fresh=True)  # sealed with the target's key at rest (sha256 = the original)
    c.execute("UPDATE office_archive SET file=? WHERE id=?", (name, aid))
    made.append({"t": "office_archive", "id": aid, "file": name})


def ofm_move_clients(c, uid, p, src, dst, to, copy, rec, made, files, ts, frm):
    cmap, kmap = {}, {}
    cols = sorted(table_columns(c, "clients") - {"id"})
    kcols = sorted(table_columns(c, "office_client_contacts") - {"id"})
    for x in p["clients"]:
        r = x["row"]
        if x["mode"] == "move":
            rec.append({"t": "clients", "id": r["id"], "org": to, "old": {"org_id": r["org_id"], "created_by": r["created_by"]}})
            c.execute("UPDATE clients SET org_id=?, created_by=?, updated_at=? WHERE id=?", (to, uid if to is None else r["created_by"], ts, r["id"]))
            for k in x["contacts"]:
                rec.append({"t": "office_client_contacts", "id": k["id"], "org": to, "old": {"org_id": k["org_id"], "contact_id": k["contact_id"]}})
            c.execute("UPDATE office_client_contacts SET org_id=?, contact_id=NULL WHERE client_id=?", (to, r["id"]))
            # the lists of other people that still name it (not visible here) lose it, like PATCH /api/clients does
            c.execute("UPDATE lists SET client_id=NULL WHERE client_id=? AND org_id IS DISTINCT FROM ?", (r["id"], to))
            cmap[r["id"]] = r["id"]
            kmap.update({k["id"]: k["id"] for k in x["contacts"]})
        else:
            row = {k: r[k] for k in cols}
            row.update(org_id=to, created_by=uid, created_at=ts, updated_at=ts, archived=0)
            if "import_run_id" in row:
                row["import_run_id"] = None
            nid = insert_id(c, f"INSERT INTO clients({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
            made.append({"t": "clients", "id": nid})
            cmap[r["id"]] = nid
            for k in x["contacts"]:
                kr = {col: k[col] for col in kcols}
                kr.update(org_id=to, client_id=nid, contact_id=None, created_at=ts, updated_at=ts)
                if "import_run_id" in kr:
                    kr["import_run_id"] = None
                kmap[k["id"]] = insert_id(c, f"INSERT INTO office_client_contacts({','.join(kr)}) VALUES({','.join('?' * len(kr))})", list(kr.values()))
            if not r["archived"]:
                rec.append({"t": "clients", "id": r["id"], "old": {"archived": 0}, "src": 1})
                c.execute("UPDATE clients SET archived=1, updated_at=? WHERE id=?", (ts, r["id"]))
            if copy:
                for d in x["issued"]:
                    ofm_archive_copy(c, uid, made, files, src, dst, nid, d, frm)
                for a in x["arch"]:
                    ofm_archive_copy(c, uid, made, files, src, dst, nid, a, frm, kind="archive")
    return cmap, kmap


@app.post("/api/office/move-space")
def ofm_move_space():
    smv_refuse_agent()
    c = db()
    uid = office_gate(c)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if b.get("undo") not in (None, "", 0):
        return ofm_undo(c, uid, b.get("undo"))
    what = b.get("what")
    if what not in OFM_WHAT:
        raise BadInput(tr("Invalid value: {0}", "what"))
    ids = ofm_ids(b.get("ids"))
    src, rows = ofm_need(c, uid, what, ids)
    frm_ws = ofm_ws(c, src)
    to = smv_target(c, uid, b.get("to"))
    smv_same(frm_ws, to)
    dst = pb_personal(c, uid) if to is None else to
    ofm_rights(c, uid, what, src, dst, rows)
    copy = b.get("copy_issued") in (1, True, "1")
    plain = pb_owner(c, src) is None and office_role(c, uid, src) != "admin"  # a plain member out of an organisation
    p = ofm_plan(c, uid, what, src, rows, own=plain)
    if sum(len(x["contacts"]) + 1 for x in p["clients"]) + len(p["docs"]) + len(p["trips"]) + len(p["tpls"]) + len(p["meals"]) + len(p.get("ctr", ())) > SMV_MAX:
        raise BadInput(tr("Too many at once"))
    notes, block = ofm_notes(c, what, p, copy and not plain)
    if copy and plain:  # copies of an organisation's issued documents: its office admin only
        notes.append(tr("Only an admin of the organisation can take copies of its issued documents along"))
        copy = False
    counts = {"clients": len(p["clients"]), "copied": sum(1 for x in p["clients"] if x["mode"] == "copy"), "drafts": len(p["docs"]),
              "trips": len(p["trips"]), "templates": len(p["tpls"]), "meals": len(p["meals"]), "contacts": sum(len(x["contacts"]) for x in p["clients"]),
              "issued": sum(len(x["issued"]) + len(x["arch"]) for x in p["clients"]) + p["keep"].get("issued", 0),
              "stay": sum(p["keep"].values()), "contracts": len(p.get("ctr", ()))}
    if b.get("dry"):
        return jsonify(smv_answer(notes, block, count=counts))
    if block:
        raise Denied(409, block)
    write_lock(c, f"office_move_{int(src)}")
    ts = iso(now_utc())
    org_name = ""
    if frm_ws:
        o = c.execute("SELECT name FROM orgs WHERE id=?", (frm_ws,)).fetchone()
        org_name = o["name"] if o else ""
    frm = {"from": ofm_ws_key(frm_ws), "name": org_name}
    rec, made, files, old_files = [], [], [], []
    try:
        cmap, kmap = {}, {}
        if what == "clients":
            cmap, kmap = ofm_move_clients(c, uid, p, src, dst, to, copy, rec, made, files, ts, frm)
        for r in p["docs"]:
            ofm_move_doc(c, rec, r, src, dst, cmap, kmap, ts)
        for r in p["trips"]:
            ofm_move_row(c, rec, "office_trips", r, src, dst, dst, {"client_id": None, "updated_at": ts})
            for it in c.execute("SELECT * FROM office_trip_items WHERE trip_id=? ORDER BY id", (r["id"],)).fetchall():
                ofm_move_row(c, rec, "office_trip_items", it, src, dst, dst, {"updated_at": ts})
        if p["trips"]:  # 2.117.0 A (#2292): the own purposes of the moved trips are offered in the new office too
            from .travel import rka_purposes_adopt
            rka_purposes_adopt(c, dst, uid, [r["purpose"] for r in p["trips"]])
        for r in p["meals"]:  # 2.119.0 A (#2288): the draft, its bill (sealed anew for the target) and its log
            from .meals import bw_file_copy, bw_path
            ofm_move_row(c, rec, "office_meals", r, src, dst, dst, {**ofm_meal_people(c, uid, r, src, dst), "updated_at": ts})
            for f in c.execute("SELECT * FROM office_meal_files WHERE meal_id=? AND org_id=? ORDER BY id", (r["id"], src)).fetchall():
                new = bw_file_copy(c, src, dst, f["file"])
                files.append(bw_path(dst, new))
                old_files.append(bw_path(src, f["file"]))
                ofm_move_row(c, rec, "office_meal_files", f, src, dst, dst, {"file": new})
            for lg in c.execute("SELECT * FROM office_meal_log WHERE meal_id=? AND org_id=? ORDER BY id", (r["id"], src)).fetchall():
                ofm_move_row(c, rec, "office_meal_log", lg, src, dst, dst)
        for r in p["tpls"]:
            ofm_move_row(c, rec, "office_doc_templates", r, src, dst, dst, {"updated_at": ts})
            ofm_detach(c, rec, "office_gen_docs", "template_id", r["id"], "office_doc_templates")
        if p.get("ctr"):  # 2.119.1 C (#2298)
            rmv_move(c, uid, p, src, dst, rec, made, files, ts)
        detail = {"src": src, "dst": dst, "what": what, "ids": ids, "copy": 1 if copy else 0, "rows": rec, "made": made, "at": ts}
        mid = insert_id(c, "INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES(?,?,?,?,?,?,?)",
                        (f"office_{what}", ids[0], frm_ws, to, uid, ts, json.dumps(detail, default=str)))
        log = {"move_id": mid, "what": what, **{k: v for k, v in counts.items() if v}}
        ofx_log(c, src, "move_out", target="space", detail=dict(log, to=ofm_ws_key(to)))
        ofx_log(c, dst, "move_in", target="space", detail=dict(log, **{"from": ofm_ws_key(frm_ws)}))
        bump(c)
        c.commit()
        rmv_unlink(p.get("gone"))  # 2.119.1 C (#2298): the PDFs' old copies in the source's folder
    except BaseException:
        c.rollback()
        for f in files:
            try:
                os.unlink(f)
            except OSError:
                pass
        raise
    for f in old_files:  # 2.119.0 A (#2288): the bills now live (sealed anew) in the target; the undo writes them back
        try:
            os.unlink(f)
        except OSError:
            pass
    return jsonify(smv_answer(notes, None, ok=True, move_id=mid, count=counts, space=ofm_ws_key(to), from_space=ofm_ws_key(frm_ws),
                              clients={str(k): v for k, v in cmap.items()}))


def ofm_undo(c, uid, mid):
    """2.119.1 review F7 (#2298): the undo below; on an error the PDF copies it made are removed again (as ofm_move_space)."""
    files = []
    try:
        return rmv_undo_run(c, uid, mid, files)
    except BaseException:
        c.rollback()
        rmv_unlink(files)
        raise


def rmv_undo_run(c, uid, mid, files):
    """Takes move mid of uid back (one step; 409 when it was taken back already or does not fit any more)."""
    if isinstance(mid, bool) or not isinstance(mid, int):
        raise BadInput(tr("Invalid value: {0}", "undo"))
    q = ",".join("?" * len(OFM_WHAT))
    x = c.execute(f"SELECT * FROM space_moves WHERE id=? AND by_id=? AND kind IN ({q})", (mid, uid, *(f"office_{w}" for w in OFM_WHAT))).fetchone()
    if not x:
        raise Denied(404)
    try:
        d = json.loads(x["detail"] or "{}")
    except ValueError:
        d = {}
    if d.get("undone") or d.get("undo_of") or d.get("what") not in OFM_WHAT:
        raise Denied(409, tr("This was undone already"))
    src, dst, what = int(d["src"]), int(d["dst"]), d["what"]
    rt, rs = office_role(c, uid, dst), office_role(c, uid, src)
    if not rt or not rs:
        raise Denied(404)
    ofm_writer(c, uid, src, dst)
    ofm_groups(c, uid, what, src, dst)
    if what in OFM_ADMIN and (rs != "admin" or rt != "admin"):
        raise Denied(403, tr(OFFICE_ADMIN_ONLY))
    write_lock(c, f"office_move_{int(dst)}")
    ts = iso(now_utc())
    back, kept, gone = 0, 0, []
    from .legacyimport import fi_number_taken
    cfiles = {r["id"] for r in d.get("rows") or [] if r["t"] == "office_contract_files"}
    # 2.97.0 review (H1): a draft issued in the target since, or a trip billed / in DATEV there, never moves back
    for r in d.get("rows") or []:
        if r["t"] in ("office_docs", "office_trips", "office_meals") and not r.get("detach") and not r.get("src"):
            cur = c.execute(f"SELECT * FROM {r['t']} WHERE id=?", (r["id"],)).fetchone()
            hold = ofm_doc_hold if r["t"] == "office_docs" else ofm_trip_hold if r["t"] == "office_trips" else ofm_meal_hold  # 2.119.0 A (#2288)
            if cur and (cur["org_id"] or None) == (r.get("org") or None) and hold(c, cur):
                raise Denied(409, tr("Cannot be undone: a document was issued in the target since"))
    for r in reversed(d.get("rows") or []):
        t, rid, old = r["t"], r["id"], dict(r.get("old") or {})  # the detail is the server's own record
        cur = c.execute(f"SELECT * FROM {t} WHERE id=?", (rid,)).fetchone()
        if not cur:
            continue
        if r.get("detach"):  # a link that ended: back only while it is still empty
            col = r["detach"]
            if cur[col] is None and c.execute(f"SELECT 1 FROM {r['ref']} WHERE id=?", (old[col],)).fetchone():
                c.execute(f"UPDATE {t} SET {col}=? WHERE id=?", (old[col], rid))
            continue
        if r.get("src"):  # the source client archived by the move
            c.execute(f"UPDATE {t} SET archived=? WHERE id=? AND archived=1", (old.get("archived", 0), rid))
            continue
        if (cur["org_id"] or None) != (r.get("org") or None):
            kept += 1  # moved on since: stays where it is now
            continue
        for col, ref in OFM_FK.get(t, {}).items():
            if old.get(col) and not c.execute(f"SELECT 1 FROM {ref} WHERE id=?", (old[col],)).fetchone():
                old[col] = None
        if r.get("cfile"):  # 2.119.1 C (#2298): the PDF back into the source's folder, sealed with its key
            old["file"] = rmv_file_copy(c, cur, dst, src, cur["contract_id"], files)
            gone.append(rmv_path(dst, cur["file"]))
        if r.get("area"):
            old.update(ofm_reseal(c, t, cur, dst, src))
        if t == "office_meal_files" and old.get("file") and old["file"] != cur["file"]:  # 2.119.0 A (#2288): the bill back
            from .meals import bw_file_copy, bw_path
            bw_file_copy(c, dst, src, cur["file"], old["file"])
            gone.append(bw_path(dst, cur["file"]))
        if t == "office_docs" and old.get("number"):
            if c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND number=? AND id!=?", (src, old["number"], rid)).fetchone() \
                    or fi_number_taken(c, src, old["number"]):
                old["number"] = ""
        if t == "office_docs":
            old["updated_at"] = ts
        ofm_set(c, t, rid, old)
        back += 1
        if t == "office_contracts" and not r.get("src"):
            # 2.119.1 review F8 (#2298): PDFs added in the target since go back with the contract (copied into the source's
            # folder with its key); the deleted ones stay in the target's trash, where its purge removes them
            for f in c.execute("SELECT * FROM office_contract_files WHERE org_id=? AND contract_id=? AND deleted_at IS NULL ORDER BY id",
                               (dst, rid)).fetchall():
                if f["id"] in cfiles:
                    continue
                name = rmv_file_copy(c, f, dst, src, rid, files)
                c.execute("UPDATE office_contract_files SET org_id=?, file=? WHERE id=?", (src, name, f["id"]))
                if name != f["file"]:
                    gone.append(rmv_path(dst, f["file"]))
    for m in reversed(d.get("made") or []):
        if m["t"] == "office_archive":
            r = c.execute("SELECT file FROM office_archive WHERE id=? AND org_id=? AND copy_of IS NOT NULL", (m["id"], dst)).fetchone()
            if r:
                c.execute("DELETE FROM office_archive WHERE id=?", (m["id"],))
                if r["file"]:
                    gone.append(os.path.join(OFFICE_DIR, str(int(dst)), r["file"]))
        elif m["t"] == "clients":
            # 2.97.0 review (L5): only while the new client is still in the target workspace
            if c.execute("SELECT 1 FROM clients WHERE id=? AND org_id IS NOT DISTINCT FROM ?", (m["id"], x["to_org"])).fetchone():
                if ofm_refs(c, "clients", m["id"], skip=("office_client_contacts",)):
                    kept += 1  # the target uses the new client since: it stays
                else:
                    c.execute("DELETE FROM clients WHERE id=?", (m["id"],))  # its contact persons go with it (cascade)
        elif m["t"] in ("office_contracts", "office_contract_files", "office_texts"):
            kept += rmv_unmake(c, m, dst, gone)  # 2.119.1 C (#2298)
    d["undone"] = ts
    c.execute("UPDATE space_moves SET detail=? WHERE id=?", (json.dumps(d, default=str), mid))
    nid = insert_id(c, "INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES(?,?,?,?,?,?,?)",
                    (x["kind"], x["obj_id"], x["to_org"], x["from_org"], uid, ts, json.dumps({"undo_of": mid})))
    log = {"move_id": nid, "undo_of": mid, "what": what, "rows": back}
    ofx_log(c, dst, "move_out", target="space", detail=dict(log, to=ofm_ws_key(x["from_org"])))
    ofx_log(c, src, "move_in", target="space", detail=dict(log, **{"from": ofm_ws_key(x["to_org"])}))
    bump(c)
    c.commit()
    files.clear()  # committed: the copies stay
    for f in gone:
        try:
            os.unlink(f)
        except OSError:
            pass
    return jsonify(smv_answer([], None, ok=True, move_id=nid, undone=mid, kept=kept, space=ofm_ws_key(x["from_org"])))


# ---------------------------------------------------------------- 2.119.1 C (#2298): framework contracts
# A contract moves with its live PDF files (re-sealed with the target's key, a new file in the target's folder, the old one
# goes after the commit). Like a client: one that an issued document (or anything but a draft) still points at stays in
# the old office archived and is created anew in the target with copies of its files; the drafts pointing at a moving
# contract lose the link (the undo puts it back). The rights text blocks it names are copied into the target (one with
# the same kind and text there is used); its client stays behind (another workspace), the undo puts it back.
RMV_RIGHTS = ("rights_time_id", "rights_territory_id", "rights_media_id")


def rmv_path(oid, name):
    from .contractfiles import dma_path
    return dma_path(oid, name)


def rmv_plan(c, p, rows):
    p["ctr"] = []
    for r in rows:
        issued = drafts = 0
        for d in c.execute("SELECT * FROM office_docs WHERE contract_id=? ORDER BY id", (r["id"],)).fetchall():
            if ofm_doc_hold(c, d) == "issued":
                issued += 1
            else:
                drafts += 1
        files = c.execute("SELECT * FROM office_contract_files WHERE org_id=? AND contract_id=? AND deleted_at IS NULL ORDER BY id",
                          (r["org_id"], r["id"])).fetchall()
        copy = issued or ofm_refs(c, "office_contracts", r["id"], skip=("office_docs",))
        p["ctr"].append({"row": r, "mode": "copy" if copy else "move", "issued": issued, "drafts": 0 if copy else drafts, "files": files})


def rmv_notes(p):
    cs = p["ctr"]
    moved = [x for x in cs if x["mode"] == "move"]
    notes = [trn("{0} framework contract moves with its PDF files", "{0} framework contracts move with their PDF files", len(moved)) if moved else ""]
    for x in [x for x in cs if x["mode"] == "copy"][:8]:
        notes.append(trn("“{1}” stays archived in the old workspace for {0} issued document and is created anew in the target",
                         "“{1}” stays archived in the old workspace for {0} issued documents and is created anew in the target", x["issued"], x["row"]["name"])
                     if x["issued"] else tr("“{0}” is still used in the old workspace (projects, trips or deals): it stays there archived and is created anew in the target",
                                            x["row"]["name"]))
    n = sum(x["drafts"] for x in cs)
    notes.append(trn("{0} draft loses its framework contract", "{0} drafts lose their framework contract", n) if n else "")
    n = sum(1 for x in cs if x["row"]["client_id"])
    notes.append(trn("{0} framework contract loses its client (clients stay in their workspace)",
                     "{0} framework contracts lose their client (clients stay in their workspace)", n) if n else "")
    return notes


def rmv_file_copy(c, f, src, dst, cid, files):
    """Copies the stored PDF of contract file row f from office area src into dst's folder, sealed with dst's key. -> the
    new bare file name (f's own one when the file is missing); the new path is noted in files (removed on an error)."""
    from .contractfiles import dma_dir
    p = rmv_path(src, f["file"])
    if not p or not os.path.isfile(p):
        return f["file"]
    data = oc_read_file(c, p)
    name = f"contract{int(cid)}-{uuid.uuid4().hex[:16]}.pdf"
    os.makedirs(dma_dir(dst), mode=0o700, exist_ok=True)
    path = rmv_path(dst, name)
    files.append(path)
    oc_write_file(c, dst, path, data, fresh=True)  # like the upload: sealed with the area's key at rest
    os.chmod(path, 0o600)
    return name


def rmv_texts(c, r, src, dst, tmap, made):
    """{rights column: text id in dst} for the rights text blocks contract row r names in src (copied when dst has none)."""
    out = {}
    for col in RMV_RIGHTS:
        tid = r[col]
        if not tid:
            continue
        if tid not in tmap:
            t = c.execute("SELECT * FROM office_texts WHERE id=? AND org_id=?", (tid, src)).fetchone()
            if not t:
                tmap[tid] = None
            else:
                same = c.execute("SELECT id FROM office_texts WHERE org_id=? AND kind=? AND text_de=? AND text_en=? ORDER BY archived, id LIMIT 1",
                                 (dst, t["kind"], t["text_de"], t["text_en"])).fetchone()
                if same:
                    tmap[tid] = same["id"]
                else:
                    row = {k: t[k] for k in sorted(table_columns(c, "office_texts") - {"id"})}
                    row["org_id"] = dst
                    tmap[tid] = insert_id(c, f"INSERT INTO office_texts({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
                    made.append({"t": "office_texts", "id": tmap[tid]})
        out[col] = tmap[tid]
    return out


def rmv_move(c, uid, p, src, dst, rec, made, files, ts):
    tmap = {}
    p["gone"] = []
    cols = sorted(table_columns(c, "office_contracts") - {"id"})
    for x in p["ctr"]:
        r = x["row"]
        extra = {"client_id": None, "updated_at": ts, **rmv_texts(c, r, src, dst, tmap, made)}
        if x["mode"] == "move":
            ofm_move_row(c, rec, "office_contracts", r, src, dst, dst, extra)
            ofm_detach(c, rec, "office_docs", "contract_id", r["id"], "office_contracts")
            for f in x["files"]:
                name = rmv_file_copy(c, f, src, dst, r["id"], files)
                ofm_move_row(c, rec, "office_contract_files", f, src, dst, dst, {"file": name})
                rec[-1]["cfile"] = 1
                if name != f["file"]:
                    p["gone"].append(rmv_path(src, f["file"]))
            continue
        row = {k: r[k] for k in cols}
        row.update(ofm_reseal(c, "office_contracts", r, src, dst), org_id=dst, created_at=ts, archived=0, **extra)
        if "import_run_id" in row:
            row["import_run_id"] = None
        nid = insert_id(c, f"INSERT INTO office_contracts({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
        made.append({"t": "office_contracts", "id": nid})
        for f in x["files"]:
            name = rmv_file_copy(c, f, src, dst, nid, files)
            if name == f["file"]:
                continue  # the stored file is missing: no copy
            fid = insert_id(c, "INSERT INTO office_contract_files(org_id, contract_id, name, file, size, sha256, date, created_by, created_at) "
                               "VALUES(?,?,?,?,?,?,?,?,?)", (dst, nid, f["name"], name, f["size"], f["sha256"], f["date"], uid, ts))
            made.append({"t": "office_contract_files", "id": fid, "contract": nid})
        if not r["archived"]:
            rec.append({"t": "office_contracts", "id": r["id"], "old": {"archived": 0}, "src": 1})
            c.execute("UPDATE office_contracts SET archived=1, updated_at=? WHERE id=?", (ts, r["id"]))


def rmv_unlink(paths):
    for f in paths or ():
        try:
            if f:
                os.unlink(f)
        except OSError:
            pass


def rmv_unmake(c, m, dst, gone):
    """The undo of a copy made by a contract move (in the target dst): a contract copy the target uses since stays (1)."""
    t, rid = m["t"], m["id"]
    if t == "office_contract_files":
        if ofm_refs(c, "office_contracts", m.get("contract") or 0):
            return 0  # its contract stays
        r = c.execute("SELECT file FROM office_contract_files WHERE id=? AND org_id=?", (rid, dst)).fetchone()
        if r:
            c.execute("DELETE FROM office_contract_files WHERE id=?", (rid,))
            gone.append(rmv_path(dst, r["file"]))
        return 0
    if not c.execute(f"SELECT 1 FROM {t} WHERE id=? AND org_id=?", (rid, dst)).fetchone():
        return 0
    if ofm_refs(c, t, rid):
        return 1 if t == "office_contracts" else 0  # used in the target since: it stays
    if t == "office_contracts":  # files the target added since go into its trash (purged with the files later)
        c.execute("UPDATE office_contract_files SET deleted_at=? WHERE org_id=? AND contract_id=? AND deleted_at IS NULL", (iso(now_utc()), dst, rid))
    c.execute(f"DELETE FROM {t} WHERE id=?", (rid,))
    return 0
