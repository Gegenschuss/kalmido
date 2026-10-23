"""2.68.0 (#1839): old data into the office with the person's own agent -- the agent reads, the person decides.

Kalmido fixes one JSON format; the agent (any model, also a local one) reads the old data itself (a spreadsheet, a PDF, a
list in a mail) and sends it as ONE import proposal: POST /api/v1/agent/proposals/import (scope "import", off for every
agent until a person turns it on; MCP propose_import)
  {area: "fixed_costs", user_id?, title?, summary?, note?, items: [{label, amount, repeat, start, until?, category?, vat_rate?}]}
(the fields of the spreadsheet import of 2.67, office/fixedimport.py). It writes nothing itself: the proposal is a ready
proposal job of kind "import" (agent_jobs, as the layout proposals of agents/lyprop.py); the person gets News + push
"Proposal ready" and a card with the preview of the spreadsheet import: every row new / already there (unticked) / with an
error (greyed out, with the reason), checked against the office as it is when the card is OPENED, never when it is made.
Accepting writes the ticked rows (VAT per row changed there) with the person's account through fixedimport.fci_write
(every row checked again, all or nothing, MAX_FIXED, the office log "import fixed_costs" names the agent); one undo step
removes exactly the rows it made (unchanged since), redo makes them again.

Boundaries: the office routes stay closed to agent tokens (office.model office_gate) and nothing of the office goes back
to the agent -- neither the card nor the job / its events carry the office's rows or which rows were already there; after
the decision the agent hears only counts (created / skipped). The person: lyp_person (the owner of a personal agent or a
person who may chat with it, in the agent's organisation when it has one); the office module must be on for them. The
target is the office the person works in when ACCEPTING (office_org with the admin role, also the personal office of a
freelancer); an agent of an organisation only into that organisation. Only the person the card is for can open, accept,
discard or undo it (proposals.need_prop). At most AIM_ROWS rows per card, AIM_OPEN_MAX open cards per agent, a card
expires after AIM_DAYS days. Kalmido never runs a model itself."""
import hashlib
import json
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.pg import insert_id
from ..core.i18n import tr
from ..core.db import bump, db, iso, now_utc, parse_iso
from ..core.access import Denied
from ..accounts.session import me
from ..core.errors import BadInput
from ..api.common import v1_args, v1_err, v1_json, v1_view

AIM_KIND = "import"
AIM_AREAS = ("fixed_costs",)  # later: further areas of the office (the format keeps the field)
AIM_ROWS = 500                # rows per card (as the spreadsheet import)
AIM_OPEN_MAX = 5              # open import cards per agent
AIM_DAYS = 14                 # an open card expires after this many days
AIM_DAY_MAX = 20              # import proposals of one agent for one person per 24 hours (each one is News + push)
AIM_NOTE_MAX = 2000
AIM_FIELDS = ("label", "amount", "repeat", "start", "until", "category", "vat_rate")
AIM_CUT = {"label": 300, "amount": 40, "repeat": 20, "start": 20, "until": 20, "category": 150, "vat_rate": 10}


def _scalar(k, v):
    """One field of a row as the agent sent it, kept only as a short scalar (the real check comes with rk_fixed_clean)."""
    import re
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v if v == v and abs(v) < 10 ** 12 else None
    if isinstance(v, str):
        return re.sub(r"[\x00-\x1f\x7f]", "", v).strip()[:AIM_CUT[k]]
    return None


