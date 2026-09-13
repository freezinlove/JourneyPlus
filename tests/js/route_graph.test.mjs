import test from 'node:test';
import assert from 'node:assert/strict';
import {graphStructure} from '../../src/journeyplus/product/static/route_graph.js';

test('shared destination has one node and preserves both incoming applications',()=>{
  const graph=graphStructure({routes:[{step_refs:['direct']},{step_refs:['via','last']}],steps:{
    direct:{from:'A',to:'C'},via:{from:'A',to:'B'},last:{from:'B',to:'C'}},nodes:{
    c:{ref:'c',step_refs:['direct','last']},b:{ref:'b',step_refs:['via']}}});
  assert.equal(graph.nodes.length,3);assert.equal(graph.edges.length,3);
  assert.deepEqual(graph.nodes.find(n=>n.ref==='c').step_refs,['direct','last']);
  assert.equal(graph.nodes.filter(n=>n.name==='C').length,1);
});

test('shared step is drawn once while retaining its route memberships',()=>{
  const graph=graphStructure({routes:[{step_refs:['common','b']},{step_refs:['common','c']}],steps:{
    common:{from:'A',to:'Shared'},b:{from:'Shared',to:'B'},c:{from:'Shared',to:'C'}}});
  assert.equal(graph.edges.length,3);
  assert.deepEqual(graph.edges.find(e=>e.step_ref==='common').routes,[0,1]);
});

test('public application is an entry, never an invented held membership',()=>{
  const graph=graphStructure({routes:[{step_refs:['public']}],steps:{public:{from:null,to:'Gold'}}});
  const origin=graph.nodes.find(n=>n.origin);
  assert.equal(origin.ref,'public-application');assert.equal(origin.name,'公开申请入口');
  assert.equal(origin.browseRef,undefined);
});

test('same identity connection with different refs is drawn only once',()=>{
  const graph=graphStructure({routes:[{step_refs:['one']},{step_refs:['two']}],steps:{
    one:{from:'A',to:'C',paid:true},two:{from:'A',to:'C',paid:true}}});
  assert.equal(graph.nodes.length,2);assert.equal(graph.edges.length,1);
});

test('one root includes every query source even when only one contributes highest routes',()=>{
  const graph=graphStructure({routes:[{step_refs:['one'],query_sources:[
    {tier_ref:'m',program_name:'Marriott Bonvoy',tier_name:'Platinum Elite'},
    {tier_ref:'l',program_name:'Lufthansa Miles & More',tier_name:'Senator'}]}],steps:{
      one:{from:'Lufthansa Miles & More Senator',to:'Asante Gold',paid:true}}});
  assert.equal(graph.nodes.filter(n=>n.origin).length,1);
  assert.match(graph.nodes[0].name,/Marriott Bonvoy Platinum Elite/);
  assert.match(graph.nodes[0].name,/Lufthansa Miles & More Senator/);
});

test('merged root shares one connection and uses free supporting step',()=>{
  const graph=graphStructure({routes:[{step_refs:['paid']},{step_refs:['free']}],steps:{
    paid:{from:'Lufthansa Senator',to:'Gold',to_tier_id:'gold',paid:true},
    free:{from:'Marriott Platinum',to:'Gold',to_tier_id:'gold',paid:false}}});
  assert.equal(graph.edges.length,1);assert.equal(graph.nodes.filter(n=>n.origin).length,1);
  assert.equal(graph.edges[0].step_ref,'free');
});

test('binary fee flags do not need any amount fields',async()=>{
  const {money}=await import('../../src/journeyplus/product/static/knowledge_ui.js');
  assert.equal(money({paid:true,state:'KNOWN'}),'付费');
  assert.equal(money({paid:false,state:'KNOWN'}),'免费');
});
