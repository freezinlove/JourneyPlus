"""One read produces an immutable page and, when applicable, a reusable report."""
from urllib.parse import urlsplit
from uuid import UUID

from journeyplus.agent.adapters.artifacts import digest
from journeyplus.agent.adapters.models import Artifact
from journeyplus.agent.adapters.transactions import transaction
from journeyplus.agent.report_pages import parse_report_detail, report_body_complete


def save_page(page, ctx):
    page = dict(page)  # Never mutate the HTTP cache or the downloaded HTML.
    url = urlsplit(page['final_url'])
    report = None
    if url.hostname in {'statusmatcher.com', 'www.statusmatcher.com'} and url.path.startswith('/report/'):
        try:
            report = parse_report_detail(page['raw_html'], page['final_url']).model_dump(mode='json', exclude_none=True)
            report['body_complete'] = not page.get('raw_truncated', False) or report_body_complete(page['raw_html'])
        except ValueError as error:
            # A changed report layout must not discard readable page content.
            page['report_error'] = str(error)[:200]
    artifacts = ctx.artifact_port
    with transaction(artifacts.factory) as session:
        page_ref = artifacts.put_in(session, ctx.workspace_id, 'PAGE', page,
                                    call_id=ctx.call_id, turn_id=ctx.turn_id)
        if report is not None:
            report['page_ref'] = page_ref
            root = artifacts.put_in(session, ctx.workspace_id, 'REPORT',
                                    {'reports': {report['report_ref']: report}},
                                    call_id=ctx.call_id, turn_id=ctx.turn_id, source_refs=[page_ref])
            page['report_ref'] = root + '#report:' + report['report_ref']
            # Set the link before publishing either object; subsequent reads and
            # cursor continuations use these same immutable objects.
            row = session.get(Artifact, UUID(page_ref.removeprefix('artifact:')))
            row.payload = dict(page)
            row.content_hash = digest(page)
    return page_ref, page, report


def resolve_report(artifact, ctx):
    """A page reference may alias its saved report, but never triggers parsing."""
    if artifact['kind'] == 'PAGE' and artifact['payload'].get('report_ref'):
        return ctx.artifact_port.read(ctx.workspace_id, artifact['payload']['report_ref'])
    return artifact
