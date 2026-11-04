# 2.2.0: fake GitHub (Enterprise layout, /api/v3 on 127.0.0.1:8090) and fake Gitea / Forgejo (/api/v1 on 127.0.0.1:8091)
# for p220_api_test.py / p220_ui.js. Runs INSIDE the test container (docker exec -d python /data/fake_git.py); no real
# GitHub is ever called. The suite writes the repositories into /data/git.json (re-read on every request):
#   {"<port>": {"owner/repo": {"token": "...", "default_branch": "main", "pulls": [...], "commits": {"main": [...]},
#                              "compare": {"<head ref>": [...]}, "status": {"<sha>": {...}}, "checks": {"<sha>": [...]}}},
#    "remaining": 4999, "rate_block": false, "slow": 0}
# Every request is logged to /data/git.log (port, path, Authorization, If-None-Match, status).
# 2.18.0 (#408): + fake GitLab (/api/v4 on 127.0.0.1:8092: projects by URL-encoded path incl. nested groups, PRIVATE-TOKEN or
# Bearer, RateLimit-* headers) and fake Bitbucket Cloud (/2.0 on 127.0.0.1:8093: {values: [...]} pages, Bearer or Basic
# user:app-password). Their repositories in git.json use the providers' own shapes: "pulls" = merge requests / pull
# requests, "commits" {branch: [...]}, "compare" {ref: [...]}, "status" {sha: [...]}, "tags" [...] (also GitHub / Gitea).
# 2.151.0 A (#2558): + "branches" [...] (the providers' shapes: GitHub {name, commit: {sha}}, Gitea {name, commit: {id}}, GitLab
# {name, commit: {id}}, Bitbucket {name, target: {hash}}) and compares between two refs: "compare" {"<base>...<head>": [...]}
# is looked up first (tags), then {"<head>": [...]} as before.
# 2.394.0 B (#3377): + issues (GitHub and GitLab, pages by page / per_page): "issues" [...] in the provider's shape (GitHub's
# list holds pull requests too), "issue_comments" {"<number>": [...]} (GitLab: notes, system notes included), "issues_off"
# (404 like a repository with issues switched off), "issues_denied" (403: a token without read access to issues).
# 2.394.0 C (#3377): + the issue sync: one issue (GET issues/<n>), the list filtered by since= / updated_after= and sorted
# oldest first when asked (direction=asc / sort=asc), the writes PATCH issues/<n> (GitLab PUT), POST issues (a new one),
# POST issues/<n>/comments (GitLab notes) -- applied to /data/git.json; their time stamp is "write_ts" of git.json (else
# now), "write_denied" (403) refuses them; the repository answer carries "permissions" (GitHub {push: ...} from
# "permissions", GitLab project_access.access_level from "access_level"). Every write is logged with method + body.
# 2.394.0 D (#3377 review): "write_fail" {skip, times, status} lets the first `skip` writes of a repository pass and refuses
# the next `times` (counted down in git.json); a title longer than the provider takes is refused (422: GitHub 256, GitLab
# 255); the issue events ("events" {"<n>": [...]} for GitHub, "resource_state_events" / "resource_label_events" for
# GitLab; a repository without the key answers 404); "comments_rate" (GitHub: the comments of an issue hit the rate
# limit); "perm_by_token" {token: permissions} (GitHub: each of these tokens is taken, with its permissions); "slow_write"
# (s a write waits; its start is written to /data/git.start first, so a suite can act while it runs).
import base64
import os
import hashlib
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open('/data/git.log', 'a', buffering=1)
WLOCK = threading.Lock()  # 2.394.0 C (#3377): writes into git.json one at a time
PREFIX = {8090: '/api/v3', 8091: '/api/v1', 8092: '/api/v4', 8093: '/2.0'}


