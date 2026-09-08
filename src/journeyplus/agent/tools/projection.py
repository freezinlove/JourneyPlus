"""Tool-owned atomic row groups for model projections."""
from .results import DATA_MODELS

PRIMARY = {'catalog.lookup': ('candidates',), 'activity.read': ('activities','sections'),
           'routes.evaluate': ('candidates',), 'holdings.read': ('holdings',),
           'waiting.manage': ('goals',), 'workspace.read': ('messages','artifacts','sections'),
           'web.search': ('results',), 'research.parse': ('reports',)}


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
