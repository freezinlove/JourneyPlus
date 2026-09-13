"""Existing production and read paths work without per-field evidence."""
from uuid import UUID

from sqlalchemy import select

from journeyplus.article_operations import process_pending_articles
from journeyplus.contracts import FactField, FactSet
from journeyplus.knowledge.source_documents import source_documents
from journeyplus.knowledge.workflow_knowledge import WorkflowActivityReader
from journeyplus.membership.contributions import StatusMatchOfficialContributionAdapter, OrdinaryArticleContributionAdapter
from journeyplus.models import ArticleOpportunityRecord, BriefRecord, FactSetRecord, StatusEvent
from journeyplus.product.briefs import ProductBriefService
from journeyplus.statusmatch.graph import MembershipGraphService
from journeyplus.statusmatch.project_workflow import process_pending_statusmatch_projects
from tests.test_agent_workflow_reads import original_factory
from tests.test_article_pipeline_v2 import V2Provider, _collect
from tests.test_statusmatch_project_workflow import ProjectProvider, _extraction, _seed_active_watch


def without_evidence(value):
    if isinstance(value, dict):
        return {key: without_evidence(child) for key, child in value.items()
                if key not in {'evidence', 'raw_text'}}
    if isinstance(value, list):
        return [without_evidence(child) for child in value]
    return value


def test_official_production_archive_brief_and_graph_without_field_evidence(original_factory):
    with original_factory.begin() as session:
        _seed_active_watch(session)
    provider = ProjectProvider([without_evidence(_extraction(narrative_mappings=[{
        "source_program": "Example Air", "source_tiers": ["Gold"],
        "target_tier": "Gold", "availability": "AVAILABLE",
    }]))])
    result = process_pending_statusmatch_projects(original_factory, provider)
    assert (result.succeeded, result.failed, result.model_calls) == (1, 0, 2), result.errors
    fact_id = UUID(result.projects[0].fact_set_id)
    with original_factory.begin() as session:
        record = session.get(FactSetRecord, fact_id)
        assert record.facts['what_happened']['evidence'] == []
        # Table parsers may keep optional metadata; consumers must also work
        # when it is absent from every mapping and price.
        record.facts = FactSet.model_validate(without_evidence(record.facts)).model_dump(mode='json')
        event = session.get(StatusEvent, record.event_id)
        brief = session.get(BriefRecord, event.current_brief_id)
        assert {url.rstrip('/') for url in brief.content['source_links']} == {
            'https://example.statusmatch.com', 'https://example.statusmatch.com/faq',
            'https://example.statusmatch.com/terms',
        }
        event_id = event.id
    with original_factory() as session:
        reader = WorkflowActivityReader(session)
        detail = reader.detail(event_id)
        assert len(detail['sources']) == 3
        assert detail['briefs']
        ref = 'document:' + detail['sources'][0]['document_version_ref'] + ':0'
        material = reader.materials(selector={'ref': str(event_id)}, version_ref=str(fact_id), section_refs=[ref])
        assert material['data']['snippets'][0]['text']
        graph = MembershipGraphService(session).build()
        assert graph.edges
        batch = StatusMatchOfficialContributionAdapter(session).read()
        assert batch.contributions
        assert all(claim.provenance.source_url for claim in batch.contributions)
        assert all(not claim.evidence for claim in batch.contributions)
        assert MembershipGraphService(session).audit().fidelity.missing_evidence_claim_ids == []
        assert any(item.opportunity_id == fact_id for item in ProductBriefService(session).list().items)
    repeated = process_pending_statusmatch_projects(original_factory, provider)
    assert repeated.model_calls == 0

    # Later captures must not silently change the archive for the first facts.
    from journeyplus.models import DocumentVersion, StatusMatchChangeSet
    with original_factory.begin() as session:
        batch = session.scalar(select(StatusMatchChangeSet))
        old_document = session.get(DocumentVersion, batch.faq_document_version_id)
        replacement = DocumentVersion(
            source_item_id=old_document.source_item_id, canonical_url=old_document.canonical_url,
            raw_body='Later FAQ', normalized_body='Later FAQ', content_type='text/plain',
            storage_mode='test', raw_hash='a' * 64, normalized_hash='a' * 64,
            parser_version='archive-version-test', fetched_at=old_document.fetched_at,
        )
        session.add(replacement)
        session.flush()
        current = session.get(FactSetRecord, fact_id)
        newer = FactSetRecord(event_id=event_id, version=2, schema_version=current.schema_version, facts=current.facts)
        session.add(newer)
        session.flush()
        session.add(StatusMatchChangeSet(
            event_id=event_id, from_fact_set_id=fact_id, to_fact_set_id=newer.id,
            activity_document_version_id=batch.activity_document_version_id,
            faq_document_version_id=replacement.id, terms_document_version_id=batch.terms_document_version_id,
            kind='FACTS_CHANGED', changes=[],
        ))
        session.get(StatusEvent, event_id).current_fact_set_id = newer.id
        old_doc_id, new_doc_id, new_fact_id = old_document.id, replacement.id, newer.id
    with original_factory() as session:
        reader = WorkflowActivityReader(session)
        historical = reader.detail(event_id, fact_id)
        current = reader.detail(event_id, new_fact_id)
        assert str(old_doc_id) in {doc['document_version_ref'] for doc in historical['sources']}
        assert str(new_doc_id) not in {doc['document_version_ref'] for doc in historical['sources']}
        assert str(new_doc_id) in {doc['document_version_ref'] for doc in current['sources']}