def state():
    try:
        return json.load(open('/data/git.json'))
    except (OSError, ValueError):
        return {}


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, obj, st, etag=True):
        port = self.server.server_address[1]
        body = json.dumps(obj).encode() if obj is not None else b''
        tag = '"' + hashlib.md5(body).hexdigest() + '"'
        inm = self.headers.get('If-None-Match')
        if code == 200 and etag and inm == tag:
            code, body = 304, b''
        LOG.write(json.dumps({'port': port, 'path': self.path, 'auth': self.headers.get('Authorization'), 'inm': inm,
                              'ptok': self.headers.get('PRIVATE-TOKEN'), 'method': self.command, 'body': getattr(self, 'wbody', None),
                              'status': code, 'ua': self.headers.get('User-Agent')}) + '\n')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        if port == 8092:
            self.send_header('RateLimit-Remaining', str(st.get('gl_remaining', 1999)))
            self.send_header('RateLimit-Reset', str(int(time.time()) + int(st.get('reset_in', 120))))
        if port == 8090:
            self.send_header('X-RateLimit-Remaining', str(st.get('remaining', 4999)))
            self.send_header('X-RateLimit-Reset', str(int(time.time()) + int(st.get('reset_in', 120))))
        if code == 429:
            self.send_header('Retry-After', '120')
        if code in (200, 304):
            self.send_header('ETag', tag)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        port = self.server.server_address[1]
        st = state()
        if st.get('slow'):
            time.sleep(float(st['slow']))
        p = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(p.query)
        pre = PREFIX[port]
        if port == 8092:
            return self.gitlab(p, q, st)
        if port == 8093:
            return self.bitbucket(p, q, st)
        if not p.path.startswith(pre + '/repos/'):
            return self._send(404, {'message': 'Not Found'}, st)
        parts = p.path[len(pre) + 7:].split('/')
        if len(parts) < 2:
            return self._send(404, {'message': 'Not Found'}, st)
        key, rest = parts[0] + '/' + parts[1], parts[2:]
        repos = st.get(str(port), {})
        r = repos.get(key)
        if port == 8090 and st.get('rate_block'):
            return self._send(403, {'message': 'API rate limit exceeded'}, {**st, 'remaining': 0}, etag=False)
        if r is None:
            return self._send(404, {'message': 'Not Found'}, st)
        want, pbt = r.get('token'), r.get('perm_by_token') or {}  # 2.394.0 D: perm_by_token
        got = self.headers.get('Authorization') or ''
        tok = next((t for t in (list(pbt) or [want]) if t and got in ('Bearer ' + t, 'token ' + t)), None)
        if (want or pbt) and not tok:
            return self._send(401, {'message': 'Bad credentials'}, st)
        if not rest:
            return self._send(200, {'name': parts[1], 'owner': {'login': parts[0]}, 'default_branch': r.get('default_branch', 'main'),
                                    'permissions': pbt.get(tok) or r.get('permissions', {'admin': False, 'push': True, 'pull': True})}, st)
        if rest == ['pulls']:
            return self._send(200, r.get('pulls', []), st)
        if rest == ['tags']:
            return self._send(200, r.get('tags', []), st)
        if rest == ['branches']:
            return self._send(200, r.get('branches', []), st)
        if rest == ['commits']:
            return self._send(200, r.get('commits', {}).get((q.get('sha') or ['main'])[0], []), st)
        if rest[0] == 'issues':  # 2.394.0 B (#3377)
            return self._issues(r, rest, q, st)
        if rest[0] == 'compare' and len(rest) >= 2:
            both = urllib.parse.unquote('/'.join(rest[1:]))
            head = both.split('...', 1)[-1]
            cmp = r.get('compare', {})
            return self._cmp(cmp[both] if both in cmp else cmp.get(head, []), st)
        if rest[0] == 'commits' and len(rest) == 3 and rest[2] == 'status':
            return self._send(200, r.get('status', {}).get(rest[1], {'state': 'pending', 'total_count': 0, 'statuses': []}), st)
        if rest[0] == 'commits' and len(rest) == 3 and rest[2] == 'check-runs':
            if port != 8090:
                return self._send(404, {'message': 'Not Found'}, st)
            return self._send(200, {'total_count': len(r.get('checks', {}).get(rest[1], [])), 'check_runs': r.get('checks', {}).get(rest[1], [])}, st)
        return self._send(404, {'message': 'Not Found'}, st)


    def _cmp(self, v, st):
        """2.151.0 A2 (#2558 review): a compare entry is a list of commits, or a whole answer {commits, ahead_by}, or
        {status: 404 | 500} (an error)."""
        if isinstance(v, dict) and v.get('status'):
            return self._send(v['status'], {'message': 'error'}, st, etag=False)
        return self._send(200, v if isinstance(v, dict) else {'commits': v}, st)

    def _authed(self, r, st):
        want = r.get('token')
        if not want:
            return True
        got = self.headers.get('Authorization') or ''
        ok = got == 'Bearer ' + want or self.headers.get('PRIVATE-TOKEN') == want or \
            (':' in want and got == 'Basic ' + base64.b64encode(want.encode()).decode())
        if not ok:
            self._send(401, {'message': '401 Unauthorized'}, st)
        return ok

    def gitlab(self, p, q, st):
        pre = '/api/v4/projects/'
        if not p.path.startswith(pre):
            return self._send(404, {'message': '404 Not Found'}, st)
        if st.get('gl_block'):
            return self._send(429, {'message': 'Retry later'}, st, etag=False)
        parts = p.path[len(pre):].split('/')
        key, rest = urllib.parse.unquote(parts[0]), parts[1:]
        r = st.get('8092', {}).get(key)
        if r is None:
            return self._send(404, {'message': '404 Project Not Found'}, st)
        if not self._authed(r, st):
            return
        if not rest:
            return self._send(200, {'path': key.rsplit('/', 1)[-1], 'path_with_namespace': key,
                                    'default_branch': r.get('default_branch', 'main'),
                                    'permissions': {'project_access': {'access_level': r.get('access_level', 30)}, 'group_access': None}}, st)
        if rest == ['merge_requests']:
            return self._send(200, r.get('pulls', []), st)
        if rest == ['repository', 'commits']:
            return self._send(200, r.get('commits', {}).get((q.get('ref_name') or ['main'])[0], []), st)
        if rest == ['repository', 'compare']:
            cmp, to = r.get('compare', {}), (q.get('to') or [''])[0]
            both = (q.get('from') or [''])[0] + '...' + to
            return self._cmp(cmp[both] if both in cmp else cmp.get(to, []), st)
        if rest == ['repository', 'branches']:
            return self._send(200, r.get('branches', []), st)
        if rest[:2] == ['repository', 'commits'] and len(rest) == 4 and rest[3] == 'statuses':
            return self._send(200, r.get('status', {}).get(urllib.parse.unquote(rest[2]), []), st)
        if rest == ['repository', 'tags']:
            return self._send(200, r.get('tags', []), st)
        if rest[0] == 'issues':  # 2.394.0 B (#3377)
            return self._issues(r, [x if i != 2 else 'comments' for i, x in enumerate(rest)] if rest[2:3] == ['notes'] else rest, q, st)
        return self._send(404, {'message': '404 Not Found'}, st)

    def bitbucket(self, p, q, st):
        pre = '/2.0/repositories/'
        if not p.path.startswith(pre):
            return self._send(404, {'type': 'error'}, st)
        parts = p.path[len(pre):].split('/')
        if len(parts) < 2:
            return self._send(404, {'type': 'error'}, st)
        key, rest = parts[0] + '/' + parts[1], parts[2:]
        r = st.get('8093', {}).get(key)
        if r is None:
            return self._send(404, {'type': 'error', 'error': {'message': 'Repository not found'}}, st)
        if not self._authed(r, st):
            return
        if not rest:
            return self._send(200, {'slug': parts[1], 'full_name': key, 'mainbranch': {'name': r.get('default_branch', 'main')}}, st)
        if rest == ['pullrequests']:
            return self._send(200, {'values': r.get('pulls', []), 'pagelen': 30}, st)
        if rest[0] == 'commits' and len(rest) == 2:
            ref = urllib.parse.unquote(rest[1])
            if q.get('exclude'):
                cmp, both = r.get('compare', {}), q['exclude'][0] + '...' + ref
                return self._send(200, {'values': cmp[both] if both in cmp else cmp.get(ref, [])}, st)
            return self._send(200, {'values': r.get('commits', {}).get(ref, [])}, st)
        if rest[0] == 'commit' and len(rest) == 3 and rest[2] == 'statuses':
            return self._send(200, {'values': r.get('status', {}).get(rest[1], [])}, st)
        if rest == ['refs', 'tags']:
            return self._send(200, {'values': r.get('tags', [])}, st)
        if rest == ['refs', 'branches']:
            return self._send(200, {'values': r.get('branches', [])}, st)
        return self._send(404, {'type': 'error'}, st)

    def _issues(self, r, rest, q, st):
        """2.394.0 B (#3377): the issue list / the comments of one issue, one page of it."""
        if r.get('issues_off'):
            return self._send(404, {'message': 'Not Found'}, st)
        if r.get('issues_denied'):
            return self._send(403, {'message': 'Resource not accessible by personal access token'}, st)
        if rest == ['issues']:
            items = r.get('issues', [])
            since = (q.get('since') or q.get('updated_after') or [''])[0]
            if since:  # 2.394.0 C (#3377)
                items = [x for x in items if str(x.get('updated_at') or '')[:19] >= since[:19]]
            if (q.get('direction') or q.get('sort') or [''])[0] == 'asc':
                items = sorted(items, key=lambda x: str(x.get('updated_at') or ''))
        elif len(rest) == 2:  # 2.394.0 C (#3377): one issue
            one = [x for x in r.get('issues', []) if str(x.get('number', x.get('iid'))) == rest[1]]
            return self._send(200, one[0], st) if one else self._send(404, {'message': 'Not Found'}, st)
        elif len(rest) == 3 and rest[2] == 'comments':
            if r.get('comments_rate'):  # 2.394.0 D
                return self._send(403, {'message': 'API rate limit exceeded'}, {**st, 'remaining': 0}, etag=False)
            items = r.get('issue_comments', {}).get(rest[1], [])
        elif len(rest) == 3 and rest[2] in ('events', 'resource_state_events', 'resource_label_events'):  # 2.394.0 D
            if rest[2] not in r:
                return self._send(404, {'message': 'Not Found'}, st)
            items = r[rest[2]].get(rest[1], [])
        else:
            return self._send(404, {'message': 'Not Found'}, st)
        page, per = int((q.get('page') or ['1'])[0]), int((q.get('per_page') or ['20'])[0])
        return self._send(200, items[(page - 1) * per:page * per], st)


    # ---- 2.394.0 C (#3377): issue writes (GitHub PATCH / POST, GitLab PUT / POST), applied to git.json
    def do_PATCH(self):
        self._write()

    def do_PUT(self):
        self._write()

    def do_POST(self):
        self._write()

    def _write(self):
        port = self.server.server_address[1]
        n = int(self.headers.get('Content-Length') or 0)
        try:
            self.wbody = json.loads(self.rfile.read(n).decode() or 'null') if n else None
        except ValueError:
            self.wbody = None
        if state().get('slow_write'):  # 2.394.0 D
            with open('/data/git.start', 'a') as f:
                f.write(self.command + ' ' + self.path + '\n')
            time.sleep(float(state()['slow_write']))
        with WLOCK:
            st = state()
            p = urllib.parse.urlsplit(self.path)
            gl = port == 8092
            if gl:
                parts = p.path[len('/api/v4/projects/'):].split('/')
                key, rest = urllib.parse.unquote(parts[0]), parts[1:]
            else:
                parts = p.path[len(PREFIX[port]) + 7:].split('/')
                key, rest = '/'.join(parts[:2]), parts[2:]
            r = st.get(str(port), {}).get(key)
            if r is None or rest[:1] != ['issues']:
                return self._send(404, {'message': 'Not Found'}, st, etag=False)
            if not self._authed(r, st) if gl else (r.get('token') and (self.headers.get('Authorization') or '') not in ('Bearer ' + r['token'], 'token ' + r['token'])):
                return None if gl else self._send(401, {'message': 'Bad credentials'}, st, etag=False)
            if r.get('write_denied'):
                return self._send(403, {'message': 'Resource not accessible by personal access token'}, st, etag=False)
            wf = r.get('write_fail')  # 2.394.0 D
            if wf and wf.get('skip', 0) > 0:
                wf['skip'] -= 1
            elif wf and wf.get('times', 0) > 0:
                wf['times'] -= 1
                self._save(st)
                return self._send(wf.get('status', 422), {'message': 'Validation Failed'}, st, etag=False)
            if isinstance(self.wbody, dict) and len(str(self.wbody.get('title') or '')) > (255 if gl else 256):
                return self._send(422, {'message': 'Validation Failed', 'errors': [{'field': 'title', 'code': 'invalid'}]}, st, etag=False)
            ts = st.get('write_ts') or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            b, items = self.wbody if isinstance(self.wbody, dict) else {}, r.setdefault('issues', [])
            no_key = 'iid' if gl else 'number'
            if len(rest) == 1 and self.command == 'POST':  # a new issue
                no = max([x.get(no_key, 0) for x in items] + [0]) + 1
                web = f"http://127.0.0.1:{port}/{key}/" + ('-/issues/' if gl else 'issues/') + str(no)
                lab = (b.get('labels') or '').split(',') if gl else b.get('labels') or []
                it = {no_key: no, 'title': b.get('title', ''), ('description' if gl else 'body'): b.get('description' if gl else 'body') or '',
                      'state': 'opened' if gl else 'open', 'labels': [x for x in lab if x] if gl else [{'name': x} for x in lab],
                      'assignees': [], ('author' if gl else 'user'): {('username' if gl else 'login'): 'kalmido-bot'},
                      ('web_url' if gl else 'html_url'): web, 'created_at': ts, 'updated_at': ts, 'closed_at': None,
                      ('user_notes_count' if gl else 'comments'): 0}
                items.insert(0, it)
            else:
                one = [x for x in items if str(x.get(no_key)) == (rest[1] if len(rest) > 1 else '')]
                if not one:
                    return self._send(404, {'message': 'Not Found'}, st, etag=False)
                it = one[0]
                if len(rest) == 3 and self.command == 'POST':  # a comment / note
                    cms = r.setdefault('issue_comments', {}).setdefault(rest[1], [])
                    cid = max([x.get('id', 0) for v in r['issue_comments'].values() for x in v] + [1000]) + 1
                    cm = {'id': cid, 'body': b.get('body', ''), ('author' if gl else 'user'): {('username' if gl else 'login'): 'kalmido-bot'},
                          'created_at': ts, 'updated_at': ts, **({'system': False} if gl else {})}
                    cms.append(cm)
                    ck = 'user_notes_count' if gl else 'comments'
                    it[ck] = (it.get(ck) or 0) + 1
                    it['updated_at'] = ts
                    self._save(st)
                    return self._send(201, cm, st, etag=False)
                for f in ('title', 'body', 'description'):
                    if f in b:
                        it[f] = b[f]
                if 'labels' in b:
                    it['labels'] = [x for x in b['labels'].split(',') if x] if gl else [{'name': x} for x in b['labels']]
                if 'state' in b:
                    it['state'], it['closed_at'] = b['state'], ts if b['state'] == 'closed' else None
                if 'state_event' in b:
                    it['state'] = 'closed' if b['state_event'] == 'close' else 'opened'
                    it['closed_at'] = ts if it['state'] == 'closed' else None
            it['updated_at'] = ts
            self._save(st)
            return self._send(201 if self.command == 'POST' else 200, it, st, etag=False)

    def _save(self, st):
        tmp = '/data/git.json.w'
        with open(tmp, 'w') as f:
            json.dump(st, f)
        os.replace(tmp, '/data/git.json')


for port in (8090, 8091, 8092, 8093):
    threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever, daemon=True).start()
while True:
    time.sleep(3600)
