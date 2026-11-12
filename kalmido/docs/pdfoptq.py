"""2.892.0 (#4873, includes #4806): "Optimise PDF" -- the routes, the queue step and the stored state (the tools: docs/pdfopt.py).

A scanned PDF of a document (recognised by text recognition, or optimised before) becomes smaller and searchable: the
result is a NEW VERSION of its file through the file store's version path (files/store.py fs_new_version: the write right,
locked folders / months, the upload check, the quota, the seal of its space). The original stays as the older version
(the tab History restores it; GET .../pdfopt names it "orig", the view offers it as "Download original"). Not smaller ->
no new version, the file stays as it is (state "same", both sizes shown). After a new version the document is recognised
again (its text now comes from the text layer).

Started by: the action in the document view (POST /api/docs/<id>/pdfopt: first {check: 1} -- the pages are measured in the
queue and the dialog lists the blank pages that would go -- then the run with the level and the switch), the one selection
bar of the file store (POST /api/docs/pdfopt with ids: no list before, the result per document), and the setting "Optimise
new scans automatically" of a workspace (doc_cfg pdf_opt_auto, docs/store.py cfg_get): after the FIRST recognition of a
scanned PDF, level auto, never removing pages (no person saw a list), NEVER for the office's receipts / office documents
(GoBD: the image must match; there only the button, with the hint that the original stays).

Rights: the routes only for people (agents: 403), the document through the file store's access (docs/web.py _doc ->
need_node, AccessCtx: write for the run); the queue checks the write right of the person who asked once more right before
it writes (fs_role), the version path checks the rest. The runs go through their own thread next to the documents queue
(docs/ingest.py po_run_once, 2.1069.0 #5412: a run of up to PO_DOC_S never holds up the recognition of new documents; both
share the tools' slot per page, ocr._SEM), one at a time, a workspace not served lately first, with the limits of
docs/pdfopt.py and at most PO_WAIT_MAX waiting per person and PO_WS_MAX per workspace (429).

doc_meta.pdf_opt (fragment 4873_a): JSON without any content of the document, only numbers and words of the state:
  queued / running ({"q": 1, ...} first: the queue's partial index): state check | scan (measuring) | wait | run (optimising)
  ready (measured: pages), done (from, to, before, after, drop, kinds), same (before, after), failed (error), skipped (error)
  and always: mode, blank, auto, by (the person), v (the version worked on), at, orig ({from, to}: the version before the
  first optimisation and the optimised one, kept over later checks)."""
import calendar
import json
import time

from contextlib import nullcontext

from flask import has_app_context, jsonify

from ..core.config import app
from ..core.db import OperationalError, body, bump, db, err, now_iso
from ..core.i18n import N_, lang as _lang, tr
from ..core.access import Denied, acx_of, live_sql
from ..core.pg import write_lock
from ..accounts.session import me
from ..files.fslock import fsl_chain_ids, fsl_hold  # 2.970 (#5653)
from ..files.store import fs_chain, fs_deleted, fs_log_add, fs_new_version, fs_read, fs_role
from ..office.periodlock import pl_receipt_need_open
from . import store as S
from . import pdfopt as P
from .area import ar_guess, ar_is_receipt
from .ingest import doc_on_done, docs_kick
from .ocr import ocr_langs
from .web import _doc

