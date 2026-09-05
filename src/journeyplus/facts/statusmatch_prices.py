from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from selectolax.parser import HTMLParser, Node

from journeyplus.content.cleaner import lightly_clean
from journeyplus.contracts import (
    ApplicationRoute,
    EvidenceRef,
    FactField,
    FactSet,
    RawDocument,
    RoutePrice,
    RoutePriceAvailability,
)
from journeyplus.models import DocumentVersion
from journeyplus.sources.statusmatch_links import is_project_statusmatch_host


_HISTORICAL_HEADING_RE = re.compile(r"\brecently\s+ended\s+offers?\b", re.I)
_STATUS_HEADER_RE = re.compile(r"\bstatus\s+tier\b|\btier$", re.I)
_FEE_HEADER_RE = re.compile(r"\bapplication\s+fee\b", re.I)
_SCOPE_HEADER_RE = re.compile(
    r"(?:country|region|residence|airline|hotel|card|membership|programme|program|scope|type)",
    re.I,
)
_GENERIC_CONTEXT_RE = re.compile(
    r"(?:status\s+match\s+)?terms(?:\s*(?:&|and)\s*conditions)?$"
    r"|terms\s*(?:&|and)\s*conditions$",
    re.I,
)
_LISTED_CURRENCY_RE = re.compile(r"listed\s+in\s+(?P<currency>[A-Z]{3})", re.I)
_UNAVAILABLE_RE = re.compile(r"(?:not\s+available|unavailable|不可用|不可申请)", re.I)
_SUBSET_UNAVAILABLE_RE = re.compile(
    r"not\s+available\s+for\s+(?P<regions>.+?)\s*[.!;]*$",
    re.I,
)
_CONDITIONAL_RE = re.compile(
    r"(?:additional|optional|select\s+members?|only|subject\s+to|except|\*|\^)"
    r"|not\s+available\s+for|部分申请人|可选|额外|另付|仅限",
    re.I,
)
_CURRENCY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bUSD\b|US\$|\$", re.I), "USD"),
    (re.compile(r"\bEUR\b|€", re.I), "EUR"),
    (re.compile(r"\bCAD\b|C\$", re.I), "CAD"),
    (re.compile(r"\bGBP\b|£", re.I), "GBP"),
    (re.compile(r"\bAUD\b|A\$", re.I), "AUD"),
    (re.compile(r"\bCNY\b|\bRMB\b|¥", re.I), "CNY"),
    (re.compile(r"\bAED\b", re.I), "AED"),
    (re.compile(r"\bJPY\b", re.I), "JPY"),
)
_AMOUNT_RE = re.compile(
    r"(?<![\d.])([0-9]{1,9}(?:,[0-9]{3})*(?:\.[0-9]{1,4})?)(?![\d.])"
)
_EXPLICIT_FREE_RE = re.compile(
    r"(?:"
    r"no\s+(?:status\s+match\s+|application\s+|matching\s+)?fees?"
    r"|no\s+fees?\s+(?:is\s+)?payable"
    r"|(?:status\s+match|application)\s+(?:is\s+)?free"
    r"|free\s+status\s+match"
    r")",
    re.I,
)
_EXPLICIT_PAID_RE = re.compile(
    r"(?:"
    r"application\s+fees?\s+(?:apply|applies|start|starts|vary|varies|differ|differs)"
    r"|pay(?:ment\s+of)?\s+(?:the\s+|an?\s+)?(?:application|relevant)\s+fees?"
    r"|(?:application|status\s+match)\s+fees?\s+(?:of|from|starting\s+at)"
    r"|purchase\s+commitment"
    r")",
    re.I,
)
_NUMERIC_FEE_RE = re.compile(
    r"(?:application|status\s+match|upgrade)\s+fees?.{0,80}"
    r"(?:USD|EUR|CAD|GBP|AUD|CNY|RMB|AED|JPY|US\$|C\$|A\$|[$€£¥])\s*\d"
    r"|(?:USD|EUR|CAD|GBP|AUD|CNY|RMB|AED|JPY|US\$|C\$|A\$|[$€£¥])\s*\d"
    r".{0,80}(?:application|status\s+match|upgrade)\s+fees?",
    re.I,
)


