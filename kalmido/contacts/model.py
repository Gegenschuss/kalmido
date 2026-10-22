"""Contacts (module "contacts"): address books, rights, vCard 3 / 4 reading + writing, search, links to tasks, birthdays."""
import base64
import hashlib
import json
import quopri
import re
import secrets
import time
import urllib.parse
from datetime import date

from flask import has_request_context

from ..core.i18n import lang, N_, tr
from ..core.pg import insert_id, like_escape, system_ctx
from ..core.db import bump, iso, iso_ms, local_now, now_utc, usettings
from ..accounts.session import me
from ..core.access import acx_org_ok, collab_all, Denied, list_role, org_trips_hidden, task_visible, WRITE_ROLES
from ..tasks.validation import DATE_MIN_Y
from ..collab.comments import user_names
from ..core.errors import BadInput
from ..core.config import APP_NAME, APP_VERSION  # 2.149.0 G (#2517): pulled up from functions


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
# 2.52.0 C (#1438): an address book can belong to an organisation (owner_org_id = its org_id, NULL = a person's book). Its
# admins manage it (role 'owner'), its other members (people, no kid accounts, no agents) read or change it as org_role
# says (view | edit | none); shares (book_members) add to that. owner_id stays filled: the technical manager (whose lists the
# birthdays go to), without rights of its own -- leaving the organisation or deleting the account hands it on (orgbooks.py).
BOOK_RANK = {None: 0, "view": 1, "edit": 2, "owner": 3}


def obk_org(b):
    return (b["owner_org_id"] if "owner_org_id" in b.keys() else None) or None


def obk_org_role(c, uid, oid, org_role):
    """The role person uid has in an address book of organisation oid through that organisation: 'owner' for its admins,
    org_role ('view' | 'edit') for its other members, else None. Agents and kid accounts only through a share."""
    from ..accounts.orgs import org_role as om_role
    u = c.execute("SELECT kind, kid FROM users WHERE id=?", (uid,)).fetchone()
    if not u or (u["kind"] or "user") == "agent" or u["kid"] or c.execute("SELECT 1 FROM agents WHERE user_id=?", (uid,)).fetchone():
        return None
    r = om_role(c, uid, oid)
    if r == "admin":
        return "owner"
    if r in ("guest", "accounting"):
        return None  # 2.143.0 A (#2151): only books shared with them personally
    if r == "readonly" and org_role in BOOK_ROLES:
        return "view"  # 2.143.0 A (#2151)
    return org_role if r and collab_all() and org_role in BOOK_ROLES else None


def book_role(c, uid, b):
    """2.143.0 A (#2151): read-only in the book's organisation -> view."""
    role = _book_role(c, uid, b)
    return _bk_ro(c, uid, b["org_id"] if role and "org_id" in b.keys() else None, role)


def _bk_ro(c, uid, oid, role):
    if role and oid and role != "view":
        from ..accounts.orgroles import org_readonly
        if org_readonly(c, uid, oid):
            return "view"
    return role


