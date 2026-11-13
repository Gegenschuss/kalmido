"""2.560.0 C (#4700): office_texts gets created_at / updated_at, so a text block (letter blocks, the office's texts) saved from a
dialog that is not fresh any more answers 409 instead of overwriting (core/conflict.py ccf_check, office/model.py office_update).
Old rows keep '' (no check until their next save); new columns only, older versions ignore them."""
MIGRATIONS = [
    ("office_texts", "created_at", "ALTER TABLE office_texts ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ("office_texts", "updated_at", "ALTER TABLE office_texts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP"),
]
