"""2.558.0 (#4709): the two things of the shared core that the layer accounts needs, without importing upward.

core/objects.py (the shared core, layer domain: it stands on the file store's register) fills them when it loads; kalmido's
package import loads every module of ORDER, so they are always filled before a request or a command runs (the same pattern
as core/instance.UPDATE_KICK).
  OBJ     kind -> the registered hooks of obj_register (accounts/orgretain.py reads it: the heir of an account's objects)
  REVOKE  the functions f(c, uid, org, reason, heir=None, role=None) of what a person loses (core/objects.obj_revoke_person)
"""
OBJ = {}
REVOKE = []


def person_revoked(c, uid, org, reason, heir=None, role=None):
    """What a person loses when they leave an organisation, change role, the organisation retires or the account goes
    (accounts/orgs.py, accounts/users.py, accounts/orgretain.py call it). {what: number of rows} of every hook."""
    out = {}
    for f in REVOKE:
        out.update(f(c, uid, org, reason, heir=heir, role=role) or {})
    return out
