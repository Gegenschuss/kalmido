"""2.151.0 A (#2558): the build state of a task -- the list's repository is the evidence, the task list the truth."""
import re
import urllib.parse
from flask import g, jsonify

from ..core.config import app
from ..core.db import body, bump, db, err, iso, now_utc
from ..core.i18n import tr
from ..core.access import need_list, plists, pvis
from ..core.pg import st_ids
from ..api.v1 import v1_args, v1_view
from .git import (CalError, git_api, git_branch_id, git_commit_norm, git_conn_lists, git_conns_of_list, git_http, git_items,
                  git_need_manage, git_take_commits, git_task_ids, git_urls, git_version, GitRate, GIT_ITEMS, _gs)


# ---------------------------------------------------------------- 2.151.0 A (#2558): what was built for a task, and is it live
# Kalmido is the ground truth for tickets and releases, not the tools next to it: every task of a list with a
# repository carries code.build = {state, version, branches, package, stale}:
#  state "released" = a linked commit (or the merge commit of a linked merged pull request) is in a version tag (version = the
#  highest such tag; null when it is older than every tag Kalmido looked at), "main" = in the default branch, no tag yet,
#  "branch" = only on a branch / an open pull request, "none" = nothing linked.
#  branches = branches of the task (kalmido-<id>, task-<id>, <id>-slug, or the branch of its open pull request) with commits
#  the default branch does not have (ahead > 0), also after a release (new work).
#  package = the list's version field ("Package", "Version", "Release", "Target version" ..., or the one picked in the
#  repository dialog) and whether a tag with exactly that version exists (2.151 = 2.151.0; "2.46c" cannot be checked: never
#  released). Deliberately no "lower than the newest version": packages are built in parallel and renumbered.
#  stale = the task is still open although its package or its code is released.
# The poll (git.py git_poll) finds it out with few requests: per NEW version tag one compare with the version before it
# (the first tag that holds a commit wins), once for an existing connection the newest GB_FILL_TAGS tags; one branch list
# (ETag) and a compare only for a branch whose head or the default branch moved (at most GB_BRANCH_CMP per poll).
GB_FILL_TAGS = 11          # newest version tags compared pairwise once (10 compares) for a connection made before 2.151
GB_TAG_CMP = 3             # tag compares per poll
GB_BRANCH_CMP = 5          # branch compares per poll
GB_CMP_MAX = 250           # commits of one compare that are looked at
GB_VER_NAMES = ("paket", "package", "version", "release", "ziel-version", "target version")
GB_VER_RE = re.compile(r"[vV]?(\d{1,9}(?:\.\d{1,9}){0,3})")


def gb_key(v):
    """A version (tag name or field value) -> its sort key (4 numbers, missing ones 0), None unless it is digits with dots
    and an optional leading v (2.151 == 2.151.0 == v2.151.0; "2.46c", "nightly", "2.1-rc1" are none)."""
    m = GB_VER_RE.fullmatch(str(v or "").strip())
    if not m:
        return None
    n = [int(x) for x in m.group(1).split(".")]
    return tuple(n + [0] * (4 - len(n)))


def _gb_api(prov, k, what, a="", b=""):
    """Paths of the build requests per provider: branches (one page) | tagcmp (the commits of tag b not in tag a)."""
    p, e = k["path"], (lambda s: urllib.parse.quote(s, safe=""))
    if what == "branches":
        return {"gitlab": f"{p}/repository/branches?per_page=100", "bitbucket": f"{p}/refs/branches?pagelen=100",
                "gitea": f"{p}/branches?limit=50"}.get(prov) or f"{p}/branches?per_page=100"
    if prov == "bitbucket":  # one page of the newest 100
        return f"{p}/commits/{e(b)}?exclude={e(a)}&pagelen=100"
    return git_api(prov, k, "compare", a, b)


def _gb_get(k, path):
    st, _, j = git_http(k, path)
    if k["low"]:
        raise GitRate(k["low"])
    return j if st == 200 else None


