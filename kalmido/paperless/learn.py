"""2.69.0 B (#1847): what a Paperless-ngx import teaches Kalmido -- for the import over the address and the ZIP import alike.

- Rules: the matching of Paperless-ngx' tags, correspondents and document types (matching_algorithm + match + is_insensitive)
  becomes document rules of the workspace (docs/rules.py): 1 any, 2 all, 3 literal -> exact, 4 regex, 5 fuzzy; the target is
  the name the mapping gives (renamed, a tag as a folder; left out = no rule). 6 "auto" has no counterpart (Paperless learns
  those itself): Kalmido's learning takes them over and they are reported, never dropped silently; 0 "none" is no rule.
  pl_rules remembers where a rule came from, so a later import never brings it twice -- nor back after it was changed or
  deleted in Kalmido. A rule that is already there with the same content is not made again.
- Learning: the documents of the run go into the workspace's models once at the end, as confirmed examples, with the values
  that came from Paperless-ngx (never what the recognition added). The models are loaded and stored once per feature.
- Workflows (2.581.0, #4803): each trigger of a Paperless-ngx workflow becomes a document flow (docs/flows.py) where the fields
  match: consumption / document added -> received, document updated -> changed, scheduled (created / added date + offset) ->
  scheduled; sources, file name, has tags / correspondent / type, the matching; actions assignment (tags, correspondent, type,
  custom fields) and removal (tags). 2.635.0 (#4856): owner / permissions become the flow's action "share" of the shared core
  (docs/flows.py): the owner and "change" users / groups get "edit", "view" ones "view", matched by user name / group name to
  the people and groups the importing person may share the workspace's documents with (fl_share_pool); one not found there,
  "remove owners / permissions" and the rest are reported. Not taken over and reported besides:
  title, storage path, e-mail, "remove all", webhooks (an import never brings a webhook: its target is checked when a person saves it).
pll_finish never raises: an error here must not spoil the import's state (it is logged)."""
import json
from collections import Counter

from ..core.db import insert_id, iso, now_utc
from ..docs import classify as CL
from ..docs import rules as RU
from ..docs import store as S
from ..docs.flows import fl_share_pool  # 2.635.0 (#4856)

PLL_ALGO = {1: "any", 2: "all", 3: "exact", 4: "regex", 5: "fuzzy"}
PLL_AUTO = 6
PLL_RULES_MAX = 500      # document rules per workspace an import fills up to
PLL_LIST_MAX = 50        # names of rules not taken over that the summary lists
PLL_TRAIN_MAX = 5000     # newest documents of one run the models learn from
PLL_KINDS = (("tags", "tags"), ("correspondents", "senders"), ("document_types", "types"))
# 2.581.0 (#4803): Paperless-ngx' workflow numbers (documents/models.py WorkflowTrigger / WorkflowAction)
PLL_WF_TRIG = {1: "received", 2: "received", 3: "changed", 4: "scheduled"}
PLL_WF_SRC = {1: "scan", 2: "upload", 3: "mail", 4: "upload"}   # consume folder, API upload, mail fetch, web UI
PLL_WF_DATE = {"created": "date", "added": "added"}
PLL_WF_MAX = 200         # workflows of one import


def _wf_ids(v):
    return [x for x in (v if isinstance(v, list) else []) if isinstance(x, int) and not isinstance(x, bool)][:50]


