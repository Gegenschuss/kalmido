"""2.1148.0 (#4895): the point "Receipts" below the folder tree of the file store -- a list of references, no copies.

Below the collections "From <area>" (files/fsviews.py) the top of a space (private / org:<id>) lists one more read-only
collection "Receipts" with up to three parts, each only while it has something the person may read:
  rcoffice  the recorded receipts of the space's office (rc_receipts on the documents of the office's documents space,
            as the receipts list of the bookkeeping, office/receiptlist.py: nothing in the trash, no receipt without amount)
  rcmeals   the entertainment receipts of the space's office (office_meals, not in the trash)
  rcbudget  the receipts of the household budget entries of the space's budget lists (budget_files of live entries)
and "receipts" = all three parts together (one group per part / per budget list).

The receipts stay where they are: an item carries no file address, only `open` = the app address of its area
(office/books/receipts, office/meals, budget/<list>/<YYYY-MM>); editing, deleting and booking only there. The rights are
the areas' own, worked out for the space shown:
  office    the person's personal office (private; never made here) or the organisation's office, the feature "office" on
            and the area not switched off by the organisation's admins; then exactly who reads the receipts list / the
            entertainment receipts: the office's admin / the personal office's owner / accounting (office/model.py
            office_org admin=True), or through office groups (office/rights.py) at least "view" of the area, "own" = only the
            person's own rows (as the receipts list and office/meals.py bw_rows); the entertainment receipts also need the
            country pack's function money.meals; every receipt document also needs the person's file right (fs_roles_many)
  budget    the module "budget", no agent / API token (life/budget.py bud_hidden), the organisation's area "life" on; a
            budget list the person sees with a role above participant (as life/budget.py bud_lists)
Kids get nothing (as the office's office_gate); agents and API tokens never reach the file store's collections
(files/fsviews.py _person)."""
import json

from flask import g

from ..accounts.orgroles import office_allowed
from ..accounts.orgs import org_role
from ..accounts.wsareas import wsa_org_off
from ..core.access import list_role, list_state_sql, live_sql, vis_sql
from ..core.db import usettings
from ..core.i18n import N_, tr
from ..core.orgcrypt import OrgCryptError, oc_dec_fields
from ..docs.store import doc_opener
from ..life.budget import bud_dec, bud_hidden, entry_out
from ..office.books import bk_ws
from ..office.calc import dec, dstr, money
from ..office.homecur import hc_code, hc_home
from ..office.meals import bw_calc, bw_cols, bw_own_rows
from ..office.model import OFFICE_FEAT, office_settings, pb_owner, pb_personal
from ..office.packs import office_feature_on
from ..office.rights import LV, ofr_rights
from .store import fs_roles_many

# collection key -> its name; "receipts" = all parts, RCX_PARTS in the order of the tree
RCX_KEYS = {"receipts": N_("Receipts"), "rcoffice": N_("Office"), "rcmeals": N_("Entertainment"), "rcbudget": N_("Household")}
RCX_PARTS = ("rcoffice", "rcmeals", "rcbudget")
RCX_OPEN = {"rcoffice": "office/books/receipts", "rcmeals": "office/meals"}  # the area's own list (budget: per list)


def _cap(limit):
    """Rows read for limit receipts (some are refused: a file right, no amount)."""
    return int(min(2000, max(50, limit * 4)))


def _kid():
    u = g.get("user")
    return u is None or ("kid" in u.keys() and bool(u["kid"]))


def rcx_office(c, uid, oid, area):
    """(office area id, own uid | None) when uid may read area ("receipts" | "meals") of the office of space oid (None:
    the personal office), else None. own = the level "own" of office groups: only the person's own rows."""
    if _kid() or OFFICE_FEAT not in (usettings(c, uid).get("features") or "").split(","):
        return None
    if oid is None:
        off = pb_personal(c, uid, create=False)  # a person who never opened the office has none: nothing to show
    else:
        off = oid if OFFICE_FEAT not in wsa_org_off(c, oid) else None
    if not off:
        return None
    if area == "meals" and not office_feature_on(office_settings(c, off), "money.meals"):
        return None  # the country pack's function is off: the office answers 404 there
    if office_allowed(c, uid, off, write=False) is not None:
        return None  # review F1: a guest reads nothing of the office, also with a group (office_org: 403 after ofr_check)
    r = ofr_rights(c, uid, off)
    if r is None:  # not ruled by groups: the admins' routes (office_org admin=True)
        owner = pb_owner(c, off)
        if owner is not None:
            return (off, None) if owner == uid else None
        role = org_role(c, uid, off)
        if role in ("admin", "accounting"):
            return off, None
        return None
    lv = r["levels"].get(area, "none")
    if lv == "own":
        return off, uid
    return (off, None) if LV.get(lv, 0) >= LV["view"] else None


