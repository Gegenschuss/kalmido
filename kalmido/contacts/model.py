"""Contacts (module "contacts"): address books, rights, vCard 3 / 4 reading + writing, search, links to tasks, birthdays."""
import base64
import hashlib
import json
import re
import secrets
from datetime import date

from flask import has_request_context

from ..core.i18n import lang, N_, tr
from ..core.db import bump, iso, iso_ms, local_now, now_utc, usettings
from ..accounts.session import me
from ..core.access import collab_all, Denied, list_role, task_visible, WRITE_ROLES
from ..tasks.validation import DATE_MIN_Y
from ..collab.comments import user_names
from ..personal.timetrack import BadInput


# ---------------------------------------------------------------- 2.21.0 (#658): contacts
# Kalmido keeps the contacts itself (one database with the tasks and events) and serves them over CardDAV
# (contacts/carddav.py), so the phone's contacts app syncs directly. Address books (books) belong to a person and are
# shared like lists (book_members: view = read, edit = change). A contact is one vCard: the fields Kalmido shows and
# edits are columns (name parts, company, e-mails, phones, addresses, web links, birthday, anniversary, notes, groups,
# photo); every other property a client wrote is kept as it came (extra) and sent back, so a round trip loses nothing.
# Contacts are sensitive: the API needs the scope "contacts" (never in an agent's default), only people who see the
# address book see a contact, and a task only shows the contacts linked to it to those who see both.
# Links: a contact <-> tasks (waiting on / responsible outside / about), <-> event attendees, birthdays + anniversaries
# -> yearly tasks (module Family: the book's birthday list), an external CardDAV account (family import) is mirrored into
# an address book of its own.
BOOKS_MAX = 30
CONTACTS_PER_BOOK = 20000
PHOTO_MAX = 512 * 1024              # characters of the stored data URI
FIELD_MAX, NOTE_MAX, ITEMS_MAX = 300, 20000, 30
EXTRA_MAX = 32000
CT_LINKS = ("waiting", "responsible", "about")
CT_KINDS = ("individual", "org", "group")
BOOK_ROLES = ("view", "edit")
BOOK_COLORS = ("#6d8cff", "#2dd4bf", "#f5b041", "#f87171", "#c084fc", "#4ade80")
# properties mapped to columns (the rest goes to extra)
VC_MAPPED = {"BEGIN", "END", "VERSION", "PRODID", "UID", "FN", "N", "NICKNAME", "ORG", "TITLE", "EMAIL", "TEL", "ADR", "URL",
             "BDAY", "ANNIVERSARY", "X-ANNIVERSARY", "NOTE", "CATEGORIES", "PHOTO", "REV", "KIND", "X-ADDRESSBOOKSERVER-KIND"}


def contacts_on(c, uid):
    return "contacts" in (usettings(c, uid).get("features") or "").split(",")


# ---- address books and rights
def book_role(c, uid, b):
    if b is None:
        return None
    if b["owner_id"] != uid and c.execute("SELECT disabled FROM users WHERE id=?", (b["owner_id"],)).fetchone()[0]:
        return None  # a disabled owner's address books are gone for the members too (like in the lists of books)
    if b["owner_id"] == uid:
        return "owner"
    if not collab_all():
        return None
    r = c.execute("SELECT role FROM book_members WHERE book_id=? AND user_id=?", (b["id"], uid)).fetchone()
    return r[0] if r else None


def need_book(c, bid, write=False, manage=False, uid=None):
    uid = uid or me()
    b = c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone()
    role = book_role(c, uid, b)
    if not role:
        raise Denied(404)
    if manage and role != "owner":
        raise Denied(403, tr("Only the owner of the address book can do this"))
    if write and role not in ("owner", "edit"):
        raise Denied(403, tr("You can only read this address book"))
    return b, role


def my_book_ids(c, uid):
    out = {r[0]: "owner" for r in c.execute("SELECT id FROM books WHERE owner_id=?", (uid,))}
    if collab_all():
        for r in c.execute("SELECT m.book_id, m.role FROM book_members m JOIN books b ON b.id=m.book_id JOIN users u ON u.id=b.owner_id "
                           "WHERE m.user_id=? AND u.disabled=0", (uid,)):
            out.setdefault(r[0], r[1])
    return out


def book_public(c, b, uid, names=None):
    role = book_role(c, uid, b)
    d = {"id": b["id"], "name": b["name"], "color": b["color"], "owner_id": b["owner_id"], "role": role,
         "org_id": b["org_id"],  # 2.30.0 (#1036): its workspace (None = private)
         "imported": bool(b["src_id"]), "birthdays_list_id": b["occ_list_id"] if role == "owner" else None,
         "count": c.execute("SELECT COUNT(*) FROM contacts WHERE book_id=? AND kind!='group'", (b["id"],)).fetchone()[0]}
    if names is not None:
        d["owner_name"] = names.get(b["owner_id"], "?")
    if role == "owner":
        d["members"] = [{"user_id": m[0], "role": m[1]} for m in
                        c.execute("SELECT user_id, role FROM book_members WHERE book_id=? ORDER BY added_at", (b["id"],))]
    return d


def books_for(c, uid):
    ids = my_book_ids(c, uid)
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    rows = c.execute(f"SELECT * FROM books WHERE id IN ({q}) ORDER BY owner_id!=?, id", [*ids, uid]).fetchall()
    names = user_names(c, [r["owner_id"] for r in rows])
    return [book_public(c, r, uid, names) for r in rows]


