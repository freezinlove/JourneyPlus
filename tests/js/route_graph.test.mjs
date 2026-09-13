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
