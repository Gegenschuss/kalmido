"""2.391.0 (#3362): setting up integrations through the REST API -- webhooks (own and an organisation's), API tokens and
repository connections under /api/v1, for scripts of a person (agents never: scope "integrations" is in SCOPES_AGENT_NEVER,
never part of the legacy "write" or a default, and the token routes refuse agents themselves).

One code path with the web app: every route here only checks what is special about a token and then runs the very view
of Settings (g.body hands it the request), so need_webhook / _need_org_admin / git_need_manage / the field checks are the
same. Secrets (the token itself, a webhook's signing secret, a repository's hook secret) come back once in the answer
that creates / rotates them and never in a list; a repository's access token is only stored (sealed), never returned.

A token never makes a token that may more than itself (token_cap): its effective scopes, its addresses, its projects and
its lifetime are the ceiling of the new one. Webhooks deliver events of every project their owner sees, so only a token
for all projects manages them (like app passwords, 2.79.0 #476 M1)."""
import ipaddress
from datetime import timedelta
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db, iso, now_utc, parse_iso
from ..core.access import Denied, token_lists
from ..core.errors import BadInput, reject_unknown
from ..api.common import v1_args, v1_call, v1_json, v1_view
from ..api.v1 import api_scopes, SCOPES, SCOPES_WRITE, token_delete, token_insert, token_lists_clean, tokens_list
from ..api.scopes import ips_clean, need_scope, scopes_clean
from ..tasks.validation import as_int
from ..integrations import webhooks as wh
from ..integrations import git as gi
from ..integrations import gitbuild as gb
from ..integrations.gitfolder import gf_row
from ..api.v1 import need_api  # 2.369.5 (#2517): pulled up from functions

V1S_TOKEN_IN = ("name", "scopes", "allowed_ips", "list_ids", "expires_days")
V1S_HOOK_IN = ("name", "url", "events", "enabled")
V1S_REPO_IN = ("provider", "base_url", "repo", "owner", "token")
V1S_REPO_PATCH = ("token", "hook", "hash_ids", "author_name", "author_email")


def v1s_view(view, *a, b=None):
    """Runs a Settings view with b as its body and answers what it answers (201 included; errors -> v1_out)."""
    g.body = b if b is not None else {}
    try:
        return view(*a)
    finally:
        g.body = None


def v1s_folder_repo_limit(cid):
    """2.391.0 (#3362 review S1): a folder repository belongs to the folder, not to one list -- its owner path does not see a
    token's project limit, so a token limited to projects cannot change or remove one (404, like a repository it cannot see)."""
    if token_lists() is not None and gf_row(db(), cid):
        raise Denied(404)


def v1s_person():
    if (g.user["kind"] or "user") == "agent":  # the scope already keeps agents out; this stays if a scope table ever changes
        raise Denied(403, tr("Agents cannot set up integrations"))


def v1s_all_lists():
    if token_lists() is not None:
        raise Denied(403, tr("Only a token for all projects may manage webhooks"))


# ---- a new token never more than the calling one
def _nets(csv_):
    return [ipaddress.ip_network(x, strict=False) for x in (csv_ or "").split(",") if x]


