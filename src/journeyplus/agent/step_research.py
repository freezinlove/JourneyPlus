"""Permission-gated, bounded per-step research. No official-knowledge writes."""
from dataclasses import dataclass,field
from datetime import datetime,UTC
import httpx
from journeyplus.agent.research_http import ResearchBudget,ResearchBudgetExceeded,read_research_html,permitted_url
from journeyplus.agent.report_pages import list_report_candidates,select_report_candidates,parse_report_detail
from journeyplus.agent.research_cache import cached_observations,save_observations


@dataclass
class ResearchRun:
    budget:ResearchBudget=field(default_factory=ResearchBudget)
    detail_count:int=0
    pages:dict=field(default_factory=dict)
    reports:dict=field(default_factory=dict)
    official_reads:dict=field(default_factory=dict)


class StepResearchService:
    def __init__(self,*,enabled=False,companies=None,identities=None,client=None,response_limit=1_000_000,timeout_seconds=12,max_pages=2):
        if not 0<response_limit<=1_000_000 or not 0<timeout_seconds<=30 or not isinstance(max_pages,int) or not 1<=max_pages<=2:
            raise ValueError("Research limits exceed permitted bounds")
        self.response_limit=response_limit;self.timeout_seconds=timeout_seconds;self.max_pages=max_pages
        self.enabled=enabled
        self.companies=companies or {}
        self.identities=identities or {}
        self.client=client or httpx.Client(follow_redirects=False)

    def research_steps(self,targets,state,*,user_requested,workspace_expires_at,refresh=False,run=None,identities=None):
        if not self.enabled:return {'status':'DISABLED','steps':[],'http_requests':0}
        if not user_requested:return {'status':'NOT_REQUESTED','steps':[],'http_requests':0}
        if not targets:return {'status':'INSUFFICIENT','steps':[],'http_requests':0,'reason':'STEP_REQUIRED'}
        identities=identities if identities is not None else self.identities
        run=run or ResearchRun();before=run.budget.requests;results=[]
        now=datetime.now(UTC)
        for target in targets:
            step_before=run.budget.requests
            cached=None if refresh else cached_observations(state,target,now=now)
            if cached is not None:
                results.append({**cached,'status':('PARTIAL' if cached['reports'] else 'UNAVAILABLE') if cached['coverage'].get('stopped_reason') not in {None,'NO_REPORTS'} else 'COMPLETED' if cached['reports'] else 'INSUFFICIENT'});continue
            mapping=self.companies.get(target.to_program_ref)
            if not mapping or not mapping.get('verified_at'):
                results.append({'step_ref':target.step_ref,'status':'UNAVAILABLE','reason':'COMPANY_MAPPING_UNVERIFIED'});continue
            step_identities=dict(identities)
            for candidate_mapping in self.companies.values():
                for name,identity in candidate_mapping.get('identities',{}).items():step_identities.setdefault(name,identity)
            step_identities.update(self.companies.get(target.from_program_ref,{}).get('identities',{}))
            step_identities.update(mapping.get('identities',{}))
            from journeyplus.knowledge.publication import canonical_key
            for program_id,tier_id in [(target.from_program_ref,target.from_tier_ref),(target.to_program_ref,target.to_tier_ref)]:
                item=self.companies.get(program_id,{})
                label=item.get('tier_labels',{}).get(tier_id)
                if label:
                    step_identities[canonical_key(item['title']+' '+label)]={'program_ref':program_id,'tier_ref':tier_id}
                    if label.startswith('elite '):step_identities[canonical_key(item['title']+' '+label[6:])]={'program_ref':program_id,'tier_ref':tier_id}
            reports=[];stopped=None
            try:
                url=permitted_url(mapping['verified_url'])
                if '/company/' not in url:raise ValueError('COMPANY_MAPPING_INVALID')
                candidates=[]
                for page in range(self.max_pages):
                    page_url=url if page==0 else url+'?page-to=1'
                    try:
                        if page_url not in run.pages:
                            html,final_url=read_research_html(self.client,page_url,run.budget,response_limit=self.response_limit,timeout_seconds=self.timeout_seconds)
                            run.pages[page_url]=list_report_candidates(html,final_url)
                        candidates.extend(run.pages[page_url])
                        if not run.pages[page_url]:break
                    except httpx.HTTPError:
                        stopped='HTTP_ERROR';break
                    except ValueError as exc:
                        if isinstance(exc,ResearchBudgetExceeded):raise
                        stopped='PARSE_ERROR';break
                for candidate in select_report_candidates(candidates,target,step_identities,now.date()):
                    report_url=candidate['url']
                    if report_url not in run.reports:
                        if run.detail_count>=8:
                            stopped='REPORT_BUDGET';break
                        run.detail_count+=1
                        html,final_url=read_research_html(self.client,report_url,run.budget,response_limit=self.response_limit,timeout_seconds=self.timeout_seconds)
                        run.reports[report_url]=(html,final_url)
                    report=parse_report_detail(*run.reports[report_url],step_identities)
                    if report.to_program_ref==target.to_program_ref and (target.from_program_ref is None or report.from_program_ref==target.from_program_ref):
                        reports.append(report)
            except ResearchBudgetExceeded as exc:
                stopped='TIME_BUDGET' if 'DEADLINE' in str(exc) else 'BYTE_BUDGET' if 'BYTE' in str(exc) or 'RESPONSE' in str(exc) else 'REQUEST_BUDGET'
            except httpx.HTTPError:stopped='HTTP_ERROR'
            except ValueError:stopped='PARSE_ERROR'
            reports=list({r.report_ref:r for r in reports}.values())
            coverage={'complete':False,'requests':run.budget.requests-step_before,'report_count':len(reports),
                      'stopped_reason':stopped or (None if reports else 'NO_REPORTS')}
            save_observations(state,target,reports,now=now,workspace_expires_at=workspace_expires_at,coverage=coverage)
            result=cached_observations(state,target,now=now)
            results.append({**(result or {}),'step_ref':target.step_ref,'cache_hit':False,
                'status':'PARTIAL' if stopped and reports else 'UNAVAILABLE' if stopped else 'COMPLETED' if reports else 'INSUFFICIENT'})
        statuses={r['status'] for r in results}
        status='PARTIAL' if len(statuses)>1 or 'PARTIAL' in statuses else next(iter(statuses))
        return {'status':status,'steps':results,'http_requests':run.budget.requests-before,
                'coverage':{'search_complete':False,'detail_count':run.detail_count,'bytes_read':run.budget.bytes_read}}


