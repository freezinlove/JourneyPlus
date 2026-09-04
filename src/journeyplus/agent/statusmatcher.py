from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from selectolax.parser import HTMLParser

from journeyplus.agent.contracts import (
    ExperienceAvailability,
    ExperienceOutcome,
    ExperienceReport,
    StatusMatcherObservation,
)
from journeyplus.membership.normalization import normalize_key
from journeyplus.product.contracts import CandidateRoute, CandidateRouteStep


_BASE_URL = "https://statusmatcher.com"
_COMPANY_PATH = re.compile(r"^/company/[A-Za-z0-9-]+$")
_GENERIC_PROGRAM_TOKENS = {
    "air",
    "airline",
    "airlines",
    "and",
    "club",
    "elite",
    "frequent",
    "hotel",
    "hotels",
    "loyalty",
    "miles",
    "program",
    "rewards",
    "status",
}
_PRACTICAL_PATTERNS = (
    (re.compile(r"(?:proof|screenshot|statement|membership\s+card|证明|截图|账单)", re.I), "多份报告提到需要会籍证明、截图或账户记录。"),
    (re.compile(r"(?:book(?:ed|ing)?|reservation|itinerary|ticket|预订|行程|机票)", re.I), "多份报告提到已有预订或后续行程可能影响处理。"),
    (re.compile(r"(?:week|day|hour|等待|工作日|周|天)", re.I), "多份报告提到处理需要等待，时长会因个案而异。"),
    (re.compile(r"(?:resident|country|region|地区|居住|国家)", re.I), "多份报告提到地区或居住资格限制。"),
    (re.compile(r"(?:den(?:y|ied)|declin|not\s+eligible|拒绝|不符合)", re.I), "多份报告出现拒绝或资格不符反馈。"),
)


# Page aliases are an adapter concern, not match facts. Unknown names fail closed.
_COMPANY_SLUGS = {
    "aegean airlines": "aegean-airlines",
    "aegean miles+bonus": "aegean-airlines",
    "air canada": "air-canada",
    "air canada aeroplan": "air-canada",
    "aeroplan": "air-canada",
    "air france": "air-france",
    "air france flying blue": "air-france",
    "air france klm flying blue": "air-france",
    "alaska airlines": "alaska-airlines",
    "alaska airlines atmos rewards": "alaska-airlines",
    "american airlines": "american-airlines",
    "american airlines aadvantage": "american-airlines",
    "asiana airlines": "asiana-airlines",
    "asiana club": "asiana-airlines",
    "british airways": "british-airways",
    "british airways club": "british-airways",
    "cathay": "cathay-pacific",
    "cathay pacific": "cathay-pacific",
    "china airlines": "china-airlines",
    "china airlines dynasty flyer": "china-airlines",
    "china eastern airlines": "china-eastern-airlines",
    "delta air lines": "delta-air-lines",
    "delta skymiles": "delta-air-lines",
    "emirates": "emirates",
    "emirates skywards": "emirates",
    "flying blue": "air-france",
    "hilton honors": "hilton",
    "intercontinental": "intercontinental",
    "ihg one rewards": "intercontinental",
    "kenya airways": "kenya-airways",
    "kenya airways asante rewards": "kenya-airways",
    "asante rewards": "kenya-airways",
    "lufthansa": "lufthansa",
    "lufthansa miles more": "lufthansa",
    "lufthansa miles and more": "lufthansa",
    "miles more": "lufthansa",
    "lotusmiles vietnam airlines": "vietnam-airlines",
    "vietnam airlines": "vietnam-airlines",
    "vietnam airlines lotusmiles": "vietnam-airlines",
    "qatar airways": "qatar-airways",
    "qatar airways privilege club": "qatar-airways",
    "singapore airlines": "singapore-airlines",
    "singapore airlines krisflyer": "singapore-airlines",
    "turkish airlines": "turkish-airlines",
    "turkish airlines miles smiles": "turkish-airlines",
    "turkish airlines miles and smiles": "turkish-airlines",
    "united airlines": "united-airlines",
    "united mileageplus": "united-airlines",
    "world of hyatt": "hyatt",
}


