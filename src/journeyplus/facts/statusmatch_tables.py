from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from selectolax.parser import HTMLParser, Node

from journeyplus.contracts import EvidenceRef, StatusMapping
from journeyplus.sources.statusmatch_links import is_project_statusmatch_host


_SOURCE_HEADER_RE = re.compile(
    r"^(?:airline|hotel|hotels|cruise line|card type(?:/region)?|"
    r"your country of residence)$",
    re.IGNORECASE,
)
_EXCLUDED_HEADER_MARKERS = (
    "application fee",
    "country/region",
    "status tier",
    "timeline",
    "what you see",
)
_FOOTNOTE_MARKER_RE = re.compile(r"(?<!\*)\*{1,4}(?!\*)|\^")
_WHITESPACE_RE = re.compile(r"\s+")
_TARGET_OFFER_RE = re.compile(
    r"^(?P<program>.+?)\s+(?:silver|gold|platinum|diamond|titanium)\s+"
    r"status\s+offer$",
    re.IGNORECASE,
)


class MappingSourceCategory(StrEnum):
    AIRLINE = "AIRLINE"
    HOTEL = "HOTEL"
    CRUISE = "CRUISE"
    CARD = "CARD"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MappingSourceMetadata:
    source_program: str
    category: MappingSourceCategory
    table_index: int
    row_index: int


def extract_statusmatch_status_mappings(
    *,
    raw_html: str | None,
    canonical_url: str,
    document_version_id: UUID,
) -> list[StatusMapping]:
    if raw_html is None or not canonical_url.casefold().endswith("/faq"):
        return []
    host = canonical_url.split("/", 3)[2].casefold()
    if not is_project_statusmatch_host(host):
        return []

    tree = HTMLParser(raw_html)
    footnotes = _footnote_definitions(tree)
    mappings: list[StatusMapping] = []
    for table_index, table in enumerate(tree.css("table"), start=1):
        rows = [_cells(row) for row in table.css("tr")]
        rows = [row for row in rows if row]
        if len(rows) < 2:
            continue
        flat = _flat_program_tier_table(
            rows,
            canonical_url=canonical_url,
            document_version_id=document_version_id,
            table_index=table_index,
        )
        if flat is not None:
            mappings.extend(flat)
            continue
        matrix = _matrix_mapping_table(
            rows,
            footnotes=footnotes,
            canonical_url=canonical_url,
            document_version_id=document_version_id,
            table_index=table_index,
        )
        if matrix is not None:
            mappings.extend(matrix)
    return _deduplicate_mappings(mappings)


def extract_statusmatch_mapping_source_metadata(
    *,
    raw_html: str | None,
    canonical_url: str,
) -> list[MappingSourceMetadata]:
    """Return deterministic source categories without changing FactSet mappings."""
    if raw_html is None or not canonical_url.casefold().endswith("/faq"):
        return []
    host = canonical_url.split("/", 3)[2].casefold()
    if not is_project_statusmatch_host(host):
        return []

    tree = HTMLParser(raw_html)
    result: list[MappingSourceMetadata] = []
    seen: set[tuple[str, MappingSourceCategory]] = set()
    for table_index, table in enumerate(tree.css("table"), start=1):
        rows = [_cells(row) for row in table.css("tr")]
        rows = [row for row in rows if row]
        header_index = next(
            (
                index
                for index, row in enumerate(rows[:3])
                if len(row) >= 2 and _SOURCE_HEADER_RE.fullmatch(_cell_text(row[0]))
            ),
            None,
        )
        if header_index is None:
            continue
        header_text = [_cell_text(cell) for cell in rows[header_index]]
        if any(
            marker in " ".join(header_text).casefold()
            for marker in _EXCLUDED_HEADER_MARKERS
        ):
            continue
        category = _mapping_source_category(header_text[0])
        for row_index, row in enumerate(
            rows[header_index + 1 :], start=header_index + 2
        ):
            if len(row) < 2:
                continue
            source_program = _strip_markers(" ".join(_cell_lines(row[0])))
            if not source_program:
                continue
            key = (_normalize(source_program).casefold(), category)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                MappingSourceMetadata(
                    source_program=source_program,
                    category=category,
                    table_index=table_index,
                    row_index=row_index,
                )
            )
    return result


def _mapping_source_category(value: str) -> MappingSourceCategory:
    folded = _normalize(value).casefold()
    if folded == "airline":
        return MappingSourceCategory.AIRLINE
    if folded in {"hotel", "hotels"}:
        return MappingSourceCategory.HOTEL
    if folded == "cruise line":
        return MappingSourceCategory.CRUISE
    if folded in {"card type", "card type/region", "your country of residence"}:
        return MappingSourceCategory.CARD
    return MappingSourceCategory.UNKNOWN