def extract_statusmatch_price_routes(
    *,
    raw_html: str | None,
    canonical_url: str,
    document_version_id: UUID,
) -> list[ApplicationRoute]:
    """Deterministically parse current StatusMatch application-fee tables."""
    if raw_html is None:
        return []
    folded_url = canonical_url.casefold().rstrip("/")
    if not (folded_url.endswith("/faq") or folded_url.endswith("/terms")):
        return []
    host = canonical_url.split("/", 3)[2].casefold()
    if not is_project_statusmatch_host(host):
        return []

    tree = HTMLParser(raw_html)
    historical = False
    current_heading: str | None = None
    table_index = 0
    routes: list[ApplicationRoute] = []
    root = tree.body or tree.root
    if root is None:
        return []
    for node in root.traverse(include_text=False):
        if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            heading = _text(node)
            if _HISTORICAL_HEADING_RE.search(heading):
                historical = True
            elif heading:
                current_heading = heading
            continue
        if node.tag != "table":
            continue
        table_index += 1
        if historical:
            continue
        parsed = _parse_fee_table(
            node,
            context=current_heading,
            canonical_url=canonical_url,
            document_version_id=document_version_id,
            table_index=table_index,
        )
        routes.extend(parsed)
    return merge_statusmatch_application_routes([], routes)


def statusmatch_current_document_body(document: DocumentVersion) -> str:
    """Build the current-only text view used by AI and fee-signal policy.

    The persisted snapshot remains untouched. Only historical application-fee
    tables below ``Recently ended offers`` are removed; later status-mapping
    content stays available to the project workflow.
    """
    if document.raw_body:
        tree = HTMLParser(document.raw_body)
        root = tree.body or tree.root
        if root is not None:
            historical = False
            changed = False
            candidates = [
                node
                for node in root.traverse(include_text=False)
                if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6", "table"}
            ]
            for node in candidates:
                if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                    if _HISTORICAL_HEADING_RE.search(_text(node)):
                        historical = True
                        node.decompose()
                        changed = True
                    continue
                if historical and _fee_header_index(_table_rows(node)) is not None:
                    node.decompose()
                    changed = True
            if changed:
                scoped = lightly_clean(
                    RawDocument(
                        source_id="status_services_mail",
                        external_id=f"statusmatch-current:{document.id}",
                        canonical_url=document.canonical_url,
                        body=root.html,
                        content_type="text/html",
                    )
                )
                return scoped.normalized_body
    return _remove_historical_fee_tables_from_markdown(document.normalized_body)


def merge_statusmatch_application_routes(
    deterministic: list[ApplicationRoute],
    narrative: list[ApplicationRoute],
) -> list[ApplicationRoute]:
    merged: dict[str, ApplicationRoute] = {}
    order: list[str] = []
    for raw_route in [*deterministic, *narrative]:
        route = _normalize_conditional_prices(raw_route)
        key = _normalize(route.scope).casefold()
        existing = merged.get(key)
        if existing is None:
            merged[key] = route
            order.append(key)
            continue
        evidence = _merge_evidence(existing.evidence, route.evidence)
        prices = _merge_prices(existing.prices, route.prices)
        conflicts = _price_conflicts(prices)
        inherited_conflict = existing.conflict or route.conflict
        conflict = inherited_conflict or bool(conflicts)
        notes = [existing.conflict_note, route.conflict_note]
        if conflicts:
            notes.append("FAQ、TERMS 或正文对同一申请范围和等级给出不同当前价格，需要人工复核。")
        merged[key] = existing.model_copy(
            update={
                "eligibility": existing.eligibility or route.eligibility,
                "region": existing.region or route.region,
                "cost": existing.cost or route.cost,
                "prices": prices,
                "action_link": existing.action_link or route.action_link,
                "evidence": evidence,
                "conflict": conflict,
                "conflict_note": " ".join(
                    dict.fromkeys(note for note in notes if note)
                )
                if conflict
                else None,
            }
        )
    return [merged[key] for key in order]