class StatusMatcherExperienceClient:
    def __init__(
        self,
        *,
        enabled: bool = False,
        timeout_seconds: float = 12,
        max_response_bytes: int = 1_000_000,
        max_pages: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("StatusMatcher timeout must be between 0 and 30 seconds")
        if not 1 <= max_response_bytes <= 1_000_000:
            raise ValueError("StatusMatcher response limit must not exceed 1000000 bytes")
        if not 1 <= max_pages <= 2:
            raise ValueError("StatusMatcher page limit must be between 1 and 2")
        self.enabled = enabled
        self._max_response_bytes = max_response_bytes
        self._max_pages = max_pages
        self._client = client or httpx.Client(
            base_url=_BASE_URL,
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={
                "User-Agent": "JourneyPlus/0.1 (status experience research)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )

    def research(self, route: CandidateRoute) -> StatusMatcherObservation:
        observed_at = datetime.now(UTC)
        if not self.enabled:
            return _unavailable(
                route.route_id,
                observed_at,
                ExperienceAvailability.DISABLED,
                "StatusMatcher 自动调查未启用。",
            )
        reports: list[ExperienceReport] = []
        source_urls: list[str] = []
        missing_steps: list[str] = []
        try:
            for step in route.steps:
                slug = _resolve_slug(step.program)
                if slug is None:
                    missing_steps.append(step.program)
                    continue
                page_reports, page_urls = self._step_reports(step, slug)
                reports.extend(page_reports)
                source_urls.extend(page_urls)
        except (httpx.HTTPError, ValueError) as exc:
            return _unavailable(
                route.route_id,
                observed_at,
                ExperienceAvailability.UNAVAILABLE,
                f"StatusMatcher 调查暂不可用：{type(exc).__name__}",
            )

        reports = list(
            {
                (
                    report.outcome,
                    report.source_program,
                    report.target_program,
                    report.summary,
                ): report
                for report in reports
            }.values()
        )[:20]
        counts = Counter(report.outcome for report in reports)
        complete = not missing_steps and len(source_urls) >= len(route.steps)
        availability = (
            ExperienceAvailability.AVAILABLE
            if complete and len(reports) >= 2
            else ExperienceAvailability.INSUFFICIENT
        )
        limitation_parts = ["结果来自用户自报案例，不代表真实审批概率或通过保证。"]
        if missing_steps:
            limitation_parts.append(
                "未能可靠定位以下步骤的公司页：" + "、".join(missing_steps)
            )
        if len(reports) < 2:
            limitation_parts.append("可比报告不足两条。")
        return StatusMatcherObservation(
            availability=availability,
            route_id=route.route_id,
            source_urls=list(dict.fromkeys(source_urls))[:10],
            observed_at=observed_at,
            comparable_report_count=len(reports),
            outcome_counts=dict(counts),
            signal=_signal(counts, len(reports), complete),
            practical_notes=_practical_notes(reports),
            reports=reports,
            limitation=" ".join(limitation_parts),
        )

    def _step_reports(
        self, step: CandidateRouteStep, slug: str
    ) -> tuple[list[ExperienceReport], list[str]]:
        reports: list[ExperienceReport] = []
        urls: list[str] = []
        source_program = step.source_node_id.rsplit("::", 1)[0]
        for page in range(self._max_pages):
            path = f"/company/{slug}"
            if page:
                path += f"?page-to={page}"
            html, url = self._read_html(path)
            urls.append(url)
            parsed = _parse_obtaining_reports(html)
            reports.extend(
                report
                for report in parsed
                if _programs_comparable(source_program, report.source_program)
            )
        return reports, urls

    def _read_html(self, path: str) -> tuple[str, str]:
        if not _COMPANY_PATH.fullmatch(path.split("?", 1)[0]):
            raise ValueError("unsupported StatusMatcher path")
        with self._client.stream("GET", path) as response:
            response.raise_for_status()
            final = urlsplit(str(response.url))
            if final.scheme != "https" or final.hostname != "statusmatcher.com":
                raise ValueError("StatusMatcher redirected outside the allowlist")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self._max_response_bytes:
                    raise ValueError("StatusMatcher response exceeded size limit")
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
            return b"".join(chunks).decode(encoding, errors="replace"), str(response.url)


def _resolve_slug(program: str) -> str | None:
    return _COMPANY_SLUGS.get(_program_key(program))


def _program_key(value: str) -> str:
    return " ".join(token for token in normalize_key(value).split() if token != "and")


def _programs_comparable(expected: str, observed: str) -> bool:
    left = _program_key(expected)
    right = _program_key(observed)
    if left == right or left in right or right in left:
        return True
    left_tokens = set(left.split()) - _GENERIC_PROGRAM_TOKENS
    right_tokens = set(right.split()) - _GENERIC_PROGRAM_TOKENS
    return bool(left_tokens and right_tokens and left_tokens == right_tokens)


def _parse_obtaining_reports(html: str) -> list[ExperienceReport]:
    tree = HTMLParser(html)
    heading = tree.css_first("#report-list-to")
    if heading is None or heading.parent is None:
        raise ValueError("obtaining report section not found")
    reports: list[ExperienceReport] = []
    for item in heading.parent.css("div.d-flex.mb-3"):
        outcome_node = item.css_first(".result-box span")
        title_node = item.css_first("h6")
        summary_node = item.css_first(".instructions")
        if outcome_node is None or title_node is None or summary_node is None:
            continue
        title = " ".join(title_node.text(separator=" ").split())
        parts = re.split(r"\s+to\s+", title, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) != 2:
            continue
        raw_outcome = outcome_node.text(strip=True).upper()
        outcome = (
            ExperienceOutcome(raw_outcome)
            if raw_outcome in ExperienceOutcome._value2member_map_
            else ExperienceOutcome.OTHER
        )
        summary = " ".join(summary_node.text(separator=" ").split())[:600]
        if not summary:
            summary = "报告未提供可见说明。"
        reports.append(
            ExperienceReport(
                outcome=outcome,
                source_program=parts[0].strip(),
                target_program=parts[1].strip(),
                summary=summary,
            )
        )
    return reports


def _signal(
    counts: Counter[ExperienceOutcome], total: int, complete: bool
) -> str:
    if total < 2 or not complete:
        return "证据不足"
    if total >= 3 and counts[ExperienceOutcome.MATCH] / total >= 0.6:
        return "较强"
    if counts[ExperienceOutcome.DENY] / total >= 0.5:
        return "较弱"
    return "一般"


def _practical_notes(reports: list[ExperienceReport]) -> list[str]:
    notes: list[str] = []
    texts = [report.summary for report in reports]
    for pattern, note in _PRACTICAL_PATTERNS:
        if sum(bool(pattern.search(text)) for text in texts) >= 2:
            notes.append(note)
    return notes


def _unavailable(
    route_id: str,
    observed_at: datetime,
    availability: ExperienceAvailability,
    limitation: str,
) -> StatusMatcherObservation:
    return StatusMatcherObservation(
        availability=availability,
        route_id=route_id,
        observed_at=observed_at,
        signal="暂不可用" if availability != ExperienceAvailability.INSUFFICIENT else "证据不足",
        limitation=limitation,
    )
