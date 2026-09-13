// Select only the immutable edge's option, mapping and applicable prices.
export function activityForStep(detail, step) {
  if (detail.ref !== step.activity_ref || detail.version_ref !== step.version_ref) throw Error('版本与路径不一致');
  const activity=structuredClone(detail);
  const mappingOnly=detail.data_model==='aiworkflow'&&step.option_ref==null;
  if(mappingOnly&&detail.options.some(option=>option.ref!=='mappings'))throw Error('版本与申请方式不一致');
  activity.options=activity.options.filter(option=>option.ref===(mappingOnly?'mappings':step.option_ref));
  if(activity.options.length!==1)throw Error('版本与申请方式不一致');
  const option=activity.options[0];
  const mappings=detail.data_model==='aiworkflow'?detail.options.flatMap(o=>o.mappings||[]):option.mappings;
  option.mappings=mappings.filter(mapping=>mapping.ref===step.mapping_ref);
  if(option.mappings.length!==1)throw Error('版本与来源映射不一致');
  const prices=new Set(['fees','conditional_items','alternative_items'].flatMap(key=>(step[key]||[]).map(item=>item.ref)));
  option.prices=(option.prices||[]).filter((price,index)=>prices.has(detail.data_model==='aiworkflow'?`${detail.version_ref}/${option.ref}/price-${index}`:price.ref));
  // Activity/option fee badges summarize all tiers; don't carry them into one selected edge.
  if(detail.data_model==='aiworkflow'){
    delete activity.fee;delete option.fee;
    if(step.fee_free)option.fee={label:'免费'};
  }
  activity.detail_scope='SELECTED_ROUTE_STEP';
  return activity;
}