def _book_role(c, uid, b):
    if b is None:
        return None
    if "org_id" in b.keys() and not acx_org_ok(c, uid, b["org_id"]):  # 2.36.2 (#1142): organisation books: members only
        return None
    if obk_org(b):  # 2.52.0 C (#1438): an organisation's address book -- its roles, plus a share; the manager's account does not matter
        if b["org_id"] != b["owner_org_id"]:
            return None  # never across the boundary (the nightly check counts such a row)
        role = obk_org_role(c, uid, b["owner_org_id"], b["org_role"])
        r = c.execute("SELECT role FROM book_members WHERE book_id=? AND user_id=?", (b["id"], uid)).fetchone() if collab_all() else None
        return max(role, r[0] if r else None, key=lambda x: BOOK_RANK.get(x, 0))
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
    out = {r[0]: "owner" for r in c.execute("SELECT id, org_id FROM books WHERE owner_id=? AND owner_org_id IS NULL", (uid,))
           if acx_org_ok(c, uid, r[1])}
    from ..accounts.orgs import user_orgs
    oids = user_orgs(c, uid)
    if oids:  # 2.52.0 C (#1438): the address books of my organisations, as their roles allow
        base = {}  # per organisation: admin ('owner') or a member who gets the book's org_role (one lookup each)
        for r in c.execute(f"SELECT id, owner_org_id, org_role FROM books WHERE owner_org_id IN ({','.join('?' * len(oids))}) "
                           "AND org_id=owner_org_id", oids).fetchall():
            if r[1] not in base:
                base[r[1]] = obk_org_role(c, uid, r[1], "edit") if acx_org_ok(c, uid, r[1]) else None
            role = base[r[1]] if base[r[1]] in (None, "owner") else (r[2] if r[2] in BOOK_ROLES else None)
            if role:
                out[r[0]] = role
    if collab_all():
        for r in c.execute("SELECT m.book_id, m.role, b.org_id, b.owner_org_id FROM book_members m JOIN books b ON b.id=m.book_id "
                           "JOIN users u ON u.id=b.owner_id WHERE m.user_id=? AND (u.disabled=0 OR b.owner_org_id IS NOT NULL)", (uid,)):
            if acx_org_ok(c, uid, r[2]) and (not r[3] or r[3] == r[2]):  # 2.36.2 (#1142): organisation books only for its members
                if BOOK_RANK.get(r[1], 0) > BOOK_RANK.get(out.get(r[0]), 0):  # 2.52.0 C (#1438): the better of share + organisation role
                    out[r[0]] = r[1]
    from ..accounts.orgroles import org_roles_of
    if out and "readonly" in org_roles_of(c, uid).values():  # 2.143.0 A (#2151)
        orgs = {r[0]: r[1] for r in c.execute(f"SELECT id, org_id FROM books WHERE id IN ({','.join(str(int(k)) for k in out)})")}
        out = {k: _bk_ro(c, uid, orgs.get(k), v) for k, v in out.items()}
    return out


def book_public(c, b, uid, names=None):
    role = book_role(c, uid, b)
    d = {"id": b["id"], "name": b["name"], "color": b["color"], "owner_id": b["owner_id"], "role": role,
         "org_id": b["org_id"],  # 2.30.0 (#1036): its workspace (None = private)
         "imported": bool(b["src_id"]), "birthdays_list_id": b["occ_list_id"] if role == "owner" else None,
         "count": c.execute("SELECT COUNT(*) FROM contacts WHERE book_id=? AND kind!='group'", (b["id"],)).fetchone()[0]}
    if names is not None:
        d["owner_name"] = names.get(b["owner_id"], "?")
    oo = obk_org(b)  # 2.52.0 C (#1438): owned by the organisation (org_role: what its members may), or may go to it (can_org)
    d["org_owned"], d["org_role"] = bool(oo), (b["org_role"] if oo else None)
    d["can_org"] = bool(not oo and role == "owner" and b["org_id"] and not b["src_id"] and obk_can_take(c, uid, b["org_id"]))
    if role == "owner":
        d["members"] = [{"user_id": m[0], "role": m[1]} for m in
                        c.execute("SELECT user_id, role FROM book_members WHERE book_id=? ORDER BY added_at", (b["id"],))]
    return d


def obk_can_take(c, uid, oid):
    """May person uid hand an address book over to organisation oid? Only its admins; never a personal office."""
    with system_ctx(c):  # the organisation row itself (a personal office is a hidden orgs row)
        real = c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL AND retired_at IS NULL", (oid,)).fetchone()
    return bool(real) and obk_org_role(c, uid, oid, "none") == "owner"


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
    if c.execute("SELECT COUNT(*) FROM books WHERE owner_id=? AND owner_org_id IS NULL", (uid,)).fetchone()[0] >= BOOKS_MAX:  # 2.52.0 C (#1438): own books
        raise Denied(409, tr("At most {0} address books", BOOKS_MAX))
    used = [r[0] for r in c.execute("SELECT color FROM books WHERE owner_id=?", (uid,))]
    col = f.get("color") or next((x for x in BOOK_COLORS if x not in used), BOOK_COLORS[0])
    ts = iso_ms(now_utc())
    return insert_id(c, "INSERT INTO books(owner_id,name,color,src_id,created_at,changed_at,org_id) VALUES(?,?,?,?,?,?,?)",
                     (uid, f["name"], col, src_id, ts, ts, oid))


