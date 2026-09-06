"""Ground explicit region / tier / fee tables, preserving merged-cell scope."""
import re
from decimal import Decimal


def key(value):
    return ' '.join(value.casefold().split())


def regional_fee_rows(quote):
    active=False;region=None;rows=[]
    for line in quote.splitlines():
        if '|' not in line:
            if line.strip():active=False;region=None
            continue
        cells=[re.sub(r'[*_`]','',v).strip() for v in line.strip().strip('|').split('|')]
        if len(cells)!=3:active=False;region=None;continue
        if [key(v) for v in cells[:2]]==['country/region','status tier'] and key(cells[2]).startswith('application fee'):
            active=True;region=None;continue
        if not active:continue
        if all(re.fullmatch(r'[- :]*',v) for v in cells):continue
        if cells[0]:region=cells[0]
        match=re.fullmatch(r'(USD|EUR|GBP)\s+([0-9]+(?:\.[0-9]+)?)(?:\s+(.*))?',cells[2])
        if not region or not cells[1] or not match:
            active=False;region=None;continue
        rows.append({'region':region,'tier':cells[1],'currency':match[1],
                     'amount':Decimal(match[2]),'qualifier':match[3] or ''})
    return rows


def region_scope_matches(row,option,price):
    required=[];excluded=[]
    for group in (option.get('conditions',{}),price.get('conditions',{})):
        for condition in group.get('items',[]):
            if condition.get('topic')!='RESIDENCY' or condition.get('known_state')!='KNOWN':continue
            value=condition.get('value');operator=condition.get('operator')
            values=[value] if operator=='EQ' and isinstance(value,str) else value if operator=='IN' and isinstance(value,list) else []
            values={key(v) for v in values}
            if condition.get('effect')=='REQUIRE':required.append(values)
            elif condition.get('effect')=='EXCLUDE':excluded.extend(values)
    countries={key(v.strip()) for v in row['region'].split(',')}
    if not required:return False
    allowed=set.intersection(*required)
    if not allowed or not allowed<=countries:return False
    qualifier=row['qualifier']
    if qualifier:
        match=re.fullmatch(r'Not Available for (.+)',qualifier,re.I)
        if not match or key(match[1]) not in excluded:return False
    return True
