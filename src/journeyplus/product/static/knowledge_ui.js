'use strict';
const $ = (q) => document.querySelector(q);
const labels = {EXPIRED:'已结束',ARCHIVED:'已归档',UPCOMING:'尚未开始',ACTIVE:'进行中',FRESH:'近期资料',STALE:'资料已过期',MATCH:'符合查询条件',NEARBY:'接近要求',UNKNOWN:'有待核实',NONE:'无需挑战',REQUIRED:'需要挑战',PARTIAL:'部分费用已知',KNOWN:'已核实',AVAILABLE:'可申请',UNAVAILABLE:'不可申请',INCOMPLETE:'资料待补全',DISABLED:'调查未启用',NOT_REQUESTED:'未请求经验调查'};
const el = (tag, text, cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
async function api(path, body, method) {const r=await fetch(path,{method:method||(body?'POST':'GET'),headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'请求未完成，请检查输入或刷新后重试');return data;}
function money(cost){if(typeof cost?.paid==='boolean')return cost.paid?'付费':'免费';if(cost?.is_proven_free)return '免费';const totals=cost?.totals||[];const parts=totals.filter(x=>!totals.some(v=>Number(v.amount)>0)||Number(x.amount)>0).map(x=>`${x.role==='CHALLENGE_SPEND'?'挑战支出':'申请费用'} ${x.currency||''} ${Number(x.amount).toLocaleString('zh-CN')}`);return parts.join('；')||'费用未知';}
function readable(value){if(value==null)return '未知';if(typeof value!=='object')return labels[value]||String(value);if(value.known_state)return value.known_state==='KNOWN'?readable(value.value):labels[value.known_state]||'待核实';if(Array.isArray(value))return value.map(readable).join('；')||'暂无';if(value.items)return value.items.map(x=>x.raw_text||x.reason||'有资格条件，需核对来源').join('；')||'暂无已记录条件';if(value.kind==='NONE')return '无需挑战';if(value.kind==='DURATION')return `${({COMPLETION:'完成要求后',APPROVAL:'批准后',APPLICATION:'申请后'})[value.anchor]||'起算时间待核实，持续'} ${value.months!=null?value.months+' 个月':value.days+' 天'}`;if(value.kind==='FIXED_END')return `有效至 ${readable(value.end)}`;if(value.precision==='DATE')return value.date;if(value.precision==='MONTH')return value.month;if(value.precision==='INSTANT')return value.instant;if(value.precision==='RELATIVE')return `相对约定起点 ${value.offset_days} 天，具体起点请核对原文`;if(value.raw_text)return value.raw_text;return Object.entries(value).filter(([k])=>!k.endsWith('_id')&&!k.endsWith('_ids')&&!['schema_version','evidence_ids'].includes(k)).map(([k,v])=>`${({activity:'活动',option:'申请方式',kind:'类型',start:'开始',end:'结束',date:'日期',duration:'期限',unit:'单位',amount:'金额',currency:'币种',metrics:'要求',precision:'精度'})[k]||k}：${readable(v)}`).join('；');}
const detailNavigation=new WeakMap();
function showDetail(dialog){
  if(dialog.open)return;
  if(!detailNavigation.has(dialog)){
    const state={token:null};detailNavigation.set(dialog,state);
    addEventListener('popstate',()=>{if(dialog.open&&history.state?.journeyplusDetail!==state.token)dialog.close();});
    dialog.addEventListener('close',()=>{if(history.state?.journeyplusDetail===state.token)history.back();});
  }
  const state=detailNavigation.get(dialog);state.token=crypto.randomUUID();
  history.pushState({...history.state,journeyplusDetail:state.token},'');dialog.showModal();
}
function fact(parent,name,value){const dl=el('dl',undefined,'fact');dl.append(el('dt',name),el('dd',readable(value)));parent.append(dl);}
function activityDetail(a,parent,observations=[],includeHistory=true,checks=[]){if(a.data_model==='aiworkflow')return workflowActivityDetail(a,parent,includeHistory,checks);parent.append(el('h3',a.name||'活动资料'));const priceGaps=(a.validation_notes||[]).filter(n=>n.code==='PRICE_EVIDENCE_WITHHELD').length;const mappingGaps=(a.validation_notes||[]).filter(n=>n.code==='MAPPING_TABLE_INCOMPLETE').reduce((sum,n)=>sum+n.mapping_count,0);if(priceGaps)parent.append(el('p',`有 ${priceGaps} 项收费尚未通过来源或适用关系核对，已标记未知，不计入确定总价。可在费用依据中查看原文。`,'caveat'));if(mappingGaps)parent.append(el('p',`来源表中还有 ${mappingGaps} 项会籍映射未完成逐项验证，当前路径不代表完整覆盖。`,'caveat'));if(a.is_current===false)parent.append(el('p','这是回答当时的历史版本，当前资料已有更新。','caveat'));fact(parent,'资料状态',a.freshness||a.status);if(a.published_at)fact(parent,'发布时间',new Date(a.published_at).toLocaleString('zh-CN'));if(a.facts?.summary)fact(parent,'概述',a.facts.summary);for(const check of checks)fact(parent,check.result==='PASS'?'已核对条件':'待核对条件',check.reason);if(a.detail_scope!=='SELECTED_ROUTE_STEP'&&a.facts?.conditions?.items?.length)fact(parent,'活动资格条件',a.facts.conditions);for(const o of a.options||[]){const box=el('section',undefined,'detail-option');box.append(el('h4',o.label));fact(box,'申请状态',o.availability);if(a.detail_scope!=='SELECTED_ROUTE_STEP')fact(box,'资格条件',o.conditions);fact(box,'挑战要求',o.challenge);fact(box,'申请日期',o.application_window);fact(box,'有效期',o.status_validity);if(a.detail_scope!=='SELECTED_ROUTE_STEP')mappingDetails(o,box);if(!o.prices?.length)fact(box,'申请费用','尚未明确');for(const p of o.prices||[]){const target=o.mappings.find(m=>m.target_tier_id===p.target_tier_id);fact(box,target?`${target.to_tier} 费用`:'适用范围内费用',p.known_state==='KNOWN'?(Number(p.amount)===0?'免费':`${p.currency} ${Number(p.amount).toLocaleString('zh-CN')}`):(p.known_state==='CONFLICT'?'费用来源存在冲突':'费用未知'));if(p.raw_text){const evidence=el('details');evidence.append(el('summary','费用依据'),el('p',p.raw_text));box.append(evidence);}if(p.availability!=='AVAILABLE')fact(box,'费用适用性','尚未核实，不能作为确定总价');if(p.combination==='CONDITIONAL'||p.combination==='ALTERNATIVE')fact(box,'收费方式',p.combination==='CONDITIONAL'?'有条件费用':'互斥费用，需确认适用项');if(p.conditions?.items?.length)fact(box,'费用条件',p.conditions);}parent.append(box);}researchDetail(observations,parent);activitySources(a,parent,includeHistory);}

function workflowActivityDetail(a,parent,includeHistory,checks){
  const value=v=>v&&typeof v==='object'&&!Array.isArray(v)&&'value' in v?v.value:v;
  parent.append(el('h3',a.name||'活动资料'));
  if(a.is_current===false)parent.append(el('p','这是回答当时的历史版本，当前资料已有更新。','caveat'));
  fact(parent,'资料状态',a.card?.lifecycle_status);
  if(a.fee)fact(parent,'付费情况',a.fee.label);
  if(value(a.facts?.cost))fact(parent,'费用说明',value(a.facts.cost));
  for(const check of checks)fact(parent,check.result==='PASS'?'已核对条件':'待核对条件',check.reason);
  for(const [key,label] of [['eligibility','申请资格'],['challenge_requirements','挑战要求'],['application_start','申请开始'],['deadline','申请截止'],['status_validity','会籍有效期'],['caveats','注意事项']]){
    if(a.facts?.[key])fact(parent,label,value(a.facts[key]));
  }
  for(const option of a.options||[]){
    const section=el('section',undefined,'detail-option');section.append(el('h4',option.label));
    if(option.region)fact(section,'适用地区',option.region);
    if(option.eligibility)fact(section,'申请条件',option.eligibility);
    if(option.fee)fact(section,'付费情况',option.fee.label);
    if(option.cost)fact(section,'费用说明',option.cost);
    if(option.mappings?.length)mappingDetails(option,section);
    for(const price of option.prices||[]){
      const unavailable=price.availability==='UNAVAILABLE';
      const conflict=price.conflict||option.conflict||a.facts?.cost?.conflict;
      let amount=unavailable?'此等级不可申请':conflict?'费用存在冲突':price.amount!=null?(Number(price.amount)===0?'免费':`${price.currency||''} ${price.amount}`):'费用待确认';
      if(!unavailable&&!conflict&&price.availability==='CONDITIONAL')amount+='（条件费用，不作为确定必付金额）';
      if(!unavailable&&!conflict&&price.availability==='UNKNOWN')amount+='（适用性待确认）';
      fact(section,`${price.target_tier||''}申请费用`,amount);
      if(price.availability==='CONDITIONAL'&&price.raw_text)fact(section,'费用条件',price.raw_text);
    }
    const url=option.action_link||value(a.facts?.action_link);
    if(typeof url==='string'&&/^https?:\/\//.test(url)){const link=el('a','官方申请入口 ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';section.append(link);}
    parent.append(section);
  }
  for(const brief of a.briefs||[]){const box=el('details');box.append(el('summary','活动简报'));briefContent(brief,box);parent.append(box);}
  activitySources({...a,briefs:[],options:[]},parent,includeHistory);
}

function mappingDetails(option,parent){
  const mappings=option.mappings||[];
  if(!mappings.length)return;
  const section=el('details');section.append(el('summary',`来源会籍与对应等级 · ${mappings.length} 项`));
  const filter=el('input');filter.type='search';filter.placeholder='筛选项目或等级';
  filter.setAttribute('aria-label',`筛选来源会籍 · ${option.label}`);
  const list=el('div'),notice=el('p'),more=el('button','显示更多映射');more.type='button';
  section.append(filter,notice,list,more);parent.append(section);
  let visible=20;
  function render(){
    const term=filter.value.trim().toLocaleLowerCase();
    const selected=mappings.filter(m=>[m.from_program,...(m.from_tiers||[]),m.to_tier,m.source_scope?.rule_text].filter(Boolean).join(' ').toLocaleLowerCase().includes(term));
    list.replaceChildren();
    for(const mapping of selected.slice(0,visible)){
      const source=mapping.from_program?`${mapping.from_program} · ${(mapping.from_tiers||[]).join('、')||'项目内适用等级'}`:
        mapping.source_scope?.kind==='PUBLIC'?'公开申请':mapping.source_scope?.rule_text||'来源资格尚未核实';
      const row=el('section',undefined,'detail-option');row.append(el('strong',`${source} → ${mapping.to_tier}`));
      if(mapping.availability!=='AVAILABLE')row.append(el('p',mapping.availability==='UNAVAILABLE'?'不可申请':'资格或适用性待核实','caveat'));
      if((typeof mapping.conditions==='string'&&mapping.conditions.trim())||mapping.conditions?.items?.length)row.append(el('p',readable(mapping.conditions)));
      list.append(row);
    }
    notice.textContent=selected.length?`已显示 ${Math.min(visible,selected.length)} / ${selected.length} 项`:'本次筛选未找到记录，不代表官方未提供其他机会。';
    more.hidden=visible>=selected.length;
  }
  filter.addEventListener('input',()=>{visible=20;render();});
  more.onclick=()=>{visible+=20;render();};
  section.addEventListener('toggle',()=>{if(section.open)render();});
}
function briefContent(brief,parent){
  parent.append(el('p',readable(brief.content.summary)));
  for(const change of brief.content.changes||[]){
    const item=el('section',undefined,'detail-option');item.append(el('h4',change.label||'资料变化'));
    if(change.impact)item.append(el('p',change.impact));
    for(const [key,label] of [['before','变更前'],['after','变更后']]){
      const value=change[key];if(value===undefined)continue;
      if(value&&Array.isArray(value.items)&&'count' in value){
        item.append(el('strong',`${label} · ${value.count} 项`));
        for(const row of value.items){
          if('amount' in row){
            const price=row.known_state==='KNOWN'?`${row.currency||''} ${row.amount??'金额待核实'}`:'费用待核实';
            item.append(el('p',`${row.target} · ${({APPLICATION:'申请费',BUY_UP:'升级费',CHALLENGE_SPEND:'挑战消费'})[row.fee_role]||'费用'}：${price}${row.availability!=='AVAILABLE'?' · 适用性待核实':''}${['CONDITIONAL','ALTERNATIVE'].includes(row.combination)?' · 附适用条件':''}`));
            if(row.conditions?.items?.length)item.append(el('p',readable(row.conditions)));
          }else item.append(el('p',`${row.source} → ${row.target}`));
        }
        if(value.omitted)item.append(el('small',`另有 ${value.omitted} 项，请在对应版本完整资料中核对。`));
      }else fact(item,label,value);
    }parent.append(item);
  }
}
function activitySources(a,parent,includeHistory){for(const b of a.briefs||[]){if(b.status!=='READY')continue;const d=el('details');d.append(el('summary',b.kind==='UPDATE'?'变化简报':'活动简报'));briefContent(b,d);parent.append(d);}if(includeHistory&&a.ref)activityHistory(a,parent);if(a.sources?.length){const sources=el('details');sources.append(el('summary','来源与资料时间'));for(const s of a.sources){try{const u=new URL(s.url);if(!['http:','https:'].includes(u.protocol))continue;const line=el('p'),link=el('a',`${s.role==='THIRD_PARTY'?'文章来源':'官方来源'} · ${u.hostname}`);link.href=u.href;link.target='_blank';link.rel='noopener noreferrer';line.append(link,el('small',` · 资料获取于 ${new Date(s.fetched_at).toLocaleDateString('zh-CN')}`));sources.append(line);}catch{}}parent.append(sources);}const links=new Map();for(const o of a.options||[]){const value=o.action_link?.value?.url;if(value)links.set(value,o.label);}if(links.size){const d=el('details');d.append(el('summary','申请链接'));for(const [value,label] of links){try{const url=new URL(value);if(!['http:','https:'].includes(url.protocol))continue;const line=el('p'),link=el('a',label||'查看申请页面');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';line.append(link);d.append(line);}catch{}}parent.append(d);}}
function activityHistory(activity,parent){
  const section=el('details');section.append(el('summary','版本与变化历史'));
  const content=el('div');section.append(content);parent.append(section);
  let loaded=false,loading=false;
  async function load(before=null){
    if(loading)return;loading=true;
    const notice=el('p','正在读取历史…');content.append(notice);
    try{
      const result=await api(`/v2/activities/${activity.ref}/history${before?`?before_version=${before}`:''}`);
      notice.remove();loaded=true;
      for(const version of result.versions){
        const entry=el('details');
        entry.append(el('summary',`${version.is_current?'当前':'历史'} · ${new Date(version.created_at).toLocaleString('zh-CN')}`));
        if(version.brief_status==='READY'){
          const link=el('a','查看此版本简报');link.href=version.brief_url;entry.append(link);
        }else entry.append(el('p',version.brief_status==='MISSING'?'此版本尚无简报，可查看当时的完整资料。':'简报状态暂不可用，可查看当时的完整资料。'));
        const button=el('button','查看此版本资料');entry.append(button);
        button.onclick=async()=>{
          button.disabled=true;
          try{
            const detail=await api(`/v2/activities/${activity.ref}?version_ref=${version.version_ref}`);
            const body=el('section',undefined,'detail-option');activityDetail(detail,body,[],false);button.replaceWith(body);
          }catch(error){button.textContent=error.message+' · 重试';button.disabled=false;}
        };
        content.append(entry);
      }
      if(!result.versions.length)content.append(el('p','暂无已发布版本。'));
      if(result.has_more){const more=el('button','更早版本');more.onclick=()=>{more.remove();load(result.next_before_version);};content.append(more);}
    }catch(error){notice.textContent=error.message;const retry=el('button','重试历史读取');retry.onclick=()=>{notice.remove();retry.remove();load(before);};content.append(retry);}
    finally{loading=false;}
  }
  section.addEventListener('toggle',()=>{if(section.open&&!loaded)load();});
}
function researchDetail(observations,parent){
  if(!observations.length)return;const section=el('section',undefined,'detail-option');section.append(el('h3','申请经验'));
  for(const observation of observations){const item=el('details');item.append(el('summary',observation.direction),el('p',observation.text));
    for(const citation of observation.citations||[]){try{const url=new URL(citation.url);if(url.protocol!=='https:'||!['statusmatcher.com','www.statusmatcher.com'].includes(url.hostname))continue;
      const p=el('p'),link=el('a','查看这条自报案例');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';p.append(link);
      const comparison=({EXACT:'精确可比',PARTIAL:'部分可比',INCOMPARABLE:'未计入可比样本'})[citation.comparability?.state]||'可比性待核实';
      p.append(el('small',`${comparison} · 报告提交：${readable(citation.submitted_at)} · 实际申请：${readable(citation.application_at)}`));
      if(citation.original_from||citation.original_to)p.append(el('small',`${citation.original_from||'来源等级未知'} → ${citation.original_to||'目标等级未知'}`));
      if(citation.evidence_excerpt)p.append(el('small',citation.evidence_excerpt));item.append(p);}catch{}}
    section.append(item);
  }parent.append(section);
}

function activityCard(activity,onOpen){
  const button=el('button',undefined,'card'),card=activity.card||{};
  button.append(el('strong',activity.name||'活动资料'));
  if(activity.is_current===false)button.append(el('small','历史版本'));
  if(['EXPIRED','ARCHIVED','CLOSED'].includes(card.lifecycle_status))button.append(el('small','已结束'));
  button.append(el('p',card.summary||'暂无摘要'));
  const date=activity.updated_at?new Date(activity.updated_at):null;
  const time=el('small',date&&!Number.isNaN(date.getTime())
    ?`更新于 ${date.toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'})}`:'更新时间未提供');
  button.append(time);
  button.onclick=onOpen;return button;
}

export {$,labels,el,api,money,readable,fact,activityDetail,activityCard,showDetail};
