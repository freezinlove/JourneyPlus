import test from 'node:test';
import assert from 'node:assert/strict';
import {renderBrief} from '../../src/journeyplus/product/static/brief_view.js';

const fixture = () => ({
  brief:{title:'Rewards 匹配活动',summary:'简洁活动摘要'},
  brief_updated_at:'2026-09-14T01:00:00Z', fee:{label:'付费'},
  relationship:{text:'你的会籍存在直接匹配路径'},
  facts:{eligibility:{value:'不应单列申请资格'},caveats:{value:'不应铺开全部条款'},status_mappings:[
    {source_program:'Source',source_tiers:['Gold'],target_tier:'Platinum',conditions:'需满足此映射条件'},
    {source_program:'Other',source_tiers:['Silver'],target_tier:'Gold'},
  ]},
  routes:[{scope:'申请方案',prices:[{target_tier:'Platinum',currency:'USD',amount:'99',availability:'AVAILABLE'}]}],
  action_links:['https://example.com/apply'],source_links:['https://example.com/faq'],
});
test('brief contains the agreed sections and complete tables, without full activity fields',()=>{
  const html=renderBrief(fixture());
  for(const text of ['Rewards 匹配活动','简洁活动摘要','和我的关系','完整映射表','价格表','申请入口','原文链接','简报更新于','付费','Source','Other','Platinum','Gold','USD 99','需满足此映射条件','https://example.com/apply','https://example.com/faq'])assert.ok(html.includes(text),text);
  for(const text of ['不应单列申请资格','不应铺开全部条款','资料状态','挑战要求','版本与变化历史'])assert.ok(!html.includes(text),text);
});
test('missing version brief never falls back to current summary or full facts',()=>{
  assert.equal(renderBrief({...fixture(),brief:null,summary:'new version summary'}),'<p class="empty">此版本尚无已生成简报。</p>');
});
test('ended activity, no tables, free fee and no holdings remain readable',()=>{
  const html=renderBrief({...fixture(),lifecycle_status:'EXPIRED',fee:{label:'免费'},facts:{},routes:[],relationship:{text:'尚未保存会籍'}});
  for(const text of ['已结束','免费','尚未保存会籍','原文没有可展示的会籍映射表','原文没有可展示的匹配费用表'])assert.ok(html.includes(text),text);
});
test('model text is escaped and unsafe source/application URLs are not actionable',()=>{
  const detail=fixture();detail.brief.title='<img onerror="bad">';detail.action_links.push('javascript:bad()');detail.source_links.push('data:text/html,bad');
  const html=renderBrief(detail);
  assert.ok(html.includes('&lt;img'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('javascript:'));
  assert.ok(!html.includes('data:text/html'));
});
test('application URLs with and without a root slash are one entry',()=>{
  const detail=fixture();detail.action_links=['https://example.com','https://example.com/'];
  const html=renderBrief(detail);
  assert.equal((html.match(/前往申请页面/g)||[]).length,1);
});