def book_fields(b, create=False):
    out = {}
    if "name" in b or create:
        n = b.get("name")
        if not isinstance(n, str) or not n.strip():
            raise BadInput(tr("Name missing"))
        out["name"] = re.sub(r"[\x00-\x1f\x7f]", " ", n).strip()[:100]
    if "color" in b:
        v = b["color"]
        if not isinstance(v, str) or not (v == "" or re.fullmatch(r"#[0-9a-fA-F]{6}", v)):
            raise BadInput(tr("Invalid value: {0}", tr("Color")))
        out["color"] = v.lower()
    return out


def book_create(c, uid, b, src_id=None):
    """2.30.0 (#1036): b.org_id = its workspace (None / 0 = private, else an organisation of uid); not given: an address book
    mirrored from an outside account (src_id) is private, else the default of a new object (ws_obj_default)."""
    from ..accounts.orgs import clean_org_id, ws_obj_default
    f = book_fields(b, True)
    oid = clean_org_id(c, b["org_id"], uid) if "org_id" in b else (None if src_id else ws_obj_default(c, uid))
    if c.execute("SELECT COUNT(*) FROM books WHERE owner_id=?", (uid,)).fetchone()[0] >= BOOKS_MAX:
        raise Denied(409, tr("At most {0} address books", BOOKS_MAX))
    used = [r[0] for r in c.execute("SELECT color FROM books WHERE owner_id=?", (uid,))]
    col = f.get("color") or next((x for x in BOOK_COLORS if x not in used), BOOK_COLORS[0])
    ts = iso_ms(now_utc())
    return c.execute("INSERT INTO books(owner_id,name,color,src_id,created_at,changed_at,org_id) VALUES(?,?,?,?,?,?,?)",
                     (uid, f["name"], col, src_id, ts, ts, oid)).lastrowid


def default_book(c, uid, create=True):
    r = c.execute("SELECT id FROM books WHERE owner_id=? AND src_id IS NULL ORDER BY id LIMIT 1", (uid,)).fetchone()
    if r:
        return r[0]
    return book_create(c, uid, {"name": tr("Contacts", lg=lang(c, uid))}) if create else None


def book_touch(c, bid):
    c.execute("UPDATE books SET changed_at=? WHERE id=?", (iso_ms(now_utc()), bid))


def book_member_set(c, bid, uid, role):
    from ..collab.news import news_add
    from ..agents.admin import personal_agent_foreign
    from ..agents.core import is_agent
    if not collab_all():
        raise Denied(409, tr("Collaboration is turned off on this server"))
    if role not in BOOK_ROLES:
        raise BadInput(tr("Invalid value: {0}", "role"))
    b = c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone()
    u = c.execute("SELECT * FROM users WHERE id=? AND disabled=0", (uid,)).fetchone()
    if not u or uid == b["owner_id"] or personal_agent_foreign(c, uid, me()):
        raise Denied(404, tr("unknown user"))
    if is_agent(u) and not has_request_context():
        raise Denied(404, tr("unknown user"))
    if not c.execute("SELECT 1 FROM book_members WHERE book_id=? AND user_id=?", (bid, uid)).fetchone():  # a new member
        from ..accounts.orgs import need_visible, ws_fit_problem
        need_visible(c, uid)  # 2.30.0 (#1036, B2): only people one may see (404 as for an unknown id)
        p = ws_fit_problem(c, b["org_id"], uid, "book")  # 2.30.0 (#1036, B3): an organisation's address book only inside it
        if p:
            raise Denied(409, p)
    if c.execute("SELECT 1 FROM book_members WHERE book_id=? AND user_id=?", (bid, uid)).fetchone():
        c.execute("UPDATE book_members SET role=? WHERE book_id=? AND user_id=?", (role, bid, uid))
    else:
        c.execute("INSERT INTO book_members(book_id,user_id,role,added_at) VALUES(?,?,?,?)", (bid, uid, role, iso(now_utc())))
        news_add(c, uid, "abshare", data={"book_id": bid, "name": b["name"], "role": role}, row="share")
    book_touch(c, bid)


def contact_visible(c, cid, uid):
    """The contact row when uid sees its address book (and the contacts module is on for uid), else None."""
    r = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    if not r or not contacts_on(c, uid):
        return None
    b = c.execute("SELECT * FROM books WHERE id=?", (r["book_id"],)).fetchone()
    return r if book_role(c, uid, b) else None


def need_contact(c, cid, write=False, uid=None):
    uid = uid or me()
    r = contact_visible(c, cid, uid)
    if not r:
        raise Denied(404)
    b = c.execute("SELECT * FROM books WHERE id=?", (r["book_id"],)).fetchone()
    role = book_role(c, uid, b)
    if write and role not in ("owner", "edit"):
        raise Denied(403, tr("You can only read this address book"))
    return r, role


def contact_by_email(c, uid, email):
    ids = my_book_ids(c, uid)
    if not ids or not email or not contacts_on(c, uid):
        return None
    q = ",".join("?" * len(ids))
    em = '"' + email.lower().replace('"', "") + '"'
    em = em.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    r = c.execute(f"SELECT id FROM contacts WHERE book_id IN ({q}) AND lower(emails) LIKE ? ESCAPE '\\' ORDER BY id LIMIT 1",
                  [*ids, f"%{em}%"]).fetchone()
    return r[0] if r else None


