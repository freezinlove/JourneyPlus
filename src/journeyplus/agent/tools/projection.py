"""Tool-owned atomic row groups for model projections."""
from .results import DATA_MODELS

PRIMARY = {'catalog.lookup': ('candidates',), 'activity.read': ('activities','sections'),
           'routes.evaluate': ('candidates',), 'holdings.read': ('holdings',),
           'waiting.manage': ('goals',), 'workspace.read': ('messages','artifacts','sections'),
           'web.search': ('results',), 'research.parse': ('reports',)}


def model_view_for(name):
    """Small operation observations; full receipts stay in the artifact store.

    This hook never changes persisted business records or explicit artifact reads.
    Projection is idempotent so old messages and newly completed calls agree.
    """
    if name not in {'holdings.read', 'holdings.write', 'waiting.manage'}:
        return None

    def entity(row):
        if not isinstance(row, dict):
            return row
        # Keep unknowns, actual conditions, identity status and revision. Only
        # the audit copy of user wording and duplicate extraction labels go.
        return {key: value for key, value in row.items()
                if key not in {'source_record', 'display_statement', 'name_authority',
                               'conditions_schema_version'}}

    def view(result):
        result = result.model_copy(deep=True)
        if result.error or result.status not in {'OK', 'EMPTY'}:
            return result
        data = result.data
        if data.get('projection') == 'operation_summary':
            return result
        if 'outcome' in data:
            before, after = entity(data.get('before')), entity(data.get('after'))
            compact = {key: value for key, value in data.items() if key not in {'before', 'after'}}
            compact['entity'] = after if after is not None else before
            compact['state'] = ('present' if after is not None else
                                'deleted' if before is not None else 'absent')
            if isinstance(before, dict) and isinstance(after, dict):
                compact['changes'] = {key: {'from': before.get(key), 'to': after.get(key)}
                                      for key in before.keys() | after.keys()
                                      if key not in {'revision', 'ref'} and before.get(key) != after.get(key)}
            compact['projection'] = 'operation_summary'
            result.data = compact
            # A write has no list page. Status/outcome remain authoritative.
            result.coverage = {key: value for key, value in result.coverage.items()
                               if key not in {'total', 'returned', 'complete', 'omissions'}}
        else:
            for key in ('holdings', 'goals'):
                if isinstance(data.get(key), list):
                    data[key] = [entity(row) for row in data[key]]
        # Arguments remain in the paired model call. Unlike route queries,
        # these do not carry inherited constraints absent from that call.
        result.effective_input = {}
        return result

    return view


def trim_for(name):
    def trim(result):
        data=result.data
        key=next((key for key in PRIMARY.get(name,()) if isinstance(data.get(key),list)),None)
        if key is None or len(data[key])<=1:return None
        data[key].pop()
        count=len(data[key])
        if name=='routes.evaluate':
            if 'route_refs' in data:data['route_refs']=[row['ref'] for row in data[key]]
            if 'steps' in data:
                used={ref for row in data[key] for ref in row.get('step_refs',[])}
                data['steps']=[step for step in data['steps'] if step['ref'] in used]
            if 'metrics' in data:
                from journeyplus.agent.services.route_metrics import metrics
                data['metrics']={key:value for key,value in metrics(data['candidates']).items() if key!='items'}
        elif name=='research.parse':
            data['report_refs']=data['report_refs'][:count]
            data['comparisons']=data['comparisons'][:count]
        return count
    return trim
