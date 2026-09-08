import {$,el,api,activityCard,activityDetail,showDetail} from './knowledge_ui.js';
let offset=0,loading=false;
async function openActivity(activity){
  $('#detail-content').replaceChildren(el('p','正在读取活动…'));showDetail($('#detail'));
  try{const detail=await api(`/v2/activities/${activity.ref}?version_ref=${activity.version_ref}`);const pane=$('#detail-content');pane.replaceChildren();activityDetail(detail,pane);}
  catch(error){$('#detail-content').replaceChildren(el('p',error.message));}
}
async function load(){
  if(loading)return;loading=true;$('#more').disabled=true;$('#notice').textContent='正在读取当前活动…';
  try{
    const result=await api(`/v2/activities?view=cards&limit=8&offset=${offset}`);
    for(const activity of result.activities)$('#activities').append(activityCard(activity,()=>openActivity(activity)));
    offset+=result.activities.length;$('#more').hidden=!result.has_more;
    $('#notice').textContent=offset?'只展示已发布资料；未完成核实的活动可能尚未列入。':'暂时没有已发布活动。';
  }catch(error){$('#notice').textContent=error.message;$('#more').hidden=false;$('#more').textContent='重试读取';}
  finally{loading=false;$('#more').disabled=false;}
}
async function start(){
  await load();
  const params=new URLSearchParams(location.search);
  const activityId=params.get('activity_id'),version=params.get('version_ref');
  if(activityId&&version){
    await openActivity({ref:activityId,version_ref:version});
    if(params.get('section')==='brief'){
      const sections=[...document.querySelectorAll('#detail-content details')];
      const brief=sections.find(d=>d.querySelector('summary')?.textContent.trim()==='活动简报');
      if(brief){brief.open=true;brief.scrollIntoView({block:'nearest'});}else{$('#detail-content').prepend(el('p','此版本尚无已生成简报，以下为同版本资料详情。'));}
    }
    return;
  }
  const legacy=params.get('legacy_opportunity');
  if(!legacy)return;
  try{
    const resolved=await api(`/v2/legacy/opportunities/${encodeURIComponent(legacy)}`);
    $('#notice').textContent=resolved.message;
    if(resolved.status==='RESOLVED')await openActivity({ref:resolved.activity_ref,version_ref:resolved.version_ref});
  }catch(error){$('#notice').textContent=error.message;}
}
$('#more').onclick=load;$('#close').onclick=()=>$('#detail').close();start();
