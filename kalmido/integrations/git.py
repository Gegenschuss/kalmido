"""Git integration of project lists (GitHub, GitLab, Gitea / Forgejo, Bitbucket) and tickets for agents."""
import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import g, has_request_context, jsonify, request

from ..core.config import app, APP_NAME, APP_VERSION, PUBLIC_URL, SECRET_KEY
from ..core.pg import insert_id
from ..core.i18n import N_, tr
from ..core.db import body, bump, connect, db, err, iso, now_utc, parse_iso
from ..accounts.session import GATE, me
from ..core.access import Denied, is_project, list_role, MANAGE_ROLES, need_list, need_task
from ..tasks.validation import log_act
from ..tasks.tasks import one_task
from ..tasks.lifecycle import do_complete, signed, undo_status
from ..core.errors import BadInput, UnknownFields
from ..notify.push import _b64u, _b64u_dec
from ..notify.alerts import _env_int, aa_count
from ..calendars.subscriptions import _cal_opener, cal_allow, cal_err_text, cal_host_allowed, cal_rate, CAL_TIMEOUT, CalError
from ..agents.core import agent_row, agent_runtime, git_author_clean, git_author_str, is_agent
from ..tasks.ticketkey import tk_find, tk_has_key, tk_prefixes, tk_text_pairs, tk_text_re  # 2.390.0 (#3353)
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions


# ---------------------------------------------------------------- 2.2.0 (#271): Git integration, (#339) tickets for agents
# A PROJECT list can be connected to one or more repositories (list dialog > "Repository"): GitHub (github.com or a GitHub
# Enterprise server) or Gitea / Forgejo. Only the list owner and list admins (people, never agents) connect, change or remove
# them; everyone who sees the list sees the results. The access token (read-only is enough; optional for public repos) is
# write-only and sealed (AES-GCM, KALMIDO_SECRET_KEY, associated data = the connection);
# without the key no token can be stored.
# Kalmido only READS: a background thread (git_loop, like the calendar sync) polls every connection every KALMIDO_GIT_POLL
# seconds (default 180) with ETag / If-None-Match (a 304 costs GitHub no rate limit), reads the rate-limit headers (below
# GIT_RATE_FLOOR requests left it pauses until the reset; 403 / 429 with a reset or Retry-After likewise), backs off on errors
# (interval x 2^fails, at most an hour) and does at most GIT_PER_TICK connections per tick, so requests never wait on it.
# Per poll: the newest GIT_ITEMS pull requests, the newest GIT_ITEMS commits of the default branch, the commits of at most
# GIT_BRANCHES branches of open pull requests that name a task (compare against the default branch), and the combined status +
# check runs of at most GIT_CI pull request heads whose CI is unknown / pending / changed. Every request goes through the SSRF
# guard of the calendar subscriptions (internal hosts only where an admin allowed them), no redirects are followed.
# MATCHING (only tasks of the connected list): "#<task id>" in a commit message, pull request title or body; branch names
# kalmido-<id> / kalmido-<id>-..., task-<id>..., <id>-slug (the last path segment; older suggestions had a title slug). Only linked pull requests / commits are stored.
# KEYWORDS: "fixes / closes / resolves #<id>" (also fix / fixed, close / closed, resolve / resolved, German "erledigt") in a
# MERGED pull request (title / body) or a commit on the default branch that came after the connection was made complete the
# task, once per task (git_closes; the activity names the pull request / commit, "Undo" reopens it).
# Optional inbound webhook per connection (off by default): POST /api/hooks/git/<id> with the GitHub (X-Hub-Signature-256) or
# Gitea / Forgejo (X-Gitea-Signature / X-Forgejo-Signature) HMAC-SHA256 of a per-connection secret only triggers the next
# poll at once; its body is never trusted.
# #339: an agent assigned to a task in such a list gets the repository in its task events (data.repo: provider, URLs,
# owner / repo, default branch, a suggested branch kalmido-<id> (2.5.1, #396: no title part), the linked pull requests + CI); when its pull request
# is ready it posts a comment with suggestion {kind: "merge_request", pr_url, summary} (MCP request_merge_approval): 👍 / 👎
# by an approver (list owner / admin, the assignee, an instance admin) sets it approved / rejected and sends the agent the
# usual "reaction" event with approval + merge_request. Kalmido never merges anything: the agent does, with its own credentials.
GIT_POLL_S = _env_int("KALMIDO_GIT_POLL", 180)          # s between two polls of a connection
GIT_TICK_S = _env_int("KALMIDO_GIT_TICK", 15)           # s between two looks at what is due
GIT_PER_TICK = 4                                        # connections per tick
GIT_ITEMS = 30                                          # pull requests / commits per request
GIT_BRANCHES = 3                                        # branches of open pull requests per poll
GIT_CI = 5                                              # CI lookups per poll
GIT_RATE_FLOOR = 25                                     # requests left: pause until the reset
GIT_BACKOFF_MAX = 3600                                  # s
GIT_MAX_BYTES = 4 * 1024 * 1024
GIT_HOOK_MAX_BYTES = 25 * 1024 * 1024                   # 2.126.0 B (#1979 I5): inbound hook body (GitHub sends at most 25 MB)
GIT_HOOK_PER_MIN = 120                                  # 2.126.0 B (#1979 I5): inbound hooks per connection and minute
GIT_MAX_CONNS = 5                                       # per list
GIT_TASK_PRS, GIT_TASK_COMMITS = 5, 5                   # shown per task
GIT_PROVIDERS = ("github", "gitea", "gitlab", "bitbucket")
# 2.18.0 (#408 "Software 2" A): GitLab (gitlab.com or self-hosted, API v4; nested groups: the owner may be "group/sub",
# the project path is URL-encoded in the API) and Bitbucket CLOUD (api.bitbucket.org/2.0; Bitbucket Server / Data Center
# has another API and is not supported) next to GitHub and Gitea / Forgejo. Their answers are mapped onto the GitHub shape
# the poller reads (git_pr_norm / git_commit_norm), so matching, keywords, CI and the merge requests work the same.
# Hosts whose provider is unambiguous (the address of a repository on github.com / gitlab.com / bitbucket.org):
GIT_HOSTS = {"github.com": "github", "www.github.com": "github", "api.github.com": "github", "gitlab.com": "gitlab",
             "www.gitlab.com": "gitlab", "bitbucket.org": "bitbucket", "www.bitbucket.org": "bitbucket", "api.bitbucket.org": "bitbucket"}
GIT_API_SUFFIX = ("/api/v3", "/api/v1", "/api/v4", "/2.0")
GIT_TAGS_KEEP = 500                                     # tag names remembered per connection
GIT_ERR = {"auth": N_("Access denied: check the token (it needs read access to the repository)"),
           "not_found": N_("Repository not found, or the token cannot see it"),
           "rate": N_("Rate limit of the Git server reached, polling pauses until it resets"),
           "parse": N_("Unexpected answer from the Git server")}
GIT_HASH_RE = re.compile(r"(?<![\w/&#])#(\d{1,9})\b")
GIT_KEY_RE = re.compile(r"(?<![\w-])(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|erledigt)\s*:?\s+#(\d{1,9})\b", re.I)
GIT_BRANCH_RE = re.compile(r"^(?:(?:kalmido|task)[-_](\d{1,9})(?:[-_].*)?|(\d{1,9})-[a-z].*)$", re.I)
GIT_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_GIT_WAKE = threading.Event()


class GitRate(Exception):
    def __init__(self, until):
        super().__init__("rate")
        self.until = until


GIT_TOKEN_MAX = 400  # longest access token accepted


def git_norm_base_url(u):
    """The base URL of a self-hosted Git server (http(s), no credentials / query / fragment; a trailing /api is dropped)."""
    from ..calendars.subscriptions import cal_norm_url
    u = cal_norm_url(u)
    from ..admin.hosting import hosted
    if not u or not u.lower().startswith(("https://",) if hosted() else ("http://", "https://")):  # 2.24.0 (#905): hosted = HTTPS only
        return None
    p = urllib.parse.urlsplit(u)
    if p.query or p.fragment:
        return None
    if p.scheme.lower() == "http":  # 2.306.0 D3 (#2875): also localhost only through the allow list (no exception)
        # 2.190.0 C (#2496): the access token never goes in plain text: http only for hosts an admin allowed (like webhooks)
        try:
            port = p.port or 80
        except ValueError:
            return None
        if not cal_host_allowed(cal_allow(db()), p.hostname, port):
            raise BadInput(tr("The Git server needs https:// (http:// only for hosts an admin allowed)"))
    u = u.rstrip("/")
    if u.lower().endswith("/api"):
        u = u[:-4]
    return u


def git_err_text(stored):
    code = (stored or "").partition(":")[0]
    return tr(GIT_ERR[code]) if code in GIT_ERR else cal_err_text(stored)


