"""Backfill existing workflow names, preserving IDs, facts and all raw documents.

Dry run by default. --apply requires a new backup path. No schema changes.
Conflicting saved programmes abort the transaction instead of deleting a holding.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, select, update, text
from journeyplus.config import Settings
from journeyplus.membership.identity import (
    canonical_program, canonical_tier, normalize_fact_payload, resolve_identity, directory_version,
)
from journeyplus.article_pipeline.interpretation import _json_signature


def plan(rows):
    changes = []
    events = {str(r['id']): r for r in rows['status_events']}
    for table in ('status_events', 'article_opportunities'):
        for row in rows[table]:
            values = {'program': canonical_program(row['program'])}
            if row['target_status']:
                values['target_status'] = canonical_tier(row['program'], row['target_status'])
            if table == 'article_opportunities':
                facts = normalize_fact_payload(row['facts'], row['program'])
                if facts != row['facts']:
                    values.update(facts=facts, fact_signature=_json_signature(facts))
            changed = {k: v for k, v in values.items() if row[k] != v}
            if changed: changes.append((table, row['id'], changed))
    for row in rows['fact_sets']:
        facts = normalize_fact_payload(row['facts'], events[str(row['event_id'])]['program'])
        if facts != row['facts']: changes.append(('fact_sets', row['id'], {'facts': facts}))
    keys = {}
    for row in rows['status_holdings']:
        identity = resolve_identity(row['program_display_name'], row['tier_display_name'])
        values = {}
        if identity['status'] == 'OK':
            values = {'program_key': identity['program_key'], 'tier_key': identity['tier_key'],
                      'program_display_name': identity['program_name'], 'tier_display_name': identity['tier_name']}
        key = values.get('program_key', row['program_key'])
        if key in keys:
            raise ValueError(f"Holding collision for {key}: {keys[key]} / {row['id']}; no data changed")
        keys[key] = row['id']
        changed = {k: v for k, v in values.items() if row[k] != v}
        if changed: changes.append(('status_holdings', row['id'], changed))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.apply and args.backup is None: parser.error('--apply requires --backup')
    engine = create_engine(Settings.from_env().database_url)
    names = ('status_events', 'fact_sets', 'article_opportunities', 'status_holdings')
    try:
        with engine.begin() as connection:
            tables = {n: Table(n, MetaData(), autoload_with=connection) for n in names}
            if args.apply and connection.dialect.name == 'postgresql':
                connection.execute(text('LOCK TABLE status_events, fact_sets, article_opportunities, status_holdings IN SHARE ROW EXCLUSIVE MODE'))
            rows = {n: [dict(r) for r in connection.execute(select(t)).mappings()] for n, t in tables.items()}
            changes = plan(rows)
            if args.apply:
                args.backup.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive create: never overwrite the only pre-change backup.
                with args.backup.open('x') as output:
                    json.dump({'directory_version': directory_version(), 'tables': rows}, output,
                              ensure_ascii=False, default=str, indent=2)
                args.backup.chmod(0o600)
                for table, identity, values in changes:
                    connection.execute(update(tables[table]).where(tables[table].c.id == identity)
                                       .values(**values, updated_at=datetime.now(timezone.utc)))
            print(json.dumps({'applied': args.apply, 'rows': {n: len(r) for n, r in rows.items()},
                'changed': {n: sum(t == n for t, _, _ in changes) for n in names},
                'changes': [{'table': t, 'id': str(i), 'fields': list(v)} for t, i, v in changes]}, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == '__main__': main()
