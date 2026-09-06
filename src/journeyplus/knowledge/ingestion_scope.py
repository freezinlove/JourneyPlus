"""Source-specific admission policy shared by refresh and backfill."""
from datetime import UTC, datetime
from urllib.parse import urlsplit

LOYALTYLOBBY_START = datetime(2026, 9, 5, 16, tzinfo=UTC)  # Sep 6, Asia/Shanghai

def article_scope_reason(item):
    """Publication date gates LL articles; fetching an old URL is not new publication."""
    host = (urlsplit(item.canonical_url).hostname or '').lower()
    if item.source_id != 'loyaltylobby_feed' and host != 'loyaltylobby.com' and not host.endswith('.loyaltylobby.com'):
        return None
    published = item.published_at
    if published is None:
        return 'PUBLICATION_DATE_UNKNOWN'
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    return 'HISTORICAL_LOYALTYLOBBY' if published < LOYALTYLOBBY_START else None