def token_cap(c, b):
    """The checked values of a token the calling token creates -> (name, scopes, exp, ips, lids); Denied 403 when the new
    token would have more scopes, more addresses, more projects or a longer life than the calling token."""
    t = g.token
    name = str(b.get("name") or "").strip()[:60]
    if not name:
        raise BadInput(tr("Name missing"))
    want = set(scopes_clean(b.get("scopes") or ["read"], g.user))
    if "write" in want:  # stored as the fine scopes: a later "write" must not grow beyond what the calling token had
        want = (want - {"write"}) | set(SCOPES_WRITE)
    more = [s for s in SCOPES if s in want - set(g.scopes)]
    if more:
        raise Denied(403, tr("A token cannot create a token with more permissions than its own: {0}", ", ".join(more)))
    ips = ips_clean(b.get("allowed_ips"))
    mine = _nets(t["allowed_ips"] if "allowed_ips" in t.keys() else "")
    if mine:
        if not ips:
            ips = ",".join(str(n) for n in mine)  # no addresses given = the calling token's
        elif not all(any(n.version == m.version and n.subnet_of(m) for m in mine) for n in _nets(ips)):
            raise Denied(403, tr("A token cannot create a token for more addresses than its own"))
    raw, tl = b.get("list_ids"), token_lists()
    if tl is not None and raw not in (None, "", []):  # before list_ids_clean: a project outside the token is not even visible (400)
        try:
            ask = {int(x) for x in (raw if isinstance(raw, list) else str(raw).split(",")) if str(x).strip()}
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "list_ids")) from None
        if not ask <= set(tl):
            raise Denied(403, tr("A token cannot create a token for more projects than its own"))
    lids = token_lists_clean(c, raw)
    if tl is not None and not lids:
        lids = ",".join(str(x) for x in sorted(tl))  # no projects given = the calling token's
    days = b.get("expires_days")
    exp = None
    if days not in (None, "", 0):
        exp = now_utc() + timedelta(days=as_int(days, tr("Expiry"), 1, 3650))
    if t["expires_at"]:
        until = parse_iso(t["expires_at"])
        if exp is None:
            exp = until  # no expiry given = the calling token's
        elif exp > until:
            raise Denied(403, tr("A token cannot create a token that lives longer than itself (until {0})", t["expires_at"][:10]))
    return name, sorted(want), iso(exp) if exp else None, ips, lids


def v1s_tokens():
    v1s_person()
    need_scope("account")  # tokens are credentials of the account


@app.get("/api/v1/me/tokens")
@v1_view
def v1s_token_list():
    v1_args(())
    v1s_tokens()
    j = v1_call(tokens_list)
    tl = token_lists()
    if tl is not None:  # 2.575.0 (#3948): a project-limited token sees the others' projects only within its own limit
        for t in j["tokens"]:
            t["list_ids"] = [x for x in t["list_ids"] if x in tl] if t["list_ids"] else sorted(tl)
    return jsonify(data=j["tokens"], scopes=j["scopes"], limit=j["limit"], enabled=j["enabled"], rate=j["rate"])


@app.post("/api/v1/me/tokens")
@v1_view
def v1s_token_create():
    """{name, scopes?, allowed_ips?, list_ids?, expires_days?} -> the token (shown this once), never more than the calling one."""
    v1_args(())
    b = v1_json()
    reject_unknown(b, V1S_TOKEN_IN)
    v1s_tokens()
    need_api()
    c = db()
    name, scopes, exp, ips, lids = token_cap(c, b)
    return token_insert(c, name, scopes, exp, ips, lids)


@app.delete("/api/v1/me/tokens/<int:tid>")
@v1_view
def v1s_token_delete(tid):
    """Revokes one of the person's tokens (the calling one too)."""
    v1_args(())
    v1s_tokens()
    r = db().execute("SELECT scopes FROM api_tokens WHERE id=? AND user_id=?", (tid, g.user["id"])).fetchone()
    if r and "docs:upload" in api_scopes(r["scopes"]):  # a scan inbox key belongs to its inbox (Documents > Settings)
        raise Denied(403, tr("A scan inbox key is removed in the document settings"))
    return v1s_view(token_delete, tid)


# ---- webhooks: the person's own (/me/webhooks) and an organisation's (/orgs/{id}/webhooks, its admins)
def v1s_hook_scope(oid):
    v1s_person()
    v1s_all_lists()
    if oid:
        wh.who_need_admin(oid)


def v1s_hook_list(oid=None):
    v1_args(())
    v1s_hook_scope(oid)
    j = v1_call(wh.wh_list_do, oid)
    return jsonify(data=j["hooks"], events=j["events"], enabled=j["enabled"])


def v1s_hook_create(oid=None):
    v1_args(())
    b = v1_json()
    reject_unknown(b, V1S_HOOK_IN)
    v1s_hook_scope(oid)
    return v1s_view(wh.wh_create_do, oid, b=b)


