"""2.250.0 A (#2992): the office hits of the web search (GET /api/search, tasks/ftsearch.py): clients (name, contact person,
customer number) and documents (number, client, project title / reference) of the office area the person works in.

Visible exactly like the office lists themselves: the feature "office" on, a person (no agent, no kid, no API token),
the office area of the workspace (office_where: private = the personal office, an organisation = its office), the
organisation role (office_allowed: guests nothing) and the level "view" of the area "Quotes & invoices" (office_can: groups,
"Previous access", admins / personal owner). Clients also need the feature "clients" (their page) and the same
membership as GET /api/clients. A short list per kind (BS_LIMIT), ILIKE on the plain columns (no index, no migration).
No routes of its own; the agents' API (fts_v1) never asks for it."""
import json
import re

from flask import g, has_request_context

from ..core.db import usettings
from ..core.pg import like_escape
from ..core.errors import BadInput, Denied
from ..accounts.orgroles import office_allowed, user_orgs_full
from ..accounts.orgs import user_orgs
from .model import office_on, office_where, pb_cl_sql, pb_owner, pb_personal
from .rights import office_can

BS_LIMIT = 5


def _rec(v):
    try:
        d = json.loads(v or "{}")
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def bs_office_oid(c, uid):
    """The office area whose hits uid may see in this request, or None (no office hits at all)."""
    if not has_request_context():
        return None
    u = getattr(g, "user", None)
    if u is None or ("kind" in u.keys() and u["kind"] == "agent") or ("kid" in u.keys() and u["kid"]):
        return None
    if g.get("auth_via") not in ("session", "proxy"):  # API tokens (agents' API), public links: never office hits
        return None
    if not office_on(c, uid):
        return None
    # 2.250.0 (#2992 review): office_where would make the personal office on this read (pb_personal create=True); without
    # one there is nothing to find
    orgs, ws = user_orgs(c, uid), (usettings(c, uid).get("workspace") or "").strip()
    m = re.fullmatch(r"org:(\d{1,9})", ws)
    if not (m and int(m.group(1)) in orgs) and (ws == "private" or not orgs) and pb_personal(c, uid, create=False) is None:
        return None
    try:
        oid, _role = office_where(c, uid)
    except (BadInput, Denied):
        return None
    if office_allowed(c, uid, oid, write=False) or not office_can(c, uid, oid, "offers", "view"):
        return None
    return oid


def _clients_ok(c, uid, oid):
    """True when uid sees the clients of office area oid on the clients page (feature + GET /api/clients' membership)."""
    if "clients" not in (usettings(c, uid).get("features") or "").split(","):
        return False
    if pb_owner(c, oid) is not None:
        return pb_owner(c, oid) == uid
    return oid in set(user_orgs(c, uid)) & set(user_orgs_full(c, uid))


def bs_office_hits(c, uid, q):
    """[{kind: client | offer | invoice | credit | reminder | delivery, id, label, sub, go}] for q (at most BS_LIMIT per
    group: clients, documents); [] when uid sees no office."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    oid = bs_office_oid(c, uid)
    if oid is None:
        return []
    like = f"%{like_escape(q)}%"
    low, cf = q.lower(), q.casefold()
    out = []
    if _clients_ok(c, uid, oid):
        for r in c.execute(f"""SELECT id, name, contact, customer_no FROM clients WHERE {pb_cl_sql(c, oid)} AND archived=0 AND deleted_at IS NULL
                AND (name ILIKE ? ESCAPE '\\' OR contact ILIKE ? ESCAPE '\\' OR customer_no ILIKE ? ESCAPE '\\')
                ORDER BY (lower(name) LIKE ? ESCAPE '\\') DESC, lower(name), id LIMIT {BS_LIMIT} -- pg-ok: both sides lower-cased""",
                           (like, like, like, f"{like_escape(low)}%")).fetchall():
            sub = r["contact"] if low in (r["contact"] or "").lower() and low not in (r["name"] or "").lower() else ""
            out.append({"kind": "client", "id": r["id"], "label": r["name"] or "…", "sub": sub or r["customer_no"] or "",
                        "go": f"client/{int(r['id'])}"})
    # documents: the columns the document list searches (odoc_list ?q=); the recipient JSON only by its values
    rows = c.execute(f"""SELECT d.id, d.kind, d.number, d.project_title, d.project_ref, d.recipient, d.date, cl.name AS client_name
            FROM office_docs d LEFT JOIN clients cl ON cl.id=d.client_id
            WHERE d.org_id=? AND (d.number ILIKE ? ESCAPE '\\' OR d.project_title ILIKE ? ESCAPE '\\' OR d.project_ref ILIKE ? ESCAPE '\\'
                OR d.recipient ILIKE ? ESCAPE '\\' OR cl.name ILIKE ? ESCAPE '\\')
            ORDER BY (lower(d.number) LIKE ? ESCAPE '\\') DESC, d.date DESC, d.id DESC LIMIT {BS_LIMIT * 6} -- pg-ok: both sides lower-cased""",
                     (oid, like, like, like, like, like, f"{like_escape(low)}%")).fetchall()
    n = 0
    for r in rows:
        rec = _rec(r["recipient"])
        who = r["client_name"] or rec.get("name") or ""
        vals = [r["number"], r["project_title"], r["project_ref"], r["client_name"]] + [v for v in rec.values() if isinstance(v, str)]
        if not any(cf in (v or "").casefold() for v in vals):
            continue  # only a key of the recipient JSON matched ("name", "street" …)
        out.append({"kind": r["kind"], "id": r["id"], "label": r["number"] or r["project_title"] or "…",
                    "sub": " · ".join(x for x in (who, r["project_title"] if r["number"] else "") if x),
                    "go": f"office/offers/{int(r['id'])}"})
        n += 1
        if n >= BS_LIMIT:
            break
    return out
