# Fake calendar servers for calendars_test.py / calendars_ui.js. Runs INSIDE the test container
# (docker exec -d python /data/stub_calendar.py) and logs every request to /data/calstub.log.
#   127.0.0.1:8095  ICS files + a small CalDAV server (allow-listed via KALMIDO_CALENDAR_ALLOW_HOSTS)
#   127.0.0.1:8096  an "internal service" that must never be reached (not allow-listed)
# All dates are relative to today, so the fixtures always fall into the sync window.
import base64
import json
import os
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

LOG = open('/data/calstub.log', 'a', buffering=1)
USER, PW = 'alice', 'secret-pw'
T = date.today()


def d(n):
    return (T + timedelta(days=n)).strftime('%Y%m%d')


def monday(n=0):
    return T - timedelta(days=T.weekday()) + timedelta(weeks=n)


def good_ics():
    m0 = monday(-2)  # a Monday two weeks ago
    ex = m0 + timedelta(weeks=3)   # excluded Monday (EXDATE)
    ov = m0 + timedelta(weeks=4)   # moved Monday (RECURRENCE-ID override)
    # the New York event: every Tuesday 09:00 America/New_York for 20 weeks (crosses a DST change)
    ny = T - timedelta(days=(T.weekday() - 1) % 7)
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//stub//calendars test//EN
X-WR-CALNAME:Team Calendar
BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:weekly-1@stub
DTSTAMP:20260101T000000Z
DTSTART;TZID=Europe/Berlin:{m0:%Y%m%d}T100000
DTEND;TZID=Europe/Berlin:{m0:%Y%m%d}T110000
RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10
EXDATE;TZID=Europe/Berlin:{ex:%Y%m%d}T100000
SUMMARY:Weekly planning
LOCATION:Room 4
END:VEVENT
BEGIN:VEVENT
UID:weekly-1@stub
DTSTAMP:20260101T000000Z
RECURRENCE-ID;TZID=Europe/Berlin:{ov:%Y%m%d}T100000
DTSTART;TZID=Europe/Berlin:{ov:%Y%m%d}T150000
DTEND;TZID=Europe/Berlin:{ov:%Y%m%d}T160000
SUMMARY:Weekly planning (moved)
END:VEVENT
BEGIN:VEVENT
UID:allday-1@stub
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:{d(3)}
DTEND;VALUE=DATE:{d(6)}
SUMMARY:Conference trip
END:VEVENT
BEGIN:VEVENT
UID:ny-1@stub
DTSTAMP:20260101T000000Z
DTSTART;TZID=America/New_York:{ny:%Y%m%d}T090000
DTEND;TZID=America/New_York:{ny:%Y%m%d}T093000
RRULE:FREQ=WEEKLY;COUNT=20
SUMMARY:New York standup
END:VEVENT
BEGIN:VEVENT
UID:floating-1@stub
DTSTAMP:20260101T000000Z
DTSTART:{d(1)}T083000
DTEND:{d(1)}T090000
SUMMARY:Floating breakfast
END:VEVENT
BEGIN:VEVENT
UID:today-1@stub
DTSTAMP:20260101T000000Z
DTSTART;TZID=Europe/Berlin:{d(0)}T130000
DTEND;TZID=Europe/Berlin:{d(0)}T140000
SUMMARY:Lunch with Sam
LOCATION:Cafe Central
DESCRIPTION:Agenda: https://example.org/agenda?x=1 and javascript:alert(1)\\nsecond line
END:VEVENT
BEGIN:VEVENT
UID:cancel-1@stub
DTSTAMP:20260101T000000Z
DTSTART;TZID=Europe/Berlin:{d(2)}T120000
DTEND;TZID=Europe/Berlin:{d(2)}T130000
STATUS:CANCELLED
SUMMARY:Cancelled meeting
END:VEVENT
BEGIN:VEVENT
UID:xss-1@stub
DTSTAMP:20260101T000000Z
DTSTART;TZID=Europe/Berlin:{d(0)}T170000
DTEND;TZID=Europe/Berlin:{d(0)}T173000
SUMMARY:<img src=x onerror="window.__xss=1">Evil <b>bold</b>
LOCATION:<script>window.__xss=2</script>
DESCRIPTION:<a href="javascript:window.__xss=3">click</a> <img src=x onerror=window.__xss=4> https://ok.example/path
END:VEVENT
BEGIN:VEVENT
UID:minutely@stub
DTSTAMP:20260101T000000Z
DTSTART:{d(-1)}T000000Z
DURATION:PT1M
RRULE:FREQ=MINUTELY
SUMMARY:Every minute
END:VEVENT
BEGIN:VEVENT
UID:ancient@stub
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:00010101
RRULE:FREQ=DAILY;INTERVAL=7
SUMMARY:Ancient weekly
END:VEVENT
BEGIN:VEVENT
UID:never@stub
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:{d(0)}
RRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=31
SUMMARY:Never repeats
END:VEVENT
BEGIN:VTODO
UID:todo@stub
SUMMARY:A task, not an event
END:VTODO
END:VCALENDAR
"""


def google_ics():
    return f"""BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALNAME:mo@example.com
