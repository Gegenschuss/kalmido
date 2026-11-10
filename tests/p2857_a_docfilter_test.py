#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.857.0 API tests, part A (#5518): the documents' saved views on the shared core's filter (docs/dfilter.py, core/filters.py
kflt_where; docs/dviews.py). Own container (start.sh). Invented names and generated texts only.
 - a view keeps rules {op, conds}: sender, type, tag, folder (with its subfolders / only itself), document date (from / to, a
   year), file type, "is empty", text with the search syntax; AND / OR; "is none of" always on top, also with OR
 - rueckfall: "is none of" keeps the documents without a value (no sender is none of the senders: SQL NULL)
 - an older view (only its query string) opens converted and hits the SAME documents as the documents search with that
   query (the list's own filters, ?view=, the views' count, the dialog's count) -- for every kind of filter the search knew
 - hits and counts ALWAYS with the rights of whoever looks: a member counts only his documents (count route, ?view=, a view an
   admin shared with everyone); another's private view: 404 also through ?view=
 - bad rules: conditions that do not fit are left out, no filter at all is 400; the count needs a signed-in person
 - 2.897.0 (#5547): an agent's GET /api/v1/documents?view= takes the view's workspace and state as well (rueckfall); an older
   view with field ids "9, " / from/to longer than 10 characters converts as the search reads it (rueckfall); the window of
   opened texts of a phrase (KALMIDO_DSR_TEXT_MAX, 3 here) comes after the view's other conditions and the list's filters (rueckfall)
freelancer-matrix: obj (a person without an organisation: her view with rules, its count and hits)
usage: p2857_a_docfilter_test.py <datadir>"""
import os
import sys
from urllib.parse import urlencode

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, H, check, docker_logs_on_first_fail, done, fresh, sess, until  # noqa: E402

fresh(env={"KALMIDO_DSR_TEXT_MAX": "3"}, prefix="P2857A")  # 2.897.0 (#5547): a small window of opened texts (the phrase test below)
docker_logs_on_first_fail()
K = "docview"
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
WS = f"org:{ORG}"
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
check(r.ok, "setup: bob a member " + r.text[:200])
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FID, Fr = freelancer(B, A)


def folder(s, name, space=None, parent=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"space": space} if space else {}), **({"parent_id": parent} if parent else {})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def doc_new(s, name, text, ws, parent=None, **fields):
    """A text document of workspace ws, recognised (its words in the index), its fields set, moved into parent."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text.encode(), "text/plain"))])
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    if fields:
        r = s.patch(B + f"/api/docs/{nid}", json=fields)
        assert r.ok, r.text
    if parent:
        r = s.patch(B + f"/api/files/nodes/{nid}", json={"parent_id": parent})
        assert r.ok, r.text
    return nid


def ids_of(r):
    return sorted(d["id"] for d in r.json()["docs"]) if r.ok else r.status_code


def flat(s, q, ws=WS):
    """The documents search with the query string q (the list's own filters)."""
    return ids_of(s.get(B + "/api/docs?" + urlencode({"ws": ws, "facets": "0", "limit": "200"}) + ("&" + q if q else "")))


def in_view(s, vid, ws=WS):
    return ids_of(s.get(B + "/api/docs", params={"ws": ws, "facets": "0", "limit": "200", "view": vid}))


def count(s, ws=WS, **b):
    r = s.post(B + "/api/docs/views/count", json={"ws": ws, **b})
    return r.json() if r.ok else r.status_code


def total(s, rules, ws=WS):
    j = count(s, ws, rules=rules)
    return j["total"] if isinstance(j, dict) else j


def hit_ids(s, rules, ws=WS):
    """The documents rules hit, through a view of s (made, read, deleted)."""
    r = s.post(B + f"/api/obj/{K}", json={"title": "probe", "rules": rules, "ws": ws})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    out = in_view(s, vid, ws)
    s.post(B + f"/api/obj/{K}/{vid}/trash")
    return out


def rules(*conds, op="and"):
    return {"op": op, "conds": list(conds)}


# ---------------------------------------------------------------- the documents
OPEN, SHUT = folder(A, "Open papers", WS), folder(A, "Board only", WS)
SUB = folder(A, "Open letters", parent=OPEN)
check(A.patch(B + f"/api/files/nodes/{OPEN}", json={"org_access": "view"}).ok, "setup: a folder every member reads (with its subfolder)")
D1 = doc_new(A, "walrus-1.txt", "Walrus invoice spring", WS, OPEN, sender="Polar Ltd", type="Invoice", tags=["Tax"], date="2025-03-10")
D2 = doc_new(A, "walrus-2.txt", "Walrus letter summer", WS, SUB, sender="Ice GmbH", type="Letter", tags=["Private"], date="2024-06-01")
D3 = doc_new(A, "walrus-3.txt", "Walrus contract board", WS, SHUT, sender="Polar Ltd", type="Invoice", tags=["Tax"], date="2025-01-05")
D4 = doc_new(A, "narwhal-4.txt", "Narwhal note autumn", WS, OPEN, date="2023-02-02")
ALL = sorted([D1, D2, D3, D4])
check(flat(A, "") == ALL and flat(Bo, "") == sorted([D1, D2, D4]), f"setup: the admin sees four, the member three {flat(A, '')} {flat(Bo, '')}")
fc = A.get(B + "/api/docs/facets", params={"ws": WS}).json()
g = lambda kind, name: next(",".join(map(str, x["ids"])) for x in fc[kind] if x["name"] == name)  # noqa: E731
POLAR, ICE, INV, LET, TAX, PRIV = g("senders", "Polar Ltd"), g("senders", "Ice GmbH"), g("types", "Invoice"), g("types", "Letter"), g("tags", "Tax"), g("tags", "Private")

# ---------------------------------------------------------------- conditions, AND / OR, "is none of"
T = {"f": "text", "op": "has", "v": "Walrus"}
check(total(A, rules(T)) == 3 and total(Bo, rules(T)) == 2, "text: the admin counts three, the member only his two (his rights)")
check(hit_ids(A, rules({"f": "sender", "op": "in", "v": [POLAR]})) == sorted([D1, D3]), "sender is one of")
check(hit_ids(Bo, rules({"f": "sender", "op": "in", "v": [POLAR]})) == [D1], "the member: only the sender's document he sees")
check(hit_ids(A, rules({"f": "type", "op": "in", "v": [LET]})) == [D2], "document type")
check(hit_ids(A, rules({"f": "sender", "op": "in", "v": [ICE]}, {"f": "tag", "op": "in", "v": [TAX]}, op="or")) == sorted([D1, D2, D3]), "OR: any one")
check(hit_ids(A, rules({"f": "sender", "op": "in", "v": [ICE]}, {"f": "tag", "op": "in", "v": [TAX]})) == [], "AND: all of them")
check(hit_ids(A, rules(T, {"f": "tag", "op": "nin", "v": [TAX]}, op="or")) == [D2], "OR with \"is none of\": the none holds on top")
check(hit_ids(A, rules({"f": "sender", "op": "nin", "v": [POLAR]})) == sorted([D2, D4]),
      "rueckfall: \"is none of\" keeps the document without a sender (NULL)")
check(hit_ids(A, rules({"f": "tag", "op": "nin", "v": [TAX, PRIV]})) == [D4], "is none of several tags: the one without tags")
check(hit_ids(A, rules({"f": "sender", "op": "empty"})) == [D4] and hit_ids(A, rules({"f": "tag", "op": "empty"})) == [D4], "is empty")
check(hit_ids(A, rules({"f": "folder", "op": "in", "v": [str(OPEN)]})) == sorted([D1, D2, D4]), "folder with its subfolders")
check(hit_ids(A, rules({"f": "folder", "op": "in", "v": [str(OPEN)], "sub": 0})) == sorted([D1, D4]), "folder only itself (an older view)")
check(hit_ids(Bo, rules({"f": "folder", "op": "in", "v": [str(SHUT)]})) == [], "a folder the member cannot see: nothing")
check(hit_ids(A, rules({"f": "date", "op": "from", "v": "2025-01-01"})) == sorted([D1, D3]), "document date from")
check(hit_ids(A, rules({"f": "date", "op": "in", "v": ["2024", "2023"]})) == sorted([D2, D4]), "document date: one of the years")
check(hit_ids(A, rules({"f": "date", "op": "to", "v": "2024-12-31"}, {"f": "date", "op": "from", "v": "2024-01-01"})) == [D2], "from and to")
check(hit_ids(A, rules({"f": "added", "op": "in", "v": ["d7"]})) == ALL, "added: the last 7 days")
check(hit_ids(A, rules({"f": "ftype", "op": "in", "v": ["text"]})) == ALL and hit_ids(A, rules({"f": "ftype", "op": "in", "v": ["pdf"]})) == [], "file type")
check(hit_ids(A, rules({"f": "text", "op": "has", "v": "tag:Tax -board"})) == [D1], "text with the search syntax")
check(hit_ids(A, rules({"f": "text", "op": "nhas", "v": "Walrus"})) == [D4], "text does not contain")
check(hit_ids(A, rules({"f": "asn", "op": "empty"})) == ALL and hit_ids(A, rules({"f": "asn", "op": "set"})) == [], "archive number with / without")

# ---------------------------------------------------------------- an older view: its query string hits the same documents
OLD = ["q=Walrus", f"sender={POLAR}&tag={TAX}", f"tag={TAX}&tag={PRIV}&tag_mode=all", f"tag={TAX}&tag={PRIV}", f"not_tag={TAX}",
       f"under={OPEN}", f"folder={OPEN}", "from=2025-01-01&to=2025-12-31", "no_sender=1", "q=tag:Tax Walrus", "ftype=text",
       "q=-board Walrus", f"type={INV}&no_tag=1", "q=Walrus&sort=title&dir=asc", "added_from=2020-01-01",
       # 2.897.0 (#5547) rueckfall: a field id with a space / a comma at the end, from / to longer than 10 characters
       "cf=999999,%20:Yes", "cf=999999,:Yes", "from=2025-01-01T00:00:00Z&to=2025-12-31T23:59:59Z", "added_to=2020-01-01%2000:00"]
for s, who in ((A, "admin"), (Bo, "member")):
    for q in OLD:
        r = s.post(B + f"/api/obj/{K}", json={"title": "old " + q[:40], "query": q, "ws": WS})
        vid = r.json()["id"]
        want = flat(s, q)
        conv = count(s, query=q)
        lv = {v["id"]: v for v in s.get(B + "/api/docs/views", params={"ws": WS}).json()["items"]}[vid]
        check(in_view(s, vid) == want and lv["count"] == len(want) and conv["total"] == len(want) and lv["rules"]["conds"] == conv["rules"]["conds"],
              f"{who}: the older view \"{q}\" hits the same {want} (view {in_view(s, vid)}, count {lv['count']}, converted {conv})")
        s.post(B + f"/api/obj/{K}/{vid}/trash")
r = A.post(B + f"/api/obj/{K}", json={"title": "Sorted", "query": "q=Walrus&sort=title&dir=asc", "ws": WS})
SV = r.json()
check(SV["rules"].get("sort") == "title" and SV["rules"].get("dir") == "asc" and SV["query"] == "q=Walrus&sort=title&dir=asc",
      f"the older view keeps its sort in the converted rules, its query stays stored {SV}")
h = A.get(B + f"/api/docs/views/{SV['id']}/hits", params={"limit": 5}).json()
want = [d["id"] for d in A.get(B + "/api/docs", params={"ws": WS, "q": "Walrus", "sort": "title", "dir": "asc", "facets": "0"}).json()["docs"]]
check([d["id"] for d in h["docs"]] == want and h["total"] == 3, f"its hits in its sort (as the search sorts by title) {want} {h}")

# ---------------------------------------------------------------- a view with rules: list, hits, rights, sharing
R1 = rules({"f": "sender", "op": "in", "v": [POLAR]}, {"f": "type", "op": "in", "v": [LET]}, op="or")
r = A.post(B + f"/api/obj/{K}", json={"title": "Polar or letters", "rules": R1, "ws": WS})
check(r.status_code == 201 and r.json()["rules"] == R1 and r.json()["query"] == "", f"a new view keeps its rules ({r.status_code} {r.text[:200]})")
VID = r.json()["id"]
lv = {v["id"]: v for v in A.get(B + "/api/docs/views", params={"ws": WS}).json()["items"]}
check(lv[VID]["count"] == 3 and lv[VID]["rules"] == R1, "listed with its count and its rules")
check(in_view(A, VID) == sorted([D1, D2, D3]), "the list in the view (?view=)")
check(ids_of(A.get(B + "/api/docs", params={"ws": WS, "facets": "0", "view": VID, "q": "spring"})) == [D1], "a search on top narrows the view")
check(A.get(B + f"/api/docs/views/{VID}/hits").json()["total"] == 3, "Today's hits")
check(Bo.get(B + "/api/docs", params={"ws": WS, "view": VID}).status_code == 404, "another's private view: 404 also through ?view=")
check(A.post(B + f"/api/docs/views/{VID}/share", json={"all": True}).ok, "setup: the admin shares it with everyone")
lb = {v["id"]: v for v in Bo.get(B + "/api/docs/views", params={"ws": WS}).json()["items"]}
check(lb.get(VID, {}).get("count") == 2 and in_view(Bo, VID) == sorted([D1, D2]), f"the member: the same filter with HIS documents {lb.get(VID)}")
r = Bo.patch(B + f"/api/obj/{K}/{VID}", json={"rules": rules(T)})
check(r.status_code in (403, 404), f"the member does not change the shared view ({r.status_code})")
cur = A.get(B + f"/api/obj/{K}/{VID}").json()
R2 = rules({"f": "tag", "op": "in", "v": [PRIV]})
r = A.patch(B + f"/api/obj/{K}/{VID}", json={"rules": R2, "expect_updated_at": cur["updated_at"]})
check(r.ok and r.json()["rules"] == R2 and in_view(A, VID) == [D2], f"changed rules ({r.status_code} {r.text[:200]})")
r = A.patch(B + f"/api/obj/{K}/{VID}", json={"rules": R1, "expect_updated_at": cur["updated_at"]})
check(r.status_code == 409, f"a stale version: 409 ({r.status_code})")

# ---------------------------------------------------------------- bad rules
r = A.post(B + f"/api/obj/{K}", json={"title": "Odd", "ws": WS, "rules": {"op": "xor", "conds": [
    {"f": "sender", "op": "in", "v": [POLAR]}, {"f": "nope", "op": "in", "v": ["1"]}, {"f": "sender", "op": "gt", "v": 3},
    {"f": "cf", "op": "in", "v": ["x"], "ids": "1; DROP"}, "x", {"f": "text", "op": "has", "v": ["no"]}], "evil": "1"}})
check(r.status_code == 201 and r.json()["rules"] == {"op": "and", "conds": [{"f": "sender", "op": "in", "v": [POLAR]}, {"f": "text", "op": "has", "v": ""}]},
      f"conditions that do not fit are left out ({r.status_code} {r.text[:300]})")
check(A.post(B + f"/api/obj/{K}", json={"title": "Bad", "ws": WS, "rules": "not json"}).status_code == 400, "rules that are no filter: 400")
check(A.post(B + f"/api/obj/{K}", json={"title": "Bad", "ws": WS, "rules": [1, 2]}).status_code == 400, "a list is no filter: 400")
j = count(A, rules={"op": "and", "conds": [{"f": "text", "op": "has", "v": "x" * 30000}]})
check(isinstance(j, dict) and len(j["rules"]["conds"][0]["v"]) == 500 and j["total"] == len(flat(A, "q=" + "x" * 500)),
      f"a long text is cut (500), not an error, and counts as the search with that text {j if not isinstance(j, dict) else j['total']}")
check(count(A, ws="org:abc", rules=R1) == 400, "the count: a bad workspace is 400")
check(sess().post(B + "/api/docs/views/count", json={"rules": R1}).status_code in (401, 403), "the count needs a signed-in person")

# ---------------------------------------------------------------- 2.857.0 (#5518 review): limits and robust values (rueckfall)
j = count(A, rules=rules({"f": "sender", "op": "nin", "v": [str(900000 + i) for i in range(40)]}))
check(isinstance(j, dict) and len(j["rules"]["conds"][0]["v"]) == 30, "a name condition keeps at most 30 names, as the search")
j = count(A, rules=rules(*[{"f": "text", "op": "has", "v": f"word{i}"} for i in range(8)], op="or"))
check(isinstance(j, dict) and len(j["rules"]["conds"]) == 5, "at most 5 text conditions per filter")
ALL = len(flat(A, ""))
check(total(A, rules({"f": "text", "op": "nhas", "v": "date:foo"})) == ALL, "a text with nothing searchable is off, not an empty view")
check(total(A, rules({"f": "asn", "op": "eq", "v": "\u00b2"})) == ALL, "asn: a superscript digit is no number (off, no 500)")
r = A.post(B + f"/api/obj/{K}", json={"title": "Odd folder", "ws": WS, "rules": rules({"f": "folder", "op": "in", "v": ["\u00b2"]})})
check(r.status_code == 201, f"a view with an odd folder value is stored ({r.status_code})")
check(A.get(B + "/api/docs/views", params={"ws": WS}).status_code == 200, "the views' list stays 200 with an odd folder value (no 500)")
check(A.get(B + "/api/docs", params={"ws": WS, "view": "\u00b2"}).status_code != 500, "?view= with a superscript digit is no 500")
A.post(B + f"/api/obj/{K}/{r.json()['id']}/trash")

# ---------------------------------------------------------------- 2.897.0 (#5547): the agent's ?view=, the window of opened texts
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "docbot", "display_name": "Docbot", "scopes": ["read", "files:read"], "org_id": ORG})
check(r.ok, "setup: an agent of the organisation " + r.text[:200])
AG, AGH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
for f_ in (OPEN, SHUT):
    check(A.post(B + f"/api/files/nodes/{f_}/shares", json={"agent_id": AG, "role": "view"}).status_code == 201, "setup: the folders shared with the agent")


