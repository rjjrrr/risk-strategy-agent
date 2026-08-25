from __future__ import annotations

import math
import time
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor, RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score, log_loss, mean_absolute_error,
                             mean_squared_error, ndcg_score, precision_score, r2_score, recall_score, roc_auc_score)
from sklearn.model_selection import train_test_split

from .meta_features import FORBIDDEN_FUTURE_FIELDS, META_FEATURES, build_meta_features, targets

try:
    from lightgbm import LGBMClassifier
except ImportError:  # pragma: no cover
    LGBMClassifier = None


def safe_auc(y, p): return float(roc_auc_score(y,p)) if len(set(y))>1 else None


def classification_metrics(y, p) -> dict:
    y=np.asarray(y,dtype=int);p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6);pred=(p>=.5).astype(int)
    return {"auc":safe_auc(y,p),"pr_auc":float(average_precision_score(y,p)) if y.any() else 0.0,"precision":float(precision_score(y,pred,zero_division=0)),"recall":float(recall_score(y,pred,zero_division=0)),"f1":float(f1_score(y,pred,zero_division=0)),"brier_score":float(brier_score_loss(y,p)),"log_loss":float(log_loss(y,p,labels=[0,1])),"ece":expected_calibration_error(y,p),"calibration_curve":calibration_curve(y,p)}


def expected_calibration_error(y,p,bins=10):
    y=np.asarray(y);p=np.asarray(p);total=len(y);value=0.0
    for lo in np.linspace(0,1,bins,endpoint=False):
        mask=(p>=lo)&(p<(lo+1/bins) if lo+1/bins<1 else p<=1)
        if mask.any(): value += mask.mean()*abs(float(y[mask].mean())-float(p[mask].mean()))
    return float(value) if total else 0.0


def calibration_curve(y,p,bins=10):
    output=[];y=np.asarray(y);p=np.asarray(p)
    for lo in np.linspace(0,1,bins,endpoint=False):
        mask=(p>=lo)&(p<(lo+1/bins) if lo+1/bins<1 else p<=1)
        if mask.any(): output.append({"predicted":float(p[mask].mean()),"actual":float(y[mask].mean()),"count":int(mask.sum())})
    return output


def regression_metrics(y,p):
    y=np.asarray(y,dtype=float);p=np.asarray(p,dtype=float)
    pearson=float(np.corrcoef(y,p)[0,1]) if len(y)>1 and np.std(y)>0 and np.std(p)>0 else 0.0
    ranks_y=np.argsort(np.argsort(y));ranks_p=np.argsort(np.argsort(p));spearman=float(np.corrcoef(ranks_y,ranks_p)[0,1]) if len(y)>1 else 0.0
    return {"mae":float(mean_absolute_error(y,p)),"rmse":float(math.sqrt(mean_squared_error(y,p))),"r2":float(r2_score(y,p)),"spearman":0.0 if math.isnan(spearman) else spearman,"pearson":0.0 if math.isnan(pearson) else pearson}


def ranking_metrics(y, gain, score, prefix=""):
    y=np.asarray(y);gain=np.asarray(gain);score=np.asarray(score);result={}
    relevance=np.maximum(gain-gain.min(),0)+y*.01
    for k in (5,10):
        size=min(k,len(y));order=np.argsort(-score)[:size]
        result[f"ndcg_at_{k}"]=float(ndcg_score([relevance],[score],k=size)) if size>1 else 0.0
        result[f"precision_at_{k}"]=float(y[order].mean()) if size else 0.0
        result[f"positive_hit_rate_at_{k}"]=float(y[order].mean()) if size else 0.0
        result[f"mean_actual_gain_at_{k}"]=float(gain[order].mean()) if size else 0.0
    return result


def distribution(rows):
    return {"count":len(rows),"positive_rate":float(np.mean([targets(x)["positive"] for x in rows])) if rows else 0,"model_type":dict(Counter(str(x.get("model_type")) for x in rows)),"feature_type":dict(Counter(str((x.get("feature_types") or ["UNKNOWN"])[0]) for x in rows)),"semantic_domain":dict(Counter(str((x.get("semantic_domains") or ["UNKNOWN"])[0]) for x in rows)),"action_type":dict(Counter(str(x.get("action_type")) for x in rows))}


