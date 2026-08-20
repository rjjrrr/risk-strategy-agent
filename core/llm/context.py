from __future__ import annotations
import hashlib,json
from typing import Any
from core.json_utils import sanitize_json

class AgentContextBuilder:
    def __init__(self,max_items=30,max_chars=12000):self.max_items=max_items;self.max_chars=max_chars
    def build(self,agent_type:str,conversation:dict,attachments:list,source:dict[str,Any])->dict:
        context={'dataset_id':conversation.get('dataset_id'),'agent_type':agent_type,'attachments':attachments[:self.max_items]}
        for key in ('dataset_summary','variable_profiles','rule_groups','semantic','hypotheses','features','experiments','diagnoses','model_state','evaluation'):
            value=source.get(key)
            if isinstance(value,list):value=value[:self.max_items]
            if value is not None:context[key]=value
        text=json.dumps(sanitize_json(context),ensure_ascii=False,sort_keys=True)
        if len(text)>self.max_chars:text=text[:self.max_chars]+'...TRUNCATED'
        return {'text':text,'hash':hashlib.sha256(text.encode()).hexdigest(),'summary':{'dataset_id':conversation.get('dataset_id'),'attachment_count':len(attachments),'included_sections':list(context),'chars':len(text)}}
