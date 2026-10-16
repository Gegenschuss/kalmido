"""2.61.0 (#1820): text recognition for normal Ablage files in the background. Part C fills this in; until then a no-op."""


def ts_after_store(c, kind, ref_id, org_id, info):
    """Queue the text recognition of the stored file (never slows the upload down)."""
    return None


def ts_marks(c, kind, ids):
    """{id: {"text": "found"|"none"|"wait"}} for the files of `kind` the recognition has seen."""
    return {}
