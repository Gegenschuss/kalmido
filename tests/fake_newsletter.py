# 2.55.0 (#1455): tiny newsletter services for p255_e_api_test.py; runs INSIDE the test container (docker exec -d python
# /data/fake_newsletter.py). Three ports:
#   8086 listmonk  -- the routes and answers as recorded from a real listmonk 6.2.0 ("Authorization: token user:token",
#                     409 "E-mail already exists.", PUT /api/subscribers/<id> REPLACES the lists, "add" re-subscribes)
#   8087 Brevo     -- API v3 as documented (header api-key)
#   8088 CleverReach -- REST v3 as documented (OAuth client credentials -> bearer token)
# State: /data/nl.json (the test may change it between runs: unsubscribe, confirm, bounce); every request goes to
# /data/nl.log as {port, method, path, auth} (auth = whether the expected credential came along, never its value).
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

LOCK = threading.Lock()
LOG = open('/data/nl.log', 'a', buffering=1)
LM_AUTH = 'token lmuser:lm-secret-token-1234'
BR_KEY = 'brevo-key-1234567890'
CR_BASIC = 'Basic Y3ItY2xpZW50OmNyLXNlY3JldC0xMjM0NTY='  # cr-client:cr-secret-123456
CR_TOKEN = 'cr-bearer-token'


def load():
    try:
        d = json.load(open('/data/nl.json'))
    except (OSError, ValueError):
        d = {}
    for k, v in (('lm', {'lists': [], 'subs': [], 'bounces': [], 'seq': 100}), ('br', {'lists': [], 'folders': [], 'contacts': {}, 'blocked': {}, 'seq': 10}),
                 ('cr', {'groups': [], 'receivers': {}, 'seq': 500})):
        d.setdefault(k, v)
    return d


def save(d):
    with open('/data/nl.json.new', 'w') as f:
        json.dump(d, f)
    import os
    os.replace('/data/nl.json.new', '/data/nl.json')