def _flat_program_tier_table(
    rows: list[list[Node]],
    *,
    canonical_url: str,
    document_version_id: UUID,
    table_index: int,
) -> list[StatusMapping] | None:
    header = [_cell_text(cell) for cell in rows[0]]
    if len(header) != 2 or "existing programme" not in header[0].casefold():
        return None
    if "tier" not in header[0].casefold() or "tier" not in header[1].casefold():
        return None

    mappings: list[StatusMapping] = []
    for row_index, row in enumerate(rows[1:], start=2):
        if len(row) != 2:
            continue
        source = _cell_text(row[0])
        target = _cell_text(row[1])
        if not source or not target:
            continue
        source_program, source_tier = _split_flat_source(source, target)
        mappings.append(
            StatusMapping(
                source_program=source_program,
                source_tiers=[source_tier],
                target_tier=target,
                availability="AVAILABLE",
                evidence=[
                    _mapping_evidence(
                        document_version_id,
                        canonical_url,
                        table_index,
                        row_index,
                        source_program,
                        target,
                    )
                ],
            )
        )
    return mappings


def _matrix_mapping_table(
    rows: list[list[Node]],
    *,
    footnotes: dict[str, str],
    canonical_url: str,
    document_version_id: UUID,
    table_index: int,
) -> list[StatusMapping] | None:
    header_index = next(
        (
            index
            for index, row in enumerate(rows[:3])
            if len(row) >= 2 and _SOURCE_HEADER_RE.fullmatch(_cell_text(row[0]))
        ),
        None,
    )
    if header_index is None:
        return None
    header = rows[header_index]
    header_text = [_cell_text(cell) for cell in header]
    folded_header = " ".join(header_text).casefold()
    if any(marker in folded_header for marker in _EXCLUDED_HEADER_MARKERS):
        return None

    target_program = _target_program(rows, header_index)
    targets = [
        _target_details(cell, target_program, footnotes)
        for cell in header[1:]
    ]
    if not all(target for target in targets):
        return None

    mappings: list[StatusMapping] = []
    for row_index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if len(row) < 2:
            continue
        source_text = " ".join(_cell_lines(row[0]))
        source_program = _strip_markers(source_text)
        source_markers = _markers(source_text)
        if not source_program:
            continue
        for column, target in enumerate(targets, start=1):
            if column >= len(row):
                tier_lines: list[str] = []
                raw_cell_text = ""
            else:
                tier_lines = _cell_lines(row[column])
                raw_cell_text = _cell_text(row[column])
            target_tier, target_markers, target_conditions = target
            unavailable = not tier_lines or _is_unavailable(raw_cell_text)
            if unavailable:
                availability = "UNAVAILABLE"
                source_tiers: list[str] = []
                conditions = None
            else:
                cell_markers = _markers(raw_cell_text)
                source_tiers = [
                    cleaned
                    for line in tier_lines
                    if (cleaned := _strip_markers(line))
                    and not _is_unavailable(cleaned)
                ]
                if not source_tiers:
                    availability = "UNAVAILABLE"
                    conditions = None
                else:
                    markers = tuple(dict.fromkeys((*source_markers, *target_markers, *cell_markers)))
                    availability = "CONDITIONAL" if markers else "AVAILABLE"
                    conditions = (
                        _conditions_for_markers(
                            markers,
                            footnotes,
                            fallback=target_conditions,
                        )
                        if markers
                        else None
                    )
            mappings.append(
                StatusMapping(
                    source_program=source_program,
                    source_tiers=source_tiers,
                    target_tier=target_tier,
                    availability=availability,
                    conditions=conditions,
                    evidence=[
                        _mapping_evidence(
                            document_version_id,
                            canonical_url,
                            table_index,
                            row_index,
                            source_program,
                            target_tier,
                        )
                    ],
                )
            )
    return mappings


def _cells(row: Node) -> list[Node]:
    return [
        cell
        for cell in row.css("th, td")
        if cell.parent is not None and cell.parent.mem_id == row.mem_id
    ]


def _cell_lines(cell: Node) -> list[str]:
    return [
        normalized
        for value in cell.text(separator="\n", strip=True).splitlines()
        if (normalized := _normalize(value))
    ]


def _cell_text(cell: Node) -> str:
    return " ".join(_cell_lines(cell))


