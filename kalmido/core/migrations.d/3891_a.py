"""2.622.0 (#3891): short-lived state that every web process of an instance must see (core/ephem.py): sign-in steps, OIDC
states, download tickets, undo tokens, typing / presence markers, short counters. ns = the kind, k = the key (a hash only),
v = the value (sealed where it holds a secret), uid / grp / ip = what a lookup or a cap goes by (ip as a hash), n = a counter,
exp = end (Unix time; an expired row counts as gone and is deleted on the next pass). A new table only: older versions
ignore it."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS eph_state (
  ns TEXT NOT NULL, k TEXT NOT NULL, v TEXT NOT NULL DEFAULT '', uid BIGINT, grp TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '',
  n BIGINT NOT NULL DEFAULT 0, at DOUBLE PRECISION NOT NULL, exp DOUBLE PRECISION NOT NULL, PRIMARY KEY (ns, k));
CREATE INDEX IF NOT EXISTS eph_state_exp ON eph_state(exp);
CREATE INDEX IF NOT EXISTS eph_state_grp ON eph_state(ns, grp) WHERE grp<>'';
CREATE INDEX IF NOT EXISTS eph_state_uid ON eph_state(ns, uid) WHERE uid IS NOT NULL;
CREATE INDEX IF NOT EXISTS eph_state_ip ON eph_state(ns, ip) WHERE ip<>'';
"""