def v1s_hook_update(wid, oid=None):
    v1_args(())
    b = v1_json()
    reject_unknown(b, V1S_HOOK_IN)
    v1s_hook_scope(oid)
    return v1s_view(wh.wh_update_do, wid, oid, b=b)


def v1s_hook_do(fn, wid, oid=None):
    v1_args(())
    v1s_hook_scope(oid)
    return v1s_view(fn, wid, oid)


@app.get("/api/v1/me/webhooks")
@v1_view
def v1s_webhooks():
    return v1s_hook_list()


@app.post("/api/v1/me/webhooks")
@v1_view
def v1s_webhook_create():
    """{name?, url, events, enabled?} -> the webhook + its signing secret (shown this once)."""
    return v1s_hook_create()


@app.patch("/api/v1/me/webhooks/<int:wid>")
@v1_view
def v1s_webhook_update(wid):
    return v1s_hook_update(wid)


@app.delete("/api/v1/me/webhooks/<int:wid>")
@v1_view
def v1s_webhook_delete(wid):
    return v1s_hook_do(wh.wh_delete_do, wid)


@app.post("/api/v1/me/webhooks/<int:wid>/secret")
@v1_view
def v1s_webhook_secret(wid):
    return v1s_hook_do(wh.wh_secret_do, wid)


@app.post("/api/v1/me/webhooks/<int:wid>/test")
@v1_view
def v1s_webhook_test(wid):
    return v1s_hook_do(wh.wh_test_do, wid)


@app.get("/api/v1/me/webhooks/<int:wid>/log")
@v1_view
def v1s_webhook_log(wid):
    return v1s_hook_do(wh.wh_log_do, wid)


@app.get("/api/v1/orgs/<int:oid>/webhooks")
@v1_view
def v1s_org_webhooks(oid):
    return v1s_hook_list(oid)


@app.post("/api/v1/orgs/<int:oid>/webhooks")
@v1_view
def v1s_org_webhook_create(oid):
    return v1s_hook_create(oid)


@app.patch("/api/v1/orgs/<int:oid>/webhooks/<int:wid>")
@v1_view
def v1s_org_webhook_update(oid, wid):
    return v1s_hook_update(wid, oid)


@app.delete("/api/v1/orgs/<int:oid>/webhooks/<int:wid>")
@v1_view
def v1s_org_webhook_delete(oid, wid):
    return v1s_hook_do(wh.wh_delete_do, wid, oid)


@app.post("/api/v1/orgs/<int:oid>/webhooks/<int:wid>/secret")
@v1_view
def v1s_org_webhook_secret(oid, wid):
    return v1s_hook_do(wh.wh_secret_do, wid, oid)


@app.post("/api/v1/orgs/<int:oid>/webhooks/<int:wid>/test")
@v1_view
def v1s_org_webhook_test(oid, wid):
    return v1s_hook_do(wh.wh_test_do, wid, oid)


@app.get("/api/v1/orgs/<int:oid>/webhooks/<int:wid>/log")
@v1_view
def v1s_org_webhook_log(oid, wid):
    return v1s_hook_do(wh.wh_log_do, wid, oid)


# ---- repository connections of a project (its owner / list admins; GET /lists/{id}/repos is in errorreports.py)
@app.post("/api/v1/lists/<int:lid>/repos")
@v1_view
def v1s_repo_add(lid):
    """{provider?, base_url?, repo, owner?, token?} -> the connection (the access token only stored, never returned)."""
    v1_args(())
    b = v1_json()
    reject_unknown(b, V1S_REPO_IN)
    v1s_person()
    return v1s_view(gi.git_add, lid, b=b)


@app.patch("/api/v1/repos/<int:cid>")
@v1_view
def v1s_repo_update(cid):
    """{token?, hook?: on (new secret, shown this once) | off, hash_ids?, author_name?, author_email?}"""
    v1_args(())
    b = v1_json()
    reject_unknown(b, V1S_REPO_PATCH)
    v1s_person()
    v1s_folder_repo_limit(cid)
    return v1s_view(gi.git_update, cid, b=b)


