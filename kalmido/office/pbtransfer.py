"""2.137.0 D (#1981): the personal office into an existing organisation the person is an admin of (one way, no undo).

GET  /api/office/move/check?org=<id>   the preview: what goes along, what stays, who sees it afterwards, the conflicts
POST /api/office/move/org {org, confirm: true}   the transfer (409 with the conflicts when there are any)

Next to POST /api/office/move (web.py pb_move_post: the personal office becomes a NEW organisation, unchanged). Only a
person, never an agent or an API token; the office shown must be the caller's own personal office (409), the target an
organisation the caller is a member of (404 otherwise) and an admin of (403).
Every row keeps its id (all links stay): org_id personal office -> target in every office_* table (the catalogue of the
database, so a table added later is never forgotten), the protected fields opened with the personal office's key and
sealed with the target's (core/orgcrypt.py FIELDS, JSON_KEYS, the purchase price of positions; the office log only where
it carries a protected key, oc_log_detail). Finalised documents keep status, lock and number (B4, #1969): numbers are
never rewritten -- a number the target already uses (documents or archive) refuses the transfer (409 with the list).
The private clients move along like in pb_move_post (org_id NULL & created_by -> the target, their contact persons too,
the links of those to private address books end). The letters' links to the owner's private documents and address
books end (review A2, 2.153.0: the documents stay private, pb_letter_detach); a signature the person has in the target
already stays, the personal office keeps the other one (review A1).
What stays in the personal office: its settings and company data (bank, tax: the target's are never overwritten), the
start balance and the real balances of the cash flow (the bank account of the company), the number counters (the
person's own sequence never restarts; a counter the target does not have yet is copied, so the target continues after
the moved numbers) and a catalogue pack the target has installed itself.
Files below OFFICE_DIR/<personal office> are written anew below OFFICE_DIR/<target> (same name, sealed with the target's
key) before the commit; the old ones go only after it (on an error the personal office stays as it was). The settings'
own files (logo, letterhead) stay; the frozen copies of finalised documents (logo-<hash>.png, lhs-<hash>.pdf) go along.
One entry "move" in the target's office log."""
import os
import re

from flask import g, jsonify, request

from ..core.config import OFFICE_DIR, app
from ..core.access import Denied, acx_drop
from ..core.db import body, bump, db, err, uset
from ..core.i18n import N_, tr, trn
from ..core.orgcrypt import FIELDS, JSON_KEYS, oc_dec_fields, oc_log_detail, oc_read_file, oc_write_file
from ..core.pg import IntegrityError, system_ctx, table_columns, write_lock
from .ledger import ofx_log
from .model import office_gate, office_org, pb_owner
from .officemove import ofm_reseal

PBT_KEEP = ("office_settings", "office_company", "office_cf_start", "office_cf_actual", "office_numbers",
            "office_period_locks")  # 2.148.0 A (#2471): the locks of each area stay its own
PBT_SEALED = set(FIELDS) | {t for t, _c in JSON_KEYS} | {"office_doc_items"}
PBT_STAY_FILE = re.compile(r"logo\.png|letterhead-[0-9a-f]{16}\.pdf")  # the settings' own files (pdfweb.LOGO_FILE, letterhead.BP_FILE_RE)
PBT_SAME_FILE = re.compile(r"logo-[0-9a-f]{16}\.png|lhs-[0-9a-f]{16}\.pdf")  # content-addressed copies: the same name = the same content
PBT_PLAIN_FILE = re.compile(r"logo.*\.png")  # logos are stored plain (shown openly)
PBT_ONLY_PB = N_("Only a personal office can move into an organisation")
# what the preview names (table -> label); everything else counts as "further office data"
PBT_LABELS = (("office_docs", N_("Documents")), ("office_payments", N_("Payments")), ("office_contracts", N_("Framework contracts")),
              ("office_trips", N_("Travel expenses")), ("office_meals", N_("Entertainment receipts")),
              ("office_cash_entries", N_("Cash book")), ("office_archive", N_("Archive of old documents")),
              ("office_bank_tx", N_("Bank statements")), ("office_drives", N_("Logbook")))
PBT_MASTER = ("office_services", "office_equipment", "office_sets", "office_texts", "office_roles")


def pbt_tables(c):
    """Every office_* table with an org_id column (the database's own catalogue), sorted."""
    return sorted(r[0] for r in c.execute("SELECT table_name FROM information_schema.columns WHERE table_schema=current_schema() "
                                          "AND column_name='org_id' AND table_name LIKE 'office\\_%'"))  # pg-ok: table names are lower case


