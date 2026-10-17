# 2.75.0 (#1411): a tiny OpenAI-compatible chat-completions endpoint for p275_a_api_test.py; runs INSIDE the test container
# (docker exec -d python /data/fake_ai.py) on port 8089: POST /v1/chat/completions.
# Expects "Authorization: Bearer test-key" (401 otherwise). Every request goes to /data/ai.log as one JSON line
# {model, messages, auth} (auth = whether the expected key came along, never the header itself).
# Answers by markers in the user message: FAKE_TIMEOUT -> sleeps 20 s, FAKE_BAD -> broken JSON content, FAKE_500 -> HTTP 500
# (the body carries a fake secret the server must never pass on), FAKE_BIG -> a 3 MB answer, FAKE_FOREIGN -> a proposal
# with ids outside the input; otherwise a canonical answer for the kind named in the system prompt ([kind: x]).
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open('/data/ai.log', 'a', buffering=1)
KEY = 'Bearer test-key'


def ids_in(text, key):
    return [int(x) for x in re.findall(r'"' + key + r'": (\d+)', text)]


def answer(kind, user):
    if kind in ('summary', 'draft'):
        return f'FAKE {kind} answer. Second line.'
    if kind == 'extract':
        if 'FAKE_FOREIGN' in user:
            return json.dumps({'summary': 'x', 'tasks': [{'title': 'Foreign', 'assignee_id': 999999, 'section': 'Nope', 'due': 'soon'},
                                                         {'title': ''}, 'junk']})
        return '```json\n' + json.dumps({'summary': 'Two tasks', 'tasks': [{'title': 'Call the printer', 'due': '2030-01-15'},
                                                                            {'title': 'Book the room', 'notes': 'big one', 'extra': 1}]}) + '\n```'
    if kind == 'tags':
        tid = (ids_in(user, 'task_id') or [0])[0]
        return 'Here you go: ' + json.dumps({'summary': 'Tagged', 'items': [{'task_id': tid, 'tags': ['#urgent', 'office'], 'due': '2030-02-01',
                                                                            'priority': 'high', 'list_id': 424242}]})
    if kind == 'triage':
        tids = ids_in(user, 'task_id')
        lids = ids_in(user, 'id')
        items = [{'task_id': t, 'list_id': (999999 if 'FAKE_FOREIGN' in user else (lids[0] if lids else None)), 'tags': ['sorted']}
                 for t in tids]
        items.append({'task_id': 888888, 'list_id': None})
        return json.dumps({'summary': 'Sorted', 'items': items})
    if kind == 'dayplan':
        tids = ids_in(user, 'task_id')
        return json.dumps({'summary': 'Plan', 'items': [{'task_id': t, 'start': f'{9 + i:02d}:00', 'duration': 30} for i, t in enumerate(tids[:3])]
                           + [{'task_id': 777777, 'start': '12:00'}]})
    return 'unknown kind'


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj=None, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        try:
            req = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            req = {}
        ok = self.headers.get('Authorization') == KEY
        LOG.write(json.dumps({'path': self.path, 'model': req.get('model'), 'messages': req.get('messages'), 'auth': ok,
                              'max_tokens': req.get('max_tokens')}) + '\n')
        if self.path != '/v1/chat/completions':
            return self.send(404, {'error': 'not found'})
        if not ok:
            return self.send(401, {'error': 'bad key'})
        msgs = req.get('messages') or [{}, {}]
        system, user = msgs[0].get('content', ''), msgs[-1].get('content', '')
        m = re.search(r'\[kind: (\w+)\]', system)
        kind = m.group(1) if m else ''
        if 'FAKE_TIMEOUT' in user:
            time.sleep(20)
        if 'FAKE_500' in user:
            return self.send(500, {'error': 'internal FAKE-PROVIDER-SECRET-XYZ'})
        if 'FAKE_BIG' in user:
            return self.send(200, raw=b'{"choices": [{"message": {"content": "' + b'A' * (3 * 1024 * 1024) + b'"}}]}')
        content = '{"summary": "broken' if 'FAKE_BAD' in user else answer(kind, user)
        self.send(200, {'id': 'x', 'object': 'chat.completion', 'model': req.get('model'),
                        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}]})


ThreadingHTTPServer(('127.0.0.1', 8089), H).serve_forever()
