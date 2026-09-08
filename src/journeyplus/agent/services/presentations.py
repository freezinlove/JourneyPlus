"""Pure builders preserve model-selected order and immutable version links."""
from copy import deepcopy


def build_block(selection, objects):
    payload={'objects':[]}
    links=[]
    for ref,obj in zip(selection.object_refs,objects):
        value=deepcopy(obj)
        if selection.type in {'route_graph','comparison'}:
            if not value.get('step_refs') or 'cost' not in value:
                raise ValueError('Selected object is not a computed route')
        if selection.type=='activity_card' and not value.get('version_ref'):
            raise ValueError('Activity card requires a published version')
        if value.get('brief_url'):
            links.append({'object_ref':ref,'url':value['brief_url'],'version_ref':value['version_ref']})
        for brief in value.get('brief_links',[]):
            link={'object_ref':ref,'url':brief['url'],'version_ref':brief['version_ref']}
            if link not in links:links.append(link)
        payload['objects'].append({'ref':ref,'data':value})
    return {'type':selection.type,'title':selection.title,'reason':selection.reason,
            'ordered_refs':selection.object_refs,'roles':[r.model_dump() for r in selection.roles],
            'columns':selection.columns,'labels':[obj.get('name',obj.get('title',obj.get('to',''))) for obj in objects],'links':links,'payload':payload}
