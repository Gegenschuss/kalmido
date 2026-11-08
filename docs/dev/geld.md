# Money in the database

*Since 2.755.0 (#5293). For developers of Kalmido.*

One rule for every new amount column of the office:

- **Amounts: `NUMERIC(14,2)`** in the office currency (12 places before the point, 2 after). Sums may run in SQL. The
  driver (kalmido/core/pg.py) gives NUMERIC to Python as `int` / `float`; take it into the calculator with
  `office/calc.py dec()` and give it out with `dstr()` ("23.80"). Rates, quantities and prices per unit that need more
  places stay `NUMERIC(14,4)` (office_doc_items.qty / rate, office_payments.amount).
- **Minor units (`BIGINT`, cents) only at the border to a payment provider** (office_pay_*.amount_minor, fee_minor): the
  provider counts that way, nothing else does.
- **A column encrypted at rest stays `TEXT`** (kalmido/core/orgcrypt.py `FIELDS`: office_bank_tx.amount, office_cf_*.amount,
  office_trip_items.amount, office_cc_lines.amount, ...): its ciphertext is no number. Its plain value is decimal text.
- **No new decimal text.** The columns that were TEXT and are not encrypted were turned by kalmido/core/moneycol.py
  (`MC_COLS`: office_doc_items.net / tax_amount, office_cash_entries.amount, office_ledger_entries.amount) at the start of
  2.755: only when every value is the same number afterwards ('' = 0, or NULL where the column may be empty); else the column
  stays TEXT and the start log names it (`migrations: 5293: ...`). `oc_dec_fields` turns those columns back into the
  two-place text the office code and the exports always had, so the answers, the exports and the hash chain of the
  finalised documents (office/chain.py) did not change.
- A new column is a fragment in kalmido/core/migrations.d/ as always (docs/ARCHITECTURE.md, Migrations); changing the type
  of an existing column is a one-way step and goes through a function of its own in `init_db` like `mc_migrate`.
