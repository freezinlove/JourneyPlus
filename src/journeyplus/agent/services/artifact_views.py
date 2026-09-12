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
    if not 1 <= limit <= 30:raise ValueError('Artifact view limit must be between 1 and 30')
    encoded=json.dumps(records,ensure_ascii=False,sort_keys=True)
    key=hashlib.sha256(('route-overview-v1\n'+encoded+'\n'+(query or '')).encode()).hexdigest()[:24]
    from .route_archive import overviews
    summaries=[section for record in records for section in overviews(record)
               if not query or matches(section['value'],query.casefold())]
    small = len(encoded.encode()) <= 2500 and not query and not summaries
    if small:
        offset = 0
        if cursor:
            saved, separator, raw = cursor.partition('|')
            if saved != key or not separator or not raw.isdigit():
                raise ValueError('STALE_REFERENCE: artifact cursor does not match these refs and query')
            offset = int(raw)
            if offset > len(records):raise ValueError('Invalid artifact cursor offset')
        selected = records[offset:offset+limit]
        end = offset+len(selected)
        return {'artifacts': selected, 'total': len(records),
                'next_cursor': key+'|'+str(end) if end<len(records) else None}
    chunks=list(summaries)
    def walk(ref,value,path,ancestors=()):
        serialized=json.dumps(value,ensure_ascii=False)
        context={'ancestors':list(ancestors)} if ancestors else {}
        if len(serialized.encode())<=1800:
            chunks.append({'artifact_ref':ref,'path':path,'value':value,**context})
        elif isinstance(value,dict):
            # Keep the original parent identity/state alongside fragmented data.
            # A fee or condition chunk must not become detached from its version
            # or UNKNOWN marker merely because an enclosing object is large.
            fields={key:item for key,item in value.items()
                    if not isinstance(item,(dict,list)) and len(json.dumps(item,ensure_ascii=False).encode())<=500}
            parents=(*ancestors,{'path':path,'fields':fields}) if fields else ancestors
            for name,item in value.items():walk(ref,item,path+'/'+name.replace('~','~0').replace('/','~1'),parents)
        elif isinstance(value,list):
            for index,item in enumerate(value):walk(ref,item,path+'/'+str(index),ancestors)
        elif isinstance(value,str):
            for offset in range(0,len(value),400):
                chunks.append({'artifact_ref':ref,'path':path,'value':value[offset:offset+400],
                               'start':offset,'end':min(offset+400,len(value)),'characters':len(value),**context})
        else:raise ValueError('Unsupported artifact value')
    for record in records:
        payload=record['payload'];start=len(chunks)
        if query and isinstance(payload.get('sections'),dict):
            # Search whole original sections BEFORE pagination. Filtering tiny
            # chunks after splitting loses a mapping's fee/conditions whenever
            # its source name occurs in a different chunk. Sections also avoid
            # replaying both the original options and their section copies.
            for name,section in payload['sections'].items():
                if name not in payload.get('search_section_keys',payload['sections']):continue
                if matches(section,query.casefold()):
                    walk(record['ref'],section,'/sections/'+name.replace('~','~0').replace('/','~1'))
        elif query and isinstance(payload.get('snippets'),list):
            for index,snippet in enumerate(payload['snippets']):
                if matches(snippet,query.casefold()):
                    walk(record['ref'],snippet,'/snippets/'+str(index),
                         ({'path':'','fields':{key:payload[key] for key in ('activity_ref','version_ref') if key in payload}},))
        else:
            walk(record['ref'],payload,'')
            if query:chunks[start:]=[chunk for chunk in chunks[start:] if matches(chunk['value'],query.casefold())]
    offset=0
    if cursor:
        saved,separator,raw=cursor.partition('|')
        if saved!=key or not separator or not raw.isdigit():raise ValueError('STALE_REFERENCE: artifact cursor does not match these refs and query')
        offset=int(raw)
        if offset>len(chunks):raise ValueError('Invalid artifact cursor offset')
    selected=[];size=0
    for chunk in chunks[offset:]:
        length=len(json.dumps(chunk,ensure_ascii=False).encode())
        if len(selected)>=limit or selected and size+length>2500:break
        selected.append(chunk);size+=length
    return {'sections':selected,'section_count':len(chunks),'next_cursor':key+'|'+str(offset+len(selected)) if offset+len(selected)<len(chunks) else None}