def v1_view(vid, **p):
    r = sess().get(B + "/api/v1/documents", params={"view": vid, **p}, headers=AGH)
    return sorted(d["id"] for d in r.json()["data"]) if r.ok else r.status_code


def agent_view(title, ws, rl):
    r = A.post(B + f"/api/obj/{K}", json={"title": title, "rules": rl, "ws": ws})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert A.post(B + f"/api/obj/{K}/{vid}/shares", json={"agent_id": AG, "role": "view"}).status_code == 201
    return vid


VW = agent_view("Walrus here", WS, rules(T))
check(v1_view(VW) == sorted([D1, D2, D3]), f"#5547: the agent's list through a view shared with it {v1_view(VW)}")
VP = agent_view("Walrus private", "private", rules(T))
check(in_view(A, VP, "private") == [] and v1_view(VP) == [],
      f"#5547 rueckfall: the view's workspace holds for the agent as in the app (private: none of the organisation's) {v1_view(VP)}")
VS = agent_view("Failed only", WS, {**rules(T), "state": "failed"})
check(in_view(A, VS) == [] and v1_view(VS) == [], f"#5547 rueckfall: the view's state holds for the agent as in the app {v1_view(VS)}")
check(sess().get(B + "/api/v1/documents", params={"view": VS, "state": "done"}, headers=AGH).json()["data"] != [],
      "#5547: a parameter of the request goes before the view's")