def _wf_one(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else (v.get("id") if isinstance(v, dict) and isinstance(v.get("id"), int) else None)


def pll_wf_trigger(t):
    """A trigger of the API answer or the export -> the plain shape learn.py reads."""
    t = t if isinstance(t, dict) else {}
    algo = t.get("matching_algorithm")
    src = t.get("sources")
    if isinstance(src, str):  # stored as "1,2,3" (a multi-select field) in older versions / exports
        src = [int(x) for x in src.split(",") if x.strip().isdigit()]
    return {"type": t.get("type"), "sources": _wf_ids(src), "filename": str(t.get("filter_filename") or "")[:200],
            "path": bool(t.get("filter_path")), "mailrule": t.get("filter_mailrule") is not None,
            "tags": _wf_ids([_wf_one(x) for x in t.get("filter_has_tags") or []]),
            "sender": _wf_one(t.get("filter_has_correspondent")), "type_id": _wf_one(t.get("filter_has_document_type")),
            "match": str(t.get("match") or "")[:1000], "algo": algo if isinstance(algo, int) and not isinstance(algo, bool) else 0,
            "insens": t.get("is_insensitive") is not False, "days": t.get("schedule_offset_days"),
            "date": str(t.get("schedule_date_field") or "added"), "recurring": bool(t.get("schedule_is_recurring"))}


def pll_wf_action(a):
    a = a if isinstance(a, dict) else {}
    vals = a.get("assign_custom_fields_values") if isinstance(a.get("assign_custom_fields_values"), dict) else {}
    return {"type": a.get("type"), "tags": _wf_ids([_wf_one(x) for x in a.get("assign_tags") or []]),
            "sender": _wf_one(a.get("assign_correspondent")), "type_id": _wf_one(a.get("assign_document_type")),
            "fields": {str(k): vals.get(str(k), vals.get(k)) for k in _wf_ids([_wf_one(x) for x in a.get("assign_custom_fields") or []])},
            "untag": _wf_ids([_wf_one(x) for x in a.get("remove_tags") or []]),
            "share": _wf_share(a),  # 2.635.0 (#4856): owner / permissions -> the action share
            "rest": [k for k in ("assign_title", "assign_storage_path", "remove_all_tags", "remove_all_correspondents",
                                 "remove_all_document_types", "remove_all_custom_fields", "remove_all_owners", "remove_all_permissions",
                                 "remove_owners", "remove_correspondents", "remove_document_types", "remove_custom_fields")
                     if a.get(k) not in (None, "", [], False)]}


def _wf_share(a):
    """2.635.0 (#4856): [[user | group, Paperless id, edit | view]] of an action's owner and permissions (the higher role wins)."""
    out = {}
    for key, kind, role in (("assign_view_users", "user", "view"), ("assign_view_groups", "group", "view"),
                            ("assign_change_users", "user", "edit"), ("assign_change_groups", "group", "edit")):
        for i in _wf_ids([_wf_one(x) for x in a.get(key) or []]):
            out[(kind, i)] = "edit" if role == "edit" else out.get((kind, i), "view")
    own = _wf_one(a.get("assign_owner"))
    if isinstance(own, int):
        out[("user", own)] = "edit"
    return [[k, i, r] for (k, i), r in sorted(out.items())]


def pll_wf_who(c, ws, uid, people):
    """2.635.0 (#4856): a resolver (kind user | group, Paperless id) -> {user_id | group_id: Kalmido id} or None: by user name /
    group name (case-insensitive, an ambiguous group name matches nothing) among the people and groups uid may share the
    documents of ws with (docs/flows.py fl_share_pool). people = {"users": {pk: user name}, "groups": {pk: name}} of the import."""
    pool = fl_share_pool(c, ws, uid)
    ids = sorted(pool["user_id"])
    names = {}
    if ids:
        names = {str(r[1]).strip().lower(): r[0] for r in c.execute(
            f"SELECT id, username FROM users WHERE id IN ({','.join('?' * len(ids))})", ids) if r[1]}
    grp = Counter(str(n).strip().lower() for n in pool["group_id"].values())
    gnames = {str(n).strip().lower(): i for i, n in pool["group_id"].items() if grp[str(n).strip().lower()] == 1}
    people = people if isinstance(people, dict) else {}

    def who(kind, pl_id):
        src = people.get("users" if kind == "user" else "groups") or {}
        nm = str(src.get(str(pl_id)) or src.get(pl_id) or "").strip().lower()
        kid = (names if kind == "user" else gnames).get(nm) if nm else None
        return {"user_id" if kind == "user" else "group_id": kid} if kid else None
    return who


def pll_wf_api(x):
    """A workflow of GET /api/workflows/ (triggers / actions nested) -> {id, name, enabled, triggers, actions}."""
    return {"id": x.get("id"), "name": str(x.get("name") or "")[:120], "enabled": x.get("enabled") is not False,
            "triggers": [pll_wf_trigger(t) for t in (x.get("triggers") or [])[:20]], "actions": [pll_wf_action(a) for a in (x.get("actions") or [])[:20]]}


def pll_wf_export(wfs, trigs, acts, fields=None):
    """The workflows of an export manifest: wfs = [(pk, fields)] of documents.workflow, trigs / acts = {pk: fields}."""
    out = []
    for pk, f in wfs[:PLL_WF_MAX]:
        out.append({"id": pk, "name": str(f.get("name") or "")[:120], "enabled": f.get("enabled") is not False,
                    "triggers": [pll_wf_trigger(trigs[t]) for t in _wf_ids(f.get("triggers")) if t in trigs],
                    "actions": [pll_wf_action(acts[a]) for a in _wf_ids(f.get("actions")) if a in acts]})
    return out


def _wf_plan(labels, mapping, fields=None, who=None):
    """[(kind 'workflow', {id, name}, rule | None, why)] -- one flow per trigger of a workflow (pl_id = workflow id * 100 + n).
    who = pll_wf_who's resolver (None: owner / permissions are reported, #4856)."""
    names = {k: {x["id"]: x for x in (labels or {}).get(k) or [] if isinstance(x, dict)} for k, _m in PLL_KINDS}
    fnames = fields or {}

    def nm(kind, mkey, lid):
        lab = names[kind].get(lid)
        tgt = _target(kind, mkey, lab, mapping) if lab else None
        return tgt[1] if tgt and (kind != "tags" or tgt[0] == "tags") else None

    out = []
    for wf in ((labels or {}).get("workflows") or [])[:PLL_WF_MAX]:
        if not isinstance(wf, dict) or not isinstance(wf.get("id"), int):
            continue
        acts, why = {"tags": [], "untag": [], "fields": {}, "share": []}, ""
        for a in wf.get("actions") or []:
            for kind, pid, role in a.get("share") or []:  # 2.635.0 (#4856)
                t = who(kind, pid) if who else None
                if t:
                    acts["share"].append({**t, "role": role})
                else:
                    why = why or "owner"
            if a.get("type") == 1:
                acts["tags"] += [n for n in (nm("tags", "tags", t) for t in a.get("tags") or []) if n]
                for f, kind, mkey in (("sender", "correspondents", "senders"), ("type", "document_types", "types")):
                    if a.get("sender" if f == "sender" else "type_id") and f not in acts:
                        v = nm(kind, mkey, a["sender" if f == "sender" else "type_id"])
                        if v:
                            acts[f] = v
                for fid, v in (a.get("fields") or {}).items():
                    fn = (fnames.get(int(fid)) or fnames.get(str(fid)) or {}).get("name") if str(fid).isdigit() else None
                    if fn:
                        acts["fields"][fn] = None if v is None else str(v)
            elif a.get("type") == 2:
                acts["untag"] += [n for n in (nm("tags", "tags", t) for t in a.get("untag") or []) if n]
            else:
                why = why or ("webhook" if a.get("type") == 4 else "email" if a.get("type") == 3 else "action")
            if a.get("rest"):
                why = why or ("owner" if any("owner" in k or "users" in k or "groups" in k or "permissions" in k for k in a["rest"]) else "action")
        for i, t in enumerate((wf.get("triggers") or [])[:20]):
            lab = {"id": wf["id"] * 100 + i, "name": wf.get("name") or f"#{wf['id']}"}
            trig = PLL_WF_TRIG.get(t.get("type"))
            raw = {"name": lab["name"], "trigger": trig, "off": not wf.get("enabled", True),
                   "sources": sorted({PLL_WF_SRC[x] for x in t.get("sources") or [] if x in PLL_WF_SRC}),
                   "filename": t.get("filename") or "", "has_tags": [n for n in (nm("tags", "tags", x) for x in t.get("tags") or []) if n],
                   "has_sender": nm("correspondents", "senders", t["sender"]) if t.get("sender") else "",
                   "has_type": nm("document_types", "types", t["type_id"]) if t.get("type_id") else "",
                   **{k: v for k, v in acts.items() if v}}
            if len(raw["sources"]) == len(set(PLL_WF_SRC.values())):
                raw["sources"] = []
            tw = why
            if not trig:
                out.append(("workflow", lab, None, "trigger"))
                continue
            if trig == "scheduled":
                if t.get("date") not in PLL_WF_DATE or t.get("recurring") or not isinstance(t.get("days"), int):
                    out.append(("workflow", lab, None, "trigger"))
                    continue
                raw["days"], raw["from"] = max(0, min(RU.DAYS_MAX, t["days"])), PLL_WF_DATE[t["date"]]
            if t.get("algo") in PLL_ALGO and str(t.get("match") or "").strip():
                raw.update({"kind": PLL_ALGO[t["algo"]], "match": str(t["match"]).strip()[:RU.PATTERN_MAX], "case": t.get("insens") is False})
            elif t.get("algo") == PLL_AUTO:
                tw = tw or "auto"
            if t.get("path") or t.get("mailrule"):
                tw = tw or "filter"
            try:
                out.append(("workflow", lab, RU.clean_rule(raw, share=True), tw))
            except RU.RuleError:
                out.append(("workflow", lab, None, tw or "pattern"))
    return out


def _target(kind, mkey, lab, mapping):
    """(feature, name) of a label after the mapping, or None when it is left out."""
    m = (mapping.get(mkey) or {}).get(str(lab.get("id")))
    if kind == "tags":
        to = m.get("to") if isinstance(m, dict) else "tag"
        name = str((m.get("name") if isinstance(m, dict) else "") or lab.get("name") or "").strip()
        if to == "skip" or not name:
            return None
        return ("folder" if to == "folder" else "tags", name)
    if m == "":
        return None
    name = str(m if isinstance(m, str) and m else lab.get("name") or "").strip()
    return ("sender" if kind == "correspondents" else "type", name) if name else None


def _plan(labels, mapping, who=None):
    """[(kind, label, rule | None, why)] -- why '' = a rule, 'auto' = Paperless learns it, 'long' / 'pattern' = not taken over."""
    out = []
    for kind, mkey in PLL_KINDS:
        for lab in (labels or {}).get(kind) or []:
            algo = lab.get("algo") if isinstance(lab, dict) else None
            if not isinstance(algo, int) or isinstance(algo, bool) or algo == 0 or not isinstance(lab.get("id"), int):
                continue
            tgt = _target(kind, mkey, lab, mapping)
            if not tgt:
                continue
            if algo == PLL_AUTO:
                out.append((kind, lab, None, "auto"))
                continue
            if algo not in PLL_ALGO:
                out.append((kind, lab, None, "unknown"))
                continue
            match = str(lab.get("match") or "").strip()
            if not match:
                continue  # Paperless-ngx matches nothing with an empty pattern either
            if len(match) > RU.PATTERN_MAX:
                out.append((kind, lab, None, "long"))
                continue
            raw = {"kind": PLL_ALGO[algo], "match": match, "case": lab.get("insens") is False,
                   tgt[0]: [tgt[1]] if tgt[0] == "tags" else tgt[1]}
            try:
                out.append((kind, lab, RU.clean_rule(raw), ""))
            except RU.RuleError:
                out.append((kind, lab, None, "pattern"))
    return out + _wf_plan(labels, mapping, (labels or {}).get("_fields"), who)  # 2.581.0 (#4803); who: #4856


def _key(rule):
    return json.dumps({k: v for k, v in rule.items() if k != "id"}, sort_keys=True, ensure_ascii=False)


def _summary(plan, done=None):
    """Counts + the names of what was not taken over ('auto' counted apart: Kalmido's learning covers those)."""
    bad = [{"kind": k, "name": str(lab.get("name") or "")[:S.NAME_MAX], "why": why} for k, lab, _r, why in plan if why not in ("", "auto")]
    return {"auto": sum(1 for p in plan if p[3] == "auto"), "unsupported": bad[:PLL_LIST_MAX], "unsupported_n": len(bad),
            **(done or {})}


def pll_rules_preview(labels, mapping, c=None, ws=None, src=None):
    """For the preview: {convert, dup, auto, unsupported: [{kind, name, why}], unsupported_n, on}. With c / ws / src the rules
    already taken over (or there with the same content) count as dup."""
    mapping = mapping if isinstance(mapping, dict) else {}
    plan = _plan(labels, mapping)
    rules = [p for p in plan if p[2]]
    dup = 0
    if c is not None and ws:
        have = {_key(r) for r in S.rules_get(c, ws)}
        for kind, lab, rule, _why in rules:
            if (src and c.execute("SELECT 1 FROM pl_rules WHERE ws=? AND src=? AND kind=? AND pl_id=?",
                                  (ws, src, kind, lab["id"])).fetchone()) or _key(rule) in have:
                dup += 1
    return _summary(plan, {"convert": len(rules) - dup, "dup": dup, "on": mapping.get("rules", True) is not False})


def _take_rules(c, ws, org_id, uid, src, plan):
    """Store the planned rules (in Paperless' order, after the workspace's own). Returns (new, dup, over the limit)."""
    have = {_key(r) for r in S.rules_get(c, ws)}
    count = c.execute("SELECT COUNT(*) FROM doc_rules WHERE ws=?", (ws,)).fetchone()[0]
    pos = int(c.execute("SELECT COALESCE(MAX(pos), 0) FROM doc_rules WHERE ws=?", (ws,)).fetchone()[0] or 0)
    new = dup = 0
    over = []
    for kind, lab, rule, _why in plan:
        if not rule:
            continue
        if c.execute("SELECT 1 FROM pl_rules WHERE ws=? AND src=? AND kind=? AND pl_id=?", (ws, src, kind, lab["id"])).fetchone():
            dup += 1
            continue
        if rule.get("share"):  # 2.635.0 (#4856): the importing person is the share's author (docs/flows.py _share checks them)
            rule = {**rule, "share_by": uid}
        k = _key(rule)
        if k in have:
            dup += 1
            c.execute("INSERT INTO pl_rules(ws, src, kind, pl_id, org_id, rule_id, created_at) VALUES(?,?,?,?,?,NULL,?) ON CONFLICT DO NOTHING",
                      (ws, src, kind, lab["id"], org_id, iso(now_utc())))
            continue
        if count >= PLL_RULES_MAX:
            over.append({"kind": kind, "name": str(lab.get("name") or "")[:S.NAME_MAX], "why": "limit"})
            continue
        pos += 1
        rid = insert_id(c, "INSERT INTO doc_rules(org_id, ws, pos, data, created_by, created_at) VALUES(?,?,?,?,?,?)",
                        (org_id, ws, pos, S._jseal(c, ws, "doc_rules.data", rule), uid, iso(now_utc())))
        c.execute("INSERT INTO pl_rules(ws, src, kind, pl_id, org_id, rule_id, created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                  (ws, src, kind, lab["id"], org_id, rid, iso(now_utc())))
        have.add(k)
        count += 1
        new += 1
    return new, dup, over


def _imported_values(c, ws, m, node, ids):
    """(tokens, {feature: value}) of a document as it came from Paperless-ngx: before the recognition ran from the import's
    given values (suggest._given), after it from the values it set as "import". The folder only when the import put it there."""
    given = S.meta_json(c, m, "suggest", {}).get("_given") or {}
    auto = S.meta_json(c, m, "auto", {})
    text = str(given.get("text") or "") if given else S.meta_text(c, m)
    toks = CL.tokens(f"{node['name']}\n{text}")
    vals = {}

    def lid(kind, name):
        k = (kind, str(name).strip().lower())
        if k not in ids:
            ids[k] = S.label_id(c, ws, kind, name)
        return ids[k]

    if given:
        for f in ("sender", "type"):
            if given.get(f):
                v = lid(f, given[f])
                if v:
                    vals[f] = str(v)
        tags = given.get("tags") or []
        tags = [t.strip() for t in tags.split(",")] if isinstance(tags, str) else tags
        tv = [str(x) for x in (lid("tag", t) for t in tags if str(t).strip()) if x]
        if tv:
            vals["tags"] = tv
    else:
        cur = S.current(c, m, node)
        for f in ("sender", "type"):
            if auto.get(f) == "import" and cur[f]:
                vals[f] = str(cur[f])
        if auto.get("tags") == "import" and cur["tags"]:
            vals["tags"] = [str(t) for t in cur["tags"]]
    if "folder" not in auto:
        fl = S.folder_label(c, node)
        if fl:
            vals["folder"] = str(fl)
    return toks, vals


def _add(model, label, counts, n):
    """learn() for n documents at once: their token counts added to one class (the same sums, computed once)."""
    if n <= 0:
        return
    cl = CL._cls(model, str(label or ""))
    cl["n"] += n
    model["docs"] = model.get("docs", 0) + n
    t = cl["t"]
    for w, k in counts.items():
        t[w] = t.get(w, 0) + k
    if len(t) > CL.MAX_VOCAB:
        for w, _n in sorted(t.items(), key=lambda kv: kv[1])[:len(t) - CL.MAX_VOCAB]:
            del t[w]
    cl["w"] = sum(t.values())


def pll_train(c, ws, nids):
    """The models of ws learn the imported values of these documents (each once: one already trained is left alone).
    Returns the number of documents that taught something."""
    lv = S.cfg_get(c, ws)["levels"]
    ids, docs = {}, []
    for nid in nids:
        m = S.meta_row(c, nid)
        node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        if not m or not node or m["ws"] != ws or node["deleted_at"] or S.meta_json(c, m, "trained", {}):
            continue
        toks, vals = _imported_values(c, ws, m, node, ids)
        vals = {f: v for f, v in vals.items() if lv.get(f) != "off"}
        if toks and vals:
            docs.append((nid, set(toks), vals))
    if not docs:
        return 0
    for f in ("sender", "type", "folder"):
        by = {}
        for _nid, toks, vals in docs:
            if f in vals:
                by.setdefault(vals[f], Counter()).update(toks)
        if by:
            model = S.model_get(c, ws, f)
            for label, cnt in by.items():
                _add(model, label, cnt, sum(1 for d in docs if d[2].get(f) == label))
            S.model_put(c, ws, f, model)
    tagged = [d for d in docs if "tags" in d[2]]
    if tagged:
        models = S.model_get(c, ws, "tags")
        every = Counter()
        for _nid, toks, _v in tagged:
            every.update(toks)
        has = {}
        for _nid, toks, vals in tagged:
            for t in vals["tags"]:
                h = has.setdefault(t, [Counter(), 0])
                h[0].update(toks)
                h[1] += 1
        for t in {str(x["id"]) for x in S.labels(c, ws, "tag")} | set(has):
            yes, n = has.get(t, (Counter(), 0))
            m = CL.tag_model(models, t)
            _add(m, "1", yes, n)
            _add(m, "0", every - yes, len(tagged) - n)
        S.model_put(c, ws, "tags", models)
    for nid, _toks, vals in docs:
        S.meta_set_json(c, nid, ws, "trained", vals)
    return len(docs)


def pll_stored(res):
    """2.69.0 review (N4): the summary as it is stored (plain, next to the run's counts): numbers only -- the names of the
    labels not taken over are shown in the preview, never kept."""
    if not res:
        return ""
    return json.dumps({k: v for k, v in res.items() if k != "unsupported" and isinstance(v, (int, bool))}, separators=(",", ":"))


def _who_safe(c, ws, uid, labels):
    """2.635.0 (#4856): pll_wf_who for the workflows of the import, None without workflows or on an error (owner / permissions
    are then reported as before, the rest of the learning goes on)."""
    if not (labels or {}).get("workflows"):
        return None
    try:
        with c.savepoint():
            return pll_wf_who(c, ws, uid, (labels or {}).get("_people"))
    except Exception as e:  # noqa: BLE001 -- the share mapping never spoils the import's learning
        print("paperless: learn who", type(e).__name__, e, flush=True)
        return None


def pll_finish(c, ws, org_id, uid, src, since, labels, mapping):
    """Once at the end of an import run (also after a stop / a full storage): the rules (unless the mapping says no) and the
    learning from the documents this run brought. {rules_new, rules_dup, auto, unsupported, unsupported_n, trained}; {} on an
    error (logged, the import's state stays as it is)."""
    mapping = mapping if isinstance(mapping, dict) else {}
    try:
        with c.savepoint():
            who = _who_safe(c, ws, uid, labels)  # 2.635.0 (#4856)
            plan = _plan(labels, mapping, who)
            new = dup = 0
            over = []
            if mapping.get("rules", True) is not False:
                new, dup, over = _take_rules(c, ws, org_id, uid, src, plan)
            nids = [r[0] for r in c.execute("""SELECT node_id FROM pl_imported WHERE ws=? AND src=? AND dup=0 AND node_id IS NOT NULL
                                               AND created_at >= ? ORDER BY created_at DESC LIMIT ?""", (ws, src, since, PLL_TRAIN_MAX))]
            trained = pll_train(c, ws, nids)
            out = _summary(plan, {"rules_new": new, "rules_dup": dup, "trained": trained})
            if over:
                out["unsupported"] = (out["unsupported"] + over)[:PLL_LIST_MAX]
                out["unsupported_n"] += len(over)
            if mapping.get("rules", True) is False:
                out["rules_off"] = True
            return out
    except Exception as e:  # noqa: BLE001 -- learning never spoils the import
        print("paperless: learn", type(e).__name__, e, flush=True)
        return {}