def git_seal(cid, what, s):
    if not SECRET_KEY:
        raise BadInput(git_key_error())
    n = os.urandom(12)
    return "v1." + _b64u(n + AESGCM(SECRET_KEY).encrypt(n, s.encode(), f"kalmido-git:{what}:{cid}".encode()))


def git_unseal(cid, what, s):
    if not SECRET_KEY or not s or not s.startswith("v1."):
        return ""
    try:
        raw = _b64u_dec(s[3:])
        return AESGCM(SECRET_KEY).decrypt(raw[:12], raw[12:], f"kalmido-git:{what}:{cid}".encode()).decode()
    except (InvalidTag, ValueError, TypeError):
        return ""


def git_key_error():
    return tr("Set KALMIDO_SECRET_KEY on the server to store repository tokens (32 random bytes, base64)")


def git_urls(provider, base):
    """(API base, web base) of a connection."""
    if provider == "github":
        return ("https://api.github.com", "https://github.com") if not base else (base + "/api/v3", base)
    if provider == "gitlab":  # 2.18.0
        return ("https://gitlab.com/api/v4", "https://gitlab.com") if not base else (base + "/api/v4", base)
    if provider == "bitbucket":  # 2.18.0: Bitbucket Cloud (a base only for a compatible API under <base>/2.0, e.g. tests)
        return ("https://api.bitbucket.org/2.0", "https://bitbucket.org") if not base else (base + "/2.0", base)
    return base + "/api/v1", base


def git_repo_path(provider, owner, repo):
    """2.18.0: the API path of a repository (GitLab: the URL-encoded project path, nested groups included)."""
    q = urllib.parse.quote
    if provider == "gitlab":
        return "/projects/" + q(f"{owner}/{repo}", safe="")
    if provider == "bitbucket":
        return f"/repositories/{q(owner, safe='')}/{q(repo, safe='')}"
    return f"/repos/{q(owner)}/{q(repo)}"


def git_auth(provider, token):
    """2.18.0: the auth header of a provider. GitHub: Bearer; Gitea: token; GitLab: PRIVATE-TOKEN for its own tokens
    (glpat-... and other gl* prefixes), Bearer otherwise (OAuth tokens; also accepted for older personal tokens);
    Bitbucket: "user:app-password" as Basic, an access token (repository / workspace) as Bearer."""
    if not token:
        return {}
    if provider == "github":
        return {"Authorization": "Bearer " + token}
    if provider == "gitlab":
        return {"PRIVATE-TOKEN": token} if token.startswith("gl") else {"Authorization": "Bearer " + token}
    if provider == "bitbucket":
        return {"Authorization": ("Basic " + base64.b64encode(token.encode()).decode()) if ":" in token else "Bearer " + token}
    return {"Authorization": "token " + token}


def git_owner_ok(provider, owner):
    """owner = one name; on GitLab a group path with sub groups (group/sub/...)."""
    parts = str(owner or "").split("/")
    return len(parts) <= (20 if provider == "gitlab" else 1) and \
        all(GIT_NAME_RE.fullmatch(x) and x not in (".", "..") for x in parts)


def git_items(j):
    """A list answer: GitHub / Gitea / GitLab send a JSON array, Bitbucket a page {values: [...]}; None otherwise."""
    if isinstance(j, list):
        return j
    if isinstance(j, dict) and isinstance(j.get("values"), list):
        return j["values"]
    return None


def git_default_of(j):
    """The default branch in a repository answer (Bitbucket: mainbranch.name)."""
    if not isinstance(j, dict):
        return None
    d = j.get("default_branch") or _gd(j, "mainbranch", "name")
    return d if isinstance(d, str) else None


def git_ids(text):
    return {int(x) for x in GIT_HASH_RE.findall(text or "")}


def git_branch_id(ref, hash_ok=True):
    """The task id in a branch name; hash_ok False (2.390.0, #3353: a project with a key whose repository does not read
    "#123" any more) only kalmido-<id> / task-<id>, not "<id>-slug" (the branch names Git servers make for their issues)."""
    m = GIT_BRANCH_RE.match(str(ref or "").rsplit("/", 1)[-1])
    return int(m.group(1) or (m.group(2) if hash_ok else 0) or 0) or None if m else None


def git_keys(text):
    return {int(x) for x in GIT_KEY_RE.findall(text or "")}


class GitMatch:
    """2.390.0 (#3353): what a connection's texts name, for the lists lids: "#123" (unless the projects have a key and the
    connection's switch "Keep reading #number" is off), "APP-123" (current keys and old ones of their tasks) in commits and
    pull requests, "app-123-..." / "APP-123" in branch names, and the closing keywords before either."""

    def __init__(self, c, r, lids):
        self.c, self.lids = c, lids
        keys = r.keys() if hasattr(r, "keys") else ()
        self.hash_ok = ("hash_ids" not in keys or bool(r["hash_ids"])) or not tk_has_key(c, lids)
        pre = tk_prefixes(c, lids)
        self.rx, self.brx = tk_text_re(pre), tk_text_re(pre, branch=True)
        alt = "|".join(sorted((re.escape(p) for p in pre), key=len, reverse=True))
        self.krx = re.compile(rf"(?<![\w-])(?i:fix(?:e[sd])?|close[sd]?|resolve[sd]?|erledigt)\s*:?\s+({alt})-(\d{{1,9}})\b") if pre else None

    def _keys(self, pairs):
        return tk_find(self.c, pairs, self.lids) if pairs else set()

    def named(self, text, branch=None):
        """The live tasks of the lists that text (+ the branch name) names."""
        ids = git_ids(text) if self.hash_ok else set()
        bid = git_branch_id(branch, self.hash_ok) if branch else None
        pairs = tk_text_pairs(text, self.rx)
        if branch:
            pairs |= tk_text_pairs(str(branch).rsplit("/", 1)[-1], self.brx, branch=True)
        return git_task_ids(self.c, self.lids, ids | ({bid} if bid else set())) | self._keys(pairs)

    def closes(self, text):
        """The live tasks of the lists that text completes ("fixes #12" / "fixes APP-12")."""
        ids = git_keys(text) if self.hash_ok else set()
        pairs = {(p, int(n)) for p, n in self.krx.findall(text or "")} if self.krx else set()
        return git_task_ids(self.c, self.lids, ids) | self._keys(pairs)


def git_task_ids(c, lids, ids):
    """The ids among ids of live tasks in the lists lids (one list id or a set: 2.33.0 #934, a folder repository serves all
    project lists of its folder)."""
    ids = sorted({int(i) for i in ids if i})[:200]
    lids = sorted({lids} if isinstance(lids, int) else set(lids))
    if not ids or not lids:
        return set()
    return {r[0] for r in c.execute(f"""SELECT id FROM tasks WHERE list_id IN ({','.join('?' * len(lids))}) AND deleted_at IS NULL
                                        AND id IN ({','.join('?' * len(ids))})""", (*lids, *ids))}


def git_conn_lists(c, r):
    """2.33.0 (#934): the lists connection r serves -- its list, or for a folder repository every project list of the folder
    that uses it (not switched off, no own repository, no nearer folder repository)."""
    from ..integrations.gitfolder import gf_lists_of_conn
    lids = gf_lists_of_conn(c, r["id"])
    return {r["list_id"]} if lids is None else lids


def git_conns_of_list(c, lid):
    """2.33.0 (#934): the repositories list lid uses: its own ones, else the ones of its folder (inherited)."""
    from ..integrations.gitfolder import gf_conns_for_list, gf_own_conns
    return gf_own_conns(c, lid) or gf_conns_for_list(c, lid)


def git_public(c, r, manage=False):
    web = git_urls(r["provider"], r["base_url"])[1]
    from ..integrations.gitfolder import gf_folder
    d = {"id": r["id"], "list_id": r["list_id"], "provider": r["provider"], "base_url": r["base_url"],
         "folder": gf_folder(c, r["id"]),  # 2.33.0 (#934): a folder repository (the folder's path), None = the list's own
         "web_url": f"{web}/{r['owner']}/{r['repo']}", "owner": r["owner"], "repo": r["repo"],
         "full_name": f"{r['owner']}/{r['repo']}", "default_branch": r["default_branch"] or None,
         "status": "error" if r["last_error"] and r["last_error"] != "rate" else "ok" if r["polled_at"] else "new",
         "error": git_err_text(r["last_error"]) if r["last_error"] else "", "polled_at": r["polled_at"],
         "hash_ids": bool(r["hash_ids"]) if "hash_ids" in r.keys() else True,  # 2.390.0 (#3353)
         "author_name": r["author_name"], "author_email": r["author_email"]}  # 2.396.0 A (#3386): '' = the agent's git author
    if manage:
        d.update(token=bool(r["token"]), hook=bool(r["hook_secret"]), hook_url=f"{PUBLIC_URL.rstrip('/')}/api/hooks/git/{r['id']}")
    return d


def git_ctx(c, r):
    api = git_urls(r["provider"], r["base_url"])[0]
    return {"api": api, "provider": r["provider"], "token": git_unseal(r["id"], "token", r["token"]), "allow": cal_allow(c),
            "path": git_repo_path(r["provider"], r["owner"], r["repo"]), "low": None}


