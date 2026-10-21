"""2.149.0 G (#2517): the request context of the signed-in person. me() lived in accounts/session.py (which re-exports it);
the core modules read it from here, so the lowest layer no longer imports accounts at module level."""
from flask import g


def me():
    return g.user["id"]