def distribution_shift(train: dict, test: dict) -> dict:
    details={}
    for field in ("model_type","feature_type","semantic_domain","action_type"):
        keys=set(train[field])|set(test[field]);tn=max(1,train["count"]);vn=max(1,test["count"])
        details[field]=.5*sum(abs(train[field].get(k,0)/tn-test[field].get(k,0)/vn) for k in keys)
    details["positive_rate_gap"]=abs(train["positive_rate"]-test["positive_rate"])
    return {"detected":any(v>.15 for v in details.values()),"reason":"TEMPORAL_DISTRIBUTION_SHIFT" if any(v>.15 for v in details.values()) else "NO_MATERIAL_SHIFT","distances":details}


def target_audit(rows):
    output={}
    for name in ("delta_oot_auc","delta_oot_ks","delta_lift10"):
        values=np.asarray([targets(x)[name] for x in rows],dtype=float)
        output[name]={"mean":float(values.mean()),"std":float(values.std()),**{f"p{int(q*100):02d}":float(np.quantile(values,q)) for q in (.01,.05,.25,.5,.75,.95,.99)},"near_zero_rate":float((np.abs(values)<1e-4).mean())}
    output["probability_positive"]={"positive":sum(targets(x)["positive"] for x in rows),"negative":len(rows)-sum(targets(x)["positive"] for x in rows),"source":"counterfactual_decision == POSITIVE"}
    return output


def audit_dataset(rows):
    split=max(1,int(len(rows)*.8));train,test=rows[:split],rows[split:]
    vectors=[tuple(sorted(build_meta_features(x).items())) for x in rows]
    train_dist,test_dist=distribution(train),distribution(test)
    return {"target_distribution":target_audit(rows),"outcomes":dict(Counter(str(x.get("counterfactual_decision")) for x in rows)),"full_distribution":distribution(rows),"train_distribution":train_dist,"test_distribution":test_dist,"meta_feature_unique_rate":len(set(vectors))/len(vectors) if vectors else 0,"id_leakage":bool({"dataset_id","feature_id","hypothesis_id"}&set(META_FEATURES)),"future_leakage":sorted(FORBIDDEN_FUTURE_FIELDS&set(META_FEATURES)),"temporal_distribution_shift":distribution_shift(train_dist,test_dist)}


def compare_models(rows, random_state=42):
    started=time.perf_counter();rows=sorted(rows,key=lambda x:str(x.get("timestamp")));split=int(len(rows)*.8);train,test=rows[:split],rows[split:]
    vec=DictVectorizer(sparse=False);xtr=vec.fit_transform([build_meta_features(x) for x in train]);xte=vec.transform([build_meta_features(x) for x in test]);cols=[f"m{i}" for i in range(xtr.shape[1])];xtr=pd.DataFrame(xtr,columns=cols);xte=pd.DataFrame(xte,columns=cols)
    ytr=np.asarray([targets(x)["positive"] for x in train]);yte=np.asarray([targets(x)["positive"] for x in test]);gain=np.asarray([targets(x)["delta_oot_auc"] for x in test])
    models={"LogisticRegression":LogisticRegression(max_iter=500),"RandomForest":RandomForestClassifier(n_estimators=100,random_state=random_state,min_samples_leaf=4),"GradientBoosting":GradientBoostingClassifier(random_state=random_state)}
    if LGBMClassifier: models["LightGBM"]=LGBMClassifier(n_estimators=80,random_state=random_state,verbosity=-1)
    results={"RandomPredictor":classification_metrics(yte,np.full(len(yte),.5)),"HistoricalPositiveRate":classification_metrics(yte,np.full(len(yte),float(ytr.mean())))};scores={}
    if any("latent_positive_probability" in x for x in test): results["OracleRule"]=classification_metrics(yte,[float(x.get("latent_positive_probability") or 0) for x in test])
    best_name=None;best_auc=-1
    for name,model in models.items():
        model.fit(xtr,ytr);p=model.predict_proba(xte)[:,1];metrics=classification_metrics(yte,p);results[name]=metrics;scores[name]=p
        if (metrics["auc"] or 0)>best_auc:best_auc=metrics["auc"] or 0;best_name=name
    rng=np.random.default_rng(random_state);phase5=np.asarray([2*(str(x.get("validation_metrics",{}).get("feature_novelty"))=="HIGH")-float(x.get("cost") or 0)-float(x.get("validation_metrics",{}).get("psi") or 0) for x in test]);historical=np.asarray([float(x.get("feature_credit_before") or .5) for x in test])
    ranking={"Random":ranking_metrics(yte,gain,rng.random(len(test))),"Phase5Deterministic":ranking_metrics(yte,gain,phase5),"HistoricalCredit":ranking_metrics(yte,gain,historical)}
    if any("latent_expected_gain" in x for x in test): ranking["Oracle"]=ranking_metrics(yte,gain,[float(x["latent_expected_gain"]) for x in test])
    for name,p in scores.items(): ranking[name]=ranking_metrics(yte,gain,p)
    # Random split is diagnostic only.
    idx=np.arange(len(rows));train_idx,test_idx=train_test_split(idx,test_size=.2,random_state=random_state,stratify=[targets(x)["positive"] for x in rows]);rv=DictVectorizer(sparse=False);rxtr=rv.fit_transform([build_meta_features(rows[i]) for i in train_idx]);rxte=rv.transform([build_meta_features(rows[i]) for i in test_idx]);random_model=LogisticRegression(max_iter=500).fit(rxtr,[targets(rows[i])["positive"] for i in train_idx]);random_auc=safe_auc([targets(rows[i])["positive"] for i in test_idx],random_model.predict_proba(rxte)[:,1])
    return {"models":results,"ranking":ranking,"best_model":best_name,"time_split_auc":best_auc,"random_split_auc":random_auc,"performance_ms":round((time.perf_counter()-started)*1000,3)}


