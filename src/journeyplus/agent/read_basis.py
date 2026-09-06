"""Small execution receipts for the user's expandable answer basis."""
from journeyplus.models import now_utc


def read_basis(tool,packet,reason=None):
    data=packet.get('data',{});versions=[]
    for item in [*data.get('activities',[]),*data.get('steps',{}).values(),*data.get('research_steps',[])]:
        ref=item.get('version_ref')
        if ref and ref not in versions:versions.append(ref)
    result={'tool':tool,'status':packet.get('status'),'coverage':packet.get('coverage'),'snapshot_ref':packet.get('snapshot_ref'),
            'read_at':now_utc().isoformat(),'version_refs':versions[:12],'additional_version_count':max(0,len(versions)-12)}
    if data.get('reason_counts'):
        result['filter_reasons']=dict(list(data['reason_counts'].items())[:12])
    if reason:result['reason']=reason
    return result