def _gb_cmp(j, prov):
    """A compare answer -> (commits oldest first in the GitHub shape, ahead or None)."""
    if isinstance(j, dict) and isinstance(j.get("commits"), list):
        lst = j["commits"]
        n = j.get("ahead_by") if isinstance(j.get("ahead_by"), int) else j.get("total_commits") if isinstance(j.get("total_commits"), int) else len(lst)
    elif prov == "bitbucket" and git_items(j) is not None:
        lst = list(reversed(git_items(j)))
        n = len(lst)
    else:
        return None, None
    return [git_commit_norm(x, prov) for x in lst[-GB_CMP_MAX:]], n


def _gb_shas(lst):
    return [x["sha"][:64] for x in lst if isinstance(x, dict) and isinstance(x.get("sha"), str)]


def _gb_link(c, r, lst, branch):
    """Links the compare's commits that name a task (git_take_commits looks at GIT_ITEMS at a time; never completes a task)."""
    ch = False
    for i in range(0, len(lst), GIT_ITEMS):
        ch |= git_take_commits(c, r, lst[i:i + GIT_ITEMS], branch, False)
    return ch


def gb_main(c, r, item):
    """The default branch's newest commit (a branch is compared again once it moved)."""
    sha = _gs(item.get("sha") if isinstance(item, dict) else "", 64)
    if sha and sha != (r["main_sha"] or ""):
        c.execute("UPDATE git_conns SET main_sha=? WHERE id=?", (sha, r["id"]))


def gb_tags(c, r, k, prov):
    """The first version tag of the linked commits: compare each version tag not looked at yet with the version before it
    (ascending, at most GB_TAG_CMP per poll; tags seen after the baseline, or among the newest GB_FILL_TAGS). A compare that
    fails (tag gone, no access) is not tried again (cmp 2)."""
    rows = c.execute("SELECT name, cmp, seen_at FROM git_tags WHERE conn_id=?", (r["id"],)).fetchall()
    vt = sorted(((gb_key(x["name"]), x["name"], x) for x in rows if gb_key(x["name"])), key=lambda y: (y[0], y[1]))
    if len(vt) < 2:
        return False
    window, base = {x[1] for x in vt[-GB_FILL_TAGS:]}, r["tags_at"] or ""
    todo = [i for i, (_, n, x) in enumerate(vt) if i and not x["cmp"] and (n in window or (x["seen_at"] or "") > base)][:GB_TAG_CMP]
    changed, floor = False, r["tags_floor"] or ""
    for i in todo:
        prev, name = vt[i - 1][1], vt[i][1]
        try:
            lst, _ = _gb_cmp(_gb_get(k, _gb_api(prov, k, "tagcmp", prev, name)), prov)
        except CalError:
            lst = None
        if lst is None:
            c.execute("UPDATE git_tags SET cmp=2 WHERE conn_id=? AND name=?", (r["id"], name))
            continue
        changed |= _gb_link(c, r, lst, r["default_branch"] or "")
        shas = _gb_shas(lst)
        for j in range(0, len(shas), 100):
            part = shas[j:j + 100]
            q = ",".join("?" * len(part))
            changed |= bool(c.execute(f"UPDATE git_commits SET tag=? WHERE conn_id=? AND tag='' AND sha IN ({q})", (name, r["id"], *part)).rowcount)
            changed |= bool(c.execute(f"UPDATE git_prs SET tag=? WHERE conn_id=? AND tag='' AND merge_sha IN ({q})", (name, r["id"], *part)).rowcount)
        ats = [m["commit"]["committer"]["date"] for m in lst if isinstance(m, dict) and isinstance(m.get("commit"), dict)
               and isinstance(m["commit"].get("committer"), dict) and isinstance(m["commit"]["committer"].get("date"), str)]
        if ats and (not floor or min(ats) < floor):
            floor = min(ats)
        c.execute("UPDATE git_tags SET cmp=1 WHERE conn_id=? AND name=?", (r["id"], name))
    if floor != (r["tags_floor"] or ""):
        c.execute("UPDATE git_conns SET tags_floor=? WHERE id=?", (floor, r["id"]))
    return changed


def _gb_branch_of(x, prov):
    if not isinstance(x, dict):
        return "", ""
    cm = x.get("target") if prov == "bitbucket" else x.get("commit")
    cm = cm if isinstance(cm, dict) else {}
    return _gs(x.get("name"), 250), _gs(cm.get("hash") or cm.get("sha") or cm.get("id"), 64)