def _item(kind, i, name, day, amount, cur, open_, sub="", mime="", size=0):
    return {"id": i, "kind": kind, "name": name, "sub": sub, "created_at": day or None, "amount": amount, "currency": cur or "",
            "open": open_, "mime": mime or "", "size": int(size or 0)}


def _office(c, uid, oid, limit):
    """[(title, open, items)] -- the recorded receipts of the office of space oid, newest first."""
    acc = rcx_office(c, uid, oid, "receipts")
    if not acc:
        return []
    off, own = acc
    ws = bk_ws(c, off)
    home = hc_home(office_settings(c, off))
    day = "COALESCE(NULLIF(d.doc_date, ''), NULLIF(CAST(r.paid_at AS text), ''))"
    rows = c.execute(f"""SELECT r.node_id, d.amount, d.currency, d.ws, n.name, n.mime, n.size, {day} AS day FROM rc_receipts r
                         JOIN doc_meta d ON d.node_id=r.node_id JOIN fs_nodes n ON n.id=r.node_id
                         WHERE d.ws=? AND n.kind='file' AND {live_sql('n')}"""
                     + (" AND COALESCE(n.created_by, n.owner_id)=?" if own else "")
                     + f" ORDER BY {day} DESC NULLS LAST, r.node_id DESC LIMIT {_cap(limit)}",
                     (ws,) + ((own,) if own else ())).fetchall()
    if not rows:
        return []
    acc = fs_roles_many(c, [r["node_id"] for r in rows], uid)  # in the trash / no file right: not listed
    opener, items = {}, []
    for r in rows:
        if acc[r["node_id"]][0] or not acc[r["node_id"]][1]:
            continue
        if r["ws"] not in opener:
            opener[r["ws"]] = doc_opener(c, r["ws"], "doc_meta.amount")
        raw = opener[r["ws"]](r["amount"]) or ""
        a = dec(raw, "0") if raw else dec(0)
        if a == 0:
            continue  # as the bookkeeping: a receipt without an amount is none yet
        cur = hc_code(r["currency"]) or (r["currency"] or "").strip().upper() or home
        items.append(_item("rc", r["node_id"], r["name"] or "", r["day"], dstr(money(a)), cur, RCX_OPEN["rcoffice"], mime=r["mime"], size=r["size"]))
        if len(items) >= limit:
            break
    return [(tr("Office"), RCX_OPEN["rcoffice"], items)] if items else []


def _meals(c, uid, oid, limit):
    """[(title, open, items)] -- the entertainment receipts of the office of space oid (not in the trash), newest first."""
    acc = rcx_office(c, uid, oid, "meals")
    if not acc:
        return []
    off, own = acc
    if own is not None:  # entered by the person or with the person as host (office/meals.py bw_rows); review F3: the host
        # column (sealed) is opened only for the rows of others, and only the ids / host / author are read for that
        few = c.execute(f"SELECT id, created_by, host FROM office_meals WHERE org_id=? AND {live_sql()} ORDER BY date DESC, id DESC LIMIT 5000",
                        (off,)).fetchall()
        ids = [r["id"] for r in bw_own_rows(c, off, few, own)][:limit]
        if not ids:
            return []
        rows = c.execute(f"SELECT {bw_cols(c)} FROM office_meals WHERE org_id=? AND id IN ({','.join('?' * len(ids))}) "
                         "ORDER BY date DESC, id DESC", (off, *ids)).fetchall()
    else:
        rows = c.execute(f"SELECT {bw_cols(c)} FROM office_meals WHERE org_id=? AND {live_sql()} ORDER BY date DESC, id DESC "
                         f"LIMIT {_cap(limit)}", (off,)).fetchall()
    items = []
    for r in rows[:limit]:
        d = oc_dec_fields(c, off, "office_meals", r)
        try:
            gross = bw_calc(_lines(d.get("amounts")), d.get("tip"))["gross"]
        except (ValueError, KeyError, TypeError, ArithmeticError):
            gross = ""
        name = (d.get("place_name") or "").strip() or (d.get("occasion") or "").strip() or tr("Entertainment")
        sub = (d.get("occasion") or "").strip() if (d.get("place_name") or "").strip() else ""
        items.append(_item("meal", r["id"], name, d.get("date"), gross, d.get("currency") or "", RCX_OPEN["rcmeals"], sub=sub))
    return [(tr("Entertainment"), RCX_OPEN["rcmeals"], items)] if items else []


