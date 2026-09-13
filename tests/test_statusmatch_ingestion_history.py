from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from journeyplus.content.cleaner import lightly_clean
from journeyplus.content.service import IngestionService
from journeyplus.contracts import RawDocument
from journeyplus.facts.statusmatch_prices import extract_statusmatch_price_routes
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.watchlist import statusmatch_page_item, record_statusmatch_page_result
from journeyplus.statusmatch.project_workflow import statusmatch_project_job_key


def fee(region, amount):
    return '<table><tr><th>Country/Region</th><th>Status Tier</th><th>Application Fee</th></tr>' + f'<tr><td>{region}</td><td>Silver</td><td>USD {amount}</td></tr></table>'


def page(old_fee=99, *, moved=False, token='one'):
    active=fee('Active country',89) if not moved else ''
    ended=fee('Active country',89) if moved else ''
    return ('<html><body><h1>Offer</h1>'+active+'<h3>Recently ended offers</h3>'+fee('Retired country',old_fee)+ended+
        '<h3>Eligible airline mappings</h3><table><tr><th>Airline</th><th>Silver</th><th>Gold</th></tr>'
        '<tr><td>Example Air</td><td>Bronze</td><td>Silver</td></tr></table>'
        '<p>Mapping footnote: Gold optional. <a href="https://example.test/apply">Apply</a></p>'
        f'<form>{token}</form><a href="/cdn-cgi/l/email-protection#{token}">Contact</a></body></html>')


def raw(body, url='https://example.statusmatch.com/faq'):
    return RawDocument(source_id='status_services_mail',external_id='faq',canonical_url=url,body=body,content_type='text/html')


def test_ingestion_body_omits_only_retired_fees_and_preserves_raw_and_mapping():
    source=raw(page());cleaned=lightly_clean(source)
    assert cleaned.raw_body==source.body and 'Retired country' in cleaned.raw_body
    assert 'Recently ended offers' not in cleaned.normalized_body
    assert 'Retired country' not in cleaned.normalized_body
    for text in ['Active country','USD 89','Example Air','Bronze','Mapping footnote','https://example.test/apply']:
        assert text in cleaned.normalized_body
    full=lightly_clean(source,exclude_historical_fees=False)
    assert 'Retired country' in full.normalized_body
    assert full.normalized_hash!=cleaned.normalized_hash
    assert 'Retired country' in lightly_clean(raw(page(),url='https://statusmatcher.com/company/example')).normalized_body
    assert 'Retired country' in lightly_clean(raw(page(),url='https://example.test/article')).normalized_body


def test_full_content_changes_are_observed_even_when_reading_text_is_identical(db_session):
    seed_sources(db_session);service=IngestionService(db_session)
    item=statusmatch_page_item(host='example.statusmatch.com',page_kind='faq',canonical_url='https://example.statusmatch.com/faq',refresh=True)
    moment=datetime(2026,9,13,tzinfo=UTC)
    def ingest(body):
        nonlocal moment
        result=service.ingest(item,raw(body));moment+=timedelta(seconds=1)
        record_statusmatch_page_result(db_session,item=item,result=result,checked_at=moment)
        return result
    first=ingest(page());assert first.new_version
    # Neither ads/forms nor volatile email tokens cause another observation.
    repeat=ingest(page(token='two'));assert not repeat.new_version
    changed=ingest(page(old_fee=149));assert changed.new_version
    assert first.document_version.normalized_body==changed.document_version.normalized_body
    assert first.document_version.id!=changed.document_version.id
    assert changed.document_version.duplicate_of_id is None
    # Reappearance of an exact older snapshot is detected without a UNIQUE error.
    reverted=ingest(page());assert reverted.new_version
    assert reverted.document_version.id==first.document_version.id
    assert service.current_document(item).id==first.document_version.id
    assert not ingest(page()).new_version
    # A newly retired region disappears from both current prose and price facts.
    moved=ingest(page(moved=True));assert moved.new_version
    assert 'Active country' not in moved.document_version.normalized_body
    assert 'Example Air' in moved.document_version.normalized_body
    routes=extract_statusmatch_price_routes(raw_html=moved.document_version.raw_body,canonical_url=item.canonical_url,document_version_id=moved.document_version.id)
    assert not routes
    assert not service.reparse_outdated_snapshots(source_id='status_services_mail')


def test_returned_snapshot_can_trigger_workflow_again_with_same_document_ids():
    watch=SimpleNamespace(id=uuid4());provider=SimpleNamespace(metadata=SimpleNamespace(config_version='test'))
    now=datetime(2026,9,13,tzinfo=UTC)
    pages={k:SimpleNamespace(current_document_version_id=uuid4(),last_changed_at=now) for k in ('activity','faq','terms')}
    first=statusmatch_project_job_key(watch,pages,provider)
    assert first==statusmatch_project_job_key(watch,pages,provider)
    pages['faq'].last_changed_at=now+timedelta(days=1)
    assert first!=statusmatch_project_job_key(watch,pages,provider)


def test_markdown_ingestion_retains_following_mapping_without_a_new_heading():
    source=raw('## Recently ended offers\n\n|Country|Status Tier|Application Fee|\n|---|---|---|\n|Old|Gold|USD 99|\n\n|Airline|Gold|\n|---|---|\n|Example Air|Silver|\n\nFootnote survives')
    source.content_type='text/markdown'
    body=lightly_clean(source).normalized_body
    assert 'USD 99' not in body and 'Example Air' in body and 'Footnote survives' in body


def test_historical_section_does_not_remove_fees_from_a_later_separate_section():
    source = raw('<h2>Recently ended offers</h2><h3>Old region</h3>' + fee('Retired country',99)
                 + '<h2>Current offers</h2>' + fee('Active country',89))
    body = lightly_clean(source).normalized_body
    assert 'Retired country' not in body
    assert 'Active country' in body and 'USD 89' in body
