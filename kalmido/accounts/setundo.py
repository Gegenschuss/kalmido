"""2.985.0 (#5394): undo across devices, stage 6 rest -- a person's settings in the core's step groups (core/undogroups.py).

The settings are key-value rows (table user_settings: user_id, key, value; no id, no version, no org), so a step is not a
copy of a row but a diff part (core/undodiff.py) of its own kind per key: kind "setting", ref_id = the person, data
{k: key, b: the stored value before | None (no row: the standard), a: the value after | None}. One request (PATCH
/api/settings, POST /api/settings/reset, PATCH /api/v1/me/notifications) records one part per key it really changed, in one
group of area "self" labelled with the setting's readable name (accounts/settings.py RS_ITEMS) or "Settings reset".

Recorded right before the commit (core/pg.py Conn.pre_commit, su_flush), so a request that fails records nothing. Taken
back (core/undoweb.py _diff_part): only by the person itself, under the settings lock (usettings-<uid>, as the PATCH), only
while the key still holds the value the step left (another device changed it since = 409, the part stays and is named);
the folders' marks of show_done_views / show_progress and the active saved arrangement follow as on a PATCH. An agent never
records (core/undodiff.py undo_person). SU_QUIET: keys a view changes by itself while one moves around (the folded
folders, the shown workspace, column widths, the tour, ...) are no step: they would bury the real ones in the list; nor is a
key that goes from no value to an empty one ('' / {} / []: the first save of a device's look).
2.1013.0 (#5773): nor is a PATCH /api/settings the app sends by itself with {_auto: 1} (static/js: a view's block switches
lyOptSet, a folder a list edit / move adds, a device's own settings handed to the account once): no step at all.

2.985.0 (#5394, review F4-F6, F9):
- a reset (POST /api/settings/reset) marks the view state too (SU_QUIET keys it puts back) and the active saved arrangement
  of each view key (part data "lyv"); taking it back puts both back and empties the in-app "undo the reset" (reset_undo),
  so the two ways never put the values back twice. The parts of a reset carry "r": 1. Review N4: a reset marks every key
  it puts back, also the private ones of RS_ITEMS (quiet hours); the in-app "undo the reset" ({undo: true}) is marked the
  same way with "r": 2 (its arrangements follow the values as on a PATCH).
- review N6: a value cleaned on the way back is what the part holds afterwards, so the way forward compares against it.
- SU_PRIVATE: privacy choices (push channel and "title only", sharing defaults, photo metadata, video players, read receipts,
  own mails, quiet hours, busy times; review F3: the assistant, mails with contents, the calendar feed, test mode) are never a step: "Back to here" must not undo them silently.
- su_run checks the key again (known, not server-only, not private, view state only as a part of a reset) and stores the
  value through clean_setting as PATCH /api/settings does (an old value that is no longer valid = 409, nothing written).
- PATCH /api/settings of the same keys from the same device within SU_BUNDLE_S seconds joins the group before while that is
  still the person's newest (core/undogroups.py undo_bundle): a setting tried out several times is one step. 2.997.0 (#5705,
  #5706): not a key holding several entries (a json list / map, a comma list): each change there is a step (_su_many).

Interface:
  su_mark(c, uid, keys, label=None, reset=False, lyv=None, bundle=False)
                          before the request writes keys: their stored values now (once per key and request)"""
import hashlib

from flask import g

from ..core.db import bump, uset, usettings
from ..core.errors import BadInput, Denied
from ..core.i18n import LANGS, N_, tr
from ..core.pg import write_lock
from ..core.schema import USER_DEFAULTS
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from ..core.undogroups import ug_device, undo_bundle, undo_label
from .layouts import LAYOUT_KEYS
from .layoutsets import lyv_follow, lyv_set_active
from .settings import RS_EMPTY, RS_ITEMS, RS_KEYS, SET_DELTA_CSV, SETTINGS_SERVER_ONLY, clean_setting, notif_update, rs_done_sync, rs_put

SU_KIND = "setting"
SU_AREA = "self"
SU_CHANGED = N_("Setting changed: {0}")
SU_CHANGED_N = N_("{0} settings changed")
SU_RESET = N_("Settings reset to the standard")
SU_CONFLICT = N_("Changed again in the meantime, so it cannot be undone")
# view state a view writes by itself (no step); the server-only keys are never a step either (accounts/settings.py)
SU_QUIET = ("workspace", "side_view", "folders_closed", "sections_closed", "col_widths", "detail_split", "detail_fold",
            "detail_cm_fold", "settings_more", "trial_hint_seen", "tours_seen", "office_ws_hint", "ab_cards", "reset_undo",
            "whatsnew_seen", "tour")
