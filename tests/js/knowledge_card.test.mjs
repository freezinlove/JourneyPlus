import test from 'node:test';
import assert from 'node:assert/strict';
import {activityCard} from '../../src/journeyplus/product/static/knowledge_ui.js';

globalThis.document={createElement(tag){return {tag,children:[],append(...nodes){this.children.push(...nodes);}};}};
const text=node=>[node.textContent||'',...node.children.map(text)].join(' ');
test('activity cards show the summary and actual update time without legacy verification fields',()=>{
  let opened=false;
  const node=activityCard({name:'活动标题',updated_at:'2026-09-14T01:02:03Z',card:{summary:'摘要 <正文>',lifecycle_status:'UNKNOWN',challenge:'UNKNOWN',fees:[{value:'不应展示'}]}},()=>opened=true);
  const value=text(node);
  assert.match(value,/活动标题/);assert.match(value,/摘要 <正文>/);
  assert.match(value,/2026\/9\/14/);assert.doesNotMatch(value,/09:02|01:02/);assert.doesNotMatch(value,/查看简报/);
  assert.doesNotMatch(value,/核实|核对|挑战|不应展示/);
  node.onclick();assert.equal(opened,true);
});
test('historical and ended cards keep factual markers and missing dates are not fabricated',()=>{
  const value=text(activityCard({is_current:false,card:{lifecycle_status:'EXPIRED'}},()=>{}));
  assert.match(value,/历史版本/);assert.match(value,/已结束/);
  assert.match(value,/暂无摘要/);assert.match(value,/更新时间未提供/);
  assert.doesNotMatch(value,/待核对|Invalid Date/);
});
