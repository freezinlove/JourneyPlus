import {renderBrief} from './brief_view.js?v=20260914-brief-view';
import {$,el,api,activityCard,activityDetail} from './knowledge_ui.js';
import {createKnowledgeNavigation} from './knowledge_navigation.js?v=20260914-navigation-2';
let offset=0,loading=false;
const dialog=$('#detail'),pane=$('#detail-content');
const navigation=createKnowledgeNavigation({
  location,history,
  read:activity=>api(`/v2/activities/${encodeURIComponent(activity.ref)}${activity.briefOnly?"/brief":""}?version_ref=${encodeURIComponent(activity.version_ref)}`),
  show:briefOnly=>{
    dialog.querySelector('h2').textContent=briefOnly?'活动简报':'活动详情';
    pane.replaceChildren(el('p','正在读取活动…'));
    dialog.scrollTop=0;
    if(!dialog.open)dialog.showModal();
  },
  clear:()=>{if(dialog.open)dialog.close();pane.replaceChildren();},
  render:(detail,briefOnly)=>{pane.replaceChildren();if(briefOnly)pane.innerHTML=renderBrief(detail);else activityDetail(detail,pane);},
  error:error=>pane.replaceChildren(el('p',error.message)),
});
async function load(){
  if(loading)return;loading=true;$('#more').disabled=true;$('#notice').textContent='正在读取当前活动…';
  try{
    const result=await api(`/v2/activities?view=cards&limit=8&offset=${offset}`);
    for(const activity of result.activities){
      const card=activityCard(activity,()=>navigation.open(activity));
      card.lastElementChild.textContent='查看简报 →';
      $('#activities').append(card);
    }
    offset+=result.activities.length;$('#more').hidden=!result.has_more;
    $('#notice').textContent=offset?'只展示已发布资料；未完成核实的活动可能尚未列入。':'暂时没有已发布活动。';
  }catch(error){$('#notice').textContent=error.message;$('#more').hidden=false;$('#more').textContent='重试读取';}
  finally{loading=false;$('#more').disabled=false;}
}
async function start(){
  const params=new URLSearchParams(location.search);
  const legacy=params.get('legacy_opportunity');
  if(legacy&&!params.has('activity_id')){
    try{
      const resolved=await api(`/v2/legacy/opportunities/${encodeURIComponent(legacy)}`);
      if(resolved.status==='RESOLVED')await navigation.open({ref:resolved.activity_ref,version_ref:resolved.version_ref});
      else $('#notice').textContent=resolved.message;
    }catch(error){$('#notice').textContent=error.message;}
  }else await navigation.sync();
  void load();
}
addEventListener('popstate',()=>navigation.sync());
$('#more').onclick=load;
$('#close').onclick=()=>navigation.close();
dialog.addEventListener('cancel',event=>{event.preventDefault();void navigation.close();});
start();
