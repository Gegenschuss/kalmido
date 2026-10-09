"""Version, update check and instance settings (admins)."""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from flask import g, jsonify

from ..core.config import (
    app, APP_VERSION, safe_urlopen, UPDATE_CHECK_ENV, UPDATE_EVERY, UPDATE_MAX_BYTES, UPDATE_RETRY, UPDATE_URL,
)
from ..core.schema import USER_DEFAULTS
from ..core.i18n import LANGS, N_, tr
from ..core.db import body, bump, connect, db, err, gset, gsetting, iso, now_utc, parse_iso, uset, usettings
from ..accounts.session import GATE, me
from ..accounts.oidc import oidc_public
from ..core.access import _COLLAB_ALL, _TIME_ALL, collab_all, time_all


# ---------------------------------------------------------------- version, update check, instance settings

def semver(v):
    m = re.fullmatch(r"v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})", (v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def update_enabled(c):
    return UPDATE_CHECK_ENV and gsetting(c, "update_check") != "0"


def update_state(c):
    """Cached result of the last check. 1.9.0: a cached release older than the running version is never reported
    (it came from a check made before an update: admins saw "latest 1.2.0" while 1.8 ran)."""
    try:
        info = json.loads(gsetting(c, "update_info") or "{}")
    except ValueError:
        info = {}
    info = info if isinstance(info, dict) else {}
    latest, cur = semver(info.get("latest")), semver(APP_VERSION)
    if cur and (not latest or latest < cur) and info.get("latest"):
        info = {**info, "latest": APP_VERSION, "url": ""}
    return info


def about_info(c, u):
    """Version for everyone logged in; update check result and switches only for admins."""
    from ..personal.timetrack import time_day_h
    from ..calendars.subscriptions import CAL_ALLOW_ENV, cal_allow_parse, cal_allow_text, CAL_ON
    from ..admin.backup import BK_ON_ENV
    from ..api.v1 import PUB_ENV
    d = {"version": APP_VERSION}
    if u and u["is_admin"]:
        info = update_state(c)
        latest, cur = semver(info.get("latest")), semver(APP_VERSION)
        d.update(time_day_h=time_day_h(c), collab_all=collab_all(), time_all=time_all(), update_check=gsetting(c, "update_check") != "0", update_env=UPDATE_CHECK_ENV,
                 checked_at=info.get("checked_at") or "", latest=info.get("latest") or "", error=info.get("error") or "",
                 url=info.get("url") or "", available=bool(update_enabled(c) and latest and cur and latest > cur),
                 cal_on=CAL_ON, cal_allow_hosts=gsetting(c, "cal_allow_hosts"),
                 cal_allow_env=cal_allow_text(cal_allow_parse(CAL_ALLOW_ENV)[0]),
                 twofa_required=gsetting(c, "twofa_required") == "1", passkey_login=gsetting(c, "passkey_login") != "0",
                 oidc=oidc_public(c), backups_env=BK_ON_ENV,
                 public_links=gsetting(c, "public_links") != "0", public_links_env=PUB_ENV)
        from ..accounts.signup import signup_admin
        d.update(signup_admin(c))  # 2.23.0 (#711)
        from ..admin.hosting import hosting_admin
        d.update(hosting_admin(c))  # 2.24.0 (#905 #907 #910 #899)
    return d


def update_fetch():
    """Latest release from UPDATE_URL -> {latest, url} (only a plain x.y.z tag and a github.com link are kept)."""
    req = urllib.request.Request(UPDATE_URL, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": f"Kalmido/{APP_VERSION} (update check)"})
    with safe_urlopen(req, timeout=15) as r:
        raw = r.read(UPDATE_MAX_BYTES + 1)
    if len(raw) > UPDATE_MAX_BYTES:
        raise ValueError("response too large")
    j = json.loads(raw.decode("utf-8"))
    tag = str(j.get("tag_name") or "") if isinstance(j, dict) else ""
    if not semver(tag) or j.get("draft") or j.get("prerelease"):
        raise ValueError("no release tag")
    url = str(j.get("html_url") or "")
    if not url.startswith("https://github.com/"):
        url = ""
    return {"latest": tag.lstrip("v"), "url": url[:300]}


def update_check(c, force=False):
    """Check once a day (the result is cached in the DB, so restarts do not ask again)."""
    from ..notify.alerts import aa_cfg, aa_now
    if not update_enabled(c):
        return
    info = update_state(c)
    last = parse_iso(info["checked_at"]) if info.get("checked_at") else None
    # checked again at once after an update (the cache belongs to the version that ran then), sooner after an error
    every = UPDATE_RETRY if info.get("error") else UPDATE_EVERY
    if not force and last and info.get("for") == APP_VERSION and (now_utc() - last).total_seconds() < every:
        return
    new = {"checked_at": iso(now_utc()), "for": APP_VERSION}
    try:
        new.update(update_fetch())
    except urllib.error.HTTPError as e:
        # 404 = no release published yet: nothing to report, not an error
        new.update(latest=info.get("latest") or "", url=info.get("url") or "", error="" if e.code == 404 else f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001  (network, json, anything: keep the last known release)
        new.update(latest=info.get("latest") or "", url=info.get("url") or "", error=type(e).__name__)
    gset(c, "update_info", json.dumps(new))
    c.commit()
    latest, cur = semver(new.get("latest")), semver(APP_VERSION)
    if latest and cur and latest > cur and new["latest"] != gsetting(c, "aa_update_notified"):
        cfg = aa_cfg(c)
        if cfg["on"] and "update" in cfg["kinds"]:  # once per new version
            aa_now("update", "update:" + new["latest"], N_("Kalmido {0} is available (installed: {1}). Nothing is installed automatically."),
                   [new["latest"], APP_VERSION], click=new.get("url") or None)
            gset(c, "aa_update_notified", new["latest"])
            c.commit()


def update_loop():
    while True:
        try:
            with GATE.bg():
                c = connect()
                try:
                    update_check(c)
                finally:
                    c.close()
        except Exception as e:  # noqa: BLE001
            print("update check error:", e, flush=True)
        time.sleep(3600)  # wakes hourly, asks GitHub at most once a day


@app.get("/api/about")
def about():
    return jsonify(about_info(db(), g.user))


@app.patch("/api/admin/settings")
def admin_settings():
    """Instance-wide switches (admins): collab_all, time_all, update_check."""
    from ..personal.timetrack import clean_day_hours
    from ..accounts.users import need_admin
    from ..notify.alerts import aa_now, aa_switch
    from ..calendars.subscriptions import cal_allow_parse, cal_allow_text
    need_admin()
    b, c = body(), db()
    old = {k: gsetting(c, k) not in ("0", "") for k in ("collab_all", "time_all", "update_check") + AUTH_SWITCHES}
    hosts = None
    if "cal_allow_hosts" in b:  # internal hosts calendar subscriptions may reach (SSRF allow-list)
        v = b["cal_allow_hosts"]
        if not isinstance(v, str) or len(v) > 5000:
            return err(tr("Invalid value: {0}", "cal_allow_hosts"))
        ent, bad = cal_allow_parse(v)
        if bad:
            return err(tr("Not a host name or host:port: {0}", ", ".join(bad[:5])))
        if len(ent) > 50:
            return err(tr("At most {0} hosts", 50))
        hosts = cal_allow_text(list(dict.fromkeys(ent)))
        if hosts == gsetting(c, "cal_allow_hosts"):
            hosts = None
        else:
            gset(c, "cal_allow_hosts", hosts)
    if "time_day_h" in b:  # 2.7.0 (#407): hours per day / shift for every list without its own value
        dh = clean_day_hours(b["time_day_h"])
        if dh is False:
            return err(tr("Hours per day: a number from 1 to 24"))
        gset(c, "time_day_h", "" if dh is None else str(dh))
    e = _apply_instance(c, b)
    if e:
        return e
    from ..admin.hosting import hosting_settings
    e = hosting_settings(c, b)  # 2.24.0: storage quota, support address, mail limit, the notice
    if e:
        c.rollback()
        return e
    bump(c)
    c.commit()
    for k, was in old.items():
        if k in b and b[k] != was:
            aa_switch(c, g.user, k, b[k])
    if hosts is not None:
        aa_now("security", f"calhosts:{int(time.time())}", N_("{0} changed the internal hosts calendar subscriptions may reach: {1}"),
               [g.user["username"], hosts or "-"])
    if b.get("update_check") is True and UPDATE_CHECK_ENV:
        threading.Thread(target=_update_now, daemon=True).start()
    return jsonify(about_info(c, g.user))


SETUP_MODULES = ("cal", "timeline", "matrix", "kanban", "habits", "pomo", "stats", "progress", "deps", "fields")


@app.post("/api/admin/setup")
def admin_setup():
    """Step 2 of the first-run setup ("What do you want to use?"): {lang, collab_all, time_all, modules: [...], sample?}.
    Sets the instance switches, the modules of new users (default_features; the admin gets them too) and the
    language. Collaboration and time tracking stay in the modules list: the instance switch alone decides, so
    turning one on later in Settings makes it available to everyone at once. Admin only; all changeable later."""
    from ..accounts.onboarding import sample_create, sample_state
    from ..accounts.users import need_admin
    from ..lists.templates import ptype_create, PTYPE_NAMES, PTYPES
    from ..family.family import family_examples, PURPOSES
    need_admin()
    b, c = body(), db()
    mods = b.get("modules")
    if not isinstance(mods, list) or not all(isinstance(m, str) for m in mods):
        return err(tr("Invalid value: {0}", "modules"))
    lang = b.get("lang")
    if lang is not None and lang not in LANGS:
        return err(tr("Invalid value: {0}", "lang"))
    e = _apply_instance(c, {k: b[k] for k in ("collab_all", "time_all") if k in b})
    if e:
        return e
    fs = ",".join(f for f in USER_DEFAULTS["features"].split(",") + ["family"] if f in ("collab", "time") or f in mods)
    gset(c, "default_features", fs)
    uset(c, me(), "features", fs)
    if lang:
        gset(c, "default_lang", lang)
        uset(c, me(), "lang", lang)
    if b.get("org_name"):  # 2.23.0 (#799): the first-run setup asks once for the organisation's name (unless configured)
        from ..accounts.orgs import instance_mode, main_org, ORG_NAME_ENV
        import re as _re
        nm = _re.sub(r"\s+", " ", str(b["org_name"])).strip()[:60]
        if nm and instance_mode(c) == "organisation" and not ORG_NAME_ENV and main_org(c):
            c.execute("UPDATE orgs SET name=? WHERE id=?", (nm, main_org(c)))
    pt = b.get("project_type")  # 2.4.0 (#243): "Start with a project" of a built-in type
    if pt not in (None, "") and pt not in PTYPES:
        return err(tr("Invalid value: {0}", "project_type"))
    if pt:
        ptype_create(c, me(), pt, tr(PTYPE_NAMES[pt], lg=lang or None))
    if b.get("purpose") not in (None, ""):  # 2.19.0 (#653): "What do you use Kalmido for?" (the modules came above)
        if b["purpose"] not in PURPOSES:
            return err(tr("Invalid value: {0}", "purpose"))
        uset(c, me(), "purpose", b["purpose"])
        from ..family.family import _LIFE, PURPOSE_ON  # 2.22.0 (#741): the Home & life modules of the purpose (the admin's own)
        on = [m for m in PURPOSE_ON[b["purpose"]] if m in _LIFE]
        if on:
            uset(c, me(), "features", ",".join([x for x in fs.split(",") if x] + on))
        if b["purpose"] == "family":
            family_examples(c, me())
    if b.get("sample") is True and not sample_state(c, me()):  # 1.8.0: "Create a sample project"
        sample_create(c, me())
    elif "sample" in b:
        uset(c, me(), "sample_ask", "0")  # decided here: the welcome tour does not ask again
    gset(c, "setup_step2", "done")
    bump(c)
    c.commit()
    return jsonify(about_info(c, g.user))


AUTH_SWITCHES = ("twofa_required", "passkey_login", "oidc_autocreate", "public_links")


def _apply_instance(c, b):
    """Stores the instance switches of b (caller commits); an error response for a non-boolean value."""
    from ..personal.timetrack import stop_timer
    keys = ("collab_all", "time_all", "update_check") + AUTH_SWITCHES
    if any(k in b and not isinstance(b[k], bool) for k in keys):
        return err(tr("Invalid value: {0}", next(k for k in keys if k in b and not isinstance(b[k], bool))))
    from ..accounts.signup import signup_settings
    e = signup_settings(c, b)  # 2.23.0 (#711): registration mode + domains
    if e:
        return e
    for k in keys:
        if k in b:
            gset(c, k, "1" if b[k] else "0")
    if "collab_all" in b:
        _COLLAB_ALL["on"] = b["collab_all"]
        if b["collab_all"] and b.get("collab_personal_on") is True:  # "Turn on collaboration now?" (second user)
            for (uid,) in c.execute("SELECT id FROM users WHERE disabled=0").fetchall():
                fs = [f for f in usettings(c, uid)["features"].split(",") if f]
                if "collab" not in fs:
                    uset(c, uid, "features", ",".join(fs + ["collab"]))
    if "time_all" in b:
        if not b["time_all"] and time_all():  # stop running timers now (entries kept, end = now)
            now, ts = now_utc(), iso(now_utc())
            for r in c.execute("SELECT * FROM time_entries WHERE end IS NULL").fetchall():
                stop_timer(c, r, now, ts)
        _TIME_ALL["on"] = b["time_all"]
    return None


def _update_now():
    c = connect()
    try:
        update_check(c, force=True)
    finally:
        c.close()