def gb_branches(c, r, k, get, prov):
    """Branches with a task's name (or the branch of an open pull request of a task) and how far they are ahead of the
    default branch. get = the poll's GET with ETag (None = unchanged since the last poll)."""
    cid, default = r["id"], r["default_branch"] or ""
    try:  # optional like the tags: a server without the endpoint never breaks the poll
        j = git_items(get("branches", _gb_api(prov, k, "branches")))
    except CalError:
        j = None
    changed = False
    if j is not None:
        heads = {}
        for x in j:
            n, sha = _gb_branch_of(x, prov)
            if n and n != default:
                heads[n] = sha
        ids = {n: git_branch_id(n) for n in heads}
        live = git_task_ids(c, git_conn_lists(c, r), {i for i in ids.values() if i})
        pr = {x["head_ref"]: x["tid"] for x in c.execute(
            """SELECT p.head_ref, MIN(l.task_id) AS tid FROM git_prs p JOIN git_links l ON l.conn_id=p.conn_id AND l.kind='pr'
               AND l.ref=CAST(p.number AS TEXT) WHERE p.conn_id=? AND p.state='open' AND p.head_ref<>'' GROUP BY p.head_ref""", (cid,))}
        want = {n: (ids[n] if ids[n] in live else pr.get(n)) for n in heads}
        want = {n: t for n, t in want.items() if t}
        for x in c.execute("SELECT name, ahead FROM git_branches WHERE conn_id=?", (cid,)).fetchall():
            if x["name"] not in want:  # gone (deleted after the merge) or no task any more
                if x["ahead"] == 0:  # merged: its commits are in the default branch
                    c.execute("UPDATE git_commits SET branch=? WHERE conn_id=? AND branch=?", (default, cid, x["name"]))
                c.execute("DELETE FROM git_branches WHERE conn_id=? AND name=?", (cid, x["name"]))
                changed = True
        for n, t in want.items():
            changed |= bool(c.execute("""INSERT INTO git_branches(conn_id,name,task_id,sha) VALUES(?,?,?,?) ON CONFLICT(conn_id,name)
                                         DO UPDATE SET task_id=excluded.task_id, sha=excluded.sha
                                         WHERE git_branches.task_id IS DISTINCT FROM excluded.task_id OR git_branches.sha<>excluded.sha""",
                                      (cid, n, t, heads[n])).rowcount)
    main = c.execute("SELECT main_sha FROM git_conns WHERE id=?", (cid,)).fetchone()["main_sha"] or ""
    for x in c.execute("""SELECT name, sha, ahead FROM git_branches WHERE conn_id=? AND (ahead IS NULL OR sha<>cmp_sha OR cmp_main<>?)
                          ORDER BY seen_at, name LIMIT ?""", (cid, main, GB_BRANCH_CMP)).fetchall():
        try:
            lst, n = _gb_cmp(_gb_get(k, git_api(prov, k, "compare", default, x["name"])), prov)
        except CalError:
            lst, n = None, None
        if lst is not None:
            changed |= _gb_link(c, r, lst[-GIT_ITEMS:], x["name"])
        c.execute("UPDATE git_branches SET ahead=COALESCE(?, ahead), cmp_sha=?, cmp_main=?, seen_at=? WHERE conn_id=? AND name=?",
                  (n, x["sha"], main, iso(now_utc()), cid, x["name"]))
        changed |= n is not None and n != x["ahead"]  # a new compare with the same result changes nothing the client shows
    return changed


# ---- the version field of a list
def gb_fields(c, lid):
    """The list's text / select fields (id, name, type, options) in order."""
    return c.execute("SELECT id, name, type, options FROM list_fields WHERE list_id=? AND type IN ('text','select') ORDER BY sort, id",
                     (lid,)).fetchall()


def gb_ver_field(c, lid, setting=None, fields=None):
    """The field row that holds the package / target version of list lid, None = none (switched off or no such field).
    setting: lists.git_ver_field (NULL = by its name, 0 = off, else the field id)."""
    if setting is None:
        x = c.execute("SELECT git_ver_field FROM lists WHERE id=?", (lid,)).fetchone()
        setting = x["git_ver_field"] if x else 0
    if setting == 0:
        return None
    fields = gb_fields(c, lid) if fields is None else fields
    if setting is not None:
        return next((f for f in fields if f["id"] == setting), None)
    return next((f for f in fields if f["type"] == "text" and (f["name"] or "").strip().casefold() in GB_VER_NAMES), None)