def pbt_where(t):
    """The rows of table t in office area ? (positions: also those of the area's documents without an org_id of their own)."""
    if t == "office_doc_items":
        return "(org_id=? OR doc_id IN (SELECT id FROM office_docs WHERE org_id=?))", 2
    return "org_id=?", 1


def pbt_source():
    """(c, uid, personal office id) for a person in their own personal office; agents and tokens 403, else 409."""
    c = db()
    uid = office_gate(c)  # agents 403
    if g.get("auth_via") == "token":
        raise Denied(403, tr("Only in the app, not with an access token"))
    src = office_org(c, uid, admin=True)
    if pb_owner(c, src) != uid:
        raise Denied(409, tr(PBT_ONLY_PB))
    return c, uid, src


def pbt_target(c, uid, v):
    """The target organisation: one the caller is a member of (404) and an admin of (403), never a personal office."""
    from ..accounts.orgs import org_role
    try:
        dst = int(v)
    except (TypeError, ValueError):
        raise Denied(404, tr("Organisation not found"))
    role = org_role(c, uid, dst) if dst > 0 else None
    with system_ctx(c):  # instance structure: whether the target is a real organisation (personal offices have no members)
        r = c.execute("SELECT name, personal_of FROM orgs WHERE id=?", (dst,)).fetchone()
    if not role or not r or r["personal_of"] is not None:
        raise Denied(404, tr("Organisation not found"))
    if role != "admin":
        raise Denied(403, tr("Only an admin of the organisation can take your office into it"))
    return dst, r["name"]


def _text_cols(c, t):
    return [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
                                    "AND table_name=? AND data_type='text' ORDER BY column_name", (t,))]


def pbt_files(src):
    """[(relative name, path)] below the personal office's folder that go along (no parts / temp files, no links)."""
    d = os.path.join(OFFICE_DIR, str(int(src)))
    out = []
    if not os.path.isdir(d):
        return out
    for root, dirs, files in os.walk(d):
        dirs.sort()
        for fn in sorted(files):
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, d)
            if fn.endswith((".part", ".tmp")) or os.path.islink(p) or not os.path.isfile(p) or PBT_STAY_FILE.fullmatch(rel):
                continue
            out.append((rel, p))
    return out


