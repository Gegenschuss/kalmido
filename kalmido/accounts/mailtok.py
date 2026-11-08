"""2.674.0 (#4382 finding 5): the secret tokens of the plus addresses (mail_tokens, hub_tokens, doc_mail) no longer lie in
the database as plain text.

A new token is stored sealed with the server key in the column token (seal, purpose MTK_SEAL; the address stays visible in
the settings) and as its SHA-256 in token_hash; a mail is matched by that hash (mtk_where). A row of an older version (token
in plain text, token_hash NULL) keeps working: mtk_where also finds it by the plain token. Turning those old rows into sealed
ones is a later one-way step (the version before could not read them any more), so it is not done here.

  stored, h = mtk_new(c, tok)            # INSERT ... (token, token_hash) VALUES (stored, h)
  w, a = mtk_where(tok)                  # SELECT * FROM hub_tokens WHERE {w}
  mail_addr(mtk_plain(c, r["token"]))    # the address for the person"""
import hashlib

MTK_SEAL = "mailtok"


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
