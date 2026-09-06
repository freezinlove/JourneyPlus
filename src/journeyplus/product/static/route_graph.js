import {el,money,labels} from './knowledge_ui.js';
const observers=new Set();let graphId=0;
export function disposeGraphs(){for(const observer of observers)observer.disconnect();observers.clear();}

export function graphStructure(payload){
  const nodes=new Map(),edges=new Map();
  for(const [routeIndex,route] of payload.routes.entries()){
    let previous=null;
    for(const [index,ref] of route.step_refs.entries()){
      const step=payload.steps[ref];
      if(index===0){
        previous=step.from?`origin:${step.from_tier_id||step.from}`:'public-application';
        if(!nodes.has(previous))nodes.set(previous,{ref:previous,name:step.from||'公开申请入口',level:0,origin:true});
      }
      const group=Object.values(payload.nodes||{}).find(node=>node.step_refs.includes(ref));
      const target=group?.ref||`target:${step.to_tier_id||step.to}`;
      const node=nodes.get(target)||{ref:target,browseRef:group?.ref||ref,name:step.to,level:index+1,step_refs:[]};
      node.level=Math.max(node.level,index+1);if(!node.step_refs.includes(ref))node.step_refs.push(ref);nodes.set(target,node);
      const key=`${previous}>${target}@${ref}`;
      const edge=edges.get(key)||{from:previous,to:target,step_ref:ref,routes:[]};
      if(!edge.routes.includes(routeIndex))edge.routes.push(routeIndex);edges.set(key,edge);previous=target;
    }
  }
  return {nodes:[...nodes.values()],edges:[...edges.values()]};
}

function stepCost(step){
  if(!step.fees?.length)return '费用待核实';
  if(!step.fee_unknown&&step.fees.every(fee=>Number(fee.amount)===0))return '免费';
  return money({totals:step.fees}).replaceAll('申请费用 ','')+(step.fee_unknown?' · 另有待核实费用':'');
}