def filter_redundant_statusmatch_narrative_routes(
    narrative: list[ApplicationRoute],
    deterministic: list[ApplicationRoute],
) -> list[ApplicationRoute]:
    """Keep narrative-only prices without duplicating parsed fee-table routes."""
    deterministic_prices = {
        _price_signature(price)
        for route in deterministic
        for price in route.prices
    }
    if not deterministic_prices:
        return narrative
    result: list[ApplicationRoute] = []
    for route in narrative:
        if not route.prices:
            result.append(route)
            continue
        unique_prices = [
            price
            for price in route.prices
            if _price_signature(price) not in deterministic_prices
        ]
        if unique_prices:
            result.append(route.model_copy(update={"prices": unique_prices}))
    return result


def apply_statusmatch_fee_policy(
    fact_set: FactSet,
    documents: list[DocumentVersion],
) -> FactSet:
    """Normalize project-level fee meaning after closure has already been excluded."""
    text_by_document = {
        document.id: " ".join(statusmatch_current_document_body(document).split())
        for document in documents
    }
    free_evidence = _signal_evidence(documents, text_by_document, _EXPLICIT_FREE_RE)
    paid_evidence = _signal_evidence(
        documents,
        text_by_document,
        re.compile(
            rf"(?:{_EXPLICIT_PAID_RE.pattern})|(?:{_NUMERIC_FEE_RE.pattern})",
            re.I,
        ),
    )
    price_evidence = _merge_evidence(
        [],
        [
            evidence
            for route in fact_set.application_routes
            for price in route.prices
            if price.amount is not None
            for evidence in price.evidence
        ],
    )
    has_amount = bool(price_evidence) or _fact_cost_has_amount(fact_set.cost.value)

    if free_evidence and paid_evidence:
        cost = FactField(
            value=None,
            evidence=_merge_evidence(free_evidence, paid_evidence),
            conflict=True,
            alternatives=["免费", "付费"],
        )
    elif has_amount:
        cost = fact_set.cost
        if cost.value is None:
            cost = FactField(
                value="费用因申请路线和目标等级而异",
                evidence=price_evidence,
            )
    elif paid_evidence:
        cost = FactField(value="收费，金额未公布", evidence=paid_evidence)
    elif free_evidence:
        cost = FactField(value="免费", evidence=free_evidence)
    else:
        # Absence is not evidence of zero cost, even with all three pages present.
        cost = FactField()
    return fact_set.model_copy(update={"cost": cost})


