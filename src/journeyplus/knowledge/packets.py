"""Deterministic bounded disclosure; never truncate strings or serialized JSON."""
from copy import deepcopy
import json


def encoded_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def decision_packet(result: dict, *, max_bytes: int = 15000) -> dict:
    """Keep atomic facts/cards; an omitted item remains explicitly inspectable.

    Byte ceilings are conservative input limits, not claims about provider tokens.
    Source sections are one atomic group because a footnote can reverse a rule.
    """
    packet = deepcopy(result)
    omitted = []
    if encoded_bytes(packet) <= max_bytes:
        return packet
    data = packet.get('data', {})
    # Do not split a table from its exceptions just to satisfy an input budget.
    if data.get('snippets'):
        omitted.extend({'ref': x['ref'], 'kind': 'SECTION'} for x in data['snippets'])
        data['snippets'] = []
    for key in ('changes', 'facts', 'cards', 'routes', 'activities'):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        while items and encoded_bytes(packet) > max_bytes - 1200:
            item = items.pop()
            if isinstance(item, dict) and item.get('ref'):
                omitted.append({'ref': item['ref'], 'kind': key.upper()})
    if omitted:
        packet['status'] = 'PARTIAL'
        packet.setdefault('caveats', []).append('内容预算限制：部分完整资料尚未展开；不能据此判断没有限制或没有其他方案。')
        packet.setdefault('coverage', {}).update(presentation_has_more=True, content_complete=False, content_stopped_reason='MODEL_INPUT_BUDGET')
        packet['expansions'] = (packet.get('expansions', []) + omitted)[:12]
        packet['omitted_item_count'] = len(omitted)
    if encoded_bytes(packet) > max_bytes:
        # A single indivisible record can exceed the budget. Fail closed, preserving
        # the exact snapshot and the query scope instead of sending a partial rule.
        return {'schema_version': 1, 'status': 'NEEDS_INSPECTION', 'snapshot_ref': packet.get('snapshot_ref'),
                'data': {}, 'coverage': {**packet.get('coverage', {}), 'content_complete': False},
                'caveats': ['完整对象超出本轮内容预算，请限定活动、方案或问题维度后继续读取。'],
                'expansions': packet.get('expansions', [])[:3]}
    return packet
