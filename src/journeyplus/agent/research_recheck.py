"""Experience signals request official reading; they never mutate official facts."""
import re
from journeyplus.knowledge.packets import decision_packet


def needs_official_recheck(observation):
    if observation.get('official_recheck_needed'):return True
    for citation in observation.get('citations',[]):
        text=citation.get('evidence_excerpt') or ''
        if re.search(r'(?:matched|status match).{0,80}(?:not accepted|ineligible|not eligible|rejected)|(?:must|needs? to|required to).{0,30}(?:earned|fly|stay)|匹配.{0,20}(?:不接受|不认可)|必须.{0,12}(?:保级|飞行|入住)',text,re.I):return True
    return False


def recheck_official_materials(packet,steps,read,cache,*,limit=2):
    reads=[]
    for observation in packet.get('data',{}).get('step_observations',[]):
        if not needs_official_recheck(observation):continue
        step=steps.get(observation['step_ref'])
        if not step:continue
        activity=step['activity_ref']
        if activity not in cache:
            if len(cache)>=limit:
                observation['official_recheck_status']='PENDING_BUDGET';continue
            try:
                material=read(step)
                cache[activity]=decision_packet(material,max_bytes=5000)
                reads.append({'activity_ref':activity,'material':cache[activity]})
            except Exception as exc:
                cache[activity]={'status':'FAILED','data':{},'error_type':type(exc).__name__}
                reads.append({'activity_ref':activity,'material':cache[activity]})
        material=cache[activity]
        refs=[{'activity_ref':a['ref'],'version_ref':a['version_ref']} for a in material.get('data',{}).get('activities',[]) if a.get('version_ref')]
        observation['official_recheck_status']='FACTS_READ_REQUIRES_REVIEW' if refs else 'UNAVAILABLE'
        observation['official_recheck_refs']=refs
        observation['official_recheck_version_changed']=any(ref['version_ref']!=step['version_ref'] for ref in refs)
    if reads:packet['data']['official_rechecks']=reads
    return packet