# the partial index's predicate (pdf_opt <> '', fragment 4873_a) first, so the planner takes it; then the queue mark (no LIKE,
# pg_dialect). The index itself calls no function: a backup refuses index statements with calls outside _CALL_HEADS.
PO_Q = "d.pdf_opt <> '' AND left(d.pdf_opt, 6) = '{\"q\":1'"
# review F3: an automatic run waits while the general input still sorts its document -- left out in SQL (no LIMIT before it);
# _dump writes "auto" right after "q", so the start of the text tells it
PO_PICK = "NOT (left(d.pdf_opt, 15) = '{\"q\":1,\"auto\":1' AND d.area_sort IN ('pending', 'sorting'))"
PO_RUN = ("check", "scan", "wait", "run")
PO_WAIT_MAX = P.OCR._env_int("KALMIDO_PDFOPT_WAIT", 200, 1, 100000)  # review F2: runs one person may have waiting at most
# 2.1069.0 (#5412, review 2.781 F2): runs one workspace may have waiting at most (the person's limit above stays)
PO_WS_MAX = P.OCR._env_int("KALMIDO_PDFOPT_WS_WAIT", 200, 1, 100000)
_PQ = {"recent": [], "clean": True}  # review F2: the workspaces served last (round robin as docs/ingest.py DOCS_NEXT)
PO_STALE = P.PO_DOC_S + 600          # s after which a run cut off (a restart) is taken up again
PO_TRIES = 2
PO_BULK = 200                        # documents of one selection at most
PO_ERRORS = {
    "no_ocr": N_("Text recognition is not available on this server."),
    "unreadable": N_("The file is damaged or cannot be read."),
    "too_many_pages": N_("Too many pages to optimise here."),
    "too_big": N_("The file is too big to optimise here."),
    "too_complex": N_("The file took too long or too much memory to read."),
    "failed": N_("Optimising failed."),
    "changed": N_("The file changed meanwhile. Please start again."),
    "locked": N_("The file cannot get a new version (locked folder or closed month)."),
    "denied": N_("You may no longer change this file."),
    "quota": N_("Your storage is full."),
    "office": N_("Receipts of the office are never optimised automatically."),
    "gone": N_("The document is no longer there."),
}
PO_FULL = N_("Too many documents wait for optimising. Please try again later.")


def _now():
    return now_iso()


def _person(c):
    if acx_of(c, me()).role == "agent":  # people only: an agent changes no file this way (review F12: nor reads its state)
        raise Denied(403)


def po_get(m):
    try:
        v = json.loads((m["pdf_opt"] if "pdf_opt" in m.keys() else "") or "{}")
    except (ValueError, TypeError):
        v = {}
    return v if isinstance(v, dict) else {}


def _dump(v):
    """"q" first (the queue's predicate looks at the start of the text), "auto" right after it (PO_PICK), then the rest."""
    head = {"q": 1} if v.get("state") in PO_RUN else {}
    rest = {k: x for k, x in v.items() if k not in ("q", "auto")}
    return json.dumps({**head, "auto": 1 if v.get("auto") else 0, **rest}, separators=(",", ":"))


def po_put(c, nid, v, old=None):
    """Write the state; old = the text read before (compare and set: False when somebody else changed it meanwhile)."""
    if old is None:
        c.execute("UPDATE doc_meta SET pdf_opt=? WHERE node_id=?", (_dump(v), nid))
        return True
    return c.execute("UPDATE doc_meta SET pdf_opt=? WHERE node_id=? AND pdf_opt=?", (_dump(v), nid, old)).rowcount == 1


def po_office(c, m, guess=False):
    """An office document or a receipt (GoBD: never changed without a person, docs/area.py). guess (review F1, the automatic
    run): also a document the recognition takes for an invoice / receipt (ar_guess) that is not sorted into the office yet."""
    return m["area"] == "office" or ar_is_receipt(c, m["node_id"]) or (guess and ar_guess(c, m["node_id"]) == "office")


def po_orig(v, n):
    """{from, to} of the original before the first optimisation -- only while the optimised version is the current one (review
    F7: a restored or newer version makes it no "original" any more)."""
    o = v.get("orig") if isinstance(v.get("orig"), dict) else {}
    return o if o.get("from") and o.get("to") and int(o["to"]) == int(n["cur_version"] or 0) else {}


def _is_pdf(n):
    return (n["mime"] or "").lower() == "application/pdf" or str(n["name"] or "").lower().endswith(".pdf")


