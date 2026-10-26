"""2.299.0 D (#3193): the fixed check of a receipt (docs/rcheck.py rck_check) at the receipt -- never blocking, hints only.

Which documents: a receipt of the office (rc_receipts) or a document the recognition read invoice values off
(doc_meta.extracted). The check runs on the values the receipt has now: the recognised ones (doc_meta.extracted), the
document's date / amount / sender, the receipt's VAT rate and category (an entertainment category = the meal details)
and the recognised text (an incoming e-invoice: its fields only, no text checks).

Stored, not counted live: the receipts list of the bookkeeping must stay fast with thousands of receipts (the text is
sealed: opening and reading it per receipt and request would cost seconds). doc_meta.rchk keeps the codes ("." = none,
"" = not checked yet), rchk_at the state they were made for (a hash of the values they read, rck_stamp):
after every recognition run the hook writes them; a list finds the stale ones by the state and checks at most RCK_FILL of
them per request (the rest the next time, "pending"). A single document (its sheet, the API v1) is always checked fresh.
"Hide hints" (POST /api/docs/<id>/checks {do: hide | show}) keeps the codes shown at that time in rchk_ok (like dup_ok of a
duplicate): a new, different hint shows again. People with the right edit on the document; agents 403 (they read the
hints with the document)."""
import hashlib
import re

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, err
from ..core.i18n import tr
from ..core.numtext import user_dec
from ..files.store import fs_log_add
from ..docs import store as S
from ..docs.ingest import doc_on_done
from ..docs.web import _doc, _no_agent, doc_json
from ..docs.rcheck import rck_check

RCK_FILL = 200          # stale receipts checked per list request (the rest on the next one; ~1 s)
RCK_VER = "1"           # part of the stamp: a new rule set checks every receipt again
RCK_MEAL = re.compile(r"bewirt|restaurant|gastst|hospitality|entertainment|\bmeals?\b", re.I)
_AMT = re.compile(r"-?\d+\.\d{2}")


def _rc(c, nid):
    return c.execute("SELECT category, vat_pct, set_at FROM rc_receipts WHERE node_id=?", (nid,)).fetchone()  # what rck_stamp reads


def rck_stamp(m, r):
    """The state the hints are made for: the values they read (not only times: two changes may fall in one second)."""
    v = [RCK_VER, m["updated_at"], m["extracted"], m["amount"], m["doc_date"], m["currency"], m["sender_id"], m["type_id"]]
    v += [r["set_at"], r["category"], r["vat_pct"]] if r else []
    return hashlib.sha1("\x1f".join("" if x is None else str(x) for x in v).encode()).hexdigest()[:20]


def rck_fields(c, m, r):
    """(fields for rck_check, text or None) of document meta m (r: its receipt row or None); None when it is no receipt."""
    det = S.meta_json(c, m, "extracted", {}) if m["extracted"] else {}
    if not r and not det:
        return None
    ws = m["ws"]
    f = {k: v for k, v in det.items() if not k.startswith("_")}
    f["date"] = m["doc_date"] or None
    f["amount"] = S.doc_open(c, ws, "doc_meta.amount", m["amount"]) or None
    f["sender"] = S.label_name(c, ws, "sender", m["sender_id"]) if m["sender_id"] else None
    if not f.get("currency"):
        f["currency"] = m["currency"] or None
    if r and r["vat_pct"] is not None and not f.get("vat_pct") and not f.get("vat_rates"):
        f["vat_pct"] = r["vat_pct"]          # set by a person
    kind = " ".join(x for x in ((r["category"] or "") if r else "", S.label_name(c, ws, "type", m["type_id"]) if m["type_id"] else "") if x)
    f["meal"] = bool(RCK_MEAL.search(kind))
    f["einvoice"] = bool(det.get("_einv"))
    return f, (None if f["einvoice"] else S.meta_text(c, m))


def rck_codes(items):
    return ",".join(x["code"] for x in items) or "."


def _shown(codes, ok):
    """The codes of rchk not hidden by rchk_ok."""
    ok = set((ok or "").split(","))
    return [x for x in (codes or "").split(",") if x and x != "." and x not in ok]


def rck_run(c, m, r=None, store=True):
    """Check document meta m now -> items (None: no receipt); store=True keeps the codes (rchk) and the state they are for."""
    if r is None:
        r = _rc(c, m["node_id"])
    fx = rck_fields(c, m, r)
    items = rck_check(fx[0], fx[1]) if fx else None
    if store:
        c.execute("UPDATE doc_meta SET rchk=?, rchk_at=? WHERE node_id=?", (rck_codes(items or []), rck_stamp(m, r), m["node_id"]))
    return items


def rck_on_done(c, nid, first):
    """doc_on_done hook: check the document after every recognition run."""
    m = S.meta_row(c, nid)
    if m:
        rck_run(c, m)


def _text(x):
    d = user_dec()
    args = [a.replace(".", d) if _AMT.fullmatch(a) else a for a in x.get("args") or []]
    return tr(x["msg"], *args)


def rck_view(c, m):
    """{items [{code, level, text}], hidden: the shown ones hidden by a person} for a document's sheet / the API v1; None
    when it is no receipt or nothing is to say."""
    items = rck_run(c, m, store=False)
    if not items:
        return None
    ok = set((m["rchk_ok"] or "").split(","))
    return {"items": [{"code": x["code"], "level": x["level"], "text": _text(x)} for x in items],
            "hidden": all(x["code"] in ok for x in items)}


def rck_seen(c, rows, fill=False):
    """{node_id: number of shown hints} for list rows (node_id, rchk, rchk_at, rchk_ok + the columns of rck_stamp);
    fill=True checks up to RCK_FILL stale ones now (and commits). -> (counts, pending = stale ones left)."""
    out, stale = {}, []
    for x in rows:
        if x["rchk"] and x["rchk_at"] == rck_stamp(x, x):
            out[x["node_id"]] = len(_shown(x["rchk"], x["rchk_ok"]))
        else:
            stale.append(x)
    done = 0
    if fill and stale:
        for x in stale[:RCK_FILL]:
            done += 1
            m = S.meta_row(c, x["node_id"])
            if m:
                out[x["node_id"]] = len(_shown(rck_codes(rck_run(c, m) or []), m["rchk_ok"]))
        c.commit()
    for x in stale[done:]:  # not checked yet: what was stored before (maybe nothing)
        out.setdefault(x["node_id"], len(_shown(x["rchk"], x["rchk_ok"])))
    return out, len(stale) - done


@app.post("/api/docs/<int:nid>/checks")
def rck_post(nid):
    """{do: "hide"} hides the hints shown now (a new, different one shows again), {do: "show"} shows them again (its undo).
    People with the right edit on the document; agents 403."""
    c = db()
    _no_agent()
    m, n = _doc(c, nid, write=True)
    act = body().get("do")
    if act not in ("hide", "show"):
        return err(tr("Invalid value: {0}", "do"))
    items = rck_run(c, m, store=True) if act == "hide" else []
    codes = ",".join(x["code"] for x in items or [])
    c.execute("UPDATE doc_meta SET rchk_ok=? WHERE node_id=?", (codes, nid))
    fs_log_add(c, nid, "edit")
    bump(c)
    c.commit()
    m, n = _doc(c, nid)
    return jsonify({"doc": doc_json(c, m, n, full=True, role=n["role"])})


def _hook():
    if rck_on_done not in doc_on_done:
        doc_on_done.append(rck_on_done)


_hook()
