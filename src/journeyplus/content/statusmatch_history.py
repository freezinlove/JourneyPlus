"""Remove retired fee tables from official-project reading text, not snapshots."""
import re
from urllib.parse import urlsplit

from journeyplus.sources.statusmatch_links import is_project_statusmatch_host

HISTORICAL_HEADING_RE = re.compile(r"\brecently\s+ended\s+offers?\b", re.I)
STATUS_HEADER_RE = re.compile(r"\bstatus\s+tier\b|\btier$", re.I)
FEE_HEADER_RE = re.compile(r"\bapplication\s+fee\b", re.I)


def is_statusmatch_project_page(url: str) -> bool:
    return is_project_statusmatch_host((urlsplit(url).hostname or '').casefold())


def remove_historical_fee_tables(value: str) -> str:
    """Keep later mapping tables, surrounding prose, footnotes and links."""
    lines = value.splitlines()
    result = []
    historical = False
    historical_level = 6
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = line.strip().strip('#*_ ')
        heading_marker = re.match(r'^\s*(#{1,6})\s+', line)
        if HISTORICAL_HEADING_RE.fullmatch(heading):
            historical = True
            historical_level = len(heading_marker[1]) if heading_marker else 6
            index += 1
            continue
        if heading_marker and len(heading_marker[1]) <= historical_level:
            historical = False
        if historical and line.lstrip().startswith('|'):
            end = index
            while end < len(lines) and lines[end].lstrip().startswith('|'):
                end += 1
            block = lines[index:end]
            # Recognize the fee header; a later airline/tier mapping is retained.
            cells = [[re.sub(r'[*_`]', '', cell).strip() for cell in row.strip('| ').split('|')]
                     for row in block[:4]]
            fee_table = any(any(STATUS_HEADER_RE.search(c) for c in row)
                            and any(FEE_HEADER_RE.search(c) for c in row) for row in cells)
            if not fee_table:
                result.extend(block)
            index = end
            continue
        result.append(line)
        index += 1
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(result)).strip()