@app.delete("/api/v1/repos/<int:cid>")
@v1_view
def v1s_repo_delete(cid):
    v1_args(())
    v1s_person()
    v1s_folder_repo_limit(cid)
    return v1s_view(gi.git_delete, cid)


@app.put("/api/v1/lists/<int:lid>/repos/version-field")
@v1_view
def v1s_repo_version_field(lid):
    """{field: auto | off | <id of a text / select field>} -- the field with the package / target version."""
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("field",))
    v1s_person()
    return v1s_view(gb.gb_ver_set, lid, b=b)


# ---- the OpenAPI document
def v1s_spec(paths, schemas, op, ok, errs, ref, pid):
    S, I = "integrations", "Account"
    hid, oidp, owid = pid("id", "Webhook id"), pid("id", "Organisation id"), pid("webhook_id", "Webhook id")
    tok = {"type": "object", "properties": {
        "id": {"type": "integer"}, "name": {"type": "string"}, "prefix": {"type": "string"},
        "scopes": {"type": "array", "items": {"type": "string"}}, "effective_scopes": {"type": "array", "items": {"type": "string"}},
        "allowed_ips": {"type": "array", "items": {"type": "string"}}, "list_ids": {"type": "array", "items": {"type": "integer"}},
        "expires_at": {"type": ["string", "null"]}, "created_at": {"type": "string"}, "last_used_at": {"type": ["string", "null"]},
        "expired": {"type": "boolean"}, "upload_only": {"type": "boolean"},
        "token": {"type": "string", "description": "Only in the answer of POST: the token (abk_...), shown this once"}}}
    schemas["ApiToken"] = tok
    hook = {"type": "object", "properties": {
        "id": {"type": "integer"}, "name": {"type": "string"}, "url": {"type": "string"}, "events": {"type": "array", "items": {"type": "string"}},
        "enabled": {"type": "boolean"}, "disabled_reason": {"type": "string"}, "created_at": {"type": "string"}, "pending": {"type": "integer"},
        "last": {"type": ["object", "null"]},
        "secret": {"type": "string", "description": "Only in the answer of POST and POST .../secret: the signing secret (whsec_...), shown this once"}}}
    schemas["Webhook"] = hook
    hook_in = {"type": "object", "additionalProperties": False, "properties": {
        "name": {"type": "string", "maxLength": 60}, "url": {"type": "string", "description": "https address the events are POSTed to"},
        "events": {"type": "array", "items": {"type": "string"}, "description": "See GET .../webhooks (events)"}, "enabled": {"type": "boolean"}}}
    tok_in = {"type": "object", "required": ["name"], "additionalProperties": False, "properties": {
        "name": {"type": "string", "maxLength": 60},
        "scopes": {"type": "array", "items": {"type": "string"}, "description": "At most the calling token's effective scopes (default: read)"},
        "allowed_ips": {"type": "array", "items": {"type": "string"}, "description": "Within the calling token's addresses (default: its addresses, or any)"},
        "list_ids": {"type": "array", "items": {"type": "integer"}, "description": "Within the calling token's projects (default: its projects, or all)"},
        "expires_days": {"type": ["integer", "null"], "minimum": 1, "maximum": 3650,
                         "description": "Never beyond the calling token's expiry (default: its expiry, or none)"}}}
    page_of = lambda n, **extra: {"type": "object", "properties": {"data": {"type": "array", "items": ref(n)}, **extra}}  # noqa: E731
    lst = page_of("Webhook", events={"type": "array", "items": {"type": "string"}}, enabled={"type": "boolean"})
    paths["/me/tokens"] = {
        "get": op("My API tokens (never their value)", "Account", ok(page_of("ApiToken", scopes={"type": "array", "items": {"type": "object"}})) | errs("403"), scope=S,
                  desc="Needs the scopes integrations and account. People only."),
        "post": op("Create an API token (shown this once; never more than the calling token)", "Account",
                   ok(ref("ApiToken"), "Created", "201") | errs("400", "403", "409"), scope=S, body=tok_in,
                   desc="Needs integrations and account. Scopes, addresses, projects and lifetime stay within the calling token's.")}
    paths["/me/tokens/{id}"] = {
        "delete": op("Revoke one of my API tokens", "Account", ok({"type": "object"}) | errs("403", "404"), [pid("id", "Token id")], scope=S)}
    for base, params, one, who in (("/me/webhooks", [], [hid], "my"), ("/orgs/{id}/webhooks", [oidp], [oidp, owid], "the organisation's (its admins)")):
        item = base + ("/{id}" if not params else "/{webhook_id}")
        paths[base] = {
            "get": op(f"List {who} webhooks (never their secret)", I, ok(lst) | errs("403", "404"), params, scope=S,
                      desc="Only a token for all projects (webhooks deliver events of every project)."),
            "post": op(f"Create one of {who} webhooks (the signing secret is shown this once)", I,
                       ok(ref("Webhook"), "Created", "201") | errs("400", "403", "404", "409"), params, scope=S, body=hook_in)}
        paths[item] = {
            "patch": op(f"Change one of {who} webhooks", I, ok(ref("Webhook")) | errs("400", "403", "404", "409"), one, scope=S, body=hook_in),
            "delete": op(f"Delete one of {who} webhooks", I, ok({"type": "object"}) | errs("403", "404"), one, scope=S)}
        paths[item + "/secret"] = {
            "post": op("A new signing secret (the old one stops at once; shown this once)", I, ok({"type": "object"}) | errs("403", "404", "409"),
                       one, scope=S)}
        paths[item + "/test"] = {
            "post": op("Send a ping event now (no retries) and answer the result", I, ok({"type": "object"}) | errs("403", "404", "409"),
                       one, scope=S)}
        paths[item + "/log"] = {
            "get": op("The delivery log of a webhook", I, ok({"type": "object"}) | errs("403", "404"), one, scope=S)}
    lp, rp = pid("id", "Project id (internally: list)"), pid("id", "Repository connection id")
    repo_in = {"type": "object", "required": ["repo"], "additionalProperties": False, "properties": {
        "provider": {"type": "string", "enum": list(gi.GIT_PROVIDERS)}, "base_url": {"type": "string"},
        "repo": {"type": "string", "description": "owner/name or the repository's address"}, "owner": {"type": "string"},
        "token": {"type": "string", "description": "Access token of the provider: only stored (sealed), never returned"}}}
    paths.setdefault("/lists/{id}/repos", {})["post"] = op(
        "Connect a repository to a project (its owner / project admins; people only)", "Lists", ok(ref("Repo"), "Created", "201") | errs("400", "403", "404", "409"),
        [lp], scope=S, body=repo_in)
    paths["/lists/{id}/repos/version-field"] = {
        "put": op("Which field holds the package / target version (auto, off or a field id)", I, ok({"type": "object"}) | errs("400", "403", "404"),
                  [lp], scope=S, body={"type": "object", "required": ["field"], "additionalProperties": False,
                                       "properties": {"field": {"type": ["string", "integer"], "description": "auto | off | field id"}}})}
    paths["/repos/{id}"] = {
        "patch": op("Change a repository connection (hook on: its secret is shown this once)", "Lists", ok(ref("Repo")) | errs("400", "403", "404", "409"),
                    [rp], scope=S, body={"type": "object", "additionalProperties": False, "properties": {
                        "token": {"type": "string", "description": "New access token, \"\" = remove (never returned)"},
                        "hook": {"type": "string", "enum": ["on", "off"]}, "hash_ids": {"type": "boolean"},
                        "author_name": {"type": "string"}, "author_email": {"type": "string"}}}),
        "delete": op("Remove a repository connection with its stored pull requests and commits", "Lists", ok({"type": "object"}) | errs("403", "404"),
                     [rp], scope=S)}