def pbt_plan(c, uid, src, dst):
    """What a transfer of personal office src into organisation dst would do: {moves, keeps, conflicts, counts, files, ...}."""
    counts, keeps, conflicts, notes = {}, [], [], []
    tables = pbt_tables(c)
    from .periodlock import pl_first_month, pl_label, pl_through
    lk, first = pl_through(c, dst), pl_first_month(c, src)
    if lk and first and first <= lk:  # 2.148.0 A (#2471): nothing lands in a locked month of the organisation
        conflicts.append(tr("The organisation is locked up to {0}; the personal office has data from {1}", pl_label(lk), pl_label(first)))
    if pl_through(c, src):  # its own locks stay behind: the moved data would be editable again in the organisation
        conflicts.append(tr("The personal office is locked up to {0}; locked data cannot move", pl_label(pl_through(c, src))))
    for t in tables:
        w, n = pbt_where(t)
        k = c.execute(f"SELECT COUNT(*) FROM {t} WHERE {w}", (src,) * n).fetchone()[0]
        if t in PBT_KEEP:
            continue
        counts[t] = k
        if not k:
            continue
        # a protected value this version does not know how to seal anew: never moved half readable
        done = set(FIELDS.get(t, ())) | {col for (tt, col) in JSON_KEYS if tt == t} | {"cost_enc"}
        cols = [x for x in _text_cols(c, t) if x not in done]
        if cols and c.execute(f"SELECT 1 FROM {t} WHERE {w} AND ({' OR '.join(f'strpos({x}, ?)>0' for x in cols)}) LIMIT 1",
                              (src,) * n + ("kenc1:",) * len(cols)).fetchone():
            conflicts.append(tr("{0}: encrypted data that cannot be moved", t))
    taken = [r[0] for r in c.execute(
        "SELECT number FROM office_docs WHERE org_id=? AND number!='' AND number IN (SELECT number FROM office_docs WHERE org_id=? AND number!='' "
        "UNION SELECT number FROM office_archive WHERE org_id=? AND number!='') UNION SELECT number FROM office_archive WHERE org_id=? AND number!='' "
        "AND number IN (SELECT number FROM office_docs WHERE org_id=? AND number!='' UNION SELECT number FROM office_archive WHERE org_id=? AND number!='') "
        "ORDER BY 1", (src, dst, dst, src, dst, dst))]
    for x in taken[:50]:
        conflicts.append(tr("The number {0} is already used", x))
    if len(taken) > 50:
        conflicts.append(trn("and {0} more number", "and {0} more numbers", len(taken) - 50))
    files = pbt_files(src)
    ddir = os.path.join(OFFICE_DIR, str(int(dst)))
    for rel, _p in files:
        if os.path.exists(os.path.join(ddir, rel)) and not PBT_SAME_FILE.fullmatch(rel):
            conflicts.append(tr("The file {0} already exists in the organisation", rel))
    with system_ctx(c):  # the caller's own private clients and the names of the target's clients (the caller is its admin)
        cl = [r[0] for r in c.execute("SELECT id FROM clients WHERE org_id IS NULL AND created_by=?", (uid,))]
        same = c.execute("SELECT COUNT(*) FROM clients WHERE org_id IS NULL AND created_by=? AND archived=0 AND lower(name) IN "
                         "(SELECT lower(name) FROM clients WHERE org_id=? AND archived=0)", (uid, dst)).fetchone()[0]
        who = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN m.role='admin' THEN 1 ELSE 0 END), 0) AS a FROM org_members m "
                        "JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND COALESCE(u.kind, 'user')!='agent'", (dst,)).fetchone()
    moves = []
    if cl:
        moves.append(trn("{0} client with its contact persons", "{0} clients with their contact persons", len(cl)))
    for t, label in PBT_LABELS:
        if counts.get(t):
            if t == "office_docs":
                fin = c.execute("SELECT COUNT(*) FROM office_docs WHERE org_id=? AND number!=''", (src,)).fetchone()[0]
                moves.append(trn("{0} document ({1} with a number, they stay finalised and unchanged)",
                                 "{0} documents ({1} with a number, they stay finalised and unchanged)", counts[t], fin))
            else:
                moves.append(f"{tr(label)}: {counts[t]}")
    m = sum(counts.get(t, 0) for t in PBT_MASTER)
    if m:
        moves.append(f"{tr('Master data')}: {m}")
    rest = sum(v for t, v in counts.items() if t not in dict(PBT_LABELS) and t not in PBT_MASTER)
    if rest:
        moves.append(trn("{0} further entry (positions, log, templates, ...)", "{0} further entries (positions, log, templates, ...)", rest))
    if files:
        moves.append(f"{tr('Files')}: {len(files)}")
    keeps.append(tr("Settings, company data and bank details of your office (the organisation keeps its own)"))
    keeps.append(tr("Your number counters: your personal office keeps counting on, the organisation keeps its own"))
    keeps.append(tr("Absences, bookings and everything outside the office stay private"))
    if same:
        notes.append(trn("{0} client has the same name as one in the organisation: both stay, they are not merged",
                         "{0} clients have the same name as one in the organisation: both stay, they are not merged", same))
    rec = c.execute("SELECT COUNT(*) FROM office_cash_entries WHERE org_id=? AND node_id IS NOT NULL", (src,)).fetchone()[0]
    if rec:
        notes.append(trn("{0} receipt stays in your private file store: only you can open it",
                         "{0} receipts stay in your private file store: only you can open them", rec))
    lk = pb_letter_links(c, src)
    if lk:
        notes.append(trn("{0} link of a letter to a private document ends: the document stays in your private documents",
                         "{0} links of letters to private documents end: the documents stay in your private documents", lk))
    if counts.get("office_texts") and c.execute("SELECT 1 FROM office_texts WHERE org_id=? LIMIT 1", (dst,)).fetchone():
        notes.append(trn("{0} text block is added to those of the organisation (the same text can show twice there)",
                         "{0} text blocks are added to those of the organisation (the same text can show twice there)", counts["office_texts"]))
    # only the text blocks every office gets on its first use: nothing to move
    total = sum(v for t, v in counts.items() if t != "office_texts") + len(cl) + len(files)
    if not total:
        conflicts.append(tr("Your personal office is empty: there is nothing to move"))
    return {"counts": counts, "clients": cl, "files": files, "moves": moves, "keeps": keeps, "notes": notes, "conflicts": conflicts,
            "numbers": taken, "viewers": {"people": who["n"], "admins": who["a"]}, "total": total, "tables": tables}