def po_why_not(c, m, n):
    """None when the document may be optimised, else the reason (translated)."""
    if n["kind"] != "file" or not _is_pdf(n):
        return tr("Only PDF files can be optimised.")
    orig = po_orig(po_get(m), n)
    if m["method"] != "ocr" and not orig:
        return tr("Only scanned PDFs can be optimised: this PDF has its own text.")
    if m["state"] not in ("done", "failed") and not orig:
        return tr("Please wait until the recognition is finished.")
    if not P.po_available():
        return tr(PO_ERRORS["no_ocr"])
    if int(m["pages"] or 0) > P.PO_PAGES:
        return tr("Too many pages to optimise here (at most {0}).", P.PO_PAGES)
    if int(n["size"] or 0) > P.PO_MAX:  # review F8: before anything is read
        return tr(PO_ERRORS["too_big"])
    return None


def po_view(c, m, n, full=True):
    """What the document view / the dialog shows: {can, why, office, state, mode, blank, auto, before, after, from, to, drop,
    kinds, pages (the measured ones: [{k, b}]), error, error_text, orig (the version to download as the original, when the
    optimised one is the current)}."""
    v = po_get(m)
    why = po_why_not(c, m, n) if n["kind"] == "file" else tr("Only PDF files can be optimised.")
    o = po_orig(v, n)
    out = {"can": why is None, "why": why or "", "office": po_office(c, m), "state": v.get("state") or "",
           "orig": o.get("from") or None}
    if not full:
        return out
    out.update({k: v.get(k) for k in ("mode", "blank", "auto", "before", "after", "drop", "kinds", "from", "to")})
    out["current"] = n["cur_version"]
    # the measure / result belongs to the current version (a new version made by it: its number is "to")
    out["fresh"] = int(v.get("to" if v.get("state") == "done" else "v") or 0) == int(n["cur_version"] or 0)
    if isinstance(v.get("pages"), list):
        out["pages"] = [{"k": p.get("k"), "b": p.get("b")} for p in v["pages"]]
    e = v.get("error") or ""
    out["error"], out["error_text"] = e, tr(PO_ERRORS[e]) if e in PO_ERRORS else ""
    return out


def po_brief(c, m, n):
    """docs/web.py doc_json (the full view): only what the head's actions need."""
    if n["kind"] != "file" or not _is_pdf(n):
        return None
    try:
        return po_view(c, m, n, full=False)
    except Exception:  # noqa: BLE001 -- a broken state never breaks the document view
        return None


def _queue(c, nid, m, n, uid, mode, blank, check, auto=False):
    """Mark the document for the queue (the caller checked rights and po_why_not, holds no lock)."""
    write_lock(c, f"docs_pdfopt_{int(nid)}")
    m = S.meta_row(c, nid)
    cur = po_get(m)
    if cur.get("state") in PO_RUN:
        return False  # already on its way
    ver = int(n["cur_version"] or 0)
    keep = {k: cur[k] for k in ("orig",) if k in cur}
    v = {"state": "check" if check else "wait", "mode": mode, "blank": 1 if blank else 0, "auto": 1 if auto else 0, "by": uid,
         "v": ver, "at": _now(), "tries": 0, **keep}
    if not check and cur.get("state") == "ready" and int(cur.get("v") or 0) == ver and isinstance(cur.get("pages"), list):
        v["pages"] = cur["pages"]  # the list the person saw: the same pages go
    elif not check:
        v["blank"] = 0  # review F5: pages only go after a person saw the list of exactly this version (the check first)
    po_put(c, nid, v)
    return True


def po_waiting(c, uid):
    """Review F2: the runs person uid has waiting or running (all workspaces)."""
    rows = c.execute(f"SELECT d.pdf_opt FROM doc_meta d WHERE {PO_Q}").fetchall()
    return sum(1 for r in rows if po_get(r).get("by") == uid)


