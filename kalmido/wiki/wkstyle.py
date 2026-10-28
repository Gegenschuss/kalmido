"""2.371.3 (#3152): the reading style of a knowledge space -- a fixed choice, never CSS of its own (shared, public and
sealed spaces show it alike).

WIKI_STYLES: '' = Clear (as before), 'book' (serif, narrow column, more line spacing), 'compact' (dense, docs), 'notepad'
(paper look). The default of an organisation's space is orgs.wiki_style (its admins set it), the one of the private space
users.wiki_style (the person is its own admin, the freelancer parity). Every person may override it for herself (the
account setting wkSt of the web app, static/js/wklive.js); the browser only maps a known value to a class, the server only
stores a known value. Older versions ignore both columns."""
from flask import g, jsonify

from ..core.config import app
from ..core.db import body, db
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me

WIKI_STYLES = ("", "book", "compact", "notepad")


def wst_get(c, oid, uid):
    """The default style of a space (org id or None = the private space of uid); an unknown stored value = ''."""
    r = (c.execute("SELECT wiki_style FROM orgs WHERE id=?", (oid,)) if oid else
         c.execute("SELECT wiki_style FROM users WHERE id=?", (uid,))).fetchone()
    v = (r[0] if r else "") or ""
    return v if v in WIKI_STYLES else ""


def wst_may(c, oid, uid):
    """May uid set the default style of the space? An organisation: its admins; the private space: its person (no agent)."""
    from ..agents.core import is_agent
    if is_agent(g.user):
        return False
    if not oid:
        return True
    from ..accounts.orgs import is_org_admin
    return is_org_admin(c, uid, oid)


@app.put("/api/wiki/style")
def wiki_style_put():
    """{space: private|org:<id>, style: ''|book|compact|notepad} -- the default reading style of the space (admins of the
    organisation; the private space: the person). Answers {space, style}."""
    from .pages import wiki_space, wiki_space_key
    c, b, uid = db(), body(), me()
    st = b.get("style")
    if not isinstance(st, str) or st not in WIKI_STYLES:
        return jsonify(error=tr("Invalid value: {0}", "style")), 400
    oid = wiki_space(c, uid, b.get("space"))
    if not wst_may(c, oid, uid):
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    if oid:
        c.execute("UPDATE orgs SET wiki_style=? WHERE id=?", (st, oid))
    else:
        c.execute("UPDATE users SET wiki_style=? WHERE id=?", (st, uid))
    c.commit()
    return jsonify(space=wiki_space_key(oid), style=st)
