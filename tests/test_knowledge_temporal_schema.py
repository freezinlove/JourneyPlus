"""Model-facing temporal schema rejects the shapes that broke real backfill."""
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from journeyplus.knowledge.contracts import Temporal

@pytest.mark.parametrize('value,valid',[
    ({'precision':'RELATIVE','raw_text':'until further notice'},False),
    ({'precision':'RELATIVE','offset_days':30},False),
    ({'precision':'RELATIVE','offset_days':30,'anchor':'APPROVAL'},True),
    ({'precision':'DATE','date':'2026-09-09','offset_days':30},False),
    ({'precision':'DATE','date':'2026-09-09'},True),
    ({'precision':'UNKNOWN','raw_text':'until further notice'},True),
    ({'precision':'UNKNOWN','offset_days':0},False),
])
def test_temporal_public_schema_matches_runtime(value,valid):
    assert Draft202012Validator(Temporal.model_json_schema()).is_valid(value)==valid
    if valid:Temporal.model_validate(value)
    else:
        with pytest.raises(ValidationError):Temporal.model_validate(value)
