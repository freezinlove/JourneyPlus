from copy import deepcopy
from decimal import Decimal

import pytest

from journeyplus.contracts import ApplicationRoute, RoutePrice, StatusMapping
from journeyplus.facts.statusmatch_tables import extract_statusmatch_status_mappings
from journeyplus.facts.statusmatch_prices import extract_statusmatch_price_routes
from journeyplus.statusmatch.contracts import StatusMatchProjectExtraction
from journeyplus.statusmatch.table_drafts import (
    apply_table_updates, model_document_body, read_table_drafts, table_drafts,
)
from tests.test_statusmatch_prices import _document
from tests.test_statusmatch_project_workflow import _extraction


def _bases():
    mappings = [StatusMapping(source_program="Air Club", source_tiers=["Gold", "Diamond"],
                              target_tier="Gold", availability="CONDITIONAL", conditions="居民限定")]
    routes = [ApplicationRoute(scope="Region A, Region B", region="Region A, Region B",
                               eligibility="现有精英会员", cost="申请费不退", prices=[
        RoutePrice(target_tier="Gold", amount=Decimal("99.1234"), currency="USD", availability="AVAILABLE"),
        RoutePrice(target_tier="Platinum", amount=399, currency="USD", availability="AVAILABLE"),
    ])]
    return mappings, routes


def _updates(**kwargs):
    return StatusMatchProjectExtraction.model_validate(_extraction() | kwargs)


def test_compact_columns_roundtrip_keeps_full_semantics_and_decimal_prices():
    mappings, routes = _bases()
    encoded = table_drafts(mappings, routes)
    assert encoded["deterministic_status_mappings"]["rows"][0][0] == "m1"
    assert encoded["deterministic_price_routes"]["rows"][0][0] == "r1"
    assert read_table_drafts(encoded) == (mappings, routes)
    assert "evidence" not in str(encoded)


def test_unmentioned_rows_and_fields_survive_patch_and_refs_are_not_persisted():
    mappings, routes = _bases()
    original = deepcopy((mappings, routes))
    updated_mappings, updated_routes = apply_table_updates(mappings, routes, _updates(
        route_updates=[{"ref": "r1", "scope": "地区甲、乙", "clear_fields": ["cost"]}],
    ))
    assert (mappings, routes) == original
    assert updated_mappings == mappings
    assert updated_routes[0].prices == routes[0].prices
    assert updated_routes[0].eligibility == routes[0].eligibility
    assert updated_routes[0].cost == routes[0].cost
    assert updated_routes[0].scope == routes[0].scope
    assert "ref" not in updated_routes[0].model_dump()


def test_null_defaults_and_cached_extraction_roundtrip_preserve_base_values():
    mappings, routes = _bases()
    extraction = _updates(
        mapping_updates=[{"ref": "m1", "conditions": None}],
        route_updates=[{"ref": "r1", "cost": None,
                        "price_updates": [{"ref": "p2", "availability": "UNAVAILABLE"}]}],
    )
    result = apply_table_updates(mappings, routes, extraction)
    restored = StatusMatchProjectExtraction.model_validate(extraction.model_dump(mode="json"))
    assert apply_table_updates(mappings, routes, restored) == result
    assert result[0] == mappings
    assert result[1][0].cost == routes[0].cost
    assert result[1][0].prices[1].target_tier == "Platinum"


def test_prose_can_split_base_route_without_retyping_other_prices():
    mappings, routes = _bases()
    _, result = apply_table_updates(mappings, routes, _updates(route_updates=[
        {"ref": "r1", "scope": "Region A", "region": "Region A",
         "price_updates": [{"ref": "p2", "availability": "UNAVAILABLE"}]},
        {"ref": "r1", "scope": "Region B", "region": "Region B"},
    ]))
    assert result == routes


def test_mapping_condition_is_supplemented_in_place_not_marked_as_conflict():
    mappings, routes = _bases()
    result, _ = apply_table_updates(mappings, routes, _updates(mapping_updates=[
        {"ref": "m1", "conditions": "居民限定；须有本地身份证明"},
    ]))
    assert len(result) == 1
    assert result[0].source_tiers == ["Gold", "Diamond"]
    assert result[0].conditions == "居民限定"
    assert not result[0].conflict