def _parse_fee_table(
    table: Node,
    *,
    context: str | None,
    canonical_url: str,
    document_version_id: UUID,
    table_index: int,
) -> list[ApplicationRoute]:
    rows = _table_rows(table)
    header_index = _fee_header_index(rows)
    if header_index is None:
        return []
    header = rows[header_index]
    status_index = next(
        index for index, value in enumerate(header) if _STATUS_HEADER_RE.search(value)
    )
    fee_index = next(
        index for index, value in enumerate(header) if _FEE_HEADER_RE.search(value)
    )
    scope_index = next(
        (
            index
            for index, value in enumerate(header)
            if index not in {status_index, fee_index} and _SCOPE_HEADER_RE.search(value)
        ),
        None,
    )
    inherited_scope = ""
    inherited_currency = header[fee_index]
    grouped: dict[tuple[str, str | None], list[RoutePrice]] = {}
    group_order: list[tuple[str, str | None]] = []
    subset_unavailable: dict[
        tuple[str, str | None],
        list[tuple[str | None, list[str], str, EvidenceRef]],
    ] = {}
    last_price_key: tuple[str, str | None] | None = None
    for row_index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if len(row) == 1 and row[0]:
            currency_match = _LISTED_CURRENCY_RE.search(row[0])
            if currency_match is not None:
                inherited_currency = (
                    f"{header[fee_index]} {currency_match.group('currency').upper()}"
                )
                continue
            if (
                last_price_key is not None
                and _UNAVAILABLE_RE.search(row[0])
                and grouped[last_price_key]
            ):
                previous = grouped[last_price_key][-1]
                unavailable_regions = _unavailable_subset_regions(
                    row[0], last_price_key[1]
                )
                if unavailable_regions:
                    subset_unavailable.setdefault(last_price_key, []).append(
                        (
                            previous.target_tier,
                            unavailable_regions,
                            row[0],
                            EvidenceRef(
                                document_version_id=document_version_id,
                                source_url=canonical_url,
                                locator=(
                                    f"当前费用表 {table_index} 第 {row_index} 行："
                                    f"{row[0]}"
                                )[:500],
                            ),
                        )
                    )
                    continue
                grouped[last_price_key][-1] = previous.model_copy(
                    update={
                        "availability": RoutePriceAvailability.CONDITIONAL,
                        "raw_text": f"{previous.raw_text}; {row[0]}"[:1000],
                    }
                )
                continue
            inherited_scope = row[0]
            continue
        if max(status_index, fee_index) >= len(row):
            continue
        if scope_index is not None and scope_index < len(row) and row[scope_index]:
            inherited_scope = row[scope_index]
        tier = _clean_tier(row[status_index])
        raw_fee = row[fee_index]
        if not tier or not raw_fee:
            continue
        row_scope = inherited_scope or ""
        scope = _combined_scope(context, row_scope)
        region = row_scope or None
        price_evidence = EvidenceRef(
            document_version_id=document_version_id,
            source_url=canonical_url,
            locator=(
                f"当前费用表 {table_index} 第 {row_index} 行："
                f"{scope} / {tier} / {raw_fee}"
            )[:500],
        )
        unavailable_regions = _unavailable_subset_regions(raw_fee, region)
        parsed_fee = (
            _SUBSET_UNAVAILABLE_RE.sub("", raw_fee).strip(" ;,.-")
            if unavailable_regions
            else raw_fee
        )
        price = _route_price(
            tier=tier,
            raw_fee=parsed_fee,
            fee_header=inherited_currency,
            evidence=price_evidence,
        )
        if price is None:
            continue
        key = (scope, region)
        if key not in grouped:
            grouped[key] = []
            group_order.append(key)
        grouped[key].append(price)
        if unavailable_regions:
            subset_unavailable.setdefault(key, []).append(
                (tier, unavailable_regions, raw_fee, price_evidence)
            )
        last_price_key = key
    routes: list[ApplicationRoute] = []
    for scope, region in group_order:
        prices = _merge_prices([], grouped[(scope, region)])
        routes.extend(
            _split_subset_unavailable_routes(
                scope=scope,
                region=region,
                prices=prices,
                exceptions=subset_unavailable.get((scope, region), []),
            )
        )
    return routes


def _table_rows(table: Node) -> list[list[str]]:
    rows = [[_text(cell) for cell in row.css("th, td")] for row in table.css("tr")]
    return [row for row in rows if any(row)]


def _fee_header_index(rows: list[list[str]]) -> int | None:
    return next(
        (
            index
            for index, row in enumerate(rows[:4])
            if any(_STATUS_HEADER_RE.search(cell) for cell in row)
            and any(_FEE_HEADER_RE.search(cell) for cell in row)
        ),
        None,
    )


def _remove_historical_fee_tables_from_markdown(value: str) -> str:
    lines = value.splitlines()
    result: list[str] = []
    historical = False
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = line.strip().strip("#*_ ")
        if _HISTORICAL_HEADING_RE.fullmatch(heading):
            historical = True
            index += 1
            continue
        if historical and line.lstrip().startswith("|"):
            end = index
            while end < len(lines) and lines[end].lstrip().startswith("|"):
                end += 1
            block = lines[index:end]
            joined = " ".join(block)
            if _STATUS_HEADER_RE.search(joined) and _FEE_HEADER_RE.search(joined):
                index = end
                continue
            result.extend(block)
            index = end
            continue
        result.append(line)
        index += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(result)).strip()


