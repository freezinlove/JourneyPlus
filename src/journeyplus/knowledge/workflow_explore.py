"""Page projections of AIWorkflow knowledge, without an Agent runtime."""
from sqlalchemy import select
from journeyplus.memberships_validity import membership_date

from journeyplus.models import StatusHolding, StatusEvent, FactSetRecord, ArticleOpportunityRecord
from .text import canonical
from .workflow_knowledge import catalog, identity_id
from .workflow_routes import WorkflowRouteService


def search_catalog(session, text, *, limit=20):
    programs, tiers, aliases = catalog(session)
    tokens = canonical(text).split()
    matches = []
    for program in programs:
        names = [program.display_name, program.canonical_key]
        names.extend(a.normalized_alias for a in aliases if a.program_id == program.id)
        program_tiers = [t for t in tiers if t.program_id == program.id]
        selected = [t for t in program_tiers if all(token in canonical(
            ' '.join([*names, t.display_name, t.canonical_key])) for token in tokens)]
        if selected:
            matches.append({'id': str(program.id), 'name': program.display_name,
                'category': program.category, 'alliance': program.alliance,
                'tiers': [{'id': str(t.id), 'name': t.display_name} for t in selected]})
    return {'programs': matches[:limit], 'has_more': len(matches) > limit}


def explore(session, query):
    if query.max_amount is not None and not query.currency:
        raise ValueError('预算上限需要币种')
    if query.free_only and query.max_amount is not None:
        raise ValueError('免费与金额上限不能同时指定')
    programs, tiers, _ = catalog(session)
    tier_ids = {t.id for t in tiers}
    if any(t not in tier_ids for t in query.starting_tier_ids):
        raise ValueError('所选起点已不在当前目录，请重新查找会籍等级。')
    if query.target_program_id and query.target_program_id not in {p.id for p in programs}:
        raise ValueError('目标项目已不在当前目录，请重新选择。')
    if query.target_tier_id and query.target_tier_id not in tier_ids:
        raise ValueError('目标等级已不在当前目录，请重新选择。')
    roots = set(query.starting_tier_ids)
    use_saved = query.use_saved_holdings if query.use_saved_holdings is not None else not roots
    unresolved = 0
    if use_saved:
        # Select original columns only: the chosen schema has no program/tier FKs.
        rows = session.execute(select(StatusHolding.program_key, StatusHolding.tier_key).where(
            (StatusHolding.valid_until.is_(None)) |
            (StatusHolding.valid_until >= membership_date())))
        for program_key, tier_key in rows:
            tier = identity_id('tier', program_key + '::' + tier_key)
            if tier in tier_ids:
                roots.add(tier)
            else:
                unresolved += 1
    prepared = query.model_copy(update={'starting_tier_ids': sorted(roots, key=str), 'use_saved_holdings': False})
    result = WorkflowRouteService(session).query(prepared)
    coverage = result['coverage']
    coverage.update(unresolved_holding_count=unresolved, search_performed=bool(roots))
    if unresolved:
        coverage.update(search_complete=False, stopped_reason=coverage['stopped_reason'] or 'CATALOG_METADATA_GAPS')
    if not roots:
        coverage['message'] = ('没有可用于计算的已保存会籍，请查找并选择本次起点。' if use_saved else
            '当前匹配图需要具体的起点会籍，暂不能完整查询无需会籍的公开申请机会。')
    # Like Agent, show matching and uncertain candidates, never known violations
    # as results satisfying the selected free/budget/challenge constraints.
    routes = [r for r in result['server_routes'].values() if r['classification'] in result['presentation_classes']]
    coverage['filtered_route_count'] = len(result['server_routes']) - len(routes)
    step_refs = {ref for r in routes for ref in r['step_refs']}
    return {'data_model': 'aiworkflow',
        'routes': [{k: v for k, v in r.items() if k not in {'fact_refs', 'selection_reasons'}} for r in routes],
        'steps': {ref: result['server_steps'][ref] for ref in step_refs},
        'snapshot': result['snapshot'], 'coverage': coverage}


def opportunity_reference(session, identity):
    """Resolve existing links by their original IDs, keeping the selected version."""
    fact = session.get(FactSetRecord, identity)
    event = session.get(StatusEvent, fact.event_id if fact else identity)
    article = session.get(ArticleOpportunityRecord, identity) if not event else None
    if event:
        activity, version = event.id, fact.id if fact else event.current_fact_set_id
    elif article:
        activity, version = article.id, article.analysis_id
    else:
        return {'status': 'NOT_FOUND', 'message': '活动不存在。'}
    if not version:
        return {'status': 'NOT_PUBLISHED', 'message': '此活动尚无可读取的事实版本。'}
    return {'status': 'RESOLVED', 'activity_ref': str(activity), 'version_ref': str(version),
        'message': '已按活动标识定位到对应版本资料。'}
