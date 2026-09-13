"""Conservative page adapter; company/report layouts verified on 2026-09-07."""
import re
from urllib.parse import urljoin, urlsplit
from datetime import date
from selectolax.parser import HTMLParser
from journeyplus.agent.research_http import permitted_url
from journeyplus.contracts import StrictModel
from journeyplus.knowledge.publication import canonical_key


class ReportDetail(StrictModel):
    """Observed report fields, without a second outcome classifier."""
    report_ref: str
    url: str
    original_from: str | None = None
    original_to: str | None = None
    reported_label: str | None = None
    submitted_at: str | None = None
    application_at: str | None = None
    text: str


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


def parse_report_detail(html,url):
    from journeyplus.agent.services.statusmatcher_content import cleaned_page
    cleaned=cleaned_page(html,url)
    tree=cleaned[0] if cleaned is not None else HTMLParser(html)
    article=tree.css_first('article')
    live=article is None
    article=article or tree.body
    if article is None:raise ValueError('REPORT_DETAIL_NOT_FOUND')
    heading=article.css_first('h1') if not live else article.css_first('.instructions').parent.css_first('h4') if article.css_first('.instructions') else None
    body=article.css_first('.instructions')
    if heading is None or body is None:raise ValueError('REPORT_DETAIL_FIELDS_MISSING')
    title=' '.join(heading.text(separator=' ').split())
    direction=re.split(r'\s+to\s+',re.sub(r'^From\s+','',title,flags=re.I),maxsplit=1,flags=re.I)
    if len(direction)!=2:raise ValueError('REPORT_DIRECTION_MISSING')
    text=' '.join(body.text(separator=' ').split())
    if not text:raise ValueError('REPORT_BODY_MISSING')
    label=article.css_first('.result-box span');reported=label.text(strip=True).upper() if label else None
    if live:
        header=article.css_first('h3')
        if header and 'Report:' in header.text():reported=header.text().split('Report:',1)[1].strip().upper()
    dates={}
    for node in article.css('dt'):
        name=node.text(strip=True).casefold();value=node.next
        if name not in {'submitted','application date'} or value is None or value.tag!='dd':continue
        raw=value.text(strip=True)
        try:parsed=date.fromisoformat(raw)
        except ValueError:continue
        dates['submitted_at' if name=='submitted' else 'application_at']=parsed.isoformat()
    if live:
        stamp=re.search(r'From:\s*.*?\bon ([A-Z][a-z]+ \d{1,2}, \d{4})',article.text(separator=' ',strip=True))
        if stamp:
            from datetime import datetime
            try:dates['submitted_at']=datetime.strptime(stamp[1],'%B %d, %Y').date().isoformat()
            except ValueError:pass
    return ReportDetail(report_ref=urlsplit(url).path.rstrip('/').split('/')[-1],url=permitted_url(url),
        original_from=direction[0],original_to=direction[1],
        reported_label=reported, text=text, **dates)



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


def report_body_complete(html):
    """Require an explicit closing tag; DOM parsers repair truncated HTML."""
    from html.parser import HTMLParser as TokenParser
    class BodyBoundary(TokenParser):
        def __init__(self):
            super().__init__()
            self.stack=[];self.target=None;self.complete=False
        def handle_starttag(self,tag,attrs):
            if tag in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:return
            self.stack.append(tag)
            if self.target is None and 'instructions' in dict(attrs).get('class','').split():
                self.target=len(self.stack)
        def handle_endtag(self,tag):
            if tag not in self.stack:return
            depth=len(self.stack)-self.stack[::-1].index(tag)
            if self.target==depth and tag==self.stack[self.target-1]:self.complete=True
            self.stack=self.stack[:depth-1]
    parser=BodyBoundary();parser.feed(html)
    return parser.complete
