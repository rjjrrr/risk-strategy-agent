from __future__ import annotations

import hashlib
import json
import math
import pickle
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import brier_score_loss, mean_absolute_error, mean_squared_error, precision_score, recall_score, roc_auc_score

try:
    from lightgbm import LGBMClassifier, LGBMRegressor
    HAS_LIGHTGBM = True
except ImportError:  # pragma: no cover
    HAS_LIGHTGBM = False

from core.json_utils import sanitize_json
from .audit import SurrogatePredictionRegistry, SurrogateRegistry
from .meta_features import META_FEATURES, build_meta_features, targets
from .schemas import SurrogateModelRecord
from .diagnostics import classification_metrics, ranking_metrics, regression_metrics


class SurrogateTrainer:
    def __init__(self, root: str | Path, *, minimum: int = 30, active_threshold: int = 100):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.minimum = minimum; self.active_threshold = active_threshold
        self.registry = SurrogateRegistry(self.root)

    def train(self, rows: list[dict], *, user_confirmed: bool = False) -> dict:
        if not user_confirmed:
            raise ValueError("SURROGATE_TRAINING_REQUIRES_USER_CONFIRMATION")
        usable = sorted([x for x in rows if x.get("counterfactual_decision") in {"POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE"}], key=lambda x: str(x.get("timestamp") or ""))
        dataset_hash = hashlib.sha256(json.dumps([(x.get("experiment_id"), x.get("timestamp")) for x in usable], separators=(",", ":")).encode()).hexdigest()
        surrogate_id = f"SG_{uuid.uuid4().hex[:12]}"
        if len(usable) < self.minimum:
            row = SurrogateModelRecord(surrogate_id=surrogate_id, version="1.0", algorithm="NONE", training_window=self._window(usable), training_count=len(usable), features=META_FEATURES, targets=["delta_oot_auc", "delta_oot_ks", "delta_lift10", "positive"], status="INSUFFICIENT_DATA", training_dataset_hash=dataset_hash).model_dump()
            self.registry.add(row); return {**row, "reason": "SURROGATE_INSUFFICIENT_DATA"}
        try:
            split = max(1, min(len(usable) - 1, int(len(usable) * 0.8)))
            train_rows, test_rows = usable[:split], usable[split:]
            vectorizer = DictVectorizer(sparse=False)
            x_train_array = vectorizer.fit_transform([build_meta_features(x) for x in train_rows])
            x_test_array = vectorizer.transform([build_meta_features(x) for x in test_rows])
            columns = [f"mf_{i}" for i in range(x_train_array.shape[1])]
            x_train = pd.DataFrame(x_train_array, columns=columns)
            x_test = pd.DataFrame(x_test_array, columns=columns)
            y_train = [targets(x) for x in train_rows]; y_test = [targets(x) for x in test_rows]
            classifier = LGBMClassifier(random_state=42, n_estimators=60, verbosity=-1) if HAS_LIGHTGBM else GradientBoostingClassifier(random_state=42)
            labels = np.asarray([x["positive"] for x in y_train])
            if len(set(labels)) < 2:
                raise ValueError("Surrogate classification target needs both classes")
            classifier.fit(x_train, labels)
            calibrated = CalibratedClassifierCV(estimator=clone(classifier), method="sigmoid", cv=3)
            calibrated.fit(x_train, labels)
            regressors = {}
            for target in ("delta_oot_auc", "delta_oot_ks", "delta_lift10"):
                model = LGBMRegressor(random_state=42, n_estimators=60, verbosity=-1) if HAS_LIGHTGBM else GradientBoostingRegressor(random_state=42)
                model.fit(x_train, np.asarray([x[target] for x in y_train])); regressors[target] = model
            probabilities_before = classifier.predict_proba(x_test)[:, 1]
            probabilities = calibrated.predict_proba(x_test)[:, 1]
            predictions = (probabilities >= 0.5).astype(int)
            actual = np.asarray([x["positive"] for x in y_test])
            classification = classification_metrics(actual, probabilities)
            calibration = {"method": "PLATT", "before": classification_metrics(actual, probabilities_before), "after": classification}
            regression = {}
            predicted_auc = None
            for target, model in regressors.items():
                observed = np.asarray([x[target] for x in y_test]); predicted = model.predict(x_test)
                if target == "delta_oot_auc": predicted_auc = predicted
                regression[target] = regression_metrics(observed, predicted)
            gain_actual=np.asarray([x["delta_oot_auc"] for x in y_test]); surrogate_ranking=ranking_metrics(actual,gain_actual,predicted_auc if predicted_auc is not None else probabilities)
            rng=np.random.default_rng(42); random_ranking=ranking_metrics(actual,gain_actual,rng.random(len(actual)))
            phase5_score=np.asarray([2*(str(x.get("validation_metrics",{}).get("feature_novelty"))=="HIGH")-float(x.get("cost") or 0)-float(x.get("validation_metrics",{}).get("psi") or 0) for x in test_rows])
            phase5_ranking=ranking_metrics(actual,gain_actual,phase5_score)
            top_k_hit_rate=surrogate_ranking["positive_hit_rate_at_5"]
            artifact = self.root / f"{surrogate_id}.pkl"
            known = {"feature_types": sorted({str((x.get("feature_types") or ["UNKNOWN"])[0]) for x in train_rows}), "semantic_domains": sorted({str((x.get("semantic_domains") or ["UNKNOWN"])[0]) for x in train_rows}), "model_types": sorted({str(x.get("model_type") or "UNKNOWN") for x in train_rows})}
            ref=np.asarray(x_train_array[:500],dtype=float);scale=np.std(ref,axis=0);scale[scale<1e-9]=1;normalized=(ref-ref.mean(axis=0))/scale
            nearest=np.min(np.sqrt(((normalized[:,None,:]-normalized[None,:,:])**2).sum(axis=2))+np.eye(len(normalized))*1e9,axis=1) if len(normalized)>1 else np.asarray([0.0]);distance_threshold=float(np.quantile(nearest,.95)+1e-6)
            artifact.write_bytes(pickle.dumps({"vectorizer": vectorizer, "classifier": classifier, "calibrated_classifier": calibrated, "regressors": regressors, "meta_features": META_FEATURES, "columns": columns, "known": known, "reference": ref, "reference_mean":ref.mean(axis=0), "reference_scale":scale, "distance_threshold":distance_threshold}))
            signal_gate=(classification.get("auc") or 0)>=.60 or regression["delta_oot_auc"]["spearman"]>=.20
            ranking_gate=surrogate_ranking["ndcg_at_10"]>random_ranking["ndcg_at_10"] and surrogate_ranking["ndcg_at_10"]>=phase5_ranking["ndcg_at_10"]
            if len(usable)<self.active_threshold: status="EXPERIMENTAL";why=f"training_count {len(usable)} < {self.active_threshold}"
            elif signal_gate and ranking_gate: status="ACTIVE";why="ACTIVE_GATE_PASSED"
            elif not signal_gate: status="DISABLED_LOW_SIGNAL";why="TIME_SPLIT_SIGNAL_BELOW_GATE"
            else: status="EXPERIMENTAL";why="RANKING_NOT_BETTER_THAN_BASELINES"
            record = SurrogateModelRecord(surrogate_id=surrogate_id, version="1.1", algorithm="LightGBM" if HAS_LIGHTGBM else "GradientBoosting", training_window=self._window(usable), training_count=len(usable), features=META_FEATURES, targets=["delta_oot_auc", "delta_oot_ks", "delta_lift10", "positive"], metrics={"classification": classification, "calibration":calibration,"regression": regression, "ranking":{"surrogate":surrogate_ranking,"random":random_ranking,"phase5":phase5_ranking},"top_k_hit_rate": top_k_hit_rate, "split": "TIME_ORDERED_80_20", "train_count": len(train_rows), "test_count": len(test_rows),"active_gate":{"signal":signal_gate,"ranking":ranking_gate,"passed":status=="ACTIVE","why":why}}, status=status, artifact=str(artifact), training_dataset_hash=dataset_hash).model_dump()
            self.registry.add(record); return record
        except Exception as exc:
            record = SurrogateModelRecord(surrogate_id=surrogate_id, version="1.0", algorithm="GradientBoosting", training_window=self._window(usable), training_count=len(usable), features=META_FEATURES, targets=["delta_oot_auc", "delta_oot_ks", "delta_lift10", "positive"], status="FAILED", training_dataset_hash=dataset_hash, metrics={"error": str(exc)}).model_dump()
            self.registry.add(record); return record

    def predict(self, candidate: dict, surrogate_id: str | None = None) -> dict:
        records = [x for x in self.registry.all() if x.get("status") in {"EXPERIMENTAL", "ACTIVE"}]
        record = self.registry.get(surrogate_id) if surrogate_id else (records[-1] if records else None)
        if not record or not record.get("artifact"):
            return {"status": "SURROGATE_INSUFFICIENT_DATA", "fallback": True, "uncertainty": "HIGH"}
        artifact = Path(record["artifact"]).resolve()
        allowed_root = self.root.resolve()
        if allowed_root not in artifact.parents or artifact.suffix != ".pkl":
            raise ValueError("INVALID_SURROGATE_ARTIFACT_PATH")
        bundle = pickle.loads(artifact.read_bytes())
        vector = build_meta_features(candidate)
        x_array = bundle["vectorizer"].transform([vector])
        x = pd.DataFrame(x_array, columns=bundle.get("columns") or [f"mf_{i}" for i in range(x_array.shape[1])])
        probability = float(bundle.get("calibrated_classifier",bundle["classifier"]).predict_proba(x)[0, 1])
        gains = {target: float(model.predict(x)[0]) for target, model in bundle["regressors"].items()}
        vector_hash = hashlib.sha256(json.dumps(sanitize_json(vector), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        known = bundle.get("known") or {}
        categorical_ood = vector["feature_type"] not in known.get("feature_types", []) or vector["semantic_domain"] not in known.get("semantic_domains", []) or vector["model_type"] not in known.get("model_types", [])
        reference=np.asarray(bundle.get("reference",[]));normalized=(np.asarray(x_array[0])-np.asarray(bundle.get("reference_mean",0)))/np.asarray(bundle.get("reference_scale",1));distance=float(np.min(np.sqrt((((reference-np.asarray(bundle.get("reference_mean",0)))/np.asarray(bundle.get("reference_scale",1))-normalized)**2).sum(axis=1)))) if len(reference) else 0.0
        distance_ood=distance>float(bundle.get("distance_threshold",1e9));unseen=categorical_ood or distance_ood;margin=abs(probability-.5)
        uncertainty = "HIGH" if unseen or margin<.10 else "LOW" if margin>=.35 and distance<=float(bundle.get("distance_threshold",1e9))*.6 else "MEDIUM"
        result = {"status": record["status"], "surrogate_version": record["version"], "surrogate_id": record["surrogate_id"], "training_dataset_hash": record["training_dataset_hash"], "training_experiment_count": record["training_count"], "positive_probability": probability, "expected_delta_auc": gains["delta_oot_auc"], "expected_delta_ks": gains["delta_oot_ks"], "expected_delta_lift10": gains["delta_lift10"], "uncertainty": uncertainty, "out_of_distribution": unseen,"categorical_ood":categorical_ood,"nearest_experiment_distance":distance,"distance_threshold":float(bundle.get("distance_threshold",0)),"probability_margin":margin, "feature_vector_hash": vector_hash, "fallback": False}
        SurrogatePredictionRegistry(self.root).add({"prediction_id": f"SP_{uuid.uuid4().hex[:12]}", "candidate_id": candidate.get("candidate_id"), **result})
        return result

    @staticmethod
    def _window(rows: list[dict]) -> dict[str, str | None]:
        return {"start": str(rows[0].get("timestamp")) if rows else None, "end": str(rows[-1].get("timestamp")) if rows else None}
