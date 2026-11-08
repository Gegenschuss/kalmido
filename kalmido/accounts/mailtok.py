"""2.674.0 (#4382 finding 5): the secret tokens of the plus addresses (mail_tokens, hub_tokens, doc_mail) no longer lie in
the database as plain text.

A new token is stored sealed with the server key in the column token (seal, purpose MTK_SEAL; the address stays visible in
the settings) and as its SHA-256 in token_hash; a mail is matched by that hash (mtk_where). A row of an older version (token
in plain text, token_hash NULL) keeps working: mtk_where also finds it by the plain token. Turning those old rows into sealed
ones is a later one-way step (the version before could not read them any more), so it is not done here.

2.705.0 (#5151): that step, done by the watchdog (notify/push.py, mtk_reseal_tick, daily): the rows of an older version are
sealed + hashed in place. Not at once: only MTK_RESEAL_DAYS after the first start of a version with this step (setting
MTK_SINCE), so going back to the version before 2.674 within that time still finds every address. After it, such a version
would no longer find the old addresses (a version from 2.674 on still does: by the hash, and it opens the sealed token).

  stored, h = mtk_new(c, tok)            # INSERT ... (token, token_hash) VALUES (stored, h)
  w, a = mtk_where(tok)                  # SELECT * FROM hub_tokens WHERE {w}
  mail_addr(mtk_plain(c, r["token"]))    # the address for the person"""
import hashlib
import time
from datetime import timedelta

from ..core.db import gset, gsetting, iso, now_utc, parse_iso
from ..core.pg import system_ctx

MTK_SEAL = "mailtok"
MTK_TABLES = ("mail_tokens", "hub_tokens", "doc_mail")  # 2.705.0 (#5151): token is the primary key of each
MTK_RESEAL_DAYS = 14     # 2.705.0 (#5151): the old rows stay plain this long after the first start with mtk_reseal_tick
MTK_SINCE = "mtk_reseal_since"
MTK_BATCH = 500
MTK_RUN = {"at": 0.0}


def mtk_hash(tok):
    return hashlib.sha256(str(tok or "").encode()).hexdigest()


def mtk_new(c, tok):
    """(the value for the column token: sealed, the value for token_hash) of a new token."""
    from ..accounts.login import seal
    return seal(c, MTK_SEAL, tok), mtk_hash(tok)


def mtk_plain(c, stored):
    """The token of a stored value: a sealed one opened, an old plain one as it is ('' for none / one that does not open)."""
    if not stored:
        return ""
    if not str(stored).startswith("v1."):  # a plain token never has a dot (token_urlsafe, 'd' + ..., letters and digits)
        return stored
    from ..accounts.login import unseal
    try:
        return unseal(c, MTK_SEAL, stored)
    except Exception:  # noqa: BLE001 -- another server key: no address rather than an error page
        return ""


def mtk_where(tok, alias=""):
    """(SQL condition, args) that finds the row of the token tok of an incoming mail: by its hash, a row of an older version
    (no hash yet) by its plain token."""
    p = f"{alias}." if alias else ""
    return f"({p}token_hash=? OR ({p}token_hash IS NULL AND {p}token=?))", (mtk_hash(tok), str(tok or ""))


def mtk_row_where(r):
    """2.705.0 (#5151, review F1): (SQL condition, args) of the row r read before: by its stored token, or by its hash when
    mtk_reseal_tick sealed it in between (the token is the primary key and changes then)."""
    return "(token=? OR token_hash=?)", (r["token"], r["token_hash"] or mtk_hash(r["token"]))


def mtk_reseal_tick(c, force=False):
    """2.705.0 (#5151): daily (watchdog, system context). The first run notes its time (MTK_SINCE) and changes nothing;
    from MTK_RESEAL_DAYS after it, every row of MTK_TABLES still in plain text (token_hash NULL) gets its token sealed and
    its hash, in batches each committed on its own. Returns the number of rows sealed."""
    if not force and time.time() - MTK_RUN["at"] < 86400:
        return 0
    MTK_RUN["at"] = time.time()
    since = gsetting(c, MTK_SINCE)
    if not since:
        gset(c, MTK_SINCE, iso(now_utc()))
        c.commit()
        return 0
    try:
        if parse_iso(since) + timedelta(days=MTK_RESEAL_DAYS) > now_utc():
            return 0
    except (TypeError, ValueError):
        return 0
    n = 0
    with system_ctx(c):  # the addresses of every person and organisation; nothing is shown to anybody
        for t in MTK_TABLES:  # fixed names, no input
            while True:
                rows = c.execute(f"SELECT token FROM {t} WHERE token_hash IS NULL AND token<>'' AND token NOT LIKE 'v1.%' "
                                 f"LIMIT {MTK_BATCH}").fetchall()
                done = 0
                for r in rows:
                    stored, h = mtk_new(c, r["token"])
                    done += c.execute(f"UPDATE {t} SET token=?, token_hash=? WHERE token=? AND token_hash IS NULL",
                                      (stored, h, r["token"])).rowcount or 0
                c.commit()
                n += done
                if len(rows) < MTK_BATCH or not done:
                    break
    if n:
        print("plus addresses sealed:", n, flush=True)
    return n
