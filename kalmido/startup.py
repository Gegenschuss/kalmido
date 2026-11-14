"""Start-up: init_db() and the background threads (watchdog, update check, calendars, backups, webhooks, mail, git)."""
import os

from .core.config import UPDATE_CHECK_ENV
from .core.db import connect, gset, gsetting, init_db, mig_flags_sync
from .core.instance import update_loop
from .notify.push import watchdog
from .notify.alerts import aa_secret_key
from .calendars.subscriptions import cal_loop, CAL_ON
from .admin.backup import backup_loop, bk_leftovers_alert, bk_tools_note, BK_ON_ENV
from .api.v1 import WH_ON
from .integrations.webhooks import wh_loop
from .notify.channels import chn_loop, CH_ON
from .integrations.git import git_loop
from .integrations.mail import MAIL_IN_ON, mail_loop
from .hub.mailbox import mbx_loop
from .integrations.docflowhook import dfh_loop  # 2.581.0 (#4803)
from .events.model import migrate_family_events
from .core.env import env_bool
from .office.model import onc_long_report  # 2.312.0 C (#3265)
from .office.okern import ofk_trash_retire  # 2.1005.0 (#5415); 2.1073.0 (#5865): the copies back, then the table goes
from .office.cfstart import cfs_start_fix  # review 2.1067.0 (F1, #5789)
from .files.store import fs_addr_log_purge  # 2.1145.0 (#6062)


# 2.42.0 (#828): `python -m kalmido.admin.orgcrypt_cli ...` loads the package too: no background threads in that process
_OC_CLI = "kalmido.admin.orgcrypt_cli" in getattr(__import__("sys"), "orig_argv", ())
if _OC_CLI:
    os.environ["TASKS_WATCHDOG"] = "0"
init_db()
_c = connect()
try:
    migrate_family_events(_c)  # 2.21.0 (#659), once: the family events of 2.19 (tasks with people) become events
    # 2.924.0 (#5069): the one-shot of #4712 (ev_kern_copy) is part of events/evkern.py ev_kern_drop (core/db.init_db START)
    if gsetting(_c, "migr_addrlog6062") != "1":  # 2.1145.0 (#6062): one way, once -- old history lines naming the account of a
        # share by e-mail address go (files/store.py fs_addr_log_purge; since 2.1138.0 such a share writes none). Here and not in
        # init_db: core may not import the file store (tools/check_layers.py)
        try:
            _n = fs_addr_log_purge(_c)
            gset(_c, "migr_addrlog6062", "1")
            _c.commit()
            if _n:
                print(f"history lines naming the account of a share by address removed {_n}", flush=True)
        except Exception as _e:  # noqa: BLE001  never stops the start; tried again at the next one
            _c.rollback()
            print(f"history lines of shares by address: clean-up FAILED ({type(_e).__name__}: {_e})", flush=True)
    mig_flags_sync(_c)  # 2.102.0 D (#1996): a one-shot of just now (its flag) into kalmido_migrations
    _c.commit()
    # 2.1005.0 (#5415, one way, every start): the office trash's copies of the kinds on the core's trash back as rows of it
    # (office/okern.py; here and not in init_db: the office kinds are registered once the app's modules are loaded)
    try:  # review 2.1005.0 (F1): a copy the step cannot read never stops the app from starting
        _n = ofk_trash_retire(_c)  # 2.1073.0 (#5865, one way): the copies back, then the table office_trash goes
        if any(v for k, v in _n.items() if k != "dropped"):
            print(f"office trash: copies back into their tables {_n['back']}, left as copies {_n['kept']} (unreadable {_n['bad']}, "
                  f"held {_n['held']})", flush=True)
        if _n["dropped"] is not None:
            print(f"office trash: the old table office_trash is gone ({_n['dropped']} copies that could not come back went with it)", flush=True)
    except Exception as _e:  # noqa: BLE001
        _c.rollback()
        print(f"office trash: copies back / drop FAILED, the table stays ({type(_e).__name__}: {_e})", flush=True)
    try:  # Fable review 2.1073.0 (F1): its own block -- a failure above never skips it
        if cfs_start_fix(_c):  # review 2.1067.0 (F1, #5789): a start balance set by an older version on a trashed row
            _c.commit()
    except Exception as _e:  # noqa: BLE001
        _c.rollback()
        print(f"office trash: start balance check FAILED ({type(_e).__name__}: {_e})", flush=True)