# 2.997.0 (#5625): the roadmap's view state (zoom, collapsed projects, list selection, filters: static/js/roadmap.js rmSet) is
# saved by the view itself while one looks around, like the column widths; as a step (bundled, the newest again on every save)
# it went back with the undo of a project shift and changed the zoom under the person's next drag
SU_QUIET += ("roadmap",)
SU_NAMES = {"lang": N_("Language"), "notify": N_("What notifies you (bell and push)")}
SU_CHANGED_PLAIN = N_("Setting changed")  # review F5: a key without a readable name is never shown raw
SU_INVALID = N_("The old value is no longer valid, so it cannot be undone")
# review F5: privacy choices -- never a step (like the reset leaves them out, accounts/settings.py RS_ITEMS)
SU_PRIVATE = ("push_title_only", "push_channel", "share_defaults", "photo_meta_strip", "video_ext_ok", "chat_read_receipts",
              "mail_from_me", "quiet_from", "quiet_to", "freebusy_share")
# 2.985.0 (#5394, review F3): consent to the built-in assistant (contents go to a model), contents leaving by mail (digest,
# assignment / mention mails), what the calendar feed gives out, and an office's test mode (undone, the next document is real)
SU_PRIVATE += ("assistant_on", "digest_mail", "mail_assign", "mail_mention", "ical_scope", "trial_mode")
SU_BUNDLE_S = 600  # review F6: the same settings changed again from the same device within 10 minutes = one step


def _raw(c, uid, keys):
    keys = list(keys)
    if not keys:
        return {}
    got = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM user_settings WHERE user_id=? AND key = ANY(CAST(? AS TEXT[]))",
                                                    (int(uid), keys))}
    return {k: got.get(k) for k in keys}


def su_mark(c, uid, keys, label=None, reset=False, lyv=None, bundle=False):  # reset: False | True (a reset) | 2 (its in-app undo)
    """Remember the stored values of keys before this request writes them (the first mark of a key wins); the parts are
    written at the commit (su_flush). label = (key, [values]) of the group instead of the setting's name (a reset).
    reset (review F4): the view state is a part as well, lyv = {view key: id of its active saved arrangement}; bundle
    (review F6): PATCH /api/settings, see the module docstring."""
    who = undo_person(c)
    if who is None or int(who) != int(uid):
        return
    m = g.get("su_marks")
    if m is None or m["uid"] != int(uid):
        m = g.su_marks = {"uid": int(uid), "before": {}, "label": None, "reset": 0, "lyv": {}, "bundle": False}
    # review N4: a reset (and its in-app undo) marks every key it puts back, the private ones of RS_ITEMS too
    new = [k for k in dict.fromkeys(keys) if k not in m["before"] and (reset or (k not in SU_PRIVATE and k not in SU_QUIET))]
    m["before"].update(_raw(c, uid, new))
    if label:
        m["label"] = label
    m["reset"] = m["reset"] or (2 if reset == 2 else 1 if reset else 0)
    m["lyv"].update({k: int(v) for k, v in (lyv or {}).items() if v})
    m["bundle"] = bool(bundle) if len(m["before"]) == len(new) else False  # bundled only when this request marks alone
    c.pre_commit["settings.undo"] = su_flush


def _su_many(k, *vals):
    """2.997.0 (#5705, #5706): does setting k hold several entries (a comma list, a json list / map)? Not the device's look
    (one map the app syncs as a whole after every change of it, dialogs.js lookPush: stays one bundled step)."""
    return k != "look" and (k in SET_DELTA_CSV or any(str(v or "").lstrip()[:1] in ("[", "{") for v in vals))


def su_name(k):
    """The readable name of setting k: [i18n key] (translated for the reader, core/i18n.py tr_stored), None without one."""
    if k in SU_NAMES:
        return [SU_NAMES[k]]
    for _grp, name, keys in RS_ITEMS:
        if k in keys:
            return [name]
    return None


def su_label(ch):
    """The label of the changed keys ch (review F5: never a raw key name)."""
    if len(ch) != 1:
        return SU_CHANGED_N, [len(ch)]
    n = su_name(ch[0])
    return (SU_CHANGED, [n]) if n else (SU_CHANGED_PLAIN, [])


