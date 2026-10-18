"""2.95.0 (#1932): the per diem (Verpflegungsmehraufwand, VMA) of a trip -- the German flat rates per calendar day.

Rates: Germany 28 EUR (a full day of 24 hours) / 14 EUR (the day of arrival / departure of a trip with an overnight stay,
or a single day of more than 8 hours) (section 9 (4a) EStG); abroad the rates of the BMF letter of the year:
2025 = BMF letter of 2 December 2024 (BStBl I 2024 p. 1549), 2026 = BMF letter of 5 December 2025
(IV C 5 - S 2353/00094/007/012). The tables below are taken over from those letters line by line, never estimated; a year
without a table gives no amount but a hint (VMA_YEARS). Countries the letter does not name: the rate of Luxembourg; the
overseas / outer territories: the rate of the mother country; the letter's own extensions (Micronesia = Philippines,
Antigua and Barbuda, Dominica, Grenada, Guyana, St. Kitts and Nevis, St. Lucia, St. Vincent and the Grenadines, Suriname =
Trinidad and Tobago) are in VMA_ALIAS.

The country of a day: where one is before midnight (the letter's rule for days of travel and the days in between); a day
of a trip has country + place (a city of the table, '' = "im Uebrigen" / the whole country). Meals provided cut the rate
of that day by 20 % (breakfast) / 40 % (lunch) / 40 % (dinner) of the FULL day's rate of that day's country, never below 0.
A single-day trip needs its start and end time (more than 8 hours = the partial rate, else nothing); a trip over two days
without an overnight stay (overnight = 0) needs both times too, counts its hours together and gets at most one partial
rate, on the day with the most hours (section 9 (4a) sentence 3 no. 3 EStG). On the day of the return the rate of the last
place of work abroad applies (the default of a trip abroad does that; a day set to Germany gets the German rate).

Pure functions only (no database, no Flask): travel.py stores the trip's fields and calls vma_trip; the report and the
import use the same function."""
from datetime import date, timedelta
from decimal import Decimal

from .calc import dstr, money


# The tables: CODE;place ('' = the whole country / "im Uebrigen");full day;partial day (EUR). Germany is the law's rate.
VMA_YEARS = {2025: "BMF 02.12.2024 (BStBl I 2024 S. 1549)", 2026: "BMF 05.12.2025 (IV C 5 - S 2353/00094/007/012)"}
VMA_HOME = {2025: (28, 14), 2026: (28, 14)}
VMA_DEFAULT = "LU"  # the letter: countries it does not name get the rate of Luxembourg
VMA_ALIAS = {  # the letter's own extensions and the overseas / outer territories (rate of the mother country)
    "FM": "PH", **{k: "TT" for k in ("AG", "DM", "GD", "GY", "KN", "LC", "VC", "SR")},
    **{k: "FR" for k in ("GF", "GP", "MQ", "RE", "YT", "BL", "MF", "PM", "PF", "NC", "WF", "TF")},
    **{k: "NL" for k in ("AW", "CW", "SX", "BQ")}, **{k: "DK" for k in ("GL", "FO")},
    **{k: "US" for k in ("PR", "GU", "VI", "AS", "MP", "UM")},
    **{k: "GB" for k in ("GI", "BM", "KY", "VG", "TC", "MS", "AI", "FK", "SH", "PN", "IO", "GS")},
    **{k: "NO" for k in ("SJ", "BV")}, **{k: "AU" for k in ("CX", "CC", "NF", "HM")}, **{k: "NZ" for k in ("CK", "NU", "TK")},
    "AX": "FI", "EA": "ES", "IC": "ES",
}
VMA_PLACE_ALIAS = {"HK": ("CN", "Hongkong")}  # the letter lists Hong Kong under China
VMA_CUT = {"b": Decimal("0.2"), "l": Decimal("0.4"), "d": Decimal("0.4")}  # breakfast / lunch / dinner of the full day's rate
VMA_MAX_DAYS = 400

