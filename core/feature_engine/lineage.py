from __future__ import annotations

import hashlib
import json
import pandas as pd


EXECUTION_CODE_VERSION = "feature-engine-v1"


def dataset_version(df: pd.DataFrame) -> str:
    schema=[(str(c),str(df[c].dtype)) for c in df.columns]
    hashes=pd.util.hash_pandas_object(df, index=True).to_numpy(dtype="uint64",copy=False)
    digest=hashlib.sha256();digest.update(json.dumps(schema,separators=(",",":"),ensure_ascii=False).encode());digest.update(str(len(df)).encode());digest.update(hashes.tobytes())
    return digest.hexdigest()


def next_feature_version(rows: list[dict], feature_name: str) -> str:
    versions=[]
    for row in rows:
        if row.get("feature_name")==feature_name:
            try:versions.append(int(str(row.get("version") or row.get("feature_version") or "1").split(".")[0]))
            except ValueError:pass
    return f"{max(versions,default=0)+1}.0"
