"""Republish only Kenya's equivalent root-link spelling; preserve old versions."""
import argparse
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from journeyplus.config import Settings
from journeyplus.contracts import FactSet
from journeyplus.facts.service import _normalize_statusmatch_action_links
from journeyplus.models import StatusEvent, StatusMatchWatch, FactSetRecord, BriefRecord, StatusMatchChangeSet, DocumentVersion
from journeyplus.statusmatch.project_workflow import StatusMatchProjectWorkflow
from journeyplus.statusmatch.briefs import save_official_brief
from journeyplus.statusmatch.contracts import StatusMatchProjectIdentity


def repair(apply=False):
    with Session(create_engine(Settings.from_env().database_url)) as s:
        watch = s.scalar(select(StatusMatchWatch).where(StatusMatchWatch.host == 'kenya-airways.statusmatch.com').with_for_update())
        event = s.get(StatusEvent, watch.current_event_id)
        old = s.get(FactSetRecord, event.current_fact_set_id)
        brief = s.get(BriefRecord, event.current_brief_id)
        facts = FactSet.model_validate(old.facts)
        corrected = _normalize_statusmatch_action_links(facts, {'https://kenya-airways.statusmatch.com/'})
        if facts == corrected:
            print('Already normalized'); return
        workflow = StatusMatchProjectWorkflow(s, None)
        snapshot = s.scalar(select(StatusMatchChangeSet).where(StatusMatchChangeSet.to_fact_set_id == old.id).order_by(StatusMatchChangeSet.created_at.desc()))
        assert snapshot is not None
        current, _ = workflow._persist_fact_set(event=event, fact_set=corrected, current_record=old)
        workflow._persist_change_set(event=event, previous=old, current=current,
            activity=s.get(DocumentVersion, snapshot.activity_document_version_id),
            faq=s.get(DocumentVersion, snapshot.faq_document_version_id),
            terms=s.get(DocumentVersion, snapshot.terms_document_version_id))
        save_official_brief(s, current, StatusMatchProjectIdentity(program=event.program,
            title=brief.content['title'], summary=brief.content['summary'], target_status=event.target_status))
        print({'previous':str(old.id), 'current':str(current.id), 'version':current.version,
               'action_link':corrected.action_link.value, 'applied':apply})
        if apply: s.commit()
        else: s.rollback()

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    repair(parser.parse_args().apply)
