"""Exact, reviewed spelling equivalence for route nodes; never rank equivalence.

Historical catalogue IDs remain intact. These keys join only the same named
programme/tier, not different tiers with a shared alliance or similar rank.
"""
import re
from sqlalchemy import select
from journeyplus.knowledge.models import MembershipAlias


# Reviewed against the target heading and programme title of this official FAQ.
# Do not generalize this into unordered-word or fuzzy programme matching.
REVIEWED_PROGRAM_SPELLINGS = {
    'lotusmiles (vietnam airlines)': 'vietnam airlines lotusmiles',
    'vietnam airlines lotusmiles': 'vietnam airlines lotusmiles',
}
REVIEWED_IDENTITY_SOURCES = ['https://vietnamairlines.statusmatch.com/faq']


def key(value):
    return ' '.join(value.casefold().split())


def program_key(program):
    return REVIEWED_PROGRAM_SPELLINGS.get(key(program.display_name), key(program.display_name))


def tier_label(program, label):
    label=key(label)
    names={key(program.display_name), program_key(program)}
    names.update(name for name,canonical in REVIEWED_PROGRAM_SPELLINGS.items() if canonical==program_key(program))
    for name in sorted(names,key=len,reverse=True):
        if label.startswith(name+' '):
            label=label[len(name)+1:];break
    return re.sub(r'\s+status$','',label)


def route_identities(session, programs, tiers):
    labels={identity:{tier_label(programs[tier.program_id],tier.display_name)} for identity,tier in tiers.items()}
    # Only parser-proven target headers create equivalence. Ordinary aliases may
    # be ambiguous and must never collapse graph nodes.
    for alias in session.scalars(select(MembershipAlias).where(MembershipAlias.origin=='OFFICIAL_TABLE_TARGET_LABEL')):
        if alias.tier_id in labels:
            labels[alias.tier_id].add(tier_label(programs[alias.program_id],alias.normalized_alias))
    parent={identity:identity for identity in tiers}
    def root(identity):
        while parent[identity]!=identity:
            parent[identity]=parent[parent[identity]];identity=parent[identity]
        return identity
    by_label={}
    for identity in sorted(tiers,key=str):
        scope=program_key(programs[tiers[identity].program_id])
        for label in labels[identity]:
            token=(scope,label)
            if token in by_label:
                a,b=root(identity),root(by_label[token])
                parent[max(a,b,key=str)]=min(a,b,key=str)
            else:by_label[token]=identity
    canonical={identity:root(identity) for identity in tiers}
    metadata={}
    for program in programs.values():
        group=[p for p in programs.values() if program_key(p)==program_key(program)]
        categories={p.category for p in group if p.category!='OTHER'}
        alliances={p.alliance for p in group if p.alliance}
        metadata[program.id]={'category':next(iter(categories)) if len(categories)==1 else 'OTHER',
                              'alliance':next(iter(alliances)) if len(alliances)==1 else None}
    return canonical, metadata