def _normalize(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _target_program(rows: list[list[Node]], header_index: int) -> str | None:
    if header_index == 0:
        return None
    title_row = rows[header_index - 1]
    if len(title_row) < 2 or _cell_text(title_row[0]):
        return None
    title = _cell_text(title_row[-1])
    if title.casefold().endswith(" tier"):
        return title[:-5].strip()
    offer = _TARGET_OFFER_RE.fullmatch(title)
    return offer.group("program").strip() if offer else None


def _target_details(
    cell: Node,
    target_program: str | None,
    footnotes: dict[str, str],
) -> tuple[str, tuple[str, ...], str | None] | None:
    raw_target = _cell_text(cell)
    markers = _markers(raw_target)
    target = _strip_markers(raw_target)
    target = re.sub(r"^eligible\s+for\s+", "", target, flags=re.IGNORECASE)
    if not target:
        return None
    if target_program and not target.casefold().startswith(target_program.casefold()):
        target = f"{target_program} {target}"
    return target, markers, _conditions_for_markers(markers, footnotes)


def _split_flat_source(source: str, target: str) -> tuple[str, str]:
    target_tier = target.rsplit(" ", 1)[-1]
    if source.casefold().endswith(f" {target_tier.casefold()}"):
        return source[: -(len(target_tier) + 1)].strip(), source[-len(target_tier) :]
    source_program, _, source_tier = source.rpartition(" ")
    return (source_program or source), (source_tier or source)


def _markers(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_FOOTNOTE_MARKER_RE.findall(value)))


def _strip_markers(value: str) -> str:
    return _normalize(_FOOTNOTE_MARKER_RE.sub("", value))


def _is_unavailable(value: str) -> bool:
    folded = _strip_markers(value).casefold()
    return folded in {"", "-", "n/a", "not available", "unavailable"}


def _footnote_definitions(tree: HTMLParser) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for node in tree.css("p, li"):
        text = _normalize(node.text(separator=" ", strip=True))
        matches = [
            match
            for match in _FOOTNOTE_MARKER_RE.finditer(text)
            if match.start() == 0 or text[match.start() - 1].isspace()
        ]
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            explanation = _normalize(text[match.end() : end])
            if explanation:
                definitions[match.group()] = explanation
    return definitions


def _conditions_for_markers(
    markers: tuple[str, ...],
    footnotes: dict[str, str],
    *,
    fallback: str | None = None,
) -> str | None:
    values = [footnotes[marker] for marker in markers if marker in footnotes]
    if not values and fallback:
        values.append(fallback)
    if not values and markers:
        values.append("表格包含脚注限制：" + "、".join(markers))
    return " ".join(dict.fromkeys(values))[:1000] or None


def _mapping_evidence(
    document_version_id: UUID,
    canonical_url: str,
    table_index: int,
    row_index: int,
    source_program: str,
    target_tier: str,
) -> EvidenceRef:
    return EvidenceRef(
        document_version_id=document_version_id,
        source_url=canonical_url,
        locator=(
            f"FAQ mapping table {table_index}, row {row_index}: "
            f"{source_program} -> {target_tier}"
        )[:500],
    )


def _deduplicate_mappings(mappings: list[StatusMapping]) -> list[StatusMapping]:
    deduplicated: dict[tuple[str, str], StatusMapping] = {}
    for mapping in mappings:
        key = (
            _normalize(mapping.source_program).casefold(),
            _normalize(mapping.target_tier).casefold(),
        )
        existing = deduplicated.get(key)
        if existing is None:
            deduplicated[key] = mapping
            continue
        source_tiers = list(dict.fromkeys((*existing.source_tiers, *mapping.source_tiers)))
        availability = (
            "CONDITIONAL"
            if "CONDITIONAL" in {existing.availability, mapping.availability}
            else (
                "AVAILABLE"
                if source_tiers
                else "UNAVAILABLE"
            )
        )
        conditions = (
            " ".join(
                dict.fromkeys(
                    value
                    for value in (existing.conditions, mapping.conditions)
                    if value
                )
            )[:1000]
            or None
        )
        if availability != "CONDITIONAL":
            conditions = None
        deduplicated[key] = existing.model_copy(
            update={
                "source_tiers": source_tiers,
                "availability": availability,
                "conditions": conditions,
                "evidence": _merge_evidence(existing, mapping),
            }
        )
    return list(deduplicated.values())


def _merge_evidence(
    first: StatusMapping, second: StatusMapping
) -> list[EvidenceRef]:
    merged: list[EvidenceRef] = []
    seen: set[tuple[str, str, str]] = set()
    for evidence in (*first.evidence, *second.evidence):
        key = (
            str(evidence.document_version_id),
            str(evidence.source_url).rstrip("/"),
            evidence.locator,
        )
        if key not in seen:
            seen.add(key)
            merged.append(evidence)
    return merged
