from __future__ import annotations

from datetime import date as DateValue, datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator, ConfigDict

from journeyplus.contracts import StrictModel

T = TypeVar("T")
KnownState = Literal["KNOWN", "UNKNOWN", "CONFLICT", "NOT_APPLICABLE"]
Availability = Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN", "CONFLICT"]


class Alternative(StrictModel, Generic[T]):
    value: T
    evidence_ids: list[UUID] = Field(min_length=1)


class FactValue(StrictModel, Generic[T]):
    model_config = ConfigDict(json_schema_extra={"allOf":[
        {"if":{"required":["value"],"properties":{"value":{"not":{"type":"null"}}}},
         "then":{"required":["known_state","evidence_ids"],"properties":{"known_state":{"const":"KNOWN"},"evidence_ids":{"minItems":1}}}}
    ]})
    schema_version: Literal[1] = 1
    known_state: KnownState = "UNKNOWN"
    value: T | None = None
    raw_text: str = ""
    evidence_ids: list[UUID] = Field(default_factory=list)
    alternatives: list[Alternative[T]] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent(self):
        if self.known_state == "KNOWN":
            if self.value is None or not self.evidence_ids:
                raise ValueError("Known facts require a value and evidence")
        elif self.value is not None:
            raise ValueError("Only KNOWN may expose an effective value")
        if self.known_state == "CONFLICT" and len(self.alternatives) < 2:
            raise ValueError("Conflict requires separately evidenced alternatives")
        if self.known_state != "CONFLICT" and self.alternatives:
            raise ValueError("Alternatives require CONFLICT")
        if self.known_state == "NOT_APPLICABLE" and not self.raw_text:
            raise ValueError("Not applicable requires a reason")
        return self


class SourceScope(StrictModel):
    model_config = ConfigDict(json_schema_extra={"allOf":[
        {"if":{"properties":{"kind":{"const":"CATEGORY_RULE"}},"required":["kind"]},
         "then":{"required":["category","rule_text","evidence_ids"],"properties":{"category":{"enum":["AIRLINE","HOTEL","CRUISE","OTHER"]},"rule_text":{"type":"string","minLength":1},"program_id":{"type":"null"},"tier_ids":{"maxItems":0}}}},
        {"if":{"properties":{"kind":{"const":"EXACT_TIERS"}},"required":["kind"]},
         "then":{"required":["program_id","tier_ids","evidence_ids"],"properties":{"program_id":{"type":"string","format":"uuid"},"tier_ids":{"minItems":1},"category":{"type":"null"}}}}
    ]})
    kind: Literal["EXACT_TIERS", "PROGRAM_ANY_TIER", "CATEGORY_RULE", "PUBLIC", "UNKNOWN"] = "UNKNOWN"
    program_id: UUID | None = None
    tier_ids: list[UUID] = Field(default_factory=list)
    category: Literal["AIRLINE", "HOTEL", "CRUISE", "OTHER"] | None = None
    rule_text: str | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def scope_shape(self):
        if self.kind != "UNKNOWN" and not self.evidence_ids:
            raise ValueError("An explicit source scope requires evidence")
        if self.kind == "EXACT_TIERS":
            if not self.program_id or not self.tier_ids or self.category:
                raise ValueError("Exact scope requires a program and tiers")
        elif self.kind == "PROGRAM_ANY_TIER":
            if not self.program_id or self.tier_ids or self.category:
                raise ValueError("Program scope must not imply individual tiers")
        elif self.kind == "CATEGORY_RULE":
            if not self.category or not self.rule_text or self.program_id or self.tier_ids:
                raise ValueError("CATEGORY_RULE requires category and nonempty rule_text, program_id=null, tier_ids=[]")
        elif self.program_id or self.tier_ids or self.category:
            raise ValueError("Public and unknown scopes cannot contain inferred identities")
        return self


class Condition(StrictModel):
    model_config = ConfigDict(json_schema_extra={"allOf":[
        {"if":{"required":["value"],"properties":{"value":{"not":{"type":"null"}}}},
         "then":{"required":["known_state","evidence_ids"],"properties":{"known_state":{"const":"KNOWN"},"evidence_ids":{"minItems":1}}}},
        *[{"if":{"required":["known_state","operator"],"properties":{"known_state":{"const":"KNOWN"},"operator":{"const":operator}}},
           "then":{"properties":{"value":{"type":kind}}}}
          for operator,kind in [("IN","array"),("EQ","string"),("TEXT","string"),("GTE","integer")]],
        {"if":{"required":["known_state","operator"],"properties":{"known_state":{"const":"KNOWN"},"operator":{"const":"GTE"}}},
         "then":{"properties":{"topic":{"const":"MIN_REMAINING_VALIDITY"}}}}
    ]})
    condition_id: str
    topic: Literal["SOURCE_ACQUISITION", "RESIDENCY", "MIN_REMAINING_VALIDITY", "PRIOR_PARTICIPATION", "DOCUMENT_REQUIREMENT", "OTHER"]
    operator: Literal["EQ", "IN", "GTE", "TEXT"]
    value: str | int | list[str] | None = None
    known_state: KnownState = "UNKNOWN"
    raw_text: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    effect: Literal["REQUIRE", "EXCLUDE", "INFORMATIONAL"] = "REQUIRE"
    supersedes_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def typed_operator(self):
        if self.known_state == "KNOWN" and (self.value is None or not self.evidence_ids):
            raise ValueError("Known condition requires value and evidence")
        if self.known_state != "KNOWN" and self.value is not None:
            raise ValueError("Unknown condition cannot have effective value")
        if self.known_state == "KNOWN":
            if self.operator == "GTE" and (type(self.value) is not int or self.topic != "MIN_REMAINING_VALIDITY"):
                raise ValueError("GTE supports remaining validity in days only")
            if self.operator == "IN" and not isinstance(self.value, list):
                raise ValueError("IN requires a list")
            if self.operator in {"EQ", "TEXT"} and not isinstance(self.value, str):
                raise ValueError("EQ/TEXT require text")
        return self