def git_http(k, path, etag=None):
    """One GET against the provider's API -> (status, headers, json or None on 304). Raises CalError / GitRate."""
    gh = k["provider"] == "github"
    hd = {"User-Agent": f"{APP_NAME}/{APP_VERSION} (git integration)",
          "Accept": "application/vnd.github+json" if gh else "application/json"}
    if gh:
        hd["X-GitHub-Api-Version"] = "2022-11-28"
    hd.update(git_auth(k["provider"], k["token"]))  # 2.18.0: per provider (GitLab PRIVATE-TOKEN, Bitbucket Basic / Bearer)
    if etag:
        hd["If-None-Match"] = etag
    req = urllib.request.Request(k["api"] + path, headers=hd, method="GET")

    def rate(h):
        if not h:
            return
        # 2.18.0: GitLab sends RateLimit-Remaining / RateLimit-Reset (no X- prefix)
        rem = h.get("X-RateLimit-Remaining") or h.get("RateLimit-Remaining")
        reset = h.get("X-RateLimit-Reset") or h.get("RateLimit-Reset")
        if rem is not None and str(rem).isdigit() and int(rem) < GIT_RATE_FLOOR:
            k["low"] = float(reset) if reset and str(reset).isdigit() else time.time() + 900
    try:
        r = _cal_opener(k["allow"]).open(req, timeout=CAL_TIMEOUT)
    except urllib.error.HTTPError as e:
        code, h = e.code, e.headers
        e.close()
        rate(h)
        if code == 304:
            return 304, h, None
        ra = (h.get("Retry-After") if h else None) or ""
        if code == 429 or (code == 403 and h and ("0" in (h.get("X-RateLimit-Remaining"), h.get("RateLimit-Remaining")) or ra)):
            reset = (h.get("X-RateLimit-Reset") or h.get("RateLimit-Reset")) if h else None
            raise GitRate(time.time() + int(ra) if ra.isdigit() else float(reset) if reset and reset.isdigit() else time.time() + 900) from None
        if code in (401, 403):
            raise CalError("auth", code) from None
        if code in (404, 410):
            raise CalError("not_found", code) from None
        if code in (301, 302, 303, 307, 308):
            raise CalError("redirect") from None
        raise CalError("http", code) from None
    except CalError:
        raise
    except urllib.error.URLError as e:
        rs = e.reason
        if isinstance(rs, CalError):
            raise rs from None
        if isinstance(rs, ssl.SSLError):
            raise CalError("tls") from None
        if isinstance(rs, (TimeoutError, socket.timeout)):
            raise CalError("timeout") from None
        raise CalError("network") from None
    except ssl.SSLError:
        raise CalError("tls") from None
    except (TimeoutError, socket.timeout):
        raise CalError("timeout") from None
    except (OSError, http.client.HTTPException, ValueError):
        raise CalError("network") from None
    try:
        with r:
            rate(r.headers)
            data = r.read(GIT_MAX_BYTES + 1)
            if len(data) > GIT_MAX_BYTES:
                raise CalError("too_large")
            return r.status, r.headers, json.loads(data.decode("utf-8") or "null")
    except CalError:
        raise
    except (ValueError, UnicodeDecodeError):
        raise CalError("parse") from None
    except (TimeoutError, socket.timeout):
        raise CalError("timeout") from None
    except (OSError, http.client.HTTPException):
        raise CalError("network") from None


def _gs(v, n=300):
    return str(v or "")[:n]


def _git_web(u):
    """A link from the provider for the web app: http(s) only."""
    u = _gs(u, 500)
    return u if u.lower().startswith(("https://", "http://")) else ""


GIT_PR_BODY_MAX = 4000  # 2.126.0 B (#1978): a pull request's text is read only for task references (was 20000)


def git_pr_of(p):
    """A pull request of either provider -> our fields (None if it does not look like one)."""
    if not isinstance(p, dict) or not isinstance(p.get("number"), int):
        return None
    merged = bool(p.get("merged_at")) or p.get("merged") is True
    head = p.get("head") if isinstance(p.get("head"), dict) else {}
    user = p.get("user") if isinstance(p.get("user"), dict) else {}
    return {"number": p["number"], "title": _gs(p.get("title"), 500), "body": str(p.get("body") or "")[:GIT_PR_BODY_MAX],
            "state": "merged" if merged else "open" if p.get("state") == "open" else "closed",
            "author": _gs(user.get("login"), 100), "url": _git_web(p.get("html_url")), "head_ref": _gs(head.get("ref"), 250),
            "head_sha": _gs(head.get("sha"), 64), "updated_at": _gs(p.get("updated_at"), 40), "merged_at": _gs(p.get("merged_at"), 40) or None,
            # 2.151.0 A (#2558): the merge (squash) commit of a merged one: its first version tag is the pull request's
            # (GitHub / Gitea send a test merge commit for open ones too: only kept once merged)
            "merge_sha": _gs(p.get("merge_commit_sha"), 64) if merged else ""}


def git_commit_of(x):
    if not isinstance(x, dict) or not isinstance(x.get("sha"), str):
        return None
    cm = x.get("commit") if isinstance(x.get("commit"), dict) else {}
    au = cm.get("author") if isinstance(cm.get("author"), dict) else {}
    co = cm.get("committer") if isinstance(cm.get("committer"), dict) else {}
    login = x.get("author").get("login") if isinstance(x.get("author"), dict) else None
    return {"sha": x["sha"][:64], "message": str(cm.get("message") or "")[:4000], "author": _gs(login or au.get("name"), 100),
            "url": _git_web(x.get("html_url")), "at": _gs(co.get("date") or au.get("date"), 40) or None}


def _gd(x, *keys):
    """Nested dict lookup of a provider answer that never trusts the shape."""
    for k_ in keys:
        x = x.get(k_) if isinstance(x, dict) else None
    return x


def git_pr_norm(p, prov):
    """2.18.0: a GitLab merge request / Bitbucket pull request in the GitHub shape git_pr_of reads (None: not one).
    GitLab: opened / locked (being merged) = open, merged, closed. Bitbucket: OPEN, MERGED, DECLINED / SUPERSEDED = closed
    (it has no merge time in the list: the last update of a merged one counts)."""
    if prov not in ("gitlab", "bitbucket") or not isinstance(p, dict):
        return p
    if prov == "gitlab":
        if not isinstance(p.get("iid"), int):
            return None
        st = p.get("state")
        return {"number": p["iid"], "title": p.get("title"), "body": p.get("description"), "merged": st == "merged",
                "state": "open" if st in ("opened", "locked") else "closed",
                "merged_at": (p.get("merged_at") or p.get("updated_at")) if st == "merged" else None,
                "user": {"login": _gd(p, "author", "username")}, "html_url": p.get("web_url"),
                "head": {"ref": p.get("source_branch"), "sha": p.get("sha")}, "updated_at": p.get("updated_at"),
                "merge_commit_sha": p.get("squash_commit_sha") or p.get("merge_commit_sha")}  # 2.151.0 A (#2558)
    if not isinstance(p.get("id"), int):
        return None
    st = str(p.get("state") or "").upper()
    return {"number": p["id"], "title": p.get("title"), "body": p.get("description"), "merged": st == "MERGED",
            "state": "open" if st == "OPEN" else "closed",
            "merged_at": (p.get("closed_on") or p.get("updated_on")) if st == "MERGED" else None,
            "user": {"login": _gd(p, "author", "nickname") or _gd(p, "author", "display_name")},
            "html_url": _gd(p, "links", "html", "href"),
            "head": {"ref": _gd(p, "source", "branch", "name"), "sha": _gd(p, "source", "commit", "hash")},
            "updated_at": p.get("updated_on"), "merge_commit_sha": _gd(p, "merge_commit", "hash")}  # 2.151.0 A (#2558)


def git_commit_norm(x, prov):
    """2.18.0: a GitLab / Bitbucket commit in the GitHub shape git_commit_of reads."""
    if prov not in ("gitlab", "bitbucket") or not isinstance(x, dict):
        return x
    if prov == "gitlab":
        return {"sha": x.get("id"), "html_url": x.get("web_url"),
                "commit": {"message": x.get("message"), "author": {"name": x.get("author_name"), "date": x.get("authored_date")},
                           "committer": {"date": x.get("committed_date")}}}
    who = _gd(x, "author", "user", "display_name") or re.sub(r"\s*<[^>]*>", "", str(_gd(x, "author", "raw") or ""))
    return {"sha": x.get("hash"), "html_url": _gd(x, "links", "html", "href"),
            "commit": {"message": x.get("message"), "author": {"name": who, "date": x.get("date")}, "committer": {"date": x.get("date")}}}


