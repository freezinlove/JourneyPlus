"""Server filtering where SQL folding preserves the existing search semantics."""
from sqlalchemy import cast,Text,or_


def json_search(column,query,dialect):
    if not query:return None
    # Non-ASCII case folding (e.g. ß/SS) differs across SQL engines. Preserve
    # exact behavior with a fallback instead of silently losing those matches.
    import re
    if not query.isascii() or not re.fullmatch(r'[A-Za-z0-9 -]+',query):return None
    value=cast(column,Text)
    match=value.ilike('%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%',escape='\\')
    if dialect=='postgresql':
        # Unicode text can casefold into an ASCII query. Keep these candidates
        # for the authoritative Python fold below as well.
        return or_(match,value.op('~')('[^\\x00-\\x7F]'))
    return None
