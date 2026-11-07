"""2.636.0 (#4565): the shot list of a shoot (project type "shoot", lists/templates.py PTYPES) as a PDF.

GET /api/lists/<id>/shotlist.pdf: one table per shooting day (= the columns of the board, the sections in their order; cards
without a column first, under "Tasks" as on the board): No., a small picture (the card's first image file), the shot (card
title), Scene, Shot size, Lens, Location. The fields are found by name (the type's field names in every app language, the
person creating the project named them in hers). Only with the industry Film & Video (accounts/onboarding.py app_industry),
else 404 as for a list one cannot see. Same reading rules as the CSV export (lists/listexport.py): list_role (the access
context) decides, participants get only their own cards (tvis), a list with the lock has only ciphertext (409), agents use
/api/v1/tasks (403). A picture comes through need_attachment (seen task, not encrypted in the browser, not locked by the
virus scanner); one that cannot be read leaves its cell empty. Written with the office's PDF writer (office/pdf.py)."""
import os
import re

from flask import Response, request

from ..core.config import app, ATT_DIR
from ..core.i18n import LANGS, lang, tr
from ..core.db import db, local_now
from ..core.access import Denied, list_role, tvis
from ..core.orgcrypt import oc_read_file
from ..accounts.session import me
from ..tasks.attachments import need_attachment, uploader_is_agent
from ..collab.comments import user_names
from ..collab.liste2e import le2e_mode
from .listexport import lex_value
from .templates import ptype_ok
from ..office.pdf import A4_H, C_INK, C_INK2, C_RULE, MM, PDF_CW, PDF_L, _Page, pdf_date, pdf_image_object, pdf_text_width, pdf_wrap, pdf_write

# the type's fields (lists/templates.py PTYPES["shoot"]) in the order of the table's columns
SHT_FIELDS = ("Scene|shot", "Shot size", "Lens|shot", "Location|shot")
SHT_FS, SHT_LH, SHT_LINES = 8.6, 11.0, 4  # the cells: font size, line height, lines at most
SHT_PIC_MAX = 120  # pictures in one PDF at most (the rest stay empty: a list of hundreds of shots stays a small file)


def sht_names(key):
    """Every name field `key` of the type can have: its text in each app language and the English source, case folded."""
    out = {key.split("|")[0].strip().casefold()}
    for d in LANGS.values():
        v = d.get(key) if isinstance(d, dict) else None
        if isinstance(v, str) and v.strip():
            out.add(v.strip().casefold())
    return out


def sht_fields(c, lid):
    """{type field key: list_fields row} of list lid (the first field of each name; a renamed field is not found)."""
    rows = c.execute("SELECT * FROM list_fields WHERE list_id=? ORDER BY sort, id", (lid,)).fetchall()
    out = {}
    for k in SHT_FIELDS:
        ns = sht_names(k)
        f = next((r for r in rows if (r["name"] or "").strip().casefold() in ns), None)
        if f is not None:
            out[k] = f
    return out


def sht_days(c, uid, lid):
    """[(day name, [shot dicts])] of list lid as uid may see it: the cards without a column first ("Tasks", only when there
    are some), then one entry per section. A shot: {id, no, title, done, Scene|shot, Shot size, Lens|shot, Location|shot}."""
    done = request.args.get("done", "1") != "0"
    secs = c.execute("SELECT id, name FROM sections WHERE list_id=? ORDER BY sort, id", (lid,)).fetchall()
    rows = c.execute(f"""SELECT t.id, t.title, t.status, t.section_id FROM tasks t WHERE t.list_id=? AND t.parent_id IS NULL
        AND t.deleted_at IS NULL AND t.status != -1 AND {tvis(c, uid, 't.', write=True)}{'' if done else ' AND t.status=0'}
        ORDER BY t.sort, t.id""", (lid,)).fetchall()
    fs = sht_fields(c, lid)
    vals = {}
    if rows and fs:
        q = ",".join(str(int(r["id"])) for r in rows)
        fq = ",".join(str(int(f["id"])) for f in fs.values())
        for r in c.execute(f"SELECT task_id, field_id, value FROM task_field_values WHERE task_id IN ({q}) AND field_id IN ({fq})"):
            vals[(r[0], r[1])] = r[2]
    names = user_names(c, [int(v) for v in vals.values() if str(v).isdigit()]) if vals else {}
    sec_ids = {s["id"] for s in secs}
    by = {}
    for r in rows:
        by.setdefault(r["section_id"] if r["section_id"] in sec_ids else None, []).append(r)
    days = ([(tr("Tasks"), by[None])] if by.get(None) else []) + [(s["name"], by.get(s["id"], [])) for s in secs]
    out, no = [], 0
    for name, ts in days:
        shots = []
        for r in ts:
            no += 1
            d = {"id": r["id"], "no": no, "title": r["title"] or "", "done": r["status"] == 2}
            for k, f in fs.items():
                d[k] = lex_value(c, f, vals.get((r["id"], f["id"])), names)
            shots.append(d)
        out.append((name, shots))
    return out


def sht_picture(c, tid):
    """(w, h, data) of the picture of shot tid for the PDF writer: its first image file the person may open, else None."""
    for a in c.execute("SELECT id FROM attachments WHERE task_id=? AND comment_id IS NULL AND deleted_at IS NULL AND COALESCE(enc, 0)=0 "
                       "AND mime LIKE 'image/%' ORDER BY id LIMIT 3", (tid,)).fetchall():
        try:
            row = need_attachment(c, a["id"], False)
            raw = oc_read_file(c, os.path.join(ATT_DIR, row["path"]))
        except Exception:  # noqa: BLE001  (not to be opened, missing or a damaged sealed file: the cell stays empty)
            continue
        img = pdf_image_object(raw) if raw else None
        if img:
            return img
    return None


