"""2.47.1 (#1721): a fixed colour per account (agents and people), the same everywhere: the fill behind the initials, a thin
ring around a photo. users.color = a colour of ACCOUNT_COLORS ('' = not given yet). It is given once and then kept: at
the start for the accounts from before, later the first time somebody's state lists the account. Per organisation the
agents come first, then the people, each gets the colour used least among its organisation (ties: palette order). Every
person changes their own colour in the profile, admins / organisation admins / owners the colour of an agent."""
from ..core.pg import system_ctx, write_lock

# readable with white (dark ones) or dark initials in the light and the dark theme; the order spreads the hues, so the
# first accounts of an organisation differ clearly (the client keeps the same list: ACCOUNT_COLORS in core.js)
ACCOUNT_COLORS = ("#3e63dd", "#f76b15", "#30a46c", "#a43cb4", "#cf3539", "#12a594",
                  "#e2a336", "#c2307f", "#2aa7dc", "#8d5f3e", "#6e56cf", "#99b13a")


def ac_valid(v):
    return isinstance(v, str) and v.lower() in ACCOUNT_COLORS


def _ac_peers(c, uid):
    """The accounts whose colours an account should differ from: its organisations' members and agents; without an
    organisation the people it shares lists with and the personal agents (of itself / its owner)."""
    a = c.execute("SELECT org_id, owner_id FROM agents WHERE user_id=?", (uid,)).fetchone()
    orgs = [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=?", (uid,))]
    if a and a["org_id"]:
        orgs.append(a["org_id"])
    if orgs:
        ph = ",".join("?" * len(orgs))
        return c.execute(f"""SELECT u.color FROM users u WHERE u.id!=? AND u.color!='' AND (u.id IN (SELECT user_id FROM org_members
                             WHERE org_id IN ({ph})) OR u.id IN (SELECT user_id FROM agents WHERE org_id IN ({ph})))""",
                         (uid, *orgs, *orgs)).fetchall()
    base = a["owner_id"] if a and a["owner_id"] else uid
    return c.execute("""SELECT u.color FROM users u WHERE u.id!=? AND u.color!='' AND (u.id=? OR u.id IN
                        (SELECT user_id FROM agents WHERE owner_id=?) OR u.id IN
                        (SELECT owner_id FROM lists WHERE id IN (SELECT list_id FROM list_members WHERE user_id=?)) OR u.id IN
                        (SELECT user_id FROM list_members WHERE list_id IN (SELECT id FROM lists WHERE owner_id=?
                         UNION SELECT list_id FROM list_members WHERE user_id=?)))""",
                     (uid, base, base, base, base, base)).fetchall()


def ac_pick(c, uid):
    used = {}
    for r in _ac_peers(c, uid):
        used[r[0]] = used.get(r[0], 0) + 1
    return min(ACCOUNT_COLORS, key=lambda k: (used.get(k, 0), ACCOUNT_COLORS.index(k)))


def ac_assign(c, uids=None):
    """Gives the accounts uids (None = every account) without a colour one; agents first. Returns how many got one.
    Counting the colours of other organisations' accounts needs the system context; nothing of them leaves this function."""
    with system_ctx(c):
        q = "SELECT id FROM users WHERE color=''"
        args = ()
        if uids is not None:
            ids = [int(x) for x in uids]
            if not ids:
                return 0
            q += f" AND id IN ({','.join('?' * len(ids))})"
            args = tuple(ids)
        todo = [r[0] for r in c.execute(q + " ORDER BY CASE WHEN kind='agent' THEN 0 ELSE 1 END, id", args)]
        if not todo:
            return 0
        write_lock(c, "ac_color")  # two requests at once: the second one sees the first one's colours
        n = 0
        for uid in todo:
            n += c.execute("UPDATE users SET color=? WHERE id=? AND color=''", (ac_pick(c, uid), uid)).rowcount
        return n


def ac_color_map(c, uid):
    """{user id: colour} of the accounts I see anyway: me, the people of my lists (like avatar_map), the members and agents
    of my organisations and my personal agents. Accounts without a colour get one here (committed at once)."""
    from ..core.access import vis_sql
    rows = c.execute(f"""SELECT id, color FROM users WHERE id=? OR id IN (SELECT owner_id FROM lists WHERE id IN {vis_sql()})
                         OR id IN (SELECT user_id FROM list_members WHERE list_id IN {vis_sql()})
                         OR id IN (SELECT user_id FROM org_members WHERE org_id IN (SELECT org_id FROM org_members WHERE user_id=?))
                         OR id IN (SELECT user_id FROM agents WHERE owner_id=? OR org_id IN
                                   (SELECT org_id FROM org_members WHERE user_id=?))""",
                     (uid, uid, uid, uid, uid, uid, uid, uid)).fetchall()
    missing = [r["id"] for r in rows if not r["color"]]
    if missing and ac_assign(c, missing):
        c.commit()
        rows = c.execute(f"SELECT id, color FROM users WHERE id IN ({','.join('?' * len(rows))})",
                         tuple(r["id"] for r in rows)).fetchall()
    return {str(r["id"]): r["color"] for r in rows if r["color"]}