def aim_validate(b, inp):
    """prop_validate for kind import: {area, title?, summary?, note?, items} -> {area, note, items: [{row, label, amount,
    repeat, start, until, category, vat_rate}]}. Only the shape is checked here; every row is judged when the card is shown
    and again when it is accepted. Unknown fields of a row (an org_id, an id, created_by ...) are dropped."""
    from ..agents.proposals import _p_keys, _p_str
    from ..office.fixedimport import fci_num, fci_vat_guess
    from ..office.calc import dstr, money
    _p_keys(b, "", ("kind", "summary", "area", "title", "note", "items"))
    area = b.get("area", "fixed_costs")
    if area not in AIM_AREAS:
        raise BadInput(tr("Only fixed costs can be imported for now (area fixed_costs)"))
    raw = b.get("items")
    if not isinstance(raw, list) or not raw:
        raise BadInput(tr("Missing field: {0}", "items"))
    if len(raw) > AIM_ROWS:
        raise BadInput(tr("Too many rows (at most {0})", AIM_ROWS))
    items = []
    for i, it in enumerate(raw):
        if not isinstance(it, dict):
            raise BadInput(tr("Invalid value: {0}", f"items[{i}]"))
        row = {"row": i + 1, **{k: _scalar(k, it.get(k)) for k in AIM_FIELDS}}
        if isinstance(row["amount"], str):  # "1.200,50", "29,90", "1200.50": read like a spreadsheet cell
            d = fci_num(row["amount"])
            if d is not None:
                row["amount"] = dstr(money(d))
        if row["vat_rate"] in (None, ""):  # as the spreadsheet import: 19 %, insurances, contributions, bank, taxes, memberships 0 % (2.122.2)
            row["vat_rate"] = fci_vat_guess(row["label"], row["category"])  # 2.122.2 (#2323)
        items.append(row)
    return {"area": area, "note": _p_str(b.get("note"), "note", AIM_NOTE_MAX, line=False), "items": items}


# ---------------------------------------------------------------- judging the rows (the card and the acceptance)
def aim_item(row, vat=None):
    """A stored row -> what fci_write gets."""
    it = {k: row.get(k) for k in AIM_FIELDS}
    if vat is not None:
        it["vat_rate"] = vat
    return it


def aim_rows(c, oid, items, vats=None):
    """The rows of a card judged like the spreadsheet preview: [{k, row, label, amount, gross, repeat, start, until, category,
    vat_rate, status new|dup|error, reason, sel}]. oid None = no office to compare with (only new / error)."""
    from ..office.cashflow import fci_gross, rk_fixed_clean
    from ..office.calc import dstr
    from ..office.fixedimport import fci_key, fci_seen
    seen = fci_seen(c, oid) if oid else set()
    out = []
    for i, row in enumerate(items):
        vat = (vats or {}).get(str(i))
        base = {"k": str(i), "row": row.get("row", i + 1), "label": str(row.get("label") or "")[:200], "amount": "", "gross": "",
                "repeat": "", "start": "", "until": "", "category": str(row.get("category") or "")[:100], "vat_rate": 0,
                "status": "error", "reason": "", "sel": False}
        try:
            f = rk_fixed_clean(aim_item(row, vat))
        except BadInput as x:
            out.append({**base, "reason": str(x.args[0] if x.args else x)})
            continue
        key = fci_key(f["label"], f["amount"], f["repeat"], f["start"])
        dup = key in seen
        seen.add(key)
        out.append({**base, **{k: f[k] for k in ("label", "amount", "repeat", "start", "category", "vat_rate")}, "until": f["until"] or "",
                    "gross": dstr(fci_gross(f["amount"], f["vat_rate"])), "status": "dup" if dup else "new",
                    "reason": tr("Already there") if dup else "", "sel": not dup})
    return out


def aim_target(c, j):
    """The office the person takes the card over into, now: (org id, name, personal). The office module on, the admin role
    there (403), an agent of an organisation only into that one (409: switch the workspace)."""
    from ..office.model import OFFICE_OFF, office_on, office_org, pb_owner
    uid = me()
    if not office_on(c, uid):
        raise Denied(403, tr(OFFICE_OFF))
    oid = office_org(c, uid, admin=True, area="cashflow")  # 2.187.0 C (#2476): fixed costs = the cash flow area
    inp = json.loads(j["input"] or "{}")
    if "org" in inp:  # 2.68.0 (#1839 review): the agent's organisation when it proposed - stays bound after the person left it
        want = inp["org"]
    else:
        a = c.execute("SELECT org_id FROM agents WHERE user_id=?", (j["agent_id"],)).fetchone()
        if not a:  # not visible (any more): never "free for every office"
            raise Denied(409, tr("There is no proposal to apply (anymore)"))
        want = a["org_id"]
    name = (c.execute("SELECT name FROM orgs WHERE id=?", (want or oid,)).fetchone() or [""])[0]
    if want and want != oid:
        raise Denied(409, tr("This proposal can only be taken over into the office of “{0}”: switch your workspace there first", name or "?"))
    personal = pb_owner(c, oid) is not None
    return oid, (tr("Your personal office") if personal else name), personal