finally:
    _c.close()
from .admin.worker import wrk_conn_check, wrk_start, WRK_ROLE
wrk_conn_check()  # 2.102.0 D (#1994): replicas x pool against Postgres' max_connections -> warn in the log
from .admin.clientip import ip_startup_check
ip_startup_check()  # 2.33.0 (#834): many accounts from one private address -> warn in the log
from .office.pdfweb import rx_office_perms
rx_office_perms()  # 2.39.1 (#1210 N8): office folders of older versions become 0700
if not _OC_CLI and env_bool("TASKS_WATCHDOG", True):  # 2.370.2 (#2779): folders a hard stop of a restore left behind
    bk_leftovers_alert()
if not _OC_CLI and env_bool("TASKS_WATCHDOG", True) and WRK_ROLE != "web":  # 2.42.0 (#828): existing organisation data gets encrypted at
    # rest (a background pass, idempotent); not in helper processes (CLI, scripts run with TASKS_WATCHDOG=0)
    from .admin.orgcrypt_cli import oc_migrate_start
    oc_migrate_start(300)  # after an update's health check: a failed update rolls back before anything is encrypted
if not _OC_CLI and env_bool("TASKS_WATCHDOG", True):  # 2.266.0 (#2964): every process (also "web") sends its own admin alerts
    import threading
    from .notify.alerts import aa_flush_loop
    threading.Thread(target=aa_flush_loop, daemon=True, name="admin-alerts").start()
# 2.102.0 D (#1997): not in the role "web" (the worker runs them); each loop runs in one process of the instance (wrk_start)
# 2.149.0 D (#2511): TASKS_WATCHDOG read like every switch (true/on = on as well; was only "1")
if env_bool("TASKS_WATCHDOG", True) and WRK_ROLE != "web":
    wrk_start("watchdog", watchdog)
    if UPDATE_CHECK_ENV:
        wrk_start("update-check", update_loop)
    if CAL_ON:  # calendar subscriptions: background sync
        wrk_start("calendars", cal_loop)
    if BK_ON_ENV:  # automatic backups (schedule + retention; off until an admin turns them on)
        wrk_start("backup", backup_loop)
    if WH_ON:  # webhook deliveries (queue + retries)
        wrk_start("webhooks", wh_loop)
    if CH_ON:  # 2.142.0 A (#2145): notification channels (Slack, Matrix, Telegram, Signal)
        wrk_start("channels", chn_loop)
    if MAIL_IN_ON:  # 2.17.0 (#443): new tasks by e-mail (one mailbox, polled)
        wrk_start("mail-in", mail_loop)
    wrk_start("docflows", dfh_loop)  # 2.581.0 (#4803): scheduled document flows + their webhook calls (idle without any)
    wrk_start("mailboxes", mbx_loop)  # 2.141.0 A (#2141): the own mailboxes of the workspaces (idle without any)
    wrk_start("git", git_loop)  # 2.2.0 (#271): repositories of project lists (idle without any)
    # 2.574.0 (#3779): the ntfy share inboxes (NTFY_INBOX_* and the personal ones) are gone: sharing goes through the share
    # menu, /drop and the mail inbox
if not _OC_CLI and env_bool("TASKS_WATCHDOG", True) and WRK_ROLE != "web":  # 2.312.0 C (#3265): once per instance start, not per web process
    _c = connect()
    try:
        onc_long_report(_c)  # saved number schemes onc_parse no longer reads -> log + admin alert (nothing is changed)
    except Exception as e:  # noqa: BLE001 - a report, never a reason not to start
        print("office: number scheme check:", type(e).__name__, flush=True)
    finally:
        _c.close()
    aa_secret_key()  # 2.359.3 (#2510)
    if BK_ON_ENV:
        try:
            bk_tools_note()  # 2.359.3 (#2945)
        except Exception as e:  # noqa: BLE001 - a report, never a reason not to start
            print("backup: tools check:", type(e).__name__, flush=True)