def _gb_fval(f, v):
    """A field value as text (a select stores the option id)."""
    if f["type"] != "select":
        return str(v or "").strip()
    import json
    try:
        opts = json.loads(f["options"] or "{}").get("options") or []
    except (ValueError, AttributeError):
        opts = []
    return next((str(o.get("name") or "").strip() for o in opts if isinstance(o, dict) and str(o.get("id")) == str(v)), "")


def gb_ver_info(c, lid):
    """The repository dialog: {setting: "auto" | "off" | <field id>, field: {id, name} | null (the one in use), fields: [...]}."""
    x = c.execute("SELECT git_ver_field FROM lists WHERE id=?", (lid,)).fetchone()
    s = x["git_ver_field"] if x else None
    fields = gb_fields(c, lid)
    f = gb_ver_field(c, lid, s, fields)
    return {"setting": "auto" if s is None else "off" if s == 0 else s, "field": {"id": f["id"], "name": f["name"]} if f else None,
            "fields": [{"id": y["id"], "name": y["name"]} for y in fields]}


@app.put("/api/lists/<int:lid>/repos/version-field")
def gb_ver_set(lid):
    """{field: "auto" | "off" | <id of a text / select field of the list>} -- the list owner / a list admin (people)."""
    c = db()
    git_need_manage(c, lid)
    v = body().get("field")
    if v == "auto":
        s = None
    elif v == "off":
        s = 0
    elif isinstance(v, int) and not isinstance(v, bool) and any(f["id"] == v for f in gb_fields(c, lid)):
        s = v
    else:
        return err(tr("Invalid value: {0}", "field"))
    c.execute("UPDATE lists SET git_ver_field=? WHERE id=?", (s, lid))
    bump(c)
    c.commit()
    return jsonify(gb_ver_info(c, lid))