def pbt_public(p, dst, name):
    v = p["viewers"]
    return {"org": {"id": dst, "name": name}, "ok": not p["conflicts"], "moves": p["moves"], "keeps": p["keeps"], "notes": p["notes"],
            "conflicts": p["conflicts"], "numbers": p["numbers"][:50],
            "who": trn("Afterwards {0} member of “{1}” with access to the office sees it; admins also see purchase prices and bank details.",
                       "Afterwards all {0} members of “{1}” with access to the office see it; admins also see purchase prices and bank details.",
                       v["people"], name)}


@app.get("/api/office/move/check")
def pbt_check():
    """The preview of a transfer of the personal office shown into organisation ?org=."""
    c, uid, src = pbt_source()
    dst, name = pbt_target(c, uid, request.args.get("org"))
    return jsonify(pbt_public(pbt_plan(c, uid, src, dst), dst, name))


def pbt_reseal(c, t, r, src, dst):
    if t == "office_doc_log":  # the log stays plain where it carries no protected key (the daily mail count reads it)
        return {"detail": oc_log_detail(c, dst, oc_dec_fields(c, src, t, r)["detail"])}
    return ofm_reseal(c, t, r, src, dst)


def pb_letter_links(c, src):
    """The links of the letters of personal office src to documents: link rows + filed letter PDFs (review A2, 2.153.0).
    A personal office links only the owner's private documents, which stay private when the office moves."""
    links = c.execute("SELECT COUNT(*) FROM office_letter_links WHERE org_id=?", (src,)).fetchone()[0]
    pdfs = c.execute("SELECT COUNT(*) FROM office_letters WHERE org_id=? AND node_id IS NOT NULL", (src,)).fetchone()[0]
    return links + pdfs


def pb_letter_detach(c, src):
    """Before personal office src moves (pbt_post, web.py pb_move_post): the letters' links to the owner's private
    documents and address books end -- only the links, the documents and contacts stay as they are (the frozen recipient
    of a letter stays). -> the number of document links ended."""
    n = c.execute("DELETE FROM office_letter_links WHERE org_id=?", (src,)).rowcount
    n += c.execute("UPDATE office_letters SET node_id=NULL WHERE org_id=? AND node_id IS NOT NULL", (src,)).rowcount
    c.execute("UPDATE office_letters SET contact_id=NULL WHERE org_id=? AND contact_id IS NOT NULL", (src,))
    return n


def pbt_rows(c, src, dst, tables):
    """org_id src -> dst in every office table (protected fields sealed anew) -> {table: n}."""
    out = {}
    for t in tables:
        if t in PBT_KEEP:
            continue
        w, n = pbt_where(t)
        extra, args = "", ()
        if t == "office_pack_installs":  # a pack the target has installed itself stays (one active install per pack)
            extra = (" AND NOT (removed_at IS NULL AND EXISTS (SELECT 1 FROM office_pack_installs x WHERE x.org_id=? AND x.removed_at IS NULL "
                     "AND x.kind=office_pack_installs.kind AND x.code=office_pack_installs.code))")
            args = (dst,)
        elif t == "office_letter_profiles":  # review A1 (2.153.0): one signature per person and area; the target's own stays
            extra = (" AND NOT EXISTS (SELECT 1 FROM office_letter_profiles x WHERE x.org_id=? AND x.user_id=office_letter_profiles.user_id)")
            args = (dst,)
        if t in PBT_SEALED:
            if "id" not in table_columns(c, t):
                raise RuntimeError(f"pbtransfer: {t} has no id column")
            k = 0
            for r in c.execute(f"SELECT * FROM {t} WHERE {w}{extra} ORDER BY id", (src,) * n + args).fetchall():
                cols = {"org_id": dst, **pbt_reseal(c, t, r, src, dst)}
                if t == "office_doc_items":  # 2.144.5 A2 (#1523, review R10): the source list of a position stays behind
                    cols["list_id"] = None
                c.execute(f"UPDATE {t} SET {', '.join(x + '=?' for x in cols)} WHERE id=?", [*cols.values(), r["id"]])
                k += 1
            out[t] = k
        else:
            out[t] = c.execute(f"UPDATE {t} SET org_id=? WHERE {w}{extra}", (dst,) + (src,) * n + args).rowcount
    return out


