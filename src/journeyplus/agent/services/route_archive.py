"""Business overview ahead of lossless archive pages; never a new fact store."""
from copy import deepcopy
import json

from .materials import compact


def overviews(record):
    root, _, fragment=record['ref'].partition('#')
    payload=record['payload']
    if record.get('kind')=='ROUTES' and not fragment:
        routes=[{**payload['routes'][key], 'ref':root+'#route:'+key}
                for key in payload.get('route_order',sorted(payload.get('routes',{})))
                if key in payload.get('routes',{})]
        steps={root+'#step:'+key:value for key,value in payload.get('steps',{}).items()}
    elif record.get('kind')=='MATERIAL' and isinstance(payload.get('data',{}).get('candidates'),list):
        data=payload['data']
        routes=[row for row in data['candidates'] if '#route:' in str(row.get('ref',''))]
        values=data.get('steps',[])
        steps=values if isinstance(values,dict) else {row['ref']:row for row in values if 'ref' in row}
    else:
        return []
    result=[]
    for route in routes:
        route_root=route['ref'].partition('#')[0]
        refs=[sid if sid.startswith('artifact:') else route_root+'#step:'+sid
              for sid in route.get('step_refs',[])]
        ordered=[steps[ref] for ref in refs if ref in steps]
        summary={key:deepcopy(route[key]) for key in
                 ('ref','path','from','to','paid','cost','challenge','eligibility','constraint_match','source_versions')
                 if key in route}
        summary['object_type']='route'
        summary['step_details_available']=bool(refs) and len(ordered)==len(refs)
        if ordered:
            summary['path']=[ordered[0].get('from'),*[step.get('to') for step in ordered]]
            summary['steps']=[compact({**{key:deepcopy(step[key]) for key in
                ('paid','from','to','fees','cost_description','fee_unknown','fee_conflict','alternative_items',
                 'conditional_items','status_validity','challenge','eligibility','application_window',
                 'availability','application_scope','source_acquisition','constraint_checks','material_caveats',
                 'activity_ref','version_ref','brief_url','action_link','source_links') if key in step},
                'ref':ref,'object_type':'step'}) for ref,step in ((r,steps[r]) for r in refs if r in steps)]
        summary=compact(summary)
        # Do not split price/validity/conflict values into disconnected scalar
        # fragments. Oversized overviews remain explicit indexes; full pages follow.
        if len(json.dumps(summary,ensure_ascii=False).encode())>6000:
            summary={'ref':route['ref'],'object_type':'route','overview_omitted':True,
                     'reason':'Read this route with routes.evaluate inspect for its complete details.'}
        result.append({'artifact_ref':record['ref'],'section':'route_overview','derived':True,
                       'value':summary})
    return result
