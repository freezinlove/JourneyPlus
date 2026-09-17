from __future__ import annotations

from uuid import uuid4

from journeyplus.facts.statusmatch_tables import (
    extract_statusmatch_status_mappings,
)


def test_source_name_footnote_is_a_qualification_not_program_identity():
    html = '''<table><tr><td></td><td>Target Club Tier</td></tr>
    <tr><th>Airline</th><th>Gold</th></tr>
    <tr><td>Aer Lingus **** AerClub</td><td>Platinum</td></tr></table>
    <p>**** Limited to EU/UK Passport holders.</p>'''
    mappings = extract_statusmatch_status_mappings(raw_html=html,
        canonical_url='https://example.statusmatch.com/faq', document_version_id=uuid4())
    assert len(mappings) == 1
    assert mappings[0].source_program == 'Aer Lingus AerClub'
    assert mappings[0].availability == 'CONDITIONAL'
    assert mappings[0].conditions == 'Limited to EU/UK Passport holders.'


def test_mapping_parser_excludes_region_fee_tables_but_keeps_later_tier_table() -> None:
    html = """
    <html><body>
      <h3>Recently ended offers</h3>
      <table>
        <tr><td>Country/Region</td><td>Status Tier</td><td>Application Fee</td></tr>
        <tr><td>Canada</td><td>Gold</td><td>CAD 299</td></tr>
      </table>
      <table>
        <tr><td></td><td colspan="3">Target Club Tier</td></tr>
        <tr><td>AIRLINE</td><td>SILVER</td><td>GOLD</td><td>PLATINUM^ **</td></tr>
        <tr>
          <td><strong>Example Air</strong><p>Example Rewards</p></td>
          <td>Silver<br></td>
          <td>Gold<br>Platinum<br></td>
          <td>Diamond**<br></td>
        </tr>
        <tr>
          <td><strong>Second Air</strong><p>Second Club</p></td>
          <td></td><td>Not Available</td><td>Not Available</td>
        </tr>
      </table>
      <p>* Illustrative examples. ** Applicants may choose Gold instead.
         ^ Platinum is unavailable in Example Region.</p>
    </body></html>
    """

    mappings = extract_statusmatch_status_mappings(
        raw_html=html,
        canonical_url="https://example.statusmatch.com/faq",
        document_version_id=uuid4(),
    )

    assert len(mappings) == 6
    assert not any("Canada" in mapping.source_program for mapping in mappings)
    example_gold = next(
        mapping
        for mapping in mappings
        if mapping.source_program == "Example Air Example Rewards"
        and mapping.target_tier == "Target Club GOLD"
    )
    assert example_gold.source_tiers == ["Gold", "Platinum"]
    example_platinum = next(
        mapping
        for mapping in mappings
        if mapping.source_program == "Example Air Example Rewards"
        and mapping.target_tier == "Target Club PLATINUM"
    )
    assert example_platinum.availability == "CONDITIONAL"
    assert "Example Region" in (example_platinum.conditions or "")
    assert "choose Gold" in (example_platinum.conditions or "")
    unavailable = next(
        mapping
        for mapping in mappings
        if mapping.source_program == "Second Air Second Club"
        and mapping.target_tier == "Target Club SILVER"
    )
    assert unavailable.availability == "UNAVAILABLE"
    assert unavailable.source_tiers == []


def test_mapping_parser_structures_flat_existing_program_tier_table() -> None:
    html = """
    <table>
      <tr><td>Existing programme &amp; tier</td><td>Enrich tier</td></tr>
      <tr><td>Air India Maharaja Club Silver</td><td>Enrich Silver</td></tr>
      <tr><td>Air India Maharaja Club Gold</td><td>Enrich Gold</td></tr>
    </table>
    """

    mappings = extract_statusmatch_status_mappings(
        raw_html=html,
        canonical_url="https://enrich.statusmatch.com/faq",
        document_version_id=uuid4(),
    )

    assert [mapping.source_program for mapping in mappings] == [
        "Air India Maharaja Club",
        "Air India Maharaja Club",
    ]
    assert [mapping.source_tiers for mapping in mappings] == [["Silver"], ["Gold"]]
    assert [mapping.target_tier for mapping in mappings] == [
        "Enrich Silver",
        "Enrich Gold",
    ]


def test_plural_airlines_and_allowed_column_are_not_target_tiers():
    from uuid import uuid4
    html = """<table><tr><th>Airlines</th><th>Matching Allowed &amp; Selected</th><th>Elite</th><th>Premier Elite</th></tr>
    <tr><td>Lufthansa</td><td>Yes</td><td>Frequent Traveller</td><td>Senator<br>HON Circle</td></tr>
    <tr><td>Excluded Air</td><td>No</td><td>Gold</td><td>Platinum</td></tr></table>"""
    rows = extract_statusmatch_status_mappings(raw_html=html,
        canonical_url="https://philippineairlines.statusmatch.com/faq/", document_version_id=uuid4())
    assert len(rows) == 2
    assert rows[1].target_tier == "Premier Elite"
    assert rows[1].source_tiers == ["Senator", "HON Circle"]
    assert all(row.source_program == "Lufthansa" for row in rows)