def git_api(prov, k, what, default="", ref=""):
    """2.18.0: the API path of one poll request per provider (what: pulls | commits | compare | tags)."""
    p, e = k["path"], (lambda s: urllib.parse.quote(s, safe=""))
    gh = prov == "github"
    if what == "pulls":
        return {"gitlab": f"{p}/merge_requests?state=all&order_by=updated_at&sort=desc&per_page={GIT_ITEMS}",
                "bitbucket": f"{p}/pullrequests?state=OPEN&state=MERGED&state=DECLINED&state=SUPERSEDED&sort=-updated_on&pagelen={GIT_ITEMS}"
                }.get(prov) or f"{p}/pulls?state=all&" + (f"sort=updated&direction=desc&per_page={GIT_ITEMS}" if gh else f"sort=recentupdate&limit={GIT_ITEMS}")
    if what == "commits":
        return {"gitlab": f"{p}/repository/commits?ref_name={e(default)}&per_page={GIT_ITEMS}",
                "bitbucket": f"{p}/commits/{e(default)}?pagelen={GIT_ITEMS}"}.get(prov) or \
            f"{p}/commits?sha={urllib.parse.quote(default)}&" + (f"per_page={GIT_ITEMS}" if gh else f"limit={GIT_ITEMS}&stat=false&verification=false&files=false")
    if what == "compare":
        return {"gitlab": f"{p}/repository/compare?from={e(default)}&to={e(ref)}",
                "bitbucket": f"{p}/commits/{e(ref)}?exclude={e(default)}&pagelen={GIT_ITEMS}"}.get(prov) or f"{p}/compare/{e(default)}...{e(ref)}"
    return {"gitlab": f"{p}/repository/tags?order_by=updated&sort=desc&per_page={GIT_ITEMS}",
            "bitbucket": f"{p}/refs/tags?sort=-target.date&pagelen={GIT_ITEMS}"}.get(prov) or \
        f"{p}/tags?" + (f"per_page={GIT_ITEMS}" if gh else f"limit={GIT_ITEMS}")


def git_tag_url(r, name):
    web = f"{git_urls(r['provider'], r['base_url'])[1]}/{r['owner']}/{r['repo']}"
    q = urllib.parse.quote(name, safe="")
    return {"gitlab": f"{web}/-/tags/{q}", "bitbucket": f"{web}/src/{q}"}.get(r["provider"]) or f"{web}/releases/tag/{q}"


GIT_TOK_RE = re.compile(r"[^\s,;:()\[\]{}\"'“”„«»<>]+")


def git_version(s):
    """A version token without a leading v / V, case-folded; '' unless it starts with a digit (never fuzzy)."""
    s = str(s or "").strip().rstrip(".!?")
    s = s[1:] if s[:1] in ("v", "V") else s
    return s.casefold() if s[:1].isdigit() else ""


