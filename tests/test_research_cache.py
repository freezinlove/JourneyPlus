from datetime import datetime,UTC,timedelta
from journeyplus.agent.research_cache import save_observations,cached_observations
from tests.test_step_observations import target,report


def test_context_change_reuses_reports_but_rechecks_comparability():
    now=datetime(2026,9,6,tzinfo=UTC);state={};t=target()
    save_observations(state,t,[report()],now=now,workspace_expires_at=now+timedelta(hours=24),coverage={'complete':True})
    first=cached_observations(state,t,now=now)
    assert first['observations'][0]['comparability']['state']=='EXACT'
    changed=t.model_copy(update={'context':{'source_acquisition':'MATCHED'},'step_ref':'new-render-ref'})
    second=cached_observations(state,changed,now=now)
    assert second['cache_hit'] and second['incomparable_count']==1
    assert first['observations'][0]['comparability']['state']=='EXACT'
    assert cached_observations(state,t.model_copy(update={'activity_version_ref':'new-version'}),now=now) is None


def test_cache_never_outlives_workspace_and_does_not_store_html():
    now=datetime(2026,9,6,tzinfo=UTC);state={};expires=now+timedelta(minutes=10)
    save_observations(state,target(),[report()],now=now,workspace_expires_at=expires,coverage={})
    result=cached_observations(state,target(),now=now)
    assert result['expires_at']==expires.isoformat()
    assert 'raw_html' not in str(state)
    assert cached_observations(state,target(),now=expires) is None
    assert not state['research']['step_records_v1']


def test_metadata_cannot_smuggle_raw_page_into_workspace():
    import pytest
    from pydantic import ValidationError
    now=datetime(2026,9,6,tzinfo=UTC);state={}
    with pytest.raises(ValidationError):
        save_observations(state,target(),[report()],now=now,workspace_expires_at=now+timedelta(hours=1),coverage={'raw_html':'private page'})
    assert state=={}
