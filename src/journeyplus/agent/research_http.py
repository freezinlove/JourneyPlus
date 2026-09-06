"""Shared, bounded HTTP reads for permitted StatusMatcher research."""
from dataclasses import dataclass,field
from time import monotonic
from urllib.parse import urljoin,urlsplit
import re
import httpx


class ResearchBudgetExceeded(ValueError):
    pass


@dataclass
class ResearchBudget:
    max_requests:int=12
    max_bytes:int=4_000_000
    duration_seconds:float=20
    started:float=field(default_factory=monotonic)
    requests:int=0
    bytes_read:int=0

    def remaining(self):
        remaining=self.duration_seconds-(monotonic()-self.started)
        if remaining<=0:raise ResearchBudgetExceeded('RESEARCH_DEADLINE')
        return remaining


def permitted_url(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='statusmatcher.com' or parsed.username or parsed.password or parsed.port not in {None,443}:
        raise ValueError('STATUSMATCHER_URL_NOT_ALLOWED')
    if not re.fullmatch(r'/(?:company|report)/[A-Za-z0-9-]+/?',parsed.path):raise ValueError('STATUSMATCHER_PATH_NOT_ALLOWED')
    return url


def read_research_html(client,url,budget,*,response_limit=1_000_000,timeout_seconds=12):
    url=permitted_url(urljoin('https://statusmatcher.com',url))
    while True:
        remaining=budget.remaining()
        if budget.requests>=budget.max_requests:raise ResearchBudgetExceeded('RESEARCH_REQUEST_LIMIT')
        budget.requests+=1
        with client.stream('GET',url,follow_redirects=False,timeout=min(timeout_seconds,remaining)) as response:
            if response.status_code in {301,302,303,307,308}:
                location=response.headers.get('location')
                if not location:raise ValueError('REDIRECT_WITHOUT_LOCATION')
                # Validate before issuing a request, including each redirect hop.
                url=permitted_url(urljoin(url,location));continue
            response.raise_for_status()
            parts=[];size=0
            for chunk in response.iter_bytes():
                budget.remaining();size+=len(chunk);budget.bytes_read+=len(chunk)
                if size>response_limit:raise ResearchBudgetExceeded('RESEARCH_RESPONSE_LIMIT')
                if budget.bytes_read>budget.max_bytes:raise ResearchBudgetExceeded('RESEARCH_TOTAL_BYTES')
                parts.append(chunk)
            budget.remaining()
            return b''.join(parts).decode(response.encoding or 'utf-8',errors='replace'),url
