"""Workspace-local short references; database identifiers never need to be copied by a model."""
import re


class ReferenceMap:
    def __init__(self,state:dict):
        self.entries=state.setdefault("references",{})
        self.reverse={v:k for k,v in self.entries.items()}
        self.next_index=max((int(k[1:]) for k in self.entries if re.fullmatch(r'K\d+',k)),default=0)+1

    def encode(self,value):
        if isinstance(value,dict):return {self.encode(k):self.encode(v) for k,v in value.items()}
        if isinstance(value,list):return [self.encode(v) for v in value]
        if isinstance(value,str) and (re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27}(?:/[a-zA-Z0-9_./-]+)?",value) or re.fullmatch(r"[0-9a-f]{16}",value)):
            if value not in self.reverse:
                key=f"K{self.next_index}";self.next_index+=1;self.entries[key]=value;self.reverse[value]=key
            return self.reverse[value]
        return value

    def encode_packet(self,value,*,max_bytes=15000):
        """Register only references actually disclosed after budget selection."""
        from journeyplus.knowledge.packets import decision_packet,project_model_packet
        temporary=ReferenceMap({'references':dict(self.entries)})
        packet=decision_packet(temporary.encode(project_model_packet(value)),max_bytes=max_bytes)
        return self._commit_disclosed(packet,temporary)

    def encode_packets(self,value,*,max_bytes=21000):
        from journeyplus.knowledge.packets import decision_packets,project_model_packet
        temporary=ReferenceMap({'references':dict(self.entries)})
        packet=decision_packets(temporary.encode([project_model_packet(item) for item in value]),max_bytes=max_bytes)
        return self._commit_disclosed(packet,temporary)

    def _commit_disclosed(self,packet,temporary):
        visible=set()
        def visit(item):
            if isinstance(item,dict):
                for key,child in item.items():visit(key);visit(child)
            elif isinstance(item,list):
                for child in item:visit(child)
            elif isinstance(item,str) and item in temporary.entries:visible.add(item)
        visit(packet)
        for key in visible:
            self.entries[key]=temporary.entries[key]
            self.reverse[temporary.entries[key]]=key
        self.next_index=max((int(k[1:]) for k in self.entries if re.fullmatch(r'K\d+',k)),default=0)+1
        return packet

    def decode(self,value):
        if isinstance(value,dict):return {self.decode(k):self.decode(v) for k,v in value.items()}
        if isinstance(value,list):return [self.decode(v) for v in value]
        return self.entries.get(value,value) if isinstance(value,str) else value

    def require_disclosed(self,value):
        """Check identifier arguments before decoding or touching the database."""
        if not isinstance(value,dict):return
        for key,child in value.items():
            if key=='ref' or key.endswith(('_id','_ids','_ref','_refs')):
                for ref in child if isinstance(child,list) else [child]:
                    if ref is not None and ref not in self.entries and ref not in self.reverse:
                        raise ValueError('对象尚未披露，请先按名称定位，不得猜测数据库标识')
            elif isinstance(child,dict):self.require_disclosed(child)
