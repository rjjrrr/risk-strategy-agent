from __future__ import annotations


def entry_route(state):
    entry=str(state.get("entry_point") or "RUN_ALL").upper()
    if entry in {"RUN_ALL","FROM_ANALYSIS"}:return "build_context"
    if entry=="FROM_FEATURE":return "cheap_validation" if state.get("feature_ids") else "feature_compile"
    if entry=="FROM_VALIDATION":return "cheap_validation"
    if entry=="FROM_DECISION":return "decision_context"
    if entry=="FROM_EXPERIMENT":return "shadow_predict" if state.get("plan_id") else "decision_context"
    return "end"


def route(state,default="end"):
    if state.get("cancel_requested"):return "end"
    return state.get("next_route") or default
