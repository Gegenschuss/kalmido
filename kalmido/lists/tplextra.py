"""2.363.3 (#3134): what a duplicate and a template carry beyond the plain task nodes (lists/templates.py).

Duplicating and templates take everything except comments and times. What names people, lists or stored files stays on the
server: x = {"nodes": {node key: {a, g, r, xt, lt, pf, tf, sp, ln, files}}, "list": {wip, ltags, sprints, sprint_cfg, points_on,
links}}, in a template the column templates.extra (never sent to a client; a template edit keeps it, node by node key; 2.463.0,
#3860: in the account export without the numbers of other people, lists and tasks, tx_export / tx_import). The rules on use,
whatever the template or the original said:
 - a person (assignee, reviewer, person field) only when they may be assigned in the target list (check_assignee / field_value),
   tags of other people only when they see the target list: a copy gives nobody a right they did not have
 - a place in a further list only within the rules of multilist.ml_check (same workspace, write on the target)
 - files are real copies: a template's in template_files (below ATT_DIR/tplfiles/<template id>/, sealed for the template's owner,
   they count for that person's storage), so deleting the original takes nothing away. Files of comments stay behind; a file
   found infected, one encrypted in the browser and what does not fit the person's storage are skipped and named in skipped_files."""
import json
import os
import re
import uuid

from ..core.config import ATT_DIR
from ..core.db import insert_id, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_role
from ..core.errors import BadInput
from ..core.orgcrypt import oc_copy_file, oc_user_space, oc_task_org, oc_task_space  # 2.369.5 (#2517): pulled up from functions
from .lists import LIST_COLOR_RE  # 2.369.5 (#2517): pulled up from functions
from ..tasks.tasks import check_assignee  # 2.369.5 (#2517): pulled up from functions
from ..lists.groups import check_group_assignee  # 2.369.5 (#2517): pulled up from functions

TX_MAX_FILES, TX_MAX_BYTES = 500, 1024 ** 3  # per request: the copy runs inside it
TX_MAX_ROWS = 500  # 2.463.0 (#3860): per part of an imported extra


def tx_state():
    """The files of one request: saved = written so far (the caller unlinks them on a failure), skipped = names left behind."""
    return {"saved": [], "skipped": [], "n": 0, "bytes": 0}


def tx_list(c, lid, base, dup, x):
    """The list's part of x; -> {sprint id: index} of the sprints that come along (not the closed ones, their review stays)."""
    from datetime import date
    r = c.execute("SELECT sprint_cfg, points_on FROM lists WHERE id=?", (lid,)).fetchone()
    wip = {s["name"]: s["wip_limit"] for s in c.execute("SELECT name, wip_limit FROM sections WHERE list_id=? AND wip_limit IS NOT NULL", (lid,))}
    idx, sprints = {}, []
    for s in c.execute("SELECT * FROM sprints WHERE list_id=? AND state<>'closed' ORDER BY num", (lid,)).fetchall():
        idx[s["id"]] = len(sprints)
        sprints.append({"name": s["name"], "goal": s["goal"], "state": s["state"] if dup else "planned",
                        "s": (date.fromisoformat(s["start"]) - base).days, "e": (date.fromisoformat(s["end_day"]) - base).days})
    x["list"] = {"wip": wip, "sprints": sprints, "sprint_cfg": r["sprint_cfg"] or "", "points_on": r["points_on"] or 0,
                 "ltags": [{"name": t["name"], "color": t["color"], "sort": t["sort"]}
                           for t in c.execute("SELECT name, color, sort FROM list_tags WHERE list_id=? ORDER BY sort, id", (lid,))],
                 "links": [{"title": t["title"], "url": t["url"]}
                           for t in c.execute("SELECT title, url FROM list_links WHERE list_id=? AND deleted_at IS NULL ORDER BY sort, id", (lid,))]}
    return idx


