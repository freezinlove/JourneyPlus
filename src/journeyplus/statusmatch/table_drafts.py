"""Official-project table inputs and reference-based prose supplements.

References exist only within one extraction. Persisted facts keep their existing
schema; snapshots and the ordinary-article pipeline are never modified here.
"""
from __future__ import annotations

from types import SimpleNamespace

from selectolax.parser import HTMLParser

from journeyplus.content.cleaner import lightly_clean
from journeyplus.contracts import ApplicationRoute, RawDocument, RoutePrice, StatusMapping
from journeyplus.facts.statusmatch_prices import (
    extract_statusmatch_price_routes,
    statusmatch_current_document_body,
)
from journeyplus.facts.statusmatch_tables import extract_statusmatch_status_mappings
from journeyplus.models import DocumentVersion
from journeyplus.statusmatch.contracts import StatusMatchProjectExtraction


MAPPING_COLUMNS = [
    "ref", "source_program", "source_tiers", "target_tier", "availability",
    "conditions", "conflict", "conflict_note",
]
ROUTE_COLUMNS = [
    "ref", "scope", "eligibility", "region", "cost", "action_link",
    "conflict", "conflict_note", "prices",
]
PRICE_COLUMNS = ["ref", "target_tier", "amount", "currency", "availability", "raw_text"]


def table_drafts(mappings: list[StatusMapping], routes: list[ApplicationRoute]) -> dict:
    """Column names once, complete business values in every row, no citations."""
    mapping_rows = []
    for i, mapping in enumerate(mappings, 1):
        data = mapping.model_dump(mode="json") | {"ref": f"m{i}"}
        mapping_rows.append([data[column] for column in MAPPING_COLUMNS])
    route_rows = []
    for i, route in enumerate(routes, 1):
        prices = []
        for j, price in enumerate(route.prices, 1):
            data = price.model_dump(mode="json") | {"ref": f"p{j}"}
            prices.append([data[column] for column in PRICE_COLUMNS])
        data = route.model_dump(mode="json") | {"ref": f"r{i}", "prices": prices}
        route_rows.append([data[column] for column in ROUTE_COLUMNS])
    return {
        "deterministic_status_mappings": {
            "count": len(mappings), "columns": MAPPING_COLUMNS, "rows": mapping_rows,
        },
        "deterministic_price_routes": {
            "count": len(routes), "columns": ROUTE_COLUMNS,
            "price_columns": PRICE_COLUMNS, "rows": route_rows,
        },
    }


def read_table_drafts(request: dict) -> tuple[list[StatusMapping], list[ApplicationRoute]]:
    mappings = []
    for row in request["deterministic_status_mappings"]["rows"]:
        data = dict(zip(MAPPING_COLUMNS, row, strict=True))
        data.pop("ref")
        mappings.append(StatusMapping.model_validate(data))
    routes = []
    for row in request["deterministic_price_routes"]["rows"]:
        data = dict(zip(ROUTE_COLUMNS, row, strict=True))
        data.pop("ref")
        prices = []
        for price_row in data["prices"]:
            price = dict(zip(PRICE_COLUMNS, price_row, strict=True))
            price.pop("ref")
            prices.append(price)
        routes.append(ApplicationRoute.model_validate(data | {"prices": prices}))
    return mappings, routes


def model_document_body(document: DocumentVersion) -> str:
    """Remove only rows the parsers covered, leaving headings/notes/fallback rows."""
    current_body = statusmatch_current_document_body(document)
    if not document.raw_body:
        return current_body
    mapping_rows: dict[int, set[int]] = {}
    price_rows: dict[int, set[int]] = {}
    args = dict(raw_html=document.raw_body, canonical_url=document.canonical_url,
                document_version_id=document.id)
    extract_statusmatch_status_mappings(**args, parsed_table_rows=mapping_rows)
    extract_statusmatch_price_routes(**args, parsed_table_rows=price_rows)
    tree = HTMLParser(document.raw_body)
    changed = False
    for table_index, table in enumerate(tree.css("table"), 1):
        covered = mapping_rows.get(table_index, set()) | price_rows.get(table_index, set())
        # Nested tables are not a layout understood by these parsers.
        if not covered or table.css("table table"):
            continue
        for row_index, row in enumerate(table.css("tr"), 1):
            if row_index in covered:
                # Preserve inline links even when their containing row is parsed.
                # Rows with non-text annotations stay in the fallback view.
                if row.css("a, img, sup, abbr"):
                    continue
                row.decompose()
                changed = True
    if not changed:
        return current_body
    cleaned = lightly_clean(RawDocument(
        source_id="status_services_mail", external_id=f"table-draft:{document.id}",
        canonical_url=document.canonical_url, body=tree.html, content_type="text/html",
    ))
    # Apply the existing historical-fee exclusion after removing covered rows.
    view = SimpleNamespace(id=document.id, canonical_url=document.canonical_url, raw_body=tree.html,
                           normalized_body=cleaned.normalized_body)
    return statusmatch_current_document_body(view)


