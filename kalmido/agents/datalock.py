"""2.235.0 B (#2902): data an agent may never see (block list per area / project / tag), enforced in every read path.

Scaffold of the leader (job 1391); the part fills it."""


def dl_public(c, a):
    """What agent row a reads in GET /api/v1/agent "data_lock" (None until the part fills it)."""
    return None