def tx_collect(c, uid, lid, order, base, x, dup=False, fidx=None, ftypes=None):
    """Fills x from the tasks of order [(task id, node key), ...]. fidx / ftypes (a whole list): + the list's part and the person /
    task fields (index in the template's fields); dup: states and dates as they are."""
    from ..files.scan import sc_marks
    smap = tx_list(c, lid, base, dup, x) if fidx is not None else {}
    keys, nodes = dict(order), x.setdefault("nodes", {})
    x.setdefault("skipped", [])
    if not keys:
        return
    q = ",".join(str(int(i)) for i in keys)

    def nd(tid):
        return nodes.setdefault(keys[tid], {})
    for r in c.execute(f"SELECT id, assignee_id, assignee_group_id, reviewer_id, delegate_agent_id, sprint_id FROM tasks WHERE id IN ({q})"):
        for k, col in (("a", "assignee_id"), ("g", "assignee_group_id"), ("r", "reviewer_id"), ("dl", "delegate_agent_id")):
            if r[col]:
                nd(r["id"])[k] = r[col]
        if r["sprint_id"] in smap:
            nd(r["id"])["sp"] = smap[r["sprint_id"]]
    for r in c.execute(f"SELECT task_id, user_id, tag FROM task_tags WHERE task_id IN ({q}) AND user_id<>? ORDER BY tag", (uid,)):
        nd(r["task_id"]).setdefault("xt", {}).setdefault(str(r["user_id"]), []).append(r["tag"])
    for r in c.execute(f"SELECT k.task_id, t.name FROM task_list_tags k JOIN list_tags t ON t.id=k.tag_id WHERE k.task_id IN ({q})"):
        nd(r["task_id"]).setdefault("lt", []).append(r["name"])
    for r in c.execute(f"SELECT task_id, list_id FROM task_links WHERE task_id IN ({q})"):
        nd(r["task_id"]).setdefault("ln", []).append(r["list_id"])
    for r in c.execute(f"SELECT task_id, field_id, value FROM task_field_values WHERE task_id IN ({q})") if fidx else ():
        i, ty = fidx.get(r["field_id"]), (ftypes or {}).get(r["field_id"])
        if i is not None and ty == "person":
            nd(r["task_id"]).setdefault("pf", {})[str(i)] = r["value"]
        elif i is not None and ty == "task" and str(r["value"]).isdigit():  # a task of the copy: its copy, else the same task
            nd(r["task_id"]).setdefault("tf", {})[str(i)] = {"k": keys[int(r["value"])]} if int(r["value"]) in keys else {"id": r["value"]}
    rows = c.execute(f"""SELECT id, task_id, name, mime, size, path, enc FROM attachments WHERE task_id IN ({q}) AND comment_id IS NULL
                         AND deleted_at IS NULL ORDER BY id""").fetchall()
    marks = sc_marks(c, "att", [r["id"] for r in rows])
    for r in rows:
        scan = (marks.get(r["id"]) or {}).get("scan")
        if r["enc"] or scan == "infected":
            x["skipped"].append(r["name"])
        else:
            nd(r["task_id"]).setdefault("files", []).append({"name": r["name"], "mime": r["mime"], "size": r["size"], "path": r["path"], "scan": scan or "clean"})