class ConditionSet(StrictModel):
    schema_version: Literal[1] = 1
    items: list[Condition] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({c.condition_id for c in self.items}) != len(self.items):
            raise ValueError("Duplicate condition identity")
        return self


class Temporal(StrictModel):
    precision: Literal["INSTANT", "DATE", "MONTH", "RELATIVE", "UNKNOWN"]
    instant: datetime | None = None
    date: DateValue | None = None
    month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    timezone: str | None = None
    anchor: Literal["APPROVAL", "APPLICATION", "COMPLETION"] | None = None
    offset_days: int | None = None
    raw_text: str = ""
    evidence_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def precision_shape(self):
        values = {"INSTANT": self.instant, "DATE": self.date, "MONTH": self.month, "RELATIVE": self.offset_days}
        active = [k for k, v in values.items() if v is not None]
        if active != ([] if self.precision == "UNKNOWN" else [self.precision]):
            raise ValueError("Temporal precision must match exactly one value")
        if self.instant and self.instant.tzinfo is None:
            raise ValueError("Instant requires timezone")
        if self.precision == "RELATIVE" and self.anchor is None:
            raise ValueError("Relative time needs an anchor")
        return self


class ApplicationWindow(StrictModel):
    start: FactValue[Temporal] = Field(default_factory=FactValue)
    end: FactValue[Temporal] = Field(default_factory=FactValue)


class ChallengeMetric(StrictModel):
    unit: Literal["NIGHTS", "STAYS", "FLIGHTS", "SPEND", "OTHER"]
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    raw_text: str = ""


class ChallengeValue(StrictModel):
    kind: Literal["NONE", "REQUIRED"]
    metrics: list[ChallengeMetric] = Field(default_factory=list)
    window: Temporal | None = None

    @model_validator(mode="after")
    def no_false_none(self):
        if self.kind == "NONE" and (self.metrics or self.window):
            raise ValueError("No challenge cannot contain requirements")
        return self


class ValidityValue(StrictModel):
    kind: Literal["FIXED_END", "DURATION"]
    end: Temporal | None = None
    months: int | None = Field(default=None, gt=0)
    days: int | None = Field(default=None, gt=0)
    anchor: Literal["APPROVAL", "COMPLETION"] | None = None

    @model_validator(mode="after")
    def valid_shape(self):
        if self.kind == "FIXED_END" and (self.end is None or self.months or self.days or self.anchor):
            raise ValueError("Fixed validity needs only an end")
        if self.kind == "DURATION" and (self.end or not self.anchor or (self.months is None) == (self.days is None)):
            raise ValueError("Duration requires one length and anchor")
        return self


class ApplicationLink(StrictModel):
    url: HttpUrl
    role: Literal["APPLICATION", "INFORMATION"] = "APPLICATION"


class ActivityFacts(StrictModel):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1)
    summary: FactValue[str] = Field(default_factory=FactValue)
    conditions: ConditionSet = Field(default_factory=ConditionSet)
    lifecycle: FactValue[Literal["OPEN", "UPCOMING", "CLOSED"]] = Field(default_factory=FactValue)
    application_window: ApplicationWindow = Field(default_factory=ApplicationWindow)
    caveats: list[FactValue[str]] = Field(default_factory=list)


class MappingDraft(StrictModel):
    key: str = Field(min_length=1)
    source_scope: SourceScope
    target_program_id: UUID
    target_tier_id: UUID
    conditions: ConditionSet = Field(default_factory=ConditionSet)
    availability: Availability = "UNKNOWN"
    evidence_ids: list[UUID] = Field(min_length=1)


