from __future__ import annotations

import os,sqlite3,threading,uuid
from pathlib import Path
from typing import Any

from .schemas import LLMBindingInput
from core.model_agent.registry import utc_now

def mask_secret(secret:str|None)->str|None:
    if not secret:return None
    return f"{secret[:3]}-****{secret[-4:]}" if len(secret)>7 else "****"

class SessionSecretStore:
    _values:dict[str,str]={}; _lock=threading.Lock()
    @classmethod
    def put(cls,key_ref:str,value:str):
        with cls._lock: cls._values[key_ref]=value
    @classmethod
    def get(cls,key_ref:str|None)->str|None:
        if not key_ref:return None
        return cls._values.get(key_ref) or os.getenv(key_ref)

class BindingStore:
    def __init__(self,path:str|Path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self._init()
    def _connect(self):
        con=sqlite3.connect(self.path,timeout=15);con.row_factory=sqlite3.Row;return con
    def _init(self):
        with self._connect() as c:c.execute('''CREATE TABLE IF NOT EXISTS llm_bindings_metadata(binding_id TEXT PRIMARY KEY,display_name TEXT UNIQUE,provider TEXT,base_url TEXT,key_ref TEXT,model TEXT,temperature REAL,max_tokens INTEGER,timeout_seconds REAL,enabled INTEGER,is_default INTEGER,priority INTEGER,fallback_binding_id TEXT,created_at TEXT,updated_at TEXT)''')
    def create(self,data:LLMBindingInput)->dict[str,Any]:
        binding_id=f"B_{uuid.uuid4().hex[:10]}"; key_ref=data.key_ref
        if data.api_key:
            key_ref=key_ref or f"RISK_AGENT_SESSION_{binding_id}"
            SessionSecretStore.put(key_ref,data.api_key)
        now=utc_now();row={**data.model_dump(exclude={'api_key'}),'binding_id':binding_id,'key_ref':key_ref,'created_at':now,'updated_at':now}
        if row['is_default']:self._clear_default()
        with self.lock,self._connect() as c:c.execute(f"INSERT INTO llm_bindings_metadata({','.join(row)}) VALUES({','.join('?' for _ in row)})",tuple(row.values()))
        return self.public(row)
    def _clear_default(self):
        with self._connect() as c:c.execute("UPDATE llm_bindings_metadata SET is_default=0")
    def all(self,enabled_only=False):
        query="SELECT * FROM llm_bindings_metadata"+(" WHERE enabled=1" if enabled_only else "")+" ORDER BY is_default DESC,priority,created_at"
        with self._connect() as c:return [self.public(dict(x)) for x in c.execute(query)]
    def raw(self,binding_id):
        with self._connect() as c:r=c.execute("SELECT * FROM llm_bindings_metadata WHERE binding_id=?",(binding_id,)).fetchone()
        if not r:raise KeyError(binding_id)
        return dict(r)
    def public(self,row):
        out={**row};secret=SessionSecretStore.get(out.get('key_ref'));out['enabled']=bool(out.get('enabled'));out['is_default']=bool(out.get('is_default'));out['api_key_plaintext']=secret;out['api_key_masked']=secret;out['has_secret']=bool(secret);return out
    def update(self,binding_id,changes):
        allowed={'display_name','provider','base_url','key_ref','model','temperature','max_tokens','timeout_seconds','enabled','is_default','priority','fallback_binding_id'}; api_key=changes.pop('api_key',None)
        if api_key:
            key_ref=changes.get('key_ref') or self.raw(binding_id).get('key_ref') or f"RISK_AGENT_SESSION_{binding_id}";changes['key_ref']=key_ref;SessionSecretStore.put(key_ref,api_key)
        changes={k:v for k,v in changes.items() if k in allowed};changes['updated_at']=utc_now()
        if changes.get('is_default'):self._clear_default()
        with self.lock,self._connect() as c:c.execute(f"UPDATE llm_bindings_metadata SET {','.join(f'{k}=?' for k in changes)} WHERE binding_id=?",(*changes.values(),binding_id))
        return self.public(self.raw(binding_id))
    def delete(self,binding_id):
        with self.lock,self._connect() as c:c.execute("DELETE FROM llm_bindings_metadata WHERE binding_id=?",(binding_id,))
    def resolve(self,binding_id=None):
        if binding_id and binding_id!='AUTO_ROUTER':
            row=self.raw(binding_id)
            if not row['enabled']:raise ValueError('Binding is disabled')
            return row,'User-selected binding'
        rows=[self.raw(x['binding_id']) for x in self.all(True)]
        if not rows:from .exceptions import NoActiveBinding;raise NoActiveBinding('No active LLM binding configured.')
        return rows[0],('Default binding' if rows[0]['is_default'] else 'Enabled binding with highest priority')
