#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.576.0 part D (#4188): the .xlsx import reads its parts as a stream (iterparse) and stops at the limits; at most two
imports read at the same time. Own container (start.sh). Invented names only, the files are made here.
 - memory (measured with tracemalloc in a Python process of the app container, the app's own reader functions): a sheet
   with far more filled cells than the limit is refused early - the peak stays a fraction of what a whole tree of the same
   part takes (measured in the same process as the reference, so without the fix the check is red); the legacy import
   stops reading after its row limit; a sharedStrings part with too many entries is refused early as well
 - the guards stay: DOCTYPE, ENTITY (also cut between two read pieces), two-byte encodings = 400
 - a third import while two read: 429 with a clear text (the app's error answer), afterwards it reads again
 - fable review (limits made small in the probe): other elements between the cells of a row count until the row ends
   (too large); other elements between rows / shared strings leave the tree; nesting deeper than 64 is refused; one cell
   with ever new shared formulas is bounded
 - over HTTP: a normal file (shared strings, a drop-down list from another sheet, a shared formula) still imports; a file
   with too many cells is a 400 naming the limit; the legacy preview of a person without an organisation still reads
usage: p2576_d_import_test.py <datadir>      (P2576D_NOSTART=1 = the server already runs)"""
# freelancer-matrix: sheets
import io
import json
import os
import subprocess
import sys
import zipfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, CT, check, sess  # noqa: E402,F401

FEAT = FEATURES + ",sheets,office"

# the .xlsx maker, used here and inside the container (the same text)
GEN = r'''
import io, zipfile

def xlsx_parts(sheets, strings=None, extra=None):
    """sheets: [(name, sheet xml body inside <sheetData>, tail after </sheetData>)] -> {part: bytes}"""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    wb = "".join(f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, (n, _b, _t) in enumerate(sheets))
    rels = "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                   for i in range(len(sheets)))
    p = {"[Content_Types].xml": b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
         "xl/workbook.xml": f'<?xml version="1.0"?><workbook {ns} {rns}><sheets>{wb}</sheets></workbook>'.encode(),
         "xl/_rels/workbook.xml.rels": f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>'.encode()}
    for i, (_n, body, tail) in enumerate(sheets):
        p[f"xl/worksheets/sheet{i + 1}.xml"] = (f'<?xml version="1.0"?><worksheet {ns}><sheetData>' + body + "</sheetData>" + tail + "</worksheet>").encode()
    if strings is not None:
        p["xl/sharedStrings.xml"] = (f'<?xml version="1.0"?><sst {ns}>' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>").encode()
    p.update(extra or {})
    return p

def xlsx(parts):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in parts.items():
            z.writestr(n, d)
    return b.getvalue()

def col(i):
    s = ""
    i += 1
    while i:
        i, m = divmod(i - 1, 26)
        s = chr(65 + m) + s
    return s

def grid_body(rows, cols, val=lambda r, c: str(r * 1000 + c)):
    out = []
    for r in range(1, rows + 1):
        out.append(f'<row r="{r}">' + "".join(f'<c r="{col(c)}{r}"><v>{val(r, c)}</v></c>' for c in range(cols)) + "</row>")
    return "".join(out)
'''
exec(GEN)  # noqa: S102 - our own text above

# ---------------------------------------------------------------- inside the app container: the reader functions themselves
PROBE = GEN + r'''
import json, time, tracemalloc
from xml.etree import ElementTree as ET
from kalmido.core.config import app
from kalmido.core.errors import BadInput, Denied
from kalmido.core.access import denied
from kalmido.office import legacyimport as li
from kalmido.sheets import io as sio

out = {}
def measure(fn):
    tracemalloc.start()
    t0 = time.monotonic()
    try:
        res, err = fn(), None
    except (BadInput, Denied) as e:
        res, err = None, (e.text() if hasattr(e, "text") else str(e))
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return res, err, peak, time.monotonic() - t0

with app.test_request_context("/", headers={"Accept-Language": "en"}):
    # 1. a sheet far over the filled-cell limit (400 000 cells): refused early, low peak
    body = grid_body(2000, 200)
    raw = xlsx(xlsx_parts([("Big", body, "")]))
    out["big_bytes"] = len(raw)
    _r, err, peak, secs = measure(lambda: sio.shx_read_xlsx(raw))
    out["big_err"], out["big_peak"], out["big_secs"] = err, peak, secs
    xml = zipfile.ZipFile(io.BytesIO(raw)).read("xl/worksheets/sheet1.xml")
    _r, _e, ref_peak, _s = measure(lambda: len(ET.fromstring(xml)))  # the way before 2.576.0: the whole tree first
    out["tree_peak"] = ref_peak
    del xml
    # 2. the same through the legacy import: it stops after its row limit (2000 + 50) and keeps only those rows
    body = grid_body(12000, 3)
    raw2 = xlsx(xlsx_parts([("Contacts", body, "")]))
    res, err, peak, _s = measure(lambda: li.fi_xlsx_read(raw2))
    out["legacy_rows"] = len((res or {}).get("contacts") or [])
    out["legacy_err"], out["legacy_peak"] = err, peak
    xml = zipfile.ZipFile(io.BytesIO(raw2)).read("xl/worksheets/sheet1.xml")
    _r, _e, out["legacy_tree_peak"], _s = measure(lambda: len(ET.fromstring(xml)))
    del xml
    # 3. sharedStrings with more entries than allowed: refused before the sheet
    raw3 = xlsx(xlsx_parts([("S", '<row r="1"><c r="A1" t="s"><v>0</v></c></row>', "")], strings=[f"s{i}" for i in range(li.XL_STRINGS_MAX + 10)]))
    _r, err, peak, _s = measure(lambda: sio.shx_read_xlsx(raw3))
    out["strings_err"], out["strings_peak"] = err, peak
    # 4. the guards: DOCTYPE, ENTITY (also cut at the piece border), two-byte encoding
    p = xlsx_parts([("G", '<row r="1"><c r="A1" t="s"><v>0</v></c></row>', "")], strings=["x"])
    def with_part(name, data):
        q = dict(p)
        q[name] = data
        return xlsx(q)
    ent = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>&a;</t></si></sst>'
    pad = b'<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t><![CDATA['
    pad += b"y" * (li.XL_CHUNK - len(pad) - 4) + b"<!ENTITY z]]></t></si></sst>"  # "<!EN" | "TITY" over the border
    u16 = p["xl/workbook.xml"].decode().replace('<?xml version="1.0"?>', '<?xml version="1.0" encoding="UTF-16"?>').encode("utf-16")
    for key, raw4 in (("guard_doctype", with_part("xl/sharedStrings.xml", ent)), ("guard_border", with_part("xl/sharedStrings.xml", pad)),
                      ("guard_utf16", with_part("xl/workbook.xml", u16))):
        for which, fn in (("sheet", sio.shx_read_xlsx), ("legacy", li.fi_xlsx_read)):
            _r, err, _p, _s = measure(lambda: fn(raw4))
            out[f"{key}_{which}"] = err
    out["guard_plain"] = measure(lambda: sio.shx_read_xlsx(xlsx(p)))[1]
    # 5. two imports read: a third gets 429 at once
    small = xlsx(xlsx_parts([("T", grid_body(2, 2), "")]))
    li._XL_SLOTS.acquire()
    li._XL_SLOTS.acquire()
    try:
        for which, fn in (("sheet", lambda: sio.shx_read_xlsx_all(small, 5)), ("legacy", lambda: li.fi_xlsx_read(small))):
            t0 = time.monotonic()
            try:
                fn()
                out[f"busy_{which}"] = None
            except Denied as e:
                resp, code = denied(e)
                out[f"busy_{which}"] = [code, resp.get_json().get("error"), time.monotonic() - t0]
    finally:
        li._XL_SLOTS.release()
        li._XL_SLOTS.release()
    out["free_again"] = len(sio.shx_read_xlsx_all(small, 5)[0].rows)
    # 6. fable review H1/H2/M1: limits made small here, the patterns scaled down the same way
    keep = (li.XL_TREE_MAX, sio.XL_TREE_MAX, sio.SHX_STORED_MAX, li.xl_events, sio.xl_events)
    live = {"max": 0}
    def counting(z, name, budget, most, events=("start", "end")):  # the reader's own events; counts what still hangs in the tree
        root, i = None, 0
        for ev, el in keep[3](z, name, budget, most, events):
            if root is None:
                root = el
            i += 1
            if i % 50 == 0:
                live["max"] = max(live["max"], sum(1 for _x in root.iter()))
            yield ev, el
    def live_max(fn):
        live["max"] = 0
        r = measure(fn)
        return [r[0] if r[1] is None else r[1], live["max"]]
    junk = "<x>" + "<y/>" * 500 + "</x>"
    li.XL_TREE_MAX = sio.XL_TREE_MAX = 1000
    li.xl_events = sio.xl_events = counting
    try:
        # H1: something between the cells of one row: n is not reset by a cell -> too large
        in_row = '<row r="1">' + "".join(junk + f'<c r="{col(i)}1"><v>{i}</v></c>' for i in range(5)) + "</row>"
        out["h1_row_legacy"] = measure(lambda: li.fi_xlsx_read(xlsx(xlsx_parts([("Contacts", in_row, "")]))))[1]
        out["h1_row_sheet"] = measure(lambda: sio.shx_read_xlsx(xlsx(xlsx_parts([("T", in_row, "")]))))[1]
        # H1: something between the rows / the shared strings: it leaves the tree, the tree stays small
        between = "".join(junk + f'<row r="{i}"><c r="A{i}"><v>{i}</v></c></row>' for i in range(1, 6))
        raw6 = xlsx(xlsx_parts([("Contacts", between, "")]))
        out["h1_rows_legacy"] = live_max(lambda: len(li.fi_xlsx_read(raw6)["contacts"]))
        out["h1_rows_sheet"] = live_max(lambda: len(sio.shx_read_xlsx(raw6).rows))
        z6 = zipfile.ZipFile(io.BytesIO(raw6))
        out["h1_rows_dv"] = live_max(lambda: sio._dv_labels(z6, set(z6.namelist()), [0], [("Contacts", "xl/worksheets/sheet1.xml", False)],
                                                            "Contacts!$A$1:$A$9", []))
        sst = ('<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               + "".join(junk + f"<si><t>s{i}</t></si>" for i in range(5)) + "</sst>").encode()
        raw7 = xlsx(xlsx_parts([("S", '<row r="1"><c r="A1" t="s"><v>4</v></c></row>', "")], extra={"xl/sharedStrings.xml": sst}))
        out["h1_sst"] = live_max(lambda: sio.shx_read_xlsx(raw7).rows[0][0]["v"])
    finally:
        li.XL_TREE_MAX, sio.XL_TREE_MAX, sio.SHX_STORED_MAX, li.xl_events, sio.xl_events = keep
    # H2: nested deeper than any real file -> refused (sheet, workbook)
    deep = '<row r="1"><c r="A1"><v>1</v></c></row>' + "<x>" * 100 + "</x>" * 100
    out["h2_sheet"] = measure(lambda: sio.shx_read_xlsx(xlsx(xlsx_parts([("D", deep, "")]))))[1]
    out["h2_legacy"] = measure(lambda: li.fi_xlsx_read(xlsx(xlsx_parts([("Contacts", deep, "")]))))[1]
    q = xlsx_parts([("W", '<row r="1"><c r="A1"><v>1</v></c></row>', "")])
    q["xl/workbook.xml"] = q["xl/workbook.xml"].replace(b"</workbook>", b"<x>" * 100 + b"</x>" * 100 + b"</workbook>")
    out["h2_workbook"] = measure(lambda: sio.shx_read_xlsx(xlsx(q)))[1]
    out["h2_shallow"] = measure(lambda: sio.shx_read_xlsx(xlsx(xlsx_parts([("D", deep.replace("<x>" * 100, "<x>" * 50).replace("</x>" * 100, "</x>" * 50), "")]))))[1]
    # M1: the same cell again and again, each time with a new shared formula: the formulas are bounded as well
    sio.SHX_STORED_MAX = 50
    try:
        rep = '<row r="1">' + "".join(f'<c r="A1"><f t="shared" ref="A1:A2" si="{i}">B1+{i}</f></c>' for i in range(80)) + "</row>"
        out["m1_shared"] = measure(lambda: sio.shx_read_xlsx(xlsx(xlsx_parts([("F", rep, "")]))))[1]
    finally:
        sio.SHX_STORED_MAX = keep[2]
print(json.dumps(out))
'''

kt.fresh(prefix="P2576D")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})

r = subprocess.run(["docker", "exec", "-i", CT, "python", "-"], input=PROBE, capture_output=True, text=True, timeout=600)
check(r.returncode == 0, "the probe runs in the app container " + r.stderr[-800:])
P = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {}
MB = 1024 * 1024
print("measured:", json.dumps({k: (round(v / MB, 1) if k.endswith("peak") else v) for k, v in P.items()}))

# 1. early stop at the cell limit
check("Too many filled cells" in (P.get("big_err") or ""), f"#4188 400 000 cells: refused with the limit {P.get('big_err')}")
check(P.get("big_bytes", 99 * MB) < 10 * MB, f"#4188 the file is a normal upload size {P.get('big_bytes')}")
check(P.get("big_peak", 1e12) < 48 * MB, f"#4188 peak while refusing stays small: {P.get('big_peak', 0) / MB:.1f} MB")
check(P.get("big_peak", 1e12) * 3 < P.get("tree_peak", 0),
      f"#4188 rollback check: the whole tree of the same part takes far more ({P.get('tree_peak', 0) / MB:.1f} MB vs {P.get('big_peak', 0) / MB:.1f} MB)")
# 2. legacy: row limit
check(P.get("legacy_err") is None and P.get("legacy_rows") == 2050, f"#4188 legacy import keeps its first 2050 rows {P.get('legacy_rows')} {P.get('legacy_err')}")
check(P.get("legacy_peak", 1e12) * 3 < P.get("legacy_tree_peak", 0),
      f"#4188 legacy import stops reading after its rows ({P.get('legacy_peak', 0) / MB:.1f} MB vs tree {P.get('legacy_tree_peak', 0) / MB:.1f} MB)")
# 3. sharedStrings
check("Too many filled cells" in (P.get("strings_err") or ""), f"#4188 too many shared strings: refused {P.get('strings_err')}")
check(P.get("strings_peak", 1e12) < 64 * MB, f"#4188 shared strings peak {P.get('strings_peak', 0) / MB:.1f} MB")
# 4. guards
for key in ("guard_doctype", "guard_border", "guard_utf16"):
    for which in ("sheet", "legacy"):
        check("not a spreadsheet" in (P.get(f"{key}_{which}") or ""), f"#4188 {key} ({which}): refused {P.get(f'{key}_{which}')}")
check(P.get("guard_plain") is None, f"#4188 the same file without the trick reads {P.get('guard_plain')}")
# 5. at most two at once
for which in ("sheet", "legacy"):
    b = P.get(f"busy_{which}") or [0, "", 99]
    check(b[0] == 429 and "Two spreadsheet imports" in (b[1] or "") and b[2] < 1, f"#4188 a third import ({which}): 429 at once {b}")
check(P.get("free_again") == 2, f"#4188 the places are free again afterwards {P.get('free_again')}")
# 6. fable review (limits scaled down to 1000 elements in the probe)
for key in ("h1_row_legacy", "h1_row_sheet"):
    check("too large" in (P.get(key) or ""), f"#4188 H1 other elements between the cells of a row count until the row ends ({key}): {P.get(key)}")
for key, want in (("h1_rows_legacy", 5), ("h1_rows_sheet", 5), ("h1_rows_dv", ["1", "2", "3", "4", "5"]), ("h1_sst", "s4")):
    v = P.get(key) or [None, 99999]
    check(v[0] == want and v[1] < 800, f"#4188 H1 other elements between rows / entries leave the tree ({key}): result {v[0]}, at most {v[1]} elements held")
for key in ("h2_sheet", "h2_legacy", "h2_workbook"):
    check("not a spreadsheet" in (P.get(key) or ""), f"#4188 H2 nested 100 deep: refused ({key}) {P.get(key)}")
check(P.get("h2_shallow") is None, f"#4188 H2 nested 50 deep still reads {P.get('h2_shallow')}")
check("Too many filled cells" in (P.get("m1_shared") or ""), f"#4188 M1 one cell with ever new shared formulas: bounded {P.get('m1_shared')}")

# ---------------------------------------------------------------- over HTTP
ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
tail = ('<dataValidations count="1"><dataValidation type="list" sqref="B2:B5"><formula1>Opts!$A$1:$A$3</formula1></dataValidation></dataValidations>')
body = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>'
        '<row r="2"><c r="A2"><v>3</v></c><c r="B2" t="s"><v>3</v></c><c r="C2"><f t="shared" ref="C2:C3" si="0">A2*2</f><v>6</v></c></row>'
        '<row r="3"><c r="A3"><v>5</v></c><c r="B3" t="s"><v>4</v></c><c r="C3"><f t="shared" si="0"/><v>10</v></c></row>')
opts = '<row r="1"><c r="A1" t="s"><v>3</v></c></row><row r="2"><c r="A2" t="s"><v>4</v></c></row><row r="3"><c r="A3" t="s"><v>5</v></c></row>'
NORMAL = xlsx(xlsx_parts([("Plan", body, tail), ("Opts", opts, "")], strings=["Item", "State", "Double", "open", "done", "later"]))


def import_ok(s, who):
    r = s.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("plan.xlsx", NORMAL)})
    check(r.status_code == 201, f"#4188 {who}: a normal .xlsx imports {r.status_code} {r.text[:200]}")
    if r.status_code != 201:
        return
    sid = r.json()["sheet"]["id"]
    g = s.get(B + f"/api/sheets/{sid}").json()
    txt = json.dumps(g, ensure_ascii=False)
    check("Item" in txt and "Double" in txt, f"#4188 {who}: header from the shared strings")
    check("done" in txt and "later" in txt, f"#4188 {who}: the drop-down choices from the other sheet")
    rep = r.json().get("report") or {}
    check(rep.get("formulas", 0) >= 2, f"#4188 {who}: both shared formulas taken over {rep}")


import_ok(A, "admin")
r = A.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("big.xlsx", xlsx(xlsx_parts([("Big", grid_body(400, 150), "")])))})
check(r.status_code == 400 and "50" in r.text and "cells" in r.text, f"#4188 too many cells over HTTP: 400 with the limit {r.status_code} {r.text[:200]}")

# a person without an organisation: table import and legacy preview
FID, Fr = freelancer(B, A, features=FEAT)
import_ok(Fr, "freelancer")
legacy = xlsx(xlsx_parts([("Contacts", '<row r="1"><c r="A1" t="s"><v>0</v></c></row><row r="2"><c r="A2" t="s"><v>1</v></c></row>', "")],
                         strings=["addresses", "Example GmbH\nMain Street 1\n10115 Berlin"]))
r = Fr.post(B + "/api/office/legacy/preview", files={"file": ("old.xlsx", legacy, "application/octet-stream")})
check(r.ok and "Example GmbH" in r.text, f"#4188 freelancer: the legacy preview reads the shared strings {r.status_code} {r.text[:200]}")

sys.exit(kt.done("p2576_d_import"))
