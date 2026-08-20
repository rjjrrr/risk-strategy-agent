from __future__ import annotations
import json,sqlite3,threading,uuid
from pathlib import Path
from typing import Any
from core.json_utils import sanitize_json
from core.model_agent.registry import utc_now

JSON_FIELDS={'attachments','tool_calls','proposal_ids','payload','context_summary'}
class ChatStore:
    def __init__(self,path:str|Path):self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self._init()
    def connect(self):c=sqlite3.connect(self.path,timeout=20,check_same_thread=False);c.row_factory=sqlite3.Row;return c
    def _init(self):
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS conversations(conversation_id TEXT PRIMARY KEY,title TEXT,agent_type TEXT,default_binding_id TEXT,dataset_id TEXT,experiment_id TEXT,state_id TEXT,created_at TEXT,updated_at TEXT,archived INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS messages(message_id TEXT PRIMARY KEY,conversation_id TEXT,role TEXT,content TEXT,attachments TEXT,agent_type TEXT,binding_id TEXT,provider TEXT,model TEXT,prompt_version TEXT,tool_calls TEXT,proposal_ids TEXT,latency_ms INTEGER,prompt_tokens INTEGER,completion_tokens INTEGER,total_tokens INTEGER,status TEXT,error TEXT,parent_message_id TEXT,execution_mode TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS llm_calls(call_id TEXT PRIMARY KEY,conversation_id TEXT,message_id TEXT,agent_type TEXT,provider TEXT,binding_id TEXT,model TEXT,prompt_version TEXT,input_context_hash TEXT,context_summary TEXT,latency_ms INTEGER,prompt_tokens INTEGER,completion_tokens INTEGER,total_tokens INTEGER,success INTEGER,error_type TEXT,error_summary TEXT,state_id TEXT,experiment_id TEXT,router_decision_reason TEXT,execution_mode TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS agent_proposals(proposal_id TEXT PRIMARY KEY,conversation_id TEXT,message_id TEXT,proposal_type TEXT,title TEXT,payload TEXT,reason TEXT,requires_human INTEGER,status TEXT,registry_object_id TEXT,created_at TEXT,updated_at TEXT);
            ''')
    def _decode(self,row):
        if row is None:return None
        out=dict(row)
        for key in JSON_FIELDS:
            if key in out and out[key] and isinstance(out[key],(str,bytes,bytearray)):
                try:out[key]=json.loads(out[key])
                except ValueError:pass
        for key in ('archived','success','requires_human'):
            if key in out and out[key] is not None:out[key]=bool(out[key])
        return out
    def _insert(self,table,row):
        row=sanitize_json(row);encoded={k:json.dumps(v,ensure_ascii=False,allow_nan=False) if k in JSON_FIELDS else v for k,v in row.items()}
        with self.lock,self.connect() as c:c.execute(f"INSERT INTO {table}({','.join(encoded)}) VALUES({','.join('?' for _ in encoded)})",tuple(encoded.values()))
        return row
    def create_conversation(self,**values):
        now=utc_now();row={'conversation_id':f"C_{uuid.uuid4().hex[:12]}",'title':values.get('title') or 'New chat','agent_type':values.get('agent_type','GENERAL_CHAT'),'default_binding_id':values.get('default_binding_id'),'dataset_id':values.get('dataset_id'),'experiment_id':values.get('experiment_id'),'state_id':values.get('state_id'),'created_at':now,'updated_at':now,'archived':0};self._insert('conversations',row);return self._decode(row)
    def conversations(self,search=None):
        q="SELECT * FROM conversations WHERE archived=0";args=[]
        if search:q+=" AND title LIKE ?";args=[f'%{search}%']
        q+=" ORDER BY updated_at DESC"
        with self.connect() as c:return [self._decode(x) for x in c.execute(q,args)]
    def conversation(self,cid):
        with self.connect() as c:r=c.execute("SELECT * FROM conversations WHERE conversation_id=?",(cid,)).fetchone()
        if not r:raise KeyError(cid)
        out=self._decode(r);out['messages']=self.messages(cid);return out
    def update_conversation(self,cid,changes):
        allowed={'title','agent_type','default_binding_id','dataset_id','experiment_id','state_id','archived'};changes={k:v for k,v in changes.items() if k in allowed};changes['updated_at']=utc_now()
        with self.lock,self.connect() as c:c.execute(f"UPDATE conversations SET {','.join(f'{k}=?' for k in changes)} WHERE conversation_id=?",(*changes.values(),cid))
        return self.conversation(cid)
    def delete_conversation(self,cid):return self.update_conversation(cid,{'archived':1})
    def add_message(self,**values):
        row={'message_id':values.get('message_id') or f"M_{uuid.uuid4().hex[:12]}",'conversation_id':values['conversation_id'],'role':values['role'],'content':values.get('content',''),'attachments':values.get('attachments',[]),'agent_type':values.get('agent_type'),'binding_id':values.get('binding_id'),'provider':values.get('provider'),'model':values.get('model'),'prompt_version':values.get('prompt_version'),'tool_calls':values.get('tool_calls',[]),'proposal_ids':values.get('proposal_ids',[]),'latency_ms':values.get('latency_ms'),'prompt_tokens':values.get('prompt_tokens'),'completion_tokens':values.get('completion_tokens'),'total_tokens':values.get('total_tokens'),'status':values.get('status','PENDING'),'error':values.get('error'),'parent_message_id':values.get('parent_message_id'),'execution_mode':values.get('execution_mode'),'created_at':utc_now()};self._insert('messages',row);return self._decode(row)
    def messages(self,cid):
        with self.connect() as c:return [self._decode(x) for x in c.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",(cid,))]
    def update_message(self,mid,changes):
        changes={k:(json.dumps(sanitize_json(v),ensure_ascii=False) if k in JSON_FIELDS else sanitize_json(v)) for k,v in changes.items()}
        with self.lock,self.connect() as c:c.execute(f"UPDATE messages SET {','.join(f'{k}=?' for k in changes)} WHERE message_id=?",(*changes.values(),mid))
        with self.connect() as c:return self._decode(c.execute("SELECT * FROM messages WHERE message_id=?",(mid,)).fetchone())
    def add_call(self,**values):
        row={'call_id':f"CALL_{uuid.uuid4().hex[:12]}",'created_at':utc_now(),**values};self._insert('llm_calls',row);return self._decode(row)
    def calls(self,filters):
        allowed={'conversation_id','agent_type','binding_id','success'};where=[];args=[]
        for k,v in filters.items():
            if k in allowed and v is not None:where.append(f'{k}=?');args.append(int(v) if k=='success' else v)
        q='SELECT * FROM llm_calls'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY created_at DESC'
        with self.connect() as c:return [self._decode(x) for x in c.execute(q,args)]
    def add_proposal(self,**values):
        now=utc_now();row={'proposal_id':f"P_{uuid.uuid4().hex[:12]}",'status':'PENDING','registry_object_id':None,'created_at':now,'updated_at':now,**values};self._insert('agent_proposals',row);return self._decode(row)
    def proposals(self,conversation_id=None):
        q='SELECT * FROM agent_proposals';args=[]
        if conversation_id:q+=' WHERE conversation_id=?';args=[conversation_id]
        q+=' ORDER BY created_at DESC'
        with self.connect() as c:return [self._decode(x) for x in c.execute(q,args)]
    def proposal(self,pid):
        with self.connect() as c:r=c.execute('SELECT * FROM agent_proposals WHERE proposal_id=?',(pid,)).fetchone()
        if not r:raise KeyError(pid)
        return self._decode(r)
    def update_proposal(self,pid,status,registry_object_id=None):
        with self.lock,self.connect() as c:c.execute('UPDATE agent_proposals SET status=?,registry_object_id=?,updated_at=? WHERE proposal_id=?',(status,registry_object_id,utc_now(),pid))
        return self.proposal(pid)
