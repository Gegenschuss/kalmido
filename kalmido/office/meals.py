"""2.119.0 A (#2288): entertainment receipts (Bewirtungsbelege, section 4 (5) no. 2 EStG) -- an office module built like the
travel expenses (office/travel.py). A meal (office_meals): date, place (restaurant name + address), occasion, host and the
other participants (people of the office {id} or free names {name, extra = company / function}), the gross amounts split
by food / drinks and VAT rate, the tip, an optional restaurant bill (office_meal_files, one live file, sealed like the
contract files), status draft | approved.

Approving checks the required fields, takes new places and people into the choice lists (office_meal_choices, no
duplicates, case ignored; a removed one comes back) and locks the meal: PATCH / DELETE / a new file -> 409 until somebody
with the right undoes the approval (POST .../unlock {reason?}). Every approval and unlock is a row of office_meal_log
(who, when, reason) that stays whatever happens later (also in the office log, ofx_log target "meals"). The approval is
the host's digital confirmation (name + time instead of a signature on paper).

Deleting: drafts only, into the trash (deleted_at, undo = POST .../restore), purged with the files after BW_PURGE_DAYS.
A meal that was ever approved is kept for BW_KEEP_YEARS after the end of its year (retention of receipts, 409 before).
The PDF (Eigenbeleg, GET .../pdf), the evaluation of the approved meals (GET /api/office/meals/report: gross, input VAT
100 %, net 70 % deductible / 30 % not, the tip without VAT counted in) with the filters of the travel expenses (person =
host or participant, period, occasion), also as CSV and PDF.

Every route: office_gate + office_org with the admin of the office area (like the travel expenses; members get 403, agents
and kids 403); a meal of another office area is 404. A person without an organisation works in the personal office (its
own admin). Texts and amounts encrypted at rest (orgcrypt FIELDS). Never reached by agents."""
import csv
import hashlib
import io
import json
import os
import re
import urllib.parse
import uuid
from datetime import date, timedelta

from flask import Response, jsonify, request

from ..core.access import Denied
from ..core.config import MAX_FILE_MB, OFFICE_DIR, app
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields, oc_read_file, oc_write_file
from ..core.pg import insert_id, write_lock, system_ctx
from ..core.errors import BadInput
from ..files.scan import sc_after_store, sc_guard, sc_scan  # 2.190.0 D (#2561): pulled up, the later scan
from .calc import dec, dstr, money
from .ledger import ofx_log
from .rights import ofr_own_uid
from .travel import _amount, _csv_safe, _ctx, _date, _text, rk_home_cur, rk_people, rka_person_arg, rka_pkey

BW_KINDS = ("food", "drinks")
BW_RATES = ("19", "7", "0")  # the usual German rates; another rate (0-100) is kept as it is
BW_CHOICE_KINDS = ("place", "person")
BW_MAX_GUESTS = 40
BW_MAX_LINES = 20
BW_MAX_CHOICES = 500
BW_PURGE_DAYS = 30
BW_KEEP_YEARS = 8  # receipts: 8 years after the end of the year (since 2025); 2.147.0 (#2459): the DE pack's value, see bw_years
BW_BILL_HINT = dec(250)  # from 250 EUR gross the bill must name the company
BW_SHARE = dec("0.7")  # deductible share of the net amount
# an occasion that only says "a business meal" is not enough (the tax office asks for the concrete reason)
BW_VAGUE = {"geschäftsessen", "geschaeftsessen", "arbeitsessen", "essen", "bewirtung", "business meal", "business lunch",
            "business dinner", "meal", "lunch", "dinner"}
BW_LOCKED = N_("This entertainment receipt is approved and locked. Undo the approval first.")
BW_OWN_RO = N_("This entertainment receipt was entered by somebody else: you can read it, but not change it.")  # 2.187.1 B (#2735)
BW_OWN_HOST = N_("Only the host confirms an entertainment receipt.")
BW_KEPT = N_("An approved entertainment receipt is kept until {0} (retention)")
BW_FILE_TYPES = ((b"%PDF-", "application/pdf", ".pdf"), (b"\xff\xd8\xff", "image/jpeg", ".jpg"), (b"\x89PNG\r\n\x1a\n", "image/png", ".png"))


def bw_dir(oid):
    return os.path.join(OFFICE_DIR, str(int(oid)))


def bw_path(oid, file):
    """The stored file's path (file = a bare name below the office area's folder, never a path)."""
    if not file or os.path.basename(file) != file:
        return None
    return os.path.join(bw_dir(oid), file)


def bw_file_copy(c, src, dst, file, new=None):
    """The file of office src sealed anew for office dst (a move between offices, its undo: new = the old name) -> the new
    bare name; raises when unreadable."""
    p = bw_path(src, file)
    data = oc_read_file(c, p)
    ext = os.path.splitext(file)[1][:5]
    new = new or f"meal-{uuid.uuid4().hex[:16]}{ext}"
    os.makedirs(bw_dir(dst), mode=0o700, exist_ok=True)
    oc_write_file(c, dst, bw_path(dst, new), data, fresh=True)
    os.chmod(bw_path(dst, new), 0o600)
    return new


# ---------------------------------------------------------------- cleaning the input
def _person(v, known, name="host"):
    """{id} (a person of the office) | {name, extra} -> the stored dict or None."""
    if v in (None, "", {}):
        return None
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", name))
    if v.get("id") not in (None, ""):
        try:
            pid = int(v["id"])
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", name))
        if pid not in known:
            raise BadInput(tr("Invalid value: {0}", name))
        return {"id": pid, "name": known[pid]}
    n = " ".join(_text(v.get("name"), name, 200).split())[:120]
    if not n:
        return None
    return {"name": n, "extra": " ".join(_text(v.get("extra"), name, 300).split())[:200]}