def research_decision_packet(result):
    observations=[]
    for step in result.get('steps',[]):
        summary={k:v for k,v in step.items() if k!='reports'}
        summary['ref']=step['step_ref']
        from journeyplus.agent.research_recheck import needs_official_recheck
        summary['official_recheck_needed']=needs_official_recheck({'citations':step.get('reports',[])})
        comparisons={o['report_ref']:o.get('comparability') for o in step.get('observations',[])}
        summary['citations']=[{'submitted_at':r.get('submitted_at'),'application_at':r.get('application_at'),
                               'original_from':r.get('original_from'),'original_to':r.get('original_to'),
                               'comparability':comparisons.get(r['report_ref']), 'report_ref':r['report_ref'],'url':r['url'],'outcome':r['normalized_outcome'],
                               'evidence_excerpt':r.get('evidence_excerpt')} for r in step.get('reports',[])[:3]]
        observations.append(summary)
    return {'schema_version':1,'status':result['status'],'cache_hit':bool(observations) and all(s.get('cache_hit',False) for s in observations),'data':{'step_observations':observations},
            'coverage':{**result.get('coverage',{}),'search_complete':False,'http_requests':result.get('http_requests',0)},
            'caveats':['用户自报案例只提供经验线索，不代表实际审批概率。']}


def research_answer_text(results,steps):
    selected={s['step_ref']:s for result in results for s in result.get('data',{}).get('step_observations',[])}
    lines=[]
    windows={'APPLICATION_12M':'近12个月申请','APPLICATION_12_TO_24M':'12至24个月前申请',
             'HISTORICAL_APPLICATION':'历史申请','RECENT_SUBMISSION_APPLICATION_UNKNOWN':'近期提交，申请日期未知',
             'APPLICATION_DATE_UNKNOWN':'申请日期未知'}
    outcomes={'DIRECT_MATCH':'直接匹配','CHALLENGE':'挑战','DENIED':'拒绝'}
    for ref,observation in selected.items():
        step=steps.get(ref,{})
        label=((step.get('from') or '公开申请')+' → '+step['to']) if step.get('to') else '所选步骤'
        if observation.get('status')=='UNAVAILABLE':lines.append(label+'：经验资料暂不可用。');continue
        if not observation.get('windows'):
            lines.append(label+'：本次没有找到足够可比的申请案例，不能据此判断申请结果。')
        else:lines.append(label+'：以下为有限范围的自报案例。')
        if observation.get('incomparable_count'):lines.append(f"另有 {observation['incomparable_count']} 个案例的来源或目标等级不同，未计入可比样本。")
        for window,counts in observation.get('windows',{}).items():
            parts=[]
            for kind,label_kind in [('exact_counts','精确可比'),('partial_counts','部分可比')]:
                parts.extend(f"{label_kind}{outcomes[outcome]} {count} 例" for outcome,count in counts[kind].items())
            if counts['unknown_count']:parts.append(f"结果未知 {counts['unknown_count']} 例")
            lines.append(windows.get(window,window)+'：'+'；'.join(parts)+'。')
        if observation.get('status')=='PARTIAL':lines.append('本步骤仅取得部分资料，仍有读取失败或预算限制。')
        if observation.get('official_recheck_status')=='FACTS_READ_REQUIRES_REVIEW':lines.append('案例提示可能存在来源取得或挑战限制，已读取官方资料供核对；尚未据此改变官方规则。')
        elif observation.get('official_recheck_status') in {'PENDING_BUDGET','UNAVAILABLE'}:lines.append('案例涉及的来源取得或挑战限制仍待核对官方资料。')
        if observation.get('official_recheck_version_changed'):lines.append('当前官方资料版本已有更新，原路径仍保留原版本，需重新评估。')
        if observation.get('observed_at'):lines.append('调查时间：'+observation['observed_at'])
    if lines:lines.append('这些计数不代表真实审批成功率；不同步骤不合并样本，也不连乘概率。')
    return '\n'.join(lines)
