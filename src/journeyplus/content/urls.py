from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "omhide",
    "pubdate",
    "ref",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def canonicalize_url(url: str, *, extra_drop: set[str] | None = None) -> str:
    parts = urlsplit(url.strip())
    drop = TRACKING_PARAMETERS | {item.lower() for item in (extra_drop or set())}
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in drop
    ]
    scheme = parts.scheme.lower() or "https"
    hostname = (parts.hostname or "").lower()
    port = parts.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        hostname = f"{hostname}:{port}"
    path = parts.path or "/"
    return urlunsplit((scheme, hostname, path, urlencode(sorted(query)), ""))

