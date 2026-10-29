"""2.55.0 E (#1455): the newsletter connection of a workspace and the sync with the service (no own mass mailing).

One connection per workspace (ws like the documents: 'o<org>' for an organisation, set up by its admins; 'u<uid>' for a
person's own space -- a freelancer without an organisation is their own admin). The contacts come only from the address
books of exactly that workspace: an organisation's own address books (books.owner_org_id = its id), or the person's own
books outside every organisation -- never a member's private book, never another workspace.

- The access data are sealed with a key derived from the server key per workspace (like the Paperless-ngx token, also
  with the organisation's encryption off) and never leave the server; the app only gets "set" + the last four characters.
- Consent per contact (contacts.nl_status): '' unknown | yes | pending (double opt-in at the service) | unsub | bounce.
  Only contacts with an address and consent go to the service (mode doi: also the pending ones, as unconfirmed -- the
  service sends the opt-in mail). unsub / bounce never go there again; a run does not turn them back either (also not when the
  service reports the address active again).
- A run: first service -> Kalmido (unsubscriptions, bounces, confirmed opt-ins of every segment's list come back to the
  contacts), then Kalmido -> service (add, rename, take off the list what Kalmido put there and no longer matches; what
  somebody else put on the list stays). Every run is logged (numbers + error codes, never access data or addresses).
- Planned: daily when "auto" is on (the watchdog starts it, at most one run per connection at a time)."""
import json
import re
import threading
from datetime import timedelta

from ..core.db import connect, iso, now_utc, parse_iso
from ..core.i18n import N_, tr
from ..core.pg import system_ctx
from .adapters import NWL_KINDS, NwlError, nwl_adapter
from ..core.config import SECRET_KEY  # 2.149.0 G (#2517): pulled up from functions
from ..core.orgcrypt import oc_dec_k, oc_enc_k, OrgCryptError  # 2.149.0 G (#2517): pulled up from functions

NWL_STATUS = ("", "yes", "pending", "unsub", "bounce")
NWL_BLOCKED = ("unsub", "bounce")
NWL_MODES = ("consented", "doi")
NWL_SEG_MAX = 50
NWL_RUNS_KEEP = 50
NWL_EVERY_H = 24
NWL_SOURCE_MAX = 200
NWL_ERRORS_MAX = 20
_EMAIL = re.compile(r"[^@\s'\"\\<>,;]+@[^@\s'\"\\<>,;]+\.[^@\s'\"\\<>,;]+")
_BUSY = set()
_LOCK = threading.Lock()

NWL_ERR = {"key": N_("The access data are not set (or the server key changed): enter them again"),
           "auth": N_("The newsletter service refused the access data"),
           "network": N_("The newsletter service could not be reached"),
           "redirect": N_("The newsletter service answered with a redirect: check the address"),
           "answer": N_("The newsletter service sent an answer Kalmido does not understand: check the address"),
           "rate": N_("The newsletter service asks to slow down: the run stopped, the next one goes on"),
           "list": N_("The list of this segment no longer exists at the newsletter service"),
           "kind": N_("Unknown newsletter service"),
           "failed": N_("The run stopped because of an error")}


def nwl_err_text(stored):
    if not stored:
        return ""
    code = str(stored).partition(":")[0]
    if code in NWL_ERR:
        return tr(NWL_ERR[code])
    from ..calendars.subscriptions import cal_err_text
    return cal_err_text(stored)


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


def nwl_email_ok(e):
    return isinstance(e, str) and len(e) <= 254 and bool(_EMAIL.fullmatch(e))


# ---- the sealed access data --------------------------------------------------------------------------------------------
_KEYS = {}


def _key(ws):
    if not SECRET_KEY:
        return None
    k = _KEYS.get(ws)
    if k is None:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        k = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-newsletter-secret-v1|" + ws.encode()).derive(SECRET_KEY)
        _KEYS[ws] = k
    return k