class PriceDraft(StrictModel):
    model_config = ConfigDict(json_schema_extra={"allOf":[
        {"if":{"properties":{"target_scope":{"const":"ALL_TARGETS"}},"required":["target_scope"]},
         "then":{"properties":{"target_tier_id":{"type":"null"}}},
         "else":{"required":["target_tier_id"],"properties":{"target_tier_id":{"type":"string","format":"uuid"}}}},
        {"if":{"properties":{"mapping_scope":{"const":"ALL_MAPPINGS"}},"required":["mapping_scope"]},
         "then":{"properties":{"mapping_keys":{"maxItems":0}}},
         "else":{"required":["mapping_keys"],"properties":{"mapping_keys":{"minItems":1}}}},
        {"if":{"required":["amount"],"properties":{"amount":{"not":{"type":"null"}}}},
         "then":{"required":["known_state"],"properties":{"known_state":{"const":"KNOWN"}}}}
    ]})
    key: str = Field(min_length=1)
    target_tier_id: UUID | None = None
    target_scope: Literal["EXACT", "ALL_TARGETS"] = "EXACT"
    mapping_scope: Literal["EXPLICIT", "ALL_MAPPINGS"] = "EXPLICIT"
    mapping_keys: list[str] = Field(default_factory=list)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    known_state: KnownState = "UNKNOWN"
    fee_role: Literal["APPLICATION", "CHALLENGE_SPEND", "OTHER"] = "APPLICATION"
    charge_key: str = Field(min_length=1)
    combination: Literal["REQUIRED", "ALTERNATIVE", "CONDITIONAL"] = "REQUIRED"
    alternative_group: str | None = None
    conditions: ConditionSet = Field(default_factory=ConditionSet)
    raw_text: str = Field(min_length=1)
    availability: Availability = "UNKNOWN"
    evidence_ids: list[UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def price_scope(self):
        if (self.target_scope == "EXACT") != (self.target_tier_id is not None):
            raise ValueError("target_scope EXACT requires target_tier_id; ALL_TARGETS requires target_tier_id=null")
        if (self.mapping_scope == "EXPLICIT") != bool(self.mapping_keys):
            raise ValueError("Explicit price scope requires mapping keys")
        if self.known_state == "KNOWN" and (self.amount is None or (self.amount != 0 and self.currency is None)):
            raise ValueError("Known nonzero price needs amount and currency")
        if self.known_state != "KNOWN" and self.amount is not None:
            raise ValueError("Unknown/conflicting price cannot expose an effective amount")
        if self.availability == "UNAVAILABLE" and self.amount is not None:
            raise ValueError("Unavailable price is not payable")
        if (self.combination == "ALTERNATIVE") != bool(self.alternative_group):
            raise ValueError("Alternative fees require a group")
        return self


class OptionDraft(StrictModel):
    logical_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    method: Literal["MATCH", "CHALLENGE", "OTHER"]
    source_scope: SourceScope
    conditions: ConditionSet = Field(default_factory=ConditionSet)
    challenge: FactValue[ChallengeValue] = Field(default_factory=FactValue)
    application_window: ApplicationWindow = Field(default_factory=ApplicationWindow)
    status_validity: FactValue[ValidityValue] = Field(default_factory=FactValue)
    action_link: FactValue[ApplicationLink] = Field(default_factory=FactValue)
    availability: Availability = "UNKNOWN"
    mappings: list[MappingDraft] = Field(default_factory=list)
    prices: list[PriceDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def associations(self):
        mappings = {m.key: m for m in self.mappings}
        if len(mappings) != len(self.mappings) or len({p.key for p in self.prices}) != len(self.prices):
            raise ValueError("Duplicate mapping or price key")
        for price in self.prices:
            if not set(price.mapping_keys) <= mappings.keys():
                raise ValueError("Price references a mapping outside this option")
            targets = {mappings[k].target_tier_id for k in price.mapping_keys} if price.mapping_keys else {m.target_tier_id for m in self.mappings}
            if price.target_scope == "EXACT" and price.target_tier_id not in targets:
                raise ValueError(f"Price target is not mapped by this option: price={price.key}, mapping_keys={price.mapping_keys}. A conditional buy-up to another tier needs its own evidenced mapping to that target; do not attach it to a mapping ending at the lower tier.")
            if price.mapping_keys and price.target_scope == "EXACT" and targets != {price.target_tier_id}:
                raise ValueError("Price target disagrees with its mappings")
        return self


class DocumentBinding(StrictModel):
    document_version_id: UUID
    role: Literal["OFFICIAL_PRIMARY", "OFFICIAL_SUPPORT", "THIRD_PARTY"]
    section_ids: list[UUID] = Field(default_factory=list)


class ValidationNote(StrictModel):
    code:Literal['PRICE_EVIDENCE_WITHHELD','MAPPING_TABLE_INCOMPLETE']='PRICE_EVIDENCE_WITHHELD'
    option_key:str|None=None
    price_key:str|None=None
    group_ref:str|None=None
    mapping_count:int=Field(default=0,ge=0)
    evidence_ids:list[UUID]=Field(min_length=1)


class KnowledgeDraft(StrictModel):
    schema_version: Literal[1] = 1
    activity_id: UUID
    base_version_id: UUID | None = None
    extraction_key: str = Field(min_length=1)
    facts: ActivityFacts
    documents: list[DocumentBinding] = Field(min_length=1)
    options: list[OptionDraft] = Field(default_factory=list)
    validation_notes:list[ValidationNote]=Field(default_factory=list)

    @model_validator(mode="after")
    def unique_options(self):
        if len({o.logical_key for o in self.options}) != len(self.options):
            raise ValueError("Duplicate application method identity")
        return self
