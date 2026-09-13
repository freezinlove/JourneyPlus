"""Shared, local programme/tier identity lookup. Never calls a model or network."""
from functools import lru_cache
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .normalization import normalize_key, normalize_tier, strip_program_prefix


@lru_cache(maxsize=1)
def directory():
    return json.loads(Path(__file__).with_name('identity_directory.json').read_text())


@lru_cache(maxsize=1)
def directory_version():
    return hashlib.sha256(Path(__file__).with_name('identity_directory.json').read_bytes()).hexdigest()[:16]


@lru_cache(maxsize=1)
def _index():
    programs, aliases, tiers = {}, {}, {}
    for program in directory()['programs']:
        key = program['key']
        if key in programs:
            raise ValueError('Duplicate identity programme: '+key)
        programs[key] = program
        for alias in [key, program['name'], *program['aliases']]:
            aliases.setdefault(normalize_key(alias), set()).add(key)
        for tier in program['tiers']:
            for alias in [tier['name'], *tier['aliases']]:
                tiers.setdefault((key, normalize_tier(alias)), set()).add(tier['name'])
    return programs, aliases, tiers


def program_candidates(name):
    programs, aliases, _ = _index()
    return [programs[k] for k in sorted(aliases.get(normalize_key(name), ()))]


def program_record(name):
    candidates = program_candidates(name)
    return candidates[0] if len(candidates) == 1 else None


def resolve_identity(program, tier=None):
    """Unknown/ambiguous labels stay unresolved; colours never cross programmes."""
    candidates = program_candidates(program)
    if len(candidates) != 1:
        return {'status': 'AMBIGUOUS' if candidates else 'NOT_FOUND',
                'program_name': program, 'tier_name': tier,
                'candidates': [{'program_name': p['name']} for p in candidates]}
    p = candidates[0]
    result = {'status': 'OK', 'program_key': p['key'], 'program_name': p['name'],
              'category': p['category'], 'tier_name': None, 'tier_key': None}
    if tier is None:
        return result
    aliases = [p['name'], program, *p['aliases']]
    label = strip_program_prefix(tier, aliases)
    matches = _index()[2].get((p['key'], normalize_tier(label)), set())
    if len(matches) != 1:
        return {**result, 'status': 'AMBIGUOUS' if matches else 'NOT_FOUND',
                'tier_name': tier, 'candidates': [t['name'] for t in p['tiers']]}
    name = next(iter(matches))
    record = next(t for t in p['tiers'] if t['name'] == name)
    return {**result, 'tier_name': name, 'tier_key': normalize_tier(name),
            'catalogue_state': record['state']}


def canonical_program(name):
    record = program_record(name)
    return record['name'] if record else name


def canonical_tier(program, tier):
    resolved = resolve_identity(program, tier)
    return resolved['tier_name'] if resolved['status'] == 'OK' else tier


def matches_identity_query(query, program, tier=None):
    """Search exact registered names, including joined Chinese programme + tier.

    This does not resolve free prose, infer a tier, or perform fuzzy binding.
    """
    p = program_record(program)
    if not p:
        return False
    program_names = [p['name'], *p['aliases']]
    tier_record = next((t for t in p['tiers'] if t['name'] == canonical_tier(program, tier)), None) if tier else None
    tier_names = [tier_record['name'], *tier_record['aliases']] if tier_record else []
    compact = lambda value: normalize_key(value).replace(' ', '')
    phrases = {compact(n) for n in program_names + tier_names}
    phrases.update(compact(pn + tn) for pn in program_names for tn in tier_names)
    if compact(query) in phrases:
        return True
    # Multiple Chinese names separated by spaces are independent search terms.
    terms = query.split()
    return len(terms) > 1 and all(any(ord(c) > 127 for c in term) for term in terms) and any(
        compact(term) in phrases for term in terms)


def normalize_facts(facts, program):
    """Entry-time normalization of identity fields only, preserving row order.

    No deduplication: separate mapping conditions and evidence retain their rows.
    Fee tier labels must change together with mapping targets.
    """
    return type(facts).model_validate(normalize_fact_payload(facts.model_dump(), program))


def normalize_fact_payload(facts, program):
    """Change names only, including historical JSON without adding new defaults."""
    result = deepcopy(facts)
    for mapping in result.get('status_mappings', []):
        original = mapping['source_program']
        mapping['source_tiers'] = [canonical_tier(original, t) for t in mapping['source_tiers']]
        mapping['source_program'] = canonical_program(original)
        mapping['target_tier'] = canonical_tier(program, mapping['target_tier'])
    for route in result.get('application_routes', []):
        for price in route.get('prices', []):
            if price.get('target_tier'):
                price['target_tier'] = canonical_tier(program, price['target_tier'])
    # target_status is often a whole sentence: only an exact registered name changes.
    if result.get('target_status', {}).get('value'):
        result['target_status']['value'] = canonical_tier(program, result['target_status']['value'])
    return result


def unregistered_names(facts, program):
    """Compact audit output; unknown extraction remains valid and is never dropped."""
    pairs = [(m.source_program, t) for m in facts.status_mappings for t in m.source_tiers]
    pairs += [(program, m.target_tier) for m in facts.status_mappings]
    return sorted({(p, t) for p, t in pairs if resolve_identity(p, t)['status'] != 'OK'})