def test_mapping_unavailable_and_additional_conditional_price():
    mappings, routes = _bases()
    result, route_result = apply_table_updates(mappings, routes, _updates(
        mapping_updates=[{"ref": "m1", "availability": "UNAVAILABLE"}],
        route_updates=[{"ref": "r1", "additional_prices": [{
            "target_tier": "Platinum", "amount": 50, "currency": "EUR",
            "availability": "CONDITIONAL", "raw_text": "另购升级服务",
        }]}],
    ))
    assert result[0].source_tiers == mappings[0].source_tiers
    assert result[0].conditions == mappings[0].conditions
    assert len(route_result[0].prices) == 2
    assert route_result[0].prices[:2] == routes[0].prices
    assert route_result[0].prices == routes[0].prices


@pytest.mark.parametrize("updates", [
    {"route_updates": [{"ref": "r8", "cost": "不退费"}]},
    {"mapping_updates": [{"ref": "m8", "conditions": "居民限定"}]},
    {"route_updates": [{"ref": "r1", "price_updates": [{"ref": "p8", "amount": 100}]}]},
])
def test_unknown_refs_do_not_silently_drop_or_overwrite_rows(updates):
    with pytest.raises(ValueError, match="Unknown table reference"):
        apply_table_updates(*_bases(), _updates(**updates))


def test_model_body_removes_covered_rows_but_keeps_notes_headers_and_partial_rows():
    html = """<html><body><h1>Current offer</h1><p>Applicants must be residents.</p>
    <table><caption>Membership matching</caption>
      <tr><td></td><td>Target Club Tier</td></tr>
      <tr><th>Airline</th><th>Gold*</th></tr>
      <tr><td>CoveredAir</td><td>Diamond</td></tr>
      <tr><td>PartialAir</td><td>Silver</td><td>Extra condition</td></tr>
      <tr><td colspan="2">In-table condition</td></tr>
    </table><p>* Local passport required.</p>
    <table><tr><td>Unrecognized heading</td><td>Unrecognized data</td></tr></table>
    </body></html>"""
    document = _document("faq", html)
    snapshot = (document.raw_body, document.normalized_body)
    mappings = extract_statusmatch_status_mappings(raw_html=html,
        canonical_url=document.canonical_url, document_version_id=document.id)
    assert any(m.source_program == "CoveredAir" for m in mappings)

    body = model_document_body(document)

    assert "CoveredAir" not in body
    for text in ("Current offer", "Membership matching", "Target Club Tier", "Applicants",
                 "PartialAir", "Extra condition", "In-table condition", "Local passport", "Unrecognized data"):
        assert text in body
    assert (document.raw_body, document.normalized_body) == snapshot


def test_price_input_keeps_inherited_scopes_notes_unknown_columns_and_links():
    html = """<html><body><h2>Fee schedule</h2><p>Fees are non-refundable.</p>
    <table><tr><th>Country/Region</th><th>Status Tier</th><th>Application Fee</th></tr>
      <tr><td colspan="3">Listed in USD</td></tr><tr><td colspan="3">Region A</td></tr>
      <tr><td></td><td>Gold</td><td>USD 99</td></tr>
      <tr><td></td><td>Platinum</td><td>USD 399</td><td>Processing rule</td></tr>
      <tr><td></td><td>Silver</td><td><a href="/pay">USD 49</a></td></tr>
    </table><p>Additional optional services may incur fees.</p></body></html>"""
    document = _document("terms", html)
    routes = extract_statusmatch_price_routes(raw_html=html, canonical_url=document.canonical_url,
                                              document_version_id=document.id)
    assert routes[0].prices[0].amount == 99
    body = model_document_body(document)
    assert "USD 99" not in body
    for text in ("Region A", "Fee schedule", "Listed in USD", "non-refundable", "USD 399",
                 "Processing rule", "USD 49", "/pay", "Additional optional services"):
        assert text in body


def test_plain_text_or_unparsed_tables_remain_available_without_snapshot_changes():
    document = _document("faq", "<p>Gold applicants pay EUR 123.</p><table><tr><td>Custom conditions</td></tr></table>")
    assert "EUR 123" in model_document_body(document)
    assert "Custom conditions" in model_document_body(document)
    document.raw_body = None
    assert model_document_body(document) == document.normalized_body


