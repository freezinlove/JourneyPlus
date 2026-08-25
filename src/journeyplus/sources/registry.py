from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from journeyplus.models import Source


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name: str
    adapter_type: str
    human_url: str
    discovery_config: dict[str, Any]
    content_strategy: str
    access_policy: dict[str, Any] = field(default_factory=dict)
    collection_cadence: str | None = None
    automatic_scheduling: bool = False
    enabled: bool = True

    def as_record(self) -> dict[str, Any]:
        value = asdict(self)
        value["id"] = value.pop("source_id")
        value["discovery_config"]["human_url"] = value.pop("human_url")
        value["discovery_config"]["content_strategy"] = value.pop(
            "content_strategy"
        )
        return value


SOURCE_REGISTRY: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        source_id="ffb_elite_status_feed",
        name="Frequent Flyer Bonuses Elite Status",
        adapter_type="feed",
        human_url="https://blog.frequentflyerbonuses.com/",
        discovery_config={
            "feed_url": "https://blog.frequentflyerbonuses.com/category/elite-status/feed",
        },
        content_strategy="fetch_article",
        access_policy={"external_output": "original_brief_and_source_link"},
        collection_cadence="P1D",
        enabled=False,
    ),
    SourceDefinition(
        source_id="awardwallet_elite_status_feed",
        name="AwardWallet Elite Status",
        adapter_type="feed",
        human_url="https://awardwallet.com/blog/tag/elite-status/",
        discovery_config={
            "feed_url": "https://awardwallet.com/blog/tag/elite-status/feed/",
            "strip_query_params": ["pubDate"],
        },
        content_strategy="fetch_article",
        access_policy={"external_output": "original_brief_and_source_link"},
        collection_cadence="P1D",
        enabled=False,
    ),
    SourceDefinition(
        source_id="status_services_mail",
        name="StatusMatch and GetStatus Mail",
        adapter_type="gmail",
        human_url="https://www.statusmatch.com/",
        discovery_config={
            "account": "kirikoomiku@gmail.com",
            "label": "statusmatch",
            "recipient_alias": "kirikoomiku+statusmatch@gmail.com",
            "query": "to:(kirikoomiku+statusmatch@gmail.com)",
            "oauth_scope": "https://www.googleapis.com/auth/gmail.readonly",
        },
        content_strategy="message_body_and_linked_statusmatch_pages",
        access_policy={
            "read_only": True,
            "sender_allowlist": None,
            "attachments": "ignore_unknown_types",
            "secrets_in_logs": False,
        },
        collection_cadence="P1D",
        automatic_scheduling=True,
    ),
    SourceDefinition(
        source_id="loyaltylobby_feed",
        name="LoyaltyLobby",
        adapter_type="feed",
        human_url="https://loyaltylobby.com/",
        discovery_config={
            "feed_url": "https://loyaltylobby.com/feed/",
            "strip_query_params": ["omhide"],
        },
        content_strategy="feed_body_only",
        access_policy={"fetch_article_page": False},
        collection_cadence="P1D",
        automatic_scheduling=True,
    ),
    SourceDefinition(
        source_id="frequentmiler_elite_status_feed",
        name="Frequent Miler Elite Status",
        adapter_type="feed",
        human_url="https://frequentmiler.com/",
        discovery_config={
            "feed_url": "https://frequentmiler.com/category/travel/elite-status/feed/",
        },
        content_strategy="feed_body_only",
        access_policy={"fetch_article_page": False},
        collection_cadence="P1D",
        enabled=False,
    ),
    SourceDefinition(
        source_id="verylvke_feed",
        name="飞常旅客 VERYLVKE",
        adapter_type="feed",
        human_url="https://www.verylvke.com/",
        discovery_config={"feed_url": "https://www.verylvke.com/feed/"},
        content_strategy="feed_body_only_multi_hint",
        access_policy={"fetch_article_page": False},
        collection_cadence="P1D",
        enabled=False,
    ),
)


def get_source_definition(source_id: str) -> SourceDefinition:
    try:
        return next(item for item in SOURCE_REGISTRY if item.source_id == source_id)
    except StopIteration as exc:
        raise KeyError(f"Unknown source: {source_id}") from exc


def seed_sources(session: Session) -> list[Source]:
    records: list[Source] = []
    for definition in SOURCE_REGISTRY:
        values = definition.as_record()
        source = session.get(Source, definition.source_id)
        if source is None:
            source = Source(**values)
            session.add(source)
        else:
            for key, value in values.items():
                if key != "id":
                    setattr(source, key, value)
        records.append(source)
    for retired_source_id in (
        "statusmatcher_reports",
        "ffb_status_match_catalog",
    ):
        retired = session.get(Source, retired_source_id)
        if retired is not None:
            retired.enabled = False
            retired.automatic_scheduling = False
            retired.collection_cadence = None
    session.flush()
    return records