VN = A.post(B + f"/api/obj/{K}", json={"title": "Not shared", "rules": rules(T), "ws": WS}).json()["id"]
check(v1_view(VN) == 404, "#5547: a view not shared with the agent stays 404")

# the window (3 texts here): four documents with the phrase, the one with the sender last
Z = [doc_new(A, f"zebra-{i}.txt", "Zebra stripes paper", WS) for i in range(3)]
Z4 = doc_new(A, "zebra-4.txt", "Zebra stripes paper", WS, sender="Stripe Co")
fc = A.get(B + "/api/docs/facets", params={"ws": WS}).json()
STRIPE = g("senders", "Stripe Co")
PH = {"f": "text", "op": "has", "v": '"zebra stripes"'}
check(flat(A, urlencode({"q": '"zebra stripes"', "sender": STRIPE})) == [Z4], "setup: the search finds it (its filters first)")
check(hit_ids(A, rules({"f": "sender", "op": "in", "v": [STRIPE]}, PH)) == [Z4],
      "#5547 rueckfall: a view's phrase is looked for after its other conditions (AND), not in the first texts of all")
VZ = A.post(B + f"/api/obj/{K}", json={"title": "Zebra", "rules": rules(PH), "ws": WS}).json()["id"]
check(ids_of(A.get(B + "/api/docs", params={"ws": WS, "facets": "0", "view": VZ, "sender": STRIPE})) == [Z4],
      "#5547 rueckfall: the list's own filters narrow before the view's phrase")