def _copy(c, uid, f, rel, sid, st):
    """Writes the copy of file f at rel for space sid; False = skipped (named in st)."""
    from ..admin.hosting import quota_fits
    size, src = int(f["size"] or 0), os.path.join(ATT_DIR, f["path"])
    if st["n"] >= TX_MAX_FILES or st["bytes"] + size > TX_MAX_BYTES or not os.path.isfile(src) or not quota_fits(c, uid, size):
        st["skipped"].append(f["name"])
        return False
    dst = os.path.join(ATT_DIR, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    st["saved"].append(rel)
    oc_copy_file(c, src, dst, sid)
    st["n"] += 1
    st["bytes"] += size
    return True


def tx_store(c, uid, tpl, x, st):
    """A new template: its own copies of the files; the rest of x goes into templates.extra."""
    st["skipped"] += x.pop("skipped", [])
    for k, n in x.get("nodes", {}).items():
        for f in n.pop("files", []):
            rel = os.path.join("tplfiles", str(tpl), f"{uuid.uuid4().hex[:12]}-{f['name']}")
            if _copy(c, uid, f, rel, oc_user_space(uid), st):
                c.execute("INSERT INTO template_files(template_id,user_id,node_key,name,mime,size,path,scan,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                          (tpl, uid, k, f["name"], f["mime"], f["size"], rel, f["scan"], iso(now_utc())))
    c.execute("UPDATE templates SET extra=? WHERE id=?", (json.dumps(x, ensure_ascii=False, separators=(",", ":")), tpl))


def tx_of_template(c, r):
    """x of a stored template row, with the files of template_files."""
    try:
        x = json.loads(r["extra"] or "{}")
    except ValueError:
        x = {}
    for n in (x.get("nodes") or {}).values():  # 2.463.0 (#3860): files only from template_files: tx_store never leaves any in the column
        n.pop("files", None)
    for f in c.execute("SELECT node_key, name, mime, size, path, scan FROM template_files WHERE template_id=? ORDER BY id", (r["id"],)):
        x.setdefault("nodes", {}).setdefault(f["node_key"], {}).setdefault("files", []).append(dict(f))
    return x


def tx_export(raw, uid):
    """2.463.0 (#3860): templates.extra of person uid for the account export: what names other people, lists or tasks of this
    server means nothing elsewhere and stays behind; uid's own assignments stay (the import makes them the importer's)."""
    try:
        x = json.loads(raw or "{}")
    except ValueError:
        return {}
    out = {"list": x["list"]} if x.get("list") else {}
    nodes = {}
    for k, n in (x.get("nodes") or {}).items():
        d = {f: n[f] for f in ("lt", "sp") if f in n}
        d.update({f: uid for f in ("a", "r") if n.get(f) == uid})
        pf = {i: v for i, v in (n.get("pf") or {}).items() if str(v) == str(uid)}
        tf = {i: {"k": v["k"]} for i, v in (n.get("tf") or {}).items() if "k" in v}
        d.update({f: v for f, v in (("pf", pf), ("tf", tf)) if v})
        if d:
            nodes[k] = d
    return {**out, "nodes": nodes} if nodes else out


def _tx_int(v, lo, hi):
    return min(hi, max(lo, v)) if isinstance(v, int) and not isinstance(v, bool) else None


def _tx_rows(v):
    return [r for r in v if isinstance(r, dict)][:TX_MAX_ROWS] if isinstance(v, list) else []


def _tx_list_in(p):
    """The list's part of an imported x, rebuilt field by field (tx_apply takes it as it stands)."""
    from .projects import ov_link_clean
    txt = lambda v, n: v.strip()[:n] if isinstance(v, str) else ""  # noqa: E731
    wip = p.get("wip") if isinstance(p.get("wip"), dict) else {}
    out = {"wip": {txt(k, 200): _tx_int(v, 1, 9999) for k, v in list(wip.items())[:TX_MAX_ROWS] if txt(k, 200) and _tx_int(v, 1, 9999)},
           "points_on": 1 if p.get("points_on") else 0, "sprints": [], "ltags": [], "links": []}
    try:
        out["sprint_cfg"] = json.dumps(c) if isinstance(c := json.loads(p.get("sprint_cfg") or "{}"), dict) and c else ""
    except (TypeError, ValueError):
        out["sprint_cfg"] = ""
    for s in _tx_rows(p.get("sprints")):
        a, e = _tx_int(s.get("s"), -3650, 3650), _tx_int(s.get("e"), -3650, 3650)
        if txt(s.get("name"), 200) and a is not None and e is not None:
            out["sprints"].append({"name": txt(s["name"], 200), "goal": txt(s.get("goal"), 2000), "state": "planned", "s": a, "e": e})
    for t in _tx_rows(p.get("ltags")):
        col = t.get("color") if isinstance(t.get("color"), str) and LIST_COLOR_RE.fullmatch(t["color"]) else ""
        if txt(t.get("name"), 100):
            out["ltags"].append({"name": txt(t["name"], 100), "color": col, "sort": _tx_int(t.get("sort"), 0, 99999) or 0})
    for t in _tx_rows(p.get("links")):
        try:
            title, url = ov_link_clean({"title": txt(t.get("title"), 300), "url": txt(t.get("url"), 2000)})
        except BadInput:
            continue
        out["links"].append({"title": title, "url": url})
    return out


def tx_import(v, who, keys):
    """2.463.0 (#3860): the extra of a template from an account export as text for templates.extra. The file is not trusted:
    only the parts tx_export writes, rebuilt with the right types, node keys of the template (keys), people through who (old id
    -> id here or None); files, other people's tags, lists and tasks of the old server never get in."""
    try:
        x = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        return "{}"
    x = x if isinstance(x, dict) else {}
    out = {"list": _tx_list_in(x["list"])} if isinstance(x.get("list"), dict) else {}
    nodes, sprints = {}, len((out.get("list") or {}).get("sprints") or [])
    for k, n in (x.get("nodes") if isinstance(x.get("nodes"), dict) else {}).items():
        if k not in keys or not isinstance(n, dict):
            continue
        d = {f: u for f in ("a", "r") if (u := who(n.get(f)))}
        if isinstance(n.get("lt"), list):
            d["lt"] = [t[:100] for t in n["lt"][:TX_MAX_ROWS] if isinstance(t, str) and t]
        if _tx_int(n.get("sp"), 0, sprints - 1) is not None and n["sp"] in range(sprints):
            d["sp"] = n["sp"]
        pf = n.get("pf") if isinstance(n.get("pf"), dict) else {}
        pf = {i: str(u) for i, v_ in list(pf.items())[:TX_MAX_ROWS] if re.fullmatch(r"\d{1,4}", str(i)) and (u := who(v_))}
        tf = n.get("tf") if isinstance(n.get("tf"), dict) else {}
        tf = {i: {"k": t["k"]} for i, t in list(tf.items())[:TX_MAX_ROWS] if re.fullmatch(r"\d{1,4}", str(i)) and isinstance(t, dict) and isinstance(t.get("k"), str) and t["k"] in keys}
        d.update({f: y for f, y in (("pf", pf), ("tf", tf)) if y})
        if d:
            nodes[k] = d
    if nodes:
        out["nodes"] = nodes
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def tx_keys(data):
    """Every node key of a template's data."""
    out, todo = set(), list(data.get("tasks") or []) + ([data["task"]] if data.get("task") else [])
    while todo:
        n = todo.pop()
        out.add(n.get("k"))
        todo.extend(n.get("children") or [])
    return out - {None}


def tx_prune(c, tpl, extra, keys):
    """After an edit: what belonged to nodes that are gone goes. -> the paths to unlink after the commit."""
    try:
        x = json.loads(extra or "{}")
    except ValueError:
        x = {}
    if x.get("nodes"):
        x["nodes"] = {k: v for k, v in x["nodes"].items() if k in keys}
        c.execute("UPDATE templates SET extra=? WHERE id=?", (json.dumps(x, ensure_ascii=False, separators=(",", ":")), tpl))
    gone = [r for r in c.execute("SELECT id, node_key, path FROM template_files WHERE template_id=?", (tpl,)).fetchall() if r["node_key"] not in keys]
    for r in gone:
        c.execute("DELETE FROM template_files WHERE id=?", (r["id"],))
    return [r["path"] for r in gone]


def tx_paths(c, tpl):
    return [r[0] for r in c.execute("SELECT path FROM template_files WHERE template_id=?", (tpl,))]


def tx_reown(c, tpl, uid, made):
    """2.609.0 (#3373, review F2 / F4): template tpl gets a new owner uid (an organisation's template made private by an admin, one
    whose maker's account goes): its file copies are sealed for uid's account as new files (made += the new paths: the caller
    removes them on a rollback), the rows follow -> the old paths, to remove after the commit."""
    old = []
    for f in c.execute("SELECT id, name, path FROM template_files WHERE template_id=? AND user_id<>? ORDER BY id", (tpl, uid)).fetchall():
        src, rel = os.path.join(ATT_DIR, f["path"]), os.path.join("tplfiles", str(tpl), f"{uuid.uuid4().hex[:12]}-{f['name']}")
        if not os.path.isfile(src):
            rel = f["path"]
        else:
            made.append(rel)
            oc_copy_file(c, src, os.path.join(ATT_DIR, rel), oc_user_space(uid))
            old.append(f["path"])
        c.execute("UPDATE template_files SET user_id=?, path=? WHERE id=?", (uid, rel, f["id"]))
    return old


def tx_user_files(c, uid):
    """The files of a person's templates (user_purge unlinks them after the rows went with the account)."""
    return [r[0] for r in c.execute("SELECT path FROM template_files WHERE user_id=?", (uid,))]


def _list_part(c, uid, lid, p, start, scale):
    """The list's part onto the new list lid; -> {sprint index: new id}."""
    from datetime import timedelta
    ts = iso(now_utc())
    for name, n in (p.get("wip") or {}).items():
        c.execute("UPDATE sections SET wip_limit=? WHERE list_id=? AND name=?", (n, lid, name))
    c.execute("UPDATE lists SET sprint_cfg=?, points_on=? WHERE id=?", (p.get("sprint_cfg") or "", p.get("points_on") or 0, lid))
    smap = {}
    for i, s in enumerate(p.get("sprints") or []):
        smap[i] = insert_id(c, "INSERT INTO sprints(list_id,num,name,start,end_day,goal,state,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
                            (lid, i + 1, s["name"], (start + timedelta(days=round(s["s"] * scale))).isoformat(),
                             (start + timedelta(days=round(s["e"] * scale))).isoformat(), s["goal"], s["state"], ts, uid))
    for t in p.get("ltags") or []:
        c.execute("INSERT INTO list_tags(list_id,name,color,sort,created_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                  (lid, t["name"], t["color"], t["sort"], ts))
    for i, t in enumerate(p.get("links") or []):
        c.execute("INSERT INTO list_links(list_id,title,url,sort,created_by,created_at) VALUES(?,?,?,?,?,?)", (lid, t["title"], t["url"], i + 1, uid, ts))
    return smap


def _ok(check, *a):
    """A check of the assignee kind: None = fine; collaboration off or no right counts as no."""
    try:
        return check(*a) is None
    except (Denied, BadInput):
        return False


def _files(c, uid, tid, fs, st):
    from ..files.upsafe import up_after_store
    for f in fs:
        rel = os.path.join(str(tid), f"{uuid.uuid4().hex[:12]}-{f['name']}")
        if _copy(c, uid, f, rel, oc_task_space(c, tid), st):
            aid = insert_id(c, "INSERT INTO attachments(task_id,name,mime,size,path,created_at,user_id) VALUES(?,?,?,?,?,?,?)",
                            (tid, f["name"], f["mime"], f["size"], rel, iso(now_utc()), uid))
            up_after_store(c, "att", aid, oc_task_org(c, tid) or None, {"kind": "att", "scan": f.get("scan") or "clean"})


def _place(c, tid, lid):
    """The copy of a task also in list lid, within the rules of a link by hand."""
    from ..tasks.multilist import ml_check
    try:
        if ml_check(c, tid, lid):
            return
    except Denied:
        return
    org = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    srt = c.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM task_links WHERE list_id=?", (lid,)).fetchone()[0]
    c.execute("INSERT INTO task_links(task_id, list_id, sort, org_id, added_by, created_at) VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
              (tid, lid, float(srt), org, me(), iso(now_utc())))


def tx_apply(c, uid, lid, x, made, st, start=None, scale=1.0, fmap=None):
    """x onto the new tasks made {node key: id} in list lid (after list_created: its people count). The caller commits."""
    from .fields import field_value
    st["skipped"] += x.get("skipped", [])
    smap = _list_part(c, uid, lid, x["list"], start, scale) if x.get("list") else {}
    ltags = {r["name"].lower(): r["id"] for r in c.execute("SELECT id, name FROM list_tags WHERE list_id=?", (lid,))}
    from ..tasks.watchers import check_delegate
    seen, who = {}, {}

    def sees(u):
        return seen.setdefault(u, bool(list_role(c, lid, int(u))))

    def may(u):
        return who.setdefault(u, _ok(check_assignee, c, lid, u))

    def field(tid, f, val):
        c.execute("INSERT INTO task_field_values(task_id,field_id,value) VALUES(?,?,?) ON CONFLICT (task_id,field_id) DO UPDATE SET value=excluded.value",
                  (tid, f["id"], val))
    for k, n in (x.get("nodes") or {}).items():
        tid = made.get(k)
        if not tid:
            continue
        if n.get("a") and may(n["a"]):
            c.execute("UPDATE tasks SET assignee_id=? WHERE id=?", (n["a"], tid))
        if n.get("g") and _ok(check_group_assignee, c, lid, n["g"]):
            c.execute("UPDATE tasks SET assignee_group_id=? WHERE id=?", (n["g"], tid))
        if n.get("r") and may(n["r"]):
            c.execute("UPDATE tasks SET reviewer_id=? WHERE id=?", (n["r"], tid))
        if n.get("dl") and _ok(check_delegate, c, lid, n["dl"]):  # 2.473.0 (#3357): the agent, when it fits this list (watchers stay with the original)
            c.execute("UPDATE tasks SET delegate_agent_id=? WHERE id=?", (n["dl"], tid))
        if n.get("sp") in smap:
            c.execute("UPDATE tasks SET sprint_id=?, sprint_at=? WHERE id=?", (smap[n["sp"]], iso(now_utc()), tid))
        for u, tags in (n.get("xt") or {}).items():
            if sees(u):
                for t in tags:
                    c.execute("INSERT INTO task_tags(task_id,user_id,tag) VALUES(?,?,?) ON CONFLICT DO NOTHING", (tid, int(u), t))
        for name in n.get("lt") or []:
            if name.lower() in ltags:
                c.execute("INSERT INTO task_list_tags(task_id,tag_id) VALUES(?,?) ON CONFLICT DO NOTHING", (tid, ltags[name.lower()]))
        for i, v in (n.get("pf") or {}).items() if fmap else ():
            f = fmap[int(i)] if int(i) < len(fmap) else None
            try:
                val = field_value(c, f, v, lid) if f else None
            except BadInput:
                val = None  # 2.363.3 (#3134): somebody who may not see the target list
            if val is not None:
                field(tid, f, val)
        for i, v in (n.get("tf") or {}).items() if fmap else ():
            f = fmap[int(i)] if int(i) < len(fmap) else None
            try:
                val = str(made[v["k"]]) if "k" in v and v["k"] in made else field_value(c, f, v["id"], lid) if f and "id" in v else None
            except BadInput:
                val = None
            if f and val is not None:
                field(tid, f, val)
        for other in n.get("ln") or []:
            _place(c, tid, other)
        _files(c, uid, tid, n.get("files") or [], st)


def tx_same_list(c, uid, role, lid, order, made):
    """A task duplicated next to itself: what is bound to the list stays as it is (milestone, sprint, every field, what it waits on)."""
    keys = dict(order)
    for old, k in order:
        new = made.get(k)
        if not new:
            continue
        r = c.execute("SELECT milestone_id, sprint_id, sprint_at FROM tasks WHERE id=?", (old,)).fetchone()
        c.execute("UPDATE tasks SET milestone_id=?, sprint_id=?, sprint_at=? WHERE id=?", (r["milestone_id"], r["sprint_id"], r["sprint_at"], new))
        c.execute("""INSERT INTO task_field_values(task_id,field_id,value) SELECT ?, field_id, value FROM task_field_values WHERE task_id=?
                     ON CONFLICT DO NOTHING""", (new, old))
        for b in c.execute("SELECT blocker_id FROM task_deps WHERE task_id=?", (old,)).fetchall():
            c.execute("INSERT INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                      (new, made.get(keys.get(b[0])) or b[0], uid, iso(now_utc())))
        if role == "participant":  # the copy stays theirs, or it would vanish from their view
            c.execute("UPDATE tasks SET assignee_id=?, assignee_group_id=NULL WHERE id=?", (uid, new))
