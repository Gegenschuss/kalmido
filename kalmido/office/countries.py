"""2.40.0 (#1372): the country of a client / of the company is an ISO 3166-1 alpha-2 code from this list (the 249
officially assigned codes). The client picks it by name (Intl.DisplayNames in the browser, static/js/countries.js);
the server accepts nothing else: UK -> GB and EL -> GR (the EU's own codes) are corrected silently, everything else is a
400. Stored values from before that are not in the list stay as they are (the dialogs mark them); the e-invoice refuses
to finalise with one (einvoice._country) instead of writing DE."""
from ..core.i18n import tr
from ..core.errors import BadInput

ISO_ALPHA2 = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF
CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH
GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW
KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG
NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN
SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT
ZA ZM ZW""".split())
FK_COUNTRY_FIX = {"UK": "GB", "EL": "GR"}


def fk_country_code(v):
    """The code of v ('' stays '', None too), corrected (UK -> GB, EL -> GR), None when it is no ISO 3166-1 alpha-2 code."""
    s = str(v or "").strip().upper()
    if not s:
        return ""
    s = FK_COUNTRY_FIX.get(s, s)
    return s if s in ISO_ALPHA2 else None


def fk_country(v, what="country"):
    """fk_country_code or BadInput (400) -- for the API."""
    if v is not None and not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", what))
    code = fk_country_code(v)
    if code is None:
        raise BadInput(tr("Unknown country code: {0} (two letters, ISO 3166-1, e.g. DE, AT, CH)", str(v).strip()[:10]))
    return code


# 2.296.0 B (#3168): the country line of an address is the name in capitals in the language of the sender's country (DIN
# 5008 / UPU: "NIEDERLANDE" on a letter from Germany), not the code; names from countrynames.json (CLDR, built once)
FK_NAME_LANG = {"DE": "de", "AT": "de", "CH": "de", "LI": "de", "LU": "de", "FR": "fr", "BE": "fr", "MC": "fr", "ES": "es",
                "IT": "it", "SM": "it", "VA": "it", "NL": "nl"}
_FK_NAMES = {}


def fk_country_label(code, home):
    """The printed country of an address in a document of a sender in home (ISO code): '' for the sender's own country, the
    name in capitals in home's language (English for other countries), the text as it was for an unknown code."""
    c = fk_country_code(code)
    h = fk_country_code(home) or str(home or "").strip().upper()
    if c == "":
        return ""
    if c is None:
        return str(code).strip()
    if c == h:
        return ""
    if not _FK_NAMES:
        import json
        import os
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "countrynames.json"), encoding="utf-8") as fh:
                _FK_NAMES.update(json.load(fh))
        except (OSError, ValueError):
            _FK_NAMES["en"] = {}
    names = _FK_NAMES.get(FK_NAME_LANG.get(h, "en")) or _FK_NAMES.get("en") or {}
    return str(names.get(c) or c).upper()


# 2.296.0 F (#3168): the 27 member states (ISO codes; GR, not EL) -- reverse charge text and the client's VAT id
FK_EU = frozenset("AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split())


def fk_reverse_case(client, home):
    """'domestic' (client in the sender's country or without one), 'eu' (another member state) or 'other' (CH, GB, US ...)."""
    cc = fk_country_code(client) or str(client or "").strip().upper()
    h = fk_country_code(home) or str(home or "").strip().upper() or "DE"
    if cc in ("", h):
        return "domestic"
    return "eu" if cc in FK_EU and h in FK_EU else "other"
