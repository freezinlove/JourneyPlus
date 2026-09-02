from __future__ import annotations

import base64
import re
import zlib
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

from selectolax.parser import HTMLParser, Node


_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRACKING_HOSTS = {"email.mail.statusmatch.com", "mail.statusmatch.com"}
_GENERIC_SUBDOMAINS = {
    "email",
    "help",
    "mail",
    "support",
    "www",
}
_REDIRECT_QUERY_KEYS = (
    "l",
    "link",
    "url",
    "target",
    "redirect",
    "redirect_url",
)
_MAX_TRACKING_TOKEN_LENGTH = 16_384
_MAX_DECOMPRESSED_LENGTH = 65_536


@dataclass(frozen=True, slots=True)
class StatusMatchProjectLink:
    host: str
    canonical_url: str
    labels: tuple[str, ...] = ()


def extract_statusmatch_project_links(
    body: str,
    *,
    content_type: str,
) -> tuple[StatusMatchProjectLink, ...]:
    """Find useful project links without making any tracking-network requests."""

    labels_by_host: dict[str, set[str]] = {}
    candidate_urls: list[tuple[str, str]] = []
    if "html" in content_type.casefold() or "<a" in body.casefold():
        tree = HTMLParser(body)
        for anchor in tree.css("a[href]"):
            href = str(anchor.attributes.get("href") or "").strip()
            if href:
                candidate_urls.append((href, _anchor_label(anchor)))
    candidate_urls.extend((match, "") for match in _URL_RE.findall(body))

    for raw_url, label in candidate_urls:
        canonical = canonical_statusmatch_project_url(raw_url)
        if canonical is None:
            continue
        host = urlsplit(canonical).hostname
        assert host is not None
        normalized_label = " ".join(label.split())
        labels_by_host.setdefault(host, set())
        if normalized_label:
            labels_by_host[host].add(normalized_label[:300])

    return tuple(
        StatusMatchProjectLink(
            host=host,
            canonical_url=f"https://{host}/",
            labels=tuple(sorted(labels)),
        )
        for host, labels in sorted(labels_by_host.items())
    )


def canonical_statusmatch_project_url(raw_url: str) -> str | None:
    unwrapped = unwrap_statusmatch_tracking_url(raw_url)
    parsed = urlsplit(unwrapped)
    if parsed.scheme.casefold() != "https" or parsed.username or parsed.password:
        return None
    if parsed.port not in {None, 443}:
        return None
    host = (parsed.hostname or "").casefold().rstrip(".")
    if not is_project_statusmatch_host(host):
        return None
    return f"https://{host}/"


def unwrap_statusmatch_tracking_url(raw_url: str, *, max_depth: int = 6) -> str:
    current = raw_url.strip().replace("&amp;", "&")
    for _ in range(max_depth):
        parsed = urlsplit(current)
        host = (parsed.hostname or "").casefold().rstrip(".")
        nested = _query_redirect(parsed.query)
        if host in _TRACKING_HOSTS and parsed.path.startswith("/c/"):
            token = parsed.path.split("/c/", 1)[1].split("/", 1)[0]
            decoded = _decode_tracking_token(token)
            nested = _query_redirect(decoded) if decoded is not None else nested
        if nested is None or nested == current:
            return current
        current = nested
    return current


def normalized_statusmatch_mail_html(body: str) -> str:
    """Keep visible mail text while exposing only safe project hyperlinks."""

    tree = HTMLParser(body)
    for anchor in list(tree.css("a[href]")):
        href = str(anchor.attributes.get("href") or "").strip()
        canonical = canonical_statusmatch_project_url(href)
        if canonical is not None:
            anchor.attrs["href"] = canonical
            continue
        label = _anchor_label(anchor)
        if label:
            anchor.replace_with(label)
        else:
            anchor.decompose()
    root = tree.body or tree.root
    return root.html if root is not None else body


def statusmatch_project_page_urls(host: str) -> tuple[tuple[str, str], ...]:
    if not is_project_statusmatch_host(host):
        raise ValueError("StatusMatch page host is not project-specific")
    return (
        ("activity", f"https://{host}/"),
        ("faq", f"https://{host}/faq"),
        ("terms", f"https://{host}/terms"),
    )


def is_project_statusmatch_host(host: str) -> bool:
    suffix = ".statusmatch.com"
    if not host.endswith(suffix):
        return False
    project = host[: -len(suffix)]
    return (
        bool(project)
        and "." not in project
        and project not in _GENERIC_SUBDOMAINS
        and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", project) is not None
    )


def _anchor_label(anchor: Node) -> str:
    values = [anchor.text(separator=" ", strip=True)]
    values.extend(str(image.attributes.get("alt") or "") for image in anchor.css("img"))
    return " ".join(" ".join(values).split())


def _query_redirect(query: str) -> str | None:
    if not query:
        return None
    parsed = parse_qs(query, keep_blank_values=False)
    for key in _REDIRECT_QUERY_KEYS:
        values = parsed.get(key)
        if not values:
            continue
        candidate = unquote(values[-1]).strip()
        if candidate.casefold().startswith("https://"):
            return candidate
    return None


def _decode_tracking_token(token: str) -> str | None:
    if not token or len(token) > _MAX_TRACKING_TOKEN_LENGTH:
        return None
    try:
        padding = "=" * (-len(token) % 4)
        compressed = base64.urlsafe_b64decode(token + padding)
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(
            compressed, _MAX_DECOMPRESSED_LENGTH + 1
        )
        if (
            len(decoded) > _MAX_DECOMPRESSED_LENGTH
            or decompressor.unconsumed_tail
        ):
            return None
        decoded += decompressor.flush()
        if len(decoded) > _MAX_DECOMPRESSED_LENGTH:
            return None
        return decoded.decode("utf-8", errors="strict")
    except (ValueError, UnicodeDecodeError, zlib.error):
        return None
