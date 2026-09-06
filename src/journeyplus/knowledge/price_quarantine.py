"""Withhold unproven effective prices after bounded extraction repair.

No source/target alias is inferred. Unknown placeholders retain their charge and
scope so another valid fee cannot make a partial total look complete.
"""
from journeyplus.knowledge.contracts import KnowledgeDraft,PriceDraft,ValidationNote
from journeyplus.knowledge.models import EvidenceReference

PRICE_ERRORS=(
    'Known price raw_text must be an exact supporting source excerpt',
    'Multi-target price excerpt does not identify its target tier',
    'Price amount disagrees with explicit target association',
    'Regional price does not match target, currency, region or exclusion',
    'Universal nonzero fee lacks explicit all-target evidence',
    'Known amount is absent from its source evidence',
    'Known currency is absent from its source evidence',
    'Zero fee lacks explicit free application evidence',
)


def quarantine_unproven_prices(publication,draft):
    original=draft.model_dump(mode='json');base=draft.model_dump(mode='json')
    for option in base['options']:option['prices']=[]
    # Mapping, category, conditions, source scope and all other facts must pass.
    publication.validate(KnowledgeDraft.model_validate(base))
    result=draft.model_copy(deep=True);notes=[]
    for index,option in enumerate(original['options']):
        for price_index,price in enumerate(option['prices']):
            if price['known_state']!='KNOWN':continue
            candidate=KnowledgeDraft.model_validate(base)
            candidate.options[index].prices=[PriceDraft.model_validate(price)]
            try:publication.validate(candidate)
            except ValueError as exc:
                if not str(exc).startswith(PRICE_ERRORS):raise
                evidence=[publication.session.get(EvidenceReference,identity) for identity in candidate.options[index].prices[0].evidence_ids]
                # validate() above already checked source binding/section scope.
                raw='\n'.join(dict.fromkeys(item.quote for item in evidence))
                unknown={**price,'known_state':'UNKNOWN','amount':None,'currency':None,'availability':'UNKNOWN','raw_text':raw}
                result.options[index].prices[price_index]=PriceDraft.model_validate(unknown)
                notes.append(ValidationNote(option_key=option['logical_key'],price_key=price['key'],evidence_ids=price['evidence_ids']))
    if not notes:raise ValueError('No eligible price evidence failure to quarantine')
    result.validation_notes.extend(notes)
    publication.validate(result)
    return result