export function routeGraph(block,messageId,onBrowse,disabled=false){
  const payload=block.payload,structure=graphStructure(payload),section=el('section',undefined,'route-graph');
  section.setAttribute('aria-label','所选匹配关系图');
  const canvas=el('div',undefined,'graph-canvas'),grid=el('div',undefined,'graph-levels');
  const count=Math.max(0,...structure.nodes.map(n=>n.level))+1;
  if(count>4)grid.classList.add('graph-deep');
  grid.style.setProperty('--graph-level-count',count);
  const positions=new Map();
  for(let level=0;level<count;level++){
    const column=el('div',undefined,'graph-level');
    for(const node of structure.nodes.filter(n=>n.level===level)){
      const box=el(node.origin?'div':'button',undefined,'graph-node'+(node.origin?' graph-origin':' node-button'));
      box.append(el('strong',node.name));
      if(node.origin)box.append(el('small',node.ref==='public-application'?'不要求已有会籍':'本次查询起点'));
      else{
        box.disabled=disabled;box.append(el('small',node.step_refs.length>1?`${node.step_refs.length} 种已选申请方式`:'查看这一步的申请条件'));
        if(node.step_refs.some(ref=>payload.steps[ref].eligibility!=='PASS'))box.append(el('small','资格仍需核对','caveat'));
        box.onclick=()=>onBrowse(node.browseRef,messageId);
      }
      positions.set(node.ref,box);column.append(box);
    }grid.append(column);
  }
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),markerId=`graph-arrow-${++graphId}`;svg.classList.add('graph-edges');svg.setAttribute('aria-hidden','true');
  canvas.append(svg,grid);section.append(canvas);
  const descriptions=el('ol',undefined,'graph-routes');
  for(const [index,route] of payload.routes.entries()){
    const item=el('li');const path=[route.from||'公开申请',...route.step_refs.map(ref=>payload.steps[ref].to)].join(' → ');
    const role=route.classification==='MATCH'?(block.graph_mode==='RECOMMEND'?(route.presentation_role==='PRIMARY'?'首选':'备选'):'符合查询条件'):(labels[route.classification]||'待核实');
    item.append(el('strong',`方案 ${route.presentation_index||index+1} · ${role}`),el('div',path),el('div',money(route.cost)));
    if(block.graph_mode==='RECOMMEND'&&route.recommendation_basis)item.append(el('small',route.recommendation_basis));
    const investigated=(payload.research||[]).filter(o=>route.step_refs.includes(o.step_ref));
    if(investigated.length)item.append(el('small',`已查 ${investigated.length}/${route.step_refs.length} 步经验，样本限制见节点详情`));
    if(route.challenge==='UNKNOWN'||route.cost.state!=='KNOWN')item.append(el('small',`${route.cost.state!=='KNOWN'?'费用尚未完整核实；':''}${route.challenge==='UNKNOWN'?'挑战要求尚未核实':''}`,'caveat'));
    descriptions.append(item);
  }
  section.append(descriptions,el('small','仅表示下方列出的完整路径；共享节点不代表其他拼接顺序也可申请。','caveat'));
  function draw(){
    if(!canvas.isConnected)return;
    const bounds=canvas.getBoundingClientRect(),vertical=getComputedStyle(grid).display==='flex';
    svg.setAttribute('viewBox',`0 0 ${bounds.width} ${bounds.height}`);svg.replaceChildren();
    const defs=document.createElementNS(ns,'defs'),marker=document.createElementNS(ns,'marker'),arrow=document.createElementNS(ns,'path');
    for(const [key,value] of Object.entries({id:markerId,viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'5',markerHeight:'5',orient:'auto-start-reverse'}))marker.setAttribute(key,value);
    arrow.setAttribute('d','M0 0 L10 5 L0 10 Z');arrow.setAttribute('style','fill:#607c62;stroke:none');marker.append(arrow);defs.append(marker);svg.append(defs);
    for(const edge of structure.edges){
      const a=positions.get(edge.from).getBoundingClientRect(),b=positions.get(edge.to).getBoundingClientRect();
      const ax=(vertical?a.left+a.width/2:a.right)-bounds.left,ay=(vertical?a.bottom:a.top+a.height/2)-bounds.top;
      const bx=(vertical?b.left+b.width/2:b.left)-bounds.left,by=(vertical?b.top:b.top+b.height/2)-bounds.top;
      const path=document.createElementNS(ns,'path');
      const skipped=Math.abs(structure.nodes.find(n=>n.ref===edge.to).level-structure.nodes.find(n=>n.ref===edge.from).level)>1;
      const bend=skipped?bounds.width-6:null;
      const arcTop=Math.min(...[...positions.values()].map(node=>node.getBoundingClientRect().top-bounds.top))-16;
      
      path.setAttribute('d',vertical?(skipped?`M${ax},${ay} L${ax},${ay+20} L${bend},${ay+20} L${bend},${by-20} L${bx},${by-20} L${bx},${by}`:`M${ax},${ay} C${ax},${(ay+by)/2} ${bx},${(ay+by)/2} ${bx},${by}`):(skipped?`M${ax},${ay} L${ax+18},${ay} L${ax+18},${arcTop} L${bx-18},${arcTop} L${bx-18},${by} L${bx},${by}`:`M${ax},${ay} C${(ax+bx)/2},${ay} ${(ax+bx)/2},${by} ${bx},${by}`));
      path.setAttribute('class',edge.routes.includes(0)?'graph-primary-edge':'graph-alternative-edge');path.setAttribute('marker-end',`url(#${markerId})`);svg.append(path);
      const caption=document.createElementNS(ns,'text');caption.setAttribute('x',vertical?(skipped?bend-8:(ax+bx)/2-6):(ax+bx)/2);caption.setAttribute('y',vertical?(ay+by)/2:skipped?arcTop-6:(ay+by)/2-7);
      caption.setAttribute('text-anchor',vertical?'end':'middle');const cost=stepCost(payload.steps[edge.step_ref]);caption.textContent=cost.length>14?'费用见详情':cost;svg.append(caption);
    }
  }
  const observer=new ResizeObserver(()=>{if(canvas.isConnected)draw();else{observer.disconnect();observers.delete(observer);}});observers.add(observer);observer.observe(canvas);
  requestAnimationFrame(draw);return section;
}
