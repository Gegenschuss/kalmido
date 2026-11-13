"""2.957.0 (#4910): receipts of the credit cards and of the bank file themselves into month folders.

One part for both ways (decided 06.11.2026): a receipt matched with a position of a credit card statement goes to
"<documents folder> / Receipts / Credit card / <card> / <year> / <YYYY-MM month>" (the statement's month), the statement's
PDF as well; a receipt matched with a bank booking goes to "... / Receipts / Bank / <account> / <year> / <YYYY-MM month>"
(the booking's day). The document gets the tag "Credit card" / "Bank" of its workspace. The names are in the language of
the documents folder's owner (the office's owner; an organisation's documents folder belongs to one of its admins).

Rules of the decision:
- only a document that still lies in the inbox moves: directly in the documents folder or in its inbox folder ("Dokumente /
  Eingang"); a document a person filed by hand (any other folder) stays where it is. The tag is set either way (also for a
  document outside the documents folder).
- taking the match back moves nothing back (the unmatch routes do not call this module).
- no level per person: the card's name carries its holder ("Mastercard ·· 1234 (Name)").
- a locked folder on the way (end-to-end, fslock) takes no document: then nothing moves (docs/store.py folder_by_name).
- filing never stops the match: an error is logged and the document stays where it is.

The folders are made like a recognition rule makes them (docs/store.py folder_by_name): below the documents folder, owned by
its owner, so the document keeps its own owner and its readers (a member's receipt stays the member's; no share, no
organisation access is added). An existing folder of the same name is reused -- unless a folder of the path is opened wider
than the documents folder (organisation access, a share, a public link): then the receipt keeps only its tag (review F1).

Callers: office/cardlines.py _match (upload at the position and a later match), office/cards.py cc_upload (the statement),
office/bank.py bnk_match (kind receipt), office/bankvend.py bv_autolink (a provider's invoice matched by itself) and the
hook after the first recognition run (rcf_on_done): the first recognition of a fresh upload may replace the tags or file the
document by a rule -- the hook puts the tag back and files a document that is still in the inbox."""
from contextlib import nullcontext

from flask import has_app_context

from ..core.access import live_sql
from ..core.config import app
from ..core.i18n import LANGS, lang, tr
from ..core.orgcrypt import oc_dec_fields
from ..docs.ingest import doc_on_done
from ..docs.store import docs_root, folder_by_name, is_inbox, label_id, move_to_folder
from ..files.store import _free_name, safe_fs_name
from .bankacc import BKA_TABLE, bka_default, bka_rows
from .books import bk_ws
from .cfbank import cfb_balances

RCF_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
                 "December")
RCF_NAME_MAX = 80  # one folder name of the path (card / account), the store allows more


def rcf_month(day, lg):
    """'2026-11-05' -> '2026-11 November' (the month's name in lg, the translation file's _months; English built in)."""
    y, mo = str(day)[:4], str(day)[5:7]
    if not (y.isdigit() and mo.isdigit() and 1 <= int(mo) <= 12):
        return None
    mons = LANGS.get(str(lg or ""), {}).get("_months")
    name = mons[int(mo) - 1] if isinstance(mons, list) and len(mons) == 12 else RCF_MONTHS_EN[int(mo) - 1]
    return y, f"{y}-{mo} {str(name)[:1].upper()}{str(name)[1:]}"


def _part(name):
    """One folder name of the path: no slash (folder_by_name reads "/" as a level), not empty."""
    return safe_fs_name(str(name or "").replace("/", "-").strip()[:RCF_NAME_MAX]).strip()


def _in_inbox(c, node, root):
    """Does the document lie directly in the documents folder or in its inbox folder?"""
    p = node["parent_id"]
    if not p:
        return False
    if p == root:
        return True
    r = c.execute(f"SELECT parent_id, name FROM fs_nodes WHERE id=? AND kind='folder' AND {live_sql()}", (p,)).fetchone()
    return bool(r) and r["parent_id"] == root and is_inbox(r["name"])