# BMF letter of 2 December 2024 (from 1 January 2025)
Y2025 = """
AD;;41;28
AE;;65;44
AF;;30;20
AL;;27;18
AM;;29;20
AO;;40;27
AR;;35;24
AT;;50;33
AU;Canberra;74;49
AU;Sydney;57;38
AU;;57;38
AZ;;44;29
BA;;23;16
BB;;54;36
BD;;46;31
BE;;59;40
BF;;38;25
BG;;22;15
BH;;48;32
BI;;36;24
BJ;;40;27
BN;;45;30
BO;;46;31
BR;Brasilia;51;34
BR;Rio de Janeiro;69;46
BR;Sao Paulo;46;31
BR;;46;31
BT;;27;18
BW;;46;31
BY;;20;13
CA;Ottawa;62;41
CA;Toronto;54;36
CA;Vancouver;63;42
CA;;54;36
CD;;65;44
CF;;53;36
CG;;62;41
CH;Genf;66;44
CH;;64;43
CI;;59;40
CL;;44;29
CM;;56;37
CN;Chengdu;41;28
CN;Hongkong;71;48
CN;Kanton;36;24
CN;Peking;30;20
CN;Shanghai;58;39
CN;;48;32
CO;;34;23
CR;;60;40
CU;;51;34
CV;;38;25
CY;;42;28
CZ;;32;21
DJ;;77;52
DK;;75;50
DO;;50;33
DZ;;47;32
EC;;27;18
EE;;29;20
EG;;50;33
ER;;46;31
ES;Barcelona;34;23
ES;Kanarische Inseln;36;24
ES;Madrid;42;28
ES;Palma de Mallorca;44;29
ES;;34;23
ET;;44;29
FI;;54;36
FJ;;32;21
FR;Paris sowie die Departments 77, 78, 91 bis 95;58;39
FR;;53;36
GA;;64;43
GB;London;66;44
GB;;52;35
GE;;45;30
GH;;46;31
GM;;40;27
GN;;59;40
GQ;;42;28
GR;Athen;40;27
GR;;36;24
GT;;46;31
GW;;32;21
HN;;57;38
HR;;46;31
HT;;58;39
HU;;32;21
ID;;45;30
IE;;58;39
IL;;66;44
IN;Bangalore;42;28
IN;Chennai;22;15
IN;Kalkutta;32;21
IN;Mumbai;53;36
IN;Neu Delhi;46;31
IN;;22;15
IR;;33;22
IS;;62;41
IT;Mailand;42;28
IT;Rom;48;32
IT;;42;28
JM;;39;26
JO;;57;38
JP;Tokio;50;33
JP;Osaka;33;22
JP;;33;22
KE;;51;34
KG;;27;18
KH;;42;28
KP;;28;19
KR;;48;32
KW;;56;37
KZ;;33;22
LA;;35;24
LB;;69;46
LI;;56;37
LK;;36;24
LR;;65;44
LS;;28;19
LT;;26;17
LU;;63;42
LV;;35;24
LY;;63;42
MA;;41;28
MC;;52;35
MD;;26;17
ME;;32;21
MG;;33;22
MH;;63;42
MK;;27;18
ML;;38;25
MM;;23;16
MN;;23;16
MR;;35;24
MT;;46;31
MU;;44;29
MV;;70;47
MW;;41;28
MX;;48;32
MY;;36;24
MZ;;51;34
NA;;30;20
NE;;42;28
NG;;46;31
NI;;46;31
NL;;47;32
NO;;75;50
NP;;36;24
NZ;;58;39
OM;;64;43
PA;;41;28
PE;;34;23
PG;;59;40
PH;;41;28
PK;Islamabad;23;16
PK;;34;23
PL;Breslau;34;23
PL;Warschau;40;27
PL;;34;23
PT;;32;21
PW;;51;34
PY;;39;26
QA;;56;37
RO;Bukarest;32;21
RO;;27;18
RS;;27;18
RU;Moskau;30;20
RU;St. Petersburg;28;19
RU;;28;19
RW;;44;29
SA;Djidda;57;38
SA;Riad;56;37
SA;;56;37
SD;;33;22
SE;;66;44
SG;;71;48
SI;;38;25
SK;;33;22
SL;;57;38
SM;;34;23
SN;;42;28
SS;;51;34
ST;;36;24
SV;;65;44
SY;;38;25
TD;;42;28
TG;;39;26
TH;;36;24
TJ;;27;18
TM;;28;19
TN;;40;27
TO;;29;20
TR;Ankara;32;21
TR;Izmir;44;29
TR;;24;16
TT;;66;44
TW;;51;34
TZ;;44;29
UA;;26;17
UG;;41;28
US;Atlanta;77;52
US;Boston;63;42
US;Chicago;65;44
US;Houston;62;41
US;Los Angeles;64;43
US;Miami;65;44
US;New York City;66;44
US;San Francisco;59;40
US;Washington, D. C.;66;44
US;;59;40
UY;;40;27
UZ;;34;23
VA;;48;32
VE;;45;30
VN;;36;24
WS;;39;26
XK;;24;16
YE;;24;16
ZA;Kapstadt;33;22
ZA;Johannesburg;36;24
ZA;;29;20
ZM;;38;25
ZW;;63;42
"""
# BMF letter of 5 December 2025 (from 1 January 2026)
Y2026 = """
AD;;45;30
AE;;81;54
AL;;33;22
AM;;29;20
AO;;40;27
AR;;42;28
AT;;50;33
AU;Canberra;74;49
AU;Sydney;57;38
AU;;57;38
AZ;;44;29
BA;;32;21
BB;;54;36
BD;;46;31
BE;;59;40
BF;;39;26
BG;;38;25
BH;;48;32
BI;;58;39
BJ;;40;27
BN;;45;30
BO;;46;31
BR;Brasilia;51;34
BR;Rio de Janeiro;69;46
BR;Sao Paulo;46;31
BR;;46;31
BT;;27;18
BW;;40;27
BY;;21;14
CA;Ottawa;62;41
CA;Toronto;54;36
CA;Vancouver;63;42
CA;;54;36
CD;;65;44
CF;;53;36
CG;;53;36
CH;Bern;82;55
CH;Genf;70;47
CH;;70;47
CI;;60;40
CL;;44;29
CM;;56;37
CN;Hongkong;83;56
CN;Peking;57;38
CN;Shanghai;48;32
CN;;48;32
CO;;34;23
CR;;60;40
CU;;51;34
CV;;38;25
CY;;42;28
CZ;;32;21
DJ;;77;52
DK;;75;50
DO;;50;33
DZ;;47;32
EC;;27;18
EE;;39;26
EG;;50;33
ER;;46;31
ES;Barcelona;34;23
ES;Kanarische Inseln;36;24
ES;Madrid;42;28
ES;Palma de Mallorca;44;29
ES;;34;23
ET;;44;29
FI;;54;36
FJ;;32;21
FR;Paris sowie die Departments 77, 78, 91 bis 95;58;39
FR;;53;36
GA;;64;43
GB;London;66;44
GB;;52;35
GE;;45;30
GH;;46;31
GM;;40;27
GN;;59;40
GQ;;42;28
GR;Athen;40;27
GR;;36;24
GT;;46;31
GW;;32;21
HN;;57;38
HR;;46;31
HU;;32;21
ID;;45;30
IE;;64;43
IL;;59;40
IN;Bangalore;42;28
IN;Chennai;22;15
IN;Kalkutta;32;21
IN;Mumbai;53;36
IN;Neu Delhi;46;31
IN;;22;15
IR;;33;22
IS;;62;41
IT;Mailand;42;28
IT;Rom;48;32
IT;;42;28
JM;;39;26
JO;;57;38
JP;Tokio;50;33
JP;Osaka;33;22
JP;;33;22
KE;;48;32
KG;;35;24
KH;;42;28
KR;;39;26
KW;;63;42
KZ;;33;22
LA;;35;24
LB;;69;46
LI;;57;38
LK;;36;24
LR;;65;44
LS;;28;19
LT;;48;32
LU;;63;42
LV;;46;31
MA;;41;28
MC;;52;35
MD;;26;17
ME;;32;21
MG;;33;22
MH;;45;30
MK;;27;18
ML;;42;28
MM;;23;16
MN;;23;16
MR;;35;24
MT;;59;40
MU;;44;29
MV;;70;47
MW;;41;28
MX;;40;27
MY;;36;24
MZ;;51;34
NA;;28;19
NE;;42;28
NG;;52;35
NI;;46;31
NL;;58;39
NO;;75;50
NP;;33;22
NZ;;58;39
OM;;64;43
PA;;41;28
PE;;52;35
PG;;59;40
PH;;41;28
PK;;41;28
PL;Breslau;34;23
PL;Warschau;40;27
PL;;34;23
PT;;32;21
PW;;51;34
PY;;39;26
QA;;81;54
RO;;38;25
RS;;27;18
RU;Moskau;30;20
RU;St. Petersburg;28;19
RU;;28;19
RW;;44;29
SA;Djidda;57;38
SA;Riad;56;37
SA;;56;37
SE;;66;44
SG;;71;48
SI;;38;25
SK;;33;22
SL;;57;38
SM;;34;23
SN;;48;32
SS;;51;34
ST;;36;24
SV;;65;44
TD;;42;28
TG;;36;24
TH;;36;24
TJ;;27;18
TM;;28;19
TN;;40;27
TO;;29;20
TR;Ankara;32;21
TR;Izmir;44;29
TR;;24;16
TT;;66;44
TW;;51;34
TZ;;44;29
UA;;33;22
UG;;45;30
US;Atlanta;77;52
US;Boston;63;42
US;Chicago;65;44
US;Houston;62;41
US;Los Angeles;64;43
US;Miami;65;44
US;New York City;66;44
US;San Francisco;59;40
US;Washington, D. C.;66;44
US;;59;40
UY;;40;27
UZ;;32;21
VA;;48;32
VE;;51;34
VN;;36;24
WS;;39;26
XK;;24;16
ZA;Kapstadt;33;22
ZA;Johannesburg;36;24
ZA;;29;20
ZM;;38;25
ZW;;63;42
"""
# code;German name;English name;the letter's own name (when it differs)
NAMES = """
AD;Andorra;Andorra;
AE;Vereinigte Arabische Emirate;United Arab Emirates;
AF;Afghanistan;Afghanistan;
AG;Antigua und Barbuda;Antigua & Barbuda;
AL;Albanien;Albania;
AM;Armenien;Armenia;
AO;Angola;Angola;
AR;Argentinien;Argentina;
AT;Österreich;Austria;
AU;Australien;Australia;
AZ;Aserbaidschan;Azerbaijan;
BA;Bosnien und Herzegowina;Bosnia & Herzegovina;
BB;Barbados;Barbados;
BD;Bangladesch;Bangladesh;
BE;Belgien;Belgium;
BF;Burkina Faso;Burkina Faso;
BG;Bulgarien;Bulgaria;
BH;Bahrain;Bahrain;
BI;Burundi;Burundi;
BJ;Benin;Benin;
BN;Brunei Darussalam;Brunei;Brunei
BO;Bolivien;Bolivia;
BR;Brasilien;Brazil;
BT;Bhutan;Bhutan;
BW;Botsuana;Botswana;
BY;Belarus;Belarus;Weißrussland
CA;Kanada;Canada;
CD;Kongo-Kinshasa;Congo - Kinshasa;Kongo, Demokratische Republik
CF;Zentralafrikanische Republik;Central African Republic;
CG;Kongo-Brazzaville;Congo - Brazzaville;Kongo, Republik
CH;Schweiz;Switzerland;
CI;Côte d’Ivoire;Côte d’Ivoire;
CL;Chile;Chile;
CM;Kamerun;Cameroon;
CN;China;China;
CO;Kolumbien;Colombia;
CR;Costa Rica;Costa Rica;
CU;Kuba;Cuba;
CV;Cabo Verde;Cape Verde;Kap Verde
CY;Zypern;Cyprus;
CZ;Tschechien;Czechia;Tschechische Republik
DE;Deutschland;Germany;
DJ;Dschibuti;Djibouti;
DK;Dänemark;Denmark;
DM;Dominica;Dominica;
DO;Dominikanische Republik;Dominican Republic;
DZ;Algerien;Algeria;
EC;Ecuador;Ecuador;
EE;Estland;Estonia;
EG;Ägypten;Egypt;
ER;Eritrea;Eritrea;
ES;Spanien;Spain;
ET;Äthiopien;Ethiopia;
FI;Finnland;Finland;
FJ;Fidschi;Fiji;
FM;Mikronesien;Micronesia;
FR;Frankreich;France;
GA;Gabun;Gabon;
GB;Vereinigtes Königreich;United Kingdom;Großbritannien und Nordirland
GD;Grenada;Grenada;
GE;Georgien;Georgia;
GH;Ghana;Ghana;
GM;Gambia;Gambia;
GN;Guinea;Guinea;
GQ;Äquatorialguinea;Equatorial Guinea;
GR;Griechenland;Greece;
GT;Guatemala;Guatemala;
GW;Guinea-Bissau;Guinea-Bissau;
GY;Guyana;Guyana;
HK;Hongkong;Hong Kong;
HN;Honduras;Honduras;
HR;Kroatien;Croatia;
HT;Haiti;Haiti;
HU;Ungarn;Hungary;
ID;Indonesien;Indonesia;
IE;Irland;Ireland;
IL;Israel;Israel;
IN;Indien;India;
IR;Iran;Iran;
IS;Island;Iceland;
IT;Italien;Italy;
JM;Jamaika;Jamaica;
JO;Jordanien;Jordan;
JP;Japan;Japan;
KE;Kenia;Kenya;
KG;Kirgisistan;Kyrgyzstan;
KH;Kambodscha;Cambodia;
KN;St. Kitts und Nevis;St. Kitts & Nevis;
KP;Nordkorea;North Korea;Korea, Demokratische Volksrepublik
KR;Südkorea;South Korea;Korea, Republik
KW;Kuwait;Kuwait;
KZ;Kasachstan;Kazakhstan;
LA;Laos;Laos;
LB;Libanon;Lebanon;
LC;St. Lucia;St. Lucia;
LI;Liechtenstein;Liechtenstein;
LK;Sri Lanka;Sri Lanka;
LR;Liberia;Liberia;
LS;Lesotho;Lesotho;
LT;Litauen;Lithuania;
LU;Luxemburg;Luxembourg;
LV;Lettland;Latvia;
LY;Libyen;Libya;
MA;Marokko;Morocco;
MC;Monaco;Monaco;
MD;Republik Moldau;Moldova;Moldau, Republik
ME;Montenegro;Montenegro;
MG;Madagaskar;Madagascar;
MH;Marshallinseln;Marshall Islands;Marshall Inseln
MK;Nordmazedonien;North Macedonia;
ML;Mali;Mali;
MM;Myanmar;Myanmar (Burma);
MN;Mongolei;Mongolia;
MR;Mauretanien;Mauritania;
MT;Malta;Malta;
MU;Mauritius;Mauritius;
MV;Malediven;Maldives;
MW;Malawi;Malawi;
MX;Mexiko;Mexico;
MY;Malaysia;Malaysia;
MZ;Mosambik;Mozambique;
NA;Namibia;Namibia;
NE;Niger;Niger;
NG;Nigeria;Nigeria;
NI;Nicaragua;Nicaragua;
NL;Niederlande;Netherlands;
NO;Norwegen;Norway;
NP;Nepal;Nepal;
NZ;Neuseeland;New Zealand;
OM;Oman;Oman;
PA;Panama;Panama;
PE;Peru;Peru;
PG;Papua-Neuguinea;Papua New Guinea;
PH;Philippinen;Philippines;
PK;Pakistan;Pakistan;
PL;Polen;Poland;
PT;Portugal;Portugal;
PW;Palau;Palau;
PY;Paraguay;Paraguay;
QA;Katar;Qatar;
RO;Rumänien;Romania;
RS;Serbien;Serbia;
RU;Russland;Russia;Russische Föderation
RW;Ruanda;Rwanda;
SA;Saudi-Arabien;Saudi Arabia;
SD;Sudan;Sudan;
SE;Schweden;Sweden;
SG;Singapur;Singapore;
SI;Slowenien;Slovenia;
SK;Slowakei;Slovakia;Slowakische Republik
SL;Sierra Leone;Sierra Leone;
SM;San Marino;San Marino;
SN;Senegal;Senegal;
SR;Suriname;Suriname;
SS;Südsudan;South Sudan;
ST;São Tomé und Príncipe;São Tomé & Príncipe;São Tomé – Príncipe
SV;El Salvador;El Salvador;
SY;Syrien;Syria;
TD;Tschad;Chad;
TG;Togo;Togo;
TH;Thailand;Thailand;
TJ;Tadschikistan;Tajikistan;
TM;Turkmenistan;Turkmenistan;
TN;Tunesien;Tunisia;
TO;Tonga;Tonga;
TR;Türkei;Türkiye;
TT;Trinidad und Tobago;Trinidad & Tobago;
TW;Taiwan;Taiwan;
TZ;Tansania;Tanzania;
UA;Ukraine;Ukraine;
UG;Uganda;Uganda;
US;Vereinigte Staaten;United States;Vereinigte Staaten von Amerika (USA)
UY;Uruguay;Uruguay;
UZ;Usbekistan;Uzbekistan;
VA;Vatikanstadt;Vatican City;Vatikanstaat
VC;St. Vincent und die Grenadinen;St. Vincent & Grenadines;
VE;Venezuela;Venezuela;
VN;Vietnam;Vietnam;
WS;Samoa;Samoa;
XK;Kosovo;Kosovo;
YE;Jemen;Yemen;
ZA;Südafrika;South Africa;
ZM;Sambia;Zambia;
ZW;Simbabwe;Zimbabwe;
"""


