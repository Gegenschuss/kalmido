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