def test_article_production_keeps_links_and_mapping_without_quotes(original_factory):
    body = ('Example Air offers a direct status match to Gold. '
            'Marriott Bonvoy Platinum members pay USD 99. '
            'Apply at https://example-air.test/apply')
    with original_factory.begin() as session:
        _collect(session, [('optional-evidence', 'Example Air status match', body)])

    class Provider(V2Provider):
        def generate_structured(self, **kwargs):
            result = super().generate_structured(**kwargs)
            if kwargs['output_model'].__name__ == 'ArticleInterpretation':
                payload = without_evidence(result.model_dump(mode='json'))
                opportunity = payload['opportunities'][0]
                opportunity['cost'] = {'value': 'USD 99'}
                opportunity['status_mappings'] = [{
                    'source_program': 'Marriott Bonvoy', 'source_tiers': ['Platinum'],
                    'target_tier': 'Gold', 'availability': 'AVAILABLE',
                }]
                result = kwargs['output_model'].model_validate(payload)
            return result

    provider = Provider()
    result = process_pending_articles(original_factory, provider)
    assert result.failed == 0, result
    assert [call['model'] for call in provider.calls] == ['TitleScreenBatch', 'ArticleInterpretation', 'Brief']
    with original_factory() as session:
        record = session.scalar(select(ArticleOpportunityRecord))
        assert record.facts['cost']['value'] == 'USD 99'
        assert record.facts['cost']['evidence'] == []
        documents = source_documents(session, record)
        assert len(documents) == 1
        detail = WorkflowActivityReader(session).detail(record.id)
        assert len(detail['sources']) == 1
        assert 'https://loyaltylobby.com/optional-evidence/' in detail['card']['source_links']
        assert detail['facts']['action_link']['value'] == 'https://example-air.test/apply'
        batch = OrdinaryArticleContributionAdapter(session).read()
        assert any(claim.source_program == 'Marriott Bonvoy' for claim in batch.contributions)
        assert not any(item.reason == 'UNGROUNDED' for item in batch.excluded)
        assert ProductBriefService(session).list().items


def test_missing_evidence_does_not_silently_discard_new_fact_values():
    from journeyplus.facts.service import FactConsolidator
    result = FactConsolidator._reconcile_field(FactField(value='USD 99'), FactField(value='USD 129'))
    assert result.conflict
    assert set(result.alternatives) == {'USD 99', 'USD 129'}