def _table(txt):
    out = {}
    for ln in txt.strip().splitlines():
        code, place, full, part = ln.split(";")
        out.setdefault(code, {})[place] = (int(full), int(part))
    return out


VMA_TABLES = {2025: _table(Y2025), 2026: _table(Y2026)}
VMA_NAMES = {}  # code -> (German name, English name, the letter's own name or '')
for _ln in NAMES.strip().splitlines():
    _c, _de, _en, _bmf = _ln.split(";")
    VMA_NAMES[_c] = (_de, _en, _bmf)


def vma_country_name(code, lg="de"):
    n = VMA_NAMES.get(code)
    if not n:
        return code or ""
    return n[0] if lg == "de" else n[1]


def vma_rate(year, code, place=""):
    """(full, partial, code used, place used, how) for a day in country code (ISO) / place in year, or None when the year has
    no table. how: '' = the country's own rate, 'alias' = the rate of the mother country / the letter's extension,
    'lu' = not named in the letter -> Luxembourg."""
    try:
        year = int(year)
    except (TypeError, ValueError):
        return None
    if year not in VMA_TABLES:
        return None
    code = (code or "DE").upper()
    place = place or ""
    if code == "DE":
        f, p = VMA_HOME[year]
        return f, p, "DE", "", ""
    how = ""
    if code in VMA_PLACE_ALIAS:
        code, place = VMA_PLACE_ALIAS[code]
    tab = VMA_TABLES[year]
    if code not in tab and code in VMA_ALIAS:
        code, place, how = VMA_ALIAS[code], "", "alias"
    if code not in tab:
        code, place, how = VMA_DEFAULT, "", "lu"
    places = tab[code]
    if place not in places:
        place = ""
    if place not in places:  # a country with cities only (never in the letters, but safe)
        place = next(iter(places))
    f, p = places[place]
    return f, p, code, place, how


