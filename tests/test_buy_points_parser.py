from __future__ import annotations

import re
from pathlib import Path

import pytest

from journeyplus.buy_points.contracts import (
    BuyPointsCategory,
    BuyPointsOfferKind,
)
from journeyplus.buy_points.parser import (
    BuyPointsParseError,
    parse_awardwallet_buy_points,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture() -> str:
    return (FIXTURES / "awardwallet_buy_points.html").read_text()


def test_parser_extracts_complete_main_inventory_and_top_subset_without_ai() -> None:
    parsed = parse_awardwallet_buy_points(_fixture())

    assert parsed.advertised_offer_count == parsed.parsed_offer_count == 4
    assert parsed.section_counts == {
        BuyPointsCategory.AIRLINE: 2,
        BuyPointsCategory.HOTEL: 1,
        BuyPointsCategory.OTHER: 1,
    }
    assert parsed.page_modified_at is not None
    assert parsed.page_modified_at.isoformat() == "2026-08-25T20:02:47+00:00"
    assert len(parsed.offers_signature) == 64
    assert sum(item.top_pick for item in parsed.offers) == 2

    southwest = next(
        item for item in parsed.offers if item.program_name.startswith("Southwest")
    )
    assert southwest.offer_kind == BuyPointsOfferKind.DISCOUNT
    assert str(southwest.max_percent) == "50"
    assert str(southwest.purchase_rate_cents) == "1.5"
    assert southwest.deadline_date.isoformat() == "2026-08-26"
    assert str(southwest.detail_url).startswith("https://awardwallet.com/")
    assert southwest.evidence.detail_href_raw is not None
    assert southwest.evidence.purchase_rate_text == "1.5¢"

    virgin = next(
        item for item in parsed.offers if item.program_name.startswith("Virgin")
    )
    assert virgin.offer_text.endswith("with up to a 70% bonus")
    assert virgin.deadline_raw is virgin.deadline_date is None
    assert str(virgin.detail_url) == (
        "https://awardwallet.com/airlines/virgin-atlantic-flying-club/"
        "buy-virgin-points/"
    )
    other = next(
        item for item in parsed.offers if item.category == BuyPointsCategory.OTHER
    )
    assert str(other.action_url) == "https://storepoints.com/amtrak"


def test_offer_identity_ignores_variable_offer_fields() -> None:
    original = parse_awardwallet_buy_points(_fixture())
    changed_html = (
        _fixture()
        .replace("4 Current", "4 Current")
        .replace("with up to a 70% bonus", "with up to a 90% bonus")
        .replace("<div class=\"pt-body pt-date\"></div>", "<div class=\"pt-body pt-date\">10/2/26</div>", 1)
        .replace("<div class=\"pt-body pt-avg\">1 day</div>", "<div class=\"pt-body pt-avg\">2 days</div>", 1)
    )
    changed = parse_awardwallet_buy_points(changed_html)
    before = next(item for item in original.offers if "Virgin" in item.program_name)
    after = next(item for item in changed.offers if "Virgin" in item.program_name)

    assert before.offer_key == after.offer_key
    assert before.material_signature != after.material_signature
    assert original.offers_signature != changed.offers_signature

    without_top = parse_awardwallet_buy_points(
        re.sub(
            r'<table id="tablepress-1310">.*?</table>',
            "",
            _fixture(),
            flags=re.DOTALL,
        ).replace(
            "/blog/link/BuySouthwestRapidRewards\">Buy now",
            "/blog/link/BuySouthwestRapidRewardsV2\">Buy now",
            1,
        )
    )
    top_before = next(
        item for item in original.offers if item.program_name.startswith("Southwest")
    )
    top_after = next(
        item for item in without_top.offers if item.program_name.startswith("Southwest")
    )
    assert top_before.offer_key == top_after.offer_key
    assert top_before.top_pick is True and top_after.top_pick is False
    assert top_after.purchase_rate_cents is None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda html: html.replace("4 Current", "5 Current", 1), "Advertised"),
        (
            lambda html: html.replace(
                'id="Buy_Points_Promotions_From_Hotels"',
                'id="missing-hotel-section"',
                1,
            ),
            "Required section",
        ),
        (
            lambda html: html.replace(
                "/airlines/virgin-atlantic-flying-club/buy-virgin-points/",
                "https://awardwallet.com/airlines/southwest-rapid-rewards/buy-southwest-points/",
                1,
            ),
            "Duplicate stable",
        ),
        (lambda html: html.replace("8/26/26", "tomorrow", 1), "supported date"),
        (
            lambda html: html.replace("a 50% discount", "a generous discount", 1),
            "percentage",
        ),
        (lambda html: html.replace("1.5¢", "cheap", 1), "cents rate"),
        (
            lambda html: html.replace(
                "/blog/link/BuySouthwestRapidRewards?var2=fixture",
                "/blog/link/Unknown",
                1,
            ).replace(
                "Virgin Atlantic (Flying Club)",
                "Southwest Airlines (Rapid Rewards)",
                1,
            ),
            "ambiguous",
        ),
    ],
)
def test_parser_fails_closed_on_untrusted_inventory(mutation, message: str) -> None:
    with pytest.raises(BuyPointsParseError, match=message):
        parse_awardwallet_buy_points(mutation(_fixture()))


def test_parser_accepts_only_credible_zero_inventory() -> None:
    zero = (FIXTURES / "awardwallet_buy_points_zero.html").read_text()
    parsed = parse_awardwallet_buy_points(zero)

    assert parsed.advertised_offer_count == parsed.parsed_offer_count == 0
    assert parsed.offers == []
    assert parsed.diagnostics[0].code == "TOP_TABLE_ABSENT"

    with pytest.raises(BuyPointsParseError, match="explicit zero-count"):
        parse_awardwallet_buy_points(zero.replace("0 Current ", "No ", 1))
