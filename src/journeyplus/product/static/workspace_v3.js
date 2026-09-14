import {mappingTable} from './brief_view.js?v=20260914-mapping-table';
import {activityForStep} from './route_step.js?v=20260913-simple-matching';
import {renderText} from './agent_text.js';
import {activityDetail,readable,money} from './knowledge_ui.js?v=20260914-merged-delivery';
import {routeGraph,disposeGraphs} from './route_graph.js?v=20260914-merged-delivery';
const $=s=>document.querySelector(s);
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
let workspace=null,run=null,source=null,seq=0,busy=false,resourceFailure=null;
const messages=new Map(),presentations=new Set();
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Object.assign(new Error(({AGENT_STORAGE_SCHEMA_MISMATCH:'会话存储尚未就绪，请完成 Agent 数据库升级后点击“新对话”重试。',DATABASE_UNAVAILABLE:'数据库暂不可用，请恢复服务后点击“新对话”重试。'})[data.code]||'请求未成功，请稍后重试。'),{status:response.status});return data;}
const base=()=>`/v3/agent/workspaces/${workspace.id}`;
function lock(value){busy=value;$('#send').disabled=value||!workspace;$('#new').disabled=value;$('#import').disabled=value;$('#cancel').hidden=!value;}
const textWithLinks=renderText;
function message(id,role='assistant',text=''){if(messages.has(id))return messages.get(id);const article=el('article',undefined,`message ${role}`);article.dataset.messageId=id;article.append(el('span',role==='user'?'你':'JOURNEYPLUS','speaker'));const body=el('div',undefined,'body');textWithLinks(body,text);article.append(body);$('#messages').append(article);const item={article,body,text};messages.set(id,item);$('#intro').hidden=true;return item;}
async function artifact(ref){return api(`${base()}/artifacts/${ref.split('#')[0].replace('artifact:','')}`);}

async function detail(ref,presentation){try{let data;if(ref.startsWith('activity:')){const [id,version]=ref.replace('activity:','').split('@');data={payload:await api(`/v2/activities/${id}?version_ref=${version}`)};}else data=await artifact(ref);let object=data.payload;if(data.kind==='PAGE'&&presentation){const shown=await artifact(presentation);const selected=shown.payload.blocks.flatMap(block=>block.payload.objects).find(item=>item.ref===ref);if(selected)object=selected.data;}if(ref.includes('#')){const [kind,key]=ref.split('#')[1].split(':');object=object[{route:'routes',step:'steps',report:'reports'}[kind]][key];}const pane=$('#detail-content');pane.replaceChildren(el('h2',object.name||object.title||object.to||'资料详情'));if(object.brief_url){const a=el('a','打开对应版本简报 ↗');a.href=object.brief_url;a.target='_blank';pane.append(a);}for(const link of object.brief_links||[]){const a=el('a',`${link.title||'活动'}简报 ↗`);a.href=link.url;a.target='_blank';pane.append(a);}if(object.options&&object.version_ref){activityDetail(object,pane);}else if(object.activity_ref&&object.version_ref){pane.append(el('p',`实际匹配：${object.from||'公开申请'} → ${object.to}`));const activity=await api(`/v2/activities/${object.activity_ref}?version_ref=${object.version_ref}`);activityDetail(activityForStep(activity,object),pane,[],true,object.constraint_checks||[]);}else if(object.step_refs){for(const sid of object.step_refs){const step=data.payload.steps[sid];if(!step)continue;const section=el('section');section.append(el('h3',`${step.from||'公开申请'} → ${step.to}`));const activity=await api(`/v2/activities/${step.activity_ref}?version_ref=${step.version_ref}`);activityDetail(activityForStep(activity,step),section,[],true,step.constraint_checks||[]);pane.append(section);}}else{reportMeta(object,pane);pane.append(el('p',object.text||object.evidence_excerpt||object.content||'没有可展示的正文'));if(object.original_from)pane.append(el('p',`${object.original_from} → ${object.original_to}`));}$('#detail').showModal();if(!busy&&presentation){const result=await api(`${base()}/focus`,{presentation_ref:presentation,object_ref:ref,expected_revision:workspace.revision});workspace.revision=result.revision;workspace.focus=result.focus;}}catch(error){$('#notice').textContent=error.message;}}