def po_waiting_ws(c, ws):
    """2.1069.0 (#5412): the runs waiting or running in workspace ws (doc_meta.ws), whoever asked."""
    return c.execute(f"SELECT COUNT(*) FROM doc_meta d WHERE {PO_Q} AND d.ws=?", (ws,)).fetchone()[0]


def po_room(c, uid, ws):
    """2.1069.0 (#5412): how many more runs person uid may queue in workspace ws -- the smaller of the person's room
    (PO_WAIT_MAX) and the workspace's (PO_WS_MAX); 0 = the queue is full for them (429)."""
    return max(0, min(PO_WAIT_MAX - po_waiting(c, uid), PO_WS_MAX - po_waiting_ws(c, ws)))


def _args(d, many=False):
    mode = str(d.get("mode") or "auto")
    if mode not in P.PO_MODES:
        raise ValueError("mode")
    blank = d.get("blank")
    # decided 06.11.2026: "Remove blank pages" is on in auto; review F5: off by default for a selection (no list seen)
    blank = (mode == "auto" and not many) if blank is None else bool(blank)
    return mode, blank


@app.get("/api/docs/<int:nid>/pdfopt")
def docs_pdfopt_get(nid):
    """The state of "Optimise PDF" of a document (also for readers: the original to download; people only, review F12)."""
    c = db()
    _person(c)
    m, n = _doc(c, nid)
    return jsonify(po_view(c, m, n))


@app.post("/api/docs/<int:nid>/pdfopt")
def docs_pdfopt(nid):
    """{mode: auto | bw | gray, blank?: bool (default: on in auto), check?: 1 (only measure the pages)} -> 202 + the state.
    The queue does the work; GET .../pdfopt follows it."""
    c = db()
    _person(c)
    m, n = _doc(c, nid, write=True)
    d = body()
    try:
        mode, blank = _args(d)
    except ValueError:
        return err(tr("Invalid value: {0}", "mode"))
    why = po_why_not(c, m, n)
    if why:
        return err(why, 409)
    pl_receipt_need_open(c, nid)  # a receipt of a closed month gets no new version (409, said at once)
    write_lock(c, f"docs_pdfopt_ws_{m['ws']}")  # 2.1069.0 (#5412, review): counted and queued under the workspace's lock
    if po_room(c, me(), m["ws"]) <= 0:  # review F2; 2.1069.0 (#5412): the workspace's limit too
        return err(tr(PO_FULL), 429)
    if not _queue(c, nid, m, n, me(), mode, blank, bool(d.get("check"))):
        c.rollback()
        return err(tr("Optimising runs already."), 409)
    bump(c)
    c.commit()
    docs_kick()
    m, n = _doc(c, nid)
    return jsonify(po_view(c, m, n)), 202


@app.post("/api/docs/pdfopt")
def docs_pdfopt_many():
    """{ids: [...], mode, blank?} -- the chosen documents (the selection bar): each one the person may change and that is a
    scanned PDF is queued, the others are counted as skipped. -> 202 {queued: [ids], skipped: n}."""
    c = db()
    _person(c)
    d = body()
    try:
        mode, blank = _args(d, many=True)
        ids = [int(x) for x in (d.get("ids") or [])][:PO_BULK]
    except (ValueError, TypeError):
        return err(tr("Invalid value: {0}", "ids"))
    uid, done, skip = me(), [], 0
    room = PO_WAIT_MAX - po_waiting(c, uid)  # review F2: past the limit the rest is skipped
    if room <= 0:
        return err(tr(PO_FULL), 429)
    ws_room = {}  # 2.1069.0 (#5412): the room left per workspace (PO_WS_MAX), counted once per workspace of the selection
    for nid in dict.fromkeys(ids):
        if len(done) >= room:
            skip += 1
            continue
        try:
            m, n = _doc(c, nid, write=True)
            if po_why_not(c, m, n):
                skip += 1
                continue
            if m["ws"] not in ws_room:
                write_lock(c, f"docs_pdfopt_ws_{m['ws']}")  # 2.1069.0 (#5412, review): held to the commit
                ws_room[m["ws"]] = PO_WS_MAX - po_waiting_ws(c, m["ws"])
            if ws_room[m["ws"]] <= 0:  # 2.1069.0 (#5412): this workspace's queue is full, the others' go on
                skip += 1
                continue
            pl_receipt_need_open(c, nid)
            if _queue(c, nid, m, n, uid, mode, blank, False):
                done.append(nid)
                ws_room[m["ws"]] -= 1
            else:
                skip += 1
        except Denied:
            skip += 1
    if not done and ws_room and all(v <= 0 for v in ws_room.values()):
        c.rollback()
        return err(tr(PO_FULL), 429)  # 2.1069.0 (#5412): nothing queued only because every workspace's queue is full
    if done:
        bump(c)
    c.commit()
    if done:
        docs_kick()
    return jsonify(queued=done, skipped=skip), 202


