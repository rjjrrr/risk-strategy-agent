from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from typing import Any

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .config import RANDOM_STATE
from .evaluation import model_metrics


def temporal_split(df: pd.DataFrame, time_field: str, dev_fraction: float = .7) -> tuple[pd.Index, pd.Index]:
    parsed = pd.to_datetime(df[time_field], errors="coerce")
    valid = parsed.notna(); ordered = parsed[valid].sort_values().index
    cut = max(1, min(len(ordered)-1, int(len(ordered)*dev_fraction)))
    return ordered[:cut], ordered[cut:]


def _preprocessor(frame: pd.DataFrame, scale_numeric: bool) -> ColumnTransformer:
    numeric = [c for c in frame if pd.api.types.is_numeric_dtype(frame[c])]
    categorical = [c for c in frame if c not in numeric]
    num_steps = [("imputer", SimpleImputer(strategy="median"))]
    if scale_numeric: num_steps.append(("scaler", StandardScaler()))
    return ColumnTransformer([
        ("numeric", Pipeline(num_steps), numeric),
        ("categorical", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")),("onehot",OneHotEncoder(handle_unknown="ignore",min_frequency=5))]), categorical),
    ], remainder="drop")


class ModelTrainer:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir); self.output_dir.mkdir(parents=True, exist_ok=True)

    def train(self, model_type: str, x_dev: pd.DataFrame, y_dev: pd.Series, x_oot: pd.DataFrame, y_oot: pd.Series, model_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if model_type == "LR":
            estimator = LogisticRegression(penalty=params.get("penalty","l2"),C=params.get("C",1.0),solver="liblinear",max_iter=500,random_state=RANDOM_STATE)
            pipeline = Pipeline([("preprocess",_preprocessor(x_dev,True)),("model",estimator)])
        elif model_type == "LGBM":
            defaults={"n_estimators":160,"learning_rate":.04,"num_leaves":15,"max_depth":5,"min_child_samples":80,"subsample":.8,"colsample_bytree":.8,"reg_alpha":.1,"reg_lambda":1.0,"random_state":RANDOM_STATE,"verbosity":-1}
            aliases={"feature_fraction":"colsample_bytree","bagging_fraction":"subsample","lambda_l1":"reg_alpha","lambda_l2":"reg_lambda"}
            params={aliases.get(key,key):value for key,value in params.items()}
            defaults.update(params); estimator=LGBMClassifier(**defaults)
            pipeline=Pipeline([("preprocess",_preprocessor(x_dev,False)),("model",estimator)])
        else:
            raise ValueError(f"Unsupported model_type: {model_type}")
        pipeline.fit(x_dev,y_dev); p_dev=pipeline.predict_proba(x_dev)[:,1]; p_oot=pipeline.predict_proba(x_oot)[:,1]
        metrics=model_metrics(y_dev,p_dev,y_oot,p_oot,len(x_dev.columns)); model_path=self.output_dir/f"{model_id}.pkl"; joblib.dump(pipeline,model_path)
        fitted=pipeline.named_steps["model"]
        details={}
        if model_type=="LR": details["coefficients"]=[float(x) for x in fitted.coef_[0]]
        else:
            details["feature_importance"]=[float(x) for x in fitted.feature_importances_]
            destination=self.output_dir/f"{model_id}.txt"
            with tempfile.TemporaryDirectory(prefix="risk_agent_lgbm_") as temp_dir:
                temporary=Path(temp_dir)/f"{model_id}.txt"
                fitted.booster_.save_model(str(temporary))
                shutil.copyfile(temporary,destination)
        return {"model_id":model_id,"model_type":model_type,"model_path":str(model_path),"model_params":params,"metrics":metrics,"details":details,"pipeline":pipeline}