async function graphDetail(selectedRef,presentation,steps){
  const selected=steps[selectedRef];if(!selected){$('#notice').textContent='这一步不属于实际展示';return;}
  const alternatives=Object.values(steps).filter(step=>step.to_tier_id===selected.to_tier_id);
  if(alternatives.length===1)return detail(selectedRef,presentation);
  const pane=$('#detail-content');pane.replaceChildren(el('h2','选择申请方式'));
  for(const step of alternatives){
    const button=el('button',`${step.from||'公开申请'} → ${step.to}`);
    button.onclick=()=>detail(step.ref,presentation);pane.append(button);
  }
  $('#detail').showModal();
}

function reportMeta(report,parent){
  const labels=[];
  if(report.reported_label)labels.push(`网站标签：${({MATCH:'匹配',CHALLENGE:'挑战',DENY:'拒绝',OTHER:'其他'})[report.reported_label]||report.reported_label}`);
  if(report.submitted_at){const date=typeof report.submitted_at==='string'?report.submitted_at:report.submitted_at.date;if(date)labels.push(`报告提交：${date}`);}
  if(labels.length)parent.append(el('small',labels.join(' · '),'muted'));
  if(report.body_complete===false)parent.append(el('p','原始报告未完整获取，以下为已取得的内容。','muted'));
  if(report.url?.startsWith('https://statusmatcher.com/report/')){const link=el('a','查看原始报告 ↗');link.href=report.url;link.target='_blank';link.rel='noopener noreferrer';const line=el('p');line.append(link);parent.append(line);}
}
function reportPreview(report){const text=report.text||report.evidence_excerpt||'';return text.length>400?text.slice(0,400)+'…':text;}
function relatedReports(block,container){
  for(const attachment of block.payload.research||[]){
    const reports=attachment.data.reports?Object.values(attachment.data.reports):[attachment.data];
    const box=el('aside',undefined,'card');box.append(el('h4','公开申请经验'),el('small','用户自报资料，不能视为正式可申请路径或成功概率。','muted'));
    for(const report of reports){box.append(el('p',`${report.original_from||'来源未核实'} → ${report.original_to||'目标未核实'}`),el('p',reportPreview(report)));reportMeta(report,box);const open=el('button','查看完整报告');open.onclick=()=>detail(attachment.ref.includes('#report:')?attachment.ref:attachment.ref+'#report:'+report.report_ref);box.append(open);const binding=attachment.bindings?.find(item=>item.report_ref===report.report_ref);if(binding?.compatible_steps?.some(item=>item.identity_level==='UNKNOWN'))box.append(el('small','会籍或时间信息不完整，可比性尚未核实','muted'));}
    container.append(box);
  }
}
async function showPresentation(ref,target){
  if(presentations.has(ref))return;
  const data=await artifact(ref);if(data.kind!=='PRESENTATION')return;
  presentations.add(ref);
  for(const [index,block] of data.payload.blocks.entries()){
    const objects=block.payload.objects;
    block.next_cursor=objects.length>8?`${ref}|${index}|8`:null;
    block.payload.objects=objects.slice(0,8);
  }
  const container=el('div');(target||message(ref).article).append(container);
  await renderPresentation(ref,data,container);
}
async function renderPresentation(ref,data,container){container.replaceChildren();try{if(data.payload.answer){const reply=el('div',undefined,'body');textWithLinks(reply,data.payload.answer);container.append(reply);}for(const block of data.payload.blocks){const box=el('section',undefined,'cards');if(block.title)box.append(el('h3',block.title));if(block.reason)box.append(el('p',block.reason));if(block.type==='mapping_table'){for(const item of block.payload.objects){const body=el('section');body.append(el('h3',item.data.name));const table=el('div');table.innerHTML=mappingTable({facts:{status_mappings:(item.data.options||[]).flatMap(o=>o.mappings||[])}});body.append(table);box.append(body);}container.append(box);continue;}if(block.type==='comparison'){const table=el('table');const head=el('tr');head.append(el('th','方案'));const labels={cost:'费用',steps:'步骤',challenge:'挑战',eligibility:'资格',window:'申请窗口',validity:'有效期',conditions:'适用条件'};for(const col of block.columns)head.append(el('th',labels[col]));table.append(head);for(const item of block.payload.objects){const row=el('tr');const name=el('td');const button=el('button',`${item.data.source_group?.label||item.data.from||'公开申请'} → ${item.data.to}`);button.onclick=()=>detail(item.ref,ref);name.append(button);const role=block.roles?.find(role=>role.ref===item.ref)?.role;if(role)name.append(el('div',role==='primary'?'主选':'备选','muted'));row.append(name);for(const col of block.columns){const value=col==='cost'?money(item.data.cost):col==='steps'?String(item.data.step_count):item.data.comparison_values?.[col]?.map(cell=>`${cell.label}：${col==='conditions'?(cell.value||[]).map(check=>check.reason).join('；')||'暂无已记录条件':readable(cell.value)}`).join('\n')||readable(item.data[{window:'application_window',validity:'status_validity'}[col]||col]);row.append(el('td',value));}table.append(row);}const scroll=el('div',undefined,'table-scroll');scroll.append(table);box.append(scroll);relatedReports(block,box);container.append(box);continue;}if(block.type==='route_graph'){const routes=block.payload.objects.map((item,i)=>({...item.data,presentation_index:i+1,presentation_role:block.roles?.find(r=>r.ref===item.ref)?.role?.toUpperCase()}));const steps=Object.assign({},...routes.map(r=>r.steps));box.append(routeGraph({payload:{routes,steps},model_owned_roles:true,graph_mode:block.roles?.some(r=>r.role==='primary')?'RECOMMEND':'EXPLORE'},ref,(node)=>graphDetail(node,ref,steps),false));const briefLinks=new Map();for(const route of routes)for(const link of route.brief_links||[])if(!briefLinks.has(link.url))briefLinks.set(link.url,link);for(const link of briefLinks.values()){const a=el('a',`${link.title||'活动'} · 对应版本简报 ↗`);a.href=link.url;a.target='_blank';box.append(a);}relatedReports(block,box);container.append(box);continue;}for(const item of block.payload.objects){const object=item.data;const card=el('section',undefined,'card');const role=block.roles?.find(role=>role.ref===item.ref)?.role;if(role)card.append(el('small',role==='primary'?'首选':'备选','muted'));card.append(el('h3',object.name||object.title||object.to||(object.original_to?`${object.original_from||'未注明来源'} → ${object.original_to}`:block.type)));if(object.step_count){card.append(el('div',`${object.from||'公开申请'} → ${object.to}`,'route'),el('p',`${object.step_count} 步 · ${money(object.cost)}`));if(object.eligibility!=='PASS')card.append(el('p','申请资格仍有待核实的条件','muted'));}else if(block.type==='experience'||block.type==='evidence'){reportMeta(object,card);card.append(el('p',`${object.original_from||'来源未核实'} → ${object.original_to||'目标未核实'}`),el('p',object.excerpt||reportPreview(object)),el('small','外部资料或用户自报，不能视为正式匹配路径','muted'));}else if(object.facts?.summary)card.append(el('p',readable(object.facts.summary)));else if(object.card?.summary)card.append(el('p',object.card.summary));const open=el('button','查看详情');open.onclick=()=>detail(item.ref,ref);card.append(open);for(const link of object.brief_links||[]){const a=el('a',`${link.title||'活动'}简报 ↗`);a.href=link.url;a.target='_blank';card.append(a);}if(object.brief_url){const a=el('a','对应版本简报 ↗');a.href=object.brief_url;a.target='_blank';card.append(a);}box.append(card);}relatedReports(block,box);container.append(box);}for(const block of data.payload.blocks){
  if(!block.next_cursor)continue;
  const more=el('button',`${block.title||'展示结果'} · 继续展开`);
  more.onclick=async()=>{more.disabled=true;try{
    const page=await api(`${base()}/presentations/${ref.replace('artifact:','')}/browse`,{cursor:block.next_cursor,expected_revision:workspace.revision});
    block.payload.objects.push(...page.objects);block.next_cursor=page.next_cursor;
    await renderPresentation(ref,data,container);
  }catch(error){$('#notice').textContent=error.message;more.disabled=false;}};
  container.append(more);
}
const next=el('div',undefined,'suggestions');for(const step of data.payload.next_steps||[]){const button=el('button',step.label);button.onclick=()=>submit(step.message,step.subject_refs);next.append(button);}container.append(next);await api(`${base()}/presentations/${ref.replace('artifact:','')}/feedback`,{event_id:`rendered:${ref}`,status:'RENDERED'});}catch(error){await api(`${base()}/presentations/${ref.replace('artifact:','')}/feedback`,{event_id:`failed:${ref}`,status:'FAILED',error_code:'RENDER_FAILED'});throw error;}}
async function showImport(ref,target){
  const record=await artifact(ref);if(record.kind!=='IMPORT')return;
  const container=el('section',undefined,'cards');container.append(el('small','历史展示 · 导入资料，不表示新的执行结果','muted'));
  for(const block of record.payload.blocks||[]){
    if(block.type==='route_graph'){
      container.append(routeGraph({...block,payload:{...block.payload,nodes:{}}},ref,(sid)=>detail(ref+'#step:'+sid),false));
    }else if(block.type==='route_comparison'){
      const table=el('table');for(const row of block.payload.comparison_rows||[]){const tr=el('tr');tr.append(el('th',row.label));for(const value of row.cells)tr.append(el('td',row.key==='cost'?money(value):readable(value)));table.append(tr);}container.append(table);
    }else if(block.type==='activity_card'){
      for(const activity of block.payload.activities||[]){const card=el('section',undefined,'card');card.append(el('h3',activity.name||activity.title||'历史活动'));const button=el('button','查看当时版本');button.onclick=()=>detail(`activity:${activity.ref}@${activity.version_ref}`);card.append(button);container.append(card);}
    }else{
      const section=el('details');section.append(el('summary','历史资料依据'));for(const material of block.payload?.materials||[]){for(const fact of material.data?.facts||[])section.append(el('p',`${fact.label||''} ${readable(fact.value)}`));}container.append(section);
    }
  }
  target.append(container);
}
function operationDetails(parent,op){
  if(!op.original_statements?.length)return;
  const details=el('details');details.append(el('summary','记录依据 · 用户原始陈述'));
  for(const statement of op.original_statements)details.append(el('p',statement.text));
  parent.append(details);
}
async function historicalMessage(m){
  if(m.role==='tool')return null;
  const text=(m.content||[]).filter(p=>p.type==='text').map(p=>p.text).join('\n');
  const imports=(m.content||[]).filter(p=>p.type==='artifact');
  const attached=m.attachments||{};
  if(!text&&!imports.length&&!attached.presentation_refs?.length&&!attached.operations?.length)return null;
  const node=message(m.id,m.role,text);
  for(const part of imports)await showImport(part.ref,node.article);
  for(const ref of attached.presentation_refs||[])await showPresentation(ref,node.article);
  for(const op of attached.operations||[]){node.article.append(el('p',op.summary,'operation-receipt'));operationDetails(node.article,op);}
  if(m.metadata?.interrupted)node.article.append(el('small','此段回答中断，已保留','muted'));
  return node.article;
}
async function hydrate(){
  disposeGraphs();workspace=await api(base());$('#messages').replaceChildren();messages.clear();presentations.clear();
  for(const m of workspace.messages)await historicalMessage(m);
  if(workspace.next_cursor){const older=el('button','加载更早消息');older.onclick=()=>loadEarlier(older);$('#messages').prepend(older);}
}
async function loadEarlier(button){try{
  const page=await api(`${base()}?cursor=${workspace.next_cursor}`);const fragment=document.createDocumentFragment();
  for(const m of page.messages){const article=await historicalMessage(m);if(article)fragment.append(article);}
  button.after(fragment);workspace.next_cursor=page.next_cursor;if(!page.next_cursor)button.remove();
}catch(error){$('#notice').textContent=error.message;}}
async function handle(event){seq=event.seq;sessionStorage.setItem('journeyplus-v3-run',JSON.stringify({workspace:workspace.id,run,seq}));const p=event.payload;if(event.type==='text_delta'){const m=message(p.message_id);m.text+=p.text;textWithLinks(m.body,m.text);}if(event.type==='tool.started')$('#progress').textContent=p.label;if(event.type==='operation.applied'){const receipt=message(p.operation_ref,'assistant',p.summary);operationDetails(receipt.article,p);}if(event.type==='presentation.created'){await showPresentation(p.presentation_ref);}if(event.type==='resource.notice'){if(['MODEL_UNAVAILABLE','KNOWLEDGE_NOT_READY'].includes(p.code))resourceFailure=p.message;$('#notice').textContent=p.message||'正在根据剩余资源整理回答';}if(['completed','partial','canceled','failed'].includes(event.type)){source.close();sessionStorage.removeItem('journeyplus-v3-run');lock(false);$('#progress').textContent='';$('#notice').textContent=resourceFailure||{completed:'',partial:'本轮未完整完成，已取得的结果保留。',canceled:'已停止。已经完成的操作保留。',failed:'本轮中断，输入及已完成结果保留。'}[event.type];await hydrate();}}
function subscribe(){let queue=Promise.resolve();source=new EventSource(`${base()}/runs/${run}/events?after=${seq}`);source.onmessage=e=>{const data=JSON.parse(e.data);if(data.seq<=seq)return;queue=queue.then(()=>data.seq>seq?handle(data):undefined).catch(error=>{$('#notice').textContent=error.message;});};source.onerror=()=>{$('#progress').textContent='连接恢复中…';};}
async function submit(text,subject_refs=[]){
  if(busy)return;
  if(!workspace){$('#notice').textContent='会话尚未创建，请点击“新对话”重试。';return;}
  resourceFailure=null;
  $('#notice').textContent='';
  const saved=JSON.parse(sessionStorage.getItem('journeyplus-v3-request')||'null');
  const body=saved?.workspace===workspace.id&&saved.body.text===text&&JSON.stringify(saved.body.subject_refs)===JSON.stringify(subject_refs)?saved.body:{text,subject_refs,client_message_id:crypto.randomUUID(),expected_revision:workspace.revision};
  sessionStorage.setItem('journeyplus-v3-request',JSON.stringify({workspace:workspace.id,body}));lock(true);
  try{
    const result=await api(`${base()}/runs`,body);sessionStorage.removeItem('journeyplus-v3-request');$('#input').value='';run=result.run_id;seq=0;
    if(['COMPLETED','PARTIAL','CANCELED','FAILED'].includes(result.status)){await hydrate();lock(false);return;}
    message(body.client_message_id,'user',text);subscribe();
  }catch(error){
    $('#notice').textContent=error.message;$('#input').value=text;
    if(error.status===409){
      sessionStorage.removeItem('journeyplus-v3-request');await hydrate();
      const active=workspace.runs.find(r=>!['COMPLETED','PARTIAL','CANCELED','FAILED'].includes(r.status));
      if(active){run=active.run_id;seq=active.last_seq;subscribe();return;}
    }
    lock(false);
  }
}
$('#composer').onsubmit=e=>{e.preventDefault();const text=$('#input').value.trim();if(text)submit(text);};$('#cancel').onclick=async()=>{try{
  const result=await api(`${base()}/runs/${run}/cancel`,{idempotency_key:`cancel:${run}`});
  if(['COMPLETED','PARTIAL','CANCELED','FAILED'].includes(result.status)){
    source?.close();lock(false);$('#progress').textContent='';
    $('#notice').textContent=result.status==='COMPLETED'?'本轮已完成。':result.status==='CANCELED'?'已停止，已完成操作保留。':'本轮已结束，已取得的结果保留。';
    await hydrate();
  }else if(busy)$('#progress').textContent='正在停止…';
}catch(error){$('#notice').textContent=error.message;}};$('#close').onclick=()=>$('#detail').close();$('#new').onclick=()=>start(true);
async function start(fresh=false){lock(true);if(fresh){workspace=null;resourceFailure=null;$('#notice').textContent='';}try{const saved=fresh?null:sessionStorage.getItem('journeyplus-v3-workspace');workspace=saved?{id:saved}:await api('/v3/agent/workspaces',{});sessionStorage.setItem('journeyplus-v3-workspace',workspace.id);await hydrate();const pending=fresh?null:JSON.parse(sessionStorage.getItem('journeyplus-v3-run')||'null');const active=workspace.runs.find(r=>!['COMPLETED','PARTIAL','CANCELED','FAILED'].includes(r.status));if(active){run=active.run_id;seq=active.last_seq;subscribe();}else{sessionStorage.removeItem('journeyplus-v3-run');lock(false);}}catch(error){workspace=null;$('#notice').textContent=error.message;lock(false);}}
const legacyWorkspace=sessionStorage.getItem('journeyplus-workspace-v2');
$('#import').hidden=!legacyWorkspace;
$('#import').onclick=async()=>{if(busy)return;lock(true);try{workspace=await api('/v3/agent/workspaces',{import_workspace_id:legacyWorkspace});sessionStorage.setItem('journeyplus-v3-workspace',workspace.id);sessionStorage.removeItem('journeyplus-v3-run');await hydrate();$('#notice').textContent='旧对话已导入，历史待确认操作不会自动执行。';}catch(error){$('#notice').textContent=error.message;}finally{lock(false);}};
start().then(async()=>{try{const status=await api('/v3/agent/status');if(status.knowledge?.status==='UNAVAILABLE')$('#notice').textContent=status.knowledge.message;}catch(error){$('#notice').textContent='暂时无法确认服务就绪状态：'+error.message;}});