def _expired(j):
    return bool(j["created_at"]) and j["created_at"] < iso(now_utc() - timedelta(days=AIM_DAYS))


def aim_view_extra(c, j):
    """For the card (only the person it is for): the target office and the judged rows. Never part of what the agent sees."""
    if j["user_id"] != me() or j["prop_state"] != "ready":
        return {}
    p = json.loads(j["proposal"] or "null") or {}
    office, problem, oid = None, "", None
    try:
        oid, name, personal = aim_target(c, j)
        office = {"id": oid, "name": name, "personal": personal}
    except (BadInput, Denied) as x:
        problem = x.text() if isinstance(x, Denied) else str(x.args[0] if x.args else x)
    rows = aim_rows(c, oid, p.get("items") or [])
    return {"import": {"version": aim_version(j), "area": p.get("area"), "office": office, "problem": problem, "rows": rows,
                       "counts": {s: sum(1 for r in rows if r["status"] == s) for s in ("new", "dup", "error")},
                       "expires_at": iso(parse_iso(j["created_at"]) + timedelta(days=AIM_DAYS)) if j["created_at"] else None}}


def aim_version(j):
    """The rows the card shows (2.68.0, #1839 review): the person accepts exactly these, not rows the agent sent meanwhile."""
    return hashlib.sha256((j["proposal"] or "").encode()).hexdigest()[:16]


def aim_run(c, j, sel, ed, extra, rec):
    """Accept (as the person): the ticked rows (edits {k: {vat_rate}}) into the office the person works in, all or nothing."""
    from ..office.cashflow import CF_VAT_RATES, rk_fixed_clean
    from ..office.fixedimport import fci_write
    from ..agents.proposals import _p_keys
    if _expired(j):
        raise Denied(409, tr("This proposal has expired"))
    if "version" in (extra or {}) and extra["version"] != aim_version(j):  # 2.68.0 (#1839 review): the agent replaced the rows meanwhile
        raise Denied(409, tr("The proposal changed meanwhile: open it again"))
    items = (json.loads(j["proposal"]) or {}).get("items") or []
    oid = aim_target(c, j)[0]
    keys = sorted({int(k) for k in sel if k.isdigit() and int(k) < len(items)})
    if len(keys) != len(set(sel)):
        raise BadInput(tr("Invalid value: {0}", "select"))
    vats = {}
    for k, e in (ed or {}).items():
        if not (isinstance(k, str) and k.isdigit() and int(k) < len(items)) or not isinstance(e, dict):
            raise BadInput(tr("Invalid value: {0}", "edits"))
        _p_keys(e, f"edits.{k}", ("vat_rate",))
        v = e.get("vat_rate")
        if "vat_rate" in e and (isinstance(v, bool) or v not in CF_VAT_RATES):
            raise BadInput(tr("Invalid value: {0}", "vat_rate"))
        if "vat_rate" in e:
            vats[int(k)] = v
    todo = []
    for k in keys:
        it = aim_item(items[k], vats.get(k))
        try:
            todo.append(rk_fixed_clean(it))
        except BadInput as x:
            raise BadInput(tr("Row {0}: {1}", items[k].get("row", k + 1), str(x.args[0] if x.args else x))) from None
    ids = fci_write(c, me(), oid, todo, detail={"agent": j["agent_id"], "job": j["id"]})
    rec.update(org=oid, made=ids, rows=todo, total=len(items), written_at=iso(now_utc()))
    return rec


