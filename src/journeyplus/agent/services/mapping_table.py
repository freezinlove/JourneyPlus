"""Lossless display projection: programs in rows, target tiers in columns."""
from copy import deepcopy
import json


def mapping_table(mappings):
    targets=list(dict.fromkeys(m.get('to_tier',m.get('target_tier')) for m in mappings))
    programs={}
    for mapping in mappings:
        program=mapping.get('from_program',mapping.get('source_program')) or '其他来源'
        target=mapping.get('to_tier',mapping.get('target_tier'))
        tiers=mapping.get('from_tiers',mapping.get('source_tiers',[]))
        excluded={'ref','source_program','source_tiers','target_tier','from_program','from_tiers','to_program','to_tier',
                  'evidence','evidence_ids','schema_version'}
        notes={k:deepcopy(v) for k,v in mapping.items() if k not in excluded and v not in (None,'',[],{})}
        cells=programs.setdefault(program,[{} for _ in targets])
        cell=cells[targets.index(target)]
        key=json.dumps(notes,sort_keys=True,ensure_ascii=False)
        entry=cell.setdefault(key,{'tiers':[] ,**notes})
        entry['tiers']=list(dict.fromkeys([*entry['tiers'],*tiers]))
    return {'columns':['来源项目',*targets],
            'rows':[[program,*[list(cell.values()) for cell in cells]] for program,cells in programs.items()],
            'mapping_count':len(mappings)}