def vma_places(year):
    """{code: [place, ...]} of the year's table ('' first = the whole country / "im Uebrigen"); None without a table."""
    try:
        tab = VMA_TABLES.get(int(year))
    except (TypeError, ValueError):
        return None
    if tab is None:
        return None
    return {c: sorted(p, key=lambda x: (x != "", x.lower())) for c, p in tab.items()}


def _mins(s):
    s = str(s or "").strip()
    if len(s) == 5 and s[2] == ":" and s[:2].isdigit() and s[3:].isdigit():
        h, m = int(s[:2]), int(s[3:])
        if h < 24 and m < 60:
            return h * 60 + m
    return None


def vma_dates(date_from, date_to):
    try:
        d0 = date.fromisoformat(date_from)
        d1 = date.fromisoformat(date_to or date_from)
    except (TypeError, ValueError):
        return []
    if d1 < d0 or (d1 - d0).days >= VMA_MAX_DAYS:
        return []
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def vma_trip(trip):
    """The per diem of trip {date_from, date_to, country, t_start, t_end, overnight, vma_days: [{date, country, place, b, l, d}],
    vma_off} for ONE person:
    {amount: "372.00" | None, cut: "0.00", lines: [{country, place, kind full|partial, n, rate, sum, how}],
     days: [{date, country, place, kind full|partial|none, rate, cut, amount}], hints: [{key, year?}], source: [...]}.
    hints: off (no per diem for this trip), dates, times (a single day without start / end), short (8 hours or less),
    year (no table for that year -> amount None), alias / lu (the rate of another country was used)."""
    out = {"amount": None, "cut": "0.00", "lines": [], "days": [], "hints": [], "source": []}
    if trip.get("vma_off"):
        out["hints"].append({"key": "off"})
        out["amount"] = "0.00"
        return out
    ds = vma_dates(trip.get("date_from") or "", trip.get("date_to") or "")
    if not ds:
        out["hints"].append({"key": "dates"})
        return out
    over = {}
    for x in trip.get("vma_days") or []:
        if isinstance(x, dict) and x.get("date") in ds:
            over[x["date"]] = x
    base = (trip.get("country") or "DE").upper()
    n = len(ds)
    kinds = ["full"] * n
    if n == 1:
        a, b = _mins(trip.get("t_start")), _mins(trip.get("t_end"))
        if a is None or b is None or b <= a:
            out["hints"].append({"key": "times"})
            return out
        kinds = ["partial" if b - a > 8 * 60 else "none"]
    elif n == 2 and not trip.get("overnight"):
        a, b = _mins(trip.get("t_start")), _mins(trip.get("t_end"))
        if a is None or b is None:  # review: like a single day, the hours are needed
            out["hints"].append({"key": "times"})
            return out
        d1, d2 = 24 * 60 - a, b  # over midnight without a stay: the hours count together, on the day with the most of them
        k = "partial" if d1 + d2 > 8 * 60 else "none"
        kinds = [k, "none"] if d1 > d2 else ["none", k]
    else:
        kinds[0] = kinds[-1] = "partial"
    if all(k == "none" for k in kinds):
        out["hints"].append({"key": "short"})
    years = sorted({int(d[:4]) for d in ds})
    missing = [y for y in years if y not in VMA_TABLES]
    if missing:
        out["hints"] += [{"key": "year", "year": y} for y in missing]
        return out
    total, cut_total = Decimal(0), Decimal(0)
    lines = {}
    seen_how = set()
    for d, k in zip(ds, kinds):
        o = over.get(d) or {}
        code = (o.get("country") or base).upper()
        r = vma_rate(int(d[:4]), code, o.get("place") or (trip.get("place") if code == base else "") or "")
        full, part, used, place, how = r
        if how:
            seen_how.add((how, code, used))
        rate = Decimal(full if k == "full" else part if k == "partial" else 0)
        cut = Decimal(0)
        if k != "none":
            cut = sum((Decimal(full) * f for m, f in VMA_CUT.items() if o.get(m)), Decimal(0))
            cut = min(cut, rate)
        amt = rate - cut
        total += amt
        cut_total += cut
        out["days"].append({"date": d, "country": code, "rate_country": used, "place": place, "kind": k, "rate": dstr(rate),
                            "cut": dstr(cut), "amount": dstr(amt), "meals": [m for m in VMA_CUT if o.get(m)]})
        if k != "none":
            key = (used, place, k, int(rate))
            ln = lines.setdefault(key, {"country": used, "place": place, "kind": k, "n": 0, "rate": dstr(rate), "sum": Decimal(0), "how": how})
            ln["n"] += 1
            ln["sum"] += rate
    order = list(lines.values())  # in the order of the days
    for ln in order:
        ln["sum"] = dstr(ln["sum"])
    out["lines"] = order
    for how, code, used in sorted(seen_how):
        out["hints"].append({"key": how, "country": code, "used": used})
    out["amount"] = dstr(money(total))
    out["cut"] = dstr(money(cut_total))
    out["source"] = [VMA_YEARS[y] for y in years]
    return out


def vma_breakdown(v, lg="de", cur="EUR"):
    """The spreadsheet's text of a result of vma_trip: "Griechenland: 2 x 24 EUR + 9 x 36 EUR = 372 EUR" per country (one
    line per country, in the order of the days), plus the cut for meals."""
    by = {}
    for ln in v.get("lines") or []:
        by.setdefault((ln["country"], ln["place"]), []).append(ln)
    out = []
    sym = "€" if cur == "EUR" else cur
    def num(s):
        d = Decimal(s)
        t = format(d.quantize(Decimal(1)) if d == d.to_integral() else d, "f")
        return t.replace(".", ",") if lg == "de" else t
    for (code, place), lns in by.items():
        name = vma_country_name(code, lg) + (f" ({place})" if place else "")
        parts = " + ".join(f"{x['n']} × {num(x['rate'])} {sym}" for x in lns)
        s = sum((Decimal(x["sum"]) for x in lns), Decimal(0))
        out.append(f"{name}: {parts} = {num(str(s))} {sym}")
    return out
