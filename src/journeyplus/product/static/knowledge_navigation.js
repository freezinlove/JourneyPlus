// The URL is the source of truth for list, brief and explicit detail views.
export function activityLocation(href) {
  const params=new URL(href).searchParams;
  const ref=params.get('activity_id'),version_ref=params.get('version_ref');
  if(!ref&&!version_ref)return null;
  if(!ref||!version_ref)throw Error('活动链接缺少活动或版本信息，请从列表重新打开。');
  return {ref,version_ref,briefOnly:params.get('section')!=='detail'};
}
export function activityURL(activity,href) {
  const url=new URL('/knowledge',href);
  url.search=new URLSearchParams({activity_id:activity.ref,version_ref:activity.version_ref,section:'brief'});
  return url.pathname+url.search;
}
export function createKnowledgeNavigation({location,history,read,show,clear,render,error}) {
  let generation=0;
  async function sync() {
    const request=++generation;
    let activity;
    try {activity=activityLocation(location.href);} catch(failure){show(true);error(failure);return;}
    if(!activity){clear();return;}
    show(activity.briefOnly);
    try {
      const result=await read(activity);
      if(request===generation)render(result,activity.briefOnly);
    } catch(failure){if(request===generation)error(failure);}
  }
  function navigate(url) {
    history.pushState(null,'',url);
    return sync();
  }
  return {sync,open:activity=>navigate(activityURL(activity,location.href)),close:()=>navigate('/knowledge')};
}