def _split_subset_unavailable_routes(
    *,
    scope: str,
    region: str | None,
    prices: list[RoutePrice],
    exceptions: list[tuple[str | None, list[str], str, EvidenceRef]],
) -> list[ApplicationRoute]:
    def route(route_scope: str, route_region: str | None, route_prices: list[RoutePrice]):
        return ApplicationRoute(
            scope=route_scope,
            region=route_region,
            prices=route_prices,
            evidence=_merge_evidence(
                [],
                [
                    evidence
                    for price in route_prices
                    for evidence in price.evidence
                ],
            ),
        )

    if not exceptions or region is None:
        return [route(scope, region, prices)]
    region_parts = _split_region_names(region)
    excluded = {
        _normalize(name).casefold()
        for _, names, _, _ in exceptions
        for name in names
    }
    remaining = [
        name for name in region_parts if _normalize(name).casefold() not in excluded
    ]
    result: list[ApplicationRoute] = []
    if remaining:
        remaining_region = ", ".join(remaining)
        result.append(
            route(
                _replace_scope_region(scope, region, remaining_region),
                remaining_region,
                prices,
            )
        )
    for target_tier, names, note, note_evidence in exceptions:
        unavailable_region = ", ".join(names)
        unavailable_prices = [
            price.model_copy(
                update={
                    "amount": None,
                    "currency": None,
                    "availability": RoutePriceAvailability.UNAVAILABLE,
                    "raw_text": f"{price.raw_text}; {note}"[:1000],
                    "evidence": _merge_evidence(
                        price.evidence, [note_evidence]
                    ),
                }
            )
            if _normalize(price.target_tier or "").casefold()
            == _normalize(target_tier or "").casefold()
            else price
            for price in prices
        ]
        result.append(
            route(
                _replace_scope_region(scope, region, unavailable_region),
                unavailable_region,
                unavailable_prices,
            )
        )
    return result


def _normalize_conditional_prices(route: ApplicationRoute) -> ApplicationRoute:
    prices = [
        price.model_copy(
            update={"availability": RoutePriceAvailability.CONDITIONAL}
        )
        if price.availability == RoutePriceAvailability.AVAILABLE
        and _CONDITIONAL_RE.search(price.raw_text)
        else price
        for price in route.prices
    ]
    if prices == route.prices:
        return route
    return route.model_copy(update={"prices": prices})


def _unavailable_subset_regions(text: str, region: str | None) -> list[str]:
    if region is None:
        return []
    match = _SUBSET_UNAVAILABLE_RE.search(_normalize(text))
    if match is None:
        return []
    region_parts = _split_region_names(region)
    known = {_normalize(name).casefold(): name for name in region_parts}
    requested = _split_region_names(match.group("regions"))
    resolved = [
        known[_normalize(name).casefold()]
        for name in requested
        if _normalize(name).casefold() in known
    ]
    return list(dict.fromkeys(resolved))


def _split_region_names(value: str) -> list[str]:
    return [
        cleaned
        for part in re.split(r"\s*(?:,|;|/|\band\b|\u3001)\s*", value, flags=re.I)
        if (cleaned := _normalize(part).strip(" ."))
    ]


def _replace_scope_region(scope: str, old_region: str, new_region: str) -> str:
    normalized_scope = _normalize(scope)
    normalized_old = _normalize(old_region)
    if normalized_scope.casefold() == normalized_old.casefold():
        return new_region[:300]
    index = normalized_scope.casefold().rfind(normalized_old.casefold())
    if index >= 0:
        return (
            normalized_scope[:index]
            + new_region
            + normalized_scope[index + len(normalized_old) :]
        )[:300]
    return f"{normalized_scope} ({new_region})"[:300]