# ---- the setting "Optimise new scans automatically": after the FIRST recognition of a scanned PDF ---------------------
def po_on_done(c, nid, first):
    if not first:
        return
    m = S.meta_row(c, nid)
    if not m or m["method"] != "ocr" or m["state"] != "done" or po_get(m):
        return
    if not S.cfg_get(c, m["ws"]).get("pdf_opt_auto"):
        return
    n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not n or n["kind"] != "file" or not _is_pdf(n) or int(m["pages"] or 0) > P.PO_PAGES or int(n["size"] or 0) > P.PO_MAX:
        return
    if po_office(c, m, guess=True):  # review F1: nor what looks like an invoice / receipt
        return
    if not n["owner_id"] or acx_of(c, n["owner_id"]).role == "agent":  # review F5: an agent's file is never optimised this way
        return
    if po_waiting(c, n["owner_id"]) >= PO_WAIT_MAX:  # review F2: the automatic runs count as well
        return  # 2.1069.0 (#5412, review): not the workspace's limit - one member's full selection never stops the others' new scans
    po_put(c, nid, {"state": "wait", "mode": "auto", "blank": 0, "auto": 1, "by": n["owner_id"], "v": int(n["cur_version"] or 0),
                    "at": _now(), "tries": 0})


if po_on_done not in doc_on_done:
    doc_on_done.append(po_on_done)


