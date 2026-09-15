import {el,money,labels} from './knowledge_ui.js?v=20260907-agent-repair';
const observers=new Set();let graphId=0;
export function disposeGraphs(){for(const observer of observers)observer.disconnect();observers.clear();}

export function graphStructure(payload){
  const nodes=new Map(),edges=new Map();
  const sources=new Map();
  const rootLabel=payload.routes.every(route=>route.source_mode==='explicit')?'本次起点':'我的会籍';
  for(const route of payload.routes){
    for(const source of route.query_sources||[]){
      if(source.program_name)sources.set(source.tier_ref||`${source.program_name} ${source.tier_name||''}`,
        `${source.program_name} ${source.tier_name||''}`.trim());
    }
    const first=payload.steps[route.step_refs[0]];
    if(first?.from&&!route.query_sources?.length)sources.set(first.from_tier_id||first.from,first.from);
  }
  for(const [routeIndex,route] of payload.routes.entries()){
    let previous=null;
    for(const [index,ref] of route.step_refs.entries()){
      const step=payload.steps[ref];
      if(index===0){
        previous=step.from?'my-memberships':'public-application';
        if(!nodes.has(previous))nodes.set(previous,{ref:previous,name:step.from?`${rootLabel}：${[...new Set(sources.values())].join(' ＋ ')}`:'公开申请入口',level:0,origin:true,step_refs:[]});
      }
      const group=Object.values(payload.nodes||{}).find(node=>node.step_refs.includes(ref));
      const target=group?.ref||`member:${step.to_tier_id||step.to}`;
      const node=nodes.get(target)||{ref:target,browseRef:group?.ref||ref,name:step.to,level:index+1,step_refs:[]};
      node.level=Math.max(node.level,index+1);if(!node.step_refs.includes(ref))node.step_refs.push(ref);nodes.set(target,node);
      const key=`${previous}>${target}`;
      const edge=edges.get(key)||{from:previous,to:target,step_ref:ref,routes:[]};
      if(payload.steps[edge.step_ref]?.paid===true&&step.paid===false)edge.step_ref=ref;
      if(!edge.routes.includes(routeIndex))edge.routes.push(routeIndex);edges.set(key,edge);previous=target;
    }
  }
  return {nodes:[...nodes.values()],edges:[...edges.values()]};
}

function stepCost(step){
  if(typeof step.paid==='boolean')return step.paid?'付费':'免费';
  return step.fee_free?'免费':'付费';
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
        box.disabled=disabled;box.append(el('small',node.step_refs.length>1?`${node.step_refs.length} 种已选申请方式`:'查看匹配详情'));

        box.onclick=()=>onBrowse(node.browseRef,messageId);
      }
      positions.set(node.ref,box);column.append(box);
    }grid.append(column);
  }
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),markerId=`graph-arrow-${++graphId}`;svg.classList.add('graph-edges');svg.setAttribute('aria-hidden','true');
  canvas.append(svg,grid);section.append(canvas);
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
