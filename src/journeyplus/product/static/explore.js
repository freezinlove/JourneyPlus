import {$,el,api,activityDetail,showDetail} from './knowledge_ui.js';
import {routeGraph,disposeGraphs} from './route_graph.js';
let workspace=null,page=null,busy=false,filters={alliances:[]};
const categoryLabels={AIRLINE:'航司',HOTEL:'酒店',CRUISE:'邮轮',OTHER:'其他项目',UNKNOWN:'未分类项目'};
function lock(value){busy=value;$('#query').disabled=value;$('#more').disabled=value;$('#search').disabled=value;document.querySelectorAll('.node-button').forEach(button=>button.disabled=value);}
async function open(ref,presentation){
  if(busy)return;showDetail($('#detail'));const pane=$('#detail-content');pane.replaceChildren(el('p','正在读取申请条件…'));
  try{
    const base=`/v2/agent/workspaces/${workspace.id}`;
    const data=await api(`${base}/details`,{ref,presentation_id:presentation});workspace=await api(`${base}/focus`,{ref,presentation_id:presentation,expected_revision:workspace.revision});pane.replaceChildren();
    if(data.type==='node'){
      pane.append(el('h3',data.node.name));
      for(const [index,item] of data.alternatives.entries()){const box=el('section',undefined,'detail-option');box.append(el('h4',`申请方式 ${index+1} · ${item.step.from||'公开申请'} → ${item.step.to}`));activityDetail(item.activity,box,[],true,item.step.constraint_checks||[]);pane.append(box);}
    }else if(data.type==='step')activityDetail(data.activity,pane,[],true,data.step.constraint_checks||[]);
    else if(data.type==='activity')activityDetail(data.activity,pane);
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
  $('#more').hidden=!p.browse_cursor;
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
  event.preventDefault();if(busy||!workspace)return;lock(true);$('#notice').textContent='正在查询已发布的匹配关系…';
  const source=$('#source').value,query={starting_tier_ids:source==='saved'||source==='public'?[]:[source],use_saved_holdings:source==='saved',free_only:$('#free').checked};
  if($('#category').value)query.category=$('#category').value;if($('#alliance').value)query.alliance=$('#alliance').value;
  if(!query.free_only&&$('#amount').value!==''){query.max_amount=$('#amount').value;query.currency=$('#currency').value;}
  try{workspace=await api(`/v2/agent/workspaces/${workspace.id}/routes/explore`,{query,expected_revision:workspace.revision});render(workspace.explorations.at(-1));$('#notice').textContent='已按本次条件查询。点击节点查看申请方式，也可以回到工作区继续讨论。';}
  catch(error){$('#notice').textContent=error.message;}finally{lock(false);}
};
$('#more').onclick=async()=>{
  if(busy||!page?.browse_cursor)return;lock(true);
  try{workspace=await api(`/v2/agent/workspaces/${workspace.id}/routes/browse`,{presentation_id:page.id,anchor_ref:page.blocks[0].subject_refs[0],cursor:page.browse_cursor,expected_revision:workspace.revision});render(workspace.explorations.at(-1),true);}
  catch(error){$('#notice').textContent=error.message;}finally{lock(false);}
};
$('#close').onclick=()=>$('#detail').close();
async function start(){
  lock(true);
  try{const saved=sessionStorage.getItem('journeyplus-workspace-v2');if(saved){try{workspace=await api(`/v2/agent/workspaces/${saved}`);}catch(error){if(!/WORKSPACE_EXPIRED|工作区不存在或是旧版交互/.test(error.message))throw error;$('#notice').textContent='原工作区已失效，已开始新的临时浏览。';workspace=await api('/v2/agent/workspaces',{});}}else workspace=await api('/v2/agent/workspaces',{});sessionStorage.setItem('journeyplus-workspace-v2',workspace.id);
    filters=await api('/v2/membership/filters');for(const name of filters.alliances)$('#alliance').append(new Option(name,name));$('#alliance-notice').textContent=filters.alliances.length?'选择航司后可按已核实联盟筛选。':'当前目录尚无已核实联盟信息，暂不据此筛选。';
    if(workspace.explorations?.length){render(workspace.explorations.at(-1));$('#notice').textContent='已恢复上次浏览的页面；上方条件用于发起新查询。';}
  }catch(error){$('#notice').textContent=error.message;}finally{lock(false);}
}
start();