# ---- vCard text
def vc_esc(s):
    return str(s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\r\n", "\n").replace("\n", "\\n")


def vc_unesc(s):
    out, i = [], 0
    s = s or ""
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nx = s[i + 1]
            out.append("\n" if nx in "nN" else nx)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def vc_split(s, sep):
    """Splits a structured value at unescaped separators (the parts stay escaped)."""
    parts, cur, i = [], [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            cur.append(s[i:i + 2])
            i += 2
            continue
        if ch == sep:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def vc_unfold(text):
    return re.sub(r"\r?\n[ \t]", "", str(text or "").replace("\r\n", "\n").replace("\r", "\n")).split("\n")


def vc_fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur, n, limit = [], "", 0, 75
    for ch in line:
        k = len(ch.encode("utf-8"))
        if n + k > limit:
            out.append(cur)
            cur, n, limit = "", 0, 74
        cur += ch
        n += k
    out.append(cur)
    return "\r\n ".join(out)


LINE_RE = re.compile(r"^(?:([A-Za-z0-9-]+)\.)?([A-Za-z0-9-]+)((?:;(?:[^:\"]|\"[^\"]*\")*)?):(.*)$")


def vc_line(line):
    """-> (group, NAME, {PARAM: [values]}, value) or None."""
    m = LINE_RE.match(line)
    if not m:
        return None
    grp, name, praw, val = m.group(1) or "", m.group(2).upper(), m.group(3) or "", m.group(4)
    params = {}
    for p in re.findall(r';((?:[^;"]|"[^"]*")*)', praw):
        k, eq, v = p.partition("=")
        k = k.strip().upper()
        if not eq:  # vCard 2.1 style bare type (;HOME)
            params.setdefault("TYPE", []).append(k.lower())
            continue
        vals = [x.strip().strip('"') for x in re.findall(r'(?:"[^"]*"|[^,]+)', v)]
        if k == "TYPE":
            vals = [x.lower() for x in vals]
        params.setdefault(k, []).extend(vals)
    return grp, name, params, val


def _types(params):
    t = [x for x in params.get("TYPE", []) if x and x not in ("internet", "x400", "pref", "voice")]
    pref = "pref" in params.get("TYPE", []) or params.get("PREF", ["100"])[0] == "1"
    return t[:4], pref


def vc_date(v, params):
    """A vCard date -> 'YYYY-MM-DD' or '--MM-DD' (no year), '' when unusable."""
    v = (v or "").strip()
    m = re.match(r"^(\d{4}|--)-?(\d{2})-?(\d{2})", v)
    if not m:
        return ""
    mo, dy = int(m.group(2)), int(m.group(3))
    try:
        date(2000, mo, dy)
    except ValueError:
        return ""
    y = int(m.group(1)) if m.group(1).isdigit() else None
    if y is not None and ("X-APPLE-OMIT-YEAR" in params or y in (0, 1604) or not DATE_MIN_Y <= y <= local_now().year + 1):
        y = None
    return f"{y:04d}-{mo:02d}-{dy:02d}" if y else f"--{mo:02d}-{dy:02d}"


def parse_vcard(text):
    """One vCard -> the contact's columns (dict). BadInput when it is not a usable vCard."""
    lines = [x for x in vc_unfold(text) if x.strip()]
    starts = [i for i, x in enumerate(lines) if x.strip().upper() == "BEGIN:VCARD"]
    ends = [i for i, x in enumerate(lines) if x.strip().upper() == "END:VCARD"]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise BadInput(tr("Exactly one contact (vCard) per resource"))
    v = {"uid": "", "kind": "individual", "fn": "", "given": "", "family": "", "middle": "", "prefix": "", "suffix": "", "nickname": "",
         "org": "", "dept": "", "title": "", "emails": [], "phones": [], "addresses": [], "urls": [], "bday": "", "anniversary": "",
         "note": "", "groups": [], "photo": "", "version": "3.0"}
    keep, labels, nest = [], {}, 0
    props = []
    for line in lines[starts[0] + 1:ends[0]]:
        up = line.upper()
        if up.startswith("BEGIN:"):
            nest += 1
        if nest:
            keep.append(line)
            if up.startswith("END:"):
                nest -= 1
            continue
        p = vc_line(line)
        if not p:
            continue
        props.append((p, line))
        if p[1] == "X-ABLABEL" and p[0]:
            labels[p[0].lower()] = p[3]
    for (grp, name, params, val), line in props:
        if name == "VERSION":
            v["version"] = "4.0" if val.strip().startswith("4") else "3.0"
        elif name == "UID":
            v["uid"] = re.sub(r"[\x00-\x1f\x7f]", "", vc_unesc(val)).strip()[:250]  # never a line break (it is written unescaped)
        elif name == "FN":
            v["fn"] = vc_unesc(val).strip()[:FIELD_MAX]
        elif name == "N":
            parts = [vc_unesc(x).strip()[:FIELD_MAX] for x in vc_split(val, ";")] + [""] * 5
            v["family"], v["given"], v["middle"], v["prefix"], v["suffix"] = parts[:5]
        elif name == "NICKNAME":
            v["nickname"] = vc_unesc(val).strip()[:FIELD_MAX]
        elif name == "ORG":
            parts = [vc_unesc(x).strip()[:FIELD_MAX] for x in vc_split(val, ";")] + [""]
            v["org"], v["dept"] = parts[0], "; ".join(x for x in parts[1:] if x)[:FIELD_MAX]
        elif name == "TITLE":
            v["title"] = vc_unesc(val).strip()[:FIELD_MAX]
        elif name in ("EMAIL", "TEL", "URL"):
            t, pref = _types(params)
            val2 = vc_unesc(val).strip()
            if name == "TEL" and val2.lower().startswith("tel:"):
                val2 = val2[4:]
            if not val2:
                continue
            key = {"EMAIL": "emails", "TEL": "phones", "URL": "urls"}[name]
            if len(v[key]) < ITEMS_MAX:
                v[key].append({"value": val2[:FIELD_MAX], "type": t, "pref": pref, "group": grp, "label": labels.get(grp.lower(), "")[:60] if grp else ""})
        elif name == "ADR":
            t, pref = _types(params)
            parts = [vc_unesc(x).strip()[:FIELD_MAX] for x in vc_split(val, ";")] + [""] * 7
            a = {"pobox": parts[0], "ext": parts[1], "street": parts[2], "city": parts[3], "region": parts[4], "code": parts[5],
                 "country": parts[6], "type": t, "pref": pref, "group": grp, "label": labels.get(grp.lower(), "")[:60] if grp else ""}
            if any(a[k] for k in ("pobox", "ext", "street", "city", "region", "code", "country")) and len(v["addresses"]) < ITEMS_MAX:
                v["addresses"].append(a)
        elif name == "BDAY":
            v["bday"] = vc_date(val, params) or v["bday"]
            if not v["bday"]:
                keep.append(line)
        elif name in ("ANNIVERSARY", "X-ANNIVERSARY"):
            v["anniversary"] = vc_date(val, params) or v["anniversary"]
        elif name == "NOTE":
            v["note"] = vc_unesc(val)[:NOTE_MAX]
        elif name == "CATEGORIES":
            v["groups"] += [vc_unesc(x).strip()[:100] for x in vc_split(val, ",") if vc_unesc(x).strip()]
        elif name == "PHOTO":
            ph = _photo_in(params, val)
            if ph and not v["photo"]:
                v["photo"] = ph
            else:
                keep.append(line)
        elif name in ("KIND", "X-ADDRESSBOOKSERVER-KIND"):
            k = val.strip().lower()
            v["kind"] = "group" if k == "group" else "org" if k == "org" else "individual"
            if name == "X-ADDRESSBOOKSERVER-KIND":
                keep.append(line)
        elif name in ("REV", "PRODID", "BEGIN", "END"):
            continue
        else:
            keep.append(line)  # X-ABLabel of a mapped item stays here, with its group, and is written back next to it
    v["groups"] = list(dict.fromkeys(v["groups"]))[:ITEMS_MAX]
    if not v["fn"]:
        v["fn"] = " ".join(x for x in (v["prefix"], v["given"], v["middle"], v["family"], v["suffix"]) if x).strip() or v["org"] or \
            (v["emails"][0]["value"] if v["emails"] else "") or (v["phones"][0]["value"] if v["phones"] else "")
    extra = "\n".join(keep)
    if len(extra) > EXTRA_MAX:
        extra = extra[:EXTRA_MAX].rsplit("\n", 1)[0]
    v["extra"] = extra
    return v


def _photo_in(params, val):
    val = val.strip()
    if val.lower().startswith("data:image/"):
        m = re.fullmatch(r"data:(image/(?:jpeg|png|gif|webp));base64,([A-Za-z0-9+/=\s]+)", val, re.I)
        return f"data:{m.group(1).lower()};base64," + re.sub(r"\s", "", m.group(2)) if m and len(val) <= PHOTO_MAX else ""
    enc = [x.lower() for x in params.get("ENCODING", [])]
    if "b" in enc or "base64" in enc:
        t = (params.get("TYPE") or ["jpeg"])[0].lower().replace("image/", "")
        t = "jpeg" if t in ("jpg", "jpeg") else t
        if t not in ("jpeg", "png", "gif", "webp") or len(val) > PHOTO_MAX:
            return ""
        try:
            base64.b64decode(val, validate=False)
        except ValueError:
            return ""
        return f"data:image/{t};base64," + re.sub(r"\s", "", val)
    return ""


def _params_out(t, pref, version):
    out = ""
    if t:
        out += ";TYPE=" + ",".join(re.sub(r"[^a-z0-9-]", "", x) for x in t if re.sub(r"[^a-z0-9-]", "", x))
    if pref:
        out += ";PREF=1" if version == "4.0" else (";TYPE=pref" if not t else ",pref")
    return out


def render_vcard(r, rev=None):
    """The vCard text of a contact row (in its own version, 3.0 or 4.0)."""
    from ..core.config import APP_NAME, APP_VERSION
    ver = r["version"] if r["version"] in ("3.0", "4.0") else "3.0"
    L = ["BEGIN:VCARD", f"VERSION:{ver}", f"PRODID:-//{APP_NAME}//CardDAV {APP_VERSION}//EN", f"UID:{r['uid']}"]
    if r["kind"] != "individual" and ver == "4.0":
        L.append(f"KIND:{r['kind']}")
    L.append("FN:" + vc_esc(r["fn"] or r["org"] or " "))
    L.append("N:" + ";".join(vc_esc(r[k]) for k in ("family", "given", "middle", "prefix", "suffix")))
    if r["nickname"]:
        L.append("NICKNAME:" + vc_esc(r["nickname"]))
    if r["org"] or r["dept"]:
        L.append("ORG:" + vc_esc(r["org"]) + (";" + ";".join(vc_esc(x.strip()) for x in r["dept"].split(";")) if r["dept"] else ""))
    if r["title"]:
        L.append("TITLE:" + vc_esc(r["title"]))
    for key, prop in (("emails", "EMAIL"), ("phones", "TEL"), ("urls", "URL")):
        for it in _jl(r[key]):
            g = (it.get("group") + ".") if it.get("group") else ""
            t = list(it.get("type") or [])
            if prop == "EMAIL" and ver == "3.0" and "internet" not in t:
                t = ["internet"] + t
            val = it.get("value", "")
            val = val.replace("\\", "\\\\").replace("\n", "\\n") if prop == "URL" else vc_esc(val)
            L.append(f"{g}{prop}{_params_out(t, it.get('pref'), ver)}:{val}")
    for a in _jl(r["addresses"]):
        g = (a.get("group") + ".") if a.get("group") else ""
        L.append(f"{g}ADR{_params_out(a.get('type') or [], a.get('pref'), ver)}:" +
                 ";".join(vc_esc(a.get(k, "")) for k in ("pobox", "ext", "street", "city", "region", "code", "country")))
    for key, prop in (("bday", "BDAY"), ("anniversary", "ANNIVERSARY" if ver == "4.0" else "X-ANNIVERSARY")):
        d = r[key]
        if not d:
            continue
        if d.startswith("--"):
            L.append(f"{prop}:--{d[2:4]}{d[5:7]}" if ver == "4.0" else f"{prop};X-APPLE-OMIT-YEAR=1604:1604-{d[2:4]}-{d[5:7]}")
        else:
            L.append(f"{prop}:{d}" if ver == "3.0" else f"{prop}:{d.replace('-', '')}")
    if r["note"]:
        L.append("NOTE:" + vc_esc(r["note"]))
    gs = _jl(r["groups"])
    if gs:
        L.append("CATEGORIES:" + ",".join(vc_esc(x) for x in gs))
    if r["photo"]:
        m = re.fullmatch(r"data:image/(\w+);base64,(.+)", r["photo"], re.S)
        if m:
            L.append(f"PHOTO:{r['photo']}" if ver == "4.0" else f"PHOTO;ENCODING=b;TYPE={m.group(1).upper()}:{m.group(2)}")
    L.append(f"REV:{(rev or r['updated_at'])[:19].replace('-', '').replace(':', '')}Z")
    if r["extra"]:
        L += [x for x in r["extra"].split("\n") if x and x.upper() not in ("BEGIN:VCARD", "END:VCARD")]
    L.append("END:VCARD")
    return "\r\n".join(vc_fold(x) for x in L) + "\r\n"


def _jl(v):
    try:
        x = json.loads(v or "[]")
        return x if isinstance(x, list) else []
    except ValueError:
        return []


def search_text(v):
    parts = [v.get("fn"), v.get("given"), v.get("family"), v.get("nickname"), v.get("org"), v.get("dept"), v.get("title"), v.get("note", "")[:500]]
    for k in ("emails", "phones"):
        parts += [x.get("value", "") for x in (v.get(k) if isinstance(v.get(k), list) else _jl(v.get(k)))]
    parts += [re.sub(r"[^\d+]", "", x.get("value", "")) for x in (v.get("phones") if isinstance(v.get("phones"), list) else _jl(v.get("phones")))]
    for a in (v.get("addresses") if isinstance(v.get("addresses"), list) else _jl(v.get("addresses"))):
        parts += [a.get(k, "") for k in ("street", "city", "code", "country")]
    parts += v.get("groups") if isinstance(v.get("groups"), list) else _jl(v.get("groups"))
    return " ".join(str(x) for x in parts if x).lower()[:4000]


# ---- validation of a contact body (web + API)
CT_KEYS = ("book_id", "kind", "fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "emails",
           "phones", "addresses", "urls", "bday", "anniversary", "note", "groups", "photo")


def _s(b, k, n=FIELD_MAX):
    v = b.get(k)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", k))
    return re.sub(r"[\x00-\x1f\x7f]", " ", v).strip()[:n]


def _items(b, k, addr=False):
    v = b.get(k)
    if v in (None, ""):
        return []
    if not isinstance(v, list) or len(v) > ITEMS_MAX:
        raise BadInput(tr("Invalid value: {0}", k))
    out = []
    for it in v:
        if isinstance(it, str):
            it = {"value": it}
        if not isinstance(it, dict):
            raise BadInput(tr("Invalid value: {0}", k))
        t = it.get("type") or []
        if isinstance(t, str):
            t = [t]
        if not isinstance(t, list) or any(not isinstance(x, str) for x in t):
            raise BadInput(tr("Invalid value: {0}", k))
        t = [re.sub(r"[^a-z0-9-]", "", x.lower())[:20] for x in t][:4]
        row = {"type": [x for x in t if x], "pref": bool(it.get("pref")), "group": re.sub(r"[^A-Za-z0-9-]", "", str(it.get("group") or ""))[:20],
               "label": _s(it, "label", 60)}
        if addr:
            for f in ("pobox", "ext", "street", "city", "region", "code", "country"):
                row[f] = _s(it, f)
            if any(row[f] for f in ("pobox", "ext", "street", "city", "region", "code", "country")):
                out.append(row)
        else:
            val = _s(it, "value")
            if k == "emails" and val and not re.fullmatch(r"[^@\s<>\"]+@[^@\s<>\"]+", val):
                raise BadInput(tr("Invalid value: {0}", tr("E-mail")))
            if k == "urls" and val and not re.fullmatch(r"(?i)(https?|mailto|tel|xmpp|sip):\S+", val):
                raise BadInput(tr("Invalid value: {0}", "url"))
            if val:
                row["value"] = val
                out.append(row)
    return out


def _date_in(v, k):
    if v in (None, ""):
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", k))
    d = vc_date(v, {})
    if not d:
        raise BadInput(tr("Invalid value: {0}", k))
    return d


def contact_fields(b, old=None):
    out = {}
    for k in ("fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title"):
        if k in b or old is None:
            out[k] = _s(b, k)
    if "note" in b or old is None:
        v = b.get("note") or ""
        if not isinstance(v, str):
            raise BadInput(tr("Invalid value: {0}", "note"))
        out["note"] = v.replace("\x00", "")[:NOTE_MAX]
    if "kind" in b or old is None:
        k = b.get("kind") or "individual"
        if k not in CT_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        out["kind"] = k
    for k in ("emails", "phones", "urls"):
        if k in b or old is None:
            out[k] = json.dumps(_items(b, k), ensure_ascii=False)
    if "addresses" in b or old is None:
        out["addresses"] = json.dumps(_items(b, "addresses", True), ensure_ascii=False)
    for k in ("bday", "anniversary"):
        if k in b or old is None:
            out[k] = _date_in(b.get(k), k)
    if "groups" in b or old is None:
        g = b.get("groups") or []
        if not isinstance(g, list) or len(g) > ITEMS_MAX or any(not isinstance(x, str) for x in g):
            raise BadInput(tr("Invalid value: {0}", "groups"))
        out["groups"] = json.dumps(list(dict.fromkeys(re.sub(r"[\x00-\x1f\x7f,]", " ", x).strip()[:100] for x in g if x.strip())),
                                   ensure_ascii=False)
    if "photo" in b:
        p = b.get("photo") or ""
        if p and (not isinstance(p, str) or not _photo_in({}, p)):
            raise BadInput(tr("The photo must be a JPEG, PNG, GIF or WebP image of at most {0} KB", PHOTO_MAX // 1024 * 3 // 4))
        out["photo"] = _photo_in({}, p) if p else ""
    merged = {**(dict(old) if old is not None else {}), **out}
    if not merged.get("fn"):
        merged_fn = " ".join(x for x in (merged.get("prefix"), merged.get("given"), merged.get("middle"), merged.get("family"),
                                         merged.get("suffix")) if x).strip() or merged.get("org") or ""
        if not merged_fn:
            raise BadInput(tr("Name missing"))
        out["fn"] = merged_fn[:FIELD_MAX]
    return out


def new_uid():
    return f"kalmido-ct-{secrets.token_hex(10)}"


def contact_store(c, uid, book_id, f, cid=None, uid_=None, href=None, extra=None, version=None, src_digest=None):
    """Creates (cid None) or changes a contact with validated columns f. Returns its id; the caller commits."""
    ts = iso_ms(now_utc())  # ms: two changes in one second still differ (expect)
    if cid is None:
        if c.execute("SELECT COUNT(*) FROM contacts WHERE book_id=?", (book_id,)).fetchone()[0] >= CONTACTS_PER_BOOK:
            raise Denied(409, tr("At most {0} contacts per address book", CONTACTS_PER_BOOK))
        uid_ = uid_ or new_uid()
        cols = {k: f.get(k, "" if k not in ("emails", "phones", "addresses", "urls", "groups") else "[]") for k in
                ("kind", "fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "emails", "phones",
                 "addresses", "urls", "bday", "anniversary", "note", "groups", "photo")}
        cols["kind"] = cols["kind"] or "individual"
        cols.update(book_id=book_id, uid=uid_, href=href or (re.sub(r"[^A-Za-z0-9._-]", "_", uid_)[:180] + ".vcf"), extra=extra or "",
                    version=version or "3.0", src_digest=src_digest or "", created_by=uid, created_at=ts, updated_at=ts)
        cols["search"] = search_text({**cols, **{k: _jl(cols[k]) for k in ("emails", "phones", "addresses", "groups")}})
        cid = c.execute(f"INSERT INTO contacts({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(cols.values())).lastrowid
    else:
        f = dict(f)
        if extra is not None:
            f["extra"] = extra
        if version:
            f["version"] = version
        if src_digest is not None:
            f["src_digest"] = src_digest
        f["updated_at"] = ts
        c.execute(f"UPDATE contacts SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), cid])
        r = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        c.execute("UPDATE contacts SET search=? WHERE id=?",
                  (search_text({**dict(r), **{k: _jl(r[k]) for k in ("emails", "phones", "addresses", "groups")}}), cid))
    book_touch(c, book_id)
    occ_sync(c, cid)
    bump(c)
    return cid


def contact_dict(c, r, uid=None, links=True):
    d = {"id": r["id"], "book_id": r["book_id"], "uid": r["uid"], "kind": r["kind"]}
    for k in ("fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "bday", "anniversary", "note",
              "photo"):
        d[k] = r[k]
    for k in ("emails", "phones", "addresses", "urls", "groups"):
        d[k] = _jl(r[k])
    d["created_at"], d["updated_at"] = r["created_at"], r["updated_at"]
    if links and uid:
        d["tasks"] = [{"task_id": x["task_id"], "kind": x["kind"], "title": x["title"], "status": x["status"]}
                      for x in c.execute("""SELECT l.task_id, l.kind, t.title, t.status FROM contact_tasks l JOIN tasks t ON t.id=l.task_id
                                            WHERE l.contact_id=? AND t.deleted_at IS NULL ORDER BY t.status, t.due IS NULL, t.due""", (r["id"],))
                      if task_visible(c, x["task_id"], uid)]
        d["events"] = []
        from ..events.model import need_event
        for e in c.execute("""SELECT DISTINCT e.id FROM event_attendees a JOIN events e ON e.id=a.event_id WHERE a.contact_id=?
                              AND e.deleted_at IS NULL ORDER BY e.first_day DESC LIMIT 50""", (r["id"],)):
            try:
                er, _ = need_event(c, e[0], uid=uid)
            except Denied:
                continue
            d["events"].append({"event_id": er["id"], "title": er["title"], "start": er["start"], "all_day": bool(er["all_day"])})
        if "care" in (usettings(c, uid).get("features") or "").split(","):  # 2.22.0 (#663): my "stay in touch" for this contact
            from ..life.model import care_get
            d["care"] = care_get(c, uid, r["id"])
    return d


def contact_brief(r):
    em, ph = _jl(r["emails"]), _jl(r["phones"])
    return {"id": r["id"], "book_id": r["book_id"], "fn": r["fn"], "org": r["org"], "kind": r["kind"],
            "email": em[0].get("value", "") if em else "", "phone": ph[0].get("value", "") if ph else "",
            "photo": bool(r["photo"]), "bday": r["bday"], "groups": _jl(r["groups"])}


def contacts_query(c, uid, q="", book=None, group=None, limit=500, offset=0):
    ids = my_book_ids(c, uid)
    if book is not None:
        ids = {k: v for k, v in ids.items() if k == book}
    if not ids:
        return [], 0
    qs = ",".join("?" * len(ids))
    where, args = f"book_id IN ({qs}) AND kind!='group'", list(ids)
    for w in [x for x in re.split(r"\s+", (q or "").lower().strip()) if x][:6]:
        where += " AND search LIKE ? ESCAPE '\\'"
        args.append("%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if group:
        where += " AND groups LIKE ?"
        args.append("%" + json.dumps(group, ensure_ascii=False) + "%")
    n = c.execute(f"SELECT COUNT(*) FROM contacts WHERE {where}", args).fetchone()[0]
    rows = c.execute(f"SELECT * FROM contacts WHERE {where} ORDER BY lower(CASE WHEN family!='' THEN family ELSE fn END), lower(fn), id "
                     "LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    return rows, n


# ---- links to tasks
def link_set(c, uid, cid, tid, kind):
    if kind not in CT_LINKS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    need_contact(c, cid, uid=uid)
    if not task_visible(c, tid, uid, write=True):
        raise Denied(404)
    c.execute("INSERT OR REPLACE INTO contact_tasks(contact_id,task_id,kind,added_by,added_at) VALUES(?,?,?,?,?)",
              (cid, tid, kind, uid, iso(now_utc())))
    c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (iso(now_utc()), tid))
    bump(c)


def link_remove(c, uid, cid, tid):
    if not task_visible(c, tid, uid, write=True):
        raise Denied(404)
    need_contact(c, cid, uid=uid)
    if not c.execute("DELETE FROM contact_tasks WHERE contact_id=? AND task_id=?", (cid, tid)).rowcount:
        raise Denied(404)
    bump(c)


def task_contacts(c, uid, task_ids=None):
    """{task id: [{contact_id, kind, fn}]} of the linked contacts uid may see (for the task panel)."""
    if not contacts_on(c, uid):
        return {}
    ids = my_book_ids(c, uid)
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    out = {}
    for r in c.execute(f"""SELECT l.task_id, l.contact_id, l.kind, k.fn, k.org FROM contact_tasks l JOIN contacts k ON k.id=l.contact_id
                           WHERE k.book_id IN ({q}) ORDER BY l.added_at""", list(ids)):
        if task_ids is None or r[0] in task_ids:
            out.setdefault(r[0], []).append({"contact_id": r[1], "kind": r[2], "fn": r[3] or r[4]})
    return out


# ---- birthdays + anniversaries of own contacts -> yearly tasks (the book's birthday list; module Family)
def occ_sync(c, cid):
    from ..family.family import _jparse, occ_create, occ_next, occ_rule
    r = c.execute("SELECT k.*, b.owner_id, b.occ_list_id, b.src_id AS b_src FROM contacts k JOIN books b ON b.id=k.book_id WHERE k.id=?",
                  (cid,)).fetchone()
    if not r or r["b_src"] or not r["occ_list_id"] or r["kind"] == "group":
        return
    if list_role(c, r["occ_list_id"], r["owner_id"]) not in WRITE_ROLES:
        return
    lg = lang(c, r["owner_id"])
    for kind, val in (("birthday", r["bday"]), ("anniversary", r["anniversary"])):
        ln = c.execute("SELECT * FROM contact_occ WHERE contact_id=? AND kind=?", (cid, kind)).fetchone()
        if not val:
            continue
        if val.startswith("--"):  # --MM-DD: without the year
            mo, dy, y = int(val[2:4]), int(val[5:7]), None
        else:
            mo, dy, y = int(val[5:7]), int(val[8:10]), int(val[:4])
        name = r["fn"][:100]
        dig = f"{name}|{mo}|{dy}|{y}"
        t = c.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (ln["task_id"],)).fetchone() if ln and ln["task_id"] else None
        if t:
            if ln["digest"] == dig:
                continue
            f = _jparse(t["fam"]) or {}
            old_title = tr("Birthday: {0}", f.get("name", ""), lg=lg) if kind == "birthday" else tr("Anniversary: {0}", f.get("name", ""), lg=lg)
            f.update(name=name)
            if y:
                f["year"] = y
            else:
                f.pop("year", None)
            sets = {"fam": json.dumps(f, ensure_ascii=False, separators=(",", ":")), "updated_at": iso(now_utc())}
            if t["title"] == old_title:
                sets["title"] = tr("Birthday: {0}", name, lg=lg) if kind == "birthday" else tr("Anniversary: {0}", name, lg=lg)
            if not t["due"] or (date.fromisoformat(t["due"]).month, date.fromisoformat(t["due"]).day) != (mo, dy):
                sets.update(due=occ_next(mo, dy).isoformat(), repeat=occ_rule(mo, dy), reminded="[]")
            c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), t["id"]])
            c.execute("UPDATE contact_occ SET digest=? WHERE contact_id=? AND kind=?", (dig, cid, kind))
            continue
        if ln:  # its task was deleted by hand: not created again
            continue
        tid = occ_create(c, r["owner_id"], {"name": name, "kind": kind, "date": f"--{mo:02d}-{dy:02d}", "year": y, "lead_days": 7,
                                             "list_id": r["occ_list_id"], "src": f"contact:{cid}"}, check=False)
        f = _jparse(c.execute("SELECT fam FROM tasks WHERE id=?", (tid,)).fetchone()[0]) or {}
        f["card"] = r["uid"][:200]
        c.execute("UPDATE tasks SET fam=? WHERE id=?", (json.dumps(f, ensure_ascii=False, separators=(",", ":")), tid))
        c.execute("INSERT OR REPLACE INTO contact_occ(contact_id,kind,task_id,digest) VALUES(?,?,?,?)", (cid, kind, tid, dig))


# ---- import: vCard files and the external CardDAV accounts of the Family module
def split_vcards(text):
    """Every BEGIN:VCARD ... END:VCARD block, in one linear pass (a regex scan was quadratic on cards without an END)."""
    text = str(text or "").replace("\r\n", "\n")
    up, out, pos = text.upper(), [], 0
    while True:
        a = up.find("BEGIN:VCARD", pos)
        if a < 0:
            break
        b = up.find("END:VCARD", a)
        if b < 0:
            break
        out.append(text[a:b + 9])
        pos = b + 9
    return out


def import_vcards(c, uid, book_id, text, src_digest=False):
    """Every vCard of text into the book: the same UID is updated (importing twice changes nothing). -> counts."""
    res = {"created": 0, "updated": 0, "unchanged": 0, "errors": 0}
    for i, card in enumerate(split_vcards(text)):
        if i >= CONTACTS_PER_BOOK:
            break
        dig = hashlib.sha1(card.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]
        try:
            v = parse_vcard(card)
        except BadInput:
            res["errors"] += 1
            continue
        if not v["fn"]:  # no name, no company, no address: nothing to show
            res["errors"] += 1
            continue
        if not v["uid"]:
            v["uid"] = "import-" + hashlib.sha1((v["fn"] + "|" + json.dumps(v["emails"])).encode("utf-8"), usedforsecurity=False).hexdigest()[:20]
        old = c.execute("SELECT id, src_digest FROM contacts WHERE book_id=? AND uid=?", (book_id, v["uid"])).fetchone()
        if old and src_digest and old["src_digest"] == dig:
            res["unchanged"] += 1
            continue
        f = {k: (json.dumps(v[k], ensure_ascii=False) if isinstance(v[k], list) else v[k]) for k in
             ("kind", "fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "emails", "phones",
              "addresses", "urls", "bday", "anniversary", "note", "groups", "photo")}
        contact_store(c, uid, book_id, f, cid=old["id"] if old else None, uid_=v["uid"], extra=v["extra"], version=v["version"],
                      src_digest=dig if src_digest else None)
        res["updated" if old else "created"] += 1
    return res


def mirror_source(c, sid, cards):
    """2.19 CardDAV source (Family) -> an address book of its own (created once, named after the source): every card is
    stored / updated there, so the contacts can be seen and linked in Kalmido; the birthday tasks of the source stay."""
    s = c.execute("SELECT * FROM contact_srcs WHERE id=?", (sid,)).fetchone()
    if not s or not contacts_on(c, s["user_id"]):
        return None
    r = c.execute("SELECT id FROM books WHERE src_id=? AND owner_id=?", (sid, s["user_id"])).fetchone()
    bid = r[0] if r else book_create(c, s["user_id"], {"name": (s["name"] or tr("Imported contacts", lg=lang(c, s["user_id"])))[:100]}, src_id=sid)
    return import_vcards(c, s["user_id"], bid, "\n".join(cards), src_digest=True)


N_("Contacts")
