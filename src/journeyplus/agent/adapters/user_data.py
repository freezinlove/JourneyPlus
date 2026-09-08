"""User snapshots are read through the user connection, never knowledge access."""
from journeyplus.agent.adapters.transactions import read_session
from uuid import UUID
from sqlalchemy import select
from journeyplus.models import StatusHolding, now_utc


class UserData:
    def __init__(self,factory):self._factory=factory

    def route_sources(self,mode,refs=()):
        with read_session(self._factory) as session:
            statement=select(StatusHolding.id,StatusHolding.revision,StatusHolding.tier_id,StatusHolding.valid_until,
                             StatusHolding.program_display_name,StatusHolding.tier_display_name)
            if mode=='saved':
                statement=statement.where((StatusHolding.valid_until.is_(None))|
                                           (StatusHolding.valid_until>=now_utc().date()))
            elif refs:
                statement=statement.where(StatusHolding.id.in_([UUID(ref.removeprefix('holding:')) for ref in refs]))
            else:return []
            rows=list(session.execute(statement.order_by(StatusHolding.id)).mappings())
            if mode!='saved' and len(rows)!=len(set(refs)):raise LookupError('Holding does not exist')
            return [{'holding_ref':'holding:'+str(row['id']),'revision':row['revision'],
                     'tier_ref':'tier:'+str(row['tier_id']) if row['tier_id'] else None,
                     'valid_until':row['valid_until'].isoformat() if row['valid_until'] else None,
                     'program_name':row['program_display_name'],'tier_name':row['tier_display_name']} for row in rows]
