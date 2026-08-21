from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import feature_validation_service as service

validation_router = APIRouter(prefix="/api/feature-validation", tags=["feature-validation"])
counterfactual_router = APIRouter(prefix="/api/counterfactual", tags=["counterfactual"])
credit_router = APIRouter(prefix="/api", tags=["feature-credit"])


class ValidationBody(BaseModel):
    dataset_id: str
    time_field: str | None = None


class CounterfactualBody(BaseModel):
    dataset_id: str
    model_type: Literal["LR", "LGBM"]
    experiment_type: Literal["FEATURE_ADD", "FEATURE_REMOVE"] = "FEATURE_ADD"
    baseline_features: list[str] | None = None
    time_field: str | None = None
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    user_confirmed: bool = False


def guard(fn):
    try:
        return fn()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@validation_router.post("/{feature_id}/run")
def run_validation(feature_id: str, body: ValidationBody):
    return guard(lambda: service.run_validation(body.dataset_id, feature_id, body.time_field))


@validation_router.get("/{feature_id}")
def get_validation(feature_id: str, dataset_id: str):
    return guard(lambda: service.validation(dataset_id, feature_id))


@counterfactual_router.post("/feature/{feature_id}")
def run_counterfactual(feature_id: str, body: CounterfactualBody):
    return guard(lambda: service.run_counterfactual(
        body.dataset_id, feature_id, body.model_type, experiment_type=body.experiment_type,
        baseline_features=body.baseline_features, time_field=body.time_field, seed=body.seed,
        user_confirmed=body.user_confirmed,
    ))


@counterfactual_router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str, dataset_id: str):
    return guard(lambda: service.experiment(dataset_id, experiment_id))


@credit_router.get("/features/{feature_id}/credit")
def get_feature_credit(feature_id: str, dataset_id: str):
    return guard(lambda: service.feature_credit(dataset_id, feature_id))


@credit_router.get("/hypotheses/{hypothesis_id}/credit")
def get_hypothesis_credit(hypothesis_id: str, dataset_id: str):
    return guard(lambda: service.hypothesis_credit(dataset_id, hypothesis_id))