def aim_undo(c, j, rec, back=True):
    """Undo: the rows this card made go (only in its office, only those still there and unchanged since). Redo: the rows the
    undo removed come again (new ids; again all or nothing)."""
    from ..office.fixedimport import fci_write
    from ..office.model import office_org
    oid = rec.get("org")
    if not oid or office_org(c, me(), admin=True, area="cashflow") != oid:
        raise Denied(409, tr("Switch your workspace to the office of this import first"))
    if not back:
        rows = rec.get("removed") or []
        if not rows:
            return 0, []
        ids = fci_write(c, me(), oid, rows, detail={"agent": j["agent_id"], "job": j["id"], "redo": 1})
        rec.update(made=ids, removed=[], written_at=iso(now_utc()))  # 2.68.0 (#1839 review): rows kept at the undo stay out
        return len(ids), []
    made = [int(x) for x in rec.get("made") or []]
    q = ",".join("?" * len(made)) or "NULL"
    have = {r["id"]: r for r in c.execute(f"SELECT id, label, updated_at FROM office_fixed_costs WHERE org_id=? AND id IN ({q})", [oid] + made)}
    gone = [i for i in made if i in have and (have[i]["updated_at"] or "") <= (rec.get("written_at") or "")]
    kept = [i for i in made if i in have and i not in gone]
    by_id = dict(zip(made, rec.get("rows") or []))
    n = c.execute(f"DELETE FROM office_fixed_costs WHERE org_id=? AND id IN ({','.join('?' * len(gone)) or 'NULL'})", [oid] + gone).rowcount if gone else 0
    rec.update(removed=[by_id[i] for i in gone if i in by_id], kept=kept)
    from ..office.ledger import ofx_log
    ofx_log(c, oid, "delete", target="fixed_costs", detail={"count": n, "undo": 1, "job": j["id"]})
    return n, [tr("{0} fixed costs changed since", len(kept))] if kept else []


def aim_result(rec):
    made = rec.get("made") or []
    return {"created": len(made), "skipped": max(0, int(rec.get("total") or 0) - len(made))}


def aim_expire(c):
    """Open import cards older than AIM_DAYS are discarded (the agent is not told: it simply expired)."""
    ts = iso(now_utc())
    c.execute("""UPDATE agent_jobs SET prop_state='discarded', state='stopped', updated_at=? WHERE kind=? AND prop_state='ready'
                 AND created_at<?""", (ts, AIM_KIND, iso(now_utc() - timedelta(days=AIM_DAYS))))


