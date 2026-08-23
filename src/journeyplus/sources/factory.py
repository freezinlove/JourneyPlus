from __future__ import annotations

from journeyplus.sources.base import Fetcher, HttpxFetcher, SourceAdapter
from journeyplus.sources.feed import FeedAdapter
from journeyplus.sources.gmail import GmailClient, GmailStatusServicesAdapter
from journeyplus.sources.registry import get_source_definition


def build_adapter(
    source_id: str,
    *,
    fetcher: Fetcher | None = None,
    gmail_client: GmailClient | None = None,
) -> SourceAdapter:
    definition = get_source_definition(source_id)
    config = definition.discovery_config
    resolved_fetcher = fetcher or HttpxFetcher()
    if definition.adapter_type == "feed":
        return FeedAdapter(
            source_id=source_id,
            feed_url=str(config["feed_url"]),
            content_strategy=definition.content_strategy,
            fetcher=resolved_fetcher,
            extra_drop_params=set(config.get("strip_query_params", [])),
        )
    if definition.adapter_type == "gmail":
        if gmail_client is None:
            raise ValueError("A GmailClient is required for status_services_mail")
        return GmailStatusServicesAdapter(
            gmail_client, project_fetcher=resolved_fetcher
        )
    raise NotImplementedError(definition.adapter_type)
