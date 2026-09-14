import test from 'node:test';
import assert from 'node:assert/strict';
import {createKnowledgeNavigation,activityLocation} from '../../src/journeyplus/product/static/knowledge_navigation.js';
function setup(href='http://localhost/knowledge',read=async a=>a.ref){
  const location={href},entries=[href];let index=0;const views=[];
  const history={pushState(_state,_title,url){location.href=new URL(url,location.href).href;entries.splice(++index);entries.push(location.href);}};
  const navigation=createKnowledgeNavigation({location,history,read,show:v=>views.push(['loading',v]),clear:()=>views.push(['list']),render:(d,v)=>views.push(['result',d,v]),error:e=>views.push(['error',e.message])});
  return {location,views,navigation,async back(){location.href=entries[--index];await navigation.sync();},async forward(){location.href=entries[++index];await navigation.sync();}};
}
test('list clicks open briefs and refresh retains the clicked activity and version',async()=>{
  const s=setup();await s.navigation.open({ref:'asante',version_ref:'v2'});
  assert.deepEqual(activityLocation(s.location.href),{ref:'asante',version_ref:'v2',briefOnly:true});
  assert.deepEqual(s.views.at(-1),['result','asante',true]);
  await s.navigation.sync();assert.deepEqual(s.views.at(-1),['result','asante',true]);
});
test('close A, open B, refresh and browser back/forward never reuse A as B',async()=>{
  const s=setup('http://localhost/knowledge?activity_id=avolta&version_ref=v1&section=brief');
  await s.navigation.sync();await s.navigation.close();
  assert.equal(s.location.href,'http://localhost/knowledge');
  await s.navigation.open({ref:'asante',version_ref:'v2'});await s.navigation.sync();
  assert.deepEqual(s.views.at(-1),['result','asante',true]);
  await s.back();assert.deepEqual(s.views.at(-1),['list']);
  await s.back();assert.deepEqual(s.views.at(-1),['result','avolta',true]);
  await s.forward();await s.forward();assert.deepEqual(s.views.at(-1),['result','asante',true]);
});
test('late responses and errors cannot overwrite another activity or a closed list',async()=>{
  const pending=[];const s=setup(undefined,()=>new Promise((resolve,reject)=>pending.push({resolve,reject})));
  const a=s.navigation.open({ref:'A',version_ref:'a'}),b=s.navigation.open({ref:'B',version_ref:'b'});
  pending[1].resolve('B');await b;pending[0].resolve('A');await a;
  assert.deepEqual(s.views.at(-1),['result','B',true]);
  const c=s.navigation.open({ref:'C',version_ref:'c'});await s.navigation.close();pending[2].reject(Error('late'));await c;
  assert.deepEqual(s.views.at(-1),['list']);
});
test('historical and explicit detail links preserve their identity; invalid links do not show stale results',async()=>{
  const s=setup('http://localhost/knowledge?activity_id=A&version_ref=old&section=detail');
  await s.navigation.sync();assert.deepEqual(s.views.at(-1),['result','A',false]);
  s.location.href='http://localhost/knowledge?activity_id=B';await s.navigation.sync();assert.equal(s.views.at(-1)[0],'error');
});