X-WR-TIMEZONE:Europe/Berlin
BEGIN:VTIMEZONE
TZID:Europe/Berlin
X-LIC-LOCATION:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
DTSTART:{d(2)}T080000Z
DTEND:{d(2)}T090000Z
DTSTAMP:20260901T000000Z
UID:abc123@google.com
CREATED:20260901T000000Z
DESCRIPTION:Join: <a href="https://meet.example.com/abc">https://meet.example.com/abc</a><br><br>Bring &amp; share
LAST-MODIFIED:20260901T000000Z
LOCATION:
SEQUENCE:0
STATUS:CONFIRMED
SUMMARY:Dentist
TRANSP:OPAQUE
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:{d(-400)}
DTEND;VALUE=DATE:{d(-399)}
RRULE:FREQ=YEARLY
DTSTAMP:20260901T000000Z
UID:bday@google.com
SUMMARY:Birthday Kim
END:VEVENT
END:VCALENDAR
"""


def daily_ics():
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//stub//daily//EN
BEGIN:VEVENT
UID:daily-3000@stub
DTSTAMP:20260101T000000Z
DTSTART:{d(-50)}T070000Z
DURATION:PT15M
RRULE:FREQ=DAILY;COUNT=3000
SUMMARY:Daily check-in
END:VEVENT
END:VCALENDAR
"""


def huge_ics(n_bytes):
    head = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:x\r\n"
    ev = f"BEGIN:VEVENT\r\nUID:{{}}@huge\r\nDTSTART:{d(1)}T100000Z\r\nSUMMARY:{'x' * 60}\r\nEND:VEVENT\r\n"
    out, i = [head], 0
    size = len(head)
    while size < n_bytes:
        s = ev.format(i)
        out.append(s)
        size += len(s)
        i += 1
    out.append("END:VCALENDAR\r\n")
    return "".join(out)