def _opened(c, fid, root):
    """Is a folder between the documents folder (excluded) and fid opened wider than the documents folder itself: organisation
    access, a share or a live public link? Then a receipt does not move there (review F1: no silent widening of its readers)."""
    ids, cur = [], fid
    while cur and cur != root and len(ids) < 40:
        ids.append(cur)
        r = c.execute("SELECT parent_id, org_access FROM fs_nodes WHERE id=?", (cur,)).fetchone()
        if r is None:
            return True
        if r["org_access"]:
            return True
        cur = r["parent_id"]
    if not ids:
        return False
    q = ",".join("?" * len(ids))
    return bool(c.execute(f"SELECT 1 FROM fs_shares WHERE node_id IN ({q}) LIMIT 1", ids).fetchone()
                or c.execute(f"SELECT 1 FROM fs_ext_links WHERE node_id IN ({q}) AND revoked_at IS NULL LIMIT 1", ids).fetchone())


def rcf_file(c, nid, kind, name_of, day, uid=None, tag=True):
    """The shared part: document nid -> tag of kind ("card" | "bank") and, when it is still in the inbox, the folder
    Receipts / <Credit card|Bank> / name_of(lg) / <year> / <YYYY-MM month> of day. Returns the folder id it moved to, or None.
    name_of: lg -> the card's / account's name (read inside the caller's savepoint). uid: who matched (recorded as the maker
    of new folders; None: the documents folder's owner). tag False: the folder only (the statement's PDF is no receipt).
    A path that runs through a folder opened wider than the documents folder (organisation access, a share, a public link)
    takes no receipt: it keeps its tag and stays in the inbox."""
    node = c.execute(f"SELECT * FROM fs_nodes WHERE id=? AND kind='file' AND {live_sql()}", (nid,)).fetchone()
    if node is None:
        return None
    m = c.execute("SELECT ws FROM doc_meta WHERE node_id=?", (nid,)).fetchone()
    if m is None:
        return None
    root = docs_root(c, node)
    owner = c.execute("SELECT owner_id FROM fs_nodes WHERE id=?", (root,)).fetchone()["owner_id"] if root else node["owner_id"]
    lg = lang(c, owner)
    area = tr("Credit card", lg=lg) if kind == "card" else tr("Bank", lg=lg)
    tid = label_id(c, m["ws"], "tag", area) if tag else None
    if tid:
        from ..core.objtags import otg_ws_link
        otg_ws_link(c, nid, tid, "rule")  # 2.1119.0 (#5277): the core's link, marked as a rule's
    ym = rcf_month(day, lg)
    if not root or not ym or not _in_inbox(c, node, root):
        return None
    parts = [_part(tr("Receipts", lg=lg)), _part(area), _part(name_of(lg)) or _part(area), ym[0], ym[1]]
    fid = folder_by_name(c, node, uid or owner, "/".join(parts), path=True)
    if not fid or fid == node["parent_id"] or _opened(c, fid, root) or not move_to_folder(c, node, fid):
        return None
    nm = _free_name(c, fid, node["owner_id"], node["org_id"], node["name"], skip=nid)
    if nm != node["name"]:
        c.execute("UPDATE fs_nodes SET name=? WHERE id=?", (nm, nid))
    return fid


def rcf_safe(c, nid, kind, name_of, day, uid=None, tag=True):
    """rcf_file that never stops the caller (a match, a recognition run): an error leaves the document where it is."""
    try:
        with c.savepoint():
            return rcf_file(c, nid, kind, name_of, day, uid, tag)
    except Exception as e:  # noqa: BLE001 -- the match stands, only the filing is skipped
        print(f"WARNING receipt folder {nid}: {type(e).__name__} {e}", flush=True)
        return None


def rcf_card_name(c, oid, card_id):
    """'Mastercard ·· 1234 (Name)': the folder of a card (its holder in the name: no level per person)."""
    from .cards import CC_PROVIDERS, _holder
    r = c.execute("SELECT * FROM office_cc_cards WHERE id=? AND org_id=?", (card_id, oid)).fetchone()
    if r is None:
        return ""
    k = oc_dec_fields(c, oid, "office_cc_cards", r)
    name = CC_PROVIDERS.get(k["provider"], k["provider"] or "")
    if k["last4"]:
        name = f"{name} ·· {k['last4']}".strip()
    h = _holder(c, oid, k)
    return f"{name} ({h})" if h else name


