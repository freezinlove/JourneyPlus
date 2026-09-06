import json
from decimal import Decimal
from pathlib import Path
import re
from journeyplus.knowledge.transport import ModelDecisionPacket


def snapshot():return json.loads(Path('tests/fixtures/knowledge_validation/public_snapshot.json').read_text())


def test_frozen_public_fixture_has_complete_references_and_no_private_state():
    data=snapshot();packet=data['routes'];ModelDecisionPacket.model_validate(packet)
    assert packet['data']['query']['use_saved_holdings'] is False
    assert 'workspace' not in packet and 'server_routes' not in packet
    assert not re.search(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',json.dumps(data))
    for route in packet['data']['cards']:
        assert all(ref in packet['data']['steps'] for ref in route['step_refs'])
        assert all(ref in packet['data']['material_caveats'] for ref in route['material_caveat_refs'])


def test_frozen_fee_scope_unknown_and_alternative_path_gold():
    data=snapshot();rj=next(a for a in data['activities'] if a['name'].startswith('Royal Jordanian'))
    assert any(f['value']=='USD 149' and 'GOLD SPARROW' in f['label'] for f in rj['card']['fees'])
    assert not any(f['value']=='USD 49' and 'GOLD SPARROW' in f['label'] for f in rj['card']['fees'])
    routes=data['routes']['data']['cards'];avolta=[r for r in routes if r['to']=='Club Avolta Gold']
    assert len(avolta)>1 and len({tuple(r['step_refs']) for r in avolta})==len(avolta)
    for route in routes:
        if route['classification']=='MATCH':assert sum(Decimal(f['amount']) for f in route['cost']['totals'] if f['currency']=='USD')<=100
        if route['to']=='Radisson Rewards Premium':assert route['classification']=='UNKNOWN' and not route['cost']['is_proven_free']