def default_book(c, uid, create=True):
    r = c.execute("SELECT id FROM books WHERE owner_id=? AND src_id IS NULL AND owner_org_id IS NULL ORDER BY id LIMIT 1", (uid,)).fetchone()
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
    if not u or (uid == b["owner_id"] and not obk_org(b)) or personal_agent_foreign(c, uid, me()):  # 2.52.0 C (#1438): an org book's manager may be shared with
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
    r = c.execute(f"SELECT id FROM contacts WHERE book_id IN ({q}) AND lower(emails) ILIKE ? ESCAPE '\\' ORDER BY id LIMIT 1",
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
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if "QUOTED-PRINTABLE" in text.upper():
        text = vc_qp_join(text)
    return re.sub(r"\n[ \t]", "", text).split("\n")


def vc_qp_join(text):
    """2.45.1 (#1555): vCard 2.1 quoted-printable values: a line ending in '=' (soft line break) goes on in the next line;
    joined before the normal unfolding (that next line has no leading blank)."""
    out, cur = [], None
    for ln in text.split("\n"):
        if cur is not None and ln.strip().upper() == "END:VCARD":  # a dangling soft break must not swallow the end of the card
            out.extend((cur, ln))
            cur = None
            continue
        if cur is not None:
            cur += ln
        elif vc_is_qp(ln):
            cur = ln
        else:
            out.append(ln)
            continue
        if cur.endswith("="):
            cur = cur[:-1]
        else:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return "\n".join(out)


def vc_is_qp(ln):
    """A property line with a QUOTED-PRINTABLE parameter (no regex: two [^:]* around ';' were quadratic on long lines)."""
    head = ln.split(":", 1)[0]
    return ":" in ln and ";" in head and "QUOTED-PRINTABLE" in head.upper()


def vc_qp_decode(val, params):
    """2.45.1 (#1555): a quoted-printable value (vCard 2.1) -> text in its CHARSET (UTF-8 by default, else Latin-1)."""
    raw = quopri.decodestring(val.encode("utf-8"))
    cs = (params.get("CHARSET") or ["utf-8"])[0].strip() or "utf-8"
    for enc in (cs, "utf-8", "latin-1"):
        try:
            return raw.decode(enc).replace("\r\n", "\n")
        except (LookupError, UnicodeError, ValueError):  # e.g. CHARSET=undefined raises a bare UnicodeError
            continue
    return val


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
    if "QUOTED-PRINTABLE" in (x.upper() for x in params.get("ENCODING", []) + params.get("TYPE", [])):  # 2.45.1 (#1555)
        val = vc_qp_decode(val, params)
    return grp, name, params, val


def _types(params):
    t = [x for x in params.get("TYPE", []) if x and x not in ("internet", "x400", "pref", "voice", "quoted-printable", "base64", "8bit")]
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
                if not ph and re.match(r"https://", vc_unesc(val).strip(), re.I):
                    v["photo_url"] = vc_unesc(val).strip()  # 2.47.3 (#1738): a link; the file import may fetch it (photo_fetch)
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


# 2.47.3 (#1738): Google Contacts exports PHOTO as a link. The file import fetches it: only https on *.googleusercontent.com, at
# most PHOTO_FETCH_BYTES, a few seconds each and a budget per import, through the calendar module's SSRF guard (every resolved
# address must be public, no redirect to another host). Google's grey default pictures (the anonymous user, letters) are skipped.
PHOTO_FETCH_BYTES, PHOTO_FETCH_S = 2 * 1024 * 1024, 5
PHOTO_HOST = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)*\.googleusercontent\.com")
PHOTO_DEFAULT = re.compile(r"default-user|/AAAAAAAAAAA/")
PHOTO_MIN_BYTES = 1200  # a flat single-colour picture is smaller than this


