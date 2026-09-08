import {activityForStep} from './route_step.js';
import {$,el,api,activityDetail,showDetail} from './knowledge_ui.js';
import {routeGraph,disposeGraphs} from './route_graph.js';
let snapshot=null,offset=0,page=null,busy=false,filters={alliances:[]};
const categoryLabels={AIRLINE:'航司',HOTEL:'酒店',CRUISE:'邮轮',OTHER:'其他项目',UNKNOWN:'未分类项目'};
function lock(value){busy=value;$('#query').disabled=value;$('#more').disabled=value;$('#search').disabled=value;document.querySelectorAll('.node-button').forEach(button=>button.disabled=value);}
async function open(ref,presentation){
  if(busy)return;showDetail($('#detail'));const pane=$('#detail-content');pane.replaceChildren(el('p','正在读取申请条件…'));
  try{
    const selected=snapshot.steps[ref];if(!selected)throw Error('这一步不属于当前浏览快照');
    const visibleRefs=new Set(snapshot.routes.slice(0,offset).flatMap(route=>route.step_refs));
    const alternatives=[...visibleRefs].map(key=>snapshot.steps[key]).filter(step=>step.to_tier_id===selected.to_tier_id);
    pane.replaceChildren();
    const cache=new Map();
    for(const [index,step] of alternatives.entries()){
      const url=`/v2/activities/${step.activity_ref}?version_ref=${step.version_ref}`;
      if(!cache.has(url))cache.set(url,await api(url));
      const activity=activityForStep(cache.get(url),step);
      const section=el('section');section.append(el('h3',`申请方式 ${index+1} · ${step.from||'公开申请'} → ${step.to}`));
      const brief=el('a','打开对应版本简报 ↗');brief.href=`/knowledge?activity_id=${step.activity_ref}&version_ref=${step.version_ref}&section=brief`;brief.target='_blank';section.append(brief);
      activityDetail(activity,section,[],true,step.constraint_checks||[]);pane.append(section);
    }
  }catch(error){pane.replaceChildren(el('p',error.message));}
}
function render(p,append=false){
  page=p;if(!append){disposeGraphs();$('#results').replaceChildren();}
  if(!p)return;const block=p.blocks.find(b=>b.type==='route_graph');
  if(block?.payload.routes.length){
    const categories=[...new Set(block.payload.routes.map(r=>block.payload.steps[r.step_refs.at(-1)].target_category||'UNKNOWN'))];
    for(const [categoryIndex,category] of categories.entries()){
      const group=el('details');group.open=categoryIndex===0;group.append(el('summary',categoryLabels[category]||category));
      const routes=block.payload.routes.filter(r=>(block.payload.steps[r.step_refs.at(-1)].target_category||'UNKNOWN')===category);
      for(const [targetIndex,target] of [...new Set(routes.map(r=>r.to))].entries()){
        const chosen=routes.filter(r=>r.to===target),entry=el('details');entry.open=targetIndex===0;
        entry.append(el('summary',`${target} · 方案 ${chosen.map(r=>r.presentation_index).join('、')}`),routeGraph({...block,payload:{...block.payload,routes:chosen}},p.id,open));group.append(entry);
      }$('#results').append(group);
    }
  }else $('#results').append(el('p',p.text));
  const coverage=p.basis?.find(b=>b.tool==='query_membership_routes')?.coverage;
  $('#results').append(el('p',`本页 ${coverage?.returned_count||0} 条，已找到 ${coverage?.observed_count||0} 条。${coverage?.search_complete===false?'资料或搜索覆盖不完整，不能据此认定没有其他路径。':''}`,'page-note'));
  if(coverage?.unresolved_holding_count)$('#results').append(el('p',`有 ${coverage.unresolved_holding_count} 项已保存会籍尚未关联规范等级，未参与计算；可以明确选择本次起点继续探索。`,'caveat'));
  if(coverage?.unresolved_alliance_program_count)$('#results').append(el('p','部分目标项目尚未核实联盟身份，本次联盟筛选覆盖不完整。','caveat'));
  $('#more').hidden=offset>=snapshot.routes.length;
}
$('#search').onclick=async()=>{
  const text=$('#program-search').value.trim();if(text.length<2){$('#catalog-notice').textContent='请至少输入两个字符。';return;}
  $('#search').disabled=true;
  try{const result=await api(`/v2/membership/catalog?text=${encodeURIComponent(text)}`);$('#source').replaceChildren(new Option('使用已确认会籍','saved'),new Option('只看公开申请机会','public'));
    for(const program of result.programs){const group=document.createElement('optgroup');group.label=program.name;for(const tier of program.tiers)group.append(new Option(`${program.name} · ${tier.name}`,tier.id));$('#source').append(group);}
    $('#catalog-notice').textContent=result.has_more?'仍有其他项目，请缩小查找范围后选择。':result.programs.length?'请选择准确等级；不会保存为已持有会籍。':'未找到对应目录，请换用完整项目名。';
  }catch(error){$('#catalog-notice').textContent=error.message;}finally{$('#search').disabled=false;}
};
$('#category').onchange=()=>{$('#alliance').disabled=$('#category').value!=='AIRLINE'||!filters.alliances.length;if($('#alliance').disabled)$('#alliance').value='';};
$('#free').onchange=()=>{$('#amount').disabled=$('#free').checked;};
$('#explore-form').onsubmit=async event=>{
  event.preventDefault();if(busy)return;lock(true);$('#notice').textContent='正在查询已发布的匹配关系…';
  const source=$('#source').value,query={starting_tier_ids:source==='saved'||source==='public'?[]:[source],use_saved_holdings:source==='saved',free_only:$('#free').checked};
  if($('#category').value)query.category=$('#category').value;if($('#alliance').value)query.alliance=$('#alliance').value;
  if(!query.free_only&&$('#amount').value!==''){query.max_amount=$('#amount').value;query.currency=$('#currency').value;}
  try{snapshot=await api('/v2/explore/query',query);offset=0;nextPage(false);try{sessionStorage.setItem('journeyplus-knowledge-explore',JSON.stringify(snapshot));}catch{}$('#notice').textContent='已按本次条件查询。点击节点查看同版本申请方式和简报。';}
  catch(error){$('#notice').textContent=error.message;}finally{lock(false);}
};
function nextPage(append=true){
  const selected=snapshot.routes.slice(offset,offset+12).map((route,index)=>({...route,presentation_index:offset+index+1}));offset+=selected.length;
  render({id:'knowledge-explore',text:'当前资料范围内没有找到路径。',blocks:[{type:'route_graph',graph_mode:'EXPLORE',payload:{routes:selected,steps:snapshot.steps}}],basis:[{tool:'query_membership_routes',coverage:{...snapshot.coverage,returned_count:selected.length,observed_count:snapshot.routes.length}}]},append);
}
$('#more').onclick=()=>{if(!busy&&snapshot)nextPage();};
$('#close').onclick=()=>$('#detail').close();
async function start(){
  lock(true);
  try{
    filters=await api('/v2/membership/filters');for(const name of filters.alliances)$('#alliance').append(new Option(name,name));$('#alliance-notice').textContent=filters.alliances.length?'选择航司后可按已核实联盟筛选。':'当前目录尚无已核实联盟信息，暂不据此筛选。';
    const saved=sessionStorage.getItem('journeyplus-knowledge-explore');if(saved){snapshot=JSON.parse(saved);offset=0;nextPage(false);$('#notice').textContent='已恢复上次浏览快照；上方条件用于新查询。';}
  }catch(error){$('#notice').textContent=error.message;}finally{lock(false);}
}
start();
