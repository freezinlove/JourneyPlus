"""Republish two affected activities from stored official snapshots, without model calls.

Creates new FactSet/brief/audit versions. Existing source snapshots and old facts remain.
Run with --apply after reviewing the dry-run summary.
"""
import argparse
import json
from copy import deepcopy
from uuid import uuid4
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from journeyplus.config import Settings
from journeyplus.models import AnalysisRun, FactSetRecord, StatusEvent, StatusMatchWatch
from journeyplus.statusmatch.contracts import StatusMatchProjectExtraction
from journeyplus.statusmatch.project_workflow import StatusMatchProjectWorkflow, PROJECT_PROMPT_VERSION

HOSTS = ("flyingblue.statusmatch.com", "philippineairlines.statusmatch.com")

def repair(apply=False):
    engine = create_engine(Settings.from_env().database_url)
    with Session(engine) as session:
        reports = []
        for host in HOSTS:
            watch = session.scalar(select(StatusMatchWatch).where(StatusMatchWatch.host == host).with_for_update())
            event = session.get(StatusEvent, watch.current_event_id)
            previous = session.get(FactSetRecord, event.current_fact_set_id)
            source = next(r for r in session.scalars(select(AnalysisRun).where(
                AnalysisRun.event_id == event.id).order_by(AnalysisRun.created_at.desc()))
                if (r.result or {}).get("extraction"))
            extraction_data = deepcopy(source.result["extraction"])
            if host == HOSTS[0]:
                # The raw table supplies amounts; remove the misleading old global summary.
                extraction_data["cost"] = {"value": "按地区和目标等级收取申请费，具体金额见地区价格表。"}
            extraction = StatusMatchProjectExtraction.model_validate(extraction_data)
            audit = AnalysisRun(
                idempotency_key=f"authoritative-table-repair:{uuid4()}", event_id=event.id,
                document_version_id=source.document_version_id, stage=source.stage,
                status="RUNNING", input_version=str(previous.id), provider="deterministic-repair",
                model="none", model_config_version="table-authority-v1",
                prompt_version=PROJECT_PROMPT_VERSION, schema_version=source.schema_version)
            session.add(audit)
            session.flush()
            result = StatusMatchProjectWorkflow(session, None,
                extraction_override=(extraction, 0, audit.id)).process(watch)
            current = session.get(FactSetRecord, event.current_fact_set_id)
            prices = [p for route in current.facts["application_routes"] for p in route["prices"]]
            assert any(p["amount"] is not None for p in prices), host
            if host == HOSTS[1]:
                assert any("Senator" in m["source_tiers"] and "Premier Elite" in m["target_tier"]
                           for m in current.facts["status_mappings"])
            reports.append({"host": host, "previous": str(previous.id), "current": str(current.id),
                "version": current.version, "mapping_count": result.mapping_count,
                "numeric_prices": sum(p["amount"] is not None for p in prices),
                "applied": apply})
        if apply:
            session.commit()
        else:
            session.rollback()
        print(json.dumps(reports, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    repair(parser.parse_args().apply)
