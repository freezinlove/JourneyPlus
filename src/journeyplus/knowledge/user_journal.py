"""Transactional, opt-in user-operation journaling and conflict-safe replay.

This journal is never an Agent memory source. It holds the two explicit business
entities, including their original authorization statements, not chat history.
"""
from datetime import UTC,date,datetime
from uuid import UUID,uuid4
import json
import hashlib
from sqlalchemy import event,select,Date,DateTime,Uuid
from sqlalchemy.orm import Session
from journeyplus.models import StatusHolding,AgentWaitGoal,UserBusinessOperation

ENTITIES={'HOLDING':StatusHolding,'WAIT_GOAL':AgentWaitGoal}
KINDS={model:kind for kind,model in ENTITIES.items()}
IGNORED={'created_at','updated_at','source_interaction_id'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def snapshot(model,value):
    if value is None:return None
    result={}
    for column in model.__table__.columns:
        if column.name in IGNORED:continue
        item=value[column.name] if isinstance(value,dict) else getattr(value,column.name)
        if isinstance(item,datetime):item=(item.replace(tzinfo=UTC) if item.tzinfo is None else item.astimezone(UTC)).isoformat()
        result[column.name]=item.isoformat() if isinstance(item,date) else str(item) if isinstance(item,UUID) else item
    return json.loads(json.dumps(result))


def payload(kind,identity,before,after):
    return {'entity_kind':kind,'entity_id':str(identity),'before_state':before,'after_state':after}


def enable_journal(factory):
    factory.configure(info={**factory.kw.get('info',{}),'user_business_journal':True})


def configure_user_data(factory,mode='legacy',paused=False):
    factory.configure(info={**factory.kw.get('info',{}),'user_business_journal':mode=='unified',
                            'user_business_writes_paused':paused or mode=='rollback'})


@event.listens_for(Session,'before_flush')
def capture_before(session,flush_context,instances):
    if session.info.get('user_business_writes_paused') and not session.info.get('replaying_user_operations'):
        if any(type(row) in KINDS for row in [*session.new,*session.dirty,*session.deleted]):
            raise ValueError('USER_WRITES_PAUSED')
    if not session.info.get('user_business_journal') or session.info.get('replaying_user_operations'):return
    pending=[]
    for entity in [*session.new,*session.dirty,*session.deleted]:
        model=type(entity)
        if model not in KINDS:continue
        deleted=entity in session.deleted
        if entity not in session.new and not deleted and not session.is_modified(entity,include_collections=True):continue
        if entity.id is None:entity.id=uuid4()
        old=session.connection().execute(select(model.__table__).where(model.id==entity.id)).mappings().first()
        pending.append((entity,snapshot(model,dict(old)) if old else None,deleted))
    session.info['_pending_user_operations']=pending


@event.listens_for(Session,'after_flush')
def capture_after(session,flush_context):
    for entity,before,deleted in session.info.pop('_pending_user_operations',[]):
        kind=KINDS[type(entity)];after=None if deleted else snapshot(type(entity),entity)
        if before==after:continue
        value=payload(kind,entity.id,before,after)
        session.add(UserBusinessOperation(**{**value,'entity_id':entity.id},payload_hash=digest(value)))


@event.listens_for(Session,'after_rollback')
def clear_pending(session):session.info.pop('_pending_user_operations',None)


def export_operations(session,after_sequence=0):
    rows=session.scalars(select(UserBusinessOperation).where(UserBusinessOperation.sequence>after_sequence).order_by(UserBusinessOperation.sequence))
    return [{'sequence':row.sequence,'operation_id':str(row.operation_id),**payload(row.entity_kind,row.entity_id,row.before_state,row.after_state),
             'payload_hash':row.payload_hash,'created_at':row.created_at.isoformat()} for row in rows]


def replay_operations(session,operations):
    """Caller owns one transaction and must retain the additive knowledge tables.

    Missing catalogue dependencies, singleton conflicts or divergent user state
    fail the transaction. A repeat never overwrites a later user operation.
    """
    applied=duplicates=0;previous=session.info.get('replaying_user_operations',False)
    session.info['replaying_user_operations']=True
    try:
        last_sequence=0
        for operation in operations:
            if set(operation)!={'sequence','operation_id','entity_kind','entity_id','before_state','after_state','payload_hash','created_at'}:
                raise ValueError('Invalid user-operation envelope')
            if type(operation['sequence']) is not int or operation['sequence']<=last_sequence:
                raise ValueError('User operations must be in strictly increasing sequence order')
            last_sequence=operation['sequence']
            model=ENTITIES.get(operation['entity_kind'])
            if model is None:raise ValueError('Unsupported user-operation entity')
            value=payload(operation['entity_kind'],operation['entity_id'],operation['before_state'],operation['after_state'])
            if digest(value)!=operation['payload_hash']:raise ValueError('User-operation checksum mismatch')
            op_id=UUID(operation['operation_id']);identity=UUID(operation['entity_id'])
            existing=session.scalar(select(UserBusinessOperation).where(UserBusinessOperation.operation_id==op_id))
            if existing:
                if existing.payload_hash!=operation['payload_hash']:raise ValueError('Operation ID reused with different data')
                duplicates+=1;continue
            row=session.get(model,identity,with_for_update=True);current=snapshot(model,row)
            before=operation['before_state'];after=operation['after_state']
            columns={c.name:c for c in model.__table__.columns if c.name not in IGNORED}
            # Older immutable journal checksums remain valid after additive
            # provenance columns. Fill only these known absent defaults for
            # comparison/replay, never rewrite the historical operation.
            addition='source_record' if model is StatusHolding else 'readiness'
            before={addition:{},**before} if before is not None else None
            after={addition:{},**after} if after is not None else None
            for state in [before,after]:
                if state is not None and (set(state)!=set(columns) or state['id']!=str(identity)):
                    raise ValueError('Invalid user-operation state')
            if current!=after:
                if current!=before:raise ValueError('User state diverged; replay cannot overwrite it')
                if after is None:session.delete(row)
                else:
                    if row is None:row=model(id=identity);session.add(row)
                    for name,item in after.items():
                        kind=columns[name].type
                        if item is not None:
                            if isinstance(kind,Uuid):item=UUID(item)
                            elif isinstance(kind,DateTime):item=datetime.fromisoformat(item)
                            elif isinstance(kind,Date):item=date.fromisoformat(item)
                        setattr(row,name,item)
            session.add(UserBusinessOperation(operation_id=op_id,entity_kind=operation['entity_kind'],entity_id=identity,
                before_state=operation['before_state'],after_state=operation['after_state'],payload_hash=operation['payload_hash'],created_at=datetime.fromisoformat(operation['created_at'])))
            session.flush();applied+=1
        return {'applied':applied,'duplicates':duplicates}
    finally:session.info['replaying_user_operations']=previous
