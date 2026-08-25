from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.json_utils import sanitize_json
from .state import utc_now


class WorkflowRegistry:
    """Workflow audit only. Business state remains in the existing domain registries."""
    def __init__(self, path: str | Path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self._init()

    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path,check_same_thread=False);connection.row_factory=sqlite3.Row
        try:
            yield connection;connection.commit()
        finally:connection.close()

    def _init(self):
        with self.connect() as c:c.executescript("""
        CREATE TABLE IF NOT EXISTS graph_runs(
          run_id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,workflow_version TEXT NOT NULL,dataset_id TEXT NOT NULL,
          segment TEXT,entry_point TEXT,status TEXT,current_node TEXT,checkpoint_id TEXT,business_state_id TEXT,
          started_at TEXT,updated_at TEXT,finished_at TEXT,cancel_requested INTEGER DEFAULT 0,error TEXT);
        CREATE TABLE IF NOT EXISTS graph_node_runs(
          node_run_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,node TEXT NOT NULL,attempt INTEGER NOT NULL,status TEXT NOT NULL,
          input_refs TEXT,output_refs TEXT,patch TEXT,duration_ms REAL,error TEXT,reason_codes TEXT,started_at TEXT,finished_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_graph_nodes_run ON graph_node_runs(run_id,started_at);
        """)

    @staticmethod
    def _decode(row):
        if row is None:return None
        out=dict(row)
        for key in ("input_refs","output_refs","patch","error","reason_codes"):
            if out.get(key):
                try:out[key]=json.loads(out[key])
                except (TypeError,ValueError):pass
        if "cancel_requested" in out:out["cancel_requested"]=bool(out["cancel_requested"])
        return out

    def create_run(self,row:dict[str,Any]):
        now=utc_now();data={"status":"RUNNING","current_node":"START","checkpoint_id":None,"business_state_id":None,"started_at":now,"updated_at":now,"finished_at":None,"cancel_requested":0,"error":None,**row}
        with self.lock,self.connect() as c:c.execute(f"INSERT INTO graph_runs({','.join(data)}) VALUES({','.join('?' for _ in data)})",tuple(data.values()))
        return self.get_run(data["run_id"])

    def update_run(self,run_id:str,**changes):
        changes={**changes,"updated_at":utc_now()};encoded={k:json.dumps(sanitize_json(v),ensure_ascii=False) if k=="error" and v is not None else v for k,v in changes.items()}
        with self.lock,self.connect() as c:c.execute(f"UPDATE graph_runs SET {','.join(f'{k}=?' for k in encoded)} WHERE run_id=?",(*encoded.values(),run_id))
        return self.get_run(run_id)

    def get_run(self,run_id):
        with self.connect() as c:row=c.execute("SELECT * FROM graph_runs WHERE run_id=?",(run_id,)).fetchone()
        if not row:raise KeyError(run_id)
        return self._decode(row)

    def start_node(self,run_id,node,input_refs):
        attempt=self.next_attempt(run_id,node);node_run_id=f"GNR_{uuid.uuid4().hex[:12]}";now=utc_now()
        row={"node_run_id":node_run_id,"run_id":run_id,"node":node,"attempt":attempt,"status":"RUNNING","input_refs":json.dumps(sanitize_json(input_refs),ensure_ascii=False),"output_refs":None,"patch":None,"duration_ms":None,"error":None,"reason_codes":"[]","started_at":now,"finished_at":None}
        with self.lock,self.connect() as c:c.execute(f"INSERT INTO graph_node_runs({','.join(row)}) VALUES({','.join('?' for _ in row)})",tuple(row.values()))
        self.update_run(run_id,current_node=node,status="RUNNING");return node_run_id

    def finish_node(self,node_run_id,status,*,output_refs=None,patch=None,duration_ms=0,error=None,reason_codes=None):
        values={"status":status,"output_refs":json.dumps(sanitize_json(output_refs or {}),ensure_ascii=False),"patch":json.dumps(sanitize_json(patch or {}),ensure_ascii=False),"duration_ms":duration_ms,"error":json.dumps(sanitize_json(error),ensure_ascii=False) if error else None,"reason_codes":json.dumps(reason_codes or [],ensure_ascii=False),"finished_at":utc_now()}
        with self.lock,self.connect() as c:c.execute(f"UPDATE graph_node_runs SET {','.join(f'{k}=?' for k in values)} WHERE node_run_id=?",(*values.values(),node_run_id))

    def waiting(self,run_id,node,input_refs,review_type):
        node_id=self.start_node(run_id,node,input_refs);self.finish_node(node_id,"WAITING",output_refs={"review_type":review_type},patch={});self.update_run(run_id,status="WAITING",current_node=node)

    def event(self,run_id,node,status,output_refs=None,reason_codes=None):
        node_id=self.start_node(run_id,node,{});self.finish_node(node_id,status,output_refs=output_refs,reason_codes=reason_codes);return node_id

    def next_attempt(self,run_id,node):
        with self.connect() as c:return int(c.execute("SELECT COUNT(*) FROM graph_node_runs WHERE run_id=? AND node=?",(run_id,node)).fetchone()[0])+1

    def successful_patch(self,run_id,node,cycle=0):
        marker=f"cycle:{cycle}"
        with self.connect() as c:rows=c.execute("SELECT * FROM graph_node_runs WHERE run_id=? AND node=? AND status IN ('SUCCESS','SKIPPED') ORDER BY started_at DESC",(run_id,node)).fetchall()
        for row in rows:
            decoded=self._decode(row)
            if marker in (decoded.get("reason_codes") or []):return decoded.get("patch") or {}
        return None

    def timeline(self,run_id):
        self.get_run(run_id)
        with self.connect() as c:rows=c.execute("SELECT * FROM graph_node_runs WHERE run_id=? ORDER BY started_at,node_run_id",(run_id,)).fetchall()
        return [self._decode(row) for row in rows]

    def is_cancel_requested(self,run_id):return self.get_run(run_id).get("cancel_requested",False)