def _lines(v):
    """The amount lines of a meal (decrypted JSON text) -> list."""
    try:
        x = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        return []
    return x if isinstance(x, list) else []


def _budget(c, uid, oid, limit):
    """[(title, open, items)] -- the receipts of the live entries of the space's budget lists uid sees, per list."""
    if _kid() or bud_hidden(c, uid) or "budget" not in (usettings(c, uid).get("features") or "").split(","):
        return []
    if oid and "life" in wsa_org_off(c, oid):
        return []
    sp, a = ("org_id=?", [oid]) if oid else ("org_id IS NULL", [])
    lists = {}
    for r in c.execute(f"SELECT id, name FROM lists WHERE life='budget' AND {list_state_sql()} AND id IN {vis_sql()} AND {sp} "
                       "ORDER BY name, id", (uid, uid, *a)).fetchall():
        role = list_role(c, r["id"], uid)
        if role and role != "participant":  # a participant sees single tasks; a budget has none (life/budget.py bud_lists)
            lists[r["id"]] = r["name"] or ""
    if not lists:
        return []
    q = ",".join("?" * len(lists))
    files = c.execute(f"""SELECT f.id, f.entry_id, f.list_id, f.name, f.mime, f.size FROM budget_files f JOIN budget_entries e ON e.id=f.entry_id
                          WHERE f.list_id IN ({q}) AND e.list_id=f.list_id AND {live_sql('e')} ORDER BY e.day DESC, f.id DESC
                          LIMIT {_cap(limit)}""", list(lists)).fetchall()
    if not files:
        return []
    eids = sorted({f["entry_id"] for f in files})
    ents = {r["id"]: entry_out(bud_dec(c, "budget_entries", r)) for r in
            c.execute(f"SELECT * FROM budget_entries WHERE id IN ({','.join('?' * len(eids))})", eids)}
    out, n = {}, 0
    for f in files:
        e = ents.get(f["entry_id"])
        if e is None:
            continue
        day = e["day"] or ""
        go = f"budget/{int(f['list_id'])}" + (f"/{day[:7]}" if len(day) >= 7 else "")
        grp = out.setdefault(f["list_id"], (lists[f["list_id"]] or tr("Household"), f"budget/{int(f['list_id'])}", []))
        grp[2].append(_item("budget", f["id"], f["name"] or "", day, e["amount"], "", go, sub=e["title"] or "", mime=f["mime"], size=f["size"]))
        n += 1
        if n >= limit:
            break
    return sorted(out.values(), key=lambda x: x[0].lower())


RCX_READ = {"rcoffice": _office, "rcmeals": _meals, "rcbudget": _budget}


def rcx_groups(c, uid, oid, key, limit):
    """The groups [(title, open, items)] of the collection key in space oid for uid, at most limit receipts."""
    parts = RCX_PARTS if key == "receipts" else (key,) if key in RCX_READ else ()
    out = []
    for k in parts:
        left = limit - sum(len(x[2]) for x in out)
        if left <= 0:
            break
        out += _part(c, uid, oid, k, left)
    return out


def _part(c, uid, oid, key, limit):
    """One part; review F2: a row that cannot be opened (a key gone) leaves this part out instead of failing the file store."""
    try:
        return RCX_READ[key](c, uid, oid, limit)
    except OrgCryptError:
        return []


def rcx_collection(c, uid, oid):
    """{key, name, subs: [{key, name}]} of the space's "Receipts" (only the parts with something for uid), or None."""
    subs = [{"key": k, "name": tr(RCX_KEYS[k])} for k in RCX_PARTS if _part(c, uid, oid, k, 1)]
    return {"key": "receipts", "name": tr(RCX_KEYS["receipts"]), "subs": subs} if subs else None
