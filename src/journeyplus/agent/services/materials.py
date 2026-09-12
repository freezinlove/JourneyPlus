"""Lossless full materials plus small, directly addressable model sections."""
from copy import deepcopy


def compact(value):
    if isinstance(value,list):return [compact(item) for item in value]
    if not isinstance(value,dict):return value
    # Evidence remains in the immutable section; do not duplicate identifiers in
    # every value. Unknown states and the source's actual conditions are retained.
    return {key:compact(item) for key,item in value.items() if key not in {'schema_version','evidence_ids','evidence','logical_ref'} and not (key=='raw_text' and not item)}


def sectioned(detail):
    value=deepcopy(detail)
    sections={'facts':{'activity_ref':value['ref'],'version_ref':value['version_ref'],'facts':value['facts']}}
    searchable=[]
    scope={'activity_ref':value['ref'],'version_ref':value['version_ref']}
    if value.get('briefs'):
        sections['brief']={**scope,'briefs':value['briefs']}
        searchable.append('brief')
    for field,item in value['facts'].items():
        key='fact-'+field
        sections[key]={**scope,field:item};searchable.append(key)
    for option in value.get('options',[]):
        base={key:item for key,item in option.items() if key!='mappings'}
        sections['option-'+option['ref']]={'activity_ref':value['ref'],'version_ref':value['version_ref'],'option':base}
        for field,item in base.items():
            if field in {'ref','logical_ref','label','method','availability'}:continue
            key='option-'+option['ref']+'-'+field
            sections[key]={**scope,'option_ref':option['ref'],'option_label':option['label'],
                           'availability':option['availability'],field:item}
            searchable.append(key)
        for mapping in option.get('mappings',[]):
            sections['mapping-'+mapping['ref']]={'activity_ref':value['ref'],'version_ref':value['version_ref'],
                'option_ref':option['ref'],'option_label':option['label'],'mapping':mapping}
            searchable.append('mapping-'+mapping['ref'])
    if 'evidence' in value:
        evidence=value['evidence']
        sections['evidence-sources']={**scope,'snippets':evidence.get('data',{}).get('snippets',[]),
                                     'coverage':evidence.get('coverage'), 'expansions':evidence.get('expansions',[])}
        for snippet in evidence.get('data',{}).get('snippets',[]):
            key='source-'+snippet['ref'];sections[key]={**scope,**snippet};searchable.append(key)
    value['sections']=sections
    value['search_section_keys']=searchable
    return value


def summary(detail,ref,view):
    value={'ref':f"activity:{detail['ref']}@{detail['version_ref']}",'material_ref':ref,'title':detail['name'],
           'version_ref':detail['version_ref'],'brief_url':detail['brief_url'],'summary':detail.get('card'),
           'is_current':detail.get('is_current'),'current_version_ref':detail.get('current_version_ref')}
    if detail.get('briefs'):
        value['brief_section_ref']=ref+'#section:brief'
    if view=='detail':
        value['facts']=compact(detail['facts'])
        value['options']=[]
        for option in detail.get('options',[]):
            item=compact({key:val for key,val in option.items() if key!='mappings'})
            item['section_ref']=ref+'#section:option-'+option['ref']
            item['mapping_count']=len(option.get('mappings',[]))
            item['mapping_index']=[{'section_ref':ref+'#section:mapping-'+m['ref'],
                'from_program':m.get('from_program'),'from_tiers':m.get('from_tiers'),
                'to_tier':m.get('to_tier')} for m in option.get('mappings',[])[:5]]
            item['mapping_index_complete']=len(option.get('mappings',[]))<=5
            value['options'].append(item)
        value['section_access']='For a specific source, workspace.read kind=artifact with refs=[material_ref] and query=source name locates matching original sections. Or use activity.read section_refs for a listed section. The mapping index is a preview; omitted mappings remain in the full material.'
    if view=='changes':value['history']=detail.get('history')
    if 'evidence' in detail:
        evidence=detail['evidence'];data=evidence.get('data',{})
        value['evidence']={'facts':compact(data.get('facts',[])), 'catalog':data.get('catalog',[]),
            'source_sections_ref':ref+'#section:evidence-sources',
            'source_section_count':len(data.get('snippets',[])),
            'coverage':evidence.get('coverage'),'expansions':evidence.get('expansions',[]),
            'caveats':evidence.get('caveats',[]),
            'scope':'Requested facts with applicable conditions. Original source sections remain separately retrievable; not yet all read.'}
    return value