def dav_cal_data():
    return [f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//stub//dav//EN
BEGIN:VEVENT
UID:dav-1@stub
DTSTAMP:20260101T000000Z
DTSTART;TZID=Europe/Berlin:{d(1)}T110000
DTEND;TZID=Europe/Berlin:{d(1)}T120000
SUMMARY:Project review
LOCATION:Online
END:VEVENT
END:VCALENDAR
""", f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//stub//dav//EN
BEGIN:VEVENT
UID:dav-2@stub
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:{d(0)}
DTEND;VALUE=DATE:{d(1)}
RRULE:FREQ=WEEKLY;COUNT=4
SUMMARY:Gym week
END:VEVENT
END:VCALENDAR
"""]


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def ms(responses):
    return ('<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
            'xmlns:cs="http://calendarserver.org/ns/" xmlns:a="http://apple.com/ns/ical/">' + ''.join(
                f'<d:response><d:href>{h}</d:href><d:propstat><d:prop>{p}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
                for h, p in responses) + '</d:multistatus>')


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def _log(self):
        LOG.write(json.dumps({'port': self.server.server_address[1], 'method': self.command, 'path': self.path, 'host': self.headers.get('Host'),
                              'auth': self.headers.get('Authorization'), 'inm': self.headers.get('If-None-Match'),
                              't': time.time()}) + '\n')

    def _send(self, code, body=b'', ctype='text/calendar; charset=utf-8', extra=None, length=True):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        if length:
            self.send_header('Content-Length', str(len(b)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(b)

    def _authed(self):
        want = 'Basic ' + base64.b64encode(f'{USER}:{PW}'.encode()).decode()
        if self.headers.get('Authorization') != want:
            self._send(401, 'no', 'text/plain', {'WWW-Authenticate': 'Basic realm="dav"'})
            return False
        return True

    def do_GET(self):
        self._log()
        port, p = self.server.server_address[1], self.path.split('?')[0]
        if port == 8096:
            return self._send(200, 'internal-secret', 'text/plain')
        if p == '/good.ics':
            body = good_ics()
            etag = '"good-' + str(abs(hash(body)) % 10 ** 8) + '"'
            if self.headers.get('If-None-Match') == etag:
                return self._send(304, b'', extra={'ETag': etag})
            return self._send(200, body, extra={'ETag': etag})
        if p == '/google.ics':
            return self._send(200, google_ics())
        if p == '/daily.ics':
            return self._send(200, daily_ics())
        if p == '/huge.ics':   # announced size above the limit
            return self._send(200, huge_ics(int(os.environ.get('HUGE', 1_300_000))))
        if p == '/huge-nolen.ics':  # no Content-Length: the limit applies while reading
            return self._send(200, huge_ics(1_300_000), length=False)
        if p == '/login.html':
            return self._send(200, '<html><body>Please log in</body></html>', 'text/html')
        if p == '/garbage.ics':
            return self._send(200, 'BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:notadate\r\n', 'text/calendar')
        if p == '/flaky.ics':
            if os.path.exists('/data/flaky'):
                return self._send(500, 'boom', 'text/plain')
            return self._send(200, daily_ics())
        if p == '/redir-same.ics':
            return self._send(302, b'', 'text/plain', {'Location': '/good.ics'})
        if p == '/redir-port.ics':  # same host name, other (not allow-listed) port
            return self._send(302, b'', 'text/plain', {'Location': 'http://127.0.0.1:8096/secret'})
        if p == '/redir-evil.ics':  # other host name that resolves to 127.0.0.1
            return self._send(302, b'', 'text/plain', {'Location': 'http://evil.test:8095/good.ics'})
        if p == '/redir-meta.ics':
            return self._send(302, b'', 'text/plain', {'Location': 'http://169.254.169.254/latest/meta-data/'})
        if p == '/redir-loop.ics':
            return self._send(302, b'', 'text/plain', {'Location': '/redir-loop.ics'})
        return self._send(404, 'not found', 'text/plain')

    def do_PROPFIND(self):
        self._log()
        n = int(self.headers.get('Content-Length') or 0)
        req = self.rfile.read(n).decode() if n else ''
        p = self.path.split('?')[0]
        if p == '/.well-known/caldav':
            return self._send(301, b'', 'text/plain', {'Location': '/dav/'})
        if not p.startswith('/dav/'):
            return self._send(404, 'nope', 'text/plain')
        if not self._authed():
            return
        x = 'application/xml; charset=utf-8'
        if p in ('/dav/', '/dav/principals/alice/'):
            if 'calendar-home-set' in req and p.endswith('alice/'):
                return self._send(207, ms([(p, '<c:calendar-home-set><d:href>/dav/calendars/alice/</d:href></c:calendar-home-set>')]), x)
            return self._send(207, ms([(p, '<d:current-user-principal><d:href>/dav/principals/alice/</d:href></d:current-user-principal>'
                                           '<d:resourcetype><d:collection/></d:resourcetype>')]), x)
        if p == '/dav/calendars/alice/':
            return self._send(207, ms([
                ('/dav/calendars/alice/', '<d:resourcetype><d:collection/></d:resourcetype>'),
                ('/dav/calendars/alice/work/', '<d:resourcetype><d:collection/><c:calendar/></d:resourcetype><d:displayname>Work</d:displayname>'
                                              '<a:calendar-color>#FF8800FF</a:calendar-color><c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>'),
                ('/dav/calendars/alice/todo/', '<d:resourcetype><d:collection/><c:calendar/></d:resourcetype><d:displayname>Todos</d:displayname>'
                                              '<c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set>'),
                ('http://evil.test:8095/dav/calendars/alice/stolen/', '<d:resourcetype><d:collection/><c:calendar/></d:resourcetype><d:displayname>Elsewhere</d:displayname>'),
            ]), x)
        if p == '/dav/calendars/alice/work/':
            tag = open('/data/ctag').read().strip() if os.path.exists('/data/ctag') else 'ctag-1'
            return self._send(207, ms([(p, f'<cs:getctag>{tag}</cs:getctag><d:resourcetype><d:collection/><c:calendar/></d:resourcetype>')]), x)
        if p == '/dav/xxe/':
            return self._send(207, '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><d:multistatus xmlns:d="DAV:">&e;</d:multistatus>', x)
        return self._send(404, 'nope', 'text/plain')

    def do_REPORT(self):
        self._log()
        n = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(n)
        if not self._authed():
            return
        if self.path.split('?')[0] != '/dav/calendars/alice/work/':
            return self._send(404, 'nope', 'text/plain')
        body = ms([(f'/dav/calendars/alice/work/{i}.ics', f'<d:getetag>"e{i}"</d:getetag><c:calendar-data>{esc(cd)}</c:calendar-data>')
                   for i, cd in enumerate(dav_cal_data())])
        return self._send(207, body, 'application/xml; charset=utf-8')


for port in (8095, 8096):
    Thread(target=ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever, daemon=True).start()
while True:
    time.sleep(3600)
