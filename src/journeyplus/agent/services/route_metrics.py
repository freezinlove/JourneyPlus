"""Simple matching comparisons. Exact prices belong to activity details."""
def metrics(routes):
    return {'items':[{'ref':r['ref'],'steps':r.get('step_count'),
                     'paid':r.get('paid',not r.get('cost',{}).get('is_proven_free',False))} for r in routes],
            'proven_free_route_refs':[r['ref'] for r in routes if r.get('cost',{}).get('is_proven_free')],
            'scope':'supplied_routes_only'}
