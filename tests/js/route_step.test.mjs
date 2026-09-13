import test from 'node:test';
import assert from 'node:assert/strict';
import {activityForStep} from '../../src/journeyplus/product/static/route_step.js';

const detail={data_model:'aiworkflow',ref:'event',version_ref:'facts-1',facts:{action_link:{value:'https://example.com/apply'}},options:[
  {ref:'route-0',prices:[{target_tier:'Silver',amount:1},{target_tier:'Gold',amount:49}],mappings:[]},
  {ref:'mappings',mappings:[{ref:'mapping-0',to_tier:'Gold'},{ref:'mapping-1',to_tier:'Silver'}]},
]};
const step={activity_ref:'event',version_ref:'facts-1',option_ref:'route-0',mapping_ref:'mapping-0',fees:[{ref:'facts-1/route-0/price-1'}]};

test('selected original route preserves only the matching tier price and mapping',()=>{
  const selected=activityForStep(detail,step);
  assert.deepEqual(selected.options[0].prices,[{target_tier:'Gold',amount:49}]);
  assert.deepEqual(selected.options[0].mappings,[{ref:'mapping-0',to_tier:'Gold'}]);
  assert.equal(detail.options[0].prices.length,2);
});

test('mapping-only original facts can open without invented regional options',()=>{
  const mappingOnly={...detail,options:[detail.options[1]]};
  const selected=activityForStep(mappingOnly,{...step,option_ref:null,fees:[]});
  assert.equal(selected.options[0].ref,'mappings');
  assert.equal(selected.options[0].mappings.length,1);
  assert.deepEqual(selected.options[0].prices,[]);
  assert.equal(selected.facts.action_link.value,'https://example.com/apply');
  assert.throws(()=>activityForStep(detail,{...step,option_ref:null}));
});

test('stale versions or foreign mappings never acquire current facts',()=>{
  assert.throws(()=>activityForStep(detail,{...step,version_ref:'facts-2'}));
  assert.throws(()=>activityForStep(detail,{...step,mapping_ref:'unknown'}));
});

test('a selected tier does not inherit whole-activity mixed fee badges',()=>{
  const activity=structuredClone(detail);
  activity.fee={label:'部分免费／部分付费'};activity.options[0].fee={label:'部分免费／部分付费'};
  const selected=activityForStep(activity,step);
  assert.equal(selected.fee,undefined);assert.equal(selected.options[0].fee,undefined);
  const free=activityForStep(activity,{...step,fee_free:true});
  assert.equal(free.options[0].fee.label,'免费');
  assert.equal(activity.fee.label,'部分免费／部分付费');
});

test('simple matching expands the activity without regional path coupling',()=>{
  const selected=activityForStep(detail,{activity_ref:'event',version_ref:'facts-1',matching_policy:'simple-matching-v1'});
  assert.equal(selected.options.length,2);
  assert.equal(selected.options[0].prices.length,2);
  assert.equal(selected.detail_scope,'ACTIVITY_DETAILS');
  assert.throws(()=>activityForStep(detail,{activity_ref:'event',version_ref:'stale',matching_policy:'simple-matching-v1'}));
});
