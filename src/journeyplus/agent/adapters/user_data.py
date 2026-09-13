"""User snapshots are read through the user connection, never knowledge access."""
from journeyplus.agent.adapters.transactions import read_session
from uuid import UUID
from sqlalchemy import select
from journeyplus.models import StatusHolding


class UserData:
    def __init__(self,factory):self._factory=factory

    def route_sources(self,mode,refs=()):
        with read_session(self._factory) as session:
            statement=select(StatusHolding.id,StatusHolding.revision,StatusHolding.tier_id,StatusHolding.valid_until,
                             StatusHolding.program_display_name,StatusHolding.tier_display_name,StatusHolding.source_record)
            if refs:
                statement=statement.where(StatusHolding.id.in_([UUID(ref.removeprefix('holding:')) for ref in refs]))
            elif mode!='saved':return []
            rows=list(session.execute(statement.order_by(StatusHolding.id)).mappings())
            result= [{'holding_ref':'holding:'+str(row['id']),'revision':row['revision'],
                     'tier_ref':'tier:'+str(row['tier_id']) if row['tier_id'] else None,
                     'valid_until':row['valid_until'].isoformat() if row['valid_until'] else None,
                     'program_name':row['program_display_name'],'tier_name':row['tier_display_name'],
                     'name_authority':'CATALOG' if row['tier_id'] else 'UNVERIFIED_EXTRACTION',
                     'original_statements':(row['source_record'] or {}).get('original_statements',[]) if not row['tier_id'] else []} for row in rows]
            if mode!='saved':
                found={row['holding_ref'] for row in result}
                result.extend({'holding_ref':ref,'revision':None,'tier_ref':None,'valid_until':None,
                    'program_name':None,'tier_name':None,'code':'STALE_REFERENCE','resolution_state':'INVALID_REFERENCE'}
                    for ref in sorted(set(refs)-found))
            return result