def _group_updates(updates, prefix: str, size: int) -> dict[int, list]:
    grouped: dict[int, list] = {}
    for update in updates:
        index = int(update.ref[len(prefix):]) - 1
        if not 0 <= index < size:
            raise ValueError(f"Unknown table reference {update.ref}; use this request's draft refs")
        grouped.setdefault(index, []).append(update)
    return grouped


def _changes(update, *, exclude: set[str] | None = None) -> dict:
    # Providers and cached Pydantic dumps often materialize omitted optionals as
    # null. Neither may erase a base value. Clearing is explicit and uncommon.
    values = update.model_dump(mode="json", exclude_none=True,
                               exclude={"ref", "clear_fields"} | (exclude or set()))
    for name in update.clear_fields:
        values[name] = "" if name == "raw_text" else None
    return values


def apply_table_updates(
    mappings: list[StatusMapping], routes: list[ApplicationRoute],
    extraction: StatusMatchProjectExtraction,
) -> tuple[list[StatusMapping], list[ApplicationRoute]]:
    """Apply patches by ref; untouched facts survive without being re-generated."""
    mapping_updates = _group_updates(extraction.mapping_updates, "m", len(mappings))
    updated_mappings = []
    for i, mapping in enumerate(mappings):
        if i not in mapping_updates:
            updated_mappings.append(mapping)
            continue
        for update in mapping_updates[i]:
            changes = _changes(update)
            if changes.get("availability") == "UNAVAILABLE":
                changes.update(source_tiers=[], conditions=None)
            elif changes.get("availability") == "AVAILABLE":
                changes["conditions"] = None
            if changes.get("conflict") is False:
                changes["conflict_note"] = None
            data = mapping.model_dump(mode="json") | changes
            if changes:
                data["evidence"] = []
            updated_mappings.append(StatusMapping.model_validate(data))

    route_updates = _group_updates(extraction.route_updates, "r", len(routes))
    updated_routes = []
    for i, route in enumerate(routes):
        if i not in route_updates:
            updated_routes.append(route)
            continue
        # Two updates referencing one base explicitly split it into two routes.
        for update in route_updates[i]:
            changes = _changes(update, exclude={"price_updates", "additional_prices"})
            price_updates = _group_updates(update.price_updates, "p", len(route.prices))
            prices = []
            for j, price in enumerate(route.prices):
                patches = price_updates.get(j, [])
                if len(patches) > 1:
                    raise ValueError(f"Repeated price reference p{j + 1} in {update.ref}")
                if not patches:
                    prices.append(price)
                    continue
                values = _changes(patches[0])
                if values.get("availability") == "UNAVAILABLE":
                    values.update(amount=None, currency=None)
                data = price.model_dump(mode="json") | values
                if values:
                    data["evidence"] = []
                    data["raw_text"] = values.get("raw_text") or ""
                prices.append(RoutePrice.model_validate(data))
            prices.extend(RoutePrice.model_validate(p.model_dump(mode="json", exclude={"evidence"}))
                          for p in update.additional_prices)
            if changes.get("conflict") is False:
                changes["conflict_note"] = None
            data = route.model_dump(mode="json") | changes
            data["prices"] = [price.model_dump(mode="json") for price in prices]
            if changes or update.price_updates or update.additional_prices:
                data["evidence"] = []
            updated_routes.append(ApplicationRoute.model_validate(data))
    return updated_mappings, updated_routes