def _route_price(
    *,
    tier: str,
    raw_fee: str,
    fee_header: str,
    evidence: EvidenceRef,
) -> RoutePrice | None:
    unavailable = _UNAVAILABLE_RE.search(raw_fee) is not None
    currency = _currency(f"{fee_header} {raw_fee}")
    amount = _amount(raw_fee) if currency is not None else None
    if unavailable and amount is None:
        availability = RoutePriceAvailability.UNAVAILABLE
        currency = None
    elif amount is not None and currency is not None:
        availability = (
            RoutePriceAvailability.CONDITIONAL
            if _CONDITIONAL_RE.search(raw_fee)
            else RoutePriceAvailability.AVAILABLE
        )
    else:
        return None
    return RoutePrice(
        target_tier=tier,
        amount=amount,
        currency=currency,
        availability=availability,
        raw_text=raw_fee,
        evidence=[evidence],
    )


def _merge_prices(
    existing: list[RoutePrice], candidate: list[RoutePrice]
) -> list[RoutePrice]:
    merged: dict[tuple[str, Decimal | None, str | None, str], RoutePrice] = {}
    order: list[tuple[str, Decimal | None, str | None, str]] = []
    for price in [*existing, *candidate]:
        key = (
            _normalize(price.target_tier or "").casefold(),
            price.amount,
            price.currency,
            price.availability.value,
        )
        current = merged.get(key)
        if current is None:
            merged[key] = price
            order.append(key)
        else:
            merged[key] = current.model_copy(
                update={
                    "evidence": _merge_evidence(current.evidence, price.evidence),
                    "raw_text": current.raw_text
                    if _normalize(current.raw_text) == _normalize(price.raw_text)
                    else f"{current.raw_text}; {price.raw_text}"[:1000],
                }
            )
    return [merged[key] for key in order]


def _price_conflicts(prices: list[RoutePrice]) -> list[str]:
    current: dict[str, set[tuple[Decimal, str]]] = {}
    for price in prices:
        if (
            price.amount is None
            or price.currency is None
            or price.availability != RoutePriceAvailability.AVAILABLE
        ):
            continue
        key = _normalize(price.target_tier or "通用").casefold()
        current.setdefault(key, set()).add((price.amount, price.currency))
    return [tier for tier, values in current.items() if len(values) > 1]


def _signal_evidence(
    documents: list[DocumentVersion],
    text_by_document: dict[UUID, str],
    pattern: re.Pattern[str],
) -> list[EvidenceRef]:
    result: list[EvidenceRef] = []
    for document in documents:
        match = pattern.search(text_by_document[document.id])
        if match is None:
            continue
        result.append(
            EvidenceRef(
                document_version_id=document.id,
                source_url=document.canonical_url,
                locator=f"申请费用语义：{match.group(0)}"[:500],
            )
        )
    return result


def _fact_cost_has_amount(value: str | None) -> bool:
    return bool(value and _NUMERIC_FEE_RE.search(value))


def _combined_scope(context: str | None, row_scope: str) -> str:
    cleaned_context = _normalize(context or "")
    if _GENERIC_CONTEXT_RE.search(cleaned_context):
        cleaned_context = ""
    cleaned_row = _normalize(row_scope)
    return (cleaned_row or cleaned_context or "默认申请路线")[:300]


def _clean_tier(value: str) -> str:
    return re.sub(r"\s*(?:\*+|\^+)\s*$", "", _normalize(value))


def _currency(value: str) -> str | None:
    for pattern, currency in _CURRENCY_PATTERNS:
        if pattern.search(value):
            return currency
    return None


def _amount(value: str) -> Decimal | None:
    match = _AMOUNT_RE.search(value)
    if match is None:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _merge_evidence(
    existing: list[EvidenceRef], candidate: list[EvidenceRef]
) -> list[EvidenceRef]:
    result: list[EvidenceRef] = []
    seen: set[tuple[UUID, str, str]] = set()
    for item in [*existing, *candidate]:
        key = (item.document_version_id, str(item.source_url), item.locator)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result[:20]


def _price_signature(
    price: RoutePrice,
) -> tuple[str, Decimal | None, str | None, str]:
    return (
        _normalize(price.target_tier or "").casefold(),
        price.amount,
        price.currency,
        price.availability.value,
    )


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _text(node: Node) -> str:
    return _normalize(node.text(separator=" ", strip=True))