def nwl_key_ok(ws):
    return _key(ws) is not None


def _ws_org(ws):
    return int(ws[1:]) if ws and ws[0] == "o" else None


def nwl_seal(ws, secret):
    key = _key(ws)
    return oc_enc_k(key, _ws_org(ws) or 0, f"nl_conns.secret.v1|{ws}", json.dumps(secret)) if key and secret else ""


def nwl_secret(r):
    """The plain access data {user?, token} of a connection row ({} when they cannot be opened)."""
    key = _key(r["ws"])
    if not key or not r["secret"]:
        return {}
    try:
        v = json.loads(oc_dec_k(key, _ws_org(r["ws"]) or 0, f"nl_conns.secret.v1|{r['ws']}", r["secret"]))
    except (OrgCryptError, ValueError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


def nwl_hint(secret):
    t = str((secret or {}).get("token") or "")
    return t[-4:] if len(t) >= 12 else ""


def nwl_conn(c, ws):
    return c.execute("SELECT * FROM nl_conns WHERE ws=?", (ws,)).fetchone()


def nwl_adapter_for(c, r, secret=None):
    from ..calendars.subscriptions import cal_allow
    return nwl_adapter(r["kind"], r["url"], secret if secret is not None else nwl_secret(r), cal_allow(c, "newsletter"))


# ---- the contacts of a workspace and the segments ----------------------------------------------------------------------
def nwl_books(c, ws):
    """The address books whose contacts belong to workspace ws: [{id, name}] (2.272.0 F, #3038 review M5: not the ones in the trash)."""
    oid = _ws_org(ws)
    if oid:
        rows = c.execute("SELECT id, name FROM books WHERE owner_org_id=? AND org_id=? AND deleted_at IS NULL ORDER BY lower(name), id", (oid, oid)).fetchall()
    else:
        rows = c.execute("SELECT id, name FROM books WHERE owner_id=? AND owner_org_id IS NULL AND org_id IS NULL AND deleted_at IS NULL ORDER BY lower(name), id",
                         (int(ws[1:]),)).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def _jl(v):
    try:
        x = json.loads(v or "[]")
    except ValueError:
        return []
    return x if isinstance(x, list) else []


def nwl_contacts(c, ws):
    """Every contact (no groups) of the workspace's books."""
    ids = [b["id"] for b in nwl_books(c, ws)]
    if not ids:
        return []
    return c.execute(f"SELECT id, book_id, fn, given, family, org, emails, groups, nl_status, nl_at, nl_source FROM contacts "
                     f"WHERE book_id IN ({','.join('?' * len(ids))}) AND kind!='group' AND deleted_at IS NULL", ids).fetchall()


def nwl_email(r):
    """The contact's first valid e-mail address (lower case) or ''."""
    for e in _jl(r["emails"]):
        v = str((e or {}).get("value") or "").strip().lower() if isinstance(e, dict) else ""
        if nwl_email_ok(v):
            return v
    return ""


def nwl_name(r):
    return (r["fn"] or " ".join(x for x in (r["given"], r["family"]) if x)).strip()[:200]


def nwl_facets(c, ws):
    """What a segment can choose from: the tags and companies of the workspace's contacts, its address books."""
    tags, orgs = set(), set()
    for r in nwl_contacts(c, ws):
        tags |= {str(g)[:100] for g in _jl(r["groups"]) if isinstance(g, str) and g.strip()}
        if (r["org"] or "").strip():
            orgs.add(r["org"].strip()[:200])
    return {"tags": sorted(tags, key=str.lower)[:500], "companies": sorted(orgs, key=str.lower)[:500], "books": nwl_books(c, ws)}


def nwl_clean_rule(c, ws, rule):
    """{tags: [..], companies: [..], books: [ids]} -- only the workspace's own books; None when invalid."""
    if not isinstance(rule, dict) or set(rule) - {"tags", "companies", "books"}:
        return None
    out = {}
    for k in ("tags", "companies"):
        v = rule.get(k) or []
        if not isinstance(v, list) or len(v) > 100 or not all(isinstance(x, str) and 0 < len(x.strip()) <= 200 for x in v):
            return None
        out[k] = sorted({x.strip() for x in v})
    b = rule.get("books") or []
    own = {x["id"] for x in nwl_books(c, ws)}
    if not isinstance(b, list) or not all(isinstance(x, int) and not isinstance(x, bool) and x in own for x in b):
        return None
    out["books"] = sorted(set(b))
    return out


def nwl_match(rule, r):
    """AND between the kinds, OR within one; an empty rule takes every contact of the workspace."""
    if rule.get("books") and r["book_id"] not in rule["books"]:
        return False
    if rule.get("tags"):
        mine = {str(g).lower() for g in _jl(r["groups"])}
        if not any(t.lower() in mine for t in rule["tags"]):
            return False
    if rule.get("companies") and (r["org"] or "").strip().lower() not in {x.lower() for x in rule["companies"]}:
        return False
    return True


def nwl_wanted(status, mode):
    return status == "yes" or (mode == "doi" and status == "pending")


def nwl_seg_counts(c, conn, seg_rule, rows=None):
    rows = nwl_contacts(c, conn["ws"]) if rows is None else rows
    n = {"match": 0, "email": 0, "send": 0, "blocked": 0, "unknown": 0}
    for r in rows:
        if not nwl_match(seg_rule, r):
            continue
        n["match"] += 1
        if not nwl_email(r):
            continue
        n["email"] += 1
        st = r["nl_status"] or ""
        if st in NWL_BLOCKED:
            n["blocked"] += 1
        elif nwl_wanted(st, conn["mode"]):
            n["send"] += 1
        elif not st:
            n["unknown"] += 1
    return n


# ---- consent -----------------------------------------------------------------------------------------------------------
# 2.152.0 D (#2170): the suppression list. An unsubscription / bounce is kept as the hash of the address per workspace, so
# deleting or merging the contact never makes the address mailable again; a re-import that says "yes" stays "unsub".
def nls_hash(email):
    import hashlib
    return hashlib.sha256((email or "").strip().lower().encode()).hexdigest()


def nls_ws(c, cid):
    """(ws, org_id, hash of the first address) of a contact, from its address book; (None, None, '') when unknown."""
    r = c.execute("SELECT c.emails, b.owner_org_id, b.org_id, b.owner_id FROM contacts c JOIN books b ON b.id=c.book_id WHERE c.id=?",
                  (cid,)).fetchone()
    if not r:
        return None, None, ""
    oid = r["owner_org_id"] if r["owner_org_id"] and r["owner_org_id"] == r["org_id"] else None
    return (f"o{oid}" if oid else f"u{r['owner_id']}"), oid, nls_hash(nwl_email(r))


def nls_blocked(c, ws):
    """The suppressed hashes of a workspace."""
    return {r["email_hash"] for r in c.execute("SELECT email_hash FROM nl_suppress WHERE ws=?", (ws,))}


def nls_add(c, ws, oid, h, kind):
    if not h or h == nls_hash(""):
        return
    c.execute("INSERT INTO nl_suppress(ws, org_id, email_hash, kind, at) VALUES(?,?,?,?,?) ON CONFLICT (ws, email_hash) DO NOTHING",
              (ws, oid, h, kind, _now()))


def nls_log(c, ws, oid, h, event, source=""):
    if h and h != nls_hash(""):
        c.execute("INSERT INTO nl_consent_log(ws, org_id, email_hash, event, source, at) VALUES(?,?,?,?,?,?)",
                  (ws, oid, h, event, (source or "")[:NWL_SOURCE_MAX], _now()))


def nls_keep(c, ids):
    """Before contacts are deleted or merged away: remember the blocked ones (older ones from before the list existed)."""
    for cid in ids:
        r = c.execute("SELECT nl_status FROM contacts WHERE id=?", (cid,)).fetchone()
        if r and (r["nl_status"] or "") in NWL_BLOCKED:
            ws, oid, h = nls_ws(c, cid)
            if ws:
                nls_add(c, ws, oid, h, r["nl_status"])


def nwl_set_status(c, cid, status, source, at=None):
    """Set the consent of a contact; returns the status really set (yes / pending on a suppressed address becomes unsub)."""
    ws, oid, h = nls_ws(c, cid)
    if ws and h and status in ("yes", "pending") and h in nls_blocked(c, ws):
        status, source = "unsub", "suppression list"
    c.execute("UPDATE contacts SET nl_status=?, nl_at=?, nl_source=? WHERE id=?", (status, at or _now(), (source or "")[:NWL_SOURCE_MAX], cid))
    if ws and h:
        if status in NWL_BLOCKED:
            nls_add(c, ws, oid, h, status)
        nls_log(c, ws, oid, h, {"yes": "consent", "pending": "pending", "": "reset"}.get(status, status), source)
    return status


def nwl_contact_json(r):
    """The consent part of a contact (contacts/model.py contact_dict)."""
    keys = r.keys()
    return {"status": r["nl_status"] if "nl_status" in keys else "", "at": r["nl_at"] if "nl_at" in keys else None,
            "source": r["nl_source"] if "nl_source" in keys else ""}


# ---- a run -------------------------------------------------------------------------------------------------------------
def nwl_busy(cid):
    return cid in _BUSY


def nwl_start(c, conn, kind="manual", by=None, wait=False):
    """Start a run of connection conn (a thread; wait: in this thread). None when one runs already."""
    nwl_stale(c, conn["id"])
    if c.execute("SELECT 1 FROM nl_runs WHERE conn_id=? AND state='busy'", (conn["id"],)).fetchone():
        return None  # another server process runs it
    with _LOCK:
        if conn["id"] in _BUSY:
            return None
        _BUSY.add(conn["id"])
    try:
        rid = c.execute("INSERT INTO nl_runs(conn_id, org_id, kind, by_id, state, started_at) VALUES(?,?,?,?,?,?) RETURNING id",
                        (conn["id"], conn["org_id"], kind, by, "busy", _now())).fetchone()[0]
        c.commit()
    except Exception:
        _BUSY.discard(conn["id"])
        raise
    if wait:
        _run(conn["id"], rid)
    else:
        threading.Thread(target=_run, args=(conn["id"], rid), daemon=True, name="newsletter").start()
    return rid


def _run(conn_id, rid):
    from ..accounts.session import GATE
    try:
        with GATE.bg():
            c = connect()
            try:
                with system_ctx(c):  # newsletter worker: one workspace's connection; the queries below stay inside its ws
                    _run_conn(c, conn_id, rid)
            finally:
                c.close()
    except Exception as e:  # noqa: BLE001 -- a run never takes the server down
        print("newsletter: run", type(e).__name__, flush=True)
    finally:
        _BUSY.discard(conn_id)


def _run_conn(c, conn_id, rid):
    conn = c.execute("SELECT * FROM nl_conns WHERE id=?", (conn_id,)).fetchone()
    if not conn:
        return
    counts = {"added": 0, "renamed": 0, "removed": 0, "unsub": 0, "bounce": 0, "confirmed": 0, "skipped": 0, "segments": 0}
    errors = []
    state = "ok"

    def fail(code, seg=None):
        if len(errors) < NWL_ERRORS_MAX:
            errors.append({"code": code, "segment": seg})

    try:
        secret = nwl_secret(conn)
        if not secret:
            raise NwlError("key")
        a = nwl_adapter_for(c, conn, secret)
        segs = c.execute("SELECT * FROM nl_segments WHERE conn_id=? ORDER BY id", (conn_id,)).fetchall()
        rows = nwl_contacts(c, conn["ws"])
        by_mail = {}
        for r in rows:
            e = nwl_email(r)
            if e:
                by_mail.setdefault(e, []).append(r)
        cur_st = {r["id"]: r["nl_status"] or "" for r in rows}
        remote = {}
        # 1. service -> Kalmido: unsubscriptions, bounces and confirmed opt-ins come back to every contact with the address
        for s in segs:
            if not s["remote_id"]:
                continue
            try:
                remote[s["id"]] = a.members(s["remote_id"])
            except NwlError as e:
                fail("list" if e.code == "http" and e.detail == "404" else e.stored(), s["id"])
                continue
            for email, m in remote[s["id"]].items():
                if m["state"] in NWL_BLOCKED:  # 2.152.0 D (#2170): kept even when no contact carries the address any more
                    nls_add(c, conn["ws"], conn["org_id"], nls_hash(email), m["state"])
                for r in by_mail.get(email, []):
                    cur = cur_st[r["id"]]
                    new = None
                    if m["state"] in NWL_BLOCKED and cur != m["state"] and not (cur == "bounce" and m["state"] == "unsub"):
                        new = m["state"]
                    elif m["state"] == "active" and cur == "pending":
                        new = "yes"
                        counts["confirmed"] += 1
                    if new:
                        if new in NWL_BLOCKED:
                            counts[new] += 1
                        nwl_set_status(c, r["id"], new, "service")
                        cur_st[r["id"]] = new
        c.commit()
        status_of = {}  # an address is blocked when any of its contacts is (unsubscribed once = never again)
        sup = nls_blocked(c, conn["ws"])  # 2.152.0 D (#2170): also when the contact that unsubscribed is gone
        for email, rs in by_mail.items():
            sts = {cur_st[x["id"]] for x in rs}
            if nls_hash(email) in sup:
                sts.add("unsub")
            status_of[email] = (next((b for b in NWL_BLOCKED if b in sts), None) or ("yes" if "yes" in sts else "pending" if "pending" in sts
                                else ""), rs)
        # 2. Kalmido -> service
        for s in segs:
            if not s["remote_id"] or s["id"] not in remote:
                continue
            counts["segments"] += 1
            try:
                rule = json.loads(s["rule"] or "{}")
            except ValueError:
                rule = {}
            mine = {m["email"]: m for m in c.execute("SELECT email, remote_ref, state FROM nl_members WHERE seg_id=?", (s["id"],))}
            want = {}
            for email, (st, rs) in status_of.items():
                if st in NWL_BLOCKED or not nwl_wanted(st, conn["mode"]):
                    continue
                hit = next((x for x in rs if nwl_match(rule, x)), None)
                if hit:
                    want[email] = (nwl_name(hit), st == "yes")
            rem = remote[s["id"]]
            for email, (name, confirmed) in sorted(want.items()):
                try:
                    m = rem.get(email)
                    if m:
                        if m["state"] in NWL_BLOCKED:
                            counts["skipped"] += 1
                            continue
                        if email not in mine:
                            continue  # somebody else put it on the list: it stays theirs (not even renamed)
                        if name and m.get("name") != name:
                            a.rename(s["remote_id"], m["ref"], email, name)
                            counts["renamed"] += 1
                        ref = m["ref"]
                        st_r = m["state"]
                    else:
                        st_r, ref = a.add(s["remote_id"], email, name, confirmed)
                        if st_r in NWL_BLOCKED:  # the service blocks the address: back to the contacts, never again
                            for r in status_of[email][1]:
                                nwl_set_status(c, r["id"], st_r, "service")
                                cur_st[r["id"]] = st_r
                            counts[st_r] += 1
                            continue
                        counts["added"] += 1
                    c.execute("INSERT INTO nl_members(seg_id, org_id, email, remote_ref, state, synced_at) VALUES(?,?,?,?,?,?) "
                              "ON CONFLICT (seg_id, email) DO UPDATE SET remote_ref=excluded.remote_ref, state=excluded.state, "
                              "synced_at=excluded.synced_at", (s["id"], conn["org_id"], email, ref or "", st_r, _now()))
                except NwlError as e:
                    fail(e.stored(), s["id"])
                    if e.code in ("auth", "network", "rate"):
                        raise
            for email, m in mine.items():
                if email in want:
                    continue
                try:
                    # blocked here but active at the service = the person subscribed again through the service's own form:
                    # that stays theirs (Kalmido only lets go of it)
                    if email in rem and rem[email]["state"] not in NWL_BLOCKED and \
                            (status_of.get(email) or ("",))[0] not in NWL_BLOCKED:
                        a.remove(s["remote_id"], m["remote_ref"] or rem[email]["ref"], email)
                        counts["removed"] += 1
                    c.execute("DELETE FROM nl_members WHERE seg_id=? AND email=?", (s["id"], email))
                except NwlError as e:
                    fail(e.stored(), s["id"])
                    if e.code in ("auth", "network", "rate"):
                        raise
            c.commit()
    except NwlError as e:
        fail(e.stored())
        state = "failed"
    except Exception as e:  # noqa: BLE001
        print("newsletter: run", type(e).__name__, flush=True)
        c.rollback()
        fail("failed")
        state = "failed"
    if state == "ok" and errors:
        state = "partial"
    ts = _now()
    c.execute("UPDATE nl_runs SET state=?, ended_at=?, counts=?, errors=? WHERE id=?", (state, ts, json.dumps(counts), json.dumps(errors), rid))
    c.execute("UPDATE nl_conns SET synced_at=?, error=? WHERE id=?", (ts, errors[0]["code"] if state == "failed" else "", conn_id))
    old = c.execute("SELECT id FROM nl_runs WHERE conn_id=? ORDER BY id DESC OFFSET ?", (conn_id, NWL_RUNS_KEEP)).fetchall()
    for (oid,) in old:
        c.execute("DELETE FROM nl_runs WHERE id=?", (oid,))
    c.commit()


NWL_STALE_MIN = 30


def nwl_stale(c, conn_id):
    """A run cut off by a restart (busy, not running in this process, older than NWL_STALE_MIN) counts as failed."""
    if nwl_busy(conn_id):
        return
    old = iso(now_utc() - timedelta(minutes=NWL_STALE_MIN))
    if c.execute("UPDATE nl_runs SET state='failed', ended_at=?, errors=? WHERE conn_id=? AND state='busy' AND started_at<?",
                 (_now(), json.dumps([{"code": "failed", "segment": None}]), conn_id, old)).rowcount:
        c.commit()


def nwl_run_json(r):
    try:
        counts, errors = json.loads(r["counts"] or "{}"), json.loads(r["errors"] or "[]")
    except ValueError:
        counts, errors = {}, []
    return {"id": r["id"], "kind": r["kind"], "state": r["state"], "started_at": r["started_at"], "ended_at": r["ended_at"],
            "counts": counts, "errors": [dict(x, text=nwl_err_text(x.get("code"))) for x in errors if isinstance(x, dict)]}


# ---- planned runs (notify/push.py watchdog_tick) ------------------------------------------------------------------------
def nwl_tick(c):
    """Every connection with "auto" whose last run is a day old gets a run (each in its own thread)."""
    due = now_utc() - timedelta(hours=NWL_EVERY_H)
    for r in c.execute("SELECT * FROM nl_conns WHERE auto=1").fetchall():
        last = parse_iso(r["synced_at"]) if r["synced_at"] else None
        if (last is None or last <= due) and not nwl_busy(r["id"]):
            if r["owner_id"] and c.execute("SELECT disabled FROM users WHERE id=?", (r["owner_id"],)).fetchone()[0]:
                continue
            nwl_start(c, r, kind="auto")


__all__ = ["NWL_KINDS", "NwlError"]
