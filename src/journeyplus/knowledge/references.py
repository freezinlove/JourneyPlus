"""Workspace-local short references; database identifiers never need to be copied by a model."""
import re


class ReferenceMap:
    def __init__(self,state:dict):
        self.entries=state.setdefault("references",{})
        self.reverse={v:k for k,v in self.entries.items()}

    def encode(self,value):
        if isinstance(value,dict):return {self.encode(k):self.encode(v) for k,v in value.items()}
        if isinstance(value,list):return [self.encode(v) for v in value]
        if isinstance(value,str) and (re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27}",value) or re.fullmatch(r"[0-9a-f]{16}",value)):
            if value not in self.reverse:
                key=f"K{len(self.entries)+1}";self.entries[key]=value;self.reverse[value]=key
            return self.reverse[value]
        return value

    def decode(self,value):
        if isinstance(value,dict):return {self.decode(k):self.decode(v) for k,v in value.items()}
        if isinstance(value,list):return [self.decode(v) for v in value]
        return self.entries.get(value,value) if isinstance(value,str) else value