def rcf_card(c, oid, sid, nid, uid=None, tag=True):
    """A document of statement sid (its PDF: tag False, or a position's receipt) -> the card's month folder (the statement's
    month)."""
    if not nid:
        return None
    s = c.execute(f"SELECT card_id, month FROM office_cc_statements WHERE id=? AND org_id=? AND {live_sql()}", (sid, oid)).fetchone()
    if s is None:
        return None
    return rcf_safe(c, nid, "card", lambda lg: rcf_card_name(c, oid, s["card_id"]), f"{s['month']}-01", uid, tag)


def rcf_bank_name(c, oid, import_id, lg=None):
    """The bank account of an import: the account chosen at the import (#5183), else the one its balances name (an
    account of the office with that IBAN, else '·· <last 4>'), else the office's default account; '' = not known."""
    acct = tr("Bank account", lg=lg)

    def label(a):
        iban = "".join(str(a.get("iban") or "").split())
        return a.get("label") or a.get("bank_name") or (f"{acct} ·· {iban[-4:]}" if iban else "")
    if import_id:
        r = c.execute("SELECT bank_account_id FROM office_bank_imports WHERE id=? AND org_id=?", (import_id, oid)).fetchone()
        if r and r[0]:
            a = c.execute("SELECT * FROM office_bank_accounts WHERE id=? AND org_id=?", (r[0], oid)).fetchone()
            if a:
                return label(oc_dec_fields(c, oid, BKA_TABLE, a))
        named = {b["account"] for b in cfb_balances(c, oid) if b["import_id"] == import_id and b["account"]}
        if len(named) == 1:
            acc = "".join(next(iter(named)).split()).upper()
            for a in bka_rows(c, oid) + bka_rows(c, oid, archived=True):
                if acc and "".join(str(a.get("iban") or "").split()).upper() == acc:
                    return label(a)
            return f"{acct} ·· {acc[-4:]}" if len(acc) > 8 else acc
    d = bka_default(c, oid)
    return label(d) if d else ""


def rcf_bank(c, oid, t, nid, uid=None):
    """A receipt matched with bank booking t (a decrypted office_bank_tx row) -> the account's month folder (booking day)."""
    if not nid:
        return None
    return rcf_safe(c, nid, "bank", lambda lg: rcf_bank_name(c, oid, t["import_id"], lg), t["day"], uid)


def rcf_on_done(c, nid, first):
    """doc_on_done hook: after the FIRST recognition run of a document (it may set the tags anew or file it by a rule) a matched
    receipt gets its tag back and is filed when it still lies in the inbox (a rule that filed it elsewhere wins). Later runs
    leave what a person changed (review F8). Only rows of the office whose documents space holds the document (review F3)."""
    if not first:
        return
    try:
        with nullcontext() if has_app_context() else app.app_context(), c.savepoint():
            m = c.execute("SELECT ws FROM doc_meta WHERE node_id=?", (nid,)).fetchone()
            if m is None:
                return
            for r in c.execute("SELECT org_id, statement_id FROM office_cc_lines WHERE node_id=? AND state='matched' LIMIT 1", (nid,)).fetchall():
                if bk_ws(c, r["org_id"]) == m["ws"]:
                    rcf_card(c, r["org_id"], r["statement_id"], nid)
            for r in c.execute(f"SELECT org_id, import_id, day FROM office_bank_tx WHERE match_kind='receipt' AND match_id=? AND {live_sql()} LIMIT 1",
                               (nid,)).fetchall():
                if bk_ws(c, r["org_id"]) == m["ws"]:
                    rcf_bank(c, r["org_id"], r, nid)
    except Exception as e:  # noqa: BLE001 -- a recognised document stays as it is
        print(f"WARNING receipt folder after recognition {nid}: {type(e).__name__} {e}", flush=True)


if rcf_on_done not in doc_on_done:
    doc_on_done.append(rcf_on_done)
