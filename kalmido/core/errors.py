"""2.149.0 G (#2517): the error types and input checks every package uses. They lived in personal/timetrack.py (BadInput,
UnknownFields, reject_unknown, field_alias, web_fields) and core/access.py (Denied); both re-export them, so old and new
imports name the very same classes (except/isinstance catch either way). The error handlers stay where they were
(core.access: Denied, personal.timetrack: BadInput)."""
import time
from flask import g, has_request_context

from ..core.i18n import tr


# Permission checks raise Denied: 404 hides that a thing exists, 403 = view only / switched off, 409 = a module is off.
class Denied(Exception):
    def __init__(self, code=404, msg=None, data=None):
        super().__init__(code)
        self.code, self.msg = code, msg
        self.data = data  # 2.361.2 (#2923): more fields of the JSON answer (dict), next to "error"

    def text(self):
        # 2.298.0 C (#3187): a bare 404 says what probably happened instead of "unknown"
        return self.msg or (tr("No permission (view only)") if self.code == 403 else
                            tr("Not found. Maybe deleted or no longer shared with you.") if self.code == 404 else tr("unknown"))


class BadInput(Exception):
    pass


# ---- 2.2.1 (#359): unknown JSON fields. The REST API (/api/v1) refuses them: 400 with
# {"error": {"code": "unknown_field", "message", "fields": [...]}}. The web API (/api, the app's own endpoints) keeps
# working: it ignores them as before, but logs a warning and names them in the response header X-Kalmido-Unknown-Fields,
# so a client sending a field under the wrong name notices instead of losing the value silently. The one alias pair: a
# task's description is `content` in the web API and `notes` in /api/v1; both accept the other name too (both names with
# different values at once: 400).
class UnknownFields(BadInput):
    def __init__(self, fields):
        self.fields = sorted(str(k)[:64] for k in fields)[:50]
        super().__init__(tr("Unknown field: {0}", ", ".join(self.fields)[:200]))


def reject_unknown(b, allowed):
    """/api/v1: UnknownFields (-> 400 unknown_field) for keys of b not in allowed."""
    unknown = [k for k in b if k not in allowed]
    if unknown:
        raise UnknownFields(unknown)


def field_alias(b, have, other):
    """b with the alias `other` renamed to `have` (400 when both come with different values)."""
    if not isinstance(b, dict) or other not in b:
        return b
    if have in b and b[have] != b[other]:
        raise BadInput(tr("Send either {0} or {1}, not both", have, other))
    out = {k: v for k, v in b.items() if k != other}
    out[have] = b[other]
    return out


_UNKNOWN_LOGGED, UNKNOWN_LOG_EVERY = {}, 3600  # (what, fields) -> last warning (s); one line per hour and combination


def web_fields(b, known, what):
    """Web API: unknown keys of b are ignored (as always), logged as a warning (at most hourly per endpoint and set of
    names, never values) and named in the response header X-Kalmido-Unknown-Fields. Returns b."""
    if not isinstance(b, dict):
        return b
    unknown = sorted(str(k)[:64] for k in b if k not in known)
    if not unknown:
        return b
    if has_request_context():
        g.unknown_fields = unknown
    key, now = (what, tuple(unknown[:20])), time.time()
    if now - _UNKNOWN_LOGGED.get(key, 0) >= UNKNOWN_LOG_EVERY:
        if len(_UNKNOWN_LOGGED) > 500:
            _UNKNOWN_LOGGED.clear()
        _UNKNOWN_LOGGED[key] = now
        uid = g.user["id"] if has_request_context() and getattr(g, "user", None) else "-"
        print(f"WARNING {what}: unknown field(s) ignored: {', '.join(unknown)[:300]} (user {uid})", flush=True)
    return b
