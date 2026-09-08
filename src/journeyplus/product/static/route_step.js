// Select only the immutable edge's option, mapping and applicable prices.
export function activityForStep(detail, step) {
  if (detail.ref !== step.activity_ref || detail.version_ref !== step.version_ref) throw Error('版本与路径不一致');
  const activity=structuredClone(detail);
  activity.options=activity.options.filter(option=>option.ref===step.option_ref);
  if(activity.options.length!==1)throw Error('版本与申请方式不一致');
  const option=activity.options[0];
  option.mappings=option.mappings.filter(mapping=>mapping.ref===step.mapping_ref);
  if(option.mappings.length!==1)throw Error('版本与来源映射不一致');
  const prices=new Set(['fees','conditional_items','alternative_items'].flatMap(key=>(step[key]||[]).map(item=>item.ref)));
  option.prices=option.prices.filter(price=>prices.has(price.ref));
  activity.detail_scope='SELECTED_ROUTE_STEP';
  return activity;
}
