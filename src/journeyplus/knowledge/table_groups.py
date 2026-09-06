"""Server-owned FAQ mapping groups, assigned to options without model recopying.

Only uniquely located, permitted normalized tables qualify. Raw HTML supplies
cell structure; every published group remains bound to a normalized section.
"""
from __future__ import annotations

from collections import defaultdict
import re
from types import SimpleNamespace
from journeyplus.facts.statusmatch_tables import extract_statusmatch_status_mappings, extract_statusmatch_mapping_source_metadata
from journeyplus.knowledge.publication import CatalogService, canonical_key, signature, price_tier_labels
from journeyplus.knowledge.models import MembershipProgram
from journeyplus.knowledge.sources import create_evidence
from journeyplus.contracts import StrictModel
from pydantic import Field
from uuid import UUID


class MappingTableAssignment(StrictModel):
    group_ref:str
    option_key:str
    include_source_program_ids:list[UUID]=Field(default_factory=list,max_length=100)
    exclude_source_program_ids:list[UUID]=Field(default_factory=list,max_length=100)


def prepare_mapping_groups(session, document, sections, target_program_id):
    if not target_program_id:
        return {}, []
    parsed = extract_statusmatch_status_mappings(raw_html=document.raw_body,
        canonical_url=document.canonical_url, document_version_id=document.id)
    tables = [section for section in sections if section.kind == 'TABLE']
    catalog = CatalogService(session)
    target_program = session.get(MembershipProgram, target_program_id)
    groups = defaultdict(list)
    categories = defaultdict(set)
    for metadata in extract_statusmatch_mapping_source_metadata(raw_html=document.raw_body,canonical_url=document.canonical_url):
        categories[canonical_key(metadata.source_program)].add(metadata.category.value)
    for mapping in parsed:
        if not mapping.source_tiers or mapping.conflict:
            continue
        # Do not attach a source row to an arbitrary table when there are several
        # candidate offers. Unlocatable rows remain available in source material.
        source_name = canonical_key(mapping.source_program)
        if source_name.startswith(('all major ', 'all eligible ')):
            continue  # These are category rules, never synthetic programs/tiers.
        matches = [table for table in tables
                   if source_name in canonical_key(re.sub(r'[*_`\\]','',table.body))
                   and any(label in canonical_key(re.sub(r'[*_`\\]','',table.body))
                           for label in price_tier_labels(target_program,
                               SimpleNamespace(display_name=mapping.target_tier),table.body))]
        if len(matches) != 1:
            continue
        table = matches[0]
        evidence = create_evidence(session, table.id, table.body)
        source = catalog.program(mapping.source_program)
        known_categories = categories[source_name]
        if source.category=='OTHER' and len(known_categories)==1 and next(iter(known_categories)) in {'AIRLINE','HOTEL','CRUISE'}:
            source.category=next(iter(known_categories))
            source.metadata_provenance={**source.metadata_provenance,'category':{'evidence_id':str(evidence.id),'origin':'OFFICIAL_FAQ_TABLE_HEADER'}}
        tiers = [catalog.tier(source.id, name) for name in mapping.source_tiers]
        target = catalog.tier(target_program_id, mapping.target_tier)
        for label in price_tier_labels(target_program, target, table.body):
            if label != canonical_key(target.display_name):
                alias = catalog.alias(label, target_program_id, target.id)
                alias.origin = 'OFFICIAL_TABLE_TARGET_LABEL'
        key = 'table-' + signature({'document': str(document.id), 'table': str(table.id),
                                   'source': str(source.id), 'target': str(target.id)})[:20]
        conditions = []
        evidence_ids = [str(evidence.id)]
        if mapping.conditions:
            # Footnotes are often adjacent paragraphs, not part of the table.
            # Bind their actual section as well as the row/header evidence.
            for section in sections:
                if section.kind == 'ROW':
                    continue
                plain = re.sub(r'[*_`\\]', '', section.body)
                if canonical_key(mapping.conditions) in canonical_key(plain):
                    ref = str(create_evidence(session, section.id, section.body).id)
                    if ref not in evidence_ids:
                        evidence_ids.append(ref)
            conditions = [{'condition_id': key + '-qualification', 'topic': 'OTHER',
                           'operator': 'TEXT', 'value': mapping.conditions,
                           'raw_text': mapping.conditions, 'known_state': 'KNOWN',
                           'evidence_ids': evidence_ids}]
        groups[str(table.id)].append({'key': key,
            'source_scope': {'kind': 'EXACT_TIERS', 'program_id': str(source.id),
                             'tier_ids': [str(t.id) for t in tiers],
                             'evidence_ids': [str(evidence.id)]},
            'target_program_id': str(target_program_id), 'target_tier_id': str(target.id),
            'conditions': {'items': conditions},
            'availability': 'AVAILABLE' if mapping.availability == 'AVAILABLE' else 'UNKNOWN',
            'evidence_ids': evidence_ids})
    stored, hints = {}, []
    for section_id, mappings in groups.items():
        table = next(t for t in tables if str(t.id) == section_id)
        ref = 'table-group-' + signature({'document': str(document.id), 'section': section_id})[:16]
        stored[ref] = mappings
        hints.append({'group_ref': ref, 'heading': table.heading_path,
                      'mapping_count': len(mappings),
                      'evidence_ids': sorted({e for m in mappings for e in m['evidence_ids']}),
                      'target_tier_ids': sorted({m['target_tier_id'] for m in mappings})})
    return stored, hints


def expand_mapping_assignments(payload, groups):
    """Expand exact group references before OptionDraft's price validation."""
    from copy import deepcopy
    if not isinstance(payload, dict):
        raise ValueError('Knowledge extraction must be a JSON object')
    payload = deepcopy(payload)
    if not isinstance(payload.get('options', []), list) or any(
            not isinstance(option, dict) for option in payload.get('options', [])):
        raise ValueError('Knowledge options must be an array of objects')
    if not isinstance(payload.get('table_assignments', []), list):
        raise ValueError('Table assignments must be an array')
    options = {option.get('logical_key'): option for option in payload.get('options', [])}
    assigned = set()
    for assignment in payload.pop('table_assignments', []):
        if not isinstance(assignment, dict) or not {'group_ref','option_key'}<=set(assignment) or set(assignment)-{'group_ref','option_key','include_source_program_ids','exclude_source_program_ids'}:
            raise ValueError('Table assignment requires a group, option and optional exact source-program filters')
        group, key = assignment['group_ref'], assignment['option_key']
        if group not in groups or key not in options or (group, key) in assigned:
            raise ValueError('Unknown or duplicate mapping table assignment')
        assigned.add((group, key))
        known={mapping['source_scope'].get('program_id') for mapping in groups[group]}
        include=set(map(str,assignment.get('include_source_program_ids',[])))
        exclude=set(map(str,assignment.get('exclude_source_program_ids',[])))
        if not (include|exclude)<=known or include&exclude:raise ValueError('Mapping group source filter is unknown or contradictory')
        selected=[mapping for mapping in groups[group] if (not include or mapping['source_scope'].get('program_id') in include)
                  and mapping['source_scope'].get('program_id') not in exclude]
        if not selected:raise ValueError('Mapping source filter removed the entire table group')
        options[key].setdefault('mappings', []).extend(deepcopy(selected))
    return payload
