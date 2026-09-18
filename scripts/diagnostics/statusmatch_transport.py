"""Read-only acquisition/parse comparison. No database or model calls."""
import argparse
import json
from pathlib import Path
from uuid import UUID

from journeyplus.content.cleaner import lightly_clean
from journeyplus.contracts import RawDocument
from journeyplus.facts.statusmatch_tables import extract_statusmatch_status_mappings
from journeyplus.facts.statusmatch_prices import extract_statusmatch_price_routes
from journeyplus.sources.base import HttpxFetcher, FetchResponse
from journeyplus.sources.statusmatch_links import statusmatch_project_page_urls
from journeyplus.statusmatch.fetching import scope_statusmatch_terms_html
from journeyplus.statusmatch.transport import ChromiumFetcher, StatusMatchBatchFetcher


def parse(response, kind):
    body=response.body
    if kind=='terms': body,_=scope_statusmatch_terms_html(body)
    raw=RawDocument(source_id='status_services_mail',external_id='transport-check',
        canonical_url=response.final_url,body=body,content_type=response.content_type)
    args=dict(raw_html=body,canonical_url=response.final_url,document_version_id=UUID(int=1))
    return dict(text=lightly_clean(raw).normalized_body,
        mappings=[x.model_dump(mode='json') for x in extract_statusmatch_status_mappings(**args)],
        prices=[x.model_dump(mode='json') for x in extract_statusmatch_price_routes(**args)])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='flyingblue.statusmatch.com')
    parser.add_argument('--channel',default=None,help='Use chrome for existing local Google Chrome')
    parser.add_argument('--output',default='.local/statusmatch-transport-check')
    opts=parser.parse_args()
    out=Path(opts.output);out.mkdir(parents=True,exist_ok=True)
    http=HttpxFetcher(); browser=ChromiumFetcher(channel=opts.channel)
    rows=[]
    try:
        for kind,url in statusmatch_project_page_urls(opts.host):
            a=http.get(url);b=browser.get(url)
            (out/f'{kind}.http.html').write_text(a.body)
            (out/f'{kind}.chromium.html').write_text(b.body)
            left,right=parse(a,kind),parse(b,kind)
            row=dict(page=kind,url=url,text_equal=left['text']==right['text'],
                mappings_equal=left['mappings']==right['mappings'],prices_equal=left['prices']==right['prices'],
                mapping_count=len(right['mappings']),price_count=len(right['prices']))
            rows.append(row)
            print(json.dumps(row),flush=True)
            (out/f'{kind}.parsed.json').write_text(json.dumps(dict(http=left,chromium=right),ensure_ascii=False,indent=2))
    finally:
        http.close();browser.close()
    # Synthetic challenge only in this diagnostic; following browser acquisitions are real.
    class Trigger:
        def get(self,url): return FetchResponse('<title>Just a moment...</title>','text/html',url)
    batch=StatusMatchBatchFetcher(http=Trigger(),browser_factory=lambda:ChromiumFetcher(channel=opts.channel))
    try:
        for _,url in statusmatch_project_page_urls(opts.host): batch.get(url)
        assert batch.browser_mode
    finally: batch.close()
    (out/'report.json').write_text(json.dumps(rows,indent=2))
    if not all(r['text_equal'] and r['mappings_equal'] and r['prices_equal'] for r in rows):
        raise SystemExit('Comparison differs: inspect saved parsed files')

if __name__=='__main__': main()
