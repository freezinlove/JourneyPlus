"""Conservative page adapter; live layout remains unverified while permission is off."""
import re
from urllib.parse import urljoin, urlsplit
from datetime import date
from selectolax.parser import HTMLParser
from journeyplus.agent.research_http import permitted_url
from journeyplus.agent.step_observations import ReportObservation
from journeyplus.knowledge.publication import canonical_key


def list_report_urls(html, base_url):
    tree=HTMLParser(html);heading=tree.css_first('#report-list-to')
    if heading is None or heading.parent is None:raise ValueError('REPORT_LIST_NOT_FOUND')
    urls=[]
    for link in heading.parent.css('a[href]'):
        url=urljoin(base_url,link.attributes['href'])
        if not urlsplit(url).path.startswith('/report/'):continue
        url=permitted_url(url)
        canonical=url.split('?')[0].split('#')[0].rstrip('/')
        if canonical not in urls:urls.append(canonical)
    return urls


def parse_report_detail(html,url,identities):
    tree=HTMLParser(html)
    article=tree.css_first('article')
    if article is None:raise ValueError('REPORT_DETAIL_NOT_FOUND')
    heading=article.css_first('h1');body=article.css_first('.instructions')
    if heading is None or body is None:raise ValueError('REPORT_DETAIL_FIELDS_MISSING')
    title=' '.join(heading.text(separator=' ').split())
    direction=re.split(r'\s+to\s+',re.sub(r'^From\s+','',title,flags=re.I),maxsplit=1,flags=re.I)
    if len(direction)!=2:raise ValueError('REPORT_DIRECTION_MISSING')
    text=' '.join(body.text(separator=' ').split())
    if not text:raise ValueError('REPORT_BODY_MISSING')
    # Exact curated identity lookup; unmatched labels remain explicitly unknown.
    left=identities.get(canonical_key(direction[0]),{})
    right=identities.get(canonical_key(direction[1]),{})
    denied=bool(re.search(r'\b(?:was denied|was rejected|request denied|application denied)\b',text,re.I))
    challenge=bool(re.search(r'\b(?:offered a challenge|required to (?:fly|stay)|must (?:fly|stay)|challenge required)\b',text,re.I))
    matched=bool(re.search(r'\b(?:status was matched|match was approved|application was approved)\b',text,re.I))
    outcome='UNKNOWN' if denied and (matched or challenge) else 'DENIED' if denied else 'CHALLENGE' if challenge else 'DIRECT_MATCH' if matched else 'UNKNOWN'
    if len(text)>600:outcome='UNKNOWN'  # Do not assert an outcome whose full context is not retained.
    label=article.css_first('.result-box span');reported=label.text(strip=True).upper() if label else None
    dates={};notes=[]
    for node in article.css('dt'):
        name=node.text(strip=True).casefold();value=node.next
        if name not in {'submitted','application date'} or value is None or value.tag!='dd':continue
        raw=value.text(strip=True)
        try:parsed=date.fromisoformat(raw)
        except ValueError:continue
        dates['submitted_at' if name=='submitted' else 'application_at']={'precision':'DATE','date':parsed,'raw_text':raw}
    if 'application_at' not in dates:notes.append('申请日期未知；提交日期不替代申请日期。')
    notes.append('未核实活动期次及来源取得方式。')
    return ReportObservation(report_ref=urlsplit(url).path.rstrip('/').split('/')[-1],url=url,
        original_from=direction[0],original_to=direction[1],
        from_program_ref=left.get('program_ref'),from_tier_ref=left.get('tier_ref'),
        to_program_ref=right.get('program_ref'),to_tier_ref=right.get('tier_ref'),
        reported_label=reported if reported in {'MATCH','CHALLENGE','DENY','OTHER'} else None,
        normalized_outcome=outcome,method='CHALLENGE' if challenge else None,
        evidence_excerpt=text[:600],notes=notes,**dates)


def list_report_candidates(html,base_url):
    tree=HTMLParser(html);heading=tree.css_first('#report-list-to')
    if heading is None or heading.parent is None:raise ValueError('REPORT_LIST_NOT_FOUND')
    candidates=[]
    for item in heading.parent.css('div.d-flex.mb-3'):
        title=item.css_first('h6');stamp=item.css_first('time[datetime]')
        for link in item.css('a[href]'):
            url=urljoin(base_url,link.attributes['href'])
            if not urlsplit(url).path.startswith('/report/'):continue
            candidates.append({'url':permitted_url(url).split('?')[0].split('#')[0].rstrip('/'),
                'direction':' '.join(title.text(separator=' ').split()) if title else '',
                'submitted':stamp.attributes['datetime'] if stamp else None})
    represented={c['url'] for c in candidates}
    candidates.extend({'url':url,'direction':'','submitted':None} for url in list_report_urls(html,base_url) if url not in represented)
    return candidates


def select_report_candidates(candidates,target,identities,today):
    from datetime import datetime
    from journeyplus.agent.step_observations import months_ago
    selected={}
    for item in candidates:
        parts=re.split(r'\s+to\s+',re.sub(r'^From\s+','',item['direction'],flags=re.I),maxsplit=1,flags=re.I)
        source=identities.get(canonical_key(parts[0]),{}) if len(parts)==2 else {}
        dest=identities.get(canonical_key(parts[1]),{}) if len(parts)==2 else {}
        expected=[(source.get('program_ref'),target.from_program_ref),(dest.get('program_ref'),target.to_program_ref)]
        if any(actual is not None and wanted is not None and actual!=wanted for actual,wanted in expected):continue
        relevance=sum(actual is None for actual,wanted in expected if wanted is not None)
        try:submitted=datetime.fromisoformat(item['submitted'].replace('Z','+00:00')).date()
        except (TypeError,ValueError,AttributeError):submitted=None
        if submitted and submitted>today:continue
        recency=0 if submitted and submitted>=months_ago(today,12) else 1 if submitted and submitted>=months_ago(today,24) else 2 if submitted is None else 3
        rank=(relevance,recency,-submitted.toordinal() if submitted else 0,item['url'])
        if item['url'] not in selected or rank<selected[item['url']][0]:selected[item['url']]=(rank,item)
    return [item for _,item in sorted(selected.values(),key=lambda value:value[0])]
