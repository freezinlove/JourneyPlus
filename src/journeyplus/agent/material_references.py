"""Associate disclosed nested evidence with its immutable activity version."""


def material_refs(material):
    data=material.get('data',{})
    found=set()
    def visit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='ref' and isinstance(item,str):found.add(item)
                elif key=='evidence_ids' and isinstance(item,list):found.update(x for x in item if isinstance(x,str))
                else:visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    # Deliberately exclude catalog: programme/tier identities are not evidence.
    for key in ('activities','facts','snippets'):visit(data.get(key,[]))
    return found


def belongs_to_versions(ref,versions,materials):
    for material in materials:
        data=material.get('data',{})
        activities=data.get('activities',[])
        owners={a['version_ref'] for a in activities if a.get('version_ref')}
        for activity in activities:
            if activity.get('ref')==ref and activity.get('version_ref') in versions:return True
        for kind in ('facts','snippets'):
            for item in data.get(kind,[]):
                if ref not in material_refs({'data':{kind:[item]}}):continue
                # Parent provenance owns nested prices/evidence, including when
                # multiple activity versions share a single transport envelope.
                explicit=item.get('version_ref')
                prefix=item.get('ref','').split('/')[0]
                owner=explicit or (prefix if prefix in owners else next(iter(owners)) if len(owners)==1 else None)
                if owner in versions:return True
    return False