FEATURE_GROUPS={"FeatureMetadata":{"feature_type","feature_count_before","feature_count_added","novelty"},"ValidationMetrics":{"validation_decision","iv","psi","valid_rate","max_correlation","lr_eligible","lgbm_eligible"},"BaselineModelMetrics":{"baseline_auc","baseline_ks","baseline_lift10","baseline_auc_gap"},"HistoricalCredit":{"feature_credit_before","hypothesis_credit_before","historical_domain_success_rate","historical_feature_type_success_rate"},"Diagnosis":{"diagnosis_type"},"SemanticDomain":{"semantic_domain"},"ModelType":{"model_type"}}


def feature_group_ablation(rows):
    split=int(len(rows)*.8);train,test=rows[:split],rows[split:];output={};full_vec=DictVectorizer(sparse=False);full_x=full_vec.fit_transform([build_meta_features(x) for x in train]);full_test=full_vec.transform([build_meta_features(x) for x in test]);full_model=GradientBoostingRegressor(random_state=42).fit(full_x,[targets(x)["delta_oot_auc"] for x in train]);full=regression_metrics([targets(x)["delta_oot_auc"] for x in test],full_model.predict(full_test))["spearman"]
    for group,excluded in FEATURE_GROUPS.items():
        vector=lambda x:{k:v for k,v in build_meta_features(x).items() if k not in excluded};vec=DictVectorizer(sparse=False);xtr=vec.fit_transform([vector(x) for x in train]);xte=vec.transform([vector(x) for x in test]);model=GradientBoostingRegressor(random_state=42).fit(xtr,[targets(x)["delta_oot_auc"] for x in train]);score=regression_metrics([targets(x)["delta_oot_auc"] for x in test],model.predict(xte))["spearman"];output[group]={"without_group_spearman":score,"contribution":full-score}
    return {"full_spearman":full,"groups":output}


def permutation_importance_report(rows):
    split=int(len(rows)*.8);train,test=rows[:split],rows[split:];vec=DictVectorizer(sparse=False);xtr=vec.fit_transform([build_meta_features(x) for x in train]);xte=vec.transform([build_meta_features(x) for x in test]);model=GradientBoostingRegressor(random_state=42).fit(xtr,[targets(x)["delta_oot_auc"] for x in train]);result=permutation_importance(model,xte,[targets(x)["delta_oot_auc"] for x in test],n_repeats=3,random_state=42,scoring="neg_mean_squared_error");names=vec.get_feature_names_out();return [{"feature":str(names[i]),"importance":float(result.importances_mean[i])} for i in np.argsort(-result.importances_mean)[:20]]


def learning_curve(rows, sizes=(30,50,100,200,500,1000)):
    output=[]
    for size in sizes:
        subset=rows[:min(size,len(rows))]
        if len(subset)<30: continue
        compared=compare_models(subset);split=int(len(subset)*.8);train,test=subset[:split],subset[split:];vec=DictVectorizer(sparse=False);xtr=vec.fit_transform([build_meta_features(x) for x in train]);xte=vec.transform([build_meta_features(x) for x in test]);reg=GradientBoostingRegressor(random_state=42).fit(xtr,[targets(x)["delta_oot_auc"] for x in train]);pred=reg.predict(xte);reg_metrics=regression_metrics([targets(x)["delta_oot_auc"] for x in test],pred);rank=ranking_metrics([targets(x)["positive"] for x in test],[targets(x)["delta_oot_auc"] for x in test],pred)
        output.append({"sample_size":len(subset),"auc":compared["time_split_auc"],"spearman":reg_metrics["spearman"],"ndcg_at_10":rank["ndcg_at_10"]})
    return output
