from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import experiment_memory_service as service

router = APIRouter()


def guard(fn):
    try: return fn()
    except KeyError as exc: raise HTTPException(404, str(exc)) from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


class SimilarBody(BaseModel):
    dataset_id: str
    feature_type: str | None = None
    semantic_domain: str | None = None
    model_type: str | None = None
    diagnosis_type: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


class TrainBody(BaseModel):
    dataset_id: str
    user_confirmed: bool = False


class PredictBody(BaseModel):
    dataset_id: str
    candidate: dict[str, Any]


class RankBody(BaseModel):
    dataset_id: str
    candidates: list[dict[str, Any]]
    opportunity_index: int = 0


@router.get("/api/experiment-memory/summary")
def memory_summary(dataset_id: str): return guard(lambda: service.summary(dataset_id))


@router.get("/api/experiment-memory/similar")
def memory_similar(dataset_id: str, feature_type: str | None = None, semantic_domain: str | None = None, model_type: str | None = None, diagnosis_type: str | None = None, limit: int = 5):
    return guard(lambda: service.similar(dataset_id, {"feature_type": feature_type, "semantic_domain": semantic_domain, "model_type": model_type, "diagnosis_type": diagnosis_type, "limit": limit}))


@router.get("/api/credits/feature-types")
def feature_types(dataset_id: str): return guard(lambda: service.credits(dataset_id, "feature_types"))


@router.get("/api/credits/semantic-domains")
def semantic_domains(dataset_id: str): return guard(lambda: service.credits(dataset_id, "semantic_domains"))


@router.get("/api/credits/actions")
def actions(dataset_id: str): return guard(lambda: service.credits(dataset_id, "actions"))


@router.get("/api/credits/model-specific")
def model_specific(dataset_id: str): return guard(lambda: service.credits(dataset_id, "model_specific"))


@router.post("/api/surrogate/train")
def train(body: TrainBody): return guard(lambda: service.train(body.dataset_id, body.user_confirmed))


@router.get("/api/surrogate/models")
def models(dataset_id: str): return guard(lambda: service.models(dataset_id))


@router.get("/api/surrogate/models/{surrogate_id}")
def model(surrogate_id: str, dataset_id: str): return guard(lambda: service.model(dataset_id, surrogate_id))


@router.post("/api/surrogate/predict")
def predict(body: PredictBody): return guard(lambda: service.predict(body.dataset_id, body.candidate))


@router.post("/api/decision/rank-candidates")
def rank(body: RankBody): return guard(lambda: service.rank_candidates(body.dataset_id, body.candidates, body.opportunity_index))


@router.get("/api/surrogate/diagnostics")
def diagnostics(dataset_id: str): return guard(lambda: service.diagnostics(dataset_id))