def test_model_cannot_clear_parsed_amount_or_overwrite_mapping():
    mappings, routes = _bases()
    result_m, result_r = apply_table_updates(mappings, routes, _updates(
        mapping_updates=[{"ref": "m1", "source_tiers": ["Silver"], "target_tier": "Platinum",
                          "availability": "UNAVAILABLE"}],
        route_updates=[{"ref": "r1", "price_updates": [{"ref": "p1", "availability": "UNKNOWN",
                         "clear_fields": ["amount", "currency", "raw_text"]}]}]))
    assert result_m == mappings
    assert result_r == routes


def test_additive_prices_and_mapping_rows_still_work():
    from journeyplus.statusmatch.project_workflow import _merge_mapping_channels
    mappings, routes = _bases()
    _, updated = apply_table_updates(mappings, routes, _updates(route_updates=[{
        "ref": "r1", "additional_prices": [{"target_tier": "Silver", "amount": 49,
                                          "currency": "USD", "availability": "AVAILABLE"}]}]))
    assert updated[0].prices[:2] == routes[0].prices
    assert updated[0].prices[2].amount == 49
    extra = StatusMapping(source_program="Other Club", source_tiers=["Gold"], target_tier="Gold", availability="AVAILABLE")
    assert _merge_mapping_channels(mappings, [extra]) == [*mappings, extra]
    conflict = mappings[0].model_copy(update={"availability": "UNAVAILABLE", "source_tiers": []})
    assert _merge_mapping_channels(mappings, [conflict]) == mappings


def test_same_region_narrative_price_cannot_bypass_protection():
    from journeyplus.statusmatch.table_drafts import supplement_routes
    _, routes = _bases()
    conflict = ApplicationRoute(scope="Region A", region="Region A", cost="free", prices=[
        RoutePrice(target_tier="Gold", amount=0, currency="USD", availability="AVAILABLE")])
    assert supplement_routes(routes, [conflict]) == routes


def test_translated_region_cannot_replace_parsed_price():
    from journeyplus.statusmatch.table_drafts import supplement_routes
    original = ApplicationRoute(scope="Greece", region="Greece", prices=[
        RoutePrice(target_tier="Gold", amount=199, currency="EUR", availability="AVAILABLE")])
    prose = ApplicationRoute(scope="希腊", region="希腊", prices=[
        RoutePrice(target_tier="Gold", amount=0, currency="EUR", availability="AVAILABLE")])
    assert supplement_routes([original], [prose]) == [original]


def test_partial_region_supplement_retains_only_new_region_price():
    from journeyplus.statusmatch.table_drafts import supplement_routes
    base = ApplicationRoute(scope="Greece", region="Greece", prices=[
        RoutePrice(target_tier="Gold", amount=199, currency="EUR", availability="AVAILABLE")])
    extra = ApplicationRoute(scope="Greece, France", region="Greece, France", prices=[
        RoutePrice(target_tier="Flying Blue Gold", amount=99, currency="EUR", availability="AVAILABLE")])
    result = supplement_routes([base], [extra], program="Flying Blue")
    assert result[0] == base
    assert len(result) == 2
    assert result[1].region == "france"
    assert result[1].prices[0].amount == 99


def test_unparsed_mapping_table_retries_instead_of_accepting_empty_result():
    from journeyplus.statusmatch.project_workflow import StatusMatchProjectWorkflow
    from tests.test_statusmatch_project_workflow import ProjectProvider
    empty = _extraction() | {"narrative_status_mappings": []}
    complete = _extraction() | {"narrative_status_mappings": [{
        "source_program": "Example Air", "source_tiers": ["Gold"],
        "target_tier": "Elite", "availability": "AVAILABLE",
    }]}
    provider = ProjectProvider([empty, complete])
    result, attempts = StatusMatchProjectWorkflow(None, provider).generate_extraction(
        table_drafts([], []), "| Programme | Elite |\n| Example Air | Gold |")
    assert attempts == 2
    assert len(result.narrative_status_mappings) == 1


def test_no_mapping_table_or_prose_can_legitimately_remain_empty():
    from journeyplus.statusmatch.project_workflow import StatusMatchProjectWorkflow
    from tests.test_statusmatch_project_workflow import ProjectProvider
    provider = ProjectProvider([_extraction() | {"narrative_status_mappings": []}])
    result, attempts = StatusMatchProjectWorkflow(None, provider).generate_extraction(
        table_drafts([], []), "Application details have not been announced.")
    assert attempts == 1
    assert result.narrative_status_mappings == []
