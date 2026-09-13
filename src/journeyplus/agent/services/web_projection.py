"""Bounded excerpts of one immutable public page; cursors never refetch it."""
import hashlib
import json
from selectolax.parser import HTMLParser
from .page_sections import select_sections


def binding(args):
    return hashlib.sha256(json.dumps([args.url,args.sections,args.include_controls],ensure_ascii=False).encode()).hexdigest()[:20]


def page_excerpt(page,ref,args,text_start=0,link_start=0):
    selected=None
    tree=HTMLParser(page['raw_html'])
    controls=[{'index':index,'tag':node.tag,'name':node.attributes.get('name',''),
               'id':node.attributes.get('id',''),'option_count':len(node.css('option'))}
              for index,node in enumerate(tree.css('select'))]
    from .statusmatcher_content import cleaned_page
    cleaned=cleaned_page(page['raw_html'],page.get('final_url',page.get('url',args.url)),include_controls=args.include_controls)
    links=page['links']
    if cleaned is not None:
        tree,links=cleaned
    if args.sections:
        selected=select_sections(tree.html,args.sections,1_000_000)
        body='\n'.join(section['title']+'\n'+section['text'] for section in selected['sections'])
    else:
        for node in tree.css('script,style,noscript,nav,footer'):node.decompose()
        if not args.include_controls:
            for node in tree.css('select,input,textarea,button'):node.decompose()
        body=(tree.body or tree.root).text(separator=' ',strip=True)
    if text_start>len(body) or link_start>len(links):raise ValueError('Invalid page cursor offset')
    excerpt=body[text_start:text_start+args.max_chars].encode()[:6000].decode(errors='ignore')
    text_end=text_start+len(excerpt)
    returned=[];link_end=link_start;size=0;oversized=[]
    for index,link in enumerate(links[link_start:],start=link_start):
        length=len(json.dumps(link,ensure_ascii=False).encode())
        if length>2000:
            oversized.append(index);link_end=index+1
            if len(oversized)>=10:break
            continue
        if size+length>2000:break
        returned.append(link);size+=length;link_end=index+1
    next_cursor=(f'{ref}|{text_end}|{link_end}|{binding(args)}'
                 if text_end<len(body) or link_end<len(links) else None)
    missing=selected['missing_sections'] if selected else []
    omissions=([*missing]+(['download_prefix_only'] if page.get('raw_truncated') else [])+
               (['links_omitted_during_storage'] if page.get('links_truncated') else [])+
               (['oversized_links_expand_page_artifact'] if oversized else []))
    data={key:page[key] for key in ('url','final_url','title','observed_at','content_hash','content_hash_scope',
                                   'raw_truncated','retained_raw_bytes','links_truncated','cache_hit') if key in page}
    data.update(page_ref=ref,text=excerpt,links=returned,content_length=len(body),
                evidence_scope={'kind':'observed_page_content','authority':'not_verified',
                                'observed_at_meaning':'fetch time, not publication or policy effective date',
                                'applicability':'Claims retain their original author, date and subject; a page or report does not establish current general policy.'},
                truncated=bool(next_cursor or omissions),missing_sections=missing,
                content_scope='selected_sections' if selected else 'page_text_including_form_options' if args.include_controls else 'page_text_excluding_form_controls',
                form_controls=controls[:10])
    if selected:
        data['sections']=[{'id':section['id'],'title':section['title']} for section in selected['sections']]
        data['available_sections']=[{'id':section['id'],'title':section['title'][:300]}
                                    for section in selected['available_sections'][:20]]
    coverage={'complete':not bool(next_cursor or omissions),'omissions':omissions,
              'text_range':[text_start,text_end],'text_characters':len(body),
              'links_range':[link_start,link_end],'links_total':len(links),
              'oversized_link_indices':oversized,'snapshot_ref':ref}
    if cleaned is None or args.include_controls:
        coverage['form_control_count']=len(controls)
    else:
        data.pop('form_controls',None)
    if selected:coverage['available_sections_total']=len(selected['available_sections'])
    return data,coverage,next_cursor
