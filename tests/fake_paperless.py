# 2.48.0 (#1152): a tiny Paperless-ngx API for p248_d_paperless_api_test.py; runs INSIDE the test container (docker exec -d
# python /data/fake_paperless.py), port 8098, token "pl-secret" (header "Authorization: Token ..."). Read only, like the
# real thing as Kalmido uses it: GET /api/documents/ (ordering=id|-id, page, page_size), /api/documents/<id>/download/,
# /api/documents/<id>/notes/, /api/tags/, /api/correspondents/, /api/document_types/, /api/custom_fields/. The data is
# /data/pl.json (written by the test, re-read on every request; files as text); every request goes to /data/pl.log.
# Any other method answers 405 and is logged (the test checks that Kalmido never writes).
# 2.56.4 (#1859): pl.json "versions" = the API versions the server allows (Paperless-ngx 3.x: ["9", "10"]); an Accept header
# with another version= answers 406 like DRF's AcceptHeaderVersioning. Without "versions" every version is taken.
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

LOG = open('/data/pl.log', 'a', buffering=1)


def data():
    try:
        return json.load(open('/data/pl.json'))
    except (OSError, ValueError):
        return {}


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, raw=None, ctype='application/json', extra=None):
        b = raw if raw is not None else json.dumps(obj if obj is not None else {}).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _auth(self):
        ok = self.headers.get('Authorization') == 'Token pl-secret'
        LOG.write(json.dumps({'m': self.command, 'p': self.path, 'auth': ok, 'accept': self.headers.get('Accept', '')}) + '\n')
        if not ok:
            self._send(401, {'detail': 'Invalid token.'})
        return ok

    def _page(self, rows, q, base):
        size = int(q.get('page_size', ['25'])[0])
        page = int(q.get('page', ['1'])[0])
        part = rows[(page - 1) * size: page * size]
        nxt = f'http://127.0.0.1:8098{base}?page={page + 1}' if page * size < len(rows) else None
        self._send(200, {'count': len(rows), 'next': nxt, 'previous': None, 'results': part})

    def do_GET(self):
        if not self._auth():
            return
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        d = data()
        ver = re.search(r'version=([0-9.]+)', self.headers.get('Accept', ''))
        if ver and d.get('versions') and ver.group(1) not in d['versions']:
            return self._send(406, {'detail': 'Invalid version in "Accept" header.'})
        p = u.path
        if p == '/redirect/api/documents/':
            return self._send(302, {}, extra={'Location': 'http://example.invalid/api/documents/'})
        if p == '/api/documents/':
            docs = [{k: v for k, v in x.items() if k != 'file'} for x in d.get('documents', [])]
            docs.sort(key=lambda x: x['id'], reverse=q.get('ordering', ['id'])[0] == '-id')
            return self._page(docs, q, p)
        for kind in ('tags', 'correspondents', 'document_types', 'custom_fields'):
            if p == f'/api/{kind}/':
                return self._page(d.get(kind, []), q, p)
        parts = p.strip('/').split('/')
        if len(parts) == 4 and parts[:2] == ['api', 'documents'] and parts[2].isdigit():
            doc = next((x for x in d.get('documents', []) if x['id'] == int(parts[2])), None)
            if not doc:
                return self._send(404, {'detail': 'Not found.'})
            if parts[3] == 'download':
                raw = doc.get('file', '').encode('latin-1')
                return self._send(200, raw=raw, ctype=doc.get('mime', 'application/pdf'),
                                  extra={'Content-Disposition': f'attachment; filename="{doc.get("original_file_name", "x.pdf")}"'})
            if parts[3] == 'notes':
                return self._send(200, d.get('notes', {}).get(str(doc['id']), []))
        self._send(404, {'detail': 'Not found.'})

    def _refuse(self):
        LOG.write(json.dumps({'m': self.command, 'p': self.path, 'auth': None}) + '\n')
        self._send(405, {'detail': 'not allowed'})

    do_POST = do_PUT = do_PATCH = do_DELETE = _refuse


ThreadingHTTPServer(('127.0.0.1', 8098), H).serve_forever()
