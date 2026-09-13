"""Remove site chrome from the model view, never from the archived response."""
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser


def cleaned_page(html, url, *, include_controls=False):
    parts = urlsplit(url)
    if parts.hostname not in {'statusmatcher.com', 'www.statusmatcher.com'}:
        return None
    tree = HTMLParser(html)
    # Live company/report pages have a dedicated content column. Fixtures and
    # changed layouts fall back to the document with only explicit chrome removed.
    main = tree.css_first('.col-lg-9 section') or tree.css_first('main')
    if main is not None:
        tree = HTMLParser(main.html)
    for selector in ('script', 'style', 'noscript', 'nav', 'footer', 'aside',
                     'iframe', '.adsbygoogle', '[data-ad-client]', '.ad-container',
                     '[id^="google_ads"]', '.col-lg-3'):
        for node in tree.css(selector):
            node.decompose()
    if not include_controls:
        for selector in ('form', '#new-report', 'select', 'input', 'textarea', 'button'):
            for node in tree.css(selector):
                node.decompose()
    if parts.path.startswith('/report/') and tree.css_first('.instructions'):
        # The selected tiers are already in the report heading. The adjacent
        # palette enumerates ALL tiers and must not look like report identities.
        for node in tree.css('.status-box-column'):
            node.decompose()
    # Remove the comment-login prompt, not user-authored discussion text.
    for node in tree.css('a[href="/login"]'):
        parent=node.parent
        if parent is not None and ' '.join(parent.text(separator=' ',strip=True).split()) in {
            'Login or Register to post comments', 'Guest ( Login or Register )'
        }:
            parent.decompose()
    links = []
    seen = set()
    for node in tree.css('a[href]'):
        href = urljoin(url, node.attributes['href'])
        target = urlsplit(href)
        if target.hostname in {'statusmatcher.com', 'www.statusmatcher.com'} and (
            target.path in {'/login', '/register', '/report/create'} or target.fragment == 'new-report'
        ):
            continue
        if target.scheme == 'https' and href not in seen:
            links.append({'url': href, 'title': node.text(separator=' ', strip=True)[:300]})
            seen.add(href)
    return tree, links