def bw_lines_clean(v):
    if v in (None, ""):
        return []
    if not isinstance(v, list) or len(v) > BW_MAX_LINES:
        raise BadInput(tr("Invalid value: {0}", "amounts"))
    out = []
    for x in v:
        if not isinstance(x, dict):
            raise BadInput(tr("Invalid value: {0}", "amounts"))
        kind = x.get("kind") or "food"
        if kind not in BW_KINDS:
            raise BadInput(tr("Invalid value: {0}", "amounts"))
        rate = _amount(x.get("rate", 19), "rate", 0, 100)
        gross = _amount(x.get("gross"), "amounts", 0, 10 ** 7, allow_none=True)
        if gross is None or gross == 0:
            continue
        out.append({"kind": kind, "rate": format(rate.normalize(), "f"), "gross": dstr(money(gross))})
    return out


def bw_clean(c, oid, uid, b, cur=None):
    """The columns of a meal from body b (partial when cur is given)."""
    cur = cur or {}
    out = {}
    known = None
    if "date" in b or not cur:
        out["date"] = _date(b.get("date"), "date") or local_now().date().isoformat()
    if "place_name" in b or not cur:
        out["place_name"] = " ".join(_text(b.get("place_name"), "place_name", 200).split())[:120]
    if "place_address" in b or not cur:
        out["place_address"] = _text(b.get("place_address"), "place_address", 400)
    if "occasion" in b or not cur:
        out["occasion"] = _text(b.get("occasion"), "occasion", 500)
    if "host" in b or not cur:
        known = {p["id"]: p["name"] for p in rk_people(c, oid, uid)}
        h = _person(b.get("host"), known) if "host" in b else {"id": uid, "name": known.get(uid, "")}
        out["host"] = json.dumps(h or {}, ensure_ascii=False)
    if "guests" in b or not cur:
        known = known or {p["id"]: p["name"] for p in rk_people(c, oid, uid)}
        g = b.get("guests") or []
        if not isinstance(g, list) or len(g) > BW_MAX_GUESTS:
            raise BadInput(tr("Invalid value: {0}", "guests"))
        seen, gs = set(), []
        for x in g:
            p = _person(x, known, "guests")
            if p and rka_pkey(p) not in seen:
                seen.add(rka_pkey(p))
                gs.append(p)
        out["guests"] = json.dumps(gs, ensure_ascii=False)
    if "amounts" in b or not cur:
        out["amounts"] = json.dumps(bw_lines_clean(b.get("amounts")), ensure_ascii=False)
    if "tip" in b or not cur:
        t = _amount(b.get("tip"), "tip", 0, 10 ** 6, allow_none=True)
        out["tip"] = dstr(money(t or dec(0)))
    if "note" in b or not cur:
        out["note"] = _text(b.get("note"), "note", 2000)
    return out


# ---------------------------------------------------------------- reading
def _j(v, empty):
    try:
        x = json.loads(v or "")
    except (TypeError, ValueError):
        return empty
    return x if isinstance(x, type(empty)) else empty


def bw_calc(lines, tip):
    """The sums of a meal: per line VAT and net, gross (lines + tip), input VAT (100 %), net incl. the tip, 70 % / 30 %."""
    rows, gross, vat = [], dec(0), dec(0)
    for x in lines:
        g, r = dec(x["gross"]), dec(x["rate"])
        v = money(g * r / (100 + r)) if r else dec(0)
        rows.append({"kind": x["kind"], "rate": x["rate"], "gross": dstr(money(g)), "vat": dstr(v), "net": dstr(money(g - v))})
        gross += g
        vat += v
    t = dec(tip or 0)
    net = money(gross - vat + t)
    ded = money(net * BW_SHARE)
    return {"lines": rows, "food": dstr(money(sum((dec(x["gross"]) for x in lines if x["kind"] == "food"), dec(0)))),
            "drinks": dstr(money(sum((dec(x["gross"]) for x in lines if x["kind"] == "drinks"), dec(0)))),
            "bill": dstr(money(gross)), "tip": dstr(money(t)), "gross": dstr(money(gross + t)), "vat": dstr(money(vat)), "net": dstr(net),
            "deductible": dstr(ded), "not_deductible": dstr(money(net - ded))}


def bw_years(c, oid):
    """2.147.0 (#2459, #2461): the retention of receipts in years of office area oid (its country pack; the neutral base pack:
    the office's own value). DE stays at 8."""
    from .model import office_settings
    from .packs import office_pack_for, pack_retention
    s = office_settings(c, oid)
    return int(pack_retention(office_pack_for(s), s).get("receipts") or BW_KEEP_YEARS)


def bw_keep_until(d, years=BW_KEEP_YEARS):
    """The day before which an ever approved meal of date d may not be deleted (end of its year + the retention in years)."""
    y = int(d[:4]) if d and re.match(r"^\d{4}", d) else local_now().year
    return f"{y + years + 1}-01-01"


def bw_kept_from(date, approvals, years=BW_KEEP_YEARS):
    """2.119.0 (#2288, review): the keep period counts from the later of the meal date and its last approval, so moving the date of an
    unlocked meal back cannot shorten it. None = never approved."""
    if not approvals:
        return None
    return bw_keep_until(max([date or ""] + [a[:10] for a in approvals if a]), years)


def bw_kept(c, oid, mid, date, years=None):
    return bw_kept_from(date, [r["at"] for r in c.execute(
        "SELECT at FROM office_meal_log WHERE meal_id=? AND org_id=? AND action='approve'", (mid, oid)).fetchall()],
        years if years is not None else bw_years(c, oid))


