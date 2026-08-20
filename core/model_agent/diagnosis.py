from __future__ import annotations

import uuid
from typing import Any

from .config import HARD_GATES
from .registry import DiagnosisRegistry


class DiagnosisAgent:
    def __init__(self, registry: DiagnosisRegistry): self.registry=registry

    def diagnose(self, metrics: dict[str, Any], *, feature_validations: list[dict[str, Any]] | None = None, confirmed_leakage: list[str] | None = None, related_experiment: str | None = None) -> list[dict[str, Any]]:
        findings=[]; validations=feature_validations or []; leakage=confirmed_leakage or []
        if leakage: findings.append(self._row("LEAKAGE",{"features":leakage},"CRITICAL","HIGH","isolate from experimental Feature Pool","Governance / Feature Audit",True,True,leakage,related_experiment))
        if metrics.get("train_oot_auc_gap",0)>HARD_GATES["max_auc_gap"]: findings.append(self._row("OVERFITTING",{"auc_gap":metrics.get("train_oot_auc_gap")},"HIGH","HIGH","reduce complexity or feature pool","LAST_STABLE_STATE",True,False,[],related_experiment))
        drift=[x["feature"] for x in validations if x.get("psi",0)>=.25]
        if drift: findings.append(self._row("FEATURE_DRIFT",{"features":drift},"HIGH","HIGH","select stable features","LAST_STABLE_STATE",True,False,drift,related_experiment))
        if metrics.get("oot_auc",0)<.58: findings.append(self._row("LOW_SIGNAL",{"oot_auc":metrics.get("oot_auc")},"MEDIUM","HIGH","return to hypothesis and feature engineering",None,True,False,[],related_experiment))
        for row in findings: self.registry.add(row)
        return findings

    def _row(self,kind,evidence,severity,confidence,action,rollback,auto,human,features,experiment):
        return {"diagnosis_id":f"D_{uuid.uuid4().hex[:10]}","diagnosis_type":kind,"evidence":evidence,"severity":severity,"confidence":confidence,"recommended_action":action,"rollback_target":rollback,"auto_allowed":auto,"requires_human":human,"related_features":features,"related_experiment":experiment}
