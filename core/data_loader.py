import os
import pandas as pd

def load_data(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".csv": return pd.read_csv(path)
        if ext in (".xlsx", ".xls"): return pd.read_excel(path)
        raise ValueError("仅支持 .csv/.xlsx/.xls")
    except Exception as e:
        raise RuntimeError(f"数据读取失败: {e}") from e