def bw_logs(c, oid, ids):
    """{meal id: [{action, at, user, reason}]} oldest first."""
    if not ids:
        return {}
    out = {}
    for r in c.execute(f"SELECT * FROM office_meal_log WHERE org_id=? AND meal_id IN ({','.join('?' * len(ids))}) ORDER BY at, id", [oid] + list(ids)):
        d = oc_dec_fields(c, oid, "office_meal_log", r)
        out.setdefault(d["meal_id"], []).append({"action": d["action"], "at": d["at"], "user": d.get("user_name") or "", "reason": d.get("reason") or ""})
    return out


def bw_files(c, oid, ids):
    if not ids:
        return {}
    out = {}
    for r in c.execute(f"SELECT id, meal_id, name, size, mime, created_at FROM office_meal_files WHERE org_id=? AND deleted_at IS NULL "
                       f"AND meal_id IN ({','.join('?' * len(ids))}) ORDER BY id", [oid] + list(ids)):
        out.setdefault(r["meal_id"], []).append({"id": r["id"], "name": r["name"], "size": int(r["size"] or 0), "mime": r["mime"], "created_at": r["created_at"]})
    return out


def bw_public(c, oid, r, logs=None, files=None, years=None):
    d = oc_dec_fields(c, oid, "office_meals", r)
    lines = _j(d.get("amounts"), [])
    host = _j(d.get("host"), {})
    guests = _j(d.get("guests"), [])
    lg = (logs or {}).get(d["id"], [])
    return {"id": d["id"], "date": d["date"], "place_name": d["place_name"], "place_address": d["place_address"], "occasion": d["occasion"],
            "host": host or None, "guests": guests, "amounts": lines, "tip": d["tip"] or "0.00", "currency": d["currency"], "note": d.get("note") or "",
            "status": d["status"], "locked": d["status"] == "approved", "approved_at": d.get("approved_at"), "approved_by": d.get("approved_by"),
            "approved_name": d.get("approved_name") or "", "calc": bw_calc(lines, d["tip"]), "log": lg,
            "files": (files or {}).get(d["id"], []), "kept_until": bw_kept_from(d["date"], [x["at"] for x in lg if x["action"] == "approve"],
                                                                                    years if years is not None else bw_years(c, oid)),
            "deleted": 1 if d.get("deleted_at") else 0, "created_at": d["created_at"], "updated_at": d["updated_at"]}


def bw_rows(c, oid, year=None, mid=None, deleted=False):
    sql, args = "SELECT * FROM office_meals WHERE org_id=?", [oid]
    own = ofr_own_uid("meals")  # 2.187.0 B (#2476): office groups, level "own": only the person's own receipts
    if mid is not None:
        sql += " AND id=?"
        args.append(mid)
    if not deleted:
        sql += " AND deleted_at IS NULL"
    if year:
        sql += " AND substr(date, 1, 4)=?"
        args.append(str(year))
    rows = c.execute(sql + " ORDER BY date DESC, id DESC", args).fetchall()
    if own is not None:  # 2.187.1 B (#2735): own = entered by the person or with the person as host (the host may be encrypted)
        rows = [r for r in rows if bw_own_sees(c, oid, r, own)]
    ids = [r["id"] for r in rows]
    logs, files = bw_logs(c, oid, ids), bw_files(c, oid, ids)
    years = bw_years(c, oid)
    out = [bw_public(c, oid, r, logs, files, years) for r in rows]
    if own is not None:  # 2.187.1 B (#2735): somebody else's receipt for the person: read (and approve as host) only
        for r, m in zip(rows, out):
            m["own_ro"] = 0 if r["created_by"] == own else 1
            m["own_host"] = 1 if (m.get("host") or {}).get("id") == own else 0
    return out


def bw_host_id(c, oid, r):
    """2.187.1 B (#2735): the account id of the meal row's host (None: a free name / none)."""
    h = _j(oc_dec_fields(c, oid, "office_meals", r).get("host"), {})
    return h.get("id") if isinstance(h, dict) and isinstance(h.get("id"), int) else None


def bw_own_sees(c, oid, r, own):
    return r["created_by"] == own or bw_host_id(c, oid, r) == own


def bw_people(c, oid, uid):
    """2.119.1 (#2288): the people for host / guests without agents (an agent does not eat out)."""
    ag = {r["id"] for r in c.execute("SELECT u.id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND u.kind='agent'", (oid,)).fetchall()}
    return [p for p in rk_people(c, oid, uid) if p["id"] not in ag]


def _meal(c, oid, mid, deleted=False, mode="write"):
    """The meal row (404: none / not the person's on the level "own"). 2.187.1 B (#2735), level "own": mode "read" = entered by
    the person or the person is the host; "write" = entered by the person; "approve" = the person is the host (403 else)."""
    r = c.execute("SELECT * FROM office_meals WHERE id=? AND org_id=?" + ("" if deleted else " AND deleted_at IS NULL"), (mid, oid)).fetchone()
    own = ofr_own_uid("meals")
    if not r or (own is not None and not bw_own_sees(c, oid, r, own)):  # 2.187.0 B (#2476): level "own": somebody else's = 404
        raise Denied(404)
    if own is not None and mode == "write" and r["created_by"] != own:
        raise Denied(403, tr(BW_OWN_RO))
    if own is not None and mode == "approve" and bw_host_id(c, oid, r) != own:
        raise Denied(403, tr(BW_OWN_HOST))
    return r


def _one(c, oid, mid):
    return bw_rows(c, oid, mid=mid, deleted=True)[0]


def _need_draft(r):
    if r["status"] == "approved":
        raise Denied(409, tr(BW_LOCKED))


