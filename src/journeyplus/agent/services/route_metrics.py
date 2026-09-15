"""Simple matching comparisons. Exact prices belong to activity details."""
def metrics(routes):
    return {'items':[{'ref':r['ref'],'steps':r.get('step_count'),
                     'paid':r['paid']} for r in routes],
            'proven_free_route_refs':[r['ref'] for r in routes if r.get('paid') is False],
            'scope':'supplied_routes_only'}
