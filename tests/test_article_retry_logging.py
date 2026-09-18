import json
from types import SimpleNamespace

import httpx

from journeyplus.article_pipeline.interpretation import ArticleInterpreter
from tests.test_article_pipeline_v2 import V2Provider


def materials():
    return (
        SimpleNamespace(canonical_url='https://loyaltylobby.com/test/?token=PRIVATE_TOKEN#secret',
                        normalized_body='Example Air offers a direct status match to Gold. '
                        'Apply at https://example-air.test/apply PRIVATE_BODY'),
        SimpleNamespace(title='Example Air offer', published_at=None),
    )


def records(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name.endswith('article_pipeline.interpretation')]


def test_failed_validation_and_recovery_are_correlated(caplog):
    class Retry(V2Provider):
        def generate_structured(self, **kwargs):
            result = super().generate_structured(**kwargs)
            if len(self.calls) == 1:
                result.opportunities[0].title = None
            return result
    provider = Retry()
    result, _ = ArticleInterpreter(None, provider).render(*materials())
    assert result is not None and len(provider.calls) == 2
    events = records(caplog)
    assert [e['outcome'] for e in events] == ['retrying', 'recovered']
    assert [e['attempt'] for e in events] == [1, 2]
    assert len({e['invocation_id'] for e in events}) == 1
    assert events[0]['stage'] == 'fact_validation'
    assert 'title' in events[0]['reason']
    assert events[0]['article_url'] == 'https://loyaltylobby.com/test/'
    assert events[0]['elapsed_ms'] >= 0
    assert 'PRIVATE' not in caplog.text


def test_schema_error_records_field_without_raw_input(caplog):
    class Invalid(V2Provider):
        def generate_structured(self, **kwargs):
            return kwargs['output_model'].model_validate({'label': 'PRIVATE_INVALID_VALUE'})
    result, _ = ArticleInterpreter(None, Invalid(), max_attempts=1).render(*materials())
    assert result is None
    event = records(caplog)[0]
    assert event['outcome'] == 'exhausted'
    assert event['stage'] == 'schema_validation'
    assert any(e['location'] == ['label'] for e in event['reason'])
    assert 'PRIVATE' not in caplog.text
    assert 'input' not in event['reason'][0]


def test_provider_http_failure_logs_status_not_response_or_credentials(caplog):
    class Failure(V2Provider):
        def generate_structured(self, **kwargs):
            request = httpx.Request('POST', 'https://api.test/?key=PRIVATE_KEY')
            raise httpx.HTTPStatusError('PRIVATE_RESPONSE Bearer PRIVATE_TOKEN',
                request=request, response=httpx.Response(429, request=request))
    result, _ = ArticleInterpreter(None, Failure(), max_attempts=2).render(*materials())
    assert result is None
    events = records(caplog)
    assert [e['outcome'] for e in events] == ['retrying', 'exhausted']
    assert all(e['http_status'] == 429 for e in events)
    assert 'PRIVATE' not in caplog.text


def test_first_attempt_success_does_not_emit_retry_warning(caplog):
    result, _ = ArticleInterpreter(None, V2Provider()).render(*materials())
    assert result is not None
    assert records(caplog) == []