# ---------------------------------------------------------------- the route for agents
@app.post("/api/v1/agent/proposals/import")
@v1_view
def v1_aim_propose():
    """{area: fixed_costs, items: [...], title?, summary?, note?, user_id?} -> a ready proposal job (kind import) for the person.
    Nothing is written until the person accepts it; the answer carries no office data."""
    from ..agents.core import JOB_TITLE_MAX, job_dict, need_agent
    from ..agents.lyprop import lyp_person
    from ..agents.proposals import PROP_MAX_BYTES, _p_str, prop_ready_notify, prop_validate
    from ..agents.usage import usage_block
    from ..api.scopes import need_scope
    from ..office.model import office_on
    v1_args(())
    aid = need_agent()
    need_scope("import")
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    b = v1_json()
    c = db()
    pid = lyp_person(c, aid, b.get("user_id"))
    u = c.execute("SELECT * FROM users WHERE id=?", (pid,)).fetchone()
    if not u or ("kid" in u.keys() and u["kid"]) or not office_on(c, pid):
        return v1_err(400, tr("This person does not use the office: an import proposal is not possible"))
    if usage_block(c, aid):
        return v1_err(409, tr("You reached your usage limit"))
    p = prop_validate(AIM_KIND, {k: v for k, v in b.items() if k != "user_id"}, {"user_id": pid})
    aim_expire(c)
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND kind=? AND prop_state='ready'",
                 (aid, AIM_KIND)).fetchone()[0] >= AIM_OPEN_MAX:
        return v1_err(429, tr("At most {0} open import proposals: wait until the person decided", AIM_OPEN_MAX))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND user_id=? AND kind=? AND created_at>=?",
                 (aid, pid, AIM_KIND, iso(now_utc() - timedelta(days=1)))).fetchone()[0] >= AIM_DAY_MAX:
        return v1_err(429, tr("At most {0} import proposals per person and day", AIM_DAY_MAX))
    a = c.execute("SELECT org_id FROM agents WHERE user_id=?", (aid,)).fetchone()
    ts = iso(now_utc())
    n = len(p["items"])
    title = _p_str(b.get("title"), "title", 120) or tr("Import: {0} fixed costs", n)
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,NULL,?,?,'waiting','',?,?,?,?,'ready',NULL,?)""",
                    (aid, pid, title[:JOB_TITLE_MAX], ts, ts, AIM_KIND, json.dumps({"user_id": pid, "area": p["area"], **({"org": a["org_id"]} if a else {})}),
                     json.dumps(p, ensure_ascii=False)))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    prop_ready_notify(c, j)
    bump(c)
    c.commit()
    return jsonify({**job_dict(c, j), "rows": n, "expires_at": iso(now_utc() + timedelta(days=AIM_DAYS))}), 201


# ---------------------------------------------------------------- OpenAPI
def aim_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the import proposal (2.68.0, #1839)."""
    schemas["ImportFixedCost"] = {"type": "object", "required": ["label", "amount", "start"], "properties": {
        "label": {"type": "string", "maxLength": 200, "description": "Name of the fixed cost, e.g. Office rent"},
        "amount": {"type": ["number", "string"], "description": "Net amount in euros, more than 0: a number (1200.5) or a text read like a "
                                                              "spreadsheet cell (\"1.200,50\", \"1200.50\", \"29,90\")"},
        "repeat": {"type": "string", "enum": ["monthly", "quarterly", "yearly", "once"], "description": "Default monthly"},
        "start": {"type": "string", "format": "date", "description": "YYYY-MM-DD: the first due date (yearly / quarterly: its month counts)"},
        "until": {"type": ["string", "null"], "format": "date", "description": "YYYY-MM-DD: the last month (optional)"},
        "category": {"type": "string", "maxLength": 100, "description": "Free group, e.g. Insurances"},
        "vat_rate": {"type": "integer", "enum": [0, 7, 19], "description": "VAT on the net amount; left out: 19, insurances, contributions, bank and credit costs, taxes and memberships 0 (a tax adviser 19)"}}}
    paths["/agent/proposals/import"] = {"post": op(
        "2.68.0 (#1839): propose old data for the office (today: fixed costs) -- the person checks and takes it over", "Agents",
        ok({"type": "object"}, "Created", "201") | errs("400", "403", "404", "409", "413", "429"),
        body={"type": "object", "required": ["items"], "properties": {
            "area": {"type": "string", "enum": list(AIM_AREAS), "description": "What is imported (default fixed_costs)"},
            "items": {"type": "array", "maxItems": AIM_ROWS, "items": ref("ImportFixedCost")},
            "title": {"type": "string"}, "summary": {"type": "string", "description": "Markdown: where the data comes from"},
            "note": {"type": "string", "maxLength": AIM_NOTE_MAX, "description": "Rows you could not read, assumptions"},
            "user_id": {"type": "integer", "description": "The person you work for; a personal agent: its owner (default)"}}},
        scope="import",
        desc=f"Agents only, scope import (off until a person turns it on for you). You write nothing yourself: a ready proposal (kind import) "
             f"for the person, News + push per their settings, a card with the preview (new / already there / error per row, checked against "
             f"their office when they open it). They tick rows, may change the VAT per row and take them over into the office they work in "
             f"(one undo step). You never see their office data; the event job tells you approve / reject with counts only (created, skipped). "
             f"At most {AIM_ROWS} rows, {AIM_OPEN_MAX} open import proposals, {AIM_DAY_MAX} per person and day, expires after {AIM_DAYS} days. The office module must be on for the person.")}