# ---- the build state of tasks
def git_build_for(c, rows):
    """{task id: build} for the tasks in rows (id, list_id, status) whose list has a repository; a few queries for all."""
    if not rows or not c.execute("SELECT 1 FROM git_conns LIMIT 1").fetchone():
        return {}
    lc = {}
    own = {x[0] for x in c.execute("SELECT DISTINCT list_id FROM git_conns WHERE id NOT IN (SELECT conn_id FROM git_folders)")}
    folders = bool(c.execute("SELECT 1 FROM git_folders LIMIT 1").fetchone())
    for lid in sorted({r["list_id"] for r in rows if r["list_id"] and (folders or r["list_id"] in own)}):
        cs = git_conns_of_list(c, lid)  # own repositories, else the folder's
        if cs:
            lc[lid] = cs
    rows = [r for r in rows if r["list_id"] in lc and r["id"] and r["id"] > 0]
    if not rows:
        return {}
    conn = {k["id"]: k for cs in lc.values() for k in cs}
    cids, idl = st_ids(sorted(conn)), st_ids(sorted({r["id"] for r in rows}))
    vers = {}  # conn id -> {key: tag name}
    for x in c.execute("SELECT conn_id, name FROM git_tags WHERE conn_id = ANY(CAST(? AS BIGINT[]))", (cids,)):
        k_ = gb_key(x["name"])
        if k_ and (k_ not in vers.setdefault(x["conn_id"], {}) or len(x["name"]) < len(vers[x["conn_id"]][k_])):
            vers[x["conn_id"]][k_] = x["name"]
    ev = {}  # task id -> [(conn id, kind, tag, on main, branch name)]
    for x in c.execute("""SELECT l.task_id, l.conn_id, m.branch, m.tag, m.at FROM git_links l JOIN git_commits m ON m.conn_id=l.conn_id
                          AND m.sha=l.ref WHERE l.kind='commit' AND l.task_id = ANY(CAST(? AS BIGINT[]))
                          AND l.conn_id = ANY(CAST(? AS BIGINT[]))""", (idl, cids)):
        ev.setdefault(x["task_id"], []).append(("c", x["conn_id"], x["tag"], x["branch"], x["at"]))
    for x in c.execute("""SELECT l.task_id, l.conn_id, p.state, p.tag, p.head_ref FROM git_links l JOIN git_prs p ON p.conn_id=l.conn_id
                          AND CAST(p.number AS TEXT)=l.ref WHERE l.kind='pr' AND l.task_id = ANY(CAST(? AS BIGINT[]))
                          AND l.conn_id = ANY(CAST(? AS BIGINT[]))""", (idl, cids)):
        ev.setdefault(x["task_id"], []).append(("p", x["conn_id"], x["tag"], x["state"], x["head_ref"]))
    refs = sorted({(e[1], e[4]) for v in ev.values() for e in v if e[0] == "p" and e[3] == "open" and e[4]})
    brs, merged = {}, {}
    for x in c.execute("SELECT * FROM git_branches WHERE conn_id = ANY(CAST(? AS BIGINT[]))", (cids,)):
        merged[(x["conn_id"], x["name"])] = x["ahead"] == 0
        if x["task_id"] is not None or (x["conn_id"], x["name"]) in refs:
            brs.setdefault(x["task_id"], []).append(x)
    byref = {(x["conn_id"], x["name"]): x for v in brs.values() for x in v}
    # the version field: one per list, the values of these tasks
    vf = {lid: gb_ver_field(c, lid) for lid in lc}
    fids = sorted({f["id"] for f in vf.values() if f})
    fv = {}
    if fids:
        for x in c.execute("""SELECT task_id, field_id, value FROM task_field_values WHERE task_id = ANY(CAST(? AS BIGINT[]))
                              AND field_id = ANY(CAST(? AS BIGINT[]))""", (idl, st_ids(fids))):
            fv[(x["task_id"], x["field_id"])] = x["value"]
    out = {}
    for t in rows:
        cs = lc[t["list_id"]]
        mine = {k["id"] for k in cs}
        known = {}
        for k in cs:
            known.update(vers.get(k["id"], {}))
        tags, main, branch, floor_rel = [], False, False, False
        for e in ev.get(t["id"], []):
            k = conn.get(e[1])
            if not k or e[1] not in mine:
                continue
            if e[2] and gb_key(e[2]):
                tags.append(e[2])
            if e[0] == "c":
                on_main = e[3] == (k["default_branch"] or "") or merged.get((e[1], e[3]), False)
                if on_main and not e[2] and k["tags_floor"] and e[4] and e[4] < k["tags_floor"]:
                    floor_rel = True  # older than every tag looked at: in some earlier version
                main |= on_main
                branch |= not on_main
            else:
                main |= e[3] == "merged"
                branch |= e[3] == "open"
        own = [x for x in brs.get(t["id"], []) if x["conn_id"] in mine]
        own += [byref[(e[1], e[4])] for e in ev.get(t["id"], []) if e[0] == "p" and e[3] == "open" and (e[1], e[4]) in byref
                and byref[(e[1], e[4])] not in own and e[1] in mine]
        ahead = [x for x in own if x["ahead"]]
        branch |= bool(ahead)
        if tags:
            top = max(tags, key=lambda n: (gb_key(n), n))
            state, version = "released", git_version(top)
        elif floor_rel:
            state, version = "released", None
        else:
            state, version = ("main" if main else "branch" if branch else "none"), None
        latest = max(known) if known else None
        pkg = None
        f = vf.get(t["list_id"])
        if f:
            val = _gb_fval(f, fv.get((t["id"], f["id"])))
            if val:
                kv = gb_key(val)
                pkg = {"field": f["name"], "value": val[:100], "released": bool(kv and kv in known),
                       "latest": git_version(known[latest]) if latest else None}
        b = {"state": state, "version": version,
             "branches": [{"repo": f"{conn[x['conn_id']]['owner']}/{conn[x['conn_id']]['repo']}", "name": x["name"], "ahead": x["ahead"],
                           "url": gb_branch_url(conn[x["conn_id"]], x["name"])} for x in sorted(ahead, key=lambda y: y["name"])],
             "package": pkg, "stale": False}
        b["stale"] = t["status"] == 0 and (bool(pkg and pkg["released"]) or state == "released")
        out[t["id"]] = b
    return out


