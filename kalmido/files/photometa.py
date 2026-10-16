"""2.61.0 (#1819): photo metadata (GPS, camera) removed on upload. Part B fills this in; until then a no-op."""


def pm_strip(c, data, mime, uid=None, org_id=None):
    """Returns (data, meta): data without metadata (orientation applied first) when the setting is on, meta a dict
    (e.g. {"taken_at": "2026-10-16T12:00:00"}) read before the removal."""
    return data, {}