def bw_purge(c, oid):
    """Trashed meals older than BW_PURGE_DAYS and trashed files: the rows and the stored files go for good (caller commits)."""
    old = iso(now_utc() - timedelta(days=BW_PURGE_DAYS))
    gone = c.execute("SELECT id FROM office_meals WHERE org_id=? AND deleted_at IS NOT NULL AND deleted_at<?", (oid, old)).fetchall()
    ids = [r["id"] for r in gone]
    q = ",".join("?" * len(ids)) or "NULL"
    files = c.execute(f"SELECT id, meal_id, file FROM office_meal_files WHERE org_id=? AND ((deleted_at IS NOT NULL AND deleted_at<?) OR meal_id IN ({q}))",
                      [oid, old] + ids).fetchall()
    n, today, kept, years = 0, local_now().date().isoformat(), {}, bw_years(c, oid)
    for f in files:
        # 2.119.0 (#2288, review): a removed / replaced bill of an ever approved meal stays as long as the meal is kept
        if f["meal_id"] not in ids:
            if f["meal_id"] not in kept:
                m = c.execute("SELECT date FROM office_meals WHERE id=? AND org_id=?", (f["meal_id"], oid)).fetchone()
                k = bw_kept(c, oid, f["meal_id"], m["date"], years) if m else None
                kept[f["meal_id"]] = bool(k and today < k)
            if kept[f["meal_id"]]:
                continue
        p = bw_path(oid, f["file"])
        try:
            if p and os.path.isfile(p):
                os.remove(p)
        except OSError:
            continue  # the next read tries again
        c.execute("DELETE FROM office_meal_files WHERE id=? AND org_id=?", (f["id"], oid))
        n += 1
    for mid in ids:
        if not c.execute("SELECT 1 FROM office_meal_files WHERE meal_id=? AND org_id=? LIMIT 1", (mid, oid)).fetchone():
            c.execute("DELETE FROM office_meal_log WHERE meal_id=? AND org_id=?", (mid, oid))
            c.execute("DELETE FROM office_meals WHERE id=? AND org_id=?", (mid, oid))
            n += 1
    return n


def bw_purge_tick(c):
    """Watchdog: the trash goes after BW_PURGE_DAYS also in office areas nobody opens."""
    import time
    if time.time() - BW_TICK["at"] < 6 * 3600:
        return 0
    BW_TICK["at"] = time.time()
    old = iso(now_utc() - timedelta(days=BW_PURGE_DAYS))
    with system_ctx(c):  # trashed rows of every office area (ids and stored names only, no content is read)
        oids = {r["org_id"] for r in c.execute("SELECT DISTINCT org_id FROM office_meals WHERE deleted_at IS NOT NULL AND deleted_at<? "
                                               "UNION SELECT DISTINCT org_id FROM office_meal_files WHERE deleted_at IS NOT NULL AND deleted_at<?",
                                               (old, old)).fetchall()}
        n = sum(bw_purge(c, oid) for oid in oids)
    c.commit()
    return n


BW_TICK = {"at": 0.0}


# ---------------------------------------------------------------- the choice lists
def bw_choices(c, oid):
    """{places: [{id, name, extra}], persons: [...]} by name."""
    out = {"places": [], "persons": []}
    own = ofr_own_uid("meals")  # 2.187.0 (#2476, review): level "own": only the places / people the person added
    for r in c.execute("SELECT * FROM office_meal_choices WHERE org_id=? AND deleted_at IS NULL" + (" AND created_by=?" if own else ""),
                       (oid, own) if own else (oid,)).fetchall():
        d = oc_dec_fields(c, oid, "office_meal_choices", r)
        out["places" if d["kind"] == "place" else "persons"].append({"id": d["id"], "kind": d["kind"], "name": d["name"], "extra": d.get("extra") or ""})
    for k in out:
        out[k].sort(key=lambda x: x["name"].casefold())
    return out


def bw_choice_name(v):
    n = " ".join(_text(v, "name", 200).split())
    if not n or len(n) > 120:
        raise BadInput(tr("Invalid value: {0}", "name"))
    return n


