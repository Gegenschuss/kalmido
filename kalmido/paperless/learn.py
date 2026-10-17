"""2.69.0 B (#1847): what a Paperless-ngx import teaches Kalmido -- for the import over the address and the ZIP import alike.

- Rules: the matching of Paperless-ngx' tags, correspondents and document types (matching_algorithm + match + is_insensitive)
  becomes document rules of the workspace (docs/rules.py): 1 any, 2 all, 3 literal -> exact, 4 regex, 5 fuzzy; the target is
  the name the mapping gives (renamed, a tag as a folder; left out = no rule). 6 "auto" has no counterpart (Paperless learns
  those itself): Kalmido's learning takes them over and they are reported, never dropped silently; 0 "none" is no rule.
  pl_rules remembers where a rule came from, so a later import never brings it twice -- nor back after it was changed or
  deleted in Kalmido. A rule that is already there with the same content is not made again.
- Learning: the documents of the run go into the workspace's models once at the end, as confirmed examples, with the values
  that came from Paperless-ngx (never what the recognition added). The models are loaded and stored once per feature.
pll_finish never raises: an error here must not spoil the import's state (it is logged)."""
import json
from collections import Counter

from ..core.db import insert_id, iso, now_utc
from ..docs import classify as CL
from ..docs import rules as RU
from ..docs import store as S

PLL_ALGO = {1: "any", 2: "all", 3: "exact", 4: "regex", 5: "fuzzy"}
PLL_AUTO = 6
PLL_RULES_MAX = 500      # document rules per workspace an import fills up to
PLL_LIST_MAX = 50        # names of rules not taken over that the summary lists
PLL_TRAIN_MAX = 5000     # newest documents of one run the models learn from
PLL_KINDS = (("tags", "tags"), ("correspondents", "senders"), ("document_types", "types"))


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


def _plan(labels, mapping):
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
    return out


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


def pll_finish(c, ws, org_id, uid, src, since, labels, mapping):
    """Once at the end of an import run (also after a stop / a full storage): the rules (unless the mapping says no) and the
    learning from the documents this run brought. {rules_new, rules_dup, auto, unsupported, unsupported_n, trained}; {} on an
    error (logged, the import's state stays as it is)."""
    mapping = mapping if isinstance(mapping, dict) else {}
    try:
        with c.savepoint():
            plan = _plan(labels, mapping)
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
