from .utils import normalize_missing
def prepare(df): return df.apply(normalize_missing)