def bw_choice_add(c, oid, uid, kind, name, extra=""):
    """Adds a choice (or restores a removed one of the same name and kind) -> (row, created). Same name = the one there
    (an empty extra of it is filled in)."""
    ts = iso(now_utc())
    for r in c.execute("SELECT * FROM office_meal_choices WHERE org_id=? AND kind=? ORDER BY deleted_at IS NOT NULL, id", (oid, kind)).fetchall():
        d = oc_dec_fields(c, oid, "office_meal_choices", r)
        if d["name"].casefold() != name.casefold():
            continue
        ex = d.get("extra") or extra
        if d["deleted_at"] is None:
            if ex != (d.get("extra") or ""):
                c.execute("UPDATE office_meal_choices SET extra=?, updated_at=? WHERE id=? AND org_id=?",
                          (oc_enc_fields(c, oid, "office_meal_choices", {"extra": ex})["extra"], ts, d["id"], oid))
            return {"id": d["id"], "kind": kind, "name": d["name"], "extra": ex}, False
        row = oc_enc_fields(c, oid, "office_meal_choices", {"name": name, "extra": extra or d.get("extra") or ""})
        c.execute("UPDATE office_meal_choices SET deleted_at=NULL, name=?, extra=?, updated_at=? WHERE id=? AND org_id=?",
                  (row["name"], row["extra"], ts, d["id"], oid))
        return {"id": d["id"], "kind": kind, "name": name, "extra": extra or d.get("extra") or ""}, True
    if c.execute("SELECT COUNT(*) FROM office_meal_choices WHERE org_id=? AND deleted_at IS NULL", (oid,)).fetchone()[0] >= BW_MAX_CHOICES:
        raise BadInput(tr("Too many entries"))
    row = oc_enc_fields(c, oid, "office_meal_choices", {"org_id": oid, "kind": kind, "name": name, "extra": extra or "", "created_by": uid,
                                                         "created_at": ts, "updated_at": ts})
    cid = insert_id(c, f"INSERT INTO office_meal_choices({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    return {"id": cid, "kind": kind, "name": name, "extra": extra or ""}, True


def bw_adopt(c, oid, uid, m):
    """The place and the free names of meal m (public dict) taken into the choice lists where missing."""
    if m["place_name"]:
        bw_choice_add(c, oid, uid, "place", m["place_name"][:120], (m["place_address"] or "")[:200])
    for p in [m["host"] or {}] + list(m["guests"]):
        if p.get("name") and not p.get("id"):
            try:
                bw_choice_add(c, oid, uid, "person", bw_choice_name(p["name"]), (p.get("extra") or "")[:200])
            except BadInput:
                pass  # the limit: the meal keeps the name anyway


def _choice(c, oid, cid):
    r = c.execute("SELECT * FROM office_meal_choices WHERE id=? AND org_id=? AND deleted_at IS NULL", (cid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return oc_dec_fields(c, oid, "office_meal_choices", r)


@app.get("/api/office/meals/choices")
def bw_choices_get():
    c, uid, oid = _ctx()
    return jsonify(bw_choices(c, oid))


@app.post("/api/office/meals/choices")
def bw_choice_post():
    """{kind: place | person, name, extra?} -> 201 {id, kind, name, extra} (a removed one of the same name comes back: the
    undo of a removal); 200 when it is there already."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict) or b.get("kind") not in BW_CHOICE_KINDS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    row, made = bw_choice_add(c, oid, uid, b["kind"], bw_choice_name(b.get("name")), " ".join(_text(b.get("extra"), "extra", 300).split())[:200])
    bump(c)
    c.commit()
    return jsonify(row), 201 if made else 200


@app.patch("/api/office/meals/choices/<int:cid>")
def bw_choice_patch(cid):
    """{name?, extra?}: the meals keep what they have."""
    c, uid, oid = _ctx()
    cur = _choice(c, oid, cid)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    name = bw_choice_name(b["name"]) if "name" in b else cur["name"]
    extra = " ".join(_text(b.get("extra"), "extra", 300).split())[:200] if "extra" in b else cur.get("extra") or ""
    for r in c.execute("SELECT * FROM office_meal_choices WHERE org_id=? AND kind=? AND deleted_at IS NULL AND id<>?", (oid, cur["kind"], cid)).fetchall():
        if oc_dec_fields(c, oid, "office_meal_choices", r)["name"].casefold() == name.casefold():
            raise BadInput(tr("This entry already exists"))
    row = oc_enc_fields(c, oid, "office_meal_choices", {"name": name, "extra": extra})
    c.execute("UPDATE office_meal_choices SET name=?, extra=?, updated_at=? WHERE id=? AND org_id=?", (row["name"], row["extra"], iso(now_utc()), cid, oid))
    bump(c)
    c.commit()
    return jsonify(id=cid, kind=cur["kind"], name=name, extra=extra)


@app.delete("/api/office/meals/choices/<int:cid>")
def bw_choice_delete(cid):
    """Removes a choice (the meals keep their text); the undo posts it again."""
    c, uid, oid = _ctx()
    cur = _choice(c, oid, cid)
    ts = iso(now_utc())
    c.execute("UPDATE office_meal_choices SET deleted_at=?, updated_at=? WHERE id=? AND org_id=?", (ts, ts, cid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, choice={"id": cid, "kind": cur["kind"], "name": cur["name"], "extra": cur.get("extra") or ""})


# ---------------------------------------------------------------- routes: meals
@app.get("/api/office/meals")
def bw_meals_get():
    """?year=YYYY (optional) -> {meals, people, choices, currency, me, company}; trashed meals are not listed."""
    c, uid, oid = _ctx()
    y = request.args.get("year") or ""
    if y and not re.fullmatch(r"\d{4}", y):
        raise BadInput(tr("Invalid value: {0}", "year"))
    if bw_purge(c, oid):
        c.commit()
    return jsonify(meals=bw_rows(c, oid, year=y or None), people=bw_people(c, oid, uid), choices=bw_choices(c, oid),
                   currency=rk_home_cur(c, oid), me=uid, company=bw_company(c, oid))


@app.get("/api/office/meals/<int:mid>")
def bw_meal_get(mid):
    c, uid, oid = _ctx()
    _meal(c, oid, mid, mode="read")
    return jsonify(_one(c, oid, mid))


@app.post("/api/office/meals")
def bw_meal_post():
    """A new draft {date, place_name, place_address, occasion, host: {id}|{name, extra}, guests: [...], amounts:
    [{kind food|drinks, rate, gross}], tip, note}. 201 the meal."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = bw_clean(c, oid, uid, b)
    from .periodlock import period_need_open
    period_need_open(c, oid, row.get("date"))  # 2.148.0 A (#2471)
    ts = iso(now_utc())
    row.update(org_id=oid, currency=rk_home_cur(c, oid), status="draft", created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_meals", row)
    mid = insert_id(c, f"INSERT INTO office_meals({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, mid)), 201


@app.patch("/api/office/meals/<int:mid>")
def bw_meal_patch(mid):
    c, uid, oid = _ctx()
    write_lock(c, f"office_meal_{int(mid)}")  # 2.119.0 (#2288, review): no change slips past a parallel approval
    r = _meal(c, oid, mid)
    _need_draft(r)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = bw_clean(c, oid, uid, b, oc_dec_fields(c, oid, "office_meals", r))
    if row:
        from .periodlock import period_need_open
        period_need_open(c, oid, r["date"], row.get("date"))  # 2.148.0 A (#2471)
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_meals", row)
        c.execute(f"UPDATE office_meals SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [mid, oid])
        bump(c)
        c.commit()
    return jsonify(_one(c, oid, mid))


@app.delete("/api/office/meals/<int:mid>")
def bw_meal_delete(mid):
    """A draft into the trash (undo: POST .../restore). Approved: 409; ever approved: kept for BW_KEEP_YEARS (409)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_meal_{int(mid)}")  # 2.119.0 (#2288, review): no change slips past a parallel approval
    r = _meal(c, oid, mid)
    _need_draft(r)
    keep = bw_kept(c, oid, mid, r["date"])
    if keep:
        if local_now().date().isoformat() < keep:
            raise Denied(409, tr(BW_KEPT, keep))
    ts = iso(now_utc())
    c.execute("UPDATE office_meals SET deleted_at=?, updated_at=? WHERE id=? AND org_id=?", (ts, ts, mid, oid))
    ofx_log(c, oid, "delete", target="meals", detail={"id": mid})
    bump(c)
    c.commit()
    return jsonify(ok=True, id=mid)


@app.post("/api/office/meals/<int:mid>/restore")
def bw_meal_restore(mid):
    c, uid, oid = _ctx()
    r = _meal(c, oid, mid, deleted=True)
    if r["deleted_at"]:
        c.execute("UPDATE office_meals SET deleted_at=NULL, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), mid, oid))
        ofx_log(c, oid, "restore", target="meals", detail={"id": mid})
        bump(c)
        c.commit()
    return jsonify(_one(c, oid, mid))


def bw_missing(m):
    """The required fields an approval still misses (texts for the person)."""
    miss = []
    if not m["date"]:
        miss.append(tr("Date"))
    if not m["place_name"] or not m["place_address"].strip():
        miss.append(tr("Place with name and address"))
    occ = " ".join((m["occasion"] or "").split()).strip(" .!").casefold()
    if not occ:
        miss.append(tr("Occasion"))
    elif occ in BW_VAGUE:
        miss.append(tr("A concrete occasion (not only “business meal”)"))
    if not (m["host"] or {}).get("name"):
        miss.append(tr("Host"))
    if not m["guests"]:
        miss.append(tr("At least one guest"))
    if not m["amounts"]:
        miss.append(tr("Amounts"))
    return miss


@app.post("/api/office/meals/<int:mid>/approve")
def bw_meal_approve(mid):
    """Approves and locks a draft (the host's digital confirmation): 400 with the missing fields, 409 when approved already.
    New places and people go into the choice lists; one office_meal_log row."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_meal_{int(mid)}")
    r = _meal(c, oid, mid, mode="approve")  # 2.187.1 B (#2735): level "own": only as the host
    _need_draft(r)
    from .periodlock import period_need_open
    period_need_open(c, oid, r["date"])  # 2.148.0 A (#2471)
    m = _one(c, oid, mid)
    miss = bw_missing(m)
    if miss:
        raise BadInput(tr("Still missing: {0}", ", ".join(miss)))
    ts = iso(now_utc())
    name = bw_user_name(c, uid)
    row = oc_enc_fields(c, oid, "office_meals", {"approved_name": name})
    c.execute("UPDATE office_meals SET status='approved', approved_at=?, approved_by=?, approved_name=?, updated_at=? WHERE id=? AND org_id=?",
              (ts, uid, row["approved_name"], ts, mid, oid))
    bw_log(c, oid, mid, uid, name, "approve", "", ts)
    bw_adopt(c, oid, uid, m)
    ofx_log(c, oid, "approve", target="meals", detail={"id": mid})
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, mid))


@app.post("/api/office/meals/<int:mid>/unlock")
def bw_meal_unlock(mid):
    """{reason?} undoes the approval (the meal is a draft again); the log keeps who, when and why."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_meal_{int(mid)}")
    r = _meal(c, oid, mid)
    if r["status"] != "approved":
        raise Denied(409, tr("This entertainment receipt is not approved"))
    from .periodlock import period_need_open
    period_need_open(c, oid, r["date"])  # 2.148.0 A (#2471): an approved receipt of a locked month stays approved
    b = body()
    reason = _text(b.get("reason") if isinstance(b, dict) else None, "reason", 500)
    ts = iso(now_utc())
    c.execute("UPDATE office_meals SET status='draft', approved_at=NULL, approved_by=NULL, approved_name='', updated_at=? WHERE id=? AND org_id=?",
              (ts, mid, oid))
    bw_log(c, oid, mid, uid, bw_user_name(c, uid), "unlock", reason, ts)
    ofx_log(c, oid, "unlock", target="meals", detail={"id": mid})
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, mid))


def bw_user_name(c, uid):
    u = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone()
    return (u["display_name"] or u["username"]) if u else ""


def bw_log(c, oid, mid, uid, name, action, reason, ts):
    row = oc_enc_fields(c, oid, "office_meal_log", {"org_id": oid, "meal_id": mid, "user_id": uid, "user_name": name, "action": action,
                                                     "reason": reason or "", "at": ts})
    insert_id(c, f"INSERT INTO office_meal_log({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


# ---------------------------------------------------------------- the restaurant bill
def _fname(n, ext):
    n = os.path.basename((n or "").replace("\\", "/")).strip()
    n = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]+", "_", n)[:150] or "bill" + ext
    return n


@app.post("/api/office/meals/<int:mid>/file")
def bw_file_post(mid):
    """multipart file (PDF, JPEG or PNG) = the restaurant bill; a file there already goes into the trash (one live file).
    201 the meal. Locked meal: 409."""
    from ..admin.hosting import quota_guard
    c, uid, oid = _ctx()
    write_lock(c, f"office_meal_{int(mid)}")  # 2.119.0 (#2288, review): no change slips past a parallel approval
    r = _meal(c, oid, mid)
    _need_draft(r)
    f = request.files.get("file")
    if f is None:
        raise BadInput(tr("Invalid value: {0}", "file"))
    quota_guard(c, uid)
    data = f.stream.read(MAX_FILE_MB * 1024 * 1024 + 1)
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise BadInput(tr("{0}: larger than {1} MB", f.filename or "", MAX_FILE_MB))
    kind = next((x for x in BW_FILE_TYPES if data.startswith(x[0])), None)
    if not kind:
        raise BadInput(tr("Only PDF, JPEG or PNG files can be attached"))
    name = _fname(f.filename, kind[2])
    from ..files.upsafe import UploadRefused
    try:
        scan = sc_scan(name, data)
    except UploadRefused as e:
        raise BadInput(str(e)) from None
    file = f"meal{int(mid)}-{uuid.uuid4().hex[:16]}{kind[2]}"
    os.makedirs(bw_dir(oid), mode=0o700, exist_ok=True)
    path = bw_path(oid, file)
    oc_write_file(c, oid, path, data, fresh=True)  # sealed with the office area's key at rest (bytes from outside)
    os.chmod(path, 0o600)
    ts = iso(now_utc())
    try:
        old = [x["id"] for x in c.execute("SELECT id FROM office_meal_files WHERE meal_id=? AND org_id=? AND deleted_at IS NULL", (mid, oid))]
        c.execute("UPDATE office_meal_files SET deleted_at=? WHERE meal_id=? AND org_id=? AND deleted_at IS NULL", (ts, mid, oid))
        fid = insert_id(c, "INSERT INTO office_meal_files(org_id, meal_id, name, file, size, mime, sha256, created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (oid, mid, name, file, len(data), kind[1], hashlib.sha256(data).hexdigest(), uid, ts))
        sc_after_store(c, "omf", fid, oid, {"scan": scan})  # 2.190.0 D (#2561): scanner not reachable = checked later
        c.execute("UPDATE office_meals SET updated_at=? WHERE id=? AND org_id=?", (ts, mid, oid))
        bump(c)
        c.commit()
    except Exception:
        c.rollback()
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return jsonify(dict(_one(c, oid, mid), file_id=fid, replaced=old)), 201


def _file(c, oid, mid, fid, deleted=False):
    r = c.execute("SELECT * FROM office_meal_files WHERE id=? AND meal_id=? AND org_id=?" + ("" if deleted else " AND deleted_at IS NULL"),
                  (fid, mid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.get("/api/office/meals/<int:mid>/file/<int:fid>")
def bw_file_get(mid, fid):
    c, uid, oid = _ctx()
    _meal(c, oid, mid, mode="read")
    r = _file(c, oid, mid, fid)
    p = bw_path(oid, r["file"])
    if not p or not os.path.isfile(p):
        raise Denied(404)
    sc_guard(c, "omf", fid)  # 2.190.0 D (#2561): found infected (strict: not checked yet) = locked
    resp = Response(oc_read_file(c, p), mimetype=r["mime"] or "application/octet-stream")
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", r["name"]) or "bill"
    disp = "inline" if request.args.get("inline") == "1" else "attachment"
    resp.headers["Content-Disposition"] = f'{disp}; filename="{ascii_name}"; filename*=UTF-8\'\'' + urllib.parse.quote(r["name"])
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "sandbox"
    return resp


@app.delete("/api/office/meals/<int:mid>/file/<int:fid>")
def bw_file_delete(mid, fid):
    """The bill into the trash (undo: POST .../restore). Locked meal: 409."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_meal_{int(mid)}")  # 2.119.0 (#2288, review): no change slips past a parallel approval
    _need_draft(_meal(c, oid, mid))
    _file(c, oid, mid, fid)
    ts = iso(now_utc())
    c.execute("UPDATE office_meal_files SET deleted_at=? WHERE id=? AND org_id=?", (ts, fid, oid))
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, mid))


@app.post("/api/office/meals/<int:mid>/file/<int:fid>/restore")
def bw_file_restore(mid, fid):
    """The undo of a removal / a replacement: this file is the live one again (another live one goes into the trash)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_meal_{int(mid)}")  # 2.119.0 (#2288, review): no change slips past a parallel approval
    _need_draft(_meal(c, oid, mid))
    _file(c, oid, mid, fid, deleted=True)
    ts = iso(now_utc())
    c.execute("UPDATE office_meal_files SET deleted_at=? WHERE meal_id=? AND org_id=? AND deleted_at IS NULL AND id<>?", (ts, mid, oid, fid))
    c.execute("UPDATE office_meal_files SET deleted_at=NULL WHERE id=? AND org_id=?", (fid, oid))
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, mid))


# ---------------------------------------------------------------- the evaluation (filters like the travel expenses)
def bw_company(c, oid):
    from .model import office_settings, ofx_name1
    return ofx_name1((office_settings(c, oid).get("company") or {}).get("name") or "")


def bw_people_of(m):
    return [p for p in [m["host"] or {}] + list(m["guests"]) if p.get("name")]


def bw_filter_args():
    """(from, to, person key, occasion text) of the request: ?year= or ?from=&to=, ?person=u<id>|n:<name>, ?occasion=."""
    y = request.args.get("year") or ""
    if y and not re.fullmatch(r"\d{4}", y):
        raise BadInput(tr("Invalid value: {0}", "year"))
    df = _date(request.args.get("from"), "from") or (f"{y}-01-01" if y else "")
    dt = _date(request.args.get("to"), "to") or (f"{y}-12-31" if y else "")
    occ = _text(request.args.get("occasion"), "occasion", 200)
    return df, dt, rka_person_arg(), occ


def bw_report(c, oid, df="", dt="", person=None, occasion=""):
    """The approved meals within [df, dt] (with person = host or participant, occasion = part of the text) and their sums;
    drafts = how many drafts the filter would show besides (not in the sums)."""
    rows, drafts = [], 0
    tot = {k: dec(0) for k in ("bill", "food", "drinks", "tip", "gross", "vat", "net", "deductible", "not_deductible")}
    rates, months = {}, {}
    occ = occasion.casefold()
    for m in reversed(bw_rows(c, oid)):
        if (df and m["date"] < df) or (dt and m["date"] > dt):
            continue
        if person and person not in [rka_pkey(p) for p in bw_people_of(m)]:
            continue
        if occ and occ not in (m["occasion"] or "").casefold():
            continue
        if m["status"] != "approved":
            drafts += 1
            continue
        rows.append(m)
        k = m["calc"]
        for x in tot:
            tot[x] += dec(k[x])
        for ln in k["lines"]:
            g = rates.setdefault((ln["kind"], ln["rate"]), {"kind": ln["kind"], "rate": ln["rate"], "gross": dec(0), "vat": dec(0), "net": dec(0)})
            for x in ("gross", "vat", "net"):
                g[x] += dec(ln[x])
        mo = months.setdefault(m["date"][:7], {"key": m["date"][:7], "count": 0, "gross": dec(0), "deductible": dec(0)})
        mo["count"] += 1
        mo["gross"] += dec(k["gross"])
        mo["deductible"] += dec(k["deductible"])
    return {"meals": rows, "count": len(rows), "drafts": drafts, "total": {k: dstr(money(v)) for k, v in tot.items()},
            "rates": [{**g, **{x: dstr(money(g[x])) for x in ("gross", "vat", "net")}} for g in sorted(rates.values(), key=lambda g: (g["kind"], -dec(g["rate"])))],
            "months": [{**g, "gross": dstr(money(g["gross"])), "deductible": dstr(money(g["deductible"]))} for g in sorted(months.values(), key=lambda g: g["key"])]}


def bw_pname(p, co=""):
    ex = p.get("extra") or (co if p.get("id") else "")
    return p["name"] + (f" ({ex})" if ex else "")


def bw_fname(df, dt, person, occ, ext):
    tail = ("-" + re.sub(r"[^a-z0-9]+", "-", person.lower()).strip("-") if person else "") + ("-" + re.sub(r"[^a-z0-9]+", "-", occ.lower()).strip("-")[:40] if occ else "")
    return f"entertainment-{df or 'all'}-{dt or 'all'}{tail}.{ext}"


@app.get("/api/office/meals/report")
def bw_report_get():
    """?year= | from=&to=, person=, occasion=, format=csv|pdf -> {meals, count, drafts, total, rates, months, currency} or the file."""
    c, uid, oid = _ctx()
    df, dt, person, occ = bw_filter_args()
    rep = bw_report(c, oid, df, dt, person, occ)
    cur = rk_home_cur(c, oid)
    fmt = request.args.get("format") or ""
    if fmt == "csv":
        co = bw_company(c, oid)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        num = lambda v: str(v).replace(".", ",")  # noqa: E731
        w.writerow([tr("Date"), tr("Place"), tr("Address"), tr("Occasion"), tr("Host"), tr("Guests"), tr("Food") + f" ({cur})", tr("Drinks") + f" ({cur})",
                    tr("Tip") + f" ({cur})", tr("Gross") + f" ({cur})", tr("Input VAT") + f" ({cur})", tr("Net") + f" ({cur})",
                    tr("Deductible 70 %") + f" ({cur})", tr("Not deductible 30 %") + f" ({cur})", tr("Approved by"), tr("Approved at")])
        for m in rep["meals"]:
            k = m["calc"]
            w.writerow([m["date"], _csv_safe(m["place_name"]), _csv_safe(m["place_address"].replace("\n", ", ")), _csv_safe(m["occasion"]),
                        _csv_safe(bw_pname(m["host"] or {"name": ""}, co)), _csv_safe(", ".join(bw_pname(p, co) for p in m["guests"])),
                        num(k["food"]), num(k["drinks"]), num(k["tip"]), num(k["gross"]), num(k["vat"]), num(k["net"]), num(k["deductible"]),
                        num(k["not_deductible"]), _csv_safe(m["approved_name"]), (m["approved_at"] or "")[:16].replace("T", " ")])
        t = rep["total"]
        w.writerow([tr("Total"), rep["count"], "", "", "", "", num(t["food"]), num(t["drinks"]), num(t["tip"]), num(t["gross"]), num(t["vat"]), num(t["net"]),
                    num(t["deductible"]), num(t["not_deductible"]), "", ""])
        ofx_log(c, oid, "export", target="meals", detail={"what": "meals.csv", "from": df, "to": dt})
        c.commit()
        return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{bw_fname(df, dt, person, occ, "csv")}"'})
    if fmt == "pdf":
        from .mealpdf import bw_report_pdf
        data = bw_report_pdf(c, oid, rep, df, dt, person, occ, cur)
        ofx_log(c, oid, "export", target="meals", detail={"what": "meals.pdf", "from": df, "to": dt})
        c.commit()
        return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{bw_fname(df, dt, person, occ, "pdf")}"',
                                                                   "Cache-Control": "no-store"})
    return jsonify(dict(rep, currency=cur))


@app.get("/api/office/meals/<int:mid>/pdf")
def bw_meal_pdf(mid):
    """The receipt of one meal as PDF (Eigenbeleg; a draft is marked as such)."""
    from .mealpdf import bw_meal_pdf_data
    c, uid, oid = _ctx()
    _meal(c, oid, mid, mode="read")
    m = _one(c, oid, mid)
    data = bw_meal_pdf_data(c, oid, m)
    ofx_log(c, oid, "pdf", target="meals", detail={"id": mid}, dedupe_min=10)
    c.commit()
    disp = "inline" if request.args.get("inline") == "1" else "attachment"
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'{disp}; filename="entertainment-{m["date"]}-{mid}.pdf"',
                                                               "Cache-Control": "no-store"})
