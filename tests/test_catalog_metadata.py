from tests.db_fixture import factory
from journeyplus.knowledge.publication import CatalogService
from journeyplus.knowledge.catalog_metadata import sync_catalog_metadata
from journeyplus.knowledge.routes import RouteService
from journeyplus.membership.alliances import exact_airline_alliance


def test_metadata_enrichment_is_exact_audited_and_invalidates_query_context(factory):
    assert exact_airline_alliance('United Kingdom') is None
    with factory.begin() as s:
        catalog=CatalogService(s);air=catalog.program('Air Canada Aeroplan');ambiguous=catalog.program('United Kingdom')
        before=RouteService(s).evaluation_context();result=sync_catalog_metadata(s)
        assert air.category=='AIRLINE' and air.alliance and air.metadata_provenance['alliance']['as_of']
        assert ambiguous.category=='OTHER' and ambiguous.alliance is None
        assert before!=RouteService(s).evaluation_context()
        assert result['updated'] and not sync_catalog_metadata(s)['updated']


def test_reviewed_parenthesized_program_spelling_uses_same_directory_metadata(factory):
    with factory.begin() as s:
        program=CatalogService(s).program('Lotusmiles (Vietnam Airlines)')
        sync_catalog_metadata(s)
        assert program.category=='AIRLINE' and program.alliance==exact_airline_alliance('Vietnam Airlines').value


def test_legacy_holding_links_preserve_labels_and_do_not_create_fuzzy_programs(factory):
    from journeyplus.models import StatusHolding
    from journeyplus.knowledge.holding_migration import backfill_holding_links
    with factory.begin() as s:
        catalog=CatalogService(s);program=catalog.program('Lufthansa Miles & More');tier=catalog.tier(program.id,'Senator')
        h=StatusHolding(program_key='lufthansa miles more',tier_key='senator',program_display_name='lufthansa miles more',tier_display_name='SENATOR')
        missing=StatusHolding(program_key='mystery',tier_key='gold',program_display_name='Mystery',tier_display_name='Gold');s.add_all([h,missing]);s.flush()
        before=(h.program_display_name,h.tier_display_name,h.valid_until);result=backfill_holding_links(s)
        assert h.program_id==program.id and h.tier_id==tier.id and h.identity_status=='CONFIRMED'
        assert (h.program_display_name,h.tier_display_name,h.valid_until)==before
        assert missing.tier_id is None and len(result['unresolved'])==1
        assert not backfill_holding_links(s)['mapped']
