"""Batch-scoped HTTP acquisition with sticky browser fallback for challenges."""
from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import sys
from time import monotonic
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx

from journeyplus.sources.base import FetchResponse, HttpxFetcher
from journeyplus.sources.statusmatch_links import is_project_statusmatch_host

log = logging.getLogger(__name__)


def is_challenge(body: str, headers=None) -> bool:
    if headers and headers.get('cf-mitigated', '').lower() == 'challenge':
        return True
    from selectolax.parser import HTMLParser
    tree = HTMLParser(body)
    title = tree.css_first('title')
    title_text = title.text().strip().lower() if title else ''
    return title_text.startswith(('just a moment', 'checking your browser', 'verify you are human')) or bool(
        tree.css_first('#challenge-form, #challenge-running, #challenge-stage, .cf-challenge-running')
    )


def validate_response(url: str, response: FetchResponse) -> None:
    expected, final = urlsplit(url), urlsplit(response.final_url)
    if final.scheme != 'https' or final.hostname != expected.hostname:
        raise ValueError('StatusMatch response left its project host')
    if 'html' not in response.content_type.lower():
        raise ValueError('StatusMatch response is not HTML')
    if len(response.body.encode('utf-8')) > 2_000_000:
        raise ValueError('StatusMatch response exceeded 2 MB')
    if is_challenge(response.body, response.headers):
        raise ValueError('StatusMatch browser still returned a challenge')


class ChromiumFetcher:
    """Reuse a headed browser; return document responses, never the rendered DOM."""
    def __init__(self, *, timeout_seconds=45, channel=None):
        self.timeout_seconds = timeout_seconds
        self.channel = channel
        self._runtime = self._browser = self._context = self._xvfb = None

    def _start(self):
        if self._context is not None:
            return
        from playwright.sync_api import sync_playwright
        env = dict(os.environ)
        try:
            if sys.platform.startswith('linux') and not env.get('DISPLAY'):
                read_fd, write_fd = os.pipe()
                try:
                    self._xvfb = subprocess.Popen(
                        ['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x800x24', '-nolisten', 'tcp'],
                        pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    os.close(write_fd)
                    write_fd = None
                    if not select.select([read_fd], [], [], 5)[0]:
                        raise RuntimeError('Xvfb startup timed out')
                    display = os.read(read_fd, 32).decode().strip()
                    if not display.isdigit():
                        raise RuntimeError('Xvfb failed to allocate display')
                    env['DISPLAY'] = ':' + display
                finally:
                    os.close(read_fd)
                    if write_fd is not None:
                        os.close(write_fd)
            self._runtime = sync_playwright().start()
            self._browser = self._runtime.chromium.launch(headless=False, channel=self.channel, env=env)
            self._context = self._browser.new_context(locale='en-US')
        except Exception:
            self.close()
            raise

    def get(self, url):
        self._start()
        page = self._context.new_page()
        candidates = []
        deadline = monotonic() + self.timeout_seconds
        host = urlsplit(url).hostname

        def route_request(route):
            req = route.request
            if req.is_navigation_request() and req.frame == page.main_frame:
                target = urlsplit(req.url)
                if target.scheme != 'https' or target.hostname != host:
                    route.abort()
                    return
            route.continue_()

        def record(response):
            if response.request.is_navigation_request() and response.frame == page.main_frame:
                candidates.append(response)

        def document_finished(request):
            # Ignore subresources before asking Playwright for a response: they may
            # finish while their iframe is being detached or the page is closing.
            if not request.is_navigation_request() or request.frame != page.main_frame:
                return
            response = request.response()
            if response is not None:
                record(response)

        page.route('**/*', route_request)
        # Read only completed documents, so response.text() cannot wait on an unfinished body.
        page.on('requestfinished', document_finished)
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=self.timeout_seconds * 1000)
            while monotonic() < deadline:
                while candidates:
                    response = candidates.pop(0)
                    if is_challenge('', response.headers):
                        continue
                    if 300 <= response.status < 400:
                        continue
                    body = response.text()
                    if is_challenge(body, response.headers):
                        continue
                    if response.status >= 400:
                        raise ValueError(f'Chromium document HTTP {response.status}')
                    if response.status < 200:
                        continue
                    result = FetchResponse(body, response.headers.get('content-type', '').split(';', 1)[0].strip(), response.url, dict(response.headers), response.status)
                    validate_response(url, result)
                    return result
                page.wait_for_timeout(200)
            raise TimeoutError('Chromium did not receive a normal document before deadline')
        finally:
            page.remove_listener('requestfinished', document_finished)
            page.close()

    def close(self):
        for name, method in (('_context', 'close'), ('_browser', 'close'), ('_runtime', 'stop')):
            obj = getattr(self, name)
            setattr(self, name, None)
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:
                    log.warning('StatusMatch browser cleanup failed: %s', name)
        if self._xvfb is not None:
            self._xvfb.terminate()
            try:
                self._xvfb.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._xvfb.kill()
                self._xvfb.wait()
            self._xvfb = None


class StatusMatchBatchFetcher:
    def __init__(self, *, http=None, browser_factory=ChromiumFetcher):
        self.http = http if http is not None else HttpxFetcher()
        self.browser_factory = browser_factory
        self.browser = None
        self.browser_mode = False
        self.batch_id = uuid4().hex

    def get(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not is_project_statusmatch_host(parsed.hostname or ''):
            raise PermissionError('Outside StatusMatch project hosts')
        start = monotonic()
        switched = False
        outcome = 'failed'
        error_type = None
        status_code = None
        try:
            if not self.browser_mode:
                try:
                    result = self.http.get(url)
                    status_code = result.status_code
                    challenge = is_challenge(result.body, result.headers)
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if not is_challenge(exc.response.text, exc.response.headers):
                        raise
                    challenge = True
                if not challenge:
                    validate_response(url, result)
                    outcome = 'success'
                    return result
                self.browser_mode = True
                switched = True
            if self.browser is None:
                self.browser = self.browser_factory()
            status_code = None
            result = self.browser.get(url)
            status_code = result.status_code
            validate_response(url, result)
            outcome = 'success'
            return result
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            log.warning(json.dumps(dict(event='statusmatch_fetch', batch_id=self.batch_id,
                url=urlunsplit((parsed.scheme, parsed.hostname or '', parsed.path, '', '')),
                transport='chromium' if self.browser_mode else 'http', switched=switched,
                switch_reason='human_verification' if switched else None,
                outcome=outcome, error_type=error_type, status_code=status_code,
                elapsed_ms=round((monotonic()-start)*1000)), ensure_ascii=False))

    def close(self):
        try:
            if self.browser is not None:
                self.browser.close()
        finally:
            close = getattr(self.http, 'close', None)
            if close:
                close()


def bind_batch_adapter_factory(factory, batch):
    """Mail-discovered project pages share the same acquisition batch as monitoring."""
    from journeyplus.sources.gmail import GmailStatusServicesAdapter
    def build(source_id):
        adapter = factory(source_id)
        if isinstance(adapter, GmailStatusServicesAdapter):
            adapter.set_project_fetcher(batch)
        return adapter
    return build
