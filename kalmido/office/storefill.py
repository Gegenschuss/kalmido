"""2.357.0 (#3221, GoBD): catch-up of the stored files of finalised office documents (all kinds but quotations) from before
finalising stored them (older versions): such a document was rendered anew from its snapshot at every download, so every later change of the
print code changed it. Once after the update, in the watchdog: at most FILL_N documents every FILL_EVERY watchdog
intervals, oldest first, the position in the global settings (a restart goes on where it stopped), "done" at the end --
then it never runs again. A document with its file but without a noted SHA-256 gets the hash of that file (never
rendered again); one without a file is rendered once from its snapshot and stored as at finalising (pdfweb.epdf_store:
PDF/A-3 + XML of an invoice, sealed, both hashes, log "store"). Each office area runs as one of its admins (the owner of a
personal office), as the invoice series do. A document that fails is skipped, the run goes on (review M2: log "store_skip"
with the reason on the document, the skipped ids with their reason in the setting, a server log line per portion).
KALMIDO_OFFICE_STORE_FILL=off switches it off."""
import hashlib
import json
import time

from flask import g

from ..core.config import WATCHDOG_INTERVAL, app
from ..core.db import gset, gsetting
from ..core.env import env_bool
from ..core.pg import system_ctx, write_lock
from .docs import doc_row
from .fixedimport import fci_people
from .ledger import ofx_locked, ofx_log
from .pdfweb import EPDF_KINDS_XML, _stored, epdf_store, epdf_stored

FILL = env_bool("KALMIDO_OFFICE_STORE_FILL", True)
FILL_N = 10            # documents per portion
FILL_EVERY = 1         # watchdog intervals between two portions
FILL_SKIP_MAX = 500   # skipped documents noted in the setting
FILL_KEY = "office_store_fill"  # global settings: {"after": highest office_docs id handled so far} or {"done": 1}
_Q = {"at": 0.0}


def osf_todo(c, after, n):
    """[(id, org_id)] of finalised documents without a noted PDF hash, id above after, oldest first (every organisation).
    Quotations are left out: finalising never stores them (ledger.ofx_finalize), they stay rendered from their snapshot."""
    with system_ctx(c):
        return [(r[0], r[1]) for r in c.execute(
            "SELECT id, org_id FROM office_docs WHERE id>? AND kind<>'offer' AND COALESCE(locked_at, '')<>'' AND COALESCE(pdf_sha256, '')='' "
            "ORDER BY id LIMIT ?", (after, n)).fetchall()]


def osf_one(c, oid, did):
    """Store (or hash) document did of area oid in the current person's context; commits. Returns "hash", "store" or ""."""
    write_lock(c, f"office_doc_{int(did)}")
    r = doc_row(c, oid, did)
    if r is None or not ofx_locked(r) or (r["pdf_sha256"] if "pdf_sha256" in r.keys() else ""):
        c.rollback()
        return ""
    if _stored(oid, r, "pdf"):  # the file is there (stored before the hashes were noted): note its hash, never render again
        shas = {}
        for ext in ("pdf",) + (("xml",) if r["kind"] in EPDF_KINDS_XML else ()):
            data = epdf_stored(c, oid, r, ext, commit=False)
            if data is not None:
                shas[ext] = hashlib.sha256(data).hexdigest()
        c.execute("UPDATE office_docs SET pdf_sha256=?, xml_sha256=? WHERE id=? AND org_id=?", (shas.get("pdf", ""), shas.get("xml", ""), did, oid))
        ofx_log(c, oid, "store_hash", doc_id=did, detail={"pdf_sha256": shas.get("pdf", ""), "xml_sha256": shas.get("xml", ""), "catch_up": 1})
        c.commit()
        return "hash"
    epdf_store(c, oid, did, {"catch_up": 1})  # rendered once from its snapshot, then served as stored for ever
    c.commit()
    return "store"


def osf_area(c, oid, dids):
    """The documents dids of area oid as one of its admins (fixedimport.fci_people), in a request context of their own.
    Returns {doc id: reason} of the documents skipped (no admin, an error)."""
    with system_ctx(c):
        people = fci_people(c, oid)
    c.commit()
    if not people:
        return {did: "no admin" for did in dids}
    prev = c.ctx
    skipped = {}
    try:
        with app.test_request_context("/api/office/store-fill"):
            g.user = c.execute("SELECT * FROM users WHERE id=?", (people[0]["id"],)).fetchone()
            for did in dids:
                try:
                    osf_one(c, oid, did)
                except Exception as e:  # noqa: BLE001 -- a broken snapshot, an XRechnung without buyer reference: skip it
                    c.rollback()
                    skipped[did] = f"{type(e).__name__}: {e}"[:200]
                    try:  # the reason on the document (office log), never a stop of the run
                        ofx_log(c, oid, "store_skip", doc_id=did, detail={"reason": skipped[did], "catch_up": 1})
                        c.commit()
                    except Exception:  # noqa: BLE001
                        c.rollback()
    finally:
        c.rollback()  # whatever is left open; then the watchdog's own context again (the hook followed g.user)
        c.set_ctx(*prev)
    return skipped


def osf_tick(c, force=False):
    """One portion of the catch-up (watchdog). Returns the number of documents looked at; 0 when it is not time yet or the
    catch-up is done."""
    if not FILL or (not force and time.monotonic() - _Q["at"] < FILL_EVERY * WATCHDOG_INTERVAL):
        return 0
    _Q["at"] = time.monotonic()
    try:
        st = json.loads(gsetting(c, FILL_KEY) or "{}")
    except ValueError:
        st = {}
    st = st if isinstance(st, dict) else {}
    if st.get("done"):
        return 0
    rows = osf_todo(c, int(st.get("after") or 0), FILL_N)
    skipped = st.get("skipped") if isinstance(st.get("skipped"), dict) else {}
    if not rows:
        gset(c, FILL_KEY, json.dumps({"done": 1, "skipped": skipped}))
        c.commit()
        if skipped:
            print(f"office: store catch-up done, {len(skipped)} document(s) skipped (office log 'store_skip'): {sorted(skipped)[:20]}", flush=True)
        return 0
    by_area = {}
    for did, oid in rows:
        by_area.setdefault(oid, []).append(did)
    for oid, dids in by_area.items():
        for did, why in osf_area(c, oid, dids).items():
            if len(skipped) < FILL_SKIP_MAX:  # the office log names every one; the setting keeps the first ones
                skipped[str(did)] = why
    gset(c, FILL_KEY, json.dumps({"after": rows[-1][0], "skipped": skipped}))
    c.commit()
    print(f"office: store catch-up: {len(rows)} document(s) up to id {rows[-1][0]}, {len(skipped)} skipped so far", flush=True)
    return len(rows)