def git_take_tags(c, r, items):
    """2.18.0 (#408 "Software 2" B): the newest tags. The first read after connecting (tags_at NULL) only records them
    (baseline); a tag seen later whose name (without a leading v) equals a version token in the title of an OPEN milestone
    task (ms = 1) of the connected list completes that milestone once (git_closes, activity names repo + tag, Undo)."""
    names = []
    for x in items[:GIT_ITEMS]:
        n = _gs(x.get("name"), 200).strip() if isinstance(x, dict) else ""
        if n and n not in names:
            names.append(n)
    ts = iso(now_utc())
    if not r["tags_at"]:
        c.executemany("INSERT INTO git_tags(conn_id,name,seen_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", [(r["id"], n, ts) for n in names])
        c.execute("UPDATE git_conns SET tags_at=? WHERE id=?", (ts, r["id"]))
        return False
    new = [n for n in names if c.execute("INSERT INTO git_tags(conn_id,name,seen_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (r["id"], n, ts)).rowcount]
    if not new:
        return False
    c.execute("""DELETE FROM git_tags WHERE conn_id=? AND name NOT IN
                 (SELECT name FROM git_tags WHERE conn_id=? ORDER BY seen_at DESC, name DESC LIMIT ?)""", (r["id"], r["id"], GIT_TAGS_KEEP))
    changed = False
    lids = sorted(git_conn_lists(c, r))  # 2.33.0 (#934): a folder repository: the milestones of all its lists
    ms = c.execute(f"SELECT id, title FROM tasks WHERE list_id IN ({','.join('?' * len(lids))}) AND ms=1 AND status=0 AND deleted_at IS NULL ORDER BY id",
                   lids).fetchall() if lids else []
    for n in new:
        v = git_version(n)
        if not v:
            continue
        for t in ms:
            if v in {git_version(x) for x in GIT_TOK_RE.findall(t["title"] or "")}:
                changed |= git_close(c, r, t["id"], "tag", n, n, git_tag_url(r, n), set(lids))
    return changed


def _git_after(ts, since):
    try:
        return bool(ts) and parse_iso(ts) > parse_iso(since)
    except (ValueError, TypeError):
        return False


def git_close(c, r, tid, kind, ref, title, url, lids=None):
    """A keyword in a merged pull request / a default-branch commit: completes task tid once (git_closes)."""
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["deleted_at"] or t["status"] != 0 or t["list_id"] not in (lids if lids is not None else {r["list_id"]}) or \
            c.execute("SELECT 1 FROM git_closes WHERE task_id=?", (tid,)).fetchone():
        return False
    from ..tasks.review import rvw_gate
    if rvw_gate(c, tid):  # 2.60.0 C (#1512): waits for its review approval; a later poll completes it once approved
        return False
    undo = {}
    with app.app_context():
        g.user = {"id": None}
        nxt = do_complete(c, tid, 2, undo)
    c.execute("INSERT INTO git_closes(task_id,conn_id,kind,ref,undo,created_at) VALUES(?,?,?,?,?,?)",
              (tid, r["id"], kind, ref, json.dumps(undo), iso(now_utc())))
    log_act(c, tid, "git_done", {"repo": f"{r['owner']}/{r['repo']}", "kind": kind, "ref": ref, "title": title[:200], "url": url,
                                 **({"next": nxt} if nxt else {})}, uid=None)
    return True


def git_take_prs(c, r, items, baseline):
    changed = False
    lid, repo = git_conn_lists(c, r), f"{r['owner']}/{r['repo']}"
    gm = GitMatch(c, r, lid)
    for raw in (items or [])[:GIT_ITEMS]:
        p = git_pr_of(raw)
        if not p:
            continue
        n = str(p["number"])
        tids = gm.named(p["title"] + "\n" + p["body"], p["head_ref"])  # 2.390.0 (#3353): + APP-123
        tids |= {x[0] for x in c.execute("SELECT task_id FROM git_links WHERE conn_id=? AND kind='pr' AND ref=?", (r["id"], n))}
        if not tids:
            continue
        old = c.execute("SELECT * FROM git_prs WHERE conn_id=? AND number=?", (r["id"], p["number"])).fetchone()
        if not old or any(old[k] != p[k] for k in ("title", "state", "author", "url", "head_ref", "head_sha", "merged_at", "merge_sha")):
            changed = True
        c.execute("""INSERT INTO git_prs(conn_id,number,title,state,author,url,head_ref,head_sha,updated_at,merged_at,merge_sha)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(conn_id,number) DO UPDATE SET title=excluded.title, state=excluded.state,
                     author=excluded.author, url=excluded.url, head_ref=excluded.head_ref, head_sha=excluded.head_sha,
                     updated_at=excluded.updated_at, merged_at=excluded.merged_at,
                     merge_sha=CASE WHEN excluded.merge_sha<>'' THEN excluded.merge_sha ELSE git_prs.merge_sha END""",
                  (r["id"], p["number"], p["title"], p["state"], p["author"], p["url"], p["head_ref"], p["head_sha"], p["updated_at"], p["merged_at"],
                   p["merge_sha"]))
        fresh = old is None or not old["title"]  # a stub row from a merge request comment counts as new
        for tid in sorted(tids):
            new = c.execute("INSERT INTO git_links(task_id,conn_id,kind,ref,created_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                            (tid, r["id"], "pr", n, iso(now_utc()))).rowcount
            if baseline:
                continue
            if new or fresh:
                log_act(c, tid, "git_pr", {"repo": repo, "n": p["number"], "title": p["title"][:200], "url": p["url"],
                                           "state": "opened" if p["state"] == "open" else p["state"]}, uid=None)
                changed = True
            elif old["state"] != p["state"] and p["state"] in ("merged", "closed"):
                log_act(c, tid, "git_pr", {"repo": repo, "n": p["number"], "title": p["title"][:200], "url": p["url"], "state": p["state"]}, uid=None)
        if p["state"] == "merged" and not baseline and (old is None or old["state"] != "merged"):  # 2.60.0 C (#1512): merged = approved
            from ..tasks.review import rvw_approved_by_pr
            for tid in sorted(tids):
                changed |= rvw_approved_by_pr(c, tid, f"{repo}#{n} {p['title']}", p["url"])
        if p["state"] == "merged" and _git_after(p["merged_at"], r["created_at"]):
            for tid in sorted(gm.closes(p["title"] + "\n" + p["body"])):
                changed |= git_close(c, r, tid, "pr", n, f"#{n} {p['title']}", p["url"], lid)
    return changed


def git_take_commits(c, r, items, branch, default):
    changed = False
    lid = git_conn_lists(c, r)
    gm = GitMatch(c, r, lid)  # 2.390.0 (#3353): + APP-123, "#123" only with the switch when the projects have a key
    for raw in (items or [])[:GIT_ITEMS]:
        m = git_commit_of(raw)
        if not m:
            continue
        tids = gm.named(m["message"], None if default else branch)
        if not tids:
            continue
        first = m["message"].split("\n", 1)[0][:300]
        c.execute("""INSERT INTO git_commits(conn_id,sha,message,author,url,branch,at) VALUES(?,?,?,?,?,?,?)
                     ON CONFLICT(conn_id,sha) DO UPDATE SET branch=CASE WHEN ? THEN excluded.branch ELSE git_commits.branch END""",
                  (r["id"], m["sha"], first, m["author"], m["url"], branch, m["at"], 1 if default else 0))
        for tid in sorted(tids):
            changed |= bool(c.execute("INSERT INTO git_links(task_id,conn_id,kind,ref,created_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                                      (tid, r["id"], "commit", m["sha"], iso(now_utc()))).rowcount)
        if default and _git_after(m["at"], r["created_at"]):
            for tid in sorted(gm.closes(m["message"])):
                changed |= git_close(c, r, tid, "commit", m["sha"], first, m["url"], lid)
    return changed


def git_ci_of(k, sha, gh):
    """Combined status (+ check runs on GitHub) of a commit -> success | failure | pending | ''."""
    states = []
    if k["provider"] == "gitlab":  # 2.18.0: the latest commit statuses (pipeline jobs and external ones)
        _, _, j = git_http(k, f"{k['path']}/repository/commits/{urllib.parse.quote(sha, safe='')}/statuses?per_page=100")
        for s in j if isinstance(j, list) else []:
            st = s.get("status") if isinstance(s, dict) else None
            states.append("success" if st == "success" else "failure" if st in ("failed", "canceled") else
                          "pending" if st in ("running", "pending", "created", "preparing", "waiting_for_resource", "scheduled") else "")
        states = [s for s in states if s]
        return "failure" if "failure" in states else "pending" if "pending" in states else "success" if states else ""
    if k["provider"] == "bitbucket":  # 2.18.0: commit statuses SUCCESSFUL / FAILED / STOPPED / INPROGRESS
        _, _, j = git_http(k, f"{k['path']}/commit/{urllib.parse.quote(sha, safe='')}/statuses?pagelen=100")
        for s in git_items(j) or []:
            st = str(s.get("state") or "").upper() if isinstance(s, dict) else ""
            states.append("success" if st == "SUCCESSFUL" else "failure" if st in ("FAILED", "STOPPED") else "pending" if st == "INPROGRESS" else "")
        states = [s for s in states if s]
        return "failure" if "failure" in states else "pending" if "pending" in states else "success" if states else ""
    _, _, j = git_http(k, f"{k['path']}/commits/{urllib.parse.quote(sha)}/status")
    if isinstance(j, dict) and (j.get("total_count") or (j.get("statuses") or [])):
        s = str(j.get("state") or "")
        states.append("success" if s == "success" else "pending" if s == "pending" else "failure" if s else "")
    if gh:
        _, _, j = git_http(k, f"{k['path']}/commits/{urllib.parse.quote(sha)}/check-runs?per_page=50")
        for cr in (j or {}).get("check_runs") or [] if isinstance(j, dict) else []:
            if not isinstance(cr, dict):
                continue
            if cr.get("status") != "completed":
                states.append("pending")
            else:
                states.append("success" if cr.get("conclusion") in ("success", "neutral", "skipped") else "failure")
    states = [s for s in states if s]
    return "failure" if "failure" in states else "pending" if "pending" in states else "success" if states else ""


def git_poll(c, cid):
    """One poll of connection cid (the background thread). Never raises for provider problems (stored in last_error)."""
    from ..integrations.gitfolder import gf_rehome
    from ..integrations.gitbuild import gb_branches, gb_main, gb_released, gb_tags
    gf_rehome(c, cid)  # 2.33.0 (#934): a folder repository hangs on a list that is still in its folder
    r = c.execute("SELECT k.*, l.archived FROM git_conns k JOIN lists l ON l.id=k.list_id WHERE k.id=?", (cid,)).fetchone()
    if not r:
        return
    now = time.time()
    if r["archived"]:
        c.execute("UPDATE git_conns SET next_at=? WHERE id=?", (now + GIT_POLL_S * 4, cid))
        c.commit()
        return
    k, gh = git_ctx(c, r), r["provider"] == "github"
    etags = json.loads(r["etags"] or "{}")
    keep = dict(etags)
    # 2.13.4 (p220 flake, a real bug): a poll still running while someone saves the connection (a new token: git_update
    # resets etags / fails / next_at) must not write its result over that reset afterwards, or the fixed connection keeps
    # showing the old 401 and waits out the backoff. Its state is written only while the row still holds the token and
    # ETags it read (the sealed token has a random nonce: every save changes it).
    same, same_args = "id=? AND token IS NOT DISTINCT FROM ? AND etags IS NOT DISTINCT FROM ?", (cid, r["token"], r["etags"])
    baseline, changed = r["polled_at"] is None, False

    def get(key, path):
        st, h, j = git_http(k, path, etags.get(key))
        et = h.get("ETag") if h else None
        if st == 200 and et:
            keep[key] = et
        if k["low"]:
            raise GitRate(k["low"])
        return j if st == 200 else None
    # 2.151.0 A2 (#2558 review): an unchanged answer (304) holds nothing; gb_released asks again without ETag
    get.forget = lambda key: (etags.pop(key, None), keep.pop(key, None))
    try:
        default = r["default_branch"]
        if not default:
            j = get("repo", k["path"])
            default = git_default_of(j)
            default = _gs(default, 250) or "main"
            c.execute("UPDATE git_conns SET default_branch=? WHERE id=?", (default, cid))
            r = c.execute("SELECT k.*, l.archived FROM git_conns k JOIN lists l ON l.id=k.list_id WHERE k.id=?", (cid,)).fetchone()
        prov = r["provider"]  # 2.18.0: paths + answers per provider (git_api, git_items, git_*_norm)
        j = git_items(get("pulls", git_api(prov, k, "pulls")))
        if j is not None:
            changed |= git_take_prs(c, r, [git_pr_norm(x, prov) for x in j], baseline)
        j = git_items(get("commits", git_api(prov, k, "commits", default)))
        if j is not None:
            changed |= git_take_commits(c, r, [git_commit_norm(x, prov) for x in j], default, True)
            if j:
                gb_main(c, r, git_commit_norm(j[0], prov))  # 2.151.0 A (#2558)
        # 2.18.0 (#408): the newest tags (one request, ETag): a new one can reach a milestone
        try:  # optional: a server without the tags endpoint (or a token without access to it) never breaks the poll
            j = git_items(get("tags", git_api(prov, k, "tags")))
        except CalError:
            j = None
        if j is not None:
            changed |= git_take_tags(c, r, j)
        if r["tags_at"]:  # 2.151.0 A (#2558): the first version tag of the linked commits (after the baseline)
            changed |= gb_tags(c, r, k, prov)
            changed |= gb_released(c, r, k, get, prov)  # 2.151.0 A2 (#2558 review): untagged commits in an earlier version
        # branches of open pull requests that name a task: their own commits (compare with the default branch)
        refs = [x[0] for x in c.execute("""SELECT p.head_ref FROM git_prs p WHERE p.conn_id=? AND p.state='open' AND p.head_ref!=''
                                           AND p.head_ref!=? GROUP BY p.head_ref ORDER BY MAX(p.updated_at) DESC""", (cid, default))][:GIT_BRANCHES]
        for ref in refs:
            j = get("cmp:" + ref, git_api(prov, k, "compare", default, ref))
            # GitHub / Gitea / GitLab: {commits: [oldest .. newest]}; Bitbucket: a page of the branch's own commits, newest first
            lst = j["commits"] if isinstance(j, dict) and isinstance(j.get("commits"), list) else \
                list(reversed(git_items(j))) if prov == "bitbucket" and git_items(j) is not None else None
            if lst is not None:
                changed |= git_take_commits(c, r, [git_commit_norm(x, prov) for x in lst[-GIT_ITEMS:]], ref, False)
        keep = {x: v for x, v in keep.items() if not x.startswith("cmp:") or x[4:] in refs}
        changed |= gb_branches(c, r, k, get, prov)  # 2.151.0 A (#2558): task branches and how far ahead they are
        # CI of open pull requests (unknown, pending or a new head)
        for p in c.execute("""SELECT number, head_sha, ci, ci_sha FROM git_prs WHERE conn_id=? AND state='open' AND head_sha!=''
                              AND (ci_sha!=head_sha OR ci IN ('pending','')) ORDER BY updated_at DESC LIMIT ?""", (cid, GIT_CI)).fetchall():
            ci = git_ci_of(k, p["head_sha"], gh)
            if k["low"]:
                raise GitRate(k["low"])
            if ci != p["ci"] or p["ci_sha"] != p["head_sha"]:
                changed |= ci != p["ci"]
                c.execute("UPDATE git_prs SET ci=?, ci_sha=? WHERE conn_id=? AND number=?", (ci, p["head_sha"], cid, p["number"]))
        c.execute(f"UPDATE git_conns SET etags=?, polled_at=?, fails=0, last_error='', next_at=? WHERE {same}",
                  (json.dumps(keep), iso(now_utc()), time.time() + GIT_POLL_S, *same_args))
    except GitRate as e:
        c.execute(f"UPDATE git_conns SET etags=?, last_error='rate', next_at=? WHERE {same}",
                  (json.dumps(keep), max(e.until + 5, time.time() + 30), *same_args))
    except CalError as e:
        fails = (r["fails"] or 0) + 1
        c.execute(f"UPDATE git_conns SET etags=?, fails=?, last_error=?, next_at=? WHERE {same}",
                  (json.dumps(keep), fails, e.stored(), time.time() + min(GIT_POLL_S * 2 ** min(fails, 5), GIT_BACKOFF_MAX), *same_args))
    if changed:
        bump(c)
    c.commit()


def git_loop():
    while True:
        _GIT_WAKE.wait(GIT_TICK_S)
        _GIT_WAKE.clear()
        try:
            c = connect()
            try:
                rows = c.execute("""SELECT k.id FROM git_conns k JOIN lists l ON l.id=k.list_id WHERE k.next_at<=?
                                    ORDER BY k.next_at LIMIT ?""", (time.time(), GIT_PER_TICK)).fetchall()
                for (cid,) in rows:
                    with GATE.bg():
                        git_poll(c, cid)
            finally:
                c.close()
        except Exception as e:  # noqa: BLE001
            print("git loop error:", type(e).__name__, e, flush=True)
            aa_count("watchdog", f"git|{type(e).__name__}", "git")


def git_wake(c, cid):
    c.execute("UPDATE git_conns SET next_at=0 WHERE id=?", (cid,))
    _GIT_WAKE.set()


# ---- what a task / list shows
def git_code_for(c, ids):
    """{task id: {prs: [...], commits: [...]}} for the tasks in ids that have linked pull requests / commits."""
    ids = set(ids)
    if not ids or not c.execute("SELECT 1 FROM git_links LIMIT 1").fetchone():
        return {}
    out = {}
    for x in c.execute("""SELECT l.task_id, p.*, k.owner, k.repo, k.provider FROM git_links l JOIN git_conns k ON k.id=l.conn_id
                          JOIN git_prs p ON p.conn_id=l.conn_id AND CAST(p.number AS TEXT)=l.ref WHERE l.kind='pr'
                          ORDER BY p.state!='open', p.updated_at DESC, p.number DESC"""):
        if x["task_id"] in ids:
            lst = out.setdefault(x["task_id"], {"prs": [], "commits": []})["prs"]
            if len(lst) < GIT_TASK_PRS:
                lst.append({"repo": f"{x['owner']}/{x['repo']}", "conn": x["conn_id"], "n": x["number"], "title": x["title"],
                            "state": x["state"], "ci": x["ci"] or None, "author": x["author"], "url": x["url"], "branch": x["head_ref"],
                            "merged_at": x["merged_at"], "tag": git_tag_out(x["tag"])})  # 2.151.0 A (#2558): its first version tag
    for x in c.execute("""SELECT l.task_id, m.*, k.owner, k.repo FROM git_links l JOIN git_conns k ON k.id=l.conn_id
                          JOIN git_commits m ON m.conn_id=l.conn_id AND m.sha=l.ref WHERE l.kind='commit' ORDER BY m.at DESC"""):
        if x["task_id"] in ids:
            lst = out.setdefault(x["task_id"], {"prs": [], "commits": []})["commits"]
            if len(lst) < GIT_TASK_COMMITS:
                lst.append({"repo": f"{x['owner']}/{x['repo']}", "sha": x["sha"], "short": x["sha"][:7], "message": x["message"],
                            "author": x["author"], "url": x["url"], "branch": x["branch"], "at": x["at"],
                            "tag": git_tag_out(x["tag"])})  # 2.151.0 A (#2558): the first version tag that holds it
    return out


def git_tag_out(t):
    """2.151.0 A2 (#2558 review): a stored tag for the API; '~' (in an earlier version, which one unknown) is null."""
    return t if t and t != "~" else None


def git_repos_of_lists(c, ids):
    out = {}
    if not ids:
        return out
    from ..integrations.gitfolder import gf_conns_of_lists
    conns, pub = gf_conns_of_lists(c, ids), {}  # 2.280.0 B (#3116): all lists at once (was: git_conns_of_list per list)
    for lid in ids:  # 2.33.0 (#934): own repositories, else the folder's
        for r in conns.get(lid, ()):
            d = pub.get(r["id"]) or pub.setdefault(r["id"], git_public(c, r))  # a folder repository: once, not per list
            out.setdefault(lid, []).append({k: d[k] for k in ("id", "provider", "full_name", "web_url", "default_branch", "status", "folder",
                                                              "author_name", "author_email")})  # 2.396.0 A (#3386)
    return out


def git_author_of(c, r, aid=None):
    """2.396.0 A (#3386): the git author agent aid commits with in repository r: the project's override per part, else the
    agent's runtime git_author_name / _email, else the neutral default. (author "Name <mail>", co-author flag, source)."""
    a = agent_row(c, aid) if aid else None
    rt = agent_runtime(a) if a else {}
    name, email = r["author_name"] or rt.get("git_author_name"), r["author_email"] or rt.get("git_author_email")
    src = "project" if r["author_name"] or r["author_email"] else "agent" if a else "default"
    return git_author_str(name, email), bool(rt.get("git_coauthor")), src


def git_repo_for_task(c, t, aid=None):
    """data.repo of an agent's task event / get_task: the list's first repository + branch suggestion + linked code.
    aid (2.396.0 A, #3386): the agent it goes to (None = the caller when it is an agent) for its git author."""
    rows = git_conns_of_list(c, t["list_id"])  # 2.33.0 (#934): also a folder repository
    if not rows:
        return None
    first = git_public(c, rows[0])
    code = git_code_for(c, [t["id"]]).get(t["id"], {"prs": [], "commits": []})
    d = {k: first[k] for k in ("provider", "base_url", "web_url", "owner", "repo", "full_name", "default_branch")}
    if aid is None and has_request_context() and is_agent(getattr(g, "user", None)):
        aid = me()
    d["git_author"], d["git_coauthor"], d["git_author_source"] = git_author_of(c, rows[0], aid)  # 2.396.0 A (#3386)
    # 2.126.0 B (#1978): titles and commit messages are written by anyone with access to the repository
    d.update(api_url=git_urls(rows[0]["provider"], rows[0]["base_url"])[0], branch=f"kalmido-{t['id']}",
             prs=[{**x, "origin": "git", "untrusted": True} for x in code["prs"]],
             commits=[{**x, "origin": "git", "untrusted": True} for x in code["commits"]])
    if len(rows) > 1:
        d["others"] = [{k: x[k] for k in ("provider", "web_url", "full_name", "default_branch")} for x in (git_public(c, y) for y in rows[1:])]
    from ..integrations.gitbuild import gb_untrusted, git_build_for
    b = git_build_for(c, [t]).get(t["id"])  # 2.151.0 A (#2558): what was built for it and whether it is live
    if b:
        d["build"] = gb_untrusted(b)
    return d


# ---- #339 merge requests of agents (comments.suggestion kind merge_request)
def git_parse_pr_url(c, lid, url):
    """(connection row, number) of a pull request URL of a repository connected to list lid, else None."""
    u = str(url or "").strip()
    if len(u) > 500:
        return None
    for r in git_conns_of_list(c, lid):  # 2.33.0 (#934): also a folder repository
        web = git_urls(r["provider"], r["base_url"])[1]
        # 2.18.0: GitLab .../-/merge_requests/<n>, Bitbucket .../pull-requests/<n>
        tail = {"gitlab": r"/-/merge_requests/(\d{1,9})", "bitbucket": r"/pull-requests/(\d{1,9})"}.get(r["provider"], r"/pulls?/(\d{1,9})")
        m = re.fullmatch(re.escape(f"{web}/{r['owner']}/{r['repo']}") + tail + r"(?:/[A-Za-z]*)?/?(?:[#?].*)?", u, re.I)
        if m:
            return r, int(m.group(1))
    return None


def git_merge_request(c, t, s):
    unknown = sorted(k for k in s if k not in ("kind", "pr_url", "summary"))
    if unknown:
        raise UnknownFields(unknown)
    hit = git_parse_pr_url(c, t["list_id"], s.get("pr_url"))
    if not hit:
        raise BadInput(tr("The pull request is not in a repository connected to this project"))
    summary = s.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise BadInput(tr("Invalid value: {0}", "summary"))
    r, n = hit
    return {"kind": "merge_request", "pr_url": s["pr_url"].strip(), "repo": f"{r['owner']}/{r['repo']}", "conn": r["id"], "number": n,
            "summary": (summary or "").strip()[:2000], "state": "open"}


def git_merge_link(c, t, sug):
    """After a merge request comment: link the pull request to the task at once (stub until the next poll) + poll soon."""
    c.execute("INSERT INTO git_prs(conn_id,number,title,state,url) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
              (sug["conn"], sug["number"], "", "open", sug["pr_url"]))
    c.execute("INSERT INTO git_links(task_id,conn_id,kind,ref,created_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
              (t["id"], sug["conn"], "pr", str(sug["number"]), iso(now_utc())))
    git_wake(c, sug["conn"])


# ---- endpoints (web app)
def git_need_manage(c, lid):
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot connect repositories"))
    need_list(c, lid, write=False, manage=True)


@app.get("/api/lists/<int:lid>/repos")
def git_list(lid):
    from ..integrations.errorreports import errhook_public
    c = db()
    role = need_list(c, lid, write=False)
    manage = role in MANAGE_ROLES and not is_agent(g.user)
    from ..integrations.gitfolder import gf_conns_for_list, gf_own_conns, gf_list_state
    rows = gf_own_conns(c, lid)
    # 2.33.0 (#934): the folder's repositories this list uses (or would use: switched off / an own repository), read-only here
    from ..integrations.gitbuild import gb_ver_info
    return jsonify(repos=[git_public(c, r, manage) for r in rows], may=manage, key=bool(SECRET_KEY),
                   version_field=gb_ver_info(c, lid),  # 2.151.0 A (#2558): the field with the package / target version
                   project=is_project(c, lid), max=GIT_MAX_CONNS, errors=errhook_public(c, lid, manage),  # 2.18.0: error reports
                   folder=gf_list_state(c, lid), folder_repos=[git_public(c, r) for r in gf_conns_for_list(c, lid, ignore_own=True, ignore_off=True)])


def git_clean_input(b):
    # 2.18.0 (#408): GitLab + Bitbucket Cloud; the provider of an address on github.com / gitlab.com / bitbucket.org is
    # detected when the client sends none (other hosts: the provider select, default github as before); GitLab owners
    # may be nested groups (group/sub/repo; a web address may end in /-/...)
    provider = str(b.get("provider") or "").strip().lower()
    if provider and provider not in GIT_PROVIDERS:
        raise BadInput(tr("Invalid value: {0}", "provider"))
    base = str(b.get("base_url") or "").strip()
    name = str(b.get("repo") or "").strip()
    owner = str(b.get("owner") or "").strip()
    if "://" in name:  # a whole address: https://github.com/owner/repo(.git)
        p = urllib.parse.urlsplit(name)
        cloud = GIT_HOSTS.get((p.hostname or "").lower())
        provider = provider or cloud or "github"
        parts = [x for x in p.path.split("/") if x]
        if provider == "bitbucket" and "projects" in parts and "repos" in parts:
            raise BadInput(tr("Bitbucket Server / Data Center is not supported: connect a Bitbucket Cloud repository"))
        if provider == "gitlab" and "-" in parts:
            parts = parts[:parts.index("-")]
        if cloud == provider:  # github.com/o/r/tree/..., bitbucket.org/ws/r/src/...: the first two; gitlab.com: the path
            rel = parts if provider == "gitlab" else parts[:2]
        elif base:
            bp = [x for x in urllib.parse.urlsplit(base).path.split("/") if x]
            rel = parts[len(bp):] if bp and parts[:len(bp)] == bp else parts
        elif provider == "gitlab":
            base, rel = f"{p.scheme}://{p.netloc}", parts
        else:
            base = f"{p.scheme}://{p.netloc}" + ("/" + "/".join(parts[:-2]) if len(parts) > 2 else "")
            rel = parts[-2:]
        if len(rel) < 2:
            raise BadInput(tr("Invalid value: {0}", "repo"))
        owner, name = ("/".join(rel[:-1]), rel[-1]) if provider == "gitlab" else (rel[-2], rel[-1])
    elif "/" in name and not owner:
        owner, name = name.rsplit("/", 1) if provider == "gitlab" else name.split("/", 1)
    provider = provider or "github"
    if name.endswith(".git"):
        name = name[:-4]
    if not git_owner_ok(provider, owner) or not GIT_NAME_RE.fullmatch(name or "") or name in (".", ".."):
        raise BadInput(tr("Enter the repository as owner/name"))
    if base:
        base = git_norm_base_url(base)
        if not base or urllib.parse.urlsplit(base).path.rstrip("/").endswith(GIT_API_SUFFIX):
            raise BadInput(tr("Invalid value: {0}", "base_url"))
        if GIT_HOSTS.get((urllib.parse.urlsplit(base).hostname or "").lower()) == provider:
            base = ""  # the cloud service itself
    elif provider == "gitea":
        raise BadInput(tr("Enter the address of the Gitea / Forgejo server"))
    token = b.get("token")
    if token is not None and (not isinstance(token, str) or len(token) > GIT_TOKEN_MAX or any(ch.isspace() for ch in token.strip())):
        raise BadInput(tr("Invalid value: {0}", "token"))
    return provider, base, owner, name, (token or "").strip()


def git_repo_name_of(provider, j, owner, name):
    """(owner, name, default branch) as the provider spells them in its repository answer."""
    if provider == "gitlab":
        pwn = j.get("path_with_namespace")
        if isinstance(pwn, str) and "/" in pwn:
            owner, name = pwn.rsplit("/", 1)
    elif provider == "bitbucket":
        fn = j.get("full_name")
        if isinstance(fn, str) and "/" in fn:
            owner, name = fn.split("/", 1)
    else:
        owner = _gs(_gd(j, "owner", "login"), 100) or owner
        name = _gs(j.get("name"), 100) or name
    return _gs(owner, 300), _gs(name, 100), _gs(git_default_of(j), 250)


@app.post("/api/lists/<int:lid>/repos")
def git_add(lid):
    """{provider: github|gitea|gitlab|bitbucket, base_url?, repo: "owner/name" or its address, token?} -- the list owner / a list admin."""
    c = db()
    git_need_manage(c, lid)
    if not is_project(c, lid):
        return err(tr("The basket has no project functions"), 409)
    b = body()
    try:
        provider, base, owner, name, token = git_clean_input(b)
    except BadInput as e:
        return err(str(e))
    if token and not SECRET_KEY:
        return err(git_key_error(), 409)
    from ..integrations.gitfolder import gf_own_conns
    own = gf_own_conns(c, lid)  # 2.33.0 (#934): a folder repository hanging on this list does not count
    if len(own) >= GIT_MAX_CONNS:
        return err(tr("At most {0} repositories per project", GIT_MAX_CONNS), 409)
    if any((x["provider"], x["base_url"], x["owner"].lower(), x["repo"].lower()) == (provider, base, owner.lower(), name.lower()) for x in own):
        return err(tr("This repository is already connected"), 409)
    return git_connect(c, lid, provider, base, owner, name, token)


def git_connect(c, lid, provider, base, owner, name, token, folder=None):
    """Checks the repository with the token (nothing is stored on an error) and stores the connection on list lid; folder
    (2.33.0 #934): a folder repository (lid = one of the folder's lists, it serves all of them)."""
    if not cal_rate(me()):
        return err(tr("Too many attempts, please wait a few minutes"), 429)
    # check it at once (read the repository with the token): errors show in the dialog, nothing is stored
    k = {"api": git_urls(provider, base)[0], "provider": provider, "token": token, "allow": cal_allow(c), "low": None,
         "path": git_repo_path(provider, owner, name)}
    try:
        _, _, j = git_http(k, k["path"])
    except GitRate:
        return err(tr(GIT_ERR["rate"]), 409)
    except CalError as e:
        return err(git_err_text(e.stored()), 409 if e.code in ("auth", "not_found") else 502)
    if not isinstance(j, dict):
        return err(tr(GIT_ERR["parse"]), 502)
    owner, name, dflt = git_repo_name_of(provider, j, owner, name)
    if not git_owner_ok(provider, owner) or not GIT_NAME_RE.fullmatch(name):
        return err(tr(GIT_ERR["parse"]), 502)
    # 2.390.0 (#3353): a new connection reads "#123" only while its projects have no key (hash_ids 0; older ones keep 1)
    cid = insert_id(c, """INSERT INTO git_conns(list_id,provider,base_url,owner,repo,default_branch,created_by,created_at,next_at,hash_ids)
                       VALUES(?,?,?,?,?,?,?,?,0,0)""", (lid, provider, base, owner, name, dflt,
                                                         me(), iso(now_utc())))
    if folder:
        c.execute("INSERT INTO git_folders(conn_id,owner_id,folder,created_at) VALUES(?,?,?,?)", (cid, me(), folder, iso(now_utc())))
    if token:
        c.execute("UPDATE git_conns SET token=? WHERE id=?", (git_seal(cid, "token", token), cid))
    bump(c)
    c.commit()
    _GIT_WAKE.set()
    return jsonify(git_public(c, c.execute("SELECT * FROM git_conns WHERE id=?", (cid,)).fetchone(), True)), 201


def git_need_conn(c, cid, manage=True):
    r = c.execute("SELECT * FROM git_conns WHERE id=?", (cid,)).fetchone()
    if not r:
        raise Denied(404)
    from ..integrations.gitfolder import gf_need_conn
    if gf_need_conn(c, r, manage):  # 2.33.0 (#934): a folder repository: its folder's owner manages it
        return r
    if manage:
        if not list_role(c, r["list_id"]):
            raise Denied(404)
        git_need_manage(c, r["list_id"])
    else:
        need_list(c, r["list_id"], write=False)
    return r


@app.patch("/api/repos/<int:cid>")
def git_update(cid):
    """{token?: "..." | "" (remove), hook?: "on" (new secret, shown once) | "off", hash_ids?: true | false (2.390.0, #3353:
    a project with a key still reads "#123"), author_name?, author_email? (2.396.0 A, #3386: the git author for AI commits
    in this repository, '' = the agent's)}"""
    c = db()
    r = git_need_conn(c, cid)
    b = body()
    out = {}
    if "author_name" in b or "author_email" in b:  # 2.396.0 A (#3386)
        try:
            an, am = git_author_clean(b.get("author_name", r["author_name"]), b.get("author_email", r["author_email"]))
        except BadInput as e:
            return err(str(e))
        c.execute("UPDATE git_conns SET author_name=?, author_email=? WHERE id=?", (an, am, cid))
    if "token" in b:
        t = b["token"]
        if t is not None and (not isinstance(t, str) or len(t) > GIT_TOKEN_MAX or any(ch.isspace() for ch in t.strip())):
            return err(tr("Invalid value: {0}", "token"))
        t = (t or "").strip()
        if t and not SECRET_KEY:
            return err(git_key_error(), 409)
        c.execute("UPDATE git_conns SET token=?, etags='{}', fails=0, last_error='', next_at=0 WHERE id=?",
                  (git_seal(cid, "token", t) if t else "", cid))
    if "hash_ids" in b:  # 2.390.0 (#3353)
        if b["hash_ids"] not in (True, False, 0, 1) or isinstance(b["hash_ids"], float):
            return err(tr("Invalid value: {0}", "hash_ids"))
        c.execute("UPDATE git_conns SET hash_ids=? WHERE id=?", (1 if b["hash_ids"] else 0, cid))
    if "hook" in b:
        if b["hook"] not in ("on", "off"):
            return err(tr("Invalid value: {0}", "hook"))
        if b["hook"] == "on":
            if not SECRET_KEY:
                return err(git_key_error(), 409)
            sec = secrets.token_urlsafe(24)
            c.execute("UPDATE git_conns SET hook_secret=? WHERE id=?", (git_seal(cid, "hook", sec), cid))
            out["hook_secret"] = sec  # the only time it is shown
        else:
            c.execute("UPDATE git_conns SET hook_secret='' WHERE id=?", (cid,))
    bump(c)
    c.commit()
    _GIT_WAKE.set()
    return jsonify({**git_public(c, c.execute("SELECT * FROM git_conns WHERE id=?", (cid,)).fetchone(), True), **out})


@app.delete("/api/repos/<int:cid>")
def git_delete(cid):
    """Removes the connection with its stored pull requests, commits and links (completed tasks stay completed)."""
    c = db()
    r = git_need_conn(c, cid)
    c.execute("DELETE FROM git_links WHERE conn_id=?", (cid,))
    c.execute("DELETE FROM git_prs WHERE conn_id=?", (cid,))
    c.execute("DELETE FROM git_commits WHERE conn_id=?", (cid,))
    c.execute("DELETE FROM git_tags WHERE conn_id=?", (cid,))
    c.execute("DELETE FROM git_conns WHERE id=?", (cid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, list_id=r["list_id"])


@app.post("/api/repos/<int:cid>/refresh")
def git_refresh(cid):
    """Poll now (everyone who sees the list; at most every 20 s per repository)."""
    c = db()
    r = git_need_conn(c, cid, manage=False)
    if r["polled_at"] and (now_utc() - parse_iso(r["polled_at"])).total_seconds() < 20 and r["next_at"] > time.time() - 1:
        return jsonify(ok=True, queued=False)
    git_wake(c, cid)
    c.commit()
    return jsonify(ok=True, queued=True)


@app.post("/api/hooks/git/<int:cid>")
def git_hook(cid):
    """Inbound webhook (GitHub / Gitea / Forgejo / GitLab / Bitbucket): a valid signature only triggers the next poll at once."""
    from ..accounts.session import rate_ip
    # 2.126.0 B (#1979 I5): a limit and a size cap before the signature; review: per address, so one sender cannot hold up
    # the hooks of a connection for the repository host (a wider cap per connection stays)
    if hit_limit(f"githook:{cid}@{rate_ip()}", GIT_HOOK_PER_MIN) or hit_limit(f"githook:{cid}", GIT_HOOK_PER_MIN * 5):
        return err(tr("Too many requests"), 429)
    if (request.content_length or 0) > GIT_HOOK_MAX_BYTES:
        return err(tr("The file is too large (at most {0} MB)", GIT_HOOK_MAX_BYTES // (1024 * 1024)), 413)
    c = db()
    r = c.execute("SELECT * FROM git_conns WHERE id=?", (cid,)).fetchone()
    sec = git_unseal(cid, "hook", r["hook_secret"]) if r and r["hook_secret"] else ""
    if not sec:
        return err(tr("unknown"), 404)
    raw = request.get_data(cache=False) if request.content_length is not None else request.stream.read(GIT_HOOK_MAX_BYTES + 1)
    if len(raw or b"") > GIT_HOOK_MAX_BYTES:
        return err(tr("The file is too large (at most {0} MB)", GIT_HOOK_MAX_BYTES // (1024 * 1024)), 413)
    mac = hmac.new(sec.encode(), raw or b"", hashlib.sha256).hexdigest()
    gh = request.headers.get("X-Hub-Signature-256", "")
    gt = request.headers.get("X-Gitea-Signature", "") or request.headers.get("X-Forgejo-Signature", "")
    # 2.18.0: GitLab sends the secret itself (X-Gitlab-Token, compared in constant time), Bitbucket Cloud an HMAC-SHA256
    # in X-Hub-Signature ("sha256=...")
    gl = request.headers.get("X-Gitlab-Token", "")
    bb = request.headers.get("X-Hub-Signature", "")
    mb = mac.encode()  # 2.126.0 B (#1979 I5): compared as bytes (a header with other characters is simply wrong)
    if not ((gh.startswith("sha256=") and hmac.compare_digest(gh[7:].lower().encode("utf-8", "replace"), mb))
            or (gt and hmac.compare_digest(gt.lower().encode("utf-8", "replace"), mb))
            or (gl and hmac.compare_digest(gl.encode("utf-8", "replace"), sec.encode()))
            or (bb.startswith("sha256=") and hmac.compare_digest(bb[7:].lower().encode("utf-8", "replace"), mb))):
        return err(tr("Invalid signature"), 401)
    if request.headers.get("X-GitHub-Event") == "ping":
        return jsonify(ok=True, ping=True)
    # 2.16.0 (#637): never drop a hook. Within 10 s of the last poll it used to be ignored (debounce), so a push right after
    # a poll only showed up with the next regular poll (minutes). Now: next_at = min(next_at, polled_at + 10 s) - the
    # debounce stays, the hook is never lost (the loop picks it up on its next tick).
    now = time.time()
    due = now if not r["polled_at"] else max(now, parse_iso(r["polled_at"]).timestamp() + 10)
    if r["next_at"] > due + 1:
        if due <= now:
            git_wake(c, cid)
        else:
            c.execute("UPDATE git_conns SET next_at=? WHERE id=?", (due, cid))
        c.commit()
    return jsonify(ok=True), 202


@app.post("/api/tasks/<int:tid>/git-undo")
def git_undo(tid):
    """Takes back a completion by a keyword in a pull request / commit (the activity's "Undo")."""
    c = db()
    need_task(c, tid)
    r = c.execute("SELECT * FROM git_closes WHERE task_id=? AND undone_at IS NULL", (tid,)).fetchone()
    if not r:
        return err(tr("Changed in the meantime, nothing to undo"), 409)
    e = undo_status(c, tid, signed(tid, json.loads(r["undo"] or "{}")))
    if e:
        return err(e, 409)
    c.execute("UPDATE git_closes SET undone_at=? WHERE task_id=?", (iso(now_utc()), tid))
    log_act(c, tid, "reopen")
    bump(c)
    c.commit()
    return jsonify(one_task(c, tid))
