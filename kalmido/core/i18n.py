"""Server-side translations (tr / trn / N_) and locale helpers (static/i18n/<code>.json, see TRANSLATING.md)."""
import glob
import json
import os
import re
from flask import g, has_request_context

from ..core.config import APP_DIR
from ..core.schema import USER_DEFAULTS


# ---------------------------------------------------------------- i18n
# English is the source language: tr("English text", *args) returns the text in the UI language.
# Translations are the same JSON files the web client loads (static/i18n/<code>.json, see TRANSLATING.md).
# The language is a per-user setting; pushes use the recipient's language. A list value = [one, other] (trn()).
I18N_DIR = os.path.join(APP_DIR, "static", "i18n")


def load_languages():
    """{code: dict} of every static/i18n/*.json; English is built in (the keys themselves)."""
    out = {"en": {"_meta": {"name": "English", "locale": "en-GB"}}}
    for fn in sorted(glob.glob(os.path.join(I18N_DIR, "*.json"))):
        code = os.path.basename(fn)[:-5]
        try:
            with open(fn, encoding="utf-8") as f:
                d = json.load(f)
            if re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})?", code) and code != "en" and isinstance(d, dict):
                out[code] = d
        except (OSError, ValueError) as e:
            print("i18n: skipping", fn, e, flush=True)
    return out


LANGS = load_languages()


def languages():
    """[{code, name}] for the language selector, sorted by name."""
    return sorted(({"code": k, "name": (v.get("_meta") or {}).get("name") or k, "beta": bool((v.get("_meta") or {}).get("beta"))}
                   for k, v in LANGS.items()), key=lambda x: x["name"].casefold())  # 2.11.0: beta = machine-translated


def lang(c=None, uid=None):
    """UI language of a user (request: the logged-in user; no user: the first admin). Works in
    requests and in the watchdog threads."""
    from ..core.db import connect, db, default_uid
    try:
        if uid is None and has_request_context() and getattr(g, "user", None):
            uid = g.user["id"]
        own = c is None and not has_request_context()
        c = c or (db() if has_request_context() else connect())
        try:
            if uid is None:
                uid = default_uid(c)
            r = c.execute("SELECT value FROM user_settings WHERE user_id=? AND key='lang'", (uid,)).fetchone() \
                if uid else None
        finally:
            if own:
                c.close()
        v = r[0] if r else USER_DEFAULTS["lang"]
        return v if v in LANGS else "en"
    except Exception:  # noqa: BLE001
        return "en"


def N_(s):
    """Marks a key for tools/i18n_check.py; translated later by a tr call on the variable."""
    return s


def _key(k):
    """English display of a key: 'Text|ctx' -> 'Text'."""
    b = k.find("|")
    return k[:b] if b > 0 else k


def tr(key, *a, lg=None):
    v = LANGS.get(lg or lang(), {}).get(key)
    s = v if isinstance(v, str) else _key(key)
    return s.format(*a) if a else s


def plural_one(n, lg):
    """The "one" form for n? 1 everywhere; 2.11.0: French also uses it for 0 (like the browser's Intl.PluralRules)."""
    return n == 1 or (n == 0 and str(lg or "").split("-")[0] == "fr")


def trn(one, other, n, *a, lg=None):
    """Plural: one/other picked by n (n == 1 -> one; French: 0 and 1); {0} = n, {1}.. = a."""
    lg = lg or lang()
    v = LANGS.get(lg, {}).get(one)
    s = v[0 if plural_one(n, lg) else 1] if isinstance(v, list) and len(v) == 2 else _key(one if n == 1 else other)
    return s.format(n, *a)


# 2.11.0 (#439): number and short date formats of the server texts (pushes, CSV, public pages) per language
COMMA_LANGS = ("de", "fr", "es", "it", "nl")  # decimal comma (and ";" as the CSV separator, as their spreadsheets expect)


def lg_base(lg=None):
    return str(lg or lang()).split("-")[0]


def dec_comma(lg=None):
    return lg_base(lg) in COMMA_LANGS


def fmt_int(n, lg=None):
    """12345 -> 12,345 (en) / 12.345 (de, es, it, nl) / 12 345 (fr, narrow no-break space)."""
    s = f"{int(n or 0):,}"
    b = lg_base(lg)
    return s.replace(",", "\u202f") if b == "fr" else s.replace(",", ".") if b in COMMA_LANGS else s


def short_day(d, lg=None, year=False):
    """A date in pushes / public pages: 03.10. (de), 3 Oct (en), 3 oct. / 3 ott / 3 okt (the language's short month)."""
    lg = lg or lang()
    b = lg_base(lg)
    if b == "de":
        return d.strftime("%d.%m.%Y" if year else "%d.%m.")
    mons = LANGS.get(lg, {}).get("_months_short")
    if b == "en" or not (isinstance(mons, list) and len(mons) == 12):
        return d.strftime("%d %b %Y" if year else "%d %b")
    return f"{d.day} {mons[d.month - 1]}" + (f" {d.year}" if year else "")
