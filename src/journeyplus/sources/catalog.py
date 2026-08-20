from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from markdownify import markdownify
from selectolax.parser import HTMLParser, Node

from journeyplus.content.urls import canonicalize_url
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.sources.base import Fetcher


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    section: str
    program: str
    text: str
    action_urls: tuple[str, ...] = ()
    discarded_urls: tuple[str, ...] = ()
    raw_html: str = ""

    @property
    def action_url(self) -> str | None:
        return self.action_urls[0] if self.action_urls else None

    @property
    def record_hash(self) -> str:
        return hashlib.sha256(_normalized(self.text).encode()).hexdigest()

    @property
    def stable_key(self) -> str:
        action = canonicalize_url(self.action_url) if self.action_url else self.record_hash
        return f"{_normalized(self.section)}|{_normalized(self.program)}|{action}"


class StaticCatalogAdapter:
    source_id = "ffb_status_match_catalog"

    def __init__(self, *, catalog_url: str, fetcher: Fetcher) -> None:
        self.catalog_url = catalog_url
        self._fetcher = fetcher

    def discover(self) -> list[DiscoveredItem]:
        response = self._fetcher.get(self.catalog_url)
        records = parse_catalog_records(response.body, response.final_url)
        page_updated = _page_updated(response.body)
        results: list[DiscoveredItem] = []
        for record in records:
            external_id = hashlib.sha256(record.stable_key.encode()).hexdigest()
            record_url = (
                canonicalize_url(record.action_url)
                if record.action_url
                else f"{canonicalize_url(response.final_url)}#record-{external_id[:16]}"
            )
            results.append(
                DiscoveredItem(
                    source_id=self.source_id,
                    external_id=external_id,
                    discovered_url=self.catalog_url,
                    canonical_url=record_url,
                    title=record.program,
                    discovery_fingerprint=record.record_hash,
                    raw_metadata={
                        "section": record.section,
                        "program": record.program,
                        "record_text": record.text,
                        "action_url": record.action_url,
                        "action_urls": list(record.action_urls),
                        "discarded_urls": list(record.discarded_urls),
                        "record_hash": record.record_hash,
                        "page_updated": page_updated,
                        "catalog_url": canonicalize_url(response.final_url),
                    },
                )
            )
        return results

    def fetch(self, item: DiscoveredItem) -> RawDocument:
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=str(item.raw_metadata["record_text"]),
            content_type="text/markdown",
            metadata={
                key: item.raw_metadata.get(key)
                for key in (
                    "section",
                    "program",
                    "action_url",
                    "action_urls",
                    "discarded_urls",
                    "page_updated",
                )
            },
        )


def parse_catalog_records(html: str, base_url: str) -> list[CatalogRecord]:
    tree = HTMLParser(html)
    annotated = tree.css("[data-status-record]")
    if annotated:
        return [_record_from_node(node, base_url) for node in annotated]

    records: list[CatalogRecord] = []
    for table in tree.css("table"):
        if _is_nested_table(table):
            continue
        section = _section_from_table(table)
        for row in _direct_table_rows(table):
            program_cell = row.css_first("th[scope='row']")
            cells = row.css("td")
            if program_cell is not None and cells:
                program = program_cell.text(separator=" ", strip=True)
                offer_text, action_urls, discarded_urls = _catalog_markdown(
                    cells[0].html, base_url=base_url, program=program
                )
                if program and offer_text:
                    records.append(
                        CatalogRecord(
                            section=section,
                            program=program,
                            text=offer_text,
                            action_urls=action_urls,
                            discarded_urls=discarded_urls,
                            raw_html=cells[0].html,
                        )
                    )
                continue
            if len(cells) < 2:
                continue
            program = cells[0].text(separator=" ", strip=True)
            html_content = "<div>" + "".join(cell.html for cell in cells[1:]) + "</div>"
            text, action_urls, discarded_urls = _catalog_markdown(
                html_content, base_url=base_url, program=program
            )
            records.append(
                CatalogRecord(
                    section=section,
                    program=program,
                    text=text,
                    action_urls=action_urls,
                    discarded_urls=discarded_urls,
                    raw_html=html_content,
                )
            )
    return [record for record in records if record.program and record.text]


def _direct_table_rows(table: Node) -> list[Node]:
    """Return only rows owned by this table, excluding rows in nested tables."""

    rows: list[Node] = []
    child = table.child
    while child is not None:
        if child.tag == "tr":
            rows.append(child)
        elif child.tag in {"thead", "tbody", "tfoot"}:
            row = child.child
            while row is not None:
                if row.tag == "tr":
                    rows.append(row)
                row = row.next
        child = child.next
    return rows


def _is_nested_table(table: Node) -> bool:
    parent = table.parent
    while parent is not None:
        if parent.tag == "table":
            return True
        parent = parent.parent
    return False


def _section_from_table(table: Node) -> str:
    configured = table.attributes.get("data-section")
    if configured:
        return configured
    heading = table.css_first("thead h1, thead h2, thead h3, thead th")
    label = heading.text(separator=" ", strip=True).casefold() if heading else ""
    if "airline" in label:
        return "airline"
    if "hotel" in label:
        return "hotel"
    if "car" in label or "rental" in label:
        return "car"
    return "unspecified"


def _record_from_node(node: Node, base_url: str) -> CatalogRecord:
    program = node.attributes.get("data-program")
    if not program:
        heading = node.css_first("h2, h3, h4, strong")
        program = heading.text(separator=" ", strip=True) if heading else "Unknown program"
    text, action_urls, discarded_urls = _catalog_markdown(
        node.html, base_url=base_url, program=program
    )
    return CatalogRecord(
        section=node.attributes.get("data-section", "unspecified"),
        program=program,
        text=text,
        action_urls=action_urls,
        discarded_urls=discarded_urls,
        raw_html=node.html,
    )


def _catalog_markdown(
    html: str, *, base_url: str, program: str
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Keep the semantic record and its actionable links, not catalog page chrome."""

    tree = HTMLParser(html)
    root = tree.body or tree.root
    if root is None:
        return program, (), ()
    for image in root.css("img"):
        image.decompose()

    kept: list[str] = []
    discarded: list[str] = []
    seen: set[str] = set()
    for link in list(root.css("a[href]")):
        raw_href = str(link.attributes.get("href") or "").strip()
        label = " ".join(link.text(separator=" ", strip=True).split())
        if not raw_href:
            link.unwrap()
            continue
        absolute = urljoin(base_url, raw_href)
        normalized_label = label.casefold()
        if not label:
            discarded.append(absolute)
            link.unwrap()
            continue
        if (
            _normalized(program) == "enterprise plus"
            and "book all your enterprise rentals" in normalized_label
        ):
            discarded.append(absolute)
            parent = link.parent
            if parent is not None and parent.tag == "p":
                parent.decompose()
            else:
                link.decompose()
            continue
        dedupe_key = canonicalize_url(absolute)
        if dedupe_key in seen:
            discarded.append(absolute)
            link.unwrap()
            continue
        seen.add(dedupe_key)
        kept.append(absolute)
        link.attrs["href"] = absolute

    markdown = markdownify(root.html, heading_style="ATX").strip()
    markdown = re.sub(r"[ \t]+", " ", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    text = f"{program}\n\n{markdown}" if markdown else program
    return text, tuple(kept), tuple(discarded)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _page_updated(html: str) -> str | None:
    match = re.search(r"(?:last\s+updated|updated)\s*:?\s*([^<\n]{4,80})", html, re.I)
    return match.group(1).strip() if match else None
