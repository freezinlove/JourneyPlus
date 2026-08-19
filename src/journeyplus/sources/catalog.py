from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from selectolax.parser import HTMLParser, Node

from journeyplus.content.urls import canonicalize_url
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.sources.base import Fetcher


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    section: str
    program: str
    text: str
    action_url: str | None

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
            content_type="text/plain",
            metadata={
                key: item.raw_metadata.get(key)
                for key in ("section", "program", "action_url", "page_updated")
            },
        )


def parse_catalog_records(html: str, base_url: str) -> list[CatalogRecord]:
    tree = HTMLParser(html)
    annotated = tree.css("[data-status-record]")
    if annotated:
        return [_record_from_node(node, base_url) for node in annotated]

    records: list[CatalogRecord] = []
    for table in tree.css("table"):
        section = _section_from_table(table)
        for row in table.css("tr"):
            program_cell = row.css_first("th[scope='row']")
            cells = row.css("td")
            if program_cell is not None and cells:
                program = program_cell.text(separator=" ", strip=True)
                offer_text = cells[0].text(separator="\n", strip=True)
                if program and offer_text:
                    records.append(
                        CatalogRecord(
                            section=section,
                            program=program,
                            text=f"{program}\n{offer_text}",
                            action_url=_first_link(cells[0], base_url),
                        )
                    )
                continue
            if len(cells) < 2:
                continue
            text = "\n".join(cell.text(separator=" ", strip=True) for cell in cells)
            action = _first_link(row, base_url)
            records.append(
                CatalogRecord(
                    section=section,
                    program=cells[0].text(separator=" ", strip=True),
                    text=text,
                    action_url=action,
                )
            )
    return [record for record in records if record.program and record.text]


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
    return CatalogRecord(
        section=node.attributes.get("data-section", "unspecified"),
        program=program,
        text=node.text(separator="\n", strip=True),
        action_url=_first_link(node, base_url),
    )


def _first_link(node: Node, base_url: str) -> str | None:
    from urllib.parse import urljoin

    link = node.css_first("a[href]")
    return urljoin(base_url, link.attributes["href"]) if link else None


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _page_updated(html: str) -> str | None:
    match = re.search(r"(?:last\s+updated|updated)\s*:?\s*([^<\n]{4,80})", html, re.I)
    return match.group(1).strip() if match else None
