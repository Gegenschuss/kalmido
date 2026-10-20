"""2.121.0 (#2093): receipt categories with an account of the chart SKR03 / SKR04.

The account of a category lives where the DATEV export reads it (office_settings.data["datev_extf"]: "chart" SKR03 |
SKR04, "cat_accounts" {category casefolded: account}, office/datevin.py of 2.120.0): an own account per category, else
the default the export finds by keywords (DV_CAT_DEFAULTS), else "other expenses". This module only shows it where
categories are chosen (the receipt sheet, the receipt list, the EUeR lines); people change it there through the office
settings (PUT /api/office/settings {"datev_extf": {"cat_accounts": {...}}}, the office admin like every setting), so
the DATEV batch and the EUeR use the same account. Without the input side of the DATEV export the functions answer None
and nothing is shown."""
from .model import office_settings


def ca_settings(c, oid):
    """The DATEV settings of office oid with the input side, or None when this instance has no input side."""
    try:
        from .datevin import dv_cat_account  # noqa: F401 -- 2.120.0 C (#2090)
    except ImportError:
        return None
    from .datev import dx_settings
    st = dx_settings(office_settings(c, oid))
    return st if isinstance(st.get("cat_accounts"), dict) else None


def ca_accounts(c, oid, cats):
    """{chart, own: {category casefolded: account}, categories: {name: {account, default, own}}} for the categories cats
    (and every category with an own account), or None."""
    st = ca_settings(c, oid)
    if st is None:
        return None
    from .datevin import dv_cat_account, dv_cat_default
    own = dict(st.get("cat_accounts") or {})
    names = {x.casefold(): x for x in cats if x}
    for k in own:
        names.setdefault(k, k)
    out = {n: {"account": dv_cat_account(st, n), "default": dv_cat_default(st, n), "own": bool(own.get(k))} for k, n in names.items()}
    return {"chart": st.get("chart") or "SKR03", "own": own, "categories": out}


def ca_euer(c, oid, expenses):
    """Adds "account" to the receipt category lines (key c:...) of the EUeR expenses; unchanged without an input side."""
    st = ca_settings(c, oid)
    if st is None:
        return expenses
    from .datevin import dv_cat_account
    for x in expenses:
        if x.get("key", "").startswith("c:"):
            x["account"] = dv_cat_account(st, x["key"][2:])
    return expenses
