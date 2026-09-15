"""Read-only legacy conversation compatibility; no decision engine is imported."""
from uuid import UUID
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from journeyplus.models import AgentInteraction, AgentWaitGoal, now_utc
from journeyplus.workspace_models import WorkspaceMessage
from journeyplus.agent.adapters.artifacts import aware


def route_activity_detail(reader,step):
    activity=reader.detail(UUID(step['activity_ref']),UUID(step['version_ref']))
    options=[o for o in activity['options'] if o['ref']==step['option_ref']]
    if len(options)!=1:raise LookupError('路线申请方式与资料版本不一致')
    option=options[0]
    option['mappings']=[m for m in option['mappings'] if m['ref']==step['mapping_ref']]
    if len(option['mappings'])!=1:raise LookupError('路线映射与资料版本不一致')
    price_refs={p['ref'] for key in ('fees','conditional_items','alternative_items') for p in step[key]}
    option['prices']=[p for p in option['prices'] if p['ref'] in price_refs]
    activity['options']=options;activity['detail_scope']='SELECTED_ROUTE_STEP'
    from journeyplus.knowledge.cards import activity_card
    if 'card' in activity:activity['card']=activity_card(activity)
    return activity


def retired_response():
    return JSONResponse(status_code=410, content={'code':'AGENT_RUNTIME_RETIRED','workspace_url':'/workspace'})


def knowledge_router(factory):
    router=APIRouter(prefix='/v2')

    @router.api_route('/agent/{path:path}',methods=['POST','PUT','PATCH','DELETE'])
    def retired_agent(path:str):
        return retired_response()

    @router.api_route('/wait-goal/{path:path}',methods=['POST','PUT','PATCH','DELETE'])
    def retired_wait(path:str):
        return retired_response()

    @router.get('/agent/workspaces/{identity}')
    def read_workspace(identity:UUID):
        with factory() as session:
            row=session.get(AgentInteraction,identity)
            if row is None or row.schema_version!='workspace-1':
                raise HTTPException(404,'LEGACY_WORKSPACE_NOT_FOUND')
            if aware(row.expires_at)<=now_utc():raise HTTPException(410,'WORKSPACE_EXPIRED')
            messages=session.scalars(select(WorkspaceMessage).where(WorkspaceMessage.workspace_id==row.id)
                                     .order_by(WorkspaceMessage.ordinal,WorkspaceMessage.created_at))
            return {'id':str(row.id),'revision':row.revision,'expires_at':aware(row.expires_at).isoformat(),
                    'status':row.status,'read_only':True,
                    'messages':[{'role':m.role,'created_at':aware(m.created_at).isoformat(),**m.content} for m in messages],
                    'explorations':sorted(row.state.get('browse_presentations',{}).values(),key=lambda p:p['created_at']),
                    'pending_action':row.state.get('pending_action'),'focus':row.state.get('focus')}

    @router.get('/wait-goal')
    def read_wait():return {'read_only':True,'goals':[],'enabled':False}

    return router