def sht_fit(s, width, size, bold=False):
    """s cut with "…" so that it fits into width (points) at size."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    while s and pdf_text_width(s, size, bold) > width:
        s = s[:-2] + "…" if len(s) > 2 else ""
    return s


def sht_lines(s, width):
    """The lines of one table cell: wrapped into width, at most SHT_LINES (the last one cut with "…")."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    ls = pdf_wrap(s, SHT_FS, width) if s else [""]
    if len(ls) > SHT_LINES:
        ls = ls[:SHT_LINES - 1] + [sht_fit(" ".join(ls[SHT_LINES - 1:]), width, SHT_FS)]
    return ls


def sht_pdf(c, uid, lid, name, days):
    """The bytes of the shot list PDF of list lid (named name) with the days of sht_days."""
    lg = lang(c, uid)
    cols = [(tr("No.", lg=lg), 0.06), (tr("Picture", lg=lg), 0.17), (tr("Shot|shoot", lg=lg), 0.21), (tr("Scene|shot", lg=lg), 0.10),
            (tr("Shot size", lg=lg), 0.16), (tr("Lens|shot", lg=lg), 0.12), (tr("Location|shot", lg=lg), 0.18)]
    keys = ("no", "pic", "title") + SHT_FIELDS
    xs, x = [], PDF_L
    for _h, f in cols:
        xs.append((x, PDF_CW * f))
        x += PDF_CW * f
    pic_w = xs[1][1] - 6
    pic_h = pic_w * 9 / 16  # the frame of a 16:9 picture; another format is fitted into it
    pages, images, n_pic = [], {}, 0
    bottom = A4_H - 18 * MM

    def new_page():
        p = _Page()
        pages.append(p)
        return p

    def thead(p, y):
        for (h, _f), (cx, cw) in zip(cols, xs):
            p.text(cx, y, sht_fit(h, cw - 4, 8.2, True), 8.2, True, C_INK2)
        p.line(PDF_L, y + 12, PDF_L + PDF_CW, y + 12, 0.6, C_RULE)
        return y + 17

    page = new_page()
    y = 60.0
    page.text(PDF_L, y, sht_fit(tr("Shot list", lg=lg) + ": " + name, PDF_CW, 16, True), 16, True)
    y += 22
    page.text(PDF_L, y, pdf_date(local_now().date().isoformat(), lg), 9, False, C_INK2)
    y += 24
    if not any(shots for _n, shots in days):
        page.text(PDF_L, y, tr("No shots yet", lg=lg), 10, False, C_INK2)
    for dname, shots in days:
        if not shots:
            continue
        has_pic = []
        for s in shots:
            img = None
            if n_pic < SHT_PIC_MAX:
                img = sht_picture(c, s["id"])
                if img:
                    n_pic += 1
                    images[f"Sh{n_pic}"] = img
                    img = (f"Sh{n_pic}", img[0], img[1])
            has_pic.append(img)
        rh0 = pic_h + 8 if any(has_pic) else 16.0
        if y + 30 + rh0 > bottom:  # the day's heading never stays alone at the end of a page
            page = new_page()
            y = 60.0
        page.text(PDF_L, y, sht_fit(dname, PDF_CW, 12, True), 12, True)
        y = thead(page, y + 20)
        for s, img in zip(shots, has_pic):
            cells = {k: sht_lines(s["no"] if k == "no" else s.get(k, ""), cw - 6) for k, (_cx, cw) in zip(keys, xs) if k != "pic"}
            rh = max(rh0, 5 + SHT_LH * max(len(v) for v in cells.values()))
            if y + rh > bottom:
                page = new_page()
                page.text(PDF_L, 60.0, sht_fit(dname, PDF_CW, 12, True), 12, True)
                y = thead(page, 80.0)
            ink = C_INK2 if s["done"] else C_INK
            for k, (cx, cw) in zip(keys, xs):
                if k == "pic":
                    if img:
                        nm, w, h = img
                        sc = min(pic_w / w, pic_h / h)
                        page.image(nm, cx + (pic_w - w * sc) / 2, y + (pic_h - h * sc) / 2, w * sc, h * sc)
                    continue
                for i, ln in enumerate(cells[k]):
                    page.text(cx, y + 2 + i * SHT_LH, ln, SHT_FS, False, ink)
            y += rh
            page.line(PDF_L, y - 3, PDF_L + PDF_CW, y - 3, 0.3, C_RULE)
        y += 16
    return pdf_write(pages, images, title=tr("Shot list", lg=lg) + ": " + name, author="")


@app.get("/api/lists/<int:lid>/shotlist.pdf")
def sht_shotlist_pdf(lid):
    """The shot list of a shoot as a PDF (see the module text). 404: list not seen, not a shoot or no Film & Video."""
    c = db()
    uid = me()
    if not list_role(c, lid):
        raise Denied(404)
    r = c.execute("SELECT name, ptype FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or (r["ptype"] or "") != "shoot" or not ptype_ok(c, uid, "shoot"):
        raise Denied(404)
    if uploader_is_agent(c, uid):
        raise Denied(403)
    if le2e_mode(c, lid):
        raise Denied(409, tr("Not available in encrypted projects"))
    data = sht_pdf(c, uid, lid, r["name"] or "", sht_days(c, uid, lid))
    fn = re.sub(r"[^A-Za-z0-9._-]+", "-", r["name"] or "")[:60].strip("-") or "shoot"
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="shotlist-{fn}.pdf"',
                                                               "Cache-Control": "no-store"})