class Base(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    port = 0

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        b = json.dumps(obj if obj is not None else {}).encode() if obj is not None or code != 204 else b''
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b''
        if 'x-www-form-urlencoded' in (self.headers.get('Content-Type') or ''):
            return {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        try:
            return json.loads(raw or b'null')
        except ValueError:
            return None

    def _go(self, m):
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        ok = self.authed()
        LOG.write(json.dumps({'port': self.port, 'method': m, 'path': u.path, 'auth': ok}) + '\n')
        with LOCK:
            d = load()
            res = self.route(d, m, u.path, q, ok)
            save(d)
        self._send(*res)

    def do_GET(self):
        self._go('GET')

    def do_POST(self):
        self._go('POST')

    def do_PUT(self):
        self._go('PUT')

    def do_DELETE(self):
        self._go('DELETE')


class Listmonk(Base):
    port = 8086

    def authed(self):
        return self.headers.get('Authorization') == LM_AUTH

    @staticmethod
    def _pub(s, d):
        lists = []
        for li in s['lists']:
            L = next((x for x in d['lm']['lists'] if x['id'] == li['id']), None)
            if L:
                lists.append({'subscription_status': li['subscription_status'], 'id': L['id'], 'name': L['name'], 'optin': L['optin']})
        return {'id': s['id'], 'email': s['email'], 'name': s['name'], 'attribs': s.get('attribs', {}), 'status': s['status'], 'lists': lists}

    def route(self, d, m, p, q, ok):
        lm = d['lm']
        if not ok:
            return 403, {'message': 'invalid API credentials'}
        if p == '/api/health':
            return 200, {'data': True}
        if p == '/api/lists' and m == 'GET':
            return 200, {'data': {'results': [{'id': L['id'], 'name': L['name']} for L in lm['lists']]}}
        if p == '/api/lists' and m == 'POST':
            b = self._body()
            lm['seq'] += 1
            L = {'id': lm['seq'], 'name': b['name'], 'optin': b.get('optin', 'single'), 'type': b.get('type', 'private')}
            lm['lists'].append(L)
            return 200, {'data': L}
        if p == '/api/subscribers' and m == 'GET':
            rows = lm['subs']
            if 'list_id' in q:
                rows = [s for s in rows if any(li['id'] == int(q['list_id']) for li in s['lists'])]
            if 'query' in q:
                mm = re.fullmatch(r"subscribers\.email='([^']*)'", q['query'])
                rows = [s for s in rows if mm and s['email'] == mm.group(1)]
            per = len(rows) if q.get('per_page') == 'all' else int(q.get('per_page', 20))
            page = int(q.get('page', 1))
            part = rows[(page - 1) * per: page * per] if per else rows
            return 200, {'data': {'results': [self._pub(s, d) for s in part], 'total': len(rows), 'per_page': per, 'page': page}}
        if p == '/api/subscribers' and m == 'POST':
            b = self._body()
            if any(s['email'] == b['email'] for s in lm['subs']):
                return 409, {'message': 'E-mail already exists.'}
            lm['seq'] += 1
            st = 'confirmed' if b.get('preconfirm_subscriptions') else 'unconfirmed'
            s = {'id': lm['seq'], 'email': b['email'], 'name': b.get('name', ''), 'status': b.get('status', 'enabled'),
                 'lists': [{'id': i, 'subscription_status': st} for i in b.get('lists', [])]}
            lm['subs'].append(s)
            return 200, {'data': self._pub(s, d)}
        if p == '/api/subscribers/lists' and m == 'PUT':
            b = self._body()
            for s in lm['subs']:
                if s['id'] not in b['ids']:
                    continue
                for lid in b['target_list_ids']:
                    cur = next((li for li in s['lists'] if li['id'] == lid), None)
                    if b['action'] == 'add':  # like the real one: also re-subscribes an unsubscribed address
                        if cur:
                            cur['subscription_status'] = b.get('status', 'unconfirmed')
                        else:
                            s['lists'].append({'id': lid, 'subscription_status': b.get('status', 'unconfirmed')})
                    elif b['action'] == 'remove':
                        s['lists'] = [li for li in s['lists'] if li['id'] != lid]
                    elif b['action'] == 'unsubscribe' and cur:
                        cur['subscription_status'] = 'unsubscribed'
            return 200, {'data': True}
        mm = re.fullmatch(r'/api/subscribers/(\d+)(/optin)?', p)
        if mm:
            s = next((x for x in lm['subs'] if x['id'] == int(mm.group(1))), None)
            if not s:
                return 404, {'message': 'Subscriber not found.'}
            if mm.group(2):
                return 200, {'data': True}
            if m == 'GET':
                return 200, {'data': self._pub(s, d)}
            if m == 'PUT':  # like the real one: the lists are REPLACED (no "lists" = none), kept ones keep their status
                b = self._body()
                old = {li['id']: li for li in s['lists']}
                s['lists'] = [old.get(i, {'id': i, 'subscription_status': 'unconfirmed'}) for i in b.get('lists', [])]
                s['name'] = b.get('name', s['name'])
                return 200, {'data': self._pub(s, d)}
        if p == '/api/bounces':
            return 200, {'data': {'results': [{'email': e} for e in lm['bounces']], 'total': len(lm['bounces'])}}
        return 404, {'message': '404 unknown endpoint'}


class Brevo(Base):
    port = 8087

    def authed(self):
        return self.headers.get('api-key') == BR_KEY

    def route(self, d, m, p, q, ok):
        br = d['br']
        if not ok:
            return 401, {'code': 'unauthorized', 'message': 'Key not found'}
        if p == '/v3/account':
            return 200, {'email': 'owner@example.com', 'companyName': 'Example'}
        if p == '/v3/contacts/lists' and m == 'GET':
            off, lim = int(q.get('offset', 0)), int(q.get('limit', 10))
            return 200, {'lists': br['lists'][off:off + lim], 'count': len(br['lists'])}
        if p == '/v3/contacts/lists' and m == 'POST':
            b = self._body()
            if not b.get('folderId'):
                return 400, {'code': 'missing_parameter', 'message': 'folderId is missing'}
            br['seq'] += 1
            br['lists'].append({'id': br['seq'], 'name': b['name'], 'folderId': b['folderId']})
            return 201, {'id': br['seq']}
        if p == '/v3/contacts/folders' and m == 'GET':
            return 200, {'folders': br['folders'], 'count': len(br['folders'])}
        if p == '/v3/contacts/folders' and m == 'POST':
            br['seq'] += 1
            br['folders'].append({'id': br['seq'], 'name': self._body()['name']})
            return 201, {'id': br['seq']}
        mm = re.fullmatch(r'/v3/contacts/lists/(\d+)/contacts(/remove)?', p)
        if mm:
            lid = int(mm.group(1))
            if mm.group(2):
                for e in self._body().get('emails', []):
                    c = br['contacts'].get(e)
                    if c:
                        c['listIds'] = [x for x in c['listIds'] if x != lid]
                return 201, {'contacts': {'success': []}}
            rows = [c for c in br['contacts'].values() if lid in c['listIds'] or lid in c.get('listUnsubscribed', [])]
            off, lim = int(q.get('offset', 0)), int(q.get('limit', 50))
            return 200, {'contacts': rows[off:off + lim], 'count': len(rows)}
        if p == '/v3/smtp/blockedContacts':
            return 200, {'contacts': [{'email': e, 'reason': {'code': r}} for e, r in br['blocked'].items()], 'count': len(br['blocked'])}
        mm = re.fullmatch(r'/v3/contacts/([^/]+)', p)
        if mm:
            e = unquote(mm.group(1))
            c = br['contacts'].get(e)
            if m == 'GET':
                return (200, c) if c else (404, {'code': 'document_not_found', 'message': 'Contact does not exist'})
            if m == 'PUT' and c:
                c['attributes'].update(self._body().get('attributes', {}))
                return 204, None
            return 404, {'code': 'document_not_found'}
        if p == '/v3/contacts' and m == 'POST':
            b = self._body()
            c = br['contacts'].get(b['email'])
            if c and not b.get('updateEnabled'):
                return 400, {'code': 'duplicate_parameter'}
            new = not c
            if new:
                br['seq'] += 1
                c = br['contacts'][b['email']] = {'id': br['seq'], 'email': b['email'], 'attributes': {}, 'listIds': [], 'emailBlacklisted': False,
                                                  'listUnsubscribed': []}
            c['attributes'].update(b.get('attributes', {}))
            c['listIds'] = sorted(set(c['listIds']) | set(b.get('listIds', [])))
            return (201, {'id': c['id']}) if new else (204, None)
        return 404, {'code': 'not_found'}


class CleverReach(Base):
    port = 8088

    def authed(self):
        a = self.headers.get('Authorization') or ''
        return a == CR_BASIC if self.path.startswith('/oauth/') else a == 'Bearer ' + CR_TOKEN

    def route(self, d, m, p, q, ok):
        cr = d['cr']
        if p == '/oauth/token.php':
            b = self._body() or {}
            if not ok or b.get('grant_type') != 'client_credentials':
                return 401, {'error': 'invalid_client'}
            return 200, {'access_token': CR_TOKEN, 'expires_in': 3600, 'token_type': 'bearer'}
        if not ok:
            return 401, {'error': {'code': 401, 'message': 'Unauthorized: invalid token'}}
        if p == '/v3/groups.json' and m == 'GET':
            return 200, cr['groups']
        if p == '/v3/groups.json' and m == 'POST':
            cr['seq'] += 1
            g = {'id': cr['seq'], 'name': self._body()['name']}
            cr['groups'].append(g)
            return 200, g
        mm = re.fullmatch(r'/v3/groups\.json/(\d+)/receivers(?:/(upsert|[^/]+))?', p)
        if mm:
            gid, sub = mm.group(1), mm.group(2)
            rec = cr['receivers'].setdefault(gid, {})
            if sub == 'upsert' and m == 'POST':
                for r in self._body():
                    cur = rec.get(r['email'])
                    if cur:
                        cur['global_attributes'].update(r.get('global_attributes', {}))
                    else:
                        cr['seq'] += 1
                        rec[r['email']] = {'id': cr['seq'], 'email': r['email'], 'activated': r.get('activated', 0), 'deactivated': 0,
                                           'bounced': 0, 'global_attributes': r.get('global_attributes', {})}
                return 200, [{'status': 'ok'}]
            if sub and m == 'DELETE':
                return (200, True) if rec.pop(unquote(sub), None) else (404, {'error': {'code': 404}})
            if not sub and m == 'GET':
                rows = list(rec.values())
                per, page = int(q.get('pagesize', 100)), int(q.get('page', 0))
                return 200, rows[page * per:(page + 1) * per]
        return 404, {'error': {'code': 404, 'message': 'not found'}}


for cls in (Listmonk, Brevo, CleverReach):
    threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', cls.port), cls).serve_forever, daemon=True).start()
threading.Event().wait()