def su_flush(c):
    """The marked keys whose value changed: one part each (core/pg.py Conn.pre_commit). A failure never costs the change."""
    m = g.pop("su_marks", None)
    if not m or not m["before"]:
        return
    prev = g.get("undo_group")
    prev = dict(prev) if prev else None
    try:
        with c.savepoint():
            after = _raw(c, m["uid"], m["before"])
            ch = [k for k, v in m["before"].items() if v != after[k] and not (str(v or "") in RS_EMPTY and str(after[k] or "") in RS_EMPTY)]
            if not ch:
                return
            label = m["label"] or su_label(ch)
            undo_label(c, label[0], *label[1])
            # 2.997.0 (#5705, #5706): a key holding several entries (a json list / map: the favourites, my colour per workspace,
            # a view's arrangement; a comma list of SET_DELTA_CSV) is changed one entry at a time - another favourite moved,
            # another workspace's colour - so each change stays a step of its own (bundled, Ctrl+Z took back every favourite /
            # colour of the last 10 minutes at once); the bundle is for one choice tried again (theme, priority colour)
            if m["bundle"] and not m["reset"] and not any(_su_many(k, m["before"][k], after[k]) for k in ch):  # review F6: the same keys from the same device again = the group before
                key = hashlib.sha256(f"{ug_device()}|{','.join(sorted(ch))}".encode()).hexdigest()[:24]
                undo_bundle(f"set:{key}", SU_BUNDLE_S, newest=True, relabel=False)
            for k in ch:
                d = {"k": k, "b": m["before"][k], "a": after[k]}
                if m["reset"]:
                    d["r"] = m["reset"]
                    if m["reset"] == 1 and m["lyv"].get(k):
                        d["lyv"] = m["lyv"][k]
                ug_diff_add(c, m["uid"], SU_KIND, m["uid"], None, SU_AREA, label, d)
    except Exception as e:  # noqa: BLE001 -- the step is lost, the change itself commits
        # review F9: the group / label of the rolled-back savepoint must not be taken by a later write of this request
        g.undo_group = prev
        g.pop("undo_label", None)
        print("settings undo step not recorded:", type(e).__name__, str(e)[:200], flush=True)
    finally:
        g.pop("undo_bundle", None)


def _follow(c, uid, k, old, new):
    """What a PATCH of key k does besides storing it (accounts/settings.py settings_update): old / new = the values in effect."""
    if k in ("show_done_views", "show_progress"):
        rs_done_sync(c, uid, old, new, k)
    if k == "dashboard" or k in LAYOUT_KEYS:
        lyv_follow(c, uid, k, new or "")


def _clean(c, uid, k, v):
    """review F5: the value a part writes, checked like PATCH /api/settings (None = no row: the standard)."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise Denied(409, tr(SU_INVALID))
    try:
        if k == "notify":  # stored by notif_update, as the web app's PATCH of the whole value
            return notif_update({**usettings(c, uid), "notify": ""}, v)["notify"] if v.strip() else ""
        if k == "lang" and v not in LANGS:
            raise BadInput("lang")
        out = clean_setting(k, v)
    except (BadInput, ValueError, TypeError):
        raise Denied(409, tr(SU_INVALID)) from None
    if out is None:  # a number setting's "" = leave unchanged in a PATCH; here: the empty value it held
        if v == "":
            return ""
        raise Denied(409, tr(SU_INVALID))
    if len(out) == 200 and len(v) > 200 and v.startswith(out):
        return v  # the PATCH's catch-all cut (sv[:200]) of a key it has no rule for: the stored value as it was
    return out


def su_run(c, uid, rid, data, redo):
    """One part back (redo: forward): only the person's own key, only while it holds what the step left."""
    if int(rid) != int(uid) or not isinstance(data, dict) or not isinstance(data.get("k"), str):
        raise Denied(404)
    k = data["k"]
    reset = data.get("r") == 1
    # review F5: the key checked again -- a known one of the person, never server-only; a private choice or view state only
    # as a part of a reset or of its in-app undo (review N4: those only put back keys of RS_ITEMS)
    if k not in USER_DEFAULTS or k in SETTINGS_SERVER_ONLY:
        raise Denied(404)
    if (k in SU_PRIVATE or k in SU_QUIET) and not (data.get("r") in (1, 2) and k in RS_KEYS):
        raise Denied(404)
    write_lock(c, f"usettings-{int(uid)}")  # the lock of PATCH /api/settings
    now = _raw(c, uid, [k])[k]
    want, put = (data.get("b"), data.get("a")) if redo else (data.get("a"), data.get("b"))
    if now != want:
        raise Denied(409, tr(SU_CONFLICT))
    put = _clean(c, uid, k, put)
    data = {**data, ("a" if redo else "b"): put}  # review N6: the value as written, the next way compares against it
    old = usettings(c, uid).get(k)
    rs_put(c, uid, k, put)
    if reset and (k == "dashboard" or k in LAYOUT_KEYS):  # review F4: the saved arrangement as the reset left / found it
        if redo:
            lyv_follow(c, uid, k, "")  # the reset ends the active arrangement (it stays saved)
        elif data.get("lyv"):
            lyv_set_active(c, uid, k, int(data["lyv"]))
    else:
        _follow(c, uid, k, old, usettings(c, uid).get(k))
    if reset and not redo:  # review F4: the reset is taken back: the app's own "undo the reset" has nothing left to do
        uset(c, uid, "reset_undo", "")
    bump(c, SU_AREA)
    return data, []


undo_diff_reg(SU_KIND, su_run, SU_AREA)
