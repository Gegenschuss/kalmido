"""2.755.0 (#5293): the plain money columns of the office as NUMERIC(14,2) instead of decimal text.

The convention (docs/dev/geld.md): amounts are NUMERIC(14,2) in the office currency; integer minor units (BIGINT, cents) only at the
border to a payment provider (office_pay_*.amount_minor); a column encrypted at rest (core/orgcrypt.py FIELDS) stays TEXT, its
ciphertext is no number (office_bank_tx.amount, office_cf_*.amount, office_trip_items.amount, ...).

MC_COLS names the columns that were TEXT and are not encrypted. mc_migrate (init_db, after the steps) turns each one that is
still TEXT, in its own savepoint (Conn.savepoint), only when every value fits: a number with at most 12 places before and 2 after the point, or
'' (NULL for a nullable column, 0 for a NOT NULL one -- the code read '' as 0 already). A value that does not fit keeps the column
TEXT: the start goes on, the log names the column, the count and the first ids (`migrations: 5293: ...`), and the next start
tries again. The values stay exactly the same: no rounding, the decimal text and the number are equal. The positions of a
finalised document in the hash chain (office/chain.py) need more: there the stored text must be the exact text the number
prints as again (two places, no "-0.00"), else the chain's checksums would change -- such a column stays TEXT as well.

One way: the type does not change back (the version before reads numbers where it read text: its calculator takes both, its
exports print 23.8 instead of 23.80). The driver (core/pg.py) gives NUMERIC to Python as int / float; mc_text turns it back
into the text the code and the exports always had ("23.80"), core/orgcrypt.py oc_dec_fields calls it for every row it loads."""
import sys
from decimal import Decimal

from .pg import qi, system_ctx

MC_COLS = (  # (table, column, nullable): the plain money columns of #5293
    ("office_doc_items", "net", True),
    ("office_doc_items", "tax_amount", True),
    ("office_cash_entries", "amount", False),
    ("office_ledger_entries", "amount", False),
)
MC_TYPE = "NUMERIC(14,2)"
MC_FITS = r"^-?[0-9]{1,12}(\.[0-9]+)?$"
MC_EXACT = r"^-?[0-9]{1,12}\.[0-9]{2}$"
MC_SHOW = 5  # ids named in the log per column
MC_ID = "type:{0}.{1}"  # its row in kalmido_migrations
MC_TABLES = {t for t, _c, _n in MC_COLS}  # the allowlists of qi() (#5296)
MC_NAMES = {c for _t, c, _n in MC_COLS}


def mc_text(v):
    """A money value as the text the office code reads ("23.80"): int / float / Decimal of a NUMERIC column with two places,
    text and None as they are."""
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, (int, float, Decimal)):
        return format(Decimal(str(v)).quantize(Decimal("0.01")), "f")
    return v


def mc_fields(table, d):
    """d (a dict of a row of table) with its money columns as text (mc_text), in place; returns d."""
    for t, col, _n in MC_COLS:
        if t == table and col in d:
            d[col] = mc_text(d[col])
    return d


def mc_type(c, table, col):
    """The data type of table.col (information_schema: 'text', 'numeric', ...) or None when it is missing."""
    r = c.execute("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? AND column_name=?",
                  (table, col)).fetchone()
    return r[0] if r else None


def mc_misfits(c, table, col):
    """[ids] of the rows of table whose col does not fit NUMERIC(14,2) without a change (see the module text); the hash chain's
    positions must be exact text as well."""
    cq = qi(col, MC_NAMES)
    t = f"btrim({cq})"
    fits = f"CASE WHEN {t} ~ '{MC_FITS}' THEN {t}::numeric = round({t}::numeric, 2) ELSE {t} = '' END"
    sql = f"SELECT id FROM {qi(table, MC_TABLES)} x WHERE {cq} IS NOT NULL AND NOT ({fits})"
    if table == "office_doc_items":  # office/chain.py: a chained document's positions as the exact text
        sql += (f" OR ({cq} IS NOT NULL AND NOT ({cq} ~ '{MC_EXACT}' AND {cq} <> '-0.00') AND EXISTS (SELECT 1 FROM office_docs d "
                "WHERE d.id=x.doc_id AND d.chain_seq IS NOT NULL))")
    return [r[0] for r in c.execute(sql + " ORDER BY id").fetchall()]


def mc_migrate(c, at):
    """init_db (2.755.0, #5293): every MC_COLS column that is still TEXT becomes NUMERIC(14,2) when its values fit, each in a
    savepoint of the start's transaction (at = the start's time, ISO) -> {"table.col": "done" | "kept" | "present"}."""
    # 2.755.0 (#5293, review H1): system context for the whole run. The three tables are under FORCE ROW LEVEL SECURITY and the
    # start's connection has no organisation: without it mc_misfits saw only the rows with org_id IS NULL, while the ALTER (DDL
    # ignores row security) rewrote every row -- a chained position's "-0.00" / "23.8" became "0.00" / "23.80" and the hash
    # chain's checksums broke.
    with system_ctx(c):
        return _mc_run(c, at)


def _mc_run(c, at):
    out = {}
    for table, col, nullable in MC_COLS:
        k = f"{table}.{col}"
        typ = mc_type(c, table, col)
        if typ != "text":
            out[k] = "present" if typ else "missing"
            continue
        bad = mc_misfits(c, table, col)
        if bad:
            out[k] = "kept"
            print(f"migrations: 5293: {k} stays TEXT, {len(bad)} value(s) are no amount with two places (ids {', '.join(map(str, bad[:MC_SHOW]))}"
                  f"{', ...' if len(bad) > MC_SHOW else ''}); correct them and start again", file=sys.stderr, flush=True)
            continue
        empty = "NULL" if nullable else "0"
        tq, cq = qi(table, MC_TABLES), qi(col, MC_NAMES)
        dflt = "" if nullable else f", ALTER COLUMN {cq} SET DEFAULT 0"
        try:
            with c.savepoint():
                c.execute(f"ALTER TABLE {tq} ALTER COLUMN {cq} DROP DEFAULT, ALTER COLUMN {cq} TYPE {MC_TYPE} "
                          f"USING (CASE WHEN btrim({cq}) = '' THEN {empty} ELSE btrim({cq})::numeric END){dflt}")
        except Exception as e:  # noqa: BLE001 -- the start goes on with the column as it was, the log says why
            out[k] = "kept"
            print(f"migrations: 5293: {k} stays TEXT: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr, flush=True)
            continue
        c.execute("INSERT INTO kalmido_migrations(id,applied_at,note) VALUES(?,?,'applied') ON CONFLICT(id) DO UPDATE SET "
                  "applied_at=excluded.applied_at, note=excluded.note", (MC_ID.format(table, col), at))
        out[k] = "done"
        print(f"migrations: 5293: {k} is {MC_TYPE} now", flush=True)
    return out