def gb_branch_url(r, name):
    web = f"{git_urls(r['provider'], r['base_url'])[1]}/{r['owner']}/{r['repo']}"
    q = urllib.parse.quote(name, safe="/")
    return {"gitlab": f"{web}/-/tree/{q}", "bitbucket": f"{web}/branch/{q}", "gitea": f"{web}/src/branch/{q}"}.get(r["provider"]) or f"{web}/tree/{q}"


def gb_untrusted(b):
    """For agents: branch names are written by anyone with access to the repository."""
    return {**b, "branches": [{**x, "origin": "git", "untrusted": True} for x in b["branches"]]}


def gb_status(c, lid, agent=False):
    """GET .../lists/{id}/build-status: the OPEN tasks of the list whose build needs a look (stale, or work on a branch that
    is not in the default branch), each {id, title, build}; only tasks the caller sees."""
    rows = c.execute("SELECT id, list_id, status, title FROM tasks WHERE list_id=? AND status=0 AND deleted_at IS NULL ORDER BY id",
                     (lid,)).fetchall()
    viewer = g.user["id"] if getattr(g, "user", None) else None
    if viewer and rows and lid in set(plists(c, viewer)):  # a participant: only the tasks shared with them
        pv = pvis(c, viewer)[0]
        rows = [r for r in rows if r["id"] in pv]
    bs = git_build_for(c, rows)
    data = []
    for r in rows:
        b = bs.get(r["id"])
        if b and (b["stale"] or b["branches"] or b["state"] == "branch"):
            data.append({"id": r["id"], "title": r["title"], "build": gb_untrusted(b) if agent else b})
    cs = git_conns_of_list(c, lid)
    known = {}
    for k in cs:
        for x in c.execute("SELECT name FROM git_tags WHERE conn_id=?", (k["id"],)):
            if gb_key(x["name"]):
                known[gb_key(x["name"])] = x["name"]
    return {"data": data, "list_id": lid, "repos": len(cs), "latest": git_version(known[max(known)]) if known else None,
            "checked_at": iso(now_utc())}


@app.get("/api/lists/<int:lid>/build-status")
def gb_status_web(lid):
    c = db()
    need_list(c, lid, write=False)
    return jsonify(gb_status(c, lid))


@app.get("/api/v1/lists/<int:lid>/build-status")
@v1_view
def v1_gb_status(lid):
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    return jsonify(gb_status(c, lid, agent=True))


def gb_spec(paths, schemas, op, ok, errs, ref, pid, nul):
    """The OpenAPI additions (called from git_spec)."""
    br = {"type": "object", "properties": {"repo": {"type": "string"}, "name": {"type": "string"}, "ahead": {"type": "integer"},
                                           "url": {"type": "string"}, "origin": {"type": "string"}, "untrusted": {"type": "boolean"}}}
    build = {"type": "object", "description": "2.151.0 (#2558): the build state of the task from the list's repository",
             "properties": {"state": {"type": "string", "enum": ["released", "main", "branch", "none"]},
                            "version": nul("string", description="The highest version tag that holds its code (null: none, or older "
                                                                 "than every tag Kalmido looked at)"),
                            "branches": {"type": "array", "items": br, "description": "Branches of the task with commits the default branch lacks"},
                            "package": {"type": ["object", "null"], "description": "The list's package / version field: field, value, released "
                                        "(a tag with exactly this version exists), latest (the highest version)",
                                        "properties": {"field": {"type": "string"}, "value": {"type": "string"},
                                                       "released": {"type": "boolean"}, "latest": nul("string")}},
                            "stale": {"type": "boolean", "description": "Open although its package or its code is released"}}}
    schemas["Build"] = build
    schemas["Code"]["properties"]["build"] = ref("Build")
    item = {"type": "object", "properties": {"id": {"type": "integer"}, "title": {"type": "string"}, "build": ref("Build")}}
    schemas["BuildStatus"] = {"type": "object", "properties": {"data": {"type": "array", "items": item}, "list_id": {"type": "integer"},
                                                               "repos": {"type": "integer"}, "latest": nul("string"),
                                                               "checked_at": {"type": "string"}}}
    paths["/lists/{id}/build-status"] = {"get": op(
        "2.151.0 (#2558): open tasks of a list whose build needs a look: stale (package or code released, task still open) or "
        "work on a branch that is not in the default branch. Call it before reporting work as done", "Lists",
        ok(ref("BuildStatus")) | errs("404"), [pid("id", "List id")])}