def photo_url_ok(url):
    try:
        p = urllib.parse.urlsplit(url)
        host, port = (p.hostname or "").lower(), p.port
    except ValueError:
        return False
    return p.scheme == "https" and not p.username and not p.password and port in (None, 443) and bool(PHOTO_HOST.fullmatch(host)) \
        and not PHOTO_DEFAULT.search(p.path)


def photo_fetch(url, timeout=PHOTO_FETCH_S):
    """The picture behind a Google photo link as a data URI, '' when it is not allowed / not fetchable / a placeholder."""
    if not photo_url_ok(url):
        return ""
    from ..calendars.subscriptions import cal_http
    if not urllib.parse.urlsplit(url).query:
        url = re.sub(r"=[^/?#]*$", "", url) + "=s256"  # Google's image server resizes by this suffix
    try:
        st, hd, data, final = cal_http(url, max_bytes=PHOTO_FETCH_BYTES, timeout=timeout, deadline=timeout * 2)
    except Exception:  # noqa: BLE001 -- any failure just leaves the contact without the picture
        return ""
    if st != 200 or len(data) < PHOTO_MIN_BYTES or not photo_url_ok(final):
        return ""
    t = "jpeg" if data[:3] == b"\xff\xd8\xff" else "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "gif" if data[:4] == b"GIF8" else \
        "webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else ""
    uri = f"data:image/{t};base64," + base64.b64encode(data).decode("ascii") if t else ""
    return uri if uri and len(uri) <= PHOTO_MAX else ""


def _params_out(t, pref, version):
    out = ""
    if t:
        out += ";TYPE=" + ",".join(re.sub(r"[^a-z0-9-]", "", x) for x in t if re.sub(r"[^a-z0-9-]", "", x))
    if pref:
        out += ";PREF=1" if version == "4.0" else (";TYPE=pref" if not t else ",pref")
    return out


def render_vcard(r, rev=None):
    """The vCard text of a contact row (in its own version, 3.0 or 4.0)."""
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


CT_COPY_COLS = ("kind", "fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "emails", "phones",
                "addresses", "urls", "bday", "anniversary", "note", "groups", "photo")


def contact_copy(c, uid, cid, book_id):
    """2.138.4 C (#2378): a contact of an imported (mirrored) address book is copied, not moved: its source would bring it
    back at the next sync, so the mirror stays as it is and the target gets a new contact with the same card. -> new id."""
    r = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    return contact_store(c, uid, book_id, {k: r[k] for k in CT_COPY_COLS}, uid_=r["uid"], extra=r["extra"], version=r["version"])


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