# ---- the queue step (2.1069.0 #5412: its own thread, docs/ingest.py po_run_once -- the recognition never waits for a run) ---------------------------------------------
def _age(v):
    try:
        return time.time() - calendar.timegm(time.strptime(str(v.get("at") or "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return 1e9


def _fail(c, nid, v, key):
    po_put(c, nid, {**{k: x for k, x in v.items() if k not in ("q", "tries")}, "state": "skipped" if key == "office" else "failed",
                    "error": key, "at": _now()})
    bump(c)
    c.commit()


def po_take_up(c):
    """Review F4: the first step of a process that is the only one with a docs queue (docs/ingest.py docs_take_up): a measure
    or a run cut off by the restart goes back to check / wait at once (after PO_TRIES cut-offs: failed)."""
    rows = c.execute(f"SELECT d.node_id, d.pdf_opt FROM doc_meta d WHERE {PO_Q}").fetchall()
    for r in rows:
        v = po_get(r)
        st = v.get("state")
        if st in ("scan", "run"):
            t = int(v.get("tries") or 0) + 1
            if t >= PO_TRIES:
                po_put(c, r[0], {**{k: x for k, x in v.items() if k not in ("q", "tries")}, "state": "failed", "error": "failed", "at": _now()})
            else:
                po_put(c, r[0], {**v, "state": "check" if st == "scan" else "wait", "tries": t, "at": _now()})


def _pick(rows):
    """Review F2: the next waiting row -- a workspace not served lately first (round robin as DOCS_NEXT), then the oldest."""
    rec = _PQ["recent"]
    return min(rows, key=lambda r: (rec.index(r["ws"]) if r["ws"] in rec else -1, str(po_get(r).get("at") or ""), r[0]), default=None)


def po_queued(c):
    """One step: a waiting measure / run. Returns 1 when it did something. The caller runs it in system_ctx (the queue works
    for every workspace; rights: the person who asked, checked here)."""
    if _PQ["clean"]:  # review F9: temp folders of runs a killed process left behind (older than a run may take)
        _PQ["clean"] = False
        P.po_tmp_clean()
    # review F3: the rows an automatic run must leave for now are left out in SQL, no LIMIT before that
    rows = c.execute(f"SELECT d.node_id, d.pdf_opt, d.ws FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE {PO_Q} "
                     f"AND {PO_PICK} AND {live_sql('n')}").fetchall()
    waiting = []
    for r in rows:
        v = po_get(r)
        st = v.get("state")
        if st in ("scan", "run"):  # running: only a run cut off long ago (a restart) is taken up again
            if _age(v) > PO_STALE:
                t = int(v.get("tries") or 0) + 1
                if t >= PO_TRIES:
                    _fail(c, r[0], v, "failed")
                else:
                    po_put(c, r[0], {**v, "state": "check" if st == "scan" else "wait", "tries": t}, r[1])
                    c.commit()
                return 1
            continue
        waiting.append(r)
    r = _pick(waiting)
    if r is None:
        return 0
    # 2.1069.0 (#5412, review F2/F5): a new measure / run starts only while no document waits for its recognition -- the
    # recognition never waits for a run (own thread), and a run does not fight a backlog for the tools' slot (busy, the
    # run's clock) nor overwrite the recognition of a version it is about to replace
    if c.execute("SELECT 1 FROM doc_meta WHERE state IN ('wait', 'run') LIMIT 1").fetchone():
        return 0
    nid, old, v = r[0], r[1], po_get(r)
    _PQ["recent"] = [w for w in _PQ["recent"] if w != r["ws"]][-63:] + [r["ws"]]
    run = v["state"] == "wait"
    v = {**v, "state": "run" if run else "scan", "at": _now()}
    if not po_put(c, nid, v, old):
        c.commit()
        return 1
    c.commit()
    try:
        if _work(c, nid, v, run) == "busy":
            return 0  # another heavy reader holds the tools (it waited OCR_PAGE_S * 2 already): the next tick
    except OperationalError:
        raise
    except Exception as e:  # noqa: BLE001 -- the queue never dies; this document says it failed
        c.rollback()
        print("docs: pdf optimise", nid, type(e).__name__, flush=True)  # review F13: the kind only, no text of the error
        m = S.meta_row(c, nid)
        if m and po_get(m).get("state") in ("scan", "run"):
            _fail(c, nid, po_get(m), "failed")
    return 1


def _work(c, nid, v, run):
    m = S.meta_row(c, nid)
    n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not m or not n or n["deleted_at"] or n["kind"] != "file" or fs_deleted(fs_chain(c, nid)):  # 2.892.0 (review): + a folder above in the trash
        return _fail(c, nid, v, "gone") if m else None
    uid = v.get("by")
    if not uid or fs_role(c, nid, uid) not in ("owner", "edit"):
        return _fail(c, nid, v, "denied")
    if v.get("auto") and po_office(c, m, guess=True):
        return _fail(c, nid, v, "office")
    if int(n["size"] or 0) > P.PO_MAX:  # review F8: not read at all
        return _fail(c, nid, v, "too_big")
    ver = int(n["cur_version"] or 0)
    data = fs_read(c, nid)
    try:
        langs = ocr_langs(_lang(c, uid=uid), base=S.cfg_get(c, m["ws"])["ocr_langs"] or None)[0]
    except Exception:  # noqa: BLE001 -- the language is a hint only
        langs = None
    c.commit()  # no transaction stays open over the long work
    pages = v.get("pages") if int(v.get("v") or 0) == ver else None
    try:
        if not run:
            pages = P.po_analyse(data, langs)
        else:
            # review F5: pages only go with the list a person saw of this version (the check's "ready", _queue)
            res = P.po_optimise(data, v.get("mode") or "auto", bool(v.get("blank")) and pages is not None, langs, pages)
    except P.PoError as e:
        key = str(e)
        m = S.meta_row(c, nid)
        if key == "busy":  # another heavy reader: back into the queue, the next step tries again
            po_put(c, nid, {**po_get(m), "state": "wait" if run else "check"})
            c.commit()
            return "busy"
        return _fail(c, nid, {**v, "v": ver}, key)
    base = {k: x for k, x in v.items() if k not in ("q", "tries", "error", "pages")}
    if not run:
        cur = S.meta_row(c, nid)
        po_put(c, nid, {**base, "state": "ready", "v": ver, "pages": pages, "drop": P.po_drop(pages, bool(v.get("blank"))), "at": _now()},
               cur["pdf_opt"])
        bump(c)
        c.commit()
        return None
    pdf = res["pdf"]
    done = {**base, "v": ver, "pages": res["pages"], "drop": res["drop"], "kinds": res["kinds"], "before": len(data), "after": len(pdf), "at": _now()}
    if not P.po_smaller(len(data), len(pdf)):
        po_put(c, nid, {**done, "state": "same"})
        bump(c)
        c.commit()
        return None
    fsl_hold(c, fsl_chain_ids(c, nid))  # 2.970 (#5653, Fable review): first the locked folders' locks, then the version's (one order)
    write_lock(c, f"fs_version:{int(nid)}")  # the lock of the version number: nothing comes between the check and the write
    if int(c.execute("SELECT cur_version FROM fs_nodes WHERE id=?", (nid,)).fetchone()[0] or 0) != ver:
        return _fail(c, nid, done, "changed")
    if fs_deleted(fs_chain(c, nid)):  # 2.892.0 (review): the file or a folder above went to the trash during the run
        return _fail(c, nid, done, "gone")
    if fs_role(c, nid, uid) not in ("owner", "edit"):
        return _fail(c, nid, done, "denied")
    if v.get("auto") and po_office(c, S.meta_row(c, nid), guess=True):  # review F1: sorted into the office meanwhile
        return _fail(c, nid, done, "office")
    try:
        # 2.892.0 (review): the docs queue runs outside the app; the period lock of an office receipt keeps its cache in g
        with nullcontext() if has_app_context() else app.app_context():
            new = fs_new_version(c, nid, pdf, "application/pdf", uid=uid)
    except Denied:
        c.rollback()
        return _fail(c, nid, done, "locked")
    except OperationalError:
        raise
    except Exception as e:  # noqa: BLE001 -- the upload check (ValueError), the quota (admin/hosting.py QuotaExceeded, a layer above)
        c.rollback()
        return _fail(c, nid, done, "quota" if type(e).__name__ == "QuotaExceeded" else "failed")
    o = done.get("orig") if isinstance(done.get("orig"), dict) else {}
    orig = {"from": o["from"] if o.get("to") == ver and o.get("from") else ver, "to": new}
    # review F3: the history names the person, not nobody; review F11: the plain version number as every new version
    # (the undo list of "Last steps" records writes of a request only: core/writes.py obj_undo_pre -- the original stays
    # in the tab History and is restored there)
    fs_log_add(c, nid, "version", str(new), uid=uid)
    po_put(c, nid, {**done, "state": "done", "from": ver, "to": new, "orig": orig})
    # recognised again: the text from its text layer (review F11: as docs/pages.py, the old error goes)
    c.execute("UPDATE doc_meta SET state='wait', tries=0, error='', updated_at=? WHERE node_id=?", (now_iso(), nid))
    bump(c)
    c.commit()
    docs_kick()
    return None
