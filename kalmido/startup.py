"""Start-up: init_db() and the background threads (watchdog, update check, calendars, backups, webhooks, mail, git)."""
import os
import threading

from .core.config import NTFY_IN, ntfy_inbox_allowed, UPDATE_CHECK_ENV
from .core.i18n import N_
from .core.db import connect, init_db
from .core.pages import ntfy_inbox_loop
from .core.instance import update_loop
from .notify.push import watchdog
from .notify.alerts import aa_now
from .calendars.subscriptions import cal_loop, CAL_ON
from .admin.backup import backup_loop, BK_ON_ENV
from .api.v1 import WH_ON
from .integrations.webhooks import wh_loop
from .integrations.git import git_loop
from .integrations.mail import MAIL_IN_ON, mail_loop
from .events.model import migrate_family_events


init_db()
_c = connect()
try:
    migrate_family_events(_c)  # 2.21.0 (#659), once: the family events of 2.19 (tasks with people) become events
finally:
    _c.close()
from .admin.clientip import ip_startup_check
ip_startup_check()  # 2.33.0 (#834): many accounts from one private address -> warn in the log
if os.environ.get("TASKS_WATCHDOG", "1") == "1":
    threading.Thread(target=watchdog, daemon=True).start()
    if UPDATE_CHECK_ENV:
        threading.Thread(target=update_loop, daemon=True).start()
    if CAL_ON:  # calendar subscriptions: background sync
        threading.Thread(target=cal_loop, daemon=True).start()
    if BK_ON_ENV:  # automatic backups (schedule + retention; off until an admin turns them on)
        threading.Thread(target=backup_loop, daemon=True).start()
    if WH_ON:  # webhook deliveries (queue + retries)
        threading.Thread(target=wh_loop, daemon=True).start()
    if MAIL_IN_ON:  # 2.17.0 (#443): new tasks by e-mail (one mailbox, polled)
        threading.Thread(target=mail_loop, daemon=True).start()
    threading.Thread(target=git_loop, daemon=True).start()  # 2.2.0 (#271): repositories of project lists (idle without any)
    if NTFY_IN["token"] and NTFY_IN["url"]:
        if ntfy_inbox_allowed():
            threading.Thread(target=ntfy_inbox_loop, daemon=True).start()
        else:
            aa_now("integration", "inbox:refused", N_("The ntfy share inbox was not started: its topic on the public ntfy.sh is guessable, anyone could publish to it (NTFY_INBOX_TOPIC: 16+ characters, or an own ntfy server)."))
            print("WARNING ntfy inbox NOT started: topic", repr(NTFY_IN["topic"]), "on the public ntfy.sh can be "
                  "published to by anyone. Use an own ntfy with access control or an unguessable topic "
                  "(NTFY_INBOX_TOPIC, 16+ characters).", flush=True)