@app.post("/api/office/move/org")
def pbt_post():
    """Body {org, confirm: true}: moves the personal office shown into organisation org (see the module text)."""
    c, uid, src = pbt_source()
    b = body()
    if not isinstance(b, dict) or b.get("confirm") is not True:
        return err(tr("Please confirm the move"))
    dst, name = pbt_target(c, uid, b.get("org"))
    for a in sorted((src, dst)):  # a second click or a move-space of the same offices waits (officemove.py takes the same locks)
        write_lock(c, f"office_move_{int(a)}")
    p = pbt_plan(c, uid, src, dst)
    if p["conflicts"]:
        return jsonify(error=tr("The office cannot be moved: {0}", "; ".join(p["conflicts"][:5])), conflicts=p["conflicts"], numbers=p["numbers"][:50]), 409
    ddir = os.path.join(OFFICE_DIR, str(int(dst)))
    made = []
    try:
        for rel, path in p["files"]:  # written before the commit, removed again on an error
            to = os.path.join(ddir, rel)
            if os.path.exists(to):
                continue  # a content-addressed copy the target has already (checked in the plan)
            os.makedirs(os.path.dirname(to), mode=0o700, exist_ok=True)
            made.append(to)
            if PBT_PLAIN_FILE.fullmatch(os.path.basename(rel)):
                with open(path, "rb") as fh:
                    raw = fh.read()
                with open(to, "wb") as fh:
                    fh.write(raw)
            else:
                oc_write_file(c, dst, to, oc_read_file(c, path), fresh=True)  # sealed with the target's key at rest
            os.chmod(to, 0o600)
        own_default = c.execute("SELECT 1 FROM office_cashbooks WHERE org_id=? AND is_default=1", (dst,)).fetchone()
        moved_books = [r[0] for r in c.execute("SELECT id FROM office_cashbooks WHERE org_id=?", (src,))]
        unlinked = pb_letter_detach(c, src)
        counts = pbt_rows(c, src, dst, p["tables"])
        if own_default and moved_books:  # the target keeps its own default cash box
            q = ",".join("?" * len(moved_books))
            c.execute(f"UPDATE office_cashbooks SET is_default=0 WHERE org_id=? AND id IN ({q})", (dst, *moved_books))
        # the counters: the target continues after the moved numbers (its own counter is raised where it is lower, review
        # M2: never a number twice); the personal office keeps its own (the person's sequence never restarts)
        c.execute("INSERT INTO office_numbers(org_id, kind, period, last) SELECT ?, kind, period, last FROM office_numbers WHERE org_id=? "
                  "ON CONFLICT(org_id, kind, period) DO UPDATE SET last=GREATEST(office_numbers.last, excluded.last)", (dst, src))
        cl = p["clients"]
        if cl:
            q = ",".join("?" * len(cl))
            with system_ctx(c):  # the caller's own private clients go along into the organisation they are an admin of (as in pb_move_post)
                c.execute(f"UPDATE clients SET org_id=? WHERE org_id IS NULL AND id IN ({q})", (dst, *cl))
                c.execute(f"UPDATE office_client_contacts SET org_id=? WHERE client_id IN ({q})", (dst, *cl))
                c.execute(f"UPDATE office_client_contacts SET contact_id=NULL WHERE client_id IN ({q})", cl)  # own address books stay private
        ofx_log(c, dst, "move", target="settings", detail={"from_personal": 1, "clients": len(cl), "files": len(p["files"]),
                                                           "rows": {k: v for k, v in counts.items() if v},
                                                           "letter_links": unlinked})
        uset(c, uid, "workspace", f"org:{dst}")  # afterwards the app shows the organisation's office
        bump(c)
        c.commit()
    except Exception as e:
        c.rollback()
        for f in made:
            try:
                os.remove(f)
            except OSError:
                pass
        if isinstance(e, IntegrityError):  # the target took one of the numbers in the meantime
            return err(tr("The office cannot be moved: {0}", tr("Try again")), 409)
        raise
    for _rel, path in p["files"]:  # the old copies go only after the commit
        try:
            os.remove(path)
        except OSError:
            pass
    g.pop("pb_owner", None)
    acx_drop()
    print("personal office", src, "moved into organisation", dst, "by", g.user["username"], flush=True)
    return jsonify(ok=True, org_id=dst, name=name, clients=len(p["clients"]), files=len(p["files"]), letter_links=unlinked,
                   rows=sum(counts.values()))
