"""2.558.0 (#4693): the short list "Shared with Anna, Ben · agent X" of the file store, bundled with a listing.

ONE function (fs_share_with) reads the names of the live shares (no end date or one still ahead) of a whole listing at once:
one query on fs_shares for the rows plus the folders above (their shares apply to every row below: inherited), then one
query for the names of people / agents and one for the groups. No query per row.

Who gets the names: only who may open the Share dialog of the node (the owner, or an area that lets the person manage
the shares, files/fsroots.fs_area_share). Everybody else gets no names of foreign shares; a receiver sees "Shared by
<owner>" from the node's owner field (fs_node_json). The rights stay as they are: this only reads.

The entries: {"n": name, "k": "u" (person) | "g" (group) | "a" (agent) | "o" (the whole organisation)}, people and
groups first, then agents, each name once; "o" when the node or a folder above is open to its whole organisation.
"""
from ..core.db import now_iso as _now


def fs_share_with(c, nodes, above=()):
    """{node id: [entries]} for nodes (fs_nodes rows or dicts with id, org_access), each with the shares of the folders in
    above (rows, the folder right above first) included. The caller decides who may see them (module docstring)."""
    nodes = list(nodes)
    if not nodes:
        return {}
    above = list(above)
    ids = list({int(n["id"]) for n in nodes} | {int(a["id"]) for a in above})
    q = ",".join("?" * len(ids))
    rows = c.execute(f"SELECT node_id, user_id, group_id, agent_id FROM fs_shares WHERE node_id IN ({q}) "
                     "AND (expires_at IS NULL OR expires_at > ?) ORDER BY id", (*ids, _now())).fetchall()
    uids = {r["user_id"] or r["agent_id"] for r in rows if r["user_id"] or r["agent_id"]}
    gids = {r["group_id"] for r in rows if r["group_id"]}
    names = {}
    if uids:
        names = {r[0]: r[1] for r in c.execute(f"SELECT id, display_name FROM users WHERE id IN ({','.join('?' * len(uids))})", list(uids))}
    gnames = {}
    if gids:
        gnames = {r[0]: r[1] for r in c.execute(f"SELECT id, name FROM groups WHERE id IN ({','.join('?' * len(gids))})", list(gids))}
    per = {}
    for r in rows:
        if r["agent_id"]:
            e = ("a", names.get(r["agent_id"], ""))
        elif r["group_id"]:
            e = ("g", gnames.get(r["group_id"], ""))
        else:
            e = ("u", names.get(r["user_id"], ""))
        if e[1]:
            per.setdefault(r["node_id"], []).append(e)
    inh = [e for a in above for e in per.get(a["id"], [])]
    inh_org = any(a["org_access"] for a in above)
    out = {}
    for n in nodes:
        seen, people, agents = set(), [], []
        for k, nm in per.get(n["id"], []) + inh:
            if (k, nm) in seen:
                continue
            seen.add((k, nm))
            (agents if k == "a" else people).append({"n": nm, "k": k})
        if n["org_access"] or inh_org:
            people.insert(0, {"n": "", "k": "o"})
        out[n["id"]] = people + agents
    return out
