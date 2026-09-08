"""Deterministic heading selection over the actual fetched document."""
from selectolax.parser import HTMLParser


def select_sections(html, requested, max_chars):
    tree=HTMLParser(html)
    for node in tree.css('script,style,noscript,nav,footer'):node.decompose()
    sections=[{'id':'section-0','title':'Document','parts':[]}]
    for node in (tree.body or tree.root).traverse():
        if node.tag not in {'h1','h2','h3','h4','p','li','pre','table'}:continue
        value=node.text(separator=' ',strip=True)
        if not value:continue
        if node.tag in {'h1','h2','h3','h4'}:
            sections.append({'id':f'section-{len(sections)}','title':value,'parts':[]})
        else:
            # Avoid duplicating paragraphs nested inside a selected list/table.
            parent=node.parent
            while parent is not None and parent.tag not in {'li','pre','table'}:parent=parent.parent
            if parent is None:sections[-1]['parts'].append(value)
    wanted={value.strip().casefold() for value in requested}
    matched=set();selected=[];remaining=max_chars;truncated=False
    for section in sections:
        names={section['id'].casefold(),section['title'].casefold()}
        if not names&wanted:continue
        matched|=names&wanted
        content='\n'.join(section['parts'])
        selected.append({'id':section['id'],'title':section['title'],'text':content[:remaining]})
        if len(content)>remaining:truncated=True
        remaining=max(0,remaining-len(content))
    return {'sections':selected,'available_sections':[{'id':s['id'],'title':s['title']} for s in sections],
            'missing_sections':sorted(wanted-matched),'truncated':truncated,
            'text':'\n'.join(section['text'] for section in selected)}
