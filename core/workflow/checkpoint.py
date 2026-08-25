from __future__ import annotations

import os
import sqlite3
from pathlib import Path

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK","true")
from langgraph.checkpoint.sqlite import SqliteSaver


class SQLiteCheckpointBackend:
    def __init__(self,path:str|Path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.connection=sqlite3.connect(self.path,check_same_thread=False)
        self.saver=SqliteSaver(self.connection);self.saver.setup()

    def latest_id(self,thread_id:str)->str|None:
        item=self.saver.get_tuple({"configurable":{"thread_id":thread_id}})
        return item.config.get("configurable",{}).get("checkpoint_id") if item else None

    def close(self):self.connection.close()