# ---------------------------------------------------------------- freelancer-matrix: obj -- a person without an organisation
F1 = doc_new(Fr, "wombat.txt", "Wombat receipt", "private", sender="Burrow Shop")
F2 = doc_new(Fr, "koala.txt", "Koala receipt", "private")
ffc = Fr.get(B + "/api/docs/facets", params={"ws": "private"}).json()
BUR = next(",".join(map(str, x["ids"])) for x in ffc["senders"] if x["name"] == "Burrow Shop")
FR = rules({"f": "sender", "op": "in", "v": [BUR]}, {"f": "text", "op": "has", "v": "Koala"}, op="or")
check(count(Fr, ws="private", rules=FR)["total"] == 2, "freelancer: the dialog's count")
# tenant: POST /api/docs/views/count
check(count(A, rules=R1)["total"] > 0 and count(Fr, rules=R1)["total"] == 0,
      "#5518: a stranger's count on another organisation's workspace hits none of its documents")
r = Fr.post(B + f"/api/obj/{K}", json={"title": "Receipts", "rules": FR, "ws": "private"})
check(r.status_code == 201, f"freelancer: her view with rules ({r.status_code})")
FV = r.json()["id"]
check(in_view(Fr, FV, "private") == sorted([F1, F2]) and Fr.get(B + f"/api/docs/views/{FV}/hits").json()["total"] == 2, "freelancer: the list and the hits")
check(A.get(B + "/api/docs", params={"ws": "all", "view": FV}).status_code == 404, "the instance admin does not run her view")
sys.exit(done("p2857_a_docfilter"))