def contact_store(c, uid, book_id, f, cid=None, uid_=None, href=None, extra=None, version=None, src_digest=None, bulk=None):
    """Creates (cid None) or changes a contact with validated columns f. Returns its id; the caller commits.
    2.41.0 (#1437): bulk = {"occ": bool} from import_vcards: the caller counts once, touches the book and bumps the version
    once per batch (each per card held the instance-wide version row locked until the end of a large import)."""
    ts = iso_ms(now_utc())  # ms: two changes in one second still differ (expect)
    if cid is None:
        if bulk is None and c.execute("SELECT COUNT(*) FROM contacts WHERE book_id=?", (book_id,)).fetchone()[0] >= CONTACTS_PER_BOOK:
            raise Denied(409, tr("At most {0} contacts per address book", CONTACTS_PER_BOOK))
        uid_ = uid_ or new_uid()
        cols = {k: f.get(k, "" if k not in ("emails", "phones", "addresses", "urls", "groups") else "[]") for k in
                ("kind", "fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "emails", "phones",
                 "addresses", "urls", "bday", "anniversary", "note", "groups", "photo")}
        cols["kind"] = cols["kind"] or "individual"
        if not href:  # 2.126.0 C (#1992 K8): a UID with other characters (or a long one) gets a hash, so two never share a name
            base = re.sub(r"[^A-Za-z0-9._-]", "_", uid_)
            href = (base if base == uid_ and len(base) <= 180 else base[:170] + "-" + hashlib.sha256(uid_.encode()).hexdigest()[:8]) + ".vcf"
        cols.update(book_id=book_id, uid=uid_, href=href, extra=extra or "",
                    version=version or "3.0", src_digest=src_digest or "", created_by=uid, created_at=ts, updated_at=ts)
        cols["search"] = search_text({**cols, **{k: _jl(cols[k]) for k in ("emails", "phones", "addresses", "groups")}})
        cid = insert_id(c, f"INSERT INTO contacts({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(cols.values()))
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
    if bulk is not None:
        if bulk.get("occ"):
            occ_sync(c, cid)
        return cid
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
    from ..newsletter.sync import nwl_contact_json
    d["newsletter"] = nwl_contact_json(r)  # 2.55.0 (#1455): the newsletter consent (read only here, set via /api/newsletter/consent)
    if links and uid:
        d["tasks"] = [{"task_id": x["task_id"], "kind": x["kind"], "title": x["title"], "status": x["status"]}
                      for x in c.execute("""SELECT l.task_id, l.kind, t.title, t.status FROM contact_tasks l JOIN tasks t ON t.id=l.task_id
                                            WHERE l.contact_id=? AND t.deleted_at IS NULL ORDER BY t.status, t.due IS NULL, t.due""", (r["id"],))
                      if task_visible(c, x["task_id"], uid)]
        d["events"] = []
        from ..events.model import need_event
        for e in c.execute("""SELECT e.id FROM events e WHERE e.id IN (SELECT a.event_id FROM event_attendees a WHERE a.contact_id=?)
                              AND e.deleted_at IS NULL ORDER BY e.first_day DESC LIMIT 50""", (r["id"],)):
            try:
                er, _ = need_event(c, e[0], uid=uid)
            except Denied:
                continue
            d["events"].append({"event_id": er["id"], "title": er["title"], "start": er["start"], "all_day": bool(er["all_day"])})
        if "care" in (usettings(c, uid).get("features") or "").split(","):  # 2.22.0 (#663): my "stay in touch" for this contact
            from ..life.model import care_get, care_space
            if not (org_trips_hidden() and care_space(c, r["book_id"])):  # 2.173.0 review (#2680): an organisation's, not for agents / tokens
                d["care"] = care_get(c, uid, r["id"])
        from ..office.contacts_cl import ckl_contact_clients
        cl = ckl_contact_clients(c, r["id"], uid)
        if cl:  # 2.59.0 (#1735): "contact person at <client>" -- only for people who may open the client, else no field
            d["clients"] = cl
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
        where += " AND search ILIKE ? ESCAPE '\\'"
        args.append("%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if group:
        where += " AND groups ILIKE ? ESCAPE '\\'"
        args.append("%" + like_escape(json.dumps(group, ensure_ascii=False)) + "%")
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
    c.execute("INSERT INTO contact_tasks(contact_id,task_id,kind,added_by,added_at) VALUES(?,?,?,?,?) ON CONFLICT (contact_id,task_id) DO UPDATE SET kind=excluded.kind, added_by=excluded.added_by, added_at=excluded.added_at",
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
    from ..collab.liste2e import le2a_gen_locked
    if le2a_gen_locked(c, r["occ_list_id"]):  # 2.64.1 review (M3): no plain birthday titles in a list with the lock
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
            # 2.82.0 (#1832): the task may live in another list by now (moved): only changed where the owner may write
            if t["list_id"] != r["occ_list_id"] and (list_role(c, t["list_id"], r["owner_id"]) not in WRITE_ROLES
                                                    or le2a_gen_locked(c, t["list_id"])):
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
        c.execute("INSERT INTO contact_occ(contact_id,kind,task_id,digest) VALUES(?,?,?,?) ON CONFLICT (contact_id,kind) DO UPDATE SET task_id=excluded.task_id, digest=excluded.digest", (cid, kind, tid, dig))


# ---- import: vCard files and the external CardDAV accounts of the Family module
VC_BEGIN_RE = re.compile("BEGIN:VCARD", re.I)
VC_END_RE = re.compile("END:VCARD", re.I)


def split_vcards(text):
    """Every BEGIN:VCARD ... END:VCARD block, in one linear pass (a regex scan was quadratic on cards without an END)."""
    # 2.45.1 (#1555): searched case-insensitively in the text itself - 'ß'.upper() is 'SS', so positions found in text.upper()
    # slid off the original after the first ß and almost every card after it was cut in the wrong place
    text, out, pos = str(text or "").replace("\r\n", "\n"), [], 0
    while True:
        a = VC_BEGIN_RE.search(text, pos)
        if not a:
            break
        b = VC_END_RE.search(text, a.end())
        if not b:
            break
        out.append(text[a.start():b.end()])
        pos = b.end()
    return out


IMPORT_BATCH = 200


def import_vcards(c, uid, book_id, text, src_digest=False, batch=None, progress=None, cards=None, photos=0):
    """Every vCard of text into the book: the same UID is updated (importing twice changes nothing). -> counts.
    2.41.0 (#1437): the book is counted once, birthdays are synced only where the book keeps them, the book is touched and
    the version bumped once per batch; batch=N commits every N cards (a large import keeps what it did and never holds the
    instance-wide version row for long); progress(done, total, res) after each batch.
    2.47.3 (#1738): photos=N (seconds of budget; only the file import) fetches PHOTO links of Google's image server; an existing
    contact that already has a picture keeps it, so importing the same file again only adds the missing ones."""
    res = {"created": 0, "updated": 0, "unchanged": 0, "errors": 0}
    cards = split_vcards(text) if cards is None else cards
    bk = c.execute("SELECT occ_list_id, src_id FROM books WHERE id=?", (book_id,)).fetchone()
    bulk = {"occ": bool(bk and bk["occ_list_id"] and not bk["src_id"])}
    have = c.execute("SELECT COUNT(*) FROM contacts WHERE book_id=?", (book_id,)).fetchone()[0]
    dirty = False
    t_photos = time.monotonic() + photos

    def flush(i):
        nonlocal dirty
        if dirty:
            book_touch(c, book_id)
            bump(c)
            dirty = False
        if batch:
            c.commit()
        if progress:
            progress(i, len(cards), res)

    for i, card in enumerate(cards):
        if i >= CONTACTS_PER_BOOK:
            break
        if batch and i and i % batch == 0:
            flush(i)
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
        old = c.execute("SELECT id, src_digest, photo FROM contacts WHERE book_id=? AND uid=?", (book_id, v["uid"])).fetchone()
        if photos and not v["photo"] and v.get("photo_url"):
            v["photo"] = (old["photo"] if old else "") or (photo_fetch(v["photo_url"]) if time.monotonic() < t_photos else "")
            if v["photo"]:  # the link is replaced by the picture (it would be sent twice otherwise)
                v["extra"] = "\n".join(x for x in v["extra"].split("\n") if not (x.upper().startswith("PHOTO") and v["photo_url"] in x))
        if old and src_digest and old["src_digest"] == dig:
            res["unchanged"] += 1
            continue
        f = {k: (json.dumps(v[k], ensure_ascii=False) if isinstance(v[k], list) else v[k]) for k in
             ("kind", "fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "emails", "phones",
              "addresses", "urls", "bday", "anniversary", "note", "groups", "photo")}
        if not old and have >= CONTACTS_PER_BOOK:
            flush(i)  # what is stored so far stays (batch) / is committed by the caller
            raise Denied(409, tr("At most {0} contacts per address book", CONTACTS_PER_BOOK))
        contact_store(c, uid, book_id, f, cid=old["id"] if old else None, uid_=v["uid"], extra=v["extra"], version=v["version"],
                      src_digest=dig if src_digest else None, bulk=bulk)
        have += 0 if old else 1
        dirty = True
        res["updated" if old else "created"] += 1
    flush(min(len(cards), CONTACTS_PER_BOOK))
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
