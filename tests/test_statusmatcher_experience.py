from __future__ import annotations

from uuid import uuid4

import httpx

from journeyplus.agent.contracts import ExperienceAvailability, ExperienceOutcome
from journeyplus.agent.statusmatcher import StatusMatcherExperienceClient
from journeyplus.product.contracts import CandidateRoute, CandidateRouteStep


_HTML = """<!doctype html><html><body>
<div>
  <h4 id="report-list-to">Reports for obtaining status with Delta SkyMiles</h4>
  <div class="d-flex mb-3">
    <div><div class="result-box"><span>Match</span></div></div>
    <div class="report-list-item-middle-box"><h6>Lufthansa Miles and More to Delta SkyMiles</h6>
      <span class="instructions">Uploaded a membership card screenshot and statement.</span></div>
  </div>
  <div class="d-flex mb-3">
    <div><div class="result-box"><span>Match</span></div></div>
    <div class="report-list-item-middle-box"><h6>Lufthansa Miles &amp; More to Delta SkyMiles</h6>
      <span class="instructions">Submitted proof and membership card screenshot.</span></div>
  </div>
  <div class="d-flex mb-3">
    <div><div class="result-box"><span>Deny</span></div></div>
    <div class="report-list-item-middle-box"><h6>Turkish Airlines Miles and Smiles to Delta SkyMiles</h6>
      <span class="instructions">Request denied.</span></div>
  </div>
</div>
<div>
  <h4 id="report-list-from">Reports for leveraging status with Delta SkyMiles</h4>
  <div class="d-flex mb-3">
    <div><div class="result-box"><span>Deny</span></div></div>
    <div class="report-list-item-middle-box"><h6>Delta SkyMiles to Lufthansa Miles and More</h6>
      <span class="instructions">Reverse direction denied.</span></div>
  </div>
</div>
</body></html>"""


def _route(*, target_program: str = "Delta Air Lines") -> CandidateRoute:
    return CandidateRoute(
        route_id="route-1",
        node_path=["lufthansa miles more::gold", "delta skymiles::gold"],
        target_program=target_program,
        target_tier="Gold",
        steps=[
            CandidateRouteStep(
                source_node_id="lufthansa miles more::gold",
                target_node_id="delta skymiles::gold",
                opportunity_id=uuid4(),
                source="STATUSMATCH_OFFICIAL",
                program=target_program,
                target_status="Gold",
                summary="Status match",
                lifecycle_status="ACTIVE",
            )
        ],
    )


def test_statusmatcher_is_disabled_without_network_access() -> None:
    def fail(_request):
        raise AssertionError("network should not be called")

    client = httpx.Client(
        base_url="https://statusmatcher.com",
        transport=httpx.MockTransport(fail),
    )
    result = StatusMatcherExperienceClient(enabled=False, client=client).research(
        _route()
    )
    assert result.availability == ExperienceAvailability.DISABLED
    assert result.source_urls == []


def test_statusmatcher_parses_only_comparable_obtaining_reports() -> None:
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, text=_HTML, request=request)

    client = httpx.Client(
        base_url="https://statusmatcher.com",
        transport=httpx.MockTransport(respond),
    )
    result = StatusMatcherExperienceClient(
        enabled=True,
        max_pages=1,
        client=client,
    ).research(_route())

    assert requests == ["https://statusmatcher.com/company/delta-air-lines"]
    assert result.availability == ExperienceAvailability.AVAILABLE
    assert result.comparable_report_count == 2
    assert result.outcome_counts == {ExperienceOutcome.MATCH: 2}
    assert all(report.source_program.startswith("Lufthansa") for report in result.reports)
    assert result.practical_notes == ["多份报告提到需要会籍证明、截图或账户记录。"]
    assert "真实审批概率" in result.limitation


def test_statusmatcher_checks_bounded_pages_and_deduplicates_reports() -> None:
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, text=_HTML, request=request)

    client = httpx.Client(
        base_url="https://statusmatcher.com",
        transport=httpx.MockTransport(respond),
    )
    result = StatusMatcherExperienceClient(
        enabled=True,
        max_pages=2,
        client=client,
    ).research(_route())

    assert requests == [
        "https://statusmatcher.com/company/delta-air-lines",
        "https://statusmatcher.com/company/delta-air-lines?page-to=1",
    ]
    assert result.comparable_report_count == 2


def test_statusmatcher_unknown_company_fails_closed() -> None:
    def fail(_request):
        raise AssertionError("unknown target should not be requested")

    client = httpx.Client(
        base_url="https://statusmatcher.com",
        transport=httpx.MockTransport(fail),
    )
    result = StatusMatcherExperienceClient(enabled=True, client=client).research(
        _route(target_program="Unmapped Program")
    )
    assert result.availability == ExperienceAvailability.INSUFFICIENT
    assert "未能可靠定位" in result.limitation


def test_statusmatcher_network_and_parser_failures_degrade() -> None:
    def timeout(request: httpx.Request):
        raise httpx.ReadTimeout("timeout", request=request)

    timeout_client = httpx.Client(
        base_url="https://statusmatcher.com",
        transport=httpx.MockTransport(timeout),
    )
    timed_out = StatusMatcherExperienceClient(
        enabled=True, client=timeout_client
    ).research(_route())
    assert timed_out.availability == ExperienceAvailability.UNAVAILABLE
    assert timed_out.signal == "暂不可用"

    def unsupported(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>changed</html>", request=request)

    unsupported_client = httpx.Client(
        base_url="https://statusmatcher.com",
        transport=httpx.MockTransport(unsupported),
    )
    changed = StatusMatcherExperienceClient(
        enabled=True, client=unsupported_client
    ).research(_route())
    assert changed.availability == ExperienceAvailability.UNAVAILABLE


def test_statusmatcher_response_size_is_bounded() -> None:
    def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 101, request=request)

    client = httpx.Client(
        base_url="https://statusmatcher.com",
        transport=httpx.MockTransport(oversized),
    )
    result = StatusMatcherExperienceClient(
        enabled=True,
        max_response_bytes=100,
        client=client,
    ).research(_route())
    assert result.availability == ExperienceAvailability.UNAVAILABLE
