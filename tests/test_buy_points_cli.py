from __future__ import annotations

import json
from pathlib import Path

import journeyplus.cli as cli

from journeyplus.config import Settings
from journeyplus.contracts import DiscoveredItem, RawDocument


FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_ID = "awardwallet_buy_points_page"
PAGE_URL = (
    "https://awardwallet.com/news/current-promotions-buy-points-miles/"
)


class FixtureBuyPointsAdapter:
    source_id = SOURCE_ID

    def discover(self):
        return [
            DiscoveredItem(
                source_id=SOURCE_ID,
                external_id="current-promotions-buy-points-miles",
                discovered_url=PAGE_URL,
                canonical_url=PAGE_URL,
                title="Current Promotions",
                raw_metadata={
                    "refresh_on_discovery": True,
                    "content_strategy": "fetch_article",
                },
            )
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=SOURCE_ID,
            external_id=item.external_id,
            canonical_url=PAGE_URL,
            body=(FIXTURES / "awardwallet_buy_points.html").read_text(),
            content_type="text/html",
            metadata={
                "content_strategy": "fetch_article",
                "title": item.title,
            },
        )


def test_buy_points_cli_arguments_are_separate_from_generic_ai_processing() -> None:
    parser = cli.build_parser()

    assert parser.parse_args(["process-buy-points"]).command == "process-buy-points"
    assert parser.parse_args(["buy-points-current"]).command == "buy-points-current"
    assert parser.parse_args(["buy-points-history"]).command == "buy-points-history"
    assert parser.parse_args(["buy-points-diff"]).command == "buy-points-diff"
    assert parser.parse_args(["run-source", SOURCE_ID]).source_id == SOURCE_ID


def test_run_source_and_read_commands_work_without_ai_credentials(
    session_factory, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        classmethod(lambda cls: Settings()),
    )
    monkeypatch.setattr(cli, "engine_from_settings", lambda settings: object())
    monkeypatch.setattr(
        cli, "create_session_factory", lambda engine: session_factory
    )
    monkeypatch.setattr(
        cli,
        "build_configured_adapter",
        lambda source_id, settings: FixtureBuyPointsAdapter(),
    )

    def reject_ai_provider(settings):
        raise AssertionError("buy-points CLI must not construct an AI provider")

    monkeypatch.setattr(cli, "OpenAICompatibleProvider", reject_ai_provider)

    assert cli.main(["run-source", SOURCE_ID]) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["collection"]["new_versions"] == 1
    assert run_payload["processing"]["succeeded"] == 1
    assert run_payload["processing"]["latest_offer_count"] == 4

    assert cli.main(["buy-points-current"]) == 0
    current = json.loads(capsys.readouterr().out)
    assert current["parsed_offer_count"] == 4
    assert len(current["offers"]) == 4
    assert "advertised_offer_count" not in current
    assert "purchase_url" in current["offers"][0]
    assert {
        "offer_text",
        "evidence",
        "purchase_rate_raw",
        "purchase_rate_cents",
        "top_pick",
        "action_url",
    }.isdisjoint(current["offers"][0])

    assert cli.main(["buy-points-history", "--limit", "5"]) == 0
    history = json.loads(capsys.readouterr().out)
    assert len(history) == 1

    assert cli.main(
        [
            "buy-points-history",
            "--offer-key",
            current["offers"][0]["offer_key"],
            "--limit",
            "5",
        ]
    ) == 0
    offer_history = json.loads(capsys.readouterr().out)
    assert len(offer_history) == 1
    assert offer_history[0]["offer_key"] == current["offers"][0]["offer_key"]

    assert cli.main(["buy-points-diff"]) == 0
    assert json.loads(capsys.readouterr().out) is None

    assert cli.main(["process-buy-points"]) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["selected"] == 0
    assert repeated["latest_offer_count"] == 4
