"""Resumable artifact sections without dropping an oversized scalar forever."""
import hashlib,json


def matches(value,query):
    """Content search must not mistake a UUID substring for source evidence."""
    if isinstance(value,dict):
        return any((query in key.casefold() or matches(item,query)) for key,item in value.items()
                   if key not in {'ref','id','path','ancestors','content_hash','evidence_ids'}
                   and not key.endswith(('_ref','_refs','_id','_ids')))
    if isinstance(value,list):return any(matches(item,query) for item in value)
    return query in str(value).casefold()


def view(records,*,cursor=None,query=None,limit=30):
    """Read whole business sections, never split strings or scalar objects by bytes."""
    if not 1 <= limit <= 30:raise ValueError('Artifact view limit must be between 1 and 30')
    encoded=json.dumps(records,ensure_ascii=False,sort_keys=True)
    key=hashlib.sha256(('whole-sections-v2\n'+encoded+'\n'+(query or '')).encode()).hexdigest()[:24]
    if not query and not any(isinstance(r['payload'],dict) and isinstance(r['payload'].get('sections'),dict) for r in records):
        offset=0
        if cursor:
            saved,separator,raw=cursor.partition('|')
            if saved!=key or not separator or not raw.isdigit():raise ValueError('STALE_REFERENCE: artifact cursor does not match these refs and query')
            offset=int(raw)
            if offset>len(records):raise ValueError('Invalid artifact cursor offset')
        selected=records[offset:offset+limit];end=offset+len(selected)
        return {'artifacts':selected,'total':len(records),'next_cursor':key+'|'+str(end) if end<len(records) else None}
    sections=[]
    for record in records:
        payload=record['payload']
        if isinstance(payload,dict) and isinstance(payload.get('sections'),dict):
            # Facts and complete option/table sections replace their duplicated per-field indexes.
            names=[name for name in payload['sections'] if name in {'facts','brief','mapping_table'}
                   or name.startswith('option-') and name in {'option-'+o['ref'] for o in payload.get('options',[])}]
            if query:
                names=payload.get('search_section_keys',list(payload['sections']))
            for name in names:
                value=payload['sections'][name]
                if query and not matches(value,query.casefold()):continue
                sections.append({'artifact_ref':record['ref'],'path':'/sections/'+name,'value':value})
        else:
            if query and not matches(payload,query.casefold()):continue
            sections.append({'artifact_ref':record['ref'],'path':'','value':payload})
    offset=0
    if cursor:
        saved,separator,raw=cursor.partition('|')
        if saved!=key or not separator or not raw.isdigit():raise ValueError('STALE_REFERENCE: artifact cursor does not match these refs and query')
        offset=int(raw)
        if offset>len(sections):raise ValueError('Invalid artifact cursor offset')
    selected=sections[offset:offset+limit]
    end=offset+len(selected)
    return {'sections':selected,'section_count':len(sections),
            'next_cursor':key+'|'+str(end) if end<len(sections) else None}
