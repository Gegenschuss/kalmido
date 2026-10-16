"""2.61.0 (#1818): virus scan of uploads (ClamAV clamd) and the file type from the content. Part A fills this in;
until then every function is a no-op so the shared path (files/upsafe.py) runs."""


def sc_sniff_mime(name, data, mime):
    """The mime type from the content (magic bytes) when it differs from the declared one, else None."""
    return None


def sc_scan(name, data):
    """'clean' | 'unchecked' (scanner not reachable) | 'off' (scanner switched off). Raises upsafe.UploadRefused on a find."""
    return "off"


def sc_after_store(c, kind, ref_id, org_id, info):
    """Remember an unchecked file for the later scan."""
    return None


def sc_marks(c, kind, ids):
    """{id: {"scan": "unchecked"|"infected"}} for the files of `kind` with such a state."""
    return {}
