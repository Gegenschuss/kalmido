"""2.705.0 (#5151): the optional address rule of a key -- moved here from api/scopes.py (2.15.0 #479), so the receipt
fetcher keys (docs/fetcher.py) check it the same way without reaching up into the API layer. api/scopes.py re-exports both.
allowed_ips of a row: '' = any address, else IPs / networks (CIDR) separated by commas."""
import ipaddress
import re

from .errors import BadInput
from .i18n import tr


def ips_clean(v):
    """Allowed client addresses of a token: a list (or comma / space separated text) of IPs / networks; '' = any."""
    if v in (None, "", []):
        return ""
    items = v if isinstance(v, list) else re.split(r"[\s,]+", str(v))
    out = []
    for x in items:
        x = str(x).strip()
        if not x:
            continue
        try:
            out.append(str(ipaddress.ip_network(x, strict=False)))
        except ValueError:
            raise BadInput(tr("Invalid address or network: {0}", x[:60])) from None
    if len(out) > 20:
        raise BadInput(tr("At most {0} addresses", 20))
    return ",".join(dict.fromkeys(out))


def token_ip_ok(row, ip):
    nets = [x for x in (row["allowed_ips"] or "").split(",") if x] if "allowed_ips" in row.keys() else []
    if not nets:
        return True
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in ipaddress.ip_network(n, strict=False) for n in nets)
