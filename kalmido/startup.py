"""Start-up: init_db() and the background threads (watchdog, update check, calendars, backups, webhooks, mail, git)."""
import os

from .core.config import NTFY_IN, ntfy_inbox_allowed, UPDATE_CHECK_ENV
from .core.i18n import N_
from .core.db import connect, init_db, mig_flags_sync
from .core.pages import ntfy_inbox_loop
from .core.instance import update_loop
from .notify.push import watchdog
from .notify.alerts import aa_now
from .calendars.subscriptions import cal_loop, CAL_ON
from .admin.backup import backup_loop, BK_ON_ENV
from .api.v1 import WH_ON
from .integrations.webhooks import wh_loop
from .notify.channels import chn_loop, CH_ON
from .integrations.git import git_loop
from .integrations.mail import MAIL_IN_ON, mail_loop
from .events.model import migrate_family_events


# 2.42.0 (#828): `python -m kalmido.admin.orgcrypt_cli ...` loads the package too: no background threads in that process
_OC_CLI = "kalmido.admin.orgcrypt_cli" in getattr(__import__("sys"), "orig_argv", ())
if _OC_CLI:
    os.environ["TASKS_WATCHDOG"] = "0"
init_db()
_c = connect()
try:
    migrate_family_events(_c)  # 2.21.0 (#659), once: the family events of 2.19 (tasks with people) become events
    mig_flags_sync(_c)  # 2.102.0 D (#1996): a one-shot of just now (its flag) into kalmido_migrations
    _c.commit()
finally:
    _c.close()
from .admin.worker import wrk_conn_check, wrk_start, WRK_ROLE
wrk_conn_check()  # 2.102.0 D (#1994): replicas x pool against Postgres' max_connections -> warn in the log
from .admin.clientip import ip_startup_check
ip_startup_check()  # 2.33.0 (#834): many accounts from one private address -> warn in the log
from .office.pdfweb import rx_office_perms
rx_office_perms()  # 2.39.1 (#1210 N8): office folders of older versions become 0700
if not _OC_CLI and os.environ.get("TASKS_WATCHDOG", "1") == "1" and WRK_ROLE != "web":  # 2.42.0 (#828): existing organisation data gets encrypted at
    # rest (a background pass, idempotent); not in helper processes (CLI, scripts run with TASKS_WATCHDOG=0)
    from .admin.orgcrypt_cli import oc_migrate_start
    oc_migrate_start(300)  # after an update's health check: a failed update rolls back before anything is encrypted
# 2.102.0 D (#1997): not in the role "web" (the worker runs them); each loop runs in one process of the instance (wrk_start)
if os.environ.get("TASKS_WATCHDOG", "1") == "1" and WRK_ROLE != "web":
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
    wrk_start("git", git_loop)  # 2.2.0 (#271): repositories of project lists (idle without any)
    if NTFY_IN["token"] and NTFY_IN["url"]:
        if ntfy_inbox_allowed():
            wrk_start("ntfy-inbox", ntfy_inbox_loop)
        else:
            aa_now("integration", "inbox:refused", N_("The ntfy share inbox was not started: its topic on the public ntfy.sh is guessable, anyone could publish to it (NTFY_INBOX_TOPIC: 16+ characters, or an own ntfy server)."))
            print("WARNING ntfy inbox NOT started: topic", repr(NTFY_IN["topic"]), "on the public ntfy.sh can be "
                  "published to by anyone. Use an own ntfy with access control or an unguessable topic "
                  "(NTFY_INBOX_TOPIC, 16+ characters).", flush=True)
