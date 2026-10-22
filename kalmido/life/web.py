"""Home & life: the web API (overview, contracts, devices, upkeep, health, trips, review + journal, staying in touch, Karakeep)."""
from datetime import date

from flask import jsonify, request, Response

from ..core.config import app
from ..core.i18n import lang, tr
from ..core.db import body, bump, db, err, local_now
from ..accounts.session import me
from ..core.access import health_hidden
from ..tasks.validation import valid_date
from ..tasks.tasks import one_task
from ..life.model import (
    care_set, contract_create, device_create, health_create, journal_export, journal_list, journal_set, journal_stats, life_overview, life_space, need_life, review, trip_create,
    upkeep_create, upkeep_presets,
)
from ..life.karakeep import kk_delete, kk_lists, kk_public, kk_set, kk_sync


def _done(c, out, code=200):
    bump(c)
    c.commit()
    return jsonify(out), code


@app.get("/api/life")
def life_get():
    """The view "Home & life": the switched-on modules with their contracts, devices + upkeep, contacts to get in touch
    with, health entries, trips and the reading list (also GET /api/v1/life). 2.173.0 A (#2680): ?space=private|org:<id>
    (the app only): an organisation's trips and contacts to stay in touch with; without = the private space."""
    c, uid = db(), me()
    return jsonify(life_overview(c, uid, life_space(c, uid, request.args.get("space"))))


@app.get("/api/life/upkeep-presets")
def life_upkeep_presets():
    c = db()
    return jsonify(presets=upkeep_presets(lang(c, me())))


@app.post("/api/life/contracts")
def life_contract_new():
    """{name, ends, provider?, cost?, per?, notice?, notice_unit?, renew_months?, lead_days?, start?, account?, list_id?}
    -> a contract task: due on the last day to cancel, repeating with the renewal, reminders lead_days before + on the day."""
    c, uid = db(), me()
    tid = contract_create(c, uid, body())
    return _done(c, one_task(c, tid), 201)


@app.post("/api/life/devices")
def life_device_new():
    """{name, model?, bought?, warranty?, lead_days?, list_id?} -> a device (due when its warranty ends)."""
    c, uid = db(), me()
    tid = device_create(c, uid, body())
    return _done(c, one_task(c, tid), 201)


@app.post("/api/life/upkeep")
def life_upkeep_new():
    """{title, every_months, next?, item?, lead_days?, list_id?} -> a repeating upkeep task."""
    c, uid = db(), me()
    tid = upkeep_create(c, uid, body())
    return _done(c, one_task(c, tid), 201)


@app.post("/api/life/health")
def life_health_new():
    """{type, title, who?, date?, time?, every_months?, times?, lead_days?, list_id?} -> {tasks: [..]} in a private health list."""
    c, uid = db(), me()
    ids = health_create(c, uid, body())
    return _done(c, {"tasks": [one_task(c, x) for x in ids]}, 201)


@app.post("/api/life/trips")
def life_trip_new():
    """{name, from, to, where?, packing?, event?, folder?, space?} -> {list_id, event_id}: a trip list with bookings, things
    to do before leaving and the packing list (2.173.0 A, #2680: in the space given, private without)."""
    c, uid = db(), me()
    return _done(c, trip_create(c, uid, body()), 201)


def _review_args():
    p = request.args.get("period", "day")
    if p not in ("day", "week"):
        return None, None, err(tr("Invalid value: {0}", "period"))
    d = request.args.get("date")
    if d and not valid_date(d):
        return None, None, err(tr("Invalid value: {0}", "date"))
    return p, date.fromisoformat(d) if d else local_now().date(), None


@app.get("/api/life/review")
def life_review():
    """?period=day|week&date=YYYY-MM-DD: done, still open, moved, the next 7 days and the journal entries of the range."""
    c, uid = db(), me()
    need_life(c, uid, "review")
    p, d, e = _review_args()
    if e:
        return e
    return jsonify(review(c, uid, p, d, journal=not health_hidden(c, uid)))


@app.get("/api/life/journal")
def life_journal_list():
    """?q=&mood=&from=&to=&before=&limit=: my journal entries, newest first, 30 per page (next = the cursor for ?before=)."""
    c, uid = db(), me()
    return jsonify(journal_list(c, uid, request.args))


@app.get("/api/life/journal/stats")
def life_journal_stats():
    """?days=30|90|365: the mood distribution + the average per week (month for 365 days)."""
    c, uid = db(), me()
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 0
    return jsonify(journal_stats(c, uid, days))


@app.get("/api/life/journal/export")
def life_journal_export():
    """?format=md|csv&from=&to=: my journal as a download (own entries only, no formulas in the CSV)."""
    c, uid = db(), me()
    fmt = "csv" if request.args.get("format") == "csv" else "md"
    text = journal_export(c, uid, request.args, fmt)
    return Response(text, mimetype="text/csv; charset=utf-8" if fmt == "csv" else "text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="journal.{fmt}"', "Cache-Control": "no-store"})


@app.put("/api/life/journal/<day>")
def life_journal_put(day):
    """{text, mood?}: my journal entry of that day (private; an empty one is deleted)."""
    c, uid = db(), me()
    out = journal_set(c, uid, day, body())
    return _done(c, out)


@app.put("/api/contacts/<int:cid>/care")
def contact_care_put(cid):
    """{every_days? (0 = off), last? (YYYY-MM-DD or "today"), note?}: stay in touch with this contact (my own setting)."""
    c, uid = db(), me()
    out = care_set(c, uid, cid, body())
    return _done(c, out)


@app.get("/api/life/karakeep")
def life_kk_get():
    c = db()
    return jsonify(kk_public(c, me()))


@app.put("/api/life/karakeep")
def life_kk_put():
    """{url?, token?, list_id?, source?, archive?}: my Karakeep connection (the API key is write-only)."""
    c, uid = db(), me()
    out = kk_set(c, uid, body())
    return _done(c, out)


@app.delete("/api/life/karakeep")
def life_kk_delete():
    c, uid = db(), me()
    kk_delete(c, uid)
    return _done(c, {"ok": True})


@app.get("/api/life/karakeep/lists")
def life_kk_lists():
    c, uid = db(), me()
    need_life(c, uid, "reading")
    return jsonify(lists=kk_lists(c, uid))


@app.post("/api/life/karakeep/sync")
def life_kk_sync():
    """Fetch new bookmarks now (and archive the ticked ones in Karakeep) -> {added, archived, list_id}."""
    c, uid = db(), me()
    need_life(c, uid, "reading")
    out = kk_sync(c, uid)
    return _done(c, out)
