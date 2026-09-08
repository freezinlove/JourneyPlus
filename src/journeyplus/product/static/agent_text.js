// Render model prose as DOM nodes; model/website HTML is always literal text.
const element=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
function inline(node,text){
  const expression=/\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let offset=0;
  for(const match of text.matchAll(expression)){
    node.append(document.createTextNode(text.slice(offset,match.index)));
    if(match[1]){
      let url;try{url=new URL(match[2],location.origin);}catch{}
      if(url&&['http:','https:'].includes(url.protocol)){
        const link=element('a',match[1]);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';node.append(link);
      }else node.append(document.createTextNode(match[0]));
    }else node.append(element(match[3]?'strong':'code',match[3]||match[4]));
    offset=match.index+match[0].length;
  }
  node.append(document.createTextNode(text.slice(offset)));
}
export function renderText(node,text){
  node.replaceChildren();const lines=text.split('\n');let list=null;
  for(let i=0;i<lines.length;i++){
    const line=lines[i];
    if(!line.trim()){list=null;continue;}
    if(line.startsWith('```')){
      const code=[];while(++i<lines.length&&!lines[i].startsWith('```'))code.push(lines[i]);
      node.append(element('pre',code.join('\n')));list=null;continue;
    }
    if(line.includes('|')&&/^\s*\|?\s*:?-{3}/.test(lines[i+1]||'')){
      const table=element('table');const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|');
      const heading=element('tr');for(const value of cells(line)){const th=element('th');inline(th,value.trim());heading.append(th);}table.append(heading);i++;
      while(i+1<lines.length&&lines[i+1].includes('|')){const row=element('tr');for(const value of cells(lines[++i])){const td=element('td');inline(td,value.trim());row.append(td);}table.append(row);}
      const scroll=element('div');scroll.className='table-scroll';scroll.append(table);node.append(scroll);list=null;continue;
    }
    if(/^\s*---+\s*$/.test(line)){node.append(element('hr'));list=null;continue;}
    const heading=line.match(/^(#{1,6})\s+(.+)$/),bullet=line.match(/^\s*(?:([-*])|\d+\.)\s+(.+)$/);
    if(bullet){const tag=bullet[1]?'ul':'ol';if(!list||list.tagName.toLowerCase()!==tag){list=element(tag);node.append(list);}const item=element('li');inline(item,bullet[2]);list.append(item);continue;}
    list=null;const block=element(heading?'h'+Math.min(heading[1].length+1,6):line.startsWith('> ')?'blockquote':'p');
    inline(block,heading?heading[2]:line.replace(/^> /,''));node.append(block);
  }
}
